"""Pruebas de la costura de fuentes de datos (tareas 1.11 y 1.17).

El cliente de CØRD Fiscal se prueba con un transporte falso: la plataforma es
preexistente y externa, y una prueba que dependa de tenerla levantada no es una
prueba, es un recordatorio.
"""

from datetime import date
from decimal import Decimal

import pytest

from agente_cfdi.fuentes.configuracion import (
    CORD_FISCAL,
    SINTETICA,
    VARIABLE,
    ConfiguracionInvalida,
    fuente_desde_entorno,
)
from agente_cfdi.fuentes.cord_fiscal import PAGINA, ClienteCordFiscal
from agente_cfdi.fuentes.protocolo import (
    ErrorDeFuente,
    FuenteDeLibros,
    Movimiento,
    TipoDeMovimiento,
)
from agente_cfdi.fuentes.sintetica import ContabilidadSintetica
from agente_cfdi.sintetico.generador import generar_lote


def transporte_falso(libros, movimientos_por_libro, registro=None):
    """Imita a CØRD Fiscal sin red. `registro` acumula las rutas pedidas."""

    def transporte(ruta, parametros):
        if registro is not None:
            registro.append((ruta, dict(parametros)))
        if ruta == "/fiscal/contabilidad/libros":
            return {"libros": libros, "resumen": {}, "pendientes_de_confirmar": 0}
        libro_id = ruta.rsplit("/", 1)[-1]
        renglones = movimientos_por_libro.get(libro_id, [])
        inicio = parametros.get("offset", 0)
        return {"id": libro_id, "movimientos": renglones[inicio : inicio + parametros["limite"]]}

    return transporte


RENGLON = {
    "id": "mov-1",
    "fila": 4,
    "fecha": "2026-07-15",
    "concepto": "Venta A-1201",
    "tipo": "ingreso",
    "monto": "142878.90",
    "iva": "19707.43",
    "categoria": "ventas",
    "forma_pago": "transferencia",
    "contraparte": "Aceros del Norte",
    "rfc_contraparte": "qzu000000d18",
    "referencia": "A-1201",
    "tiene_comprobante": True,
    "datos_originales": {"col_a": "lo que venía en el Excel"},
    "problemas": [],
}


# --------------------------------------------------------------------------- #
# 1.11 — lectura por HTTP
# --------------------------------------------------------------------------- #


def test_obtiene_los_movimientos_de_una_pyme():
    cliente = ClienteCordFiscal(
        base_url="https://api.ejemplo.mx",
        token="jwt",
        transporte=transporte_falso(
            [{"id": "L1", "estado": "confirmado"}], {"L1": [RENGLON]}
        ),
    )
    (movimiento,) = cliente.movimientos()

    assert movimiento.identificador == "mov-1"
    assert movimiento.fecha == date(2026, 7, 15)
    assert movimiento.monto == Decimal("142878.90")
    assert movimiento.tipo is TipoDeMovimiento.INGRESO
    assert movimiento.es_cobrable
    assert movimiento.rfc_contraparte == "QZU000000D18"  # normalizado
    assert movimiento.tiene_comprobante


def test_la_minimizacion_ocurre_en_la_traduccion():
    """Lo que no cruza la frontera no se puede filtrar después."""
    cliente = ClienteCordFiscal(
        base_url="https://api.ejemplo.mx",
        token="jwt",
        transporte=transporte_falso(
            [{"id": "L1", "estado": "confirmado"}], {"L1": [RENGLON]}
        ),
    )
    (movimiento,) = cliente.movimientos()

    campos = set(vars(movimiento))
    for excedente in ("datos_originales", "categoria", "problemas", "iva", "contraparte"):
        assert excedente not in campos, f"{excedente} no debería cruzar"


