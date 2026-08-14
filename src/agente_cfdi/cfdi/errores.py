"""Errores de lectura de CFDI (tarea 1.9).

El criterio pide «error descriptivo, no excepción». Aquí eso significa dos cosas:

1. Nada de lo que salga del lector es una `ParseError`, un `AttributeError` ni un
   `None` que reviente tres capas más arriba. Todo fallo es un `CFDIInvalido` con
   un motivo tipificado y un mensaje que dice qué pasó y dónde.
2. El motivo es un valor, no una cadena. El agente decide qué hacer con un lote
   que trae un archivo corrupto; para eso necesita distinguir «no es un CFDI» de
   «es un CFDI 3.3» de «le falta el timbre», y no puede hacerlo leyendo prosa.
"""

from __future__ import annotations

from enum import Enum


class Motivo(Enum):
    """Por qué se rechazó un documento. El valor es estable: se registra."""

    DOCUMENTO_PELIGROSO = "documento_peligroso"
    """Trae una construcción que se usa para atacar al que parsea."""

    DEMASIADO_GRANDE = "demasiado_grande"
    XML_MAL_FORMADO = "xml_mal_formado"
    NO_ES_CFDI = "no_es_cfdi"
    VERSION_NO_SOPORTADA = "version_no_soportada"
    SIN_TIMBRE = "sin_timbre"
    UUID_AUSENTE = "uuid_ausente"
    UUID_MAL_FORMADO = "uuid_mal_formado"
    EMISOR_AUSENTE = "emisor_ausente"
    RECEPTOR_AUSENTE = "receptor_ausente"
    RFC_MAL_FORMADO = "rfc_mal_formado"
    TOTAL_AUSENTE = "total_ausente"
    TOTAL_INVALIDO = "total_invalido"
    FECHA_AUSENTE = "fecha_ausente"
    FECHA_INVALIDA = "fecha_invalida"
    MONEDA_AUSENTE = "moneda_ausente"
    MONEDA_NO_SOPORTADA = "moneda_no_soportada"


class CFDIInvalido(ValueError):
    """Un documento que no se puede leer como CFDI.

    Lleva el motivo tipificado y, cuando se conoce, el UUID — un lote de 200
    comprobantes con uno malo necesita decir *cuál*.
    """

    def __init__(self, motivo: Motivo, detalle: str, *, uuid: str | None = None) -> None:
        self.motivo = motivo
        self.detalle = detalle
        self.uuid = uuid
        ubicacion = f" (UUID {uuid})" if uuid else ""
        super().__init__(f"[{motivo.value}] {detalle}{ubicacion}")
