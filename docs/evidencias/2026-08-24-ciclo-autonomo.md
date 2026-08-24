# Evidencia — tercer día consecutivo sin que nadie lo toque (tarea 2.14)

**Verificado:** 24 de agosto de 2026, contra el proyecto real en GCP y contra
Base Sepolia.

**Qué se prueba:** que el ciclo completo —ingesta, auditoría, detección de doble
cesión, cierre, árbol de Merkle y anclaje en cadena pública— corrió solo, a su
hora, por tercer día seguido; y que la raíz que el servicio declara es
**literalmente la misma** que está publicada en la red.

**Qué NO se prueba:** ver la sección 7. Los CFDI son sintéticos, la red es
testnet y la bitácora vive en `/tmp`.

Proyecto `project-d0428141-1b39-47af-9bc` · región `us-central1` ·
servicio `agente-cfdi-run` · contrato `0xe76b981159307a79c77B29796F59087D6c13d974`.

---

## 1. Los dos jobs, y que nadie los tocó

```bash
gcloud scheduler jobs list --location=us-central1 --format="table(name.basename(),schedule,state,lastAttemptTime)"
```

```
ID                 SCHEDULE     STATE    LAST_ATTEMPT_TIME
job-cierre-diario  59 23 * * *  ENABLED  2026-08-24T05:59:02.509669Z
job-ciclo-diario   0 23 * * *   ENABLED  2026-08-24T05:00:39.288786Z
```

`23:00 America/Mexico_City` = `05:00 UTC`; `23:59` = `05:59 UTC`. Ambos jobs
apuntan a la URL del servicio desplegado:

```yaml
# job-ciclo-diario
httpTarget:
  httpMethod: POST
  uri: https://agente-cfdi-run-xsxcmt7edq-uc.a.run.app/auditoria/ciclo-diario
attemptDeadline: 180s
timeZone: America/Mexico_City
retryConfig: {retryCount: 3, minBackoffDuration: 10s, maxRetryDuration: 600s}
```

**El dato que importa:** la primera interacción humana con el sistema el 24 de
agosto ocurrió a las **21:43 UTC**, casi dieciséis horas después de que el ciclo
ya hubiera cerrado y anclado. Nadie disparó nada. Nadie confirmó nada.

---

## 2. El ciclo — 05:00:39 UTC

```bash
gcloud logging read 'resource.type="cloud_run_revision" AND timestamp>="2026-08-24T04:55:00Z" AND timestamp<="2026-08-24T06:05:00Z"'
```

Cuatro eventos estructurados, en orden:

```json
{"evento": "ciclo.inicio",    "comprobantes": 41, "origen_del_lote": "sintetico", "semilla": 20260814}
{"evento": "ciclo.auditoria", "auditados": 40, "hallazgos": 3, "rechazados": 1, "altura": 123}
{"evento": "ciclo.cesion",    "uuid": "58665D2C-659B-4A47-B432-61CA2D9E157D",
                              "primera_aceptada": true, "segunda_aceptada": false}
{"evento": "ciclo.fin",       "estado": "completado", "altura": 123}
```

```
INFO: "POST /auditoria/ciclo-diario HTTP/1.1" 200 OK
```

De 41 comprobantes, **40 pasaron y 1 fue rechazado**, con 3 hallazgos. Y la
línea que sostiene el producto entero:

> `"primera_aceptada": true, "segunda_aceptada": false`

El mismo UUID se intentó ceder dos veces. La primera cesión se registró; la
segunda **se rechazó**. Eso es el fraude del factoraje, detectado sin que nadie
mirara.

---

## 3. El cierre — 05:59:06 UTC

```json
{
  "evento": "cierre.anclado",
  "dia": "2026-08-24",
  "altura": 124,
  "verificados": 124,
  "registros_del_dia": 41,
  "raiz": "d17a61403dbd1c31a00800fd4e37e06aa0938bc97032f7e480b2763e2d849a83",
  "red": "base-sepolia",
  "referencia": "0xc3e3827fba4556593dbb090181760dee516b3b81fda6b55b2d79d1c69a8e8947",
  "verificable_por_terceros": true,
  "ya_estaba": false
}
```

```
INFO: "POST /api/cierre-diario HTTP/1.1" 200 OK
```

`"verificados": 124` sobre una altura de 124 significa que el cierre **recalculó
la cadena entera antes de anclar**. Si un solo eslabón no hubiera cuadrado, no
habría anclaje: publicar la raíz de una cadena manipulada es peor que no
publicar nada.

`"ya_estaba": false` — el contrato prohíbe reanclar un día. Este es el primer y
único anclaje del 24 de agosto.

---

## 4. La cadena de verificación, cerrada de punta a punta

### Paso 0 — el semáforo, en vivo

```bash
curl -s https://agente-cfdi-run-xsxcmt7edq-uc.a.run.app/auditoria/semaforo
```

```json
{
  "color": "verde",
  "titulo": "CADENA ÍNTEGRA Y PUBLICADA",
  "detalle": "los 124 eslabones recalculables cuadran y la raíz del 2026-08-24 está publicada en base-sepolia; cualquiera puede comprobarla sin pedirnos nada",
  "altura": 124,
  "verificados": 124,
  "posicion_del_problema": null
}
```

### Pasos 1 y 2 — el verificador independiente

```bash
python tools/verificar_prueba.py prueba.json
```

