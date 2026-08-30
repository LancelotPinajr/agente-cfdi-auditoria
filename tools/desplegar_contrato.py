"""Despliega el contrato de anclaje en una cadena EVM (tareas 2.7 y 3.6).

## Se despliega una vez por red, no en cada release

El contrato es inmutable y guarda el historial de raíces. Redesplegarlo crea uno
**vacío**: las raíces publicadas antes seguirían en la cadena, pero en una
dirección que el sistema ya no consulta, y las pruebas de inclusión emitidas
apuntarían a un contrato huérfano. Por eso el script exige confirmación explícita
y reporta la dirección para que quede escrita en la configuración.

## La llave sale de Secret Manager, no del entorno

Se lee con `gcloud` en el momento, igual que `generate_wallet.py --direccion`.
No se pide como argumento ni se acepta desde un archivo: una llave en la línea
de comandos queda en el historial del shell y en la lista de procesos.

Uso:

    python tools/desplegar_contrato.py --red base-sepolia
    python tools/desplegar_contrato.py --red base --confirmo-mainnet
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ))

from eth_account import Account  # noqa: E402
from web3 import Web3  # noqa: E402

from agente_cfdi.bitacora.anclaje import EXPLORADORES  # noqa: E402
from agente_cfdi.bitacora.ancla_evm import REDES  # noqa: E402
from generate_wallet import (  # noqa: E402
    PROYECTO,
    SECRETO,
    _ejecutable_gcloud,
    _entorno,
)

ARTEFACTO = RAIZ / "contratos" / "AnclaDeRaices.json"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def llave_privada() -> str:
    """La llave del anclaje, leída de Secret Manager en este instante."""
    resultado = subprocess.run(
        [_ejecutable_gcloud(), "secrets", "versions", "access", "latest",
         f"--secret={SECRETO}", f"--project={PROYECTO}"],
        capture_output=True, shell=False, env=_entorno(),
    )
    if resultado.returncode != 0:
        raise SystemExit(
            f"no se pudo leer {SECRETO}:\n"
            f"{resultado.stderr.decode(errors='replace')}"
        )
    return resultado.stdout.decode("ascii").strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--red", required=True, choices=sorted(REDES))
    parser.add_argument(
        "--confirmo-mainnet",
        action="store_true",
        help="obligatorio en redes reales: el gas se paga con dinero de verdad",
    )
    args = parser.parse_args()

    red = REDES[args.red]
    es_testnet = "sepolia" in args.red or "amoy" in args.red
    if not es_testnet and not args.confirmo_mainnet:
        raise SystemExit(
            f"{args.red} es una red real y el gas se paga con dinero. "
            f"Si es lo que quieres, repite con --confirmo-mainnet."
        )

    if not ARTEFACTO.exists():
        raise SystemExit(
            f"falta {ARTEFACTO}. Compila primero:\n"
            f"  python tools/compilar_contrato.py"
        )
    artefacto = json.loads(ARTEFACTO.read_text(encoding="utf-8"))

    w3 = Web3(Web3.HTTPProvider(
        os.environ.get("AGENTE_CFDI_ANCLA_RPC") or red.rpc,
        request_kwargs={"timeout": 60},
    ))
    cuenta = Account.from_key(llave_privada())

    saldo = w3.eth.get_balance(cuenta.address)
    print(f"Red        : {args.red}  (chain {red.chain_id})")
    print(f"Cuenta     : {cuenta.address}")
    print(f"Saldo      : {w3.from_wei(saldo, 'ether')} ETH")
    print(f"solc       : {artefacto['solc']}  ({len(artefacto['bytecode']) // 2 - 1} bytes)")

    if saldo == 0:
        raise SystemExit(
            "\nLa cuenta no tiene fondos: no hay con qué pagar el gas.\n"
            "En testnet pide un faucet; en mainnet transfiere unos dólares."
        )

    contrato = w3.eth.contract(abi=artefacto["abi"], bytecode=artefacto["bytecode"])
    transaccion = contrato.constructor().build_transaction({
        "from": cuenta.address,
        "nonce": w3.eth.get_transaction_count(cuenta.address, "pending"),
        "chainId": red.chain_id,
    })
    costo = transaccion["gas"] * transaccion.get("maxFeePerGas", 0)
    print(f"Gas máximo : {w3.from_wei(costo, 'ether')} ETH")

    if costo > saldo:
        raise SystemExit(
            f"\nEl gas estimado ({w3.from_wei(costo, 'ether')} ETH) supera el "
            f"saldo. Fondea más antes de reintentar."
        )

    firmada = cuenta.sign_transaction(transaccion)
    hash_tx = w3.eth.send_raw_transaction(firmada.raw_transaction)
    print(f"\nEnviada    : {hash_tx.hex()}")
    print("Esperando confirmación...")

    recibo = w3.eth.wait_for_transaction_receipt(hash_tx, timeout=300)
    if recibo["status"] != 1:
        raise SystemExit("la transacción revirtió: el contrato NO quedó desplegado")

    direccion = recibo["contractAddress"]

    # La dirección se imprime ANTES de verificar nada. En el primer despliegue
    # real, la comprobación de abajo reventó por un nodo sin sincronizar y el
    # traceback se llevó por delante la única línea que importaba: el contrato
    # estaba desplegado y el operador no tenía forma de saber dónde.
    print()
    print(f"Contrato desplegado en: {direccion}")
    print(f"Transaccion           : {hash_tx.hex()}")

    desplegado = w3.eth.contract(address=direccion, abi=artefacto["abi"])

    # Comprobar el dueño no es ceremonia: si no es esta cuenta, el job diario
    # nunca podrá anclar y el fallo aparecería a las 23:59 de algún día.
    #
    # Se reintenta porque los RPC públicos están balanceados entre varios nodos
    # y el que atienda la consulta puede no haber visto todavía el bloque que
    # acaba de minarse. No es que el contrato no exista: es que ese nodo aún no
    # se entera.
    dueno = None
    for intento in range(6):
        try:
            dueno = desplegado.functions.dueno().call()
            break
        except Exception:
            if intento == 5:
                raise SystemExit(
                    f"El contrato quedó en {direccion} pero el nodo no lo ve "
                    f"todavía. No es un fallo del despliegue: reintenta la "
                    f"comprobación en un minuto: "
                    f"  python tools/desplegar_contrato.py --comprobar {direccion} "
                    f"--red {args.red}"
                )
            time.sleep(5)

    if dueno.lower() != cuenta.address.lower():
        raise SystemExit(
            f"el contrato quedó a nombre de {dueno}, no de {cuenta.address}"
        )

    plantilla = EXPLORADORES.get(args.red)
    print()
    print("=" * 70)
    print("  Contrato desplegado")
    print("=" * 70)
    print(f"  Dirección  : {direccion}")
    print(f"  Dueño      : {dueno}  (coincide)")
    print(f"  Bloque     : {recibo['blockNumber']}")
    print(f"  Gas usado  : {recibo['gasUsed']}")
    if plantilla:
        print(f"  Explorador : {plantilla.format(hash_tx.hex())}")
    print("=" * 70)
    print()
    print("  Para que el sistema ancle de verdad, el despliegue necesita:")
    print(f"    AGENTE_CFDI_ANCLA_RED={args.red}")
    print(f"    AGENTE_CFDI_ANCLA_CONTRATO={direccion}")
    print(f"    AGENTE_CFDI_LLAVE_SECRETO={SECRETO}")
    print()
    print("  Anótala también en el README: sin la dirección publicada, un")
    print("  tercero no puede comprobar las raíces por su cuenta.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
