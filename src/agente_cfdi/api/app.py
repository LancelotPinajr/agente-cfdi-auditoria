"""Endpoints de ingesta y cesión (tarea 2.4).

## Un despliegue por PYME

El inquilino sale de la configuración, no de un encabezado de la petición. Ya lo
imponía el diseño previo: `CORD_FISCAL_TOKEN` es «el JWT del agente **para esa
PYME**», así que un despliegue ya está atado a un contribuyente. Aceptar un
`X-Inquilino` de quien llama sería peor que inútil — cualquiera escribiría en la
cadena de cualquiera con cambiar una cabecera.

**Hueco declarado:** estos endpoints no autentican a quien llama. En Cloud Run
quedan detrás de IAM, pero eso protege el perímetro, no distingue a un
financiador de otro. Antes de datos reales hace falta autenticación por
financiador — está anotado en el README, no escondido aquí.

## Qué código de estado significa qué

| Situación | Código | Por qué |
|---|---|---|
| Folio ya cedido a **otro** | `409` | Conflicto real: el recurso ya está tomado |
| Folio ya cedido al **mismo** | `200` | Reintento idempotente, no fraude |
| Libros inalcanzables | `503` | Falla de infraestructura, **no** «sin respaldo» |
| CFDI ilegible | `422` en su renglón | El lote sigue; se reporta cuál falló |

El `503` importa: si una caída de CØRD Fiscal devolviera veredictos
`sin_respaldo`, el financiador leería una falla de red como libros
inconsistentes. Se responde «no pude preguntar», que es la verdad.
"""

from __future__ import annotations

import base64
import io
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import Depends, FastAPI, HTTPException, Response, UploadFile, status

from ..auditoria.cotejo import cotejar_lote
from ..bitacora.almacen import Bitacora
from ..bitacora.anclaje import Ancla, Constancia, ErrorDeAnclaje, enlace_del_explorador
from ..bitacora.cadena import CadenaRota
from ..cfdi.errores import CFDIInvalido
from ..cfdi.lector import leer_cfdi
from ..fuentes.protocolo import ErrorDeFuente, FuenteDeLibros
from ..sintetico.generador import generar_lote
from .ciclo import anotar, semilla_configurada
from .autenticacion import exigir_token_de_escritura
from .dependencias import (
    ancla_actual,
    bitacora_actual,
    fuente_actual,
    inquilino_configurado,
)
from .esquemas import (
    ConstanciaDeAnclaje,
    EstadoDeCesion,
    LecturaRechazada,
    PasoDeLaRuta,
    PeticionDeCesion,
    PruebaDeIntegridad,
    RegistroAuditado,
    RespuestaDeAnclaje,
    RespuestaDeCesion,
    RespuestaDeCierre,
    RespuestaDeIngesta,
    Semaforo,
)

MAXIMO_ARCHIVOS = 500
"""Sin tope, la ingesta es una negación de servicio de una sola petición."""

MAXIMO_BYTES_DEL_LOTE = 64 * 1024 * 1024

DUPLICADO_EN_EL_LOTE = "uuid_duplicado_en_el_lote"
"""No es un motivo del lector: el archivo se leyó bien. Es un rechazo del lote."""

ADVERTENCIAS = {
    "sin_respaldo": (
        "la contabilidad de la PYME no registra ingreso alguno que respalde este "
        "folio; la cesión se registró, pero el respaldo contable no existe"
    ),
    "monto_distinto": (
        "los libros de la PYME registran un importe distinto al del CFDI; "
        "la cesión se registró sobre un folio con discrepancia contable"
    ),
    "no_auditado": (
        "no se pudo consultar la contabilidad de la PYME al auditar este folio; "
        "la cesión se registró sin verificación de respaldo"
    ),
}
"""Se **cede igual**, pero se dice.

Bloquear la cesión de un folio con hallazgos sería tomar por el financiador una
decisión comercial que es suya: hay quien financia cartera con descuento
sabiendo el riesgo. Lo que no es aceptable es que no se entere.
"""

