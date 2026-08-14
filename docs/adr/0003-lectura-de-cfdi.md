# ADR 0003 — Lectura de CFDI

**Estado:** aceptado · **Fecha:** 14 de agosto de 2026
**Tareas del plan:** 1.8 y 1.9

---

## Contexto

El agente recibe lotes de CFDI XML que sube una PYME. De cada comprobante
necesita seis datos —UUID, RFC del emisor, RFC del receptor, total, fecha y
moneda— para escribirlos en la bitácora encadenada.

Es la única superficie del sistema que come entrada de un tercero. Todo lo demás
—canon, hashes, Merkle, anclaje— opera sobre datos que ya pasaron por aquí. Un
lector permisivo contamina la bitácora; un lector frágil tumba el lote.

---

## Decisiones

### 1. Consciente de espacios de nombres, indiferente a los prefijos

El mismo comprobante llega como `<cfdi:Comprobante>`, como `<Comprobante>` con
el espacio por defecto, o con cualquier otro prefijo. Las tres formas son XML
válido y equivalente, y las tres existen en producción según qué PAC timbró.

El lector resuelve por espacio de nombres (`http://www.sat.gob.mx/cfd/4`), nunca
por texto. El generador sintético produce las tres variantes a propósito para que
esto quede probado y no supuesto.

### 2. Se rechaza cualquier DOCTYPE

`xml.etree.ElementTree` expande entidades internas. Diez líneas de DTD piden
gigabytes de memoria —la «bomba de mil millones de risas»— y una entidad externa
convierte al lector en un lector de archivos del servidor (XXE).

**Un CFDI nunca lleva DTD.** Rechazar la declaración de plano, en el
`TreeBuilder`, elimina las dos familias de ataque de un golpe. No hace falta
`defusedxml` ni decidir qué expansión es aceptable: ninguna lo es.

Se suma un tope de tamaño (4 MiB) que corta el archivo absurdo antes de darle
memoria, no después.

### 3. El UUID y el RFC se normalizan a mayúsculas

Parece cosmético y no lo es.

Algunos PAC timbran el UUID en minúsculas. Si entrara con el case original, el
mismo folio fiscal produciría dos hashes distintos — y entonces **la cesión
duplicada pasa de largo con solo cambiar mayúsculas**, que es precisamente el
fraude que el sistema existe para detectar. Normalizar en la puerta lo cierra.

### 4. La fecha se conserva como reloj de pared, sin zona

`Fecha` en CFDI 4.0 es hora local del lugar de expedición: no trae zona ni
fracción de segundo. No es un instante, es una declaración.

Se conserva tal cual, sin `tzinfo`. Ponerle UTC sería inventar información;
ponerle la hora de México sería adivinar mal para un emisor de Tijuana o Cancún.

**Consecuencia para la canon:** la fecha del CFDI viaja al registro como campo
de tipo `CADENA` en su forma declarada `AAAA-MM-DDThh:mm:ss`, no como `INSTANTE`.
Los campos `INSTANTE` de la bitácora se reservan para instantes que el sistema sí
observa —cuándo se escribió el registro, cuándo se ancló—, donde el reloj es
nuestro y la zona es conocida.

### 5. Se rechaza lo que no se puede representar sin perder información

Coherente con `CORD-CANON-1` (ver [ADR 0001](0001-serializacion-canonica.md)):

- Un `Total` con más decimales de los que la moneda admite es un error, no algo
  que se trunque. Truncar mete a la bitácora un importe distinto del declarado.
- Un `Total` negativo se rechaza: una nota de crédito se emite como comprobante
  de egreso, no con signo.
- Solo se admiten `MXN` y `USD`. **La escala de un importe no se puede
  adivinar** —el yen tiene cero decimales— y equivocarla corrompe el hash.
  Admitir otra moneda es agregar un renglón a la tabla, no relajar la regla.

### 6. Un CFDI 3.3 dice que es 3.3

Se detecta el espacio de nombres de la versión 3.3 y se devuelve un motivo
específico en vez de un genérico «no es CFDI». Le ahorra media hora a quien subió
el archivo equivocado.

### 7. El fallo es excepción al leer uno, y dato al leer un lote

`leer_cfdi` levanta `CFDIInvalido` —siempre con motivo tipificado y detalle—.
Nada del parser escapa como `ParseError` ni como `AttributeError`.

`leer_lote` **no** propaga: devuelve lo leído y lo rechazado por separado. Una
PYME sube 200 CFDI, uno viene truncado, y el agente tiene que procesar los 199 y
decir exactamente cuál falló y por qué. Por eso los rechazos van indexados por
origen: «uno de los 200 no sirve» no le sirve a nadie.

El motivo es un valor de enumeración, no una cadena, porque el agente decide en
función de él y no puede hacerlo leyendo prosa.

---

## Lo que este lector NO hace

**No verifica el sello del SAT.** Comprobar que un CFDI fue realmente timbrado
exige el certificado del PAC, la cadena original y la verificación de la firma.
Está fuera de alcance en esta ventana.

Conviene decirlo con precisión frente al jurado: el agente prueba que **su
bitácora** no fue alterada y que un UUID no se cedió dos veces. No prueba que el
comprobante sea auténtico ante el SAT. Son dos afirmaciones distintas, y la
segunda es un producto aparte.

**No audita la aritmética del comprobante.** Que `Total` cuadre con la suma de
conceptos e impuestos es trabajo del paso de auditoría (contra los libros en
CØRD Fiscal), no del lector. El lector lee.

---

## Consecuencias

- El agente puede procesar un lote heterogéneo sin caerse, y reportar por archivo.
- Los datos que llegan a la bitácora ya están normalizados, así que la canon no
  tiene que compensar variaciones de formato.
- Un CFDI en moneda distinta de MXN/USD se rechaza en vez de entrar mal. Es
  restrictivo a propósito y está anotado como límite conocido.
