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

  const REFRESH_MS = 30000;

  const ESTADOS = {
    urgente: { label: 'Urgente', color: '#c22f2f', badge: 'badge-urgente', prioridad: 0 },
    plaga: { label: 'Con plaga', color: '#d99412', badge: 'badge-plaga', prioridad: 1 },
    sin_plaga: { label: 'Sin plaga', color: '#2f9e5f', badge: 'badge-sin_plaga', prioridad: 2 },
    sin_clasificar: { label: 'Sin clasificar', color: '#9aa8a0', badge: 'badge-sin_clasificar', prioridad: 3 },
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
    cargando: false,
    ultimaActualizacion: null,
    error: null,
    modoRespaldo: false,
    filtros: { tipo: '', urgencia: '', cultivo: '', q: '' },
    orden: { key: 'recibido', dir: 'desc' },
    capas: new Set(Object.keys(ESTADOS)),
  };

  // ---------------------------------------------------------------------
  // DOM
  // ---------------------------------------------------------------------
  const el = {
    live: $('#live-indicator'),
    liveText: $('#live-text'),
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
    kpiUrgentes: $('#kpi-urgentes'),
    kpiUrgentesFoot: $('#kpi-urgentes-foot'),
    kpiLatencia: $('#kpi-latencia'),
    kpiLatenciaUnit: $('#kpi-latencia-unit'),
    kpiLatenciaFoot: $('#kpi-latencia-foot'),
    mapSub: $('#map-sub'),
    filtroTipo: $('#filtro-tipo'),    filtroUrgencia: $('#filtro-urgencia'),
    filtroCultivo: $('#filtro-cultivo'),
    q: $('#q'),
    limpiar: $('#limpiar'),
    tbody: $('#tbody-casos'),
    casosSub: $('#casos-sub'),
    tabla: $('#tabla-casos'),
    donutSegments: $('#donut-segments'),
    donutTotal: $('#donut-total'),
    estadoList: $('#estado-list'),
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
      const [resumen, parcelas, reportes] = await Promise.all([
        fetchJSON('/api/resumen', ctrl.signal),
        fetchJSON('/api/parcelas', ctrl.signal),
        fetchJSON('/api/reportes', ctrl.signal),
      ]);
      state.resumen = resumen;
      state.parcelas = parcelas.parcelas || [];
      state.reportes = reportes.reportes || [];
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
        el.tbody.innerHTML = `<tr><td colspan="6" class="empty">No hay datos disponibles. ${esc(mensaje)}</td></tr>`;
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

    el.kpiUrgentes.textContent = nf.format(casos.urgentes ?? 0);
    const pctUrg = casos.es_plaga ? Math.round((casos.urgentes / casos.es_plaga) * 100) : 0;
    el.kpiUrgentesFoot.textContent = `${pctUrg}% de ${nf.format(casos.es_plaga ?? 0)} casos con plaga`;

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
  const mapCtx = { map: null, capas: {}, markers: new Map(), listo: false };

  function initMapa() {
    const cont = $('#map');
    if (!cont || mapCtx.listo) return;
    if (typeof window.L === 'undefined') {
      $('#map-fallback').hidden = false;
      return;
    }
    const map = window.L.map(cont, { scrollWheelZoom: true, preferCanvas: true, zoomSnap: 0.5 });
    map.setView([19.48, -98.86], 11);
    window.L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 18,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>',
    }).addTo(map);

    for (const estado of Object.keys(ESTADOS)) {
      mapCtx.capas[estado] = window.L.layerGroup().addTo(map);
    }

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
      <div class="popup-badges">
        <span class="badge ${estado.badge}"><span class="dot" style="background:${estado.color}"></span>${estado.label}</span>
      </div>
      ${plagas.length ? `<div class="cell-sub">Plaga: ${esc(plagas.join(', '))}</div>` : '<div class="cell-sub">Sin plaga detectada</div>'}
      <button class="popup-action" type="button" data-filtrar-parcela="${esc(p.id)}">Ver casos de esta parcela</button>
    `;
  }

  function renderMapa() {
    if (!mapCtx.listo) return;

    const municipios = new Set(state.parcelas.map((p) => p.municipio).filter(Boolean));
    el.mapSub.textContent = `${nf.format(state.parcelas.length)} parcelas · ${municipios.size} municipios · ${nf.format((state.resumen && state.resumen.totales.productores) || 0)} productores`;

    // Evita repintar si nada cambió (así no se cierran popups abiertos cada 30 s).
    const firma = state.parcelas.map((p) => `${p.id}:${p.estado}:${p.reportes}`).join('|');
    if (firma === mapCtx.firma) return;
    mapCtx.firma = firma;

    const { map, capas } = mapCtx;
    for (const estado of Object.keys(capas)) capas[estado].clearLayers();
    mapCtx.markers.clear();

    const bounds = window.L.latLngBounds();
    let hay = false;

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
      marker.bindPopup(popupParcela(p), { maxWidth: 280, closeButton: true });
      marker.bindTooltip(`${p.nombre} · ${p.cultivo}`, { direction: 'top', offset: [0, -6], opacity: 0.9 });
      marker.addTo(capas[estado]);
      mapCtx.markers.set(p.id, marker);
      bounds.extend([p.lat, p.lon]);
      hay = true;
    }

    aplicarCapas();

    if (hay && !mapCtx.encuadrado) {
      map.fitBounds(bounds.pad(0.06), { maxZoom: 12 });
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
    state.filtros = { tipo: '', urgencia: '', cultivo: '', q: parcelaId };
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
          <span class="rk-count ${p.urgentes ? 'is-urgent' : ''}" title="${p.reportes} reportes · ${p.urgentes} urgentes">${nf.format(p.reportes)}</span>
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
          const tooltip = `${p.casos} casos · ${p.urgentes} urgentes · ${p.parcelas} parcelas`;
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
    const { tipo, urgencia, cultivo, q } = state.filtros;
    const term = q.trim().toLowerCase();
    return state.reportes.filter((r) => {
      if (tipo && r.tipo !== tipo) return false;
      if (urgencia && r.estado !== urgencia) return false;
      if (cultivo && r.cultivo !== cultivo) return false;
      if (term) {
        const blob = [
          r.id, r.texto, r.productor_nombre, r.productor_id, r.parcela_id, r.parcela_nombre,
          r.cultivo, r.plaga_nombre, r.localidad, r.municipio,
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
      { id: 'reporte', recibido: 'fecha', productor: 'productor', cultivo: 'cultivo', plaga: 'diagnóstico', estado: 'prioridad' }[state.orden.key]
    }`;

    if (!state.reportes.length) {
      el.tbody.innerHTML = '<tr><td colspan="6" class="empty">Sin reportes disponibles.</td></tr>';
      return;
    }
    if (!filtrados.length) {
      el.tbody.innerHTML = '<tr><td colspan="6" class="empty">Ningún caso coincide con los filtros.</td></tr>';
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
        ${r.plaga_nombre ? `<span class="badge badge-neutral">${esc(r.plaga_nombre)}</span>` : ''}
        <span class="badge badge-neutral">${esc(TIPO_LABEL[r.tipo] || r.tipo || '—')}</span>
      </div>
      ${texto}
      ${media.join('')}
      <dl class="detail-grid">
        <div><dt>Productor</dt><dd>${esc(r.productor_nombre || r.productor_id || '—')}</dd></div>
        <div><dt>Parcela</dt><dd>${esc(r.parcela_id || '—')} · ${esc(r.parcela_nombre || '—')}</dd></div>
        <div><dt>Cultivo / etapa</dt><dd>${esc(r.cultivo || '—')}${r.etapa ? ` · ${esc(r.etapa)}` : ''}</dd></div>
        <div><dt>Localidad</dt><dd>${esc(r.localidad || '—')}, ${esc(r.municipio || '')}</dd></div>
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
      state.filtros = { tipo: '', urgencia: '', cultivo: '', q: '' };
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
      const estado = btn.dataset.estado;
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
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', iniciar);
  else iniciar();
})();
