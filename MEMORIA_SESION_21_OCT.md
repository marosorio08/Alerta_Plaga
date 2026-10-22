# 📔 MEMORIA DE SESIÓN — 21 de octubre de 2026

> **Equipo 7_7** (`equipo02`) · Rafael Martínez (Rol A) · Emmanuel Osorio (Rol B)
> **Reto:** «Alerta Plaga» — IT Green × DIMA UACh
> **Corte de este documento:** 21-oct-2026, 18:45 (hora del centro)
> **Carácter:** bitácora del día. **No contiene credenciales**; las llaves viven en `.env`.

Este archivo cuenta **todo lo que se hizo, probó, rompió y corrigió el 21 de octubre**,
y explica **cómo se conecta con los demás `.md` del proyecto**. Es el puente entre la
historia del día 20 (`HISTORIA_DEL_PROYECTO.md`), el estado operativo
(`CHECKPOINT_SESION.md`) y el reporte de defensa (`REPORTE_FINAL.md`).

---

## 0. Cómo leer la documentación (mapa de conexiones)

```text
README.md ................ puerta de entrada técnica (estructura y uso)
   │
   ├── docs/ARQUITECTURA.md ... flujo oficial de 5 pasos (recibir → interpretar → decidir → guardar → registrar)
   ├── docs/NIVEL2.md ......... fórmulas de prioridad, semáforo, técnico y brote
   │
   ├── HISTORIA_DEL_PROYECTO.md ... bitácora narrativa del DÍA 20
   │        └── MEMORIA_SESION_21_OCT.md  ◀── ESTE DOCUMENTO (día 21)
   │                   └── REPORTE_FINAL.md ... síntesis para la defensa del viernes
   │
   ├── CHECKPOINT_SESION.md ... snapshot operativo para levantar una sesión nueva
   │        └── este documento lo actualiza del corte 14:30 al corte 18:45
   │
   ├── MEMORIA_VERIFICACION.md ... “jurisprudencia”: detalle de casos dudosos, brotes y complementos
   └── MEMORIA_HACKATHON.md ..... contexto y credenciales (gitignored, NO publicar)
```

| Documento | Qué contiene | Cuándo leerlo | Relación con esta memoria |
|---|---|---|---|
| `README.md` | Estructura del repo y uso rápido | Primera vez en el proyecto | Vista técnica de conjunto |
| `HISTORIA_DEL_PROYECTO.md` | Narrativa completa del día 20 (17:00–21:35), decisiones y errores | Para entender *por qué* existe cada módulo | Este documento **continúa** esa historia con el día 21 |
| `MEMORIA_HACKATHON.md` | Contexto, reglas, accesos y credenciales | Arranque de una sesión nueva | Contexto; **no** contiene el estado del día 21 |
| `CHECKPOINT_SESION.md` | Estado operativo, infraestructura, comandos y pendientes (corte 14:30) | **Primero**, al retomar | Este documento es su **continuación narrativa** hasta las 18:45 |
| `MEMORIA_VERIFICACION.md` | Casuística detallada: R-2043, R-2055, R-2070, R-2073, R-2082, R-2084, R-2097, complementos, probe seguro | Antes de tocar brotes, dudosos o complementos | Aquí está el **resumen del día**; allí el **detalle caso por caso** |
| `REPORTE_FINAL.md` | Arquitectura, resultados y respuestas para la defensa (corte 07:00) | Preparar la demostración del viernes | Las cifras de **este** documento son el corte 18:45 |
| `docs/ARQUITECTURA.md` | Pipeline de 5 pasos y responsabilidad de cada módulo | Explicar el diseño | Fundamento de la separación interpretar/decidir |
| `docs/NIVEL2.md` | Fórmulas exactas del nivel 2 y del brote | Defender prioridad/semáforo/técnico | Base de la regla determinista que ganó R-2122/R-2124 |
| `cache/rama_rafa.md` | Resumen histórico del PR #1 | Contexto de la rama `Rafa` | Documento histórico, no estado actual |

**Regla de mantenimiento:** este archivo es la memoria **del día 21**. El estado vivo
(qué corre, qué falta, dónde está la cola) se actualiza en `CHECKPOINT_SESION.md`; las
lecciones de casos se acumulan en `MEMORIA_VERIFICACION.md`; las cifras de defensa se
consolidan en `REPORTE_FINAL.md`.

---

## 1. Resumen ejecutivo del día

