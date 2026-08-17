"""Contabilidad sintética: la otra implementación de la costura (tarea 1.17).

Deriva los movimientos del mismo lote de CFDI que se generó, de modo que los
libros **cuadran con las facturas** — que es el caso normal de una PYME honesta.

Para que la demo tenga algo que encontrar, acepta desviaciones plantadas: una
factura sin respaldo en libros, un monto que no coincide. Son los hallazgos que
el paso de auditoría debe reportar; sin ellos la demo enseña un semáforo verde
y nadie sabe si el sistema sirve.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from ..sintetico.generador import Lote
from .protocolo import Movimiento, TipoDeMovimiento


@dataclass(frozen=True)
class Desviacion:
    """Una diferencia plantada a propósito entre los CFDI y los libros."""

    uuid: str
    clase: str  # "sin_respaldo" | "monto_distinto"
    detalle: str


@dataclass(frozen=True)
class ContabilidadSintetica:
    """Libros derivados de un lote de CFDI.

    `sin_respaldo` y `monto_alterado` reciben posiciones dentro del lote (no
    UUID) para que el escenario sea reproducible desde la semilla sin tener que
    conocer de antemano qué UUID salieron.
    """

    lote: Lote
    sin_respaldo: tuple[int, ...] = ()
    monto_alterado: tuple[int, ...] = ()
    desfase: Decimal = Decimal("150.00")

    _cache: list = field(default_factory=list, repr=False, compare=False)

    @property
    def descripcion(self) -> str:
        return f"contabilidad sintética (semilla {self.lote.semilla}) — NO son libros reales"

    @property
    def desviaciones(self) -> tuple[Desviacion, ...]:
        """Lo que el auditor debería encontrar. Es la respuesta del examen."""
        plantadas = []
        for posicion in self.sin_respaldo:
            plantadas.append(
                Desviacion(
                    uuid=self._en(posicion).uuid,
                    clase="sin_respaldo",
                    detalle="el CFDI existe y no hay ingreso registrado que lo respalde",
                )
            )
        for posicion in self.monto_alterado:
            plantadas.append(
                Desviacion(
                    uuid=self._en(posicion).uuid,
                    clase="monto_distinto",
                    detalle=f"los libros registran {self.desfase} menos que el CFDI",
                )
            )
        return tuple(plantadas)

    def movimientos(
        self, *, desde: date | None = None, hasta: date | None = None
    ) -> tuple[Movimiento, ...]:
        salida: list[Movimiento] = []
        for posicion, comprobante in enumerate(self.lote.comprobantes):
            if posicion in self.sin_respaldo:
                continue
            monto = comprobante.total
            if posicion in self.monto_alterado:
                monto -= self.desfase
            fecha = comprobante.fecha_emision.date()
            if desde and fecha < desde:
                continue
            if hasta and fecha > hasta:
                continue
            salida.append(
                Movimiento(
                    identificador=f"sint-{posicion:05d}",
                    fecha=fecha,
                    concepto=f"Venta {comprobante.serie}-{comprobante.folio}",
                    tipo=TipoDeMovimiento.INGRESO,
                    monto=monto,
                    rfc_contraparte=comprobante.receptor.rfc,
                    referencia=comprobante.uuid,
                    tiene_comprobante=True,
                )
            )
        return tuple(salida)

    def _en(self, posicion: int):
        return self.lote.comprobantes[posicion]
