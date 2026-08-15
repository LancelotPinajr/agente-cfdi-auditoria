"""El RFC como valor del dominio.

Vive aquí, y no en el paquete sintético, porque el lector de producción lo
necesita y el generador de pruebas no puede ser una dependencia de nada que
corra de verdad.
"""

from __future__ import annotations

import re

# Patrón `tdCFDI:t_RFC` del esquema de CFDI 4.0, tal cual lo publica el SAT.
# Nótese lo laxo que es: solo verifica clases de caracteres, no que la fecha
# exista ni que la homoclave corresponda. Es la puerta que el generador
# sintético aprovecha — ver `docs/datos-sinteticos.md`.
PATRON_RFC = re.compile(r"^[A-ZÑ&]{3,4}[0-9]{2}[0-1][0-9][0-3][0-9][A-Z0-9]{2}[0-9A]$")

# RFC genéricos reservados por el SAT: públicos por diseño, no son de nadie.
RFC_PUBLICO_EN_GENERAL = "XAXX010101000"
RFC_RESIDENTE_EXTRANJERO = "XEXX010101000"


def es_estructuralmente_valido(rfc: str) -> bool:
    """¿Cumple el patrón `t_RFC` del esquema de CFDI 4.0?"""
    return bool(PATRON_RFC.match(rfc))


def porcion_de_fecha(rfc: str) -> str:
    """Las 6 posiciones de fecha: 3 letras si es persona moral, 4 si es física."""
    inicio = 4 if len(rfc) == 13 else 3
    return rfc[inicio : inicio + 6]
