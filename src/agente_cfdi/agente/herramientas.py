"""Las herramientas que el agente ADK puede usar (brecha #6 del manual).

## Por qué viven aquí y no en `agente/agent.py`

`agente/agent.py` importa ADK, y el CI no lo instala: cualquier regla escrita
allí quedaría sin prueba. Estas son funciones de Python planas —sin un solo
`import` de ADK— y por eso las cubren las pruebas del repo. `agent.py` solo las
pasa en `tools=[...]`; ADK deriva el esquema de los tipos y del docstring.

## Todas son de SOLO LECTURA, y es la decisión que más importa aquí

El agente no puede ingestar, ni ceder, ni cerrar el día. Esas tres escriben en
una bitácora **append-only**: un registro mal escrito no se corrige después,
porque el diseño entero existe para que nada se pueda corregir después.

Un LLM que alucina una llamada a herramienta es un hecho conocido, no un riesgo
hipotético. Si esa llamada pudiera anexar una auditoría, bastaría una para dejar
un veredicto falso, firmado y permanente en la cadena que este producto vende
como confiable. Y si pudiera ceder, alucinar un financiador equivocado
consumiría el folio para siempre: la restricción `UNIQUE` que impide el fraude
impediría también corregir el error.

Escribir se queda en los endpoints deterministas, que validan y no improvisan.
El agente lee, explica y cita — que es donde un modelo aporta.

## Lo que estas herramientas nunca devuelven

**El nombre del financiador de una cesión.** Ya lo decidía `GET /cesiones/{uuid}`
y aquí se sostiene: saber que un folio está tomado basta para frenar una
operación; saber a nombre de quién es información comercial de un tercero. Sin
esta regla repetida aquí, el agente sería el camino fácil para sacarla.
"""

from __future__ import annotations

from ..api.dependencias import abrir_bitacora

__all__ = [
    "estado_de_integridad",
    "consultar_folio",
    "resumen_de_la_bitacora",
    "HERRAMIENTAS",
]


def estado_de_integridad() -> dict:
    """Dice si la bitácora está íntegra y si su evidencia está publicada.

    Úsala cuando pregunten por la integridad, la confiabilidad o el estado
    general del sistema, o si algo fue manipulado.

    Devuelve un color:
    - `rojo`: se detectó manipulación. Incluye la fila exacta donde se rompe.
    - `ambar`: la cadena cuadra, pero su raíz no está publicada en una red
      real, así que solo demuestra consistencia interna.
    - `verde`: cuadra Y está publicada; cualquiera puede comprobarla sin
      pedirnos nada.

    No omitas el matiz del ámbar al responder: la diferencia entre «es
    consistente» y «un tercero puede comprobarlo» es la propuesta de valor
    entera del producto.
    """
    from ..api.app import semaforo

    with abrir_bitacora() as bitacora:
        estado = semaforo(dia=None, bitacora=bitacora)
    return estado.model_dump()


def consultar_folio(uuid: str) -> dict:
    """Consulta un folio fiscal (UUID) en la bitácora.

    Úsala cuando pregunten por una factura concreta: si fue auditada, qué
    veredicto obtuvo, o si ya fue cedida a un financiador.

    Args:
        uuid: El folio fiscal del CFDI, de 36 caracteres.

    Devuelve si el folio está auditado, su veredicto (`respaldado`,
    `sin_respaldo`, `monto_distinto`), el importe del CFDI y el de los libros, y
    si ya fue cedido.

    **No devuelve a nombre de quién está la cesión** — que esté tomada basta
    para frenar una operación; la identidad del otro financiador no es asunto de
    quien pregunta. No especules sobre ella.
    """
    folio = (uuid or "").strip().upper()
    if len(folio) != 36:
        return {
            "encontrado": False,
            "error": (
                f"«{uuid}» no parece un folio fiscal: son 36 caracteres con guiones, "
                f"como 3F2504E0-4F89-41D3-9A0C-0305E82C3301"
            ),
        }

    with abrir_bitacora() as bitacora:
        auditoria = bitacora.auditoria_de(folio)
        cesion = bitacora.cesion_de(folio)

        if auditoria is None:
            return {
                "encontrado": False,
                "uuid": folio,
                "detalle": (
                    "este folio no está en la bitácora: nunca se auditó en este "
                    "despliegue. No significa que la factura sea falsa, solo que "
                    "aquí no consta."
                ),
            }

        return {
            "encontrado": True,
            "uuid": folio,
            "auditado": True,
            "veredicto": auditoria["veredicto"],
            "significado": SIGNIFICADO.get(auditoria["veredicto"], "veredicto desconocido"),
            "total_del_cfdi": auditoria["total"],
            "moneda": auditoria["moneda"],
            "posicion_en_la_cadena": int(auditoria["posicion"]),
            "cedido": cesion is not None,
            "cedido_en": cesion["cedido_en"] if cesion else None,
            # El financiador NO va aquí. Ver el docstring del módulo.
        }


def resumen_de_la_bitacora() -> dict:
    """Da el tamaño y el estado de cierre de la bitácora.

    Úsala cuando pregunten cuántas facturas se han auditado, qué tan grande es
    la cadena, o si el día ya se cerró y ancló.
    """
    from datetime import datetime, timezone

    hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with abrir_bitacora() as bitacora:
        altura = bitacora.altura()
        ancla = bitacora.ancla_del_dia(hoy)
        registros_de_hoy = len(bitacora.hojas_del_dia(hoy))

    return {
        "registros_en_la_cadena": altura,
        "registros_de_hoy": registros_de_hoy,
        "dia": hoy,
        "dia_cerrado": ancla is not None,
        "raiz_del_dia": bytes(ancla["raiz"]).hex() if ancla else None,
        "red_del_ancla": ancla["red"] if ancla else None,
        "detalle": (
            f"la cadena tiene {altura} registros; el {hoy} "
            + (
                f"ya se cerró con {int(ancla['registros'])} registros bajo una raíz"
                if ancla
                else f"aún no se cierra ({registros_de_hoy} registros hasta ahora)"
            )
        ),
    }


SIGNIFICADO = {
    "respaldado": "la contabilidad de la PYME registra un ingreso que coincide con el CFDI",
    "sin_respaldo": "la contabilidad no registra ningún ingreso que respalde este folio",
    "monto_distinto": "los libros registran un importe distinto al del comprobante",
    "no_auditado": "no se pudo consultar la contabilidad al auditar este folio",
}
"""Se manda el significado junto al veredicto en vez de confiar en que el modelo
lo recuerde: son términos del dominio, y una explicación inventada sobre un
veredicto de auditoría es peor que no dar ninguna."""

HERRAMIENTAS = [estado_de_integridad, consultar_folio, resumen_de_la_bitacora]
"""Lo que `agente/agent.py` pasa a `tools=[...]`. Todas de solo lectura."""
