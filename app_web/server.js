'use strict';

/**
 * Alerta Plaga · Dashboard del equipo 7_7 (IT Green × DIMA UACh)
 *
 * Servidor Express que:
 *   1. Actúa como proxy autenticado hacia la API del hackathon (el token nunca
 *      viaja al navegador).
 *   2. Expone endpoints agregados para el dashboard (/api/resumen, /api/parcelas,
 *      /api/reportes, /api/casos, /api/equipo).
 *   3. Sirve el frontend estático de ./public.
 *
 * Si la API no responde, cae automáticamente a los JSON de ../cache.
 */

const path = require('node:path');
const fs = require('node:fs');
const express = require('express');

// ---------------------------------------------------------------------------
// Configuración (.env local opcional, sin dependencias extra)
// ---------------------------------------------------------------------------
const ENV_FILE = path.join(__dirname, '.env');
if (fs.existsSync(ENV_FILE) && typeof process.loadEnvFile === 'function') {
  try {
    process.loadEnvFile(ENV_FILE);
  } catch (err) {
    console.warn('[alerta-plaga] no se pudo leer .env:', err.message);
  }
}

const PORT = Number.parseInt(process.env.PORT || '', 10) || 3000;
const HOST = process.env.HOST || '0.0.0.0';
const API_BASE = (process.env.API_BASE || 'https://itg.tailf75570.ts.net').replace(/\/+$/, '');
const EQUIPO_TOKEN = process.env.EQUIPO_TOKEN || '';
if (!EQUIPO_TOKEN) {
  console.warn('[alerta-plaga] EQUIPO_TOKEN vacío: se servirá el respaldo local de cache/.');
}
const API_TIMEOUT_MS = Number.parseInt(process.env.API_TIMEOUT_MS || '', 10) || 9000;
const TTL_MS = Number.parseInt(process.env.CACHE_TTL_MS || '', 10) || 20000;
const PUBLIC_DIR = path.join(__dirname, 'public');
const CACHE_DIR = process.env.CACHE_DIR || path.resolve(__dirname, '..', 'cache');

const PLAGAS_URGENTES = new Set([
  'gusano_cogollero',
  'roya_frijol',
  'tizon_tardio',
  'chapulin',
  'hlb',
  'gorgojo_khapra',
]);

const DATA_KEYS = ['parcelas', 'plagas', 'reportes', 'productores', 'tecnicos', 'equipo'];
const FALLBACK_FILES = {
  parcelas: 'parcelas.json',
  plagas: 'plagas.json',
  reportes: 'reportes.json',
  productores: 'productores.json',
  tecnicos: 'tecnicos.json',
  equipo: 'equipo.json',
  casos: 'casos_propuestos.json',
};

// ---------------------------------------------------------------------------
// Capa de datos: API del hackathon con respaldo en cache/
// ---------------------------------------------------------------------------
const store = new Map(); // name -> { data, source, at, error }
const lastError = new Map(); // name -> string

async function apiGet(endpoint, { timeout = API_TIMEOUT_MS, retries = 1 } = {}) {
  let lastErr;
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    const started = Date.now();
    try {
      const res = await fetch(`${API_BASE}${endpoint}`, {
        headers: {
          'X-Equipo-Token': EQUIPO_TOKEN,
          Accept: 'application/json',
          'User-Agent': 'alerta-plaga-dashboard/1.0',
        },
        signal: AbortSignal.timeout(timeout),
      });
      if (!res.ok) {
        throw new Error(`API ${endpoint} respondió HTTP ${res.status}`);
      }
      const data = await res.json();
      console.log(`[alerta-plaga] GET ${endpoint} ${res.status} (${Date.now() - started} ms)`);
      return data;
    } catch (err) {
      lastErr = err;
      if (err.name === 'TimeoutError' || err.name === 'AbortError') {
        lastErr = new Error(`Tiempo de espera agotado (${timeout} ms) en ${endpoint}`);
      }
      if (attempt < retries) await new Promise((r) => setTimeout(r, 400));
    }
  }
  throw lastErr;
}

