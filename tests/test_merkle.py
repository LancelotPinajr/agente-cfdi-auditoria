"""Pruebas de la ruta de Merkle y del anclaje (tareas 2.6 y 2.7)."""

import hashlib

import pytest

from agente_cfdi.bitacora.anclaje import AnclaSimulada, Constancia, ErrorDeAnclaje
from agente_cfdi.bitacora.cadena import (
    PREFIJO_NODO,
    PasoDeRuta,
    genesis,
    hash_de_registro,
    raiz_de_merkle,
    raiz_desde_ruta,
    ruta_de_merkle,
    verificar_prueba,
)


def hojas_de(cuantas):
    return [hash_de_registro(f"registro-{i}".encode(), genesis("t")) for i in range(cuantas)]


# --------------------------------------------------------------------------- #
# La ruta lleva a la raíz — para todo tamaño y toda posición
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("cuantas", range(1, 34))
def test_toda_hoja_prueba_su_pertenencia(cuantas):
    """Incluye los tamaños impares, donde hay nodos promovidos."""
    hojas = hojas_de(cuantas)
    raiz = raiz_de_merkle(hojas)
    for indice, hoja in enumerate(hojas):
        ruta = ruta_de_merkle(hojas, indice)
        assert raiz_desde_ruta(hoja, ruta) == raiz, f"falló la hoja {indice} de {cuantas}"


def test_una_sola_hoja_no_necesita_camino():
    hojas = hojas_de(1)
    assert ruta_de_merkle(hojas, 0) == ()
    assert raiz_desde_ruta(hojas[0], ()) == raiz_de_merkle(hojas)


def test_el_camino_es_logaritmico():
    """40 registros dan 6 hashes: 192 bytes en vez de la bitácora entera."""
    hojas = hojas_de(40)
    assert len(ruta_de_merkle(hojas, 7)) == 6


def test_la_hoja_promovida_usa_un_paso_menos():
    """El último de un nivel impar sube solo: no tiene hermano que registrar."""
    hojas = hojas_de(7)
    assert len(ruta_de_merkle(hojas, 6)) == 2
    assert len(ruta_de_merkle(hojas, 0)) == 3


def test_una_hoja_que_no_existe_se_rechaza():
    with pytest.raises(IndexError):
        ruta_de_merkle(hojas_de(4), 4)


def test_un_dia_sin_registros_no_tiene_ruta():
    with pytest.raises(ValueError, match="sin registros"):
        ruta_de_merkle([], 0)


# --------------------------------------------------------------------------- #
# Una prueba falsa no pasa
# --------------------------------------------------------------------------- #


def test_alterar_el_contenido_invalida_la_prueba():
    hojas = hojas_de(8)
    ruta = ruta_de_merkle(hojas, 3)
    raiz = raiz_de_merkle(hojas)
    previo = genesis("t")

    assert verificar_prueba(canonico=b"registro-3", hash_anterior=previo, ruta=ruta, raiz=raiz)
    assert not verificar_prueba(
        canonico=b"registro-3 alterado", hash_anterior=previo, ruta=ruta, raiz=raiz
    )


def test_alterar_un_hermano_invalida_la_prueba():
    hojas = hojas_de(8)
    ruta = list(ruta_de_merkle(hojas, 3))
    raiz = raiz_de_merkle(hojas)

    ruta[1] = PasoDeRuta(hermano=b"\xff" * 32, hermano_a_la_derecha=ruta[1].hermano_a_la_derecha)
    assert not verificar_prueba(
        canonico=b"registro-3", hash_anterior=genesis("t"), ruta=ruta, raiz=raiz
    )


def test_invertir_el_lado_de_un_hermano_invalida_la_prueba():
    """`SHA256(0x01‖a‖b)` no es `SHA256(0x01‖b‖a)`; el lado no se adivina."""
    hojas = hojas_de(8)
    ruta = list(ruta_de_merkle(hojas, 3))
    raiz = raiz_de_merkle(hojas)

    ruta[0] = PasoDeRuta(
        hermano=ruta[0].hermano, hermano_a_la_derecha=not ruta[0].hermano_a_la_derecha
    )
    assert not verificar_prueba(
        canonico=b"registro-3", hash_anterior=genesis("t"), ruta=ruta, raiz=raiz
    )


def test_una_ruta_de_otro_dia_no_verifica():
    hojas = hojas_de(8)
    otras = [hash_de_registro(f"otro-{i}".encode(), genesis("t")) for i in range(8)]

    assert not verificar_prueba(
        canonico=b"registro-3",
        hash_anterior=genesis("t"),
        ruta=ruta_de_merkle(otras, 3),
        raiz=raiz_de_merkle(hojas),
    )


def test_un_nodo_interno_no_se_puede_presentar_como_hoja():
    """El ataque de segunda preimagen sobre árboles de Merkle.

    Sin separación de dominios, el hash de un nodo interno se puede entregar
    como si fuera una hoja y construir un camino válido para un registro que
    nunca existió. `verificar_prueba` exige el **canónico** y recalcula la hoja
    con el prefijo `0x00`; un nodo interno lleva `0x01` y nunca puede igualarla.
    """
    hojas = hojas_de(4)
    interno = hashlib.sha256(PREFIJO_NODO + hojas[0] + hojas[1]).digest()

    # No existe contenido que produzca el hash de un nodo interno como hoja.
    for contenido in (interno, hojas[0] + hojas[1], b""):
        assert hash_de_registro(contenido, genesis("t")) != interno


def test_una_hoja_de_otro_tamano_se_rechaza():
    with pytest.raises(ValueError, match="32"):
        raiz_desde_ruta(b"corta", ())


# --------------------------------------------------------------------------- #
# Anclaje
# --------------------------------------------------------------------------- #


def test_el_ancla_simulada_se_declara_simulada():
    """Una implementación de mentira que pareciera real sería peor que ninguna."""
    constancia = AnclaSimulada().anclar(hojas_de(1)[0], dia="2026-08-16")
    assert constancia.red.startswith("simulada:")
    assert constancia.verificable_por_terceros is False


def test_una_constancia_de_red_real_si_es_verificable():
    from datetime import datetime, timezone

    real = Constancia(
        red="sepolia", referencia="0xabc", anclado_en=datetime.now(timezone.utc)
    )
    assert real.verificable_por_terceros is True


def test_el_ancla_simulada_es_determinista():
    """Las pruebas tienen que ser reproducibles desde la semilla."""
    raiz = hojas_de(1)[0]
    una = AnclaSimulada().anclar(raiz, dia="2026-08-16")
    otra = AnclaSimulada().anclar(raiz, dia="2026-08-16")
    assert una.referencia == otra.referencia


def test_raices_distintas_dan_referencias_distintas():
    ancla = AnclaSimulada()
    assert (
        ancla.anclar(hojas_de(1)[0], dia="2026-08-16").referencia
        != ancla.anclar(hojas_de(2)[1], dia="2026-08-16").referencia
    )


def test_el_mismo_dia_con_raices_distintas_no_colisiona():
    ancla = AnclaSimulada()
    raiz = hojas_de(1)[0]
    assert (
        ancla.anclar(raiz, dia="2026-08-16").referencia
        != ancla.anclar(raiz, dia="2026-08-17").referencia
    )


def test_una_raiz_de_otro_tamano_se_rechaza():
    with pytest.raises(ErrorDeAnclaje):
        AnclaSimulada().anclar(b"corta", dia="2026-08-16")
