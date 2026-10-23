# Operación — Alerta Plaga 7_7

> Guía práctica para levantar, operar y revisar el sistema sin romper nada.
> Los secretos viven en `.env` y **nunca** se suben al repositorio.

---

## 1. Requisitos

- Python 3.13+
- Node.js 20+
- Acceso a la API del reto
- Opcional: Supabase, Telegram, OpenRouter
- Opcional: acceso SSH al servidor

---

## 2. Variables de entorno

Crear `.env` en la raíz (no se versiona):

```env
# API del reto
API_BASE_URL=https://itg.tailf75570.ts.net
EQUIPO_TOKEN=...

# IA / STT / visión
OPENROUTER_API_KEY=...
OPENROUTER_MODELO_IA=gpt-4o-mini
INTERPRETAR_IA=2

# Envío real de casos
PERMITIR_ENVIOS=0

# Telegram
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
TELEGRAM_CHATS_EXTRA=...

# Supabase
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...

# Servidor
SSH_HOST=...
SSH_PORT=2202
SSH_USER=...
SSH_PASSWORD=...
```

### Variables críticas

| Variable | Efecto |
|---|---|
| `PERMITIR_ENVIOS` | `1` habilita `POST /casos` y avisos reales; `0` deja todo en seco |
| `INTERPRETAR_IA` | `0` reglas, `1` IA con respaldo, `2` consenso híbrido |
| `OPENROUTER_API_KEY` | Sin ella no hay IA ni STT/visión |
| `TELEGRAM_BOT_TOKEN` | Sin token, Telegram queda en modo seco |
| `SUPABASE_*` | Sin llaves, solo se usa `cache/` |

---

## 3. Instalación local

```powershell
python -m pip install -r requirements.txt

# Catálogos y reportes
python bot/descargar_catalogos.py --reportes

# Clasificación sin registrar
python bot/pipeline.py --desde-api --sin-notificar

# Un reporte concreto, sin registrar
python bot/evaluar_caso.py R-XXXX

# Listener en seco
python bot/listener.py --una-vez
```

---

## 4. Dashboard local

```powershell
cd app_web
npm install
$env:PORT = "3100"
$env:EQUIPO_TOKEN = "..."
node server.js
```

Abrir `http://localhost:3100`.

Sin token en el entorno, `server.js` usa un token de respaldo pensado solo para
pruebas locales. **No usar ese respaldo en producción.**

Si la API falla, el dashboard cae a `../cache/` y lo indica en `/api/resumen` y
en el pie de la página.

---

## 5. Servidor

```bash
# Copiar app_web y cache
scp -P 2202 -r app_web usuario@host:~/
scp -P 2202 -r cache usuario@host:~/

# Dashboard
cd ~/app_web
npm install --omit=dev
export EQUIPO_TOKEN="..."
pm2 start server.js --name alerta-plaga
pm2 save
```

### Agente

El agente corre bajo `supervisor` en `~/agente/.venv`.

Comando típico:

```bash
.venv/bin/python -u bot/listener.py \
  --intervalo 20 \
  --extras --avisos-reales --preguntas \
  --telegram --vigilante --resolver-dudosos
```

Con `PERMITIR_ENVIOS=0` el agente **no registra**; solo clasifica, guarda,
pregunta y deja la cola.

Para habilitar envíos:

```bash
export PERMITIR_ENVIOS=1
supervisorctl restart agente
```

---

## 6. Listener

Ciclo cada 20 s:

1. `GET /reportes`.
2. Deduplica y clasifica.
3. Recalcula brotes.
4. Aparca dudosos.
5. Registra no-dudosos (solo si `PERMITIR_ENVIOS=1`).
6. Reconciliación idempotente.

### Flags

| Flag | Efecto |
|---|---|
| `--una-vez` | una pasada y sale |
| `--enviar` | intenta registrar; requiere `PERMITIR_ENVIOS=1` |
| `--extras` | avisos, brotes, plazos |
| `--avisos-reales` | manda avisos reales |
| `--preguntas` | pregunta al productor si falta parcela/plaga |
| `--telegram` | activa el bot |
| `--vigilante` | activa el vigilante |
| `--resolver-dudosos` | procesa la cola con el modelo autónomo |
| `--reiniciar` | ignora estado y reprocesa |

