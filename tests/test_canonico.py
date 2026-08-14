"""Pruebas de `CORD-CANON-1` (tarea 1.10).

El criterio de aceptación del plan es «mismo registro → misma cadena de bytes,
sin importar orden de campos ni cómo venga el decimal», con `100.5` vs `100.50`
y con acentos. Eso son las tres primeras pruebas; el resto cubre las propiedades
de las que depende que la bitácora sirva de algo.
"""

import unicodedata
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from agente_cfdi.dominio.canonico import (
    Campo,
    ErrorDeCanonicalizacion,
    Esquema,
    Tipo,
    canonicalizar,
)

DEMO = Esquema(
    nombre="demo",
    campos=(
        Campo("uuid", Tipo.CADENA),
        Campo("emisor", Tipo.CADENA),
        Campo("total", Tipo.DECIMAL, escala=2),
        Campo("fecha", Tipo.INSTANTE),
        Campo("posicion", Tipo.ENTERO),
        Campo("cedido", Tipo.BOOLEANO),
        Campo("nota", Tipo.CADENA, opcional=True),
    ),
)

UTC = timezone.utc


def registro(**cambios):
    base = {
        "uuid": "A1B2C3D4-0000-4000-8000-000000000001",
        "emisor": "AAA010101AAA",
        "total": Decimal("1234.50"),
        "fecha": datetime(2026, 8, 14, 15, 30, 0, tzinfo=UTC),
        "posicion": 7,
        "cedido": False,
    }
    base.update(cambios)
    return base


# --------------------------------------------------------------------------- #
# Criterio de aceptación 1.10
# --------------------------------------------------------------------------- #


def test_el_orden_de_las_claves_no_cambia_los_bytes():
    directo = registro()
    invertido = dict(reversed(list(directo.items())))
    assert canonicalizar(directo, DEMO) == canonicalizar(invertido, DEMO)


@pytest.mark.parametrize(
    "valor", [Decimal("100.5"), Decimal("100.50"), Decimal("100.500"), "100.5", "100.50"]
)
def test_el_decimal_se_normaliza_a_la_escala_declarada(valor):
    """`100.5` y `100.50` son el mismo importe y deben dar los mismos bytes."""
    referencia = canonicalizar(registro(total=Decimal("100.50")), DEMO)
    assert canonicalizar(registro(total=valor), DEMO) == referencia


@pytest.mark.parametrize("valor", [100, "100", Decimal("100"), Decimal("1E+2")])
def test_un_entero_en_campo_decimal_toma_la_escala_declarada(valor):
    referencia = canonicalizar(registro(total=Decimal("100.00")), DEMO)
    assert canonicalizar(registro(total=valor), DEMO) == referencia


def test_los_acentos_se_normalizan_a_nfc():
    precompuesto = unicodedata.normalize("NFC", "Peñón Comercializadora")
    descompuesto = unicodedata.normalize("NFD", "Peñón Comercializadora")
    assert precompuesto != descompuesto, "las dos formas deben diferir en bytes"
    assert canonicalizar(registro(emisor=precompuesto), DEMO) == canonicalizar(
        registro(emisor=descompuesto), DEMO
    )


# --------------------------------------------------------------------------- #
# Inyectividad: lo que impide fabricar dos registros con el mismo hash
# --------------------------------------------------------------------------- #


def test_el_contenido_de_un_campo_no_puede_simular_otro_campo():
    """Sin prefijo de longitud, estos dos registros colisionarían."""
    a = registro(uuid="AAA", emisor="BBB")
    b = registro(uuid="AAABBB", emisor="")
    assert canonicalizar(a, DEMO) != canonicalizar(b, DEMO)


def test_un_separador_incrustado_no_rompe_la_codificacion():
    for veneno in ["|", ":", "\x1e", "5:total", '","', "\n", "\\"]:
        assert canonicalizar(registro(emisor=veneno), DEMO) != canonicalizar(
            registro(emisor=""), DEMO
        )


def test_nulo_y_cadena_vacia_son_distinguibles():
    assert canonicalizar(registro(nota=None), DEMO) != canonicalizar(
        registro(nota=""), DEMO
    )


def test_campo_opcional_ausente_equivale_a_nulo_explicito():
    sin_clave = registro()
    con_nulo = registro(nota=None)
    assert canonicalizar(sin_clave, DEMO) == canonicalizar(con_nulo, DEMO)


def test_el_tipo_forma_parte_de_la_codificacion():
    """La cadena '7' y el entero 7 no producen los mismos bytes."""
    esquema_cadena = Esquema("x", (Campo("v", Tipo.CADENA),))
    esquema_entero = Esquema("x", (Campo("v", Tipo.ENTERO),))
    assert canonicalizar({"v": "7"}, esquema_cadena) != canonicalizar(
        {"v": 7}, esquema_entero
    )


def test_dos_esquemas_con_los_mismos_campos_no_colisionan():
    uno = Esquema("cesion", (Campo("v", Tipo.CADENA),))
    otro = Esquema("auditoria", (Campo("v", Tipo.CADENA),))
    assert canonicalizar({"v": "x"}, uno) != canonicalizar({"v": "x"}, otro)