app = FastAPI(
    title="Agente de Aseguramiento y Cesión de CFDI",
    description="Audita CFDI contra los libros de la PYME y detecta doble cesión.",
    version="0.2.0",
)


@app.get("/salud")
def salud(bitacora: Bitacora = Depends(bitacora_actual)) -> dict:
    """Sonda de vida. Reporta la altura de la cadena, no si verifica.

    Verificar la cadena entera en cada sonda de Cloud Run sería recorrer toda la
    bitácora cada pocos segundos. La verificación es un endpoint aparte, que se
    llama cuando alguien quiere la respuesta y está dispuesto a esperarla.
    """
    return {
        "estado": "vivo",
        "inquilino": bitacora.inquilino,
        "altura": bitacora.altura(),
        "punta": bitacora.punta().hex(),
    }


@app.post(
    "/ingesta",
    response_model=RespuestaDeIngesta,
    dependencies=[Depends(exigir_token_de_escritura)],
)
async def ingesta(
    archivos: list[UploadFile],
    bitacora: Bitacora = Depends(bitacora_actual),
    fuente: FuenteDeLibros = Depends(fuente_actual),
) -> RespuestaDeIngesta:
    """Recibe un lote de CFDI, los audita contra los libros y los encadena.

    **Un CFDI ilegible no tumba el lote.** Se reporta en `fallas` con su nombre
    de archivo y motivo, y los demás se procesan: si un archivo corrupto abortara
    la ingesta, una PYME con 200 comprobantes tendría que adivinar cuál quitar.

    Los libros se piden **una sola vez** para todo el lote — ver
    `auditoria.cotejo.cotejar_lote`.
    """
    if not archivos:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "el lote no trae archivos")
    if len(archivos) > MAXIMO_ARCHIVOS:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"el lote trae {len(archivos)} archivos; el máximo es {MAXIMO_ARCHIVOS}",
        )

    comprobantes = []
    fallas: list[LecturaRechazada] = []
    ya_en_el_lote: dict[str, str] = {}
    bytes_leidos = 0

    for archivo in archivos:
        crudo = await archivo.read()
        bytes_leidos += len(crudo)
        if bytes_leidos > MAXIMO_BYTES_DEL_LOTE:
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE,
                f"el lote supera {MAXIMO_BYTES_DEL_LOTE} bytes",
            )
        try:
            leido = leer_cfdi(crudo)
        except CFDIInvalido as invalido:
            fallas.append(
                LecturaRechazada(
                    archivo=archivo.filename or "(sin nombre)",
                    motivo=invalido.motivo.value,
                    detalle=invalido.detalle,
                    uuid=invalido.uuid,
                )
            )
            continue

        # El mismo folio dos veces en un solo lote no es un caso legítimo: o es
        # un error del que armó el envío, o es el intento de meter la misma
        # cuenta por cobrar dos veces. Auditar ambos escribiría dos veredictos
        # para un folio que existe una sola vez, y dejaría el escenario de
        # fraude entrando en silencio.
        anterior = ya_en_el_lote.get(leido.uuid)
        if anterior is not None:
            fallas.append(
                LecturaRechazada(
                    archivo=archivo.filename or "(sin nombre)",
                    motivo=DUPLICADO_EN_EL_LOTE,
                    detalle=f"el folio ya venía en este lote, en {anterior!r}",
                    uuid=leido.uuid,
                )
            )
            continue

        ya_en_el_lote[leido.uuid] = archivo.filename or "(sin nombre)"
        comprobantes.append(leido)

    try:
        movimientos = fuente.movimientos()
    except ErrorDeFuente as falla:
        # No es «sin respaldo»: es no haber podido preguntar. Devolver veredictos
        # aquí convertiría una caída de red en un hallazgo de auditoría.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"no se pudieron obtener los libros de la PYME: {falla}",
        ) from falla

    cotejos = cotejar_lote(tuple(comprobantes), movimientos)
    registros: list[RegistroAuditado] = []

    for comprobante, cotejo in zip(comprobantes, cotejos):
        anexado = bitacora.anexar_auditoria(
            uuid=comprobante.uuid,
            rfc_emisor=comprobante.rfc_emisor,
            rfc_receptor=comprobante.rfc_receptor,
            total=comprobante.total,
            moneda=comprobante.moneda,
            fecha_emision=comprobante.fecha_emision_declarada,
            veredicto=cotejo.veredicto.value,
            fuente_de_libros=fuente.descripcion,
            monto_en_libros=cotejo.monto_en_libros,
        )
        registros.append(
            RegistroAuditado(
                uuid=comprobante.uuid,
                posicion=anexado.posicion,
                veredicto=cotejo.veredicto.value,
                hash=anexado.hash_registro.hex(),
                monto_del_cfdi=str(cotejo.monto_del_cfdi),
                monto_en_libros=(
                    str(cotejo.monto_en_libros) if cotejo.monto_en_libros is not None else None
                ),
            )
        )

    return RespuestaDeIngesta(
        auditados=len(registros),
        rechazados=len(fallas),
        hallazgos=sum(1 for cotejo in cotejos if cotejo.es_hallazgo),
        fuente_de_libros=fuente.descripcion,
        registros=registros,
        fallas=fallas,
        punta=bitacora.punta().hex(),
        altura=bitacora.altura(),
    )


