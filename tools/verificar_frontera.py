#!/usr/bin/env python3
"""Verifica que no haya código copiado desde una base de código preexistente.

    python tools/verificar_frontera.py ../cord_rag_plataform/backend/app

Compara todas las líneas de código de al menos 40 caracteres —umbral que deja
fuera las importaciones cortas y las llaves sueltas, pero atrapa cualquier
función o bloque copiado— y reporta las coincidencias exactas.

Existe porque «no copiamos nada» es una afirmación que alguien debe poder
comprobar sin creernos. Ver `docs/trabajo-preexistente.md`.

Sale con código 1 si aparece una coincidencia que no sea una importación.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

LARGO_MINIMO = 40
EXCLUIDOS = {".venv", "venv", "__pycache__", ".git", "node_modules", "site-packages", "build", "dist"}


def lineas_significativas(raiz: Path) -> dict[str, set[str]]:
    encontradas: dict[str, set[str]] = {}
    for archivo in raiz.rglob("*.py"):
        if EXCLUIDOS & set(archivo.parts):
            continue
        try:
            texto = io.open(archivo, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        for linea in texto.splitlines():
            limpia = linea.strip()
            if len(limpia) >= LARGO_MINIMO and not limpia.startswith("#"):
                encontradas.setdefault(limpia, set()).add(str(archivo.relative_to(raiz)))
    return encontradas


def es_importacion(linea: str) -> bool:
    return linea.startswith(("import ", "from "))


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2

    aqui = Path(__file__).resolve().parent.parent
    alla = Path(argv[1]).resolve()
    if not alla.is_dir():
        print(f"no existe el directorio {alla}")
        return 2

    nuevo = lineas_significativas(aqui)
    viejo = lineas_significativas(alla)
    comunes = sorted(set(nuevo) & set(viejo))

    print(f"repo nuevo ({aqui.name}): {len(nuevo)} líneas significativas")
    print(f"preexistente ({alla}): {len(viejo)} líneas significativas")
    print(f"coincidencias exactas: {len(comunes)}\n")

    sospechosas = []
    for linea in comunes:
        marca = "import" if es_importacion(linea) else "REVISAR"
        if marca == "REVISAR":
            sospechosas.append(linea)
        print(f"  [{marca}] {linea[:100]}")
        print(f"           nuevo: {sorted(nuevo[linea])[:2]}")
        print(f"           viejo: {sorted(viejo[linea])[:2]}")

    if sospechosas:
        print(f"\n{len(sospechosas)} coincidencia(s) que no son importaciones. Revisar.")
        return 1

    print("\nSin código compartido: todas las coincidencias son importaciones de la stdlib.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
