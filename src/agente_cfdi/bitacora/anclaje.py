"""Publicar la raíz del día donde no la controlamos (tarea 2.7).

## Qué compra el anclaje, exactamente

La cadena de hashes prueba que la bitácora es internamente consistente. Eso es
**circular**: la bitácora la guardamos nosotros, y quien no nos crea tampoco
tiene por qué creerle a nuestro endpoint de verificación. Con acceso a la base
podríamos reescribir todo el historial y volver a encadenarlo; saldría íntegro.

Lo que rompe la circularidad es publicar la raíz del día **donde no mandamos**.
A partir de ahí, reescribir el pasado exige además reescribir el ancla — y esa
no es nuestra.

Por eso el anclaje no es decoración: es lo único que convierte «confía en
nuestra bitácora» en «no me confíes, verifica».

## El ancla simulada tiene que verse simulada

Una implementación de mentira que devolviera un hash de transacción plausible
sería **peor que no tener nada**: pasaría por real en un video de demo y en una
captura de pantalla, y nadie notaría la diferencia hasta intentar buscarla en un
explorador de bloques.

Por eso `AnclaSimulada` marca su red con `simulada:` y la constancia lleva
`verificable_por_terceros = False`. La API propaga esa bandera. Quien mire la
respuesta sabe qué tiene enfrente sin ir a leer el código.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

PREFIJO_SIMULADA = "simulada:"


@dataclass(frozen=True)
class Constancia:
    """El comprobante de que una raíz se publicó en algún lado."""

    red: str
    referencia: str
    """El identificador con el que un tercero encuentra la publicación —un hash
    de transacción en una cadena real."""
    anclado_en: datetime

    @property
    def verificable_por_terceros(self) -> bool:
        """`False` mientras el ancla sea simulada.

        Es la diferencia entre «esto se puede comprobar sin nosotros» y «esto se
        podrá comprobar cuando conectemos la red de verdad», y la API la reporta
        tal cual en vez de dejar que se confundan.
        """
        return not self.red.startswith(PREFIJO_SIMULADA)


class ErrorDeAnclaje(RuntimeError):
    """La raíz no se pudo publicar.

    Se distingue de «el día no tuvo registros»: no haber podido anclar es una
    falla de infraestructura que se reintenta, y un día vacío no tiene nada que
    anclar.
    """


@runtime_checkable
class Ancla(Protocol):
    """Dónde se publica la raíz del día."""

    @property
    def red(self) -> str: ...

    def anclar(self, raiz: bytes, *, dia: str) -> Constancia:
        """Publica la raíz. Levanta `ErrorDeAnclaje` si no se pudo."""


@dataclass(frozen=True)
class AnclaSimulada:
    """Ancla de mentira, para que el resto del sistema se pueda probar entero.

    **No publica nada en ninguna parte.** Deriva una referencia determinista de
    la raíz para que las pruebas sean reproducibles, y se identifica como
    simulada en cada respuesta que toca.

    Sustituirla por una cadena real es cambiar esta clase por otra que cumpla el
    mismo protocolo: nada más del sistema tiene que enterarse.
    """

    etiqueta: str = "local"

    @property
    def red(self) -> str:
        return f"{PREFIJO_SIMULADA}{self.etiqueta}"

    def anclar(self, raiz: bytes, *, dia: str) -> Constancia:
        if len(raiz) != 32:
            raise ErrorDeAnclaje(f"la raíz mide {len(raiz)} bytes; se esperaban 32")
        referencia = hashlib.sha256(b"ancla-simulada|" + dia.encode() + b"|" + raiz).hexdigest()
        return Constancia(
            red=self.red,
            referencia=f"0x{referencia}",
            anclado_en=datetime.now(timezone.utc).replace(microsecond=0),
        )