@app.post(
    "/cesiones",
    response_model=RespuestaDeCesion,
    dependencies=[Depends(exigir_token_de_escritura)],
)
def ceder(
    peticion: PeticionDeCesion,
    respuesta: Response,
    bitacora: Bitacora = Depends(bitacora_actual),
) -> RespuestaDeCesion:
    """Intenta ceder una factura a un financiador.

    Antes de ceder se exige que el folio **haya sido auditado** y que el importe
    coincida con el del comprobante. Ceder algo que nunca se auditó no significa
    nada: el expediente que recibe el financiador estaría vacío. Y aceptar un
    importe distinto al del CFDI dejaría en la cadena una cesión por un monto que
    ninguna factura respalda.
    """
    auditoria = bitacora.auditoria_de(peticion.uuid)
    if auditoria is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"el folio {peticion.uuid} no ha sido auditado; ingrésalo antes de cederlo",
        )
    if Decimal(auditoria["total"]) != peticion.total:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"el importe cedido ({peticion.total}) no coincide con el del CFDI "
            f"auditado ({auditoria['total']})",
        )
    if auditoria["moneda"] != peticion.moneda:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"la moneda cedida ({peticion.moneda}) no coincide con la del CFDI "
            f"({auditoria['moneda']})",
        )

    resultado = bitacora.registrar_cesion(
        uuid=peticion.uuid,
        financiador=peticion.financiador,
        rfc_emisor=bitacora.inquilino,
        total=peticion.total,
        moneda=peticion.moneda,
    )

    if resultado.repetida:
        respuesta.status_code = status.HTTP_200_OK
    elif resultado.aceptada:
        respuesta.status_code = status.HTTP_201_CREATED
    else:
        respuesta.status_code = status.HTTP_409_CONFLICT

    veredicto = auditoria["veredicto"]
    return RespuestaDeCesion(
        aceptada=resultado.aceptada,
        motivo=resultado.motivo,
        posicion=resultado.posicion,
        uuid=peticion.uuid,
        repetida=resultado.repetida,
        posicion_de_la_cesion_previa=resultado.posicion_de_la_cesion_previa,
        veredicto=veredicto,
        advertencia=ADVERTENCIAS.get(veredicto),
    )


@app.get("/cesiones/{uuid}", response_model=EstadoDeCesion)
def estado_de_cesion(
    uuid: str, bitacora: Bitacora = Depends(bitacora_actual)
) -> EstadoDeCesion:
    """¿Este folio ya está tomado?

    **No dice a nombre de quién.** Saber que está cedido basta para que un
    financiador frene la operación; la identidad del que lo tiene es información
    comercial de un tercero, y este endpoint no la reparte.
    """
    folio = uuid.strip().upper()
    cesion = bitacora.cesion_de(folio)
    auditoria = bitacora.auditoria_de(folio)

    return EstadoDeCesion(
        uuid=folio,
        cedida=cesion is not None,
        posicion=int(cesion["posicion"]) if cesion else None,
        cedido_en=cesion["cedido_en"] if cesion else None,
        auditada=auditoria is not None,
        veredicto=auditoria["veredicto"] if auditoria else None,
    )


