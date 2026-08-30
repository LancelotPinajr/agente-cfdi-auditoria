# Sprint 3 · Manejo de estado — tareas 3.13 a 3.18

**Por qué existe este documento:** el rubro de calificación dice literalmente *manejo de
estado* y pesa dentro del 30% de disciplina arquitectónica. El plan de equipo original
nunca escribió una tarea para cubrirlo. No es una tarea abierta: es una tarea que faltaba.

**Congelación de funcionalidad: 28 de agosto.** Todo lo de aquí cabe antes, y está
ordenado para que si se corta a la mitad, lo entregado siga siendo coherente.

---

## El diagnóstico, en una línea

Hoy la bitácora es SQLite en `/tmp` de Cloud Run. Se pierde al reciclar la instancia.

Lo que **ya está bien resuelto y no se toca:**

- `--max-instances=1` en [`deploy.ps1`](../deploy.ps1) no es ahorro de costo, es el
  invariante de **un solo escritor**. Con dos instancias cada una escribiría su propia
  cadena y la punta se bifurcaría. Está documentado en el propio script.
- `BEGIN IMMEDIATE` en [`almacen.py`](../src/agente_cfdi/bitacora/almacen.py) serializa
  las escrituras *dentro* de esa instancia.

El error de diseño no es el candado. **El candado es correcto.** El error es haber
confundido el dominio del candado con el dominio de la durabilidad.

```
dominio del candado      →  una instancia   →  ya resuelto (max-instances=1 + BEGIN IMMEDIATE)
dominio de la durabilidad →  fuera de la instancia  →  NO resuelto  ← esto es 3.13–3.17
```

## La decisión: snapshot a GCS, no base gestionada

**Diferido — Cloud SQL (Postgres).** Hay que ser preciso sobre cuánto falta, porque el
proyecto está más cerca de lo que parecía: la migración **ya está escrita** en
[`migraciones/001_bitacora.sql`](../migraciones/001_bitacora.sql), con
`pg_advisory_xact_lock(hashtext(inquilino))` —por inquilino, o sea que sí escala
horizontalmente— y triggers que rechazan `UPDATE` y `DELETE`.

Lo que falta es la capa de Python: **16 puntos de acoplamiento a `sqlite3`** en dos
archivos, de cuatro clases (`connect`, `Row`, `IntegrityError`, `BEGIN IMMEDIATE`).
Cuatro costuras es poco. Pero esa ruta **no está ejercitada por pruebas** —hueco ya
declarado en ADR 0004— y ejercitarla exige levantar un servidor en CI. A cuatro días de
la congelación es abrir un frente nuevo por un problema que el snapshot ya resuelve.
Se difiere, no se descarta: es el primer trabajo de después del hackathon.

**Descartado — volumen GCS montado (FUSE) con el archivo SQLite encima.** GCS FUSE no
implementa el bloqueo de archivos de POSIX que SQLite necesita. Bajo escritura concurrente
corrompe la base. Es peor que el problema que resuelve.

**Elegido — respaldo consistente del archivo a GCS y restauración al arranque.**
`sqlite3.Connection.backup()` es biblioteca estándar, produce un snapshot consistente sin
detener escrituras, y no toca el esquema ni una sola prueba. GCS versiona los objetos, así
que además queda historial. El invariante de un solo escritor sigue siendo lo que hace que
esto sea seguro — y esa dependencia hay que declararla, no esconderla (3.15).

---

## Tareas

### 3.13 — Restauración de la bitácora al arranque ✅
**Dueño:** Dinesh · **Cerrada el 26-ago** — [`bitacora/respaldo.py`](../src/agente_cfdi/bitacora/respaldo.py)

Al iniciar, si la ruta de la bitácora no existe, el servicio descarga el último snapshot
antes de atender la primera petición. Va en el arranque y no en el primer acceso perezoso:
si no, una escritura podría ganarle y anexar sobre una cadena vacía.

> **Criterio de aceptación:** se borra `/tmp/bitacora.db`, se reinicia el servicio, y
> `GET /auditoria/semaforo` devuelve la **misma altura y la misma raíz del día** que antes
> del reinicio, sin haber corrido el ciclo. Si no hay snapshot, arranca vacía y lo dice en
> el log — nunca falla en silencio.

