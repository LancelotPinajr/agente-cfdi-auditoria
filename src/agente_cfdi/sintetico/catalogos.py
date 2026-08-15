"""Subconjuntos de los catálogos del SAT usados por el generador (tarea 1.14).

Son **valores reales** de los catálogos publicados por el SAT para CFDI 4.0, no
inventados. La razón está en el criterio de aceptación: si el lector se afina
contra XML falsos con valores falsos, se rompe el día que le llegue uno real.

Fuente: catálogos del Anexo 20 de la RMF, versión CFDI 4.0
(`c_UsoCFDI`, `c_FormaPago`, `c_MetodoPago`, `c_RegimenFiscal`, `c_Moneda`,
`c_TipoDeComprobante`, `c_Exportacion`, `c_ObjetoImp`, `c_ClaveProdServ`,
`c_ClaveUnidad`). Se incluye solo lo que el escenario de factoraje necesita.
"""

from __future__ import annotations

from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# c_RegimenFiscal
# --------------------------------------------------------------------------- #

REGIMEN_GENERAL_PERSONAS_MORALES = "601"
REGIMEN_ACTIVIDADES_EMPRESARIALES = "612"
REGIMEN_SIMPLIFICADO_DE_CONFIANZA = "626"
REGIMEN_SIN_OBLIGACIONES = "616"

REGIMENES_PERSONA_MORAL = (
    REGIMEN_GENERAL_PERSONAS_MORALES,
    REGIMEN_SIMPLIFICADO_DE_CONFIANZA,
)

# --------------------------------------------------------------------------- #
# c_UsoCFDI — el receptor declara para qué usará el comprobante
# --------------------------------------------------------------------------- #

USOS_CFDI_EMPRESARIALES = (
    "G01",  # Adquisición de mercancías
    "G03",  # Gastos en general
    "I04",  # Equipo de cómputo y accesorios
    "I08",  # Otra maquinaria y equipo
)

# --------------------------------------------------------------------------- #
# c_FormaPago / c_MetodoPago
# --------------------------------------------------------------------------- #

FORMA_PAGO_TRANSFERENCIA = "03"
FORMA_PAGO_POR_DEFINIR = "99"

METODO_PAGO_UNA_EXHIBICION = "PUE"
METODO_PAGO_DIFERIDO = "PPD"

# Regla del SAT que un jurado con oficio fiscal sí revisa: un comprobante PPD
# —pago en parcialidades o diferido, que es exactamente la venta a crédito que
# se factoriza— debe llevar FormaPago "99 Por definir", porque al timbrar
# todavía no se sabe cómo se pagará. Emitir PPD con forma de pago concreta es
# un error de emisión, no una variante.
FORMA_PAGO_OBLIGATORIA_EN_PPD = FORMA_PAGO_POR_DEFINIR

# --------------------------------------------------------------------------- #
# Otros catálogos
# --------------------------------------------------------------------------- #

MONEDA_PESOS = "MXN"
TIPO_COMPROBANTE_INGRESO = "I"
EXPORTACION_NO_APLICA = "01"
OBJETO_IMPUESTO_SI = "02"  # Sí objeto de impuesto

IMPUESTO_IVA = "002"
TASA_IVA = "0.160000"
TIPO_FACTOR_TASA = "Tasa"


@dataclass(frozen=True)
class Giro:
    """Un giro de negocio, con los códigos de catálogo que le corresponden.

    Agrupar así evita el error más visible de un generador ingenuo: una
    constructora facturando "servicios de consultoría" por unidad de pieza.
    """

    nombre: str
    clave_prod_serv: str  # c_ClaveProdServ
    clave_unidad: str  # c_ClaveUnidad
    descripcion: str
    monto_tipico: int  # centro de la distribución de importes, en pesos


GIROS = (
    Giro(
        nombre="Manufactura metalmecánica",
        clave_prod_serv="31162800",
        clave_unidad="H87",  # Pieza
        descripcion="Piezas metálicas maquinadas a especificación",
        monto_tipico=180_000,
    ),
    Giro(
        nombre="Logística y transporte de carga",
        clave_prod_serv="78101800",
        clave_unidad="E48",  # Unidad de servicio
        descripcion="Servicio de transporte de carga terrestre",
        monto_tipico=95_000,
    ),
    Giro(
        nombre="Desarrollo de software",
        clave_prod_serv="81111500",
        clave_unidad="E48",
        descripcion="Servicios de desarrollo de software a la medida",
        monto_tipico=220_000,
    ),
    Giro(
        nombre="Distribución de abarrotes",
        clave_prod_serv="50000000",
        clave_unidad="H87",
        descripcion="Abarrotes y productos de consumo",
        monto_tipico=64_000,
    ),
    Giro(
        nombre="Servicios de construcción",
        clave_prod_serv="72141100",
        clave_unidad="ACT",  # Actividad
        descripcion="Obra civil por avance de estimación",
        monto_tipico=410_000,
    ),
)

# Códigos postales reales de zonas industriales y de oficinas. `LugarExpedicion`
# y `DomicilioFiscalReceptor` deben existir en c_CodigoPostal.
CODIGOS_POSTALES = (
    "64000",  # Monterrey, NL
    "44100",  # Guadalajara, Jal
    "03100",  # Benito Juárez, CDMX
    "76120",  # Querétaro, Qro
    "72160",  # Puebla, Pue
    "20000",  # Aguascalientes, Ags
)
