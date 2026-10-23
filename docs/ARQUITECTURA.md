# Arquitectura del sistema — Alerta Plaga 7_7

> Documento vivo. Describe el sistema en `main` (`5a434f0`) y marca las
> propuestas que viven en la rama `Caso_Emmanuel` (PR #9).
>
> El objetivo no es solo “clasificar”: es **no perder puntos**, dejar
> trazabilidad y permitir que una persona revise lo dudoso antes de registrar.

---

## 1. Flujo oficial de 5 pasos

```
┌──────────────┐   ┌────────────────────┐   ┌────────────────────┐
│ 1 RECIBIR    │   │ 2 INTERPRETAR      │   │ 3 DECIDIR          │
│ GET /reportes│──▶│ reglas + IA        │──▶│ nivel2.py          │
│ dedupe/caché │   │ STT · visión       │   │ código puro        │
└──────────────┘   └────────────────────┘   └─────────┬──────────┘
                                                       │
                     ┌─────────────────────────────────▼──────────┐
                     │ 4 GUARDAR                                  │
                     │ cache/ + Supabase                          │
                     └─────────────────┬──────────────────────────┘
                                       │
                     ┌─────────────────▼──────────────────────────┐
                     │ 5 REGISTRAR                                │
                     │ POST /casos (solo con PERMITIR_ENVIOS=1)   │
                     └────────────────────────────────────────────┘
```

### Por qué esta separación

1. **El reglamento exige reglas deterministas** para prioridad, semáforo,
   técnico y brote.
2. **Reproducibilidad:** los mismos datos deben dar el mismo resultado.
3. **Testeable:** las fórmulas se comparan contra 40 casos con respuesta oficial.
4. **La IA se usa donde aporta:** leer el mensaje, transcribir voz, describir una
   foto y extraer el porcentaje. Nunca decide puntos.

---

## 2. Módulos

| Módulo | Paso | Responsabilidad |
|---|---|---|
| `bot/api_cliente.py` | 1, 5 | HTTP, token, reintentos, errores tipados |
| `bot/descargar_catalogos.py` | 1 | Baja catálogos y reportes a `cache/` |
| `bot/listener.py` | 1–5 | Polling cada 20 s, 3 fases, cola de dudosos |
| `bot/clasificador.py` | 2 | Reglas + IA, STT/visión, cultivo, hospederos, seguimientos |
| `bot/prompts.py` | 2 | Prompt JSON estricto y normalización |
| `bot/interpretar.py` | 2 | OpenRouter, `temperature=0`, respaldo determinista |
| `bot/nivel2.py` | 3 | Prioridad, semáforo, técnico, brote |
| `bot/decision_autonoma.py` | 3 | Reanálisis de dudosos en 4 intentos |
| `bot/resolver_cola.py` | 3 | Procesa la cola de dudosos |
| `bot/vigilante.py` | 3 | Avisa reportes sin registrar o con campos agregables |
| `bot/bot_telegram.py` | 3 | Bot público, comandos y botones |
| `bot/telegram_notificador.py` | 3 | Mensajes y alertas al coordinador |
| `bot/extras.py` | 3 | Avisos, preguntas, brotes y plazos |
| `bot/supabase_repositorio.py` | 4 | Upsert en Supabase |
| `bot/pipeline.py` | 1–5 | Orquestador CLI del flujo |
| `bot/confirmados.py` | 4–5 | **Rama Caso_Emmanuel:** ledger de confirmados |
| `app_web/server.js` | — | Proxy autenticado y fallback de caché |
| `app_web/public/*` | — | Dashboard Leaflet + KPIs + casos |

---

## 3. Paso 1 — Recibir

`GET /reportes` con `X-Equipo-Token`.

Se conserva:

- `id`
- `parcela_id`
- `productor_id`
- `tipo`
- `texto` / `audio_url` / `foto_url`
- `recibido`
- `respuesta_a`

El listener deduplica por `id` y refresca catálogos cada 10 min.

### Datos que se cachean

- `plagas.json`
- `parcelas.json`
- `productores.json`
- `tecnicos.json`
- `reportes.json`
- `visitas.json`
- `cache_casos_previos.json`
- `casos_propuestos.json`
- `listener_estado.json`
- `revision_pendiente.json`

---

## 4. Paso 2 — Interpretar

### Texto

Modo recomendado: `INTERPRETAR_IA=2` (consenso híbrido).

1. Reglas deterministas evalúan el mensaje.
2. La IA devuelve JSON estricto (`es_plaga`, `plaga`, `pct`).
3. Si coinciden, se acepta.
4. Si difieren:
   - se busca precedente histórico de la parcela o del cultivo;
   - si existe, manda el precedente;
   - si no, **mandan las reglas**.

Modos:

| `INTERPRETAR_IA` | Comportamiento |
|---|---|
| `0` | Solo reglas |
| `1` | IA primero, respaldo a reglas |
| `2` | Consenso híbrido con desempate histórico |

### Voz

- STT principal: `gpt-4o-transcribe`.
- Respaldo: otro modelo.
- Si los dos coinciden, alta confianza.
- Si difieren, gana la transcripción con más señal agronómica.
- Si no hay señal suficiente → `desconocida`.
- Un STT vacío **no se cachea**: se reintenta.

### Foto

- Visión con consenso de 3 modelos y `temperature=0`.
- Fusión con el pie de foto.
- Si texto y visión coinciden → alta confianza.
- Si difieren → `desconocida` salvo que el texto tenga señal fuerte.

### Reglas de apoyo

- Prefiltro de mensajes administrativos, saludos, precios, juntas, cierres.
- Anti prompt-injection.
- Cruce `parcela → cultivo`.
- Catálogo de cultivos hospederos y síntomas del documento oficial.
- Detección de seguimiento por `respuesta_a` o por ventana de 24 h.
- Extracción de porcentaje:
  - “75 %”
  - “setenta y cinco por ciento”
  - “tres cuartas partes”
  - “la mitad”
  - “una de cada cuatro matas”
  - “todas las plantas” → 100 %
  - si no lo dice → 10 %

### Regla de oro de la interpretación

`plaga` debe existir en el catálogo y ser compatible con el cultivo. Si no, se
marca `desconocida`. Nunca se inventa una plaga para “ganar” un punto.

---

## 5. Paso 3 — Decidir

Todo lo que vale puntos se calcula en `bot/nivel2.py`.

### Prioridad

```
severidad + superficie(pct) + etapa
```

- severidad: baja 15 / media 25 / alta 40 / crítica 50;
- superficie: `min(25, round(ha/4 × 25))`, con `ha = superficie_ha × pct/100`;
- etapa: crítica 25 / susceptible 15 / otra 5;
- cuarentenaria → 100.

### Semáforo

| Prioridad | Semáforo |
|---|---|
| 85–100 | rojo |
| 70–84 | naranja |
| 40–69 | amarillo |
| 0–39 | verde |

### Técnico

1. misma especialidad;
2. carga < 5 en `momento = recibido`;
3. el más cercano por haversine (R = 6371 km);
4. empates: menor carga, luego menor id;
5. si no hay candidato → `null`.

### Brote

Regla oficial:

> 3+ casos de la misma plaga, a menos de 5 km, en las últimas 168 h, contando
> el caso actual.

Implementación:

- previos + casos propios;
- sin seguimientos, no-plaga ni `desconocida`;
- ventana inclusiva de 168 h;
- `< 5 km` estricto;
- dedupe de casos propios por **productor + parcela** en clústeres de 24 h;
- `n >= 3` → `true`;
- `n == 2` → zona gris (`None`, no se envía);
- `n <= 1` → `false`.

### Decisión autónoma de dudosos

`decision_autonoma.py` hace hasta 4 intentos:

1. app vs motor;
2. solo reglas vs IA;
3. antecedentes: padre, misma parcela, seguimiento;
4. brote profundo: misma parcela o tercero por coordenadas del reporte.

Si tras 4 intentos no hay certeza, no se envía y se avisa al coordinador.
Si hay certeza y `PERMITIR_ENVIOS=1`, se registra.

---

## 6. Paso 4 — Guardar

### Caché local

Siempre se escribe en `cache/`. Es la red de seguridad si Supabase o la API
fallan.

### Supabase

`supabase_repositorio.py` hace upsert de:

- reportes;
- casos;
- envíos;
- avisos;
- preguntas;
- visitas;
- eventos.

El esquema está en `supabase/schema.sql`. RLS activo; el navegador nunca lee la
base directamente.

### Ledger de confirmados (propuesta de `Caso_Emmanuel`)

`bot/confirmados.py` guarda solo los casos que la API aceptó (`201`/`409`) con
plaga y coordenadas congeladas. El objetivo es que el brote no cuente casos que
la API no conoce: propuestas, aparcados o falsas alarmas.

---

## 7. Paso 5 — Registrar

`POST /casos` con el payload oficial:

```json
{
  "reporte_id": "R-XXXX",
  "es_plaga": true,
  "plaga": "roya_frijol",
  "semaforo": "naranja",
  "tecnico_id": "T-05",
  "brote": true
}
```

Reglas:

- una sola oportunidad por `reporte_id`;
- los campos se congelan;
- `POST /casos` no se usa como prueba;
- para probar formato: `POST /casos/validar`;
- el desempate es por latencia;
- `PERMITIR_ENVIOS=1` es obligatorio para enviar.

---

## 8. Cola de dudosos

Se aparca un caso cuando:

- `brote=true`;
- `n=2`;
- plaga `desconocida`;
- confianza < 0.55;
- voz sin transcripción;
- parcela inferida.

La cola vive en `cache/revision_pendiente.json`.

### Resolver

`resolver_cola.py`:

- reanaliza con `decision_autonoma`;
- si es seguro y los envíos están activos, registra;
- si es seguro y los envíos están apagados, deja `listo_para_envio`;
- si sigue dudoso, avisa una vez por Telegram;
- si ya está registrado, lo saca de la cola.

### Botones de Telegram

- Aceptar / registrar.
- Registrar sin brote.
- Marcar brote.
- Dejar en cola.
- Descartar.

---

## 9. Vigilante

`vigilante.py` revisa:

1. reportes publicados sin registrar;
2. casos registrados con campos agregables;
3. dudosos en cola.

Nunca registra. Solo avisa. Usa `POST /casos/validar` para comprobar estado.

---

## 10. Dashboard

`app_web/`:

- proxy autenticado a la API;
- token solo en backend;
- fallback a `cache/` si la API falla;
- KPIs;
- mapa Leaflet con parcelas y técnicos;
- monitor de casos con filtros;
- estadísticas por plaga, cultivo y municipio.

Endpoints principales:

- `/api/resumen`
- `/api/parcelas`
- `/api/reportes`
- `/api/tecnicos`
- `/api/casos`
- `/api/plagas`
- `/api/equipo`
- `/api/media/:archivo`
- `/api/health`

---

## 11. Despliegue

- agente en servidor SSH bajo `supervisor`;
- dashboard con PM2;
- `CASOS_SALIDA` comparte `casos_propuestos.json` con el dashboard;
- `PERMITIR_ENVIOS` controla el registro real;
- `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` habilitan Telegram;
- `OPENROUTER_API_KEY` habilita IA/STT/visión.

Ver [`OPERACION.md`](OPERACION.md) para comandos y variables.

---

## 12. Robustez

| Riesgo | Mitigación |
|---|---|
| API caída | caché local + reintentos |
| IA caída o JSON inválido | respaldo determinista |
| STT/visión vacío | no cachear, reintentar |
| Catálogo cambia | refresco cada 10 min |
| Caso dudoso | cola + visto bueno |
| Brote mal marcado | `n=2` gris + revisión + ledger propuesto |
| Envío accidental | `PERMITIR_ENVIOS` apagado por defecto |
| Duplicado | estado `enviados` + `validar_caso` |

---

## 13. Ramas y estado

Este documento describe `main`. La rama `Caso_Emmanuel` (PR #9) añade el ledger
de confirmados y el replay de brotes. La rama `fix/brotes-revision-rafa` (PR #8)
contiene la propuesta conservadora de brote y las alertas de revisión.

Ver [`ESTADO_Y_RAMAS.md`](ESTADO_Y_RAMAS.md) para el estado exacto y los riesgos
de merge.
