# ADR 0006 — Prueba de inclusión y anclaje

**Estado:** aceptado · **Fecha:** 16 de agosto de 2026
**Tareas del plan:** 2.6 (ruta de Merkle), 2.7 (anclaje), 2.8 (endpoint de prueba)

---

## El problema que esto resuelve, y que lo anterior no resolvía

Hasta aquí el sistema probaba que **nosotros** no alteramos nuestra bitácora.
Eso es circular: la bitácora la guardamos nosotros, y quien no nos crea tampoco
tiene por qué creerle a nuestro `/bitacora/verificacion`. Con acceso a la base
podríamos reescribir el historial completo y volver a encadenarlo — saldría
íntegro.

Lo que rompe la circularidad es publicar la raíz del día **donde no mandamos**.
A partir de ahí, reescribir el pasado exige además reescribir el ancla, y esa no
es nuestra.

---

## Decisiones

### 1. Un árbol, no una lista publicada

Un financiador que quiere comprobar **su** factura recibe su registro, el camino
de hermanos hasta la raíz y el ancla. Con eso recalcula la raíz por su cuenta.

Lo que **no** recibe son los registros de las demás operaciones de la PYME: un
hermano es un hash, y de un hash no sale el RFC ni el monto de nadie. Esa es la
razón de usar un árbol en vez de publicar la lista — no es una optimización de
tamaño, es la única forma de que un tercero verifique sin ver la cartera
completa de la empresa.

De paso el tamaño también sale bien: **40 registros dan 6 hashes**, 192 bytes.

Hay una prueba que fija esta propiedad: pide la prueba de un folio y comprueba
que ningún otro UUID ni monto del lote aparezca en la respuesta.

### 2. La prueba entrega el canónico, no la hoja ya calculada

`verificar_prueba` exige el **contenido** y recalcula la hoja con el prefijo
`0x00`. Si aceptara una hoja hecha, quien presenta la prueba podría entregar el
hash de un **nodo interno** —que lleva `0x01`— y armar un camino válido para un
registro que nunca existió. Es el ataque de segunda preimagen sobre árboles de
Merkle, y la separación de dominios del ADR 0004 existía precisamente para esto.

### 3. El lado del hermano viaja con el hash

`SHA256(0x01 ‖ a ‖ b)` no es `SHA256(0x01 ‖ b ‖ a)`. Cada paso lleva
`hermano_a_la_derecha`; un verificador que adivinara el orden aceptaría pruebas
falsas la mitad de las veces.

### 4. El nodo promovido no aporta paso

Cuando el último de un nivel impar sube solo, no tiene hermano y no se registra
nada. Duplicarlo para «rellenar» el camino reintroduciría CVE-2012-2459 por la
puerta de atrás. La prueba parametrizada recorre **todos** los índices de todos
los tamaños del 1 al 33, que es donde viven los casos impares.

### 5. El ancla simulada tiene que verse simulada

Una implementación de mentira que devolviera un hash de transacción plausible
sería **peor que no tener nada**: pasaría por real en un video de demo y en una
captura de pantalla, y nadie notaría la diferencia hasta intentar buscarla en un
explorador de bloques.

Por eso:

- `AnclaSimulada` marca su red con el prefijo `simulada:`.
- `Constancia.verificable_por_terceros` es `False` mientras ese prefijo esté.
- La API propaga la bandera **y** añade una `advertencia` en texto.
- El verificador independiente sale con **código 2**, no 0, cuando el ancla es
  simulada. Todo cuadra criptográficamente, pero no se puede comprobar fuera de
  nuestro sistema, y eso no es un éxito.

Conectar una red real es sustituir una clase por otra que cumpla el mismo
protocolo. Nada más del sistema se entera.

### 6. Anclar dos veces el mismo día devuelve la constancia original

Un job diario que se reintenta no debe producir dos raíces «oficiales»: un
tercero no sabría cuál creer, y la segunda además sería distinta si entretanto
entraron registros. La clave primaria `(inquilino, dia)` lo impone.

### 7. Un registro suprimido por retención da `410 Gone`, no una prueba a medias

Sin el canónico no se puede recalcular la hoja. Entregar una prueba que el
receptor no puede verificar sería peor que no entregar ninguna. La cadena sigue
íntegra —el eslabón no se fue— y el `410` dice exactamente qué pasó.

### 8. El verificador no importa una línea de este proyecto

[`tools/verificar_prueba.py`](../../tools/verificar_prueba.py) usa solo
`hashlib`, `json` y `base64`. Si la verificación usara nuestro código,
comprobaría que nuestro código coincide consigo mismo — que no demuestra nada.
Son treinta líneas: un financiador puede reimplementarlas desde la
especificación y llegar al mismo resultado.

Dos pruebas lo ejercitan como subproceso: una comprueba que acepta lo que la API
produce, otra que **rechaza** una prueba con el canónico manipulado.

---

## Estado real del anclaje

**El anclaje en una cadena pública no está hecho.** Lo que está hecho es todo lo
que lo rodea: el árbol, la ruta, el endpoint, la constancia, la idempotencia del
job, el verificador y la bandera que distingue lo simulado de lo real.

Conectar una red exige decidir cuál, financiar el gas y manejar una llave —
riesgos que no son de código. Al dejarlo detrás de un protocolo, ese trabajo no
bloquea nada más y el día que se conecte, `verificable_por_terceros` pasa a
`true` sin tocar el resto.

**Mientras tanto el sistema no debe presentarse como verificable por terceros**,
y por eso la bandera y la advertencia viajan en cada respuesta en lugar de vivir
en una nota al pie.
