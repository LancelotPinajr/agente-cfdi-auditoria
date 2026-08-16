# Plan de equipo — All Things Agentic Hackathon

**Entrega:** 31 de agosto de 2026, 5:00 PM PDT
**Tres sprints de una semana.** Ver [`00-plan.md`](00-plan.md) para el porqué de cada decisión.

---

## Equipo

| Quién | Carril | Responsabilidad |
|---|---|---|
| **Dinesh** | Infraestructura para el cumplimiento | Que los tres requisitos obligatorios del hackathon existan y estén desplegados: Gemini vía Vertex AI, framework ADK, Google Cloud. Despliegue, secretos, job diario, observabilidad. |
| **Gilfoyle** | Código con cumplimiento normativo | El agente y su lógica: lector de CFDI, serialización canónica, cadena de hashes, Merkle, contrato, registro de cesiones. Retención CFF art. 30 y minimización LFPDPPP en el expediente. |
| **Ambos** | Pruebas e integración final | Concurrencia, integración de extremo a extremo, ensayo y grabación, materiales de entrega. |

### La regla de oro del reparto

El carril de Dinesh es **bloqueante**. Si al cerrar el Sprint 1 no hay un agente
en ADK con Gemini corriendo en Cloud Run, no importa qué tan bueno esté el código
de Gilfoyle: la participación no es elegible. **Ante conflicto de prioridad, gana
infraestructura.**

---

## Ceremonias

- **Daily: 21:00 hrs, todos los días.** Máximo 15 minutos. Tres preguntas: qué
  cerré, qué sigue, qué me bloquea. Un bloqueo que se repite dos dailies escala a
  decisión ese mismo día.
- **Cierre de sprint:** último día del sprint en el daily. Se revisa cada criterio
  de aceptación contra la realidad, no contra la intención.
- **Planeación del siguiente sprint:** inmediatamente después del cierre.

## Definition of Done (aplica a todo)

Una tarea está cerrada solo si:

1. Su criterio de aceptación se cumple **y alguien distinto al autor lo verificó**.
2. Hay prueba automatizada, o está documentado por qué no la lleva.
3. Está en el repo público, no en la máquina de nadie.
4. No rompe nada que ya funcionaba.

---

# Sprint 1 · Elegibilidad
### 11 – 17 de agosto

**Meta del sprint:** al cerrar, la participación es elegible. Un agente en ADK con
Gemini responde desde una URL pública de Cloud Run y lee un CFDI XML.

**Si este sprint falla, el hackathon se perdió.** Todo lo demás es recortable.

### Dinesh — infraestructura

| # | Tarea | Criterio de aceptación |
|---|---|---|
| ~~1.1~~ | ~~Cuenta de Google Cloud~~ | ✅ **Hecha el 11-ago.** Cuenta gratuita (crédito de prueba, 90 días). |
| 1.1b | `gcloud` instalado y autenticado | `gcloud config list` muestra cuenta y proyecto. No estaba instalado en la máquina al 11-ago. |
| 1.1c | APIs habilitadas | `aiplatform`, `run`, `cloudscheduler`, `secretmanager` aparecen en `gcloud services list --enabled`. |
| 1.1d | **Gemini 3.5+ responde de verdad** | Una llamada real devuelve texto, no un error de cuota ni de modelo inexistente. **Es la verificación más urgente del proyecto**: si el modelo requerido no está disponible en la cuenta gratuita o en la región elegida, el plan entero cambia — y eso hay que saberlo hoy, no el día 5. El id exacto y la región quedan anotados en el README. |
| 1.2 | Repo público nuevo | Repo creado con licencia y README. Historial propio desde el primer commit. Acceso dado a `testing@devpost.com` y `cloudhackathons@google.com`. |
| 1.3 | Acceso a Gemini vía Vertex AI | Una llamada de prueba devuelve texto. El id exacto del modelo queda anotado en el README (se confirma contra el catálogo de Vertex, no se asume). |
| 1.4 | Esqueleto del agente en ADK | El agente arranca local y responde a un mensaje. Es ADK, no un wrapper — el framework aparece en `requirements`. |
| 1.5 | Despliegue en Cloud Run | `curl` a la URL pública devuelve 200. La URL queda en el README. |
| 1.6 | Secret Manager | Ninguna llave en el repo. `git log -p \| grep -i "key\|secret"` sale limpio. |
| 1.7 | Despliegue reproducible | Un tercero levanta el proyecto siguiendo solo el README, sin preguntar nada. |

