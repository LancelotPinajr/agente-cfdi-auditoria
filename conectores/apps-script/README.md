# Conectores de Google Workspace

Dos conectores que enchufan la auditoría a las herramientas que una PYME ya usa:
una **hoja de cálculo como tablero** y un **buzón de Gmail como entrada de CFDI**.

Ninguno de los dos vive dentro del agente, y esa es la decisión de diseño que
sostiene todo lo demás — ver [«Dónde encaja esto»](#dónde-encaja-esto).

## Los archivos

| Archivo | Qué hace | ¿Escribe? |
|---|---|---|
| [`configuracion.gs`](configuracion.gs) | URL del motor, límites del lote, acceso al token, log de eventos | — |
| [`panel.gs`](panel.gs) | Vuelca semáforo, raíces ancladas y padrón de folios en la hoja | no |
| [`ingestor.gs`](ingestor.gs) | Gmail y pestaña «Cola» → `POST /auditoria/ingesta` | sí |

## Instalación

1. Hoja nueva en Google Sheets → **Extensiones → Apps Script**.
2. Pegar los tres `.gs` como tres archivos del proyecto.
3. **Configuración del proyecto → Propiedades del script** → añadir
   `AGENTE_CFDI_TOKEN_ESCRITURA` con el token del despliegue.
   El token **no va en el código**: el código se ve con la hoja, las propiedades no.
4. En Gmail, crear la etiqueta `cfdi-entrada` y un filtro que la aplique a los
   correos con CFDI adjuntos. La etiqueta `cfdi-procesado` se crea sola.
5. Recargar la hoja → menú **CØRD → Instalar disparadores**.
   Panel cada 10 min, buzón cada 15.

## Las pestañas

- **Semáforo** — el tablero. Color, título y detalle tal como los emite el motor,
  más altura, punta, inquilino y estado del ancla del día en curso.
- **Anclajes** — el historial de raíces publicadas: día, raíz de Merkle, cuántos
  registros colgaban de ella, red, y el enlace al explorador cuando lo hay.
- **Folios** — el padrón. Columnas A–D las llena el ingestor; E–H las refresca el
  panel con el estado de cesión de cada UUID.
- **Cola** — carga manual. Pegar el XML en la columna A; la C se marca al enviarse.
- **Eventos** — qué hizo cada conector y cuándo. Sin esto, un ingestor que falla
  en silencio es indistinguible de un buzón vacío.

## Dónde encaja esto

El alcance funcional del agente está congelado
([frontera #5](../../docs/05-alcance-y-no-objetivos.md)): tres herramientas,
todas de solo lectura, y esa contención **es** la propiedad de seguridad — cada
herramienta nueva sería una superficie donde el modelo podría afirmar algo que
el código no verificó.

El ingestor escribe en la bitácora. Meterlo como herramienta del modelo rompería
justo ese argumento. Por eso es un cliente HTTP ordinario que llama a la misma
puerta de siempre, `/auditoria/ingesta`, con el token de escritura — exactamente
como entra hoy un lote sintético. **El modelo no lo ve, no lo invoca y no puede
invocarlo.**

Los CFDI del buzón son sintéticos, por la
[frontera #4](../../docs/05-alcance-y-no-objetivos.md): anclar la huella de datos
patrimoniales de terceros en una cadena pública no se deshace.

## Por qué el panel no lleva token

Porque no escribe. [`autenticacion.py`](../../src/agente_cfdi/api/autenticacion.py)
traza la línea en la operación y no en el servicio: consultar el semáforo,
verificar la cadena entera y consultar lo anclado son públicos a propósito,
porque que cualquiera pueda verificar es el punto entero del proyecto.
