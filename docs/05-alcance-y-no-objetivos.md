# Alcance declarado y no-objetivos

**Por qué existe este documento:** un hueco declarado es una decisión de diseño; el mismo
hueco sin declarar es un descuido. La diferencia no está en el código —es idéntico— sino
en si alguien lo pensó y escribió por qué.

Aquí están las seis fronteras que el proyecto **no** cruza, cada una con la razón y con
la condición bajo la cual dejaría de tener sentido. Ninguna es una tarea pendiente que se
nos olvidó: son seis decisiones tomadas, y este documento existe para que no se
reabran por impulso a tres días de la entrega.

**Congelación de alcance: 28 de agosto.** A partir de esa fecha ningún elemento de esta
lista se reconsidera.

---

## 1. La bitácora no migra a Cloud SQL

**Estado:** diferido, con la migración ya escrita.

El proyecto está más cerca de lo que parece: [`migraciones/001_bitacora.sql`](../migraciones/001_bitacora.sql)
existe, con `pg_advisory_xact_lock(hashtext(inquilino))` —candado por inquilino, o sea que
sí escala horizontalmente— y triggers que rechazan `UPDATE` y `DELETE`. Lo que falta es la
capa de Python: 16 puntos de acoplamiento a `sqlite3` en dos archivos, de cuatro clases.

**Por qué no ahora:** esa ruta no está ejercitada por pruebas —hueco declarado desde
[ADR 0004](adr/0004-bitacora-encadenada.md)— y ejercitarla exige levantar un servidor en
CI. Es abrir un frente nuevo por un problema que el snapshot a GCS ya resuelve
([3.13 y 3.14](03-manejo-de-estado.md), cerradas el 26-ago).

**Cuándo cambia:** en cuanto haya más de un inquilino real escribiendo. El candado por
inquilino es precisamente lo que `max-instances=1` no puede dar, y ahí la migración deja de
ser estilo y pasa a ser necesidad. Es el primer trabajo de después del hackathon.

## 2. El cliente de CØRD Fiscal no se conecta al sistema real

**Estado:** frontera deliberada, declarada en [trabajo-preexistente.md](trabajo-preexistente.md).

La fuente de libros es una interfaz con dos implementaciones —sintética y real—. La real
está escrita y **probada contra transporte falso**: se ejercita el contrato HTTP, los
códigos de error y el mapeo de veredictos, sin depender de que un servicio ajeno esté
arriba.

**Por qué no ahora:** conectarlo abre una superficie de fallo nueva la semana de la
entrega, y no prueba nada que el transporte falso no pruebe ya. Lo que demuestra el
proyecto es que el agente distingue *«los libros dicen que no hay respaldo»* de *«no pude
preguntarle a los libros»* — y eso se demuestra mejor forzando el segundo caso que
esperando a que ocurra.

**Cuándo cambia:** cuando exista un entorno de CØRD Fiscal con datos de prueba estables.
Conectarlo contra producción de un sistema con información fiscal real, para una demo,
sería exactamente el tipo de decisión que este proyecto argumenta en contra.

## 3. No hay autenticación por financiador

**Estado:** limitación conocida, no una tarea.

Hoy leer es libre y escribir exige un token compartido. El sistema sabe que *alguien
autorizado* registró una cesión; no sabe **cuál** financiador fue.

**Por qué no ahora:** identidad por financiador implica un modelo de identidad, emisión y
rotación de credenciales, y una columna de autoría en la bitácora — que es un cambio de
esquema sobre una cadena de hashes ya anclada en una red pública. El cambio es correcto y
es caro, y ninguna de las dos cosas mejora en la semana de entrega.

**Lo que sí se sostiene sin esto:** la cadena prueba que un registro no fue alterado
después de escribirse. No prueba quién lo escribió. Las dos afirmaciones son distintas y
el proyecto solo hace la primera — en el README, en el video y ante el jurado.

## 4. No se emiten ni timbran CFDI reales

**Estado:** decisión, no carencia. Se defiende, no se disculpa.

Tres razones independientes, y cada una basta sola:

| | |
|---|---|
| **No hay CSD** | Sin Certificado de Sello Digital no se puede sellar un CFDI, y obtener uno exige ser el contribuyente |
| **Timbrar es un acto fiscal** | Un CFDI timbrado existe ante el SAT, con consecuencias contables y de cancelación reales |
| **El anclaje es irreversible** | Publicar la huella de datos patrimoniales de un tercero en una cadena pública no se deshace |

La tercera es la que importa para el argumento del producto: un sistema cuya tesis es *«el
registro que se publica no se puede retirar»* no puede publicar datos de terceros para
lucirse en una demo.