1. **Se cerró la brecha de 10 puntos con MISA hasta 2 puntos** (478 vs 480 al corte),
   con **10 errores propios contra 12 de MISA**. La diferencia ya no es estructural:
   se ganó con casos nuevos bien resueltos y se perdió con brotes históricos congelados.
2. **Se resolvieron y registraron 63 de los 67 reportes publicados hoy** (R-2063 → R-2125).
   Quedan 4 pendientes: 2 en cola de revisión (R-2126, R-2128) y 2 no-plaga claros sin
   enviar (R-2127, R-2129), porque el envío automático sigue apagado.
3. **Se integró selectivamente el PR #8 de Emmanuel**: regla conservadora de brote
   (`n>=3 → true`, `n<=1 → false`, `n==2 → revisión`), fix real de R-2055, referencias
   auditables, botones de Telegram y `evaluar_caso.py`. **No** se fusionó lo que revertía
   el dedupe de 24 h ni la cola de dudosos.
4. **Se corrigieron 9 bugs/reglas** que costaban puntos: gallina ciega, inyección de
   prompts, fracciones de `pct`, voz sin transcripción, orden de la regla de cultivo
   exclusivo, reconciliación que registraba a ciegas, entre otros.
5. **Se incorporó el documento oficial de diagnóstico de plagas y cultivos hospederos**
   (`diagnostico_plagas_y_cultivos_hospederos.md`) al motor: más señales de síntomas,
   hospederos y una regla de refuerzo. **El catálogo oficial de la API sigue mandando**;
   el documento es contexto, no verdad evaluadora.
6. **La IA quedó intermitente al cierre:** el log muestra `403 Key limit exceeded` en
   las llamadas de 18:29–18:34. La clave tiene margen (~$10 de $60) y `gpt-4o-mini`
   responde 200, pero `gpt-4o` da 429 upstream. Es el principal riesgo abierto.

---

## 2. Línea del tiempo del 21 de octubre

| Hora aprox. | Qué pasó | Casos / commits |
|---|---|---|
| 06:00–09:00 | Primeras publicaciones del día; se detecta el falso negativo de brote R-2084 y el error de técnico R-2082 | R-2063 → R-2081 · `01f39f4` (dedupe cluster 24 h) |
| 09:00–10:30 | Racha perfecta en casos nuevos; primer empate con MISA | R-2085 → R-2092 · 333/355 = MISA |
| 10:30–12:00 | Barrido de complementos; R-2097 pierde 1 punto por registrar a ciegas; se blinda la reconciliación | R-2093 → R-2100 · `0ab3233`, `c1f324c` |
| 12:00–14:30 | Se decide que el resolver de dudosos corra **solo en análisis**; barrido de puntos: 0 sin registrar y 0 puntos ocultos | R-2101 → R-2114 · `2dfda76` |
| 14:30–16:40 | Todo brote se aparca y requiere visto bueno; merge selectivo del PR #8; fixes de inyección, `pct` y gallina ciega | R-2115 → R-2120 · `23bd0a3`, `aedafb3`, `2687d30`, `c59e26a`, `ee316d4` |
| 16:40–17:40 | Recta final: R-2122 destapa el orden de la regla de cultivo exclusivo; R-2123/R-2124 salen perfectos; brecha a 2 | R-2121 → R-2124 · `f3dff7f`, `bd30e75` |
| 18:12–18:34 | R-2125 (no-plaga) enviado; llegan R-2126 → R-2129; 2 quedan en cola; aparecen los 403 de IA | R-2125 → R-2129 |

**Lectura de la tabla:** cada reporte nuevo fue, a la vez, una prueba del motor y una
oportunidad de puntos. Los bugs no se “arreglaron en abstracto”: los destapó un caso
real y el fix se desplegó antes del siguiente.

---

## 3. Casos del día

### 3.1 Volumen

- **67 reportes publicados hoy** (R-2063 → R-2129): **36 texto, 21 voz, 10 foto**.
- **63 registrados** (R-2063 → R-2125), incluidos seguimientos y no-plaga.
- **4 pendientes al cierre** (ver §7).
- La bitácora fiel de lo que clasificó la app está en
  `cache/listener_bitacora_servidor.jsonl` (servidor: `~/agente/cache/listener_bitacora.jsonl`).

### 3.2 Recta final verificada (R-2115 → R-2125)

