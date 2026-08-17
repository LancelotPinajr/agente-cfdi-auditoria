"""Pruebas del lector de CFDI (tareas 1.8 y 1.9).

La 1.8 pide extraer UUID, RFC emisor, RFC receptor, total, fecha y moneda de al
menos 3 XML de estructura distinta. La 1.9 pide que un XML malformado, uno sin
UUID y uno que no es CFDI den error descriptivo y no una excepción cruda.
"""

from dataclasses import replace
from decimal import Decimal

import pytest

from agente_cfdi.cfdi.errores import CFDIInvalido, Motivo
from agente_cfdi.cfdi.lector import (
    TAMANO_MAXIMO_BYTES,
    leer_cfdi,
    leer_lote,
)
from agente_cfdi.sintetico.generador import VarianteXml, generar_lote

TODAS_LAS_VARIANTES = tuple(VarianteXml)


@pytest.fixture(scope="module")
def lote():
    return generar_lote(cantidad=30, semilla=20260814)


def un_comprobante(variante=VarianteXml.PREFIJO_ESTANDAR, semilla=11):
    base = generar_lote(cantidad=1, semilla=semilla).comprobantes[0]
    return replace(base, variante=variante)


# --------------------------------------------------------------------------- #
# 1.8 — extracción de los seis campos, en las tres estructuras
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("variante", TODAS_LAS_VARIANTES, ids=lambda v: v.value)
def test_extrae_los_seis_campos_del_criterio(variante):
    original = un_comprobante(variante)
    leido = leer_cfdi(original.a_xml())

    assert leido.uuid == original.uuid
    assert leido.rfc_emisor == original.emisor.rfc
    assert leido.rfc_receptor == original.receptor.rfc
    assert leido.total == original.total
    assert leido.fecha_emision == original.fecha_emision
    assert leido.moneda == "MXN"


def test_las_tres_estructuras_dan_exactamente_la_misma_lectura():
    """El punto de la tarea: el texto cambia, el dato leído no."""
    lecturas = {leer_cfdi(un_comprobante(v).a_xml()) for v in TODAS_LAS_VARIANTES}
    assert len(lecturas) == 1


def test_lee_el_lote_completo_sin_rechazos(lote):
    documentos = {f"cfdi_{i}.xml": c.a_xml() for i, c in enumerate(lote.comprobantes)}
    resultado = leer_lote(documentos)

    assert not resultado.hubo_rechazos
    assert len(resultado.leidos) == len(lote.comprobantes)
    assert {c.uuid for c in resultado.leidos} == {c.uuid for c in lote.comprobantes}


def test_acepta_bytes_ademas_de_texto():
    comprobante = un_comprobante()
    assert leer_cfdi(comprobante.a_xml().encode("utf-8")) == leer_cfdi(comprobante.a_xml())


def test_lee_los_datos_de_apoyo_que_el_expediente_necesita():
    original = un_comprobante()
    leido = leer_cfdi(original.a_xml())

    assert leido.version == "4.0"
    assert leido.tipo_comprobante == "I"
    assert leido.metodo_pago == "PPD"
    assert leido.forma_pago == "99"
    assert leido.serie == original.serie
    assert leido.folio == original.folio
    assert leido.nombre_emisor == original.emisor.nombre


def test_la_fecha_declarada_conserva_el_reloj_de_pared():
    """Un CFDI declara hora local sin zona. Inventarle una sería fabricar dato."""
    leido = leer_cfdi(un_comprobante().a_xml())
    assert leido.fecha_emision.tzinfo is None
    assert leido.fecha_emision_declarada == leido.fecha_emision.strftime("%Y-%m-%dT%H:%M:%S")


def test_el_uuid_se_normaliza_a_mayusculas():
    """Un PAC que timbra en minúsculas no puede producir dos folios distintos.

    Si el UUID entrara con el case original, el mismo folio fiscal daría dos
    hashes y la cesión duplicada pasaría de largo con solo cambiar mayúsculas.
    """
    original = un_comprobante()
    xml = original.a_xml()
    en_minusculas = xml.replace(
        f'UUID="{original.uuid}"', f'UUID="{original.uuid.lower()}"'
    )
    assert en_minusculas != xml
    assert leer_cfdi(en_minusculas).uuid == original.uuid


def test_el_rfc_se_normaliza_a_mayusculas():
    original = un_comprobante()
    xml = original.a_xml().replace(
        f'Rfc="{original.emisor.rfc}"', f'Rfc="{original.emisor.rfc.lower()}"'
    )
    assert leer_cfdi(xml).rfc_emisor == original.emisor.rfc


def test_ignora_la_addenda_sin_quejarse():
    """La addenda lleva elementos de un espacio ajeno; no es asunto del lector."""
    con_addenda = leer_cfdi(un_comprobante(VarianteXml.PREFIJO_ALTERNO).a_xml())
    assert con_addenda.uuid


# --------------------------------------------------------------------------- #
# 1.9 — rechazo con error descriptivo
# --------------------------------------------------------------------------- #


