"""Las mismas respuestas, en HTML, para que una herramienta de lectura las digiera.

## Por qué existen estas rutas

La API contesta en JSON, que es lo correcto para un cliente. Pero un cuaderno de
NotebookLM —o cualquier herramienta que importe una URL como fuente— recibe ese
JSON como un bloque de llaves y comillas sin jerarquía, y a partir de ahí puede
afirmar casi cualquier cosa: no distingue `verificable_por_terceros: false` de un
campo decorativo.

Estas vistas quitan esa fricción. Son las mismas cifras, redactadas en frases
completas, para que lo que la herramienta cite sea una afirmación acotada y no un
campo suelto.

## Por qué son rutas aparte y no negociación de contenido

Se podría mirar el encabezado `Accept` y devolver HTML al navegador. No se hace:
`/auditoria/semaforo` tiene un contrato documentado, hay clientes que ya lo
consumen —el panel de la hoja, el verificador independiente— y cambiar lo que
devuelve según quién pregunte convierte un contrato estable en uno que depende
del cliente. Las vistas viven en `/vista` y no le mueven nada a nadie.

## Por qué no se recalcula nada aquí

Cada vista llama a la **misma función** que sirve el JSON y solo la redacta. Si
estas páginas derivaran sus propios veredictos habría dos voces —una con pruebas
y otra sin ellas— y la segunda acabaría discrepando de la primera justo cuando
importara. Aquí solo hay presentación.

## Por qué no hay bloque `<style>` ni una línea de JavaScript

Porque el lector al que van dirigidas no es un navegador. Un extractor de texto
que quite las etiquetas sin tratar `<style>` aparte se traga el CSS **como si
fuera prosa**, y entonces la fuente que el cuaderno guarda empieza con media
hoja de reglas de tipografía. Todo el formato va en atributos `style=` de cada
etiqueta: es más verboso de escribir y deja el texto extraíble limpio, que es el
único criterio que importa aquí.

Por lo mismo no hay JavaScript: lo que no está en el HTML servido no existe para
quien importa la URL.

## Por qué la fecha del corte va arriba y en grande

Una URL importada como fuente se lee **una vez** y se queda congelada. Lo
peligroso no es que la fotografía envejezca: es que envejezca sin que se note. Un
cuaderno que afirma «la cadena está íntegra» sin decir de cuándo es esa
afirmación es exactamente el fallo que este proyecto existe para no cometer.
"""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape

from fastapi import HTTPException
from fastapi.responses import HTMLResponse

# Estilos en línea. Ver el docstring del módulo: no hay bloque `<style>` a
# propósito, para que el texto extraído de estas páginas sea solo prosa.
_BODY = (
    "font-family:Georgia,'Times New Roman',serif;max-width:46em;margin:2em auto;"
    "padding:0 1em;line-height:1.55;color:#202124"
)
_H1 = "font-size:1.6em;margin-bottom:0.2em"
_H2 = "font-size:1.2em;margin-top:1.8em;border-bottom:1px solid #dadce0;padding-bottom:0.2em"
_CORTE = "background:#f1f3f4;padding:0.8em 1em;border-left:4px solid #5f6368;margin:1em 0 2em"
_TABLA = "border-collapse:collapse;width:100%;font-size:0.9em"
_TH = "border:1px solid #dadce0;padding:0.4em 0.6em;text-align:left;background:#f1f3f4"
_TD = "border:1px solid #dadce0;padding:0.4em 0.6em;text-align:left"
_CODE = "font-family:'Courier New',monospace;font-size:0.85em;word-break:break-all"
_PIE = "margin-top:3em;font-size:0.85em;color:#5f6368;border-top:1px solid #dadce0;padding-top:1em"
_NAV = "margin-bottom:1.5em"

_SEMAFORO = {
    "verde": "#34a853",
    "ambar": "#f9ab00",
    "gris": "#9aa0a6",
    "rojo": "#d93025",
}

NAVEGACION = (
    f'<nav style="{_NAV}">'
    '<a href="/auditoria/vista" style="margin-right:1.5em">Estado</a>'
    '<a href="/auditoria/vista/anclajes">Lo anclado</a></nav>'
)