### Gilfoyle — código

| # | Tarea | Criterio de aceptación |
|---|---|---|
| 1.8 | Lector de CFDI XML | Dado un XML timbrado real, extrae UUID, RFC emisor, RFC receptor, total, fecha y moneda. Prueba con al menos 3 XML de estructura distinta. |
| 1.9 | Rechazo de XML inválido | Un XML malformado, uno sin UUID y uno que no es CFDI devuelven error descriptivo, no excepción. |
| 1.10 | Serialización canónica | `canonicalizar(registro)` es estable: mismo registro → misma cadena de bytes, sin importar orden de campos ni cómo venga el decimal. Prueba con `100.5` vs `100.50` y con acentos. |
| 1.11 | Lectura de CØRD Fiscal por HTTP | El agente obtiene los movimientos de una PYME por HTTP. **Nada de copiar código de `cord_rag_plataform`** — se consume, no se importa. |
| 1.12 | Contrato de datos del expediente | Documentado qué campos lleva el dossier y cuáles se omiten por minimización (LFPDPPP). Un RFC no viaja si no hace falta. |

### Ambos

| # | Tarea | Criterio de aceptación |
|---|---|---|
| 1.13 | Integración de humo | El agente desplegado recibe un XML y devuelve los campos extraídos. Extremo a extremo, en la nube, no en local. |

---

# Sprint 2 · El producto
### 18 – 24 de agosto

**Meta del sprint:** el ciclo completo corre **solo**. El agente recibe un lote,
audita, detecta una cesión duplicada, ancla al cierre del día, y cualquiera puede
verificar la prueba.

### Gilfoyle — código

| # | Tarea | Criterio de aceptación |
|---|---|---|
| 2.1 | Migración de la bitácora | `hash_actual`, `hash_anterior`, `posicion` en las tablas operativas. `UNIQUE (tenant_id, posicion)`. Idempotente: correrla dos veces no rompe. |
| 2.2 | Servicio de encadenamiento | `hash_n = SHA256(canónico_n ‖ hash_{n-1})`. La primera fila usa una constante génesis documentada. |
| 2.3 | Bloqueo consultivo por tenant | Dos inserciones simultáneas producen posiciones 1 y 2, nunca dos veces la misma ni una cadena bifurcada. |
| 2.4 | `GET /auditoria/verificar-cadena` | Con la cadena íntegra responde `ok`. **Se edita un monto a mano en la base y responde el número de fila exacto donde se rompió.** |
| 2.5 | Registro de cesiones | Ceder un UUID lo marca. Intentar cederlo de nuevo devuelve un rechazo que nombra la cesión previa y su fecha. |
| 2.6 | Árbol de Merkle | Con los hashes del día produce una raíz. La prueba de inclusión de cualquier hoja verifica contra la raíz. |
| 2.7 | Contrato en testnet | Guarda `bytes32` y emite evento con raíz y fecha. Desplegado en Base Sepolia o Polygon Amoy, dirección en el README. |
| 2.8 | `GET /auditoria/prueba/{uuid}` | Devuelve la prueba de Merkle y el hash de la transacción. **Un tercero la verifica sin pedirnos nada**, con la raíz que está en la cadena. |

### Dinesh — infraestructura

| # | Tarea | Criterio de aceptación |
|---|---|---|
| 2.9 | Job diario automático | Cloud Scheduler dispara el cierre. Corre dos días seguidos **sin que nadie lo toque** y deja dos anclajes. |
| 2.10 | Wallet en Secret Manager | La llave privada nunca sale de Secret Manager. Rotarla no exige redesplegar. |
| 2.11 | Logs y alertas | Un fallo del job diario es visible sin entrar a la máquina. |
| 2.12 | Reintento del job | Si el anclaje falla por red, reintenta y no ancla dos veces el mismo día. |

### Ambos

| # | Tarea | Criterio de aceptación |
|---|---|---|
| 2.13 | Prueba de concurrencia real | 50 inserciones concurrentes dejan la cadena íntegra. **Va el día 10, no al final** — es el bug que aparece frente al jurado. |
| 2.14 | Ejecución autónoma de punta a punta | Lote de CFDI → auditoría → detección de duplicado → expediente → anclaje, **sin intervención manual en ningún paso**. Es el 40% de la calificación. |

---

