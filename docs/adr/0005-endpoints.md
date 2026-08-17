# ADR 0005 — Endpoints de ingesta y cesión

**Estado:** aceptado · **Fecha:** 16 de agosto de 2026 · **Tarea del plan:** 2.4

---

## 1. El reintento del mismo financiador no es fraude

Es la decisión más importante de este ADR.

Un cliente cuya petición expiró **no puede distinguir** «no llegó» de «llegó y se
perdió la respuesta». Va a reintentar — es lo correcto. Si el reintento devolviera
`409 ya cedido`, el sistema le estaría diciendo a un financiador honesto que
cometió doble cesión, por un paquete perdido.

Por eso, cuando la cesión ya existe **y es del mismo financiador**, se responde
`200` con `repetida: true` y **no se escribe nada en la bitácora**. No hay
ambigüedad en devolver éxito: si ese financiador ya tiene la cesión, pedirla otra
vez no cambia nada.

No escribir importa igual: un evento por cada paquete perdido llenaría la cadena
de ruido, y hay una prueba que fija que cinco reintentos no mueven la altura.

El `409` queda reservado para lo que de verdad es un conflicto: **otro**
financiador pidiendo un folio tomado.

## 2. Los libros inalcanzables dan `503`, nunca «sin respaldo»

Si una caída de CØRD Fiscal produjera veredictos `sin_respaldo`, el financiador
leería una falla de red como libros inconsistentes de la PYME. La ingesta falla
entera con `503` y **no escribe nada**: veredictos que no se pudieron emitir no
se inventan.

Es la misma distinción que ya hacía `ErrorDeFuente`, sostenida hasta el borde
HTTP.

## 3. Un CFDI ilegible no tumba el lote

Se reporta en `fallas` **con nombre de archivo y motivo**, y los demás se
procesan. Si un archivo corrupto abortara la ingesta, una PYME con 200
comprobantes tendría que adivinar cuál quitar.

## 4. El mismo folio dos veces en un lote se rechaza

Lo encontró correr la demo, no una prueba: el generador planta un UUID duplicado
(escenario de cesión duplicada) y la ingesta lo aceptaba sin decir nada, dejando
dos veredictos para un folio que existe una sola vez.

El mismo folio dos veces en un solo envío no es un caso legítimo: o es un error
de quien armó el lote, o es meter la misma cuenta por cobrar dos veces. Se
rechaza el segundo con motivo `uuid_duplicado_en_el_lote`.

**El mismo folio en lotes distintos sí se admite**: reauditar es legítimo porque
los libros cambian.

## 5. Ceder un folio con hallazgos se permite, pero se advierte

La respuesta de `/cesiones` lleva el `veredicto` y, cuando hay hallazgo, una
`advertencia` explícita.

Bloquear la cesión sería tomar por el financiador una decisión comercial que es
suya —hay quien financia cartera con descuento sabiendo el riesgo—. Devolver un
`201` limpio sería dejar que se entere al ir a cobrar. Se cede y se dice.

También se exige que el folio **haya sido auditado** y que el importe coincida
con el del CFDI: ceder algo nunca auditado deja al financiador con un expediente
vacío, y aceptar otro importe dejaría en la cadena una cesión que ninguna factura
respalda.

## 6. El dinero llega como cadena, nunca como número JSON

Un número JSON es un `double` de IEEE 754, y `142878.90` no es representable: el
valor más cercano es `142878.899999999994179…`. Si el importe entrara como
número, **el importe que se firma en la bitácora no sería el que mandó el
cliente**, y el hash quedaría tomado sobre un dato que nadie escribió.

Los montos se declaran `str` y se convierten a `Decimal` a mano. Un número JSON
se rechaza con `422` y un mensaje que explica por qué.

## 7. El inquilino sale de la configuración, no de un encabezado

Un despliegue ya está atado a una PYME: `CORD_FISCAL_TOKEN` es «el JWT del agente
para esa PYME». Aceptar un `X-Inquilino` de quien llama permitiría escribir en la
cadena de cualquiera cambiando una cabecera.

## 8. El estado de una cesión no dice a nombre de quién

`GET /cesiones/{uuid}` responde si está tomado, no quién lo tiene. El hecho basta
para que un financiador frene la operación; la identidad del otro es información
comercial de un tercero.

## 9. La sonda de salud no verifica la cadena

Verificar en cada sonda de Cloud Run sería recorrer la bitácora entera cada pocos
segundos. `/bitacora/verificacion` es un endpoint aparte, para quien quiere la
respuesta y está dispuesto a esperarla — y devuelve `recalculados` y `altura` por
separado, porque un registro suprimido por retención sigue enlazando pero ya no se
puede recalcular.

---

## La trampa de la demo que esto destapó

La fuente sintética por omisión **genera su propio lote** desde
`AGENTE_CFDI_SEMILLA`. Al levantar la API y subir CFDI de otra semilla, los libros
no contienen esos folios y **todo sale `sin_respaldo`** — no porque el auditor
falle, sino porque se le pregunta por facturas de otra empresa. Rompía la promesa
de «quien clona el repo obtiene una demo que funciona».

`tools/demo.py` genera el lote con la misma semilla y cantidad que usa la fuente,
de modo que libros y comprobantes hablen de lo mismo, y verifica que las
desviaciones encontradas sean **exactamente** las plantadas.

---

## Huecos declarados

- **No hay autenticación de quien llama.** En Cloud Run los endpoints quedan
  detrás de IAM, pero eso protege el perímetro y no distingue a un financiador de
  otro. Antes de datos reales hace falta autenticación por financiador.
- **`GET /auditoria/prueba/{uuid}`** (tarea 2.8) todavía no existe; el índice por
  UUID que necesita ya está construido.
