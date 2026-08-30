# Manual de usuario — Agente CFDI

Esta guía explica **cómo usar** el sistema hoy: qué puedes hacer contra el
servicio ya publicado en internet, y cómo levantar el escenario completo de
auditoría en tu propia máquina para probar todo lo demás. No explica cómo está
construido por dentro — para eso está el
[manual técnico](manual-tecnico.md).

---

## 1. Antes de empezar: qué está disponible y qué no

| Quiero... | ¿Puedo hacerlo hoy contra internet? | ¿Cómo? |
|---|---|---|
| Hablar con el agente | ✅ Sí | §2, contra la URL pública |
| Subir CFDI y auditarlos | ✅ Sí | §3 |
| Ceder una factura a un financiador | ✅ Sí | §3 |
| Verificar que un folio no fue duplicado | ✅ Sí | §3 |
| Confirmar una prueba de integridad sin confiar en nosotros | ✅ Sí | §3, paso 6 |

Hasta el 17 de agosto de 2026 el servicio publicado era **solo un chat** y el
auditor había que levantarlo en tu máquina. Ya no: el motor de auditoría está
desplegado y cuelga de `/auditoria`.

### Dos advertencias antes de que lo pruebes

**La bitácora pública es una demo compartida y abierta.** Cualquiera en internet
puede escribir en ella. Lo que subas ahí lo ve quien pregunte, y lo que veas
puede haberlo puesto alguien más. **No subas CFDI reales.**

**Se borra sola.** La cadena vive en el disco temporal del servidor: cada vez que
se publica una versión nueva, vuelve a empezar en altura 0. Si necesitas que tus
pruebas persistan o estar seguro de que nadie más las toca, levántalo en tu
máquina — §3, opción B.

---

## 2. Hablar con el agente publicado

No necesitas instalar nada. El servicio está abierto:

**URL:** `https://agente-cfdi-run-xsxcmt7edq-uc.a.run.app`

### Comprobar que está vivo

```bash
curl https://agente-cfdi-run-xsxcmt7edq-uc.a.run.app/
```

Debe responder algo como:

```json
{"status": "ok", "service": "agente-cfdi", "framework": "google-adk", "model": "gemini-3.5-flash"}
```

### Enviar un mensaje

```bash
curl -X POST https://agente-cfdi-run-xsxcmt7edq-uc.a.run.app/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "hola, ¿qué haces?"}'
```

La respuesta trae tu mensaje contestado, un `session_id` y el modelo usado:

```json
{"reply": "...", "session_id": "3f2a...", "model": "gemini-3.5-flash"}
```

### Mantener una conversación

Reutiliza el `session_id` que te devolvió la primera respuesta para que el
agente recuerde lo que ya hablaron:

```bash
curl -X POST https://agente-cfdi-run-xsxcmt7edq-uc.a.run.app/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "¿y qué es un CFDI?", "session_id": "3f2a..."}'
```

### Qué esperar y qué no

- Responde en español, sin adornos.
- **No inventa** UUID, RFC, montos ni fechas: si no tiene el dato, lo dice.
- No da opinión financiera ni recomienda operar.
- **Hoy no puede consultar la bitácora ni verificar un folio real** — todavía no
  tiene esas herramientas conectadas. El auditor ya está publicado, pero el chat
  y el auditor no se hablan entre sí: para auditar usa el §3 directamente.
- Si cierras el navegador o pasa un rato sin usarlo, la conversación se
  olvida: no se guarda en ningún lado.

### Una nota sobre acceso

Este servicio es público a propósito, para que cualquiera pueda probarlo sin
pedir permiso. Eso también significa que cualquier otra persona en internet
puede usarlo, así que no envíes ahí datos que no quieras compartir.

---

## 3. El escenario completo

Esto es lo que muestra el proyecto de verdad: subir un lote de CFDI, ver cómo
se audita contra los libros de una PYME, detectar que una factura se intentó
ceder dos veces, y comprobar la prueba de integridad sin tener que confiar en
el sistema.

Hay dos formas de correrlo. **Los pasos 3 al 6 son idénticos**; lo único que
cambia es la dirección base.

| | Opción A — contra la nube | Opción B — en tu máquina |
|---|---|---|
| Instalar algo | solo Python y el repo | igual |
| Dirección base | `https://agente-cfdi-run-xsxcmt7edq-uc.a.run.app/auditoria` | `http://127.0.0.1:8000` |
| Quién más escribe ahí | cualquiera en internet | nadie |
| Persistencia | se borra al publicar una versión | tu archivo, hasta que lo borres |
| Para qué sirve | comprobar que está vivo de verdad | probar en serio, aislado |