| Reporte | Hora | Tipo | Cultivo | App (bitácora) | Resultado final | Puntos |
|---|---|---|---|---|---|---|
| R-2115 | 15:09 | voz | maíz | `desconocida` (0.3) | **gallina_ciega** tras ampliar señales de gusanos blancos/enroscados | 5/5 |
| R-2116 | 15:17 | texto | — | `desconocida` | **seguimiento** de pulgón (mismo productor) | 2/2 |
| R-2117 | 15:34 | texto | maíz | pulgon | **pulgon** + intento de inyección detectado y descartado | 5/5 |
| R-2118 | 15:45 | voz | frijol | roya_frijol, `brote=True` | **roya_frijol** (brote aparcado y aprobado) | 5/5 |
| R-2119 | 15:59 | voz | frijol | roya_frijol | **roya_frijol** | 5/5 |
| R-2120 | 16:37 | foto | jitomate | mosquita_blanca | **mosquita_blanca** | 5/5 |
| R-2121 | 16:45 | voz | grano almacenado | gorgojo_khapra (cultivo exclusivo, sin texto útil) | **gorgojo_khapra** | 5/5 |
| R-2122 | 16:56 | voz | papa | `desconocida` (0.3) | **tizon_tardio** con `pct=75 %` | 5/5 |
| R-2123 | 17:01 | voz | frijol | roya_frijol, `n=2` | **roya_frijol** (revisión conjunta por `n==2`) | 5/5 |
| R-2124 | 17:07 | texto | papa | tizon_tardio | **tizon_tardio** (“quemadas / como si les hubiera caído hielo”) | 5/5 |
| R-2125 | 18:12 | texto | frijol | no-plaga (0.92) | **no-plaga**: “Buenas noches, nomás para saludar” | 1/1 |

**Historias que valen oro para la defensa:**

- **R-2115** es el caso que obligó a ampliar las señales de **gallina ciega**
  (`gusanos blancos enroscados`, `raíces comidas`, `marchitez con humedad`).
  El commit `2687d30` salió 10 minutos después del reporte.
- **R-2122** es el caso que destapó que la regla de **cultivo exclusivo** corría
  *antes* de la transcripción: al no haber texto aún, perdía el `pct` y decía
  `desconocida`. Se movió a **fallback después de STT/visión** (`f3dff7f`) y el caso
  salió 5/5. Es exactamente la “deducción determinista” que nos llevó al liderato
  momentáneo: si el catálogo de la API solo admite **tizón** en papa, no hay que
  inventar otra plaga.
- **R-2124** confirmó la misma regla por texto: “se ven como quemadas, como si les
  hubiera caído hielo” → **tizon_tardio**, sin ambigüedad.

### 3.3 Casos que costaron puntos (y por qué no se repiten)

| Caso | Error | Lección |
|---|---|---|
| R-2082 | Técnico calculado con el momento/parcela equivocados (T-08 en vez de T-06) | Calcular el técnico **siempre** con `recibido` y la parcela del reporte, antes de enviar |
| R-2084 | `brote=false` cuando la API esperaba `true` | Dedupe por **cluster de 24 h**, no por productor global |
| R-2097 | Texto vago en frijol registrado a ciegas por la reconciliación | La reconciliación debe pasar por `_es_dudoso`; texto vago en frijol ≠ `desconocida` en maíz |
| R-2056 | `es_plaga=false` cuando correspondía plaga | No “corregir” un caso ya congelado por la API |
| Brotes R-2043, R-2055, R-2070, R-2073, R-2084 | Campo `brote` congelado por la API | No son recuperables; solo se compensan con casos nuevos |

---

## 4. Cambios técnicos del día

