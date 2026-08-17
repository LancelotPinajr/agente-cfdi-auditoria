# Contrato de datos del expediente de cesión

**Tarea del plan:** 1.12 · **Fecha:** 14 de agosto de 2026
**Marco:** LFPDPPP (arts. 6, 8, 11, 16) y CFF art. 30

Qué datos salen del sistema, hacia quién, y —sobre todo— **qué no sale**.

---

## 1. Dos artefactos, dos audiencias, dos contratos

Es la decisión que sostiene todo lo demás. El sistema produce **dos** cosas
distintas y la tentación de fundirlas en una sola respuesta es exactamente el
error que hay que evitar.

| | **Expediente de cesión** | **Prueba de integridad** |
|---|---|---|
| Para quién | un financiador **identificado**, en una operación concreta | **cualquiera**, sin pedirnos nada |
| Endpoint | `POST /cesiones` → dossier | `GET /auditoria/prueba/{uuid}` |
| Contiene datos personales | sí, los mínimos | **no, ninguno** |
| Base de legitimación | consentimiento expreso del contribuyente (art. 8) | no aplica: no hay datos personales |

La prueba de integridad es pública porque **no lleva un solo dato personal**:
hashes, una ruta de Merkle, una raíz y un hash de transacción. Un tercero
verifica que un registro existía en un momento dado sin enterarse de quién
facturó a quién ni por cuánto.

Ese es el punto del anclaje. Si la prueba pública llevara el RFC, habríamos
publicado la cartera de una PYME en una cadena de bloques para siempre.

---

## 2. El expediente de cesión

### 2.1 Campos que sí viajan

| Campo | Por qué es indispensable |
|---|---|
| `uuid` | Identifica el activo que se cede. Sin él no hay operación ni detección de doble cesión. |
| `rfc_emisor` | La PYME es parte del contrato de cesión. |
| `nombre_emisor` | El contrato se firma con una razón social, no con un RFC. |
| `rfc_receptor` | **El financiador compra el riesgo de este deudor.** Es el dato que determina el precio; omitirlo haría inútil el expediente. |
| `nombre_receptor` | Para notificar la cesión al deudor, que es requisito para oponerla frente a él. |
| `total` y `moneda` | El monto de la cuenta por cobrar. |
| `fecha_emision` | Arranca el cómputo del plazo. |
| `dias_credito` y `fecha_vencimiento` | Cuándo se cobra: es la variable de descuento. |
| `serie` y `folio` | Para conciliar con el deudor, que ya tiene ese folio en su contabilidad. |
| `resultado_de_auditoria` | Veredicto, no evidencia: `respaldado` / `sin_respaldo` / `monto_distinto`. |
| `estado_de_cesion` | `disponible` o `ya_cedido`, con la fecha de la cesión previa si la hay. |
| `hash_del_registro`, `posicion` | Para amarrar el expediente a la bitácora. |
| `fuente_de_libros` | Si se auditó contra CØRD Fiscal o contra una demo sintética. **El financiador tiene derecho a saberlo.** |

### 2.2 Campos que NO viajan, y por qué

Esta tabla es la tarea 1.12. Cada renglón es una decisión, no un olvido.

| Campo omitido | Está disponible | Por qué se omite |
|---|---|---|
| **Descripción de los conceptos** | sí, en el CFDI | Revela **qué** le vende la PYME a quién. Es su ventaja competitiva y no cambia en nada el precio de una cuenta por cobrar. El caso más claro de minimización del art. 6. |
| **Domicilio fiscal (CP) de ambas partes** | sí | Localiza a las partes. No interviene en la decisión de compra. |
| **Régimen fiscal del receptor** | sí | Es asunto del receptor con el SAT, no del financiador. |
| **El XML completo del CFDI** | sí | Llevaría de un golpe todo lo anterior más el sello y el certificado. Viaja su hash, que prueba lo mismo sin revelar nada. |
| **Sello, certificado, `NoCertificado`** | sí | Material criptográfico del emisor. No aporta al expediente y amplía la superficie. |
| **El resto de los movimientos contables** | sí, vía CØRD Fiscal | El financiador necesita el **veredicto** de la auditoría, no la contabilidad completa de la PYME. Entregar los libros sería la desproporción más grande posible. |
| **Los demás clientes de la PYME** | sí | Su cartera de clientes es información comercial sensible y no tiene relación con esta cesión. |
| **Datos de otros CFDI del mismo lote** | sí | Cada expediente cubre **una** cesión. |
| **`datos_originales`, `categoria`, `problemas`** de los movimientos | sí, en CØRD Fiscal | **Ni siquiera cruzan la frontera del agente.** Ver §3. |
| **IVA desglosado** | sí | El financiador compra el total exigible. El desglose es información fiscal del emisor. |