def test_ignora_los_libros_sin_confirmar():
    """Un libro sin confirmar es una interpretación que nadie validó."""
    cliente = ClienteCordFiscal(
        base_url="https://api.ejemplo.mx",
        token="jwt",
        transporte=transporte_falso(
            [{"id": "L1", "estado": "propuesto"}, {"id": "L2", "estado": "confirmado"}],
            {"L1": [RENGLON], "L2": [dict(RENGLON, id="mov-2")]},
        ),
    )
    assert [m.identificador for m in cliente.movimientos()] == ["mov-2"]


def test_pagina_hasta_agotar_el_libro():
    renglones = [dict(RENGLON, id=f"mov-{i}") for i in range(PAGINA + 30)]
    registro = []
    cliente = ClienteCordFiscal(
        base_url="https://api.ejemplo.mx",
        token="jwt",
        transporte=transporte_falso(
            [{"id": "L1", "estado": "confirmado"}], {"L1": renglones}, registro
        ),
    )
    assert len(cliente.movimientos()) == PAGINA + 30
    offsets = [p["offset"] for r, p in registro if "libros/L1" in r]
    assert offsets == [0, PAGINA]


def test_filtra_por_ventana_de_fechas():
    renglones = [
        dict(RENGLON, id="viejo", fecha="2026-01-10"),
        dict(RENGLON, id="dentro", fecha="2026-07-15"),
        dict(RENGLON, id="nuevo", fecha="2026-08-30"),
    ]
    cliente = ClienteCordFiscal(
        base_url="https://api.ejemplo.mx",
        token="jwt",
        transporte=transporte_falso([{"id": "L1", "estado": "confirmado"}], {"L1": renglones}),
    )
    obtenidos = cliente.movimientos(desde=date(2026, 7, 1), hasta=date(2026, 7, 31))
    assert [m.identificador for m in obtenidos] == ["dentro"]


def test_un_movimiento_sin_fecha_no_entra_en_una_ventana():
    """No se puede afirmar que algo sin fecha cayó dentro de un periodo."""
    renglones = [dict(RENGLON, id="sin_fecha", fecha=None)]
    cliente = ClienteCordFiscal(
        base_url="https://api.ejemplo.mx",
        token="jwt",
        transporte=transporte_falso([{"id": "L1", "estado": "confirmado"}], {"L1": renglones}),
    )
    assert cliente.movimientos(desde=date(2026, 1, 1)) == ()
    assert len(cliente.movimientos()) == 1  # sin ventana sí entra


def test_un_renglon_basura_no_tumba_la_auditoria_del_resto():
    """La contabilidad importada de un Excel trae renglones basura por definición."""
    renglones = [
        {"nada": "que ver"},
        None,
        dict(RENGLON, id="bueno"),
        dict(RENGLON, id="sin_monto", monto=None),
        "esto no es un renglón",
    ]
    cliente = ClienteCordFiscal(
        base_url="https://api.ejemplo.mx",
        token="jwt",
        transporte=transporte_falso([{"id": "L1", "estado": "confirmado"}], {"L1": renglones}),
    )
    assert [m.identificador for m in cliente.movimientos()] == ["bueno"]


def test_un_tipo_desconocido_no_se_convierte_en_ingreso():
    """Adivinar aquí inventaría cobros que la PYME no registró."""
    renglones = [dict(RENGLON, id="raro", tipo="pendiente_de_revision")]
    cliente = ClienteCordFiscal(
        base_url="https://api.ejemplo.mx",
        token="jwt",
        transporte=transporte_falso([{"id": "L1", "estado": "confirmado"}], {"L1": renglones}),
    )
    (movimiento,) = cliente.movimientos()
    assert movimiento.tipo is TipoDeMovimiento.SIN_CLASIFICAR
    assert not movimiento.es_cobrable


def test_un_importe_float_no_arrastra_el_error_del_binario():
    renglones = [dict(RENGLON, id="flotante", monto=100.5)]
    cliente = ClienteCordFiscal(
        base_url="https://api.ejemplo.mx",
        token="jwt",
        transporte=transporte_falso([{"id": "L1", "estado": "confirmado"}], {"L1": renglones}),
    )
    (movimiento,) = cliente.movimientos()
    assert movimiento.monto == Decimal("100.5")


