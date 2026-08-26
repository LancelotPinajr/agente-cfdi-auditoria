# Ruta al premio — del 24 al 30 de agosto

**Escrito el 24 de agosto**, último día del Sprint 2. Congelación el 28. Envío el 30.

---

## El cálculo que decide todo lo demás

| Rubro | Peso | Dónde estás | Puntos que quedan sobre la mesa |
|---|---|---|---|
| Innovación y ejecución autónoma | 40% | **fuerte** — 3 días desatendidos, detección de doble cesión en vivo | pocos |
| Disciplina arquitectónica y estado | 30% | **fuerte con un flanco** — 375 pruebas, canon congelado, ADRs | algunos, y baratos |
| Demo y production readiness | 30% | **a la mitad** — documentación completa, **el video no existe** | **casi todos** |

**La conclusión incómoda:** cada hora que le metas al agente vale casi cero. Ya ganaste
ese rubro. Cada hora que le metas al video vale mucho, porque ahí tienes un cero.

El instinto de ingeniero es seguir mejorando el sistema. Ese es el error que hace perder
hackathons con buen código. **A partir de hoy el proyecto no se mejora: se demuestra.**

---

## Lo primero, en los próximos 30 minutos

### Paso 0 — Empujar y abrir PR a `main`

Ahora mismo `origin/main` no tiene la evidencia del 24, ni la dirección del contrato en el
README, ni el subtitulado, ni las tareas de estado. Todo eso vive en la rama `ricardo` de
una laptop.

**Un jurado que abra el repo hoy ve un proyecto que se detuvo el 21 de agosto.** Y tu
propia Definition of Done dice: *«está en el repo público, no en la máquina de nadie»*.

Es la acción con más puntos por minuto de todo el proyecto y cuesta dos minutos.

```bash
git -C D:/CORD/agente-cfdi-ricardo push origin ricardo
```

Luego PR de `ricardo` a `main` y merge. **La rama por defecto es lo que se evalúa.**

### Paso 0b — Confirmar los accesos de la tarea 1.2

Verificar que `testing@devpost.com` y `cloudhackathons@google.com` tienen acceso al repo.
Es un requisito de elegibilidad del Sprint 1 que nadie ha vuelto a mirar desde el día 2.
Si el repo es público no hace falta, pero **confírmalo**, no lo supongas: es el tipo de
detalle administrativo que descalifica un proyecto técnicamente impecable.

---

## Día 24 — hoy, lo que queda de tarde

| | Tarea | Quién | Horas |
|---|---|---|---|
| 1 | **Paso 0** — push, PR, merge a `main` | Ricardo | 0.2 |
| 2 | **3.16** — el semáforo distingue «vacía» de «íntegra» | Gilfoyle | 2 |
| 3 | **3.15** — ADR 0007, el invariante de un solo escritor | Gilfoyle | 2 |
| 4 | **Los 4 stills de referencia** de Elena y Diego | Ricardo | 2 |

**Por qué 3.16 hoy y no mañana:** hoy tu semáforo diría *verde* sobre una cadena vacía,
porque una cadena de altura 0 verifica trivialmente. Verde por haberlo perdido todo es el
fallo exacto que este producto existe para no cometer. Si el jurado lo encuentra antes que
tú, se cae el argumento entero — y el argumento es el producto.

**Por qué los stills hoy:** la generación con Veo 3 es iterativa y lenta. Todo plano con
rostro depende de esos cuatro stills. Es la dependencia más larga del proyecto y no
requiere que el código esté listo. Arráncala en paralelo.

---

## Día 25 — persistencia y el texto que el jurado lee primero

| | Tarea | Quién | Horas |
|---|---|---|---|
| 5 | **3.13 + 3.14** — restauración al arranque y respaldo a GCS | Dinesh + Gilfoyle | 6 |
| 6 | **3.5** — texto de la submission | Ricardo | 3 |
| 7 | Seguir generando planos del Acto I y II | Ricardo | — |

**Sobre 3.5:** el jurado lee el texto de la submission **antes** de ver el video. Es la
primera impresión y hoy no existe. Tiene que abrir con el fraude que resuelves —la misma
cuenta por cobrar vendida dos veces— no con el stack. El stack va al final.

---

## Día 26 — mainnet y la evidencia que vale un plano

| | Tarea | Quién | Horas |
|---|---|---|---|
| 8 | **3.6 — ANCLAJE EN MAINNET** | Dinesh | 3 |
| 9 | **3.17** — evidencia de supervivencia al despliegue | Ambos | 4 |
| 10 | **3.2** — diagrama de arquitectura | Gilfoyle | 2 |
| 11 | Generar planos del Acto III y V | Ricardo | — |