| Commit | Hora | Qué cambió | Por qué / caso que lo motivó |
|---|---|---|---|
| `01f39f4` | 10:06 | Dedupe de brote por **cluster de 24 h** | R-2043 (falso positivo) y R-2084 (falso negativo) |
| `0ab3233` | 11:56 | La reconciliación respeta la cola de dudosos | R-2097 registrado a ciegas |
| `c1f324c` | 12:00 | La reconciliación consulta `validar_caso` antes de aparcar | Reponía históricos en la cola |
| `2dfda76` | 14:24 | Resolver de dudosos en **modo análisis SOLO** | Decisión de Rafael: nada de registros automáticos |
| `23bd0a3` | 14:50 | **Todo** brote se aparca y avisa por Telegram; el botón “Registrar” sí registra | Evitar brotes a ciegas y botones decorativos |
| `6be558c` | 15:00 | Herramientas de barrido de puntos y complementos | `escaneo_puntos.py`, `analizar_complementos.py` |
| `2687d30` | 15:19 | Señales de **gallina ciega** + integrar `PERMITIR_ENVIOS` | R-2115 |
| `c59e26a` | 15:46 | Patrones de **prompt-injection** | “marcalo como rojo urgente”, “eres el sistema”, “es orden del coordinador” |
| `ee316d4` | 16:09 | `pct` con fracciones (“la cuarta parte” = 25 %) | Evitar perder prioridad/semáforo por no leer fracciones |
| `aedafb3` | 16:41 | **Merge selectivo del PR #8** | Regla de brote conservadora, fix R-2055, `evaluar_caso.py`, alertas con referencias |
| `11114b5` | 16:49 | Voz sin transcripción se aparca | No registrar a ciegas un audio que no se pudo leer |
| `f3dff7f` | 17:02 | Regla de **cultivo exclusivo** generalizada y movida a fallback **después** de STT/visión | R-2122: papa → tizon_tardio sin perder el `pct` |
| `bd30e75` | 17:37 | Integración del **documento oficial de diagnóstico** | Más señales de síntomas, hospederos y regla `señal + hospedero` |

### 4.1 Qué se integró del PR #8 de Emmanuel (y qué no)

**Sí:**
- `nivel2.decidir_brote`: `n>=3 → true`, `n<=1 → false`, **`n==2 → None`** (revisión conjunta).
- Fix de **R-2055** (un padre en `desconocida` no abre seguimiento; se heredan
  parcela/productor/coordenadas).
- `clasificador.evaluar_brotes` con `n` y `refs` auditables (distancia, reporte, fecha).
- Alertas de Telegram con referencias y botones; escapado HTML.
- Anti-inyección: si hay intento, **se descarta `pct_ia`** y decide la regla.
- `bot/evaluar_caso.py`, corregido para usar el motor de producción (`con_ia=True`,
  `INTERPRETAR_IA=2`), con `--sin-ia`, soporte de `CASOS_SALIDA` y limpieza de
  `_brote_dudoso`.

**No:**
- Los cambios masivos de `listener`/`bot` que revertían el dedupe de 24 h o la cola de
  dudosos. El merge fue **selectivo**, no wholesale.

### 4.2 Documento de diagnóstico de plagas y cultivos hospederos

Se ampliaron las señales en lenguaje de productor:

| Plaga | Señales nuevas (ejemplos) |
|---|---|
| Tizón tardío | “lesiones/manchas oscuras”, “crecimiento blanquecino”, “blanco abajo de la hoja”, “avanza rápido” |
| Roya del frijol | “pústulas”, “polvo rojizo/anaranjado/oxidado” |
| Gusano cogollero | “larvas/daño dentro del cogollo”, “hojas perforadas” |
| Pulgón | “hojas enrolladas”, “melaza pegajosa”, “agrupados en los brotes” |
| Mosquita blanca | “vuelan al mover”, “ninfas en el envés” |
| Gallina ciega | “larvas blancas en el suelo”, “daños en raíces” |
| Chapulín | “mordeduras irregulares”, “insectos saltadores” |
| Mancha chocolate | “lesiones color chocolate” |
| HLB | “frutos deformes”, “maduración desigual” |

También se amplió `CULTIVO_POR_MENCION` (sorgo, naranja, mandarina, toronja, pepino,
chile, lechuga, etc.) y se añadió la regla **`señal + hospedero`**: una señal débil se
refuerza si el texto menciona un cultivo hospedero **compatible con el catálogo oficial**.

**Advertencia que quedó grabada en el código y en la memoria:**
el documento es una guía agronómica; **la API evalúa con su propio catálogo**:

- `pulgon` en la API: `avena`, `trigo`, `maíz`, `haba` — **no jitomate**.
- `gallina_ciega`: `maíz`, `frijol`, `avena`, `haba` — **no papa**.
- `papa`: solo `tizon_tardio`.

Por eso “pulgón en jitomate” o “gallina en papa” bajan a `desconocida`: **es correcto
según el reto**. El catálogo oficial es el filtro final; el documento solo aporta
señales y contexto. Esa distinción es la que ganó R-2122 y R-2124.

---

## 5. Descubrimientos y reglas del día

