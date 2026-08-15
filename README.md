# Agente de Aseguramiento y Cesión de CFDI

Un agente que audita CFDI de una PYME mexicana, los escribe en una bitácora
encadenada por hash, detecta cuando una factura se intenta ceder dos veces, y
ancla la evidencia del día en una cadena pública — de modo que un financiador
pueda verificarla **sin confiar en nosotros**.

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

## Estado

| Pieza | Estado |
|---|---|
| Serialización canónica `CORD-CANON-2` | ✅ implementada y congelada |
| Generador de CFDI sintéticos | ✅ |
| Lector de CFDI 4.0 | ✅ |
| Fuente de libros (sintética + CØRD Fiscal) | ✅ |
| Bitácora encadenada | ⬜ Sprint 2 |
| Registro de cesiones | ⬜ Sprint 2 |
| Merkle + anclaje | ⬜ Sprint 2 |
| Agente ADK + Gemini en Cloud Run | ⬜ carril de infraestructura |

188 pruebas, sin dependencias de terceros salvo `httpx` para el cliente HTTP.

---

## Arranque

Requiere **Python 3.11+**.

```bash
git clone <url-del-repo> && cd cord-agente-cfdi
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
```

---

## Datos de la demo: sintéticos, por diseño

La demo corre con CFDI **sintéticos**, no con facturas reales de una PYME. No es
una concesión:

- **Hace reproducible el proyecto.** Cualquiera clona el repo y levanta la demo
  completa sin necesitar facturas de nadie.
- **Permite grabar el escenario de manipulación sin censurar nada.**
- **Es coherente con nuestro propio aviso de privacidad.** El video es público y
  un CFDI real lleva datos patrimoniales identificables (LFPDPPP).

Los RFC generados usan patrones reservados del SAT para que **no puedan
coincidir con los de una persona real**. La fuente de datos es una interfaz con
dos implementaciones —sintética y real—, de modo que cambiar de una a otra es
configuración, no reescritura. Pasar a datos reales exige antes consentimiento
expreso (LFPDPPP art. 8, por tratarse de datos patrimoniales), minimización
según el [contrato del expediente](docs/contrato-expediente.md) y retención
conforme al CFF art. 30.

---

## Cambiar la fuente de libros

Sin configurar nada corre contra la fuente sintética. Para leer los libros
reales desde CØRD Fiscal:

```bash
export AGENTE_CFDI_FUENTE=cord_fiscal
export CORD_FISCAL_URL=https://api.cordgroup.cloud
export CORD_FISCAL_TOKEN=...   # de Secret Manager, nunca del repo
```

## Documentación

- [ADR 0001 — Serialización canónica `CORD-CANON-2`](docs/adr/0001-serializacion-canonica.md)
- [ADR 0003 — Lectura de CFDI](docs/adr/0003-lectura-de-cfdi.md)
- [Contrato de datos del expediente](docs/contrato-expediente.md) — qué sale, qué no, y por qué
- [Datos sintéticos](docs/datos-sinteticos.md) — RFC que no pueden ser de nadie, y huecos conocidos
- [Frontera con CØRD Fiscal](docs/trabajo-preexistente.md) — declaración verificable

## Trabajo preexistente

Este repositorio es **código nuevo**, escrito íntegramente dentro del periodo de
la convocatoria; su historial de git lo evidencia.

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
