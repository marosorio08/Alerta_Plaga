# Nivel 2 — prioridad, semáforo y técnico

> Documento de diseño para la defensa individual del viernes.
> Explica **qué cambió**, **por qué se estructuró así** y **cómo verificarlo**.

---

## 1. Cómo detectamos el cambio del reto

El cambio no llegó por correo: se descubre comparando la API consigo misma.

| Señal | Antes | Después |
|---|---|---|
| `GET /equipo → avance.maximo_posible` | 103 | **188** |
| `avance.aciertos` | `es_plaga`, `plaga` | + **`semaforo`**, **`tecnico`** |
| Esquema `Caso` en `/openapi.json` | 5 campos | + `semaforo`, `tecnico_id`, `prioridad` |
| `urgente` | calificaba | *"Nivel 1, ya no se usa"* |

Con eso localizamos las secciones **7, 8 y 9 de `/reglas`**, que traen las fórmulas exactas.
**Lección de ingeniería:** el sistema debía adaptarse sin reescribirse; por eso el catálogo y
las reglas se leen de la API y no están hardcodeados.

---

## 2. Decisión de arquitectura: separar "interpretar" de "decidir"

```
                    ┌──────────────────────────────┐
   reporte  ───────▶│  clasificador.py  (IA)       │  ¿es plaga? ¿cuál? ¿qué %?
   (texto/voz/foto) │  reglas de lenguaje + LLM    │  + cruce parcela→cultivo
                    └──────────────┬───────────────┘
                                   │ plaga + pct
                    ┌──────────────▼───────────────┐
                    │  nivel2.py  (código puro)    │  prioridad → semáforo → técnico
                    │  sin IA, determinista        │  mismas entradas = misma salida
                    └──────────────┬───────────────┘
                                   │ semaforo, tecnico_id, prioridad
                    ┌──────────────▼───────────────┐
                    │  caso_para_api()             │  limpia campos internos
                    └──────────────┬───────────────┘
                                   ▼
                        POST /casos/validar → POST /casos
```

**Por qué así:**

1. **El reglamento lo exige.** "Reglas (código, sin IA): calculan la prioridad y el semáforo
   y eligen al técnico. Con los mismos datos dan siempre el mismo resultado."
2. **Reproducibilidad.** Si el semáforo dependiera de un LLM, dos ejecuciones darían dos
   respuestas distintas y no podríamos defenderlo.
3. **Testeable.** Al ser funciones puras, se comparan contra los 40 casos previos.
4. **La IA queda donde sí aporta:** leer el mensaje (plaga) y extraer el porcentaje afectado,
   que es justo lo que el reto le pide al agente.

---

## 3. Fórmulas implementadas (`bot/nivel2.py`)

### 3.1 Prioridad (0–100)

| Factor | Cálculo | Máx. |
|---|---|---:|
| Severidad | baja 15 · media 25 · alta 40 · crítica 50 | 50 |
| Superficie | `ha = superficie_ha × pct/100`; `min(25, round(ha/4 × 25))` | 25 |
| Etapa | crítica para esa plaga/cultivo 25 · susceptible 15 · otra 5 | 25 |

- Redondeo **comercial** (`14.06 → 14`, `14.5 → 15`): `floor(x + 0.5)`.
- **Cuarentenaria → 100 directo**, sin cálculo.

### 3.2 Semáforo

| Prioridad | Semáforo | Visita |
|---|---|---|
| 85–100 | rojo | 24 h |
| 70–84 | naranja | 48 h |
| 40–69 | amarillo | 72 h |
| 0–39 | verde | 7 días |

### 3.3 Técnico

1. Solo de la **especialidad de la plaga** (`entomologia` / `fitopatologia`).
2. Solo con **carga < 5** en el momento del mensaje.
3. El **más cercano** a la parcela por haversine (R = 6371 km).
4. Empates: menor carga → menor id. Si nadie cumple: `null`.

**Detalle clave:** la carga se consulta con `GET /tecnicos?momento=<recibido>`, no con la hora
actual. La API simula que la carga cambia con el tiempo; usar "ahora" daría otro técnico.

### 3.4 Porcentaje afectado (`pct`)

Se interpreta del mensaje, como haría un técnico:

| Frase del productor | pct |
|---|---|
| "el 75%", "setenta y cinco por ciento" | 75 |
| "tres cuartas partes" | 75 |
| "la mitad" | 50 |
| "una de cada cuatro matas" | 25 |
| "una quinta parte" | 20 |
| no lo dice | **10** (mismo criterio que `/casos-previos`) |

