"""Durabilidad de la bitácora fuera de la instancia (tareas 3.13 y 3.14).

## Qué resuelve, y qué explícitamente no

`--max-instances=1` y `BEGIN IMMEDIATE` resuelven el **dominio del candado**: un
solo escritor, escrituras serializadas, cadena que no se bifurca. Eso ya estaba
bien resuelto y este módulo no lo toca — ver ADR 0007.

Lo que falta es el **dominio de la durabilidad**, que es otro problema con otra
solución: la bitácora es un archivo SQLite en `/tmp` de Cloud Run, y `/tmp` se
borra al reciclar la instancia. Un despliegue nuevo arrancaba en altura 0 con la
cadena del día anterior perdida.

Aquí se replica el archivo a un almacén externo tras cada confirmación, y se
restaura al arranque si la ruta no existe. **No** se resuelve el escalamiento
horizontal: sigue habiendo un solo escritor, y con dos instancias esto no basta.
La solución de eso es Postgres con `pg_advisory_lock`, y es trabajo posterior.

## Por qué un solo hilo consumidor, y no una subida por confirmación

Lo natural es que cada commit dispare su propia subida en segundo plano. **Eso
reordena.** El candado serializa las *escrituras*, no las *subidas*: dos subidas
en vuelo compiten, y si la del snapshot de altura 41 aterriza después de la de
altura 42, el objeto vigente en el almacén queda siendo el más viejo. La
restauración devuelve entonces una cadena más corta —sin error, sin excepción,
sin log— que verifica perfecto porque es un prefijo válido de sí misma.

Es exactamente el fallo que el ADR 0007 describe: no uno que rompa, uno que
**produce evidencia de aspecto correcto**. Por eso las subidas pasan por un solo
hilo: el orden de llegada al almacén es el orden de confirmación, por
construcción y no por suerte.

## Por qué la instantánea pendiente se reemplaza en vez de encolarse

Si entran tres confirmaciones mientras hay una subida en vuelo, solo se sube la
última. No es una optimización con pérdida: cada instantánea es el archivo
**completo**, así que la de altura 44 contiene todo lo que contenían las de 42 y
43. Encolarlas subiría tres veces el mismo estado final.

El efecto colateral importante es que el trabajo pendiente no crece sin límite
bajo carga. Una cola sí lo haría, y el momento en que se notaría sería una
ingesta de lote grande — justo cuando menos conviene.

## La cola que se pierde, declarada

La instantánea se toma de forma **síncrona** tras el commit —tiene que ser así,
la conexión se cierra al terminar la petición— pero la subida es **asíncrona**.
Entre una confirmación y su subida hay una ventana en la que un `SIGKILL` de la
instancia se lleva esas escrituras: el almacén conserva el snapshot anterior.

El criterio de la tarea 3.14 dice «nunca con una escritura perdida». Eso solo es
literalmente cierto con subida síncrona dentro de la petición, que es justo lo
que «la subida ocurre fuera del candado» descarta, y costaría un viaje de red
por confirmación. **La ventana existe, está acotada a una subida, y se declara**
— no se esconde detrás de una redacción que suene mejor. `Replicador.degradado`
la expone y el semáforo la reporta.

Lo que sí es cierto sin matices: un fallo del almacén nunca tumba una petición
ni revierte una escritura ya confirmada. Deja el sistema degradado y avisando.

## Por qué el almacén es un protocolo

Mismo criterio que `fuentes/protocolo.py` y que `AnclaSimulada` frente a
`AnclaEVM`: quien corre las pruebas o levanta la demo en su máquina no tiene por
qué tener credenciales de Google Cloud. `RespaldoEnDirectorio` ejercita
exactamente el mismo camino de código que `RespaldoGCS`, así que las pruebas
prueban el mecanismo y no un simulacro del mecanismo.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

VARIABLE_DESTINO = "AGENTE_CFDI_RESPALDO"
"""Dónde se replica. `gs://cubeta/objeto` para GCS, o una ruta de directorio.

