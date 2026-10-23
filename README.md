# 🌾 Alerta Plaga — Equipo 7_7

Sistema de apoyo a la **junta de sanidad vegetal de Texcoco** para el hackathon
**Alerta Plaga** (IT Green × DIMA UACh).

Recibe reportes de productores por texto, voz o foto; identifica la plaga, calcula
prioridad, semáforo, técnico y brote; guarda la trazabilidad y registra el caso en
la API del reto cuando los envíos están habilitados.

> **Documentación viva.** Este README es la entrada. El detalle está en
> [`docs/`](docs/):
>
> - [`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md) — flujo de 5 pasos y módulos.
> - [`docs/NIVEL2.md`](docs/NIVEL2.md) — fórmulas, brote y validación.
> - [`docs/OPERACION.md`](docs/OPERACION.md) — cómo correrlo y operarlo.
> - [`docs/DECISIONES_Y_PROPUESTAS.md`](docs/DECISIONES_Y_PROPUESTAS.md) — por qué
>   se tomó cada decisión y qué sigue.
> - [`docs/ESTADO_Y_RAMAS.md`](docs/ESTADO_Y_RAMAS.md) — estado de `main`,
>   ramas, PRs y pendientes.

---

## 1. Qué hace

```
reporte del productor
        │
        ▼
1. RECIBIR       GET /reportes, deduplicación, caché
2. INTERPRETAR   reglas + IA; STT para voz; visión para foto
3. DECIDIR       prioridad · semáforo · técnico · brote (código puro)
4. GUARDAR       cache/ + Supabase
5. REGISTRAR     POST /casos (solo con PERMITIR_ENVIOS=1)
```

La IA **interpreta** el mensaje. El código **decide** los puntos. Esta separación
es obligatoria por el reglamento y permite reproducibilidad.

### Reglas que gobiernan los puntos

| Campo | Cómo se calcula |
|---|---|
| `es_plaga` / `plaga` | Reglas + IA + cruce con catálogo/cultivo |
| `semaforo` | `severidad + superficie(pct) + etapa` |
| `tecnico_id` | Especialidad + carga < 5 al `recibido` + haversine |
| `brote` | 3+ casos, misma plaga, < 5 km, 168 h |
| `prioridad` | Opcional, no da puntos; se manda como retroalimentación |

Detalle completo en [`docs/NIVEL2.md`](docs/NIVEL2.md).

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

El estado cambia rápido: la fuente de verdad es la API, no este README.

### Qué está implementado en `main`

- motor de texto, voz y foto;
- consenso híbrido reglas + IA;
- nivel 2 determinista;
- brote con dedupe **productor + parcela** en clústeres de 24 h;
- política conservadora `n=2` (zona gris, no se envía);
- cola de dudosos con visto bueno;
- preguntas automáticas cuando falta parcela o plaga;
- modelo de decisión autónoma de 4 intentos;
- vigilante de reportes sin registrar / agregables;
- bot de Telegram;
- dashboard con mapa, KPIs y monitor de casos;
- Supabase + caché local.

### Qué propone la rama `Caso_Emmanuel` (PR #9)

- ledger de casos **confirmados por la API** para contar brotes solo con lo que la
  API conoce;
- exclusión de falsas alarmas del conteo;
- recálculo del brote al aprobar un caso desde Telegram;
- `bot/probar_brotes.py` y `bot/replay_brotes.py`;
- coherencia de hospedero como **evidencia para revisión**, sin filtrar la regla.

Ver [`docs/ESTADO_Y_RAMAS.md`](docs/ESTADO_Y_RAMAS.md) y
[`REPORTE_BROTES_CASO_EMMANUEL.md`](REPORTE_BROTES_CASO_EMMANUEL.md).

---

## 3. Estructura

```
bot/
├── listener.py             Motor en tiempo real (polling cada 20 s)
├── clasificador.py         Reglas + IA + STT/visión + cruce de cultivo
├── nivel2.py               Prioridad, semáforo, técnico y brote (código puro)
├── decision_autonoma.py    Reanálisis de dudosos en 4 intentos
├── resolver_cola.py        Cola de dudosos y decisión autónoma
├── vigilante.py            Avisos de reportes sin registrar / agregables
├── bot_telegram.py         Bot público y botones de coordinación
├── extras.py               Avisos, preguntas, brotes y plazos
├── api_cliente.py          Cliente HTTP de la API del reto
├── supabase_repositorio.py Persistencia en Supabase
├── pipeline.py             Flujo de 5 pasos por CLI
├── evaluar_caso.py         Evalúa un reporte sin registrar
├── probar_motor.py         Batería principal sin gastar API
├── validar_nivel2.py       Validación 40/40/40
├── validar_brote.py        Validación de brote
├── confirmados.py          (rama Caso_Emmanuel) ledger de confirmados
├── probar_brotes.py        (rama Caso_Emmanuel) invariantes de brote
└── replay_brotes.py        (rama Caso_Emmanuel) replay de variantes

app_web/                    Dashboard Express + Leaflet
supabase/schema.sql         Esquema PostgreSQL/Supabase
docs/                       Arquitectura, nivel 2, operación, decisiones
cache/                      Datos locales (gitignored)
.env                        Credenciales (gitignored, nunca se sube)
```

---

## 4. Inicio rápido local

Requisitos:

- Python 3.13+
- Node.js 20+
- Un `.env` con `EQUIPO_TOKEN` y `API_BASE_URL`

```powershell
python -m pip install -r requirements.txt

# Catálogos y reportes
python bot/descargar_catalogos.py --reportes

# Clasificación sin registrar
python bot/pipeline.py --desde-api --sin-notificar

# Evaluar un reporte concreto sin registrar
python bot/evaluar_caso.py R-XXXX

# Listener en seco (no registra)
python bot/listener.py --una-vez
```

Dashboard:

```powershell
cd app_web
npm install
node server.js
# http://localhost:3000
```

### Envío real

El envío está **apagado por defecto**:

```env
PERMITIR_ENVIOS=1
```

Sin esa variable, el listener solo clasifica, guarda y pregunta; **no** hace
`POST /casos` ni manda avisos reales.

> Regla de oro: `POST /casos` no es un probe. Para probar formato se usa
> `POST /casos/validar`, que no registra.

---

## 5. Pruebas

| Comando | Qué valida |
|---|---|
| `python bot/probar_motor.py` | Batería general del motor |
| `python bot/validar_nivel2.py` | Prioridad, semáforo y técnico contra 40 previos |
| `python bot/validar_brote.py` | Brote 40/40 + casos reales |
| `python bot/probar_brotes.py` | Invariantes de brote (rama `Caso_Emmanuel`) |
| `python bot/replay_brotes.py` | Replay offline de variantes de brote |

Los tests offline requieren `cache/` con catálogos y casos previos. Algunos
comandos que consultan la API necesitan `.env`.

---

## 6. Seguridad y secretos

- `.env` **no** se versiona.
- El token del equipo nunca llega al navegador: el dashboard lo usa solo en el
  backend como `X-Equipo-Token`.
- El token de respaldo de `server.js` es solo para pruebas locales.
- No se guardan tokens en `cache/`, README ni documentos.
- Los scripts de `cache/` son locales y no se commitean.

---

## 7. Equipo

| Persona | Rol principal según el trabajo realizado |
|---|---|
| Rafael Martínez | Arquitectura, motor de reglas, IA, listener, brote, bot, despliegue y documentación |
| Emmanuel Osorio | Dashboard, Supabase, reconciliación del listener, pausa de envíos y rama de brotes |

El detalle de aportaciones y ramas está en
[`docs/ESTADO_Y_RAMAS.md`](docs/ESTADO_Y_RAMAS.md).

---

## 8. Documentación histórica

Estos documentos conservan el contexto de cada corte; pueden estar desfasados:

- [`CHECKPOINT_SESION.md`](CHECKPOINT_SESION.md) — estado del 21-oct.
- [`MEMORIA_VERIFICACION.md`](MEMORIA_VERIFICACION.md) — errores y protocolo de dudosos.
- [`MEMORIA_SESION_22_OCT.md`](MEMORIA_SESION_22_OCT.md) — sesión de cierre 21/22-oct.
- [`ANALISIS_14_CASOS_22OCT.md`](ANALISIS_14_CASOS_22OCT.md) — análisis de 14 casos del 22-oct.
- [`REPORTE_FINAL.md`](REPORTE_FINAL.md) — reporte del 21-oct.
- [`HISTORIA_DEL_PROYECTO.md`](HISTORIA_DEL_PROYECTO.md) — historia larga hasta el 20-oct.
