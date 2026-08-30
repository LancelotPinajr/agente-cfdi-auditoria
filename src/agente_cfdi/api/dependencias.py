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
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..bitacora.almacen import Bitacora
from ..bitacora.anclaje import Ancla, AnclaSimulada
from ..bitacora.respaldo import (
    AlmacenDeRespaldo,
    Replicador,
    Restauracion,
    almacen_desde_entorno,
    restaurar_si_falta,
)
from ..fuentes.configuracion import fuente_desde_entorno
from ..fuentes.protocolo import FuenteDeLibros
from .ciclo import anotar

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


# --------------------------------------------------------------------- #
# Durabilidad: réplica y restauración (tareas 3.13 y 3.14)
# --------------------------------------------------------------------- #

_CANDADO_DE_RESPALDO = threading.Lock()
_REPLICADOR: Replicador | None = None
_ALMACEN: AlmacenDeRespaldo | None = None
_RESPALDO_RESUELTO = False
_RESTAURACION: Restauracion | None = None


def almacen_de_respaldo() -> AlmacenDeRespaldo | None:
    """El almacén configurado, resuelto una sola vez por proceso.

    Se memoriza incluso cuando es `None`: releer el entorno en cada petición
    haría que un cambio de configuración a mitad de la vida del proceso
    partiera la bitácora entre dos destinos sin que nadie lo notara.
    """
    global _ALMACEN, _RESPALDO_RESUELTO
    with _CANDADO_DE_RESPALDO:
        if not _RESPALDO_RESUELTO:
            _ALMACEN = almacen_desde_entorno()
            _RESPALDO_RESUELTO = True
        return _ALMACEN


def replicador_actual() -> Replicador | None:
    """El replicador del proceso, o `None` si no hay respaldo configurado.

    **Uno por proceso, no uno por petición.** Es lo que hace que las subidas
    pasen todas por el mismo hilo y no se reordenen; un replicador por petición
    devolvería exactamente el problema que la tarea 3.14 evita.
    """
    global _REPLICADOR
    almacen = almacen_de_respaldo()
    if almacen is None:
        return None
    with _CANDADO_DE_RESPALDO:
        if _REPLICADOR is None:
            _REPLICADOR = Replicador(almacen, anotar=anotar)
            _REPLICADOR.iniciar()
        return _REPLICADOR


def _solicitar_replica(bitacora: Bitacora) -> None:
    """Gancho de post-confirmación. Toma la instantánea y la encola.

    La instantánea se toma aquí, síncrona, porque la conexión de esta petición
    se cierra en cuanto termine. Subirla es lo que se difiere.
    """
    replicador = replicador_actual()
    if replicador is None:
        return
    replicador.solicitar(bitacora.instantanea())


def restaurar_al_arranque() -> Restauracion:
    """Instala el último snapshot si la ruta no existe. La llama el arranque."""
    global _RESTAURACION
    _RESTAURACION = restaurar_si_falta(
        ruta_de_la_bitacora(),
        almacen_de_respaldo(),
        inquilino=inquilino_configurado(),
        anotar=anotar,
    )
    return _RESTAURACION


def restauracion_del_arranque() -> Restauracion | None:
    """Qué pasó al arrancar, para que el semáforo lo pueda declarar."""
    return _RESTAURACION


def reiniciar_respaldo() -> None:
    """Olvida el estado memorizado. Solo para las pruebas."""
    global _REPLICADOR, _ALMACEN, _RESPALDO_RESUELTO, _RESTAURACION
    replicador = _REPLICADOR
    if replicador is not None:
        replicador.detener()
    with _CANDADO_DE_RESPALDO:
        _REPLICADOR = None
        _ALMACEN = None
        _RESPALDO_RESUELTO = False
        _RESTAURACION = None


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
        bitacora = Bitacora(
            conexion,
            inquilino=inquilino_configurado(),
            al_confirmar=_solicitar_replica,
        )
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