Vacía significa **sin respaldo**, y es el predeterminado a propósito: las
pruebas y la demo local no deben necesitar un almacén. Lo que no se permite es
una configuración a medias — ver `almacen_desde_entorno`.
"""

OBJETO_PREDETERMINADO = "bitacora/bitacora.db"

Anotador = Callable[..., None]


def _sin_registro(evento: str, **campos: object) -> None:
    """Registro nulo.

    El anotador se **inyecta** en vez de importar `api.ciclo.anotar` porque este
    paquete no puede depender de `api`: la bitácora es el núcleo y la API es una
    de sus fachadas. De paso, las pruebas capturan las líneas sin tocar stdout.
    """


@dataclass(frozen=True)
class Instantanea:
    """Una copia consistente del archivo completo, con la altura que tenía."""

    contenido: bytes
    altura: int

    @property
    def tamano(self) -> int:
        return len(self.contenido)


@dataclass(frozen=True)
class Recuperada:
    """Lo que devuelve el almacén al pedirle el último snapshot.

    `altura_declarada` es lo que dicen los metadatos y puede ser `None` o
    mentira: un proceso muerto a media escritura puede dejar el objeto y sus
    metadatos desincronizados. La altura que se reporta como cierta se recalcula
    leyendo el archivo restaurado — ver `restaurar_si_falta`. El dato declarado
    solo sirve para detectar y anunciar la discrepancia.
    """

    contenido: bytes
    generacion: str
    altura_declarada: int | None = None
    subido_en: str | None = None


class AlmacenDeRespaldo(Protocol):
    """Dónde vive la copia. Ver las dos implementaciones de abajo."""

    @property
    def descripcion(self) -> str:
        """Legible en un log. Nunca incluye credenciales."""
        ...

    def subir(self, instantanea: Instantanea) -> str:
        """Publica la instantánea y devuelve la generación resultante."""
        ...

    def ultimo(self) -> Recuperada | None:
        """La copia vigente, o `None` si nunca se subió ninguna."""
        ...


# --------------------------------------------------------------------- #
# Tomar la instantánea
# --------------------------------------------------------------------- #


def tomar_instantanea(conexion: sqlite3.Connection, *, altura: int) -> Instantanea:
    """Copia consistente del archivo sin detener las escrituras.

    `Connection.backup()` es biblioteca estándar y hace justo lo que hace falta:
    si la base cambia mientras copia, reinicia la copia en vez de entregar una
    mezcla de dos estados. Copiar el archivo con `shutil.copy` **no** es
    equivalente — puede capturar páginas de dos transacciones distintas y
    producir un archivo que no abre, o peor, uno que abre y está mal.

    Se copia a memoria y se serializa, en vez de a un archivo temporal, para no
    depender de que haya disco escribible ni de limpiar el temporal si el
    proceso muere en medio.

    ## Por qué se exige que no haya transacción abierta

    `Connection.backup()` contra una conexión que tiene su propia transacción de
    escritura abierta **no levanta: se cuelga**. La API de respaldo de SQLite
    devuelve `SQLITE_BUSY` y el envoltorio de Python reintenta en un bucle que
    nadie rompe, porque el candado que espera lo tiene el mismo hilo que espera.

    Hoy no puede pasar —el gancho corre después del `COMMIT`, ver
    `almacen._Transaccion.__exit__`— pero la distancia entre «no puede pasar» y
    «pasa» son dos líneas movidas de sitio. En Cloud Run el síntoma sería una
    petición colgada hasta el tiempo de espera del balanceador, sin traza y sin
    error. Se prefiere una excepción inmediata que diga qué se hizo mal.
    """
    if conexion.in_transaction:
        raise RuntimeError(
            "no se puede tomar una instantánea con una transacción abierta en "
            "esta conexión: backup() esperaría un candado que tiene este mismo "
            "hilo y no volvería. La instantánea se toma DESPUÉS del COMMIT"
        )
    destino = sqlite3.connect(":memory:")
    try:
        conexion.backup(destino)
        return Instantanea(contenido=destino.serialize(), altura=altura)
    finally:
        destino.close()


def revisar_instantanea(contenido: bytes, *, inquilino: str) -> int | None:
    """¿Estos bytes son una bitácora que abre y cuadra? Devuelve su altura.

    Devuelve `None` si no lo son. Existe porque el criterio de la tarea 3.14
    exige que un snapshot interrumpido a media subida **no** se instale: se
    prueba que el anterior sigue siendo válido, no se supone. Instalar un
    archivo corrupto y descubrirlo en la primera consulta sería cambiar una
    pérdida ruidosa por una silenciosa.

    `PRAGMA integrity_check` recorre la estructura entera. Es caro y corre una
    sola vez por arranque, que es exactamente cuando vale la pena pagarlo.
    """
    with tempfile.TemporaryDirectory() as carpeta:
        sonda = Path(carpeta) / "revision.db"
        sonda.write_bytes(contenido)
        try:
            conexion = sqlite3.connect(sonda)
        except sqlite3.Error:
            return None
        try:
            veredicto = conexion.execute("PRAGMA integrity_check").fetchone()
            if veredicto is None or veredicto[0] != "ok":
                return None
            fila = conexion.execute(
                "SELECT COUNT(*) FROM bitacora_cadena WHERE inquilino = ?",
                (inquilino,),
            ).fetchone()
            return int(fila[0])
        except sqlite3.Error:
            # Abre pero no tiene el esquema de una bitácora. Tampoco sirve.
            return None
        finally:
            conexion.close()


# --------------------------------------------------------------------- #
# Los dos almacenes
# --------------------------------------------------------------------- #


class RespaldoEnDirectorio:
    """Respaldo contra un directorio del sistema de archivos.

    Es lo que usan las pruebas y la demo local. No es un simulacro: ejercita el
    mismo camino que GCS —serializar, subir, recuperar, restaurar— y por eso lo
    que se prueba aquí es el mecanismo de verdad.
    """

    def __init__(self, directorio: Path | str) -> None:
        self._directorio = Path(directorio)
        self._objeto = self._directorio / "bitacora.db"
        self._metadatos = self._directorio / "bitacora.meta.json"

    @property
    def descripcion(self) -> str:
        return f"directorio:{self._directorio}"

    def subir(self, instantanea: Instantanea) -> str:
        self._directorio.mkdir(parents=True, exist_ok=True)
        generacion = str(time.time_ns())

        # Escribir aparte y renombrar. `os.replace` es atómico en Windows y en
        # POSIX, así que un proceso muerto a media escritura deja el objeto
        # ANTERIOR intacto — nunca uno a medias. Es la propiedad que la tarea
        # 3.14 pide demostrar.
        parcial = self._directorio / "bitacora.db.parcial"
        parcial.write_bytes(instantanea.contenido)
        os.replace(parcial, self._objeto)

        # Los metadatos van después y son advertidamente advisorios: si el
        # proceso muere entre las dos escrituras, quedan desfasados. Por eso la
        # restauración recalcula la altura del archivo en vez de creerles.
        self._metadatos.write_text(
            json.dumps(
                {
                    "altura": instantanea.altura,
                    "generacion": generacion,
                    "subido_en": _ahora_texto(),
                    "bytes": instantanea.tamano,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return generacion

    def ultimo(self) -> Recuperada | None:
        if not self._objeto.exists():
            return None
        contenido = self._objeto.read_bytes()

        altura_declarada: int | None = None
        subido_en: str | None = None
        generacion = str(self._objeto.stat().st_mtime_ns)
        if self._metadatos.exists():
            try:
                datos = json.loads(self._metadatos.read_text(encoding="utf-8"))
                altura_declarada = int(datos["altura"])
                generacion = str(datos.get("generacion", generacion))
                subido_en = datos.get("subido_en")
            except (ValueError, KeyError, TypeError):
                # Metadatos ilegibles no invalidan el respaldo: el archivo es la
                # fuente de verdad y la altura se recalcula de todos modos.
                pass

        return Recuperada(
            contenido=contenido,
            generacion=generacion,
            altura_declarada=altura_declarada,
            subido_en=subido_en,
        )


class RespaldoGCS:
    """Respaldo contra un objeto de Google Cloud Storage.

    GCS versiona los objetos si la cubeta tiene versionado activo, así que
    además del snapshot vigente queda historial sin que este código haga nada.

    Los metadatos viajan **en la misma petición** que el contenido, así que aquí
    no existe el desfase que sí tiene el respaldo en directorio: o se publica la
    versión completa con sus metadatos, o no se publica nada.
    """

    def __init__(self, cubeta: str, objeto: str, *, cliente: object | None = None) -> None:
        self._cubeta = cubeta
        self._objeto = objeto
        self._cliente = cliente

    @property
    def descripcion(self) -> str:
        return f"gs://{self._cubeta}/{self._objeto}"

    def _blob(self):
        # El import va aquí y no arriba por la misma razón que `web3` en
        # `dependencias.ancla_actual`: quien corre las pruebas con el respaldo
        # en directorio no tiene por qué instalar el SDK de Google Cloud.
        if self._cliente is None:
            from google.cloud import storage

            self._cliente = storage.Client()
        return self._cliente.bucket(self._cubeta).blob(self._objeto)

    def subir(self, instantanea: Instantanea) -> str:
        blob = self._blob()
        blob.metadata = {
            "altura": str(instantanea.altura),
            "subido_en": _ahora_texto(),
        }
        blob.upload_from_string(
            instantanea.contenido, content_type="application/vnd.sqlite3"
        )
        return str(blob.generation)

    def ultimo(self) -> Recuperada | None:
        blob = self._blob().bucket.get_blob(self._objeto)
        if blob is None:
            return None
        metadatos = blob.metadata or {}
        altura_declarada: int | None = None
        try:
            altura_declarada = int(metadatos["altura"])
        except (KeyError, ValueError, TypeError):
            pass
        return Recuperada(
            contenido=blob.download_as_bytes(),
            generacion=str(blob.generation),
            altura_declarada=altura_declarada,
            subido_en=metadatos.get("subido_en"),
        )


def almacen_desde_entorno(
    variable: str = VARIABLE_DESTINO,
) -> AlmacenDeRespaldo | None:
    """Construye el almacén configurado, o `None` si no hay ninguno.

    **No se degrada en silencio.** Si la variable trae un `gs://` mal formado,
    esto levanta en vez de caer a un respaldo local que nadie pidió: un
    despliegue que cree estar replicando a GCS y esté escribiendo en el disco
    efímero que intenta abandonar es el peor resultado posible — se pierde igual
    y además nadie se entera. Mismo criterio que `ancla_actual`.
    """
    crudo = os.environ.get(variable, "").strip()
    if not crudo:
        return None

    if crudo.startswith("gs://"):
        resto = crudo[len("gs://") :]
        cubeta, _, objeto = resto.partition("/")
        if not cubeta:
            raise RuntimeError(
                f"{variable}={crudo!r} no nombra una cubeta: "
                f"se esperaba gs://cubeta/objeto"
            )
        return RespaldoGCS(cubeta, objeto or OBJETO_PREDETERMINADO)

    return RespaldoEnDirectorio(crudo)


# --------------------------------------------------------------------- #
# El replicador (tarea 3.14)
# --------------------------------------------------------------------- #


class Replicador:
    """Sube instantáneas al almacén, en orden y sin acumular trabajo.

    Un solo hilo consumidor y una sola instantánea pendiente. El razonamiento de
    las dos decisiones está en el encabezado del módulo; lo que importa desde
    fuera es la garantía que dan juntas: **el orden de llegada al almacén es el
    orden de confirmación**, y el trabajo pendiente no crece bajo carga.
    """

    def __init__(
        self,
        almacen: AlmacenDeRespaldo,
        *,
        anotar: Anotador = _sin_registro,
        nombre: str = "respaldo-bitacora",
    ) -> None:
        self._almacen = almacen
        self._anotar = anotar
        self._nombre = nombre

        self._condicion = threading.Condition()
        self._pendiente: Instantanea | None = None
        self._trabajando = False
        self._detenido = False
        self._hilo: threading.Thread | None = None

        # Estado observable. Lo lee el semáforo y lo leen las pruebas.
        self.altura_replicada = -1
        self.generacion: str | None = None
        self.ultimo_error: str | None = None
        self.subidas = 0
        self.coalescidas = 0

    @property
    def descripcion(self) -> str:
        return self._almacen.descripcion

    @property
    def degradado(self) -> bool:
        """La última subida falló. La escritura local está, la copia no."""
        return self.ultimo_error is not None

    def iniciar(self) -> None:
        with self._condicion:
            if self._hilo is not None:
                return
            self._detenido = False
            # `daemon=True`: un cierre del proceso no debe quedarse esperando a
            # una subida. La contrapartida —que un cierre puede llevarse la
            # instantánea pendiente— es la misma ventana ya declarada arriba.
            self._hilo = threading.Thread(
                target=self._trabajar, name=self._nombre, daemon=True
            )
            self._hilo.start()

    def solicitar(self, instantanea: Instantanea) -> None:
        """Pide replicar. No bloquea y no levanta: la escritura ya está hecha."""
        with self._condicion:
            if self._pendiente is not None:
                # Reemplazar no pierde nada: la nueva instantánea es el archivo
                # completo y contiene todo lo de la anterior.
                self.coalescidas += 1
            self._pendiente = instantanea
            self._condicion.notify_all()

    def vaciar(self, tiempo_limite: float = 10.0) -> bool:
        """Espera a que no quede trabajo. Para las pruebas y el cierre ordenado."""
        limite = time.monotonic() + tiempo_limite
        with self._condicion:
            while self._pendiente is not None or self._trabajando:
                restante = limite - time.monotonic()
                if restante <= 0:
                    return False
                self._condicion.wait(restante)
        return True

    def detener(self, tiempo_limite: float = 10.0) -> None:
        self.vaciar(tiempo_limite)
        with self._condicion:
            self._detenido = True
            self._condicion.notify_all()
        hilo = self._hilo
        if hilo is not None:
            hilo.join(tiempo_limite)
        self._hilo = None

    # ----------------------------------------------------------------- #
    # Interno
    # ----------------------------------------------------------------- #

    def _trabajar(self) -> None:
        while True:
            with self._condicion:
                while self._pendiente is None and not self._detenido:
                    self._condicion.wait()
                if self._pendiente is None:
                    return
                trabajo = self._pendiente
                self._pendiente = None
                self._trabajando = True
            try:
                self._subir(trabajo)
            finally:
                with self._condicion:
                    self._trabajando = False
                    self._condicion.notify_all()

    def _subir(self, instantanea: Instantanea) -> None:
        if instantanea.altura < self.altura_replicada:
            # Con un solo hilo consumidor esto no debería poder ocurrir. Está
            # porque el día que alguien añada un segundo hilo «para que vaya más
            # rápido», el resultado tiene que ser una línea de log y no una
            # cadena que encoge en silencio.
            self._anotar(
                "respaldo.retroceso_rechazado",
                altura_ofrecida=instantanea.altura,
                altura_replicada=self.altura_replicada,
            )
            return

        try:
            generacion = self._almacen.subir(instantanea)
        except Exception as fallo:  # noqa: BLE001 - cualquier fallo degrada, ninguno tumba
            self.ultimo_error = f"{type(fallo).__name__}: {fallo}"
            self._anotar(
                "respaldo.fallo",
                altura=instantanea.altura,
                destino=self._almacen.descripcion,
                error=self.ultimo_error,
            )
            return

        self.altura_replicada = instantanea.altura
        self.generacion = generacion
        self.ultimo_error = None
        self.subidas += 1
        self._anotar(
            "respaldo.subido",
            altura=instantanea.altura,
            generacion=generacion,
            bytes=instantanea.tamano,
            destino=self._almacen.descripcion,
        )


# --------------------------------------------------------------------- #
# La restauración (tarea 3.13)
# --------------------------------------------------------------------- #


@dataclass(frozen=True)
class Restauracion:
    """Qué pasó al arrancar. Siempre se produce una — el silencio no es opción.

    Los estados posibles:

    | `estado` | Significa |
    |---|---|
    | `sin_respaldo` | No hay almacén configurado. Arranca vacía, como antes de 3.13. |
    | `ya_existia` | La ruta tenía datos; no se toca nada. |
    | `sin_snapshot` | Hay almacén pero nunca se subió nada. Arranca vacía. |
    | `restaurada` | Se instaló la copia. `altura` es la real, recalculada. |
    | `corrupta` | Llegó un snapshot que no abre o no cuadra. **No se instala.** |
    | `fallo` | El almacén no respondió. Arranca vacía y avisa. |
    """

    estado: str
    detalle: str
    altura: int = 0
    generacion: str | None = None
    subido_en: str | None = None
    altura_declarada: int | None = None

    @property
    def restaurada(self) -> bool:
        return self.estado == "restaurada"

    @property
    def discrepancia(self) -> bool:
        """Los metadatos decían una altura y el archivo tenía otra."""
        return (
            self.restaurada
            and self.altura_declarada is not None
            and self.altura_declarada != self.altura
        )


def restaurar_si_falta(
    ruta: Path,
    almacen: AlmacenDeRespaldo | None,
    *,
    inquilino: str,
    anotar: Anotador = _sin_registro,
) -> Restauracion:
    """Instala el último snapshot si la ruta no existe. Idempotente.

    El orden importa: **no se toca una bitácora que ya está**. Si la ruta tiene
    datos, este arranque no es una instancia nueva sino un reinicio del proceso
    dentro de la misma, y sobrescribirla con una copia posiblemente más vieja
    sería provocar justo la pérdida que este módulo evita.

    Nunca levanta. Un almacén caído tiene que dejar el servicio arrancando y
    diciéndolo, no impedir que arranque: sin bitácora se puede al menos leer el
    semáforo y enterarse de que no hay cadena.
    """
    if almacen is None:
        detalle = (
            f"{VARIABLE_DESTINO} está vacía: la bitácora no se replica y no "
            f"sobrevive al reciclaje de la instancia"
        )
        anotar("bitacora.restauracion", estado="sin_respaldo", detalle=detalle)
        return Restauracion(estado="sin_respaldo", detalle=detalle)

    if ruta.exists() and ruta.stat().st_size > 0:
        detalle = f"la bitácora ya existe en {ruta}; no se restaura nada"
        anotar(
            "bitacora.restauracion",
            estado="ya_existia",
            ruta=str(ruta),
            detalle=detalle,
        )
        return Restauracion(estado="ya_existia", detalle=detalle)

    try:
        recuperada = almacen.ultimo()
    except Exception as fallo:  # noqa: BLE001 - arrancar y avisar, nunca no arrancar
        detalle = (
            f"no se pudo consultar {almacen.descripcion}: "
            f"{type(fallo).__name__}: {fallo}"
        )
        anotar("bitacora.restauracion", estado="fallo", detalle=detalle)
        return Restauracion(estado="fallo", detalle=detalle)

    if recuperada is None:
        detalle = (
            f"{almacen.descripcion} no tiene ningún snapshot todavía; "
            f"la bitácora arranca vacía"
        )
        anotar("bitacora.restauracion", estado="sin_snapshot", detalle=detalle)
        return Restauracion(estado="sin_snapshot", detalle=detalle)

    # Se revisa ANTES de instalar. Un snapshot truncado por una subida
    # interrumpida no puede reemplazar a una ruta vacía y descubrirse después:
    # más vale arrancar sin cadena y decirlo que arrancar con una que no abre.
    altura = revisar_instantanea(recuperada.contenido, inquilino=inquilino)
    if altura is None:
        detalle = (
            f"el snapshot {recuperada.generacion} de {almacen.descripcion} no "
            f"pasa integrity_check o no tiene el esquema de una bitácora; "
            f"NO se instala y la bitácora arranca vacía"
        )
        anotar(
            "bitacora.restauracion",
            estado="corrupta",
            generacion=recuperada.generacion,
            detalle=detalle,
        )
        return Restauracion(
            estado="corrupta", detalle=detalle, generacion=recuperada.generacion
        )

    ruta.parent.mkdir(parents=True, exist_ok=True)
    parcial = ruta.with_name(ruta.name + ".parcial")
    parcial.write_bytes(recuperada.contenido)
    os.replace(parcial, ruta)

    restauracion = Restauracion(
        estado="restaurada",
        detalle=(
            f"cadena restaurada desde {almacen.descripcion} "
            f"(generación {recuperada.generacion}) en altura {altura}"
        ),
        altura=altura,
        generacion=recuperada.generacion,
        subido_en=recuperada.subido_en,
        altura_declarada=recuperada.altura_declarada,
    )
    anotar(
        "bitacora.restauracion",
        estado="restaurada",
        altura=altura,
        altura_declarada=recuperada.altura_declarada,
        generacion=recuperada.generacion,
        subido_en=recuperada.subido_en,
        destino=almacen.descripcion,
        discrepancia=restauracion.discrepancia,
    )
    return restauracion


def _ahora_texto() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