**Lo que sí se afirma**, y [3.18](03-manejo-de-estado.md) lo vuelve preciso: los XML son
CFDI 4.0 **estructuralmente válidos ante los XSD oficiales del SAT**; lo único sintético
son el RFC y el sello. Los RFC llevan `000000` en la porción de fecha — el SAT no pudo
haberlos asignado nunca, a nadie. Ver [datos-sinteticos.md](datos-sinteticos.md).

## 5. El alcance funcional del agente está cerrado

**Estado:** congelado el 28-ago.

El agente hace tres cosas y las tres son de solo lectura: consulta el estado de un folio,
explica un veredicto y reporta la integridad de la cadena. **Ninguna afirmación de
integridad pasa por el modelo** — el hash, el encadenamiento, la detección de manipulación
y la prueba de Merkle son código determinista con pruebas. El modelo orquesta y redacta;
no decide si un CFDI está respaldado.

**Por qué no se amplía:** cada herramienta nueva es una superficie donde el modelo podría
afirmar algo que el código no verificó. La contención —tres herramientas, todas de lectura—
es la propiedad de seguridad, no una etapa temprana de un plan más grande.

---

## 6. El anclaje se queda en testnet; no sube a mainnet

**Estado:** decidido. Mainnet es el cambio de una variable, y aun así no se hace.

Conviene precisar qué frontera es esta, porque se confunde con otra. **Base Sepolia ya es
una cadena pública:** las transacciones son reales, cualquiera las consulta en
`sepolia.basescan.org` sin pedirnos nada, y el sistema las reporta con
`verificable_por_terceros: true` y el semáforo en verde. Lo que separa testnet de mainnet
no es la verificabilidad — es la permanencia y el valor económico.

El ancla **simulada** sí es otra cosa, y esa no se usa en producción: se declara falsa en
la respuesta HTTP y tiñe el semáforo de ámbar precisamente para que nadie la confunda con
esto.

El código soporta mainnet de punta a punta: `base` está en `REDES` (chain 8453) y en
`EXPLORADORES` ([`ancla_evm.py`](../src/agente_cfdi/bitacora/ancla_evm.py),
[`anclaje.py`](../src/agente_cfdi/bitacora/anclaje.py)). No falta ingeniería.

**Por qué no ahora:** porque cambiar de red **no migra los anclajes existentes**, y ese
costo es mayor que el beneficio a cuatro días del envío. El contrato es por red y
`anclar()` es por día e irrepetible por diseño: los anclajes del 17 y del 24 se quedan en
Sepolia para siempre. Cambiar hoy significa llegar a la entrega con dos o tres días en
mainnet y el resto del rastro en otra red — la evidencia del ciclo autónomo, que es el
argumento más fuerte del proyecto, partida entre dos exploradores sin una razón visible.

Se suma que `dueno` es `immutable` y se fija en el constructor
([`AnclaDeRaices.sol`](../contratos/AnclaDeRaices.sol)): el contrato de mainnet tendría que
desplegarse desde la misma wallet que firma los anclajes, o el job revierte con
`NoEsElDueno()` todas las noches. Es un paso más, con dinero real y una dependencia externa,
para una propiedad que nadie va a comprobar en la evaluación.

**Cuándo cambia:** los testnets se retiran. Base Sepolia no va a existir para siempre, así
que un ancla ahí es evidencia con fecha de caducidad — y una bitácora cuyo propósito es
sobrevivir al tiempo no puede depender de una red que no lo hará. El día que haya un
financiador real tomando decisiones de crédito contra estas raíces, mainnet deja de ser
cosmético y pasa a ser el soporte del producto. Cuesta alrededor de 1 USD al año. Va
inmediatamente después del hackathon, junto con Cloud SQL.

## Lo que estas seis fronteras tienen en común

Ninguna es un límite de esfuerzo. Las seis son el mismo criterio aplicado a seis lugares
distintos: **el sistema no afirma más de lo que puede demostrar.** Una bitácora que no
sobrevive al reinicio no debe decir «íntegra». Un cliente HTTP no probado contra el sistema
real no debe presentarse como integrado. Una cadena que no sabe quién escribió no debe
sugerir que sí. Un CFDI sintético no debe presentarse como timbrado. Un ancla simulada no debe pintarse
del mismo color que una publicada.

Es la misma regla que hace que el semáforo tenga un color gris para «sin cadena que
verificar» ([3.16](03-manejo-de-estado.md)), y que el sistema se niegue a anclar una cadena
rota en vez de publicarla en silencio.