@app.get("/bitacora/verificacion")
def verificacion(bitacora: Bitacora = Depends(bitacora_actual)) -> dict:
    """Recorre la cadena entera y reporta el resultado.

    `recalculados` y `altura` se devuelven por separado a propósito: cuando un
    registro se suprimió por retención, su eslabón sigue enlazando pero ya no se
    puede recalcular. «Verifiqué 200» y «verifiqué 3 y confié en 197» no son lo
    mismo, y quien lea esto tiene que poder distinguirlos.
    """
    from ..bitacora.cadena import CadenaRota

    altura = bitacora.altura()
    try:
        recalculados = bitacora.verificar()
    except CadenaRota as rota:
        return {
            "integra": False,
            "altura": altura,
            "posicion_del_problema": rota.posicion,
            "detalle": rota.detalle,
        }
    return {
        "integra": True,
        "altura": altura,
        "recalculados": recalculados,
        "suprimidos_por_retencion": altura - recalculados,
        "punta": bitacora.punta().hex(),
    }


@app.post(
    "/bitacora/anclaje",
    response_model=RespuestaDeAnclaje,
    dependencies=[Depends(exigir_token_de_escritura)],
)
def anclar(
    dia: str | None = None,
    bitacora: Bitacora = Depends(bitacora_actual),
    ancla: Ancla = Depends(ancla_actual),
) -> RespuestaDeAnclaje:
    """Publica la raíz del día (tarea 2.7). Lo dispara el job diario.

    **Anclar dos veces el mismo día devuelve la constancia original**, no una
    nueva. Un job que se reintenta no debe producir dos raíces «oficiales»: un
    tercero no sabría cuál creer, y la segunda además sería distinta si
    entretanto entraron registros.
    """
    objetivo = dia or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        constancia = bitacora.anclar_dia(objetivo, ancla)
    except ValueError as vacio:
        # Un día sin registros no tiene raíz. No es un error del servidor: no
        # hay nada que publicar.
        raise HTTPException(status.HTTP_409_CONFLICT, f"{objetivo}: {vacio}") from vacio
    except ErrorDeAnclaje as falla:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"no se pudo anclar {objetivo}: {falla}"
        ) from falla

    fila = bitacora.ancla_del_dia(objetivo)
    return RespuestaDeAnclaje(
        dia=objetivo,
        raiz=bytes(fila["raiz"]).hex(),
        registros=int(fila["registros"]),
        red=constancia.red,
        referencia=constancia.referencia,
        anclado_en=fila["anclado_en"],
        verificable_por_terceros=constancia.verificable_por_terceros,
    )


