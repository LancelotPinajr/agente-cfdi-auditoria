/**
 * El panel: la hoja como tablero de auditoría.
 *
 * ## Por qué el panel no usa NotebookLM
 *
 * NotebookLM no tiene conector de Gmail, no toma una hoja de cálculo como
 * fuente nativa, y una URL importada es una *fotografía* del momento en que se
 * importó — no la vuelve a leer sola. Un tablero cuyo semáforo se congela el
 * día que lo creaste es peor que no tener tablero, porque parece vivo.
 *
 * Así que el tablero vive aquí, contra los endpoints de lectura, que son
 * públicos por decisión explícita del proyecto. NotebookLM entra después y en
 * otro papel: se le da `reporte.html` —prosa, no JSON— para que explique la
 * evidencia, no para que la vigile.
 *
 * ## Por qué el panel no necesita token
 *
 * Porque no escribe. `src/agente_cfdi/api/autenticacion.py` traza la línea en
 * la operación y no en el servicio: verificar la cadena entera es público, y
 * que lo sea es el punto entero del producto. Este archivo se queda de ese
 * lado de la línea.
 */

/** Los cuatro colores del semáforo, tal como los define `esquemas.Semaforo`. */
var COLORES = {
  verde: '#34a853',
  ambar: '#f9ab00',
  gris:  '#9aa0a6',
  rojo:  '#d93025'
};

/** Menú propio al abrir la hoja, para no depender del editor de scripts. */
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('CØRD')
    .addItem('Actualizar panel', 'actualizarPanel')
    .addItem('Ver lo anclado', 'refrescarAnclajes')
    .addSeparator()
    .addItem('Ingerir correo ahora', 'ingerirDesdeCorreo')
    .addItem('Ingerir cola de la hoja', 'ingerirDesdeLaCola')
    .addSeparator()
    .addItem('Instalar disparadores', 'instalarDisparadores')
    .addToUi();
}

/** Lo que corre cada N minutos y lo que corre el botón del menú. */
function actualizarPanel() {
  pintarSemaforo();
  refrescarAnclajes();
  refrescarFolios();
}

/**
 * Vuelca semáforo + verificación + salud en la pestaña principal.
 *
 * Se pinta el color que dice el servidor y no uno calculado aquí. El matiz
 * importa: el ámbar de «íntegra pero sin publicar» es una afirmación
 * cuidadosamente acotada del motor, y recalcularla en el cliente sería
 * inventar un veredicto que nadie probó.
 */
function pintarSemaforo() {
  var semaforo     = leerDelMotor('/semaforo');
  var verificacion = leerDelMotor('/bitacora/verificacion');
  var salud        = leerDelMotor('/salud');

  var h = hoja(HOJA_SEMAFORO);
  h.clear();

  h.getRange('A1').setValue('Auditoría CØRD — estado de la bitácora')
                  .setFontSize(16).setFontWeight('bold');
  h.getRange('A2').setValue('Actualizado: ' +
      Utilities.formatDate(new Date(), 'America/Mexico_City', 'yyyy-MM-dd HH:mm:ss'))
                  .setFontColor('#5f6368');

  h.getRange('A4').setValue(semaforo.titulo)
                  .setFontSize(20).setFontWeight('bold')
                  .setFontColor('#ffffff')
                  .setBackground(COLORES[semaforo.color] || COLORES.gris);
  h.getRange('A4:D4').merge();

  h.getRange('A5').setValue(semaforo.detalle).setWrap(true);
  h.getRange('A5:D5').merge();

  var filas = [
    ['Altura de la cadena',        semaforo.altura],
    ['Eslabones verificados',      semaforo.verificados],
    ['Cadena íntegra',             verificacion.integra ? 'sí' : 'NO'],
    ['Punta',                      verificacion.punta],
    ['Suprimidos por retención',   verificacion.suprimidos_por_retencion],
    ['Inquilino',                  salud.inquilino],
    ['Día en curso',               semaforo.dia || '—'],
    ['Posición del problema',      semaforo.posicion_del_problema === null
                                     ? 'ninguno' : semaforo.posicion_del_problema],
    ['Red del ancla',              semaforo.ancla ? semaforo.ancla.red : 'sin anclar'],
    ['Referencia del ancla',       semaforo.ancla ? semaforo.ancla.referencia : '—'],
    ['Verificable por terceros',   semaforo.ancla
                                     ? (semaforo.ancla.verificable_por_terceros ? 'sí' : 'no')
                                     : 'todavía no'],
    ['Explorador',                 semaforo.enlace_al_explorador || '—']
  ];
  h.getRange(7, 1, filas.length, 2).setValues(filas);
  h.getRange(7, 1, filas.length, 1).setFontWeight('bold');

  // `enlace_al_explorador` es `null` cuando no hay dónde comprobarlo, y el
  // esquema dice explícitamente que no se inventa una URL. Se respeta.
  if (semaforo.enlace_al_explorador) {
    h.getRange(7 + filas.length - 1, 2)
     .setFormula('=HYPERLINK("' + semaforo.enlace_al_explorador + '";"ver en el explorador")');
  }

  h.setColumnWidth(1, 220);
  h.setColumnWidth(2, 520);
  registrarEvento('panel', 'semáforo ' + semaforo.color + ', altura ' + semaforo.altura);
}

