"""Serialización canónica `CORD-CANON-1`.

Lleva un registro lógico a una única cadena de bytes, de forma determinista y
reversible en principio (la codificación es inyectiva). Es la entrada del hash
que encadena la bitácora.

El formato y las razones de cada decisión están en `docs/adr/0001-serializacion-canonica.md`.
**Esta función se congela al cerrar el Sprint 1**: cambiarla invalida todos los
hashes ya escritos. Una canon nueva es `CORD-CANON-2`, no una edición de esta.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, DecimalException
from enum import Enum
from typing import Any, Mapping

VERSION = b"CORD-CANON-1"

# Precisión máxima admitida en una escala declarada. Un tope explícito evita que
# un esquema mal escrito pida una escala absurda y produzca cadenas gigantes.
ESCALA_MAXIMA = 18


class ErrorDeCanonicalizacion(ValueError):
    """El registro no admite una representación canónica.

    Siempre es preferible a devolver bytes de dudosa procedencia: un registro
    que no se puede canonicalizar tampoco se puede auditar.
    """


class Tipo(Enum):
    """Tipos declarables en un esquema.

    El valor es la etiqueta de un solo byte que precede a la carga en la
    codificación. `NULO` no se declara: se emite cuando un campo opcional viene
    ausente o en `None`.
    """

    CADENA = "s"
    DECIMAL = "d"
    ENTERO = "i"
    BOOLEANO = "b"
    INSTANTE = "t"
    NULO = "n"


@dataclass(frozen=True)
class Campo:
    """Un campo declarado del esquema.

    `escala` solo aplica a `DECIMAL` y es obligatoria ahí: sin escala fija,
    `100.5` y `100.50` producirían bytes distintos, que es justo lo que esta
    función existe para impedir.
    """

    nombre: str
    tipo: Tipo
    escala: int | None = None
    opcional: bool = False

    def __post_init__(self) -> None:
        if not self.nombre:
            raise ErrorDeCanonicalizacion("un campo del esquema no tiene nombre")
        if self.tipo is Tipo.NULO:
            raise ErrorDeCanonicalizacion(
                f"campo '{self.nombre}': NULO no se declara; usa opcional=True"
            )
        if self.tipo is Tipo.DECIMAL:
            if self.escala is None:
                raise ErrorDeCanonicalizacion(
                    f"campo decimal '{self.nombre}' no declara escala"
                )
            if not 0 <= self.escala <= ESCALA_MAXIMA:
                raise ErrorDeCanonicalizacion(
                    f"campo '{self.nombre}': escala {self.escala} fuera de [0, {ESCALA_MAXIMA}]"
                )
        elif self.escala is not None:
            raise ErrorDeCanonicalizacion(
                f"campo '{self.nombre}': la escala solo aplica a campos decimales"
            )


@dataclass(frozen=True)
class Esquema:
    """Conjunto ordenado de campos que define un tipo de registro.

    El nombre viaja dentro de los bytes canónicos: dos esquemas distintos nunca
    producen la misma cadena aunque coincidan campo por campo.
    """

    nombre: str
    campos: tuple[Campo, ...]

    def __post_init__(self) -> None:
        if not self.nombre:
            raise ErrorDeCanonicalizacion("el esquema no tiene nombre")
        if not self.campos:
            raise ErrorDeCanonicalizacion(f"el esquema '{self.nombre}' no declara campos")
        vistos: set[str] = set()
        for campo in self.campos:
            if campo.nombre in vistos:
                raise ErrorDeCanonicalizacion(
                    f"el esquema '{self.nombre}' declara '{campo.nombre}' dos veces"
                )
            vistos.add(campo.nombre)

    @property
    def nombres(self) -> frozenset[str]:
        return frozenset(campo.nombre for campo in self.campos)

    def canonicalizar(self, registro: Mapping[str, Any]) -> bytes:
        return canonicalizar(registro, self)


def canonicalizar(registro: Mapping[str, Any], esquema: Esquema) -> bytes:
    """Devuelve la representación canónica del registro bajo el esquema dado.

    El orden de las claves en `registro` es irrelevante: manda el orden
    declarado en el esquema. Una clave no declarada es un error — un dato que
    entra sin quedar bajo el hash es un dato que después se puede negar.
    """
    if not isinstance(registro, Mapping):
        raise ErrorDeCanonicalizacion(
            f"se esperaba un mapeo de campos, llegó {type(registro).__name__}"
        )

    sobrantes = set(registro) - esquema.nombres
    if sobrantes:
        raise ErrorDeCanonicalizacion(
            f"esquema '{esquema.nombre}': campos no declarados "
            f"{sorted(sobrantes)}; el esquema es estricto por diseño"
        )

    partes = [VERSION, _netstring(_utf8(esquema.nombre))]
    for campo in esquema.campos:
        if campo.nombre not in registro:
            if not campo.opcional:
                raise ErrorDeCanonicalizacion(
                    f"esquema '{esquema.nombre}': falta el campo obligatorio '{campo.nombre}'"
                )
            valor = None
        else:
            valor = registro[campo.nombre]

        partes.append(_netstring(_utf8(campo.nombre)))
        partes.append(_netstring(_codificar_valor(valor, campo)))

    return b"".join(partes)


# --------------------------------------------------------------------------- #
# Codificación de valores
# --------------------------------------------------------------------------- #


def _codificar_valor(valor: Any, campo: Campo) -> bytes:
    if valor is None:
        if not campo.opcional:
            raise ErrorDeCanonicalizacion(
                f"campo '{campo.nombre}' es obligatorio y llegó nulo"
            )
        return Tipo.NULO.value.encode("ascii")

    codificadores = {
        Tipo.CADENA: _cadena,
        Tipo.DECIMAL: _decimal,
        Tipo.ENTERO: _entero,
        Tipo.BOOLEANO: _booleano,
        Tipo.INSTANTE: _instante,
    }
    carga = codificadores[campo.tipo](valor, campo)
    return campo.tipo.value.encode("ascii") + carga


def _cadena(valor: Any, campo: Campo) -> bytes:
    if not isinstance(valor, str):
        raise ErrorDeCanonicalizacion(
            f"campo '{campo.nombre}': se esperaba cadena, llegó {type(valor).__name__}"
        )
    # NFC: 'ñ' precompuesta y 'n' + tilde combinante son la misma cadena para un
    # humano y bytes distintos para SHA-256.
    return _utf8(unicodedata.normalize("NFC", valor))


def _decimal(valor: Any, campo: Campo) -> bytes:
    assert campo.escala is not None  # garantizado por Campo.__post_init__

    if isinstance(valor, bool):
        raise ErrorDeCanonicalizacion(
            f"campo '{campo.nombre}': un booleano no es un decimal"
        )
    if isinstance(valor, float):
        # 0.1 + 0.2 no es 0.3, y ningún formato de salida arregla eso.
        raise ErrorDeCanonicalizacion(
            f"campo '{campo.nombre}': float no se admite en un campo monetario; "
            f"usa Decimal, int o str"
        )
    if not isinstance(valor, (Decimal, int, str)):
        raise ErrorDeCanonicalizacion(
            f"campo '{campo.nombre}': se esperaba decimal, llegó {type(valor).__name__}"
        )

    try:
        numero = Decimal(valor)
    except (DecimalException, ValueError) as exc:
        raise ErrorDeCanonicalizacion(
            f"campo '{campo.nombre}': '{valor}' no es un decimal válido"
        ) from exc

    if not numero.is_finite():
        raise ErrorDeCanonicalizacion(
            f"campo '{campo.nombre}': '{valor}' no es un número finito"
        )

    cuantizado = numero.quantize(Decimal(1).scaleb(-campo.escala))
    if cuantizado != numero:
        # Redondear en silencio mete dos importes distintos a la bitácora con el
        # mismo hash. El problema se corrige en el origen, no aquí.
        raise ErrorDeCanonicalizacion(
            f"campo '{campo.nombre}': '{valor}' tiene más precisión que la escala "
            f"declarada ({campo.escala}); no se redondea en silencio"
        )

    if cuantizado.is_zero():
        cuantizado = abs(cuantizado)  # '-0.00' y '0.00' son el mismo importe

    return _utf8(format(cuantizado, "f"))


def _entero(valor: Any, campo: Campo) -> bytes:
    if isinstance(valor, bool):
        raise ErrorDeCanonicalizacion(
            f"campo '{campo.nombre}': un booleano no es un entero"
        )
    if not isinstance(valor, int):
        raise ErrorDeCanonicalizacion(
            f"campo '{campo.nombre}': se esperaba entero, llegó {type(valor).__name__}"
        )
    return _utf8(str(valor))


def _booleano(valor: Any, campo: Campo) -> bytes:
    if not isinstance(valor, bool):
        raise ErrorDeCanonicalizacion(
            f"campo '{campo.nombre}': se esperaba booleano, llegó {type(valor).__name__}"
        )
    return b"1" if valor else b"0"


def _instante(valor: Any, campo: Campo) -> bytes:
    if not isinstance(valor, datetime):
        raise ErrorDeCanonicalizacion(
            f"campo '{campo.nombre}': se esperaba datetime, llegó {type(valor).__name__}"
        )
    if valor.tzinfo is None or valor.tzinfo.utcoffset(valor) is None:
        # Asumir UTC o la hora local daría hashes distintos según dónde corra el
        # proceso. Un instante sin zona no es un instante.
        raise ErrorDeCanonicalizacion(
            f"campo '{campo.nombre}': datetime sin zona horaria; "
            f"la canon exige un instante inequívoco"
        )
    if valor.microsecond:
        raise ErrorDeCanonicalizacion(
            f"campo '{campo.nombre}': la canon tiene precisión de segundo y el "
            f"valor trae fracción; no se trunca en silencio"
        )
    return _utf8(valor.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))


# --------------------------------------------------------------------------- #
# Lectura humana
# --------------------------------------------------------------------------- #


def describir(registro: Mapping[str, Any], esquema: Esquema, *, separador: str = " | ") -> str:
    """Rinde el registro con separadores, **para que lo lea una persona**.

    Los bytes canónicos son ilegibles a propósito (`10:referencia16:sOC-88…`) y
    eso estorba al depurar, al revisar un expediente o al enseñar la demo. Esta
    función da la vista con separadores que se quiere para eso.

    **Su salida nunca se hashea ni se guarda.** Es la misma razón por la que
    `canonicalizar` no usa separadores: no son inyectivos. Aquí da igual, porque
    de esta cadena no depende ninguna afirmación de integridad; allá es fatal.

    Separar las dos representaciones —una para la máquina, otra para el humano—
    da la legibilidad sin tocar la propiedad que sostiene la bitácora.
    """
    partes = [f"esquema={esquema.nombre}"]
    for campo in esquema.campos:
        valor = registro.get(campo.nombre)
        if valor is None:
            partes.append(f"{campo.nombre}=∅")
        else:
            rendido = _codificar_valor(valor, campo)[1:].decode("utf-8")
            partes.append(f"{campo.nombre}={rendido}")
    return separador.join(partes)


# --------------------------------------------------------------------------- #
# Primitivas
# --------------------------------------------------------------------------- #


def _netstring(crudo: bytes) -> bytes:
    """`len:bytes` — codificación con prefijo de longitud.

    Es lo que hace la concatenación inyectiva sin necesidad de escapar nada:
    ningún contenido de un campo puede simular el final de ese campo.

    **Por qué no separadores.** Con `|` entre campos, estos dos registros
    distintos producen los mismos bytes y por lo tanto el mismo hash:

        referencia="OC-88|900000.00", monto="1.00"
        referencia="OC-88",           monto="900000.00|1.00"

    Quien controle un campo de texto libre —`concepto` en un CFDI lo es—
    fabrica pares así a voluntad. En una bitácora cuyo único propósito es
    probar que nadie alteró nada, dos registros indistinguibles son el final
    del argumento. Está fijado en `test_canonico.py::test_los_separadores_colisionan`.

    Escapar los separadores también funcionaría, pero mueve la corrección a un
    punto donde un error es silencioso: si el escape falla, el hash sigue
    saliendo y nadie se entera hasta que alguien lo explota.
    """
    return str(len(crudo)).encode("ascii") + b":" + crudo


def _utf8(texto: str) -> bytes:
    return texto.encode("utf-8")