**Cómo se cumplió.** `test_la_cadena_sobrevive_a_que_se_borre_la_ruta` borra el archivo,
levanta el servicio de nuevo y comprueba que la prueba de Merkle del mismo folio sale con
la **misma raíz, misma posición, misma punta y misma altura**. Se usa la raíz de
`/auditoria/prueba/{uuid}` y no la del semáforo porque el semáforo no la expone — el
endpoint que menciona el criterio es `/semaforo`, no `/auditoria/semaforo`.

Tres cosas que el criterio no pedía y están:

- Un snapshot que no pasa `PRAGMA integrity_check` **no se instala**. Arranca vacía y lo
  dice. Instalar un archivo corrupto y descubrirlo en la primera consulta sería cambiar
  una pérdida ruidosa por una silenciosa.
- No se restaura encima de una bitácora que ya existe: un reinicio del proceso dentro de
  la misma instancia no es una instancia nueva.
- El semáforo ya no dice sólo «está vacía». Dice **por qué**: sin respaldo configurado,
  sin snapshot, snapshot corrupto o almacén caído. Eran cuatro problemas distintos que se
  veían igual.

### 3.14 — Respaldo consistente después de cada escritura confirmada ✅
**Dueño:** Gilfoyle · **Cerrada el 26-ago** — 20 pruebas nuevas, 397 en total

Tras cada transacción confirmada, `Connection.backup()` produce un snapshot y se sube. La
subida ocurre **fuera** del candado de escritura: un fallo de red no puede tumbar una
cesión ya confirmada.

> **Criterio de aceptación:** el objeto en GCS cambia de generación tras cada commit. Se
> mata el proceso a media subida y el snapshot anterior sigue siendo válido y restaurable
> — se prueba, no se supone. Un fallo de GCS deja el sistema degradado y alertando, nunca
> con una escritura perdida ni una petición caída.

**Una corrección al enunciado, y por qué importa.** «La subida ocurre fuera del candado»
admite una implementación que devuelve el problema: si cada commit dispara su propia
subida, dos subidas se traslapan y pueden llegar en orden inverso. El snapshot de altura
41 aterriza después del de 42 y queda como vigente. La restauración vuelve entonces a una
cadena más corta **sin error y sin log**, que verifica perfecto porque es un prefijo
válido de sí misma. Es el fallo del ADR 0007: no uno que rompa, uno que produce evidencia
de aspecto correcto.

Por eso las subidas pasan por **un solo hilo consumidor**, y la instantánea pendiente se
reemplaza en vez de encolarse — no se pierde nada, cada instantánea es el archivo completo.
`test_las_subidas_llegan_al_almacen_en_orden_de_confirmacion` lo fija.

**La ventana que sí existe, declarada.** La instantánea se toma síncrona tras el commit
(la conexión se cierra al terminar la petición) pero la subida es asíncrona. Un `SIGKILL`
entre las dos se lleva esas escrituras. «Nunca con una escritura perdida» sólo es
literalmente cierto con subida síncrona, que es lo que «fuera del candado» descarta. La
ventana está acotada a una subida, el apagado ordenado la vacía, y `/semaforo` la reporta
en el bloque `respaldo`. No se esconde detrás de una redacción que suene mejor.

### 3.15 — El invariante de un solo escritor, declarado como ADR ✅
**Dueño:** Gilfoyle · **Cerrada el 25-ago** — [ADR 0007](adr/0007-dominio-del-candado-y-dominio-de-la-durabilidad.md)

`ADR 0007`: por qué el dominio del candado y el dominio de la durabilidad son distintos,
por qué `max-instances=1` es una condición de corrección y no una optimización, y qué
exactamente se rompe si alguien sube ese número creyendo que escala.

> **Criterio de aceptación:** el ADR existe y `deploy.ps1` lo referencia por número en el
> comentario de `--max-instances`. Alguien que herede el proyecto no puede subir la bandera
> sin toparse con la explicación.

### 3.16 — El semáforo distingue «vacía» de «íntegra» ✅
**Dueño:** Gilfoyle · **Cerrada el 25-ago** — color `gris`, 377 pruebas

**Fue la tarea más barata de las seis y la que más importaba.** Una cadena de altura 0
verifica trivialmente: no hay ningún eslabón que pueda no cuadrar. Antes de 3.16, ese caso
caía en el ámbar **«ÍNTEGRA, SIN PUBLICAR»**, con un detalle que afirmaba que los eslabones
recalculables cuadraban. Cuadraban cero. Afirmar integridad justo después de haberlo
perdido todo es exactamente el fallo que este producto existe para no cometer.

