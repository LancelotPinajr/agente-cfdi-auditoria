"""Ancla contra una cadena EVM real (tareas 2.7 y 3.6).

Esto es lo que convierte «confía en nuestra bitácora» en «no me confíes,
verifica»: publica la raíz del día en una cadena pública donde no mandamos.

## La llave nunca vive en este objeto

El constructor recibe un **proveedor** de llave, no una llave. Así el sistema la
pide en el momento de anclar y quien la sirve puede ir a Secret Manager cada
vez; rotarla no exige redesplegar, que es lo que pide la tarea 2.10. Una llave
guardada como atributo viviría en memoria desde que arranca la instancia hasta
que la reciclen, que en Cloud Run pueden ser días.

## Por qué se consulta antes de escribir

El contrato prohíbe reanclar un día. Mandar la transacción a ciegas gastaría gas
para recibir un revert sin explicación, así que primero se pregunta qué hay
publicado y se distingue el caso inocuo —misma raíz, reintento— del que es una
alarma: una raíz distinta para el mismo día significa que la bitácora local
cambió después de anclar, o que alguien más tiene la llave.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from eth_account import Account
from web3 import Web3
from web3.exceptions import Web3Exception

from .anclaje import Constancia, ErrorDeAnclaje

RAIZ_VACIA = bytes(32)


@dataclass(frozen=True)
class Red:
    """Una cadena EVM y cómo llegarle."""

    chain_id: int
    rpc: str


REDES = {
    # Los nombres coinciden con las llaves de `EXPLORADORES` en `anclaje.py`:
    # si divergen, la raíz se publica pero nadie encuentra dónde verla, que es
    # justo el punto del anclaje.
    "base-sepolia": Red(chain_id=84532, rpc="https://sepolia.base.org"),
    "base": Red(chain_id=8453, rpc="https://mainnet.base.org"),
    "polygon-amoy": Red(chain_id=80002, rpc="https://rpc-amoy.polygon.technology"),
    "polygon": Red(chain_id=137, rpc="https://polygon-rpc.com"),
}

ABI = [
    {
        "type": "function",
        "name": "anclar",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "raiz", "type": "bytes32"},
            {"name": "dia", "type": "string"},
        ],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "consultar",
        "stateMutability": "view",
        "inputs": [{"name": "dia", "type": "string"}],
        "outputs": [
            {"name": "raiz", "type": "bytes32"},
            {"name": "momento", "type": "uint256"},
        ],
    },
    {
        "type": "function",
        "name": "dueno",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "address"}],
    },
]
"""Solo lo que este sistema usa.

El ABI completo del contrato incluye los `mapping` públicos y el evento; aquí
van las tres funciones que se llaman de verdad. Un ABI recortado no puede
invocar por accidente algo que no se pretendía.
"""


@dataclass
class AnclaEVM:
    """Publica la raíz del día en un contrato de una cadena EVM.

    Cumple el protocolo `Ancla`, así que sustituir `AnclaSimulada` por esta es
    cambiar qué devuelve `ancla_actual()`; nada más del sistema se entera.
    """

    nombre_de_red: str
    contrato: str
    llave: Callable[[], str]
    """Devuelve la llave privada en hex. Se invoca **en cada anclaje**, no una
    vez al construir: es lo que permite rotarla sin redesplegar."""

    rpc: str | None = None
    """Sobrescribe el RPC público. Los públicos limitan por IP; para un anclaje
    al día alcanzan, pero en producción conviene uno propio."""

    espera_del_recibo: int = 180

    def __post_init__(self) -> None:
        if self.nombre_de_red not in REDES:
            raise ValueError(
                f"red desconocida: {self.nombre_de_red!r}; "
                f"las conocidas son {sorted(REDES)}"
            )
        self.contrato = Web3.to_checksum_address(self.contrato)

    @property
    def red(self) -> str:
        return self.nombre_de_red

    @property
    def _config(self) -> Red:
        return REDES[self.nombre_de_red]

    def _conectar(self) -> Web3:
        url = self.rpc or self._config.rpc
        return Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 30}))

    def _instancia(self, w3: Web3):
        return w3.eth.contract(address=self.contrato, abi=ABI)

    # --- Lectura ----------------------------------------------------------- #

    def raiz_publicada(self, dia: str) -> bytes | None:
        """Qué raíz tiene la cadena para ese día, o `None` si ninguna."""
        try:
            raiz, _ = self._instancia(self._conectar()).functions.consultar(dia).call()
        except Web3Exception as falla:
            raise ErrorDeAnclaje(
                f"no se pudo consultar {self.red}: {falla}"
            ) from falla
        return None if raiz == RAIZ_VACIA else bytes(raiz)

    # --- Escritura --------------------------------------------------------- #

    def anclar(self, raiz: bytes, *, dia: str) -> Constancia:
        if len(raiz) != 32:
            raise ErrorDeAnclaje(f"la raíz mide {len(raiz)} bytes; se esperaban 32")

        previa = self.raiz_publicada(dia)
        if previa is not None:
            if previa == raiz:
                raise ErrorDeAnclaje(
                    f"{dia} ya está anclado en {self.red} con esta misma raíz, "
                    f"pero este sistema no guardó el hash de esa transacción. La "
                    f"publicación existe y es correcta: hay que reconciliar la "
                    f"constancia a mano, no volver a anclar."
                )
            raise ErrorDeAnclaje(
                f"{dia} ya está anclado en {self.red} con una raíz DISTINTA "
                f"({previa.hex()} contra {raiz.hex()}). Esto no se arregla "
                f"reintentando: o la bitácora local cambió después de anclar, o "
                f"alguien más publicó con esta llave."
            )

        w3 = self._conectar()
        cuenta = Account.from_key(self.llave())

        try:
            transaccion = self._instancia(w3).functions.anclar(
                raiz, dia
            ).build_transaction(
                {
                    "from": cuenta.address,
                    "nonce": w3.eth.get_transaction_count(cuenta.address, "pending"),
                    "chainId": self._config.chain_id,
                }
            )
            firmada = cuenta.sign_transaction(transaccion)
            hash_tx = w3.eth.send_raw_transaction(firmada.raw_transaction)
        except Web3Exception as falla:
            raise ErrorDeAnclaje(
                f"no se pudo publicar la raíz de {dia} en {self.red}: {falla}"
            ) from falla

        referencia = hash_tx.hex()
        if not referencia.startswith("0x"):
            referencia = "0x" + referencia

        try:
            recibo = w3.eth.wait_for_transaction_receipt(
                hash_tx, timeout=self.espera_del_recibo
            )
        except Exception as falla:
            # Que expire la espera **no** significa que no se publicó: la
            # transacción ya está difundida y puede minarse después. Decirlo
            # importa, porque reintentar a ciegas gastaría gas por una raíz que
            # quizá ya quedó, y el contrato revertiría el segundo intento.
            raise ErrorDeAnclaje(
                f"la transacción {referencia} no confirmó en "
                f"{self.espera_del_recibo} s. Sigue difundida y puede minarse "
                f"después: compruébala en el explorador antes de volver a "
                f"anclar este día."
            ) from falla

        if recibo["status"] != 1:
            raise ErrorDeAnclaje(
                f"la transacción {referencia} se minó pero revirtió; la raíz de "
                f"{dia} NO quedó publicada"
            )

        bloque = w3.eth.get_block(recibo["blockNumber"])
        return Constancia(
            red=self.red,
            referencia=referencia,
            anclado_en=datetime.fromtimestamp(
                bloque["timestamp"], tz=timezone.utc
            ).replace(microsecond=0),
        )