### 2.3 «Un RFC no viaja si no hace falta»

El criterio del plan, aplicado literalmente:

- En la **prueba de integridad pública**: no viaja ningún RFC. Ninguno.
- En el **expediente**: viajan dos RFC —emisor y receptor— y ninguno más. En
  particular **no viaja el RFC de los demás clientes** de la PYME, aunque el
  agente los tenga a la mano por haber leído el lote completo.
- En los **logs**: no se registra ningún RFC. Un log rota a un sistema de
  observabilidad con otro control de acceso y otro periodo de retención; meter
  ahí un dato patrimonial es filtrarlo por la puerta de atrás.

---

## 3. La minimización ocurre en la petición, no en el filtro

Un detalle de implementación que es en realidad una decisión de cumplimiento.

`fuentes/cord_fiscal.py` traduce cada renglón de CØRD Fiscal a un `Movimiento`
del dominio y **descarta ahí mismo** `datos_originales` (el renglón crudo del
Excel de la PYME), `categoria`, `problemas` y `proyecto`.

No se guardan «por si acaso» para filtrarlos al armar el expediente. **Lo que no
cruza la frontera no se puede filtrar mal después, ni aparecer en un volcado de
memoria, ni quedarse en una caché.** Es la diferencia entre minimizar de verdad
y prometerlo en un párrafo del aviso de privacidad.

---

## 4. ¿Es un hash un dato personal?

Un jurado técnico va a preguntarlo, y la respuesta cómoda —«no, es un hash»— es
falsa en general.

Un hash es **seudonimización**, no anonimización, si el conjunto de preimágenes
posibles es pequeño: quien conozca la estructura del registro puede probar
candidatos hasta acertar. Hashear un RFC solo, por ejemplo, es reversible en
segundos: hay pocos RFC posibles.

**Por qué aquí no lo es.** El preimagen de cada hoja es el registro canónico
completo, que incluye el **UUID del CFDI: 122 bits de entropía** que el atacante
no puede adivinar ni enumerar. Sin el UUID no hay ataque de diccionario posible,
y con el UUID ya se tenía el dato de todos modos.

**Consecuencia operativa:** el UUID **nunca** se publica junto a la hoja en la
prueba pública. Quien pide `GET /auditoria/prueba/{uuid}` ya conoce ese UUID —lo
trae en la petición— y no obtiene nada nuevo. Publicar un índice de UUID a
hashes destruiría la propiedad. Queda escrito para que a nadie se le ocurra
exponer ese índice «para facilitar la verificación».

---

## 5. Retención

Dos obligaciones que apuntan en direcciones opuestas y hay que resolver, no
ignorar.

| Norma | Qué exige |
|---|---|
| **CFF art. 30** | Conservar la contabilidad y los comprobantes **5 años**. |
| **LFPDPPP art. 11** | Suprimir los datos personales cuando dejen de ser necesarios para la finalidad. |

**Cómo se resuelve:**

- La obligación del CFF recae en el **contribuyente** sobre **sus propios**
  comprobantes, y se cumple en CØRD Fiscal, que es donde vive su contabilidad.
  Este agente no es el custodio fiscal de nadie.
- La **bitácora encadenada** conserva hashes, no datos personales, y es
  **inmutable por diseño**: borrar una fila rompe la cadena. Por eso no puede
  contener datos personales — y no los contiene. La cadena vive indefinidamente
  porque un hash sin preimagen no es un dato personal.
- El **expediente** sí lleva datos personales y por lo tanto **sí caduca**: se
  conserva mientras dure la relación con el financiador más el plazo de
  prescripción de la acción mercantil, y luego se suprime. Suprimirlo no toca la
  cadena, porque la cadena solo guarda su hash.

Separar «lo que prueba» de «lo que identifica» es lo que permite cumplir las dos
normas a la vez. Si el dato personal viviera dentro de la cadena, cumplir la
LFPDPPP exigiría romper la prueba de integridad.

---

## 6. Pendientes declarados

- **Aviso de privacidad específico.** El de CØRD cubre la plataforma. La cesión
  a un tercero es una **transferencia** (art. 36) y necesita su propia cláusula.
  Fuera de la ventana del hackathon; anotado para no darlo por hecho.
- **Derechos ARCO sobre el expediente.** El procedimiento de acceso y
  cancelación no está implementado. Con datos sintéticos no hay titular que los
  ejerza; con datos reales es requisito previo, no posterior.
- **Notificación de la cesión al deudor.** Es requisito mercantil para oponer la
  cesión frente a él, y está fuera de alcance: el sistema arma el expediente, la
  operación la hace el financiador.
