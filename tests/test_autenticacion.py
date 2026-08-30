"""Quién puede escribir en la bitácora.

Lo que se prueba aquí no es que el token funcione: es que **la línea esté donde
se decidió ponerla**. Un endpoint de lectura que empiece a exigir credencial
rompe la promesa de que cualquiera puede verificar la cadena sin pedirnos nada,
y un endpoint de escritura que se quede sin guardia deja la bitácora abierta a
internet. Las dos direcciones son regresiones y las dos se prueban.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agente_cfdi.api.app import app
from agente_cfdi.api.autenticacion import VARIABLE_TOKEN

TOKEN = "un-token-de-prueba-largo-y-aburrido"

UUID = "9F2C1A88-FB09-47F8-B5F9-6DD1C6889D8C"
CESION = {"uuid": UUID, "financiador": "Banco Norte", "total": "1.00", "moneda": "MXN"}

# Las cuatro que escriben, con un cuerpo que basta para pasar la validación de
# esquema. Lo que importa es el código de la puerta, no el de la lógica.
ESCRITURAS = [
    ("post", "/cesiones", {"json": CESION}),
    ("post", "/bitacora/anclaje", {}),
    ("post", "/cierre-diario", {}),
    ("post", "/ingesta", {"files": [("archivos", ("x.xml", b"<x/>", "application/xml"))]}),
]

LECTURAS = [
    "/salud",
    "/semaforo",
    "/bitacora/verificacion",
    f"/cesiones/{UUID}",
]


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTE_CFDI_BITACORA", str(tmp_path / "bitacora.db"))
    monkeypatch.delenv(VARIABLE_TOKEN, raising=False)
    monkeypatch.delenv("K_SERVICE", raising=False)
    return TestClient(app)


def _llamar(cliente, metodo, ruta, extra, token=None):
    cabeceras = {"Authorization": f"Bearer {token}"} if token else {}
    return getattr(cliente, metodo)(ruta, headers=cabeceras, **extra)


# --------------------------------------------------------------------------- #
# En Cloud Run sin token: cerrado
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("metodo,ruta,extra", ESCRITURAS)
def test_en_cloud_run_sin_token_no_se_escribe(cliente, monkeypatch, metodo, ruta, extra):
    """Desplegar y olvidar la variable deja el sistema **cerrado**, no abierto.

    El 503 es deliberado y no un 401: el problema no son las credenciales de
    quien llama, es que este despliegue no está listo para recibir escrituras.
    Decir «no autorizado» mandaría a buscar un token que no serviría de nada.
    """
    monkeypatch.setenv("K_SERVICE", "agente-cfdi-run")
    assert _llamar(cliente, metodo, ruta, extra).status_code == 503


@pytest.mark.parametrize("ruta", LECTURAS)
def test_las_lecturas_nunca_piden_token(cliente, monkeypatch, ruta):
    """Ni siquiera en Cloud Run sin token configurado.

    Que un tercero pueda verificar la cadena **sin pedirnos permiso** es la tesis
    del proyecto. Si esto se rompe, el anclaje pierde sentido: daría lo mismo
    publicar la raíz si para comprobarla hay que tocarnos la puerta.
    """
    monkeypatch.setenv("K_SERVICE", "agente-cfdi-run")
    assert cliente.get(ruta).status_code == 200


# --------------------------------------------------------------------------- #
# En local: abierto
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("metodo,ruta,extra", ESCRITURAS)
def test_en_local_sin_token_se_escribe(cliente, metodo, ruta, extra):
    """Fuera de Cloud Run no se exige nada.

    Ahí la bitácora es un archivo del desarrollador con datos sintéticos: no hay
    nada que proteger, y exigir un token volvería insoportable correr la demo.
    Lo que se comprueba es que la respuesta **no** sea de la puerta.
    """
    assert _llamar(cliente, metodo, ruta, extra).status_code not in (401, 403, 503)


# --------------------------------------------------------------------------- #
# Con token configurado
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("metodo,ruta,extra", ESCRITURAS)
def test_sin_cabecera_es_401(cliente, monkeypatch, metodo, ruta, extra):
    monkeypatch.setenv(VARIABLE_TOKEN, TOKEN)
    respuesta = _llamar(cliente, metodo, ruta, extra)
    assert respuesta.status_code == 401
    # Sin este encabezado, un cliente HTTP no sabe qué tipo de credencial pedir.
    assert respuesta.headers.get("WWW-Authenticate") == "Bearer"


@pytest.mark.parametrize("metodo,ruta,extra", ESCRITURAS)
def test_token_equivocado_es_403(cliente, monkeypatch, metodo, ruta, extra):
    """403 y no 401: la credencial llegó y se entendió; simplemente no sirve."""
    monkeypatch.setenv(VARIABLE_TOKEN, TOKEN)
    assert _llamar(cliente, metodo, ruta, extra, token="otro").status_code == 403


@pytest.mark.parametrize("metodo,ruta,extra", ESCRITURAS)
def test_token_correcto_pasa(cliente, monkeypatch, metodo, ruta, extra):
    monkeypatch.setenv(VARIABLE_TOKEN, TOKEN)
    respuesta = _llamar(cliente, metodo, ruta, extra, token=TOKEN)
    assert respuesta.status_code not in (401, 403, 503)


def test_el_esquema_tiene_que_ser_bearer(cliente, monkeypatch):
    """Mandar el token con el esquema equivocado no lo hace válido."""
    monkeypatch.setenv(VARIABLE_TOKEN, TOKEN)
    respuesta = cliente.post(
        "/cierre-diario", headers={"Authorization": f"Basic {TOKEN}"}
    )
    assert respuesta.status_code == 401


def test_bearer_se_acepta_sin_importar_mayusculas(cliente, monkeypatch):
    """`Bearer`, `bearer` y `BEARER` son el mismo esquema para HTTP."""
    monkeypatch.setenv(VARIABLE_TOKEN, TOKEN)
    respuesta = cliente.post(
        "/cierre-diario", headers={"Authorization": f"BEARER {TOKEN}"}
    )
    assert respuesta.status_code not in (401, 403)


def test_el_token_no_se_repite_en_la_respuesta(cliente, monkeypatch):
    """Un mensaje de error que devuelva el token esperado lo regala.

    Suena obvio y es exactamente el descuido que se cuela: interpolar el valor
    en el texto para «ayudar a depurar».
    """
    monkeypatch.setenv(VARIABLE_TOKEN, TOKEN)
    respuesta = _llamar(cliente, "post", "/cierre-diario", {}, token="otro")
    assert TOKEN not in respuesta.text


def test_el_token_tolera_espacios_al_final(cliente, monkeypatch):
    """Cloud Scheduler manda la cabecera con un espacio de más, y funciona.

    No es hipotético: verificado el 20-ago-2026 contra el job real, cuya
    cabecera mide 51 caracteres y termina en `'wp_RxM4 '`. El espacio se cuela
    al configurar el job desde PowerShell, porque `gcloud` en Windows escribe
    CRLF y la variable arrastra el sobrante.

    Que funcione fue suerte —el `strip()` estaba puesto por costumbre, no por
    este caso— así que ahora es una propiedad probada. Sin ella, el cierre
    diario devolvería 403 todas las noches y la causa sería invisible: los dos
    tokens se ven idénticos en pantalla.
    """
    monkeypatch.setenv(VARIABLE_TOKEN, TOKEN)
    respuesta = cliente.post(
        "/cierre-diario", headers={"Authorization": f"Bearer {TOKEN} "}
    )
    assert respuesta.status_code not in (401, 403)


def test_el_token_configurado_tambien_tolera_sobrantes(cliente, monkeypatch):
    """El otro lado del mismo problema.

    Guardar el secreto con `$token | gcloud secrets versions add` le agrega un
    salto de línea, así que la variable de entorno que Cloud Run inyecta puede
    traerlo. Si el valor esperado no se limpiara, ningún token del mundo casaría.
    """
    monkeypatch.setenv(VARIABLE_TOKEN, f"{TOKEN}\n")
    respuesta = cliente.post(
        "/cierre-diario", headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert respuesta.status_code not in (401, 403)
