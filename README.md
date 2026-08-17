# Agente de Aseguramiento y Cesión de CFDI

[![pruebas](https://github.com/LancelotPinajr/agente-cfdi-auditoria/actions/workflows/pruebas.yml/badge.svg)](https://github.com/LancelotPinajr/agente-cfdi-auditoria/actions/workflows/pruebas.yml)

Un agente que audita CFDI de una PYME mexicana, los escribe en una bitácora
encadenada por hash, detecta cuando una factura se intenta ceder dos veces, y
publica la raíz de la evidencia del día — de modo que un financiador pueda
verificarla **sin confiar en nosotros**.

> **El anclaje todavía es simulado.** El árbol de Merkle, la prueba de
> inclusión, el endpoint y el verificador independiente están hechos; falta
> conectar una red real. Mientras tanto cada respuesta lo declara
> (`verificable_por_terceros: false`) en vez de dejarlo escrito solo aquí.

Escrito para el [All Things Agentic Hackathon](https://allthingsagentichackathon.devpost.com/),
categoría *Fortified Enterprise Fleet*.

---

## El problema

Una PYME con CFDI ya timbrados y cobrables a 30–90 días necesita liquidez. El
factoraje existe, pero el financiador enfrenta dos riesgos que hoy se cubren con
confianza y papeleo:

1. **¿Los libros de esta PYME son fieles?** Auditar cuesta y no escala.
2. **¿Esta factura ya fue cedida a alguien más?** Es *el* fraude del factoraje:
   la misma cuenta por cobrar vendida dos veces.

Una cadena de hashes por sí sola **no resuelve el segundo problema**. Encadenar
prueba que nosotros no alteramos nuestra bitácora; no impide ceder dos veces el
mismo UUID. Lo que sí lo impide es un registro de cesiones **verificable por
terceros** — y por eso el anclaje no es decoración.

## El ciclo que el agente ejecuta solo

```
  1. INGESTA      lote de CFDI XML que sube la PYME
  2. VALIDACIÓN   estructura, UUID, emisor, receptor, monto, fecha
  3. AUDITORÍA    contrasta contra los libros de la PYME (CØRD Fiscal, por HTTP)
  4. REGISTRO     escribe en bitácora encadenada por hash
  5. DETECCIÓN    ¿este UUID ya fue cedido? → alerta
  6. EXPEDIENTE   arma el dossier de cesión para el financiador
  ─── al cierre del día ───
  7. MERKLE       árbol con los hashes del día → una sola raíz
  8. ANCLAJE      una transacción con la raíz
  9. PRUEBA       endpoint que devuelve la prueba de Merkle + el tx hash
```

Los pasos 1–6 corren por lote; 7–9 los dispara un job diario. Nada de esto se
pide paso a paso.

---

## Stack

| Componente | Tecnología |
|---|---|
| Modelo | Gemini 3.5 Flash (`gemini-3.5-flash`, versión `3.5-flash-05-2026`) |
| Framework de agentes | Google ADK |
| Infraestructura | Google Cloud Run |
| Job diario | Cloud Scheduler |
| Secretos | Secret Manager |

### Nota sobre el modelo

Se usa el id exacto y no un alias `*-latest`, para que la versión sea
verificable por un jurado. Descartados: familia 2.5 (por debajo del requisito de
3.5+) y variantes EAP/Confidential.

Verificado el 14-ago-2026 vía Gemini API. Migración a Vertex AI: **[PENDIENTE]**

**Ninguna afirmación de integridad del sistema pasa por el modelo.** El hash, el
encadenamiento, la detección de doble cesión y la prueba de Merkle son código
determinista con pruebas; el modelo orquesta y redacta, no decide si un CFDI está
respaldado. Por eso Flash alcanza —no hay tier Pro en 3.5+— y por eso el veredicto
es auditable sin confiar en el modelo.

---

## Estado

| Pieza | Estado |
|---|---|
| Serialización canónica `CORD-CANON-2` | ✅ implementada y congelada |
| Generador de CFDI sintéticos | ✅ |
| Lector de CFDI 4.0 | ✅ |
| Fuente de libros (sintética + CØRD Fiscal) | ✅ |
| Verificación del modelo | ✅ vía Gemini API; Vertex pendiente |
| Bitácora encadenada | ✅ |
| Registro de cesiones | ✅ |
| Endpoints de ingesta y cesión | ✅ |
| Cotejo contra los libros | ✅ |
| Prueba de inclusión (Merkle) | ✅ |
| Anclaje | ⚠️ simulado — falta conectar red real |
| Agente ADK en Cloud Run | ⬜ carril de infraestructura |

320 pruebas. El núcleo verificable —canon, hashes, cadena, Merkle, cotejo— no
depende de nada externo; FastAPI, uvicorn y httpx entran solo en el borde HTTP.

---

## Requisitos

- Python 3.11+
- Cuenta de Google Cloud con facturación activa (para el smoke test del modelo)
- `gcloud` CLI instalado y autenticado

## Arranque local

En Windows, PowerShell bloquea scripts por defecto:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Entorno, dependencias y pruebas:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
```

Prueba de humo del modelo (necesita `GOOGLE_API_KEY`):

```bash
python smoke_test.py
```

Debe imprimir `ok`.

## Variables de entorno

| Variable | Descripción |
|---|---|
| `GOOGLE_API_KEY` | Key de Google AI Studio |
| `GOOGLE_CLOUD_PROJECT` | [PENDIENTE] |
| `GOOGLE_CLOUD_REGION` | [PENDIENTE] |
| `AGENTE_CFDI_FUENTE` | `sintetica` (por omisión) o `cord_fiscal` |
| `CORD_FISCAL_URL` | Base de la API de CØRD Fiscal |
| `CORD_FISCAL_TOKEN` | JWT del agente para esa PYME — de Secret Manager, nunca del repo |
| `AGENTE_CFDI_SEMILLA` | Semilla del lote sintético |

Sin configurar nada, el agente corre contra la fuente sintética: quien clona el
repo obtiene una demo que funciona, no un error de credenciales.

## Despliegue

[PENDIENTE — 1.5]

## Endpoints

| Método | Ruta | Qué hace |
|---|---|---|
| `POST` | `/ingesta` | Sube un lote de CFDI XML: los lee, los audita contra los libros y los encadena |
| `POST` | `/cesiones` | Intenta ceder un folio a un financiador |
| `GET` | `/cesiones/{uuid}` | ¿Está tomado? (no dice a nombre de quién) |
| `GET` | `/bitacora/verificacion` | Recorre la cadena entera y reporta si es íntegra |
| `GET` | `/salud` | Sonda de vida |
| `POST` | `/bitacora/anclaje` | Publica la raíz de Merkle del día (job diario) |
| `GET` | `/auditoria/prueba/{uuid}` | La prueba de inclusión, verificable sin nosotros |

Levantar y correr el escenario completo:

```bash
python -m uvicorn agente_cfdi.api.app:app --port 8000
```

```bash
python tools/demo.py
```

`tools/demo.py` genera el lote **con la misma semilla que usa la fuente de
libros**. Sin eso, los libros no contienen los folios que se suben y todo sale
`sin_respaldo` — no porque el auditor falle, sino porque se le pregunta por
facturas de otra empresa.

### Códigos de estado que significan algo

| Situación | Código |
|---|---|
| Folio ya cedido a **otro** financiador | `409` |
| Folio ya cedido al **mismo** (reintento de red) | `200`, idempotente |
| Libros inalcanzables | `503`, **no** «sin respaldo» |
| CFDI ilegible o duplicado dentro del lote | se reporta en `fallas`; el lote sigue |

**Hueco declarado:** los endpoints no autentican a quien llama. En Cloud Run
quedan detrás de IAM, pero eso protege el perímetro y no distingue a un
financiador de otro. Antes de datos reales hace falta autenticación por
financiador.

## Contrato en blockchain

**Todavía no hay anclaje real.** Está hecho todo lo que lo rodea —árbol de
Merkle, ruta de inclusión, endpoint, constancia, idempotencia del job diario y
verificador independiente— detrás de un protocolo con una implementación
simulada.

El ancla simulada **se declara como tal** en cada respuesta
(`verificable_por_terceros: false`, más una advertencia en texto) y el
verificador sale con código 2 en vez de 0. Un ancla de mentira que pareciera real
sería peor que ninguna: pasaría por buena en un video de demo.

Conectar una red es sustituir una clase por otra que cumpla el mismo protocolo;
exige decidir red, financiar gas y manejar una llave — riesgos que no son de
código. Ver [ADR 0006](docs/adr/0006-anclaje-y-prueba.md).

### Verificar una prueba sin confiar en nosotros

```bash
curl -s localhost:8000/auditoria/prueba/<UUID> > prueba.json
```

```bash
python tools/verificar_prueba.py prueba.json
```

Ese script **no importa una sola línea de este proyecto** — solo `hashlib`,
`json` y `base64`. Si la verificación usara nuestro código, comprobaría que
nuestro código coincide consigo mismo, que no demuestra nada.

---

## Datos de la demo: sintéticos, por diseño

La demo corre con CFDI **sintéticos**, no con facturas reales de una PYME. No es
una concesión:

- **Hace reproducible el proyecto.** Cualquiera clona el repo y levanta la demo
  completa sin necesitar facturas de nadie.
- **Permite grabar el escenario de manipulación sin censurar nada.**
- **Es coherente con nuestro propio aviso de privacidad.** El video es público y
  un CFDI real lleva datos patrimoniales identificables (LFPDPPP).

Los RFC generados llevan `000000` en la porción de fecha, que el SAT no puede
haber asignado nunca —no existe el día cero del mes cero— y que el esquema de
CFDI 4.0 acepta. Así **no pueden coincidir con los de una persona real**.

La fuente de datos es una interfaz con dos implementaciones —sintética y real—,
de modo que cambiar de una a otra es configuración, no reescritura. Pasar a datos
reales exige antes consentimiento expreso (LFPDPPP art. 8, por tratarse de datos
patrimoniales), minimización según el
[contrato del expediente](docs/contrato-expediente.md) y retención conforme al
CFF art. 30.

---

## Documentación

- [ADR 0001 — Serialización canónica `CORD-CANON-2`](docs/adr/0001-serializacion-canonica.md)
- [ADR 0003 — Lectura de CFDI](docs/adr/0003-lectura-de-cfdi.md)
- [ADR 0004 — Bitácora encadenada y registro de cesiones](docs/adr/0004-bitacora-encadenada.md)
- [ADR 0005 — Endpoints de ingesta y cesión](docs/adr/0005-endpoints.md)
- [ADR 0006 — Prueba de inclusión y anclaje](docs/adr/0006-anclaje-y-prueba.md)
- [Contrato de datos del expediente](docs/contrato-expediente.md) — qué sale, qué no, y por qué
- [Datos sintéticos](docs/datos-sinteticos.md) — RFC que no pueden ser de nadie, y huecos conocidos
- [Frontera con CØRD Fiscal](docs/trabajo-preexistente.md) — declaración verificable
- [Bitácora](docs/bitacora/) — estado y decisiones por día

## Trabajo preexistente

Este agente se construyó íntegramente durante el periodo de submission; el
historial de git lo evidencia.

**CØRD Fiscal** es una plataforma **preexistente** de la que este agente consume
los libros contables de la PYME **por HTTP**, al mismo nivel que Postgres o
FastAPI. Nada de su código se copia ni se importa aquí — y no hay que creernos:

```bash
python tools/verificar_frontera.py ../cord_rag_plataform/backend/app
```

Al 14-ago: 3 coincidencias en 1062 líneas, las tres `from datetime import …`.
Detalle en [docs/trabajo-preexistente.md](docs/trabajo-preexistente.md).

## Licencia

MIT — ver [LICENSE](LICENSE).
