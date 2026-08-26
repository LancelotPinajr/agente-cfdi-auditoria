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


class PasoDeLaRuta(BaseModel):
    hermano: str
    hermano_a_la_derecha: bool
    """El lado viaja con el hash porque `SHA256(0x01‖a‖b)` no es `SHA256(0x01‖b‖a)`.
    Un verificador que adivine el orden acepta pruebas falsas la mitad de las veces."""


class ConstanciaDeAnclaje(BaseModel):
    red: str
    referencia: str
    anclado_en: str
    verificable_por_terceros: bool
    """`False` mientras el ancla sea simulada. Se reporta en vez de dejar que se
    confunda con una publicación real — ver `bitacora/anclaje.py`."""


class RespuestaDeAnclaje(ConstanciaDeAnclaje):
    dia: str
    raiz: str
    registros: int


class PruebaDeIntegridad(BaseModel):
    """Lo que un tercero necesita para comprobar un folio sin confiar en nosotros.

    **No trae los registros de las demás operaciones de la PYME.** Los hermanos
    de la ruta son hashes, y de un hash no sale el RFC ni el monto de nadie: por
    eso se usa un árbol en vez de publicar la bitácora.
    """

    uuid: str
    posicion: int
    dia: str
    canonico: str
    """El registro en su forma canónica, en base64.

    Se entrega el contenido y no la hoja ya calculada: si el verificador
    aceptara una hoja hecha, se le podría entregar el hash de un nodo interno y
    armar un camino válido para un registro que nunca existió.
    """

    hash_anterior: str
    hoja: str
    ruta: list[PasoDeLaRuta]
    raiz: str
    registros_del_dia: int
    ancla: ConstanciaDeAnclaje | None
    verificable_por_terceros: bool
    advertencia: str | None = None


class RespuestaDeCierre(BaseModel):
    """El resultado del cierre del día (tarea 2.9).

    Lo consume Cloud Scheduler, no una persona, así que `estado` es una palabra
    fija y no un texto libre: un job que reporta prosa no se puede vigilar.
    """

    estado: str
    """`anclado`, `ya_estaba_anclado`, `sin_movimientos` o `cadena_rota`."""

    dia: str
    registros_del_dia: int
    altura: int
    verificados: int
    raiz: str | None = None
    ancla: ConstanciaDeAnclaje | None = None
    detalle: str


class Semaforo(BaseModel):
    """El estado de integridad de un vistazo (tarea 3.11).

    ## Por qué son tres colores y no dos

    El plan pedía verde «cadena íntegra» / rojo «manipulación detectada». Faltaba
    un estado, y es justo el que tenemos hoy: **la cadena está íntegra pero nadie
    de fuera puede comprobarlo**, porque el ancla es simulada.

    Pintarlo verde sería mentir en el lugar más visible del producto: un color
    verde dice «esto está comprobado» y aquí lo único comprobado es que nuestra
    bitácora es consistente consigo misma. Pintarlo rojo sería peor —no hay
    manipulación— y volvería inútil la única señal de alarma.

    Por eso el verde exige **las dos cosas**: cadena íntegra Y raíz publicada en
    una red real. El día que el anclaje deje de ser simulado, esto se pone verde
    solo, sin tocar una línea.

    ## Por qué son cuatro y no tres (tarea 3.16)

    Faltaba distinguir **«íntegra» de «vacía»**, y no es un matiz: una cadena de
    altura 0 verifica trivialmente porque no hay ningún eslabón que pueda no
    cuadrar. Hasta hoy ese caso salía ámbar «ÍNTEGRA, SIN PUBLICAR», con un
    detalle que decía que los eslabones cuadraban. Cuadraban cero.

    Importa porque la bitácora vive en un SQLite en `/tmp` de Cloud Run y se
    pierde al reciclar la instancia. El escenario real no es teórico: se recicla
    la instancia, la cadena arranca en altura 0, y el semáforo informa que todo
    está en orden. **Afirmar integridad justo después de haberlo perdido todo es
    el fallo exacto que este producto existe para no cometer**, y sería el más
    caro de que lo encuentre alguien de fuera.

    El gris no es una alarma —no hay manipulación, y pintarlo rojo gastaría la
    única señal que debe significar algo— pero tampoco es una confirmación. Dice
    lo único honesto que se puede decir: aquí no hay nada que verificar.
    """

    color: str
    """`verde`, `ambar`, `gris` o `rojo`."""

    titulo: str
    detalle: str
    altura: int
    verificados: int
    posicion_del_problema: int | None = None
    dia: str | None = None
    ancla: ConstanciaDeAnclaje | None = None
    enlace_al_explorador: str | None = None
    """`None` cuando no hay dónde comprobarlo. No se inventa una URL."""
