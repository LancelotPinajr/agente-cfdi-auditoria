"""La bitácora persistida: append-only, encadenada y sin carreras (tareas 2.1–2.3).

## Dos tablas, y por qué no una

| Tabla | Qué guarda | Vive |
|---|---|---|
| `bitacora_cadena` | posición, hash, hash anterior | **para siempre** |
| `bitacora_registros` | el canónico, con RFC y montos | hasta que caduca |

La cadena **no contiene datos personales**: son hashes. Por eso puede ser
inmutable y eterna sin chocar con el art. 11 de la LFPDPPP. El contenido, que sí
los tiene, vive aparte y se puede suprimir cuando deja de ser necesario —y
suprimirlo **no rompe la cadena**, porque los eslabones siguen enlazando.

Si el dato personal viviera dentro de la cadena, cumplir la ley de protección de
datos exigiría romper la prueba de integridad. Separar «lo que prueba» de «lo que
identifica» es lo que permite cumplir las dos cosas. Ver
`docs/contrato-expediente.md` §5.

## La doble cesión no se detecta con un SELECT

Lo natural es consultar si el UUID ya fue cedido y, si no, insertarlo. **Eso
tiene una carrera**: dos peticiones simultáneas consultan, ambas ven «libre», y
ambas escriben. No es una hipótesis de laboratorio — es exactamente lo que hace
quien quiere ceder dos veces: mandar las dos solicitudes a la vez.

Aquí la garantía es una **restricción `UNIQUE` sobre el UUID**. La base de datos
no puede contener dos cesiones del mismo folio fiscal, sin importar el orden ni
la concurrencia. El `SELECT` previo existe solo para dar un mensaje decente; si
desapareciera, la propiedad seguiría en pie.

## Alcance del registro de cesiones: global, no por inquilino

La restricción es sobre el UUID **a secas**, no sobre `(inquilino, uuid)`. Un
folio fiscal lo emite el SAT y pertenece a un solo emisor, así que el ámbito
correcto del fraude es global: acotarlo por inquilino lo derrotaría cualquiera
que pueda abrir dos cuentas.

El precio es que un inquilino puede descubrir que un UUID ajeno está tomado. Por
eso el rechazo dice **«ya cedido»** y nunca a quién: el hecho basta para frenar
la operación, la identidad del otro financiador no es asunto suyo.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterator, Mapping

from ..dominio.canonico import canonicalizar
from .cadena import Eslabon, genesis, hash_de_registro, raiz_de_merkle, verificar_cadena
from .eventos import Evento, esquema_de

ESQUEMA_SQL = """
CREATE TABLE IF NOT EXISTS bitacora_cadena (
    inquilino     TEXT    NOT NULL,
    posicion      INTEGER NOT NULL,
    hash_registro BLOB    NOT NULL,
    hash_anterior BLOB    NOT NULL,
    escrito_en    TEXT    NOT NULL,
    PRIMARY KEY (inquilino, posicion)
);

CREATE TABLE IF NOT EXISTS bitacora_registros (
    inquilino TEXT    NOT NULL,
    posicion  INTEGER NOT NULL,
    evento    TEXT    NOT NULL,
    canonico  BLOB    NOT NULL,
    PRIMARY KEY (inquilino, posicion),
    FOREIGN KEY (inquilino, posicion)
        REFERENCES bitacora_cadena (inquilino, posicion) ON DELETE CASCADE
);

