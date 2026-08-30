"""Lee del contrato la raíz publicada de un día. El último paso de la verificación.

`verificar_prueba.py` termina diciendo que falta un paso y que ese no depende de
nosotros: comprobar que la raíz a la que llega el camino de Merkle es de verdad
la que está en la red. Esto lo hace, y lo hace **sin tocar nuestro servicio**:
habla directamente con un nodo público de Base por JSON-RPC.

Igual que el verificador, **no importa una sola línea del proyecto**: solo
`json`, `sys` y `urllib`, todos de la biblioteca estándar. Ni siquiera `web3`.
Un financiador tiene que poder correr esto sin instalar nada.

El selector de función va escrito a mano y no calculado, porque calcularlo
exigiría keccak256, que no está en la stdlib — y meter una dependencia aquí
arruinaría justo lo que este archivo demuestra:

    keccak256("raizDelDia(string)")[:4] = fe181097

Uso:

    python tools/leer_raiz_publicada.py 2026-08-24
    python tools/leer_raiz_publicada.py 2026-08-24 <raiz-esperada-en-hex>

Con la raíz esperada devuelve 0 si coincide y 1 si no. Sin ella solo imprime lo
que haya publicado, que también sirve: un día sin anclar sale en ceros.
"""

import json
import sys
import urllib.request

RPC = "https://sepolia.base.org"
CONTRATO = "0xe76b981159307a79c77B29796F59087D6c13d974"
SELECTOR_RAIZ_DEL_DIA = "fe181097"

CERO = "0" * 64

# Misma razon que en `verificar_prueba.py`: la consola de Windows usa cp1252 por
# omision y revienta con los guiones largos de abajo. Quien corra esto no tiene
# por que configurar su terminal primero.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def raiz_publicada(dia: str) -> str:
    """Codifica a mano la llamada `raizDelDia(string)` y la manda por eth_call.

    El ABI de un `string` son tres piezas: el desplazamiento al dato (siempre 32
    aquí, porque es el único argumento), la longitud en bytes, y el contenido
    rellenado a múltiplo de 32.
    """
    crudo = dia.encode()
    datos = (
        "0x"
        + SELECTOR_RAIZ_DEL_DIA
        + "%064x" % 32
        + "%064x" % len(crudo)
        + crudo.hex().ljust(64, "0")
    )
    peticion = urllib.request.Request(
        RPC,
        data=json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_call",
                "params": [{"to": CONTRATO, "data": datos}, "latest"],
            }
        ).encode(),
        # Los RPC públicos devuelven 403 al User-Agent por omisión de urllib.
        headers={
            "Content-Type": "application/json",
            "User-Agent": "cord-verificador/1.0",
        },
    )
    with urllib.request.urlopen(peticion, timeout=60) as respuesta:
        cuerpo = json.load(respuesta)

    if "error" in cuerpo:
        raise RuntimeError(cuerpo["error"].get("message", "error del RPC"))
    return cuerpo["result"][2:]


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2

    dia = argv[0]
    esperada = argv[1].lower().removeprefix("0x") if len(argv) > 1 else None

    raiz = raiz_publicada(dia).lower()

    print(f"contrato   : {CONTRATO}  (base-sepolia)")
    print(f"dia        : {dia}")
    print(f"raiz en red: {raiz}")

    if raiz == CERO:
        print("\n[X] ese dia no tiene raiz publicada")
        return 1

    if esperada is None:
        return 0

    print(f"raiz dada  : {esperada}")
    if raiz == esperada:
        print("\n[OK] COINCIDEN — la raiz declarada es la que esta en la red")
        return 0

    print("\n[X] NO COINCIDEN")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
