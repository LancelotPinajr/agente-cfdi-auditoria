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

**Descartado — Cloud SQL (Postgres).** Es la respuesta "correcta" de libro y la que más
puntuaría en abstracto. Pero la capa de persistencia es `sqlite3` crudo, no un ORM:
migrarla a cuatro días de la congelación pone en riesgo las 375 pruebas para ganar un
punto de estilo. Se declara como el siguiente paso, no se hace ahora.

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

### 3.13 — Restauración de la bitácora al arranque
**Dueño:** Dinesh · **Estimado:** medio día

Al iniciar, si la ruta de la bitácora no existe, el servicio descarga el último snapshot
de GCS antes de atender la primera petición.

> **Criterio de aceptación:** se borra `/tmp/bitacora.db`, se reinicia el servicio, y
> `GET /auditoria/semaforo` devuelve la **misma altura y la misma raíz del día** que antes
> del reinicio, sin haber corrido el ciclo. Si no hay snapshot, arranca vacía y lo dice en
> el log — nunca falla en silencio.

### 3.14 — Respaldo consistente después de cada escritura confirmada
**Dueño:** Gilfoyle · **Estimado:** medio día

Tras cada transacción confirmada, `Connection.backup()` produce un snapshot y se sube a
GCS. La subida ocurre **fuera** del candado de escritura: un fallo de red no puede tumbar
una cesión ya confirmada.

> **Criterio de aceptación:** el objeto en GCS cambia de generación tras cada commit. Se
> mata el proceso a media subida y el snapshot anterior sigue siendo válido y restaurable
> — se prueba, no se supone. Un fallo de GCS deja el sistema degradado y alertando, nunca
> con una escritura perdida ni una petición caída.

### 3.15 — El invariante de un solo escritor, declarado como ADR
**Dueño:** Gilfoyle · **Estimado:** dos horas

`ADR 0007`: por qué el dominio del candado y el dominio de la durabilidad son distintos,
por qué `max-instances=1` es una condición de corrección y no una optimización, y qué
exactamente se rompe si alguien sube ese número creyendo que escala.

> **Criterio de aceptación:** el ADR existe y `deploy.ps1` lo referencia por número en el
> comentario de `--max-instances`. Alguien que herede el proyecto no puede subir la bandera
> sin toparse con la explicación.

### 3.16 — El semáforo distingue «vacía» de «íntegra»
**Dueño:** Gilfoyle · **Estimado:** dos horas

**Esta es la tarea que más importa de las seis y la más barata.** Una cadena de altura 0
verifica trivialmente: no hay ningún eslabón que pueda no cuadrar. Hoy, si la bitácora se
pierde, el semáforo diría **verde** sobre una cadena vacía. Verde por haberlo perdido todo
es exactamente el fallo que este producto existe para no cometer.

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
3.16  (2 h)   ← primero: es el más barato y el que arregla un fallo de honestidad
3.15  (2 h)   ← se puede escribir en paralelo, no toca código
3.13  (½ día) ← restauración
3.14  (½ día) ← respaldo   (13 y 14 son una sola pieza, pero 13 se prueba sola)
3.17  (½ día) ← la evidencia que lo demuestra
3.18  (½ día) ← si sobra tiempo antes del 28
```

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
