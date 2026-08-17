"""Pruebas de la bitácora encadenada (tareas 2.1, 2.2 y 2.3).

Lo que se prueba aquí no es que el código corra: es que **la manipulación se
detecte**. Cada prueba de esta sección monta un ataque concreto y verifica que
la cadena lo delate señalando la posición.
"""

import sqlite3
import threading
from decimal import Decimal

import pytest

from agente_cfdi.bitacora.almacen import Bitacora, BitacoraCorrupta
from agente_cfdi.bitacora.cadena import (
    CadenaRota,
    Eslabon,
    PREFIJO_HOJA,
    PREFIJO_NODO,
    genesis,
    hash_de_registro,
    raiz_de_merkle,
    verificar_cadena,
)
from agente_cfdi.bitacora.eventos import Evento, Veredicto

UUID_A = "9F2C1A88-FB09-47F8-B5F9-6DD1C6889D8C"
UUID_B = "3A7E5B21-CD04-4E9A-8B12-7FA3D5E90C44"


def auditoria(uuid=UUID_A, total="142878.90", veredicto=Veredicto.RESPALDADO):
    return {
        "uuid": uuid,
        "rfc_emisor": "QZU000000D18",
        "rfc_receptor": "ABC000000X11",
        "total": Decimal(total),
        "moneda": "MXN",
        "fecha_emision": "2026-07-15T10:30:00",
        "veredicto": veredicto.value,
        "fuente_de_libros": "sintetica",
    }


@pytest.fixture
def bitacora():
    return Bitacora.en_memoria("QZU000000D18")


# --------------------------------------------------------------------------- #
# 2.1 y 2.2 — se escribe y se encadena
# --------------------------------------------------------------------------- #


def test_migrar_es_idempotente(bitacora):
    bitacora.migrar()
    bitacora.migrar()
    assert bitacora.altura() == 0


def test_la_cadena_vacia_verifica(bitacora):
    assert bitacora.verificar() == 0
    assert bitacora.punta() == genesis("QZU000000D18")


def test_cada_registro_apunta_al_anterior(bitacora):
    primero = bitacora.anexar(Evento.CFDI_AUDITADO, auditoria())
    segundo = bitacora.anexar(Evento.CFDI_AUDITADO, auditoria(uuid=UUID_B))

    eslabones = list(bitacora.eslabones())
    assert [e.posicion for e in eslabones] == [0, 1]
    assert eslabones[0].hash_anterior == genesis("QZU000000D18")
    assert eslabones[1].hash_anterior == primero.hash_registro
    assert bitacora.punta() == segundo.hash_registro
    assert bitacora.verificar() == 2


def test_el_hash_depende_del_contenido(bitacora):
    uno = bitacora.anexar(Evento.CFDI_AUDITADO, auditoria(total="100.00"))
    otro = Bitacora.en_memoria("QZU000000D18").anexar(
        Evento.CFDI_AUDITADO, auditoria(total="100.01")
    )
    assert uno.hash_registro != otro.hash_registro


def test_dos_inquilinos_no_comparten_genesis():
    """Sin esto, los registros de una PYME se podrían injertar en otra cadena."""
    assert genesis("QZU000000D18") != genesis("ABC000000X11")


def test_un_registro_injertado_de_otra_cadena_no_verifica():
    ajena = Bitacora.en_memoria("ABC000000X11")
    ajena.anexar(Evento.CFDI_AUDITADO, auditoria())
    (prestado,) = list(ajena.eslabones())

    with pytest.raises(CadenaRota) as caso:
        verificar_cadena([prestado], "QZU000000D18")
    assert caso.value.posicion == 0


# --------------------------------------------------------------------------- #
# Detección de manipulación — el punto del producto
# --------------------------------------------------------------------------- #


def test_alterar_un_monto_rompe_la_cadena_en_esa_posicion(bitacora):
    """El escenario que se graba en el video de la demo."""
    for _ in range(5):
        bitacora.anexar(Evento.CFDI_AUDITADO, auditoria())
    assert bitacora.verificar() == 5

    # Alguien con acceso a la base edita el canónico del registro 2.
    original = bitacora._cx.execute(
        "SELECT canonico FROM bitacora_registros WHERE posicion = 2"
    ).fetchone()["canonico"]
    alterado = bytes(original).replace(b"d142878.90", b"d999999.90")
    assert alterado != original
    bitacora._cx.execute(
        "UPDATE bitacora_registros SET canonico = ? WHERE posicion = 2", (alterado,)
    )

    with pytest.raises(CadenaRota) as caso:
        bitacora.verificar()
    assert caso.value.posicion == 2
    assert "alterado" in caso.value.detalle