async function readFallback(name) {
  const file = FALLBACK_FILES[name];
  if (!file) throw new Error(`Sin archivo de respaldo para "${name}"`);
  const filePath = path.join(CACHE_DIR, file);
  const raw = await fs.promises.readFile(filePath, 'utf8');
  return JSON.parse(raw);
}

const inflight = new Map(); // evita pedir lo mismo varias veces en paralelo

/**
 * Devuelve los datos de una entidad. Prioridad: API -> cache/ -> memoria.
 * La respuesta incluye `source` ('api' | 'cache' | 'local') para avisar en UI.
 */
async function getData(name, { force = false } = {}) {
  const hit = store.get(name);
  if (!force && hit && Date.now() - hit.at < TTL_MS) return hit;
  if (inflight.has(name)) return inflight.get(name);

  const tarea = (async () => {
    try {
      // "casos" no se puede leer desde la API (solo acepta POST /casos),
      // el bot publica las clasificaciones propuestas en cache/casos_propuestos.json.
      const data = name === 'casos' ? await readFallback('casos') : await apiGet(`/${name}`);
      const record = { name, data, source: name === 'casos' ? 'local' : 'api', at: Date.now(), error: null };
      store.set(name, record);
      lastError.delete(name);
      return record;
    } catch (err) {
      const mensaje = err && err.message ? err.message : String(err);
      lastError.set(name, mensaje);
      console.warn(`[alerta-plaga] fallback a cache para "${name}": ${mensaje}`);
      try {
        const data = await readFallback(name);
        const record = { name, data, source: 'cache', at: Date.now(), error: mensaje };
        store.set(name, record);
        return record;
      } catch (fallbackErr) {
        if (hit) return { ...hit, error: mensaje, stale: true };
        throw new Error(`Datos no disponibles (API: ${mensaje} · cache: ${fallbackErr.message})`);
      }
    }
  })();

  inflight.set(name, tarea);
  try {
    return await tarea;
  } finally {
    inflight.delete(name);
  }
}

// ---------------------------------------------------------------------------
// Agregaciones
// ---------------------------------------------------------------------------
function estadoDeCaso(caso) {
  if (!caso) return 'sin_clasificar';
  if (caso.urgente) return 'urgente';
  if (caso.es_plaga) return 'plaga';
  return 'sin_plaga';
}

function nombrePlaga(plagasPorId, id) {
  if (!id) return null;
  if (id === 'desconocida') return 'Plaga sin identificar';
  const p = plagasPorId.get(id);
  return p ? p.nombre : id;
}

