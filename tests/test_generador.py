"""Pruebas del generador sintético (tareas 1.14, 1.15 y 1.16).

**Alcance, dicho de frente:** estas pruebas verifican las propiedades
estructurales del esquema de CFDI 4.0 —patrones, atributos obligatorios, valores
de catálogo, aritmética de importes— pero **no corren una validación XSD real**
contra el esquema publicado por el SAT. Eso exige `lxml` y descargar el esquema,
y queda anotado como hueco conocido en `docs/datos-sinteticos.md`.
"""

import re
from collections import Counter
from decimal import Decimal
from xml.etree import ElementTree as ET

import pytest

from agente_cfdi.sintetico import catalogos as cat
from agente_cfdi.sintetico.generador import (
    NS_CFDI,
    NS_TFD,
    VarianteXml,
    generar_lote,
)
from agente_cfdi.sintetico.rfc import (
    FECHA_IMPOSIBLE,
    RFC_PUBLICO_EN_GENERAL,
    es_estructuralmente_valido,
    es_sintetico,
    rfc_persona_fisica,
    rfc_persona_moral,
)

PATRON_UUID = re.compile(
    r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$"
)


@pytest.fixture(scope="module")
def lote():
    return generar_lote(cantidad=40, semilla=20260814)


def raiz(comprobante):
    return ET.fromstring(comprobante.a_xml())


def timbre(arbol):
    return arbol.find(f".//{{{NS_TFD}}}TimbreFiscalDigital")


# --------------------------------------------------------------------------- #
# 1.14 — validez estructural contra CFDI 4.0
# --------------------------------------------------------------------------- #


def test_todo_comprobante_es_xml_bien_formado(lote):
    for comprobante in lote.comprobantes:
        raiz(comprobante)  # ET levanta ParseError si no lo es


def test_la_raiz_es_un_comprobante_cfdi_4(lote):
    for comprobante in lote.comprobantes:
        arbol = raiz(comprobante)
        assert arbol.tag == f"{{{NS_CFDI}}}Comprobante"
        assert arbol.get("Version") == "4.0"


@pytest.mark.parametrize(
    "atributo",
    [
        "Version", "Fecha", "Sello", "NoCertificado", "Certificado", "SubTotal",
        "Moneda", "Total", "TipoDeComprobante", "Exportacion", "LugarExpedicion",
    ],
)
def test_atributos_obligatorios_del_comprobante(lote, atributo):
    """`Exportacion` es de las que solo existen en 4.0: si falta, es un 3.3 disfrazado."""
    for comprobante in lote.comprobantes:
        assert raiz(comprobante).get(atributo) is not None, atributo


@pytest.mark.parametrize(
    "atributo", ["Rfc", "Nombre", "DomicilioFiscalReceptor", "RegimenFiscalReceptor", "UsoCFDI"]
)
def test_el_receptor_lleva_los_campos_que_4_0_agrego(lote, atributo):
    for comprobante in lote.comprobantes:
        receptor = raiz(comprobante).find(f"{{{NS_CFDI}}}Receptor")
        assert receptor is not None and receptor.get(atributo) is not None, atributo


def test_los_valores_vienen_de_catalogos_reales(lote):
    for comprobante in lote.comprobantes:
        arbol = raiz(comprobante)
        receptor = arbol.find(f"{{{NS_CFDI}}}Receptor")
        emisor = arbol.find(f"{{{NS_CFDI}}}Emisor")
        assert receptor.get("UsoCFDI") in cat.USOS_CFDI_EMPRESARIALES
        assert emisor.get("RegimenFiscal") in cat.REGIMENES_PERSONA_MORAL
        assert arbol.get("Moneda") == cat.MONEDA_PESOS
        assert arbol.get("TipoDeComprobante") == cat.TIPO_COMPROBANTE_INGRESO
        assert arbol.get("LugarExpedicion") in cat.CODIGOS_POSTALES


def test_ppd_obliga_forma_de_pago_por_definir(lote):
    """Regla del SAT: al timbrar una venta a crédito no se sabe cómo se cobrará."""
    for comprobante in lote.comprobantes:
        arbol = raiz(comprobante)
        if arbol.get("MetodoPago") == cat.METODO_PAGO_DIFERIDO:
            assert arbol.get("FormaPago") == cat.FORMA_PAGO_POR_DEFINIR


def test_el_timbre_existe_y_su_uuid_esta_bien_formado(lote):
    for comprobante in lote.comprobantes:
        tfd = timbre(raiz(comprobante))
        assert tfd is not None
        assert tfd.get("Version") == "1.1"
        assert PATRON_UUID.match(tfd.get("UUID"))


