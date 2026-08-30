"""Pruebas de las herramientas del agente (brecha #6 del manual).

No importan ADK: las herramientas son Python plano justamente para que el CI
—que instala solo lo declarado en `pyproject.toml`— pueda ejercitarlas.
"""

import pytest
from fastapi.testclient import TestClient

from agente_cfdi.agente import (
    HERRAMIENTAS,
    consultar_folio,
    estado_de_integridad,
    resumen_de_la_bitacora,
)
from agente_cfdi.api import dependencias
from agente_cfdi.api.app import app
from agente_cfdi.fuentes.sintetica import ContabilidadSintetica
from agente_cfdi.sintetico.generador import generar_lote

SEMILLA = 20260815


@pytest.fixture
def lote():
    return generar_lote(cantidad=5, semilla=SEMILLA)


@pytest.fixture
def entorno(tmp_path, lote, monkeypatch):
    """Una bitácora real en disco, que es como las ve el agente."""
    monkeypatch.setenv(dependencias.VARIABLE_RUTA, str(tmp_path / "bitacora.db"))
    monkeypatch.setenv(dependencias.VARIABLE_INQUILINO, "DEMO000000XX0")
    libros = ContabilidadSintetica(lote=lote, sin_respaldo=(1,), monto_alterado=(3,))
    app.dependency_overrides[dependencias.fuente_actual] = lambda: libros
    with TestClient(app) as cliente:
        yield cliente
    app.dependency_overrides.clear()


def ingestar(cliente, lote):
    return cliente.post(
        "/ingesta",
        files=[
            ("archivos", (f"{c.uuid}.xml", c.a_xml().encode("utf-8"), "application/xml"))
            for c in lote.comprobantes
        ],
    ).json()


# --------------------------------------------------------------------------- #
# El agente no puede escribir
# --------------------------------------------------------------------------- #


def test_ninguna_herramienta_escribe_en_la_bitacora(entorno, lote):
    """La decisión que más importa de este módulo.

    Un LLM que alucina una llamada a herramienta es un hecho conocido. Si esa
    llamada pudiera anexar una auditoría, bastaría una para dejar un veredicto
    falso, firmado y permanente en una cadena que no se puede corregir.
    """
    ingestar(entorno, lote)
    antes = entorno.get("/salud").json()

    for herramienta in HERRAMIENTAS:
        if herramienta is consultar_folio:
            herramienta(lote.comprobantes[0].uuid)
        else:
            herramienta()

    despues = entorno.get("/salud").json()
    assert despues["altura"] == antes["altura"]
    assert despues["punta"] == antes["punta"]


def test_no_hay_herramienta_de_ingesta_ni_de_cesion(entorno):
    """Si alguien añade una que escriba, esta prueba lo tiene que frenar."""
    nombres = {h.__name__ for h in HERRAMIENTAS}
    prohibidas = {"ingestar", "ceder", "registrar_cesion", "cerrar_dia", "anclar"}
    assert not (nombres & prohibidas)
    assert nombres == {"estado_de_integridad", "consultar_folio", "resumen_de_la_bitacora"}


# --------------------------------------------------------------------------- #
# Ni filtra el financiador
# --------------------------------------------------------------------------- #


def test_consultar_folio_no_revela_el_financiador(entorno, lote):
    """El agente sería el camino fácil para sacar lo que el endpoint oculta."""
    ingestar(entorno, lote)
    comprobante = lote.comprobantes[0]
    entorno.post(
        "/cesiones",
        json={
            "uuid": comprobante.uuid,
            "financiador": "Banco Norte",
            "total": str(comprobante.total),
            "moneda": "MXN",
        },
    )

    resultado = consultar_folio(comprobante.uuid)

    assert resultado["cedido"] is True
    assert "Banco Norte" not in str(resultado)
    assert not any("financiador" in clave for clave in resultado)


# --------------------------------------------------------------------------- #
# Lo que sí devuelven
# --------------------------------------------------------------------------- #