function construirModelo(records) {
  const parcelas = records.parcelas?.data || [];
  const plagas = records.plagas?.data || [];
  const reportes = records.reportes?.data || [];
  const productores = records.productores?.data || [];
  const casos = records.casos?.data || [];
  const equipo = records.equipo?.data || null;

  const plagasPorId = new Map(plagas.map((p) => [p.id, p]));
  const productoresPorId = new Map(productores.map((p) => [p.id, p]));
  const parcelasPorId = new Map(parcelas.map((p) => [p.id, p]));
  const casosPorReporte = new Map(casos.map((c) => [c.reporte_id, c]));

  // --- Reportes enriquecidos --------------------------------------------
  const reportesEnriquecidos = reportes
    .map((r) => {
      const caso = casosPorReporte.get(r.id) || null;
      const parcela = parcelasPorId.get(r.parcela_id) || null;
      const productor = productoresPorId.get(r.productor_id) || null;
      return {
        ...r,
        plaga_id: caso && caso.es_plaga ? caso.plaga || 'desconocida' : null,
        plaga_nombre: caso && caso.es_plaga ? nombrePlaga(plagasPorId, caso.plaga || 'desconocida') : null,
        es_plaga: caso ? Boolean(caso.es_plaga) : null,
        urgente: Boolean(caso && caso.urgente),
        estado: estadoDeCaso(caso),
        clasificado: Boolean(caso),
        parcela_nombre: parcela ? parcela.nombre : null,
        cultivo: parcela ? parcela.cultivo : null,
        etapa: parcela ? parcela.etapa : null,
        localidad: parcela ? parcela.localidad : null,
        municipio: parcela ? parcela.municipio : null,
        productor_nombre: productor ? productor.nombre : null,
        lat: r.lat != null ? r.lat : parcela ? parcela.lat : null,
        lon: r.lon != null ? r.lon : parcela ? parcela.lon : null,
      };
    })
    .sort((a, b) => String(b.recibido).localeCompare(String(a.recibido)));

  const reportesPorId = new Map(reportesEnriquecidos.map((r) => [r.id, r]));

  const casosEnriquecidos = casos.map((c) => {
    const rep = reportesPorId.get(c.reporte_id) || null;
    return {
      ...c,
      estado: estadoDeCaso(c),
      plaga_nombre: c.es_plaga ? nombrePlaga(plagasPorId, c.plaga || 'desconocida') : null,
      tipo: rep ? rep.tipo : null,
      recibido: rep ? rep.recibido : null,
      parcela_id: rep ? rep.parcela_id : null,
      parcela_nombre: rep ? rep.parcela_nombre : null,
      cultivo: rep ? rep.cultivo : null,
      productor_nombre: rep ? rep.productor_nombre : null,
    };
  });

  const reportesPorParcela = new Map();
  for (const r of reportesEnriquecidos) {
    if (!r.parcela_id) continue;
    if (!reportesPorParcela.has(r.parcela_id)) reportesPorParcela.set(r.parcela_id, []);
    reportesPorParcela.get(r.parcela_id).push(r);
  }

  // --- Parcelas con estado derivado --------------------------------------
  const parcelasEnriquecidas = parcelas.map((p) => {
    const propios = reportesPorParcela.get(p.id) || [];
    const estados = propios.map((r) => r.estado);
    let estado = 'sin_clasificar';
    if (estados.includes('urgente')) estado = 'urgente';
    else if (estados.includes('plaga')) estado = 'plaga';
    else if (estados.includes('sin_plaga')) estado = 'sin_plaga';

    const plagasDetectadas = [...new Set(propios.filter((r) => r.plaga_id).map((r) => r.plaga_id))];
    const productor = productoresPorId.get(p.productor_id);
    return {
      ...p,
      estado,
      reportes: propios.length,
      urgentes: propios.filter((r) => r.urgente).length,
      plaga_ids: plagasDetectadas,
      plagas: plagasDetectadas.map((id) => nombrePlaga(plagasPorId, id)),
      productor_nombre: productor ? productor.nombre : null,
      ultimo_reporte: propios.length
        ? propios.map((r) => r.recibido).sort().slice(-1)[0]
        : null,
    };
  });

  const parcelasPorEstado = { urgente: 0, plaga: 0, sin_plaga: 0, sin_clasificar: 0 };
  for (const p of parcelasEnriquecidas) parcelasPorEstado[p.estado] += 1;

  // --- Totales de casos ---------------------------------------------------
  const conClasificacion = casos.length;
  const urgentes = casos.filter((c) => c.urgente).length;
  const esPlaga = casos.filter((c) => c.es_plaga).length;
  const noPlaga = casos.filter((c) => !c.es_plaga).length;
  const sinClasificar = Math.max(0, reportes.length - casosPorReporte.size);

  const avance = (equipo && equipo.avance) || {};

  // --- Conteo por plaga ---------------------------------------------------
  const porPlagaMap = new Map();
  for (const c of casos) {
    if (!c.es_plaga) continue;
    const id = c.plaga || 'desconocida';
    if (!porPlagaMap.has(id)) porPlagaMap.set(id, { id, casos: 0, urgentes: 0, parcelas: new Set() });
    const entry = porPlagaMap.get(id);
    entry.casos += 1;
    if (c.urgente) entry.urgentes += 1;
    const rep = reportesPorId.get(c.reporte_id);
    if (rep && rep.parcela_id) entry.parcelas.add(rep.parcela_id);
  }
  const porPlaga = [...porPlagaMap.values()]
    .map((e) => ({
      id: e.id,
      nombre: nombrePlaga(plagasPorId, e.id),
      tipo: (plagasPorId.get(e.id) || {}).tipo || null,
      severidad: (plagasPorId.get(e.id) || {}).severidad || null,
      urgente_regla: PLAGAS_URGENTES.has(e.id),
      casos: e.casos,
      urgentes: e.urgentes,
      parcelas: e.parcelas.size,
    }))
    .sort((a, b) => b.casos - a.casos || b.urgentes - a.urgentes);

  // --- Conteo por cultivo -------------------------------------------------
  const porCultivoMap = new Map();
  const getCultivo = (nombre) => {
    if (!porCultivoMap.has(nombre)) {
      porCultivoMap.set(nombre, {
        cultivo: nombre,
        parcelas: 0,
        superficie_ha: 0,
        reportes: 0,
        plagas: 0,
        urgentes: 0,
      });
    }
    return porCultivoMap.get(nombre);
  };
  for (const p of parcelasEnriquecidas) {
    const c = getCultivo(p.cultivo || 'sin cultivo');
    c.parcelas += 1;
    c.superficie_ha += Number(p.superficie_ha) || 0;
  }
  for (const r of reportesEnriquecidos) {
    const c = getCultivo(r.cultivo || 'sin cultivo');
    c.reportes += 1;
    if (r.plaga_id) c.plagas += 1;
    if (r.urgente) c.urgentes += 1;
  }
  const porCultivo = [...porCultivoMap.values()]
    .map((c) => ({ ...c, superficie_ha: Math.round(c.superficie_ha * 10) / 10 }))
    .sort((a, b) => b.plagas - a.plagas || b.reportes - a.reportes);

  // --- Reportes por tipo --------------------------------------------------
  const reportesPorTipo = { texto: 0, voz: 0, foto: 0, otro: 0 };
  for (const r of reportes) {
    if (Object.prototype.hasOwnProperty.call(reportesPorTipo, r.tipo)) reportesPorTipo[r.tipo] += 1;
    else reportesPorTipo.otro += 1;
  }

  // --- Top parcelas -------------------------------------------------------
  const topParcelas = [...parcelasEnriquecidas]
    .filter((p) => p.reportes > 0)
    .sort((a, b) => b.reportes - a.reportes || b.urgentes - a.urgentes)
    .slice(0, 8)
    .map((p) => ({
      id: p.id,
      nombre: p.nombre,
      cultivo: p.cultivo,
      localidad: p.localidad,
      estado: p.estado,
      reportes: p.reportes,
      urgentes: p.urgentes,
      plagas: p.plagas,
    }));

  // --- Por municipio ------------------------------------------------------
  const porMunicipioMap = new Map();
  for (const p of parcelasEnriquecidas) {
    const m = p.municipio || 'sin municipio';
    if (!porMunicipioMap.has(m)) porMunicipioMap.set(m, { municipio: m, parcelas: 0, reportes: 0, urgentes: 0 });
    const e = porMunicipioMap.get(m);
    e.parcelas += 1;
    e.reportes += p.reportes;
    e.urgentes += p.urgentes;
  }
  const porMunicipio = [...porMunicipioMap.values()].sort((a, b) => b.reportes - a.reportes);

  const fuentes = {};
  for (const [k, v] of Object.entries(records)) {
    fuentes[k] = v ? (v.stale ? 'memoria' : v.source) : 'no disponible';
  }

  const resumen = {
    actualizado: new Date().toISOString(),
    fuentes,
    errores: Object.fromEntries(lastError),
    equipo: {
      nombre: (equipo && equipo.nombre) || '7_7',
      integrantes: (equipo && equipo.integrantes) || [],
      repo: (equipo && equipo.repo) || null,
      puntos: avance.puntos ?? null,
      maximo_posible: avance.maximo_posible ?? null,
      lugar: avance.lugar ?? null,
      enviados: avance.enviados ?? null,
      publicados: avance.publicados ?? null,
      aciertos_total: avance.aciertos_total ?? null,
      errores_total: avance.errores_total ?? null,
      latencia_mediana_min: avance.latencia_mediana_min ?? null,
      ultima_actividad: avance.ultima_actividad ?? null,
    },
    totales: {
      parcelas: parcelas.length,
      reportes: reportes.length,
      productores: productores.length,
      tecnicos: (records.tecnicos?.data || []).length,
      plagas_catalogo: plagas.length,
      superficie_ha: Math.round(parcelasEnriquecidas.reduce((s, p) => s + (Number(p.superficie_ha) || 0), 0) * 10) / 10,
    },
    casos: {
      clasificados: conClasificacion,
      sin_clasificar: sinClasificar,
      es_plaga: esPlaga,
      urgentes,
      plaga_normal: esPlaga - urgentes,
      no_plaga: noPlaga,
    },
    parcelas_estado: parcelasPorEstado,
    reportes_por_tipo: reportesPorTipo,
    por_plaga: porPlaga,
    por_cultivo: porCultivo,
    por_municipio: porMunicipio,
    top_parcelas: topParcelas,
  };

  return { resumen, parcelas: parcelasEnriquecidas, reportes: reportesEnriquecidos, casos: casosEnriquecidos };
}

