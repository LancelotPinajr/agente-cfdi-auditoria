"""RFC sintéticos que no pueden pertenecer a una persona real (tarea 1.15).

Un RFC aleatorio **es el RFC de alguien**. `ABC850612QW3` no es una cadena
inventada: es un contribuyente con nombre, domicilio y obligaciones. Publicarlo
en un video de YouTube junto a montos y plazos de cobro es difundir un dato
personal patrimonial de un tercero que nunca lo consintió.

La solución está explicada en `docs/datos-sinteticos.md`. En resumen: se fija la
porción de fecha del RFC en `000000`, que el esquema de CFDI 4.0 acepta y el SAT
no puede haber asignado nunca.
"""

from __future__ import annotations

import random
import re

# Patrón `tdCFDI:t_RFC` del esquema de CFDI 4.0, tal cual. El lector y las
# pruebas validan contra este mismo patrón.
PATRON_RFC = re.compile(r"^[A-ZÑ&]{3,4}[0-9]{2}[0-1][0-9][0-3][0-9][A-Z0-9]{2}[0-9A]$")

# La fecha imposible. El SAT construye el RFC con la fecha de constitución de la
# persona moral o de nacimiento de la persona física; no existe el día cero del
# mes cero. El esquema, en cambio, solo verifica clases de caracteres —
# `[0-1][0-9]` acepta `00` y `[0-3][0-9]` también— así que el XML valida.
#
# Es la única propiedad de la que se puede afirmar colisión imposible. Un
# prefijo de letras "raro" no sirve: cualquier terna de letras puede tocarle a
# una empresa real.
FECHA_IMPOSIBLE = "000000"

# RFC genéricos reservados por el SAT. Estos sí son públicos y de uso previsto.
RFC_PUBLICO_EN_GENERAL = "XAXX010101000"
RFC_RESIDENTE_EXTRANJERO = "XEXX010101000"

_LETRAS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_HOMOCLAVE = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
_DIGITO_VERIFICADOR = "0123456789A"


class RFCInseguro(ValueError):
    """Un RFC generado podría pertenecer a una persona real."""


def rfc_persona_moral(rng: random.Random) -> str:
    """RFC de 12 posiciones para una persona moral sintética."""
    return _construir(rng, longitud_alfabetica=3)


def rfc_persona_fisica(rng: random.Random) -> str:
    """RFC de 13 posiciones para una persona física sintética."""
    return _construir(rng, longitud_alfabetica=4)


def _construir(rng: random.Random, longitud_alfabetica: int) -> str:
    letras = "".join(rng.choice(_LETRAS) for _ in range(longitud_alfabetica))
    homoclave = "".join(rng.choice(_HOMOCLAVE) for _ in range(2))
    verificador = rng.choice(_DIGITO_VERIFICADOR)
    generado = f"{letras}{FECHA_IMPOSIBLE}{homoclave}{verificador}"

    # Cinturón y tirantes: la propiedad que hace seguro este módulo se verifica
    # aquí, no solo en las pruebas. Un cambio descuidado en la construcción no
    # debe poder producir un RFC atribuible en silencio.
    if not es_sintetico(generado):
        raise RFCInseguro(
            f"'{generado}' no cumple la marca de RFC sintético; no se emite"
        )
    return generado


def es_sintetico(rfc: str) -> bool:
    """¿Este RFC lleva la marca que garantiza que nadie lo tiene asignado?

    Los genéricos del SAT cuentan como seguros: son públicos por diseño.
    """
    if rfc in (RFC_PUBLICO_EN_GENERAL, RFC_RESIDENTE_EXTRANJERO):
        return True
    if not PATRON_RFC.match(rfc):
        return False
    return _porcion_de_fecha(rfc) == FECHA_IMPOSIBLE


def es_estructuralmente_valido(rfc: str) -> bool:
    """¿Cumple el patrón `t_RFC` del esquema de CFDI 4.0?"""
    return bool(PATRON_RFC.match(rfc))


def _porcion_de_fecha(rfc: str) -> str:
    # 3 letras (moral) o 4 (física); la fecha son las 6 posiciones siguientes.
    inicio = 4 if len(rfc) == 13 else 3
    return rfc[inicio : inicio + 6]