def test_el_timbrado_nunca_es_anterior_a_la_emision(lote):
    for comprobante in lote.comprobantes:
        assert comprobante.fecha_timbrado >= comprobante.fecha_emision


def test_la_aritmetica_de_importes_cuadra(lote):
    """Un total que no cuadra con sus conceptos delata un CFDI falso a simple vista."""
    for comprobante in lote.comprobantes:
        arbol = raiz(comprobante)
        conceptos = arbol.findall(f".//{{{NS_CFDI}}}Concepto")
        assert conceptos

        subtotal = Decimal("0.00")
        for nodo in conceptos:
            importe = Decimal(nodo.get("Importe"))
            assert importe == Decimal(nodo.get("Cantidad")) * Decimal(nodo.get("ValorUnitario"))
            subtotal += importe

        assert Decimal(arbol.get("SubTotal")) == subtotal
        iva = Decimal(
            arbol.find(f"{{{NS_CFDI}}}Impuestos").get("TotalImpuestosTrasladados")
        )
        assert Decimal(arbol.get("Total")) == subtotal + iva


def test_el_concepto_declara_objeto_de_impuesto(lote):
    """`ObjetoImp` es obligatorio en 4.0 y no existía en 3.3."""
    for comprobante in lote.comprobantes:
        for nodo in raiz(comprobante).findall(f".//{{{NS_CFDI}}}Concepto"):
            assert nodo.get("ObjetoImp") == cat.OBJETO_IMPUESTO_SI


def test_el_emisor_no_se_factura_a_si_mismo(lote):
    for comprobante in lote.comprobantes:
        assert comprobante.emisor.rfc != comprobante.receptor.rfc
        assert comprobante.emisor.nombre != comprobante.receptor.nombre


# --------------------------------------------------------------------------- #
# Variantes estructurales — lo que el lector tiene que soportar (para 1.8)
# --------------------------------------------------------------------------- #


def test_el_lote_ejercita_las_tres_variantes(lote):
    presentes = {c.variante for c in lote.comprobantes}
    assert presentes == set(VarianteXml)


def test_las_tres_variantes_producen_el_mismo_comprobante_para_un_lector_con_espacios_de_nombres():
    """Textos distintos, árbol equivalente. Es el punto de tener variantes."""
    lote = generar_lote(cantidad=1, semilla=3)
    base = lote.comprobantes[0]

    lecturas = []
    for variante in VarianteXml:
        from dataclasses import replace

        arbol = ET.fromstring(replace(base, variante=variante).a_xml())
        lecturas.append(
            (
                arbol.get("Total"),
                arbol.find(f"{{{NS_CFDI}}}Emisor").get("Rfc"),
                arbol.find(f"{{{NS_CFDI}}}Receptor").get("Rfc"),
                timbre(arbol).get("UUID"),
            )
        )
    assert len(set(lecturas)) == 1


def test_la_variante_con_addenda_lleva_elementos_ajenos():
    """El lector debe ignorar la addenda sin quejarse, no tropezar con ella."""
    from dataclasses import replace

    base = generar_lote(cantidad=1, semilla=5).comprobantes[0]
    arbol = ET.fromstring(replace(base, variante=VarianteXml.PREFIJO_ALTERNO).a_xml())
    addenda = arbol.find(f"{{{NS_CFDI}}}Addenda")
    assert addenda is not None and len(addenda) > 0


# --------------------------------------------------------------------------- #
# 1.15 — los RFC no pueden ser de nadie
# --------------------------------------------------------------------------- #


def test_todos_los_rfc_del_lote_son_sinteticos(lote):
    for comprobante in lote.comprobantes:
        for parte in (comprobante.emisor, comprobante.receptor):
            assert es_estructuralmente_valido(parte.rfc), parte.rfc
            assert es_sintetico(parte.rfc), f"{parte.rfc} podría ser de una persona real"


def test_la_marca_de_seguridad_es_la_fecha_imposible():
    import random

    rng = random.Random(1)
    for _ in range(500):
        for generado in (rfc_persona_moral(rng), rfc_persona_fisica(rng)):
            assert es_estructuralmente_valido(generado)
            assert FECHA_IMPOSIBLE in generado
            assert es_sintetico(generado)


def test_persona_moral_y_fisica_tienen_las_longitudes_del_sat():
    import random

    rng = random.Random(2)
    assert len(rfc_persona_moral(rng)) == 12
    assert len(rfc_persona_fisica(rng)) == 13


