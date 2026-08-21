"""Quién puede escribir en la bitácora.

## Por qué no se cierra el servicio entero

El despliegue es público **a propósito**: un jurado tiene que poder abrir la URL
y probar el agente sin pedirle una credencial a nadie. Cerrarlo con IAM rompería
justo eso.

Pero desde que el motor de auditoría se montó (tarea 1.13), esa puerta abierta
ya no da a un chat: da a una base de datos donde cualquiera con la URL podía
ingerir comprobantes, registrar cesiones y disparar el cierre del día.

Así que la línea no se traza en el servicio, se traza en la **operación**:

| Se puede sin credencial | Exige token |
|---|---|
| Consultar salud y semáforo | Ingerir CFDI |
| Verificar la cadena entera | Registrar una cesión |
| Pedir una prueba de inclusión | Anclar / cerrar el día |
| Preguntarle al agente | |

Leer no compromete nada —de hecho, que cualquiera pueda verificar la cadena es
el punto entero del proyecto— y escribir sí.

## El default es negar, pero solo donde importa

Un servicio en Cloud Run **sin token configurado** rechaza toda escritura. Es
deliberado: equivocarse por omisión tiene que dejar el sistema cerrado, no
abierto. Desplegar y olvidar la variable produce un `503` ruidoso, no una
bitácora pública.

En local no se exige nada. Ahí no hay nada que proteger —la bitácora es un
archivo del desarrollador con datos sintéticos— y obligar a un token volvería
insoportable correr las pruebas y la demo.

La diferencia se detecta con `K_SERVICE`, que Cloud Run inyecta en cada
contenedor y que no existe fuera de él.
"""

from __future__ import annotations

import hmac
import os

from fastapi import Header, HTTPException, status

VARIABLE_TOKEN = "AGENTE_CFDI_TOKEN_ESCRITURA"

ESQUEMA = "bearer"


def _token_esperado() -> str:
    return os.environ.get(VARIABLE_TOKEN, "").strip()


def _corre_en_cloud_run() -> bool:
    """`K_SERVICE` lo inyecta Cloud Run y no existe en una máquina local."""
    return bool(os.environ.get("K_SERVICE"))


def exigir_token_de_escritura(
    authorization: str | None = Header(default=None),
) -> None:
    """Deja pasar solo a quien traiga el token de escritura.

    Se usa como dependencia de ruta, no como middleware: así queda escrito en
    cada endpoint si exige credencial o no, y añadir uno nuevo obliga a decidirlo
    en vez de heredarlo por descuido.
    """
    esperado = _token_esperado()

    if not esperado:
        if _corre_en_cloud_run():
            # Fallar aquí es incómodo y es lo correcto: la alternativa es una
            # bitácora abierta a internet porque alguien olvidó una variable.
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                f"este despliegue no tiene {VARIABLE_TOKEN} configurada, así que "
                f"no acepta escrituras. No es un rechazo de tus credenciales: es "
                f"que el servicio no está listo para recibirlas.",
            )
        return

    if not authorization:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "esta operación escribe en la bitácora y exige un token; "
            "mándalo en la cabecera Authorization",
            headers={"WWW-Authenticate": "Bearer"},
        )

    esquema, _, credencial = authorization.partition(" ")
    if esquema.lower() != ESQUEMA or not credencial:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "la cabecera Authorization debe ser 'Bearer <token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # `compare_digest` y no `==`: comparar cadenas con el operador normal termina
    # en cuanto encuentra una diferencia, y ese tiempo distinto deja adivinar el
    # token carácter por carácter. Aquí cuesta lo mismo acertar el primero que
    # todos.
    if not hmac.compare_digest(credencial.strip(), esperado):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "el token no corresponde a este despliegue",
        )
