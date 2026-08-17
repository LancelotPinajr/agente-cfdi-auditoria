# Datos sintéticos: por qué, cómo, y qué no garantizan

**Tareas:** 1.14, 1.15, 1.16, 1.17 · **Fecha:** 14 de agosto de 2026

La demo corre con CFDI sintéticos. Este documento explica la decisión, la
propiedad de seguridad que hace publicables estos datos, y los huecos que quedan
—porque un jurado técnico va a buscar exactamente esos.

---

## 1. Por qué sintéticos

No es una concesión por falta de datos. Es la decisión correcta por tres razones
independientes:

**Reproducibilidad.** El criterio 3.3 pide que alguien ajeno levante el proyecto
siguiendo el README. Eso es imposible si la demo necesita facturas reales de una
PYME. Con el generador en el repo, cualquiera reproduce el lote completo —
`generar_lote(semilla=20260814)` da el mismo lote byte por byte en cualquier
máquina. La reproducibilidad es parte del 30% de *production readiness*.

**El escenario de manipulación se graba entero.** La tarea 3.12 —alterar un
monto y enseñar el semáforo en rojo— se muestra sin difuminar nada.

**Coherencia con nuestro propio aviso de privacidad.** Un CFDI real lleva RFC,
razón social, montos y plazos de cobro: datos patrimoniales identificables bajo
la LFPDPPP. Publicarlos en un video de YouTube exige consentimiento expreso
(art. 8). Decir en el video «usamos datos sintéticos porque nuestro propio aviso
de privacidad lo exige» no es una excusa: es la demostración de la disciplina
que evalúa la categoría *Fortified Enterprise*.

---

## 2. RFC que no pueden ser de nadie (tarea 1.15)

Este es el punto que más fácil se hace mal.

**Un RFC aleatorio es el RFC de alguien.** `MELM850612QW3` no es una cadena
inventada: es un contribuyente con nombre, domicilio y obligaciones fiscales.
Generarlo al azar y publicarlo junto a montos y plazos de cobro es difundir un
dato patrimonial de un tercero que nunca lo consintió — y hacerlo por accidente
no cambia nada.

### La propiedad

Todos los RFC generados llevan **`000000` en la porción de fecha**.

```
QZU 000000 D18
 │     │     └── homoclave y dígito verificador
 │     └──────── la fecha imposible
 └────────────── letras de la razón social
```

Por qué esto funciona, y por qué nada más lo hace:

- **El SAT no puede haberlo asignado.** El RFC codifica la fecha de constitución
  de la persona moral o de nacimiento de la física. No existe el día cero del mes
  cero. Ningún contribuyente tiene ni tendrá jamás un RFC con esa porción.
- **El esquema de CFDI 4.0 lo acepta.** El patrón `tdCFDI:t_RFC` es
  `[A-ZÑ&]{3,4}[0-9]{2}[0-1][0-9][0-3][0-9][A-Z0-9]{2}[0-9A]`: solo verifica
  clases de caracteres. `[0-1][0-9]` acepta `00` y `[0-3][0-9]` también. El XML
  valida.
- **Es verificable en un renglón.** `es_sintetico(rfc)` no depende de mantener
  una lista negra ni de consultar nada.

### Lo que se descartó

| Alternativa | Por qué no |
|---|---|
| RFC totalmente aleatorios | Es exactamente el problema: cualquier RFC bien formado puede estar asignado. |
| Un prefijo de letras «raro» (`ZZZ`, `XXX`) | Ninguna terna de letras está reservada. `ZZZ` puede tocarle a una empresa real, y `XXX` colisiona con la familia de genéricos del SAT. |
| Solo el genérico `XAXX010101000` | Es seguro pero es **uno solo**. Con todos los emisores y receptores iguales, el lote no distingue PYMEs ni clientes y la demo no muestra nada. |
| Homoclave inválida | La homoclave no se puede verificar sin el algoritmo del SAT, así que no es una marca comprobable. |

Los genéricos reservados **sí** se usan donde corresponde: `XAXX010101000`
(público en general) y `XEXX010101000` (residente en el extranjero) están en el
módulo y `es_sintetico` los reconoce como seguros, porque son públicos por
diseño.

### La marca se verifica al generar, no solo al probar

`rfc.py` comprueba la propiedad **dentro de la función que construye el RFC** y
levanta `RFCInseguro` si no se cumple. Un cambio descuidado en la construcción no
puede producir un RFC atribuible en silencio; falla en el acto.

---

## 3. Realismo (tarea 1.16)

Un lote que se ve falso a simple vista destruye la credibilidad de la demo aunque
el sistema esté impecable. Lo que se cuida:

