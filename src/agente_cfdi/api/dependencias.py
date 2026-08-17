"""De dónde saca la API su bitácora y su fuente de libros.

## Una conexión por petición

SQLite prohíbe compartir una conexión entre hilos, y el servidor atiende en
varios. Cada petición abre la suya contra el mismo archivo y la cierra al
terminar; la serialización entre peticiones la da `BEGIN IMMEDIATE` dentro del
almacén, no un candado de Python — que no serviría con más de un proceso.

El `timeout` no es decorativo: es cuánto espera una petición a que otra suelte
el candado de escritura antes de rendirse. Con cero, dos cesiones simultáneas se
caerían con «database is locked» en vez de resolverse una tras otra.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Iterator

from ..bitacora.almacen import Bitacora
from ..bitacora.anclaje import Ancla, AnclaSimulada
from ..fuentes.configuracion import fuente_desde_entorno
from ..fuentes.protocolo import FuenteDeLibros

VARIABLE_RUTA = "AGENTE_CFDI_BITACORA"
VARIABLE_INQUILINO = "AGENTE_CFDI_INQUILINO"

RUTA_PREDETERMINADA = "bitacora.db"
INQUILINO_PREDETERMINADO = "DEMO000000XX0"
"""RFC con `000000` en la porción de fecha: el SAT no pudo asignarlo nunca —no
existe el día cero del mes cero— así que no coincide con el de nadie real."""

ESPERA_POR_EL_CANDADO = 15.0


def ruta_de_la_bitacora() -> Path:
    return Path(os.environ.get(VARIABLE_RUTA, RUTA_PREDETERMINADA))


def inquilino_configurado() -> str:
    """El contribuyente de este despliegue.

    Sale de la configuración y **nunca** de un encabezado de la petición: un
    despliegue ya está atado a una PYME porque su token de CØRD Fiscal lo está.
    Dejar que quien llama elija el inquilino permitiría escribir en la cadena de
    cualquiera con cambiar una cabecera.
    """
    return os.environ.get(VARIABLE_INQUILINO, INQUILINO_PREDETERMINADO).strip()


def bitacora_actual() -> Iterator[Bitacora]:
    conexion = sqlite3.connect(
        ruta_de_la_bitacora(), timeout=ESPERA_POR_EL_CANDADO, check_same_thread=False
    )
    try:
        bitacora = Bitacora(conexion, inquilino=inquilino_configurado())
        bitacora.migrar()
        yield bitacora
    finally:
        conexion.close()


def fuente_actual() -> FuenteDeLibros:
    return fuente_desde_entorno()


def ancla_actual() -> Ancla:
    """Dónde se publica la raíz del día.

    Hoy siempre simulada. Conectar una cadena real es sustituir esta función por
    otra que devuelva una implementación del mismo protocolo — nada más del
    sistema tiene que enterarse. La bandera `verificable_por_terceros` viaja
    hasta la respuesta HTTP para que la diferencia nunca quede escondida.
    """
    return AnclaSimulada(etiqueta=os.environ.get("AGENTE_CFDI_ANCLA", "local"))
