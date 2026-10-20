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

## Regla de urgencia (código puro, sin IA)

```python
PLAGAS_URGENTES = {"gusano_cogollero", "roya_frijol", "tizon_tardio",
                   "chapulin", "hlb", "gorgojo_khapra"}
urgente = es_plaga and (plaga in PLAGAS_URGENTES)
```

## Estado (20-oct-2026, noche)

- Repo registrado con `PATCH /equipo` ✔
- Catálogos y 55 reportes descargados y en caché ✔
- Clasificador determinista: 20 reportes de texto resueltos (14 plaga + 6 no-plaga);
  34 voz/foto requieren transcripción/visión → plaga `desconocida`
- **Pendiente:** renovar OpenRouter API key (está expirada) para voz/fotos;
  `motor_audio_foto.py`, despliegue `app_web/`, telegram notificador

## Integrantes

- Rafael Martínez — IA, lógica y backend
- Emmanuel Osorio — fullstack, servidor SSH y Telegram
