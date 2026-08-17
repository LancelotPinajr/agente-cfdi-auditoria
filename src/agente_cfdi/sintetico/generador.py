"""Generador de CFDI sintéticos (tareas 1.14, 1.15 y 1.16).

Produce comprobantes **estructuralmente válidos** contra el esquema de CFDI 4.0,
con valores de catálogo reales y RFC que no pueden pertenecer a nadie, y los
serializa en varias formas de XML distintas para que el lector se pruebe contra
la variedad que existe allá afuera.

Lo que este generador **no** hace, dicho de frente: no firma. `Sello`,
`Certificado` y `SelloSAT` son relleno con la forma correcta pero sin validez
criptográfica — timbrar exige el certificado de un PAC. Validez estructural no
es validez fiscal, y el sistema nunca debe presentar un comprobante sintético
como timbrado. Ver `docs/datos-sinteticos.md`.

Todo el generador es determinista dada una semilla: el mismo `semilla` produce
el mismo lote, byte por byte. Es lo que hace reproducible la demo del video.
"""

from __future__ import annotations

import random
import uuid as _uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from xml.sax.saxutils import quoteattr

from . import catalogos as cat
from .rfc import rfc_persona_moral

NS_CFDI = "http://www.sat.gob.mx/cfd/4"
NS_TFD = "http://www.sat.gob.mx/TimbreFiscalDigital"
NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"
NS_ADDENDA = "http://cord.mx/addenda/terminos"

CENTAVO = Decimal("0.01")

# Un CFDI declara su fecha en hora local del lugar de expedición, sin zona. No
# es un instante: es un reloj de pared declarado. El lector lo conserva tal cual
# en vez de inventarle una zona — ver `docs/adr/0003-lectura-de-cfdi.md`.
FORMATO_FECHA_CFDI = "%Y-%m-%dT%H:%M:%S"


class VarianteXml(Enum):
    """Formas distintas de escribir el mismo comprobante.

    Todas son XML válido y equivalente para un procesador consciente de espacios
    de nombres. Existen porque un lector que busque la cadena `"cfdi:Emisor"` en
    el texto funciona con la primera y falla con las otras dos — y en producción
    llegan las tres.
    """

    PREFIJO_ESTANDAR = "prefijo_estandar"
    """`<cfdi:Comprobante>` con todo declarado en la raíz. Lo más común."""

    SIN_PREFIJO = "sin_prefijo"
    """CFDI como espacio de nombres por defecto: `<Comprobante xmlns="...">`."""

    PREFIJO_ALTERNO = "prefijo_alterno"
    """Prefijo `c:`, el timbre declarando su propio espacio en el hijo, y una
    Addenda con elementos ajenos que el lector debe ignorar sin quejarse."""


@dataclass(frozen=True)
class Contribuyente:
    rfc: str
    nombre: str
    regimen_fiscal: str
    codigo_postal: str
    giro: cat.Giro