# Sprint 3 · La entrega
### 25 – 31 de agosto · cierre 17:00 PDT

**Meta del sprint:** materiales entregados con dos días de margen. Aquí se gana el
30% de *production readiness* y es donde más equipos se caen.

**Congelación de funcionalidad el 28.** Lo que no esté para entonces no entra.

### Ambos

| # | Tarea | Criterio de aceptación |
|---|---|---|
| 3.1 | Guion del video | Escrito el día 25. Cubre problema, propuesta de valor y la ejecución autónoma. Cronometrado bajo 4 minutos leyéndolo en voz alta. |
| 3.2 | Diagrama de arquitectura | Muestra Gemini, ADK, Cloud Run, el job diario y el anclaje. Legible en el video sin pausar. |
| 3.3 | README de arranque | Alguien ajeno levanta el proyecto siguiéndolo. Se prueba con una persona real. |
| 3.4 | Declaración de trabajo preexistente | CØRD Fiscal declarado explícitamente como plataforma preexistente con la que integra. Sin ambigüedad. |
| 3.5 | Texto de la submission | Features, tecnologías, fuentes de datos y aprendizajes. |
| 3.6 | Anclaje a mainnet | Al menos un anclaje real en Base o Polygon mainnet, con el enlace al explorador. |
| 3.7 | Grabación | Día 28. Muestra la ejecución autónoma con datos reales y el despliegue en Google Cloud. Inglés o subtítulos en inglés. YouTube público. |
| 3.8 | Envío | **Día 30, no el 31.** Un día entero de margen para lo que salga mal. |

### Dinesh

| # | Tarea | Criterio de aceptación |
|---|---|---|
| 3.9 | URL viva y estable | Responde durante toda la ventana de evaluación. Probada desde fuera de la red del equipo. |
| 3.10 | Datos de demo cargados | El entorno tiene el lote que se usa en el video, reproducible. |

### Gilfoyle

| # | Tarea | Criterio de aceptación |
|---|---|---|
| 3.11 | Semáforo de integridad | Verde «cadena íntegra» / rojo «manipulación detectada», con el enlace a la transacción del día. |
| 3.12 | Escenario de manipulación | Guion reproducible: se altera un monto, el semáforo se pone rojo, el endpoint nombra la fila. Es el momento más fuerte del video. |

---

## Dependencias que hay que vigilar

```
1.1 (cuenta GCP) ─┬─> 1.3 ─> 1.4 ─> 1.5 ─> 1.13 ─> 2.9
                  └─> 1.6 ────────────────────────> 2.10

1.10 (canónica) ──> 2.2 ──> 2.3 ──> 2.4 ──> 2.13
                     └────> 2.6 ──> 2.7 ──> 2.8 ──> 3.6

2.14 (autonomía) ─> 3.1 ──> 3.7 ──> 3.8
```

**1.1 bloquea la mitad del proyecto y es un trámite administrativo.** Es lo
primero que se arranca, hoy mismo, aunque no se escriba código.

**1.10 bloquea toda la cadena.** Si la serialización canónica cambia después de
que haya registros escritos, todos los hashes previos dejan de verificar. Se
congela al cerrar el Sprint 1.

---

## Riesgos por carril

| Riesgo | Dueño | Señal temprana | Qué hacer |
|---|---|---|---|
| La cuenta de GCP se atrasa | Dinesh | No está lista el día 2 | Escalar en el daily; considerar cuenta personal como puente |
| Vertex AI con cuota insuficiente | Dinesh | Errores de cuota en 1.3 | Solicitar aumento el mismo día; es trámite, tarda |
| La cadena se bifurca | Gilfoyle | 2.13 falla | Ya está previsto: el bloqueo consultivo es 2.3, no un parche |
| Gas o wallet sin fondos | Dinesh | 2.7 no despliega | Testnet cubre todo el desarrollo; mainnet solo en 3.6 |
| El video se deja al final | Ambos | El guion no está el día 25 | Congelación el 28 es innegociable |
| Datos personales en un video público | Ambos | Se decide el 27 | **Decidir en el Sprint 1**: CFDI reales con consentimiento, o sintéticos |

---

## Lo que sigue sin decidirse

**Los datos de la demo.** CFDI reales convencen más, pero el video es público y
ahí aplica el aviso de privacidad de CØRD. Sintéticos evitan el problema y cuestan
credibilidad. **Se decide en el Sprint 1**, no el día de grabar.