def test_consultar_folio_trae_el_veredicto_y_su_significado(entorno, lote):
    cuerpo = ingestar(entorno, lote)
    con_hallazgo = next(r for r in cuerpo["registros"] if r["veredicto"] == "sin_respaldo")

    resultado = consultar_folio(con_hallazgo["uuid"])

    assert resultado["encontrado"] is True
    assert resultado["veredicto"] == "sin_respaldo"
    assert "no registra ningún ingreso" in resultado["significado"]
    assert resultado["cedido"] is False


def test_un_folio_desconocido_no_se_confunde_con_una_factura_falsa(entorno):
    """«Aquí no consta» y «es falsa» no son lo mismo, y el modelo podría mezclarlas."""
    resultado = consultar_folio("00000000-0000-0000-0000-000000000000")

    assert resultado["encontrado"] is False
    assert "No significa que la factura sea falsa" in resultado["detalle"]


def test_un_uuid_mal_formado_se_explica_en_vez_de_reventar(entorno):
    resultado = consultar_folio("no-soy-un-uuid")

    assert resultado["encontrado"] is False
    assert "36 caracteres" in resultado["error"]


def test_consultar_folio_tolera_minusculas_y_espacios(entorno, lote):
    ingestar(entorno, lote)
    laxo = f"  {lote.comprobantes[2].uuid.lower()}  "
    assert consultar_folio(laxo)["encontrado"] is True


def test_el_estado_de_integridad_es_ambar_con_ancla_simulada(entorno, lote):
    ingestar(entorno, lote)
    estado = estado_de_integridad()

    assert estado["color"] == "ambar"
    assert estado["verificados"] == 5


def test_el_estado_de_integridad_detecta_la_manipulacion(entorno, lote, tmp_path):
    import sqlite3

    ingestar(entorno, lote)
    conexion = sqlite3.connect(tmp_path / "bitacora.db")
    conexion.execute(
        "UPDATE bitacora_registros SET canonico = ? WHERE posicion = 2", (b"alterado",)
    )
    conexion.commit()
    conexion.close()

    estado = estado_de_integridad()
    assert estado["color"] == "rojo"
    assert estado["posicion_del_problema"] == 2


def test_el_resumen_cuenta_la_cadena_y_dice_si_se_cerro(entorno, lote):
    ingestar(entorno, lote)

    antes = resumen_de_la_bitacora()
    assert antes["registros_en_la_cadena"] == 5
    assert antes["dia_cerrado"] is False
    assert antes["raiz_del_dia"] is None

    entorno.post("/cierre-diario")

    despues = resumen_de_la_bitacora()
    assert despues["dia_cerrado"] is True
    assert len(despues["raiz_del_dia"]) == 64


def test_las_herramientas_leen_la_misma_bitacora_que_los_endpoints(entorno, lote):
    """Duplicar la lectura del entorno haría que el agente consultara otra base."""
    ingestar(entorno, lote)

    por_endpoint = entorno.get("/salud").json()["altura"]
    por_herramienta = resumen_de_la_bitacora()["registros_en_la_cadena"]

    assert por_endpoint == por_herramienta == 5


# --------------------------------------------------------------------------- #
# Lo que el modelo va a leer
# --------------------------------------------------------------------------- #


def test_toda_herramienta_trae_docstring(entorno):
    """ADK se lo pasa al modelo como descripción: sin él, no sabe cuándo usarla."""
    for herramienta in HERRAMIENTAS:
        assert herramienta.__doc__, f"{herramienta.__name__} no tiene docstring"
        assert len(herramienta.__doc__) > 80


def test_toda_herramienta_devuelve_algo_serializable(entorno, lote):
    """ADK manda el resultado como JSON; un objeto raro rompe el turno."""
    import json

    ingestar(entorno, lote)
    for herramienta in HERRAMIENTAS:
        salida = (
            herramienta(lote.comprobantes[0].uuid)
            if herramienta is consultar_folio
            else herramienta()
        )
        json.dumps(salida)  # levanta si no es serializable