---

## 7. Cola de dudosos

Archivo: `cache/revision_pendiente.json`.

Estados típicos:

| Estado | Significado |
|---|---|
| `por_reanalizar` | pendiente de decisión autónoma |
| `listo_para_envio` | seguro, pero envíos apagados |
| `duda_persistente` | 4 intentos sin certeza; avisado |
| `enviado_auto` | registrado por el resolver |

### Resolver

```powershell
python bot/resolver_cola.py --una-vez
python bot/resolver_cola.py --intervalo 90
```

- con `PERMITIR_ENVIOS=1` y decisión segura → registra;
- con envíos apagados → deja `listo_para_envio`;
- si sigue dudoso → avisa una vez por Telegram;
- si ya está registrado → sale de la cola.

### Botones de Telegram

- Aceptar / registrar.
- Registrar sin brote.
- Marcar brote.
- Dejar en cola.
- Descartar.

Los botones **no dan puntos por sí mismos**; el punto lo da `POST /casos`.

---

## 8. Vigilante

```powershell
python bot/vigilante.py --una-vez --sin-telegram
```

Revisa:

- publicados sin registrar;
- casos con campos agregables;
- dudosos.

Nunca registra. Usa `POST /casos/validar`.

---

## 9. Bot de Telegram

```powershell
python bot/bot_telegram.py --una-vez
python bot/bot_telegram.py            # long polling
python bot/bot_telegram.py --seco     # no manda avisos
```

Comandos de productor:

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

---

## 10. Pruebas

```powershell
python bot/probar_motor.py       # batería general
python bot/validar_nivel2.py     # 40/40/40
python bot/validar_brote.py      # 40/40 + 5/5
python bot/probar_brotes.py      # invariantes de brote (rama)
python bot/replay_brotes.py      # replay de variantes (rama)
```

Los tests offline necesitan `cache/` con catálogos y previos.

---

## 11. Seguridad operativa

- No usar `POST /casos` como probe: **registra**.
- Usar `POST /casos/validar` para probar formato.
- No registrar un caso dudoso sin visto bueno.
- No mandar brote con `n=2` sin revisar.
- No inferir parcela y registrar a ciegas.
- No activar `PERMITIR_ENVIOS=1` sin revisar la cola.
- No subir `.env`.
- No commitear `cache/`.

---

## 12. Problemas comunes

| Síntoma | Causa probable | Acción |
|---|---|---|
| `Falta EQUIPO_TOKEN` | `.env` ausente | crear `.env` |
| Listener no registra | `PERMITIR_ENVIOS=0` | activar solo con visto bueno |
| Dashboard sin datos | API caída | revisar `/api/health` y `cache/` |
| Telegram no manda | token/chat ausente | revisar `.env` |
| Voz queda `desconocida` | STT vacío | no cachear; reintentar |
| Brote dudoso | `n=2` | revisar cola |
| Caso ya registrado | 409 | no reenviar; usar `validar_caso` |
| Muchos 409 | reconciliación vieja | limpiar cola/estado con cuidado |

---

## 13. Checklist antes de enviar

1. ¿La plaga está en el catálogo y es compatible con el cultivo?
2. ¿El pct sale del texto?
3. ¿El técnico se calculó con `momento = recibido`?
4. ¿El brote se calculó con el conjunto completo?
5. ¿Si es `n=2`, hay visto bueno?
6. ¿Si es seguimiento, solo se mandan `es_plaga` + `plaga`?
7. ¿El reporte ya estaba registrado?
8. ¿`PERMITIR_ENVIOS` está en el valor correcto?

---

## 14. Documentos relacionados

- [`ARQUITECTURA.md`](ARQUITECTURA.md)
- [`NIVEL2.md`](NIVEL2.md)
- [`DECISIONES_Y_PROPUESTAS.md`](DECISIONES_Y_PROPUESTAS.md)
- [`ESTADO_Y_RAMAS.md`](ESTADO_Y_RAMAS.md)