def test_borrar_un_eslabon_del_medio_se_detecta(bitacora):
    for _ in range(4):
        bitacora.anexar(Evento.CFDI_AUDITADO, auditoria())
    bitacora._cx.execute("DELETE FROM bitacora_cadena WHERE posicion = 1")

    with pytest.raises(CadenaRota) as caso:
        bitacora.verificar()
    assert caso.value.posicion == 2
    assert "hueco" in caso.value.detalle


def test_reescribir_un_hash_para_tapar_el_hueco_tambien_se_detecta(bitacora):
    """El atacante recalcula un hash pero no puede recalcular los siguientes."""
    for _ in range(4):
        bitacora.anexar(Evento.CFDI_AUDITADO, auditoria())

    falso = hash_de_registro(b"lo que yo quiera", genesis("QZU000000D18"))
    bitacora._cx.execute(
        "UPDATE bitacora_cadena SET hash_registro = ? WHERE posicion = 0", (falso,)
    )

    with pytest.raises(CadenaRota) as caso:
        bitacora.verificar()
    # Falla en 0 (el contenido ya no da ese hash) antes de llegar al eslabón roto.
    assert caso.value.posicion == 0


def test_intercambiar_el_contenido_de_dos_registros_se_detecta(bitacora):
    """Reordenar sin tocar los eslabones: cada uno deja de producir su hash."""
    for i in range(3):
        bitacora.anexar(Evento.CFDI_AUDITADO, auditoria(total=f"{100 + i}.00"))

    uno, otro = (
        bytes(
            bitacora._cx.execute(
                "SELECT canonico FROM bitacora_registros WHERE posicion = ?", (p,)
            ).fetchone()["canonico"]
        )
        for p in (1, 2)
    )
    bitacora._cx.execute("UPDATE bitacora_registros SET canonico = ? WHERE posicion = 1", (otro,))
    bitacora._cx.execute("UPDATE bitacora_registros SET canonico = ? WHERE posicion = 2", (uno,))

    with pytest.raises(CadenaRota) as caso:
        bitacora.verificar()
    assert caso.value.posicion == 1


def test_la_clave_foranea_impide_mover_un_registro_a_una_posicion_inexistente(bitacora):
    """Ni siquiera hace falta la cadena para frenar esto: lo frena el esquema."""
    bitacora.anexar(Evento.CFDI_AUDITADO, auditoria())
    with pytest.raises(sqlite3.IntegrityError):
        bitacora._cx.execute("UPDATE bitacora_registros SET posicion = 99 WHERE posicion = 0")


# --------------------------------------------------------------------------- #
# Retención: suprimir datos sin romper la prueba
# --------------------------------------------------------------------------- #


def test_suprimir_el_contenido_no_rompe_la_cadena(bitacora):
    """La propiedad que permite cumplir la LFPDPPP sin sacrificar la integridad."""
    for _ in range(5):
        bitacora.anexar(Evento.CFDI_AUDITADO, auditoria())

    bitacora.suprimir_registro(2)

    assert bitacora.altura() == 5          # el eslabón sigue ahí
    assert bitacora.verificar() == 4       # pero ya no se recalcula


def test_la_verificacion_distingue_lo_recalculado_de_lo_confiado(bitacora):
    """«Verifiqué 200» y «verifiqué 3 y confié en 197» no son lo mismo."""
    for _ in range(3):
        bitacora.anexar(Evento.CFDI_AUDITADO, auditoria())
    for posicion in (0, 1, 2):
        bitacora.suprimir_registro(posicion)

    assert bitacora.verificar() == 0
    assert bitacora.altura() == 3
    assert all(not e.verificable for e in bitacora.eslabones())


# --------------------------------------------------------------------------- #
# 2.3 — doble cesión
# --------------------------------------------------------------------------- #


def test_la_primera_cesion_se_acepta(bitacora):
    resultado = bitacora.registrar_cesion(
        uuid=UUID_A,
        financiador="Banco Norte",
        rfc_emisor="QZU000000D18",
        total=Decimal("142878.90"),
    )
    assert resultado.aceptada
    assert bitacora.cesion_de(UUID_A)["financiador"] == "Banco Norte"


def test_la_segunda_cesion_del_mismo_folio_se_rechaza(bitacora):
    primera = bitacora.registrar_cesion(
        uuid=UUID_A, financiador="Banco Norte",
        rfc_emisor="QZU000000D18", total=Decimal("142878.90"),
    )
    segunda = bitacora.registrar_cesion(
        uuid=UUID_A, financiador="Factor Sur",
        rfc_emisor="QZU000000D18", total=Decimal("142878.90"),
    )

    assert not segunda.aceptada
    assert segunda.posicion_de_la_cesion_previa == primera.posicion
    # El financiador original conserva la cesión.
    assert bitacora.cesion_de(UUID_A)["financiador"] == "Banco Norte"


