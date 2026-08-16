# All Things Agentic Hackathon — Plan de ejecución

**Escrito:** 11 de agosto de 2026
**Entrega:** 31 de agosto de 2026, 5:00 PM PDT — **20 días**
**Reglas:** https://allthingsagentichackathon.devpost.com/rules

---

## 1. Las restricciones, sin adornos

### Requisitos obligatorios que hoy NO cumplimos

| Requisito de las bases | Estado hoy | Acción |
|---|---|---|
| Gemini 3.5+ vía Gemini API o Vertex AI | NVIDIA `gpt-oss-120b` | Proveedor nuevo |
| Un framework de agentes de Google (ADK, GenAI SDK, Antigravity SDK, GenKit) | LangGraph | Agente nuevo en ADK |
| Un servicio de infraestructura de Google Cloud | Supabase | Cloud Run |

Los tres son **binarios**: sin ellos la participación no es elegible, por buena que
sea la solución. Esto manda sobre cualquier otra prioridad.

### La regla que define el encuadre

> «Projects must be newly created during the Submission Period.»

CØRD Fiscal son **20,630 líneas escritas antes** del periodo. Presentarlo tal cual
y declararlo «preexistente» es justo lo que la regla busca impedir.

**Encuadre adoptado:** el proyecto que se presenta es el **Agente de Aseguramiento
y Cesión de CFDI**, escrito íntegramente dentro de la ventana. CØRD Fiscal se
declara como **plataforma preexistente con la que integra**, al mismo nivel que
Postgres o FastAPI. Es cierto, es verificable en el historial de git del repo
nuevo, y lo que se construye es exactamente lo que hacía falta de todos modos.

**Consecuencia operativa:** repo público **nuevo**, con su propio historial. Nada
se copia y pega desde `cord_rag_plataform`; lo que se necesite de allá se consume
por HTTP.

### Cómo puntúan

| Criterio | Peso | Qué mira |
|---|---|---|
| Innovación y utilidad operativa | **40%** | Problema real, **ejecución autónoma** |
| Disciplina arquitectónica y stack | **30%** | Decisiones de ingeniería, manejo de estado |
| Demo y production readiness | **30%** | Documentación, video que pruebe la ejecución |

Bonus: 0.2 por cada modelo adicional de Google integrado (máx. 0.6), 0.2 por
contenido publicado, 0.2 por difusión.

**Categoría objetivo:** *Fortified Enterprise Fleet* — es la que encaja con un
agente de auditoría e integridad. Premio de $20,000.

---

## 2. Qué construimos

### El problema

Una PYME mexicana con CFDI ya timbrados y cobrables a 30–90 días necesita
liquidez. El factoraje existe, pero el financiador enfrenta dos riesgos que hoy
se cubren con confianza y papeleo:

1. **¿Los libros de esta PYME son fieles?** Auditar cuesta y no escala.
2. **¿Esta factura ya fue cedida a alguien más?** Es *el* fraude del factoraje:
   la misma cuenta por cobrar vendida dos veces.

### La tesis

Una cadena de hashes **no resuelve el segundo problema**. Encadenar prueba que
*nosotros* no alteramos nuestra bitácora — no impide ceder dos veces el mismo
UUID. Lo que sí lo impide es un **registro de cesiones verificable por terceros**.

Por eso el anclaje no es decoración: es lo que permite que un financiador
compruebe, **sin confiar en CØRD**, que un registro existía en un momento dado.
Esa es la respuesta a «¿y por qué no una base de datos?».

### El ciclo que el agente ejecuta solo

```
  1. INGESTA      lote de CFDI XML que sube la PYME (sin integrar PAC)
  2. VALIDACIÓN   estructura, UUID, emisor, receptor, monto, fecha
  3. AUDITORÍA    contrasta contra los libros de la PYME (CØRD Fiscal)
  4. REGISTRO     escribe en bitácora encadenada por hash
  5. DETECCIÓN    ¿este UUID ya fue cedido? → alerta
  6. EXPEDIENTE   arma el dossier de cesión para el financiador
  ─── al cierre del día ───
  7. MERKLE       árbol con los hashes del día → una sola raíz
  8. ANCLAJE      una transacción con la raíz
  9. PRUEBA       endpoint que devuelve la prueba de Merkle + el tx hash
```

Los pasos 1–6 corren por lote; 7–9 los dispara un job diario. **Nada de esto se
pide paso a paso** — ese es el 40% de «ejecución autónoma».

---

## 3. Decisiones de diseño

### 3.1 Serialización canónica

El hash se calcula sobre una representación **canónica** del registro, no sobre
lo que devuelva el ORM. Sin esto la verificación falla por razones espurias:
orden de campos distinto, `100.5` vs `100.50`, acentos en otra codificación.

Regla: campos en orden fijo declarado, montos como cadena con escala fija, fechas
en ISO-8601 UTC, UTF-8, sin espacios. La función vive en el dominio puro y tiene
pruebas propias.

### 3.2 Concurrencia

`hash_n = SHA256(contenido_n ‖ hash_{n-1})` tiene una carrera obvia: dos
inserciones simultáneas leen el mismo `hash_anterior` y bifurcan la cadena.