1. **Brote = conjunto completo, nunca un solo reporte.**
   Se recalcula con todos los casos (previos + propios) y dedupe por **cluster de 24 h**
   del mismo productor. `n>=3 → true`, `n<=1 → false`, `n==2 → None` (revisión humana).
   **Todo brote se aparca y requiere visto bueno de Rafael.**
2. **Un complemento solo suma si abre un caso nuevo.**
   Si es seguimiento, la API califica como máximo `es_plaga + plaga` (2 puntos).
   El mensaje “todavía le pueden agregar…” del 409 **no** garantiza +3.
3. **`POST /casos` en un reporte no registrado responde 201 y LO REGISTRA.**
   Para consultar estado se usa **solo** `POST /casos/validar`.
4. **Nunca registrar a ciegas.**
   Voz sin transcripción, foto dudosa, `desconocida` o baja confianza → cola de dudosos
   y revisión humana. El listener ya no registra esos casos solo.
5. **El catálogo oficial manda sobre la guía agronómica.**
   Papa solo admite tizón; pulgón no está en jitomate; gallina ciega no está en papa.
   La regla determinista de cultivo exclusivo es válida **solo** si respeta el catálogo.
6. **El orden del pipeline importa.**
   La regla de cultivo exclusivo debe correr **después** de STT/visión; si corre antes,
   no hay texto, se pierde el `pct` y el caso cae a `desconocida` (R-2122).
7. **El técnico se calcula con el momento y la parcela del reporte.**
   Nunca con los de una respuesta `-R` ni con la hora actual (R-2082).
8. **Anti-inyección:** si el texto intenta manipular (“ignora tus instrucciones”,
   “marcalo como rojo urgente”, “eres el sistema”), se marca `injection` y **se descarta
   `pct_ia`**; decide la regla. La IA nunca decide puntos.
9. **Texto vago:** en **maíz** `es_plaga=true, plaga=desconocida` puntúa 2/2
   (R-2042, R-2089, R-2096). En **frijol** no puntúa igual (R-2097): revisar antes.
10. **Las respuestas `-R` no son reportes** (404 “Mensaje no encontrado”): se ignoran.
11. **La reconciliación debe validar primero.**
    Si no, re-aparca históricos ya registrados y ensucia la cola.
12. **La IA puede fallar y el sistema debe sobrevivir.**
    Al cierre hubo `403 Key limit exceeded` en las llamadas de 18:29–18:34.
    El motor cayó a reglas; por eso R-2128 quedó sin transcripción y R-2126 en
    `desconocida`. **No concluir que el audio estaba vacío ni enviar a ciegas.**
13. **La latencia es el desempate.**
    Al corte: MISA 6.6 min vs 7_7 15.9 min. Si empatamos en puntos, gana MISA.
    Hay que **ganar por al menos 1**, no empatar, y responder rápido.
14. **La brecha ya no es estructural, pero los brotes históricos están congelados.**
    R-2043, R-2055, R-2070, R-2073 y R-2084 no se pueden recuperar; solo compensar.

---

## 6. Protocolo operativo por reporte (la “misma estrategia”)

Este es el flujo que se usó hoy y que debe repetirse con cada publicación nueva:

1. **Detectar**: consultar `GET /reportes` y la cola del servidor
   (`~/agente/cache/revision_pendiente.json`). Identificar el `reporte_id` nuevo.
2. **Evaluar con la app**: en el servidor,
   ```bash
   cd ~/agente && CASOS_SALIDA=/home/equipo02/app/cache/casos_propuestos.json \
     .venv/bin/python -X utf8 bot/evaluar_caso.py R-XXXX
   ```
   Usa el motor de producción (`con_ia=True`, `INTERPRETAR_IA=2`).
3. **Verificar de forma independiente**:
   - plaga y `es_plaga` contra señales del texto/transcripción;
   - `pct` (incluidas fracciones: “la cuarta parte” = 25 %);
   - prioridad y semáforo (`docs/NIVEL2.md`);
   - técnico calculado con `recibido` y la parcela del reporte;
   - brote con el **conjunto completo** y referencias (distancia/fecha/productor);
   - si es seguimiento (mismo productor/parcela <24 h o “¿cuándo vienen?”).
4. **Comparar**: si la app y la verificación **coinciden**, se envía el payload.
   Si **difieren**, **NO se envía**: se reporta y se decide con Rafael.