def test_el_intento_rechazado_tambien_queda_escrito(bitacora):
    """Una bitácora que solo guarda lo que salió bien no sirve para investigar."""
    bitacora.registrar_cesion(
        uuid=UUID_A, financiador="Banco Norte",
        rfc_emisor="QZU000000D18", total=Decimal("1.00"),
    )
    bitacora.registrar_cesion(
        uuid=UUID_A, financiador="Factor Sur",
        rfc_emisor="QZU000000D18", total=Decimal("1.00"),
    )

    eventos = [
        f["evento"]
        for f in bitacora._cx.execute(
            "SELECT evento FROM bitacora_registros ORDER BY posicion"
        )
    ]
    assert eventos == [Evento.CESION_REGISTRADA.value, Evento.CESION_RECHAZADA.value]
    assert bitacora.verificar() == 2


def test_folios_distintos_se_ceden_sin_estorbarse(bitacora):
    assert bitacora.registrar_cesion(
        uuid=UUID_A, financiador="Banco Norte",
        rfc_emisor="QZU000000D18", total=Decimal("1.00"),
    ).aceptada
    assert bitacora.registrar_cesion(
        uuid=UUID_B, financiador="Factor Sur",
        rfc_emisor="QZU000000D18", total=Decimal("1.00"),
    ).aceptada


def test_la_restriccion_unique_es_la_garantia_no_el_select(bitacora):
    """Si el SELECT previo desapareciera, la propiedad seguiría en pie.

    Se salta la lógica de la aplicación y se inserta directo: la base rechaza.
    """
    bitacora.registrar_cesion(
        uuid=UUID_A, financiador="Banco Norte",
        rfc_emisor="QZU000000D18", total=Decimal("1.00"),
    )
    with pytest.raises(sqlite3.IntegrityError):
        bitacora._cx.execute(
            "INSERT INTO cesiones (uuid, inquilino, financiador, posicion, cedido_en)"
            " VALUES (?, ?, ?, ?, ?)",
            (UUID_A, "QZU000000D18", "Factor Sur", 99, "2026-08-14T00:00:00Z"),
        )


CONCURRENTES = 8


