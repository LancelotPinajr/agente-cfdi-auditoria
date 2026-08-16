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
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import Depends, FastAPI, HTTPException, Response, UploadFile, status

from ..auditoria.cotejo import cotejar_lote
from ..bitacora.almacen import Bitacora
from ..bitacora.anclaje import Ancla, ErrorDeAnclaje
from ..cfdi.errores import CFDIInvalido
from ..cfdi.lector import leer_cfdi
from ..fuentes.protocolo import ErrorDeFuente, FuenteDeLibros
from .dependencias import ancla_actual, bitacora_actual, fuente_actual
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
    RespuestaDeIngesta,
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


@app.post("/ingesta", response_model=RespuestaDeIngesta)
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


@app.post("/cesiones", response_model=RespuestaDeCesion)
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


@app.post("/bitacora/anclaje", response_model=RespuestaDeAnclaje)
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
