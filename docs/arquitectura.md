# Arquitectura

**Tarea 3.2** · 26 de agosto de 2026

Un diagrama de arquitectura casi siempre es un inventario de cajas: aquí está todo lo que
usamos. Ese diagrama no dice nada que el `requirements.txt` no diga mejor.

Este intenta otra cosa. Está dibujado para que **dos decisiones se vean antes de leerse**,
porque son las dos que sostienen el producto y las dos que un jurado tiene que creerse:

1. **La línea de confianza.** La verificación ocurre del lado de afuera. Si el dibujo no
   muestra dónde termina nuestra infraestructura, no muestra el producto.
2. **El modelo está fuera de la ruta del dato.** Gemini cuelga del pipeline, no vive dentro.
   Esa es la afirmación de seguridad del proyecto — *ninguna afirmación de integridad pasa
   por el modelo*— y aquí se puede ver, no solo leer.

---

## El mapa

![Arquitectura del agente](arquitectura.svg)

*Fuente: [`arquitectura.svg`](arquitectura.svg). Vectorial y con geometría fija a propósito —
la cámara del video hace push-in sobre nodos concretos y necesita coordenadas conocidas, y un
vector aguanta cualquier acercamiento sin pixelarse.*

> **Por qué está dibujado a mano y no generado.** El primer intento fue Mermaid. El
> auto-layout puso `Cloud Scheduler` **fuera** del recuadro de nuestra infraestructura,
> mandó Base Sepolia a la izquierda —con el anclaje leyéndose de derecha a izquierda— y cruzó
> la prueba de Merkle en diagonal por encima de todo. Un diagrama cuyo layout no controlas no
> puede sostener un argumento que depende de qué está de qué lado de una línea.

---

## Cómo leerlo

**La flecha gruesa que sale de `CÓDIGO DETERMINISTA` hacia `BASE SEPOLIA` lleva una
condición: *si y solo si la cadena cuadra*.** Ese `si y solo si` es el producto. El cierre
diario recalcula la cadena entera antes de anclar, y si un solo eslabón no cuadra devuelve
`500`, nombra la fila y **no ancla**. Publicar la raíz de una cadena manipulada sería peor
que no publicar nada: convertiría el sistema en un sello de aprobación sobre un dato falso.

**Las dos flechas que llegan al verificador vienen de lados distintos, y esa es la
demostración.** Una trae la prueba de Merkle desde nosotros. La otra trae la raíz desde Base,
por `eth_call`, sin tocar nuestro servicio. Si las dos coinciden, el registro es íntegro **y
no hubo que creernos**. Si el verificador importara nuestro código, comprobaría que nuestro
código coincide consigo mismo, que no demuestra nada.

**El agente cuelga de la bitácora con una flecha punteada, y va en un solo sentido.** No está
entre los datos y la cadena; está al lado, leyendo. Sus tres herramientas —estado de
integridad, consulta de folio, resumen de la bitácora— son de solo lectura. El modelo
orquesta y redacta; no decide si un CFDI está respaldado. Cada herramienta nueva sería una
superficie donde el modelo podría afirmar algo que el código no verificó, y por eso el
alcance está congelado en tres.

**`CØRD Fiscal` entra por un lado, no por el centro.** Es una plataforma preexistente que
este proyecto consume por HTTP, al mismo nivel que consume Postgres o cualquier servicio
ajeno — declarado y verificable en [trabajo-preexistente.md](trabajo-preexistente.md). En el
código es una interfaz con dos implementaciones, sintética y real, así que cambiar de fuente
es configuración y no reescritura. Por eso el dibujo la pone como una entrada intercambiable
y no como un cimiento.

**`Cloud Storage` tiene flecha de ida y vuelta con la bitácora.** La bitácora vive en `/tmp`
de Cloud Run, que una revisión nueva borra. El snapshot va de ida al cerrar y de vuelta al
arrancar, y por eso la cadena sobrevive a un despliegue en la misma altura, con las pruebas
todavía validando contra la cadena pública. Es la respuesta al hueco más real que tenía el
proyecto — y la razón por la que no se migró a Cloud SQL a tres días de la entrega está en
[ADR 0007](adr/0007-dominio-del-candado-y-dominio-de-la-durabilidad.md).

---

## Lo que el diagrama deja fuera a propósito

Un diagrama legible sin pausar no aguanta más de una docena de cajas. Estas se omitieron, y
conviene que quede escrito para que nadie las agregue después creyendo que se olvidaron:

| Omitido | Por qué |
|---|---|
| Cloud Monitoring y sus dos políticas | Es observabilidad del job, no ruta del dato. Está en el README |
| Cloud Build y el `Dockerfile` | Cómo llega el código a producción, no cómo corre |
| `main.py` vs `app.py` — dos apps, un despliegue | Detalle de montaje HTTP. Importa para operar, no para entender la garantía |
| El generador sintético | Vive dentro del pipeline como una implementación de la fuente |
| Los endpoints uno por uno | La tabla del README los tiene, y son quince |

---

## En el video: 20 segundos, cinco tiempos

Va en el Acto III, **entre P16 y P17**, como secuencia `P16a`–`P16e`. P16 termina con
*«Entonces dejamos de hacerlo solos»* — el mapa contesta la pregunta que esa línea deja
abierta: *solos, ¿entonces quién?*. Y desemboca en P17, que es la captura real del mismo
pipeline funcionando. Mapa primero, territorio después.

