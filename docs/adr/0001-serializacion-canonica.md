# ADR 0001 — Serialización canónica `CORD-CANON-1`

**Estado:** aceptado · **Fecha:** 14 de agosto de 2026
**Tarea del plan:** 1.10 · **Congelación:** cierre del Sprint 1 (17-ago)

---

## Contexto

La bitácora encadena registros con `hash_n = SHA256(canónico_n ‖ hash_{n-1})`.
El hash no se calcula sobre lo que devuelva el ORM ni sobre un `json.dumps`: se
calcula sobre una representación **canónica** — una función total y determinista
que lleva un registro lógico a una única cadena de bytes.

Sin esto, la verificación falla por razones que no tienen nada que ver con
manipulación: el diccionario vino en otro orden, el driver devolvió `100.5` donde
antes había `100.50`, el nombre del emisor llegó con la `é` descompuesta en dos
puntos de código. Un auditor vería «cadena rota» y no habría nadie que la rompiera.

Y hay una razón más dura: **esta función no se puede cambiar después.** Si la
canonicalización cambia cuando ya hay registros escritos, todos los hashes previos
dejan de verificar y la bitácora entera queda inservible. De ahí la congelación y
de ahí el número de versión en el prefijo.

## Decisión

Se adopta `CORD-CANON-1`: codificación **binaria, con prefijo de longitud y
etiqueta de tipo**, contra un esquema declarado.

### Formato

```
CORD-CANON-1 ‖ netstring(nombre_del_esquema) ‖ campo₁ ‖ campo₂ ‖ … ‖ campoₙ
```

donde, para cada campo del esquema **en el orden declarado**:

```
campoᵢ = netstring(nombre_utf8) ‖ netstring(etiqueta_de_tipo ‖ valor_utf8)
netstring(b) = decimal(len(b)) ‖ ":" ‖ b
```

Ejemplo (esquema `demo`, un campo `total` con valor decimal `100.5` y escala 2):

```
CORD-CANON-15:demo5:total7:d100.50
```

### Etiquetas de tipo

| Etiqueta | Tipo | Representación |
|---|---|---|
| `s` | cadena | UTF-8, normalizado a Unicode **NFC** |
| `d` | decimal | escala fija declarada por campo, notación posicional, sin signo en el cero |
| `i` | entero | decimal, sin ceros a la izquierda |
| `b` | booleano | `1` / `0` |
| `t` | instante | ISO-8601 UTC, precisión de segundo, sufijo `Z` |
| `n` | nulo | carga vacía |

---

## Por qué así, y no de la otra forma

### Prefijo de longitud en vez de separador

Lo natural es unir los campos con `|` o `\x1e`. Es una vulnerabilidad.

Con separador, el registro `{"rfc": "AAA010101AAA|999999.00", "total": "1.00"}`
y el registro `{"rfc": "AAA010101AAA", "total": "999999.00|1.00"}` **producen la
misma cadena** y por lo tanto el mismo hash. Quien controle el contenido de un
campo de texto puede fabricar dos registros distintos con la misma huella. En una
bitácora cuyo único propósito es demostrar que nadie alteró nada, eso es fatal.

Escapar el separador lo arregla, pero convierte la función en algo con casos
borde. El prefijo de longitud lo hace imposible por construcción: la codificación
es inyectiva sin excepciones y no hay nada que escapar.

### Etiqueta de tipo

Sin etiqueta, la cadena `"100.50"` y el decimal `100.50` colisionan. Y algo más
sutil: un campo opcional ausente colisiona con el mismo campo presente y vacío
— `None` y `""` tienen que ser distinguibles, porque «no declaró moneda» y
«declaró moneda vacía» no son el mismo hecho.

### Decimales: se rechaza, no se redondea

Si un valor trae más precisión que la escala declarada (`100.505` en un campo de
escala 2), la función **levanta un error**. No redondea.

Redondear en silencio significa que dos importes distintos entran a la bitácora
con el mismo hash. En un sistema de factoraje, esa diferencia son centavos que
alguien cobra. La función se niega y el problema se resuelve donde nació — en el
lector o en la fuente de datos —, no debajo de la alfombra criptográfica.

Por la misma razón se **rechaza `float`**. `0.1 + 0.2` no es `0.3` y ningún
prefijo de longitud arregla eso. Los montos entran como `Decimal`, `int` o `str`.

### Instantes: se rechaza lo ambiguo

Un `datetime` sin zona horaria se rechaza — no se asume UTC ni la hora local del
servidor, porque el mismo registro daría hashes distintos según dónde corra el
proceso. La precisión es de segundo, que es la de `Fecha` en CFDI 4.0; una
fracción de segundo distinta de cero también se rechaza en vez de truncarse, por
el mismo argumento que los decimales.

### NFC

`"Peñón"` puede llegar con `ñ` como un punto de código o como `n` + tilde
combinante. Son la misma cadena para un humano y bytes distintos para SHA-256.
Se normaliza a NFC, que es lo que produce cualquier fuente mexicana sensata y lo
que recomienda el W3C para intercambio.

### Esquema estricto

Un campo que llega y no está declarado es un error, no un campo que se ignora.
Ignorarlo significa que un dato entró al sistema sin quedar bajo la protección
del hash — exactamente el hueco por el que alguien mete algo que después niega.

### El prefijo de versión

`CORD-CANON-1` va en los bytes que se hashean. Si algún día hace falta una
canon 2, los registros viejos siguen verificando con su propia regla y no hay
forma de confundir uno con otro. Cambiar la canon **no** es editar esta función:
es escribir `CORD-CANON-2` y dejar la 1 intacta para siempre.

---

## Consecuencias

- **A favor:** codificación inyectiva demostrable, independiente del lenguaje.
  Un tercero puede reimplementarla desde este documento y llegar a los mismos
  bytes — que es justo lo que la tarea 2.8 le exige a un financiador.
- **A favor:** los errores salen en el momento de escribir, no el día de la
  auditoría.
- **En contra:** más estricta que un `json.dumps` ordenado. Cada tipo de registro
  necesita su esquema declarado y los datos sucios se rechazan en la puerta.
  Es el costo, y es el punto.
- **Irreversible:** al cerrar el Sprint 1 esta función no se toca.

## Alternativas descartadas

| Alternativa | Por qué no |
|---|---|
| `json.dumps(sort_keys=True)` | No fija escala de decimales, no distingue tipos, y la representación de `float` depende de la implementación. |
| JCS (RFC 8785) | Resuelve el orden y el escape, pero hereda los números de JSON: `100.5` y `100.50` son el mismo número y no hay forma de fijar escala. |
| Protobuf / CBOR canónico | Formatos serios, pero atan la verificación a una librería. Un auditor tendría que confiar en un decodificador; aquí puede leer los bytes con la vista. |
| Firmar el XML original del CFDI | El registro de la bitácora incluye datos que no están en el CFDI (posición, resultado de auditoría, tenant). |