5. **Brotes**: siempre van a la cola de dudosos y requieren aprobación explícita.
   `n==2` también va a revisión conjunta.
6. **Registrar**: `POST /casos` con el payload aprobado. Antes, si hay duda,
   `POST /casos/validar` (no registra).
7. **Cerrar**: verificar puntos en `GET /tabla.json`, limpiar la cola y anotar el caso.
8. **Nunca** activar `PERMITIR_ENVIOS` ni el registro automático sin decisión de Rafael.

---

## 7. Estado al cierre (corte 18:45)

### 7.1 Tabla oficial

| Métrica | **7_7** | **MISA** |
|---|---:|---:|
| Puntos | **478 / 516** | **480 / 516** |
| Enviados | 125 / 129 | 126 / 129 |
| Errores | **10** | 12 |
| Aciertos `es_plaga` | 99 | 98 |
| Aciertos `plaga` | 100 | 97 |
| Aciertos `semaforo` | 98 | 97 |
| Aciertos `tecnico` | 99 | 97 |
| Aciertos `brote` | 93 | **99** |
| Latencia mediana | 15.9 min | **6.6 min** |
| Lugar | 2.º | 1.º |

**Brecha: MISA +2.** Nosotros tenemos **2 errores menos**, pero MISA nos gana el
desempate por latencia y nos saca ventaja en `brote` (99 % vs 93 %).

### 7.2 Cola de dudosos (servidor)

| Reporte | Hora | Detalle | Motivo | Estado |
|---|---|---|---|---|
| **R-2126** | 18:27 | papa, P-061, “Las matas se están secando.” | plaga desconocida (motor en reglas por el 403 de IA) | **revisar con Rafael** |
| **R-2128** | 18:32 | voz de 2.8 s, sin transcripción | no se leyó el audio (probablemente por el 403 de IA) | **reintentar STT y revisar** |

### 7.3 Pendientes de envío (no están en cola, pero no se han registrado)

| Reporte | Hora | Texto | Clasificación | Potencial |
|---|---|---|---|---|
| **R-2127** | 18:31 | “¿Cuánto están pagando el kilo de maíz?” | no-plaga (0.92) | +1 |
| **R-2129** | 18:34 | “Mi compadre dice que hay un apoyo del gobierno para semilla, ¿es cierto?” | no-plaga (0.92) | +1 |

**No se enviaron porque `PERMITIR_ENVIOS` sigue apagado.** Son claros y, con el visto
bueno de Rafael, se registran en un minuto. **+2 inmediatos** llevarían a 480 (empate),
pero el desempate por latencia favorece a MISA: hay que **pasar de 480**, no empatar.

### 7.4 Infraestructura

- Servidor: `supervisorctl status agente` → **RUNNING**.
- Commit desplegado: **`bd30e75`** (diagnóstico de plagas y hospederos).
- Resolver de dudosos: **modo ANÁLISIS SOLO** (no registra).
- `PERMITIR_ENVIOS`: **sin definir** → el agente no registra solo.
- Batería local al cierre:
  - `probar_motor.py` → **94/94**
  - `validar_nivel2.py` → **40/40/40**
  - `validar_brote.py` → **40/40 + 5/5 reales**
  - `analizar_brotes.py` → **5/5**

---

## 8. Riesgos abiertos y pendientes

1. **🔴 IA intermitente (403 / 429).**
   El log muestra `403 Key limit exceeded (total limit)` en 18:29–18:34. La clave del
   servidor tiene límite de $60 y ~$10 disponibles; `gpt-4o-mini` responde 200 y
   `gpt-4o` da 429 upstream. **Acción:** vigilar el log, rotar la clave si
   se repite y **reintentar la transcripción de R-2128** cuando la IA esté estable.
2. **🟠 4 reportes sin registrar.** R-2127 y R-2129 son no-plaga claros (+2). R-2126 y
   R-2128 requieren revisión. Mientras no se envíen, la brecha de 2 no se cierra.
3. **🟠 Desempate por latencia.** MISA 6.6 min vs 15.9 min. Si terminamos empatados en
   puntos, gana MISA. **Hay que superarlos por al menos 1 punto** y responder rápido.
4. **🟡 Brotes históricos congelados.** R-2043, R-2055, R-2070, R-2073, R-2084 no se
   recuperan. La única vía es acertar los brotes nuevos y que MISA falle alguno.