@pytest.mark.parametrize(
    "rfc",
    [
        "AAA850612QW3",   # fecha real: podría estar asignado
        "PEGJ900101HN4",  # persona física con fecha real
        "MELM8506129K1",
    ],
)
def test_un_rfc_con_fecha_real_no_pasa_por_sintetico(rfc):
    """La prueba que le da sentido a la anterior: la marca discrimina de verdad."""
    assert es_estructuralmente_valido(rfc)
    assert not es_sintetico(rfc)


def test_los_genericos_del_sat_cuentan_como_seguros():
    assert es_sintetico(RFC_PUBLICO_EN_GENERAL)


@pytest.mark.parametrize("basura", ["", "AB", "AAA0000001", "aaa000000d18", "AAA00000#D18"])
def test_rfc_malformado_no_pasa_ninguna_validacion(basura):
    assert not es_estructuralmente_valido(basura)
    assert not es_sintetico(basura)


# --------------------------------------------------------------------------- #
# 1.16 — distribuciones creíbles y el escenario de fraude
# --------------------------------------------------------------------------- #


def test_los_montos_tienen_dispersion(lote):
    totales = [c.total for c in lote.comprobantes]
    assert len(set(totales)) > len(totales) * 0.9, "montos repetidos: se ve sintético"
    assert max(totales) / min(totales) > 3, "sin cola larga no parece cartera real"


def test_los_plazos_de_cobro_se_reparten(lote):
    plazos = Counter(c.dias_credito for c in lote.comprobantes)
    assert set(plazos) <= {30, 45, 60, 90}
    assert len(plazos) >= 3, "todos los clientes con el mismo plazo no es realista"


def test_las_fechas_se_reparten_en_una_ventana(lote):
    fechas = sorted(c.fecha_emision for c in lote.comprobantes)
    assert (fechas[-1] - fechas[0]).days > 30
    assert len({f.date() for f in fechas}) > 10, "todo emitido el mismo día"


def test_la_pyme_le_factura_a_clientes_recurrentes(lote):
    clientes = Counter(c.receptor.rfc for c in lote.comprobantes)
    assert 2 <= len(clientes) <= 6
    assert max(clientes.values()) > 1, "ningún cliente repite; no es una cartera"


def test_hay_un_solo_emisor_por_lote(lote):
    assert len({c.emisor.rfc for c in lote.comprobantes}) == 1


def test_el_lote_con_fraude_planta_un_uuid_repetido():
    lote = generar_lote(cantidad=15, semilla=99, con_cesion_duplicada=True)
    assert lote.uuid_duplicado is not None

    apariciones = Counter(c.uuid for c in lote.comprobantes)
    assert apariciones[lote.uuid_duplicado] == 2
    assert [u for u, n in apariciones.items() if n > 1] == [lote.uuid_duplicado]


def test_el_duplicado_llega_con_otra_forma_de_xml():
    """Si la detección comparara bytes del archivo, esto se le escaparía."""
    lote = generar_lote(cantidad=15, semilla=99, con_cesion_duplicada=True)
    copias = [c for c in lote.comprobantes if c.uuid == lote.uuid_duplicado]
    assert copias[0].variante is not copias[1].variante
    assert copias[0].a_xml() != copias[1].a_xml()
    assert copias[0].total == copias[1].total


def test_sin_fraude_no_hay_uuid_repetido(lote):
    assert lote.uuid_duplicado is None
    apariciones = Counter(c.uuid for c in lote.comprobantes)
    assert max(apariciones.values()) == 1


# --------------------------------------------------------------------------- #
# Reproducibilidad — de esto depende que la demo del video se pueda repetir
# --------------------------------------------------------------------------- #


def test_la_misma_semilla_produce_el_mismo_lote_byte_por_byte():
    uno = generar_lote(cantidad=10, semilla=4242, con_cesion_duplicada=True)
    otro = generar_lote(cantidad=10, semilla=4242, con_cesion_duplicada=True)
    assert [c.a_xml() for c in uno.comprobantes] == [c.a_xml() for c in otro.comprobantes]
    assert uno.uuid_duplicado == otro.uuid_duplicado


def test_semillas_distintas_producen_lotes_distintos():
    uno = generar_lote(cantidad=10, semilla=1)
    otro = generar_lote(cantidad=10, semilla=2)
    assert {c.uuid for c in uno.comprobantes} != {c.uuid for c in otro.comprobantes}


@pytest.mark.parametrize(("cantidad", "fraude"), [(0, False), (1, True)])
def test_lotes_imposibles_se_rechazan(cantidad, fraude):
    with pytest.raises(ValueError):
        generar_lote(cantidad=cantidad, con_cesion_duplicada=fraude)