@app.get("/auditoria/prueba/{uuid}", response_model=PruebaDeIntegridad)
def prueba_de_integridad(
    uuid: str, bitacora: Bitacora = Depends(bitacora_actual)
) -> PruebaDeIntegridad:
    """La prueba de que un folio está en la bitácora, verificable **sin nosotros**.

    Devuelve el registro del folio, el camino de hermanos hasta la raíz del día y
    el ancla. Con eso un financiador recalcula la raíz por su cuenta y la compara
    contra la publicada — ver `tools/verificar_prueba.py`, que lo hace sin
    importar una sola línea de este proyecto.

    **Lo que no devuelve** son los registros de las demás operaciones de la PYME.
    Los hermanos del camino son hashes; de un hash no sale el RFC ni el monto de
    nadie. Para 40 registros del día, el camino son 6 hashes.
    """
    folio = uuid.strip().upper()
    try:
        prueba = bitacora.prueba_de(folio)
    except ValueError as suprimido:
        # El registro caducó por retención: el eslabón sigue en la cadena pero
        # el canónico ya no está. Entregar una prueba que el receptor no puede
        # verificar sería peor que no entregar ninguna.
        raise HTTPException(status.HTTP_410_GONE, str(suprimido)) from suprimido

    if prueba is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"el folio {folio} no está en la bitácora"
        )

    if prueba.ancla is None:
        advertencia = (
            "el día de este registro todavía no se ancla, así que esta prueba solo "
            "demuestra consistencia interna de nuestra bitácora — que es justo lo que "
            "un tercero no tiene por qué creernos"
        )
    elif not prueba.verificable_por_terceros:
        advertencia = (
            f"el ancla es SIMULADA ({prueba.ancla.red}): no está publicada en ninguna "
            f"red y no se puede comprobar fuera de este sistema"
        )
    else:
        advertencia = None

    return PruebaDeIntegridad(
        uuid=prueba.uuid,
        posicion=prueba.posicion,
        dia=prueba.dia,
        canonico=base64.b64encode(prueba.canonico).decode("ascii"),
        hash_anterior=prueba.hash_anterior.hex(),
        hoja=prueba.hoja.hex(),
        ruta=[
            PasoDeLaRuta(hermano=p.hermano.hex(), hermano_a_la_derecha=p.hermano_a_la_derecha)
            for p in prueba.ruta
        ],
        raiz=prueba.raiz.hex(),
        registros_del_dia=prueba.registros_del_dia,
        ancla=(
            ConstanciaDeAnclaje(
                red=prueba.ancla.red,
                referencia=prueba.ancla.referencia,
                anclado_en=prueba.ancla.anclado_en.strftime("%Y-%m-%dT%H:%M:%SZ"),
                verificable_por_terceros=prueba.ancla.verificable_por_terceros,
            )
            if prueba.ancla
            else None
        ),
        verificable_por_terceros=prueba.verificable_por_terceros,
        advertencia=advertencia,
    )


