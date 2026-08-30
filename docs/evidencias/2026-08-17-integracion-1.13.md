# Evidencia — integración de humo extremo a extremo (tarea 1.13)

**Verificado:** 17 de agosto de 2026, 20:57–20:58 UTC, contra el servicio real en
Cloud Run.

Criterio de aceptación, del plan de equipo:

> El agente desplegado recibe un XML y devuelve los campos extraídos. Extremo a
> extremo, **en la nube, no en local**.

Proyecto `project-d0428141-1b39-47af-9bc` · región `us-central1` ·
servicio `agente-cfdi-run` · revisión **`agente-cfdi-run-00002-b4c`**.

---

## 1. El antes y el después, en el mismo log

Esto es lo que hace la evidencia difícil de discutir: la misma URL, con siete
minutos de diferencia, contra dos revisiones distintas.

| Timestamp | URL | Status | Revisión |
|---|---|---|---|
| 2026-08-17T20:50:39.749Z | `/auditoria/salud` | **404** | `agente-cfdi-run-00001-2x8` |
| 2026-08-17T20:57:46.603Z | `/auditoria/salud` | **200** | `agente-cfdi-run-00002-b4c` |

Antes del despliegue el motor de auditoría viajaba en la imagen pero no estaba
montado ni instalado: `import agente_cfdi` fallaba y la ruta no existía. La
revisión `00002` es el primer despliegue que incluye el motor verificable.

Build de Cloud Build: `74c202ea-f66f-4dac-8bb8-4491e1bd6916`.

---

## 2. La corrida completa, lado servidor

```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="agente-cfdi-run" AND httpRequest.requestUrl:"/auditoria/"' \
  --project project-d0428141-1b39-47af-9bc --limit 20 --freshness=1h
```

Todo sobre `agente-cfdi-run-00002-b4c`, en orden cronológico:

| Timestamp | Método | Ruta | Status | Latencia |
|---|---|---|---|---|
| 20:57:59.481Z | GET | `/auditoria/salud` | 200 | 5.4 ms |
| 20:57:59.687Z | POST | `/auditoria/ingesta` | 200 | **52.3 ms** |
| 20:57:59.814Z | POST | `/auditoria/cesiones` | **201** | 7.2 ms |
| 20:57:59.892Z | POST | `/auditoria/cesiones` | **200** | 4.1 ms |
| 20:57:59.971Z | POST | `/auditoria/cesiones` | **409** | 5.5 ms |
| 20:58:00.051Z | POST | `/auditoria/cesiones` | 201 | 5.0 ms |
| 20:58:00.128Z | POST | `/auditoria/bitacora/anclaje?dia=2026-08-17` | 200 | 6.7 ms |
| 20:58:00.205Z | GET | `/auditoria/auditoria/prueba/58665D2C-…` | 200 | 6.7 ms |
| 20:58:00.359Z | GET | `/auditoria/bitacora/verificacion` | 200 | 5.5 ms |

Los tres códigos seguidos en `/cesiones` **son** el escenario de fraude:
`201` la primera cesión, `200` el reintento del mismo financiador —un timeout de
red no es fraude— y `409` cuando un segundo financiador intenta el mismo folio.

52 ms para leer, auditar y encadenar 40 comprobantes.

---

## 3. Lo que pidió el criterio: campos extraídos de un XML

Salida completa en [`salida-1.13.txt`](salida-1.13.txt). El registro canónico que
devolvió la nube para uno de los folios:

```
CORD-CANON-2|cfdi_auditado|evento|scfdi_auditado|inquilino|sDEMO000000XX0
|escrito_en|t2026-08-17T20:57:59Z|uuid|s58665D2C-659B-4A47-B432-61CA2D9E157D
|rfc_emisor|sSBZ000000171|rfc_receptor|sQTB0000006X4|total|d513508.83
|moneda|sMXN|fecha_emision|s2026-08-13T01:09:14|veredicto|srespaldado
|monto_en_libros|d513508.83
|fuente_de_libros|scontabilidad sintética (semilla 20260814) — NO son libros reales
```

UUID, RFC emisor, RFC receptor, total, moneda y fecha de emisión, extraídos de un
CFDI 4.0 timbrado. Criterio cumplido.

### Quién extrajo esos campos

**No el modelo.** La extracción la hizo `agente_cfdi.cfdi.lector.leer_cfdi`, que
es un parser de XML consciente de espacios de nombres, determinista y con
pruebas. En toda la corrida no hay una sola petición a `/api/chat`: las nueve
peticiones del log son endpoints de auditoría.