### Opción A — contra el servicio publicado

Sin levantar nada. Comprueba que responde:

```bash
curl https://agente-cfdi-run-xsxcmt7edq-uc.a.run.app/auditoria/salud
```

```json
{"estado": "vivo", "inquilino": "DEMO000000XX0", "altura": 0, "punta": "..."}
```

Y corre el escenario completo apuntando ahí:

```bash
AGENTE_CFDI_API="https://agente-cfdi-run-xsxcmt7edq-uc.a.run.app/auditoria" python tools/demo.py
```

Salta al **paso 4** para leer qué hace ese script. La primera petición puede
tardar unos segundos: el servidor estaba dormido.

### Opción B — en tu máquina

#### Requisitos

- Python 3.11 o más nuevo.
- Ninguna cuenta ni credencial: el sistema trae datos de prueba (sintéticos)
  listos para usar.

### Paso 1 — Preparar el entorno

En Windows, si PowerShell bloquea el script de activación:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Instalar:

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

*(En Mac/Linux, el activador es `source .venv/bin/activate`.)*

### Paso 2 — Levantar el servidor de auditoría

```bash
python -m uvicorn agente_cfdi.api.app:app --port 8000
```

Déjalo corriendo. Abre una **segunda terminal** para todo lo que sigue.

### Paso 3 — Confirmar que responde

```bash
curl http://127.0.0.1:8000/salud
```

```json
{"estado": "vivo", "inquilino": "DEMO000000XX0", "altura": 0, "punta": "..."}
```

`altura: 0` es correcto — todavía no se ha subido nada.

### Paso 4 — Correr el escenario completo

```bash
python tools/demo.py
```

Este script hace, en orden, todo lo que el sistema sabe hacer:

1. Genera 40 CFDI de prueba y los sube en un lote.
2. Los audita contra los libros de la PYME de ejemplo.
3. Encuentra las desviaciones plantadas a propósito (un monto que no cuadra,
   un folio sin respaldo contable, un folio repetido).
4. Cede una factura limpia a un financiador — **Banco Norte**.
5. Reintenta la misma cesión — se acepta como reintento, no como fraude.
6. Intenta ceder **la misma factura** a otro financiador — **Factor Sur** —
   y se rechaza: ya estaba tomada.
7. Cede una factura con hallazgos — se acepta, pero con advertencia.
8. Publica la raíz del día (el "ancla", hoy simulada) y genera la prueba de
   inclusión de un folio.
9. Corre el verificador independiente sobre esa prueba.
10. Verifica que la cadena completa sea íntegra.

Si todo sale bien, termina sin errores y el código de salida es `0`. Si algo
no cuadra, lo dice explícitamente e imprime qué se esperaba contra qué
encontró.

### Paso 5 — Probarlo tú mismo, a mano

Los ejemplos usan la dirección local. **Si estás en la opción A**, cambia
`http://127.0.0.1:8000` por
`https://agente-cfdi-run-xsxcmt7edq-uc.a.run.app/auditoria` y todo lo demás es
igual.

Consultar si un folio ya fue cedido (usa un UUID que haya salido en el paso
anterior, lo ves en la salida de `tools/demo.py`):

```bash
curl http://127.0.0.1:8000/cesiones/<UUID>
```

Verificar que la cadena entera sea consistente:

```bash
curl http://127.0.0.1:8000/bitacora/verificacion
```

### Paso 6 — Verificar una prueba de integridad sin confiar en el sistema

Esta es la parte que demuestra el punto central del proyecto: **no hace falta
creerle al sistema**, se puede comprobar.

```bash
curl -s http://127.0.0.1:8000/auditoria/prueba/<UUID> > prueba.json
python tools/verificar_prueba.py prueba.json
```

*(En la opción A la ruta queda `/auditoria/auditoria/prueba/<UUID>`. No es un
error de dedo: el primer `/auditoria` es dónde está montado el auditor y el
segundo es el nombre de la ruta.)*

El verificador **no usa ni una línea de este proyecto** — solo herramientas
estándar de Python (`hashlib`, `json`, `base64`). Recalcula el hash desde
cero y confirma que efectivamente lleva a la raíz publicada.

Salida esperada hoy:

