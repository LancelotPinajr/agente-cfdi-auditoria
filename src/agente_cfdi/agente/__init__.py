"""Lo que el agente ADK puede hacer, sin depender de ADK.

Este paquete no importa `google.adk` a propósito: así el CI —que instala solo
lo declarado en `pyproject.toml`— puede probar las herramientas. El cableado con
ADK vive en `agente/agent.py`, en la raíz del repo.
"""

from .herramientas import (
    HERRAMIENTAS,
    consultar_folio,
    estado_de_integridad,
    resumen_de_la_bitacora,
)

__all__ = [
    "HERRAMIENTAS",
    "consultar_folio",
    "estado_de_integridad",
    "resumen_de_la_bitacora",
]
