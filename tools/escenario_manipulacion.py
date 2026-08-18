"""El escenario de manipulación, reproducible de principio a fin (tarea 3.12).

## Qué demuestra

Que alterar un registro ya escrito **no se puede hacer en silencio**. Se cambia
un monto directamente en la base de datos —saltándose la API, que es como lo
haría alguien con acceso— y el sistema lo detecta, dice en qué fila, se niega a
anclar y pone el semáforo en rojo.

## Por qué se altera la base y no se usa la API

Un ataque desde la API no probaría nada: la API es append-only por diseño y no
tiene endpoint para editar un registro pasado. El escenario interesante es el
del insider con acceso a la base, que es justo el que una bitácora encadenada
existe para cubrir. Si se demostrara «manipulando» por la vía que ya está
cerrada, la demo sería un teatro.

## Lo que este escenario NO prueba

Que nadie pueda reescribir **toda** la cadena. Quien tenga acceso a la base
puede alterar un registro y recalcular todos los hashes posteriores; saldría
íntegra. Eso lo cubre el anclaje —la raíz publicada no cambia— y por eso el
semáforo distingue «íntegra» de «íntegra y publicada». Con el ancla simulada,
esa segunda mitad todavía no está.

Uso:

    python -m uvicorn agente_cfdi.api.app:app --port 8000    # en otra terminal
    python tools/escenario_manipulacion.py
"""

from __future__ import annotations

import os
import sqlite3
import sys

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agente_cfdi.sintetico.generador import generar_lote  # noqa: E402

BASE = os.environ.get("AGENTE_CFDI_API", "http://127.0.0.1:8000")
RUTA_BD = os.environ.get("AGENTE_CFDI_BITACORA", "bitacora.db")
FILA_ALTERADA = 3

COLORES = {"verde": "🟢", "ambar": "🟡", "rojo": "🔴"}


def mostrar_semaforo(cliente: httpx.Client, momento: str) -> dict:
    estado = cliente.get("/semaforo").json()
    icono = COLORES.get(estado["color"], "?")
    print(f"\n  {icono} {momento}: {estado['titulo']}")
    print(f"     {estado['detalle']}")
    if estado.get("posicion_del_problema") is not None:
        print(f"     ► fila señalada: {estado['posicion_del_problema']}")
    if estado.get("enlace_al_explorador"):
        print(f"     ► comprobar en: {estado['enlace_al_explorador']}")
    return estado


def main() -> int:
    cliente = httpx.Client(base_url=BASE, timeout=60)

    # --- 1. Contabilidad limpia ---------------------------------------------
    lote = generar_lote(cantidad=8, semilla=20260814)
    archivos = [
        ("archivos", (f"{c.uuid}.xml", c.a_xml().encode("utf-8"), "application/xml"))
        for c in lote.comprobantes
    ]
    ingesta = cliente.post("/ingesta", files=archivos).json()
    print(f"1. Se auditan {ingesta['auditados']} CFDI y se encadenan.")
    print(f"   altura de la cadena: {ingesta['altura']}")

    mostrar_semaforo(cliente, "antes de cerrar el día")

    # --- 2. Cierre del día --------------------------------------------------
    cierre = cliente.post("/cierre-diario").json()
    print(f"\n2. Cierre del día: {cierre['estado']}")
    print(f"   raíz: {cierre['raiz']}")

    estado = mostrar_semaforo(cliente, "tras el cierre")
    if estado["color"] == "rojo":
        print("\n   ✗ la cadena ya venía rota; el escenario no prueba nada")
        return 1

    # Se guarda para comprobar después que la raíz publicada NO cambia.
    raiz_publicada = cierre["raiz"]

    # --- 3. La manipulación -------------------------------------------------
    print(f"\n3. Alguien con acceso a la base edita la fila {FILA_ALTERADA}.")
    if not os.path.exists(RUTA_BD):
        # La base la crea el servidor en su primera petición, así que no puede
        # comprobarse antes de la ingesta: aquí ya tiene que existir.
        print(f"   No encuentro la bitácora en {RUTA_BD!r}.")
        print("   Exporta AGENTE_CFDI_BITACORA con la MISMA ruta que usó el servidor.")
        return 2

    conexion = sqlite3.connect(RUTA_BD)
    antes = conexion.execute(
        "SELECT canonico FROM bitacora_registros WHERE posicion = ?", (FILA_ALTERADA,)
    ).fetchone()
    if antes is None:
        print(f"   no hay registro en la posición {FILA_ALTERADA}")
        return 1

    original = antes[0].decode("utf-8", "replace")
    alterado = original.replace("|veredicto|ssin_respaldo", "|veredicto|srespaldado")
    if alterado == original:
        # Si ese folio no era un hallazgo, se infla el monto en su lugar.
        import re

        alterado = re.sub(r"\|total\|d[\d.]+", "|total|d999999.99", original)

    conexion.execute(
        "UPDATE bitacora_registros SET canonico = ? WHERE posicion = ?",
        (alterado.encode("utf-8"), FILA_ALTERADA),
    )
    conexion.commit()
    conexion.close()
    print("   (se cambió el contenido, NO el hash: es lo que haría quien no sabe")
    print("    que el hash se recalcula al verificar)")

    # --- 4. La detección ----------------------------------------------------
    estado = mostrar_semaforo(cliente, "después de la manipulación")
    if estado["color"] != "rojo":
        print("\n   ✗ el semáforo NO se puso rojo; la detección falló")
        return 1
    if estado["posicion_del_problema"] != FILA_ALTERADA:
        print(f"\n   ✗ señaló la fila {estado['posicion_del_problema']}, no la {FILA_ALTERADA}")
        return 1

    # --- 5. Y no se vuelve a anclar ----------------------------------------
    reintento = cliente.post("/cierre-diario")
    cuerpo = reintento.json()
    print(f"\n5. El job diario vuelve a correr → HTTP {reintento.status_code}, {cuerpo['estado']}")
    print(f"   {cuerpo['detalle']}")
    if cuerpo["estado"] != "cadena_rota":
        print("   ✗ ancló sobre una cadena rota")
        return 1

    # --- 6. La raíz ya publicada no cambió ---------------------------------
    prueba = cliente.get(f"/auditoria/prueba/{lote.comprobantes[0].uuid}")
    if prueba.status_code == 200:
        raiz_ahora = prueba.json()["raiz"]
        print("\n6. La raíz sellada antes de la manipulación:")
        print(f"   {raiz_publicada}")
        print(f"   {'sigue igual' if raiz_ahora == raiz_publicada else 'CAMBIÓ'} — "
              f"por eso el ancla es lo que cierra el hueco")

    print("\n" + "=" * 70)
    print("Resultado: la alteración se detectó, se nombró la fila exacta, el")
    print("cierre se negó a anclar y el semáforo quedó en rojo.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
