"""Serialización canónica `CORD-CANON-2`.

Lleva un registro lógico a una única cadena de bytes, de forma determinista e
**inyectiva**: dos registros distintos nunca producen los mismos bytes. Es la
entrada del hash que encadena la bitácora.

El formato usa separadores y es legible:

    CORD-CANON-2|cesion|uuid|s9F2C1A88-…|monto|d142878.90|cedido|b1

La inyectividad **no viene del separador sino del escapado**. Unir campos con
`|` sin escapar es una vulnerabilidad, no un formato: quien controle un campo de
texto libre fabrica dos registros distintos con el mismo hash. La demostración
está en `test_canonico.py::test_los_separadores_sin_escapar_colisionan`.

Aquí no es una afirmación: `descanonicalizar` recupera el registro exacto a
partir de los bytes. Una codificación que se puede decodificar sin ambigüedad es
inyectiva por construcción, y eso se prueba por ida y vuelta.

Las razones de cada decisión están en `docs/adr/0001-serializacion-canonica.md`.
**Esta función se congela al cerrar el Sprint 1**: cambiarla invalida todos los
hashes ya escritos. Una canon nueva es `CORD-CANON-3`, no una edición de esta.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, DecimalException
from enum import Enum
from typing import Any, Mapping

VERSION = "CORD-CANON-2"

SEPARADOR = "|"
ESCAPE = "\\"

# Un registro canónico es siempre **una línea**: los saltos se escapan. Así se
# puede volcar la bitácora a un archivo de texto, verla en un log o pegarla en
# un expediente sin que el formato dependa de dónde se mire.
_ESCAPES = {ESCAPE: ESCAPE + ESCAPE, SEPARADOR: ESCAPE + SEPARADOR, "\n": ESCAPE + "n", "\r": ESCAPE + "r"}
_DESESCAPES = {ESCAPE: ESCAPE, SEPARADOR: SEPARADOR, "n": "\n", "r": "\r"}

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

    El valor es la etiqueta de un solo carácter que precede a la carga. Sin ella
    un `NULO` y una cadena vacía darían los mismos bytes, que son dos hechos
    distintos: «no se declaró» y «se declaró vacío».
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

    def descanonicalizar(self, crudo: bytes) -> dict[str, Any]:
        return descanonicalizar(crudo, self)


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

    piezas = [VERSION, esquema.nombre]
    for campo in esquema.campos:
        if campo.nombre not in registro:
            if not campo.opcional:
                raise ErrorDeCanonicalizacion(
                    f"esquema '{esquema.nombre}': falta el campo obligatorio '{campo.nombre}'"
                )
            valor = None
        else:
            valor = registro[campo.nombre]

        piezas.append(campo.nombre)
        piezas.append(_codificar_valor(valor, campo))

    return SEPARADOR.join(_escapar(pieza) for pieza in piezas).encode("utf-8")


def descanonicalizar(crudo: bytes, esquema: Esquema) -> dict[str, Any]:
    """Recupera el registro a partir de sus bytes canónicos.

    **Existe para probar que la codificación es inyectiva.** Si de los bytes se
    puede recuperar el registro exacto, entonces dos registros distintos no
    pueden haber producido los mismos bytes — que es precisamente la propiedad
    de la que depende toda la bitácora.

    No es una función de conveniencia: es la mitad de la demostración. La otra
    mitad son las pruebas de ida y vuelta en `test_canonico.py`.
    """
    if not isinstance(crudo, (bytes, bytearray)):
        raise ErrorDeCanonicalizacion(
            f"se esperaban bytes, llegó {type(crudo).__name__}"
        )
    try:
        texto = bytes(crudo).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ErrorDeCanonicalizacion(f"los bytes no son UTF-8 válido: {exc}") from exc

    piezas = [_desescapar(p) for p in _partir(texto)]
    esperadas = 2 + 2 * len(esquema.campos)
    if len(piezas) != esperadas:
        raise ErrorDeCanonicalizacion(
            f"esquema '{esquema.nombre}': se esperaban {esperadas} piezas, "
            f"llegaron {len(piezas)}"
        )
    if piezas[0] != VERSION:
        raise ErrorDeCanonicalizacion(
            f"versión de canon {piezas[0]!r}; esta implementación es {VERSION}"
        )
    if piezas[1] != esquema.nombre:
        raise ErrorDeCanonicalizacion(
            f"los bytes son del esquema {piezas[1]!r}, no de '{esquema.nombre}'"
        )

    registro: dict[str, Any] = {}
    for indice, campo in enumerate(esquema.campos):
        nombre = piezas[2 + 2 * indice]
        carga = piezas[3 + 2 * indice]
        if nombre != campo.nombre:
            raise ErrorDeCanonicalizacion(
                f"se esperaba el campo '{campo.nombre}' y llegó {nombre!r}"
            )
        registro[campo.nombre] = _decodificar_valor(carga, campo)
    return registro


# --------------------------------------------------------------------------- #
# Escapado — de aquí sale la inyectividad
# --------------------------------------------------------------------------- #


def _escapar(pieza: str) -> str:
    """Vuelve el separador inofensivo dentro de un valor.

    El orden importa: la barra invertida se escapa **primero**, o el escape de
    `|` se volvería a escapar y la vuelta no sería exacta.
    """
    salida = []
    for caracter in pieza:
        salida.append(_ESCAPES.get(caracter, caracter))
    return "".join(salida)


def _desescapar(pieza: str) -> str:
    salida = []
    caracteres = iter(pieza)
    for caracter in caracteres:
        if caracter != ESCAPE:
            salida.append(caracter)
            continue
        try:
            siguiente = next(caracteres)
        except StopIteration:
            raise ErrorDeCanonicalizacion(
                "escape colgante al final de una pieza"
            ) from None
        if siguiente not in _DESESCAPES:
            raise ErrorDeCanonicalizacion(f"escape desconocido: '\\{siguiente}'")
        salida.append(_DESESCAPES[siguiente])
    return "".join(salida)


def _partir(texto: str) -> list[str]:
    """Parte por separadores **no escapados**.

    Un `str.split('|')` a secas partiría también los `\\|` que están dentro de un
    valor, y ahí se pierde la propiedad.
    """
    piezas: list[str] = []
    actual: list[str] = []
    escapando = False
    for caracter in texto:
        if escapando:
            actual.append(caracter)
            escapando = False
        elif caracter == ESCAPE:
            actual.append(caracter)
            escapando = True
        elif caracter == SEPARADOR:
            piezas.append("".join(actual))
            actual = []
        else:
            actual.append(caracter)
    if escapando:
        raise ErrorDeCanonicalizacion("escape colgante al final del registro")
    piezas.append("".join(actual))
    return piezas


# --------------------------------------------------------------------------- #
# Codificación de valores
# --------------------------------------------------------------------------- #


def _codificar_valor(valor: Any, campo: Campo) -> str:
    if valor is None:
        if not campo.opcional:
            raise ErrorDeCanonicalizacion(
                f"campo '{campo.nombre}' es obligatorio y llegó nulo"
            )
        return Tipo.NULO.value

    codificadores = {
        Tipo.CADENA: _cadena,
        Tipo.DECIMAL: _decimal,
        Tipo.ENTERO: _entero,
        Tipo.BOOLEANO: _booleano,
        Tipo.INSTANTE: _instante,
    }
    return campo.tipo.value + codificadores[campo.tipo](valor, campo)


def _decodificar_valor(carga: str, campo: Campo) -> Any:
    if not carga:
        raise ErrorDeCanonicalizacion(f"campo '{campo.nombre}': carga vacía sin etiqueta")
    etiqueta, resto = carga[0], carga[1:]

    if etiqueta == Tipo.NULO.value:
        if not campo.opcional:
            raise ErrorDeCanonicalizacion(
                f"campo '{campo.nombre}': nulo en un campo obligatorio"
            )
        if resto:
            raise ErrorDeCanonicalizacion(
                f"campo '{campo.nombre}': un nulo no lleva carga"
            )
        return None

    if etiqueta != campo.tipo.value:
        raise ErrorDeCanonicalizacion(
            f"campo '{campo.nombre}': etiqueta '{etiqueta}' no corresponde a "
            f"'{campo.tipo.value}' ({campo.tipo.name})"
        )

    if campo.tipo is Tipo.CADENA:
        return resto
    if campo.tipo is Tipo.DECIMAL:
        return Decimal(resto)
    if campo.tipo is Tipo.ENTERO:
        return int(resto)
    if campo.tipo is Tipo.BOOLEANO:
        if resto not in ("0", "1"):
            raise ErrorDeCanonicalizacion(f"campo '{campo.nombre}': booleano {resto!r}")
        return resto == "1"
    return datetime.strptime(resto, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _cadena(valor: Any, campo: Campo) -> str:
    if not isinstance(valor, str):
        raise ErrorDeCanonicalizacion(
            f"campo '{campo.nombre}': se esperaba cadena, llegó {type(valor).__name__}"
        )
    # NFC: 'ñ' precompuesta y 'n' + tilde combinante son la misma cadena para un
    # humano y bytes distintos para SHA-256.
    return unicodedata.normalize("NFC", valor)


def _decimal(valor: Any, campo: Campo) -> str:
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

    return format(cuantizado, "f")


def _entero(valor: Any, campo: Campo) -> str:
    if isinstance(valor, bool):
        raise ErrorDeCanonicalizacion(
            f"campo '{campo.nombre}': un booleano no es un entero"
        )
    if not isinstance(valor, int):
        raise ErrorDeCanonicalizacion(
            f"campo '{campo.nombre}': se esperaba entero, llegó {type(valor).__name__}"
        )
    return str(valor)


def _booleano(valor: Any, campo: Campo) -> str:
    if not isinstance(valor, bool):
        raise ErrorDeCanonicalizacion(
            f"campo '{campo.nombre}': se esperaba booleano, llegó {type(valor).__name__}"
        )
    return "1" if valor else "0"


def _instante(valor: Any, campo: Campo) -> str:
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
    return valor.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
