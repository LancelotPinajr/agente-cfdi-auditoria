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
from contextlib import contextmanager
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


@contextmanager
def abrir_bitacora() -> Iterator[Bitacora]:
    """Abre la bitácora fuera de FastAPI.

    Existe porque las herramientas del agente ADK corren sin inyección de
    dependencias y necesitan exactamente la misma configuración —misma ruta,
    mismo inquilino— que los endpoints. Duplicar esa lectura del entorno sería
    la forma más fácil de que el agente acabara consultando otra bitácora que la
    que el servicio escribe.
    """
    conexion = sqlite3.connect(
        ruta_de_la_bitacora(), timeout=ESPERA_POR_EL_CANDADO, check_same_thread=False
    )
    try:
        bitacora = Bitacora(conexion, inquilino=inquilino_configurado())
        bitacora.migrar()
        yield bitacora
    finally:
        conexion.close()


def bitacora_actual() -> Iterator[Bitacora]:
    with abrir_bitacora() as bitacora:
        yield bitacora


def fuente_actual() -> FuenteDeLibros:
    return fuente_desde_entorno()


VARIABLE_RED = "AGENTE_CFDI_ANCLA_RED"
VARIABLE_CONTRATO = "AGENTE_CFDI_ANCLA_CONTRATO"


def ancla_actual() -> Ancla:
    """Dónde se publica la raíz del día.

    Sale de la configuración, y el default es la simulada **a propósito**:
    equivocarse por omisión tiene que llevar a un ancla que se declara falsa, no
    a una que parece real. La bandera `verificable_por_terceros` viaja hasta la
    respuesta HTTP para que la diferencia nunca quede escondida.

    Para anclar de verdad hacen falta las tres cosas a la vez: la red, la
    dirección del contrato y una llave. Si falta cualquiera, **no se degrada en
    silencio a simulada**: se levanta. Un despliegue que cree estar anclando en
    mainnet y esté firmando constancias de mentira es exactamente el escenario
    que este proyecto existe para no producir.
    """
    red = os.environ.get(VARIABLE_RED, "").strip()
    if not red:
        return AnclaSimulada(etiqueta=os.environ.get("AGENTE_CFDI_ANCLA", "local"))

    contrato = os.environ.get(VARIABLE_CONTRATO, "").strip()
    if not contrato:
        raise RuntimeError(
            f"{VARIABLE_RED}={red!r} pide anclar en una cadena real, pero "
            f"{VARIABLE_CONTRATO} está vacía: no hay dónde publicar la raíz"
        )

    # Los import van aquí y no arriba porque `web3` solo hace falta cuando se
    # ancla de verdad: quien corre las pruebas o levanta la demo con el ancla
    # simulada no tiene por qué instalarlo.
    from ..bitacora.ancla_evm import AnclaEVM
    from ..bitacora.llaves import proveedor_desde_entorno

    return AnclaEVM(
        nombre_de_red=red,
        contrato=contrato,
        llave=proveedor_desde_entorno(),
        rpc=os.environ.get("AGENTE_CFDI_ANCLA_RPC") or None,
    )
