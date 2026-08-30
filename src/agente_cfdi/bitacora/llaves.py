"""De dónde sale la llave privada del anclaje (tarea 2.10).

## El criterio es «rotarla no exige redesplegar»

Eso descarta la ruta cómoda. Cloud Run sabe inyectar un secreto como variable de
entorno con `--set-secrets`, pero resuelve la versión **al arrancar la
instancia**: con `--min-instances=1` esa instancia vive días, así que rotar el
secreto no cambiaría nada hasta el siguiente despliegue. Justo lo que la tarea
prohíbe.

Por eso se pide `versions/latest` a Secret Manager **en cada anclaje**. Es una
petición al día: el costo es irrelevante y la propiedad se cumple de verdad.

## Por qué REST y no el cliente oficial

`google-cloud-secret-manager` arrastra gRPC y protobuf —un stack nativo
completo— para lo que aquí es un `GET` con un token. La librería se gana su
peso cuando te ahorra complejidad real; para un endpoint, no. Es el criterio
opuesto al del anclaje, donde sí se usa `web3` porque firmar transacciones tiene
nonces, gas y EIP-1559 de por medio.

La identidad sale del **metadata server**, así que en Cloud Run no hay
credencial que configurar ni archivo de llave que custodiar.
"""

from __future__ import annotations

import base64
import os

import httpx

METADATA = "http://metadata.google.internal/computeMetadata/v1"
SECRET_MANAGER = "https://secretmanager.googleapis.com/v1"

TIEMPO_LIMITE = 10.0


class ErrorDeLlave(RuntimeError):
    """No se pudo obtener la llave. Nunca lleva el valor en el mensaje."""


def _token_de_la_instancia(cliente: httpx.Client) -> str:
    respuesta = cliente.get(
        f"{METADATA}/instance/service-accounts/default/token",
        headers={"Metadata-Flavor": "Google"},
        timeout=TIEMPO_LIMITE,
    )
    respuesta.raise_for_status()
    return respuesta.json()["access_token"]


def llave_de_secret_manager(
    proyecto: str, secreto: str, *, version: str = "latest"
) -> str:
    """Lee la llave privada de Secret Manager, ahora mismo.

    `version="latest"` es deliberado: es lo que hace que rotar el secreto surta
    efecto sin tocar el despliegue.
    """
    try:
        with httpx.Client() as cliente:
            token = _token_de_la_instancia(cliente)
            respuesta = cliente.get(
                f"{SECRET_MANAGER}/projects/{proyecto}/secrets/{secreto}"
                f"/versions/{version}:access",
                headers={"Authorization": f"Bearer {token}"},
                timeout=TIEMPO_LIMITE,
            )
            respuesta.raise_for_status()
            crudo = respuesta.json()["payload"]["data"]
    except httpx.HTTPError as falla:
        # El mensaje nombra el secreto, jamás su contenido: esto termina en los
        # logs de Cloud Run, que mucha gente puede leer.
        raise ErrorDeLlave(
            f"no se pudo leer el secreto {secreto!r} del proyecto {proyecto!r}: {falla}"
        ) from falla
    except (KeyError, ValueError) as falla:
        raise ErrorDeLlave(
            f"el secreto {secreto!r} no tiene el formato esperado de Secret Manager"
        ) from falla

    llave = base64.b64decode(crudo).decode("ascii").strip()
    if not llave:
        raise ErrorDeLlave(
            f"el secreto {secreto!r} está vacío; "
            f"¿se creó el secreto pero nunca se le agregó una versión?"
        )
    return llave


def proveedor_desde_entorno():
    """Devuelve el proveedor de llave que corresponda a la configuración.

    Prioridad, de mayor a menor:

    1. `AGENTE_CFDI_LLAVE_SECRETO` — se lee de Secret Manager en cada anclaje.
       Es la ruta de producción y la única que cumple la tarea 2.10.
    2. `AGENTE_CFDI_LLAVE` — la llave en texto plano en el entorno. **Solo para
       desarrollo contra testnet**, donde perderla cuesta gas de mentira.

    Si no hay ninguna, no se devuelve un proveedor a medias: quien pida anclar
    tiene que enterarse de que no hay con qué firmar.
    """
    secreto = os.environ.get("AGENTE_CFDI_LLAVE_SECRETO")
    if secreto:
        proyecto = os.environ.get("GOOGLE_CLOUD_PROJECT")
        if not proyecto:
            raise ErrorDeLlave(
                "AGENTE_CFDI_LLAVE_SECRETO está fijado pero GOOGLE_CLOUD_PROJECT no; "
                "sin proyecto no hay dónde buscar el secreto"
            )
        return lambda: llave_de_secret_manager(proyecto, secreto)

    plana = os.environ.get("AGENTE_CFDI_LLAVE")
    if plana:
        return lambda: plana.strip()

    raise ErrorDeLlave(
        "no hay llave configurada: fija AGENTE_CFDI_LLAVE_SECRETO (producción) "
        "o AGENTE_CFDI_LLAVE (desarrollo contra testnet)"
    )