@app.post(
    "/ciclo-diario",
    dependencies=[Depends(exigir_token_de_escritura)],
)
async def ciclo_diario(
    cantidad: int = 40,
    bitacora: Bitacora = Depends(bitacora_actual),
    fuente: FuenteDeLibros = Depends(fuente_actual),
) -> dict:
    """Entrega el lote del día y lo lleva hasta el expediente (tarea 2.14).

    El criterio de 2.14 pide el ciclo entero *sin intervención manual en ningún
    paso*. El anclaje ya era automático desde 2.9, pero **el lote lo subía una
    persona**: un ciclo cuyo primer paso necesita a alguien con `curl` es un
    cierre automático de un trabajo manual, no un sistema autónomo.

    Este endpoint hace lo que haría la PYME —entregar las facturas del día— y lo
    dispara un segundo job unas horas antes del cierre.

    **El lote es sintético y la respuesta lo dice.** No se inventan facturas para
    que parezcan reales; salen del generador, con los RFC que el SAT no puede
    haber asignado. Lo que el ciclo demuestra no es que existan facturas, sino
    que el sistema las audita, las encadena, detecta el duplicado y publica la
    raíz sin que nadie intervenga. Esa parte no es simulada.

    **Correr dos veces el mismo día no ensucia nada, pero no hace lo obvio.**
    El generador es determinista, así que la segunda corrida trae los mismos
    folios. La ingesta los reaudita —legítimo: la cadena guarda todas las
    auditorías y el índice apunta a la última—. Y la cesión a Banco Norte vuelve
    a salir **aceptada**, que sorprende hasta que se recuerda por qué: ceder al
    mismo financiador dos veces es un reintento de red, no un fraude, y el
    sistema lo trata como idempotente. La que se rechaza, en la primera corrida
    y en todas, es la de Factor Sur: otro financiador sobre un folio ya tomado.
    """
    lote = generar_lote(
        cantidad=cantidad,
        semilla=semilla_configurada(),
        con_cesion_duplicada=True,
    )
    anotar(
        "ciclo.inicio",
        comprobantes=len(lote.comprobantes),
        semilla=lote.semilla,
        origen_del_lote="sintetico",
    )

    # Se reconstruyen `UploadFile` en vez de duplicar la lógica de `/ingesta`:
    # el ciclo tiene que recorrer exactamente el mismo camino que un lote subido
    # a mano, o dejaría de probar lo que dice probar.
    archivos = [
        UploadFile(
            file=io.BytesIO(comprobante.a_xml().encode("utf-8")),
            filename=f"{comprobante.uuid}.xml",
        )
        for comprobante in lote.comprobantes
    ]
    auditado = await ingesta(archivos, bitacora=bitacora, fuente=fuente)
    anotar(
        "ciclo.auditoria",
        auditados=auditado.auditados,
        rechazados=len(auditado.fallas),
        hallazgos=auditado.hallazgos,
        altura=auditado.altura,
    )

    # --- Cesión y detección del duplicado --------------------------------- #
    #
    # Se cede un folio respaldado y acto seguido se intenta cederlo otra vez a
    # OTRO financiador. Es el fraude que da sentido al producto, y el ciclo lo
    # ejecuta cada día para que el rechazo quede registrado, no descrito.
    respaldados = [r for r in auditado.registros if r.veredicto == "respaldado"]
    cesion: dict[str, object] = {"intentada": False}

    if respaldados:
        elegido = respaldados[0]
        primera = bitacora.registrar_cesion(
            uuid=elegido.uuid,
            financiador="Banco Norte",
            rfc_emisor=inquilino_configurado(),
            total=Decimal(str(elegido.monto_del_cfdi)),
        )
        segunda = bitacora.registrar_cesion(
            uuid=elegido.uuid,
            financiador="Factor Sur",
            rfc_emisor=inquilino_configurado(),
            total=Decimal(str(elegido.monto_del_cfdi)),
        )
        cesion = {
            "intentada": True,
            "uuid": elegido.uuid,
            "primera_aceptada": primera.aceptada,
            "segunda_aceptada": segunda.aceptada,
        }
        anotar("ciclo.cesion", **cesion)

        if segunda.aceptada:
            # Si esto pasa, el producto no sirve: el mismo folio se vendió dos
            # veces. Se grita en el log aunque la petición termine bien.
            anotar(
                "ciclo.ALERTA",
                detalle="la segunda cesión fue aceptada; la doble cesión NO se detectó",
                uuid=elegido.uuid,
            )

    resumen = {
        "estado": "completado",
        "origen_del_lote": "sintetico",
        "comprobantes": len(lote.comprobantes),
        "auditados": auditado.auditados,
        "hallazgos": auditado.hallazgos,
        "altura": auditado.altura,
        "cesion": cesion,
        "detalle": (
            "lote entregado, auditado y encadenado. El anclaje lo hace el cierre "
            "diario; este paso solo deja la cadena lista."
        ),
    }
    anotar("ciclo.fin", **{k: v for k, v in resumen.items() if k != "detalle"})
    return resumen