Solución: columna `posicion` con `UNIQUE (tenant_id, posicion)` y bloqueo
consultivo de Postgres por tenant durante el cálculo. Quien pierda la carrera
reintenta. **Hay que probarlo con inserciones concurrentes reales**, no asumirlo.

### 3.3 Una cadena por tenant

Aislamiento multi-tenant: la cadena de una PYME no puede depender de las
escrituras de otra. El árbol de Merkle diario sí cruza tenants —cubre el cierre
de todas las cadenas— y por eso una sola transacción sirve para todos.

### 3.4 Lo que la cadena NO detecta

Si alguien borra **la última** fila, la cadena queda consistente y no se entera.
El anclaje lo cubre: la raíz anclada incluye la posición final de cada cadena, y
una posición que retrocede es evidencia.

Vale decirlo en el video. Un jurado técnico va a buscar exactamente ese hueco.

### 3.5 Anclaje

Desarrollo contra **testnet** (Base Sepolia o Polygon Amoy), con salto a mainnet
solo para los días de la demo. Contrato mínimo: guarda `bytes32` y emite un
evento con la raíz y la fecha. Fracciones de centavo por transacción diaria.

Las llaves de la wallet **no van al repo**: Secret Manager de GCP.

---

## 4. Calendario

Tres carriles en paralelo. El primero es el que no puede resbalar.

### Días 1–6 · Elegibilidad (bloqueante)

- [ ] Repo público nuevo, licencia, README inicial
- [ ] Proyecto en Google Cloud, facturación, cuotas
- [ ] Agente en **ADK** con **Gemini vía Vertex AI** — el id exacto del modelo se
      confirma al arrancar contra el catálogo de Vertex
- [ ] Desplegado en **Cloud Run**, con URL viva
- [ ] Lector de CFDI XML: parseo, UUID, emisor, receptor, monto, fecha
- [ ] Acceso de solo lectura a CØRD Fiscal por HTTP

**Al cerrar el día 6 la participación ya es elegible.** Si esto se atrasa, todo
lo demás se recorta, no al revés.

### Días 7–14 · El producto

- [ ] Serialización canónica + pruebas
- [ ] Migración: `hash_actual`, `hash_anterior`, `posicion` en las tablas operativas
- [ ] Servicio de encadenamiento con bloqueo consultivo
- [ ] Prueba de concurrencia real
- [ ] `GET /auditoria/verificar-cadena`
- [ ] Registro de cesiones + detección de UUID duplicado
- [ ] Árbol de Merkle + job diario (Cloud Scheduler → Cloud Run)
- [ ] Contrato en testnet + anclaje
- [ ] `GET /auditoria/prueba/{uuid}` → prueba de Merkle + tx hash

### Días 15–20 · La entrega

Aquí se gana el 30% de *production readiness*, y es donde más equipos se caen.

- [ ] Diagrama de arquitectura
- [ ] README con instrucciones de arranque reproducibles
- [ ] Video ≤ 4 min, en inglés o con subtítulos, en YouTube público
- [ ] Texto de la submission: features, tecnologías, fuentes de datos, aprendizajes
- [ ] Declaración explícita de CØRD Fiscal como trabajo preexistente
- [ ] Anclaje a mainnet para la demo
- [ ] Ensayo del video con datos reales

### Carril paralelo · Interfaz

Puede avanzar desde el día 7 sin bloquear al backend: semáforo de integridad
(verde «cadena íntegra» / rojo «manipulación detectada»), vista del expediente de
cesión, y el enlace al explorador de bloques con la transacción del día.

---

## 5. Riesgos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| El stack de Google se atrasa | **Descalificación** | Días 1–6 son intocables; si se atrasa, se recorta producto |
| La regla de «newly created» se interpreta en contra | Descalificación | Repo nuevo con historial propio; declaración explícita |
| El anclaje come el presupuesto | Producto incompleto | Testnet primero; mainnet es el último paso, no el primero |
| Nadie prueba la concurrencia | Cadena bifurcada frente al jurado | Prueba de inserciones concurrentes en el día 10, no al final |
| El video se deja para el final | Pierde 30% | Guion escrito el día 14, grabación el 18, margen de dos días |

---

## 6. Fuera de alcance, dicho a propósito

- **Integrar un PAC.** La PYME sube el XML que ya tiene. Timbrar es otro producto.
- **Mover dinero.** El agente arma el expediente y prueba la integridad; la
  operación financiera la hace el financiador fuera del sistema.
- **Migrar la base a Cloud SQL.** Supabase se queda. Cloud Run cubre el requisito.
- **Cambiar el proveedor del chat de la plataforma.** Solo el agente nuevo usa Gemini.
- **Consenso distribuido propio.** Se ancla en una cadena existente. Ya estaba
  argumentado en `docs/fiscal/04-tokenizacion-y-blockchain.md` §3.4.

---

## 7. Lo que falta decidir

1. **Quién hace qué.** Hay al menos dos carriles paralelos desde el día 7.
2. **Datos de la demo.** ¿CFDI reales de una PYME con su consentimiento, o un
   lote sintético? Reales convencen más; sintéticos evitan un problema de datos
   personales en un video público. Con datos reales aplica el aviso de privacidad
   y hay que tratarlo antes de grabar.
3. **Cuenta de Google Cloud** con facturación activa — es un trámite que puede
   tardar y bloquea el día 1.