### 3.5 Brote (sección 9 del reglamento)

Hay **brote** si, contando el caso actual, hay **3 o más casos de la misma plaga**
cuyas parcelas están a **menos de 5 km** y que llegaron en los **últimos 7 días
(168 h, incluido el momento del mensaje)**.

| Aspecto | Decisión |
|---|---|
| ¿Qué cuenta? | Los previos (`GET /casos-previos`) + los casos propios |
| ¿Qué no cuenta? | Seguimientos, mensajes que no son reportes, `desconocida` |
| ¿Qué hora? | La `recibido` del mensaje, no la de procesamiento |
| ¿Distancia? | Haversine entre parcelas, R = 6371 km, **estrictamente < 5 km** |
| Sin coordenadas | No se manda el campo → vale 0, nunca resta |

**Detalle de la ventana:** solo cuentan los casos **recibidos antes o a la vez**
que el mensaje. Un caso que llega después no hace "brote retroactivo" para los
anteriores; por eso la regla se evalúa sobre el conjunto completo y no reporte
por reporte. La regla da **40/40** contra la respuesta oficial de `/casos-previos`.

---

## 4. Verificación (lo que se puede mostrar el viernes)

```bash
python bot/validar_nivel2.py    # fórmulas reales contra 40 casos con respuesta correcta
python bot/validar_brote.py     # regla de brote contra los 40 casos previos
python bot/probar_motor.py      # 58 pruebas sin gastar API
```

Resultado actual:

```
Casos previos: 40
Prioridad: 40/40   Semáforo: 40/40   Técnico: 40/40
Brote: 40/40
Pruebas: 58 | fallos: 0
```

El caso del reglamento también coincide: maíz 4.5 ha, V8, cogollero, 50 % →
`40 + 14 + 25 = 79` → **naranja**.

---

## 5. Compatibilidad: por qué nada se rompió

| Riesgo | Mitigación |
|---|---|
| El dashboard de Emmanuel usaba `urgente` | Se conserva como derivado: `urgente = semaforo ∈ {rojo, naranja}` |
| La API rechazaría campos internos (`_pct`) | `caso_para_api()` filtra solo los campos del esquema |
| Cambian el catálogo (nuevas plagas/severidades) | La urgencia y los candidatos se derivan de `GET /plagas` |
| Se cae un modelo de IA | STT y visión tienen respaldo y consenso |
| Un reporte raro | El listener captura la excepción y sigue |

---

## 6. Extras implementados (apagados por defecto)

| Extra | Módulo | Cómo se activa |
|---|---|---|
| Avisos (`/avisos`): cuarentenaria, asignación, folio | `extras.py` | `--extras` (+ `--avisos-reales`) |
| Preguntas (`/preguntas`) cuando falta parcela o plaga | `extras.py` | `--preguntas` |
| Brotes: 3+ casos, misma plaga, <5 km, 7 días | `extras.py` | `--extras` |
| Plazos: escalar si no hubo visita | `extras.py` | `extras.py` (consola) |
| Telegram rojo/naranja con botones | `telegram_notificador.py` | `TELEGRAM_BOT_TOKEN` en `.env` |

**Por qué apagados:** un aviso mal disparado no resta puntos, pero ensucia el buzón y puede
confundir al coordinador. Se activan cuando el flujo esté validado.

---

## 7. Preguntas probables y respuesta corta

**¿Por qué el semáforo no lo decide la IA?**
Porque el reglamento lo prohíbe y porque necesitamos reproducibilidad: los mismos datos deben
dar siempre el mismo color. La IA interpreta el mensaje; el código decide.

**¿Cómo evitan que un mensaje manipule la prioridad?**
La prioridad se calcula con la parcela y el catálogo, nunca con el texto. Un "ponme prioridad
100" no entra en ninguna fórmula. Además se detecta y se registra como intento de inyección.

**¿Qué pasa si el productor no dice el porcentaje?**
Se usa 10 %, el mismo valor por omisión que usa la API en `/casos-previos`.

**¿Qué pasa si no hay técnico disponible?**
Se manda `null`. El reglamento dice que no mandar técnico vale 0, igual que equivocarse en él
resta; `null` es la respuesta honesta.

**¿Cómo validaron las fórmulas?**
Contra los 40 casos de `/casos-previos`, que traen la respuesta correcta: 40/40 en prioridad,
semáforo y técnico.

**¿Qué pasa si los organizadores cambian el catálogo otra vez?**
El listener refresca `/plagas` y `/parcelas` cada 10 minutos. La severidad, la especialidad y
los cultivos compatibles salen del catálogo, no del código.