def test_una_caida_de_red_es_error_de_fuente_y_no_libros_inconsistentes():
    """Confundirlas reportaría al financiador una caída como fraude contable."""

    def transporte_caido(ruta, parametros):
        raise ConnectionError("se cayó la red")

    cliente = ClienteCordFiscal(
        base_url="https://api.ejemplo.mx", token="jwt", transporte=transporte_caido
    )
    with pytest.raises(ErrorDeFuente) as caso:
        cliente.movimientos()
    assert "CØRD Fiscal" in str(caso.value)


def test_el_error_no_repite_el_token():
    def transporte_caido(ruta, parametros):
        raise ConnectionError("falló con el token secreto-no-publicar")

    cliente = ClienteCordFiscal(
        base_url="https://api.ejemplo.mx",
        token="secreto-no-publicar",
        transporte=transporte_caido,
    )
    with pytest.raises(ErrorDeFuente) as caso:
        cliente.movimientos()
    assert "secreto-no-publicar" not in str(caso.value)


def test_una_respuesta_con_otro_contrato_se_denuncia():
    def transporte_raro(ruta, parametros):
        return {"resultados": []}

    cliente = ClienteCordFiscal(
        base_url="https://api.ejemplo.mx", token="jwt", transporte=transporte_raro
    )
    with pytest.raises(ErrorDeFuente, match="contrato cambió"):
        cliente.movimientos()


def test_la_descripcion_no_incluye_el_token():
    cliente = ClienteCordFiscal(base_url="https://api.ejemplo.mx/", token="jwt")
    assert cliente.descripcion == "CØRD Fiscal (api.ejemplo.mx)"


# --------------------------------------------------------------------------- #
# 1.17 — las dos implementaciones cumplen la misma costura
# --------------------------------------------------------------------------- #


def test_ambas_fuentes_satisfacen_el_protocolo():
    sintetica = ContabilidadSintetica(lote=generar_lote(cantidad=5, semilla=1))
    real = ClienteCordFiscal(base_url="https://api.ejemplo.mx", token="jwt")
    assert isinstance(sintetica, FuenteDeLibros)
    assert isinstance(real, FuenteDeLibros)


def test_las_dos_devuelven_movimientos_del_mismo_tipo():
    sintetica = ContabilidadSintetica(lote=generar_lote(cantidad=5, semilla=1))
    real = ClienteCordFiscal(
        base_url="https://api.ejemplo.mx",
        token="jwt",
        transporte=transporte_falso([{"id": "L1", "estado": "confirmado"}], {"L1": [RENGLON]}),
    )
    for fuente in (sintetica, real):
        for movimiento in fuente.movimientos():
            assert isinstance(movimiento, Movimiento)
            assert isinstance(movimiento.monto, Decimal)


def test_la_fuente_se_nombra_a_si_misma_en_el_expediente():
    """Un financiador tiene derecho a saber si audita libros reales o una demo."""
    sintetica = ContabilidadSintetica(lote=generar_lote(cantidad=3, semilla=1))
    assert "NO son libros reales" in sintetica.descripcion


# --------------------------------------------------------------------------- #
# Fuente sintética
# --------------------------------------------------------------------------- #


def test_los_libros_sinteticos_cuadran_con_las_facturas():
    lote = generar_lote(cantidad=10, semilla=8)
    libros = ContabilidadSintetica(lote=lote)
    movimientos = libros.movimientos()

    assert len(movimientos) == len(lote.comprobantes)
    assert sum(m.monto for m in movimientos) == sum(c.total for c in lote.comprobantes)
    assert not libros.desviaciones


