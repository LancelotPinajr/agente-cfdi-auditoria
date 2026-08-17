"""Qué se escribe en la bitácora, y con qué forma canónica.

Cada clase de evento declara su esquema `CORD-CANON-2`. El esquema es estricto:
un campo no declarado hace fallar la canonicalización, porque **un dato que
entra sin quedar bajo el hash es un dato que después se puede negar**.

## La fecha del CFDI no es un instante

`fecha_emision` viaja como `CADENA` en su forma declarada `AAAA-MM-DDThh:mm:ss`,
no como `INSTANTE`. Un CFDI declara un reloj de pared local sin zona; ponerle
UTC sería inventar información. Los campos `INSTANTE` se reservan para momentos
que el sistema sí observa —cuándo escribió, cuándo ancló—, donde el reloj es
nuestro. Ver [ADR 0003](../../../docs/adr/0003-lectura-de-cfdi.md) §4.
"""

from __future__ import annotations

from enum import Enum

from ..dominio.canonico import Campo, Esquema, Tipo


class Evento(Enum):
    """Las cosas que le pasan a un CFDI y que quedan registradas."""

    CFDI_AUDITADO = "cfdi_auditado"
    """Se leyó el comprobante y se contrastó contra los libros de la PYME."""

    CESION_REGISTRADA = "cesion_registrada"
    """La factura se cedió a un financiador. Es el evento que la vuelve tomada."""

    CESION_RECHAZADA = "cesion_rechazada"
    """Se intentó ceder algo ya cedido. **Se escribe igual.**

    Un intento rechazado es justo lo que un investigador querrá ver después, y
    una bitácora que solo guarda lo que salió bien no sirve para investigar
    nada.
    """


class Veredicto(Enum):
    """El resultado de contrastar un CFDI contra la contabilidad."""

    RESPALDADO = "respaldado"
    SIN_RESPALDO = "sin_respaldo"
    MONTO_DISTINTO = "monto_distinto"
    NO_AUDITADO = "no_auditado"
    """No se pudo preguntar a la fuente de libros.

    Se distingue de `SIN_RESPALDO` a propósito: no encontrar respaldo es un
    hallazgo de auditoría, no haber podido preguntar es una falla de
    infraestructura. Confundirlos reportaría una caída de red al financiador
    como libros inconsistentes.
    """


_COMUNES = (
    Campo("evento", Tipo.CADENA),
    Campo("inquilino", Tipo.CADENA),
    Campo("escrito_en", Tipo.INSTANTE),
)

ESQUEMA_CFDI_AUDITADO = Esquema(
    nombre="cfdi_auditado",
    campos=_COMUNES
    + (
        Campo("uuid", Tipo.CADENA),
        Campo("rfc_emisor", Tipo.CADENA),
        Campo("rfc_receptor", Tipo.CADENA),
        Campo("total", Tipo.DECIMAL, escala=2),
        Campo("moneda", Tipo.CADENA),
        Campo("fecha_emision", Tipo.CADENA),
        Campo("veredicto", Tipo.CADENA),
        Campo("monto_en_libros", Tipo.DECIMAL, escala=2, opcional=True),
        Campo("fuente_de_libros", Tipo.CADENA),
    ),
)
"""El expediente declara de qué fuente salieron los libros: un financiador tiene
derecho a saber si lo que audita es contabilidad real o una demo sintética."""

ESQUEMA_CESION_REGISTRADA = Esquema(
    nombre="cesion_registrada",
    campos=_COMUNES
    + (
        Campo("uuid", Tipo.CADENA),
        Campo("rfc_emisor", Tipo.CADENA),
        Campo("financiador", Tipo.CADENA),
        Campo("total", Tipo.DECIMAL, escala=2),
        Campo("moneda", Tipo.CADENA),
    ),
)

ESQUEMA_CESION_RECHAZADA = Esquema(
    nombre="cesion_rechazada",
    campos=_COMUNES
    + (
        Campo("uuid", Tipo.CADENA),
        Campo("financiador", Tipo.CADENA),
        Campo("motivo", Tipo.CADENA),
        Campo("posicion_de_la_cesion_previa", Tipo.ENTERO),
    ),
)
"""El rechazo apunta a la **posición** de la cesión previa, no a su fecha.

Una posición es verificable: quien reciba la prueba de integridad puede pedir
ese eslabón y comprobarlo. Una fecha solo se puede creer.
"""

ESQUEMAS: dict[Evento, Esquema] = {
    Evento.CFDI_AUDITADO: ESQUEMA_CFDI_AUDITADO,
    Evento.CESION_REGISTRADA: ESQUEMA_CESION_REGISTRADA,
    Evento.CESION_RECHAZADA: ESQUEMA_CESION_RECHAZADA,
}


def esquema_de(evento: Evento) -> Esquema:
    try:
        return ESQUEMAS[evento]
    except KeyError:  # pragma: no cover - imposible con el Enum
        raise ValueError(f"no hay esquema declarado para {evento}") from None
