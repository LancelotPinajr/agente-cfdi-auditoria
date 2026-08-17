"""Pruebas del cotejo contra los libros."""

from datetime import date, datetime
from decimal import Decimal

from agente_cfdi.auditoria.cotejo import cotejar
from agente_cfdi.bitacora.eventos import Veredicto
from agente_cfdi.cfdi.lector import ComprobanteLeido
from agente_cfdi.fuentes.protocolo import Movimiento, TipoDeMovimiento

UUID = "9F2C1A88-FB09-47F8-B5F9-6DD1C6889D8C"


def comprobante(total="1000.00", uuid=UUID):
    return ComprobanteLeido(
        uuid=uuid,
        rfc_emisor="QZU000000D18",
        rfc_receptor="ABC000000X11",
        total=Decimal(total),
        moneda="MXN",
        fecha_emision=datetime(2026, 7, 15, 10, 30),
        fecha_timbrado=datetime(2026, 7, 15, 10, 35),
        version="4.0",
    )


def movimiento(monto="1000.00", referencia=UUID, tipo=TipoDeMovimiento.INGRESO):
    return Movimiento(
        identificador="m-1",
        fecha=date(2026, 7, 15),
        concepto="Venta",
        tipo=tipo,
        monto=Decimal(monto),
        referencia=referencia,
    )


def test_un_movimiento_del_mismo_importe_respalda():
    resultado = cotejar(comprobante(), (movimiento(),))
    assert resultado.veredicto is Veredicto.RESPALDADO
    assert resultado.diferencia == Decimal("0")
    assert not resultado.es_hallazgo


def test_sin_movimiento_es_sin_respaldo():
    resultado = cotejar(comprobante(), ())
    assert resultado.veredicto is Veredicto.SIN_RESPALDO
    assert resultado.monto_en_libros is None
    assert resultado.diferencia is None
    assert resultado.es_hallazgo


def test_un_importe_distinto_es_hallazgo():
    resultado = cotejar(comprobante("1000.00"), (movimiento("850.00"),))
    assert resultado.veredicto is Veredicto.MONTO_DISTINTO
    assert resultado.diferencia == Decimal("150.00")
    assert resultado.es_hallazgo


def test_los_pagos_parciales_se_suman():
    """Un CFDI saldado en dos renglones está respaldado, no desviado."""
    resultado = cotejar(comprobante("1000.00"), (movimiento("400.00"), movimiento("600.00")))
    assert resultado.veredicto is Veredicto.RESPALDADO
    assert resultado.renglones == 2


def test_un_ingreso_contado_dos_veces_es_hallazgo():
    """Lo que destapó la demo: el mismo folio registrado dos veces en los libros."""
    resultado = cotejar(comprobante("1000.00"), (movimiento("1000.00"), movimiento("1000.00")))
    assert resultado.veredicto is Veredicto.MONTO_DISTINTO
    assert resultado.monto_en_libros == Decimal("2000.00")


def test_un_movimiento_de_otro_folio_no_respalda():
    otro = movimiento(referencia="00000000-0000-0000-0000-000000000000")
    assert cotejar(comprobante(), (otro,)).veredicto is Veredicto.SIN_RESPALDO


def test_un_egreso_no_respalda_un_cfdi_de_ingreso():
    egreso = movimiento(tipo=TipoDeMovimiento.EGRESO)
    assert cotejar(comprobante(), (egreso,)).veredicto is Veredicto.SIN_RESPALDO


def test_un_movimiento_sin_referencia_no_se_adivina():
    """Dos facturas del mismo cliente por el mismo importe son indistinguibles
    sin referencia; adivinar produce un veredicto que parece riguroso y no lo es."""
    huerfano = movimiento(referencia=None)
    assert cotejar(comprobante(), (huerfano,)).veredicto is Veredicto.SIN_RESPALDO


def test_la_referencia_se_compara_sin_importar_mayusculas_ni_espacios():
    laxo = movimiento(referencia=f"  {UUID.lower()}  ")
    assert cotejar(comprobante(), (laxo,)).veredicto is Veredicto.RESPALDADO


def test_no_auditado_no_cuenta_como_hallazgo():
    """Una caída de red no es una desviación contable."""
    from agente_cfdi.auditoria.cotejo import Cotejo

    caido = Cotejo(
        uuid=UUID,
        veredicto=Veredicto.NO_AUDITADO,
        monto_del_cfdi=Decimal("1000.00"),
        monto_en_libros=None,
    )
    assert not caido.es_hallazgo
