# ADR 0004 — Bitácora encadenada y registro de cesiones

**Estado:** aceptado · **Fecha:** 15 de agosto de 2026
**Tareas del plan:** 2.1, 2.2, 2.3 (y la base de 2.6)

---

## Contexto

El producto hace dos afirmaciones distintas, y conviene no confundirlas:

1. **«Nuestra bitácora no fue alterada.»** La resuelve el encadenamiento por
   hash más el anclaje.
2. **«Esta factura no se cedió antes.»** *No* la resuelve el encadenamiento. Una
   cadena de hashes prueba que no editamos el pasado; no impide escribir dos
   cesiones del mismo folio, una tras otra, ambas perfectamente encadenadas.

La segunda es el fraude que el negocio existe para prevenir, y necesita su
propio mecanismo.

---

## Decisiones

### 1. Dos tablas: la cadena vive para siempre, el contenido caduca

| Tabla | Contenido | Retención |
|---|---|---|
| `bitacora_cadena` | posición, hash, hash anterior | indefinida |
| `bitacora_registros` | el canónico, con RFC y montos | caduca |

La cadena **no contiene datos personales**. Por eso puede ser inmutable y eterna
sin chocar con el art. 11 de la LFPDPPP, que obliga a suprimir los datos cuando
dejan de ser necesarios. El contenido vive aparte y **suprimirlo no rompe la
cadena**: los eslabones siguen enlazando, y lo único que se pierde es poder
recalcular *ese* hash.

Si el dato personal viviera dentro de la cadena, cumplir la ley de protección de
datos exigiría romper la prueba de integridad. Separar «lo que prueba» de «lo que
identifica» es lo que permite cumplir ambas.

**Consecuencia en la verificación:** `verificar()` devuelve **cuántos eslabones
se recalcularon de verdad**, no un booleano. Un auditor tiene que poder
distinguir «verifiqué 200 registros» de «verifiqué 3 y confié en 197».

### 2. La doble cesión se impide con una restricción, no con un `SELECT`

Lo natural es consultar si el UUID ya fue cedido y, si no, insertarlo. **Eso
tiene una carrera**: dos peticiones simultáneas consultan, ambas ven «libre», y
ambas escriben. No es una hipótesis de laboratorio — mandar las dos solicitudes
a la vez es exactamente lo que haría quien quiere ceder dos veces.

La garantía es una **`PRIMARY KEY` sobre el UUID**. La base no puede contener dos
cesiones del mismo folio, sin importar orden ni concurrencia. El `SELECT` previo
existe solo para dar un mensaje decente; si desapareciera, la propiedad seguiría
en pie — y hay una prueba que lo comprueba insertando por debajo de la
aplicación.

### 3. El ámbito del registro de cesiones es global, no por inquilino

La restricción es sobre el UUID a secas, no sobre `(inquilino, uuid)`. Un folio
fiscal lo emite el SAT y pertenece a un solo emisor, así que el ámbito correcto
del fraude es global: **acotarlo por inquilino lo derrotaría cualquiera que pueda
abrir dos cuentas.**

El precio es una fuga mínima: un inquilino puede descubrir que un UUID ajeno está
tomado. Por eso el rechazo dice «ya cedido» y **nunca a quién**. El hecho basta
para frenar la operación; la identidad del otro financiador no es asunto suyo.

### 4. `BEGIN IMMEDIATE` / `pg_advisory_xact_lock`: disponibilidad, no corrección

Leer la punta de la cadena y escribir el siguiente eslabón tienen que ser una
sola operación indivisible, o dos escritores leen el mismo `hash_anterior` y
bifurcan.

**El candado y la restricción hacen cosas distintas, y se necesitan los dos:**

- La **clave primaria `(inquilino, posicion)`** es la corrección. Aunque el
  candado fallara, dos eslabones no pueden ocupar la misma posición.
- El **candado** es la disponibilidad. Se midió: sin él, bajo ocho peticiones
  simultáneas, SQLite devuelve «database is locked» a la mayoría. Nadie cede dos
  veces —la restricción aguanta— pero peticiones legítimas se caen y el operador
  no sabe si su factura quedó cedida.

Está fijado en dos pruebas: una exige que las ocho reciban respuesta definitiva,
y otra corre la misma carga contra una variante sin candado para comprobar que la
primera de verdad distingue algo.

### 5. Los intentos rechazados también se escriben

Un intento de doble cesión genera un evento `cesion_rechazada` en la bitácora,
apuntando a la **posición** de la cesión previa —no a su fecha, porque una
posición se puede verificar y una fecha solo se puede creer.

Una bitácora que solo guarda lo que salió bien no sirve para investigar nada, y
el intento fallido es justo lo que un investigador va a querer ver.

### 6. Separación de dominios por prefijo de byte

| Prefijo | Qué se hashea |
|---|---|
| `0x00` | una hoja de la bitácora |
| `0x01` | un nodo interno del árbol de Merkle |
| `0x02` | el génesis de una cadena |

Sin esto se puede presentar el hash de un **nodo interno** como si fuera una hoja
y construir una prueba de Merkle válida para un registro que nunca existió. Es el
ataque de segunda preimagen sobre árboles de Merkle; la defensa estándar
(RFC 6962) es exactamente esta. Se hace **ahora**, aunque el árbol sea de la
tarea 2.6, porque agregarlo después invalidaría todo lo escrito.

### 7. El génesis depende del inquilino

`genesis(inquilino) = SHA256(0x02 ‖ "CORD-BITACORA-1" ‖ inquilino)`.

Con un génesis constante, los registros de una PYME podrían injertarse en la
cadena de otra: los eslabones encajan porque nada en el hash dice de quién es la
cadena. Atarlo al inquilino convierte ese injerto en una cadena que no verifica.

### 8. El nodo impar se promueve, no se duplica

En el árbol de Merkle, cuando un nivel tiene un número impar de nodos, el último
sube al siguiente nivel tal cual. Duplicarlo es la falla de Bitcoin
(CVE-2012-2459): dos conjuntos distintos de hojas producen la misma raíz.

---

## SQLite en las pruebas, PostgreSQL en producción

La implementación corre sobre **SQLite** para que el proyecto se levante y se
verifique en cualquier máquina sin instalar un servidor — cuenta para el criterio
de reproducibilidad, y significa que un jurado puede correr `pytest` y ver las
218 pruebas sin configurar nada.

La migración de producción está en
[`migraciones/001_bitacora.sql`](../../migraciones/001_bitacora.sql), con las
mismas restricciones más dos cosas que SQLite no tiene:

- `pg_advisory_xact_lock(hashtext(inquilino))`, que además es **por inquilino**:
  dos PYMEs escriben en paralelo sin estorbarse.
- Un *trigger* que rechaza `UPDATE` y `DELETE` sobre la cadena, de modo que el
  append-only lo imponga la base y no la disciplina de quien escribe.

**Hueco declarado:** la ruta de PostgreSQL no está ejercitada por pruebas —no hay
servidor en el entorno de desarrollo—. Las propiedades son las mismas y el SQL
está escrito, pero «escrito» no es «probado», y conviene decirlo antes de que lo
pregunten.

---

## Consecuencias

- Alterar cualquier registro rompe la verificación **en su posición exacta**, que
  es el escenario que se graba para la demo.
- Suprimir datos por retención es una operación soportada, no un problema.
- La detección de doble cesión no depende de que la aplicación se acuerde de
  consultar antes.
- El árbol de Merkle (2.6) y el anclaje (2.7) pueden construirse encima sin tocar
  nada de esto.
