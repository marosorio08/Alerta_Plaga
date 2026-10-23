# 🌾 Alerta Plaga — Equipo 7_7 (IT Green × DIMA UACh)

Sistema de apoyo a la **junta de sanidad vegetal de Texcoco** para el hackathon
**Alerta Plaga**.

Recibe reportes de productores por **texto, voz o foto**, identifica la plaga,
calcula **prioridad**, **semáforo**, **técnico** y **brote**, guarda la
trazabilidad y registra el caso en la API del reto cuando los envíos están
habilitados.

> **Este README es la visión completa del sistema en `main`.** También explica
> qué hace cada rama y qué mejoras están propuestas. Para el detalle de fórmulas
> y arquitectura, ver [`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md) y
> [`docs/NIVEL2.md`](docs/NIVEL2.md).

---

## 1. Qué problema resuelve

Un productor manda un mensaje a la junta:

> “Se me está echando a perder la milpa, hay gusanos verdes en el cogollo.”

El sistema debe:

1. decidir si es plaga;
2. identificar la plaga del catálogo;
3. estimar el porcentaje afectado;
4. calcular prioridad y semáforo;
5. asignar un técnico;
6. decidir si hay brote;
7. guardar evidencia y registrar el caso.

La IA **interpreta** el mensaje. El código **decide** los puntos. Esa separación
es obligatoria por el reglamento y permite reproducibilidad.

---

## 2. Estado actual

> Último corte documentado en el repo: **22-oct-2026, 13:30**.
> Para la tabla en vivo: `GET https://itg.tailf75570.ts.net/tabla.json`.

| Dato | Valor documentado |
|---|---|
| Puntos | 576/662 |
| Lugar | 2.º |
| Enviados | 158/167 |
| Pendientes | 9 |
| Errores | 14 |
| Cierre del reto | 22-oct-2026, 23:59 |

El estado cambia rápido. La fuente de verdad es la API, no este README.

### Código de `main` analizado

- Head de código analizado: `252b840`.
- El head actual de `main` puede incluir commits de documentación posteriores;
  este README describe el código de `252b840`.
- Incluye el modelo de decisión autónoma de 4 intentos.
- Incluye dedupe de brote por **productor + parcela**.
- Incluye el aviso por Telegram de aciertos por reporte enviado.
- Incluye el fix de `409` en el resolver.
- El despliegue del agente escribe `PERMITIR_ENVIOS=1` por defecto si no se
  define; para pausar envíos hay que poner `PERMITIR_ENVIOS=0`.

### Ramas de trabajo

| Rama | Head | Vs `main` de código (252b840) | Qué aporta |
|---|---|---|---|
| `Caso_Emmanuel` | `04a2d40` | 11 atrás / 2 adelante | Ledger de confirmados, replay y documentación |
| `fix/brotes-revision-rafa` | `1768656` | 26 atrás / 1 adelante | Brote conservador, `evaluar_caso`, alertas |
| `Rafa` | `5cf0e93` | 61 atrás / 0 adelante | `REPORTE_FINAL`; PRs #1–#4 mergeados |
| `fix/supabase-persistencia` | `252a498` | 74 atrás / 0 adelante | Supabase; PR #5 mergeado |

> Los conteos de ramas se comparan contra el código de `main` en `252b840`;
> el commit de este README no se cuenta.

PRs:

- #1–#6: mergeados.
- #8: abierto, base `Caso_Emmanuel`; brote conservador y alertas.
- #9: abierto, base `main`; ledger de confirmados, replay y documentación.

Detalle de ramas: ver la sección 11.

---

## 3. Flujo oficial de 5 pasos

```
1. RECIBIR       GET /reportes, deduplicación, caché
2. INTERPRETAR   reglas + IA; STT para voz; visión para foto
3. DECIDIR       prioridad · semáforo · técnico · brote (código puro)
4. GUARDAR       cache/ + Supabase
5. REGISTRAR     POST /casos (solo con PERMITIR_ENVIOS=1)
```

### Paso 1 — Recibir

`bot/listener.py` consulta la API cada 20 s.

Se conserva:

- `id`
- `parcela_id`
- `productor_id`
- `tipo`
- `texto` / `audio_url` / `foto_url`
- `recibido`
- `respuesta_a`

El listener deduplica por `id` y refresca catálogos cada 10 min.

Datos cacheados:

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

### Paso 2 — Interpretar

#### Texto

Modo recomendado: `INTERPRETAR_IA=2` (consenso híbrido).

1. Reglas deterministas evalúan el mensaje.
2. La IA devuelve JSON estricto (`es_plaga`, `plaga`, `pct`).
3. Si coinciden, se acepta.
4. Si difieren:
   - se busca precedente histórico de la parcela o del cultivo;
   - si existe, manda el precedente;
   - si no, **mandan las reglas**.

| `INTERPRETAR_IA` | Comportamiento |
|---|---|
| `0` | Solo reglas |
| `1` | IA primero, respaldo a reglas |
| `2` | Consenso híbrido con desempate histórico |

#### Voz

- STT principal: `gpt-4o-transcribe`.
- Respaldo: otro modelo.
- Si los dos coinciden, alta confianza.
- Si difieren, gana la transcripción con más señal agronómica.
- Si no hay señal suficiente → `desconocida`.
- Un STT vacío **no se cachea**: se reintenta.

#### Foto

- Visión con consenso de 3 modelos y `temperature=0`.
- Fusión con el pie de foto.
- Si texto y visión coinciden → alta confianza.
- Si difieren → `desconocida`, salvo que el texto tenga señal fuerte.

#### Reglas de apoyo

- Prefiltro de mensajes administrativos, saludos, precios, juntas y cierres.
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
  - “hojas agujeradas” no es 100 %
  - si no lo dice → 10 %

#### Regla de oro

`plaga` debe existir en el catálogo y ser compatible con el cultivo. Si no, se
marca `desconocida`. Nunca se inventa una plaga para “ganar” un punto.

### Paso 3 — Decidir

Todo lo que vale puntos se calcula en `bot/nivel2.py`.

#### Prioridad

```
severidad + superficie(pct) + etapa
```

- severidad: baja 15 / media 25 / alta 40 / crítica 50;
- superficie: `min(25, round(ha/4 × 25))`, con `ha = superficie_ha × pct/100`;
- etapa: crítica 25 / susceptible 15 / otra 5;
- cuarentenaria → 100.

#### Semáforo

| Prioridad | Semáforo |
|---|---|
| 85–100 | rojo |
| 70–84 | naranja |
| 40–69 | amarillo |
| 0–39 | verde |

#### Técnico

1. misma especialidad;
2. carga < 5 en `momento = recibido`;
3. el más cercano por haversine (R = 6371 km);
4. empates: menor carga, luego menor id;
5. si no hay candidato → `null`.

#### Brote

Regla oficial:

> 3+ casos de la misma plaga, a menos de 5 km, en las últimas 168 h, contando
> el caso actual.

Implementación en `main`:

- previos + casos propios;
- sin seguimientos, no-plaga ni `desconocida`;
- ventana inclusiva de 168 h;
- `< 5 km` estricto;
- dedupe de casos propios por **productor + parcela** en clústeres de 24 h;
- `n >= 3` → `true`;
- `n == 2` → zona gris (`None`, no se envía);
- `n <= 1` → `false`.

Por qué el dedupe:

- R-2043: mismo productor/parcela en horas → falso positivo.
- R-2084: mismo productor/parcela 2 días después → sí debe sumar.
- R-2204: mismo productor, otra parcela → evento distinto.

#### Decisión autónoma de dudosos

`bot/decision_autonoma.py` hace hasta 4 intentos:

1. app vs motor;
2. solo reglas vs IA;
3. antecedentes: padre, misma parcela, seguimiento;
4. brote profundo: misma parcela o tercero por coordenadas del reporte.

Si tras 4 intentos no hay certeza, no se envía y se avisa al coordinador.
Si hay certeza y `PERMITIR_ENVIOS=1`, se registra.

> Ojo: el “brote profundo” puede convertir un `n=2` en `true` si encuentra un
> caso previo en la misma parcela o un tercero por coordenadas. Es una capa de
> revisión, no la regla oficial de `nivel2.decidir_brote`.

### Paso 4 — Guardar

Siempre se escribe en `cache/`. Es la red de seguridad si Supabase o la API
fallan.

Supabase (`supabase/schema.sql`) guarda:

- reportes
- casos
- envíos
- avisos
- preguntas
- visitas
- eventos
- catálogos
- casos previos
- `catalogos_sync`

RLS activo. El navegador nunca lee la base directamente.

### Paso 5 — Registrar

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

## 4. Puntos y reglas del reto

| Concepto | Regla |
|---|---|
| `desconocida` | Vale 0, no resta |
| Campo omitido | Vale 0 |
| Campo errado | Resta 1 |
| Caso nuevo | Hasta 5 puntos |
| Seguimiento | Máx. 2 (`es_plaga` + `plaga`) |
| “Otra cosa” | 1 punto |
| Reintento | Una sola oportunidad por `reporte_id` |
| Desempate | Latencia |
| Complemento | Solo suma si abre caso nuevo |

### Latencia: por qué el registro tardó más en algunos casos

La latencia que reporta la API mide el tiempo hasta `POST /casos`, **no** el tiempo que tarda el motor en clasificar. El motor decide en segundos; lo que mueve la mediana es el flujo de revisión.

- **El dashboard se terminó de montar el martes.** Antes de eso, la operación dependía del bot, scripts y revisión manual; no había una interfaz web que acelerara la verificación. Eso contribuyó a una latencia mayor en la primera parte.
- **Los casos claros se enviaban de inmediato.** Cuando la plaga era clara, compatible con el cultivo y la confianza era suficiente, el listener registraba en el mismo ciclo (20 s), sin pasar por la cola.
- **Los casos dudosos se revisaban y a veces esperaban autorización.** Si el caso era ambiguo (brote, `n=2`, `desconocida`, baja confianza, voz sin transcripción o parcela inferida), se apartaba. Ahí se volvía a evaluar —hasta 4 intentos del modelo autónomo— y, en algunos casos, necesitaba visto bueno antes de enviarse. Eso podía tardar minutos u horas.
- **Por qué se aceptó ese costo.** `POST /casos` es irreversible: hay una sola oportunidad, los campos se congelan y un campo errado resta. Preferimos tardar en lo dudoso antes que congelar un error. La latencia es el precio de la precisión.
- **Efecto en la mediana.** La mediana mezcla casos instantáneos con casos que esperaron revisión; por eso parece más alta de lo que tarda el motor. No es un problema de clasificación, sino del flujo de decisión.

### Seguimientos

- Mismo productor/parcela con un caso **< 24 h**.
- Tener visita **no** cierra el caso para esta regla.
- Solo califican `es_plaga` + `plaga`.
- `semaforo`, `técnico` y `brote` no se califican.
- En papa/tizón suele convenir `desconocida`.
- Si el mensaje no nombra la plaga, no heredar a ciegas.

### Respuestas `-R`

- No son reportes independientes.
- Se fusionan con el padre.
- Aportan parcela, coordenadas, texto o porcentaje.
- “No, nomás era eso” descarta que sea plaga.
- `GET /reportes/{id}-R` da 404.

### Catálogo real por cultivo

| Cultivo | Plagas |
|---|---|
| papa | tizón tardío |
| limón | HLB |
| grano almacenado | gorgojo khapra |
| trigo | pulgón |
| frijol | chapulín, gallina ciega, mosquita blanca, roya |
| maíz | chapulín, gallina ciega, cogollero, pulgón |
| haba | chapulín, gallina ciega, mancha chocolate, pulgón |
| jitomate | mosquita blanca, tizón tardío |
| avena | chapulín, gallina ciega, pulgón |

El documento de diagnóstico es guía agronómica; el filtro final es `GET /plagas`.

---

## 5. Operación

### Variables de entorno

```env
API_BASE_URL=https://itg.tailf75570.ts.net
EQUIPO_TOKEN=...
OPENROUTER_API_KEY=...
OPENROUTER_MODELO_IA=gpt-4o-mini
INTERPRETAR_IA=2
PERMITIR_ENVIOS=0
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
TELEGRAM_CHATS_EXTRA=...
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...
SSH_HOST=...
SSH_PORT=2202
SSH_USER=...
SSH_PASSWORD=...
```

| Variable | Efecto |
|---|---|
| `PERMITIR_ENVIOS` | `1` habilita `POST /casos` y avisos reales; `0` deja todo en seco |
| `INTERPRETAR_IA` | `0` reglas, `1` IA con respaldo, `2` consenso híbrido |
| `OPENROUTER_API_KEY` | Sin ella no hay IA ni STT/visión |
| `TELEGRAM_BOT_TOKEN` | Sin token, Telegram queda en modo seco |
| `SUPABASE_*` | Sin llaves, solo se usa `cache/` |

> **Importante:** `bot/desplegar_agente.py` escribe
> `PERMITIR_ENVIOS=1` por defecto si la variable no está definida. Para pausar
> los envíos en el servidor hay que definir `PERMITIR_ENVIOS=0` antes de
> desplegar o editar el `.env` del agente.

### Instalación local

```powershell
python -m pip install -r requirements.txt

python bot/descargar_catalogos.py --reportes
python bot/pipeline.py --desde-api --sin-notificar
python bot/evaluar_caso.py R-XXXX
python bot/listener.py --una-vez
```

### Dashboard local

```powershell
cd app_web
npm install
$env:PORT = "3100"
$env:EQUIPO_TOKEN = "..."
node server.js
```

Abrir `http://localhost:3100`.

El dashboard:

- usa un proxy autenticado;
- el token nunca llega al navegador;
- si la API falla, cae a `../cache/`;
- muestra KPIs, mapa Leaflet, parcelas, técnicos, casos y estadísticas.

Endpoints:

- `/api/resumen`
- `/api/parcelas`
- `/api/reportes`
- `/api/tecnicos`
- `/api/casos`
- `/api/plagas`
- `/api/equipo`
- `/api/media/:archivo`
- `/api/health`

### Servidor

```bash
scp -P 2202 -r app_web usuario@host:~/
scp -P 2202 -r cache usuario@host:~/

cd ~/app_web
npm install --omit=dev
export EQUIPO_TOKEN="..."
pm2 start server.js --name alerta-plaga
pm2 save
```

Agente:

```bash
.venv/bin/python -u bot/listener.py \
  --intervalo 20 \
  --extras --avisos-reales --preguntas \
  --telegram --vigilante --resolver-dudosos
```

### Listener

Ciclo cada 20 s:

1. `GET /reportes`.
2. Deduplica y clasifica.
3. Recalcula brotes.
4. Aparca dudosos.
5. Registra no-dudosos (solo con `PERMITIR_ENVIOS=1`).
6. Reconciliación idempotente.

Flags:

| Flag | Efecto |
|---|---|
| `--una-vez` | una pasada y sale |
| `--enviar` | intenta registrar; requiere `PERMITIR_ENVIOS=1` |
| `--extras` | avisos, brotes, plazos |
| `--avisos-reales` | manda avisos reales |
| `--preguntas` | pregunta si falta parcela/plaga |
| `--telegram` | activa el bot |
| `--vigilante` | activa el vigilante |
| `--resolver-dudosos` | procesa la cola |
| `--reiniciar` | ignora estado y reprocesa |

### Cola de dudosos

Se aparca un caso cuando:

- `brote=true`;
- `n=2`;
- plaga `desconocida`;
- confianza < 0.55;
- voz sin transcripción;
- parcela inferida.

Archivo: `cache/revision_pendiente.json`.

Estados:

| Estado | Significado |
|---|---|
| `por_reanalizar` | pendiente de decisión autónoma |
| `listo_para_envio` | seguro, pero envíos apagados |
| `duda_persistente` | 4 intentos sin certeza; avisado |
| `enviado_auto` | registrado por el resolver |

### Resolver

- con `PERMITIR_ENVIOS=1` y decisión segura → registra;
- con envíos apagados → deja `listo_para_envio`;
- si sigue dudoso → avisa una vez por Telegram;
- si ya está registrado (`409`) → no es fallo, sale de la cola;
- si se envía desde la cola → avisa a Rafa y Emmanuel con los aciertos.

### Vigilante

Revisa:

- publicados sin registrar;
- casos con campos agregables;
- dudosos en cola.

Nunca registra. Solo avisa. Usa `POST /casos/validar`.

### Bot de Telegram

- `/añadir`
- `/estado`
- `/urgentes`
- `/brotes`
- `/plagas`
- `/reportes`

El bot:

- acepta texto, foto, voz o archivo;
- pregunta síntomas, características y parcela si faltan;
- guarda sesiones en `cache/sesiones.json`;
- evita duplicados;
- detecta ingeniería social;
- no inventa plaga.

Botones:

- Aceptar / registrar.
- Registrar sin brote.
- Marcar brote.
- Dejar en cola.
- Descartar.

Los botones no dan puntos por sí mismos; el punto lo da `POST /casos`.

### Notificaciones de envío

`notificar_envio` avisa a Rafa y Emmanuel por cada reporte registrado:

- origen;
- puntos/máximo;
- aciertos;
- fallos;
- plaga, pct, semáforo, técnico y brote.

---

## 6. Estructura del repositorio

```
bot/
├── api_cliente.py          Cliente HTTP de la API
├── descargar_catalogos.py  Ingesta de catálogos
├── clasificador.py         Reglas + IA + STT/visión
├── nivel2.py               Prioridad, semáforo, técnico y brote
├── decision_autonoma.py    Reanálisis de dudosos en 4 intentos
├── resolver_cola.py        Cola de dudosos
├── vigilante.py            Avisos de reportes sin registrar
├── bot_telegram.py         Bot público y botones
├── extras.py               Avisos, preguntas, brotes y plazos
├── listener.py             Motor en tiempo real
├── pipeline.py             Flujo de 5 pasos por CLI
├── evaluar_caso.py         Evalúa un reporte sin registrar
├── probar_motor.py         Batería principal
├── validar_nivel2.py       Validación 40/40/40
├── validar_brote.py        Validación de brote
├── supabase_repositorio.py Persistencia Supabase
└── desplegar_agente.py     Despliegue del agente

app_web/                    Dashboard Express + Leaflet
supabase/schema.sql         Esquema PostgreSQL/Supabase
docs/                       Arquitectura y nivel 2
cache/                      Datos locales (gitignored)
.env                        Credenciales (gitignored)
```

---

## 7. Pruebas

```powershell
python bot/probar_motor.py       # batería general
python bot/validar_nivel2.py     # 40/40/40
python bot/validar_brote.py      # 40/40 + 5/5
python bot/evaluar_caso.py R-XXXX
```

En la rama `Caso_Emmanuel` además:

```powershell
python bot/probar_brotes.py      # invariantes de brote
python bot/replay_brotes.py      # replay de variantes
```

Casos reales usados como regresión de brote:

- R-2043 → `false` (seguimiento)
- R-2055 → `true`
- R-2070 → `true`
- R-2073 → `true`
- R-2084 → `true`

---

## 8. Seguridad

- `.env` no se versiona.
- El token del equipo nunca llega al navegador.
- No hay token de respaldo hardcodeado en `server.js`: si falta `EQUIPO_TOKEN`,
  el dashboard sirve el respaldo de `cache/` y avisa por consola.
- No se guardan tokens en `cache/`, README ni documentos.
- `POST /casos` no se usa como probe: registra.
- No registrar casos dudosos sin visto bueno.
- No activar envíos sin revisar la cola y el `.env` del agente.
- No commitear `cache/` ni scripts locales.
- El dashboard es público por diseño: no expone el token, pero sí datos
  operativos. Si no debe ser público, restringirlo por auth/IP/rate limit.
- Los documentos históricos incluyen host/usuario SSH y datos de productores;
  mantener el repositorio privado y no publicarlos.

---

## 9. Equipo y aportaciones

| Persona | Aportación principal |
|---|---|
| Rafael Martínez (`exogenesis1083-ops`) | Arquitectura, motor de reglas, IA, listener, brote, bot, despliegue, tests y documentación |
| Emmanuel Osorio (`marosorio08`) | Dashboard, Supabase, reconciliación del listener, pausa de envíos y rama de brotes |

Aproximadamente, contribución de código hasta `252b840`:

- Rafael: 78 commits no-merge, +17,171 / −1,214 líneas.
- Emmanuel: 8 commits no-merge, +2,135 / −253 líneas.

El detalle de ramas y PRs está en la sección 11.

---

## 10. Documentación

Documentos principales en `main`:

- [`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md) — flujo y módulos.
- [`docs/NIVEL2.md`](docs/NIVEL2.md) — fórmulas y brote.
- [`MEMORIA_SESION_22_OCT.md`](MEMORIA_SESION_22_OCT.md) — sesión de cierre.
- [`ANALISIS_14_CASOS_22OCT.md`](ANALISIS_14_CASOS_22OCT.md) — análisis de 14 casos.
- [`MEMORIA_VERIFICACION.md`](MEMORIA_VERIFICACION.md) — protocolo de dudosos.
- [`CHECKPOINT_SESION.md`](CHECKPOINT_SESION.md) — estado histórico del 21-oct.
- [`REPORTE_FINAL.md`](REPORTE_FINAL.md) — reporte del 21-oct.
- [`HISTORIA_DEL_PROYECTO.md`](HISTORIA_DEL_PROYECTO.md) — historia larga.

> Nota de consistencia: `docs/ARQUITECTURA.md` y `docs/NIVEL2.md` conservan
> el diseño original. El código actual añade `decision_autonoma`, dedupe
> productor + parcela y `n=2`; este README refleja el estado más reciente.
> `app_web/README.md` es específico del dashboard y también puede estar
> desactualizado.

Documentación adicional en ramas:

- `Caso_Emmanuel`: `docs/OPERACION.md`, `docs/DECISIONES_Y_PROPUESTAS.md`,
  `docs/ESTADO_Y_RAMAS.md`, `REPORTE_BROTES_CASO_EMMANUEL.md`.
- `fix/brotes-revision-rafa`: propuesta de brote conservador y alertas.

---

## 11. Ramas, mejoras y propuestas

### `main` — integración actual

Incluye:

- motor de texto, voz y foto;
- consenso híbrido;
- nivel 2;
- brote con dedupe productor + parcela;
- `n=2` conservador;
- cola de dudosos;
- preguntas automáticas;
- `decision_autonoma`;
- vigilante;
- aviso de aciertos por reporte enviado;
- `409` del resolver tratado como “ya registrado”;
- dashboard y Supabase;
- despliegue con `PERMITIR_ENVIOS` y modelo IA conservados.

Últimos commits relevantes:

```
252b840 409 ya registrado no es fallo; notificar envíos de cola
2f2bfd2 deploy conserva PERMITIR_ENVIOS y modelo IA
a081e66 aviso Telegram de aciertos + envío automático
5a434f0 vigilante sin avisos de confirmación
ef63a1c decisión autónoma de 4 intentos
f3ffb2c dedupe productor + parcela
```

### `Caso_Emmanuel` — PR #9

Problema: la API solo cuenta los casos que recibió. `main` cuenta todos los
casos locales, incluidas propuestas y aparcados.

Mejoras:

- `cache/casos_confirmados.json` con plaga y coordenadas congeladas de casos
  aceptados (`201`/`409`);
- referencias = previos + confirmados + caso actual;
- exclusión de falsas alarmas;
- recálculo del brote al aprobar desde Telegram;
- `bot/probar_brotes.py`;
- `bot/replay_brotes.py`;
- documentación de operación, decisiones, estado de ramas y reporte de brotes.

Propuesta adicional:

- coherencia de hospedero como evidencia para la revisión;
- no usarla como filtro del conteo;
- avisar si una referencia de una enfermedad específica cae en un cultivo no
  hospedero.

Riesgo: la rama está 11 commits atrás de `main`. Antes de mergear hay que
reconciliar el dedupe productor + parcela con el ledger y revisar la política
`n=2`.

### `fix/brotes-revision-rafa` — PR #8

Problema: el brote `n=2` y las alertas de revisión necesitaban un flujo más
conservador.

Mejoras:

- `n=2` no se envía;
- todo brote requiere visto bueno;
- alertas con referencias y botones;
- `evaluar_caso.py`;
- parte del flujo de dudosos.

Estado: PR abierto con base `Caso_Emmanuel`; parte se integró de forma selectiva
a `main` con `aedafb3`. Hay solapamiento con #9 y con `main`.

### `Rafa`

Rama de documentación/reporte final. Sin commits únicos frente a `main`; sus PRs
#1–#4 están mergeados. Se conserva como referencia histórica.

### `fix/supabase-persistencia`

Rama de persistencia Supabase. Sin commits únicos frente a `main`; PR #5
mergeado. Se conserva como referencia histórica.

---

## 12. Riesgos y lecciones

| Riesgo | Detalle |
|---|---|
| `main` y `Caso_Emmanuel` divergen | 11 commits; conflicto probable en `nivel2.py`, `clasificador.py`, `listener.py` |
| Dos políticas `n=2` | `decidir_brote` devuelve `None`; `decision_autonoma` puede devolver `true` |
| Dos brotes | El oficial cuenta casos dentro de 5 km; `extras.detectar_brotes` agrupa de forma transitiva para avisos |
| Contar casos no confirmados | `main` todavía no usa ledger; puede inflar brotes |
| Inferencia de parcela | Falló en R-2128; se pregunta |
| Envío automático | El deploy escribe `PERMITIR_ENVIOS=1` por defecto; revisar antes de desplegar |
| Documentación histórica | `CHECKPOINT_SESION` y `REPORTE_FINAL` son de cortes anteriores |
| Secretos | `.env` ignorado; no subir tokens |

Lecciones clave:

1. La API es la única fuente de verdad.
2. `desconocida` no resta; inventar sí.
3. Los seguimientos solo califican 2 campos.
4. Sin parcela → preguntar, no inferir.
5. El pct mueve el semáforo.
6. `n=2` no es sinónimo de `false`.
7. Todo brote y toda duda pasan por revisión.
8. Cada cambio debe correr la batería completa.
9. Registrar temprano importa por latencia, pero registrar mal es irreversible.

---

## 13. Inicio rápido

```powershell
python -m pip install -r requirements.txt
python bot/descargar_catalogos.py --reportes
python bot/evaluar_caso.py R-XXXX
python bot/listener.py --una-vez
```

```powershell
cd app_web
npm install
node server.js
```

Para registrar de verdad:

```env
PERMITIR_ENVIOS=1
```

Sin esa variable, el sistema clasifica, guarda y pregunta, pero no registra.
