'use strict';

/**
 * Dashboard Alerta Plaga · equipo 7_7
 * Frontend sin build: HTML + CSS + JS vanilla, Leaflet por CDN.
 */
(() => {
  // ---------------------------------------------------------------------
  // Utilidades
  // ---------------------------------------------------------------------
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const nf = new Intl.NumberFormat('es-MX');
  const n1 = new Intl.NumberFormat('es-MX', { maximumFractionDigits: 1 });
  const fmtFecha = new Intl.DateTimeFormat('es-MX', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: 'America/Mexico_City',
  });
  const fmtHora = new Intl.DateTimeFormat('es-MX', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
    timeZone: 'America/Mexico_City',
  });

  const esc = (value) =>
    String(value ?? '').replace(/[&<>"']/g, (c) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    }[c]));

  const fecha = (iso) => {
    if (!iso) return '—';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '—';
    return fmtFecha.format(d).replace('.', '');
  };

  function actualizarSaludo() {
    if (!el.saludo) return;
    const hora = Number(new Intl.DateTimeFormat('en-US', {
      hour: '2-digit',
      hourCycle: 'h23',
      timeZone: 'America/Mexico_City',
    }).format(new Date()));
    let texto = '🌙 Hola, buenas noches';
    if (hora >= 6 && hora < 12) texto = '🌅 Hola, buenos días';
    else if (hora >= 12 && hora < 19) texto = '☀️ Hola, buenas tardes';
    el.saludo.textContent = texto;
  }

  const REFRESH_MS = 30000;

  const ESTADOS = {
    urgente: { label: 'Urgente', color: '#ff6b6b', badge: 'badge-urgente', prioridad: 0 },
    plaga: { label: 'Con plaga', color: '#ffb84d', badge: 'badge-plaga', prioridad: 1 },
    sin_plaga: { label: 'Sin plaga', color: '#2dd4a7', badge: 'badge-sin_plaga', prioridad: 2 },
    sin_clasificar: { label: 'Sin clasificar', color: '#8fa99a', badge: 'badge-sin_clasificar', prioridad: 3 },
  };

  const SEMAFORO = {
    rojo: { label: 'Rojo', emoji: '🔴', color: '#ff6b6b', badge: 'badge-semaforo-rojo', orden: 0 },
    naranja: { label: 'Naranja', emoji: '🟠', color: '#ffb84d', badge: 'badge-semaforo-naranja', orden: 1 },
    amarillo: { label: 'Amarillo', emoji: '🟡', color: '#e8c547', badge: 'badge-semaforo-amarillo', orden: 2 },
    verde: { label: 'Verde', emoji: '🟢', color: '#2dd4a7', badge: 'badge-semaforo-verde', orden: 3 },
  };

  const TIPO_LABEL = { texto: 'Texto', voz: 'Voz', foto: 'Foto' };
  const TIPO_ICON = {
    texto: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 6h16M4 12h16M4 18h10"/></svg>',
    voz: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3Z"/><path d="M5 11a7 7 0 0 0 14 0"/><path d="M12 18v3"/></svg>',
    foto: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="9" cy="10" r="1.6"/><path d="m21 16-5-5-6 6"/></svg>',
  };

  // ---------------------------------------------------------------------
  // Estado
  // ---------------------------------------------------------------------
  const state = {
    resumen: null,
    parcelas: [],
    reportes: [],
    tecnicos: [],
    cargando: false,
    ultimaActualizacion: null,
    error: null,
    modoRespaldo: false,
    filtros: { tipo: '', urgencia: '', semaforo: '', brote: '', cultivo: '', q: '' },
    orden: { key: 'recibido', dir: 'desc' },
    capas: new Set(Object.keys(ESTADOS)),
    tecnicosVisible: true,
  };

  // ---------------------------------------------------------------------
  // DOM
  // ---------------------------------------------------------------------
  const el = {
    live: $('#live-indicator'),
    liveText: $('#live-text'),
    saludo: $('#saludo'),
    refreshBtn: $('#refresh-btn'),
    banner: $('#banner'),
    bannerText: $('#banner-text'),
    bannerRetry: $('#banner-retry'),
    kpiPuntos: $('#kpi-puntos'),
    kpiPuntosMax: $('#kpi-puntos-max'),
    kpiPuntosBar: $('#kpi-puntos-bar'),
    kpiPuntosFoot: $('#kpi-puntos-foot'),
    kpiLugar: $('#kpi-lugar'),
    kpiLugarFoot: $('#kpi-lugar-foot'),
    kpiReportes: $('#kpi-reportes'),
    kpiReportesFoot: $('#kpi-reportes-foot'),
    kpiSemaforo: $('#kpi-semaforo'),
    kpiSemaforoFoot: $('#kpi-semaforo-foot'),
    kpiBrotes: $('#kpi-brotes'),
    kpiBrotesFoot: $('#kpi-brotes-foot'),
    kpiTecnicos: $('#kpi-tecnicos'),
    kpiTecnicosFoot: $('#kpi-tecnicos-foot'),
    kpiLatencia: $('#kpi-latencia'),
    kpiLatenciaUnit: $('#kpi-latencia-unit'),
    kpiLatenciaFoot: $('#kpi-latencia-foot'),
    mapSub: $('#map-sub'),
    filtroTipo: $('#filtro-tipo'),    filtroUrgencia: $('#filtro-urgencia'),
    filtroSemaforo: $('#filtro-semaforo'),
    filtroBrote: $('#filtro-brote'),
    filtroCultivo: $('#filtro-cultivo'),
    q: $('#q'),
    limpiar: $('#limpiar'),
    tbody: $('#tbody-casos'),
    casosSub: $('#casos-sub'),
    tabla: $('#tabla-casos'),
    donutSegments: $('#donut-segments'),
    donutTotal: $('#donut-total'),
    estadoList: $('#estado-list'),
    semaforoList: $('#semaforo-list'),
    topParcelas: $('#top-parcelas'),
    chartPlagas: $('#chart-plagas'),
    chartCultivos: $('#chart-cultivos'),
    plagasSub: $('#plagas-sub'),
    cultivosSub: $('#cultivos-sub'),
    mapToggles: $('#map-toggles'),
    modal: $('#modal'),
    modalBody: $('#modal-body'),
    modalTitle: $('#modal-title'),
    modalEyebrow: $('#modal-eyebrow'),
    modalClose: $('#modal-close'),
    footerFuente: $('#footer-fuente'),
    footerHora: $('#footer-hora'),
  };

  // ---------------------------------------------------------------------
  // Carga de datos
  // ---------------------------------------------------------------------
  async function fetchJSON(url, signal) {
    const res = await fetch(url, { signal, headers: { Accept: 'application/json' }, cache: 'no-store' });
    if (!res.ok) {
      let detalle = `HTTP ${res.status}`;
      try {
        const body = await res.json();
        detalle = body.detalle || body.mensaje || detalle;
      } catch (_) { /* respuesta no JSON */ }
      throw new Error(detalle);
    }
    return res.json();
  }

  async function cargar({ silencioso = false } = {}) {
    if (state.cargando) return;
    state.cargando = true;
    setLive('loading');
    el.refreshBtn.disabled = true;
    const ctrl = new AbortController();
    const timeout = setTimeout(() => ctrl.abort(), 20000);

    try {
      const [resumen, parcelas, reportes, tecnicos] = await Promise.all([
        fetchJSON('/api/resumen', ctrl.signal),
        fetchJSON('/api/parcelas', ctrl.signal),
        fetchJSON('/api/reportes', ctrl.signal),
        fetchJSON('/api/tecnicos', ctrl.signal).catch(() => ({ tecnicos: [] })),
      ]);
      state.resumen = resumen;
      state.parcelas = parcelas.parcelas || [];
      state.reportes = reportes.reportes || [];
      state.tecnicos = tecnicos.tecnicos || [];
      state.ultimaActualizacion = new Date();
      state.error = null;
      state.modoRespaldo = Object.values(resumen.fuentes || {}).some((v) => v === 'cache' || v === 'memoria');
      ocultarBanner();

      renderKPIs();
      renderMapa();
      renderDonut();
      renderTopParcelas();
      renderCharts();
      poblarCultivos();
      renderTabla();
      renderFooter();
      setLive('ok');
      actualizarReloj();
    } catch (err) {
      const mensaje = err.name === 'AbortError' ? 'La solicitud tardó demasiado (20 s)' : err.message;
      state.error = mensaje;
      setLive('error');
      if (!silencioso || !state.resumen) mostrarBanner(`No se pudieron actualizar los datos: ${mensaje}`);
      if (!state.resumen) {
        el.tbody.innerHTML = `<tr><td colspan="9" class="empty">No hay datos disponibles. ${esc(mensaje)}</td></tr>`;
      }
    } finally {
      clearTimeout(timeout);
      state.cargando = false;
      el.refreshBtn.disabled = false;
    }
  }

  // ---------------------------------------------------------------------
  // Indicadores
  // ---------------------------------------------------------------------
  function setLive(mode) {
    el.live.classList.remove('is-loading', 'is-error', 'is-stale');
    if (mode === 'loading') {
      el.live.classList.add('is-loading');
      el.liveText.textContent = 'Actualizando…';
    } else if (mode === 'error') {
      el.live.classList.add('is-error');
      el.liveText.textContent = 'Sin conexión con la API';
    }
  }

  function actualizarReloj() {
    if (!state.ultimaActualizacion || state.cargando) return;
    const seg = Math.max(0, Math.round((Date.now() - state.ultimaActualizacion.getTime()) / 1000));
    if (state.error) {
      el.live.classList.add('is-error');
      el.liveText.textContent = `Último dato: hace ${seg} s`;
      return;
    }
    el.live.classList.remove('is-error');
    if (state.modoRespaldo) {
      el.live.classList.add('is-stale');
      el.liveText.textContent = `Respaldo local · hace ${seg} s`;
      return;
    }
    if (seg > 90) {
      el.live.classList.add('is-stale');
      el.liveText.textContent = `Datos de hace ${Math.round(seg / 60)} min`;
    } else {
      el.live.classList.remove('is-stale');
      el.liveText.textContent = `En vivo · hace ${seg} s`;
    }
  }

  function renderKPIs() {
    const r = state.resumen;
    if (!r) return;
    const eq = r.equipo || {};
    const casos = r.casos || {};
    const totales = r.totales || {};

    el.kpiPuntos.textContent = eq.puntos != null ? nf.format(eq.puntos) : '—';
    el.kpiPuntosMax.textContent = eq.maximo_posible ? `/ ${nf.format(eq.maximo_posible)}` : '';
    const pct = eq.puntos != null && eq.maximo_posible ? Math.min(100, (eq.puntos / eq.maximo_posible) * 100) : 0;
    el.kpiPuntosBar.style.width = `${pct}%`;
    el.kpiPuntosFoot.textContent = `${nf.format(eq.publicados ?? 0)} publicados · ${nf.format(eq.enviados ?? 0)} enviados`;

    el.kpiLugar.textContent = eq.lugar != null ? `${eq.lugar}°` : '—';
    el.kpiLugarFoot.textContent = 'posición en el hackathon';

    el.kpiReportes.textContent = nf.format(totales.reportes ?? 0);
    el.kpiReportesFoot.textContent = `${nf.format(casos.clasificados ?? 0)} clasificados · ${nf.format(casos.sin_clasificar ?? 0)} pendientes`;

    const sem = casos.semaforo || {};
    const tech = r.tecnicos || {};
    const urgentes = casos.urgentes ?? ((sem.rojo || 0) + (sem.naranja || 0));
    el.kpiSemaforo.textContent = nf.format(urgentes);
    const desglose = [
      `🔴 ${nf.format(sem.rojo || 0)}`,
      `🟠 ${nf.format(sem.naranja || 0)}`,
      `🟡 ${nf.format(sem.amarillo || 0)}`,
      `🟢 ${nf.format(sem.verde || 0)}`,
    ];
    if (sem.sin_dato) desglose.push(`⚪ ${nf.format(sem.sin_dato)} sin dato`);
    el.kpiSemaforoFoot.textContent = desglose.join(' · ');

    el.kpiBrotes.textContent = nf.format(casos.brotes ?? 0);
    const seguimientos = casos.seguimientos ?? 0;
    el.kpiBrotesFoot.textContent = `${nf.format(casos.con_tecnico ?? 0)} casos con técnico · ${nf.format(seguimientos)} seguimiento${seguimientos === 1 ? '' : 's'}`;

    const cargaMedia = tech.carga_media;
    el.kpiTecnicos.textContent = nf.format(tech.disponibles ?? 0);
    el.kpiTecnicosFoot.textContent = `${nf.format(tech.asignados ?? 0)} con casos · ${nf.format(tech.total ?? 0)} en la junta${
      cargaMedia != null ? ` · carga media ${n1.format(cargaMedia)}` : ''
    }`;

    const lat = eq.latencia_mediana_min;
    el.kpiLatencia.textContent = lat != null ? n1.format(lat) : '—';
    el.kpiLatenciaUnit.textContent = lat != null ? 'min' : '';
    el.kpiLatenciaFoot.textContent = lat != null
      ? 'mediana de respuesta del servidor'
      : (eq.ultima_actividad ? `Última actividad ${fecha(eq.ultima_actividad)}` : 'Sin datos del servidor');
  }

  // ---------------------------------------------------------------------
  // Mapa
  // ---------------------------------------------------------------------
  const mapCtx = {
    map: null,
    capas: {},
    tecnicosLayer: null,
    markers: new Map(),
    listo: false,
    firma: null,
    firmaTecnicos: null,
  };

  function initMapa() {
    const cont = $('#map');
    if (!cont || mapCtx.listo) return;
    if (typeof window.L === 'undefined') {
      $('#map-fallback').hidden = false;
      return;
    }
    const map = window.L.map(cont, { scrollWheelZoom: true, preferCanvas: true, zoomSnap: 0.5 });
    map.setView([19.48, -98.86], 11);
    const atribucion = 'Tiles &copy; <a href="https://www.esri.com/" target="_blank" rel="noopener">Esri</a> &mdash; Esri, DeLorme, NAVTEQ';
    map.createPane('etiquetas');
    map.getPane('etiquetas').style.zIndex = 350;
    window.L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
      maxZoom: 19,
      maxNativeZoom: 16,
      attribution: atribucion,
    }).addTo(map);
    window.L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}', {
      maxZoom: 19,
      maxNativeZoom: 16,
      pane: 'etiquetas',
      attribution: atribucion,
    }).addTo(map);

    for (const estado of Object.keys(ESTADOS)) {
      mapCtx.capas[estado] = window.L.layerGroup().addTo(map);
    }
    mapCtx.tecnicosLayer = window.L.layerGroup().addTo(map);

    map.on('popupopen', (e) => {
      const popupEl = e.popup.getElement();
      if (!popupEl) return;
      const btn = popupEl.querySelector('[data-filtrar-parcela]');
      if (btn) {
        btn.addEventListener('click', () => {
          filtrarPorParcela(btn.getAttribute('data-filtrar-parcela'));
          map.closePopup();
        });
      }
    });

    mapCtx.map = map;
    mapCtx.listo = true;

    // Si ya había datos, pintarlos
    if (state.parcelas.length) renderMapa();
  }

  function colorEstado(estado) {
    return (ESTADOS[estado] || ESTADOS.sin_clasificar).color;
  }

  function radioParcela(ha) {
    const area = Number(ha) || 0;
    return Math.max(5, Math.min(15, 4.6 + Math.sqrt(area) * 1.9));
  }

  function badgeSemaforo(semaforo, prioridad) {
    const info = SEMAFORO[semaforo];
    if (!info) return '<span class="cell-sub">—</span>';
    const extra = prioridad != null ? ` · ${nf.format(prioridad)}` : '';
    return `<span class="badge ${info.badge}" title="Prioridad ${prioridad != null ? `${prioridad}/100` : 'sin dato'}"><span class="dot" style="background:${info.color}"></span>${info.label}${extra}</span>`;
  }

  function badgeBrote(brote) {
    return brote
      ? '<span class="badge badge-brote">🦠 Brote</span>'
      : '<span class="cell-sub">—</span>';
  }

  function popupParcela(p) {
    const estado = ESTADOS[p.estado] || ESTADOS.sin_clasificar;
    const plagas = (p.plagas || []).filter(Boolean);
    return `
      <div class="popup-title">${esc(p.nombre)} <span class="cell-sub">${esc(p.id)}</span></div>
      <div class="popup-meta">${esc(p.cultivo)}${p.etapa ? ` · ${esc(p.etapa)}` : ''}</div>
      <div class="popup-row"><span>Productor</span><span>${esc(p.productor_nombre || '—')}</span></div>
      <div class="popup-row"><span>Localidad</span><span>${esc(p.localidad || '—')}, ${esc(p.municipio || '')}</span></div>
      <div class="popup-row"><span>Superficie</span><span>${p.superficie_ha != null ? `${n1.format(p.superficie_ha)} ha` : '—'}</span></div>
      <div class="popup-row"><span>Reportes</span><span>${nf.format(p.reportes || 0)}</span></div>
      <div class="popup-row"><span>Semáforo</span><span>${p.semaforo ? badgeSemaforo(p.semaforo, p.prioridad) : '—'}</span></div>
      <div class="popup-row"><span>Técnico</span><span>${esc(p.tecnico_nombre || p.tecnico_id || 'Sin asignar')}</span></div>
      <div class="popup-badges">
        <span class="badge ${estado.badge}"><span class="dot" style="background:${estado.color}"></span>${estado.label}</span>
        ${p.brote ? badgeBrote(true) : ''}
      </div>
      ${plagas.length ? `<div class="cell-sub">Plaga: ${esc(plagas.join(', '))}</div>` : '<div class="cell-sub">Sin plaga detectada</div>'}
      <button class="popup-action" type="button" data-filtrar-parcela="${esc(p.id)}">Ver casos de esta parcela</button>
    `;
  }

  function iconoTecnico(t) {
    const clase = t.especialidad === 'fitopatologia' ? 'is-fito' : 'is-ento';
    return window.L.divIcon({
      className: 'tech-marker',
      html: `<span class="tech-marker-dot ${clase}" aria-hidden="true">T</span>`,
      iconSize: [24, 24],
      iconAnchor: [12, 12],
      popupAnchor: [0, -14],
    });
  }

  function popupTecnico(t) {
    const especialidad = t.especialidad === 'fitopatologia' ? 'Fitopatología' : t.especialidad === 'entomologia' ? 'Entomología' : (t.especialidad || 'Sin especialidad');
    const estado = t.disponible ? 'Disponible' : 'Carga alta';
    return `
      <div class="popup-title">👷 ${esc(t.nombre || t.id)} <span class="cell-sub">${esc(t.id)}</span></div>
      <div class="popup-meta">${esc(especialidad)} · ${esc(estado)}</div>
      <div class="popup-row"><span>Base</span><span>${esc(t.base || '—')}</span></div>
      <div class="popup-row"><span>Carga</span><span>${t.carga != null ? `${nf.format(t.carga)}${t.tope != null ? ` / ${nf.format(t.tope)}` : ''}` : '—'}</span></div>
      <div class="popup-row"><span>Casos asignados</span><span>${nf.format(t.casos || 0)}</span></div>
      <div class="popup-row"><span>Brotes</span><span>${nf.format(t.brotes || 0)}</span></div>
      <div class="popup-badges">
        <span class="badge ${t.disponible ? 'badge-sin_plaga' : 'badge-plaga'}">${t.disponible ? '✅ Disponible' : '⚠️ Carga alta'}</span>
      </div>
    `;
  }

  function renderMapa() {
    if (!mapCtx.listo) return;

    const municipios = new Set(state.parcelas.map((p) => p.municipio).filter(Boolean));
    el.mapSub.textContent = `${nf.format(state.parcelas.length)} parcelas · ${nf.format(state.tecnicos.length)} técnicos · ${municipios.size} municipios · ${nf.format((state.resumen && state.resumen.totales.productores) || 0)} productores`;

    const bounds = window.L.latLngBounds();
    let hay = false;
    for (const p of state.parcelas) {
      if (p.lat == null || p.lon == null) continue;
      bounds.extend([p.lat, p.lon]);
      hay = true;
    }
    for (const t of state.tecnicos) {
      if (t.lat == null || t.lon == null) continue;
      bounds.extend([t.lat, t.lon]);
    }

    // Evita repintar si nada cambió (así no se cierran popups abiertos cada 30 s).
    const firmaParcelas = state.parcelas
      .map((p) => `${p.id}:${p.estado}:${p.reportes}:${p.semaforo}:${p.brote}:${p.tecnico_id}`)
      .join('|');
    const { capas } = mapCtx;

    if (firmaParcelas !== mapCtx.firma) {
      mapCtx.firma = firmaParcelas;
      for (const estado of Object.keys(capas)) capas[estado].clearLayers();
      mapCtx.markers.clear();

      for (const p of state.parcelas) {
        if (p.lat == null || p.lon == null) continue;
        const estado = ESTADOS[p.estado] ? p.estado : 'sin_clasificar';
        const marker = window.L.circleMarker([p.lat, p.lon], {
          radius: radioParcela(p.superficie_ha),
          color: '#ffffff',
          weight: 1.2,
          opacity: 0.9,
          fillColor: colorEstado(estado),
          fillOpacity: estado === 'sin_clasificar' ? 0.5 : 0.82,
        });
        marker.bindPopup(popupParcela(p), { maxWidth: 300, closeButton: true });
        marker.bindTooltip(`${p.nombre} · ${p.cultivo}`, { direction: 'top', offset: [0, -6], opacity: 0.9 });
        marker.addTo(capas[estado]);
        mapCtx.markers.set(p.id, marker);
      }
    }

    const firmaTecnicos = state.tecnicos
      .map((t) => `${t.id}:${t.carga}:${t.casos}:${t.brotes}:${t.disponible}`)
      .join('|');
    if (firmaTecnicos !== mapCtx.firmaTecnicos) {
      mapCtx.firmaTecnicos = firmaTecnicos;
      if (mapCtx.tecnicosLayer) mapCtx.tecnicosLayer.clearLayers();

      for (const t of state.tecnicos) {
        if (t.lat == null || t.lon == null) continue;
        const marker = window.L.marker([t.lat, t.lon], {
          icon: iconoTecnico(t),
          title: `Técnico ${t.nombre || t.id}`,
          alt: `Técnico ${t.nombre || t.id}`,
          keyboard: true,
        });
        marker.bindPopup(popupTecnico(t), { maxWidth: 280, closeButton: true });
        marker.bindTooltip(`👷 ${t.nombre || t.id} · carga ${t.carga ?? '—'}`, {
          direction: 'top',
          offset: [0, -12],
          opacity: 0.95,
        });
        marker.addTo(mapCtx.tecnicosLayer);
      }
    }

    aplicarCapas();

    if (hay && !mapCtx.encuadrado) {
      mapCtx.map.fitBounds(bounds.pad(0.06), { maxZoom: 12 });
      mapCtx.encuadrado = true;
    }
  }

  function aplicarCapas() {
    if (!mapCtx.listo) return;
    for (const estado of Object.keys(ESTADOS)) {
      const capa = mapCtx.capas[estado];
      if (!capa) continue;
      const activa = state.capas.has(estado);
      const enMapa = mapCtx.map.hasLayer(capa);
      if (activa && !enMapa) capa.addTo(mapCtx.map);
      if (!activa && enMapa) mapCtx.map.removeLayer(capa);
    }

    const tecnicosLayer = mapCtx.tecnicosLayer;
    if (tecnicosLayer) {
      const enMapa = mapCtx.map.hasLayer(tecnicosLayer);
      if (state.tecnicosVisible && !enMapa) tecnicosLayer.addTo(mapCtx.map);
      if (!state.tecnicosVisible && enMapa) mapCtx.map.removeLayer(tecnicosLayer);
    }
  }

  function enfocarParcela(parcelaId) {
    const p = state.parcelas.find((x) => x.id === parcelaId);
    if (!p || !mapCtx.listo) return false;
    const marker = mapCtx.markers.get(parcelaId);
    mapCtx.map.setView([p.lat, p.lon], Math.max(mapCtx.map.getZoom(), 14), { animate: true });
    if (marker) marker.openPopup();
    return true;
  }

  function filtrarPorParcela(parcelaId) {
    state.filtros = { tipo: '', urgencia: '', semaforo: '', brote: '', cultivo: '', q: parcelaId };
    sincronizarControles();
    renderTabla();
    const total = filtrarReportes().length;
    $('#monitor').scrollIntoView({ behavior: 'smooth', block: 'start' });
    toast(`Mostrando ${total} caso${total === 1 ? '' : 's'} de la parcela ${parcelaId}`);
  }

  // ---------------------------------------------------------------------
  // Donut y top parcelas
  // ---------------------------------------------------------------------
  function renderDonut() {
    const r = state.resumen;
    if (!r) return;
    const counts = r.parcelas_estado || {};
    const total = Object.values(counts).reduce((a, b) => a + b, 0);
    el.donutTotal.textContent = nf.format(total);

    const C = 2 * Math.PI * 54;
    let offset = 0;
    const partes = [];
    for (const [estado, info] of Object.entries(ESTADOS)) {
      const value = counts[estado] || 0;
      if (!value) continue;
      const len = (value / total) * C;
      partes.push(
        `<circle class="donut-seg" cx="70" cy="70" r="54" stroke="${info.color}" ` +
        `stroke-dasharray="${Math.max(len - 2, 0.5)} ${C}" stroke-dashoffset="${-offset}">` +
        `<title>${info.label}: ${value}</title></circle>`,
      );
      offset += len;
    }
    el.donutSegments.innerHTML = partes.join('');

    el.estadoList.innerHTML = Object.entries(ESTADOS)
      .map(([estado, info]) => {
        const value = counts[estado] || 0;
        const pct = total ? Math.round((value / total) * 100) : 0;
        return `<li>
          <span class="dot" style="background:${info.color}"></span>
          <span class="lg-label">${info.label}</span>
          <span class="lg-value">${nf.format(value)}</span>
          <span class="lg-pct">${pct}%</span>
        </li>`;
      })
      .join('');

    renderSemaforoPanel();
  }

  function renderSemaforoPanel() {
    if (!el.semaforoList) return;
    const sem = (state.resumen && state.resumen.casos && state.resumen.casos.semaforo) || {};
    const filas = Object.entries(SEMAFORO).map(([id, info]) => ({ id, info, value: sem[id] || 0 }));
    if (sem.sin_dato) filas.push({ id: 'sin_dato', info: { label: 'Sin dato', color: '#8fa99a' }, value: sem.sin_dato });
    const total = filas.reduce((s, f) => s + f.value, 0);
    el.semaforoList.innerHTML = filas
      .map(({ info, value }) => {
        const pct = total ? Math.round((value / total) * 100) : 0;
        return `<li>
          <span class="dot" style="background:${info.color}"></span>
          <span class="lg-label">${info.label}</span>
          <span class="lg-value">${nf.format(value)}</span>
          <span class="lg-pct">${pct}%</span>
        </li>`;
      })
      .join('');
  }

  function renderTopParcelas() {
    const top = (state.resumen && state.resumen.top_parcelas) || [];
    if (!top.length) {
      el.topParcelas.innerHTML = '<li class="empty">Sin reportes registrados</li>';
      return;
    }
    el.topParcelas.innerHTML = top
      .map((p) => `
        <li data-parcela="${esc(p.id)}" tabindex="0">
          <div>
            <span class="rk-name">${esc(p.nombre)}</span>
            <span class="rk-sub">${esc(p.cultivo)} · ${esc(p.localidad || '')}</span>
          </div>
          <span class="rk-count ${p.urgentes ? 'is-urgent' : ''}" title="${p.reportes} reportes · ${p.urgentes} urgentes${p.semaforo ? ` · semáforo ${SEMAFORO[p.semaforo].label}` : ''}${p.brote ? ' · brote activo' : ''}">${nf.format(p.reportes)}</span>
        </li>`)
      .join('');

    $$('li[data-parcela]', el.topParcelas).forEach((li) => {
      const activar = () => {
        const id = li.getAttribute('data-parcela');
        enfocarParcela(id);
        $('#map').scrollIntoView({ behavior: 'smooth', block: 'center' });
      };
      li.addEventListener('click', activar);
      li.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          activar();
        }
      });
    });
  }

  // ---------------------------------------------------------------------
  // Gráficas de barras
  // ---------------------------------------------------------------------
  function renderCharts() {
    const r = state.resumen;
    if (!r) return;

    // Plagas
    const plagas = (r.por_plaga || []).slice(0, 9);
    const totalCasos = (r.casos && r.casos.es_plaga) || 0;
    el.plagasSub.textContent = `${nf.format(totalCasos)} casos con plaga · ${plagas.length} diagnósticos`;
    if (!plagas.length) {
      el.chartPlagas.innerHTML = '<p class="empty">Aún no hay plagas clasificadas.</p>';
    } else {
      const max = Math.max(...plagas.map((p) => p.casos), 1);
      el.chartPlagas.innerHTML = plagas
        .map((p) => {
          const clase = p.urgente_regla ? 'is-urgent' : p.id === 'desconocida' ? 'is-unknown' : '';
          const tooltip = `${p.casos} casos · ${p.urgentes} urgentes · ${p.brotes || 0} brotes · ${p.parcelas} parcelas`;
          return `<div class="bar-row" title="${esc(tooltip)}">
            <span class="bar-label">${esc(p.nombre)}</span>
            <span class="bar-track"><span class="bar-fill ${clase}" data-w="${((p.casos / max) * 100).toFixed(1)}"></span></span>
            <span class="bar-value">${nf.format(p.casos)}</span>
          </div>`;
        })
        .join('');
      animarBarras(el.chartPlagas);
    }

    // Cultivos
    const cultivos = (r.por_cultivo || []).filter((c) => c.reportes > 0).slice(0, 9);
    const totalReportes = (r.totales && r.totales.reportes) || 0;
    el.cultivosSub.textContent = `${nf.format(totalReportes)} reportes en ${cultivos.length} cultivos`;
    if (!cultivos.length) {
      el.chartCultivos.innerHTML = '<p class="empty">Aún no hay reportes por cultivo.</p>';
      return;
    }
    const maxC = Math.max(...cultivos.map((c) => c.plagas || 0), 1);
    el.chartCultivos.innerHTML = cultivos
      .map((c) => {
        const valor = c.plagas || 0;
        const tooltip = `${c.cultivo}: ${c.reportes} reportes · ${c.plagas} con plaga · ${c.urgentes} urgentes · ${c.parcelas} parcelas`;
        return `<div class="bar-row" title="${esc(tooltip)}">
          <span class="bar-label">${esc(c.cultivo)}</span>
          <span class="bar-track"><span class="bar-fill ${c.urgentes ? 'is-urgent' : ''}" data-w="${((valor / maxC) * 100).toFixed(1)}"></span></span>
          <span class="bar-value">${nf.format(valor)}</span>
        </div>`;
      })
      .join('');
    animarBarras(el.chartCultivos);
  }

  function animarBarras(contenedor) {
    requestAnimationFrame(() => {
      $$('.bar-fill', contenedor).forEach((bar) => {
        bar.style.width = `${bar.dataset.w}%`;
      });
    });
  }

  // ---------------------------------------------------------------------
  // Tabla / monitor de casos
  // ---------------------------------------------------------------------
  function filtrarReportes() {
    const { tipo, urgencia, semaforo, brote, cultivo, q } = state.filtros;
    const term = q.trim().toLowerCase();
    return state.reportes.filter((r) => {
      if (tipo && r.tipo !== tipo) return false;
      if (urgencia && r.estado !== urgencia) return false;
      if (semaforo === 'sin_dato') {
        if (!(r.es_plaga && !r.semaforo)) return false;
      } else if (semaforo && r.semaforo !== semaforo) {
        return false;
      }
      if (brote === '1' && !r.brote) return false;
      if (brote === '0' && r.brote) return false;
      if (cultivo && r.cultivo !== cultivo) return false;
      if (term) {
        const blob = [
          r.id, r.texto, r.productor_nombre, r.productor_id, r.parcela_id, r.parcela_nombre,
          r.cultivo, r.plaga_nombre, r.localidad, r.municipio, r.semaforo,
          r.tecnico_id, r.tecnico_nombre,
        ].join(' ').toLowerCase();
        if (!blob.includes(term)) return false;
      }
      return true;
    });
  }

  function ordenarReportes(lista) {
    const { key, dir } = state.orden;
    const factor = dir === 'asc' ? 1 : -1;
    const peso = (r) => {
      switch (key) {
        case 'id': return r.id;
        case 'recibido': return r.recibido || '';
        case 'productor': return `${r.productor_nombre || ''} ${r.parcela_nombre || ''}`.toLowerCase();
        case 'cultivo': return (r.cultivo || '').toLowerCase();
        case 'plaga': return (r.plaga_nombre || 'zzz').toLowerCase();
        case 'semaforo': return r.semaforo ? SEMAFORO[r.semaforo].orden : 4;
        case 'tecnico': return (r.tecnico_nombre || r.tecnico_id || 'zzz').toLowerCase();
        case 'brote': return r.brote ? 0 : 1;
        case 'estado': return (ESTADOS[r.estado] || ESTADOS.sin_clasificar).prioridad;
        default: return '';
      }
    };
    return [...lista].sort((a, b) => {
      const va = peso(a);
      const vb = peso(b);
      if (va < vb) return -1 * factor;
      if (va > vb) return 1 * factor;
      return String(a.id).localeCompare(String(b.id));
    });
  }

  function badgeEstado(estado) {
    const info = ESTADOS[estado] || ESTADOS.sin_clasificar;
    return `<span class="badge ${info.badge}"><span class="dot" style="background:${info.color}"></span>${info.label}</span>`;
  }

  function renderTabla() {
    const filtrados = ordenarReportes(filtrarReportes());
    const total = state.reportes.length;
    el.casosSub.textContent = `${nf.format(filtrados.length)} de ${nf.format(total)} reportes · ordenados por ${
      {
        id: 'reporte',
        recibido: 'fecha',
        productor: 'productor',
        cultivo: 'cultivo',
        plaga: 'diagnóstico',
        semaforo: 'semáforo',
        tecnico: 'técnico',
        brote: 'brote',
        estado: 'prioridad',
      }[state.orden.key]
    }`;

    if (!state.reportes.length) {
      el.tbody.innerHTML = '<tr><td colspan="9" class="empty">Sin reportes disponibles.</td></tr>';
      return;
    }
    if (!filtrados.length) {
      el.tbody.innerHTML = '<tr><td colspan="9" class="empty">Ningún caso coincide con los filtros.</td></tr>';
      return;
    }

    const frag = document.createDocumentFragment();
    for (const r of filtrados) {
      const tr = document.createElement('tr');
      tr.tabIndex = 0;
      tr.dataset.reporte = r.id;
      if (r.estado === 'urgente') tr.classList.add('is-urgente');
      const tipoLabel = TIPO_LABEL[r.tipo] || r.tipo || '—';
      const icono = TIPO_ICON[r.tipo] || TIPO_ICON.texto;
      const diag = r.plaga_nombre
        ? `<span class="badge ${r.estado === 'urgente' ? 'badge-urgente' : 'badge-plaga'}">${esc(r.plaga_nombre)}</span>`
        : r.clasificado
          ? '<span class="badge badge-sin_plaga">No es plaga</span>'
          : '<span class="badge badge-sin_clasificar">Pendiente</span>';
      const semaforoCell = r.semaforo
        ? badgeSemaforo(r.semaforo, r.prioridad)
        : r.seguimiento
          ? '<span class="badge badge-neutral">Seguimiento</span>'
          : '<span class="cell-sub">—</span>';
      const tecnicoCell = r.tecnico_id
        ? `<span class="cell-main">${esc(r.tecnico_nombre || r.tecnico_id)}</span>${
            r.tecnico_nombre ? `<span class="cell-sub">${esc(r.tecnico_id)}</span>` : ''
          }`
        : `<span class="cell-sub">${r.es_plaga && !r.seguimiento ? 'Sin asignar' : '—'}</span>`;
      tr.innerHTML = `
        <td><span class="cell-id">${esc(r.id)}</span></td>
        <td class="cell-date">${esc(fecha(r.recibido))}</td>
        <td>
          <span class="cell-main">${esc(r.productor_nombre || r.productor_id || '—')}</span>
          <span class="cell-sub">${esc(r.parcela_id || 'sin parcela')} · ${esc(r.parcela_nombre || '—')}</span>
        </td>
        <td>
          <span class="cell-main">${esc(r.cultivo || '—')}</span>
          <span class="cell-sub">${esc(r.etapa || '')}</span>
        </td>
        <td>${diag}<span class="cell-sub"><span class="tipo">${icono}</span>${esc(tipoLabel)}</span></td>
        <td>${semaforoCell}</td>
        <td>${tecnicoCell}</td>
        <td>${badgeBrote(r.brote)}</td>
        <td>${badgeEstado(r.estado)}</td>
      `;
      tr.addEventListener('click', () => abrirDetalle(r));
      tr.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          abrirDetalle(r);
        }
      });
      frag.appendChild(tr);
    }
    el.tbody.replaceChildren(frag);
  }

  function sincronizarControles() {
    $$('.seg', el.filtroTipo).forEach((b) => b.classList.toggle('is-on', b.dataset.tipo === state.filtros.tipo));
    el.filtroUrgencia.value = state.filtros.urgencia;
    el.filtroSemaforo.value = state.filtros.semaforo;
    el.filtroBrote.value = state.filtros.brote;
    el.filtroCultivo.value = state.filtros.cultivo;
    el.q.value = state.filtros.q;
  }

  function poblarCultivos() {
    const cultivos = [...new Set(state.parcelas.map((p) => p.cultivo).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'es'));
    const valor = state.filtros.cultivo;
    el.filtroCultivo.innerHTML = '<option value="">Todos los cultivos</option>' +
      cultivos.map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join('');
    el.filtroCultivo.value = cultivos.includes(valor) ? valor : '';
  }

  // ---------------------------------------------------------------------
  // Detalle (modal)
  // ---------------------------------------------------------------------
  let ultimoFoco = null;

  function abrirDetalle(r) {
    if (!el.modal) return;
    ultimoFoco = document.activeElement;
    const estado = ESTADOS[r.estado] || ESTADOS.sin_clasificar;
    el.modalEyebrow.textContent = `Reporte ${r.id} · ${TIPO_LABEL[r.tipo] || r.tipo || 'sin tipo'}`;
    el.modalTitle.textContent = r.parcela_nombre || 'Caso sin parcela';

    const media = [];
    if (r.foto_url) {
      const archivo = String(r.foto_url).split('/').pop();
      media.push(`<figure class="modal-media">
        <img src="/api/media/${encodeURIComponent(archivo)}" alt="Foto del reporte ${esc(r.id)}" loading="lazy" data-media-img>
        <figcaption>Fotografía enviada por el productor</figcaption>
      </figure>`);
    }
    if (r.audio_url) {
      const archivo = String(r.audio_url).split('/').pop();
      media.push(`<figure class="modal-media">
        <audio controls preload="none" src="/api/media/${encodeURIComponent(archivo)}"></audio>
        <figcaption>Nota de voz${r.duracion_s ? ` · ${n1.format(r.duracion_s)} s` : ''}</figcaption>
      </figure>`);
    }

    const texto = r.texto
      ? `<blockquote class="quote">“${esc(r.texto)}”</blockquote>`
      : r.tipo === 'voz'
        ? `<blockquote class="quote is-empty">Nota de voz${r.duracion_s ? ` de ${n1.format(r.duracion_s)} s` : ''}. Escucha el audio para revisar el caso.</blockquote>`
        : '<blockquote class="quote is-empty">Este reporte no incluye texto.</blockquote>';

    el.modalBody.innerHTML = `
      <div class="popup-badges">
        ${badgeEstado(r.estado)}
        ${r.semaforo ? badgeSemaforo(r.semaforo, r.prioridad) : ''}
        ${r.brote ? badgeBrote(true) : ''}
        ${r.seguimiento ? '<span class="badge badge-neutral">Seguimiento</span>' : ''}
        ${r.plaga_nombre ? `<span class="badge badge-neutral">${esc(r.plaga_nombre)}</span>` : ''}
        ${r.tecnico_id ? `<span class="badge badge-neutral">👷 ${esc(r.tecnico_nombre || r.tecnico_id)}</span>` : ''}
        <span class="badge badge-neutral">${esc(TIPO_LABEL[r.tipo] || r.tipo || '—')}</span>
      </div>
      ${texto}
      ${media.join('')}
      <dl class="detail-grid">
        <div><dt>Productor</dt><dd>${esc(r.productor_nombre || r.productor_id || '—')}</dd></div>
        <div><dt>Parcela</dt><dd>${esc(r.parcela_id || '—')} · ${esc(r.parcela_nombre || '—')}</dd></div>
        <div><dt>Cultivo / etapa</dt><dd>${esc(r.cultivo || '—')}${r.etapa ? ` · ${esc(r.etapa)}` : ''}</dd></div>
        <div><dt>Localidad</dt><dd>${esc(r.localidad || '—')}, ${esc(r.municipio || '')}</dd></div>
        <div><dt>Semáforo</dt><dd>${r.semaforo ? `${SEMAFORO[r.semaforo].emoji} ${SEMAFORO[r.semaforo].label}` : '—'}</dd></div>
        <div><dt>Prioridad / afectación</dt><dd>${r.prioridad != null ? `${nf.format(r.prioridad)}/100` : '—'}${r.pct != null ? ` · ${n1.format(r.pct)} %` : ''}</dd></div>
        <div><dt>Técnico asignado</dt><dd>${r.tecnico_id ? `${esc(r.tecnico_nombre || r.tecnico_id)}${r.tecnico_nombre ? ` · ${esc(r.tecnico_id)}` : ''}` : (r.es_plaga && !r.seguimiento ? 'Sin asignar' : '—')}</dd></div>
        <div><dt>Brote</dt><dd>${r.seguimiento ? 'No aplica (seguimiento)' : r.brote ? '🦠 Sí, brote activo' : 'No'}</dd></div>
        ${r.seguimiento ? `<div><dt>Seguimiento de</dt><dd>${esc(r.seguimiento_de || 'caso previo')}</dd></div>` : ''}
        <div><dt>Recibido</dt><dd>${esc(fecha(r.recibido))}</dd></div>
        <div><dt>Coordenadas</dt><dd>${r.lat != null && r.lon != null ? `${Number(r.lat).toFixed(5)}, ${Number(r.lon).toFixed(5)}` : '—'}</dd></div>
      </dl>
      <div class="modal-actions">
        <button class="btn btn-ghost" type="button" data-accion="mapa">Ver en el mapa</button>
        <button class="btn btn-ghost" type="button" data-accion="parcela">Filtrar casos de la parcela</button>
      </div>
    `;

    const foto = $('[data-media-img]', el.modalBody);
    if (foto) {
      foto.addEventListener('error', () => {
        const figura = foto.closest('figure');
        if (figura) figura.innerHTML = '<p class="empty">La fotografía no está disponible.</p>';
      });
    }

    const accionMapa = $('[data-accion="mapa"]', el.modalBody);    const accionParcela = $('[data-accion="parcela"]', el.modalBody);
    if (accionMapa) {
      accionMapa.addEventListener('click', () => {
        cerrarModal();
        if (r.parcela_id) enfocarParcela(r.parcela_id);
        $('#map').scrollIntoView({ behavior: 'smooth', block: 'center' });
      });
    }
    if (accionParcela && r.parcela_id) {
      accionParcela.addEventListener('click', () => {
        cerrarModal();
        filtrarPorParcela(r.parcela_id);
      });
    } else if (accionParcela) {
      accionParcela.remove();
    }

    el.modal.hidden = false;
    document.body.style.overflow = 'hidden';
    el.modalClose.focus();
  }

  function cerrarModal() {
    if (!el.modal || el.modal.hidden) return;
    el.modal.hidden = true;
    document.body.style.overflow = '';
    if (ultimoFoco && typeof ultimoFoco.focus === 'function') ultimoFoco.focus();
  }

  // ---------------------------------------------------------------------
  // Banner / toast
  // ---------------------------------------------------------------------
  function mostrarBanner(mensaje) {
    el.bannerText.textContent = mensaje;
    el.banner.hidden = false;
  }
  function ocultarBanner() {
    el.banner.hidden = true;
  }
  let toastTimer = null;
  function toast(mensaje) {
    let nodo = $('.toast');
    if (!nodo) {
      nodo = document.createElement('div');
      nodo.className = 'toast';
      nodo.setAttribute('role', 'status');
      document.body.appendChild(nodo);
    }
    nodo.textContent = mensaje;
    nodo.classList.add('is-visible');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => nodo.classList.remove('is-visible'), 3200);
  }

  function renderFooter() {
    const f = (state.resumen && state.resumen.fuentes) || {};
    const usaCache = Object.values(f).some((v) => v === 'cache' || v === 'memoria');
    el.footerFuente.textContent = usaCache
      ? 'Fuente: respaldo local (cache) — API no disponible'
      : 'Fuente: API del hackathon';
    el.footerHora.textContent = `Actualizado ${fmtHora.format(new Date())} h (America/Mexico_City)`;
  }

  // ---------------------------------------------------------------------
  // Eventos
  // ---------------------------------------------------------------------
  function bindEventos() {
    el.refreshBtn.addEventListener('click', () => cargar());
    el.bannerRetry.addEventListener('click', () => cargar());

    el.filtroTipo.addEventListener('click', (e) => {
      const btn = e.target.closest('.seg');
      if (!btn) return;
      state.filtros.tipo = btn.dataset.tipo || '';
      sincronizarControles();
      renderTabla();
    });

    el.filtroUrgencia.addEventListener('change', (e) => {
      state.filtros.urgencia = e.target.value;
      renderTabla();
    });
    el.filtroSemaforo.addEventListener('change', (e) => {
      state.filtros.semaforo = e.target.value;
      renderTabla();
    });
    el.filtroBrote.addEventListener('change', (e) => {
      state.filtros.brote = e.target.value;
      renderTabla();
    });
    el.filtroCultivo.addEventListener('change', (e) => {
      state.filtros.cultivo = e.target.value;
      renderTabla();
    });

    let debounce;
    el.q.addEventListener('input', (e) => {
      clearTimeout(debounce);
      const valor = e.target.value;
      debounce = setTimeout(() => {
        state.filtros.q = valor;
        renderTabla();
      }, 180);
    });

    el.limpiar.addEventListener('click', () => {
      state.filtros = { tipo: '', urgencia: '', semaforo: '', brote: '', cultivo: '', q: '' };
      sincronizarControles();
      renderTabla();
    });

    const ordenarPor = (th) => {
      const key = th.dataset.sort;
      if (!key) return;
      if (state.orden.key === key) state.orden.dir = state.orden.dir === 'asc' ? 'desc' : 'asc';
      else state.orden = { key, dir: key === 'recibido' ? 'desc' : 'asc' };
      $$('th[data-sort]', el.tabla).forEach((n) => {
        n.setAttribute('aria-sort', n.dataset.sort === state.orden.key ? (state.orden.dir === 'asc' ? 'ascending' : 'descending') : 'none');
      });
      renderTabla();
    };

    const thead = el.tabla.querySelector('thead');
    thead.addEventListener('click', (e) => {
      const th = e.target.closest('th[data-sort]');
      if (th) ordenarPor(th);
    });
    thead.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      const th = e.target.closest('th[data-sort]');
      if (!th) return;
      e.preventDefault();
      ordenarPor(th);
    });

    el.mapToggles.addEventListener('click', (e) => {
      const btn = e.target.closest('.toggle');
      if (!btn) return;
      if (btn.dataset.capa === 'tecnicos') {
        state.tecnicosVisible = !state.tecnicosVisible;
        btn.classList.toggle('is-on', state.tecnicosVisible);
        aplicarCapas();
        return;
      }
      const estado = btn.dataset.estado;
      if (!estado) return;
      if (state.capas.has(estado)) state.capas.delete(estado);
      else state.capas.add(estado);
      btn.classList.toggle('is-on', state.capas.has(estado));
      aplicarCapas();
    });

    el.modalClose.addEventListener('click', cerrarModal);
    el.modal.addEventListener('click', (e) => {
      if (e.target === el.modal) cerrarModal();
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') cerrarModal();
    });

    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) cargar({ silencioso: true });
    });
  }

  // ---------------------------------------------------------------------
  // Arranque
  // ---------------------------------------------------------------------
  function iniciar() {
    bindEventos();
    sincronizarControles();
    initMapa();
    cargar();
    setInterval(() => {
      if (!document.hidden) cargar({ silencioso: true });
    }, REFRESH_MS);
    setInterval(actualizarReloj, 1000);
    actualizarReloj();
    actualizarSaludo();
    setInterval(actualizarSaludo, 60000);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', iniciar);
  else iniciar();
})();