| Propiedad | Cómo |
|---|---|
| Montos con cola larga | Distribución lognormal alrededor del monto típico del giro. Una uniforme se detecta de inmediato. |
| Plazos de cobro reales | 30 días (40%), 45 (20%), 60 (28%), 90 (12%) — el reparto del factoraje de PYME. |
| Coherencia giro/producto | `c_ClaveProdServ` y `c_ClaveUnidad` salen del giro del emisor. Una constructora no factura consultoría por pieza. |
| Cartera, no desconocidos | Un emisor y 3–5 clientes recurrentes, no una factura por cliente nuevo. |
| Fechas dispersas | Ventana de ~75 días, no todo el mismo día. |
| `PPD` con `FormaPago 99` | Regla del SAT para venta a crédito. Es justo el comprobante que se factoriza; equivocarlo delata que nadie leyó el Anexo 20. |
| Aritmética que cuadra | `Importe = Cantidad × ValorUnitario`, `SubTotal = Σ Importe`, `Total = SubTotal + IVA`. Se construye de abajo hacia arriba para que no haya que reconciliar redondeos. |

### El fraude plantado

`generar_lote(con_cesion_duplicada=True)` mete el mismo UUID dos veces en el
lote, **con otra forma de XML**. Es lo que pasa en la realidad cuando la segunda
cesión entra por otro canal, y sirve de prueba negativa: si la detección
comparara los bytes del archivo en vez del UUID timbrado, esto se le escaparía.

En el Sprint 2, con el registro de cesiones, la detección cruzará también lotes
y días distintos. El plante intra-lote es lo que se puede probar sin bitácora.

---

## 4. Variantes estructurales de XML

El mismo comprobante se serializa de tres formas:

| Variante | Qué cambia | Qué rompe |
|---|---|---|
| `PREFIJO_ESTANDAR` | `<cfdi:Comprobante>`, todo declarado en la raíz | nada — es lo común |
| `SIN_PREFIJO` | CFDI como espacio de nombres por defecto | un lector que busque la cadena `"cfdi:Emisor"` |
| `PREFIJO_ALTERNO` | prefijo `c:`, el timbre declara su espacio en el hijo, y hay una `Addenda` con elementos ajenos | un lector que asuma prefijos fijos o que se atragante con lo que no conoce |

Las tres son XML válido y equivalente para un procesador consciente de espacios
de nombres, y las tres llegan en producción. Es lo que satisface «al menos 3 XML
de estructura distinta» del criterio 1.8 con variedad que de verdad ejercita al
lector, en vez de tres archivos que solo cambian de monto.

---

## 5. Huecos conocidos

Dicho aquí para que nadie lo descubra en la sesión de preguntas.

**No hay firma criptográfica.** `Sello`, `Certificado`, `SelloCFD` y `SelloSAT`
son relleno con la forma y longitud correctas, sin validez alguna. Timbrar exige
el certificado de un PAC. **Validez estructural no es validez fiscal**, y el
sistema nunca debe presentar un comprobante sintético como timbrado.

Consecuencia de diseño para el lector: verificar el sello del SAT está **fuera de
alcance** en esta ventana. El agente prueba que *su bitácora* no fue alterada, no
que el CFDI fue timbrado. Son dos afirmaciones distintas y conviene no
confundirlas frente al jurado.

**No se corre validación XSD real.** Las pruebas verifican las propiedades
estructurales del esquema —patrones, atributos obligatorios de 4.0, catálogos,
aritmética— pero no ejecutan una validación contra el `.xsd` publicado por el
SAT, que exigiría `lxml` y descargar el esquema. Es el hueco más grande de esta
pieza; se cierra agregando `lxml` y el esquema al repo si sobra tiempo en el
Sprint 3.

**Los catálogos son subconjuntos.** Solo lo que el escenario de factoraje
necesita, no el Anexo 20 completo. Los valores incluidos son reales.

**Las razones sociales son ficticias pero no verificadas.** Una razón social
inventada podría coincidir con una empresa real. El riesgo es mucho menor que
con el RFC —el nombre no identifica fiscalmente y no hay dato patrimonial
atribuible sin RFC—, pero no es cero y queda anotado.

---

## 6. La puerta para datos reales (tarea 1.17)

La fuente de datos es una interfaz con dos implementaciones. Cambiar de la
sintética a la real es configuración, no reescritura.

**Eso no significa que el cambio sea voltear una bandera.** Antes se exige:

1. **Consentimiento expreso** del contribuyente (LFPDPPP art. 8 — se trata de
   datos patrimoniales, no basta el consentimiento tácito).
2. **Minimización** en el expediente según el
   [contrato del expediente](contrato-expediente.md): un RFC no viaja si no hace
   falta.
3. **Retención** conforme al CFF art. 30.

Queda escrito aquí para que nadie lo tome por un paso trivial más adelante.
