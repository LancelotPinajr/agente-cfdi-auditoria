"""Comprueba que ADK acepta las herramientas y sabe describirlas.

## Por qué existe

Las herramientas son Python plano para que el CI pueda probarlas sin ADK — pero
eso deja un hueco: **que ADK las acepte no lo prueba nadie**. Si una firma o una
anotación no le gustan, el fallo aparece al construir el agente, es decir, al
arrancar el contenedor en Cloud Run. Nadie se enteraría hasta el despliegue.

Es exactamente la forma del bug de `python-multipart`: algo que funciona en la
máquina donde se escribió y no en el entorno donde corre.

Este script fuerza la conversión a `FunctionTool`, que es donde ADK deriva el
esquema del modelo desde los tipos y el docstring. Si eso pasa, el agente
arranca.

Uso:

    pip install -e ".[dev,agente]"
    python tools/verificar_agente.py
"""

from __future__ import annotations

import os
import sys

# `agente/` vive en la raíz del repo, no en `src/`, así que `pip install -e .`
# no lo instala: lo encuentra el contenedor porque copia todo y arranca desde
# ahí. Corriendo este script, `sys.path[0]` es `tools/`, y sin esta línea el
# import fallaría por la ruta y no por lo que queremos comprobar.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

ESPERADAS = {"estado_de_integridad", "consultar_folio", "resumen_de_la_bitacora"}

# Escribir en una bitácora append-only no se le confía a un modelo: una llamada
# alucinada dejaría un veredicto falso, firmado y permanente.
PROHIBIDAS = {"ingestar", "ceder", "registrar_cesion", "cerrar_dia", "anclar", "borrar"}


def main() -> int:
    from google.adk.tools import FunctionTool

    from agente.agent import root_agent
    from agente_cfdi.agente import HERRAMIENTAS

    print(f"Agente     : {root_agent.name}")
    print(f"Modelo     : {root_agent.model}")
    print(f"Herramientas: {len(HERRAMIENTAS)}\n")

    nombres = {h.__name__ for h in HERRAMIENTAS}
    if nombres != ESPERADAS:
        print(f"✗ el conjunto de herramientas cambió: {nombres}")
        return 1
    if nombres & PROHIBIDAS:
        print(f"✗ hay herramientas de escritura: {nombres & PROHIBIDAS}")
        return 1

    for funcion in HERRAMIENTAS:
        # Aquí es donde ADK deriva el esquema. Si la firma o el docstring no le
        # sirven, revienta — que es justo lo que queremos que pase en el CI y no
        # en el arranque del contenedor.
        herramienta = FunctionTool(funcion)
        declaracion = herramienta._get_declaration()
        if declaracion is None:
            print(f"✗ ADK no pudo describir {funcion.__name__}")
            return 1

        parametros = getattr(declaracion.parameters, "properties", None) or {}
        print(f"  ✓ {declaracion.name}({', '.join(parametros) or ''})")
        if not declaracion.description:
            print(f"    ✗ sin descripción: el modelo no sabría cuándo usarla")
            return 1

    if not root_agent.tools:
        print("\n✗ el agente se construyó SIN herramientas")
        return 1

    print(f"\n✓ ADK acepta las {len(HERRAMIENTAS)} herramientas y el agente construye")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
