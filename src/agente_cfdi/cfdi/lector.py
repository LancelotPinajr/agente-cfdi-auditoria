"""Lector de CFDI 4.0 (tareas 1.8 y 1.9).

Extrae de un comprobante timbrado los datos que la bitácora necesita: UUID, RFC
del emisor y del receptor, total, moneda y fechas. Es consciente de espacios de
nombres, así que le da igual si el XML viene con prefijo `cfdi:`, con el espacio
por defecto o con un prefijo cualquiera.

**Lo que este lector NO hace:** verificar el sello del SAT. Comprobar que un CFDI
fue realmente timbrado exige el certificado del PAC y la cadena original, y está
fuera de alcance en esta ventana. El agente prueba que *su bitácora* no fue
alterada, no que el comprobante sea auténtico ante el SAT. Son dos afirmaciones
distintas y conviene no confundirlas.

Decisiones que se explican en `docs/adr/0003-lectura-de-cfdi.md`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, DecimalException
from typing import Mapping
from xml.etree import ElementTree as ET

from ..dominio.rfc import PATRON_RFC
from .errores import CFDIInvalido, Motivo

NS_CFDI_4 = "http://www.sat.gob.mx/cfd/4"
NS_CFDI_3 = "http://www.sat.gob.mx/cfd/3"  # solo para dar un error útil
NS_TFD = "http://www.sat.gob.mx/TimbreFiscalDigital"

# Un CFDI de 200 conceptos anda en decenas de KB. El tope corta el archivo
# absurdo antes de darle memoria, no después.
TAMANO_MAXIMO_BYTES = 4 * 1024 * 1024

# `Fecha` en CFDI 4.0: hora local del lugar de expedición, sin zona y sin
# fracción de segundo. El patrón del esquema es exactamente este.
PATRON_FECHA = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])T\d{2}:\d{2}:\d{2}$")

PATRON_UUID = re.compile(
    r"^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$"
)

# Monedas con dos decimales. Ampliar esta tabla es el único cambio que hace falta
# para admitir otra: la escala del importe **no** se puede adivinar (el yen tiene
# cero decimales) y equivocarla corrompe el hash del registro.
DECIMALES_POR_MONEDA = {"MXN": 2, "USD": 2}


@dataclass(frozen=True)
class ComprobanteLeido:
    """Los datos de un CFDI que la bitácora encadena.

    `fecha_emision` y `fecha_timbrado` son **sin zona horaria a propósito**: un
    CFDI declara un reloj de pared local, no un instante. Inventarles una zona
    sería fabricar información que el documento no trae.
    """

    uuid: str
    rfc_emisor: str
    rfc_receptor: str
    total: Decimal
    moneda: str
    fecha_emision: datetime
    fecha_timbrado: datetime
    version: str
    tipo_comprobante: str | None = None
    metodo_pago: str | None = None
    forma_pago: str | None = None
    serie: str | None = None
    folio: str | None = None
    nombre_emisor: str | None = None
    nombre_receptor: str | None = None

    @property
    def fecha_emision_declarada(self) -> str:
        """La fecha tal como la declara el comprobante, en su forma canónica."""
        return self.fecha_emision.strftime("%Y-%m-%dT%H:%M:%S")


def leer_cfdi(documento: str | bytes) -> ComprobanteLeido:
    """Lee un CFDI 4.0 timbrado.

    Levanta `CFDIInvalido` —siempre con motivo y detalle— ante cualquier
    documento que no lo sea. Nunca deja escapar una excepción del parser.
    """
    crudo = _a_bytes(documento)
    arbol = _parsear(crudo)
    _verificar_que_es_cfdi_4(arbol)

    timbre = arbol.find(f".//{{{NS_TFD}}}TimbreFiscalDigital")
    if timbre is None:
        raise CFDIInvalido(
            Motivo.SIN_TIMBRE,
            "el comprobante no trae complemento TimbreFiscalDigital; sin timbre "
            "no hay UUID y no es una factura cedible",
        )

    uuid = _uuid(timbre)
    emisor = _parte(arbol, "Emisor", Motivo.EMISOR_AUSENTE, uuid)
    receptor = _parte(arbol, "Receptor", Motivo.RECEPTOR_AUSENTE, uuid)
    moneda = _moneda(arbol, uuid)

    return ComprobanteLeido(
        uuid=uuid,
        rfc_emisor=_rfc(emisor, "Emisor", uuid),
        rfc_receptor=_rfc(receptor, "Receptor", uuid),
        total=_total(arbol, moneda, uuid),
        moneda=moneda,
        fecha_emision=_fecha(arbol.get("Fecha"), "Comprobante/@Fecha", uuid),
        fecha_timbrado=_fecha(
            timbre.get("FechaTimbrado"), "TimbreFiscalDigital/@FechaTimbrado", uuid
        ),
        version=arbol.get("Version"),
        tipo_comprobante=arbol.get("TipoDeComprobante"),
        metodo_pago=arbol.get("MetodoPago"),
        forma_pago=arbol.get("FormaPago"),
        serie=_texto(arbol.get("Serie")),
        folio=_texto(arbol.get("Folio")),
        nombre_emisor=_texto(emisor.get("Nombre")),
        nombre_receptor=_texto(receptor.get("Nombre")),
    )


# --------------------------------------------------------------------------- #
# Parseo endurecido
# --------------------------------------------------------------------------- #


class _ConstructorSinDTD(ET.TreeBuilder):
    """Constructor que se niega a procesar una declaración de tipo de documento.

    `xml.etree` expande entidades internas: diez líneas de DTD bastan para pedir
    gigabytes de memoria (la «bomba de mil millones de risas»), y una entidad
    externa convierte al lector en un lector de archivos del servidor.

    Un CFDI **nunca** lleva DOCTYPE. Rechazarlo de plano elimina las dos familias
    de ataque de un golpe, sin depender de una librería externa y sin intentar
    adivinar cuál expansión es aceptable.
    """

    def doctype(self, nombre, pubid, system):  # noqa: D102 - firma impuesta por ET
        raise CFDIInvalido(
            Motivo.DOCUMENTO_PELIGROSO,
            f"el documento declara un DOCTYPE ({nombre!r}); un CFDI no lleva DTD "
            f"y procesarla abre la puerta a expansión de entidades",
        )


def _a_bytes(documento: str | bytes) -> bytes:
    if isinstance(documento, str):
        crudo = documento.encode("utf-8")
    elif isinstance(documento, (bytes, bytearray)):
        crudo = bytes(documento)
    else:
        raise CFDIInvalido(
            Motivo.XML_MAL_FORMADO,
            f"se esperaba texto o bytes, llegó {type(documento).__name__}",
        )
    if not crudo.strip():
        raise CFDIInvalido(Motivo.XML_MAL_FORMADO, "el documento está vacío")
    if len(crudo) > TAMANO_MAXIMO_BYTES:
        raise CFDIInvalido(
            Motivo.DEMASIADO_GRANDE,
            f"{len(crudo)} bytes exceden el tope de {TAMANO_MAXIMO_BYTES}",
        )
    return crudo


def _parsear(crudo: bytes) -> ET.Element:
    try:
        return ET.fromstring(crudo, parser=ET.XMLParser(target=_ConstructorSinDTD()))
    except CFDIInvalido:
        raise  # el rechazo de DOCTYPE viaja intacto
    except ET.ParseError as exc:
        raise CFDIInvalido(
            Motivo.XML_MAL_FORMADO, f"el XML no está bien formado: {exc}"
        ) from exc
    except (ValueError, UnicodeDecodeError) as exc:
        # Codificación declarada que no corresponde al contenido, entre otras.
        raise CFDIInvalido(
            Motivo.XML_MAL_FORMADO, f"el documento no se pudo decodificar: {exc}"
        ) from exc


def _verificar_que_es_cfdi_4(arbol: ET.Element) -> None:
    if arbol.tag == f"{{{NS_CFDI_3}}}Comprobante":
        raise CFDIInvalido(
            Motivo.VERSION_NO_SOPORTADA,
            "es un CFDI 3.3; desde 2023 solo 4.0 es válido y 3.3 no trae los "
            "campos que el expediente necesita (RegimenFiscalReceptor, Exportacion)",
        )
    if arbol.tag != f"{{{NS_CFDI_4}}}Comprobante":
        raise CFDIInvalido(
            Motivo.NO_ES_CFDI,
            f"la raíz es {arbol.tag!r}; se esperaba un Comprobante en el espacio "
            f"de nombres {NS_CFDI_4}",
        )
    version = arbol.get("Version")
    if version != "4.0":
        raise CFDIInvalido(
            Motivo.VERSION_NO_SOPORTADA,
            f"el atributo Version dice {version!r}; solo se admite '4.0'",
        )


# --------------------------------------------------------------------------- #
# Extracción de campos
# --------------------------------------------------------------------------- #


def _uuid(timbre: ET.Element) -> str:
    crudo = timbre.get("UUID")
    if not crudo:
        raise CFDIInvalido(
            Motivo.UUID_AUSENTE, "el TimbreFiscalDigital no trae atributo UUID"
        )
    # A mayúsculas siempre. Algunos PAC timbran en minúsculas y el mismo folio
    # fiscal daría dos hashes distintos: la cesión duplicada pasaría de largo
    # justo porque el atacante cambió el case. Normalizar aquí lo cierra.
    normalizado = crudo.strip().upper()
    if not PATRON_UUID.match(normalizado):
        raise CFDIInvalido(
            Motivo.UUID_MAL_FORMADO,
            f"{crudo!r} no tiene la forma de un folio fiscal (8-4-4-4-12 hexadecimal)",
        )
    return normalizado


def _parte(arbol: ET.Element, etiqueta: str, motivo: Motivo, uuid: str) -> ET.Element:
    nodo = arbol.find(f"{{{NS_CFDI_4}}}{etiqueta}")
    if nodo is None:
        raise CFDIInvalido(
            motivo, f"el comprobante no trae elemento {etiqueta}", uuid=uuid
        )
    return nodo


def _rfc(nodo: ET.Element, etiqueta: str, uuid: str) -> str:
    crudo = nodo.get("Rfc")
    if not crudo:
        raise CFDIInvalido(
            Motivo.RFC_MAL_FORMADO, f"{etiqueta} sin atributo Rfc", uuid=uuid
        )
    normalizado = crudo.strip().upper()
    if not PATRON_RFC.match(normalizado):
        raise CFDIInvalido(
            Motivo.RFC_MAL_FORMADO,
            f"el RFC del {etiqueta.lower()} ({crudo!r}) no cumple el patrón del SAT",
            uuid=uuid,
        )
    return normalizado


def _moneda(arbol: ET.Element, uuid: str) -> str:
    crudo = arbol.get("Moneda")
    if not crudo:
        raise CFDIInvalido(
            Motivo.MONEDA_AUSENTE, "el comprobante no declara Moneda", uuid=uuid
        )
    moneda = crudo.strip().upper()
    if moneda not in DECIMALES_POR_MONEDA:
        raise CFDIInvalido(
            Motivo.MONEDA_NO_SOPORTADA,
            f"moneda {moneda!r} fuera de alcance; solo "
            f"{sorted(DECIMALES_POR_MONEDA)} porque la escala del importe no se "
            f"puede adivinar y equivocarla corrompe el hash del registro",
            uuid=uuid,
        )
    return moneda


def _total(arbol: ET.Element, moneda: str, uuid: str) -> Decimal:
    crudo = arbol.get("Total")
    if crudo is None or not crudo.strip():
        raise CFDIInvalido(
            Motivo.TOTAL_AUSENTE, "el comprobante no trae atributo Total", uuid=uuid
        )
    texto = crudo.strip()
    try:
        total = Decimal(texto)
    except (DecimalException, ValueError) as exc:
        raise CFDIInvalido(
            Motivo.TOTAL_INVALIDO, f"Total={crudo!r} no es un número", uuid=uuid
        ) from exc

    if not total.is_finite():
        raise CFDIInvalido(
            Motivo.TOTAL_INVALIDO, f"Total={crudo!r} no es finito", uuid=uuid
        )
    if total < 0:
        raise CFDIInvalido(
            Motivo.TOTAL_INVALIDO,
            f"Total={crudo!r} es negativo; una nota de crédito se emite como "
            f"comprobante de egreso, no con signo",
            uuid=uuid,
        )

    escala = DECIMALES_POR_MONEDA[moneda]
    if -total.as_tuple().exponent > escala:
        # Truncar aquí metería a la bitácora un importe distinto del declarado.
        raise CFDIInvalido(
            Motivo.TOTAL_INVALIDO,
            f"Total={crudo!r} trae más de {escala} decimales para {moneda}",
            uuid=uuid,
        )
    return total.quantize(Decimal(1).scaleb(-escala))


def _fecha(crudo: str | None, ubicacion: str, uuid: str) -> datetime:
    if not crudo:
        raise CFDIInvalido(
            Motivo.FECHA_AUSENTE, f"falta {ubicacion}", uuid=uuid
        )
    texto = crudo.strip()
    if not PATRON_FECHA.match(texto):
        raise CFDIInvalido(
            Motivo.FECHA_INVALIDA,
            f"{ubicacion}={crudo!r} no cumple el formato AAAA-MM-DDThh:mm:ss "
            f"del esquema (sin zona horaria y sin fracción de segundo)",
            uuid=uuid,
        )
    try:
        # El patrón admite 2026-02-31; solo el calendario lo desmiente.
        return datetime.strptime(texto, "%Y-%m-%dT%H:%M:%S")
    except ValueError as exc:
        raise CFDIInvalido(
            Motivo.FECHA_INVALIDA, f"{ubicacion}={crudo!r} no existe en el calendario", uuid=uuid
        ) from exc


def _texto(crudo: str | None) -> str | None:
    if crudo is None:
        return None
    limpio = unicodedata.normalize("NFC", crudo.strip())
    return limpio or None


# --------------------------------------------------------------------------- #
# Lectura por lote
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class LecturaFallida:
    """Un documento del lote que no se pudo leer, y por qué."""

    origen: str
    motivo: Motivo
    detalle: str


@dataclass(frozen=True)
class ResultadoDeLote:
    leidos: tuple[ComprobanteLeido, ...]
    fallidos: tuple[LecturaFallida, ...]

    @property
    def hubo_rechazos(self) -> bool:
        return bool(self.fallidos)

    def __len__(self) -> int:
        return len(self.leidos) + len(self.fallidos)


def leer_lote(documentos: Mapping[str, str | bytes]) -> ResultadoDeLote:
    """Lee un lote completo separando lo leído de lo rechazado.

    Un archivo corrupto **no puede tumbar el lote**: la PYME sube 200 CFDI y uno
    viene truncado, y el agente tiene que procesar los 199 y decir exactamente
    cuál falló y por qué. Por eso aquí el fallo es un dato y no una excepción —
    al revés que en `leer_cfdi`, donde leer un solo documento y que salga mal sí
    es un error del que llama.

    `documentos` va indexado por origen (nombre de archivo o identificador del
    lote) porque «uno de los 200 no sirve» no le sirve a nadie.
    """
    leidos: list[ComprobanteLeido] = []
    fallidos: list[LecturaFallida] = []
    for origen, documento in documentos.items():
        try:
            leidos.append(leer_cfdi(documento))
        except CFDIInvalido as exc:
            fallidos.append(
                LecturaFallida(origen=origen, motivo=exc.motivo, detalle=exc.detalle)
            )
    return ResultadoDeLote(leidos=tuple(leidos), fallidos=tuple(fallidos))
