# Nivel 2 — prioridad, semáforo, técnico y brote

> Documento de diseño y defensa. Explica **qué se calcula**, **por qué** y
> **cómo se verifica**. Las fórmulas viven en `bot/nivel2.py` y no dependen de la IA.

---

## 1. Contexto

El reto cambió a mitad de camino. Lo detectamos comparando la API consigo misma:

| Señal | Antes | Después |
|---|---|---|
| `GET /equipo → avance.maximo_posible` | 103 | 188 |
| Campos calificados | `es_plaga`, `plaga` | + `semaforo`, `tecnico` |
| Esquema de `Caso` | 5 campos | + `semaforo`, `tecnico_id`, `prioridad` |
| `urgente` | calificaba | ya no se usa |

La lección de ingeniería: **el catálogo y las reglas se leen de la API**, no se
hardcodean. Si los organizadores agregan plagas o cambian severidades, el motor
se adapta sin reescribirse.

---

## 2. Separar “interpretar” de “decidir”

```
reporte
  │
  ▼
clasificador.py        ¿es plaga? ¿cuál? ¿qué %?
  │                    reglas + IA + STT/visión
  ▼
nivel2.py              prioridad → semáforo → técnico → brote
  │                    código puro, determinista
  ▼
caso_para_api()        limpia campos internos
  │
  ▼
POST /casos/validar → POST /casos
```

### Por qué

1. **El reglamento lo exige:** prioridad, semáforo, técnico y brote son reglas
   de código, sin IA.
2. **Reproducibilidad:** los mismos datos deben dar el mismo resultado.
3. **Testeable:** funciones puras contra 40 casos con respuesta oficial.
4. **La IA queda donde aporta:** interpretar el lenguaje, transcribir voz y
   describir fotos.

---

## 3. Prioridad (0–100)

```
prioridad = severidad + superficie + etapa
```

| Factor | Cálculo | Máx. |
|---|---|---:|
| Severidad | baja 15 · media 25 · alta 40 · crítica 50 | 50 |
| Superficie | `ha = superficie_ha × pct/100`; `min(25, round(ha/4 × 25))` | 25 |
| Etapa | crítica 25 · susceptible 15 · otra 5 | 25 |

- Redondeo comercial: `floor(x + 0.5)`.
- **Cuarentenaria → 100 directo**, sin cálculo.

### Ejemplo del reglamento

Maíz, 4.5 ha, V8, cogollero, 50 %:

```
severidad 40 + superficie 14 + etapa 25 = 79 → naranja
```

---

## 4. Semáforo

| Prioridad | Semáforo | Visita |
|---|---|---|
| 85–100 | rojo | 24 h |
| 70–84 | naranja | 48 h |
| 40–69 | amarillo | 72 h |
| 0–39 | verde | 7 días |

---

## 5. Técnico

1. Misma especialidad que la plaga.
2. Carga < 5 en `momento = recibido`.
3. El más cercano a la parcela por haversine (R = 6371 km).
4. Empates: menor carga, luego menor id.
5. Si nadie cumple → `null`.

**Detalle clave:** la carga se consulta con
`GET /tecnicos?momento=<recibido>`, no con la hora actual. La API simula que la
carga cambia con el tiempo.

---

## 6. Porcentaje afectado (`pct`)

| Frase del productor | pct |
|---|---:|
| “el 75 %”, “setenta y cinco por ciento” | 75 |
| “tres cuartas partes” | 75 |
| “la mitad” | 50 |
| “una de cada cuatro matas” | 25 |
| “una quinta parte” | 20 |
| “todas las plantas / todas las matas” | 100 |
| “hojas agujeradas” | no es 100 %; se usa la señal del texto |
| no lo dice | 10 |

El pct mueve el semáforo. Por eso se corrigió:

- “la cuarta/quinta/sexta parte” sin “una”;
- “todas las plantas”;
- no confundir “hojas agujeradas” con 100 %.

---

## 7. Brote (sección 9)

### 7.1 Regla oficial

Hay brote si, contando el caso actual, hay **3 o más casos de la misma plaga**:

- a **menos de 5 km** de la parcela del mensaje;
- recibidos en los **7 días previos** (168 h, incluido el momento);
- contando `/casos-previos` y los casos propios.

No cuentan:

- seguimientos;
- mensajes que no son reportes;
- casos que quedaron como `desconocida`.

La hora es `recibido`, no la de procesamiento. La distancia es haversine entre
parcelas, R = 6371 km. La ventana es inclusiva.

### 7.2 Dedupe de casos propios

Los casos propios del **mismo productor y la misma parcela** se agrupan en
clústeres de 24 h:

- varios reportes en horas = **1 evento**;
- más de 24 h = **evento nuevo**;
- otra parcela del mismo productor = **otro evento** (R-2204).

Los `/casos-previos` **nunca** se deduplican.

Por qué:

- R-2043: mismo productor en horas → falso positivo si no se deduplica.
- R-2084: mismo productor/parcela 2 días después → sí debe sumar.
- R-2204: mismo productor en otra parcela → no debe colapsarse.

### 7.3 Política `n=2`

| n | Decisión |
|---:|---|
| 0–1 | `false` |
| 2 | zona gris: no se envía `brote`; va a revisión |
| ≥3 | `true` |

`n=2` no es sinónimo de `false`: R-2152 demostró que puede ser `true`. Por eso
no se manda a ciegas.

### 7.4 Brote profundo en decisión autónoma

`decision_autonoma.py` puede convertir un `n=2` en `true` si encuentra:

- un caso previo en la **misma parcela**, o
- un tercer caso por **coordenadas del reporte**.

Si no, lo deja en `false`. Esta es una capa de revisión, no la regla oficial.

### 7.5 Propuesta de ledger de confirmados (rama `Caso_Emmanuel`)

Problema: la API solo puede contar los casos que realmente recibió. Si el motor
cuenta propuestas locales, aparcados o falsas alarmas, puede inflar un brote.

Propuesta:

- `cache/casos_confirmados.json` con plaga y coordenadas congeladas de casos
  aceptados (`201`/`409`);
- referencias = previos + confirmados + caso actual;
- excluir falsas alarmas;
- recalcular al aprobar desde Telegram.

Esto no cambia la fórmula: cambia **qué casos se usan como referencia**.

### 7.6 Propuesta de coherencia de hospedero

El documento de diagnóstico del reto tiene una tabla de cultivos hospederos.
Se propone usarla como **evidencia para la revisión**, no como filtro del brote:

- si una referencia de una enfermedad específica aparece en un cultivo no
  hospedero, avisar al revisor;
- no descartar automáticamente una plaga polífaga por cultivo;
- el conteo oficial sigue siendo plaga + distancia + tiempo.

La regla oficial no usa cultivo. Meterlo como filtro sería un error.

---

## 8. Validación

```powershell
python bot/validar_nivel2.py    # prioridad, semáforo y técnico 40/40/40
python bot/validar_brote.py     # brote 40/40 + casos reales
python bot/probar_motor.py      # batería general del motor
python bot/probar_brotes.py     # invariantes de brote (rama Caso_Emmanuel)
python bot/replay_brotes.py     # replay offline de variantes
```

Resultados de referencia:

```
Casos previos: 40
Prioridad: 40/40   Semáforo: 40/40   Técnico: 40/40
Brote: 40/40
Casos reales documentados: 5/5
```

Casos reales usados como regresión de brote:

- R-2043 → `false` (seguimiento)
- R-2055 → `true`
- R-2070 → `true`
- R-2073 → `true`
- R-2084 → `true`

---

## 9. Decisiones de diseño y por qué

| Decisión | Por qué |
|---|---|
| Semáforo no lo decide la IA | Reglamento + reproducibilidad |
| `desconocida` en vez de inventar | No resta y evita errores |
| Preguntar parcela en vez de inferir | La inferencia falló en R-2128 |
| `n=2` a revisión | Puede ser true o false; R-2152 |
| Dedupe productor + parcela | Evita R-2043 y R-2204; permite R-2084 |
| Ledger de confirmados | La API solo cuenta lo que recibió |
| Hospedero como evidencia | Ayuda al revisor sin romper la regla |
| `PERMITIR_ENVIOS=0` por defecto | Evita registrar a ciegas |

---

## 10. Preguntas frecuentes

**¿Por qué no usar la IA para prioridad o semáforo?**
Porque el reglamento lo prohíbe y porque dos ejecuciones darían resultados
distintos. La IA interpreta; el código decide.

**¿Qué pasa si el productor no dice el porcentaje?**
Se usa 10 %, el mismo criterio de `/casos-previos`.

**¿Qué pasa si no hay técnico disponible?**
Se manda `null`. Es la respuesta honesta y no resta más que equivocarse.

**¿Qué pasa si el reporte no trae parcela?**
Se pregunta al productor. No se infiere a ciegas.

**¿Qué pasa si un seguimiento nombra una plaga?**
La API solo califica `es_plaga` + `plaga`; semáforo, técnico y brote no se
califican. En papa/tizón suele convenir `desconocida`.

**¿Qué pasa si el catálogo cambia?**
El listener refresca `/plagas` y `/parcelas` cada 10 min. El motor se adapta.