```
✓ el contenido produce la hoja declarada
✓ el camino lleva a la raíz declarada

⚠ el ancla es SIMULADA (simulada:local).
  No está publicada en ninguna red: no se puede comprobar fuera de su sistema.
```

Esto **no es un error** — es honestidad del sistema. El anclaje en una red
pública todavía no está conectado (ver el manual técnico, §5.4), así que el
verificador te avisa exactamente hasta dónde puedes confiar hoy: hasta ahí es
matemática verificable; lo que falta es la publicación externa.

---

## 4. Guía rápida de las respuestas

### Cuando subes CFDI (`/ingesta`)

| Campo | Qué significa |
|---|---|
| `auditados` | Cuántos comprobantes se procesaron |
| `rechazados` | Cuántos no se pudieron leer o venían repetidos en el lote |
| `hallazgos` | Cuántos tuvieron alguna discrepancia contable |
| `veredicto` de cada registro | `respaldado`, `sin_respaldo`, `monto_distinto` o `no_auditado` |

### Cuando cedes una factura (`/cesiones`)

| Código | Significa |
|---|---|
| `201` | Se registró la cesión |
| `200` | Ya la habías cedido tú mismo antes (reintento, no error) |
| `409` | Ya está cedida — a ti mismo con datos distintos, o a otro financiador |
| `503` | No se pudo consultar la contabilidad de la PYME (no es un rechazo, es una falla temporal) |

Si el `veredicto` no es `respaldado`, la respuesta trae una `advertencia` en
texto explicando el hallazgo. **La cesión se registra de todos modos** — la
decisión de operar con ese riesgo es del financiador, no del sistema.

---

## 5. Preguntas frecuentes

**¿Necesito una cuenta de Google Cloud para probar la demo local?**
No. La fuente de datos por omisión es sintética; no llama a ningún servicio
externo salvo el que tú mismo levantas en tu máquina.

**¿Puedo usar mis propios CFDI en vez de los de prueba?**
El sistema soporta CFDI 4.0 reales, pero conectar datos reales de una PYME
exige antes su consentimiento expreso y no es lo que hace `tools/demo.py`
(que genera datos sintéticos con una semilla fija). Ver
[contrato-expediente.md](contrato-expediente.md).

**¿Por qué el chat público no puede auditar mis facturas?**
Porque son dos aplicaciones y todavía no se hablan. Desde el 17 de agosto de 2026
las dos están publicadas —el chat en `/api/chat` y el auditor en `/auditoria`—
pero el modelo no tiene conectadas las herramientas para consultar la bitácora.
Puedes auditar llamando al auditor directamente (§3); lo que aún no puedes es
pedírselo al chat en español.

**¿Es seguro subir mis CFDI al servicio publicado?**
No. Es una demo abierta: cualquiera en internet puede leer y escribir en esa
bitácora, y el contenido se borra cada vez que se publica una versión nueva. Usa
los datos sintéticos, o levántalo en tu máquina (opción B).

**El verificador me dice que el ancla es "simulada". ¿Eso quiere decir que
el sistema no sirve?**
No. Quiere decir que la parte que sí se puede verificar matemáticamente
—que el registro no fue alterado y que pertenece a la cadena— **pasó**. Lo
que falta es publicar la raíz en una red pública fuera del control del
sistema, que es un paso de infraestructura pendiente, no un defecto del
cálculo.

**¿Dónde reporto un problema o reviso qué falta?**
En el [manual técnico](manual-tecnico.md), §10, hay un inventario priorizado
de lo que falta por resolver.

---

## 6. Glosario breve

| Término | En palabras simples |
|---|---|
| **CFDI** | La factura electrónica mexicana, en formato XML |
| **UUID** (o folio) | El identificador único de cada CFDI, asignado por el SAT |
| **Cesión** | Cuando una PYME vende el derecho a cobrar una factura a un financiador |
| **Doble cesión** | El fraude que el sistema existe para evitar: vender la misma factura dos veces |
| **Bitácora encadenada** | El registro donde cada movimiento queda ligado matemáticamente al anterior, para que alterar uno se note |
| **Anclaje** | Publicar un resumen del día en un lugar que el sistema no controla, para que no haya que confiarle la palabra |
| **Prueba de inclusión** | El comprobante de que un folio específico está en la bitácora, verificable sin acceso al sistema |
| **Veredicto** | El resultado de comparar un CFDI contra la contabilidad de la PYME |
