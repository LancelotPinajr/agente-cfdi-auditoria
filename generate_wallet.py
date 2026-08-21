"""Genera la wallet que firma los anclajes (tareas 2.10 y 3.6).

## La llave no toca el disco

La versión anterior de este script pedía pegar la llave en un `tu_llave.txt` y
borrarlo después. Funciona hasta que no: el archivo caía en la raíz del repo, un
`git add -A` lo habría publicado, y una llave privada en un historial de git es
irrecuperable — se puede reescribir el historial, pero no se puede saber quién
ya lo clonó.

Aquí la llave nace, se manda a Secret Manager por la entrada estándar y muere
con el proceso. No queda archivo y no queda en el historial del shell, porque
viaja por una tubería y no como argumento de la línea de comandos.

Lo único que sale a pantalla es la **dirección pública**, que es lo que hace
falta para pedir el faucet y para comprobar a nombre de quién quedó el contrato.

Uso:

    python generate_wallet.py --subir       # genera, sube y reporta la dirección
    python generate_wallet.py --direccion   # qué dirección tiene el secreto actual
    python generate_wallet.py --solo-llave  # imprime la llave (para tuberías a mano)
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

from eth_account import Account

PROYECTO = "project-d0428141-1b39-47af-9bc"
SECRETO = "WALLET_PRIVATE_KEY"

# El SDK de esta máquina es una instalación portátil y no está en el PATH, y hay
# dos cuentas autenticadas. Es la misma disciplina que `deploy.ps1`: fijar el
# binario y la configuración explícitamente, porque el default podría subir el
# secreto al proyecto equivocado y eso no avisa.
SDK_BIN = Path(
    os.environ.get("GCLOUD_SDK_BIN", r"D:\CORD\tools\google-cloud-sdk\bin")
)
CONFIG_POR_OMISION = r"D:\CORD\tools\gcloud-config-ricardo"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _ejecutable_gcloud() -> str:
    """Dónde está gcloud.

    En Windows el ejecutable es `gcloud.cmd`, un archivo por lotes: `subprocess`
    con `shell=False` no lo encuentra si se le pide «gcloud» a secas, y por eso
    la primera versión de esto fallaba con `WinError 2`.
    """
    nombres = ["gcloud.cmd", "gcloud.exe", "gcloud"] if os.name == "nt" else ["gcloud"]
    for nombre in nombres:
        candidato = SDK_BIN / nombre
        if candidato.exists():
            return str(candidato)
    for nombre in nombres:
        hallado = shutil.which(nombre)
        if hallado:
            return hallado
    raise SystemExit(
        f"No encontré gcloud. Lo busqué en {SDK_BIN} y en el PATH. "
        f"Si el SDK está en otro lado, fija GCLOUD_SDK_BIN."
    )


def _entorno() -> dict:
    entorno = os.environ.copy()
    entorno.setdefault("CLOUDSDK_CONFIG", CONFIG_POR_OMISION)
    return entorno


def subir(llave: str) -> None:
    """Manda la llave a Secret Manager por stdin, sin pasar por disco."""
    orden = [
        _ejecutable_gcloud(), "secrets", "versions", "add", SECRETO,
        "--data-file=-", f"--project={PROYECTO}",
    ]
    # `input=` escribe en la entrada estándar del proceso hijo. La llave nunca
    # aparece en `ps`, ni en el historial, ni en un archivo temporal.
    resultado = subprocess.run(
        orden, input=llave.encode("ascii"), capture_output=True,
        shell=False, env=_entorno(),
    )
    if resultado.returncode != 0:
        raise SystemExit(
            f"gcloud rechazó la subida:\n{resultado.stderr.decode(errors='replace')}"
        )


def direccion_del_secreto() -> str:
    """Qué dirección corresponde a la llave que hoy vive en Secret Manager."""
    resultado = subprocess.run(
        [_ejecutable_gcloud(), "secrets", "versions", "access", "latest",
         f"--secret={SECRETO}", f"--project={PROYECTO}"],
        capture_output=True, shell=False, env=_entorno(),
    )
    if resultado.returncode != 0:
        raise SystemExit(
            f"no se pudo leer el secreto:\n{resultado.stderr.decode(errors='replace')}"
        )
    return Account.from_key(resultado.stdout.decode("ascii").strip()).address


def main() -> int:
    if "--solo-llave" in sys.argv:
        # Sin salto de línea final: Secret Manager guarda los bytes tal cual y
        # un `\n` de más convierte la llave en algo que no parsea.
        cuenta = Account.create()
        llave = cuenta.key.hex()
        sys.stdout.write(llave if llave.startswith("0x") else "0x" + llave)
        return 0

    if "--direccion" in sys.argv:
        print(f"Dirección de la llave en Secret Manager: {direccion_del_secreto()}")
        return 0

    if "--subir" not in sys.argv:
        print(__doc__)
        print("Sin --subir no hago nada: generar una wallet y no guardarla en el")
        print("mismo paso es la forma más fácil de perderla.")
        return 1

    cuenta = Account.create()
    llave = cuenta.key.hex()
    subir(llave if llave.startswith("0x") else "0x" + llave)

    print("=" * 68)
    print("  Wallet generada y guardada en Secret Manager")
    print("=" * 68)
    print(f"  Secreto           : {SECRETO}")
    print(f"  Dirección pública : {cuenta.address}")
    print("=" * 68)
    print()
    print("  La llave privada no se mostró, no se escribió en disco y ya no")
    print("  existe fuera de Secret Manager. Si necesitas la dirección otra vez:")
    print("      python generate_wallet.py --direccion")
    print()
    print("  Siguiente paso: fondear esa dirección en Base Sepolia (faucet")
    print("  gratuito) para poder desplegar el contrato de anclaje.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
