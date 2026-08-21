"""Corre el escenario completo contra una API ya levantada.

## Por qué este script existe

La fuente sintética por omisión **genera su propio lote** a partir de
`AGENTE_CFDI_SEMILLA`. Si alguien levanta la API y sube CFDI de otra semilla, los
libros no contienen esos folios y **todo sale `sin_respaldo`** — no porque el
auditor falle, sino porque se le está preguntando por facturas de otra empresa.

Este script genera el lote **con la misma semilla y la misma cantidad** que usa
la fuente, de modo que los libros y los comprobantes hablen de lo mismo. Las
únicas desviaciones que aparecen son las plantadas a propósito, que es lo que
hace legible la demo.

Uso:

    python -m uvicorn agente_cfdi.api.app:app --port 8000    # en otra terminal
    python tools/demo.py
"""

from __future__ import annotations

import os
import sys

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agente_cfdi.fuentes.configuracion import fuente_desde_entorno  # noqa: E402
from agente_cfdi.sintetico.generador import generar_lote  # noqa: E402

BASE = os.environ.get("AGENTE_CFDI_API", "http://127.0.0.1:8000")

# La consola de Windows usa cp1252 por omisión y revienta con los símbolos de
# abajo. Un escenario de demo que muera con UnicodeEncodeError a media grabación
# es peor que no tenerlo, y quien lo corra no tiene por qué configurar su
# terminal primero. Mismo criterio que en `verificar_prueba.py`.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# Los mismos valores con los que `fuente_desde_entorno` construye el lote
# sintético. Si cambian allá, cambian aquí — están juntos a propósito.
SEMILLA = int(os.environ.get("AGENTE_CFDI_SEMILLA", "20260814"))
CANTIDAD = 40


def main() -> int:
    fuente = fuente_desde_entorno()
    lote = generar_lote(cantidad=CANTIDAD, semilla=SEMILLA, con_cesion_duplicada=True)

    plantadas = {d.uuid: d.clase for d in getattr(fuente, "desviaciones", ())}
    print(f"Fuente de libros : {fuente.descripcion}")
    print(f"Lote             : {len(lote)} CFDI, semilla {SEMILLA}")
    print(f"Desviaciones plantadas: {len(plantadas)}\n")

    cliente = httpx.Client(base_url=BASE, timeout=60)
    print("salud →", cliente.get("/salud").json())

    archivos = [
        ("archivos", (f"{c.uuid}.xml", c.a_xml().encode("utf-8"), "application/xml"))
        for c in lote.comprobantes
    ]
    ingesta = cliente.post("/ingesta", files=archivos).json()
    print(
        f"\ningesta → auditados={ingesta['auditados']} "
        f"rechazados={ingesta['rechazados']} hallazgos={ingesta['hallazgos']}"
    )

    # El lote trae el mismo folio dos veces (escenario de cesión duplicada). El
    # segundo se rechaza en la ingesta, y en los libros ese folio quedó
    # registrado dos veces — un ingreso contado doble, que es un hallazgo real.
    duplicado = lote.uuid_duplicado
    if duplicado:
        rechazo = [f for f in ingesta["fallas"] if f["uuid"] == duplicado]
        if not rechazo:
            print(f"  ✗ el folio duplicado {duplicado[:8]}… entró al lote sin objeción")
            return 1
        print(f"  ✓ folio duplicado rechazado en la ingesta: {rechazo[0]['detalle']}")
        plantadas = {**plantadas, duplicado: "monto_distinto"}

    encontradas = {
        r["uuid"]: r["veredicto"] for r in ingesta["registros"] if r["veredicto"] != "respaldado"
    }
    if encontradas == plantadas:
        print(f"  ✓ el auditor encontró exactamente las {len(plantadas)} desviaciones esperadas")
    else:
        print("  ✗ lo encontrado NO coincide con lo esperado")
        print(f"    esperadas  : {plantadas}")
        print(f"    encontradas: {encontradas}")
        return 1

    for uuid, clase in plantadas.items():
        detalle = next(r for r in ingesta["registros"] if r["uuid"] == uuid)
        print(
            f"    {uuid[:8]}… {clase}: CFDI {detalle['monto_del_cfdi']} "
            f"vs libros {detalle['monto_en_libros']}"
        )

    # --- doble cesión -------------------------------------------------------
    limpio = next(r for r in ingesta["registros"] if r["veredicto"] == "respaldado")
    cuerpo = {
        "uuid": limpio["uuid"],
        "financiador": "Banco Norte",
        "total": limpio["monto_del_cfdi"],
        "moneda": "MXN",
    }

    primera = cliente.post("/cesiones", json=cuerpo)
    print(f"\ncesión a Banco Norte      → {primera.status_code} {primera.json()['motivo']}")

    reintento = cliente.post("/cesiones", json=cuerpo)
    print(
        f"reintento de Banco Norte  → {reintento.status_code} "
        f"repetida={reintento.json()['repetida']} (un timeout de red no es fraude)"
    )

    segunda = cliente.post("/cesiones", json={**cuerpo, "financiador": "Factor Sur"})
    print(
        f"cesión a Factor Sur       → {segunda.status_code} {segunda.json()['motivo']} "
        f"(previa en posición {segunda.json()['posicion_de_la_cesion_previa']})"
    )

    # --- ceder algo con hallazgos advierte ----------------------------------
    sucio_uuid = next(iter(plantadas))
    sucio = next(r for r in ingesta["registros"] if r["uuid"] == sucio_uuid)
    con_hallazgo = cliente.post(
        "/cesiones",
        json={
            "uuid": sucio_uuid,
            "financiador": "Factor Sur",
            "total": sucio["monto_del_cfdi"],
            "moneda": "MXN",
        },
    ).json()
    print(f"\ncesión de un folio con hallazgo → {con_hallazgo['veredicto']}")
    print(f"  advertencia: {con_hallazgo['advertencia']}")

    # --- anclaje y prueba de inclusión --------------------------------------
    import datetime
    import json
    import subprocess

    hoy = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    anclaje = cliente.post(f"/bitacora/anclaje?dia={hoy}").json()
    print(f"\nanclaje del {anclaje['dia']} → {anclaje['registros']} registros")
    print(f"  raíz : {anclaje['raiz']}")
    print(f"  red  : {anclaje['red']}")
    print(f"  verificable por terceros: {anclaje['verificable_por_terceros']}")

    prueba = cliente.get(f"/auditoria/prueba/{limpio['uuid']}").json()
    print(
        f"\nprueba de {limpio['uuid'][:8]}… → {len(prueba['ruta'])} hashes "
        f"para {prueba['registros_del_dia']} registros del día"
    )

    serializada = json.dumps(prueba)
    ajenos = [
        r["uuid"]
        for r in ingesta["registros"]
        if r["uuid"] != limpio["uuid"] and r["uuid"] in serializada
    ]
    if ajenos:
        print(f"  ✗ la prueba expone {len(ajenos)} folios ajenos")
        return 1
    print(f"  ✓ no expone ninguno de los otros {len(ingesta['registros']) - 1} folios de la PYME")

    archivo = "prueba_demo.json"
    with open(archivo, "w", encoding="utf-8") as salida:
        json.dump(prueba, salida, indent=2)
    print(f"\n--- verificador independiente sobre {archivo} ---")
    # El subproceso escribe directo al descriptor; sin vaciar antes, lo nuestro
    # sale después de lo suyo cuando la salida va a un archivo o a una tubería.
    sys.stdout.flush()
    subprocess.run([sys.executable, "tools/verificar_prueba.py", archivo])

    print("\nverificación de la cadena →", cliente.get("/bitacora/verificacion").json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