async function cargarTodo({ force = false } = {}) {
  const names = [...DATA_KEYS, 'casos'];
  const results = await Promise.allSettled(names.map((n) => getData(n, { force })));
  const records = {};
  names.forEach((name, i) => {
    const r = results[i];
    if (r.status === 'fulfilled') records[name] = r.value;
    else console.warn(`[alerta-plaga] sin datos para "${name}": ${r.reason.message}`);
  });
  if (!records.reportes || !records.parcelas) {
    const detalle = results
      .filter((r) => r.status === 'rejected')
      .map((r) => r.reason.message)
      .join(' | ');
    throw new Error(`No fue posible obtener el catálogo base (${detalle})`);
  }
  if (!records.casos) records.casos = { data: [], source: 'no disponible' };
  return construirModelo(records);
}

// ---------------------------------------------------------------------------
// App HTTP
// ---------------------------------------------------------------------------
const app = express();
app.disable('x-powered-by');
app.set('trust proxy', 1);

app.use((req, res, next) => {
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('Referrer-Policy', 'strict-origin-when-cross-origin');
  if (req.path.startsWith('/api/')) res.setHeader('Cache-Control', 'no-store');
  next();
});

const asyncRoute = (fn) => (req, res, next) => Promise.resolve(fn(req, res, next)).catch(next);