```
Folio            : 58665D2C-659B-4A47-B432-61CA2D9E157D
Día              : 2026-08-24  (41 registros)
Camino           : 6 hashes de hermanos

Registro (canónico):
  CORD-CANON-2|cfdi_auditado|evento|scfdi_auditado|inquilino|sDEMO000000XX0
  |escrito_en|t2026-08-24T05:00:39Z|uuid|s58665D2C-659B-4A47-B432-61CA2D9E157D
  |rfc_emisor|sSBZ000000171|rfc_receptor|sQTB0000006X4|total|d513508.83
  |moneda|sMXN|fecha_emision|s2026-08-13T01:09:14|veredicto|srespaldado
  |monto_en_libros|d513508.83|fuente_de_libros|scontabilidad sintética
   (semilla 20260814) — NO son libros reales

✓ el contenido produce la hoja declarada  20333b25e057a399…
✓ el camino lleva a la raíz declarada     d17a61403dbd1c31…

✓ raíz anclada en base-sepolia
  referencia: 0xc3e3827fba4556593dbb090181760dee516b3b81fda6b55b2d79d1c69a8e8947
  fecha     : 2026-08-24T05:59:04Z
```

Este verificador **no importa una sola línea del proyecto**: solo `hashlib`,
`json` y `base64`. Si usara nuestro código, comprobaría que nuestro código
coincide consigo mismo, que no demuestra nada.

### Paso 3 — la lectura contra la red, que no depende de nosotros

El verificador termina diciendo que falta un último paso, y que ese no depende
de nosotros. Hasta hoy ese paso había que darlo a mano, abriendo el explorador.
Ya no: `tools/leer_raiz_publicada.py` hace un `eth_call` a
`raizDelDia("2026-08-24")` contra el RPC público de Base Sepolia, **sin pasar
por nuestro servicio** y sin más dependencias que la biblioteca estándar — ni
siquiera `web3`.

```bash
python tools/leer_raiz_publicada.py 2026-08-24 d17a61403dbd1c31a00800fd4e37e06aa0938bc97032f7e480b2763e2d849a83
```

```
contrato   : 0xe76b981159307a79c77B29796F59087D6c13d974  (base-sepolia)
dia        : 2026-08-24
raiz en red: d17a61403dbd1c31a00800fd4e37e06aa0938bc97032f7e480b2763e2d849a83
raiz dada  : d17a61403dbd1c31a00800fd4e37e06aa0938bc97032f7e480b2763e2d849a83

[OK] COINCIDEN — la raiz declarada es la que esta en la red
```

Los dos casos negativos también se comprobaron: con una raíz falsa dice
`NO COINCIDEN` y sale con código 1; con un día sin anclar (`2026-01-01`) el
contrato devuelve ceros y dice `ese dia no tiene raiz publicada`.

**El lazo queda cerrado:**

```
contenido del registro  →  hoja declarada         ✓
camino de Merkle        →  raíz declarada         ✓
raíz declarada          == raíz en Base Sepolia   ✓   ← leído de la red, no de nosotros
```

---

## 5. Tres días consecutivos, los tres leídos de la cadena

Las tres raíces se consultaron directamente al contrato, no a nuestra API:

| Día | Raíz publicada en Base Sepolia | Transacción | Intervención |
|---|---|---|---|
| 2026-08-22 | `3a540914bb5d4252…2c8851a1` | `0xd3d279e1…` | manual (primer anclaje) |
| 2026-08-23 | `fe20dcc2dbe7f8c9…572f083c` | `0x1f23d51d…` | **ninguna** |
| 2026-08-24 | `d17a61403dbd1c31…2d849a83` | `0xc3e3827f…` | **ninguna** |

Un día desatendido puede ser suerte. Dos seguidos ya es un sistema.

---

## 6. La suite, el mismo día

```bash
python -m pytest
```

```
375 passed, 1 warning in 10.18s
```

---

## 7. Qué NO prueba esta evidencia

Se declara para que nadie lo lea de más:

- **La red es testnet.** Base Sepolia, no mainnet. Repetirlo en mainnet cuesta
  ~1 USD al año y es la tarea 3.6.
- **Los CFDI son sintéticos, y es una decisión.** Los RFC llevan `000000` en la
  porción de fecha, que el SAT no puede haber asignado nunca. Un anclaje público
  de CFDI reales expondría datos patrimoniales identificables — y el anclaje es
  irreversible por diseño.
- **La contabilidad contra la que se auditó es generada** (semilla `20260814`).
  El propio registro canónico lo dice en claro: `NO son libros reales`. Nunca se
  ha corrido contra una instancia viva de CØRD Fiscal.
- **La bitácora vive en un SQLite en `/tmp` de Cloud Run.** Cada despliegue la
  borra. Hoy lo tapa el ciclo diario, que la vuelve a llenar. Es el punto más
  débil del sistema, y está declarado también en el README.
- **El token de escritura distingue quién puede escribir, no quién es.** No hay
  autenticación por financiador.

---

## Reproducirlo

```bash
curl -s https://agente-cfdi-run-xsxcmt7edq-uc.a.run.app/auditoria/semaforo
```

```bash
curl -s https://agente-cfdi-run-xsxcmt7edq-uc.a.run.app/auditoria/auditoria/prueba/58665D2C-659B-4A47-B432-61CA2D9E157D > prueba.json && python tools/verificar_prueba.py prueba.json
```

```bash
python tools/leer_raiz_publicada.py 2026-08-24 d17a61403dbd1c31a00800fd4e37e06aa0938bc97032f7e480b2763e2d849a83
```

La prueba tal como la devolvió el servicio quedó guardada en
[`prueba-2026-08-24.json`](prueba-2026-08-24.json), y el anclaje se puede ver
también en el explorador, que tampoco es nuestro:
<https://sepolia.basescan.org/tx/0xc3e3827fba4556593dbb090181760dee516b3b81fda6b55b2d79d1c69a8e8947>
