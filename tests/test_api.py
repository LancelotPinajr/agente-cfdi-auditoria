"""Pruebas de los endpoints de ingesta y cesión (tarea 2.4)."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from agente_cfdi.api import dependencias
from agente_cfdi.api.app import app
from agente_cfdi.bitacora.almacen import Bitacora
from agente_cfdi.fuentes.sintetica import ContabilidadSintetica
from agente_cfdi.sintetico.generador import generar_lote

SEMILLA = 20260815
INQUILINO = "DEMO000000XX0"


@pytest.fixture
def lote():
    return generar_lote(cantidad=6, semilla=SEMILLA)


@pytest.fixture
def libros(lote):
    """Libros con dos desviaciones plantadas: una sin respaldo, una con desfase."""
    return ContabilidadSintetica(lote=lote, sin_respaldo=(1,), monto_alterado=(3,))


@pytest.fixture
def cliente(tmp_path, libros, monkeypatch):
    monkeypatch.setenv(dependencias.VARIABLE_RUTA, str(tmp_path / "bitacora.db"))
    monkeypatch.setenv(dependencias.VARIABLE_INQUILINO, INQUILINO)
    app.dependency_overrides[dependencias.fuente_actual] = lambda: libros
    with TestClient(app) as cliente:
        yield cliente
    app.dependency_overrides.clear()


def archivos_de(lote, cuantos=None):
    comprobantes = lote.comprobantes[:cuantos] if cuantos else lote.comprobantes
    return [
        ("archivos", (f"{c.uuid}.xml", c.a_xml().encode("utf-8"), "application/xml"))
        for c in comprobantes
    ]


# --------------------------------------------------------------------------- #
# Salud
# --------------------------------------------------------------------------- #


def test_salud_reporta_cadena_vacia(cliente):
    cuerpo = cliente.get("/salud").json()
    assert cuerpo["estado"] == "vivo"
    assert cuerpo["altura"] == 0
    assert len(cuerpo["punta"]) == 64


# --------------------------------------------------------------------------- #
# Ingesta
# --------------------------------------------------------------------------- #


def test_la_ingesta_audita_y_encadena_el_lote(cliente, lote):
    respuesta = cliente.post("/ingesta", files=archivos_de(lote))
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()

    assert cuerpo["auditados"] == 6
    assert cuerpo["rechazados"] == 0
    assert cuerpo["altura"] == 6
    assert [r["posicion"] for r in cuerpo["registros"]] == [0, 1, 2, 3, 4, 5]

    verificacion = cliente.get("/bitacora/verificacion").json()
    assert verificacion["integra"] is True
    assert verificacion["recalculados"] == 6


def test_la_ingesta_encuentra_las_desviaciones_plantadas(cliente, lote, libros):
    cuerpo = cliente.post("/ingesta", files=archivos_de(lote)).json()

    por_uuid = {r["uuid"]: r for r in cuerpo["registros"]}
    esperados = {d.uuid: d.clase for d in libros.desviaciones}
    assert esperados, "el escenario debe traer desviaciones o no prueba nada"

    for uuid, clase in esperados.items():
        assert por_uuid[uuid]["veredicto"] == clase
    assert cuerpo["hallazgos"] == len(esperados)

    limpios = [r for r in cuerpo["registros"] if r["uuid"] not in esperados]
    assert all(r["veredicto"] == "respaldado" for r in limpios)


def test_el_expediente_declara_de_donde_salieron_los_libros(cliente, lote):
    """Un financiador tiene derecho a saber si audita contabilidad o una demo."""
    cuerpo = cliente.post("/ingesta", files=archivos_de(lote, 1)).json()
    assert "NO son libros reales" in cuerpo["fuente_de_libros"]


def test_un_archivo_corrupto_no_tumba_el_lote(cliente, lote):
    archivos = archivos_de(lote, 3)
    archivos.insert(1, ("archivos", ("roto.xml", b"<no-es-cfdi/>", "application/xml")))

    cuerpo = cliente.post("/ingesta", files=archivos).json()

    assert cuerpo["auditados"] == 3
    assert cuerpo["rechazados"] == 1
    assert cuerpo["fallas"][0]["archivo"] == "roto.xml"
    assert cuerpo["fallas"][0]["motivo"] == "no_es_cfdi"


def test_la_falla_dice_cual_archivo(cliente, lote):
    """Un lote de 200 con uno malo tiene que decir cuál, o no se puede corregir."""
    archivos = archivos_de(lote, 2)
    archivos.append(("archivos", ("mal_formado.xml", b"<cfdi:Comprobante", "application/xml")))

    cuerpo = cliente.post("/ingesta", files=archivos).json()
    assert cuerpo["fallas"][0]["archivo"] == "mal_formado.xml"
    assert cuerpo["fallas"][0]["motivo"] == "xml_mal_formado"
    assert cuerpo["fallas"][0]["detalle"]


def test_un_lote_vacio_se_rechaza(cliente):
    assert cliente.post("/ingesta", files=[]).status_code in (400, 422)


def test_un_lote_demasiado_grande_se_rechaza(cliente, lote, monkeypatch):
    """Sin tope, la ingesta es una negación de servicio de una sola petición."""
    from agente_cfdi.api import app as modulo

    monkeypatch.setattr(modulo, "MAXIMO_ARCHIVOS", 2)
    respuesta = cliente.post("/ingesta", files=archivos_de(lote, 5))
    assert respuesta.status_code == 413


def test_los_libros_inalcanzables_dan_503_y_no_sin_respaldo(cliente, lote):
    """Una caída de red no se reporta al financiador como libros inconsistentes."""
    from agente_cfdi.fuentes.protocolo import ErrorDeFuente

    class Caida:
        descripcion = "fuente caída"

        def movimientos(self, **_):
            raise ErrorDeFuente("CØRD Fiscal no respondió")

    app.dependency_overrides[dependencias.fuente_actual] = lambda: Caida()
    respuesta = cliente.post("/ingesta", files=archivos_de(lote, 2))

    assert respuesta.status_code == 503
    assert "libros" in respuesta.json()["detail"]
    # Y no se escribió nada: no hay veredictos que no se pudieron emitir.
    assert cliente.get("/salud").json()["altura"] == 0


def test_reauditar_conserva_ambas_auditorias_en_la_cadena(cliente, lote):
    """Los libros cambian; reauditar es legítimo y la cadena guarda la historia."""
    cliente.post("/ingesta", files=archivos_de(lote, 2))
    cuerpo = cliente.post("/ingesta", files=archivos_de(lote, 2)).json()

    assert cuerpo["altura"] == 4
    assert cliente.get("/bitacora/verificacion").json()["recalculados"] == 4


def test_el_mismo_folio_dos_veces_en_un_lote_se_rechaza(cliente, lote):
    """El escenario de fraude no debe entrar en silencio.

    El mismo folio dos veces en un solo envío no es un caso legítimo: o es un
    error de quien armó el lote, o es meter la misma cuenta por cobrar dos veces.
    """
    archivos = archivos_de(lote, 3)
    archivos.append(archivos[0])  # el mismo CFDI otra vez

    cuerpo = cliente.post("/ingesta", files=archivos).json()

    assert cuerpo["auditados"] == 3
    assert cuerpo["rechazados"] == 1
    falla = cuerpo["fallas"][0]
    assert falla["motivo"] == "uuid_duplicado_en_el_lote"
    assert falla["uuid"] == lote.comprobantes[0].uuid
    # Y solo se escribió un veredicto para ese folio.
    assert sum(1 for r in cuerpo["registros"] if r["uuid"] == falla["uuid"]) == 1


def test_el_mismo_folio_en_lotes_distintos_si_se_admite(cliente, lote):
    """Reauditar después es legítimo; lo que no vale es duplicarlo dentro de un envío."""
    primero = cliente.post("/ingesta", files=archivos_de(lote, 2)).json()
    segundo = cliente.post("/ingesta", files=archivos_de(lote, 2)).json()

    assert primero["rechazados"] == 0
    assert segundo["rechazados"] == 0
    assert segundo["altura"] == 4


# --------------------------------------------------------------------------- #
# Cesión
# --------------------------------------------------------------------------- #


def _ceder(cliente, comprobante, financiador):
    return cliente.post(
        "/cesiones",
        json={
            "uuid": comprobante.uuid,
            "financiador": financiador,
            "total": str(comprobante.total),
            "moneda": "MXN",
        },
    )


def test_la_primera_cesion_se_acepta(cliente, lote):
    cliente.post("/ingesta", files=archivos_de(lote))
    respuesta = _ceder(cliente, lote.comprobantes[0], "Banco Norte")

    assert respuesta.status_code == 201
    assert respuesta.json()["aceptada"] is True


def test_la_segunda_cesion_a_otro_financiador_se_rechaza_con_409(cliente, lote):
    """El fraude que el producto existe para prevenir."""
    cliente.post("/ingesta", files=archivos_de(lote))
    comprobante = lote.comprobantes[0]

    primera = _ceder(cliente, comprobante, "Banco Norte")
    segunda = _ceder(cliente, comprobante, "Factor Sur")

    assert segunda.status_code == 409
    cuerpo = segunda.json()
    assert cuerpo["aceptada"] is False
    assert cuerpo["posicion_de_la_cesion_previa"] == primera.json()["posicion"]


def test_el_reintento_del_mismo_financiador_es_idempotente(cliente, lote):
    """Un reintento de red no es fraude.

    El cliente cuya petición expiró no puede distinguir «no llegó» de «llegó y
    se perdió la respuesta». Si el reintento devolviera 409, un financiador
    honesto leería que cometió doble cesión.
    """
    cliente.post("/ingesta", files=archivos_de(lote))
    comprobante = lote.comprobantes[0]

    primera = _ceder(cliente, comprobante, "Banco Norte")
    reintento = _ceder(cliente, comprobante, "Banco Norte")

    assert primera.status_code == 201
    assert reintento.status_code == 200
    assert reintento.json()["aceptada"] is True
    assert reintento.json()["repetida"] is True
    assert reintento.json()["posicion"] == primera.json()["posicion"]


def test_el_reintento_no_infla_la_cadena(cliente, lote):
    """Un evento por cada paquete perdido llenaría la bitácora de ruido."""
    cliente.post("/ingesta", files=archivos_de(lote))
    altura_antes = cliente.get("/salud").json()["altura"]

    comprobante = lote.comprobantes[0]
    _ceder(cliente, comprobante, "Banco Norte")
    altura_con_cesion = cliente.get("/salud").json()["altura"]
    for _ in range(5):
        _ceder(cliente, comprobante, "Banco Norte")

    assert altura_con_cesion == altura_antes + 1
    assert cliente.get("/salud").json()["altura"] == altura_con_cesion


def test_el_intento_rechazado_si_queda_escrito(cliente, lote):
    cliente.post("/ingesta", files=archivos_de(lote))
    comprobante = lote.comprobantes[0]

    _ceder(cliente, comprobante, "Banco Norte")
    altura = cliente.get("/salud").json()["altura"]
    _ceder(cliente, comprobante, "Factor Sur")

    assert cliente.get("/salud").json()["altura"] == altura + 1
    assert cliente.get("/bitacora/verificacion").json()["integra"] is True


def test_no_se_puede_ceder_algo_que_no_fue_auditado(cliente, lote):
    """El expediente que recibiría el financiador estaría vacío."""
    respuesta = _ceder(cliente, lote.comprobantes[0], "Banco Norte")
    assert respuesta.status_code == 409
    assert "no ha sido auditado" in respuesta.json()["detail"]


def test_no_se_puede_ceder_por_un_importe_distinto_al_del_cfdi(cliente, lote):
    cliente.post("/ingesta", files=archivos_de(lote))
    comprobante = lote.comprobantes[0]

    respuesta = cliente.post(
        "/cesiones",
        json={
            "uuid": comprobante.uuid,
            "financiador": "Banco Norte",
            "total": str(comprobante.total + Decimal("1000.00")),
            "moneda": "MXN",
        },
    )
    assert respuesta.status_code == 409
    assert "no coincide" in respuesta.json()["detail"]


def test_ceder_un_folio_con_hallazgos_se_permite_pero_se_advierte(cliente, lote, libros):
    """Financiar cartera con riesgo es decisión del financiador; no enterarse, no.

    Bloquear la cesión sería tomar por él una decisión comercial que es suya.
    Devolver un 201 limpio sería dejar que se entere al ir a cobrar.
    """
    cliente.post("/ingesta", files=archivos_de(lote))
    sin_respaldo = next(d.uuid for d in libros.desviaciones if d.clase == "sin_respaldo")
    comprobante = next(c for c in lote.comprobantes if c.uuid == sin_respaldo)

    respuesta = _ceder(cliente, comprobante, "Banco Norte")

    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["aceptada"] is True
    assert cuerpo["veredicto"] == "sin_respaldo"
    assert "no registra ingreso alguno" in cuerpo["advertencia"]


def test_ceder_un_folio_respaldado_no_trae_advertencia(cliente, lote, libros):
    cliente.post("/ingesta", files=archivos_de(lote))
    con_hallazgo = {d.uuid for d in libros.desviaciones}
    limpio = next(c for c in lote.comprobantes if c.uuid not in con_hallazgo)

    cuerpo = _ceder(cliente, limpio, "Banco Norte").json()
    assert cuerpo["veredicto"] == "respaldado"
    assert cuerpo["advertencia"] is None


def test_folios_distintos_se_ceden_sin_estorbarse(cliente, lote):
    cliente.post("/ingesta", files=archivos_de(lote))
    assert _ceder(cliente, lote.comprobantes[0], "Banco Norte").status_code == 201
    assert _ceder(cliente, lote.comprobantes[1], "Factor Sur").status_code == 201


# --------------------------------------------------------------------------- #
# El dinero no viaja como número JSON
# --------------------------------------------------------------------------- #


def test_un_importe_como_numero_json_se_rechaza(cliente, lote):
    """`142878.90` no es representable en punto flotante binario.

    Aceptarlo firmaría en la bitácora un importe que nadie escribió.
    """
    cliente.post("/ingesta", files=archivos_de(lote))
    comprobante = lote.comprobantes[0]

    respuesta = cliente.post(
        "/cesiones",
        json={
            "uuid": comprobante.uuid,
            "financiador": "Banco Norte",
            "total": float(comprobante.total),
            "moneda": "MXN",
        },
    )
    assert respuesta.status_code == 422
    assert "punto flotante" in str(respuesta.json())


def test_un_importe_con_tres_decimales_se_rechaza(cliente, lote):
    cliente.post("/ingesta", files=archivos_de(lote))
    respuesta = cliente.post(
        "/cesiones",
        json={
            "uuid": lote.comprobantes[0].uuid,
            "financiador": "Banco Norte",
            "total": "100.123",
            "moneda": "MXN",
        },
    )
    assert respuesta.status_code == 422


def test_una_moneda_no_soportada_se_rechaza(cliente, lote):
    """La escala del importe no se puede adivinar: el yen no tiene decimales."""
    cliente.post("/ingesta", files=archivos_de(lote))
    respuesta = cliente.post(
        "/cesiones",
        json={
            "uuid": lote.comprobantes[0].uuid,
            "financiador": "Banco Norte",
            "total": "100.00",
            "moneda": "JPY",
        },
    )
    assert respuesta.status_code == 422


# --------------------------------------------------------------------------- #
# Consulta de estado
# --------------------------------------------------------------------------- #


def test_el_estado_dice_que_esta_cedido_pero_no_a_quien(cliente, lote):
    """La identidad del financiador que lo tiene no es asunto de un tercero."""
    cliente.post("/ingesta", files=archivos_de(lote))
    comprobante = lote.comprobantes[0]
    _ceder(cliente, comprobante, "Banco Norte")

    cuerpo = cliente.get(f"/cesiones/{comprobante.uuid}").json()

    assert cuerpo["cedida"] is True
    assert cuerpo["auditada"] is True
    assert "Banco Norte" not in str(cuerpo)


def test_el_estado_de_un_folio_libre(cliente, lote):
    cliente.post("/ingesta", files=archivos_de(lote))
    cuerpo = cliente.get(f"/cesiones/{lote.comprobantes[0].uuid}").json()
    assert cuerpo["cedida"] is False
    assert cuerpo["auditada"] is True


def test_el_estado_de_un_folio_desconocido(cliente):
    cuerpo = cliente.get("/cesiones/9F2C1A88-FB09-47F8-B5F9-6DD1C6889D8C").json()
    assert cuerpo["cedida"] is False
    assert cuerpo["auditada"] is False


# --------------------------------------------------------------------------- #
# El inquilino no lo elige quien llama
# --------------------------------------------------------------------------- #


def test_el_inquilino_no_se_puede_cambiar_por_encabezado(cliente, lote):
    """Si se pudiera, cualquiera escribiría en la cadena de cualquiera."""
    cliente.post("/ingesta", files=archivos_de(lote, 2))
    cuerpo = cliente.get("/salud", headers={"X-Inquilino": "OTRO000000XX0"}).json()
    assert cuerpo["inquilino"] == INQUILINO
    assert cuerpo["altura"] == 2


# --------------------------------------------------------------------------- #
# La manipulación se detecta a través de la API
# --------------------------------------------------------------------------- #


def test_alterar_la_base_por_debajo_se_detecta_en_la_verificacion(cliente, lote, tmp_path):
    """El escenario de la demo, extremo a extremo."""
    import sqlite3

    cliente.post("/ingesta", files=archivos_de(lote))
    assert cliente.get("/bitacora/verificacion").json()["integra"] is True

    conexion = sqlite3.connect(tmp_path / "bitacora.db")
    original = conexion.execute(
        "SELECT canonico FROM bitacora_registros WHERE posicion = 2"
    ).fetchone()[0]
    conexion.execute(
        "UPDATE bitacora_registros SET canonico = ? WHERE posicion = 2",
        (bytes(original).replace(b"|sMXN|", b"|sUSD|"),),
    )
    conexion.commit()
    conexion.close()

    cuerpo = cliente.get("/bitacora/verificacion").json()
    assert cuerpo["integra"] is False
    assert cuerpo["posicion_del_problema"] == 2
