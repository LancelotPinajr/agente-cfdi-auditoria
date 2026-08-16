"""Los cuerpos de petición y respuesta de la API (tarea 2.4).

## El dinero llega como cadena, nunca como número JSON

Un número en JSON es un `double` de IEEE 754, y `142878.90` no es representable
en binario: el valor más cercano es `142878.899999999994179233908653259277…`.
Si el importe entra como número, el importe que se firma en la bitácora **no es
el que mandó el cliente**, y el hash queda tomado sobre un dato que nadie
escribió.

Por eso los montos se declaran `str` y se convierten a `Decimal` a mano: un
número JSON se rechaza con un mensaje que explica por qué, en vez de aceptarlo y
perder centavos en silencio.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, Field, field_validator

MONEDAS = {"MXN", "USD"}


def _a_decimal(crudo: object, campo: str) -> Decimal:
    if isinstance(crudo, float):
        raise ValueError(
            f"{campo} llegó como número JSON, que es un double de punto flotante y "
            f"no representa importes con exactitud. Mándalo como cadena: \"142878.90\"."
        )
    if isinstance(crudo, Decimal):
        return crudo
    if not isinstance(crudo, str):
        raise ValueError(f"{campo} debe ser una cadena decimal, llegó {type(crudo).__name__}")
    try:
        valor = Decimal(crudo.strip())
    except InvalidOperation:
        raise ValueError(f"{campo}={crudo!r} no es un decimal") from None
    if not valor.is_finite():
        raise ValueError(f"{campo}={crudo!r} no es finito")
    if valor <= 0:
        raise ValueError(f"{campo} debe ser positivo, llegó {valor}")
    if -valor.as_tuple().exponent > 2:
        raise ValueError(f"{campo}={crudo!r} trae más de dos decimales")
    return valor


class PeticionDeCesion(BaseModel):
    uuid: str = Field(min_length=36, max_length=36)
    financiador: str = Field(min_length=1, max_length=200)
    total: Decimal
    moneda: str = "MXN"

    @field_validator("total", mode="before")
    @classmethod
    def _total_exacto(cls, crudo: object) -> Decimal:
        return _a_decimal(crudo, "total")

    @field_validator("uuid")
    @classmethod
    def _uuid_normalizado(cls, crudo: str) -> str:
        return crudo.strip().upper()

    @field_validator("moneda")
    @classmethod
    def _moneda_soportada(cls, crudo: str) -> str:
        moneda = crudo.strip().upper()
        if moneda not in MONEDAS:
            # La escala del importe no se puede adivinar: el yen no tiene
            # decimales, y equivocarla corrompe el hash del registro.
            raise ValueError(f"moneda {moneda!r} no soportada; se admiten {sorted(MONEDAS)}")
        return moneda


class RegistroAuditado(BaseModel):
    uuid: str
    posicion: int
    veredicto: str
    hash: str
    monto_del_cfdi: str
    monto_en_libros: str | None = None


class LecturaRechazada(BaseModel):
    archivo: str
    motivo: str
    detalle: str
    uuid: str | None = None


class RespuestaDeIngesta(BaseModel):
    """El resultado del lote, comprobante por comprobante.

    Se reportan los rechazos **con nombre de archivo**: un lote de 200 CFDI con
    uno malo tiene que decir cuál, o el operador no puede corregir nada.
    """

    auditados: int
    rechazados: int
    hallazgos: int
    fuente_de_libros: str
    registros: list[RegistroAuditado]
    fallas: list[LecturaRechazada]
    punta: str
    altura: int


class RespuestaDeCesion(BaseModel):
    aceptada: bool
    motivo: str
    posicion: int
    uuid: str
    repetida: bool = False
    posicion_de_la_cesion_previa: int | None = None
    veredicto: str
    """El resultado de la auditoría del folio que se está cediendo.

    Va en la respuesta de la cesión y no solo en la del expediente. Una cesión
    aceptada sobre una factura `sin_respaldo` devolvería si no un `201` limpio, y
    el financiador se enteraría de que compró una cuenta sin respaldo contable
    cuando fuera a cobrarla — que es exactamente lo que este producto existe
    para evitar.
    """

    advertencia: str | None = None
    """Presente cuando se cede un folio con hallazgos de auditoría."""


class EstadoDeCesion(BaseModel):
    uuid: str
    cedida: bool
    posicion: int | None = None
    cedido_en: str | None = None
    auditada: bool = False
    veredicto: str | None = None
    # El financiador NO va aquí. Ver `api/app.py`: saber que un folio está
    # tomado basta para frenar la operación; saber a nombre de quién no es
    # asunto de un tercero.
