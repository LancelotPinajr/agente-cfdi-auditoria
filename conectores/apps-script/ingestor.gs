/**
 * El ingestor: de un buzón de Gmail y de una hoja, a la bitácora encadenada.
 *
 * Sustituye la carga manual de lotes sintéticos por dos fuentes que una PYME ya
 * usa: el correo donde le llegan sus CFDI y una hoja donde los pega. Lo que
 * ocurre después —validación, cotejo contra libros, encadenamiento, detección
 * de doble cesión— no cambia ni una línea: este archivo solo entrega el lote en
 * `/auditoria/ingesta`, que es la misma puerta de siempre.
 *
 * ## Qué NO hace, y es a propósito
 *
 * No decide si un CFDI es válido, no calcula hashes y no emite veredictos. Si
 * lo hiciera, habría dos implementaciones de las reglas —una en Python con
 * pruebas, otra en JavaScript sin ellas— y la segunda acabaría discrepando de
 * la primera justo cuando importara. Aquí solo hay transporte.
 *
 * ## Los CFDI son sintéticos, y eso es una decisión
 *
 * El buzón que este conector lee recibe comprobantes del generador sintético
 * del propio repo. La frontera #4 de `docs/05-alcance-y-no-objetivos.md`
 * explica por qué no entran CFDI reales de terceros: anclar la huella de datos
 * patrimoniales ajenos en una cadena pública no se deshace, y un sistema cuya
 * tesis es «lo que se publica no se puede retirar» no puede publicar datos de
 * terceros para lucirse en una demo.
 */

/** Etiquetas del buzón. La segunda es lo que impide ingerir dos veces el mismo
 *  correo: sin ella, cada corrida del disparador volvería a mandar todo. */
var ETIQUETA_ENTRADA   = 'cfdi-entrada';
var ETIQUETA_PROCESADO = 'cfdi-procesado';

/** Cuántos hilos se miran por corrida. Apps Script corta a los 6 minutos; un
 *  tope explícito falla de forma predecible en vez de a mitad de un lote. */
var MAXIMO_HILOS = 50;

/**
 * Lee el buzón y manda a la bitácora los XML que encuentre.
 *
 * Un correo sin adjuntos XML no es un error: se etiqueta como procesado y se
 * sigue. Lo contrario dejaría el buzón atascado en el primer mensaje suelto.
 */
function ingerirDesdeCorreo() {
  var entrada = GmailApp.getUserLabelByName(ETIQUETA_ENTRADA);
  if (!entrada) {
    throw new Error('No existe la etiqueta "' + ETIQUETA_ENTRADA + '" en Gmail. ' +
                    'Créala y aplícala (o crea un filtro que la aplique) a los ' +
                    'correos con CFDI adjuntos.');
  }
  var procesado = GmailApp.getUserLabelByName(ETIQUETA_PROCESADO) ||
                  GmailApp.createLabel(ETIQUETA_PROCESADO);

  var hilos = GmailApp.search(
      'label:' + ETIQUETA_ENTRADA + ' -label:' + ETIQUETA_PROCESADO,
      0, MAXIMO_HILOS);

  if (!hilos.length) {
    registrarEvento('ingestor', 'buzón sin correos nuevos');
    return;
  }

  var archivos = [];
  hilos.forEach(function (hilo) {
    hilo.getMessages().forEach(function (mensaje) {
      mensaje.getAttachments().forEach(function (adjunto) {
        if (esCFDI(adjunto)) {
          archivos.push({
            nombre: adjunto.getName(),
            texto: adjunto.getDataAsString('UTF-8'),
            origen: 'correo: ' + mensaje.getFrom()
          });
        }
      });
    });
  });

  var resumen = enviarLote(archivos, 'correo');
  hilos.forEach(function (hilo) { hilo.addLabel(procesado); });
  registrarEvento('ingestor', hilos.length + ' hilos procesados — ' + resumen);
}

/**
 * Manda lo que esté pegado en la pestaña «Cola».
 *
 * Columna A: el XML completo. Columna B: nombre opcional. La fila se marca en
 * la columna C con el resultado, y las marcadas se saltan en la siguiente
 * corrida.
 */
function ingerirDesdeLaCola() {
  var h = hoja(HOJA_COLA);
  if (h.getLastRow() < 2) {
    h.getRange(1, 1, 1, 3)
     .setValues([['XML del CFDI', 'Nombre (opcional)', 'Estado']])
     .setFontWeight('bold');
    h.setFrozenRows(1);
    registrarEvento('ingestor', 'la cola está vacía');
    return;
  }

  var filas = h.getRange(2, 1, h.getLastRow() - 1, 3).getValues();
  var archivos = [];
  var indices = [];

  filas.forEach(function (fila, i) {
    var xml = String(fila[0] || '').trim();
    var estado = String(fila[2] || '').trim();
    if (!xml || estado) return;           // vacía, o ya enviada
    archivos.push({
      nombre: String(fila[1] || '').trim() || ('cola-' + (i + 2) + '.xml'),
      texto: xml,
      origen: 'cola'
    });
    indices.push(i + 2);
  });

  var resumen = enviarLote(archivos, 'cola');
  indices.forEach(function (fila) {
    h.getRange(fila, 3).setValue('enviada ' +
        Utilities.formatDate(new Date(), 'America/Mexico_City', 'yyyy-MM-dd HH:mm'));
  });
  registrarEvento('ingestor', 'cola — ' + resumen);
}

