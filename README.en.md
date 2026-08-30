# CFDI Assurance and Assignment Agent

[![tests](https://github.com/LancelotPinajr/agente-cfdi-auditoria/actions/workflows/pruebas.yml/badge.svg)](https://github.com/LancelotPinajr/agente-cfdi-auditoria/actions/workflows/pruebas.yml)

*English translation of [`README.md`](README.md). The Spanish version is the source of
truth: the code, the API and the log events are in Spanish, and this file keeps those
identifiers verbatim so that anything you read here can be grepped in the repository.*

An agent that audits the e-invoices (CFDI) of a Mexican small business, writes them to a
hash-chained ledger, detects when an invoice is assigned twice, and publishes the root of
the day's evidence — so that a financier can verify it **without trusting us**.

> **The anchoring is real, on testnet.** The day's root is published to our own contract on
> Base Sepolia and anyone can check it on the block explorer without asking us for anything.
> **It does not move to mainnet, and that is a decision**, not a pending task: what separates
> testnet from mainnet is not verifiability but permanence and economic value — see
> [the sixth boundary](docs/05-alcance-y-no-objetivos.md). Every response declares which
> network it anchored to and whether the result is third-party verifiable, so the difference
> is never hidden.

Built for the [All Things Agentic Hackathon](https://allthingsagentichackathon.devpost.com/),
*Fortified Enterprise Fleet* category.

---

## The problem

A small business with stamped invoices collectible in 30–90 days needs liquidity. Factoring
exists, but the financier faces two risks that today are covered with trust and paperwork:

1. **Are this company's books faithful?** Auditing costs money and does not scale.
2. **Has this invoice already been assigned to somebody else?** This is *the* factoring
   fraud: the same receivable sold twice.

A hash chain on its own **does not solve the second problem**. Chaining proves that *we* did
not alter *our* ledger; it does not prevent the same UUID from being assigned twice. What
does prevent it is an assignment registry that is **verifiable by third parties** — which is
why the anchoring is not decoration.

## The cycle the agent runs on its own

```
  1. INTAKE       a batch of CFDI XML uploaded by the company
  2. VALIDATION   structure, UUID, issuer, recipient, amount, date
  3. AUDIT        cross-checked against the company's books (CØRD Fiscal, over HTTP)
  4. LEDGER       written to a hash-chained ledger
  5. DETECTION    has this UUID already been assigned? → alert
  6. DOSSIER      assembles the assignment file for the financier
  ─── at end of day ───
  7. MERKLE       a tree over the day's hashes → one root
  8. ANCHOR       one transaction carrying that root
  9. PROOF        an endpoint returning the Merkle proof + the tx hash
```

Steps 1–6 run per batch; 7–9 are triggered by a daily job. None of this is requested step by
step.

## The map

![Agent architecture](docs/arquitectura.svg)

Two things are drawn to be seen before they are read: **where our infrastructure ends** — the
verification happens on the far side of that line — and that **the model sits outside the data
path**, hanging off the ledger by a read-only arrow. Detail in
[docs/arquitectura.md](docs/arquitectura.md) *(Spanish)*.

---

## Stack

| Component | Technology |
|---|---|
| Model | Gemini 3.5 Flash (`gemini-3.5-flash`, version `3.5-flash-05-2026`) |
| Agent framework | Google ADK |
| Infrastructure | Google Cloud Run |
| Daily job | Cloud Scheduler |
| Secrets | Secret Manager |
| Alerting | Cloud Monitoring — two policies, see «Observability» |
| Anchoring | Base (our own Solidity contract, `web3.py`) |

### A note on the model

We use the exact id rather than a `*-latest` alias, so that a judge can verify the version.
Discarded: the 2.5 family (below the 3.5+ requirement) and EAP/Confidential variants.

Verified on 16 Aug 2026 **via Vertex AI** with Application Default Credentials. The
migration from the Gemini API is done: the AI Studio prepaid balance ran out
(`429 RESOURCE_EXHAUSTED`) and the GCP project's billing is independent of it, so Vertex is
the sustainable path — and it is the same path that runs on Cloud Run, with no API key
involved.

**The location is `global`, not `us-central1`.** `gemini-3.5-flash` is not published in
`us-central1` and returns 404 there. `us-central1` is the region of the Cloud Run
deployment; these are two different things and conflating them breaks startup.

**No integrity claim made by this system passes through the model.** Hashing, chaining,
double-assignment detection and Merkle proofs are deterministic code with tests; the model
orchestrates and explains, it does not decide whether an invoice is backed by the books.
That is why Flash is enough — there is no Pro tier in 3.5+ — and why the verdict is
auditable without trusting the model.

---

## Status

| Piece | Status |
|---|---|
| Canonical serialization `CORD-CANON-2` | ✅ implemented and frozen |
| Synthetic CFDI generator | ✅ |
| CFDI 4.0 reader | ✅ |
| Books source (synthetic + CØRD Fiscal) | ✅ |
| Model verification | ✅ via Vertex AI (16 Aug) |
| Hash-chained ledger | ✅ |
| Assignment registry | ✅ |
| Intake and assignment endpoints | ✅ |
| Cross-check against the books | ✅ |
| Inclusion proof (Merkle) | ✅ |
| ADK agent on Cloud Run | ✅ deployed and verified in production |
| Integration of the two services | ✅ the public URL exposes the audit service at `/auditoria` |
| Real daily close | ✅ verifies the chain and anchors; no longer a stub |
| Integrity light | ✅ |
| Write authentication | ✅ reading is open, writing requires a token |
| Daily job alerting | ✅ two policies, confirmed with a real alert |
| Anchoring key in Secret Manager | ✅ read on every anchoring, rotatable without redeploying |
| Anchoring contract | ✅ deployed on Base Sepolia |
| Anchoring on a real network | ✅ publishing, with the proof verified against the chain |
| Autonomous daily cycle | ✅ two chained jobs: feed at 23:00, anchor at 23:59 |
| Restore at startup and snapshot to GCS | ✅ the ledger survives losing the instance |
| Anchoring on mainnet | ⛔ **not done** — decided 26 Aug, [sixth boundary](docs/05-alcance-y-no-objetivos.md) |

397 tests. The verifiable core — canonical form, hashes, chain, Merkle, cross-check —
depends on nothing external; FastAPI, uvicorn and httpx only appear at the HTTP edge.

---

## Requirements

- Python 3.11+
- A Google Cloud account with billing enabled (for the model smoke test)
- `gcloud` CLI installed and authenticated

## Running it locally

On Windows, PowerShell blocks scripts by default:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Environment, dependencies and tests:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
```

Authentication (no API key needed):

    gcloud auth login
    gcloud config set project project-d0428141-1b39-47af-9bc
    gcloud auth application-default login

Smoke test:

    python smoke_test.py

It should print the backend line followed by `ok`, like this:

    Vertex AI (project-d0428141-1b39-47af-9bc / global) | gemini-3.5-flash -> ok

## Environment variables

None are mandatory locally: the code defaults point at Vertex with ADC and at the project
below.

| Variable | Description |
|---|---|
| `GOOGLE_GENAI_USE_VERTEXAI` | `1` for Vertex (default). Takes precedence over everything else |
| `GOOGLE_CLOUD_PROJECT` | `project-d0428141-1b39-47af-9bc` |
| `GOOGLE_CLOUD_REGION` | `global` — location of the **model**, not of the deployment |
| `GEMINI_MODEL` | Overrides the model id. Default `gemini-3.5-flash` |
| `GOOGLE_API_KEY` | Only for the Gemini API path. Currently out of credits; unused |
| `AGENTE_CFDI_FUENTE` | `sintetica` (default) or `cord_fiscal` |
| `CORD_FISCAL_URL` | Base URL of the CØRD Fiscal API |
| `CORD_FISCAL_TOKEN` | The agent's JWT for that company — from Secret Manager, never from the repo |
| `AGENTE_CFDI_SEMILLA` | Seed for the synthetic batch |
| `AGENTE_CFDI_BITACORA` | Path to the SQLite file. On Cloud Run, `/tmp/bitacora.db` |
| `AGENTE_CFDI_INQUILINO` | Taxpayer ID (RFC) of the tenant. Default `DEMO000000XX0` |
| `AGENTE_CFDI_TOKEN_ESCRITURA` | Token required by the endpoints that write |
| `AGENTE_CFDI_ANCLA_RED` | `base-sepolia`, `base`, `polygon-amoy` or `polygon`. Empty = simulated anchor |
| `AGENTE_CFDI_ANCLA_CONTRATO` | Address of the anchoring contract |
| `AGENTE_CFDI_ANCLA_RPC` | Overrides the network's public RPC |
| `AGENTE_CFDI_LLAVE_SECRETO` | Name of the secret holding the private key. **Production path** |
| `AGENTE_CFDI_LLAVE` | Private key in plaintext. **Development against testnet only** |

The three anchoring variables travel together: if you set `AGENTE_CFDI_ANCLA_RED` and the
contract or the key is missing, the service **refuses to start** instead of falling back to
the simulated anchor. A deployment that believes it is anchoring to mainnet while signing
certificates of a lie is the scenario this project exists to not produce.

With nothing configured, the agent runs against the synthetic source: whoever clones the
repo gets a working demo, not a credentials error.

If you define `GOOGLE_API_KEY` in a `.env`, note that `load_dotenv()` re-injects it on every
startup: to force Vertex anyway, set `GOOGLE_GENAI_USE_VERTEXAI=1`, which takes precedence.

## Agent architecture

The agent lives in `agente/agent.py` as `root_agent`, an ADK `LlmAgent` — the name ADK looks
for by convention when loading an agent directory — and execution is driven by an ADK
`Runner`. `main.py` is only HTTP transport for Cloud Run: it contains no agent logic. That
separation lets you run the same agent with `adk run` locally without dragging the server
along.

## Deployment

Public URL: **https://agente-cfdi-run-xsxcmt7edq-uc.a.run.app**

    curl https://agente-cfdi-run-xsxcmt7edq-uc.a.run.app/
    curl -X POST https://agente-cfdi-run-xsxcmt7edq-uc.a.run.app/api/chat \
      -H "Content-Type: application/json" -d '{"message":"hola"}'

    .\deploy.ps1

The script uses `--source .`, so Cloud Build compiles the `Dockerfile` without anyone having
to build the image by hand.

### A permission you have to grant once

In recently created GCP projects, the default Compute service account — the one Cloud Build
uses — does not get permissions automatically, and deploying from source fails with a 403 on
the `run-sources-*` bucket:

    gcloud projects add-iam-policy-binding project-d0428141-1b39-47af-9bc \
      --member="serviceAccount:1031368580327-compute@developer.gserviceaccount.com" \
      --role="roles/cloudbuild.builds.builder"

### Automation (Cloud Scheduler)

The `job-cierre-diario` job fires `POST /api/cierre-diario` every day at `23:59`, with 3
retries.

Until 16 Aug it pointed at a domain that did not exist, which is why it never ran. It has
been repointed at the real URL and has run every night since 17 Aug; evidence of the first
run is in
[`docs/evidencias/2026-08-17-job-diario.md`](docs/evidencias/2026-08-17-job-diario.md).

**Those first runs hit a stub and anchored nothing.** The real close was deployed on 20 Aug.
Since then the acceptance criterion for task 2.9 has been met and exceeded: **three
consecutive days** — 22, 23 and 24 August — left three anchors, the last two with nobody
touching anything. See
[`docs/evidencias/2026-08-24-ciclo-autonomo.md`](docs/evidencias/2026-08-24-ciclo-autonomo.md).

One detail worth watching: the job fires at 23:59 Mexico City time — 05:59 UTC — but the
ledger groups by **UTC day**. The close for a UTC day runs when that day is six hours old,
so anything written afterwards falls under no root. The fix is to fire at the end of the UTC
day:

    gcloud scheduler jobs update http job-cierre-diario --location us-central1 --time-zone=Etc/UTC

## Endpoints

> **There are two applications and a single deployment.** The audit service
> (`src/agente_cfdi/api/app.py`) holds the CFDI, ledger and Merkle logic; the agent service
> (`main.py`) is the transport, and since task 1.13 it mounts the former at `/auditoria`.
> The routes in the table below are the application's: in the cloud they all hang off that
> prefix. Evidence in
> [`docs/evidencias/2026-08-17-integracion-1.13.md`](docs/evidencias/2026-08-17-integracion-1.13.md).

### Audit service — `src/agente_cfdi/api/app.py`

| Method | Route | What it does |
|---|---|---|
| `POST` | `/ingesta` | Upload a batch of CFDI XML: reads them, audits them against the books, chains them |
| `POST` | `/cesiones` | Attempt to assign an invoice to a financier |
| `GET` | `/cesiones/{uuid}` | Is it taken? (does not say by whom) |
| `GET` | `/bitacora/verificacion` | Walks the whole chain and reports whether it is intact |
| `GET` | `/salud` | Liveness probe. Does not verify the chain: that is another endpoint |
| `GET` | `/semaforo` | Green, amber or red, with the position of the broken link if there is one |
| `POST` | `/bitacora/anclaje` | Publishes the day's Merkle root |
| `POST` | `/cierre-diario` | Verifies the chain and anchors. Triggered by the job |
| `GET` | `/auditoria/prueba/{uuid}` | The inclusion proof, verifiable without us |
| `GET` | `/anclajes` | Which roots were published, on which network, and where to check them |
| `GET` | `/anclajes/{dia}` | What sits under that day's root, leaf by leaf |
| `GET` | `/vista` | The same figures in HTML prose, for tools that import a URL as a source |
| `GET` | `/vista/anclajes` | The published roots, in prose |
| `GET` | `/vista/anclajes/{dia}` | What hangs from that root, in prose |
| `GET` | `/consola` | Browser console to ingest, assign and close the day |

### Two HTML surfaces, and why they are two

The same engine serves two pages that look like the same thing and are not. Keeping
them apart is the decision, not an accident of filing.

| | `/vista` | `/consola` |
|---|---|---|
| **Who for** | A tool that imports the URL as a source (NotebookLM and the like) | A person with a browser |
| **What it does** | Writes out the traffic light, the published roots and what hangs from each one, in prose | Ingests batches, registers assignments, closes the day, and talks to the agent |
| **JavaScript** | None | Yes — the token travels in a header, and a `<form>` cannot do that |
| **Writes** | No | Yes, with a token |

**`/vista` carries no `<style>` block, and that is deliberate.** A text extractor that
strips tags without handling `<style>` separately swallows the CSS *as if it were prose*,
and the source the notebook stores opens with half a page of typography rules. All
formatting lives in per-element `style=` attributes. One test fails if anyone
reintroduces a style block, and another fails if anyone puts a form in the views.

**Every page carries the cut-off timestamp at the top and the caveats at the bottom** —
the CFDI are synthetic, testnet is not mainnet, the chain does not prove who wrote — and
they appear on all of them, not only on the front page: nobody guarantees the front page
is read before the detail. A frozen source claiming "the chain is intact" without saying
*as of when* is exactly the failure this project exists not to commit.

**The console stores the token nowhere.** It is typed, lives in that tab's memory, and
travels in `Authorization`, just as `curl` would. It is not written to `localStorage`, it
never goes in the URL — where it would end up in history, in server logs, and in the
`Referer` — and it is not persisted server-side. The page being public opens nothing:
without a token, writes are rejected exactly as always. The console is one more client,
not an exception to the authentication model.

### Who can write

Reading is open; writing requires a token. The line is not drawn at the service, it is drawn
at the operation:

| No credential | Requires `Authorization: Bearer <token>` |
|---|---|
| `/`, `/api/chat` | `POST /auditoria/ingesta` |
| `/auditoria/salud`, `/auditoria/semaforo` | `POST /auditoria/cesiones` |
| `/auditoria/bitacora/verificacion` | `POST /auditoria/bitacora/anclaje` |
| `/auditoria/auditoria/prueba/{uuid}` | `POST /api/cierre-diario` |
| `/auditoria/anclajes`, `/auditoria/anclajes/{dia}` | |
| `/auditoria/vista`, `/auditoria/vista/anclajes` | |
| `/auditoria/consola` (the page; the writes it triggers do require a token) | |

That a third party can verify the chain **without asking our permission** is the thesis of
the project: there is a test that fails if anyone puts a credential in front of a read.

On Cloud Run with no token configured, writes return `503`. Getting it wrong by omission
leaves the system closed, not open. Locally nothing is required: there the ledger is a file
full of synthetic data.

Bring it up and run the full scenario:

```bash
python -m uvicorn agente_cfdi.api.app:app --port 8000
```

```bash
python tools/demo.py
```

`tools/demo.py` generates the batch **with the same seed the books source uses**. Without
that, the books do not contain the invoices being uploaded and everything comes back
`sin_respaldo` (unbacked) — not because the auditor fails, but because it is being asked
about another company's invoices.

### Status codes that mean something

| Situation | Code |
|---|---|
| Invoice already assigned to **another** financier | `409` |
| Invoice already assigned to the **same** one (network retry) | `200`, idempotent |
| Books unreachable | `503`, **not** "unbacked" |
| CFDI unreadable or duplicated within the batch | reported in `fallas`; the batch continues |

**Declared gap:** the token distinguishes who *may* write, **not who they are**. A financier
holding the token can assign in anyone's name. Before real data, per-financier
authentication is required; today the deployment is tied to a single taxpayer, which makes
this tolerable, not correct.

### ADK agent service — `main.py` (what is deployed)

- `GET /` : Health check. Returns the framework and the model id in use.
- `POST /api/chat` : Runs one turn of the ADK agent. Takes `{"message": "hola"}` and accepts
  an optional `session_id` to thread the conversation.
- `POST /api/cierre-diario` : Called by Cloud Scheduler. Verifies the chain and anchors the
  day's root. **Requires a token.** If the chain is broken it does not anchor and responds
  `500`: publishing the root of a tampered chain would leave a permanent record of corrupt
  data.
- `/auditoria/*` : the audit service, mounted here.

**This service is deployed with `--allow-unauthenticated`**, so its reads are public. That is
deliberate, so a judge can open the URL without asking for credentials. Its writes stopped
being public on 20 Aug.

## Observability

A daily job fails in two ways, and the second one raises no alarm by itself:

| Policy | What it catches |
|---|---|
| **Daily close FAILED** | The close returned `5xx`: broken chain, or anchoring impossible |
| **Daily close DID NOT RUN** | Silence. The job was disabled, deleted, or stopped firing |

The second one is what matters: nobody returns an error because nobody runs. It gets
discovered by accident three weeks later.

    powershell -File ./configurar_alertas.ps1 -Email you@example.com

The script is idempotent and each policy carries its own runbook inside, which travels in
the body of the email. The broken-chain one says explicitly **do not retry**.

We do not use an absence condition for the second: the maximum the API accepts is 23h30m and
the job runs every 24h exactly, so the window would expire half an hour before each close and
the alert would scream daily. An alert that fires every day is an alert people learn to
ignore. Instead we sum the metric over a rolling 24h window with 30 minutes of tolerance.

Verified on 20 Aug with a throwaway policy: the email arrives in the inbox and the
documentation is visible in the body.

---

## Blockchain contract

**The anchoring is real and running.** The contract
[`contratos/AnclaDeRaices.sol`](contratos/AnclaDeRaices.sol) stores one `bytes32` per day and
emits an event; `AnclaEVM` signs and publishes, following the same protocol as the simulated
anchor.

| | |
|---|---|
| Network | **Base Sepolia** (`chain 84532`) |
| Contract | [`0xe76b981159307a79c77B29796F59087D6c13d974`](https://sepolia.basescan.org/address/0xe76b981159307a79c77B29796F59087D6c13d974) |
| Signing wallet | `0x83C889F7C0866917288E5FCF14E9792096C95dDA` |

The address goes here and not only in the configuration **on purpose**: without it published,
a third party cannot check the roots on their own, and the project's entire argument
collapses.

**It is not repeated on mainnet.** It would be a one-variable change and about a dollar of
gas per year, and even so it is not done: Base Sepolia is already a public chain — anyone can
look these transactions up without asking us — and what mainnet adds is permanence and
economic value, which is not what this project is demonstrating. The decision, and the
condition under which it would be reversed, are in
[the sixth boundary](docs/05-alcance-y-no-objetivos.md).

### How to check a root without believing us

    curl -s <URL>/auditoria/auditoria/prueba/<UUID> > prueba.json
    python tools/verificar_prueba.py prueba.json

That recomputes the leaf and walks the Merkle path. The last step — checking that the root
that path arrives at is the one published on the network — is taken by whoever is verifying,
against the contract and not against us:

    python tools/leer_raiz_publicada.py 2026-08-24 <root-the-proof-declares>

That script imports nothing from the project either: it speaks JSON-RPC to a public Base node
and does not even need `web3`. Anyone who prefers not to run anything can call
`consultar("YYYY-MM-DD")` in the block explorer, which gives the same answer.

Verified this way for the three days anchored so far, identical on both sides:

| Day | Published root |
|---|---|
| `2026-08-22` | `3a540914bb5d42525c08f04c367b4f3069e4a21ebc66b57380b3e9fc2c8851a1` |
| `2026-08-23` | `fe20dcc2dbe7f8c975809d3369e52c2abde47a8f30f3626cd23a85f0572f083c` |
| `2026-08-24` | `d17a61403dbd1c31a00800fd4e37e06aa0938bc97032f7e480b2763e2d849a83` |

The last two were anchored **with no human intervention**; the evidence with correlated logs
is in
[`docs/evidencias/2026-08-24-ciclo-autonomo.md`](docs/evidencias/2026-08-24-ciclo-autonomo.md).

The contract **forbids re-anchoring a day**. If a single day admitted two roots, whoever
holds the ledger could publish one, rewrite history and publish another, and a third party
would not know which to believe. The compiled artifact is versioned with the `sha256` of its
source so that anyone can recompile and compare against what ended up on the chain.

    python tools/compilar_contrato.py
    python tools/desplegar_contrato.py --red base-sepolia

The simulated anchor **declares itself as such** in every response
(`verificable_por_terceros: false`, plus a warning in text) and the verifier exits with code
2 instead of 0. A fake anchor that looked real would be worse than none at all: it would pass
for genuine in a demo video.

The private key lives in Secret Manager and is read with `versions/latest` **on every
anchoring**, not as an environment variable: Cloud Run resolves secrets when the instance
starts, and with `--min-instances=1` that instance lives for days, so rotating the key would
have no effect until a redeploy. It is one request per day.

    python generate_wallet.py --subir      # generates, stores, and reports the address
    python generate_wallet.py --direccion  # which address the secret holds

The key is never written to disk nor passed on the command line. See
[ADR 0006](docs/adr/0006-anclaje-y-prueba.md).

### Verifying a proof without trusting us

```bash
curl -s localhost:8000/auditoria/prueba/<UUID> > prueba.json
```

```bash
python tools/verificar_prueba.py prueba.json
```

That script **does not import a single line of this project** — only `hashlib`, `json` and
`base64`. If verification used our code, it would be checking that our code agrees with
itself, which proves nothing.

And the step that closes the loop, against the network:

```bash
python tools/leer_raiz_publicada.py <YYYY-MM-DD> <root-the-proof-declares>
```

```
record content     →  declared leaf          ✓   verificar_prueba.py
Merkle path        →  declared root          ✓   verificar_prueba.py
declared root      == root on the chain      ✓   leer_raiz_publicada.py
```

---

## Demo data: synthetic, by design

The demo runs on **synthetic** CFDI, not on a real company's invoices. This is not a
concession:

- **It makes the project reproducible.** Anyone clones the repo and brings up the full demo
  without needing anybody's invoices.
- **It allows recording the tampering scenario without censoring anything.**
- **It is consistent with our own privacy notice.** The video is public, and a real CFDI
  carries identifiable financial data (Mexican data protection law, LFPDPPP).

The generated RFCs carry `000000` in the date portion, which the tax authority could never
have issued — there is no day zero of month zero — and which the CFDI 4.0 schema accepts.
This means they **cannot collide with a real person's**.

The data source is an interface with two implementations — synthetic and real — so switching
between them is configuration, not a rewrite. Moving to real data requires prior express
consent (LFPDPPP art. 8, since this is financial data), minimization per the
[dossier data contract](docs/contrato-expediente.md), and retention under the Federal Tax
Code art. 30.

---

## Documentation

*All linked documents are in Spanish.*

- [ADR 0001 — Canonical serialization `CORD-CANON-2`](docs/adr/0001-serializacion-canonica.md)
- [ADR 0003 — Reading CFDI](docs/adr/0003-lectura-de-cfdi.md)
- [ADR 0004 — Hash-chained ledger and assignment registry](docs/adr/0004-bitacora-encadenada.md)
- [ADR 0005 — Intake and assignment endpoints](docs/adr/0005-endpoints.md)
- [ADR 0006 — Inclusion proof and anchoring](docs/adr/0006-anclaje-y-prueba.md)
- [ADR 0007 — The lock domain is not the durability domain](docs/adr/0007-dominio-del-candado-y-dominio-de-la-durabilidad.md) — why `--max-instances=1` is correctness, not cost
- [Architecture](docs/arquitectura.md) — the map, how to read it, and what it leaves out on purpose
- [State handling](docs/03-manejo-de-estado.md) — tasks 3.13 to 3.18
- [Scope and non-goals](docs/05-alcance-y-no-objetivos.md) — the six boundaries the system does not cross, and why
- [Dossier data contract](docs/contrato-expediente.md) — what leaves, what does not, and why
- [Synthetic data](docs/datos-sinteticos.md) — RFCs that cannot belong to anyone, and known gaps
- [Boundary with CØRD Fiscal](docs/trabajo-preexistente.md) — a verifiable declaration
- [Technical manual](docs/manual-tecnico.md) — how it works today, service by service
- [User manual](docs/manual-usuario.md) — how to use it, against the cloud or locally
- [Evidence](docs/evidencias/) — real runs with correlated logs
- [Daily log](docs/bitacora/) — status and decisions, day by day
- [English subtitles](docs/subtitulos/) — SRT track and the on-screen glossary
- [Google Workspace connectors](conectores/apps-script/) — the spreadsheet as a dashboard and a Gmail inbox as CFDI intake, outside the agent, and why

## Pre-existing work

This agent was built entirely during the submission period; the git history shows it.

**CØRD Fiscal** is a **pre-existing** platform from which this agent consumes the company's
accounting books **over HTTP**, at the same level as Postgres or FastAPI. None of its code is
copied or imported here — and you do not have to take our word for it:

```bash
python tools/verificar_frontera.py ../cord_rag_plataform/backend/app
```

As of 14 Aug: 3 matches across 1,062 lines, all three `from datetime import …`. Details in
[docs/trabajo-preexistente.md](docs/trabajo-preexistente.md).

## License

MIT — see [LICENSE](LICENSE).