@dataclass(frozen=True)
class Concepto:
    clave_prod_serv: str
    clave_unidad: str
    descripcion: str
    cantidad: int
    valor_unitario: Decimal

    @property
    def importe(self) -> Decimal:
        # Exacto por construcción: entero por decimal de escala 2.
        return self.cantidad * self.valor_unitario

    @property
    def iva(self) -> Decimal:
        return (self.importe * Decimal("0.16")).quantize(CENTAVO, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ComprobanteSintetico:
    """Un CFDI de ingreso sintético, con los datos comerciales que lo rodean."""

    uuid: str
    serie: str
    folio: str
    fecha_emision: datetime  # local del lugar de expedición, sin zona (así es CFDI)
    fecha_timbrado: datetime
    emisor: Contribuyente
    receptor: Contribuyente
    uso_cfdi: str
    conceptos: tuple[Concepto, ...]
    dias_credito: int
    variante: VarianteXml

    @property
    def subtotal(self) -> Decimal:
        return sum((c.importe for c in self.conceptos), Decimal("0.00"))

    @property
    def iva_trasladado(self) -> Decimal:
        return sum((c.iva for c in self.conceptos), Decimal("0.00"))

    @property
    def total(self) -> Decimal:
        return self.subtotal + self.iva_trasladado

    @property
    def fecha_vencimiento(self) -> datetime:
        return self.fecha_emision + timedelta(days=self.dias_credito)

    def a_xml(self) -> str:
        return _serializar(self)


@dataclass(frozen=True)
class Lote:
    """Un lote de CFDI tal como lo subiría una PYME."""

    comprobantes: tuple[ComprobanteSintetico, ...]
    semilla: int
    uuid_duplicado: str | None = None
    """UUID plantado dos veces en el lote, si se pidió el escenario de fraude."""

    def __len__(self) -> int:
        return len(self.comprobantes)


# --------------------------------------------------------------------------- #
# Generación
# --------------------------------------------------------------------------- #

_LUGARES = ("Monterrey", "Guadalajara", "Querétaro", "Puebla", "León", "Saltillo")
_FORMAS_JURIDICAS = ("S.A. de C.V.", "S. de R.L. de C.V.", "S.A.P.I. de C.V.")
_RAICES = (
    "Aceros del Norte",
    "Transportes Peñón",
    "Sistemas Álamo",
    "Comercializadora Bajío",
    "Constructora Mezquite",
    "Industrias Cañada",
    "Refacciones Ébano",
    "Logística Ocotlán",
)

# Los plazos de cobro que de verdad se ven en factoraje de PYME. 30 y 60 días
# dominan; 90 existe y es el que más caro cuesta financiar.
_PLAZOS = ((30, 0.40), (45, 0.20), (60, 0.28), (90, 0.12))


def contribuyente(
    rng: random.Random,
    giro: cat.Giro | None = None,
    *,
    raiz: str | None = None,
) -> Contribuyente:
    """Un contribuyente sintético coherente: el nombre, el giro y el régimen pegan."""
    giro = giro or rng.choice(cat.GIROS)
    raiz = raiz or rng.choice(_RAICES)
    nombre = f"{raiz} {rng.choice(_FORMAS_JURIDICAS)}"
    return Contribuyente(
        rfc=rfc_persona_moral(rng),
        nombre=nombre,
        regimen_fiscal=rng.choice(cat.REGIMENES_PERSONA_MORAL),
        codigo_postal=rng.choice(cat.CODIGOS_POSTALES),
        giro=giro,
    )


def comprobante(
    rng: random.Random,
    *,
    emisor: Contribuyente,
    receptor: Contribuyente,
    fecha_emision: datetime,
    variante: VarianteXml | None = None,
    uuid: str | None = None,
) -> ComprobanteSintetico:
    conceptos = _conceptos(rng, emisor.giro)
    return ComprobanteSintetico(
        uuid=uuid or _uuid_determinista(rng),
        serie=rng.choice(("A", "B", "F", "FAC")),
        folio=str(rng.randint(100, 99_999)),
        fecha_emision=fecha_emision,
        # El timbrado ocurre minutos después de la emisión, nunca antes.
        fecha_timbrado=fecha_emision + timedelta(seconds=rng.randint(30, 3600)),
        emisor=emisor,
        receptor=receptor,
        uso_cfdi=rng.choice(cat.USOS_CFDI_EMPRESARIALES),
        conceptos=conceptos,
        dias_credito=_plazo(rng),
        variante=variante or rng.choice(tuple(VarianteXml)),
    )


def generar_lote(
    *,
    cantidad: int = 20,
    semilla: int = 20260814,
    con_cesion_duplicada: bool = False,
    fecha_base: datetime | None = None,
) -> Lote:
    """Un lote de CFDI con dispersión creíble (tarea 1.16).

    `con_cesion_duplicada` planta el escenario de fraude que da sentido al
    producto: el mismo UUID aparece dos veces en el mismo lote. En el Sprint 2,
    cuando exista el registro de cesiones, la detección cruzará también lotes
    distintos y días distintos; el plante intra-lote es lo que se puede probar
    hoy sin bitácora.

    Determinista: la misma semilla da el mismo lote. Es lo que hace que la demo
    del video se pueda reproducir desde el repo (tarea 3.10).
    """
    if cantidad < 1:
        raise ValueError("un lote necesita al menos un comprobante")
    if con_cesion_duplicada and cantidad < 2:
        raise ValueError("plantar una cesión duplicada necesita al menos dos comprobantes")

    rng = random.Random(semilla)
    fecha_base = fecha_base or datetime(2026, 8, 14, 9, 0, 0)

    # Nombres sin repetir: si el emisor y un cliente comparten razón social, el
    # lote se lee como una empresa facturándose a sí misma y se cae la ilusión.
    cuantos_clientes = rng.randint(3, 5)
    raices = rng.sample(_RAICES, k=cuantos_clientes + 1)

    pyme = contribuyente(rng, raiz=raices[0])
    # Una PYME real le factura a un puñado de clientes recurrentes, no a 20
    # empresas distintas. Un lote donde cada factura va a un cliente nuevo se ve
    # falso a simple vista.
    clientes = tuple(contribuyente(rng, raiz=raiz) for raiz in raices[1:])
    if any(cliente.rfc == pyme.rfc for cliente in clientes):
        raise RuntimeError("colisión de RFC entre emisor y receptor; cambia la semilla")

    comprobantes: list[ComprobanteSintetico] = []
    for _ in range(cantidad):
        emitido = fecha_base - timedelta(
            days=rng.randint(0, 75),
            hours=rng.randint(0, 9),
            minutes=rng.randint(0, 59),
            seconds=rng.randint(0, 59),
        )
        comprobantes.append(
            comprobante(
                rng,
                emisor=pyme,
                receptor=rng.choice(clientes),
                fecha_emision=emitido,
            )
        )

    uuid_duplicado = None
    if con_cesion_duplicada:
        original = rng.choice(comprobantes[:-1])
        uuid_duplicado = original.uuid
        # Reenviado con otra forma de XML: es lo que pasa cuando la segunda
        # cesión entra por otro canal. Si la detección dependiera de comparar
        # los bytes del archivo en vez del UUID, esto se le escaparía.
        otra = next(v for v in VarianteXml if v is not original.variante)
        comprobantes.append(replace(original, variante=otra))
        rng.shuffle(comprobantes)

    return Lote(
        comprobantes=tuple(comprobantes),
        semilla=semilla,
        uuid_duplicado=uuid_duplicado,
    )


def _conceptos(rng: random.Random, giro: cat.Giro) -> tuple[Concepto, ...]:
    cuantos = rng.choices((1, 2, 3), weights=(0.55, 0.30, 0.15))[0]
    conceptos = []
    for i in range(cuantos):
        # Lognormal: la mayoría de las facturas ronda el monto típico del giro y
        # unas pocas se disparan. Una uniforme se ve sintética de inmediato.
        importe = Decimal(rng.lognormvariate(0, 0.55)) * giro.monto_tipico / cuantos
        cantidad = rng.randint(1, 40) if giro.clave_unidad == "H87" else 1
        unitario = (importe / cantidad).quantize(CENTAVO, rounding=ROUND_HALF_UP)
        unitario = max(unitario, CENTAVO)
        conceptos.append(
            Concepto(
                clave_prod_serv=giro.clave_prod_serv,
                clave_unidad=giro.clave_unidad,
                descripcion=giro.descripcion if cuantos == 1 else f"{giro.descripcion} — partida {i + 1}",
                cantidad=cantidad,
                valor_unitario=unitario,
            )
        )
    return tuple(conceptos)


def _plazo(rng: random.Random) -> int:
    dias, pesos = zip(*_PLAZOS)
    return rng.choices(dias, weights=pesos)[0]


def _uuid_determinista(rng: random.Random) -> str:
    """UUID v4 bien formado, derivado del generador sembrado.

    `uuid.uuid4()` usa entropía del sistema y rompería la reproducibilidad del
    lote, que es justo lo que la demo necesita.
    """
    return str(_uuid.UUID(int=rng.getrandbits(128), version=4)).upper()


# --------------------------------------------------------------------------- #
# Serialización a XML
# --------------------------------------------------------------------------- #


def _serializar(c: ComprobanteSintetico) -> str:
    if c.variante is VarianteXml.PREFIJO_ESTANDAR:
        return _con_prefijo(c, prefijo="cfdi", addenda=False)
    if c.variante is VarianteXml.PREFIJO_ALTERNO:
        return _con_prefijo(c, prefijo="c", addenda=True)
    return _sin_prefijo(c)


def _con_prefijo(c: ComprobanteSintetico, *, prefijo: str, addenda: bool) -> str:
    p = f"{prefijo}:"
    cuerpo = [
        f"<{p}Comprobante {_atributos_raiz(c)} "
        f'xmlns:{prefijo}={quoteattr(NS_CFDI)} xmlns:xsi={quoteattr(NS_XSI)}>',
        f"  <{p}Emisor {_atributos_emisor(c)}/>",
        f"  <{p}Receptor {_atributos_receptor(c)}/>",
        f"  <{p}Conceptos>",
    ]
    for concepto in c.conceptos:
        cuerpo += [
            f"    <{p}Concepto {_atributos_concepto(concepto)}>",
            f"      <{p}Impuestos>",
            f"        <{p}Traslados>",
            f"          <{p}Traslado {_atributos_traslado(concepto)}/>",
            f"        </{p}Traslados>",
            f"      </{p}Impuestos>",
            f"    </{p}Concepto>",
        ]
    cuerpo += [
        f"  </{p}Conceptos>",
        f"  <{p}Impuestos TotalImpuestosTrasladados={quoteattr(_m(c.iva_trasladado))}>",
        f"    <{p}Traslados>",
        f"      <{p}Traslado Base={quoteattr(_m(c.subtotal))} Impuesto={quoteattr(cat.IMPUESTO_IVA)}"
        f' TipoFactor={quoteattr(cat.TIPO_FACTOR_TASA)} TasaOCuota={quoteattr(cat.TASA_IVA)}'
        f' Importe={quoteattr(_m(c.iva_trasladado))}/>',
        f"    </{p}Traslados>",
        f"  </{p}Impuestos>",
        f"  <{p}Complemento>",
        # El timbre declara su propio espacio de nombres aquí y no en la raíz.
        # Es legal y es donde se cae un lector que asuma que todo se declara arriba.
        f"    <tfd:TimbreFiscalDigital xmlns:tfd={quoteattr(NS_TFD)} {_atributos_timbre(c)}/>",
        f"  </{p}Complemento>",
    ]
    if addenda:
        cuerpo += [
            f"  <{p}Addenda>",
            f"    <t:TerminosDePago xmlns:t={quoteattr(NS_ADDENDA)} "
            f"DiasCredito={quoteattr(str(c.dias_credito))} "
            f"Vencimiento={quoteattr(c.fecha_vencimiento.strftime(FORMATO_FECHA_CFDI))}/>",
            f"  </{p}Addenda>",
        ]
    cuerpo.append(f"</{p}Comprobante>")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + "\n".join(cuerpo) + "\n"


def _sin_prefijo(c: ComprobanteSintetico) -> str:
    cuerpo = [
        f"<Comprobante xmlns={quoteattr(NS_CFDI)} xmlns:xsi={quoteattr(NS_XSI)} "
        f"{_atributos_raiz(c)}>",
        f"  <Emisor {_atributos_emisor(c)}/>",
        f"  <Receptor {_atributos_receptor(c)}/>",
        "  <Conceptos>",
    ]
    for concepto in c.conceptos:
        cuerpo += [
            f"    <Concepto {_atributos_concepto(concepto)}>",
            "      <Impuestos>",
            "        <Traslados>",
            f"          <Traslado {_atributos_traslado(concepto)}/>",
            "        </Traslados>",
            "      </Impuestos>",
            "    </Concepto>",
        ]
    cuerpo += [
        "  </Conceptos>",
        f"  <Impuestos TotalImpuestosTrasladados={quoteattr(_m(c.iva_trasladado))}>",
        "    <Traslados>",
        f"      <Traslado Base={quoteattr(_m(c.subtotal))} Impuesto={quoteattr(cat.IMPUESTO_IVA)}"
        f' TipoFactor={quoteattr(cat.TIPO_FACTOR_TASA)} TasaOCuota={quoteattr(cat.TASA_IVA)}'
        f' Importe={quoteattr(_m(c.iva_trasladado))}/>',
        "    </Traslados>",
        "  </Impuestos>",
        "  <Complemento>",
        f"    <tfd:TimbreFiscalDigital xmlns:tfd={quoteattr(NS_TFD)} {_atributos_timbre(c)}/>",
        "  </Complemento>",
        "</Comprobante>",
    ]
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + "\n".join(cuerpo) + "\n"


def _atributos_raiz(c: ComprobanteSintetico) -> str:
    return " ".join(
        f"{clave}={quoteattr(valor)}"
        for clave, valor in (
            ("Version", "4.0"),
            ("Serie", c.serie),
            ("Folio", c.folio),
            ("Fecha", c.fecha_emision.strftime(FORMATO_FECHA_CFDI)),
            ("Sello", _relleno(c.uuid, 344)),
            ("NoCertificado", "30001000000500003416"),
            ("Certificado", _relleno(c.uuid[::-1], 200)),
            # PPD obliga a FormaPago 99: la venta a crédito no sabe todavía cómo
            # se cobrará. Es justamente el comprobante que se factoriza.
            ("FormaPago", cat.FORMA_PAGO_OBLIGATORIA_EN_PPD),
            ("MetodoPago", cat.METODO_PAGO_DIFERIDO),
            ("SubTotal", _m(c.subtotal)),
            ("Moneda", cat.MONEDA_PESOS),
            ("Total", _m(c.total)),
            ("TipoDeComprobante", cat.TIPO_COMPROBANTE_INGRESO),
            ("Exportacion", cat.EXPORTACION_NO_APLICA),
            ("LugarExpedicion", c.emisor.codigo_postal),
        )
    )


def _atributos_emisor(c: ComprobanteSintetico) -> str:
    return (
        f"Rfc={quoteattr(c.emisor.rfc)} Nombre={quoteattr(c.emisor.nombre)} "
        f"RegimenFiscal={quoteattr(c.emisor.regimen_fiscal)}"
    )


def _atributos_receptor(c: ComprobanteSintetico) -> str:
    return (
        f"Rfc={quoteattr(c.receptor.rfc)} Nombre={quoteattr(c.receptor.nombre)} "
        f"DomicilioFiscalReceptor={quoteattr(c.receptor.codigo_postal)} "
        f"RegimenFiscalReceptor={quoteattr(c.receptor.regimen_fiscal)} "
        f"UsoCFDI={quoteattr(c.uso_cfdi)}"
    )


def _atributos_concepto(concepto: Concepto) -> str:
    return " ".join(
        f"{clave}={quoteattr(valor)}"
        for clave, valor in (
            ("ClaveProdServ", concepto.clave_prod_serv),
            ("Cantidad", str(concepto.cantidad)),
            ("ClaveUnidad", concepto.clave_unidad),
            ("Descripcion", concepto.descripcion),
            ("ValorUnitario", _m(concepto.valor_unitario)),
            ("Importe", _m(concepto.importe)),
            ("ObjetoImp", cat.OBJETO_IMPUESTO_SI),
        )
    )


def _atributos_traslado(concepto: Concepto) -> str:
    return (
        f"Base={quoteattr(_m(concepto.importe))} Impuesto={quoteattr(cat.IMPUESTO_IVA)} "
        f"TipoFactor={quoteattr(cat.TIPO_FACTOR_TASA)} TasaOCuota={quoteattr(cat.TASA_IVA)} "
        f"Importe={quoteattr(_m(concepto.iva))}"
    )


def _atributos_timbre(c: ComprobanteSintetico) -> str:
    return " ".join(
        f"{clave}={quoteattr(valor)}"
        for clave, valor in (
            ("Version", "1.1"),
            ("UUID", c.uuid),
            ("FechaTimbrado", c.fecha_timbrado.strftime(FORMATO_FECHA_CFDI)),
            ("RfcProvCertif", "SPR190613I52"),
            ("SelloCFD", _relleno(c.uuid, 344)),
            ("NoCertificadoSAT", "30001000000500003417"),
            ("SelloSAT", _relleno(c.uuid[::-1], 344)),
        )
    )


def _relleno(base: str, largo: int) -> str:
    """Relleno con la forma de un sello base64, **sin validez criptográfica**.

    Está aquí para que el XML tenga la estructura completa de un comprobante
    timbrado. Cualquier verificación de firma sobre esto falla, y debe fallar.
    """
    material = "".join(ch for ch in base if ch.isalnum())
    return (material * (largo // max(len(material), 1) + 1))[:largo]


def _m(valor: Decimal) -> str:
    """Importe con la escala del peso, como lo escribe un PAC."""
    return format(valor.quantize(CENTAVO), "f")