def test_las_desviaciones_plantadas_son_las_que_el_auditor_debe_encontrar():
    lote = generar_lote(cantidad=10, semilla=8)
    libros = ContabilidadSintetica(lote=lote, sin_respaldo=(2,), monto_alterado=(5,))

    movimientos = libros.movimientos()
    assert len(movimientos) == len(lote.comprobantes) - 1

    clases = {d.clase for d in libros.desviaciones}
    assert clases == {"sin_respaldo", "monto_distinto"}
    assert {d.uuid for d in libros.desviaciones} == {
        lote.comprobantes[2].uuid,
        lote.comprobantes[5].uuid,
    }
    alterado = next(m for m in movimientos if m.referencia == lote.comprobantes[5].uuid)
    assert alterado.monto == lote.comprobantes[5].total - libros.desfase


def test_la_fuente_sintetica_respeta_la_ventana_de_fechas():
    lote = generar_lote(cantidad=20, semilla=8)
    libros = ContabilidadSintetica(lote=lote)
    corte = sorted(c.fecha_emision.date() for c in lote.comprobantes)[10]

    recientes = libros.movimientos(desde=corte)
    assert recientes and all(m.fecha >= corte for m in recientes)
    assert len(recientes) < len(libros.movimientos())


# --------------------------------------------------------------------------- #
# 1.17 — cambiar de fuente es configuración
# --------------------------------------------------------------------------- #


def test_sin_configurar_nada_sale_la_fuente_sintetica():
    """Quien clona el repo obtiene una demo que corre, no un error de credenciales."""
    fuente = fuente_desde_entorno({})
    assert isinstance(fuente, ContabilidadSintetica)
    assert fuente.movimientos()


def test_la_variable_de_entorno_elige_la_fuente_real():
    fuente = fuente_desde_entorno(
        {
            VARIABLE: CORD_FISCAL,
            "CORD_FISCAL_URL": "https://api.cordgroup.cloud",
            "CORD_FISCAL_TOKEN": "jwt",
        }
    )
    assert isinstance(fuente, ClienteCordFiscal)


@pytest.mark.parametrize(
    "entorno",
    [
        {VARIABLE: CORD_FISCAL},
        {VARIABLE: CORD_FISCAL, "CORD_FISCAL_URL": "https://api.x.mx"},
        {VARIABLE: CORD_FISCAL, "CORD_FISCAL_TOKEN": "jwt"},
    ],
)
def test_la_fuente_real_sin_credenciales_falla_diciendo_que_falta(entorno):
    with pytest.raises(ConfiguracionInvalida, match="CORD_FISCAL_"):
        fuente_desde_entorno(entorno)


def test_http_plano_se_rechaza_porque_el_token_viaja_en_cada_peticion():
    with pytest.raises(ConfiguracionInvalida, match="https"):
        fuente_desde_entorno(
            {
                VARIABLE: CORD_FISCAL,
                "CORD_FISCAL_URL": "http://api.cordgroup.cloud",
                "CORD_FISCAL_TOKEN": "jwt",
            }
        )


def test_localhost_si_puede_ser_http():
    fuente = fuente_desde_entorno(
        {
            VARIABLE: CORD_FISCAL,
            "CORD_FISCAL_URL": "http://localhost:8000",
            "CORD_FISCAL_TOKEN": "jwt",
        }
    )
    assert isinstance(fuente, ClienteCordFiscal)


def test_una_fuente_desconocida_no_cae_en_silencio_a_la_sintetica():
    with pytest.raises(ConfiguracionInvalida, match="no se reconoce"):
        fuente_desde_entorno({VARIABLE: "produccion"})


def test_la_semilla_del_lote_sintetico_es_configurable():
    uno = fuente_desde_entorno({VARIABLE: SINTETICA, "AGENTE_CFDI_SEMILLA": "1"})
    otro = fuente_desde_entorno({VARIABLE: SINTETICA, "AGENTE_CFDI_SEMILLA": "2"})
    assert uno.movimientos() != otro.movimientos()

    with pytest.raises(ConfiguracionInvalida):
        fuente_desde_entorno({VARIABLE: SINTETICA, "AGENTE_CFDI_SEMILLA": "ayer"})
