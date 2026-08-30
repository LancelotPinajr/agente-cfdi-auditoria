# Subtitulado en inglés — requisito 3.7

El criterio 3.7 del plan de equipo exige **inglés o subtítulos en inglés**. Todo el
material del proyecto está en español: README, manuales, evidencias, la interfaz del
sistema y la voz en off del video. Este directorio cubre el requisito.

Dos capas distintas, y la segunda es la que casi nadie hace:

1. **La voz en off** → [`subtitulos-en.srt`](subtitulos-en.srt). Traducción de las 20
   entradas de VO, sincronizada al montaje de `Documentacion/tratamiento-visual-video.md`.
2. **La interfaz del sistema** → los rótulos quemados de este documento. Sin esto, los
   cinco planos de captura real —que son la prueba— son ilegibles para un jurado que no
   lee español, y esos planos son justamente el 30% de *demo y production readiness*.

---

## 1. La voz en off

Archivo: `subtitulos-en.srt`, formato SRT estándar, 20 entradas.

**Cómo cargarlo:** subir a YouTube como pista de subtítulos, **no** quemarlo en el
video. Que sea una pista permite al jurado activarla o no, y YouTube la indexa.
Si la plataforma de entrega no acepta pista externa, quemarlo abajo al centro.

**Estilo:** blanco, sin caja, sombra suave, dos líneas máximo. Nunca sobre la zona
donde va texto de la interfaz en los planos de captura.

**Nota de traducción — la entrada 13 no traduce voz.** En el plano P21 (explorador de
Base Sepolia) la decisión de dirección fue dejarlo **sin narración**: que se lea. Para
un espectador que no lee español no hay nada que leer, así que ahí el subtítulo lleva
un rótulo entre corchetes que dice qué está viendo. Es la única entrada del SRT que no
corresponde a una línea de VO, y es deliberada.

---

## 2. Rótulos quemados sobre las capturas reales

Estos **sí** van quemados en el video, porque explican una interfaz que no se puede
retraducir. Tipografía monoespaciada, esquina superior izquierda, fondo semitransparente.
Aparecen 0.5 s después del corte y se quedan todo el plano.

| Plano | Rótulo en inglés |
|---|---|
| **P17** 1:06–1:12 | `INTAKE → VALIDATION → AUDIT → HASH-CHAINED LEDGER` |
| **P18** 1:12–1:17 | `DOUBLE-ASSIGNMENT DETECTED — same invoice UUID, second attempt rejected` |
| **P21** 1:32–1:37 | `PUBLIC BLOCKCHAIN EXPLORER (Base Sepolia) — not our infrastructure` |
| **P24** 1:46–1:52 | `TAMPERING DETECTED — HTTP 500, chain_broken, flagged row: 3` |
| **P25** 1:52–1:58 | `ANCHORING REFUSED — the system will not publish a tampered chain` |

---

## 3. Glosario de la interfaz — español → inglés

Los términos que aparecen literalmente en pantalla durante las capturas. Sirven para los
rótulos, para el texto de la submission (3.5) y para responder preguntas del jurado.

### Semáforo de integridad

| En pantalla | Inglés |
|---|---|
| `CADENA ÍNTEGRA Y PUBLICADA` | CHAIN INTACT AND PUBLISHED |
| `MANIPULACIÓN DETECTADA` | TAMPERING DETECTED |
| `color: verde / rojo` | status: green / red |
| `altura` | chain height |
| `verificados` | links recomputed and verified |
| `posicion_del_problema` | position of the broken link |

### Eventos del ciclo diario

| En pantalla | Inglés |
|---|---|
| `ciclo.inicio` | cycle.start |
| `ciclo.auditoria` | cycle.audit |
| `ciclo.cesion` | cycle.assignment |
| `ciclo.fin` | cycle.end |
| `cierre.anclado` | close.anchored |
| `comprobantes` | invoices in the batch |
| `auditados` / `hallazgos` / `rechazados` | audited / findings / rejected |
| `primera_aceptada` / `segunda_aceptada` | first assignment accepted / second rejected |
| `origen_del_lote: sintetico` | batch origin: synthetic |

### Anclaje

| En pantalla | Inglés |
|---|---|
| `raiz` | Merkle root |
| `referencia` | transaction hash |
| `red: base-sepolia` | network: Base Sepolia |
| `ya_estaba: false` | already anchored: false (the contract forbids re-anchoring a day) |
| `verificable_por_terceros` | independently verifiable |
| `cadena_rota` | chain_broken |

### Registro canónico y veredicto

| En pantalla | Inglés |
|---|---|
| `CORD-CANON-2` | frozen canonical serialization, version 2 |
| `veredicto: respaldado` | verdict: backed by the books |
| `veredicto: sin_respaldo` | verdict: not backed |
| `monto_en_libros` | amount found in the books |
| `fuente_de_libros` | source of the books |
| `NO son libros reales` | THESE ARE NOT REAL BOOKS |
| `inquilino` | tenant |

> `NO son libros reales` viaja dentro del propio registro canónico y por lo tanto
> **dentro del hash anclado**. No es una etiqueta añadida después: la declaración de que
> los datos son sintéticos está firmada junto con el dato. Vale la pena decirlo en el
> video — es el tipo de detalle que un jurado técnico premia.

---

## 4. Lo que falta decidir

**El README y los manuales siguen en español.** El criterio 3.7 aplica al video, no al
repositorio, así que estrictamente no es obligatorio. Pero un jurado que no lee español
va a abrir el README. La opción barata es un bloque `## In English` al inicio del README
con diez líneas: qué hace, cómo verificarlo sin confiar en nadie, y los tres comandos de
reproducción. No traducir 38 KB de manual técnico.
