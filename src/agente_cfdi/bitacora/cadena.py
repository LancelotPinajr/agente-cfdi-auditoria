"""El encadenamiento por hash de la bitácora (tarea 2.2).

    hash_n = SHA256( 0x00 ‖ canónico_n ‖ hash_{n-1} )

Alterar un registro cambia su hash, que cambia el del siguiente, y así hasta el
final. Como la raíz del día se ancla fuera de nuestro control, reescribir el
pasado exige reescribir todo lo posterior **y** el ancla — que no es nuestra.

## Lo que este módulo NO conoce

No sabe de bases de datos, ni de transacciones, ni de candados. Es aritmética
pura sobre bytes, y por eso se puede probar exhaustivamente sin levantar nada.
La parte difícil —que dos escrituras concurrentes no bifurquen la cadena— vive
en `almacen.py`, donde hay un motor que la puede garantizar.

## Separación de dominios: por qué los prefijos de byte

Cada clase de hash lleva un prefijo distinto:

| Prefijo | Qué se hashea |
|---|---|
| `0x00` | una hoja de la bitácora |
| `0x01` | un nodo interno del árbol de Merkle (tarea 2.6) |
| `0x02` | el génesis de una cadena |

Sin esto, un atacante puede presentar el hash de un **nodo interno** como si
fuera una hoja y construir una prueba de Merkle válida para un registro que
nunca existió. Es el ataque de segunda preimagen sobre árboles de Merkle, y la
defensa estándar (RFC 6962) es exactamente esta. Cuesta un byte y se hace ahora,
porque agregarlo después invalidaría todo lo ya escrito.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable, Sequence

TAMANO_HASH = 32

PREFIJO_HOJA = b"\x00"
PREFIJO_NODO = b"\x01"
PREFIJO_GENESIS = b"\x02"

ETIQUETA_GENESIS = b"CORD-BITACORA-1"


class CadenaRota(Exception):
    """La verificación encontró una inconsistencia.

    Lleva la posición exacta porque «la cadena no verifica» no le sirve a nadie:
    un auditor necesita saber **dónde** para decidir si fue manipulación o un
    error de operación.
    """

    def __init__(self, posicion: int, detalle: str) -> None:
        self.posicion = posicion
        self.detalle = detalle
        super().__init__(f"posición {posicion}: {detalle}")


def genesis(inquilino: str) -> bytes:
    """El hash anterior del primer registro de un inquilino.

    Depende del inquilino a propósito. Con un génesis constante, los registros
    de una PYME podrían injertarse en la cadena de otra: los eslabones encajan
    porque nada en el hash dice de quién es la cadena. Atarlo al inquilino
    convierte ese injerto en una cadena que no verifica.
    """
    if not inquilino:
        raise ValueError("el génesis exige un inquilino")
    return hashlib.sha256(
        PREFIJO_GENESIS + ETIQUETA_GENESIS + b"|" + inquilino.encode("utf-8")
    ).digest()


def hash_de_registro(canonico: bytes, hash_anterior: bytes) -> bytes:
    """El eslabón: `SHA256(0x00 ‖ canónico ‖ hash_anterior)`.

    El hash anterior va al final y mide siempre 32 bytes, así que la
    concatenación es inequívoca sin necesidad de separar nada: los últimos 32
    bytes son el eslabón previo y lo demás es el registro.
    """
    if not isinstance(canonico, (bytes, bytearray)):
        raise TypeError(f"el canónico debe ser bytes, llegó {type(canonico).__name__}")
    if len(hash_anterior) != TAMANO_HASH:
        raise ValueError(
            f"el hash anterior mide {len(hash_anterior)} bytes; se esperaban {TAMANO_HASH}"
        )
    return hashlib.sha256(PREFIJO_HOJA + bytes(canonico) + bytes(hash_anterior)).digest()


@dataclass(frozen=True)
class Eslabon:
    """Lo mínimo que hace falta para verificar un tramo de la cadena.

    No trae los datos del registro: **la verificación no los necesita**. Es la
    propiedad que permite conservar la cadena para siempre y borrar los datos
    personales cuando toca — ver `docs/contrato-expediente.md` §5.
    """

    posicion: int
    hash_registro: bytes
    hash_anterior: bytes
    canonico: bytes | None = None
    """Ausente cuando el registro se suprimió por retención. La cadena sigue
    verificando; lo único que se pierde es poder recalcular *ese* eslabón."""

    @property
    def verificable(self) -> bool:
        return self.canonico is not None


def verificar_cadena(eslabones: Iterable[Eslabon], inquilino: str) -> int:
    """Recorre la cadena y levanta `CadenaRota` en el primer problema.

    Devuelve cuántos eslabones se pudieron recalcular de verdad. Un eslabón sin
    canónico —suprimido por retención— se acepta como enlace pero **no cuenta**:
    quien lea el resultado debe poder distinguir «verifiqué 200 registros» de
    «verifiqué 3 y confié en 197».
    """
    esperado_anterior = genesis(inquilino)
    posicion_esperada = 0
    recalculados = 0

    for eslabon in eslabones:
        if eslabon.posicion != posicion_esperada:
            raise CadenaRota(
                eslabon.posicion,
                f"hueco en la secuencia: se esperaba la posición {posicion_esperada}",
            )
        if eslabon.hash_anterior != esperado_anterior:
            raise CadenaRota(
                eslabon.posicion,
                "el eslabón no apunta al hash del registro previo; "
                "alguien insertó, borró o reordenó",
            )
        if eslabon.canonico is not None:
            recalculado = hash_de_registro(eslabon.canonico, eslabon.hash_anterior)
            if recalculado != eslabon.hash_registro:
                raise CadenaRota(
                    eslabon.posicion,
                    "el contenido no produce el hash almacenado; el registro fue alterado",
                )
            recalculados += 1
        if len(eslabon.hash_registro) != TAMANO_HASH:
            raise CadenaRota(eslabon.posicion, "el hash almacenado no mide 32 bytes")

        esperado_anterior = eslabon.hash_registro
        posicion_esperada += 1

    return recalculados


def raiz_de_merkle(hojas: Sequence[bytes]) -> bytes:
    """La raíz del árbol sobre los hashes del día (tarea 2.6).

    Los nodos internos llevan el prefijo `0x01`, distinto del `0x00` de las
    hojas: sin esa separación se puede presentar un nodo interno como si fuera
    una hoja y probar la pertenencia de un registro que nunca existió.

    Cuando un nivel tiene un número impar de nodos, el último **se promueve** en
    vez de duplicarse. Duplicarlo es la falla de Bitcoin (CVE-2012-2459): dos
    conjuntos distintos de hojas producen la misma raíz.
    """
    if not hojas:
        raise ValueError("no hay hojas: un día sin registros no tiene raíz que anclar")
    for hoja in hojas:
        if len(hoja) != TAMANO_HASH:
            raise ValueError(f"una hoja mide {len(hoja)} bytes; se esperaban {TAMANO_HASH}")

    nivel = list(hojas)
    while len(nivel) > 1:
        siguiente = []
        for indice in range(0, len(nivel) - 1, 2):
            siguiente.append(_nodo(nivel[indice], nivel[indice + 1]))
        if len(nivel) % 2:
            siguiente.append(nivel[-1])  # se promueve, no se duplica
        nivel = siguiente
    return nivel[0]


def _nodo(izquierdo: bytes, derecho: bytes) -> bytes:
    return hashlib.sha256(PREFIJO_NODO + izquierdo + derecho).digest()