app.get('/api/health', (req, res) => {
  res.json({
    ok: true,
    servicio: 'alerta-plaga-dashboard',
    equipo: '7_7',
    api_base: API_BASE,
    uptime_s: Math.round(process.uptime()),
    ahora: new Date().toISOString(),
    errores: Object.fromEntries(lastError),
    fuentes: Object.fromEntries([...store].map(([k, v]) => [k, { source: v.source, at: new Date(v.at).toISOString() }])),
  });
});

app.get('/api/resumen', asyncRoute(async (req, res) => {
  const force = req.query.refresh === '1';
  const { resumen } = await cargarTodo({ force });
  res.json(resumen);
}));

app.get('/api/parcelas', asyncRoute(async (req, res) => {
  const force = req.query.refresh === '1';
  const { parcelas } = await cargarTodo({ force });
  let datos = parcelas;
  const { estado, cultivo, municipio, q } = req.query;
  if (estado) datos = datos.filter((p) => p.estado === estado);
  if (cultivo) datos = datos.filter((p) => p.cultivo === cultivo);
  if (municipio) datos = datos.filter((p) => p.municipio === municipio);
  if (q) {
    const term = String(q).toLowerCase();
    datos = datos.filter((p) => `${p.id} ${p.nombre} ${p.productor_nombre} ${p.localidad}`.toLowerCase().includes(term));
  }
  res.json({
    total: datos.length,
    total_parcelas: parcelas.length,
    generado: new Date().toISOString(),
    parcelas: datos,
  });
}));

app.get('/api/reportes', asyncRoute(async (req, res) => {
  const force = req.query.refresh === '1';
  const { reportes } = await cargarTodo({ force });
  let datos = reportes;
  const { tipo, estado, cultivo, urgente, q } = req.query;
  if (tipo) datos = datos.filter((r) => r.tipo === tipo);
  if (estado) datos = datos.filter((r) => r.estado === estado);
  if (cultivo) datos = datos.filter((r) => r.cultivo === cultivo);
  if (urgente === '1' || urgente === 'true') datos = datos.filter((r) => r.urgente);
  if (q) {
    const term = String(q).toLowerCase();
    datos = datos.filter((r) =>
      `${r.id} ${r.texto || ''} ${r.productor_nombre || ''} ${r.parcela_nombre || ''} ${r.plaga_nombre || ''}`
        .toLowerCase()
        .includes(term),
    );
  }
  res.json({ total: datos.length, generado: new Date().toISOString(), reportes: datos });
}));