-- La clave primaria es el UUID solo. Ahí vive la garantía contra la doble
-- cesión: la tabla no puede contener dos filas del mismo folio fiscal.
CREATE TABLE IF NOT EXISTS cesiones (
    uuid         TEXT    NOT NULL PRIMARY KEY,
    inquilino    TEXT    NOT NULL,
    financiador  TEXT    NOT NULL,
    posicion     INTEGER NOT NULL,
    cedido_en    TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cadena_dia ON bitacora_cadena (inquilino, escrito_en);
"""


class BitacoraCorrupta(RuntimeError):
    """El almacén está en un estado que no debería poder alcanzar."""


@dataclass(frozen=True)
class Anexado:
    posicion: int
    hash_registro: bytes
    canonico: bytes


@dataclass(frozen=True)
class ResultadoDeCesion:
    """Qué pasó al intentar ceder."""

    aceptada: bool
    posicion: int
    """Del evento que se acaba de escribir — aceptado o rechazado, siempre queda."""
    posicion_de_la_cesion_previa: int | None = None

    @property
    def motivo(self) -> str:
        if self.aceptada:
            return "cesion_registrada"
        return "el folio fiscal ya fue cedido"


class Bitacora:
    """Bitácora encadenada sobre SQLite.

    SQLite y no Postgres porque así el proyecto se levanta y se verifica en
    cualquier máquina sin instalar un servidor — cuenta para el criterio de
    reproducibilidad. La migración equivalente para Postgres, que es la ruta de
    producción, está en `migraciones/001_bitacora.sql`.
    """

    def __init__(self, conexion: sqlite3.Connection, *, inquilino: str) -> None:
        if not inquilino:
            raise ValueError("la bitácora exige un inquilino")
        self._cx = conexion
        self._cx.row_factory = sqlite3.Row
        self._cx.execute("PRAGMA foreign_keys = ON")
        # Sin esto, sqlite3 abre transacciones implícitas y `BEGIN IMMEDIATE`
        # no se puede pedir a mano.
        self._cx.isolation_level = None
        self.inquilino = inquilino

    @classmethod
    def en_memoria(cls, inquilino: str = "demo") -> "Bitacora":
        bitacora = cls(sqlite3.connect(":memory:"), inquilino=inquilino)
        bitacora.migrar()
        return bitacora

    def migrar(self) -> None:
        """Tarea 2.1. Idempotente: correrla dos veces no hace nada la segunda."""
        self._cx.executescript(ESQUEMA_SQL)

    # ------------------------------------------------------------------ #
    # Escritura
    # ------------------------------------------------------------------ #

    def anexar(self, evento: Evento, datos: Mapping[str, Any]) -> Anexado:
        """Escribe un evento al final de la cadena.

        `BEGIN IMMEDIATE` toma el candado de escritura **antes** de leer la
        punta, de modo que dos procesos no puedan leer el mismo `hash_anterior`
        y bifurcar. Si aun así ocurriera, la clave primaria `(inquilino,
        posicion)` rechaza el segundo: el candado evita el reintento, la
        restricción evita el desastre.
        """
        with self._transaccion():
            return self._anexar_sin_transaccion(evento, datos)

    def registrar_cesion(
        self,
        *,
        uuid: str,
        financiador: str,
        rfc_emisor: str,
        total: Decimal,
        moneda: str = "MXN",
    ) -> ResultadoDeCesion:
        """Intenta ceder una factura. Escribe pase lo que pase.

        Aceptada o rechazada, el intento queda en la bitácora. Una bitácora que
        solo guarda lo que salió bien no sirve para investigar nada.
        """
        ahora = _ahora()
        with self._transaccion():
            previa = self._cx.execute(
                "SELECT posicion FROM cesiones WHERE uuid = ?", (uuid,)
            ).fetchone()

            if previa is not None:
                anexado = self._anexar_sin_transaccion(
                    Evento.CESION_RECHAZADA,
                    {
                        "uuid": uuid,
                        "financiador": financiador,
                        "motivo": "ya_cedido",
                        "posicion_de_la_cesion_previa": int(previa["posicion"]),
                    },
                    ahora=ahora,
                )
                return ResultadoDeCesion(
                    aceptada=False,
                    posicion=anexado.posicion,
                    posicion_de_la_cesion_previa=int(previa["posicion"]),
                )

            anexado = self._anexar_sin_transaccion(
                Evento.CESION_REGISTRADA,
                {
                    "uuid": uuid,
                    "rfc_emisor": rfc_emisor,
                    "financiador": financiador,
                    "total": total,
                    "moneda": moneda,
                },
                ahora=ahora,
            )
            try:
                self._cx.execute(
                    "INSERT INTO cesiones (uuid, inquilino, financiador, posicion, cedido_en)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (uuid, self.inquilino, financiador, anexado.posicion, _texto(ahora)),
                )
            except sqlite3.IntegrityError:
                # Alguien ganó la carrera entre el SELECT y el INSERT. La
                # restricción hizo su trabajo; deshacemos y lo reportamos como
                # el rechazo que es.
                raise _CarreraDeCesion(uuid) from None

            return ResultadoDeCesion(aceptada=True, posicion=anexado.posicion)

    def suprimir_registro(self, posicion: int) -> None:
        """Borra el contenido de un registro, conservando su eslabón.

        Es la operación de retención: los datos personales caducan, la prueba de
        integridad no. Después de esto la cadena sigue verificando y ese eslabón
        deja de ser recalculable — que es exactamente lo que debe pasar.
        """
        with self._transaccion():
            self._cx.execute(
                "DELETE FROM bitacora_registros WHERE inquilino = ? AND posicion = ?",
                (self.inquilino, posicion),
            )

    # ------------------------------------------------------------------ #
    # Lectura y verificación
    # ------------------------------------------------------------------ #

    def eslabones(self) -> Iterator[Eslabon]:
        filas = self._cx.execute(
            "SELECT c.posicion, c.hash_registro, c.hash_anterior, r.canonico"
            "  FROM bitacora_cadena c"
            "  LEFT JOIN bitacora_registros r"
            "    ON r.inquilino = c.inquilino AND r.posicion = c.posicion"
            " WHERE c.inquilino = ? ORDER BY c.posicion",
            (self.inquilino,),
        )
        for fila in filas:
            yield Eslabon(
                posicion=int(fila["posicion"]),
                hash_registro=bytes(fila["hash_registro"]),
                hash_anterior=bytes(fila["hash_anterior"]),
                canonico=bytes(fila["canonico"]) if fila["canonico"] is not None else None,
            )

    def verificar(self) -> int:
        """Recorre la cadena entera. Devuelve cuántos eslabones se recalcularon."""
        return verificar_cadena(self.eslabones(), self.inquilino)

    def altura(self) -> int:
        fila = self._cx.execute(
            "SELECT COUNT(*) AS n FROM bitacora_cadena WHERE inquilino = ?",
            (self.inquilino,),
        ).fetchone()
        return int(fila["n"])

    def punta(self) -> bytes:
        """El hash del último registro, o el génesis si la cadena está vacía."""
        fila = self._cx.execute(
            "SELECT hash_registro FROM bitacora_cadena WHERE inquilino = ?"
            " ORDER BY posicion DESC LIMIT 1",
            (self.inquilino,),
        ).fetchone()
        return bytes(fila["hash_registro"]) if fila else genesis(self.inquilino)

    def hojas_del_dia(self, dia: str) -> list[bytes]:
        """Los hashes escritos en un día UTC (`AAAA-MM-DD`), en orden."""
        filas = self._cx.execute(
            "SELECT hash_registro FROM bitacora_cadena"
            " WHERE inquilino = ? AND escrito_en >= ? AND escrito_en < ?"
            " ORDER BY posicion",
            (self.inquilino, f"{dia}T00:00:00Z", f"{dia}T99"),
        )
        return [bytes(f["hash_registro"]) for f in filas]

    def raiz_del_dia(self, dia: str) -> bytes:
        """La raíz de Merkle a anclar. Levanta si el día no tuvo registros."""
        return raiz_de_merkle(self.hojas_del_dia(dia))

    def cesion_de(self, uuid: str) -> sqlite3.Row | None:
        return self._cx.execute("SELECT * FROM cesiones WHERE uuid = ?", (uuid,)).fetchone()

    # ------------------------------------------------------------------ #
    # Interno
    # ------------------------------------------------------------------ #

    def _anexar_sin_transaccion(
        self, evento: Evento, datos: Mapping[str, Any], *, ahora: datetime | None = None
    ) -> Anexado:
        ahora = ahora or _ahora()
        esquema = esquema_de(evento)
        registro = dict(datos)
        registro["evento"] = evento.value
        registro["inquilino"] = self.inquilino
        registro["escrito_en"] = ahora

        canonico = canonicalizar(registro, esquema)
        hash_anterior = self.punta()
        posicion = self.altura()
        hash_registro = hash_de_registro(canonico, hash_anterior)

        try:
            self._cx.execute(
                "INSERT INTO bitacora_cadena"
                " (inquilino, posicion, hash_registro, hash_anterior, escrito_en)"
                " VALUES (?, ?, ?, ?, ?)",
                (self.inquilino, posicion, hash_registro, hash_anterior, _texto(ahora)),
            )
        except sqlite3.IntegrityError as exc:
            # La clave primaria rechazó una bifurcación. Es la última línea de
            # defensa y significa que dos escritores llegaron a la vez.
            raise BitacoraCorrupta(
                f"otra escritura ya ocupó la posición {posicion}; la cadena no se bifurca"
            ) from exc

        self._cx.execute(
            "INSERT INTO bitacora_registros (inquilino, posicion, evento, canonico)"
            " VALUES (?, ?, ?, ?)",
            (self.inquilino, posicion, evento.value, canonico),
        )
        return Anexado(posicion=posicion, hash_registro=hash_registro, canonico=canonico)

    def _transaccion(self):
        return _Transaccion(self._cx)


class _CarreraDeCesion(RuntimeError):
    """Otra cesión del mismo UUID entró entre el SELECT y el INSERT."""

    def __init__(self, uuid: str) -> None:
        super().__init__(f"el folio {uuid} fue cedido por otra petición simultánea")


class _Transaccion:
    """`BEGIN IMMEDIATE` con reversión automática.

    `IMMEDIATE` y no el `BEGIN` perezoso: toma el candado de escritura al
    empezar, no en la primera escritura. Leer la punta de la cadena y escribir
    el siguiente eslabón tienen que ser una sola operación indivisible, y con el
    `BEGIN` normal la lectura ocurre fuera del candado.
    """

    def __init__(self, conexion: sqlite3.Connection) -> None:
        self._cx = conexion

    def __enter__(self) -> sqlite3.Connection:
        self._cx.execute("BEGIN IMMEDIATE")
        return self._cx

    def __exit__(self, tipo, valor, rastro) -> bool:
        if tipo is None:
            self._cx.execute("COMMIT")
        else:
            self._cx.execute("ROLLBACK")
        return False


def _ahora() -> datetime:
    # Sin microsegundos: la canon tiene precisión de segundo y rechaza la
    # fracción en vez de truncarla en silencio.
    return datetime.now(timezone.utc).replace(microsecond=0)


def _texto(momento: datetime) -> str:
    return momento.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
