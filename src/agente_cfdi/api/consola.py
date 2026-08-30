"""Una consola en el navegador para las operaciones de escritura.

## Por qué no vive en `/vista`

Las vistas de `vistas.py` existen para que una herramienta que importa una URL
—NotebookLM y parecidas— lea prosa limpia: sin JavaScript, sin bloque `<style>`,
sin nada que un extractor de texto pueda confundir con contenido. Un formulario
de subida rompe las tres cosas: necesita JavaScript para mandar el token en el
encabezado `Authorization`, y sus etiquetas («Examinar…», «Token de escritura»)
acabarían dentro de la fuente que el cuaderno guarda como si fueran parte del
informe.

Son dos lectores distintos con necesidades opuestas. `/vista` es para máquinas
que leen; `/consola` es para una persona con un navegador.

## Por qué el token va en un campo y no en el servidor

La consola **no guarda el token en ninguna parte**. Se teclea en el campo, vive
en la memoria de esa pestaña y se manda en el encabezado `Authorization` de cada
petición, igual que haría `curl`. No se escribe en `localStorage`, no se manda en
la URL y no se persiste del lado del servidor.

Que la página sea pública no la vuelve una puerta abierta: sin token, cada
operación de escritura rechaza igual que siempre. La consola no es una excepción
al modelo de autenticación —es un cliente más— y por eso no toca
`autenticacion.py`.

**El token nunca va en la barra de direcciones.** Un token en un query string
queda en el historial del navegador, en los logs del servidor y en el
`Referer` de cualquier enlace que se pulse después.

## Por qué una sola página y no una por endpoint

Porque el trabajo real es una secuencia —ingerir, ceder, cerrar el día,
comprobar— y repartirla en cinco páginas obligaría a teclear el token cinco
veces. La página está dividida en secciones que siguen ese orden.
"""

from __future__ import annotations

from fastapi.responses import HTMLResponse

_ESTILO = """
  :root { color-scheme: light }
  body { font-family: system-ui, -apple-system, 'Segoe UI', sans-serif;
         max-width: 52em; margin: 2em auto; padding: 0 1em; line-height: 1.5;
         color: #202124 }
  h1 { font-size: 1.5em } h2 { font-size: 1.1em; margin-top: 2em }
  section { border: 1px solid #dadce0; border-radius: 8px; padding: 1em 1.2em;
            margin-bottom: 1.2em }
  label { display: block; margin: 0.6em 0 0.2em; font-weight: 600;
          font-size: 0.9em }
  input, select { width: 100%; padding: 0.5em; border: 1px solid #dadce0;
                  border-radius: 4px; font-size: 1em; box-sizing: border-box }
  button { background: #1a73e8; color: #fff; border: 0; border-radius: 4px;
           padding: 0.6em 1.2em; font-size: 1em; cursor: pointer;
           margin-top: 0.8em }
  button:hover { background: #1557b0 }
  button.secundario { background: #5f6368 }
  pre { background: #f1f3f4; padding: 0.8em; border-radius: 4px;
        overflow-x: auto; font-size: 0.85em; white-space: pre-wrap;
        word-break: break-word }
  .aviso { background: #fef7e0; border-left: 4px solid #f9ab00;
           padding: 0.8em 1em; margin: 1em 0 }
  .fila { display: flex; gap: 1em } .fila > div { flex: 1 }
  a { color: #1a73e8 }
"""

