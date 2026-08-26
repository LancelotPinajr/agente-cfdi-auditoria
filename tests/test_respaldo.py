"""Pruebas de durabilidad de la bitácora (tareas 3.13 y 3.14).

Lo que se prueba aquí no es que el respaldo suba archivos: es que **la cadena
sobreviva a perder la instancia** y que las formas de perderla a medias —una
subida interrumpida, un almacén caído, dos subidas compitiendo— acaben en un
estado que se declara, y no en uno que parece correcto.
"""

import os
import sqlite3
import threading
import time
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agente_cfdi.api import dependencias
from agente_cfdi.api.app import app
from agente_cfdi.bitacora import respaldo
from agente_cfdi.bitacora.almacen import Bitacora
from agente_cfdi.bitacora.eventos import Veredicto
from agente_cfdi.bitacora.respaldo import (
    Instantanea,
    Replicador,
    RespaldoEnDirectorio,
    almacen_desde_entorno,
    restaurar_si_falta,
    revisar_instantanea,
    tomar_instantanea,
)
from agente_cfdi.fuentes.sintetica import ContabilidadSintetica
from agente_cfdi.sintetico.generador import generar_lote

SEMILLA = 20260815
INQUILINO = "DEMO000000XX0"
UUID_A = "9F2C1A88-FB09-47F8-B5F9-6DD1C6889D8C"
UUID_B = "3A7E5B21-CD04-4E9A-8B12-7FA3D5E90C44"


def auditoria(uuid=UUID_A, total="142878.90"):
    return {
        "uuid": uuid,
        "rfc_emisor": "QZU000000D18",
        "rfc_receptor": "ABC000000X11",
        "total": Decimal(total),
        "moneda": "MXN",
        "fecha_emision": "2026-07-15T10:30:00",
        "veredicto": Veredicto.RESPALDADO.value,
        "fuente_de_libros": "sintetica",
    }


def bitacora_en(ruta, inquilino=INQUILINO):
    conexion = sqlite3.connect(ruta)
    bitacora = Bitacora(conexion, inquilino=inquilino)
    bitacora.migrar()
    return conexion, bitacora


def capturador():
    """Un anotador que guarda las líneas en vez de imprimirlas."""
    lineas: list[dict] = []

    def anotar(evento, **campos):
        lineas.append({"evento": evento, **campos})

    return lineas, anotar


@pytest.fixture(autouse=True)
def respaldo_limpio():
    """El replicador es un singleton de proceso; entre pruebas hay que olvidarlo."""
    dependencias.reiniciar_respaldo()
    yield
    dependencias.reiniciar_respaldo()


# --------------------------------------------------------------------------- #
# La instantánea
# --------------------------------------------------------------------------- #


def test_la_instantanea_es_una_bitacora_restaurable(tmp_path):
    conexion, bitacora = bitacora_en(tmp_path / "origen.db")
    bitacora.anexar_auditoria(**auditoria(UUID_A))
    bitacora.anexar_auditoria(**auditoria(UUID_B))

    copia = bitacora.instantanea()
    conexion.close()

    assert copia.altura == 2
    assert revisar_instantanea(copia.contenido, inquilino=INQUILINO) == 2


def test_la_instantanea_se_niega_si_hay_una_transaccion_abierta(tmp_path):
    """Con una transacción abierta, `backup()` no falla: se cuelga para siempre.

    El candado que esperaría lo tiene el mismo hilo que espera, así que el
    reintento de `Connection.backup()` no termina nunca. En Cloud Run eso sería
    una petición colgada sin traza. Se exige el error inmediato.
    """
    conexion, bitacora = bitacora_en(tmp_path / "origen.db")
    bitacora.anexar_auditoria(**auditoria(UUID_A))

    conexion.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(RuntimeError, match="transacción abierta"):
            tomar_instantanea(conexion, altura=1)
    finally:
        conexion.execute("ROLLBACK")
        conexion.close()