SALVEDADES = f"""
<h2 style="{_H2}">Lo que este documento no afirma</h2>
<ul>
  <li>La cadena prueba que un registro <strong>no fue alterado después de
      escribirse</strong>. No prueba quién lo escribió: escribir exige un token
      compartido, así que el sistema sabe que alguien autorizado registró una
      cesión, no cuál financiador fue.</li>
  <li>Los CFDI son <strong>sintéticos</strong>. Son estructuralmente válidos ante
      los XSD oficiales del SAT, pero el RFC y el sello son falsos, y los RFC
      llevan <span style="{_CODE}">000000</span> en la porción de fecha: el SAT no
      pudo habérselos asignado nunca, a nadie.</li>
  <li>El anclaje vive en <strong>testnet</strong>. Es una cadena pública real y
      cualquiera la consulta, pero no tiene la permanencia ni el valor económico
      de mainnet, y esa diferencia es una decisión declarada, no un pendiente.</li>
  <li><strong>Ninguna afirmación de integridad pasa por un modelo de
      lenguaje.</strong> El hash, el encadenamiento, la detección de doble cesión
      y la prueba de Merkle son código determinista con pruebas.</li>
</ul>
"""


def _cod(valor) -> str:
    """Un hash o un identificador, escapado y en monoespaciada."""
    return f'<span style="{_CODE}">{escape(str(valor))}</span>'


def _pagina(titulo: str, cuerpo: str) -> HTMLResponse:
    """Envuelve el contenido con el encabezado de corte y las salvedades.

    El bloque de corte y el de salvedades van en **todas** las páginas y no solo
    en la portada. Una herramienta que importa fuentes no garantiza que alguien
    lea la portada antes que el detalle, así que cada página tiene que poder
    defenderse sola.
    """
    corte = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return HTMLResponse(
        "<!doctype html>\n"
        '<html lang="es"><head><meta charset="utf-8">'
        f"<title>{escape(titulo)}</title></head>"
        f'<body style="{_BODY}">'
        f'<h1 style="{_H1}">{escape(titulo)}</h1>'
        f"{NAVEGACION}"
        f'<p style="{_CORTE}"><strong>Este documento es una fotografía del {corte}.'
        "</strong> Las cifras que siguen eran ciertas en ese instante y no se "
        "actualizan solas: si esta página se importó como fuente en un cuaderno, "
        "lo que el cuaderno sabe es lo de esa fecha. Para refrescarlo hay que "
        "volver a importar la URL.</p>"
        f"{cuerpo}"
        f"{SALVEDADES}"
        f'<footer style="{_PIE}">Generado por el motor de auditoría de CØRD a '
        "partir de sus propios endpoints de lectura. Las mismas cifras en JSON "
        "están en /auditoria/semaforo, /auditoria/anclajes y "
        "/auditoria/anclajes/{día}.</footer>"
        "</body></html>"
    )


def _error(titulo: str, mensaje: str, codigo: int) -> HTMLResponse:
    """Un 404 también tiene que salir en HTML.

    Si se dejara escapar la `HTTPException`, FastAPI la convertiría en JSON y la
    herramienta que importa la URL guardaría ese JSON como si fuera el contenido
    de la página.
    """
    respuesta = _pagina(titulo, f"<p><strong>{escape(mensaje)}</strong></p>")
    return HTMLResponse(respuesta.body, status_code=codigo)