# El guion de la página. Va aquí y no en un archivo aparte porque el servicio se
# despliega desde un Dockerfile sin capa de estáticos: un archivo suelto exigiría
# montar `StaticFiles` y una carpeta más en la imagen, para un solo guion.
_GUION = """
// La raíz del motor se deriva de la URL de esta misma página, que se sirve en
// `<raíz>/consola`. En producción el motor va montado en `/auditoria`, pero en
// local corre solo: dejar el prefijo a fuego rompía uno de los dos casos, y el
// que se rompía en silencio era el de desarrollo.
const BASE = location.pathname.replace(new RegExp('/consola/?$'), '');
const $ = (id) => document.getElementById(id);

function token() {
  const t = $('token').value.trim();
  if (!t) { throw new Error('Falta el token de escritura.'); }
  return t;
}

function pinta(destino, estado, cuerpo) {
  const ok = estado >= 200 && estado < 300;
  $(destino).textContent =
    (ok ? '✅ ' : '❌ ') + estado + '\\n\\n' +
    (typeof cuerpo === 'string' ? cuerpo : JSON.stringify(cuerpo, null, 2));
}

async function pide(ruta, opciones, destino) {
  $(destino).textContent = 'Enviando…';
  try {
    const r = await fetch(ruta, opciones);
    const texto = await r.text();
    let cuerpo;
    try { cuerpo = JSON.parse(texto); } catch (e) { cuerpo = texto; }
    pinta(destino, r.status, cuerpo);
    return r.ok;
  } catch (e) {
    // Un fallo de red no trae código: se distingue de un rechazo del servidor.
    $(destino).textContent = '❌ No se pudo contactar al servicio: ' + e.message;
    return false;
  }
}

// El agente vive en el `main.py` que monta este motor, no en el motor. Por eso
// la ruta es absoluta y no cuelga de BASE: `/api/chat` está en la raíz del
// servicio, un nivel por encima de `/auditoria`.
//
// Corriendo el motor solo (desarrollo) ese endpoint no existe, y se dice con
// todas sus letras en vez de dejar un 404 críptico en pantalla.
let sesion = null;

async function preguntar(texto) {
  const mensaje = (texto || $('pregunta').value).trim();
  if (!mensaje) { $('r_agente').textContent = 'Escribe una pregunta.'; return; }
  $('pregunta').value = mensaje;
  $('r_agente').textContent = 'El agente está consultando sus herramientas…';
  try {
    const r = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      // `session_id` se conserva para que la conversación tenga hilo: sin él
      // cada pregunta empieza de cero y no se puede repreguntar.
      body: JSON.stringify({ message: mensaje, session_id: sesion })
    });
    if (r.status === 404) {
      $('r_agente').textContent =
        'Este proceso no trae al agente: estás corriendo solo el motor de ' +
        'auditoría. El agente vive en main.py — levanta `uvicorn main:app`.';
      return;
    }
    const cuerpo = await r.json();
    // Se reusa `pinta` en vez de formatear aparte: un segundo formateador
    // acabaria divergiendo del primero.
    if (!r.ok) { pinta('r_agente', r.status, cuerpo); return; }
    sesion = cuerpo.session_id;
    $('r_agente').textContent = cuerpo.reply;
    $('modelo').textContent = 'Respondió ' + cuerpo.model;
  } catch (e) {
    $('r_agente').textContent = '❌ No se pudo contactar al agente: ' + e.message;
  }
}

async function ingerir() {
  const archivos = $('archivos').files;
  if (!archivos.length) { $('r_ingesta').textContent = 'Elige al menos un XML.'; return; }
  if (archivos.length > 500) {
    $('r_ingesta').textContent = 'El máximo por lote es 500 archivos; elegiste ' +
      archivos.length + '. Pártelo en varios envíos.';
    return;
  }
  const cuerpo = new FormData();
  // El campo se llama `archivos` y se repite: así lo espera
  // `list[UploadFile]` en /ingesta.
  for (const a of archivos) { cuerpo.append('archivos', a, a.name); }
  try {
    await pide(BASE + '/ingesta',
      { method: 'POST', headers: { 'Authorization': 'Bearer ' + token() }, body: cuerpo },
      'r_ingesta');
  } catch (e) { $('r_ingesta').textContent = '❌ ' + e.message; }
}

async function ceder() {
  try {
    await pide(BASE + '/cesiones', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token(),
                 'Content-Type': 'application/json' },
      // `total` va como cadena a propósito: un número JSON con decimales se
      // rechaza, y con razón — el importe es dinero, no coma flotante.
      body: JSON.stringify({
        uuid: $('c_uuid').value.trim(),
        financiador: $('c_financiador').value.trim(),
        total: $('c_total').value.trim(),
        moneda: $('c_moneda').value
      })
    }, 'r_cesion');
  } catch (e) { $('r_cesion').textContent = '❌ ' + e.message; }
}

async function cerrar() {
  const dia = $('dia').value.trim();
  try {
    await pide(BASE + '/cierre-diario' + (dia ? '?dia=' + encodeURIComponent(dia) : ''),
      { method: 'POST', headers: { 'Authorization': 'Bearer ' + token() } },
      'r_cierre');
  } catch (e) { $('r_cierre').textContent = '❌ ' + e.message; }
}

async function ciclo() {
  const cuantos = $('cantidad').value.trim() || '40';
  try {
    await pide(BASE + '/ciclo-diario?cantidad=' + encodeURIComponent(cuantos),
      { method: 'POST', headers: { 'Authorization': 'Bearer ' + token() } },
      'r_ciclo');
  } catch (e) { $('r_ciclo').textContent = '❌ ' + e.message; }
}

async function consultar() {
  const uuid = $('q_uuid').value.trim();
  if (!uuid) { $('r_consulta').textContent = 'Escribe un UUID.'; return; }
  // Sin token: leer es público a propósito.
  await pide(BASE + '/auditoria/prueba/' + encodeURIComponent(uuid), {}, 'r_consulta');
}

async function estado() { await pide(BASE + '/semaforo', {}, 'r_estado'); }
async function anclado() { await pide(BASE + '/anclajes', {}, 'r_estado'); }

document.addEventListener('DOMContentLoaded', () => {
  $('dia').value = new Date().toISOString().slice(0, 10);
});
"""