def test_revisar_rechaza_un_snapshot_truncado(tmp_path):
    conexion, bitacora = bitacora_en(tmp_path / "origen.db")
    bitacora.anexar_auditoria(**auditoria())
    copia = bitacora.instantanea()
    conexion.close()

    mutilada = copia.contenido[: len(copia.contenido) // 2]
    assert revisar_instantanea(mutilada, inquilino=INQUILINO) is None


def test_revisar_rechaza_algo_que_no_es_una_bitacora():
    assert revisar_instantanea(b"esto no es una base de datos", inquilino=INQUILINO) is None


# --------------------------------------------------------------------------- #
# 3.14 — el respaldo
# --------------------------------------------------------------------------- #


def test_cada_subida_produce_una_generacion_distinta(tmp_path):
    """Criterio de 3.14: el objeto cambia de generación tras cada confirmación."""
    conexion, bitacora = bitacora_en(tmp_path / "origen.db")
    almacen = RespaldoEnDirectorio(tmp_path / "respaldo")

    generaciones = []
    for indice in range(3):
        bitacora.anexar_auditoria(**auditoria(uuid=f"{UUID_A[:-1]}{indice}"))
        generaciones.append(almacen.subir(bitacora.instantanea()))
    conexion.close()

    assert len(set(generaciones)) == 3
    assert almacen.ultimo().altura_declarada == 3


def test_una_subida_interrumpida_deja_intacto_el_snapshot_anterior(tmp_path, monkeypatch):
    """Criterio de 3.14: se prueba que el anterior sigue siendo válido, no se supone."""
    conexion, bitacora = bitacora_en(tmp_path / "origen.db")
    almacen = RespaldoEnDirectorio(tmp_path / "respaldo")

    bitacora.anexar_auditoria(**auditoria(UUID_A))
    almacen.subir(bitacora.instantanea())

    bitacora.anexar_auditoria(**auditoria(UUID_B))
    segunda = bitacora.instantanea()
    conexion.close()

    def morir_a_media_subida(*_args, **_kwargs):
        raise OSError("el proceso murió antes de renombrar")

    monkeypatch.setattr(respaldo.os, "replace", morir_a_media_subida)
    with pytest.raises(OSError):
        almacen.subir(segunda)
    monkeypatch.undo()

    # El objeto vigente sigue siendo el primero, entero y restaurable.
    recuperada = almacen.ultimo()
    assert revisar_instantanea(recuperada.contenido, inquilino=INQUILINO) == 1


def test_un_almacen_caido_degrada_y_anota_sin_levantar():
    """Criterio de 3.14: degradado y alertando, nunca una excepción hacia arriba."""

    class AlmacenCaido:
        descripcion = "caido"

        def subir(self, instantanea):
            raise RuntimeError("el almacén no responde")

        def ultimo(self):
            raise RuntimeError("el almacén no responde")

    lineas, anotar = capturador()
    replicador = Replicador(AlmacenCaido(), anotar=anotar)
    replicador.iniciar()
    replicador.solicitar(Instantanea(contenido=b"lo que sea", altura=1))
    assert replicador.vaciar(5.0)
    replicador.detener()

    assert replicador.degradado is True
    assert "el almacén no responde" in replicador.ultimo_error
    assert replicador.altura_replicada == -1
    assert [linea["evento"] for linea in lineas] == ["respaldo.fallo"]


# --------------------------------------------------------------------------- #
# El orden de las subidas — el fallo que produce evidencia de aspecto correcto
# --------------------------------------------------------------------------- #


class AlmacenConPuerta:
    """Almacén que se queda atorado en la primera subida hasta que se le abre."""

    descripcion = "con-puerta"

    def __init__(self):
        self.recibidas: list[int] = []
        self.en_vuelo = threading.Event()
        self.puerta = threading.Event()

    def subir(self, instantanea):
        self.recibidas.append(instantanea.altura)
        self.en_vuelo.set()
        if len(self.recibidas) == 1:
            assert self.puerta.wait(5.0)
        return f"gen-{instantanea.altura}"

    def ultimo(self):
        return None


def test_la_instantanea_pendiente_se_reemplaza_en_vez_de_encolarse():
    """Tres confirmaciones durante una subida en vuelo suben una sola vez.

    No se pierde nada: cada instantánea es el archivo completo, así que la de
    altura 5 contiene todo lo de las de 2, 3 y 4.
    """
    almacen = AlmacenConPuerta()
    replicador = Replicador(almacen)
    replicador.iniciar()

    replicador.solicitar(Instantanea(contenido=b"1", altura=1))
    assert almacen.en_vuelo.wait(5.0)

    for altura in (2, 3, 4, 5):
        replicador.solicitar(Instantanea(contenido=b"x", altura=altura))

    almacen.puerta.set()
    assert replicador.vaciar(5.0)
    replicador.detener()

    assert almacen.recibidas == [1, 5]
    assert replicador.coalescidas == 3
    assert replicador.subidas == 2
    assert replicador.altura_replicada == 5


def test_las_subidas_llegan_al_almacen_en_orden_de_confirmacion():
    """La garantía que hace que la restauración no pueda encoger la cadena."""

    class AlmacenLento:
        descripcion = "lento"

        def __init__(self):
            self.recibidas: list[int] = []

        def subir(self, instantanea):
            time.sleep(0.005)
            self.recibidas.append(instantanea.altura)
            return f"gen-{instantanea.altura}"

        def ultimo(self):
            return None

    almacen = AlmacenLento()
    replicador = Replicador(almacen)
    replicador.iniciar()
    for altura in range(1, 31):
        replicador.solicitar(Instantanea(contenido=b"x", altura=altura))
        time.sleep(0.001)
    assert replicador.vaciar(10.0)
    replicador.detener()

    assert almacen.recibidas == sorted(almacen.recibidas), "una subida se adelantó"
    assert almacen.recibidas[-1] == 30, "la última confirmación no llegó al almacén"
    assert replicador.altura_replicada == 30


def test_el_replicador_rechaza_un_retroceso_de_altura():
    """Defensa para el día que alguien añada un segundo hilo «para ir más rápido»."""

    class AlmacenQueCuenta:
        descripcion = "cuenta"

        def __init__(self):
            self.recibidas: list[int] = []

        def subir(self, instantanea):
            self.recibidas.append(instantanea.altura)
            return f"gen-{instantanea.altura}"

        def ultimo(self):
            return None

    almacen = AlmacenQueCuenta()
    lineas, anotar = capturador()
    replicador = Replicador(almacen, anotar=anotar)
    replicador.iniciar()

    replicador.solicitar(Instantanea(contenido=b"x", altura=10))
    assert replicador.vaciar(5.0)
    replicador.solicitar(Instantanea(contenido=b"x", altura=4))
    assert replicador.vaciar(5.0)
    replicador.detener()

    assert almacen.recibidas == [10], "se subió un snapshot más viejo encima"
    assert replicador.altura_replicada == 10
    assert any(l["evento"] == "respaldo.retroceso_rechazado" for l in lineas)


# --------------------------------------------------------------------------- #
# 3.13 — la restauración
# --------------------------------------------------------------------------- #


def test_no_se_restaura_encima_de_una_bitacora_que_ya_existe(tmp_path):
    """Un reinicio del proceso dentro de la misma instancia no debe pisar nada."""
    ruta = tmp_path / "bitacora.db"
    conexion, bitacora = bitacora_en(ruta)
    bitacora.anexar_auditoria(**auditoria(UUID_A))
    bitacora.anexar_auditoria(**auditoria(UUID_B))
    almacen = RespaldoEnDirectorio(tmp_path / "respaldo")
    almacen.subir(Instantanea(contenido=b"un snapshot viejo y corto", altura=0))
    conexion.close()

    resultado = restaurar_si_falta(ruta, almacen, inquilino=INQUILINO)

    assert resultado.estado == "ya_existia"
    conexion, bitacora = bitacora_en(ruta)
    assert bitacora.altura() == 2
    conexion.close()


def test_un_snapshot_corrupto_no_se_instala(tmp_path):
    ruta = tmp_path / "bitacora.db"
    carpeta = tmp_path / "respaldo"
    carpeta.mkdir()
    (carpeta / "bitacora.db").write_bytes(b"esto no es una base de datos")

    lineas, anotar = capturador()
    resultado = restaurar_si_falta(
        ruta, RespaldoEnDirectorio(carpeta), inquilino=INQUILINO, anotar=anotar
    )

    assert resultado.estado == "corrupta"
    assert not ruta.exists(), "se instaló un snapshot que no pasa integrity_check"
    assert lineas[0]["estado"] == "corrupta"


def test_un_almacen_caido_al_arrancar_no_impide_arrancar(tmp_path):
    class AlmacenCaido:
        descripcion = "caido"

        def subir(self, instantanea):
            raise RuntimeError("sin red")

        def ultimo(self):
            raise RuntimeError("sin red")

    lineas, anotar = capturador()
    resultado = restaurar_si_falta(
        tmp_path / "bitacora.db", AlmacenCaido(), inquilino=INQUILINO, anotar=anotar
    )

    assert resultado.estado == "fallo"
    assert "sin red" in resultado.detalle
    assert lineas[0]["estado"] == "fallo"


def test_la_altura_restaurada_se_recalcula_y_no_se_cree_a_los_metadatos(tmp_path):
    """Los metadatos son advisorios: la altura que se reporta sale del archivo."""
    conexion, bitacora = bitacora_en(tmp_path / "origen.db")
    bitacora.anexar_auditoria(**auditoria(UUID_A))
    bitacora.anexar_auditoria(**auditoria(UUID_B))
    copia = bitacora.instantanea()
    conexion.close()

    carpeta = tmp_path / "respaldo"
    almacen = RespaldoEnDirectorio(carpeta)
    almacen.subir(copia)
    # Se desfasan los metadatos, como haría un proceso muerto entre las dos
    # escrituras del respaldo en directorio.
    metadatos = carpeta / "bitacora.meta.json"
    metadatos.write_text(
        metadatos.read_text(encoding="utf-8").replace('"altura": 2', '"altura": 99'),
        encoding="utf-8",
    )

    resultado = restaurar_si_falta(
        tmp_path / "bitacora.db", almacen, inquilino=INQUILINO
    )

    assert resultado.altura == 2, "se creyó a los metadatos en vez de al archivo"
    assert resultado.altura_declarada == 99
    assert resultado.discrepancia is True


def test_almacen_desde_entorno_no_se_degrada_en_silencio(monkeypatch):
    monkeypatch.setenv(respaldo.VARIABLE_DESTINO, "gs://")
    with pytest.raises(RuntimeError, match="no nombra una cubeta"):
        almacen_desde_entorno()

    monkeypatch.setenv(respaldo.VARIABLE_DESTINO, "gs://mi-cubeta")
    almacen = almacen_desde_entorno()
    assert almacen.descripcion == f"gs://mi-cubeta/{respaldo.OBJETO_PREDETERMINADO}"

    monkeypatch.delenv(respaldo.VARIABLE_DESTINO)
    assert almacen_desde_entorno() is None


# --------------------------------------------------------------------------- #
# De punta a punta, por HTTP
# --------------------------------------------------------------------------- #


@pytest.fixture
def lote():
    return generar_lote(cantidad=6, semilla=SEMILLA)


@pytest.fixture
def libros(lote):
    return ContabilidadSintetica(lote=lote)


@pytest.fixture
def entorno(tmp_path, monkeypatch, libros):
    monkeypatch.setenv(dependencias.VARIABLE_RUTA, str(tmp_path / "bitacora.db"))
    monkeypatch.setenv(dependencias.VARIABLE_INQUILINO, INQUILINO)
    monkeypatch.setenv(respaldo.VARIABLE_DESTINO, str(tmp_path / "respaldo"))
    app.dependency_overrides[dependencias.fuente_actual] = lambda: libros
    yield tmp_path
    app.dependency_overrides.clear()


def archivos_de(lote, cuantos=None):
    comprobantes = lote.comprobantes[:cuantos] if cuantos else lote.comprobantes
    return [
        ("archivos", (f"{c.uuid}.xml", c.a_xml().encode("utf-8"), "application/xml"))
        for c in comprobantes
    ]


def test_la_cadena_sobrevive_a_que_se_borre_la_ruta(entorno, lote):
    """Criterio de 3.13, de punta a punta.

    Se borra el archivo —que es lo que le pasa a `/tmp` en cada despliegue— se
    arranca de nuevo, y la misma prueba de Merkle del mismo folio sale con la
    misma raíz. Sin correr el ciclo.
    """
    ruta = Path(os.environ[dependencias.VARIABLE_RUTA])
    uuid = lote.comprobantes[0].uuid

    with TestClient(app) as cliente:
        assert cliente.post("/ingesta", files=archivos_de(lote)).status_code == 200
        antes = cliente.get(f"/auditoria/prueba/{uuid}").json()
        altura_antes = cliente.get("/salud").json()["altura"]
        punta_antes = cliente.get("/salud").json()["punta"]
    # Salir del contexto ejecuta el apagado, que vacía la cola de réplica.

    ruta.unlink()
    dependencias.reiniciar_respaldo()  # proceso nuevo, misma configuración
    assert not ruta.exists()

    with TestClient(app) as cliente:
        despues = cliente.get(f"/auditoria/prueba/{uuid}").json()
        salud = cliente.get("/salud").json()
        semaforo = cliente.get("/semaforo").json()

    assert salud["altura"] == altura_antes
    assert salud["punta"] == punta_antes
    assert despues["raiz"] == antes["raiz"]
    assert despues["posicion"] == antes["posicion"]

    assert semaforo["respaldo"]["restauracion"] == "restaurada"
    assert semaforo["respaldo"]["altura_restaurada"] == altura_antes
    assert semaforo["respaldo"]["generacion"]


def test_sin_snapshot_arranca_vacia_y_lo_dice(entorno, capsys):
    """Criterio de 3.13: arranca vacía y lo dice en el log, nunca en silencio."""
    with TestClient(app) as cliente:
        cuerpo = cliente.get("/semaforo").json()

    assert cuerpo["color"] == "gris"
    assert cuerpo["respaldo"]["restauracion"] == "sin_snapshot"
    assert "nunca se ha replicado nada" in cuerpo["detalle"]

    salida = capsys.readouterr().out
    assert "bitacora.restauracion" in salida
    assert "sin_snapshot" in salida


def test_el_semaforo_distingue_por_que_esta_vacia(entorno):
    """Un snapshot corrupto y un respaldo ausente ya no se ven igual."""
    carpeta = Path(os.environ[respaldo.VARIABLE_DESTINO])
    carpeta.mkdir(parents=True)
    (carpeta / "bitacora.db").write_bytes(b"esto no es una base de datos")

    with TestClient(app) as cliente:
        cuerpo = cliente.get("/semaforo").json()

    assert cuerpo["color"] == "gris"
    assert cuerpo["respaldo"]["restauracion"] == "corrupta"
    assert "NO se instaló" in cuerpo["detalle"]


def test_un_fallo_del_respaldo_no_tumba_la_peticion(entorno, lote, monkeypatch):
    """Criterio de 3.14: ni una escritura perdida ni una petición caída."""

    def subir_que_falla(self, instantanea):
        raise RuntimeError("el almacén no responde")

    monkeypatch.setattr(RespaldoEnDirectorio, "subir", subir_que_falla)

    with TestClient(app) as cliente:
        respuesta = cliente.post("/ingesta", files=archivos_de(lote))
        assert respuesta.status_code == 200
        assert respuesta.json()["altura"] == 6

        assert dependencias.replicador_actual().vaciar(5.0)
        semaforo = cliente.get("/semaforo").json()

    # La escritura local está y la cadena verifica: lo que falló fue la copia.
    assert semaforo["altura"] == 6
    assert semaforo["color"] == "ambar"
    assert semaforo["respaldo"]["degradado"] is True
    assert "el almacén no responde" in semaforo["respaldo"]["ultimo_error"]


def test_la_replica_avanza_con_cada_ingesta(entorno, lote):
    with TestClient(app) as cliente:
        alturas = []
        for indice in range(3):
            comprobante = lote.comprobantes[indice]
            cliente.post(
                "/ingesta",
                files=[
                    (
                        "archivos",
                        (
                            f"{comprobante.uuid}.xml",
                            comprobante.a_xml().encode("utf-8"),
                            "application/xml",
                        ),
                    )
                ],
            )
            replicador = dependencias.replicador_actual()
            assert replicador.vaciar(5.0)
            alturas.append(replicador.altura_replicada)

        assert alturas == [1, 2, 3]
        assert dependencias.replicador_actual().degradado is False
