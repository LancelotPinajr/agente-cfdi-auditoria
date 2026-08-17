# Frontera con CØRD Fiscal — declaración de trabajo preexistente

**Tarea del plan:** 3.4 (adelantada al Sprint 1) · **Fecha:** 14 de agosto de 2026

> «Projects must be newly created during the Submission Period.»
> — bases del All Things Agentic Hackathon

Este documento existe para que la frontera sea **verificable**, no afirmable.
Una declaración que solo se puede creer no sirve de nada.

---

## 1. Qué es nuevo y qué es preexistente

**Nuevo (este repositorio):** el Agente de Aseguramiento y Cesión de CFDI.
Lector de CFDI, serialización canónica, bitácora encadenada, registro de
cesiones, árbol de Merkle, anclaje y las pruebas de todo ello. Escrito
íntegramente dentro del periodo de la convocatoria. El historial de git de este
repo empieza dentro de la ventana y no se importó de ningún lado.

**Preexistente:** **CØRD Fiscal** es una plataforma anterior a la convocatoria.
Este agente la consume **por HTTP**, en el mismo plano que consume Postgres,
FastAPI o cualquier servicio de terceros. Se declara como dependencia externa,
sin ambigüedad y sin adornos.

---

## 2. La regla operativa

**Nada de código se copia desde `cord_rag_plataform`. Se consume, no se importa.**

En concreto:

- Este repositorio **no importa** ningún módulo de la plataforma.
- **No comparte proceso, base de datos ni despliegue** con ella.
- Toda la interacción pasa por `fuentes/cord_fiscal.py`, que hace peticiones
  HTTP a endpoints públicos y traduce la respuesta a tipos propios.
- Si esta clase desapareciera, CØRD Fiscal seguiría funcionando igual. Si CØRD
  Fiscal desapareciera, el agente correría con su fuente sintética.

---

## 3. Cómo se verifica

### 3.1 Coincidencia de código: 3 líneas, todas `import`

Comparación de todas las líneas de código de ≥40 caracteres entre este repo y
`cord_rag_plataform/backend/app`:

```
repo nuevo: 1037 líneas significativas
cord_rag_plataform/backend/app: 13352 líneas significativas
COINCIDENCIAS EXACTAS: 3
  from dataclasses import dataclass, field
  from datetime import datetime, timedelta
  from datetime import datetime, timedelta, timezone
```

Las tres son importaciones de la biblioteca estándar de Python. Reproducible con
el script de §3.3.

### 3.2 Lo que sí se tomó, y por qué es legítimo

Se tomó **el contrato de la API**: qué rutas existen, qué parámetros aceptan y
qué campos trae la respuesta.

```
GET /fiscal/contabilidad/libros           → { libros: [{ id, estado, ... }] }
GET /fiscal/contabilidad/libros/{id}      → { movimientos: [{ id, fecha, concepto,
                                              tipo, monto, rfc_contraparte, ... }] }
Autenticación: Authorization: Bearer <JWT>; el tenant se deriva del token
```

Conocer la forma de una API que se consume **es lo que significa consumirla**.
Un cliente de Stripe conoce los nombres de campo de Stripe; eso no lo convierte
en código de Stripe. Aquí no se replicó ninguna lógica de negocio de la
plataforma: ni el importador de Excel, ni la inferencia de columnas, ni las
reglas fiscales, ni el análisis financiero. El cliente hace peticiones y traduce
respuestas.

### 3.3 Reproducir la verificación

```bash
python tools/verificar_frontera.py ../cord_rag_plataform/backend/app
```

---

## 4. Un matiz que conviene decir en voz alta

El contrato de la API se dedujo leyendo el **código fuente** de la plataforma
—los routers y el repositorio contable—, y no su documentación OpenAPI. El
resultado es idéntico (los mismos nombres de campo), pero la ruta limpia y la
que no admite discusión es derivarlo de la **superficie pública**:

```bash
curl https://<cord-fiscal>/openapi.json
```

**Acción pendiente:** contrastar el contrato de §3.2 contra `/openapi.json` de la
instancia desplegada y dejar aquí el resultado. Es media hora de trabajo y
convierte «leímos su código para saber los campos» en «leímos su API». Vale la
pena hacerlo antes de la entrega.

---

## 5. Lo que este documento NO cubre

La elegibilidad tiene **tres requisitos obligatorios más**, y ninguno depende de
esta frontera:

1. Gemini 3.5+ vía Gemini API o Vertex AI
2. Un framework de agentes de Google (ADK, GenAI SDK, Antigravity SDK, GenKit)
3. Un servicio de infraestructura de Google Cloud

Son binarios: sin ellos la participación no es elegible por buena que sea la
solución, y **nada de lo que hay en este repositorio los satisface todavía**. El
código de este repo es la lógica de dominio que el agente en ADK invoca; el
agente, el modelo y el despliegue son el carril de infraestructura y son
bloqueantes.
