"""El ciclo que corre solo, sin que nadie lo toque (tarea 2.14).

## Qué falta para que «corra solo» sea cierto

El criterio pide *lote de CFDI → auditoría → detección de duplicado →
expediente → anclaje, sin intervención manual en ningún paso*. Hasta hoy el
anclaje ya era automático —lo dispara Cloud Scheduler— pero **el lote lo subía
una persona**. Un ciclo cuyo primer paso necesita a alguien con `curl` no es
autónomo: es un cierre automático de un trabajo manual.

Esto cierra ese hueco. Un segundo job diario llama aquí unas horas antes del
cierre, y este módulo hace lo que haría la PYME: entregar las facturas del día.

## El lote es sintético, y eso se dice

No se inventan facturas para que parezcan reales. El lote sale del generador
—los mismos RFC con `000000` en la porción de fecha, que el SAT no puede haber
asignado nunca— y cada respuesta lo declara en `origen_del_lote`. La decisión
está en el README: la demo corre con datos sintéticos por diseño, no por
concesión.

Lo que el ciclo demuestra **no** es que existan facturas: es que el sistema las
audita, las encadena, detecta el duplicado y publica la raíz sin que nadie
intervenga. Esa parte no es simulada.

## Por qué cada paso se registra

Antes de esto, la única huella de un cierre era la línea de acceso de uvicorn:
un `200` sin decir qué ancló. La constancia vivía en la bitácora, que en Cloud
Run está en `/tmp` y se borra al reciclar la instancia — la del 21-ago se perdió
así. Lo que no queda en el log no ocurrió, para efectos de demostrarlo.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

REGISTRO = logging.getLogger("agente_cfdi.ciclo")


def anotar(evento: str, **campos: object) -> None:
    """Escribe una línea JSON en stdout para que Cloud Logging la indexe.

    Se usa `print` y no el `logging` de Python a propósito: Cloud Run interpreta
    cada línea de stdout que sea JSON válido como `jsonPayload`, y así los campos
    quedan consultables uno por uno. Con `logging.info("...")` todo cae en un
    `textPayload` de texto plano que sólo se puede buscar con subcadenas.
    """
    linea = {
        "evento": evento,
        "momento": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **campos,
    }
    print(json.dumps(linea, ensure_ascii=False, default=str), flush=True)


def semilla_configurada() -> int:
    """La misma semilla que usa la fuente de libros.

    No es un detalle cosmético. `fuente_desde_entorno` construye los libros
    sintéticos con `generar_lote(semilla=...)`, así que un lote generado con otra
    semilla contendría folios que los libros no conocen y **todo saldría
    `sin_respaldo`** — no porque el auditor falle, sino porque se le está
    preguntando por facturas de otra empresa. Es la misma trampa que documenta
    `tools/demo.py` en el README.
    """
    crudo = os.environ.get("AGENTE_CFDI_SEMILLA")
    if not crudo:
        return 20260814
    try:
        return int(crudo)
    except ValueError:
        return 20260814