/** Un adjunto cuenta como CFDI si es XML. El servidor decide si además es
 *  válido: filtrar más aquí sería duplicar el lector de CFDI en JavaScript. */
function esCFDI(adjunto) {
  var nombre = adjunto.getName().toLowerCase();
  return nombre.slice(-4) === '.xml' ||
         adjunto.getContentType() === 'text/xml' ||
         adjunto.getContentType() === 'application/xml';
}

/**
 * Parte el lote si hace falta y lo entrega en `/auditoria/ingesta`.
 *
 * El corte por tamaño y por número replica los topes del servidor
 * (`MAXIMO_ARCHIVOS`, `MAXIMO_BYTES_DEL_LOTE`). Se hace aquí para que un buzón
 * con 700 comprobantes se mande en dos viajes en vez de rebotar con 413 y
 * dejar todo sin ingerir.
 */
function enviarLote(archivos, origen) {
  if (!archivos.length) return 'nada que enviar';

  var token = tokenDeEscritura();
  var enviados = 0, auditados = 0, rechazados = 0, hallazgos = 0;
  var tanda = [], bytes = 0;

  function descargar() {
    if (!tanda.length) return;
    var r = postDeIngesta(tanda, token);
    enviados   += tanda.length;
    auditados  += r.auditados;
    rechazados += r.rechazados;
    hallazgos  += r.hallazgos;
    anotarFolios(r, origen);
    tanda = [];
    bytes = 0;
  }

  archivos.forEach(function (a) {
    var peso = Utilities.newBlob(a.texto).getBytes().length;
    if (tanda.length + 1 > MAXIMO_ARCHIVOS || bytes + peso > MAXIMO_BYTES_DEL_LOTE) {
      descargar();
    }
    tanda.push(a);
    bytes += peso;
  });
  descargar();

  return enviados + ' enviados, ' + auditados + ' auditados, ' +
         rechazados + ' rechazados, ' + hallazgos + ' hallazgos';
}

/**
 * El POST multipart.
 *
 * Se arma a mano porque `/ingesta` recibe `archivos: list[UploadFile]` —el
 * mismo nombre de campo repetido— y el `payload` como objeto de Apps Script no
 * admite claves duplicadas. Los CFDI son XML, o sea texto, así que el cuerpo se
 * construye como cadena y se codifica en UTF-8 al final; no hay binario que
 * corromper.
 */
function postDeIngesta(archivos, token) {
  var frontera = '----cordFrontera' + Utilities.getUuid().replace(/-/g, '');
  var cuerpo = '';

  archivos.forEach(function (a) {
    var nombre = a.nombre.replace(/"/g, '');   // comillas rompen el header
    cuerpo += '--' + frontera + '\r\n';
    cuerpo += 'Content-Disposition: form-data; name="archivos"; filename="' +
              nombre + '"\r\n';
    cuerpo += 'Content-Type: application/xml\r\n\r\n';
    cuerpo += a.texto + '\r\n';
  });
  cuerpo += '--' + frontera + '--\r\n';

  var respuesta = UrlFetchApp.fetch(MOTOR + '/ingesta', {
    method: 'post',
    contentType: 'multipart/form-data; boundary=' + frontera,
    payload: Utilities.newBlob(cuerpo).getBytes(),
    headers: { Authorization: 'Bearer ' + token },
    muteHttpExceptions: true
  });

  var codigo = respuesta.getResponseCode();
  var texto = respuesta.getContentText();

  if (codigo === 401 || codigo === 403) {
    throw new Error('El servicio rechazó el token de escritura (' + codigo +
                    '). Revisa AGENTE_CFDI_TOKEN_ESCRITURA en las propiedades ' +
                    'del script.');
  }
  if (codigo === 503) {
    throw new Error('El despliegue no tiene token de escritura configurado, ' +
                    'así que no acepta escrituras. No es tu credencial: es el ' +
                    'servicio. Ver autenticacion.py.');
  }
  if (codigo !== 200) {
    throw new Error('POST /ingesta devolvió ' + codigo + ': ' + texto.slice(0, 400));
  }
  return JSON.parse(texto);
}

/**
 * Vuelca en el padrón lo que el servidor dijo de cada comprobante.
 *
 * Se escriben los `registros` que devuelve la ingesta y no los archivos que se
 * mandaron: si uno fue rechazado, no tiene UUID ni posición y no pertenece al
 * padrón. Las fallas van al log de eventos, donde se pueden leer sin ensuciar
 * la lista de folios buenos.
 */
function anotarFolios(respuesta, origen) {
  var h = hoja(HOJA_FOLIOS);
  if (h.getLastRow() === 0) encabezadoDeFolios(h);

  var momento = Utilities.formatDate(
      new Date(), 'America/Mexico_City', 'yyyy-MM-dd HH:mm:ss');

  (respuesta.registros || []).forEach(function (r) {
    h.appendRow([r.uuid, momento, origen, r.monto_del_cfdi, '', '', '', r.veredicto]);
  });

  (respuesta.fallas || []).forEach(function (f) {
    registrarEvento('ingestor',
        'rechazado ' + f.archivo + ' — ' + f.motivo + ': ' + f.detalle);
  });
}