def registrar_vistas(app, *, salud, semaforo, verificacion, anclajes, contenido_anclado):
    """Cuelga las vistas de la aplicación, reusando sus funciones de datos.

    Las funciones llegan por parámetro y no por importación para que no haya un
    ciclo entre este módulo y `app`, y para que quede escrito —en la llamada—
    exactamente de qué endpoints derivan estas páginas.
    """
    from fastapi import Depends

    from ..bitacora.almacen import Bitacora
    from .dependencias import bitacora_actual

    @app.get("/vista", response_class=HTMLResponse, include_in_schema=False)
    def vista_estado(bitacora: Bitacora = Depends(bitacora_actual)) -> HTMLResponse:
        s = semaforo(dia=None, bitacora=bitacora)
        v = verificacion(bitacora=bitacora)
        h = salud(bitacora=bitacora)
        color = _SEMAFORO.get(s.color, _SEMAFORO["gris"])

        cuerpo = [
            f'<h2 style="{_H2}">Estado de la bitácora</h2>',
            f'<p style="background:{color};color:#fff;font-weight:bold;'
            f'padding:0.6em 1em;margin:1em 0">{escape(s.titulo)}</p>',
            f"<p>El motor lo explica así: {escape(s.detalle)}.</p>",
            f"<p>La bitácora del inquilino {_cod(h['inquilino'])} tiene una altura "
            f"de <strong>{s.altura} eslabones</strong>, de los cuales "
            f"{s.verificados} se recalcularon y "
            + (
                "todos cuadran entre sí"
                if v["integra"]
                else "<strong>NO cuadran: hay manipulación detectada</strong>"
            )
            + f". La punta de la cadena es {_cod(v['punta'])}.</p>",
        ]

        if s.posicion_del_problema is not None:
            cuerpo.append(
                f"<p><strong>Hay un problema en la posición "
                f"{s.posicion_del_problema} de la cadena.</strong> Ese es el primer "
                f"eslabón cuyo hash no corresponde con lo que la cadena afirma, y "
                f"todo lo posterior a él queda bajo sospecha.</p>"
            )

        cuerpo.append(f'<h2 style="{_H2}">Qué está publicado y qué no</h2>')
        if s.ancla:
            cuerpo.append(
                f"<p>La raíz del día {escape(str(s.dia))} está anclada en la red "
                f"<strong>{escape(s.ancla.red)}</strong>, con la referencia "
                f"{_cod(s.ancla.referencia)}, publicada el "
                f"{escape(str(s.ancla.anclado_en))}. "
                + (
                    "Esa transacción es <strong>verificable por cualquiera</strong> "
                    "sin pedirnos acceso ni credenciales."
                    if s.ancla.verificable_por_terceros
                    else "<strong>Esta ancla es simulada</strong> y el propio "
                    "sistema la declara falsa: no la cuente como evidencia externa."
                )
                + "</p>"
            )
        else:
            cuerpo.append(
                f"<p>El día {escape(str(s.dia))} <strong>todavía no tiene raíz "
                f"publicada</strong>. Hasta que la tenga, lo único demostrado es que "
                f"la bitácora es consistente consigo misma: eso prueba que nosotros "
                f"no la alteramos después de escribirla, y no prueba que un tercero "
                f"pueda comprobarlo sin confiar en nosotros. Son dos afirmaciones "
                f"distintas y solo se sostiene la primera.</p>"
            )

        if s.enlace_al_explorador:
            enlace = escape(s.enlace_al_explorador)
            cuerpo.append(
                f'<p>Comprobable en el explorador público: <a href="{enlace}">'
                f"{enlace}</a></p>"
            )

        indice = anclajes(bitacora=bitacora)
        cuerpo.append(
            f"<p>Este inquilino tiene <strong>{indice.total} "
            + ("raíz publicada" if indice.total == 1 else "raíces publicadas")
            + '</strong>. El detalle está en <a href="/auditoria/vista/anclajes">'
            "lo anclado</a>.</p>"
        )

        return _pagina("Auditoría CØRD — estado de la bitácora", "".join(cuerpo))

    @app.get("/vista/anclajes", response_class=HTMLResponse, include_in_schema=False)
    def vista_anclajes(bitacora: Bitacora = Depends(bitacora_actual)) -> HTMLResponse:
        indice = anclajes(bitacora=bitacora)

        if not indice.total:
            return _pagina(
                "Auditoría CØRD — lo anclado",
                f"<p>El inquilino {_cod(indice.inquilino)} <strong>todavía no ha "
                f"publicado ninguna raíz</strong>. No es un fallo: es que aún no hay "
                f"evidencia comprobable desde fuera.</p>",
            )

        filas = []
        for a in indice.anclajes:
            comprobar = (
                f'<a href="{escape(a.enlace_al_explorador)}">ver la transacción</a>'
                if a.enlace_al_explorador
                else "sin explorador conocido"
            )
            filas.append(
                f'<tr><td style="{_TD}">'
                f'<a href="/auditoria/vista/anclajes/{escape(a.dia)}">'
                f"{escape(a.dia)}</a></td>"
                f'<td style="{_TD}">{_cod(a.raiz)}</td>'
                f'<td style="{_TD}">{a.registros}</td>'
                f'<td style="{_TD}">{escape(a.red)}</td>'
                f'<td style="{_TD}">'
                f"{'sí' if a.verificable_por_terceros else 'no — ancla simulada'}</td>"
                f'<td style="{_TD}">{comprobar}</td></tr>'
            )

        cuerpo = (
            f"<p>El inquilino {_cod(indice.inquilino)} ha publicado "
            f"<strong>{indice.total} "
            + ("raíz" if indice.total == 1 else "raíces")
            + "</strong>. Cada una resume, en un solo hash, todos los registros "
            "escritos ese día; el enlace del día abre la lista de lo que quedó "
            "debajo de ella.</p>"
            f'<table style="{_TABLA}"><tr>'
            f'<th style="{_TH}">Día</th><th style="{_TH}">Raíz de Merkle</th>'
            f'<th style="{_TH}">Registros</th><th style="{_TH}">Red</th>'
            f'<th style="{_TH}">Verificable por terceros</th>'
            f'<th style="{_TH}">Comprobar</th></tr>' + "".join(filas) + "</table>"
        )
        return _pagina("Auditoría CØRD — lo anclado", cuerpo)

    @app.get(
        "/vista/anclajes/{dia}", response_class=HTMLResponse, include_in_schema=False
    )
    def vista_contenido(
        dia: str, bitacora: Bitacora = Depends(bitacora_actual)
    ) -> HTMLResponse:
        try:
            c = contenido_anclado(dia=dia, bitacora=bitacora)
        except HTTPException as falla:
            return _error(
                f"Auditoría CØRD — {dia}", str(falla.detail), falla.status_code
            )

        filas = []
        for h in c.hojas:
            if h.suprimido_por_retencion:
                que = "registro suprimido por retención (el hash sigue contando)"
            elif h.uuid:
                que = (
                    f"CFDI {_cod(h.uuid)} — {escape(str(h.veredicto))}, "
                    f"{escape(str(h.total))} {escape(str(h.moneda))}"
                )
            else:
                que = escape(str(h.evento or "eslabón sin auditoría asociada"))
            filas.append(
                f'<tr><td style="{_TD}">{h.posicion}</td>'
                f'<td style="{_TD}">{_cod(h.hoja)}</td>'
                f'<td style="{_TD}">{que}</td>'
                f'<td style="{_TD}">{escape(h.escrito_en)}</td></tr>'
            )

        cuerpo = [
            f"<p>La raíz del <strong>{escape(c.dia)}</strong> es {_cod(c.raiz)}, "
            f"publicada en la red <strong>{escape(c.red)}</strong> el "
            f"{escape(c.anclado_en)} con la referencia {_cod(c.referencia)}. "
            + (
                "Cualquiera puede comprobar esa transacción sin pedirnos acceso."
                if c.verificable_por_terceros
                else "<strong>El ancla es simulada</strong>: no la cuente como "
                "evidencia externa."
            )
            + "</p>"
        ]

        if c.enlace_al_explorador:
            enlace = escape(c.enlace_al_explorador)
            cuerpo.append(f'<p>Comprobar: <a href="{enlace}">{enlace}</a></p>')

        if c.advertencia:
            cuerpo.append(
                f'<p style="{_CORTE}"><strong>Advertencia.</strong> '
                f"{escape(c.advertencia)}</p>"
            )

        cuerpo.append(
            f'<h2 style="{_H2}">Lo que cuelga de esa raíz</h2>'
            f"<p>Se anclaron <strong>{c.registros} registros</strong> y hoy se leen "
            f"<strong>{len(c.hojas)}</strong>. Cada fila es una hoja del árbol de "
            f"Merkle: con la raíz, el identificador de la transacción y esta lista, "
            f"un tercero reconstruye el árbol y comprueba que su folio estaba "
            f"dentro, sin nuestra palabra de por medio.</p>"
            f'<table style="{_TABLA}"><tr>'
            f'<th style="{_TH}">Posición</th><th style="{_TH}">Hoja</th>'
            f'<th style="{_TH}">Qué es</th><th style="{_TH}">Escrito en</th></tr>'
            + "".join(filas)
            + "</table>"
        )

        return _pagina(f"Auditoría CØRD — raíz del {dia}", "".join(cuerpo))
