"""Contrastar un CFDI contra los libros de la PYME.

Es el paso 3 del ciclo: el comprobante dice «cobré 142,878.90», y la
contabilidad tiene que decir lo mismo. Cuando no coinciden, el financiador
merece enterarse **antes** de comprar la cuenta por cobrar.

## Un CFDI se puede saldar en varios renglones

Los movimientos que apuntan al mismo folio se **suman** antes de comparar. Un
pago parcial es contabilidad normal, no una desviación, y tratar cada renglón por
separado reportaría un anticipo legítimo como monto distinto.

## Lo que este módulo no decide

No decide si la PYME es confiable. Emite un veredicto por comprobante y con eso
se arma el expediente; el juicio comercial es de quien presta el dinero.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..bitacora.eventos import Veredicto
from ..cfdi.lector import ComprobanteLeido
from ..fuentes.protocolo import Movimiento


@dataclass(frozen=True)
class Cotejo:
    """El resultado de contrastar un comprobante contra los libros."""

    uuid: str
    veredicto: Veredicto
    monto_del_cfdi: Decimal
    monto_en_libros: Decimal | None
    renglones: int = 0
    """Cuántos movimientos respaldan el folio. Más de uno es normal: pagos
    parciales. Cero con veredicto distinto de `SIN_RESPALDO` sería un error."""

    @property
    def diferencia(self) -> Decimal | None:
        if self.monto_en_libros is None:
            return None
        return self.monto_del_cfdi - self.monto_en_libros

    @property
    def es_hallazgo(self) -> bool:
        """¿Esto es algo que el financiador tiene que ver?

        `NO_AUDITADO` **no** es un hallazgo: es una falla de infraestructura, y
        contarla como desviación reportaría una caída de red como libros
        inconsistentes.
        """
        return self.veredicto in (Veredicto.SIN_RESPALDO, Veredicto.MONTO_DISTINTO)


def cotejar(comprobante: ComprobanteLeido, movimientos: tuple[Movimiento, ...]) -> Cotejo:
    """Emite el veredicto de un comprobante contra los movimientos de la PYME.

    El enlace es la **referencia** del movimiento contra el UUID del
    comprobante. No se coteja por monto y fecha aproximados: dos facturas del
    mismo cliente por el mismo importe en la misma semana son indistinguibles
    así, y adivinar mal aquí produce un veredicto que parece riguroso y no lo es.
    """
    respaldos = [
        movimiento
        for movimiento in movimientos
        if movimiento.es_cobrable
        and movimiento.referencia
        and movimiento.referencia.strip().upper() == comprobante.uuid.strip().upper()
    ]

    if not respaldos:
        return Cotejo(
            uuid=comprobante.uuid,
            veredicto=Veredicto.SIN_RESPALDO,
            monto_del_cfdi=comprobante.total,
            monto_en_libros=None,
        )

    en_libros = sum((movimiento.monto for movimiento in respaldos), Decimal("0"))
    coincide = en_libros == comprobante.total
    return Cotejo(
        uuid=comprobante.uuid,
        veredicto=Veredicto.RESPALDADO if coincide else Veredicto.MONTO_DISTINTO,
        monto_del_cfdi=comprobante.total,
        monto_en_libros=en_libros,
        renglones=len(respaldos),
    )


def cotejar_lote(
    comprobantes: tuple[ComprobanteLeido, ...], movimientos: tuple[Movimiento, ...]
) -> tuple[Cotejo, ...]:
    """Coteja un lote contra **una sola** lectura de los libros.

    Se pide la contabilidad una vez y se coteja todo contra esa foto. Pedirla por
    comprobante sería un martilleo a CØRD Fiscal y, peor, cotejaría distintos
    CFDI contra distintos estados de los libros: dos comprobantes del mismo lote
    podrían recibir veredictos que nunca fueron ciertos al mismo tiempo.
    """
    return tuple(cotejar(comprobante, movimientos) for comprobante in comprobantes)
