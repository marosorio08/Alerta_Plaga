# 🏗️ Arquitectura del agente — Hackathon IT GREEN (flujo oficial de 5 pasos)

> Documento de defensa. Describe el flujo que muestra el video oficial de
> IT GREEN y cómo está implementado en `bot/` con código modular, asíncrono y
> con control de excepciones.

```
┌────────────────────────────────────────────────────────────────────────────┐
│                          FLUJO OFICIAL (5 pasos)                          │
└────────────────────────────────────────────────────────────────────────────┘

  1 RECIBIR     2 INTERPRETAR (IA)      3 DECIDIR (reglas)    4 GUARDAR   5 REGISTRAR
  GET /reportes  OpenRouter             nivel2.py             Supabase    POST /casos
  ┌──────────┐  ┌───────────────┐      ┌──────────────┐      ┌────────┐  ┌──────────┐
  │ id       │  │ JSON estricto │      │ semaforo     │      │ reporte│  │ reporte_ │
  │ parcela_ │→ │ {"es_plaga":  │→     │ tecnico_id   │→     │ caso   │→│ id,      │
  │ id       │  │  bool,        │      │ brote        │      │ envios │  │ es_plaga,│
  │ texto    │  │  "plaga",     │      │ + push coord.│      │        │  │ plaga,   │
  │          │  │  "pct"}       │      │ (Telegram)   │      │        │  │ semaforo,│
  └──────────┘  └───────────────┘      └──────────────┘      └────────┘  │ tecnico_ │
                                                                          │ id, brote│
                                                                          └──────────┘
```

## Módulos (responsabilidad única)

| Módulo | Paso | Responsabilidad |
|---|---|---|
| `api_cliente.py` | 1 y 5 | `GET /reportes`, `POST /casos`, reintentos, errores tipados |
| `prompts.py` | 2 | Prompt del agente IA con JSON estricto + parseo/normalización |
| `interpretar.py` | 2 | OpenRouter (`response_format: json_object`, temperature=0), reintentos con backoff, **respaldo determinista** |
| `clasificador.py` | 2 | Orquesta IA → reglas; cruce parcela→cultivo, anti-inyección |
| `nivel2.py` | 3 | **Reglas puras (sin IA):** prioridad → semáforo → técnico (haversine) → brote |
| `pipeline.py` | 1-5 | Orquestador documentado del flujo completo (CLI) |
| `telegram_notificador.py` | 3 | Push al coordinador (rojo/naranja/brote) con botones |
| `supabase_repositorio.py` | 4 | Upsert reportes/casos/envios/avisos/preguntas en la BD |
| `listener.py` | 1-5 | Motor en tiempo real: polling cada 20 s en el servidor |

## Detalle por paso

### 1 · RECIBIR
`GET /reportes` con `X-Equipo-Token`. Se extrae `id`, `parcela_id`, `texto`
(y `recibido`, que gobierna técnicos y brotes). El listener deduplica por id.

### 2 · INTERPRETAR (IA, con respaldo)
- Prompt: "devuelve SOLO JSON" + contexto agronómico (cultivo y candidatas).
- `response_format: {"type": "json_object"}`, `temperature=0`, 3 reintentos.
- **Normalización obligatoria** (`prompts.normalizar_interpretacion`):
  - `plaga` debe existir en el catálogo y ser compatible con el cultivo;
    si no → `"desconocida"` (nunca −1 por inventar).
  - `pct` 0-100; si el productor no lo dice o no es numérico → **10**.
  - `es_plaga:false` si el mensaje no es un reporte (también detecta y anota
    intentos de ingeniería social).
- **Respaldo determinista**: si no hay API, timeout o JSON inválido, la
  decisión la toman las reglas ponderadas (`clasificar_texto`). Un fallo de
  red jamás puede costar un punto.
- Voz y foto: STT `gpt-4o-transcribe`+respaldo y visión con consenso de 3
  modelos (`temperature=0`), integrados ANTES de la fusión texto+imagen.

### 3 · DECIDIR (reglas puras — la IA nunca decide puntos)
| Regla | Dónde | Fórmula |
|---|---|---|
| `semaforo` | `nivel2.calcular_prioridad` | `severidad + superficie(pct) + etapa`; cuarentenaria=100; umbrales rojo≥85, naranja≥70, amarillo≥40, verde<40 |
| `tecnico_id` | `nivel2.elegir_tecnico` | Especialidad + carga<5 en `momento=<recibido>` + más cercano por haversine (R=6371); empates por carga e id |
| `brote` | `nivel2.contar_casos_cercanos` | 3+ casos (contando este) de la misma plaga a **<5 km** en las últimas **168 h**; cuentan previos + casos propios |

Validación contra la respuesta oficial: **Prioridad 40/40 · Semáforo 40/40 ·
Técnico 40/40 · Brote 40/40** (`bot/validar_nivel2.py`, `bot/validar_brote.py`).

Push al coordinador: Telegram para semáforo rojo/naranja o brote, con botones
Aprobar / Cambiar técnico / Falsa alarma (procesados por `bot_telegram.py`).

### 4 · GUARDAR
`supabase_repositorio` (upsert por id): reportes, casos (con prioridad/pct
corregidos para no perder el 0), avisos, preguntas, envíos. Sin llaves de
Supabase → queda la caché local (`cache/`) y el flujo **no se rompe**.

### 5 · REGISTRAR
`POST /casos` con el payload oficial:
```json
{"reporte_id": "R-XXXX", "es_plaga": true, "plaga": "roya_frijol",
 "semaforo": "naranja", "tecnico_id": "T-05", "brote": true}
```
(+ `prioridad` opcional, sin puntos, solo retroalimentación). Una sola
oportunidad por `reporte_id`; el **desempate es por latencia**, así que los
pasos 2-4 no bloquean al 5 (notificación y guardado van en hilo).

## Asincronía y excepciones

| Garantía | Cómo |
|---|---|
| No bloquear `REGISTRAR` | `concurrent.futures.ThreadPoolExecutor` para notify/guardar |
| Un fallo no tumba el pipeline | `try/except` por paso en `pipeline.procesar` |
| IA caída | Reintentos con backoff + respaldo determinista |
| Catálogo cambia | Recarga de `/plagas` y `/parcelas` cada 10 min |
| RIRO de seguridad | Anti-inyección en prompt y en `bot_telegram._detectar_abuso` |

## Cómo se corre

```bash
# Lote completo (passos 1-4, dry-run, sin registrar)
python bot/pipeline.py --desde-api --sin-notificar

# Uno solo, con IA en el paso 2
python bot/pipeline.py --reporte R-2016 --interpretar-ia --sin-notificar

# Registrar (irreversible; requiere CONFIRMAR si se usa enviar_casos.py)
python bot/pipeline.py --desde-api --enviar --interpretar-ia
```