/**
 * Actualiza el estado de cesión de cada folio del padrón.
 *
 * El motor no expone «lista todos los UUID» —y no hace falta que lo haga—, así
 * que el padrón lo construye el ingestor: cada CFDI que entra deja su fila
 * aquí. Este método solo rellena las columnas que dependen del servidor.
 */
function refrescarFolios() {
  var h = hoja(HOJA_FOLIOS);
  if (h.getLastRow() < 2) {
    encabezadoDeFolios(h);
    return;
  }

  var uuids = h.getRange(2, 1, h.getLastRow() - 1, 1).getValues();
  var estados = uuids.map(function (fila) {
    var uuid = String(fila[0]).trim();
    if (!uuid) return ['', '', '', ''];
    try {
      var e = leerDelMotor('/cesiones/' + encodeURIComponent(uuid));
      return [
        e.cedida ? 'CEDIDA' : 'libre',
        e.cedido_en || '',
        e.auditada ? 'sí' : 'no',
        e.veredicto || ''
      ];
    } catch (err) {
      // Un folio que no se pudo consultar se marca como tal. Dejarlo en blanco
      // lo haría indistinguible de «libre», que es la afirmación contraria.
      return ['error', String(err).slice(0, 120), '', ''];
    }
  });

  h.getRange(2, 5, estados.length, 4).setValues(estados);
  registrarEvento('panel', 'refrescados ' + estados.length + ' folios');
}

/** Encabezado del padrón. Las columnas A–D las llena el ingestor; E–H, el panel. */
function encabezadoDeFolios(h) {
  h.getRange(1, 1, 1, 8).setValues([[
    'UUID', 'Ingerido', 'Origen', 'Monto',
    'Cesión', 'Cedido en', 'Auditada', 'Veredicto'
  ]]).setFontWeight('bold');
  h.setFrozenRows(1);
  h.setColumnWidth(1, 300);
}

/**
 * Vuelca el índice de raíces publicadas.
 *
 * Es la pestaña que contesta la pregunta que el resto del panel no contestaba:
 * *«¿qué se ancló, y dónde lo comprueba alguien que no nos cree?»*. El semáforo
 * habla del día en curso; esto es el historial.
 *
 * La columna del explorador queda vacía cuando el motor devuelve `null`, que es
 * lo que hace con una red sin explorador conocido. No se rellena con un texto
 * de relleno: una celda vacía dice «no hay a dónde ir», y eso es exactamente lo
 * que pasa.
 */
function refrescarAnclajes() {
  var indice = leerDelMotor('/anclajes');
  var h = hoja(HOJA_ANCLAJES);
  h.clear();

  h.getRange(1, 1, 1, 6).setValues([[
    'Día', 'Raíz de Merkle', 'Registros', 'Red', 'Verificable por terceros', 'Comprobar'
  ]]).setFontWeight('bold');
  h.setFrozenRows(1);

  if (!indice.total) {
    h.getRange(2, 1).setValue(
        'Todavía no hay ninguna raíz publicada para el inquilino ' +
        indice.inquilino + '.');
    registrarEvento('panel', 'sin anclajes que listar');
    return;
  }

  var filas = indice.anclajes.map(function (a) {
    return [a.dia, a.raiz, a.registros, a.red,
            a.verificable_por_terceros ? 'sí' : 'no — ancla simulada', ''];
  });
  h.getRange(2, 1, filas.length, 6).setValues(filas);

  indice.anclajes.forEach(function (a, i) {
    if (a.enlace_al_explorador) {
      h.getRange(2 + i, 6).setFormula(
          '=HYPERLINK("' + a.enlace_al_explorador + '";"ver la transacción")');
    }
  });

  h.setColumnWidth(2, 480);
  registrarEvento('panel', indice.total + ' raíces publicadas listadas');
}


/**
 * Deja el panel actualizándose solo.
 *
 * Diez minutos es deliberado: el ciclo que importa es diario (cierre, Merkle,
 * anclaje) y un tablero que consulta cada minuto gasta cuota sin decir nada
 * nuevo.
 */
function instalarDisparadores() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    ScriptApp.deleteTrigger(t);
  });

  ScriptApp.newTrigger('actualizarPanel').timeBased().everyMinutes(10).create();
  ScriptApp.newTrigger('ingerirDesdeCorreo').timeBased().everyMinutes(15).create();

  registrarEvento('panel', 'disparadores instalados: panel 10 min, ingesta 15 min');
  SpreadsheetApp.getUi().alert(
    'Listo. El panel se actualiza cada 10 minutos y el buzón se revisa cada 15.');
}
