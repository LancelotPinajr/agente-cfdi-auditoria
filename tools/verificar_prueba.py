"""Verificador independiente de una prueba de integridad.

**No importa una sola línea de este proyecto.** Solo `hashlib`, `json` y
`base64`, todos de la biblioteca estándar. Es deliberado: si la verificación
usara nuestro código, comprobaría que nuestro código coincide consigo mismo, que
no demuestra nada. Un financiador tiene que poder reimplementar esto desde la
especificación —son treinta líneas— y llegar al mismo resultado.

Reglas, copiadas de `docs/adr/0004-bitacora-encadenada.md`:

    hoja  = SHA256( 0x00 ‖ canónico ‖ hash_anterior )
    nodo  = SHA256( 0x01 ‖ izquierdo ‖ derecho )

Uso:

    curl -s localhost:8000/auditoria/prueba/<UUID> > prueba.json
    python tools/verificar_prueba.py prueba.json
"""

import base64
import hashlib
import json
import sys

# La consola de Windows usa cp1252 por omisión y revienta con los símbolos de
# abajo. Un verificador que muera con UnicodeEncodeError en vez de decir si la
# prueba cuadra no sirve para nada, y quien lo corra no tiene por qué configurar
# su terminal primero.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PREFIJO_HOJA = b"\x00"
PREFIJO_NODO = b"\x01"


def hoja_de(canonico: bytes, hash_anterior: bytes) -> bytes:
    return hashlib.sha256(PREFIJO_HOJA + canonico + hash_anterior).digest()


def nodo(izquierdo: bytes, derecho: bytes) -> bytes:
    return hashlib.sha256(PREFIJO_NODO + izquierdo + derecho).digest()


def raiz_desde(hoja: bytes, ruta: list) -> bytes:
    actual = hoja
    for paso in ruta:
        hermano = bytes.fromhex(paso["hermano"])
        # El lado importa: SHA256(0x01‖a‖b) no es SHA256(0x01‖b‖a).
        if paso["hermano_a_la_derecha"]:
            actual = nodo(actual, hermano)
        else:
            actual = nodo(hermano, actual)
    return actual


def main(ruta_del_archivo: str) -> int:
    with open(ruta_del_archivo, encoding="utf-8") as archivo:
        prueba = json.load(archivo)

    canonico = base64.b64decode(prueba["canonico"])
    hash_anterior = bytes.fromhex(prueba["hash_anterior"])
    raiz_declarada = bytes.fromhex(prueba["raiz"])

    print(f"Folio            : {prueba['uuid']}")
    print(f"Día              : {prueba['dia']}  ({prueba['registros_del_dia']} registros)")
    print(f"Camino           : {len(prueba['ruta'])} hashes de hermanos")
    print(f"\nRegistro (canónico):\n  {canonico.decode('utf-8', 'replace')}\n")

    # 1. La hoja se recalcula desde el contenido, no se acepta hecha. Si se
    #    aceptara, quien presenta la prueba podría entregar el hash de un nodo
    #    interno y armar un camino válido para un registro que nunca existió.
    hoja = hoja_de(canonico, hash_anterior)
    if hoja != bytes.fromhex(prueba["hoja"]):
        print("✗ el contenido NO produce la hoja declarada; el registro fue alterado")
        return 1
    print(f"✓ el contenido produce la hoja declarada  {hoja.hex()[:16]}…")

    # 2. Subir por el camino tiene que dar la raíz.
    recalculada = raiz_desde(hoja, prueba["ruta"])
    if recalculada != raiz_declarada:
        print(f"✗ el camino NO lleva a la raíz declarada")
        print(f"    recalculada: {recalculada.hex()}")
        print(f"    declarada  : {raiz_declarada.hex()}")
        return 1
    print(f"✓ el camino lleva a la raíz declarada     {recalculada.hex()[:16]}…")

    # 3. Y la raíz tiene que estar publicada donde ellos no mandan. Sin esto,
    #    todo lo anterior solo prueba que su bitácora es consistente consigo
    #    misma — que es justo lo que no hay por qué creerles.
    ancla = prueba.get("ancla")
    if ancla is None:
        print("\n⚠ la raíz NO está anclada todavía.")
        print("  Lo verificado prueba consistencia interna de su bitácora, nada más.")
        return 2
    if not ancla["verificable_por_terceros"]:
        print(f"\n⚠ el ancla es SIMULADA ({ancla['red']}).")
        print("  No está publicada en ninguna red: no se puede comprobar fuera de su sistema.")
        return 2

    print(f"\n✓ raíz anclada en {ancla['red']}")
    print(f"  referencia: {ancla['referencia']}")
    print(f"  fecha     : {ancla['anclado_en']}")
    print("\n  Falta el último paso, y ese no depende de ellos: busca esa referencia")
    print("  en la red y comprueba que la raíz publicada sea la de arriba.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