def test_xml_malformado():
    xml = un_comprobante().a_xml()[: len(un_comprobante().a_xml()) // 2]
    with pytest.raises(CFDIInvalido) as caso:
        leer_cfdi(xml)
    assert caso.value.motivo is Motivo.XML_MAL_FORMADO
    assert "bien formado" in caso.value.detalle


def test_xml_sin_uuid():
    original = un_comprobante()
    sin_uuid = original.a_xml().replace(f'UUID="{original.uuid}" ', "")
    with pytest.raises(CFDIInvalido) as caso:
        leer_cfdi(sin_uuid)
    assert caso.value.motivo is Motivo.UUID_AUSENTE


def test_xml_que_no_es_cfdi():
    with pytest.raises(CFDIInvalido) as caso:
        leer_cfdi("<pedido xmlns='urn:erp:pedidos'><linea sku='X'/></pedido>")
    assert caso.value.motivo is Motivo.NO_ES_CFDI
    assert "Comprobante" in caso.value.detalle


def test_un_cfdi_3_3_dice_que_es_3_3_y_no_solo_que_no_sirve():
    """Un mensaje útil ahorra media hora de depuración a quien sube el archivo."""
    viejo = (
        '<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/3" Version="3.3" '
        'Total="100.00" Moneda="MXN"/>'
    )
    with pytest.raises(CFDIInvalido) as caso:
        leer_cfdi(viejo)
    assert caso.value.motivo is Motivo.VERSION_NO_SOPORTADA
    assert "3.3" in caso.value.detalle


def test_cfdi_sin_timbre():
    original = un_comprobante()
    xml = original.a_xml()
    inicio = xml.index("<cfdi:Complemento>")
    fin = xml.index("</cfdi:Complemento>") + len("</cfdi:Complemento>")
    with pytest.raises(CFDIInvalido) as caso:
        leer_cfdi(xml[:inicio] + xml[fin:])
    assert caso.value.motivo is Motivo.SIN_TIMBRE


@pytest.mark.parametrize("vacio", ["", "   ", b"", b"\n"])
def test_documento_vacio(vacio):
    with pytest.raises(CFDIInvalido) as caso:
        leer_cfdi(vacio)
    assert caso.value.motivo is Motivo.XML_MAL_FORMADO


def test_tipo_de_dato_equivocado():
    with pytest.raises(CFDIInvalido) as caso:
        leer_cfdi({"no": "soy xml"})
    assert caso.value.motivo is Motivo.XML_MAL_FORMADO


def test_documento_desmedido():
    with pytest.raises(CFDIInvalido) as caso:
        leer_cfdi(b"<a>" + b"x" * TAMANO_MAXIMO_BYTES + b"</a>")
    assert caso.value.motivo is Motivo.DEMASIADO_GRANDE


@pytest.mark.parametrize(
    ("atributo", "valor", "motivo"),
    [
        ("UUID", "no-es-un-uuid", Motivo.UUID_MAL_FORMADO),
        ("UUID", "ZZZZZZZZ-FB09-47F8-B5F9-6DD1C6889D8C", Motivo.UUID_MAL_FORMADO),
        ("Moneda", "EUR", Motivo.MONEDA_NO_SOPORTADA),
        ("Total", "cien", Motivo.TOTAL_INVALIDO),
        ("Total", "-500.00", Motivo.TOTAL_INVALIDO),
        ("Total", "100.5555", Motivo.TOTAL_INVALIDO),
        ("Total", "NaN", Motivo.TOTAL_INVALIDO),
        ("Fecha", "14/08/2026", Motivo.FECHA_INVALIDA),
        ("Fecha", "2026-08-14T15:30:00-06:00", Motivo.FECHA_INVALIDA),
        ("Fecha", "2026-02-31T10:00:00", Motivo.FECHA_INVALIDA),
        ("Version", "3.3", Motivo.VERSION_NO_SOPORTADA),
    ],
)
def test_atributos_invalidos_dan_el_motivo_correcto(atributo, valor, motivo):
    original = un_comprobante()
    xml = original.a_xml()
    viejo = {
        "UUID": f'UUID="{original.uuid}"',
        "Moneda": 'Moneda="MXN"',
        "Total": f'Total="{original.total}"',
        "Fecha": f'Fecha="{original.fecha_emision.strftime("%Y-%m-%dT%H:%M:%S")}"',
        "Version": 'Version="4.0"',
    }[atributo]
    assert viejo in xml, viejo
    with pytest.raises(CFDIInvalido) as caso:
        leer_cfdi(xml.replace(viejo, f'{atributo}="{valor}"', 1))
    assert caso.value.motivo is motivo


@pytest.mark.parametrize("rfc_malo", ["", "AB", "AAA0000001", "ÑÑÑ000000###"])
def test_rfc_malformado(rfc_malo):
    original = un_comprobante()
    xml = original.a_xml().replace(
        f'Rfc="{original.emisor.rfc}"', f'Rfc="{rfc_malo}"', 1
    )
    with pytest.raises(CFDIInvalido) as caso:
        leer_cfdi(xml)
    assert caso.value.motivo is Motivo.RFC_MAL_FORMADO


@pytest.mark.parametrize("etiqueta", ["Emisor", "Receptor"])
def test_falta_una_de_las_partes(etiqueta):
    original = un_comprobante()
    xml = original.a_xml()
    inicio = xml.index(f"<cfdi:{etiqueta} ")
    fin = xml.index("/>", inicio) + 2
    with pytest.raises(CFDIInvalido) as caso:
        leer_cfdi(xml[:inicio] + xml[fin:])
    assert caso.value.motivo in (Motivo.EMISOR_AUSENTE, Motivo.RECEPTOR_AUSENTE)


def test_el_error_nombra_el_uuid_cuando_ya_se_conoce():
    """«Uno de los 200 no sirve» no le sirve a nadie."""
    original = un_comprobante()
    xml = original.a_xml().replace('Moneda="MXN"', 'Moneda="JPY"', 1)
    with pytest.raises(CFDIInvalido) as caso:
        leer_cfdi(xml)
    assert caso.value.uuid == original.uuid
    assert original.uuid in str(caso.value)


def test_ningun_rechazo_escapa_como_excepcion_cruda():
    """El criterio dice «error descriptivo, no excepción»."""
    basuras = [
        "no soy xml",
        "<sin cerrar>",
        "<a></b>",
        "<?xml version='1.0'?>",
        b"\x00\x01\x02\x03",
        "<cfdi:Comprobante/>",
        '<Comprobante xmlns="http://www.sat.gob.mx/cfd/4"/>',
        "[]",
        "{'json': true}",
    ]
    for basura in basuras:
        with pytest.raises(CFDIInvalido) as caso:
            leer_cfdi(basura)
        assert caso.value.motivo in Motivo
        assert caso.value.detalle, f"sin detalle para {basura!r}"


# --------------------------------------------------------------------------- #
# Seguridad del parser
# --------------------------------------------------------------------------- #


def test_bomba_de_entidades():
    """Diez líneas de DTD bastan para pedir gigabytes con el parser de la stdlib."""
    bomba = """<?xml version="1.0"?>
<!DOCTYPE lolz [
 <!ENTITY lol "lol">
 <!ENTITY lol1 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
 <!ENTITY lol2 "&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;">
 <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
 <!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">
]>
<r>&lol4;</r>"""
    with pytest.raises(CFDIInvalido) as caso:
        leer_cfdi(bomba)
    assert caso.value.motivo is Motivo.DOCUMENTO_PELIGROSO


def test_entidad_externa_no_convierte_al_lector_en_lector_de_archivos():
    xxe = (
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE r [ <!ENTITY secreto SYSTEM "file:///etc/passwd"> ]>\n'
        "<r>&secreto;</r>"
    )
    with pytest.raises(CFDIInvalido) as caso:
        leer_cfdi(xxe)
    assert caso.value.motivo is Motivo.DOCUMENTO_PELIGROSO


def test_un_doctype_inofensivo_tambien_se_rechaza():
    """Un CFDI nunca lleva DTD; no hay expansión que valga la pena permitir."""
    with pytest.raises(CFDIInvalido) as caso:
        leer_cfdi('<?xml version="1.0"?><!DOCTYPE r><r/>')
    assert caso.value.motivo is Motivo.DOCUMENTO_PELIGROSO


# --------------------------------------------------------------------------- #
# Lote: un archivo malo no tumba los demás
# --------------------------------------------------------------------------- #


def test_un_archivo_corrupto_no_tumba_el_lote(lote):
    documentos = {f"cfdi_{i}.xml": c.a_xml() for i, c in enumerate(lote.comprobantes)}
    documentos["truncado.xml"] = "<cfdi:Comprobante"
    documentos["ajeno.xml"] = "<pedido/>"

    resultado = leer_lote(documentos)

    assert len(resultado.leidos) == len(lote.comprobantes)
    assert len(resultado) == len(documentos)
    assert resultado.hubo_rechazos

    por_origen = {f.origen: f.motivo for f in resultado.fallidos}
    assert por_origen == {
        "truncado.xml": Motivo.XML_MAL_FORMADO,
        "ajeno.xml": Motivo.NO_ES_CFDI,
    }


def test_el_lote_vacio_no_es_un_error():
    resultado = leer_lote({})
    assert not resultado.leidos and not resultado.fallidos


def test_el_lote_con_fraude_deja_ver_el_uuid_repetido():
    """El lector no detecta la cesión duplicada — eso es del Sprint 2 — pero
    tampoco la esconde: entrega los dos comprobantes con el mismo UUID."""
    lote = generar_lote(cantidad=12, semilla=99, con_cesion_duplicada=True)
    resultado = leer_lote(
        {f"{i}.xml": c.a_xml() for i, c in enumerate(lote.comprobantes)}
    )
    uuids = [c.uuid for c in resultado.leidos]
    assert uuids.count(lote.uuid_duplicado) == 2


def test_el_total_leido_conserva_la_escala_del_peso():
    leido = leer_cfdi(un_comprobante().a_xml())
    assert leido.total == leido.total.quantize(Decimal("0.01"))
    assert -leido.total.as_tuple().exponent == 2
