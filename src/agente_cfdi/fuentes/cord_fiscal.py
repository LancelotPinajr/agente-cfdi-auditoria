"""Cliente HTTP de CØRD Fiscal (tarea 1.11).

CØRD Fiscal es una **plataforma preexistente**. Este agente la consume por HTTP,
al mismo nivel que consumiría Postgres o un servicio de terceros: **no importa
su código ni lo copia**. Si esta clase dejara de existir, CØRD Fiscal seguiría
funcionando igual, y viceversa.

Endpoints que usa (existen ya, no se piden cambios):

    GET /fiscal/contabilidad/libros              los libros importados
    GET /fiscal/contabilidad/libros/{id}         el libro con sus renglones

La PYME se identifica **por el token**, no por un parámetro. CØRD Fiscal deriva
el tenant del JWT, así que el agente lleva una credencial por PYME y no puede
pedir los libros de otra ni por descuido. Es un acierto de aislamiento que
conviene no romper agregando un `?tenant_id=`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, DecimalException
from typing import Any, Callable, Mapping, Sequence

from .protocolo import ErrorDeFuente, Movimiento, TipoDeMovimiento

TIEMPO_LIMITE_SEGUNDOS = 20.0
PAGINA = 500
MAXIMO_DE_PAGINAS = 200  # tope duro: 100 000 renglones por libro es ya absurdo

# Respuesta cruda de un endpoint: el transporte devuelve JSON ya decodificado.
Transporte = Callable[[str, Mapping[str, Any]], Any]


@dataclass(frozen=True)
class ClienteCordFiscal:
    """Lee los libros de una PYME desde CØRD Fiscal.

    `transporte` se inyecta para poder probar esto sin levantar la plataforma ni
    tocar la red. Por omisión usa `httpx`.
    """

    base_url: str
    token: str
    transporte: Transporte | None = None
    solo_confirmados: bool = True
    """Un libro sin confirmar es una interpretación que ningún humano validó.

    Auditar contra él haría que el agente afirme al financiador algo que la PYME
    todavía no reconoce como su contabilidad. El valor por omisión es el
    prudente; se puede apagar para depurar, nunca para producir un expediente.
    """

    @property
    def descripcion(self) -> str:
        return f"CØRD Fiscal ({_anfitrion(self.base_url)})"

    def movimientos(
        self, *, desde: date | None = None, hasta: date | None = None
    ) -> tuple[Movimiento, ...]:
        recolectados: list[Movimiento] = []
        for libro in self._libros():
            if self.solo_confirmados and libro.get("estado") != "confirmado":
                continue
            recolectados.extend(self._movimientos_de(str(libro["id"]), desde, hasta))
        return tuple(recolectados)

    # ----------------------------------------------------------------- #

    def _libros(self) -> Sequence[Mapping[str, Any]]:
        cuerpo = self._pedir("/fiscal/contabilidad/libros", {"limite": 200})
        libros = cuerpo.get("libros") if isinstance(cuerpo, Mapping) else None
        if not isinstance(libros, Sequence):
            raise ErrorDeFuente(
                "CØRD Fiscal respondió sin la lista 'libros'; el contrato cambió"
            )
        return [l for l in libros if isinstance(l, Mapping) and l.get("id")]

    def _movimientos_de(
        self, libro_id: str, desde: date | None, hasta: date | None
    ) -> list[Movimiento]:
        salida: list[Movimiento] = []
        offset = 0
        for _ in range(MAXIMO_DE_PAGINAS):
            cuerpo = self._pedir(
                f"/fiscal/contabilidad/libros/{libro_id}",
                {"limite": PAGINA, "offset": offset},
            )
            crudos = cuerpo.get("movimientos") if isinstance(cuerpo, Mapping) else None
            if not crudos:
                return salida
            for crudo in crudos:
                movimiento = _traducir(crudo)
                if movimiento is not None and _en_ventana(movimiento.fecha, desde, hasta):
                    salida.append(movimiento)
            if len(crudos) < PAGINA:
                return salida
            offset += PAGINA
        raise ErrorDeFuente(
            f"el libro {libro_id} superó {MAXIMO_DE_PAGINAS} páginas; se aborta "
            f"en vez de paginar sin fin"
        )

    def _pedir(self, ruta: str, parametros: Mapping[str, Any]) -> Any:
        transporte = self.transporte or self._transporte_httpx
        try:
            return transporte(ruta, parametros)
        except ErrorDeFuente:
            raise
        except Exception as exc:  # noqa: BLE001 - la causa se conserva
            # El mensaje no repite el token ni los parámetros: esto acaba en un
            # log que alguien más lee.
            raise ErrorDeFuente(
                f"no se pudo leer {ruta} de CØRD Fiscal: {type(exc).__name__}"
            ) from exc

    def _transporte_httpx(self, ruta: str, parametros: Mapping[str, Any]) -> Any:
        import httpx  # importado aquí para que las pruebas no exijan la red

        respuesta = httpx.get(
            f"{self.base_url.rstrip('/')}{ruta}",
            params=dict(parametros),
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
            },
            timeout=TIEMPO_LIMITE_SEGUNDOS,
        )
        if respuesta.status_code in (401, 403):
            raise ErrorDeFuente(
                f"CØRD Fiscal rechazó la credencial ({respuesta.status_code}); "
                f"el token del agente para esta PYME está vencido o no alcanza"
            )
        if respuesta.status_code == 404:
            raise ErrorDeFuente(f"CØRD Fiscal no conoce {ruta}")
        respuesta.raise_for_status()
        return respuesta.json()


# --------------------------------------------------------------------------- #
# Traducción: de la forma de CØRD Fiscal a la del dominio
# --------------------------------------------------------------------------- #


def _traducir(crudo: Any) -> Movimiento | None:
    """Convierte un renglón de CØRD Fiscal en un `Movimiento` minimizado.

    Devuelve `None` —en vez de reventar— cuando el renglón no trae lo mínimo.
    La contabilidad importada de un Excel tiene renglones basura por definición,
    y un renglón ilegible no puede tumbar la auditoría del resto.

    Aquí es donde ocurre la minimización: `datos_originales` (el renglón crudo
    del Excel de la PYME), `categoria`, `problemas` y `proyecto` **no se copian**.
    El agente no los necesita para cotejar un CFDI, así que no los guarda.
    """
    if not isinstance(crudo, Mapping):
        return None
    identificador = crudo.get("id")
    monto = _decimal(crudo.get("monto"))
    if identificador is None or monto is None:
        return None

    return Movimiento(
        identificador=str(identificador),
        fecha=_fecha(crudo.get("fecha")),
        concepto=str(crudo.get("concepto") or "").strip(),
        tipo=_tipo(crudo.get("tipo")),
        monto=monto,
        rfc_contraparte=_rfc(crudo.get("rfc_contraparte")),
        referencia=_opcional(crudo.get("referencia")),
        tiene_comprobante=bool(crudo.get("tiene_comprobante")),
    )


def _tipo(crudo: Any) -> TipoDeMovimiento:
    try:
        return TipoDeMovimiento(str(crudo).strip().lower())
    except ValueError:
        # Un tipo desconocido no es un ingreso. Adivinar aquí inventaría cobros.
        return TipoDeMovimiento.SIN_CLASIFICAR


def _decimal(crudo: Any) -> Decimal | None:
    if crudo is None or isinstance(crudo, bool):
        return None
    if isinstance(crudo, float):
        # El JSON de un importe llega como número y float miente con los
        # centavos. Se pasa por str para no arrastrar el error de binario.
        crudo = repr(crudo)
    try:
        valor = Decimal(str(crudo).strip())
    except (DecimalException, ValueError):
        return None
    return valor if valor.is_finite() else None


def _fecha(crudo: Any) -> date | None:
    if isinstance(crudo, date) and not isinstance(crudo, datetime):
        return crudo
    if isinstance(crudo, datetime):
        return crudo.date()
    if not crudo:
        return None
    texto = str(crudo).strip()
    for formato in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(texto[:26], formato).date()
        except ValueError:
            continue
    # Un movimiento sin fecha legible existe y es válido: la contabilidad de una
    # PYME los tiene. Se conserva sin fecha en vez de descartarlo.
    return None


def _rfc(crudo: Any) -> str | None:
    if not crudo:
        return None
    return str(crudo).strip().upper() or None


def _opcional(crudo: Any) -> str | None:
    if crudo is None:
        return None
    return str(crudo).strip() or None


def _en_ventana(fecha: date | None, desde: date | None, hasta: date | None) -> bool:
    if fecha is None:
        # Sin fecha no se puede afirmar que cayó dentro del periodo. Entra solo
        # cuando no se pidió periodo — el mismo criterio que usa CØRD Fiscal.
        return desde is None and hasta is None
    if desde and fecha < desde:
        return False
    return not (hasta and fecha > hasta)


def _anfitrion(base_url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(base_url).netloc or base_url