Se agregó el color `gris` / «SIN CADENA QUE VERIFICAR» — no alarma, pero tampoco confirma.

> **Criterio de aceptación:** con la bitácora vacía y sin snapshot que restaurar, el
> semáforo devuelve un color **distinto de verde** y un texto que dice que no hay cadena
> que verificar, no que la cadena esté íntegra. Con la cadena restaurada desde snapshot,
> el semáforo dice explícitamente que fue restaurada y de qué generación.

### 3.17 — Prueba de pérdida de instancia, de punta a punta
**Dueño:** Ambos · **Estimado:** medio día

> **Criterio de aceptación:** se despliega una revisión nueva —lo cual borra `/tmp`— y
> después del despliegue la cadena tiene la **misma altura**, verifica completa, y la
> prueba de Merkle de un UUID anterior al despliegue sigue validando contra la raíz que
> está en Base Sepolia. Evidencia escrita con logs correlacionados, en el formato de
> `docs/evidencias/`.

Esta evidencia sustituye al párrafo del README que hoy declara la debilidad. **Es el
plano de video que convierte el punto más débil del proyecto en una demostración.**

### 3.18 — Los CFDI sintéticos validan contra el esquema oficial del SAT
**Dueño:** Gilfoyle · **Estimado:** medio día · *no es manejo de estado, es credibilidad*

Cada XML generado se valida contra `cfdv40.xsd` y `TimbreFiscalDigital11.xsd` oficiales.

> **Criterio de aceptación:** prueba automatizada que valida todo lote generado contra los
> XSD del SAT. Permite afirmar con precisión: **«son CFDI 4.0 estructuralmente válidos
> ante el esquema del SAT; lo único sintético son el RFC y el sello»** — que es una
> afirmación mucho más fuerte que «son sintéticos».

---

## Orden de ejecución

```
3.16  ✅ 25-ago  ← el más barato y el que arregló un fallo de honestidad
3.15  ✅ 25-ago  ← ADR 0007, no tocaba código
3.13  ✅ 26-ago  ← restauración
3.14  ✅ 26-ago  ← respaldo   (13 y 14 acabaron siendo un solo módulo)
3.17  ( ½ día )  ← la evidencia contra el servicio real. LO QUE FALTA.
3.18  ( ½ día )  ← si sobra tiempo antes del 28
```

**Dónde está la línea entre 3.13/3.14 y 3.17.** Lo cerrado está probado *localmente*: 397
pruebas, incluidas las que borran el archivo y lo restauran. Lo que **no** está probado es
el mismo recorrido contra Cloud Run y GCS de verdad — que es exactamente lo que 3.17 pide y
por qué sigue abierta. Hasta que esa evidencia exista, lo honesto es decir que el mecanismo
funciona y que todavía no se ha visto sobrevivir a un despliegue real.

Por la misma razón `--min-instances=1` sigue en 1. Con el snapshot ya no carga peso, pero
quitar la red antes de comprobar que el suelo aguanta es como se pierde una demo. En cuanto
3.17 dé la evidencia, puede bajar a 0 y ahorrar una instancia encendida todo el mes.

Dos días de trabajo repartidos entre dos personas, con margen antes de la congelación.

**Si hay que cortar:** 3.16 y 3.15 son innegociables — cuestan cuatro horas juntas y
arreglan un fallo de honestidad más un hueco de documentación. Si solo entran esas dos, el
proyecto queda estrictamente mejor que hoy y la debilidad sigue declarada con precisión.
3.18 es el primero que se sacrifica.

---

## Lo que sigue sin resolverse después de esto

Se declara para no prometer de más:

- **No hay escalamiento horizontal.** Sigue siendo una instancia. Con snapshot a GCS el
  dato sobrevive, pero dos instancias seguirían bifurcando la cadena. La solución real es
  Postgres con `pg_advisory_lock`, y es trabajo de después del hackathon.
- **No hay autenticación por financiador.** El token distingue quién puede escribir, no
  quién es. Tampoco tiene tarea, y a cuatro días de la congelación no debe tenerla.
- **La cola entre una confirmación y su subida se pierde con un `SIGKILL`.** Acotada a una
  subida, vaciada en el apagado ordenado, reportada en `/semaforo`. Cerrarla del todo exige
  subida síncrona —un viaje de red por commit— o escribir en Postgres directamente, que es
  lo mismo que resuelve el escalamiento horizontal. Es el segundo argumento para la misma
  migración, no un problema aparte.
