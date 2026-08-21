"""Compila el contrato de anclaje y deja el artefacto versionado.

## Por qué el artefacto se versiona

`contratos/AnclaDeRaices.json` lleva el ABI y el bytecode ya compilados. Eso
permite desplegar sin compilador instalado, y —más importante— deja constancia
de **qué bytecode exacto** se publicó en la cadena. Un tercero que quiera
comprobar que el contrato desplegado corresponde al fuente de este repo puede
recompilar con la misma versión de solc y los mismos ajustes de optimización, y
comparar.

Si el `.sol` cambia y el `.json` no se regenera, se despliega código viejo sin
que nada avise. Por eso este script imprime el hash del fuente.

Uso:

    python tools/compilar_contrato.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
FUENTE = RAIZ / "contratos" / "AnclaDeRaices.sol"
ARTEFACTO = RAIZ / "contratos" / "AnclaDeRaices.json"

VERSION_SOLC = "0.8.24"
RUNS = 200

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    try:
        import solcx
    except ImportError:
        raise SystemExit(
            "falta py-solc-x. Instálalo con:\n"
            "  pip install py-solc-x"
        )

    if VERSION_SOLC not in {str(v) for v in solcx.get_installed_solc_versions()}:
        print(f"instalando solc {VERSION_SOLC}...")
        solcx.install_solc(VERSION_SOLC)

    fuente = FUENTE.read_text(encoding="utf-8")
    huella = hashlib.sha256(fuente.encode("utf-8")).hexdigest()

    salida = solcx.compile_source(
        fuente,
        output_values=["abi", "bin"],
        solc_version=VERSION_SOLC,
        optimize=True,
        optimize_runs=RUNS,
    )
    clave = next(k for k in salida if k.endswith(":AnclaDeRaices"))
    compilado = salida[clave]

    ARTEFACTO.write_text(
        json.dumps(
            {
                "nombre": "AnclaDeRaices",
                "solc": VERSION_SOLC,
                "optimizado": {"habilitado": True, "runs": RUNS},
                "sha256_del_fuente": huella,
                "abi": compilado["abi"],
                "bytecode": "0x" + compilado["bin"],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"fuente    : {FUENTE.name}  (sha256 {huella[:16]}…)")
    print(f"solc      : {VERSION_SOLC}, optimizado con {RUNS} runs")
    print(f"bytecode  : {len(compilado['bin']) // 2} bytes")
    print(f"artefacto : {ARTEFACTO.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
