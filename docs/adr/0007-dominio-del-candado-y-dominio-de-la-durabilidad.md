# ADR 0007 — El dominio del candado no es el dominio de la durabilidad

**Estado:** aceptado · **Fecha:** 24 de agosto de 2026
**Tareas del plan:** 3.13 a 3.17 · **Sucede a:** [ADR 0004](0004-bitacora-encadenada.md) §4

---

## El problema

La bitácora vive en un SQLite en `/tmp` de Cloud Run. Cada reciclado de la
instancia la borra. El 21 de agosto ya se perdió así la constancia de un cierre:
del anclaje de aquel día solo quedó la línea de acceso de uvicorn, un `200` que
no dice qué ancló.

El rubro de calificación dice literalmente *manejo de estado*, y el plan de equipo
nunca escribió una tarea para cubrirlo. No es una tarea abierta: es una tarea que
faltaba.

## El diagnóstico, que no es el que parece

El primer impulso es decir «el problema es SQLite» o «el problema es
`--max-instances=1`». Ninguno de los dos es el problema.

**El candado está bien.** `--max-instances=1` en [`deploy.ps1`](../../deploy.ps1)
no es una optimización de costo: es el invariante de **un solo escritor**. Con
dos instancias vivas, cada una escribiría contra su propio archivo en su propio
`/tmp` y la punta de la cadena se bifurcaría. Dentro de esa instancia,
`BEGIN IMMEDIATE` serializa las escrituras, y la clave primaria
`(inquilino, posicion)` sostiene la corrección aunque el candado fallara — eso es
el ADR 0004 §4 y sigue siendo cierto.

El error de diseño fue **haber confundido dos dominios que no coinciden**:

```
dominio del candado       →  dentro de una instancia   →  RESUELTO
                             (max-instances=1 + BEGIN IMMEDIATE + PK)

dominio de la durabilidad →  fuera de la instancia     →  NO RESUELTO
                             (nada sobrevive al reciclado)
```

Un candado responde *«¿quién puede escribir ahora?»*. La durabilidad responde
*«¿qué sobrevive a que este proceso desaparezca?»*. Son preguntas distintas y
hasta hoy el proyecto solo tenía respuesta para la primera.

---

## Decisiones

### 1. `--max-instances=1` es una condición de corrección, no una bandera de costo

Queda declarado aquí para que nadie lo suba creyendo que escala. **Subirlo a 2
bifurca la cadena en silencio:** dos instancias, dos archivos, dos puntas
distintas avanzando en paralelo. Ninguna de las dos daría error. Las dos
verificarían. Y al cierre del día se anclaría una raíz que solo cubre la mitad de
los registros, sin que nada avise.

Es el peor tipo de fallo que puede tener este producto: uno que produce evidencia
de aspecto correcto.

`deploy.ps1` referencia este ADR por número en el comentario de la bandera. Quien
herede el proyecto no puede tocarla sin toparse con la explicación.

### 2. La durabilidad se resuelve fuera de la instancia, y por eso no toca el candado

Snapshot del archivo a GCS con `sqlite3.Connection.backup()` —biblioteca
estándar, consistente, sin detener escrituras— y restauración al arranque. Tareas
3.13 y 3.14.

La subida ocurre **fuera** del candado de escritura: un fallo de red no puede
tumbar una cesión ya confirmada. Un fallo de GCS deja el sistema degradado y
alertando, nunca con una escritura perdida.

Esto funciona **porque** hay un solo escritor. La decisión 1 no es un requisito
previo incómodo de la decisión 2: es lo que la hace segura. Con dos escritores,
dos snapshots se pisarían y el último en subir ganaría, perdiendo los registros
del otro.

### 3. Lo descartado, y por qué

**Volumen de GCS montado (FUSE) con el archivo SQLite encima.** GCS FUSE no
implementa el bloqueo de archivos de POSIX que SQLite necesita para coordinar
escrituras. Bajo escritura concurrente corrompe la base. Es peor que el problema
que resuelve, y se descarta explícitamente porque es la primera idea que se le
ocurre a cualquiera que lea «SQLite» y «GCS» en la misma frase.

**Cloud SQL (PostgreSQL) ahora.** Es la respuesta correcta a mediano plazo y hay
que ser preciso sobre cuánto falta, porque desde ADR 0004 el proyecto se acercó
más de lo que parece:

- La migración **ya está escrita**:
  [`migraciones/001_bitacora.sql`](../../migraciones/001_bitacora.sql), con
  `pg_advisory_xact_lock(hashtext(inquilino))` —que además es por inquilino, o
  sea que sí escala horizontalmente— y triggers que rechazan `UPDATE` y `DELETE`
  sobre la cadena.
- Lo que falta es la capa de Python: **16 puntos de acoplamiento a `sqlite3`**
  repartidos en dos archivos (`almacen.py` y `api/dependencias.py`), y son cuatro
  clases de costura: `connect`, `Row`, `IntegrityError` y `BEGIN IMMEDIATE`.

Cuatro costuras es poco. Pero la ruta de PostgreSQL **no está ejercitada por
pruebas** —el hueco ya venía declarado en ADR 0004— y ejercitarla exige levantar
un servidor en CI. A cuatro días de la congelación del 28, eso es abrir un frente
nuevo para ganar un punto de estilo sobre un problema que el snapshot ya resuelve.

**Se difiere, no se descarta.** Es el primer trabajo después del hackathon, y el
día que se haga, la decisión 1 se puede revertir: `pg_advisory_xact_lock` es por
inquilino, así que el invariante de un solo escritor deja de ser necesario.

### 4. Una cadena vacía no se reporta como íntegra

Tarea 3.16, ya implementada. Consecuencia directa de este ADR: si la durabilidad
puede fallar, el sistema tiene que saber decir que falló.

Una cadena de altura 0 verifica trivialmente —no hay eslabón que pueda no
cuadrar— y hasta hoy salía en ámbar «ÍNTEGRA, SIN PUBLICAR». **Afirmar integridad
justo después de haberlo perdido todo es el fallo exacto que este producto existe
para no cometer.** Se agregó el color `gris` / «SIN CADENA QUE VERIFICAR».

---

## Lo que este ADR no resuelve

Se declara para no prometer de más:

- **No hay escalamiento horizontal.** Sigue siendo una instancia. El dato
  sobrevive; la concurrencia entre instancias no. La solución es la decisión 3
  diferida, no este ADR.
- **La pérdida entre el último snapshot y el reciclado se pierde.** El respaldo
  es después de cada escritura confirmada, así que la ventana es de milisegundos,
  pero no es cero y no se va a fingir que lo es.
- **La ruta de PostgreSQL sigue sin pruebas.** Igual que en ADR 0004. «Escrito»
  no es «probado», y conviene decirlo antes de que lo pregunten.

## Consecuencias

- El invariante que sostiene la corrección de la cadena deja de vivir en un
  comentario de un script de despliegue y pasa a ser una decisión con nombre.
- La debilidad más citada del proyecto —«se pierde en cada despliegue»— deja de
  ser una disculpa en el README y pasa a ser una propiedad medida: qué se pierde,
  en qué ventana, y qué se hace al respecto.
- La tarea 3.17 puede demostrarlo en vivo: se despliega una revisión nueva, `/tmp`
  se borra, y la cadena sigue en la misma altura con la prueba de Merkle validando
  contra la raíz que está en Base Sepolia.