**3.6 es la mejora de credibilidad más barata que te queda.** Cuesta alrededor de 1 USD de
gas al año. Convierte *«lo anclamos en testnet»* en *«está publicado en Base, en producción,
aquí está el enlace»*. Ningún otro dólar del proyecto compra tanto.

Hazlo **antes** de grabar. Si el video muestra el explorador de mainnet en vez de Sepolia,
el argumento entero cambia de registro.

**3.17 no es solo una tarea de ingeniería: es un plano de video que hoy no tienes.**
Desplegar una revisión nueva en cámara —lo cual borra `/tmp`— y que la cadena siga en la
misma altura con la prueba de Merkle validando contra la cadena pública. Tu punto más
débil convertido en demostración en vivo. Ese plano, si sale, es el segundo momento más
fuerte del video después de la manipulación.

---

## Día 27 — grabar lo real

| | Tarea | Quién | Horas |
|---|---|---|---|
| 12 | Grabar **las 5 capturas reales** (P17, P18, P21, P24, P25) | Ambos | 4 |
| 13 | Grabar el plano de supervivencia al despliegue (3.17) | Ambos | 1 |
| 14 | **3.3** — que alguien ajeno levante el proyecto con el README | Ricardo | 2 |
| 15 | Terminar de generar planos faltantes | Ricardo | — |

Las capturas se graban **después** de mainnet y **después** de la persistencia, para que lo
que se ve en pantalla sea el sistema final y no haya que regrabar. Máximo 4x de
aceleración, sin cortes dentro de una operación.

**3.3 se prueba con una persona real.** Consigue a alguien que no haya tocado el proyecto y
míralo intentar levantarlo sin ayudarle. Donde se atore, ahí está el hueco del README. Es
production readiness literal.

---

## Día 28 — congelación y montaje

**Nada de código nuevo a partir de hoy.** Lo que no esté, no entra.

| | Tarea | Horas |
|---|---|---|
| 16 | Montaje: los 29 planos, los 3 flashbacks decrecientes | 4 |
| 17 | Grabar la voz en off de Elena | 1 |
| 18 | Reajustar los tiempos del SRT a la VO real | 1 |
| 19 | Rótulos quemados en inglés sobre las 5 capturas | 1 |
| 20 | **3.7** — subir a YouTube público con la pista de subtítulos | 1 |

---

## Día 29 — margen

Reservado para lo que salga mal. **No se planea nada.** Si todo salió bien, se usa para
revisar el video completo con ojos frescos y arreglar el README.

## Día 30 — envío

**3.8 — enviar.** Un día completo antes del cierre del 31, como dice el plan.

---

## Lo que NO vas a hacer, y por qué

Se declara para que nadie lo intente en un arranque de ambición a dos días del cierre:

- **No migrar a Cloud SQL.** Arriesga 375 pruebas por un punto de estilo. Declarado como
  siguiente paso en `03-manejo-de-estado.md`.
- **No conectar CØRD Fiscal real.** El cliente HTTP está probado con transporte falso.
  Conectarlo ahora abre una superficie de fallo nueva la semana de la entrega.
- **No autenticación por financiador.** No tiene tarea y no debe tenerla.
- **No CFDI reales.** No hay CSD, timbrar es un acto fiscal con consecuencias, y publicar
  datos patrimoniales en un anclaje irreversible sería un error grave. Los sintéticos son
  la decisión correcta y hay que defenderla, no disculparla.
- **No más funcionalidad del agente.** Ya ganaste ese rubro.

---

## Los cinco argumentos con los que se gana

Si el video y la submission dicen estas cinco cosas con claridad, el proyecto compite:

1. **Resuelve el fraude real del factoraje** — la misma cuenta por cobrar vendida dos
   veces — y lo detecta en vivo, sin que nadie mire.
2. **Corrió solo tres días seguidos.** Un día es suerte. Tres es un sistema.
3. **El verificador independiente no importa una línea del proyecto.** Solo `hashlib`,
   `json` y `base64`. Si usara tu código, comprobaría que tu código coincide consigo
   mismo, que no demuestra nada.
4. **Se niega a firmar una cadena rota**, y nombra la fila exacta donde se rompió.
   Publicar la raíz de una cadena manipulada sería peor que no publicar nada.
5. **Ninguna afirmación de integridad pasa por el modelo.** El hash, el encadenamiento, la
   detección y la prueba de Merkle son código determinista con pruebas. El modelo orquesta
   y redacta; no decide si un CFDI está respaldado.