5. **🟡 `PERMITIR_ENVIOS` apagado.** Decisión consciente: nada se registra sin visto
   bueno. No activarlo sin decisión explícita de Rafael.
6. **🟡 La IA no debe decidir puntos.** El consenso híbrido usa reglas + IA, pero ante
   discrepancia mandan las reglas y el precedente histórico. Mantener esa jerarquía.

---

## 9. Comandos y archivos de referencia

### Validaciones locales (no gastan API)

```powershell
.\.venv\Scripts\python.exe bot\probar_motor.py      # 94/94
.\.venv\Scripts\python.exe bot\validar_nivel2.py    # 40/40/40
.\.venv\Scripts\python.exe bot\validar_brote.py     # 40/40 + 5/5 reales
.\.venv\Scripts\python.exe bot\analizar_brotes.py   # patrón de brote y 5/5
```

### Datos y evaluación

```powershell
.\.venv\Scripts\python.exe bot\descargar_catalogos.py --reportes
.\.venv\Scripts\python.exe bot\escaneo_puntos.py
.\.venv\Scripts\python.exe bot\analizar_complementos.py
```

### En el servidor

```bash
cd ~/agente
CASOS_SALIDA=/home/equipo02/app/cache/casos_propuestos.json \
  .venv/bin/python -X utf8 bot/evaluar_caso.py R-XXXX
supervisorctl status agente
desplegar agente --forzar          # si hace falta forzar el despliegue
cat cache/revision_pendiente.json  # cola de dudosos
tail -50 ~/logs/agente.log         # IA, clasificaciones, errores
```

### Archivos clave

| Archivo | Para qué |
|---|---|
| `bot/clasificador.py` | Señales, inyección, cultivo exclusivo, `evaluar_brotes`, fusión |
| `bot/nivel2.py` | Prioridad, semáforo, técnico, brote, `pct` |
| `bot/listener.py` | Ciclo, `_es_dudoso`, `_parkear_dudoso`, `ENVIOS_HABILITADOS` |
| `bot/evaluar_caso.py` | Evaluar un reporte sin registrar (motor de producción) |
| `bot/resolver_cola.py` | Reanálisis de la cola en modo ANÁLISIS |
| `bot/bot_telegram.py` | Botones y registro de pendientes |
| `bot/telegram_notificador.py` | Alertas de dudosos con referencias |
| `bot/escaneo_puntos.py` / `analizar_complementos.py` | Barrido de puntos y complementos |
| `bot/analizar_brotes.py` / `validar_brote.py` / `validar_nivel2.py` / `probar_motor.py` | Batería de validación |
| `cache/listener_bitacora_servidor.jsonl` | Qué clasificó realmente la app |
| `cache/casos_propuestos_servidor.json` | Casos compartidos con el dashboard |
| `cache/revision_pendiente_servidor.json` | Espejo de la cola de dudosos |

> **Convención de trabajo:** para SSH se escriben scripts temporales con `paramiko`
> leyendo `.env`; no se pegan contraseñas ni tokens en la línea de comandos. Los
> temporales se borran al terminar. `cache/` y `.env` están en `.gitignore`.

---

## 10. Nota de continuidad para la próxima sesión

1. Leer **primero** `CHECKPOINT_SESION.md` (estado operativo) y **después** este
   documento (qué pasó el 21 y por qué).
2. Revisar la cola del servidor y la tabla oficial antes de tocar nada.
3. Resolver **R-2127** y **R-2129** (no-plaga) con visto bueno; luego **R-2126** y
   **R-2128** con el protocolo de dudosos.
4. Reintentar la IA / STT antes de concluir que R-2128 está vacío.
5. No activar `PERMITIR_ENVIOS` ni el registro automático sin decisión de Rafael.
6. No tocar el dedupe de 24 h ni la cola de dudosos sin correr la batería completa.
7. Recordar: **ganar por 1, no empatar** (MISA gana el desempate por latencia).

---

### Cierre

El 21 de octubre fue el día en que el sistema dejó de ser “un motor que acierta
mucho” y se volvió **un sistema con criterio**: brotes que se aparcan, dudosos que se
revisan, complementos que no se regalan, catálogo oficial que manda sobre la guía
agronómica y una regla determinista que supo decir “en papa, esto es tizón”. La brecha
de 10 puntos se convirtió en 2. Los 4 reportes pendientes y la IA intermitente son el
trabajo inmediato; el resto es defender lo construido.
