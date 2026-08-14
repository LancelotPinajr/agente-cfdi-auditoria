"""Elegir la fuente de libros por configuración, no por código (tarea 1.17).

El criterio de aceptación es que cambiar entre la fuente sintética y la real
«sea configuración, no reescritura». Esto es esa configuración.

Cruzar hacia datos reales **no es voltear esta bandera**: antes se exige
consentimiento expreso del contribuyente (LFPDPPP art. 8), minimización según el
contrato del expediente y retención conforme al CFF art. 30. La bandera es el
último paso, no el único — ver `docs/datos-sinteticos.md` §6.
"""

from __future__ import annotations

import os
from typing import Mapping

from ..sintetico.generador import generar_lote
from .cord_fiscal import ClienteCordFiscal
from .protocolo import ErrorDeFuente, FuenteDeLibros
from .sintetica import ContabilidadSintetica

VARIABLE = "AGENTE_CFDI_FUENTE"
SINTETICA = "sintetica"
CORD_FISCAL = "cord_fiscal"


class ConfiguracionInvalida(ValueError):
    """La fuente no se pudo construir con lo que hay en el entorno."""


def fuente_desde_entorno(entorno: Mapping[str, str] | None = None) -> FuenteDeLibros:
    """Construye la fuente de libros a partir de variables de entorno.

    | Variable | Para qué |
    |---|---|
    | `AGENTE_CFDI_FUENTE` | `sintetica` (por omisión) o `cord_fiscal` |
    | `CORD_FISCAL_URL` | base de la API, p. ej. `https://api.cordgroup.cloud` |
    | `CORD_FISCAL_TOKEN` | JWT del agente **para esa PYME** |
    | `AGENTE_CFDI_SEMILLA` | semilla del lote sintético |

    El valor por omisión es la fuente sintética a propósito: quien clona el repo
    y no configura nada obtiene una demo que corre, no una excepción de
    credenciales. Y equivocarse hacia datos sintéticos es inofensivo; hacia
    datos reales, no.
    """
    entorno = entorno if entorno is not None else os.environ
    elegida = entorno.get(VARIABLE, SINTETICA).strip().lower()

    if elegida == SINTETICA:
        semilla = _entero(entorno.get("AGENTE_CFDI_SEMILLA"), predeterminado=20260814)
        return ContabilidadSintetica(
            lote=generar_lote(cantidad=40, semilla=semilla, con_cesion_duplicada=True),
            sin_respaldo=(3,),
            monto_alterado=(11,),
        )

    if elegida == CORD_FISCAL:
        base_url = (entorno.get("CORD_FISCAL_URL") or "").strip()
        token = (entorno.get("CORD_FISCAL_TOKEN") or "").strip()
        faltantes = [
            nombre
            for nombre, valor in (("CORD_FISCAL_URL", base_url), ("CORD_FISCAL_TOKEN", token))
            if not valor
        ]
        if faltantes:
            raise ConfiguracionInvalida(
                f"{VARIABLE}={CORD_FISCAL} exige {', '.join(faltantes)}. "
                f"El token va en Secret Manager, nunca en el repo."
            )
        if not base_url.startswith("https://") and "localhost" not in base_url:
            # El token viaja en cada petición: sobre HTTP plano se regala.
            raise ConfiguracionInvalida(
                f"CORD_FISCAL_URL debe ser https:// fuera de localhost (llegó {base_url!r})"
            )
        return ClienteCordFiscal(base_url=base_url, token=token)

    raise ConfiguracionInvalida(
        f"{VARIABLE}={elegida!r} no se reconoce; usa {SINTETICA!r} o {CORD_FISCAL!r}"
    )


def _entero(crudo: str | None, *, predeterminado: int) -> int:
    if not crudo:
        return predeterminado
    try:
        return int(crudo)
    except ValueError as exc:
        raise ConfiguracionInvalida(f"AGENTE_CFDI_SEMILLA={crudo!r} no es un entero") from exc


__all__ = [
    "CORD_FISCAL",
    "ConfiguracionInvalida",
    "ErrorDeFuente",
    "FuenteDeLibros",
    "SINTETICA",
    "VARIABLE",
    "fuente_desde_entorno",
]
