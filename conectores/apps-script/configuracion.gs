/**
 * Configuración compartida de los dos conectores.
 *
 * ## Por qué esta carpeta está fuera del agente
 *
 * El alcance funcional del agente ADK está congelado (frontera #5 de
 * `docs/05-alcance-y-no-objetivos.md`): tres herramientas, todas de solo
 * lectura, y esa contención *es* la propiedad de seguridad — no una etapa
 * temprana de un plan más grande.
 *
 * El ingestor de correo escribe en la bitácora. Meterlo como herramienta del
 * modelo rompería justo ese argumento. Así que vive aquí: un cliente HTTP
 * ordinario que llama a `/auditoria/ingesta` con el token de escritura,
 * exactamente como entra hoy un lote sintético. El modelo no lo ve, no lo
 * invoca y no puede invocarlo.
 *
 * ## Por qué el token no está en este archivo
 *
 * El código de Apps Script es visible para cualquiera con quien se comparta la
 * hoja. El token vive en las Propiedades del Script, que no se comparten con
 * el documento. Si falta, el ingestor se niega a correr en vez de mandar un
 * lote sin credencial y ensuciar los logs del servicio con 401.
 */

/** Raíz del despliegue. El motor de auditoría va montado en `/auditoria`. */
var BASE = 'https://agente-cfdi-run-xsxcmt7edq-uc.a.run.app';
var MOTOR = BASE + '/auditoria';

/** Límites que impone el servidor (`api/app.py`). Se respetan del lado cliente
 *  para que un lote grande se parta aquí y no rebote con 413. */
var MAXIMO_ARCHIVOS = 500;
var MAXIMO_BYTES_DEL_LOTE = 64 * 1024 * 1024;

/** Nombres de las pestañas. Cambiarlos aquí los cambia en todos lados. */
var HOJA_SEMAFORO = 'Semáforo';
var HOJA_FOLIOS   = 'Folios';
var HOJA_COLA     = 'Cola';
var HOJA_ANCLAJES = 'Anclajes';
var HOJA_EVENTOS  = 'Eventos';

/**
 * El token de escritura, o un error que explica qué hacer.
 *
 * Extensiones → Apps Script → Configuración del proyecto → Propiedades del
 * script → añadir `AGENTE_CFDI_TOKEN_ESCRITURA`.
 */
function tokenDeEscritura() {
  var token = PropertiesService.getScriptProperties()
      .getProperty('AGENTE_CFDI_TOKEN_ESCRITURA');
  if (!token) {
    throw new Error(
      'Falta la propiedad de script AGENTE_CFDI_TOKEN_ESCRITURA. ' +
      'Sin ella este conector no manda nada: prefiere no correr a mandar ' +
      'un lote sin credencial.');
  }
  return token.trim();
}

/** GET a un endpoint de lectura. No lleva token: leer es público a propósito
 *  (ver `src/agente_cfdi/api/autenticacion.py`). */
function leerDelMotor(ruta) {
  var respuesta = UrlFetchApp.fetch(MOTOR + ruta, {
    method: 'get',
    muteHttpExceptions: true
  });
  var codigo = respuesta.getResponseCode();
  if (codigo !== 200) {
    throw new Error('GET ' + ruta + ' devolvió ' + codigo + ': ' +
                    respuesta.getContentText().slice(0, 300));
  }
  return JSON.parse(respuesta.getContentText());
}

/** Devuelve la pestaña, creándola si no existe. */
function hoja(nombre) {
  var libro = SpreadsheetApp.getActiveSpreadsheet();
  return libro.getSheetByName(nombre) || libro.insertSheet(nombre);
}

/** Registro de lo que hicieron los conectores, para poder auditarlos a ellos.
 *  Sin esto, un ingestor que falla en silencio es indistinguible de un buzón
 *  vacío. */
function registrarEvento(origen, detalle) {
  var h = hoja(HOJA_EVENTOS);
  if (h.getLastRow() === 0) {
    h.appendRow(['Momento', 'Origen', 'Detalle']);
    h.getRange('A1:C1').setFontWeight('bold');
    h.setFrozenRows(1);
  }
  h.appendRow([new Date(), origen, detalle]);
}