app.get('/api/plagas', asyncRoute(async (req, res) => {
  const { data, source } = await getData('plagas', { force: req.query.refresh === '1' });
  res.json({
    total: data.length,
    fuente: source,
    plagas: data.map((p) => ({ ...p, urgente: PLAGAS_URGENTES.has(p.id) })),
  });
}));

app.get('/api/equipo', asyncRoute(async (req, res) => {
  const { data, source } = await getData('equipo', { force: req.query.refresh === '1' });
  // Nunca exponer credenciales del bloque "accesos" (SSH / token) al navegador.
  const { accesos, token, ...publico } = data || {};
  res.json({ fuente: source, ...publico });
}));

app.get('/api/casos', asyncRoute(async (req, res) => {
  const force = req.query.refresh === '1';
  const { casos } = await cargarTodo({ force });
  res.json({
    total: casos.length,
    fuente: store.get('casos') ? store.get('casos').source : 'no disponible',
    actualizado: new Date().toISOString(),
    urgentes: casos.filter((c) => c.urgente).length,
    casos,
  });
}));

// Proxy de multimedia (fotos / audios de los reportes), sin filtrar el token.
app.get('/api/media/:archivo', asyncRoute(async (req, res) => {
  const archivo = req.params.archivo;
  if (!/^[A-Za-z0-9._-]+\.(jpe?g|png|webp|gif|ogg|mp3|m4a|wav)$/i.test(archivo)) {
    return res.status(400).json({ error: true, mensaje: 'Archivo no permitido' });
  }
  const upstream = await fetch(`${API_BASE}/media/${archivo}`, {
    headers: { 'X-Equipo-Token': EQUIPO_TOKEN },
    signal: AbortSignal.timeout(15000),
  });
  if (!upstream.ok) {
    return res.status(upstream.status === 404 ? 404 : 502).json({
      error: true,
      mensaje: `La API no entregó el archivo (HTTP ${upstream.status})`,
    });
  }
  const buffer = Buffer.from(await upstream.arrayBuffer());
  res.setHeader('Content-Type', upstream.headers.get('content-type') || 'application/octet-stream');
  res.setHeader('Cache-Control', 'public, max-age=3600');
  res.send(buffer);
}));

app.use('/api', (req, res) => {
  res.status(404).json({ error: true, mensaje: `Ruta no encontrada: ${req.method} ${req.originalUrl}` });
});

// Frontend estático
app.use(express.static(PUBLIC_DIR, { extensions: ['html'], maxAge: process.env.NODE_ENV === 'production' ? '1h' : 0 }));
app.use((req, res, next) => {
  if (req.method !== 'GET' && req.method !== 'HEAD') return next();
  if (path.extname(req.path) || !req.accepts('html')) return next();
  res.sendFile(path.join(PUBLIC_DIR, 'index.html'));
});
app.use((req, res) => {
  res.status(404).type('text/plain').send('No encontrado');
});

// Manejo de errores centralizado -> JSON claro
// eslint-disable-next-line no-unused-vars
app.use((err, req, res, next) => {
  const status = err.status || 502;
  console.error('[alerta-plaga] error:', err.message);
  res.status(status).json({
    error: true,
    mensaje: 'No fue posible obtener los datos del dashboard',
    detalle: err.message,
    ahora: new Date().toISOString(),
  });
});

const server = app.listen(PORT, HOST, () => {
  console.log(`[alerta-plaga] dashboard escuchando en http://localhost:${PORT}`);
  console.log(`[alerta-plaga] API: ${API_BASE} · token ${EQUIPO_TOKEN ? 'configurado' : 'AUSENTE'}`);
  cargarTodo().catch((err) => console.warn('[alerta-plaga] precalentamiento falló:', err.message));
});

function shutdown(signal) {
  console.log(`[alerta-plaga] ${signal}: cerrando servidor...`);
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(0), 3000).unref();
}
process.on('SIGINT', () => shutdown('SIGINT'));
process.on('SIGTERM', () => shutdown('SIGTERM'));