**No cuesta ningún plano.** El criterio 3.1 pide el video cronometrado bajo cuatro minutos y
el corte va en 2:24; con esto queda en **2:44**. Los 20 segundos son aditivos.

**No viola la regla 2.3.** El tratamiento elimina el Nivel C —«no hay bloques dorados
flotando»— pero deja abierta la excepción exacta que esto usa: *«si algo tiene que ser
abstracto, es un movimiento de cámara, no una textura»*. Esto es un movimiento de cámara
sobre un plano fijo, no una animación de bloques.

### La idea: la línea de confianza se esconde hasta el final

Durante los cuatro primeros tiempos la cámara está **lo bastante cerca como para que el
recuadro punteado nunca se vea**. Solo aparece en el alejamiento. Así el pull-back no es
«aquí está todo junto» —que es lo que hace un diagrama aburrido— sino un **remate**: todo lo
que acabas de ver está de un lado de una línea, y la verificación está del otro.

El dibujo se guarda su propio argumento para el último segundo. Es la misma jugada que P20,
donde la cámara sale por la ventana: un alejamiento que cambia el significado de lo que ya
habías visto.

### Los cinco tiempos

| # | Tiempo | Dur. | Sobre qué está la cámara | Qué tiene que quedar claro | VO |
|---|---|---|---|---|---|
| **P16a** | 1:06–1:09 | 3s | `Cloud Scheduler`, y la flecha bajando al pipeline | Alguien programó las horas una vez; nadie las dispara | «Nadie lo enciende.» |
| **P16b** | 1:09–1:13 | 4s | El pipeline. Paneo lateral corto siguiendo `leer → validar → auditar → encadenar → Merkle` | Es una tubería, y es código | «Ingesta, validación, auditoría, registro.» |
| **P16c** | 1:13–1:17 | 4s | El agente ADK + Gemini. La flecha **punteada**, de un solo sentido, saliendo de la bitácora | El modelo está **al lado**, no en medio. Es el plano de la afirmación de seguridad | «El modelo explica. No decide.» |
| **P16d** | 1:17–1:21 | 4s | La flecha gruesa hacia `Base Sepolia`. La etiqueta *si y solo si la cadena cuadra* entra en foco | El anclaje tiene una condición, y la condición es el producto | «Y solo si la cadena cuadra, publica.» |
| **P16e** | 1:21–1:26 | 5s | **Alejamiento continuo** hasta el mapa completo. El recuadro punteado aparece por primera vez | Todo lo anterior era «nuestro». Lo de la derecha no necesita permiso | *silencio* |

**El silencio en P16e es deliberado**, y es la misma decisión que en P21 (*«sin narración
encima: que se lea»*). El remate no se explica.

### Cómo se dibuja

- **Paleta del registro cálido, sin excepción.** Ámbar `#E8B071`, coral `#C46A4A`, madera
  `#8A6A4F`, sobre fondo oscuro. **Cero azul** — el mapa cae dentro de la regla Her del
  tratamiento. No es un diagrama de tecnología, es un plano de dibujante iluminado de lado.
- **El coral se reserva para la flecha del anclaje.** Es el único elemento que sale de
  nuestra infraestructura, y el rojo saturado sigue reservado para el Acto IV.
- **Rotulado en inglés desde el origen.** El mapa es artefacto nuestro, no interfaz del
  sistema: se autora en inglés y así no necesita rótulo quemado encima, a diferencia de las
  cinco capturas reales. Ver [`subtitulos/README.md`](subtitulos/README.md).
- **Un solo plano fijo, cámara moviéndose encima.** No hay cortes entre los cinco tiempos:
  es un recorrido continuo. Cortar entre nodos lo convertiría en presentación.
- **Nada aparece ni desaparece.** El mapa completo existe desde el primer fotograma; lo
  único que cambia es qué parte encuadra la cámara. Si los nodos «se construyen» uno por
  uno, vuelve a ser Nivel C.

### Lo que esto arrastra

| Consecuencia | Qué hacer |
|---|---|
| Todo lo posterior a 1:06 se recorre **+20 s** | Reetiquetar la escaleta de P17 en adelante. El corte final va a 2:44 |
| Las 20 entradas del SRT se desincronizan | Ya está previsto: la tarea de reajustar tiempos del SRT a la VO real |
| P17 se queda sin su línea de VO | Se la lleva P16b, que es donde el dato encaja con la imagen. **Recomendación:** P17 corre sin narración —la captura real ya habla— o con una línea corta nueva |
| Los flashbacks decrecientes (0.8 s en P19, 0.4 s en P23 y P26) | No se tocan: son relativos a sus planos y se mueven con ellos |

---

## Y fuera del video

La restricción de legibilidad sirve igual en papel, porque un jurado tampoco pausa un README:
**diez cajas, una sola dirección de flujo de izquierda a derecha, y cero líneas cruzadas** —
verificado sobre el render, no supuesto. Las entradas se explican dentro de su propia caja en
vez de colgar la explicación de una flecha: a tres segundos por nodo, una caja que se lee sola
gana a una flecha rotulada.

El mismo mapa va en el README, en el texto de la submission, y —si preguntan en vivo— es la
respuesta de un minuto.