_PAGINA = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Consola de operación — Auditoría CØRD</title>
<style>{_ESTILO}</style></head><body>

<h1>Consola de operación</h1>
<p>Las mismas llamadas que harías con <code>curl</code>, desde el navegador. Para
leer la evidencia en prosa está <a href="vista">la vista pública</a>.</p>

<div class="aviso">
  <strong>El token no se guarda en ninguna parte.</strong> Vive en la memoria de
  esta pestaña mientras esté abierta y viaja en el encabezado
  <code>Authorization</code> de cada petición — nunca en la barra de direcciones,
  nunca en el servidor. Al recargar la página hay que volver a escribirlo.
</div>

<section>
  <label for="token">Token de escritura</label>
  <input type="password" id="token" autocomplete="off"
         placeholder="el valor de AGENTE_CFDI_TOKEN_ESCRITURA">
</section>

<h2>El agente</h2>
<section>
  <p>Pregúntale en lenguaje natural. <strong>Solo puede leer</strong>: consulta el
  estado de un folio, explica un veredicto y reporta la integridad de la cadena.
  No ingiere, no cede y no cierra el día — y si se lo pides, lo dice.</p>
  <p>Esa contención no es una etapa temprana: es la propiedad de seguridad.
  Ninguna afirmación de integridad pasa por el modelo, porque el hash, el
  encadenamiento y la prueba de Merkle son código determinista con pruebas.</p>
  <label for="pregunta">Pregunta</label>
  <input type="text" id="pregunta" placeholder="¿La bitácora está íntegra?">
  <button onclick="preguntar()">Preguntar</button>
  <button class="secundario" onclick="preguntar('¿La bitácora está íntegra y su evidencia está publicada?')">Integridad</button>
  <button class="secundario" onclick="preguntar('¿Cuántas facturas se han auditado y ya se cerró el día?')">Resumen</button>
  <button class="secundario" onclick="preguntar('Ingiere estas facturas y cierra el día por mí.')">Pídele que escriba</button>
  <pre id="r_agente">—</pre>
  <p><small id="modelo"></small></p>