@app.post(
    "/cierre-diario",
    response_model=RespuestaDeCierre,
    dependencies=[Depends(exigir_token_de_escritura)],
)
def cierre_diario(
    dia: str | None = None,
    respuesta: Response = None,  # type: ignore[assignment]
    bitacora: Bitacora = Depends(bitacora_actual),
    ancla: Ancla = Depends(ancla_actual),
) -> RespuestaDeCierre:
    """Cierra el día: verifica la cadena, arma el árbol y ancla la raíz (tarea 2.9).

    Lo dispara Cloud Scheduler. Eso cambia tres cosas frente al endpoint manual
    de `/bitacora/anclaje`:

    **Un día sin movimientos NO es un error.** El job corre todos los días, haya
    o no habido facturas. Si un domingo tranquilo devolviera `409`, el scheduler
    lo marcaría como fallo, reintentaría, y el tablero mostraría rojo por algo
    que salió bien. Se responde `200` con `estado: sin_movimientos`.

    **La cadena se verifica ANTES de anclar.** Publicar la raíz de una cadena
    manipulada sería peor que no publicar nada: dejaría constancia permanente de
    unos datos corruptos y le daría al financiador una garantía falsa. Si la
    cadena está rota no se ancla, y el job falla ruidosamente — un reintento no
    lo va a arreglar, pero nadie debería enterarse por casualidad.

    **Anclar dos veces el mismo día es inocuo.** Un reintento del scheduler
    devuelve la constancia original en vez de una segunda raíz «oficial».
    """
    objetivo = dia or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    altura = bitacora.altura()

    try:
        verificados = bitacora.verificar()
    except CadenaRota as rota:
        # No se ancla. Y se responde 500 a propósito: para el scheduler esto
        # tiene que verse rojo, no como un cierre más.
        respuesta.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        anotar(
            "cierre.cadena_rota",
            dia=objetivo,
            altura=altura,
            posicion=rota.posicion,
            detalle=rota.detalle,
        )
        return RespuestaDeCierre(
            estado="cadena_rota",
            dia=objetivo,
            registros_del_dia=0,
            altura=altura,
            verificados=0,
            detalle=(
                f"la cadena se rompe en la posición {rota.posicion}: {rota.detalle}. "
                f"No se ancló: publicar la raíz de una cadena manipulada dejaría "
                f"constancia permanente de datos corruptos."
            ),
        )

    hojas = bitacora.hojas_del_dia(objetivo)
    if not hojas:
        anotar("cierre.sin_movimientos", dia=objetivo, altura=altura)
        return RespuestaDeCierre(
            estado="sin_movimientos",
            dia=objetivo,
            registros_del_dia=0,
            altura=altura,
            verificados=verificados,
            detalle=f"{objetivo} no tuvo registros; no hay raíz que anclar",
        )

    ya_estaba = bitacora.ancla_del_dia(objetivo) is not None
    try:
        constancia = bitacora.anclar_dia(objetivo, ancla)
    except ErrorDeAnclaje as falla:
        anotar(
            "cierre.anclaje_fallido",
            dia=objetivo,
            registros_del_dia=len(hojas),
            motivo=str(falla),
        )
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"no se pudo anclar {objetivo}: {falla}",
        ) from falla

    fila = bitacora.ancla_del_dia(objetivo)

    # El registro del anclaje es la unica huella que sobrevive al reciclado de
    # la instancia. La bitacora vive en /tmp: la constancia del 21-ago se perdio
    # con una revision nueva y de aquel cierre solo quedo la linea de acceso de
    # uvicorn, un 200 que no dice que anclo. Lo que no queda en el log no ocurrio,
    # para efectos de demostrarlo.
    anotar(
        "cierre.anclado",
        dia=objetivo,
        ya_estaba=ya_estaba,
        registros_del_dia=int(fila["registros"]),
        altura=altura,
        verificados=verificados,
        raiz=bytes(fila["raiz"]).hex(),
        red=constancia.red,
        referencia=constancia.referencia,
        verificable_por_terceros=constancia.verificable_por_terceros,
        explorador=enlace_del_explorador(constancia),
    )

    return RespuestaDeCierre(
        estado="ya_estaba_anclado" if ya_estaba else "anclado",
        dia=objetivo,
        registros_del_dia=int(fila["registros"]),
        altura=altura,
        verificados=verificados,
        raiz=bytes(fila["raiz"]).hex(),
        ancla=ConstanciaDeAnclaje(
            red=constancia.red,
            referencia=constancia.referencia,
            anclado_en=fila["anclado_en"],
            verificable_por_terceros=constancia.verificable_por_terceros,
        ),
        detalle=(
            f"{len(hojas)} registros del día bajo una raíz; cadena verificada "
            f"en sus {verificados} eslabones recalculables"
            + ("" if constancia.verificable_por_terceros else " · ANCLA SIMULADA")
        ),
    )