def test_el_prefijo_de_version_esta_en_los_bytes():
    assert canonicalizar(registro(), DEMO).startswith(b"CORD-CANON-1")


# --------------------------------------------------------------------------- #
# Instantes
# --------------------------------------------------------------------------- #


def test_la_zona_horaria_se_normaliza_a_utc():
    utc = datetime(2026, 8, 14, 15, 30, 0, tzinfo=UTC)
    cdmx = datetime(2026, 8, 14, 9, 30, 0, tzinfo=timezone(timedelta(hours=-6)))
    assert canonicalizar(registro(fecha=utc), DEMO) == canonicalizar(
        registro(fecha=cdmx), DEMO
    )


def test_datetime_sin_zona_se_rechaza():
    with pytest.raises(ErrorDeCanonicalizacion, match="zona horaria"):
        canonicalizar(registro(fecha=datetime(2026, 8, 14, 15, 30, 0)), DEMO)


def test_fraccion_de_segundo_se_rechaza_en_vez_de_truncarse():
    con_micros = datetime(2026, 8, 14, 15, 30, 0, 500_000, tzinfo=UTC)
    with pytest.raises(ErrorDeCanonicalizacion, match="fracción"):
        canonicalizar(registro(fecha=con_micros), DEMO)


# --------------------------------------------------------------------------- #
# Decimales: se rechaza, no se redondea
# --------------------------------------------------------------------------- #


def test_mas_precision_que_la_escala_se_rechaza():
    with pytest.raises(ErrorDeCanonicalizacion, match="precisión"):
        canonicalizar(registro(total=Decimal("100.505")), DEMO)


def test_float_se_rechaza():
    with pytest.raises(ErrorDeCanonicalizacion, match="float"):
        canonicalizar(registro(total=100.50), DEMO)


@pytest.mark.parametrize("valor", ["NaN", "Infinity", "-Infinity"])
def test_no_finitos_se_rechazan(valor):
    with pytest.raises(ErrorDeCanonicalizacion, match="finito"):
        canonicalizar(registro(total=Decimal(valor)), DEMO)


def test_cero_negativo_es_el_mismo_importe_que_cero():
    assert canonicalizar(registro(total=Decimal("-0.00")), DEMO) == canonicalizar(
        registro(total=Decimal("0.00")), DEMO
    )


def test_notacion_exponencial_se_normaliza():
    assert canonicalizar(registro(total=Decimal("1E+2")), DEMO) == canonicalizar(
        registro(total=Decimal("100.00")), DEMO
    )


def test_decimal_invalido_da_error_descriptivo():
    with pytest.raises(ErrorDeCanonicalizacion, match="no es un decimal válido"):
        canonicalizar(registro(total="cien pesos"), DEMO)


# --------------------------------------------------------------------------- #
# Estrictez del esquema
# --------------------------------------------------------------------------- #


def test_campo_no_declarado_se_rechaza():
    with pytest.raises(ErrorDeCanonicalizacion, match="no declarados"):
        canonicalizar(registro(sorpresa="x"), DEMO)


def test_campo_obligatorio_ausente_se_rechaza():
    incompleto = registro()
    del incompleto["total"]
    with pytest.raises(ErrorDeCanonicalizacion, match="obligatorio"):
        canonicalizar(incompleto, DEMO)


def test_campo_obligatorio_nulo_se_rechaza():
    with pytest.raises(ErrorDeCanonicalizacion, match="nulo"):
        canonicalizar(registro(emisor=None), DEMO)


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("emisor", 123),          # entero donde va cadena
        ("posicion", "7"),        # cadena donde va entero
        ("posicion", True),       # bool no es entero
        ("cedido", 1),            # entero no es bool
        ("total", True),          # bool no es decimal
        ("fecha", "2026-08-14"),  # cadena donde va instante
    ],
)
def test_tipo_equivocado_da_error_descriptivo(campo, valor):
    with pytest.raises(ErrorDeCanonicalizacion, match=f"campo '{campo}'"):
        canonicalizar(registro(**{campo: valor}), DEMO)


def test_decimal_sin_escala_no_se_puede_declarar():
    with pytest.raises(ErrorDeCanonicalizacion, match="no declara escala"):
        Campo("total", Tipo.DECIMAL)


def test_esquema_con_campo_repetido_se_rechaza():
    with pytest.raises(ErrorDeCanonicalizacion, match="dos veces"):
        Esquema("x", (Campo("v", Tipo.CADENA), Campo("v", Tipo.ENTERO)))


# --------------------------------------------------------------------------- #
# Vector fijo: si esto cambia, la canon cambió y la bitácora quedó inservible
# --------------------------------------------------------------------------- #


def test_vector_congelado():
    """Centinela de congelación.

    Cualquier edición a la canon rompe esta prueba. Si falla, la pregunta no es
    «cómo actualizo el vector» sino «por qué estoy cambiando CORD-CANON-1».
    """
    esquema = Esquema(
        "demo",
        (
            Campo("total", Tipo.DECIMAL, escala=2),
            Campo("nota", Tipo.CADENA, opcional=True),
        ),
    )
    assert (
        canonicalizar({"total": Decimal("100.5")}, esquema)
        == b"CORD-CANON-14:demo5:total7:d100.504:nota1:n"
    )
