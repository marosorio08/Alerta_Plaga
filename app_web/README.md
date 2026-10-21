# Dashboard Alerta Plaga · Equipo 7_7

Dashboard web de monitoreo fitosanitario para el hackathon **Alerta Plaga**
(IT Green × DIMA, Universidad Autónoma Chapingo).

Muestra, en tiempo casi real:

- **KPIs del equipo**: puntos, lugar, reportes procesados, semáforo, brotes, técnicos disponibles y latencia mediana.
- **Mapa Leaflet** con las 264 parcelas coloreadas por estado (urgente, con plaga, sin plaga, sin clasificar) y los técnicos de campo (especialidad y carga), con capas activables.
- **Monitor de casos** con buscador y filtros por tipo (texto / voz / foto), urgencia, semáforo, brote y cultivo; columnas ordenables (incluye semáforo, técnico y brote) y ficha de detalle con prioridad, técnico y brote.
- **Estadísticas**: plagas más frecuentes, cultivos afectados, distribución de parcelas y parcelas con más reportes.

Stack: Node.js (≥ 20) + Express 4 + HTML/CSS/JS vanilla + Leaflet (CDN).
Sin build step: el frontend se sirve tal cual desde `public/`.

## Estructura

```
app_web/
├── server.js          # API + proxy autenticado + estáticos
├── package.json
├── .env.example
├── README.md
└── public/
    ├── index.html
    ├── styles.css
    ├── app.js
    └── favicon.svg
```

## Cómo correr en local

```powershell
cd app_web
npm install
$env:EQUIPO_TOKEN = "tu-token-del-equipo"   # opcional: hay un fallback en server.js
$env:PORT = 3100                            # opcional, por defecto 3000
node server.js
```

Abre <http://localhost:3100>.

Endpoints propios:

| Endpoint | Descripción |
| --- | --- |
| `GET /api/resumen` | Agregados: KPIs, por plaga, por cultivo, por municipio, top parcelas |
| `GET /api/parcelas` | 264 parcelas + estado, semáforo y brote (`?estado=`, `?semaforo=`, `?brote=1`, `?cultivo=`, `?q=`) |
| `GET /api/reportes` | Reportes enriquecidos (`?tipo=`, `?estado=`, `?urgente=1`, `?semaforo=`, `?brote=1`, `?tecnico=`, `?q=`) |
| `GET /api/tecnicos` | 12 técnicos con carga, disponibilidad y casos asignados (`?especialidad=`, `?disponible=1`, `?q=`) |
| `GET /api/casos` | Clasificaciones propuestas por el bot, con semáforo, técnico y brote (`cache/casos_propuestos.json`) |
| `GET /api/plagas` | Catálogo de plagas (marca `urgente` según la regla del reto) |
| `GET /api/equipo` | Avance del equipo **sin** credenciales |
| `GET /api/media/:archivo` | Proxy de fotos/audios de los reportes |
| `GET /api/health` | Estado del servicio y fuente de cada dato |

### Token

El token del equipo **nunca** llega al navegador: solo lo usa el backend como
header `X-Equipo-Token` hacia `https://itg.tailf75570.ts.net`.

- Local: `app_web/.env` (cópialo de `.env.example`, no se sube a git) o variable de entorno.
- Producción: variable de entorno del proceso (ver abajo).

Si `EQUIPO_TOKEN` no está definido se usa el token de respaldo que ya vive en `server.js`,
pensado solo para pruebas locales.

### Respaldo sin API

Si la API no responde (timeout de 9 s, error HTTP o sin red), el servidor cae
automáticamente a los JSON de `../cache/` (`parcelas.json`, `reportes.json`, etc.)
y lo indica en `/api/resumen` → `fuentes` y en el pie del dashboard.
`cache/` no se versiona en git, así que en el servidor conviene copiarlo junto a `app_web/`.

## Despliegue en el servidor

```bash
# 1. Copiar la carpeta (desde tu máquina)
scp -P 2202 -r app_web equipo02@179-236-73-82.sslip.io:~/
#    y, si quieres el modo de respaldo:
scp -P 2202 -r cache equipo02@179-236-73-82.sslip.io:~/

# 2. En el servidor
cd ~/app_web
npm install --omit=dev
export EQUIPO_TOKEN="<token>"
pm2 start server.js --name alerta-plaga
pm2 save
pm2 logs alerta-plaga
```

Requisitos: Node.js 20+ (probado en Node 22/24) y el puerto `3000` libre
(`PORT=3000` por defecto). La app pública queda en
`https://equipo02.179-236-73-82.sslip.io`.

Para fijar el token de forma permanente en el servidor, la vía más simple es un
archivo `.env` junto a `server.js` (el servidor lo carga solo, sin `dotenv`):

```bash
printf 'PORT=3000\nEQUIPO_TOKEN=tu-token\n' > .env
pm2 restart alerta-plaga --update-env
```

También puedes definirlo al arrancar:

```bash
EQUIPO_TOKEN="tu-token" pm2 start server.js --name alerta-plaga
```

> Nota: el frontend usa Leaflet y fuentes de CDN (unpkg / Google Fonts). Si el servidor
> o los navegadores no tienen salida a internet, el mapa no carga y el dashboard lo avisa,
> aunque las tablas y gráficas siguen funcionando.

## Variables de entorno

| Variable | Por defecto | Uso |
| --- | --- | --- |
| `PORT` | `3000` | Puerto HTTP |
| `EQUIPO_TOKEN` | token interno | Header `X-Equipo-Token` hacia la API |
| `API_BASE` | `https://itg.tailf75570.ts.net` | Base de la API del hackathon |
| `API_TIMEOUT_MS` | `9000` | Timeout por petición |
| `CACHE_TTL_MS` | `20000` | TTL de la caché en memoria |
| `CACHE_DIR` | `../cache` | Carpeta de respaldo JSON |
