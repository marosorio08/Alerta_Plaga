# 🌾 Alerta Plaga — Equipo 7_7 (IT Green × DIMA UACh)

Sistema para el hackathon **Alerta Plaga**: procesa los reportes de productores
(telegram: texto, voz `.ogg`, fotos `.jpg`), decide si son plagas del catálogo y
calcula urgencia por regla determinista. Desplegable en el servidor SSH asignado.

## Estructura

```
bot/
├── api_cliente.py          Cliente HTTP de la API del hackathon (token, reintentos)
├── descargar_catalogos.py  Ingesta y caché local (/plagas /parcelas /productores /tecnicos)
├── analisis_reportes.py    Cruce reportes + parcelas para revisión
├── clasificador.py         Motor: pre-filtro + anti-injection + cruce cultivo + urgencia
└── motor_audio_foto.py     (pendiente) transcripción .ogg y visión .jpg
app_web/                    (pendiente) dashboard en puerto 3000 del servidor
cache/                      Datos descargados (gitignored)
.env                        Credenciales (NO se sube a git)
```

## Uso rápido

```bash
python -m pip install -r requirements.txt
python bot/descargar_catalogos.py --reportes   # baja los 4 catálogos + reportes
python bot/analisis_reportes.py                 # tabla reporte -> cultivo
python bot/clasificador.py                      # clasificación completa (sin IA aún)
```

## Regla de urgencia

El Nivel 1 usaba una lista fija; el Nivel 2 ya no califica `urgente`. Ahora la urgencia
se **deriva del catálogo** (`severidad` alta/crítica o `cuarentenaria`), de modo que si
los organizadores agregan plagas el sistema se adapta sin tocar código.

## Estado (20-oct-2026, noche)

- Repo registrado con `PATCH /equipo` ✔
- Catálogos y reportes en caché ✔ (se refrescan solos cada 10 min)
- Motor completo: texto, voz (consenso de 2 modelos) y fotos (consenso de 3)
- Listener continuo que clasifica y valida sin registrar (`--enviar` es explícito)
- **0 casos registrados** en `POST /casos` a propósito, hasta validar todo

## Nivel 2 (prioridad · semáforo · técnico)

Desde el martes por la noche el reto pide, además de la plaga, un **semáforo** y un
**técnico asignado**. Todo se calcula con reglas deterministas en `bot/nivel2.py`
y se valida contra los 40 casos previos: **40/40 en prioridad, semáforo y técnico**.

```bash
python bot/validar_nivel2.py   # fórmulas contra casos con respuesta correcta
python bot/probar_motor.py     # 49 pruebas sin gastar API
python bot/extras.py           # brotes, plazos y cuarentenarias (modo seco)
```

Diseño y justificación: [`docs/NIVEL2.md`](docs/NIVEL2.md).

## Integrantes

- Rafael Martínez — IA, lógica y backend
- Emmanuel Osorio — fullstack, servidor SSH y Telegram