</section>

<h2>1. Ingerir CFDI</h2>
<section>
  <p>Sube los XML. Un archivo ilegible no tumba el lote: se reporta en
  <code>fallas</code> y los demás se procesan. Máximo 500 por envío.</p>
  <label for="archivos">Archivos XML</label>
  <input type="file" id="archivos" multiple accept=".xml,text/xml,application/xml">
  <button onclick="ingerir()">Ingerir lote</button>
  <pre id="r_ingesta">—</pre>
</section>

<h2>2. Registrar una cesión</h2>
<section>
  <p>El importe tiene que coincidir con el del CFDI. Si el folio ya fue cedido a
  otro financiador, la respuesta es <code>409</code> y queda escrito el intento.</p>
  <label for="c_uuid">UUID del folio</label>
  <input type="text" id="c_uuid" placeholder="176747D9-0B62-4F26-A9E2-E4ABB8A296DD">
  <div class="fila">
    <div><label for="c_financiador">Financiador</label>
      <input type="text" id="c_financiador" placeholder="Financiera Demo"></div>
    <div><label for="c_total">Importe</label>
      <input type="text" id="c_total" placeholder="550046.40"></div>
    <div><label for="c_moneda">Moneda</label>
      <select id="c_moneda"><option>MXN</option><option>USD</option></select></div>
  </div>
  <button onclick="ceder()">Registrar cesión</button>
  <pre id="r_cesion">—</pre>
</section>

<h2>3. Cerrar el día y anclar</h2>
<section>
  <div class="aviso">
    <strong>Anclar es irrepetible por día.</strong> Un segundo cierre del mismo
    día devuelve la constancia original, no una raíz nueva. Lo que ingieras
    <em>después</em> de anclar queda en la cadena pero fuera de la raíz publicada
    de ese día. Cierra cuando ya entró todo.
  </div>
  <p>El cierre <strong>verifica la cadena antes de anclar</strong>: publicar la
  raíz de una cadena manipulada dejaría constancia permanente de datos corruptos.</p>
  <label for="dia">Día (AAAA-MM-DD)</label>
  <input type="text" id="dia" placeholder="2026-08-28">
  <button onclick="cerrar()">Cerrar y anclar</button>
  <pre id="r_cierre">—</pre>
</section>

<h2>4. Ciclo autónomo con datos sintéticos</h2>
<section>
  <p>Genera un lote sintético, lo ingiere y lo audita solo — para ver el ciclo
  completo sin armar XML a mano.</p>
  <label for="cantidad">Cuántos comprobantes</label>
  <input type="text" id="cantidad" value="40">
  <button onclick="ciclo()">Correr el ciclo</button>
  <pre id="r_ciclo">—</pre>
</section>

<h2>5. Comprobar</h2>
<section>
  <p>Estas dos no piden token: leer es público a propósito.</p>
  <label for="q_uuid">Prueba de inclusión de un folio</label>
  <input type="text" id="q_uuid" placeholder="UUID del CFDI">
  <button onclick="consultar()">Pedir la prueba de Merkle</button>
  <pre id="r_consulta">—</pre>
  <button class="secundario" onclick="estado()">Ver el semáforo</button>
  <button class="secundario" onclick="anclado()">Ver lo anclado</button>
  <pre id="r_estado">—</pre>
</section>

<script>{_GUION}</script>
</body></html>
"""


def registrar_consola(app) -> None:
    """Cuelga la consola. No recibe funciones de datos: no lee nada del servidor.

    La página es estática y todo el trabajo lo hace el navegador contra los
    endpoints que ya existen. Por eso no hay nada que probar aquí sobre
    veredictos: no los toca.
    """

    @app.get("/consola", include_in_schema=False)
    def consola() -> HTMLResponse:
        return HTMLResponse(_PAGINA)