def _ceder_en_paralelo(ruta, fabrica):
    """Ocho hilos intentan ceder el mismo folio en el mismo instante."""
    fabrica(sqlite3.connect(ruta)).migrar()
    listos = threading.Barrier(CONCURRENTES)
    resultados: list[object] = []
    cerrojo = threading.Lock()

    def ceder(quien: int) -> None:
        propia = fabrica(sqlite3.connect(ruta, timeout=10))
        listos.wait()
        try:
            salida = propia.registrar_cesion(
                uuid=UUID_A, financiador=f"Financiador {quien}",
                rfc_emisor="QZU000000D18", total=Decimal("1.00"),
            )
            registro = salida.aceptada
        except Exception as exc:
            registro = exc
        with cerrojo:
            resultados.append(registro)

    hilos = [threading.Thread(target=ceder, args=(i,)) for i in range(CONCURRENTES)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join()
    return resultados


def test_dos_cesiones_simultaneas_solo_una_gana(tmp_path):
    """El ataque real: mandar las solicitudes a la vez.

    Se exigen **dos** propiedades, y cada una la da un mecanismo distinto:

    - **Corrección** — exactamente una cesión. La da la restricción `UNIQUE`.
    - **Disponibilidad** — las otras siete reciben un rechazo, no un error de
      infraestructura. La da `BEGIN IMMEDIATE`.

    La segunda no es cosmética: sin el candado, SQLite devuelve «database is
    locked» a la mayoría de los hilos. Nadie cede dos veces, pero peticiones
    legítimas se caen y el operador no sabe si su factura quedó cedida.
    """
    ruta = tmp_path / "bitacora.db"
    fabrica = lambda cx: Bitacora(cx, inquilino="QZU000000D18")
    resultados = _ceder_en_paralelo(ruta, fabrica)

    aceptadas = [r for r in resultados if r is True]
    rechazadas = [r for r in resultados if r is False]
    fallidas = [r for r in resultados if isinstance(r, Exception)]

    assert len(aceptadas) == 1, f"cedieron {len(aceptadas)} veces: {resultados}"
    assert not fallidas, f"peticiones caídas por contención: {fallidas}"
    assert len(rechazadas) == CONCURRENTES - 1

    final = Bitacora(sqlite3.connect(ruta), inquilino="QZU000000D18")
    assert final.verificar() == final.altura(), "la cadena se bifurcó"
    assert final._cx.execute("SELECT COUNT(*) FROM cesiones").fetchone()[0] == 1


def test_sin_el_candado_la_correccion_aguanta_pero_la_disponibilidad_no(tmp_path):
    """Prueba de que la prueba anterior sirve.

    Se corre la misma carga contra una variante con `BEGIN` perezoso en vez de
    `BEGIN IMMEDIATE`. La restricción `UNIQUE` sigue impidiendo la doble
    cesión —la corrección no depende del candado— pero aparecen caídas por
    contención. Es lo que distingue las dos implementaciones, y por eso el test
    de arriba exige `not fallidas`.
    """

    class SinCandado(Bitacora):
        def _transaccion(self):
            conexion = self._cx

            class Perezosa:
                def __enter__(self):
                    conexion.execute("BEGIN")
                    return conexion

                def __exit__(self, tipo, valor, rastro):
                    conexion.execute("COMMIT" if tipo is None else "ROLLBACK")
                    return False

            return Perezosa()

    ruta = tmp_path / "sin_candado.db"
    resultados = _ceder_en_paralelo(
        ruta, lambda cx: SinCandado(cx, inquilino="QZU000000D18")
    )

    assert len([r for r in resultados if r is True]) == 1  # la corrección aguanta
    assert [r for r in resultados if isinstance(r, Exception)], (
        "sin candado se esperaban caídas por contención; si esto deja de pasar, "
        "el test de disponibilidad de arriba ya no distingue nada"
    )


# --------------------------------------------------------------------------- #
# 2.6 — raíz de Merkle
# --------------------------------------------------------------------------- #


def test_una_sola_hoja_es_su_propia_raiz():
    hoja = hash_de_registro(b"x", genesis("t"))
    assert raiz_de_merkle([hoja]) == hoja


def test_la_raiz_cambia_si_cambia_cualquier_hoja():
    hojas = [hash_de_registro(bytes([i]), genesis("t")) for i in range(7)]
    original = raiz_de_merkle(hojas)
    for indice in range(7):
        movidas = list(hojas)
        movidas[indice] = hash_de_registro(b"otro", genesis("t"))
        assert raiz_de_merkle(movidas) != original


def test_el_orden_de_las_hojas_importa():
    hojas = [hash_de_registro(bytes([i]), genesis("t")) for i in range(4)]
    assert raiz_de_merkle(hojas) != raiz_de_merkle(list(reversed(hojas)))


def test_el_nodo_impar_se_promueve_y_no_se_duplica():
    """La falla de Bitcoin (CVE-2012-2459): duplicar el último nodo hace que dos
    conjuntos distintos de hojas produzcan la misma raíz."""
    hojas = [hash_de_registro(bytes([i]), genesis("t")) for i in range(3)]
    con_duplicado = hojas + [hojas[-1]]
    assert raiz_de_merkle(hojas) != raiz_de_merkle(con_duplicado)


def test_hoja_y_nodo_interno_no_se_pueden_confundir():
    """Sin separación de dominios se puede probar la pertenencia de un registro
    que nunca existió, presentando un nodo interno como si fuera una hoja."""
    assert PREFIJO_HOJA != PREFIJO_NODO
    izquierdo = hash_de_registro(b"a", genesis("t"))
    derecho = hash_de_registro(b"b", genesis("t"))
    nodo = raiz_de_merkle([izquierdo, derecho])
    # El nodo interno no coincide con ninguna hoja construible.
    assert nodo != hash_de_registro(izquierdo + derecho, genesis("t"))


def test_un_dia_sin_registros_no_tiene_raiz(bitacora):
    with pytest.raises(ValueError, match="sin registros"):
        bitacora.raiz_del_dia("2020-01-01")


def test_la_raiz_del_dia_cubre_los_registros_de_ese_dia(bitacora):
    for _ in range(5):
        bitacora.anexar(Evento.CFDI_AUDITADO, auditoria())
    dia = bitacora._cx.execute(
        "SELECT substr(escrito_en, 1, 10) AS d FROM bitacora_cadena LIMIT 1"
    ).fetchone()["d"]

    assert len(bitacora.hojas_del_dia(dia)) == 5
    assert len(bitacora.raiz_del_dia(dia)) == 32


# --------------------------------------------------------------------------- #
# Invariantes de la aritmética
# --------------------------------------------------------------------------- #


def test_el_hash_anterior_debe_medir_32_bytes():
    with pytest.raises(ValueError, match="32"):
        hash_de_registro(b"x", b"corto")


def test_el_genesis_exige_inquilino():
    with pytest.raises(ValueError):
        genesis("")


def test_un_eslabon_con_hash_de_otro_tamano_se_rechaza():
    malo = Eslabon(posicion=0, hash_registro=b"corto", hash_anterior=genesis("t"))
    with pytest.raises(CadenaRota):
        verificar_cadena([malo], "t")
