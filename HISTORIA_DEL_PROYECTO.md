# 📜 HISTORIA DEL PROYECTO — «Alerta Plaga» (equipo 7_7)

> **Documento de memoria y transferencia.**
> Cuenta **todo** lo que se hizo, en qué orden, por qué se tomó cada decisión,
> qué falló y cómo se corrigió, y qué queda pendiente.
>
> *Corte:* martes 20 de octubre de 2026, 21:35 (hora del centro de México).
> *Sesión de trabajo:* 17:00 → 21:35 (4 h 35 min).
> *Autor de la bitácora:* Rafael Martínez (Rol A — IA, lógica y backend).
>
> ⚠️ Este archivo **no contiene credenciales**. Las llaves viven en `.env`
> (ignorado por git) y en `MEMORIA_HACKATHON.md` (también ignorado).

---

## Índice

1. [Ficha del proyecto](#1-ficha-del-proyecto)
2. [Resumen en una página](#2-resumen-en-una-página)
3. [Línea del tiempo](#3-línea-del-tiempo)
4. [El reto y sus reglas](#4-el-reto-y-sus-reglas)
5. [Arquitectura](#5-arquitectura)
6. [Crónica detallada por etapas](#6-crónica-detallada-por-etapas)
7. [Decisiones técnicas y su justificación](#7-decisiones-técnicas-y-su-justificación)
8. [Incidentes y correcciones](#8-incidentes-y-correcciones)
9. [Verificación y pruebas](#9-verificación-y-pruebas)
10. [Despliegue en producción](#10-despliegue-en-producción)
11. [Estado actual de los datos](#11-estado-actual-de-los-datos)
12. [Lo que falta](#12-lo-que-falta)
13. [Inventario de archivos](#13-inventario-de-archivos)
14. [Comandos de operación](#14-comandos-de-operación)
15. [Cronología de Git y PRs](#15-cronología-de-git-y-prs)
16. [Glosario](#16-glosario)
17. [Notas para la defensa del viernes](#17-notas-para-la-defensa-del-viernes)
18. [Lecciones aprendidas](#18-lecciones-aprendidas)

---

## 1. Ficha del proyecto

| Campo | Valor |
|---|---|
| **Reto** | «Alerta Plaga» — curso-taller *Git, servidores y agentes de IA* |
| **Organizan** | IT Green × DIMA, Universidad Autónoma Chapingo |
| **Fechas del reto** | 19 al 23 de octubre de 2026 (cierre jueves 22, 23:59) |
| **Equipo** | `equipo02` — nombre en plataforma: **7_7** |
| **Integrantes** | Rafael Martínez (Rol A) · Emmanuel Osorio (Rol B) |
| **Repositorio** | `https://github.com/marosorio08/Alerta_Plaga_Gusano` (privado) |
| **API del reto** | `https://itg.tailf75570.ts.net` |
| **App pública** | `https://equipo02.179-236-73-82.sslip.io` (puerto 3000 del servidor) |
| **Servidor** | `ssh -p 2202 equipo02@179-236-73-82.sslip.io` (Ubuntu, Node 22, Python 3.12, 8 GB RAM) |
| **Stack** | Python 3 (bot) · Node.js 20+ + Express + Leaflet (dashboard) |
| **IA** | OpenRouter: `gpt-4o-transcribe`, `whisper-large-v3`, `gpt-4o-mini`, `gemini-2.5-flash`, `gpt-4o` |

### Reparto de trabajo (según la WBS del PDF)

| Rol | Persona | Responsabilidad |
|---|---|---|
| **A** | Rafael | IA, lógica, backend, despliegue técnico |
| **B** | Emmanuel | Dashboard (`app_web/`), Supabase, Telegram |

**Regla de convivencia acordada:** Rafa **no modifica `app_web/`** para no chocar con
Emmanuel. Todo el trabajo de Rafa vive en `bot/` y `docs/`.

---

## 2. Resumen en una página

### Lo que el sistema hace hoy

1. **Vigila** la API cada 20 s y detecta reportes nuevos (texto, voz, foto).
2. **Interpreta** el mensaje con IA: ¿es plaga?, ¿cuál?, ¿qué porcentaje de la parcela?
3. **Decide con código determinista**: prioridad → semáforo → técnico → (brote, pendiente).
4. **Valida el formato** contra `/casos/validar` sin gastar puntos.
5. **Comparte** los casos con el dashboard por un archivo JSON común.
6. **Está desplegado** en el servidor con `supervisor` (app + agente).
7. **No ha registrado nada** en `POST /casos` (decisión explícita de Rafa).

### Cifras al corte

| Dato | Valor |
|---|---|
| Reportes publicados por la API | **62** |
| Máximo posible | **238 puntos** |
| Casos registrados por nosotros | **0** |
| Puntos | **0** |
| Lugar | **4.º** |
| Reportes procesados por el listener | **61** (el 62 llegó después) |
| Casos propuestos en caché | **62** |
| Con plaga identificada | **44** |
| Con plaga `desconocida` | **6** |
| No son plaga | **12** |
| Con semáforo calculado | **43** |
| Con técnico asignado | **43** |
| Brotes detectados (agrupados) | **9** |
| Pruebas del motor | **49/49** |
| Validación Nivel 2 contra casos previos | **40/40 · 40/40 · 40/40** |

### Estado de los entregables

| Entregable | Estado |
|---|---|
| Motor de clasificación (texto) | ✅ |
| STT (voz) con consenso | ✅ |
| Visión (foto) con consenso de 3 modelos | ✅ |
| Nivel 2: prioridad, semáforo, técnico | ✅ |
| Nivel 2: brote por caso | ❌ **pendiente** (regla nueva, 21:35) |
| Listener continuo | ✅ |
| Dashboard profesional | ✅ (Emmanuel lo seguirá modificando) |
| Despliegue en servidor | ✅ app + agente con supervisor |
| Telegram | ⏸ token presente, falta `chat_id` y activación final |
| Supabase | ⏸ lo lleva Emmanuel; faltan permisos de escritura |
| Registro de casos | ⏸ **esperando orden de Rafa** |
| README final «quién hizo qué» | ⏸ pendiente |

---

## 3. Línea del tiempo

| Hora | Qué pasó |
|---|---|
| **17:00** | Lectura de `MEMORIA_HACKATHON.md`; pruebas de conexión: API, SSH y GitHub. Se descubre que el repo está **vacío y privado** y que hay **53 reportes** (la memoria decía 50). |
| **17:01** | `git init`, primer commit `f379a8c`, push verificado con la cuenta `exogenesis1083-ops`. Se excluyen `.env`, memoria, `curso_github/`, `gemini-extension/`. |
| **17:22** | Recomendación de orden: calentamientos → cliente API + catálogos → clasificador. |
| **17:49** | Llega la WBS en PDF (7 bloques). Se registra el repo (`PATCH /equipo` → `{"ok":true}`). **OpenRouter devuelve 401: key expirada.** |
| **17:50** | Descarga de `/plagas`, `/parcelas`, `/productores`, `/tecnicos`, `/reportes`. Se descubre `GET /casos-previos` (**40 casos con respuesta correcta**) y se lee `/reglas`. |
| **17:53** | Clasificador determinista con anti-inyección, cruce parcela→cultivo y regla de cultivo exclusivo (limón→HLB, grano→gorgojo). Commit `fdd0fc7`. |
| **17:58** | `motor_audio_foto.py` y `enviar_casos.py` (dry-run + `CONFIRMAR`). Commit `90d7842`. |
| **18:02** | Llega la **nueva key de OpenRouter**. Se confirma saldo ($48.95, expira 27-oct). Se lanza el dashboard en un subagente. |
| **18:04** | Transcripción de 27 audios. Bug en el prompt de visión (`.format()` con JSON de ejemplo) → corregido. |
| **18:06** | Reglas de texto reescritas con señales ponderadas; candidatos de visión restringidos por cultivo. |
| **18:11** | Consenso de **3 modelos de visión**; 8 fotos analizadas (6 unánimes, 2 con mayoría 2/3). |
| **18:13** | Dry-run de 55 casos: 55/55 validados, estimación ~94/101. **No se envía nada.** |
| **18:23** | Dashboard terminado. Se detecta el **token escrito en `server.js`** → se mueve a variable de entorno y **se purga del historial de git**. Commit `d75fcbf`. |
| **18:34** | Checklist WBS: 15 completas, 7 parciales, 10 pendientes. |
| **18:57** | Se crea la rama **`Rafa`**. Auditoría de Whisper contra otros modelos. |
| **18:59** | Consenso STT (`gpt-4o-transcribe` + `whisper`), fusión texto+foto y `respuesta_a`. |
| **19:02** | El consenso de visión se mueve **dentro del pipeline** (antes vivía en un script aparte y se perdía al reprocesar). |
| **20:11** | Corregidos `Counter` y los errores 429 con reintentos y backoff. |
| **20:14** | `listener.py` continuo + `recargar_catalogo()`; detecta solo `R-2057`. |
| **20:15** | Batería de pruebas: **31/31**. Bucle estable en 3 ciclos. Commit `b6d65a4`. |
| **20:29** | PR **#1** abierto (`Rafa` → `main`). |
| **20:36** | PR #1 **fusionado** (`140ef82`). |
| **20:39** | **Cambia el reto**: máximo 103 → 188 y aparecen `semaforo` y `tecnico` en `aciertos`. Se leen las secciones 7-9 de `/reglas`. |
| **20:40** | Fórmulas validadas contra los 40 casos previos: **40/40 en las tres**. |
| **20:52** | Orden de Rafa: implementar Nivel 2, explicar el diseño, dejar extras preparados, revisar servidor y no registrar aún. |
| **20:53** | Se confirma que **el dashboard no estaba desplegado**: en `~/app` corría otra app del curso. Solo hay `SUPABASE_URL` y `SUPABASE_PUBLISHABLE_KEY`. |
| **20:55** | `nivel2.py` + integración + parser de números en español («setenta y cinco» = 75). |
| **20:57** | `extras.py` (avisos, preguntas, brotes, plazos) y `telegram_notificador.py`. Brotes agrupados con BFS transitivo. |
| **21:00** | **49/49 pruebas**. `docs/NIVEL2.md` escrito para la defensa. |
| **21:01** | Se detecta y corrige la contraseña SSH escrita en `revisar_servidor.py`. |
| **21:02** | PR **#2** abierto. |
| **21:11** | PR #2 **fusionado** (`5f453d1`). |
| **21:13** | `package.json` en la raíz para el arranque en el servidor (`98a0327`). |
| **21:16** | `CASOS_SALIDA`: el agente escribe los casos donde los lee el dashboard (`ecce029`). |
| **21:18** | Fix: faltaba `import os` (`26ae2f3`). |
| **21:19** | **Despliegue exitoso**: `supervisor` levanta `app` y `agente`; la caché compartida tiene 62 casos con 43 semáforos. |
| **21:29** | El agente refresca catálogos solo (10 plagas, 264 parcelas). |
| **21:35** | Al documentar se descubre un **objetivo nuevo: `brote`**, y el máximo sube a **238**. |
| **21:2x** | PR #3 y #4 fusionados; `main` = `043eb55`. |

---

## 4. El reto y sus reglas

### 4.1 Nivel 1 (lunes 19)

Para cada mensaje: decidir **si es reporte de plaga** y **cuál plaga** es.
El campo `urgente` se calculaba con una lista fija.

### 4.2 Nivel 2 (martes 20, noche)

Además de lo anterior, cada caso lleva:

- `semaforo` (rojo / naranja / amarillo / verde)
- `tecnico_id`
- `brote` (booleano) ← **agregado después de las 21:00**
- `prioridad` (opcional, **no da puntos**, sirve para autoverificación)

### 4.3 Prioridad (0–100)

```
prioridad = severidad + superficie + etapa
```

| Factor | Cálculo | Máx. |
|---|---|---|
| **Severidad** | del catálogo: baja 15 · media 25 · alta 40 · crítica 50 | 50 |
| **Superficie** | `ha_afectadas = superficie_ha × pct/100`<br>`puntos = min(25, redondeo_comercial(ha_afectadas / 4 × 25))` | 25 |
| **Etapa** | crítica para esa plaga/cultivo 25 · susceptible 15 · otra 5 | 25 |

- **Redondeo comercial**: 0.5 sube (`14.06 → 14`, `14.5 → 15`).
- **Plaga cuarentenaria** → prioridad **100 (rojo)** sin cálculo.

**Ejemplo oficial:** maíz 4.5 ha, V8, cogollero (alta), mitad de las matas (50 %):
`40 + redondear(2.25/4×25 = 14.06) = 14 + 25 (V8 crítica) = 79` → **naranja**.
Nuestro código devuelve exactamente 79.

### 4.4 Semáforo y plazos

| Prioridad | Semáforo | Visita a más tardar |
|---|---|---|
| 85–100 | 🔴 rojo | 24 h |
| 70–84 | 🟠 naranja | 48 h |
| 40–69 | 🟡 amarillo | 72 h |
| 0–39 | 🟢 verde | 7 días |

Solo **rojo** y **naranja** (y los brotes) se avisan al coordinador por Telegram.

### 4.5 Técnico

1. Solo de la **especialidad de la plaga** (`entomologia` o `fitopatologia`).
2. Solo con **carga < 5** en el **momento del mensaje**:
   `GET /tecnicos?momento=<recibido>`.
3. El **más cercano** a la parcela por **haversine** (R = 6371 km).
4. Empates al metro: menor carga y luego menor `id`.
5. Si nadie cumple: `tecnico_id: null` (vale 0, no resta).

### 4.6 Brote (regla descubierta al cierre de esta bitácora)

Hay brote si, **contando el caso actual**, hay **3 o más casos de la misma plaga**
cuyas parcelas están a **menos de 5 km** de la parcela del mensaje, recibidos en los
**7 días previos (168 h, incluido el momento del mensaje)**.

- Cuentan los casos de `GET /casos-previos` **y** los casos nuevos propios.
- **No cuentan**: seguimientos, mensajes que no son reportes, reportes sin aclarar.
- La hora es la `recibido` del mensaje, no la de procesamiento.
- `GET /casos-previos` trae `brote` correcto: **11 de 40** son brote.

### 4.7 Puntos (`POST /casos`)

| Mensaje | ¿Es plaga? | ¿Plaga? | Semáforo | Técnico | Brote |
|---|---|---|---|---|---|
| Caso nuevo | +1 / −1 | +1 / −1 / `desconocida` 0 | +1 / −1 | +1 / −1 | +1 / −1 |
| Seguimiento o sin aclarar | +1 / −1 | +1 / −1 / `desconocida` 0 | no cuenta | no cuenta | no cuenta |
| Otra cosa | +1 / −1 | — | — | — | — |

- Un caso nuevo vale **hasta 5 puntos**; un seguimiento, hasta 2; «otra cosa», 1.
- **No arriesgar no resta**: `desconocida` = 0; no mandar semáforo/técnico/brote = 0.
- **Una sola vez por mensaje**: cuenta el primer envío.
- **Complemento**: si un mensaje ya registrado no tenía semáforo/técnico/brote, se puede
  reenviar solo con lo que falta; la respuesta trae `"complemento": true`.
- **Desempate por latencia**: registrar tarde cuesta el desempate.

### 4.8 Seguimientos

Un mensaje es seguimiento si es respuesta a otro (`respuesta_a`) o si el mismo
productor/parcela tiene un caso abierto **hace menos de 24 h y sin visita**
(`GET /visitas`). No abren caso nuevo: **no llevan semáforo, técnico ni brote**.

### 4.9 Retos extra (20 % de la nota)

1. Notas de voz y fotos (transcripción + visión).
2. App web en el link del equipo (panel, mapa, semáforo, técnicos, brotes).
3. Aprobación del coordinador en Telegram con botones **Aprobar / Cambiar técnico**,
   y luego `POST /avisos` al productor (folio) y al técnico.
4. Seguimientos (mismo productor/parcela < 24 h sin visita).
5. Aviso a vecinos del mismo cultivo a < 5 km cuando hay brote.
6. Plazos: escalar si no hay visita dentro del plazo del semáforo.
7. Cuarentenarias: avisar de inmediato a `sanidad_vegetal`.

---

## 5. Arquitectura

### 5.1 Flujo de datos

```
                         ┌─────────────────────────────┐
  GET /reportes  ───────▶│  listener.py                │  cada 20 s
  (texto/voz/foto)       │  estado persistente         │  refresca catálogos cada 10 min
                         └──────────────┬──────────────┘
                                        │
                         ┌──────────────▼──────────────┐
                         │  clasificador.py  (IA)      │
                         │  · pre-filtro no-plaga      │
                         │  · anti prompt-injection    │
                         │  · señales ponderadas       │
                         │  · cruce parcela→cultivo    │
                         │  · fusión texto + foto      │
                         └──────────────┬──────────────┘
                                        │ plaga + pct + es_plaga
                         ┌──────────────▼──────────────┐
                         │  nivel2.py  (código puro)   │
                         │  prioridad → semáforo       │
                         │  → técnico (haversine)      │
                         └──────────────┬──────────────┘
                                        │ semaforo, tecnico_id, prioridad
                         ┌──────────────▼──────────────┐
                         │  caso_para_api()            │  filtra _pct, _nivel2
                         └──────────────┬──────────────┘
                                        │
              ┌─────────────────────────┼─────────────────────────┐
              ▼                         ▼                         ▼
     POST /casos/validar        cache/casos_propuestos.json   extras.py / telegram
     (formato, no califica)     (lo lee el dashboard)         (avisos, brotes, plazos)
```

### 5.2 Principio de diseño central

> **La IA interpreta; el código decide.**

- **IA**: leer lenguaje natural (incluido audio con acento campesino) y decidir
  *qué plaga* y *qué porcentaje*. Es donde un LLM aporta.
- **Código**: prioridad, semáforo, técnico y brote. Es donde el reglamento exige
  reproducibilidad y donde un LLM sería un riesgo.

Esta separación permitió **validar las fórmulas contra 40 casos con respuesta correcta**
antes de tocar el pipeline.

### 5.3 Capas

| Capa | Archivos | Responsabilidad |
|---|---|---|
| **Red** | `api_cliente.py` | Token, reintentos, errores, timeout |
| **Datos** | `descargar_catalogos.py` | Caché local de catálogos y reportes |
| **Comprensión** | `clasificador.py`, `motor_audio_foto.py` | Texto, voz y foto → plaga |
| **Reglas** | `nivel2.py` | Prioridad, semáforo, técnico |
| **Orquestación** | `listener.py` | Ciclo continuo, estado, caché |
| **Salida** | `enviar_casos.py`, `extras.py`, `telegram_notificador.py` | Registro, avisos, alertas |
| **Verificación** | `probar_motor.py`, `validar_nivel2.py`, `verificar_stt.py`, `verificar_vision.py` | Pruebas sin gastar API |
| **Operación** | `desplegar_*.py`, `verificar_servidor.py`, `estado_despliegue.py` | Despliegue y diagnóstico |
| **Producto** | `app_web/` | Dashboard (Emmanuel) |

---

## 6. Crónica detallada por etapas

### Etapa 1 — Conexiones y cimientos (17:00–17:53)

**Objetivo:** comprobar accesos y dejar el repositorio listo.

- La API respondió con **53 reportes** (no 50) y máximo **98** (no 92). La memoria
  estaba desactualizada; desde entonces se decidió **no confiar en cifras escritas**
  y consultar `GET /equipo` siempre.
- El repo de GitHub existía pero **vacío y privado**; el push funcionó con las
  credenciales de Windows del usuario `exogenesis1083-ops`.
- Se versionó solo lo necesario: `.gitignore`, `opencode.json`, `requirements.txt`,
  `test_openrouter.py`. Se excluyeron `.env`, `MEMORIA_HACKATHON.md`, `curso_github/`,
  `gemini-extension/`, `.venv/`, `node_modules/`, `dist/`, logs.
- `PATCH /equipo` registró el repositorio (`{"ok":true}`), requisito del 20 % de ingeniería.
- **Primer bloqueo:** la key de OpenRouter estaba expirada (401). Se siguió trabajando
  con reglas deterministas, que resultaron ser la base del diseño final.

**Hallazgo clave:** `GET /casos-previos` devuelve **40 casos de la semana anterior con
la respuesta correcta** (`plaga`, `pct`, `prioridad`, `semaforo`, `tecnico_id`, `brote`).
Eso convirtió el reto en un problema **verificable**: cualquier regla se puede comparar
contra 40 respuestas reales antes de apostar puntos.

### Etapa 2 — Cliente, catálogos y clasificador (17:50–17:53)

Se construyó:

- `bot/api_cliente.py`: `GET/POST/PATCH`, header `X-Equipo-Token`, reintentos con
  backoff, errores tipados (`ApiError`).
- `bot/descargar_catalogos.py`: baja y cachea `/plagas` (10), `/parcelas` (264),
  `/productores` (191), `/tecnicos` (12) y `/reportes`.
- `bot/analisis_reportes.py`: tabla reporte → parcela → cultivo → etapa.
- `bot/clasificador.py`:
  - **pre-filtro** de mensajes administrativos (horarios, precios, juntas, saludos);
  - **detección de prompt injection** (R-2016: «ignora tus instrucciones…»);
  - **señales ponderadas** con modismos («chahuixtle», «chapulinada», «polvillo»,
    «aserrín», «cojo»);
  - **cruce parcela→cultivo** y **regla de cultivo exclusivo**:
    limón → `hlb`, grano almacenado → `gorgojo_khapra`;
  - **urgencia derivada del catálogo** (severidad alta/crítica o cuarentenaria),
    no una lista hardcodeada.
- `bot/enviar_casos.py`: valida con `/casos/validar`, muestra el plan y exige
  `--enviar` + escribir `CONFIRMAR`.

**Decisión:** no usar un LLM para clasificar texto. Con 20 reportes de texto, las reglas
ponderadas acertaban con confianza alta y eran auditables; un LLM habría añadido
variabilidad justo donde el reto castiga el error.

### Etapa 3 — Multimodal: voz y foto (17:56–18:13)

**Voz (27 audios):**

1. Se transcribieron con `whisper-large-v3`.
2. Al revisar, apareció ruido sistemático:
   «cojo» por *cogollo*, «acerín» por *aserrín*, «Roy» por *roya*,
   «hienas de mijitos» por *hay hormiguitas*, «duzano» por *gusano*.
3. Se comparó contra `gpt-4o-transcribe`: **acertaba en todos** esos casos.
4. **Decisión:** `gpt-4o-transcribe` como principal, `whisper` como respaldo y
   **consenso por señal agronómica** (si ambos coinciden, sube la confianza; si
   discrepan, gana la transcripción con más señal). Whisper fallaba ~35 % de las
   frases con acento campesino.

**Foto (8–9 imágenes):**

1. Primero un solo modelo (`gpt-4o-mini`): cambiaba de opinión entre llamadas
   (R-2019 decía «pulgón» en **frijol**, combinación imposible según el catálogo).
2. Se restringieron los **candidatos por cultivo**.
3. Se pasó a **3 modelos con `temperature=0`** (`gpt-4o-mini`, `gemini-2.5-flash`,
   `gpt-4o`) y **voto mayoritario**.
4. Resultado: 6 fotos unánimes; R-2019 y R-2021 con mayoría 2/3.
5. Si no hay mayoría → `desconocida` (0 puntos, sin riesgo).

**Bug corregido:** el JSON de ejemplo dentro del prompt rompía `str.format()`
(`KeyError: '"es_plaga"'`). Se escaparon las llaves.

**Bug de diseño corregido:** el consenso de visión vivía en un script aparte
(`consolidar_vision.py`). Al reprocesar, se perdía y volvían los errores. Se movió
**dentro del pipeline** (`motor_audio_foto.py`), que es donde debe vivir.

**Consumo:** las respuestas se cachean en `cache/multimedia.json` para no gastar
tokens dos veces.

### Etapa 4 — Dashboard profesional (18:02–18:24)

Se encargó a un subagente (Rol B) y Rafa lo revisó. Características:

- **Backend Express** en el puerto 3000, proxy autenticado hacia la API,
  caché de 20 s, timeout de 9 s y **respaldo a `cache/`** si la API falla.
- **Mapa Leaflet** con 264 parcelas coloreadas por estado.
- **Monitor de casos** con búsqueda, filtros por tipo/urgencia/cultivo, columnas
  ordenables y ficha de detalle.
- **Estadísticas**: plagas frecuentes, cultivos afectados, dona de parcelas,
  top parcelas.
- **KPIs**: puntos, lugar, procesados, urgentes, latencia.
- Responsivo y con auto-refresh cada 30 s.
- Endpoints propios: `/api/resumen`, `/api/parcelas`, `/api/reportes`, `/api/casos`,
  `/api/plagas`, `/api/equipo`, `/api/media/:archivo`, `/api/health`.

**Incidente de seguridad:** el subagente dejó el **token del equipo escrito en
`server.js`**. Se corrigió en dos pasos: leer solo de `process.env.EQUIPO_TOKEN` y
**purgar el token del historial de git** (commit reescrito `d75fcbf`, force-push).
Verificación posterior: «sin secretos en el historial».

**Lección:** revisar el código que produce un subagente antes de commitear;
el 20 % de ingeniería exige llaves fuera del repositorio.

### Etapa 5 — Rama `Rafa`, robustez y listener (18:57–20:16)

Rafa pidió trabajar en una rama propia y luego pasar a `main` por PR.

Se hizo:

- **Auditoría de STT** (`verificar_stt.py`) y **visión** (`verificar_vision.py`,
  `consolidar_vision.py`).
- **Consenso STT** integrado (`gpt-4o-transcribe` + `whisper`).
- **Fusión texto+foto**: el pie de foto se combina con la visión; la foto ya no
  decide sola.
- **Seguimientos con `respuesta_a`**: si un mensaje responde a otro, hereda la plaga
  del caso padre y no abre caso nuevo.
- **Inferencia de cultivo por texto** para reportes sin `parcela_id`
  (R-2055: «le cayó gusano a la milpa»).
- **`listener.py`**: ciclo continuo, estado persistente en
  `cache/listener_estado.json`, bitácora en `cache/listener_bitacora.jsonl`,
  refresco de catálogos cada 10 min, **nunca registra sin `--enviar`**.
- **`recargar_catalogo()`** en el clasificador para absorber cambios del reto sin
  reiniciar.
- **`probar_motor.py`**: 31 pruebas que no gastan API, incluida una que **modifica el
  catálogo** para comprobar que nada se rompe si los organizadores agregan plagas.
- **`generar_casos.py`**: recalcula `cache/casos_propuestos.json` para el dashboard.

El listener detectó por su cuenta **R-2056** y **R-2057**; el dashboard los leyó sin
cambios. Commit `b6d65a4`, PR **#1**, fusionado a las 20:36 (`140ef82`).

### Etapa 6 — Nivel 2 y extras (20:39–21:02)

Al sincronizar después del PR #1 se detectó que el reto había cambiado:

- `maximo_posible` 103 → **188**;
- `aciertos` ganó **`semaforo`** y **`tecnico`**;
- el esquema `Caso` ganó `semaforo`, `tecnico_id`, `prioridad`;
- `urgente` quedó marcado como «Nivel 1, ya no se usa».

Se leyeron las secciones 7, 8 y 9 de `/reglas` y se implementó:

**`bot/nivel2.py`** — funciones puras:

| Función | Qué hace |
|---|---|
| `redondeo_comercial(x)` | `floor(x + 0.5)` |
| `extraer_pct(texto)` | porcentaje dicho por el productor (ver abajo) |
| `calcular_prioridad(plaga, parcela, pct)` | severidad + superficie + etapa; cuarentenaria = 100 |
| `calcular_semaforo(prioridad)` | umbrales 85/70/40 |
| `distancia_km(...)` | haversine R = 6371 |
| `elegir_tecnico(tecnicos, plaga, parcela)` | especialidad + carga < 5 + más cercano + desempates |
| `resolver(...)` | aplica las tres reglas y devuelve el bloque del caso |

**Extracción del porcentaje** (reglas de lenguaje, no IA):

| Frase | pct |
|---|---|
| «el 75 %», «setenta y cinco por ciento» | 75 |
| «tres cuartas partes» | 75 |
| «dos terceras partes» | 66 |
| «la mitad», «medias» | 50 |
| «una tercera parte» | 33 |
| «una cuarta parte», «un cuarto» | 25 |
| «una de cada cuatro matas» | 25 |
| «una quinta parte» | 20 |
| «casi todo» | 90 |
| «toda la parcela» | 100 |
| no lo dice | **10** (igual que `/casos-previos`) |

Se añadió un **parser de números en español** para «setenta y cinco»,
«veinticinco», «ochenta y dos», etc.

**Integración:**

- `Clasificador.resolver_nivel2()` obtiene la parcela y la plaga del catálogo y llama
  a `nivel2.resolver`.
- `Clasificador.tecnicos_en(momento)` consulta `GET /tecnicos?momento=<recibido>`
  con **caché por momento** (la carga cambia con el tiempo).
- `resultados_a_casos()` agrega `semaforo`, `tecnico_id`, `prioridad` y guarda
  `_pct` / `_nivel2` como información local.
- `caso_para_api()` filtra solo los campos del esquema antes de enviar.
- `urgente` se conserva **derivado** (`semaforo ∈ {rojo, naranja}`) para no romper el
  dashboard.

**Extras (`bot/extras.py`)** — preparados y **apagados por defecto**:

| Extra | Implementación |
|---|---|
| Avisos | `POST /avisos` (cuarentenaria, asignación, folio, brote, escalamiento) |
| Preguntas | `POST /preguntas` cuando falta parcela o la plaga es `desconocida` |
| Brotes | 3+ casos, misma plaga, < 5 km, 7 días, **agrupación transitiva (BFS)** |
| Plazos | 24/48/72 h/7 días según semáforo, contra `GET /visitas` |
| Cuarentenarias | aviso inmediato a `sanidad_vegetal` |

**`bot/telegram_notificador.py`** — preparado:

- mensaje con plaga, parcela, prioridad, técnico y % de afectación;
- botones inline **✅ Aprobar / 🔁 Cambiar técnico / 🚫 Falsa alarma**;
- sin token funciona en **modo seco** (imprime, no envía).

**Listener ampliado:** `--extras`, `--avisos-reales`, `--preguntas`. Telegram se
dispara solo para rojo/naranja.

**Verificación:** `docs/NIVEL2.md` documenta el diseño y las preguntas probables de la
defensa. Se corrigió un secreto (contraseña SSH) que se había colado en
`revisar_servidor.py`. **49/49 pruebas**, fórmulas **40/40**. PR **#2**, fusionado a
las 21:11 (`5f453d1`).

### Etapa 7 — Despliegue en el servidor (21:11–21:35)

**Diagnóstico inicial:** el dashboard **no estaba desplegado**. En `~/app` corría
`bitacora-de-parcela` (otra app del curso, repo `form-DIMA-2026`) y `pm2` no existía.
El puerto 3000 estaba ocupado por esa app.

**Descubrimiento:** el servidor ya trae un mecanismo oficial de despliegue:

- `~/despliegue.conf` define cómo clonar, instalar y arrancar **app** y **agente**.
- El comando `desplegar` y `supervisor` administran los procesos.
- Hay un programa `autodespliegue` que revisa el repositorio.

Se usó ese mecanismo (no se instaló `pm2`):

```
APP_REPO    = https://github.com/marosorio08/Alerta_Plaga_Gusano.git
APP_RAMA    = main
APP_INSTALAR= npm --prefix app_web install --omit=dev
APP_INICIAR = node app_web/server.js

AGENTE_REPO = (mismo repo)
AGENTE_INICIAR = .venv/bin/python -u bot/listener.py --intervalo 20 --extras
```

**Acceso del servidor a GitHub:** se generó una **deploy key ed25519** en
`~/.ssh/deploy_alerta` y se dio de alta en el repositorio (solo lectura). Si no hay
permisos de administración, el script cae a un credential store en el servidor.

**Secretos:** se escribieron en el servidor, nunca en git:

- `~/app/app_web/.env`: `PORT`, `HOST`, `EQUIPO_TOKEN`, `API_BASE`, `CACHE_DIR`.
- `~/agente/.env`: `API_BASE_URL`, `EQUIPO_TOKEN`, `OPENROUTER_API_KEY`,
  `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `CASOS_SALIDA`.

**Caché compartida:** el agente escribe los casos en
`/home/equipo02/app/cache/casos_propuestos.json` (`CASOS_SALIDA`) y el dashboard los
lee de ahí. Así el panel muestra lo que el bot acaba de clasificar sin acoplarse por
red.

**Commits de despliegue:**

- `98a0327` — `package.json` en la raíz (`npm start` → `node app_web/server.js`).
- `ecce029` — `CASOS_SALIDA` en el listener.
- `26ae2f3` — fix: faltaba `import os`.

PR **#3** y **#4**, fusionados. `main` = `043eb55`.

**Estado verificado (21:29–21:35):**

```
supervisorctl status
  agente          RUNNING   pid 18082   uptime 0:16:09
  app             RUNNING   pid 17954   uptime 0:16:40
  autodespliegue  RUNNING
  ssh             RUNNING

~/logs/agente.log
  [21:18:51] 62 reporte(s) nuevo(s) procesado(s) | total en esta sesión: 62
  [21:18:56] listener iniciado | intervalo 20s | registro automático: NO
  [21:29:04] catálogos refrescados (10 plagas, 264 parcelas)

~/app/cache/casos_propuestos.json
  casos: 62 | con semáforo: 43

GET https://equipo02.179-236-73-82.sslip.io/api/resumen
  200 · datos reales de la API · equipo 7_7 · 62 reportes
```

**Resultado:** el sistema completo está corriendo en el servidor, sin registrar nada.

---

## 7. Decisiones técnicas y su justificación

| # | Decisión | Por qué |
|---|---|---|
| 1 | **Reglas deterministas para texto**, no LLM | Auditables, reproducibles, sin costo ni latencia; el LLM se reserva para lo que el reglamento pide interpretar |
| 2 | **`desconocida` ante la duda** | Vale 0; inventar resta 1. «No arriesgar no resta» |
| 3 | **Urgencia derivada del catálogo** | Si agregan plagas o cambian severidades, el sistema se adapta sin tocar código |
| 4 | **Candidatos de visión restringidos por cultivo** | Evita combinaciones imposibles (pulgón en frijol) |
| 5 | **3 modelos + `temperature=0` + mayoría** | Un solo modelo cambiaba de opinión entre llamadas |
| 6 | **`gpt-4o-transcribe` principal + whisper respaldo** | Whisper fallaba ~35 % con acento campesino |
| 7 | **Consenso dentro del pipeline** | Un script aparte se perdía al reprocesar y reintroducía errores |
| 8 | **Caché de multimedia** | No pagar dos veces la misma transcripción/visión |
| 9 | **Técnico con `momento=<recibido>`** | La carga la simula la API y cambia con el tiempo; usar «ahora» da otro técnico |
| 10 | **Caché de técnicos por momento** | Evita decenas de llamadas repetidas por el mismo instante |
| 11 | **`caso_para_api()`** | La API valida esquema; `_pct` y `_nivel2` son información local |
| 12 | **`urgente` derivado** | Compatibilidad con el dashboard de Emmanuel; ya no califica |
| 13 | **No tocar `app_web/`** | Evitar colisiones con el trabajo de Emmanuel |
| 14 | **Rama `Rafa` + PR verificado** | Flujo de ingeniería exigido; permite revisar antes de `main` |
| 15 | **Dry-run por defecto** | `--enviar` y `CONFIRMAR` evitan un registro irreversible por accidente |
| 16 | **Extras apagados por defecto** | Un aviso mal disparado ensucia el buzón y confunde al coordinador |
| 17 | **Caché en disco de catálogos** | El sistema sigue funcionando si la API falla; el dashboard tiene respaldo |
| 18 | **Seguimientos detectados por `respuesta_a` y palabras clave** | No abren caso nuevo; evitan semáforo/técnico donde no cuentan |
| 19 | **No registrar hasta que todo esté validado** | Una sola oportunidad por mensaje; el error resta |

---

## 8. Incidentes y correcciones

| # | Incidente | Impacto | Corrección |
|---|---|---|---|
| 1 | **Key de OpenRouter expirada** (401) | Sin voz/foto al inicio | Se pidió nueva key; llegó a las 18:02 |
| 2 | **Token del equipo en `server.js`** | Violación del 20 % de ingeniería | Variable de entorno + **purga del historial** (force-push) |
| 3 | **Contraseña SSH en `revisar_servidor.py`** | Secreto a punto de subir | Se leyó de `.env`; verificación de secretos antes del commit |
| 4 | **`.format()` roto por JSON de ejemplo** en el prompt de visión | `KeyError` y fotos sin analizar | Llaves escapadas |
| 5 | **Visión inconsistente** (R-2019 pulgón en frijol; R-2021 cambió) | Riesgo de −1 punto | 3 modelos, `temperature=0`, filtro por cultivo, mayoría |
| 6 | **Whisper inexacto** (~35 %) | Plagas mal transcritas | `gpt-4o-transcribe` + consenso por señal |
| 7 | **Consenso de visión se perdía al reprocesar** | Volvían los errores | Consenso movido al pipeline |
| 8 | **`Counter` mal usado en la votación** | Mayoría mal calculada | Corregido (se comparaba un entero) |
| 9 | **Errores 429 por ráfaga** | Fotos sin procesar | Reintentos con backoff |
| 10 | **BOM en `listener.py`** | `ast.parse` fallaba | Se eliminó el BOM y se guardó UTF-8 sin BOM |
| 11 | **Brotes duplicados/solapados** | 9 avisos donde había 1 brote | Agrupación transitiva (BFS) y firma por casos |
| 12 | **Faltaba `import os`** para `CASOS_SALIDA` | El agente no arrancaba | Commit `26ae2f3` |
| 13 | **`casos_propuestos.json` desactualizado** | Dashboard mostraba 6 no-plaga en vez de 9 | `generar_casos.py` con el motor actual |
| 14 | **Rama `Caso_Emmanuel` desfasada** | Un PR así **borraría `bot/`** | Se avisó: debe `merge main` antes del PR |
| 15 | **Consola cp1252** | `✔` y emojis rompen prints | Python con `-X utf8`, texto plano |
| 16 | **Supabase sin permisos de escritura** | No se pueden crear tablas/políticas | Solo hay URL + publishable key; falta `service_role` o contraseña de BD |
| 17 | **`pm2` no existe** | El plan original no aplicaba | Se usó el mecanismo oficial: `despliegue.conf` + `desplegar` + `supervisor` |

---

## 9. Verificación y pruebas

### 9.1 Pruebas del motor (sin gastar API)

```bash
python bot/probar_motor.py
```

```
Pruebas: 49 | fallos: 0
```

Cubre:

| Bloque | Qué verifica |
|---|---|
| 1 | Pre-filtro de mensajes administrativos |
| 2 | Plagas por modismos y sinónimos |
| 3 | Cruce parcela→cultivo y cultivo exclusivo |
| 4 | Prompt injection neutralizada |
| 5 | Urgencia derivada del catálogo |
| 6 | Seguimientos (`respuesta_a`) |
| 7 | Fusión texto+foto |
| 8 | Campos del caso |
| 9 | Formato para `POST /casos` |
| 10 | Catálogo modificado y catálogo vacío |
| 11 | Extracción de `pct` (8 frases) |
| 12 | Prioridad y semáforo (incluye el ejemplo oficial = 79) |
| 13 | Técnico (más cercano, especialidad, carga, empate, sin candidato) |
| 14 | `caso_para_api()` descarta claves internas |

### 9.2 Validación del Nivel 2 contra la verdad

```bash
python bot/validar_nivel2.py
```

```
Casos previos: 40
Prioridad: 40/40   Semáforo: 40/40   Técnico: 40/40
```

Usa **el código real** (`nivel2.py`), no una copia.

### 9.3 Otras verificaciones

| Verificación | Resultado |
|---|---|
| `POST /casos/validar` sobre los casos | 62/62 con formato OK |
| Dashboard `/api/health`, `/api/resumen`, `/api/parcelas`, `/api/reportes`, `/api/casos` | 200 con datos reales |
| App pública y local | 200 |
| Agente en supervisor | RUNNING |
| Registro automático del agente | **NO** (verificado en el log) |
| Secretos en el código | Limpio |
| Secretos en el historial de git | Limpio (tras la purga) |

---

## 10. Despliegue en producción

### 10.1 Cómo está montado

```
Servidor 179-236-73-82.sslip.io (puerto 2202, usuario equipo02)
│
├── ~/app/                  ← repositorio (rama main) + app_web/
│   ├── app_web/server.js   ← dashboard (puerto 3000, host 0.0.0.0)
│   ├── app_web/.env        ← PORT, HOST, EQUIPO_TOKEN, API_BASE, CACHE_DIR
│   └── cache/              ← catálogos, reportes y casos compartidos
│
├── ~/agente/               ← repositorio + .venv
│   ├── .env                ← API, token, OpenRouter, Telegram, CASOS_SALIDA
│   └── bot/listener.py     ← agente continuo
│
├── ~/despliegue.conf       ← receta de app y agente
├── ~/logs/app.log
├── ~/logs/agente.log
└── supervisor
    ├── app            → node app_web/server.js
    ├── agente         → .venv/bin/python -u bot/listener.py --intervalo 20 --extras
    ├── autodespliegue → revisa el repositorio
    └── ssh
```

### 10.2 Flujo de actualización

1. Se hace commit en `Rafa`, se abre PR y se fusiona a `main`.
2. El servidor (autodespliegue) detecta el commit nuevo.
3. Ejecuta `APP_INSTALAR` / `AGENTE_INSTALAR` y reinicia los servicios.
4. `supervisorctl status` debe mostrar `app` y `agente` en `RUNNING`.

### 10.3 Diagnóstico rápido

```bash
ssh -p 2202 equipo02@179-236-73-82.sslip.io
supervisorctl status
tail -20 ~/logs/agente.log
tail -20 ~/logs/app.log
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:3000/
curl -s http://localhost:3000/api/resumen | head -c 400
```

Desde Windows, los mismos chequeos están automatizados en
`bot/verificar_servidor.py` y `bot/estado_despliegue.py`.

### 10.4 Nota sobre Supabase

- En el servidor hay `SUPABASE_URL` y `SUPABASE_PUBLISHABLE_KEY` (de la app del curso).
- **No** hay `service_role` ni contraseña de base.
- Si Emmanuel va a crear tablas o políticas RLS, necesita una de esas dos.
- El dashboard actual **no depende de Supabase**: lee la API y la caché local.

---

## 11. Estado actual de los datos

### 11.1 Catálogos en caché

| Catálogo | Registros |
|---|---|
| Plagas | 10 |
| Parcelas | 264 |
| Productores | 191 |
| Técnicos | 12 |
| Casos previos (con respuesta) | 40 |
| Reportes publicados | 62 |

### 11.2 Reportes por tipo

| Tipo | Cantidad |
|---|---|
| Texto | 26 |
| Voz | 27 |
| Foto | 9 |
| **Total** | **62** |

- **6** reportes no traen `parcela_id` (requieren pregunta al productor).
- **0** respuestas de productor (`respuesta_a`) hasta el corte: todavía no se han
  hecho preguntas.

### 11.3 Clasificación propuesta (62 casos)

| Categoría | Cantidad |
|---|---|
| Plaga identificada | 44 |
| Plaga `desconocida` | 6 |
| No es plaga | 12 |

| Semáforo | Cantidad |
|---|---|
| 🔴 Rojo | 1 |
| 🟠 Naranja | 12 |
| 🟡 Amarillo | 30 |
| Sin semáforo (no plaga / desconocida) | 19 |
| **Con técnico asignado** | **43** |

### 11.4 Brotes detectados (agrupados)

| Plaga | Casos |
|---|---|
| `gusano_cogollero` | 15 |
| `roya_frijol` | 6 |
| `roya_frijol` | 4 |
| `pulgon` | 6 |
| `pulgon` | 3 |
| `pulgon` | 3 |
| `chapulin` | 6 |
| `chapulin` | 3 |
| `mosquita_blanca` | 3 |

> Son **9 agrupaciones** con el criterio de 3+ casos, misma plaga, < 5 km, 7 días.
> **Ojo:** el reglamento pide un **booleano por caso**, no una lista de grupos.
> Ese campo todavía **no se envía** (ver sección 12).

### 11.5 Tabla de posiciones

| Dato | Valor |
|---|---|
| Puntos | 0 |
| Enviados | 0 |
| Publicados | 62 |
| Máximo posible | 238 |
| Lugar | 4.º |
| Aciertos | `es_plaga`, `plaga`, `semaforo`, `tecnico`, `brote` (todos `null`) |

---

## 12. Lo que falta

### 🔴 Crítico (puntos)

| # | Tarea | Detalle |
|---|---|---|
| 1 | **Calcular `brote` por caso** | Regla de la sección 9: 3+ casos de la misma plaga, < 5 km, 168 h, contando el actual y los previos. Agregar `brote` a `CAMPOS_API` y a `resultados_a_casos()`. Validar contra los **11/40** brotes de `/casos-previos`. |
| 2 | **Registrar los casos** (`POST /casos`) | **Bloqueado por orden de Rafa.** Se puede empezar por los 20 de texto de alta confianza y luego el resto. Recordar `complemento` para lo que falte. |
| 3 | **Completar lo ya registrado** | Si se registró algo antes del Nivel 2, reenviar solo `semaforo` / `tecnico_id` / `brote`. |
| 4 | **Latencia** | El desempate es por latencia; cada hora cuenta. |

### 🟡 Importante (20 % de ingeniería y extras)

| # | Tarea | Responsable |
|---|---|---|
| 5 | **Telegram**: definir `TELEGRAM_CHAT_ID` y activar alertas rojo/naranja | Emmanuel + Rafa |
| 6 | **Botones de aprobación** (Aprobar / Cambiar técnico) y `POST /avisos` reales | Emmanuel |
| 7 | **Supabase**: `service_role` o contraseña de BD para crear tablas/políticas | Emmanuel |
| 8 | **Sincronizar `Caso_Emmanuel` con `main`** antes de su PR | Emmanuel |
| 9 | **README final**: qué hace, cómo se instala, quién hizo qué, capturas | Ambos |
| 10 | **Commits de Emmanuel** (el historial aún es casi todo de Rafa) | Emmanuel |
| 11 | **Activar extras reales**: preguntas, avisos, plazos | Rafa |
| 12 | **Detectar seguimientos por la regla de 24 h + sin visita** (no solo por texto) | Rafa |

### ⚪ Mejoras

| # | Tarea |
|---|---|
| 13 | Validar el brote por caso contra los 40 previos y añadir pruebas |
| 14 | Añadir `brote` a `docs/NIVEL2.md` y a `probar_motor.py` |
| 15 | Panel de brotes en el dashboard (Emmanuel) |
| 16 | Revisar `app_web/README.md`: menciona un «token de respaldo en `server.js`» que ya no existe |
| 17 | Limpiar scripts de inspección de una sola vez (`inspeccionar_*.py`) |
| 18 | Actualizar `MEMORIA_HACKATHON.md` con el estado final |

---

## 13. Inventario de archivos

### Raíz

| Archivo | Para qué |
|---|---|
| `README.md` | Qué es, estructura, uso, estado, Nivel 2 |
| `requirements.txt` | `openai`, `requests`, `python-dotenv`, `pypdf`, `paramiko` |
| `package.json` | Arranque en el servidor (`npm start` → `node app_web/server.js`) |
| `opencode.json` | Configuración del agente de programación |
| `.env` | Credenciales (gitignored) |
| `.gitignore` | Excluye `.env`, `cache/`, `MEMORIA_HACKATHON.md`, `curso_github/`, `gemini-extension/`, `node_modules/`, `.venv/`, `dist/` |
| `MEMORIA_HACKATHON.md` | Contexto y credenciales (gitignored) |
| `HISTORIA_DEL_PROYECTO.md` | Este documento (raíz: fácil de localizar) |
| `docs/NIVEL2.md` | Diseño del Nivel 2 y guía de defensa |

### `bot/` — motor

| Archivo | Función |
|---|---|
| `api_cliente.py` | Cliente HTTP con token, reintentos y errores tipados |
| `descargar_catalogos.py` | Descarga catálogos y reportes a `cache/` |
| `analisis_reportes.py` | Cruce reporte→parcela→cultivo |
| `clasificador.py` | Motor: reglas, anti-inyección, fusión, Nivel 2 |
| `nivel2.py` | Prioridad, semáforo, técnico, haversine, `pct` |
| `motor_audio_foto.py` | STT con consenso + visión 3 modelos + caché |
| `procesar_multimedia.py` | Procesa `.ogg`/`.jpg` en lote |
| `listener.py` | Vigilancia continua, estado, avisos, Telegram |
| `extras.py` | Avisos, preguntas, brotes, plazos, cuarentenarias |
| `telegram_notificador.py` | Alertas con botones (modo seco sin token) |
| `enviar_casos.py` | Validación + plan + `--enviar` + `CONFIRMAR` |
| `generar_casos.py` | Recalcula `casos_propuestos.json` para el dashboard |
| `probar_motor.py` | 49 pruebas sin gastar API |
| `validar_nivel2.py` | Fórmulas reales contra `/casos-previos` |
| `verificar_stt.py` | Compara modelos de transcripción |
| `verificar_vision.py` | Prueba modelos de visión |
| `consolidar_vision.py` | Consolida respuestas de visión en caché |
| `inspeccionar_api.py` | Muestra parámetros y esquemas nuevos de la API |
| `revisar_servidor.py` | Inventario del servidor sin exponer secretos |
| `estado_despliegue.py` | Resumen del despliegue (app, agente, envs) |
| `desplegar_dashboard.py` | Publica la app con `despliegue.conf` |
| `desplegar_agente.py` | Publica el agente con `despliegue.conf` |
| `ejecutar_despliegue.py` | Fuerza el despliegue y verifica HTTP |
| `preparar_despliegue.py` | Diagnóstico previo (solo lectura) |
| `configurar_acceso_git.py` | Deploy key para que el servidor lea el repo |
| `verificar_servidor.py` | Estado final de app y agente |
| `inspeccionar_despliegue.py` / `inspeccionar_agente.py` / `inspeccionar_supervisor.py` / `ver_config_agente.py` | Diagnóstico puntual de supervisor y despliegue |

### `app_web/` — dashboard (Emmanuel)

| Archivo | Función |
|---|---|
| `server.js` | Express, proxy autenticado, caché, respaldo, estáticos |
| `public/index.html` | Interfaz |
| `public/app.js` | Lógica del panel, mapa, filtros, gráficas |
| `public/styles.css` | Estilos |
| `public/favicon.svg` | Icono |
| `package.json` | Dependencia `express` |
| `.env.example` | Variables esperadas |
| `README.md` | Documentación del dashboard |

### `cache/` (gitignored)

`plagas.json`, `parcelas.json`, `productores.json`, `tecnicos.json`,
`reportes.json`, `cache_casos_previos.json`, `casos_propuestos.json`,
`multimedia.json`, `multimedia_v1_whisper.json`, `stt_doble.json`,
`vision_doble.json`, `listener_estado.json`, `listener_bitacora.jsonl`,
`visitas.json`, `openapi.json`, `media/`.

---

## 14. Comandos de operación

### Local (Windows, PowerShell)

```powershell
# Siempre con UTF-8 para evitar problemas de consola
& .venv\Scripts\python.exe -X utf8 bot\<script>.py
```

| Tarea | Comando |
|---|---|
| Bajar catálogos y reportes | `python bot/descargar_catalogos.py --reportes` |
| Clasificación completa (tabla) | `python bot/clasificador.py` |
| Regenerar casos para el dashboard | `python bot/generar_casos.py` |
| Validar fórmulas Nivel 2 | `python bot/validar_nivel2.py` |
| Pruebas del motor | `python bot/probar_motor.py` |
| Listener, una pasada | `python bot/listener.py --una-vez` |
| Listener continuo | `python bot/listener.py` |
| Listener con extras (seco) | `python bot/listener.py --extras` |
| Listener con avisos reales | `python bot/listener.py --extras --avisos-reales` |
| Listener con preguntas | `python bot/listener.py --preguntas` |
| **Registrar** (irreversible) | `python bot/enviar_casos.py --enviar` |
| Probar un solo caso | `python bot/enviar_casos.py --solo R-2002` |
| Extras por consola | `python bot/extras.py` |
| Telegram (modo seco) | `python bot/telegram_notificador.py` |
| Desplegar dashboard | `python bot/desplegar_dashboard.py` |
| Desplegar agente | `python bot/desplegar_agente.py` |
| Verificar servidor | `python bot/verificar_servidor.py` |
| Estado del despliegue | `python bot/estado_despliegue.py` |

### Servidor

```bash
supervisorctl status
supervisorctl restart app
supervisorctl restart agente
tail -f ~/logs/agente.log
tail -f ~/logs/app.log
```

---

## 15. Cronología de Git y PRs

### Commits en `main`

| Hash | Hora | Mensaje |
|---|---|---|
| `f379a8c` | 17:01 | `chore: inicializa repositorio del equipo 7_7 (Alerta Plaga)` |
| `fdd0fc7` | 17:53 | `feat(bot): cliente API, descarga de catálogos y clasificador determinista (texto)` |
| `90d7842` | 17:58 | `feat(bot): motor multimodal (whisper+vision), integración IA y script de envío con doble validación` |
| `d75fcbf` | 18:12 | `feat(app_web): dashboard profesional + clasificador ponderado con whisper y vision por consenso` |
| `140ef82` | 20:36 | Merge PR #1 |
| `5f453d1` | 21:11 | Merge PR #2 |
| `98a0327` | 21:13 | `chore(deploy): package.json raiz para el arranque en el servidor` |
| `ecce029` | 21:16 | `feat(listener): CASOS_SALIDA para compartir casos con el dashboard en el servidor` |
| `26ae2f3` | 21:18 | `fix(listener): importar os para CASOS_SALIDA` |
| `2e0685a` | — | Merge PR #3 |
| `043eb55` | — | Merge PR #4 |

### Pull Requests

| PR | Rama | Estado | Contenido |
|---|---|---|---|
| #1 | `Rafa` → `main` | ✅ fusionado | Listener continuo, STT con consenso, fusión texto+foto, seguimientos (6 archivos, +821/−49) |
| #2 | `Rafa` → `main` | ✅ fusionado | Nivel 2 + extras (12 archivos, +1190/−40) |
| #3 | `Rafa` → `main` | ✅ fusionado | `CASOS_SALIDA` |
| #4 | `Rafa` → `main` | ✅ fusionado | Fix `import os` |

### Ramas

| Rama | Estado |
|---|---|
| `main` | Estable, desplegada |
| `Rafa` | Trabajo de Rafa; se sincroniza con `main` |
| `Caso_Emmanuel` | Trabajo de Emmanuel; **debe sincronizar con `main`** antes de su PR |

---

## 16. Glosario

| Término | Significado |
|---|---|
| **Caso** | Resultado que se registra para un mensaje: `es_plaga`, `plaga`, `semaforo`, `tecnico_id`, `brote` |
| **Caso nuevo** | Mensaje que abre un caso; puede valer hasta 5 puntos |
| **Seguimiento** | Mensaje sobre un caso abierto (< 24 h, sin visita) o respuesta a otro; hasta 2 puntos |
| **`pct`** | Porcentaje de la parcela afectado, según lo dijo el productor (10 si no lo dijo) |
| **Prioridad** | Puntaje 0–100 = severidad + superficie + etapa; no da puntos, sirve para verificar |
| **Semáforo** | Color derivado de la prioridad: rojo ≥85, naranja ≥70, amarillo ≥40, verde <40 |
| **Técnico** | Técnico de la especialidad de la plaga, con carga < 5, el más cercano a la parcela |
| **Brote** | 3+ casos de la misma plaga, < 5 km, en 7 días, contando el actual |
| **Cuarentenaria** | Plaga de alerta sanitaria (HLB, gorgojo khapra): prioridad 100 y aviso inmediato |
| **Haversine** | Fórmula de distancia entre coordenadas; R = 6371 km |
| **Consenso** | Varios modelos deben coincidir para aceptar una respuesta |
| **Prompt injection** | Mensaje que intenta manipular al agente («ignora tus instrucciones…») |
| **Folio** | Identificador que se da al productor para dar seguimiento a su caso |
| **Complemento** | Reenvío de un caso ya registrado solo con los campos que faltaban |

---

## 17. Notas para la defensa del viernes

### La idea en una frase

> «La IA lee el mensaje como lo haría un técnico; el código aplica el reglamento
> como lo haría un juez.»

### Preguntas probables

**¿Por qué no usa un LLM para todo?**
Porque el reglamento exige que el semáforo, el técnico y el brote den siempre el mismo
resultado con los mismos datos. Un LLM no garantiza eso, y cada error resta un punto.
La IA se usa donde aporta: entender texto, audio con acento y fotos.

**¿Cómo saben que las fórmulas están bien?**
Contra los 40 casos de `/casos-previos`, que traen la respuesta correcta:
**40/40 en prioridad, 40/40 en semáforo, 40/40 en técnico**. Además, el ejemplo del
reglamento (4.5 ha, V8, cogollero, 50 %) da exactamente 79 → naranja.

**¿Qué pasa si el productor no dice el porcentaje?**
Se usa 10 %, el mismo valor por omisión que `/casos-previos`.

**¿Y si no hay técnico disponible?**
Se manda `null`. Vale 0, igual que equivocarse, pero es la respuesta honesta.

**¿Cómo evitan que un mensaje manipule la prioridad?**
La prioridad se calcula con la parcela y el catálogo, nunca con el texto. Un «ponme
prioridad 100» no entra en ninguna fórmula. Además se detecta y se registra.

**¿Qué pasa si los organizadores cambian el catálogo?**
El listener refresca `/plagas` y `/parcelas` cada 10 minutos. Severidad, especialidad
y cultivos compatibles salen del catálogo, no del código.

**¿Por qué el técnico se busca con la hora del mensaje?**
Porque la carga la simula la API y cambia con el tiempo. Usar «ahora» asignaría otro
técnico y perdería el punto.

**¿Qué falta?**
El campo `brote` por caso (regla nueva de la sección 9), el registro de los casos y la
activación final de Telegram.

### Qué mostrar en vivo

1. `python bot/listener.py --una-vez` → clasifica y muestra semáforo/técnico.
2. `python bot/validar_nivel2.py` → 40/40.
3. `python bot/probar_motor.py` → 49/49.
4. Dashboard público → mapa, casos, KPIs.
5. `supervisorctl status` en el servidor → app y agente corriendo.
6. `tail -f ~/logs/agente.log` → el agente trabajando en vivo.

---

## 18. Lecciones aprendidas

1. **La API es la fuente de verdad.** La memoria decía 50 reportes y 92 puntos;
   la API decía 53 y 98. Cambió cinco veces en la sesión (53 → 62). Consultar
   `GET /equipo` siempre.
2. **Los cambios del reto se detectan comparando, no esperando un aviso.**
   El Nivel 2 se descubrió porque `maximo_posible` y `aciertos` cambiaron.
   El `brote` se descubrió igual, al revisar el esquema.
3. **Un subagente puede dejar secretos.** Revisar siempre su código antes de commitear.
4. **Los bugs de integración viven en los bordes:** BOM, `import os`, `Counter`,
   `.format()`, 429. Las pruebas automatizadas los atrapan; la revisión manual no.
5. **El consenso debe vivir en el pipeline,** no en un script aparte que se puede
   olvidar.
6. **No arriesgar también es una estrategia:** `desconocida` vale 0 y evita el −1.
7. **El servidor ya tenía su mecanismo de despliegue.** Antes de instalar `pm2`,
   leer `despliegue.conf` y lo que ya corre.
8. **Una rama desfasada puede borrar trabajo ajeno.** Verificar el punto de partida
   antes de aprobar un PR.
9. **Documentar mientras se hace** ahorra reconstruir la historia después.

---

*Fin del documento. Actualizar al cierre del jueves 22 con los casos registrados,
el brote por caso, Telegram activo y las capturas finales.*