Esto importa porque el atajo existía. Se podía cumplir la frase del criterio
mandándole el XML a Gemini y pidiéndole los campos —y habría contradicho la tesis
del proyecto, que sostiene que ninguna afirmación de integridad pasa por el
modelo. No se tomó ese camino.

### Resultados de la auditoría

```
ingesta → auditados=40 rechazados=1 hallazgos=3
  ✓ folio duplicado rechazado en la ingesta
  ✓ el auditor encontró exactamente las 3 desviaciones esperadas
    F92DE933… sin_respaldo   : CFDI 496423.32 vs libros None
    099FCC1A… monto_distinto : CFDI 463714.83 vs libros 463564.83
    9B3B23B3… monto_distinto : CFDI 395375.95 vs libros 790751.90
```

Las desviaciones estaban plantadas a propósito por el generador sintético. El
auditor encontró **exactamente** esas y ninguna de más: ni falsos positivos ni
silencios.

---

## 4. La cadena cierra y un tercero puede comprobarlo

```
anclaje del 2026-08-17 → 43 registros
  raíz : f8c5e29d06b57c55c0fcd26e57c808d9d7c44e4a0e14f6b2e28af336c3160a31
  red  : simulada:local
  verificable por terceros: False

prueba de 58665D2C… → 6 hashes para 43 registros del día
  ✓ no expone ninguno de los otros 39 folios de la PYME

verificación de la cadena → integra: True, altura: 43,
  recalculados: 43, suprimidos_por_retencion: 0
  punta: 23dc5e0f9b293bb13fc7cd01f8956e70943ee4a260604d0db2003447f5e69309
```

La prueba descargada de la nube se pasó por
[`tools/verificar_prueba.py`](../../tools/verificar_prueba.py), que **no importa
una sola línea de este proyecto**:

```
✓ el contenido produce la hoja declarada  d7b9d4fc72bda950…
✓ el camino lleva a la raíz declarada     f8c5e29d06b57c55…
⚠ el ancla es SIMULADA (simulada:local).
```

Un financiador recalcula la raíz por su cuenta y la compara. Seis hashes bastan
para probar un folio entre 43 sin revelar los otros 39.

---

## 5. Qué NO prueba esto

1. **El ancla sigue simulada.** El propio verificador lo grita. Sin una raíz
   publicada en una red real, la cadena solo demuestra consistencia interna —que
   es justo lo que un tercero no tiene por qué creernos. Es la tarea 3.6 y es la
   que sostiene toda la propuesta de valor.
2. **La bitácora es efímera.** Vive en `/tmp/bitacora.db`, sobre el disco de la
   instancia. Se pierde al reciclarla y **no sobrevive un despliegue**. La corrida
   de arriba fue de un tirón, con la cadena arrancando en altura 0.
3. **Una sola instancia.** El despliegue lleva `--max-instances=1` porque con dos
   cada una escribiría su propia cadena y la punta se bifurcaría. Es un parche
   honesto hasta que haya persistencia compartida, no la solución.
4. **Datos sintéticos.** Los libros son de una contabilidad generada con semilla
   `20260814` y el inquilino es `DEMO000000XX0`, un RFC que el SAT no pudo asignar
   nunca. No se auditó un CFDI real de nadie.
5. **Sin autenticación.** El servicio está `--allow-unauthenticated`: cualquiera
   con la URL puede ingerir y ceder. Tiene que cerrarse antes de datos reales.
6. **El job diario sigue apuntando al stub.** `/api/cierre-diario` continúa
   devolviendo `"simulado"`; que el motor esté montado no lo conecta solo. Ver
   [`2026-08-17-job-diario.md`](2026-08-17-job-diario.md).

---

## Cómo reproducir

```bash
cd /d/CORD/agente-cfdi-ricardo
AGENTE_CFDI_API="https://agente-cfdi-run-xsxcmt7edq-uc.a.run.app/auditoria" \
  ./.venv/Scripts/python.exe tools/demo.py
```

La semilla del despliegue (`AGENTE_CFDI_SEMILLA=20260814`) tiene que coincidir con
la de `demo.py`. Si no coinciden, los libros y los comprobantes hablan de
empresas distintas y **todo sale `sin_respaldo`** — parecería que el auditor
falla cuando en realidad se le pregunta por facturas que nunca vio.

Los hashes de esta corrida no se reproducen: el canónico incluye `escrito_en`, así
que cada corrida produce una raíz distinta. Lo reproducible son los veredictos y
los códigos de estado.

Retención de Cloud Logging: 30 días. Después del **16 de septiembre de 2026** las
consultas de arriba dejan de devolver esta corrida.
