# 🌾 Proyecto Alerta Plaga — REPORTE COMPLETO del Equipo 7_7

> Documento final que resume **todo lo construido, decidido y aprendido** durante el
> Hackathon IT GREEN × DIMA (UACh). Complementa a `HISTORIA_DEL_PROYECTO.md` (bitácora),
> `docs/NIVEL2.md` y `docs/ARQUITECTURA.md` (fundamentos de defensa).
>
> **Corte de cifras:** 21-oct-2026, 07:00 (hora centro). Repositorio:
> `github.com/marosorio08/Alerta_Plaga_Gusano` (privado).

---

## 1. Ficha rápida

| Campo | Valor |
|---|---|
| Reto | «Alerta Plaga» — junta de sanidad vegetal de Texcoco (ficticia) |
| Equipo | `equipo02` · **7_7** · Rafael Martínez (Rol A) · Emmanuel Osorio (Rol B) |
| Cierre de la API | **jue 22-oct 23:59** · Demostraciones y defensa: viernes 23 |
| Stack | Python 3 (motor) · Node + Express + Leaflet (dashboard) · OpenRouter (IA) · Supabase (BD) |
| Despliegue | Servidor SSH `equipo02@179-236-73-82.sslip.io` bajo `supervisor` (24/7) |
| Dashboard | https://equipo02.179-236-73-82.sslip.io |
| Bot público | [@alerta_plaga_eq02_bot](https://t.me/alerta_plaga_eq02_bot) |

### Posición en vivo (corte 07:00)
| # | Equipo | Pts / máx | % | Errores | Avisos | Preguntas |
|---|---|---|---|---|---|---|
| **1** | MISA | 248/267 | 93 | 7 | 116 | 3 |
| **2** | **7_7 (nosotros)** | **247/267** | 92 | 5 | 101 | 7 |
| 3 | string | 234/267 | 88 | 10 | 37 | 6 |
| 4 | xD | 206/267 | 77 | 2 | 3 | 0 |

> Estuvimos **#1 (220 pts)** y volvimos a pelear el primer lugar; la diferencia con MISA
> es de **1 punto** al corte. Aciertos históricos: es_plaga 98–99 · plaga 100 · semáforo 97–98 ·
> técnico 100 · brote 98–100.

---

## 2. Arquitectura de 5 pasos (el flujo oficial)

```
 1 RECIBIR     2 INTERPRETAR      3 DECIDIR (reglas)    4 GUARDAR      5 REGISTRAR
 GET /reportes  consenso híbrido   nivel2 + brote       Supabase/cache POST /casos
 → id, parcela,  (Reglas + IA,     → semáforo           (upsert)       {reporte_id,
   texto         desempate histór.) → tecnico_id                          es_plaga,
                                            → brote                       plaga,
                                            → push coord. Telegram        semaforo,
                                                                           tecnico_id,
                                                                           brote}
```

| Paso | Quién | Fichero |
|---|---|---|
| 1 RECIBIR | `listener.py` (polling 20 s, dedup) + `api_cliente.py` | `bot/` |
| 2 INTERPRETAR | IA JSON estricto (`prompts.py`, `interpretar.py`) con **Consenso Híbrido** (`clasificador.clasificar_texto_hibrido`) | `bot/` |
| 3 DECIDIR | `nivel2.py` (prioridad → semáforo → técnico → brote) — **código puro, NO IA** | `bot/` |
| 4 GUARDAR | `supabase_repositorio.py` + caché local `cache/` | `bot/` |
| 5 REGISTRAR | `POST /casos`, instantáneo (notify/guardar van en hilo → latencia mínima) | `bot/pipeline.py`, `listener.py` |

**Modularidad:** `api_cliente` (red) · `prompts`/`interpretar` (IA) · `clasificador`/`nivel2`
(lógica) · `pipeline` (orquestador) · `listener` (tiempo real) · `extras`/`telegram_notificador`
(extras) · `enviar_casos`/`enviar_avisos` (operación) · `supabase_repositorio` (BD).

---

## 3. Consenso Híbrido con Desempate Histórico (`INTERPRETAR_IA=2`)

El **paso 2** mezcla determinismo e IA con un desempate auditable:

1. **Reglas** (señales ponderadas + cruce parcela→cultivo) evalúan el mensaje.
2. **IA** evalúa el mismo mensaje y devuelve SOLO JSON `{"es_plaga","plaga","pct"}`
   (`response_format: json_object`, temperature=0, 3 reintentos con backoff).
3. **Coinciden** → se envía con confianza alta (`motor=consenso_reglas_ia`).
4. **Difieren** → **precedente histórico** (`/casos-previos`): parcela resuelta o cultivo
   100 % consistente → manda el histórico (`consenso_historico`).
5. **Sin precedente → mandan SIEMPRE las Reglas** (`reglas_desempate`). La IA nunca
   anula a las reglas sin respaldo histórico *(lección del caso R-2056)*.

El `pct` que interpreta la IA entra en la prioridad (validado: pct 50 → prioridad 79).

**Validación:** prioridad/semáforo/técnico **40/40** y brote **40/40** contra `/casos-previos`
más **77** pruebas del motor (`bot/probar_motor.py`), que no gastan API.

---

## 4. Bot de Telegram (público, con personalidad)

[@alerta_plaga_eq02_bot](https://t.me/alerta_plaga_eq02_bot) — `bot/bot_telegram.py`.

- **Modo PÚBLICO**: cualquier productor conversa y reporta.
- **`/añadir` (registro de reportes):** recibe **texto, foto 📷 (visión 3 modelos),
  voz 🎙️ (STT `gpt-4o-transcribe` + respaldo whisper), archivo 📎** → hace **2 preguntas
  de diagnóstico** (síntomas y características) → pide **ubicación/parcela/cultivo solo
  si falta** → clasifica (consenso híbrido) → responde **el estado del reporte**
  (es_plaga · plaga · % · prioridad · semáforo · técnico · brote) → guarda local + Supabase.
- **Regla 24 h:** si el mismo chat ya reportó hace < 24 h, **no crea caso nuevo**: anexa la
  nueva información al folio existente y responde *"su petición ya está en proceso"*.
- **Personalidad:** saludo según la hora, trato de usted, lenguaje formal de ingeniero
  agrónomo, **no inventa ni sugiere** datos.
- **Seguridad (ingeniería social):** detecta y neutraliza prompts de inyección, pedidos de
  la base de datos/credenciales/tokens y temas ajenos → responde el rechazo cortés y
  **registra el incidente** (`cache/incidentes.json`) **y avisa a los desarrolladores**.
- **Botones para el coordinador:** ✅ Aprobar (envía folio al productor), 🔁 Cambiar técnico
  (reasigna al siguiente candidato), 🚫 Falsa alarma → con `POST /avisos` reales.
- **Sesiones a prueba de reinicios:** se persisten en `cache/sesiones.json`.

---

## 5. Reglas de decisión (paso 3, 100 % código)

### Prioridad → Semáforo
`prioridad = severidad + superficie(pct) + etapa` (cuarentenaria → 100).
- severidad: baja 15 · media 25 · alta 40 · crítica 50.
- superficie: `redondeo_comercial(ha_afectadas / 4 × 25)`, tope 25.
- etapa: crítica 25 · susceptible 15 · otra 5.
- Semáforo: rojo ≥ 85 · naranja ≥ 70 · amarillo ≥ 40 · verde < 40.
- `pct` de la IA o extraído del texto; si el productor no lo dice → **10**.

### Técnico
Especialidad de la plaga + carga < 5 en `momento=<recibido>` + más cercano por
**haversine (R=6371 km)**; empates: menor carga → menor id; sin candidato → `null`.

### Brote (refinado)
3+ casos de la misma plaga a **< 5 km** en los últimos **168 h**, contando el actual.
Cuentan `/casos-previos` + casos propios. **Refinamiento anti-falso-brote:** los casos
propios del MISMO productor cuentan **una vez por brote** (su cadena de mensajes no infla
el conteo — lección del caso R-2043). Los previos jamás se deduplican. **40/40** 🏆

---

## 6. Registro, complementos y envío automático

- **Payload oficial:** `{reporte_id, es_plaga, plaga, semaforo, tecnico_id, brote}`
  (+ `prioridad` opcional, sin puntos, para retroalimentación).
- **Envío en lote inicial (Plan B, fas IA):** 62 reportes → **62 enviados · 0 errores de red**.
  Solo 2 campos errados en todo el lote inicial.
- **Complemento:** recuperamos puntos de casos registrados sin semáforo/técnico/brote
  (R-2043 +1, R-2065 +3, R-2066 +3, R-2064 +1, R-2055 +1 → **+9 netos**).
- **Automático desde 21-oct:** el agente en el servidor corre con `--enviar`,
  `--extras --avisos-reales --preguntas --telegram` → **cada reporte nuevo se procesa
  y registra solo (~20 s de latencia)**.
- **Filosofía de puntos:** `desconocida` y campos no enviados valen **0 (nunca −1)**;
  "no arriesgar es la estrategia". Los campos de Nivel 2 se envían SIEMPRE que haya plaga
  (la API los ignora en seguimientos reales, pero los cuenta en casos nuevos).

---

## 7. Dashboard Web (Emmanuel) y Supabase

- **Dashboard** (Node + Express + Leaflet): mapa de 264 parcelas, monitor de casos con
  filtros, KPIs, semáforos/técnicos/brotes (PR de Emmanuel), capa de técnicos, `cache/`
  como respaldo si la API falla. **En producción** en el link público.
- **Supabase** (`supabase_repositorio.py` + migraciones `supabase/*.sql`): persiste
  reportes, casos (prioridad/pct corregidos), envios, avisos y preguntas. **Se activa solo**
  cuando existan `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` (pendiente de Emmanuel); sin
  llaves el sistema no se rompe (queda caché local).

---

## 8. Errores y retroalimentación (los 5 errores al corte)

| Caso | Campo | Causa raíz | ¿Corregible? |
|---|---|---|---|
| R-2056 | es_plaga | **La IA sola** dijo "no plaga" en un texto de roya; las reglas acertaban → se creó el Consenso Híbrido | ❌ (irrecuperable) |
| R-2015 | semaforo | pct/etapa de voz distinta a la oficial | ❌ |
| R-2043 | brote | casos propios del mismo productor inflaron el conteo → **regla refinada** | ❌ ya evaluado |
| R-2064 | semaforo | estimamos amarillo con respuesta parcial | ❌ |
| R-2055 | brote | regla aún conservadora en ese cluster | ❌ |

**Lecciones convertidas en código:** consenso híbrido (IA supervisada) · brote deduplicado ·
envío siempre de Nivel 2 · sesiones persistentes · complementos automáticos disponibles.

---

## 9. Lo que queda / pendientes

| Pendiente | Estado |
|---|---|
| Producir respuestas de productores (preguntas) → clasificar y complementar | ⏳ 5 respuestas llegaron; R-2042-R aún pendiente |
| Pegar `SUPABASE_SERVICE_ROLE_KEY` (Emmanuel) para persistencia en BD | ⏳ |
| README final con capturas y "quién hizo qué" | ⏳ pendiente |
| Defensa individual (Rafael **y** Emmanuel): `NIVEL2.md`, `ARQUITECTURA.md`, demo en vivo | lista |
| Monitoreo del 1.er lugar (opcional: vigilante por Telegram si nos adelantan) | ⏳ opcional |

---

## 10. Comandos útiles

```powershell
python bot/listener.py --una-vez          # una pasada de clasificación
python bot/listener.py --enviar --extras --avisos-reales --preguntas --telegram
python bot/enviar_casos.py --enviar       # registro en lote (pide CONFIRMAR)
python bot/enviar_avisos.py               # lote de avisos reales del reto extra
python bot/pipeline.py --desde-api --enviar --interpretar-ia
python bot/probar_motor.py                # 77 pruebas
python bot/validar_nivel2.py              # 40/40 fórmulas
python bot/validar_brote.py               # 40/40 brote
python bot/estado_despliegue.py           # estado en el servidor
```

---

*Fin del reporte. Actualizable hasta el cierre del jueves 22 (23:59).*
