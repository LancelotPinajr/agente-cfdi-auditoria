"""La costura entre el agente y los libros de la PYME (tarea 1.17).

El agente audita los CFDI **contra la contabilidad** de quien los emitió. Esa
contabilidad puede venir de CØRD Fiscal por HTTP o de un generador sintético;
el agente no debe notar la diferencia ni contener un `if` que la distinga.

De aquí sale la puerta hacia datos reales: cambiar de fuente es configuración,
no reescritura. Lo que **no** es trivial es cruzarla — ver
`docs/datos-sinteticos.md` §6 (consentimiento expreso, minimización, retención).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Protocol, runtime_checkable


class TipoDeMovimiento(Enum):
    INGRESO = "ingreso"
    EGRESO = "egreso"
    SIN_CLASIFICAR = "sin_clasificar"


@dataclass(frozen=True)
class Movimiento:
    """Un renglón de la contabilidad de la PYME.

    **Ya viene minimizado.** La fuente real trae más columnas de las que están
    aquí —el renglón original del Excel, la categoría inferida, notas del
    importador— y esas no cruzan la frontera: el agente no las necesita para
    cotejar un CFDI contra los libros, así que no las pide. Es la minimización
    del art. 6 de la LFPDPPP aplicada donde de verdad importa, en la petición y
    no en un párrafo del aviso de privacidad.
    """

    identificador: str
    fecha: date | None
    concepto: str
    tipo: TipoDeMovimiento
    monto: Decimal
    rfc_contraparte: str | None = None
    referencia: str | None = None
    tiene_comprobante: bool = False

    @property
    def es_cobrable(self) -> bool:
        """Un ingreso registrado es el renglón que un CFDI de ingreso debería tener detrás."""
        return self.tipo is TipoDeMovimiento.INGRESO


class ErrorDeFuente(RuntimeError):
    """La contabilidad de la PYME no se pudo obtener.

    Se distingue a propósito de «la PYME no tiene movimientos»: no encontrar
    respaldo contable de un CFDI es un hallazgo de auditoría; no haber podido
    preguntar es una falla de infraestructura. Confundirlas haría que una caída
    de red se reportara al financiador como libros inconsistentes.
    """


@runtime_checkable
class FuenteDeLibros(Protocol):
    """De dónde salen los movimientos contra los que se auditan los CFDI."""

    @property
    def descripcion(self) -> str:
        """Cómo nombrar esta fuente en el expediente y en los logs.

        Va en el expediente a propósito: un financiador tiene derecho a saber si
        lo que audita salió de la contabilidad real o de un lote de demostración.
        """

    def movimientos(
        self, *, desde: date | None = None, hasta: date | None = None
    ) -> tuple[Movimiento, ...]:
        """Los movimientos de la PYME en el periodo, ya minimizados.

        Levanta `ErrorDeFuente` si no se pudieron obtener. Devolver una tupla
        vacía significa «no hay movimientos», que es un dato distinto.
        """