@app.get("/semaforo", response_model=Semaforo)
def semaforo(
    dia: str | None = None, bitacora: Bitacora = Depends(bitacora_actual)
) -> Semaforo:
    """El estado de integridad de un vistazo (tarea 3.11).

    Recorre la cadena entera y reporta un color. Es caro a propósito: quien mira
    el semáforo quiere la respuesta de verdad, no una caché. La sonda barata para
    Cloud Run es `/salud`, que no verifica nada.
    """
    objetivo = dia or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    altura = bitacora.altura()

    # Tarea 3.16 — antes de verificar nada, distinguir «vacía» de «íntegra».
    #
    # `verificar()` sobre una cadena vacía devuelve 0 y no levanta: no hay
    # eslabón que pueda no cuadrar. Sin este corte, el flujo seguía hasta el
    # ámbar «ÍNTEGRA, SIN PUBLICAR» y afirmaba que los eslabones recalculables
    # cuadraban. Cuadraban cero, que es cierto y no significa nada.
    #
    # No es un caso de laboratorio: la bitácora vive en /tmp y se pierde al
    # reciclar la instancia. El día que eso pase, el semáforo tiene que decir
    # que no hay cadena, no que la cadena está bien.
    if altura == 0:
        return Semaforo(
            color="gris",
            titulo="SIN CADENA QUE VERIFICAR",
            detalle=(
                "la bitácora está vacía: no hay ningún eslabón que recalcular. "
                "Una cadena de altura cero verifica trivialmente, así que esto "
                "NO es una afirmación de integridad — es la ausencia de datos "
                "sobre los que afirmar nada. Si antes hubo registros, se "
                "perdieron con la instancia"
            ),
            altura=0,
            verificados=0,
            dia=objetivo,
        )

    try:
        verificados = bitacora.verificar()
    except CadenaRota as rota:
        return Semaforo(
            color="rojo",
            titulo="MANIPULACIÓN DETECTADA",
            detalle=(
                f"la cadena se rompe en la posición {rota.posicion}: {rota.detalle}"
            ),
            altura=altura,
            verificados=0,
            posicion_del_problema=rota.posicion,
            dia=objetivo,
        )

    fila = bitacora.ancla_del_dia(objetivo)
    if fila is None:
        return Semaforo(
            color="ambar",
            titulo="ÍNTEGRA, SIN PUBLICAR",
            detalle=(
                f"los {verificados} eslabones recalculables cuadran, pero el {objetivo} "
                f"todavía no se ancla: por ahora esto solo demuestra que nuestra "
                f"bitácora es consistente consigo misma"
            ),
            altura=altura,
            verificados=verificados,
            dia=objetivo,
        )

    constancia = Constancia(
        red=fila["red"],
        referencia=fila["referencia"],
        anclado_en=datetime.fromisoformat(fila["anclado_en"].replace("Z", "+00:00")),
    )
    enlace = enlace_del_explorador(constancia)
    resumen = ConstanciaDeAnclaje(
        red=constancia.red,
        referencia=constancia.referencia,
        anclado_en=fila["anclado_en"],
        verificable_por_terceros=constancia.verificable_por_terceros,
    )

    if not constancia.verificable_por_terceros:
        return Semaforo(
            color="ambar",
            titulo="ÍNTEGRA, ANCLA SIMULADA",
            detalle=(
                f"los {verificados} eslabones recalculables cuadran y la raíz del "
                f"{objetivo} está sellada, pero en un ancla SIMULADA "
                f"({constancia.red}): no hay nada publicado que un tercero pueda "
                f"consultar sin nosotros"
            ),
            altura=altura,
            verificados=verificados,
            dia=objetivo,
            ancla=resumen,
            enlace_al_explorador=enlace,
        )

    return Semaforo(
        color="verde",
        titulo="CADENA ÍNTEGRA Y PUBLICADA",
        detalle=(
            f"los {verificados} eslabones recalculables cuadran y la raíz del "
            f"{objetivo} está publicada en {constancia.red}; cualquiera puede "
            f"comprobarla sin pedirnos nada"
        ),
        altura=altura,
        verificados=verificados,
        dia=objetivo,
        ancla=resumen,
        enlace_al_explorador=enlace,
    )
