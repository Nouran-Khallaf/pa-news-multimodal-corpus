(() => {
  'use strict';

  const DATA = window.PA_DATA;
  if (!DATA) {
    document.body.innerHTML = '<p style="padding:2rem;font-family:sans-serif">Dashboard data failed to load.</p>';
    return;
  }

  const STORAGE_KEY = 'pa-corpus-review-v1';
  const THEME_KEY = 'pa-corpus-theme';
  const REVIEWER_KEY = 'pa-corpus-reviewer';
  const PAGE_SIZE = 24;

  const state = {
    view: 'overview',
    documents: DATA.documents,
    filteredDocuments: DATA.documents.slice(),
    docPage: 0,
    selectedDocumentId: null,
    attachedArticles: new Map(),
    annotations: loadJson(STORAGE_KEY, {}),
    reviewQueue: 'frame',
    reviewFiltered: [],
    reviewIndex: 0,
    nlpTab: 'lexical',
    collocationNode: null,
    collocationRows: [],
    concordanceRows: [],
    keynessRows: [],
    bncReference: DATA.bncReference || null,
  };

  const docMap = new Map(DATA.documents.map(d => [d.id, d]));
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  function storageGet(key, fallback = null) {
    try { const value = localStorage.getItem(key); return value == null ? fallback : value; }
    catch (_) { return fallback; }
  }

  function storageSet(key, value) {
    try { localStorage.setItem(key, value); return true; }
    catch (_) { return false; }
  }

  function loadJson(key, fallback) {
    try { return JSON.parse(storageGet(key, 'null')) || fallback; }
    catch (_) { return fallback; }
  }

  function saveAnnotations() {
    storageSet(STORAGE_KEY, JSON.stringify(state.annotations));
    updateReviewProgress();
  }

  function esc(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
  }

  function fmt(value, digits = 0) {
    const n = Number(value);
    if (!Number.isFinite(n)) return '—';
    return new Intl.NumberFormat('en-GB', { maximumFractionDigits: digits }).format(n);
  }

  function short(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return '—';
    return new Intl.NumberFormat('en-GB', { notation: 'compact', maximumFractionDigits: 1 }).format(n);
  }

  function titleCase(value) {
    return String(value ?? '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  }

  function dateLabel(value) {
    if (!value) return 'Date unavailable';
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return value;
    return new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }).format(d);
  }

  function toast(message) {
    const el = $('#toast');
    el.textContent = message;
    el.classList.add('show');
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => el.classList.remove('show'), 2600);
  }

  function debounce(fn, delay = 180) {
    let timer;
    return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), delay); };
  }

  function svg(tag, attrs = {}) {
    const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, value);
    return el;
  }

  function chartSize(container, minHeight = 260) {
    return { width: Math.max(320, container.clientWidth || 600), height: Math.max(minHeight, container.clientHeight || minHeight) };
  }

  function emptyChart(container, text = 'No data available') {
    container.innerHTML = `<div class="chart-empty">${esc(text)}</div>`;
  }

  function renderHorizontalBars(container, rows, labelKey, valueKey, options = {}) {
    if (!container || !rows?.length) return emptyChart(container);
    const data = rows.slice(0, options.limit || 12);
    const { width, height } = chartSize(container, options.height || 300);
    const margin = { top: 12, right: 46, bottom: 20, left: options.left || 145 };
    const innerW = width - margin.left - margin.right;
    const innerH = height - margin.top - margin.bottom;
    const barGap = 7;
    const barH = Math.max(10, (innerH - barGap * (data.length - 1)) / data.length);
    const max = Math.max(...data.map(d => Number(d[valueKey]) || 0), 1);
    container.innerHTML = '';
    const root = svg('svg', { viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': options.aria || 'Bar chart' });
    data.forEach((row, i) => {
      const y = margin.top + i * (barH + barGap);
      const value = Number(row[valueKey]) || 0;
      const w = innerW * value / max;
      const label = titleCase(row[labelKey]);
      const text = svg('text', { x: margin.left - 9, y: y + barH * .72, 'text-anchor': 'end' });
      text.textContent = label.length > 24 ? label.slice(0, 23) + '…' : label;
      root.appendChild(text);
      const bg = svg('rect', { x: margin.left, y, width: innerW, height: barH, rx: Math.min(5, barH / 2), fill: 'var(--surface-2)' });
      root.appendChild(bg);
      const bar = svg('rect', { x: margin.left, y, width: Math.max(1, w), height: barH, rx: Math.min(5, barH / 2), class: 'bar' });
      const tip = svg('title'); tip.textContent = `${label}: ${options.format ? options.format(value) : fmt(value, 2)}`; bar.appendChild(tip);
      root.appendChild(bar);
      const val = svg('text', { x: Math.min(width - 4, margin.left + w + 6), y: y + barH * .72 });
      val.textContent = options.format ? options.format(value) : short(value);
      root.appendChild(val);
      if (options.onClick) {
        [text, bg, bar, val].forEach(el => {
          el.style.cursor = 'pointer';
          el.addEventListener('click', () => options.onClick(row));
        });
      }
    });
    container.appendChild(root);
  }

  function renderLine(container, rows, xKey, yKey, options = {}) {
    if (!container || !rows?.length) return emptyChart(container);
    const data = rows.filter(r => Number.isFinite(Number(r[yKey])));
    const { width, height } = chartSize(container, options.height || 270);
    const margin = { top: 18, right: 20, bottom: 40, left: 48 };
    const innerW = width - margin.left - margin.right;
    const innerH = height - margin.top - margin.bottom;
    const maxY = Math.max(...data.map(d => Number(d[yKey]) || 0), 1);
    const points = data.map((d, i) => ({
      x: margin.left + (data.length === 1 ? innerW / 2 : i * innerW / (data.length - 1)),
      y: margin.top + innerH - (Number(d[yKey]) || 0) / maxY * innerH,
      row: d,
    }));
    container.innerHTML = '';
    const root = svg('svg', { viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': options.aria || 'Line chart' });
    for (let i = 0; i <= 4; i++) {
      const y = margin.top + innerH * i / 4;
      root.appendChild(svg('line', { x1: margin.left, x2: width - margin.right, y1: y, y2: y, class: 'axis' }));
      const label = svg('text', { x: margin.left - 8, y: y + 4, 'text-anchor': 'end' });
      label.textContent = short(maxY * (1 - i / 4)); root.appendChild(label);
    }
    const linePath = points.map((p, i) => `${i ? 'L' : 'M'} ${p.x} ${p.y}`).join(' ');
    const areaPath = `${linePath} L ${points.at(-1).x} ${margin.top + innerH} L ${points[0].x} ${margin.top + innerH} Z`;
    root.appendChild(svg('path', { d: areaPath, class: 'area' }));
    root.appendChild(svg('path', { d: linePath, class: 'line' }));
    const tickEvery = Math.max(1, Math.ceil(data.length / 9));
    points.forEach((p, i) => {
      const c = svg('circle', { cx: p.x, cy: p.y, r: 3.3, class: 'point' });
      const tip = svg('title'); tip.textContent = `${p.row[xKey]}: ${fmt(p.row[yKey])}`; c.appendChild(tip); root.appendChild(c);
      if (i % tickEvery === 0 || i === data.length - 1) {
        const t = svg('text', { x: p.x, y: height - 12, 'text-anchor': 'middle' });
        t.textContent = String(p.row[xKey]); root.appendChild(t);
      }
    });
    container.appendChild(root);
  }

  function renderDonut(container, rows, labelKey, valueKey) {
    if (!container || !rows?.length) return emptyChart(container);
    const { width, height } = chartSize(container, 320);
    const cx = width * .38, cy = height / 2, radius = Math.min(width, height) * .26;
    const total = rows.reduce((s, r) => s + Number(r[valueKey] || 0), 0) || 1;
    const palette = ['var(--accent)', 'var(--cyan)', 'var(--amber)', 'var(--red)', 'var(--green)', 'var(--accent-2)'];
    let start = -Math.PI / 2;
    container.innerHTML = '';
    const root = svg('svg', { viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': 'Donut chart' });
    rows.forEach((row, i) => {
      const value = Number(row[valueKey]) || 0;
      const angle = value / total * Math.PI * 2;
      const end = start + angle;
      const x1 = cx + radius * Math.cos(start), y1 = cy + radius * Math.sin(start);
      const x2 = cx + radius * Math.cos(end), y2 = cy + radius * Math.sin(end);
      const large = angle > Math.PI ? 1 : 0;
      const path = svg('path', { d: `M ${cx} ${cy} L ${x1} ${y1} A ${radius} ${radius} 0 ${large} 1 ${x2} ${y2} Z`, fill: palette[i % palette.length], opacity: .92 });
      const tip = svg('title'); tip.textContent = `${titleCase(row[labelKey])}: ${fmt(value)} (${fmt(value / total * 100, 1)}%)`; path.appendChild(tip); root.appendChild(path);
      start = end;
    });
    root.appendChild(svg('circle', { cx, cy, r: radius * .57, fill: 'var(--surface)' }));
    const totalText = svg('text', { x: cx, y: cy - 2, 'text-anchor': 'middle', style: 'font-size:22px;font-weight:800;fill:var(--text)' }); totalText.textContent = short(total); root.appendChild(totalText);
    const subText = svg('text', { x: cx, y: cy + 17, 'text-anchor': 'middle' }); subText.textContent = 'candidates'; root.appendChild(subText);
    rows.forEach((row, i) => {
      const y = 42 + i * 37;
      root.appendChild(svg('rect', { x: width * .7, y: y - 10, width: 10, height: 10, rx: 3, fill: palette[i % palette.length] }));
      const label = svg('text', { x: width * .7 + 16, y }); label.textContent = titleCase(row[labelKey]); root.appendChild(label);
      const value = svg('text', { x: width - 10, y, 'text-anchor': 'end' }); value.textContent = short(row[valueKey]); root.appendChild(value);
    });
    container.appendChild(root);
  }

  function renderScatter(container, rows, xKey, yKey, options = {}) {
    const data = rows.filter(r => Number.isFinite(Number(r[xKey])) && Number.isFinite(Number(r[yKey])));
    if (!container || !data.length) return emptyChart(container);
    const sampled = data.length > 1800 ? data.filter((_, i) => i % Math.ceil(data.length / 1800) === 0) : data;
    const { width, height } = chartSize(container, 340);
    const margin = { top: 15, right: 20, bottom: 42, left: 54 };
    const innerW = width - margin.left - margin.right, innerH = height - margin.top - margin.bottom;
    const xVals = sampled.map(r => Number(r[xKey])), yVals = sampled.map(r => Number(r[yKey]));
    const maxX = options.maxX || Math.max(...xVals), minX = options.minX ?? Math.min(...xVals);
    const maxY = options.maxY || Math.max(...yVals), minY = options.minY ?? Math.min(...yVals);
    const sx = v => margin.left + (Math.min(maxX, Math.max(minX, v)) - minX) / Math.max(.0001, maxX - minX) * innerW;
    const sy = v => margin.top + innerH - (Math.min(maxY, Math.max(minY, v)) - minY) / Math.max(.0001, maxY - minY) * innerH;
    container.innerHTML = '';
    const root = svg('svg', { viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': 'Scatter chart' });
    for (let i = 0; i <= 4; i++) {
      const y = margin.top + innerH * i / 4; root.appendChild(svg('line', { x1: margin.left, x2: width - margin.right, y1: y, y2: y, class: 'axis' }));
      const tl = svg('text', { x: margin.left - 8, y: y + 4, 'text-anchor': 'end' }); tl.textContent = fmt(maxY - (maxY - minY) * i / 4, 0); root.appendChild(tl);
      const x = margin.left + innerW * i / 4; const xb = svg('text', { x, y: height - 13, 'text-anchor': 'middle' }); xb.textContent = short(minX + (maxX - minX) * i / 4); root.appendChild(xb);
    }
    sampled.forEach(row => {
      const c = svg('circle', { cx: sx(Number(row[xKey])), cy: sy(Number(row[yKey])), r: 3.2, class: 'point' });
      const tip = svg('title'); tip.textContent = `${row.title || row.id}: ${options.xLabel || xKey} ${fmt(row[xKey])}; ${options.yLabel || yKey} ${fmt(row[yKey], 1)}`; c.appendChild(tip); root.appendChild(c);
    });
    const xl = svg('text', { x: margin.left + innerW / 2, y: height - 1, 'text-anchor': 'middle' }); xl.textContent = options.xLabel || titleCase(xKey); root.appendChild(xl);
    const yl = svg('text', { x: 12, y: margin.top + innerH / 2, transform: `rotate(-90 12 ${margin.top + innerH / 2})`, 'text-anchor': 'middle' }); yl.textContent = options.yLabel || titleCase(yKey); root.appendChild(yl);
    container.appendChild(root);
  }

  function renderHistogram(container, values, options = {}) {
    const clean = values.map(Number).filter(Number.isFinite);
    if (!container || !clean.length) return emptyChart(container);
    const bins = options.bins || 16, min = Math.min(...clean), max = Math.max(...clean), step = (max - min) / bins || 1;
    const rows = Array.from({ length: bins }, (_, i) => ({ label: `${(min + i * step).toFixed(2)}`, count: 0 }));
    clean.forEach(v => { rows[Math.min(bins - 1, Math.floor((v - min) / step))].count++; });
    const { width, height } = chartSize(container, 340);
    const margin = { top: 15, right: 15, bottom: 40, left: 48 }, innerW = width - margin.left - margin.right, innerH = height - margin.top - margin.bottom;
    const maxCount = Math.max(...rows.map(r => r.count), 1), gap = 3, barW = innerW / bins;
    container.innerHTML = '';
    const root = svg('svg', { viewBox: `0 0 ${width} ${height}` });
    for (let i = 0; i <= 4; i++) {
      const y = margin.top + innerH * i / 4; root.appendChild(svg('line', { x1: margin.left, x2: width - margin.right, y1: y, y2: y, class: 'axis' }));
      const t = svg('text', { x: margin.left - 7, y: y + 4, 'text-anchor': 'end' }); t.textContent = short(maxCount * (1 - i / 4)); root.appendChild(t);
    }
    rows.forEach((r, i) => {
      const h = r.count / maxCount * innerH, x = margin.left + i * barW, y = margin.top + innerH - h;
      const bar = svg('rect', { x: x + gap / 2, y, width: Math.max(1, barW - gap), height: h, rx: 3, class: 'bar' });
      const tip = svg('title'); tip.textContent = `${r.label}–${(Number(r.label) + step).toFixed(2)}: ${r.count}`; bar.appendChild(tip); root.appendChild(bar);
      if (i % 4 === 0) { const tx = svg('text', { x: x + barW / 2, y: height - 13, 'text-anchor': 'middle' }); tx.textContent = r.label; root.appendChild(tx); }
    });
    container.appendChild(root);
  }

  function showView(view) {
    state.view = view;
    $$('.view').forEach(v => v.classList.toggle('active', v.id === `view-${view}`));
    $$('.nav-item').forEach(b => b.classList.toggle('active', b.dataset.view === view));
    $('#viewTitle').textContent = ({ overview: 'Overview', explorer: 'Corpus explorer', nlp: 'NLP visualisations', review: 'Human review', quality: 'Data quality' })[view];
    $('#sidebar').classList.remove('open');
    if (view === 'overview') renderOverviewCharts();
    if (view === 'nlp') renderNlpTab();
    if (view === 'review') renderReview();
    if (view === 'explorer') renderDocumentList();
  }

  function initNavigation() {
    $$('.nav-item').forEach(btn => btn.addEventListener('click', () => showView(btn.dataset.view)));
    $$('[data-go]').forEach(btn => btn.addEventListener('click', () => showView(btn.dataset.go)));
    $('#mobileMenu').addEventListener('click', () => $('#sidebar').classList.toggle('open'));
    $('#dismissNotice').addEventListener('click', () => $('#globalNotice').style.display = 'none');
    const storedTheme = storageGet(THEME_KEY, 'light');
    document.documentElement.dataset.theme = storedTheme;
    $('#themeToggle').addEventListener('click', () => {
      const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
      document.documentElement.dataset.theme = next; storageSet(THEME_KEY, next);
      renderOverviewCharts(); renderNlpTab();
    });
  }

  function renderKpis() {
    const s = DATA.summary;
    const items = [
      ['Documents', fmt(s.documents), 'validated JSON records', '▤'],
      ['Words', short(s.words), `${fmt(s.sentences)} sentences`, 'Aa'],
      ['Images', fmt(s.images), 'document-linked records', '▧'],
      ['Filtered tokens', short(s.tokensAfterFiltering), `${fmt(s.uniqueTerms)} unique terms`, '⌁'],
      ['Frame candidates', short(s.frameCandidates), 'requires validation', '◇'],
      ['Legitimation candidates', short(s.legitimationCandidates), 'requires validation', '◈'],
      ['Actor mentions', short(s.actorMentions), 'spaCy candidates', '◎'],
      ['Date flags', fmt(s.missingDates + s.futureDates), `${s.missingDates} missing · ${s.futureDates} after reference date`, '!'],
    ];
    $('#kpiGrid').innerHTML = items.map(([label, value, note, icon]) => `<div class="kpi"><div class="kpi-top"><span>${esc(label)}</span><span class="kpi-icon">${icon}</span></div><strong>${esc(value)}</strong><small>${esc(note)}</small></div>`).join('');
  }

  function annotationCounts() {
    const all = Object.values(state.annotations);
    return {
      total: Object.values(DATA.reviewQueues).reduce((s, q) => s + q.length, 0),
      reviewed: all.filter(a => ['valid', 'reject', 'uncertain'].includes(a.status)).length,
      valid: all.filter(a => a.status === 'valid').length,
      reject: all.filter(a => a.status === 'reject').length,
      uncertain: all.filter(a => a.status === 'uncertain').length,
    };
  }

  function updateReviewProgress() {
    const c = annotationCounts(), pct = c.total ? c.reviewed / c.total * 100 : 0;
    $('#reviewProgressHero').textContent = `${fmt(pct, 1)}%`;
    $('.hero-badge')?.style.setProperty('--progress', `${pct}%`);
    $('#overallReviewPercent').textContent = `${fmt(pct, 1)}%`;
    $('#overallReviewBar').style.width = `${pct}%`;
    $('#reviewStatusSummary').innerHTML = [
      ['Valid', c.valid, 'var(--green)'], ['Rejected', c.reject, 'var(--red)'], ['Uncertain', c.uncertain, 'var(--amber)'], ['Unreviewed', c.total - c.reviewed, 'var(--accent)']
    ].map(([label, count, colour]) => `<div class="status-row"><span>${label}</span><div class="status-track"><span style="width:${count / c.total * 100}%;background:${colour}"></span></div><strong>${short(count)}</strong></div>`).join('');
  }

  function renderOverviewCharts() {
    const yearData = DATA.publicationByYear.filter(r => Number(r.year) >= 2019);
    renderLine($('#overviewTimeline'), yearData, 'year', 'articles', { height: 270 });
    renderHorizontalBars($('#overviewFrames'), DATA.frameCounts, 'category', 'count', { limit: 9, left: 155, height: 290 });
    renderHorizontalBars($('#overviewTerms'), DATA.topTerms, 'term', 'frequency', { limit: 10, left: 110, height: 290 });
  }

  function initDocumentExplorer() {
    const years = [...new Set(DATA.documents.map(d => d.year).filter(Boolean))].sort((a,b) => b-a);
    $('#yearFilter').innerHTML += years.map(y => `<option>${y}</option>`).join('');
    $('#authorFilter').innerHTML += DATA.topAuthors.map(a => `<option value="${esc(a.label)}">${esc(a.label)} (${a.count})</option>`).join('');
    $('#tagFilter').innerHTML += DATA.topTags.map(t => `<option value="${esc(t.label)}">${esc(t.label)} (${t.count})</option>`).join('');
    ['docSearch','yearFilter','authorFilter','tagFilter','dateFlagFilter','imageFilter','minWords','maxWords'].forEach(id => {
      const evt = id === 'docSearch' ? 'input' : 'change';
      $('#' + id).addEventListener(evt, debounce(applyDocumentFilters, 120));
    });
    $('#clearDocFilters').addEventListener('click', () => {
      ['docSearch','yearFilter','authorFilter','tagFilter','dateFlagFilter','imageFilter','maxWords'].forEach(id => $('#' + id).value = '');
      $('#minWords').value = 0; applyDocumentFilters();
    });
    $('#docPrev').addEventListener('click', () => { if (state.docPage > 0) { state.docPage--; renderDocumentList(); } });
    $('#docNext').addEventListener('click', () => { const max = Math.ceil(state.filteredDocuments.length / PAGE_SIZE) - 1; if (state.docPage < max) { state.docPage++; renderDocumentList(); } });
    $('#exportSelection').addEventListener('click', exportDocumentSelection);
    applyDocumentFilters();
  }

  function applyDocumentFilters() {
    const q = $('#docSearch').value.trim().toLowerCase();
    const year = $('#yearFilter').value, author = $('#authorFilter').value, tag = $('#tagFilter').value;
    const dateFlag = $('#dateFlagFilter').value, image = $('#imageFilter').value;
    const min = Number($('#minWords').value || 0), max = Number($('#maxWords').value || Infinity);
    state.filteredDocuments = DATA.documents.filter(d => {
      const hay = `${d.title} ${d.author} ${d.tags.join(' ')} ${d.id}`.toLowerCase();
      return (!q || hay.includes(q)) && (!year || String(d.year) === year) && (!author || d.author === author)
        && (!tag || d.tags.includes(tag)) && (!dateFlag || (dateFlag === 'issue' ? d.dateFlag !== 'ok' : d.dateFlag === dateFlag))
        && (!image || (image === 'yes' ? d.imageCount > 0 : d.imageCount === 0))
        && d.wordCount >= min && d.wordCount <= max;
    }).sort((a,b) => String(b.publishedAt || '').localeCompare(String(a.publishedAt || '')));
    state.docPage = 0; renderDocumentList();
  }

  function renderDocumentList() {
    const start = state.docPage * PAGE_SIZE, rows = state.filteredDocuments.slice(start, start + PAGE_SIZE);
    const pages = Math.max(1, Math.ceil(state.filteredDocuments.length / PAGE_SIZE));
    $('#docPage').textContent = `${state.docPage + 1} / ${pages}`;
    $('#docResultCount').textContent = `${fmt(state.filteredDocuments.length)} matching documents`;
    $('#documentList').innerHTML = rows.length ? rows.map(d => `<div class="document-item ${state.selectedDocumentId === d.id ? 'active' : ''}" data-doc-id="${esc(d.id)}"><h4>${esc(d.title)}</h4><div class="document-meta"><span class="${d.dateFlag !== 'ok' ? 'date-warning' : ''}">${esc(dateLabel(d.publishedAt))}</span><span>${esc(d.author)}</span><span>${fmt(d.wordCount)} words</span><span>${d.imageCount} images</span></div></div>`).join('') : '<div class="empty-state"><p>No records match these filters.</p></div>';
    $$('.document-item').forEach(el => el.addEventListener('click', () => selectDocument(el.dataset.docId)));
  }

  function selectDocument(id) {
    state.selectedDocumentId = id; renderDocumentList(); renderDocumentDetail();
  }

  function imageUrl(image) {
    return image?.url || image?.source_url || image?.src || image?.image_url || image?.final_url || '';
  }

  function imageCaption(image) {
    return image?.caption || image?.alt || image?.alt_text || image?.title || image?.local_path || image?.path || 'Image metadata';
  }

  function renderDocumentDetail() {
    const d = docMap.get(state.selectedDocumentId);
    if (!d) return;
    const attached = state.attachedArticles.get(d.id);
    const detail = $('#documentDetail');
    detail.innerHTML = `<div class="document-meta"><span class="${d.dateFlag !== 'ok' ? 'date-warning' : ''}">${esc(dateLabel(d.publishedAt))}${d.dateFlag === 'future' ? ' · after reference date' : d.dateFlag === 'missing' ? ' · missing' : ''}</span><span>${esc(d.author)}</span><span>${esc(d.id)}</span></div><h3 class="doc-title">${esc(d.title)}</h3><div class="doc-tags">${d.tags.map(t => `<span>${esc(t)}</span>`).join('')}</div><div class="doc-stats"><div class="doc-stat"><strong>${fmt(d.wordCount)}</strong><span>Words</span></div><div class="doc-stat"><strong>${fmt(d.sentenceCount)}</strong><span>Sentences</span></div><div class="doc-stat"><strong>${fmt(d.mattr50,2)}</strong><span>MATTR-50</span></div><div class="doc-stat"><strong>${fmt(d.flesch,1)}</strong><span>Flesch estimate</span></div></div><p><a href="${esc(d.url)}" target="_blank" rel="noopener noreferrer">Open source URL ↗</a></p><div id="attachedContent"></div>`;
    const target = $('#attachedContent', detail);
    if (!attached) {
      target.innerHTML = '<div class="doc-attach-note">Import the current <code>articles.jsonl</code> using the button above to inspect the complete article text and image metadata in this browser session.</div>';
      return;
    }
    const body = attached.body_clean || attached.body || (Array.isArray(attached.paragraphs) ? attached.paragraphs.join('\n\n') : '');
    const textNode = document.createElement('div'); textNode.className = 'doc-body'; textNode.textContent = body || 'No body text in the imported record.'; target.appendChild(textNode);
    const images = Array.isArray(attached.images) ? attached.images : [];
    if (images.length) {
      const heading = document.createElement('h4'); heading.textContent = `Images (${images.length})`; target.appendChild(heading);
      const grid = document.createElement('div'); grid.className = 'image-grid';
      images.forEach(img => {
        const card = document.createElement('div'); card.className = 'image-card';
        const url = imageUrl(img);
        if (/^https?:|^data:/i.test(url)) { const im = document.createElement('img'); im.src = url; im.alt = imageCaption(img); im.loading = 'lazy'; card.appendChild(im); }
        const p = document.createElement('p'); p.textContent = imageCaption(img); card.appendChild(p); grid.appendChild(card);
      });
      target.appendChild(grid);
    }
  }

  async function importArticles(file) {
    if (!file) return;
    toast(`Reading ${file.name}…`);
    const text = await file.text();
    const lines = text.split(/\r?\n/).filter(Boolean);
    const map = new Map(); let errors = 0;
    for (const line of lines) {
      try { const obj = JSON.parse(line); if (obj.document_id) map.set(String(obj.document_id), obj); }
      catch (_) { errors++; }
    }
    state.attachedArticles = map;
    toast(`Imported ${fmt(map.size)} article records${errors ? `; ${errors} parse errors` : ''}.`);
    if (state.selectedDocumentId) renderDocumentDetail();
  }


  function exportDocumentSelection() {
    const columns = ['id','title','publishedAt','year','author','tags','wordCount','sentenceCount','imageCount','mattr50','flesch','dateFlag','url'];
    const lines = [columns.join(','), ...state.filteredDocuments.map(d => columns.map(k => csvCell(k === 'tags' ? d.tags.join('|') : d[k])).join(','))];
    downloadBlob(lines.join('\n'), `pa_document_selection_${new Date().toISOString().slice(0,10)}.csv`, 'text/csv');
    toast(`Exported ${fmt(state.filteredDocuments.length)} selected documents.`);
  }

  function initNlp() {
    $$('#nlpTabs button').forEach(btn => btn.addEventListener('click', () => {
      state.nlpTab = btn.dataset.nlpTab;
      $$('#nlpTabs button').forEach(b => b.classList.toggle('active', b === btn));
      $$('.nlp-tab').forEach(t => t.classList.toggle('active', t.id === `nlp-${state.nlpTab}`));
      renderNlpTab();
    }));
    $('#termMetric').addEventListener('change', renderLexical);
    $('#ngramSize').addEventListener('change', renderLexical);
    const method = DATA.lexicalCleaning || {};
    $('#lexicalMethodSummary').innerHTML = [
      ['Content tokens', fmt(method.contentTokens)],
      ['Alphabetic token base', fmt(method.alphabeticTokenBase)],
      ['Unique content lemmas', fmt(method.uniqueContentTerms)],
      ['POS retained', (method.keptPartsOfSpeech || []).join(', ')],
      ['Custom exclusions', (method.customStopwords || []).join(', ')],
    ].map(([label, value]) => `<div class="method-chip"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join('');

    $('#runConcordance').addEventListener('click', renderConcordance);
    $('#concordanceQuery').addEventListener('keydown', e => { if (e.key === 'Enter') renderConcordance(); });
    ['concordanceMode','concordanceLimit','concordanceFiltered'].forEach(id => $('#' + id).addEventListener('change', () => { if ($('#concordanceQuery').value.trim()) renderConcordance(); }));
    $('#exportConcordance').addEventListener('click', exportConcordance);

    $('#bncFile').addEventListener('change', e => importBncReference(e.target.files[0]));
    $('#runKeyness').addEventListener('click', renderKeyness);
    ['bncTokens','keynessDirection','keynessMinFreq','keynessMinDocs','keynessMissingZero'].forEach(id => $('#' + id).addEventListener('change', () => { if (state.bncReference) renderKeyness(); }));
    $('#exportKeyness').addEventListener('click', exportKeyness);
    if (state.bncReference) {
      $('#bncTokens').value = state.bncReference.corpusTokens || 100000000;
      activateBncReference(state.bncReference);
    }

    const nodes = [...new Set(DATA.collocations.map(c => c.node))].sort();
    $('#collocationNode').innerHTML = nodes.map(n => `<option>${esc(n)}</option>`).join('');
    state.collocationNode = nodes[0];
    $('#collocationNode').addEventListener('change', e => { state.collocationNode = e.target.value; renderCollocationNetwork(); });
    ['collocationMetric','collocationLimit','collocationMinDocs'].forEach(id => {
      $('#' + id).addEventListener('change', renderCollocationNetwork);
    });
    const labels = [...new Set(DATA.topActors.map(a => a.label))].sort();
    $('#entityLabelFilter').innerHTML += labels.map(l => `<option>${esc(l)}</option>`).join('');
    $('#entityLabelFilter').addEventListener('change', renderEntities);
  }

  function renderNlpTab() {
    if (state.nlpTab === 'lexical') renderLexical();
    if (state.nlpTab === 'discourse') renderDiscourse();
    if (state.nlpTab === 'entities') renderEntities();
    if (state.nlpTab === 'readability') renderReadability();
  }

  function renderLexical() {
    const metric = $('#termMetric').value;
    renderHorizontalBars($('#termChart'), DATA.topTerms, 'term', metric, {
      limit: 16,
      left: 130,
      height: 350,
      format: metric === 'documentProportion' ? v => fmt(v * 100, 1) + '%' : short,
      onClick: row => openConcordance(row.term),
    });
    const ngramKey = $('#ngramSize').value;
    renderHorizontalBars($('#ngramChart'), DATA[ngramKey], 'ngram', 'frequency', {
      limit: 16,
      left: 185,
      height: 350,
      onClick: row => openConcordance(row.ngram),
    });
    const terms = DATA.topTerms.slice(0, 60), max = terms[0]?.frequency || 1, min = terms.at(-1)?.frequency || 1;
    $('#wordCloud').innerHTML = terms.map((t,i) => {
      const scale = .75 + (t.frequency - min) / Math.max(1,max-min) * 1.55;
      return `<button class="cloud-term" style="font-size:${scale}rem;opacity:${.48 + (60-i)/120}" title="${fmt(t.frequency)} occurrences" data-concordance-term="${esc(t.term)}">${esc(t.term)}</button>`;
    }).join('');
    $$('[data-concordance-term]').forEach(el => el.addEventListener('click', () => openConcordance(el.dataset.concordanceTerm)));
    renderCollocationNetwork();
  }

  function regexEscape(value) {
    return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

  function openConcordance(query) {
    $('#concordanceQuery').value = query;
    $('#concordanceMode').value = String(query).includes(' ') ? 'token' : (DATA.lemmaConcordance?.[String(query).toLowerCase()] ? 'lemma' : 'token');
    renderConcordance();
    $('#concordanceQuery').scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  function concordanceRegex(query, mode) {
    const escaped = regexEscape(query.trim());
    if (!escaped) return null;
    if (mode === 'substring') return new RegExp(escaped, 'i');
    const left = /^\w/.test(query) ? '\\b' : '';
    const right = /\w$/.test(query) ? '\\b' : '';
    return new RegExp(left + escaped + right, 'i');
  }

  function kwicParts(text, matchIndex, matchText, windowSize = 92) {
    const leftStart = Math.max(0, matchIndex - windowSize);
    const rightEnd = Math.min(text.length, matchIndex + matchText.length + windowSize);
    return {
      left: (leftStart > 0 ? '…' : '') + text.slice(leftStart, matchIndex),
      node: text.slice(matchIndex, matchIndex + matchText.length),
      right: text.slice(matchIndex + matchText.length, rightEnd) + (rightEnd < text.length ? '…' : ''),
    };
  }

  function sentenceLookup() {
    if (!sentenceLookup.cache) sentenceLookup.cache = new Map(DATA.sentences.map(s => [`${s.documentId}:${s.index}`, s]));
    return sentenceLookup.cache;
  }

  function renderConcordance() {
    const query = $('#concordanceQuery').value.trim();
    const results = $('#concordanceResults');
    if (!query) {
      state.concordanceRows = [];
      $('#concordanceSummary').textContent = 'Enter a term or select one from the frequency chart.';
      results.innerHTML = '';
      return;
    }
    const mode = $('#concordanceMode').value;
    const limit = Number($('#concordanceLimit').value || 50);
    const restrict = $('#concordanceFiltered').checked;
    const allowed = restrict ? new Set(state.filteredDocuments.map(d => d.id)) : null;
    const rows = [];

    if (mode === 'lemma' && DATA.lemmaConcordance?.[query.toLowerCase()]) {
      const lookup = sentenceLookup();
      for (const occurrence of DATA.lemmaConcordance[query.toLowerCase()]) {
        const [documentId, sentenceIndex, surface] = occurrence;
        if (allowed && !allowed.has(documentId)) continue;
        const sentence = lookup.get(`${documentId}:${sentenceIndex}`);
        if (!sentence) continue;
        const rx = concordanceRegex(surface || query, 'token');
        const match = rx?.exec(sentence.text);
        if (!match) continue;
        rows.push({ sentence, documentId, ...kwicParts(sentence.text, match.index, match[0]) });
        if (rows.length >= limit) break;
      }
    } else {
      const rx = concordanceRegex(query, mode);
      if (rx) {
        for (const sentence of DATA.sentences) {
          if (allowed && !allowed.has(sentence.documentId)) continue;
          const match = rx.exec(sentence.text);
          if (!match) continue;
          rows.push({ sentence, documentId: sentence.documentId, ...kwicParts(sentence.text, match.index, match[0]) });
          if (rows.length >= limit) break;
        }
      }
    }

    state.concordanceRows = rows;
    const documentCount = new Set(rows.map(r => r.documentId)).size;
    $('#concordanceSummary').textContent = `${fmt(rows.length)} concordance lines from ${fmt(documentCount)} documents${restrict ? ' within the current document filters' : ''}.`;
    results.innerHTML = rows.length ? rows.map((row, index) => {
      const doc = docMap.get(row.documentId);
      return `<button class="kwic-row" data-kwic-doc="${esc(row.documentId)}"><span class="kwic-number">${index + 1}</span><span class="kwic-context"><span class="kwic-left">${esc(row.left)}</span><mark>${esc(row.node)}</mark><span class="kwic-right">${esc(row.right)}</span></span><span class="kwic-meta"><strong>${esc(doc?.title || row.documentId)}</strong><small>${esc(dateLabel(doc?.publishedAt))} · sentence ${fmt(row.sentence.index + 1)}</small></span></button>`;
    }).join('') : '<div class="empty-state"><p>No concordance lines matched this query and filter combination.</p></div>';
    $$('[data-kwic-doc]', results).forEach(el => el.addEventListener('click', () => { selectDocument(el.dataset.kwicDoc); showView('explorer'); }));
  }

  function exportConcordance() {
    if (!state.concordanceRows.length) return toast('No concordance lines to export.');
    const query = $('#concordanceQuery').value.trim();
    const columns = ['query','document_id','sentence_index','left_context','match','right_context','title','published_at','author','url'];
    const lines = [columns.join(',')];
    state.concordanceRows.forEach(row => {
      const doc = docMap.get(row.documentId) || {};
      const values = [query,row.documentId,row.sentence.index,row.left,row.node,row.right,doc.title,doc.publishedAt,doc.author,doc.url];
      lines.push(values.map(csvCell).join(','));
    });
    downloadBlob(lines.join('\n'), `pa_concordance_${query.replace(/[^a-z0-9]+/gi,'_').slice(0,40)}.csv`, 'text/csv');
    toast(`Exported ${fmt(state.concordanceRows.length)} concordance lines.`);
  }

  function decodeTextFile(buffer) {
    const utf8 = new TextDecoder('utf-8', { fatal: false }).decode(buffer);
    const replacements = (utf8.match(/�/g) || []).length;
    if (replacements > 3) return new TextDecoder('windows-1252', { fatal: false }).decode(buffer);
    return utf8;
  }

  function splitDelimited(line, delimiter) {
    const output = [];
    let value = '', quoted = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (ch === '"') {
        if (quoted && line[i + 1] === '"') { value += '"'; i++; }
        else quoted = !quoted;
      } else if (ch === delimiter && !quoted) { output.push(value.trim()); value = ''; }
      else value += ch;
    }
    output.push(value.trim());
    return output;
  }

  function normaliseReferenceTerm(value) {
    const term = String(value || '')
      .trim()
      .toLowerCase()
      .replace(/’/g, "'")
      .replace(/^['"]|['"]$/g, '')
      .replace(/[\*#]+$/g, '');
    if (!term || /\s|[\/()]/.test(term)) return '';
    return /^[a-z][a-z'-]*$/i.test(term) ? term : '';
  }

  function parseDecoratedNumber(value) {
    const match = String(value ?? '').replace(/,/g, '').match(/-?\d+(?:\.\d+)?/);
    return match ? Number(match[0]) : NaN;
  }

  function parseBncReference(text, name) {
    const lines = text
      .split(/\r?\n/)
      .map(line => line.replace(/^\uFEFF/, ''))
      .filter(line => line.trim() && !line.trimStart().startsWith('#'));
    if (!lines.length) throw new Error('The selected file is empty.');
    const aggregate = new Map();
    let basis = null, format = null, parsed = 0;

    const add = (term, count, perMillion) => {
      term = normaliseReferenceTerm(term);
      if (!term || !/^[a-z][a-z'-]*$/i.test(term)) return;
      const old = aggregate.get(term) || { count: 0, perMillion: 0 };
      if (Number.isFinite(count)) old.count += count;
      if (Number.isFinite(perMillion)) old.perMillion += perMillion;
      aggregate.set(term, old); parsed++;
    };

    const first = lines[0];

    // UCREL List 4.1: imaginative vs informative writing, lemmatised.
    // FrIn is the informative-writing frequency per million. The source has
    // blank separator columns and @/@ inflection rows, so it needs a dedicated parser.
    const firstTabCells = first.split('\t').map(cell => cell.trim());
    const firstTabHeaders = firstTabCells.map(h => h.toLowerCase().replace(/[^a-z0-9]+/g, '_'));
    const ucrel41WordIndex = firstTabHeaders.indexOf('word');
    const ucrel41PosIndex = firstTabHeaders.indexOf('pos');
    const ucrel41FrInIndex = firstTabHeaders.indexOf('frin');
    if (ucrel41WordIndex >= 0 && ucrel41PosIndex >= 0 && ucrel41FrInIndex >= 0) {
      basis = 'perMillion';
      format = 'UCREL List 4.1 informative writing (FrIn; content lemmas)';
      const contentPos = new Set(['NoC', 'NoP', 'Verb', 'Adj', 'Adv']);
      for (const line of lines.slice(1)) {
        let cells = line.split('\t').map(cell => cell.trim());
        // A few documented source rows omit the leading blank cell.
        if (firstTabCells[0] === '' && cells.length === firstTabCells.length - 1 && cells[0] !== '') {
          cells.unshift('');
        }
        const term = cells[ucrel41WordIndex];
        const pos = cells[ucrel41PosIndex];
        if (!term || term === '@' || pos === '@' || !contentPos.has(pos)) continue;
        const pm = parseDecoratedNumber(cells[ucrel41FrInIndex]);
        if (Number.isFinite(pm)) add(term, NaN, pm);
      }
    }

    const delimiter = first.includes('\t') ? '\t' : first.includes(',') ? ',' : null;
    const headerCells = delimiter ? splitDelimited(first, delimiter) : first.split(/\s+/);
    const headers = headerCells.map(h => h.toLowerCase().replace(/[^a-z0-9]+/g, '_'));
    const termIndex = headers.findIndex(h => ['term','word','lemma','headword'].includes(h));
    const countIndex = headers.findIndex(h => ['count','frequency','raw_frequency','freq'].includes(h));
    const pmIndex = headers.findIndex(h => ['per_million','frequency_per_million','freq_per_million','pmw','frin'].includes(h));

    if (!basis && termIndex >= 0 && (countIndex >= 0 || pmIndex >= 0)) {
      basis = pmIndex >= 0 ? 'perMillion' : 'count';
      format = 'header-based table';
      for (const line of lines.slice(1)) {
        const cells = delimiter ? splitDelimited(line, delimiter) : line.split(/\s+/);
        const count = countIndex >= 0 ? Number(cells[countIndex]) : NaN;
        const pm = pmIndex >= 0 ? Number(cells[pmIndex]) : NaN;
        add(cells[termIndex], count, pm);
      }
    } else if (!basis && first.includes('\t')) {
      basis = 'perMillion';
      format = 'UCREL lemmatised list (per million)';
      for (const line of lines) {
        const cells = line.split('\t').map(x => x.trim()).filter(Boolean);
        if (cells.length < 3) continue;
        const pm = Number(cells[2]);
        if (Number.isFinite(pm)) add(cells[0], NaN, pm);
      }
    } else if (!basis) {
      const sample = first.split(/\s+/);
      const firstNumber = Number(sample[0]), secondNumber = Number(sample[1]);
      if (Number.isFinite(firstNumber) && Number.isFinite(secondNumber) && sample.length >= 4) {
        basis = 'count';
        format = 'Kilgarriff lemmatised list (raw count)';
        for (const line of lines) {
          const cells = line.split(/\s+/);
          if (cells.length < 4) continue;
          const count = Number(cells[1]);
          if (Number.isFinite(count)) add(cells[2], count, NaN);
        }
      } else if (Number.isFinite(firstNumber) && sample.length >= 3) {
        basis = 'count';
        format = 'raw frequency list';
        for (const line of lines) {
          const cells = line.split(/\s+/);
          const count = Number(cells[0]);
          if (Number.isFinite(count)) add(cells[1], count, NaN);
        }
      }
    }

    if (!aggregate.size || !basis) throw new Error('The frequency-list format could not be recognised. Supported inputs include UCREL List 4.1 (FrIn), UCREL List 1.1, Kilgarriff lemma.num/lemma.al, or a CSV with term and count/per_million columns.');
    const entries = [...aggregate.entries()].map(([term, values]) => ({ term, ...values }));
    return { name, format, basis, entries, parsedRows: parsed, corpusTokens: Number($('#bncTokens').value || 100000000), loadedAtBuild: false };
  }

  async function importBncReference(file) {
    if (!file) return;
    try {
      const text = decodeTextFile(await file.arrayBuffer());
      const reference = parseBncReference(text, file.name);
      state.bncReference = reference;
      activateBncReference(reference);
      renderKeyness();
      toast(`Loaded ${fmt(reference.entries.length)} BNC entries.`);
    } catch (error) {
      $('#bncStatus').textContent = `Import failed: ${error.message}`;
      toast(`BNC import failed: ${error.message}`);
    }
  }

  function activateBncReference(reference) {
    const map = new Map();
    (reference.entries || []).forEach(entry => {
      const term = normaliseReferenceTerm(entry.term);
      if (!term) return;
      const old = map.get(term) || { count: 0, perMillion: 0 };
      old.count += Number(entry.count || 0);
      old.perMillion += Number(entry.perMillion || 0);
      map.set(term, old);
    });
    reference.map = map;
    state.bncReference = reference;
    $('#runKeyness').disabled = false;
    $('#exportKeyness').disabled = false;
    $('#bncStatus').innerHTML = `<strong>${esc(reference.name || 'Embedded BNC reference')}</strong> · ${fmt(map.size)} unique entries · ${esc(reference.format || reference.unit || 'frequency list')} · basis: ${reference.basis === 'perMillion' ? 'rounded frequency per million' : 'raw count'}.`;
  }

  function logLikelihood(k1, n1, k2, n2) {
    const total = k1 + k2;
    if (!total || !n1 || !n2) return 0;
    const e1 = n1 * total / (n1 + n2), e2 = n2 * total / (n1 + n2);
    const part1 = k1 > 0 && e1 > 0 ? k1 * Math.log(k1 / e1) : 0;
    const part2 = k2 > 0 && e2 > 0 ? k2 * Math.log(k2 / e2) : 0;
    return 2 * (part1 + part2);
  }

  function renderKeyness() {
    const ref = state.bncReference;
    if (!ref?.map) return;
    const n1 = Number(DATA.lexicalCleaning?.alphabeticTokenBase || DATA.summary.tokensAfterFiltering || 1);
    const n2 = Number($('#bncTokens').value || ref.corpusTokens || 100000000);
    const minFreq = Number($('#keynessMinFreq').value || 1);
    const minDocs = Number($('#keynessMinDocs').value || 1);
    const directionFilter = $('#keynessDirection').value;
    const missingZero = $('#keynessMissingZero').checked;
    const rows = [];
    let matched = 0, omittedMissing = 0;

    for (const term of DATA.topTerms) {
      if (term.frequency < minFreq || term.documentFrequency < minDocs) continue;
      const entry = ref.map.get(term.term);
      if (!entry && !missingZero) { omittedMissing++; continue; }
      if (entry) matched++;
      const k1 = Number(term.frequency);
      let k2 = 0, referencePm = 0;
      if (entry) {
        if (ref.basis === 'perMillion' || (!entry.count && entry.perMillion)) {
          referencePm = Number(entry.perMillion || 0);
          k2 = referencePm * n2 / 1000000;
        } else {
          k2 = Number(entry.count || 0);
          referencePm = k2 / n2 * 1000000;
        }
      }
      const targetPm = k1 / n1 * 1000000;
      const direction = targetPm >= referencePm ? 'over' : 'under';
      if (directionFilter !== 'all' && direction !== directionFilter) continue;
      const g2 = logLikelihood(k1, n1, k2, n2);
      const logRatio = Math.log2(((k1 + 0.5) / (n1 + 1)) / ((k2 + 0.5) / (n2 + 1)));
      rows.push({ term: term.term, targetFrequency: k1, targetPm, referenceFrequency: k2, referencePm, logLikelihood: g2, logRatio, documentFrequency: term.documentFrequency, direction });
    }
    rows.sort((a,b) => b.logLikelihood - a.logLikelihood || Math.abs(b.logRatio) - Math.abs(a.logRatio));
    state.keynessRows = rows;
    const chartRows = rows.slice(0, 18).map(row => ({ ...row, displayTerm: `${row.direction === 'over' ? '↑' : '↓'} ${row.term}` }));
    renderHorizontalBars($('#keynessChart'), chartRows, 'displayTerm', 'logLikelihood', { limit: 18, left: 155, height: 420, format: v => fmt(v, 1), onClick: row => openConcordance(row.term) });
    $('#keynessTable').innerHTML = rows.slice(0, 100).map(row => `<tr class="clickable-row" data-key-term="${esc(row.term)}"><td><strong>${row.direction === 'over' ? '↑' : '↓'} ${esc(row.term)}</strong></td><td>${fmt(row.targetFrequency)}<small>${fmt(row.targetPm,1)} pm</small></td><td>${fmt(row.referenceFrequency,1)}<small>${fmt(row.referencePm,1)} pm</small></td><td>${fmt(row.logLikelihood,1)}</td><td>${fmt(row.logRatio,2)}</td><td>${fmt(row.documentFrequency)}</td></tr>`).join('');
    $$('[data-key-term]').forEach(el => el.addEventListener('click', () => openConcordance(el.dataset.keyTerm)));
    $('#bncStatus').innerHTML = `<strong>${esc(ref.name || 'BNC reference')}</strong> · ${fmt(ref.map.size)} entries · ${fmt(matched)} target lemmas matched · ${fmt(omittedMissing)} absent target lemmas omitted · ${fmt(rows.length)} keyness rows after filters.${ref.basis === 'perMillion' ? ' BNC counts are reconstructed from rounded frequencies per million.' : ''}`;
  }

  function exportKeyness() {
    if (!state.keynessRows.length) return toast('No keyness rows to export.');
    const columns = ['term','direction','target_frequency','target_per_million','reference_frequency','reference_per_million','log_likelihood_g2','log_ratio','document_frequency'];
    const lines = [columns.join(',')];
    state.keynessRows.forEach(row => lines.push([
      row.term,row.direction,row.targetFrequency,row.targetPm,row.referenceFrequency,row.referencePm,row.logLikelihood,row.logRatio,row.documentFrequency
    ].map(csvCell).join(',')));
    downloadBlob(lines.join('\n'), `pa_bnc_keyness_${new Date().toISOString().slice(0,10)}.csv`, 'text/csv');
    toast(`Exported ${fmt(state.keynessRows.length)} keyness rows.`);
  }

  function renderCollocationNetwork() {
    const node = state.collocationNode || $('#collocationNode').value;
    const metric = $('#collocationMetric')?.value || 'logDice';
    const limit = Number($('#collocationLimit')?.value || 20);
    const minDocs = Number($('#collocationMinDocs')?.value || 1);
    const metricLabel = metric === 'pmi' ? 'PMI' : 'logDice';
    const rows = DATA.collocations
      .filter(c => c.node === node && Number(c.documentFrequency) >= minDocs)
      .sort((a,b) => Number(b[metric]) - Number(a[metric]) || b.documentFrequency - a.documentFrequency)
      .slice(0, limit);
    state.collocationRows = rows;

    const container = $('#collocationNetwork');
    if (!rows.length) {
      emptyChart(container, `No collocations for “${node}” at this spread threshold`);
      $('#collocationDetails').innerHTML = '';
      return;
    }

    const width = Math.max(520, container.clientWidth || 720);
    const height = 385;
    const margin = { top: 34, right: 24, bottom: 56, left: 66 };
    const plotW = width - margin.left - margin.right;
    const plotH = height - margin.top - margin.bottom;
    const xValues = rows.map(r => Number(r[metric]));
    const yValues = rows.map(r => Number(r.documentFrequency));
    const cValues = rows.map(r => Number(r.cooccurrence));
    let xMin = Math.min(...xValues), xMax = Math.max(...xValues);
    if (xMin === xMax) { xMin -= .5; xMax += .5; }
    const xPad = Math.max(.15, (xMax - xMin) * .08);
    xMin -= xPad; xMax += xPad;
    const yMax = Math.max(...yValues, 1);
    const cMax = Math.max(...cValues, 1);
    const xScale = value => margin.left + (Number(value) - xMin) / (xMax - xMin) * plotW;
    const yScale = value => margin.top + plotH - Math.log1p(Number(value)) / Math.log1p(yMax) * plotH;
    const rScale = value => 5 + 13 * Math.sqrt(Number(value) / cMax);
    const median = values => {
      const ordered = values.slice().sort((a,b) => a-b);
      const mid = Math.floor(ordered.length / 2);
      return ordered.length % 2 ? ordered[mid] : (ordered[mid-1] + ordered[mid]) / 2;
    };
    const xMedian = median(xValues);
    const yMedian = median(yValues);

    const root = svg('svg', { viewBox:`0 0 ${width} ${height}`, class:'collocation-svg' });

    // Subtle quadrant areas distinguish concentrated from widespread associations.
    const xMidPx = xScale(xMedian), yMidPx = yScale(yMedian);
    root.appendChild(svg('rect', { x:xMidPx, y:margin.top, width:margin.left + plotW - xMidPx, height:yMidPx-margin.top, class:'collocation-quadrant strong-wide' }));
    root.appendChild(svg('rect', { x:xMidPx, y:yMidPx, width:margin.left + plotW - xMidPx, height:margin.top + plotH - yMidPx, class:'collocation-quadrant strong-narrow' }));

    const xTicks = 5;
    for (let i=0; i<=xTicks; i++) {
      const value = xMin + (xMax-xMin) * i/xTicks;
      const x = xScale(value);
      root.appendChild(svg('line', { x1:x, y1:margin.top, x2:x, y2:margin.top+plotH, class:'collocation-grid' }));
      const label = svg('text', { x, y:margin.top+plotH+22, 'text-anchor':'middle', class:'collocation-axis-tick' });
      label.textContent = value.toFixed(metric === 'pmi' ? 1 : 2);
      root.appendChild(label);
    }

    const tickCandidates = [1,2,5,10,25,50,100,250,500,1000].filter(v => v <= yMax);
    if (!tickCandidates.includes(yMax)) tickCandidates.push(yMax);
    [...new Set(tickCandidates)].forEach(value => {
      const y = yScale(value);
      root.appendChild(svg('line', { x1:margin.left, y1:y, x2:margin.left+plotW, y2:y, class:'collocation-grid' }));
      const label = svg('text', { x:margin.left-10, y:y+4, 'text-anchor':'end', class:'collocation-axis-tick' });
      label.textContent = fmt(value);
      root.appendChild(label);
    });

    root.appendChild(svg('line', { x1:xMidPx, y1:margin.top, x2:xMidPx, y2:margin.top+plotH, class:'collocation-median' }));
    root.appendChild(svg('line', { x1:margin.left, y1:yMidPx, x2:margin.left+plotW, y2:yMidPx, class:'collocation-median' }));

    const axisX = svg('text', { x:margin.left+plotW/2, y:height-10, 'text-anchor':'middle', class:'collocation-axis-label' });
    axisX.textContent = `${metricLabel} association strength`;
    root.appendChild(axisX);
    const axisY = svg('text', { x:16, y:margin.top+plotH/2, transform:`rotate(-90 16 ${margin.top+plotH/2})`, 'text-anchor':'middle', class:'collocation-axis-label' });
    axisY.textContent = 'Document frequency (log scale)';
    root.appendChild(axisY);

    const q1 = svg('text', { x:margin.left+plotW-8, y:margin.top+14, 'text-anchor':'end', class:'collocation-quadrant-label' });
    q1.textContent = 'strong + widespread'; root.appendChild(q1);
    const q2 = svg('text', { x:margin.left+plotW-8, y:margin.top+plotH-8, 'text-anchor':'end', class:'collocation-quadrant-label' });
    q2.textContent = 'strong + concentrated'; root.appendChild(q2);

    const labelled = new Set(rows.slice(0, Math.min(14, rows.length)).map(r => r.collocate));
    rows.forEach((row, index) => {
      const x = xScale(row[metric]), y = yScale(row.documentFrequency), radius = rScale(row.cooccurrence);
      const group = svg('g', { class:'collocation-point', tabindex:'0', role:'button', 'aria-label':`${row.collocate}, ${metricLabel} ${Number(row[metric]).toFixed(2)}, ${row.documentFrequency} documents` });
      const circle = svg('circle', { cx:x, cy:y, r:radius, class:'collocation-bubble', 'data-collocate':row.collocate });
      const tip = svg('title');
      tip.textContent = `${node} ↔ ${row.collocate}\n${metricLabel}: ${Number(row[metric]).toFixed(2)}\nCo-occurrence: ${fmt(row.cooccurrence)}\nDocuments: ${fmt(row.documentFrequency)}`;
      circle.appendChild(tip);
      group.appendChild(circle);
      if (labelled.has(row.collocate)) {
        const nearRight = x > width - 115;
        const nearLeft = x < margin.left + 90;
        const anchor = nearRight ? 'end' : nearLeft ? 'start' : 'middle';
        const labelX = nearRight ? x-radius-4 : nearLeft ? x+radius+4 : x;
        const labelY = nearRight || nearLeft ? y+4 : y-radius-6-(index%2)*3;
        const label = svg('text', { x:labelX, y:labelY, 'text-anchor':anchor, class:'collocation-label' });
        label.textContent = row.collocate;
        group.appendChild(label);
      }
      const inspect = () => openConcordance(row.collocate);
      group.addEventListener('click', inspect);
      group.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); inspect(); } });
      root.appendChild(group);
    });

    container.innerHTML = '';
    container.appendChild(root);

    $('#collocationDetails').innerHTML = rows.slice(0, 10).map((row, index) => {
      const metricValue = Number(row[metric]);
      const strength = (metricValue - xMin) / (xMax - xMin) * 100;
      const example = String(row.examples || '').split(' || ')[0];
      return `<button class="collocation-rank" data-collocate="${esc(row.collocate)}">
        <span class="collocation-rank-number">${index + 1}</span>
        <span class="collocation-rank-main">
          <strong>${esc(row.collocate)}</strong>
          <span class="collocation-meter"><i style="width:${Math.max(4, strength).toFixed(1)}%"></i></span>
          <small>${esc(example)}</small>
        </span>
        <span class="collocation-rank-stats">
          <b>${fmt(metricValue, 2)}</b><small>${metricLabel}</small>
          <b>${fmt(row.cooccurrence)}</b><small>co-occ.</small>
          <b>${fmt(row.documentFrequency)}</b><small>docs</small>
        </span>
      </button>`;
    }).join('');
    $$('[data-collocate]', $('#collocationDetails')).forEach(el => el.addEventListener('click', () => openConcordance(el.dataset.collocate)));
  }

  function renderDiscourse() {
    renderHorizontalBars($('#frameChart'), DATA.frameCounts, 'category', 'count', { limit: 12, left: 180, height: 350 });
    renderDonut($('#legitChart'), DATA.legitimationCounts, 'category', 'count');
    const selected = DATA.rhetoricalTotals.filter(r => !r.marker.startsWith('frame_') && !r.marker.startsWith('legitimation_')).slice(0, 14);
    renderHorizontalBars($('#rhetoricalChart'), selected, 'marker', 'count', { limit: 14, left: 205, height: 360 });
  }

  function renderEntities() {
    renderDonut($('#entityTypeChart'), DATA.entityLabelCounts, 'category', 'count');
    const label = $('#entityLabelFilter').value;
    const rows = DATA.topActors.filter(a => !label || a.label === label);
    renderHorizontalBars($('#actorChart'), rows, 'entity', 'frequency', { limit: 18, left: 155, height: 350 });
  }

  function renderReadability() {
    const docs = DATA.documents.filter(d => Number.isFinite(Number(d.wordCount)) && Number.isFinite(Number(d.flesch)) && d.wordCount > 0 && d.wordCount <= 5000 && d.flesch > -100 && d.flesch < 130);
    renderScatter($('#readabilityScatter'), docs, 'wordCount', 'flesch', { xLabel: 'Word count', yLabel: 'Flesch estimate', maxX: 5000, minY: -50, maxY: 120 });
    renderHistogram($('#mattrHistogram'), DATA.documents.map(d => d.mattr50).filter(v => v != null), { bins: 18 });
  }

  function initReview() {
    $('#reviewQueue').addEventListener('change', e => { state.reviewQueue = e.target.value; state.reviewIndex = 0; populateReviewCategories(); renderReview(); });
    ['reviewCategory','reviewStatusFilter','reviewQuotation'].forEach(id => $('#' + id).addEventListener('change', () => { state.reviewIndex = 0; renderReview(); }));
    $('#reviewSearch').addEventListener('input', debounce(() => { state.reviewIndex = 0; renderReview(); }, 130));
    $('#reviewerName').value = storageGet(REVIEWER_KEY, '');
    $('#reviewerName').addEventListener('input', e => storageSet(REVIEWER_KEY, e.target.value));
    $('#exportReview').addEventListener('click', exportAnnotations);
    $('#exportReviewTop').addEventListener('click', exportAnnotations);
    $('#importReview').addEventListener('change', e => importAnnotations(e.target.files[0]));
    populateReviewCategories();
    document.addEventListener('keydown', e => {
      if (state.view !== 'review' || /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) return;
      if (e.key === '1') setDecision('valid');
      if (e.key === '2') setDecision('reject');
      if (e.key === '3') setDecision('uncertain');
      if (e.key === 'ArrowRight') nextReview(1);
      if (e.key === 'ArrowLeft') nextReview(-1);
    });
  }

  function populateReviewCategories() {
    const queue = DATA.reviewQueues[state.reviewQueue] || [];
    const cats = [...new Set(queue.map(i => i.category).filter(Boolean))].sort();
    $('#reviewCategory').innerHTML = '<option value="">All categories</option>' + cats.map(c => `<option value="${esc(c)}">${esc(titleCase(c))}</option>`).join('');
  }

  function reviewStatus(id) { return state.annotations[id]?.status || 'unreviewed'; }

  function getFilteredReview() {
    const queue = DATA.reviewQueues[state.reviewQueue] || [];
    const category = $('#reviewCategory').value, status = $('#reviewStatusFilter').value;
    const quoteOnly = $('#reviewQuotation').checked, q = $('#reviewSearch').value.trim().toLowerCase();
    return queue.filter(item => {
      const doc = item.documentId ? docMap.get(item.documentId) : null;
      const text = `${item.sentence || ''} ${item.context || ''} ${item.surfaceForm || ''} ${item.category || ''} ${item.documentId || ''} ${doc?.title || ''}`.toLowerCase();
      return (!category || item.category === category) && (!status || reviewStatus(item.id) === status)
        && (!quoteOnly || item.quotation || item.reportedSpeech)
        && (!q || text.includes(q));
    });
  }

  function renderReview() {
    state.reviewFiltered = getFilteredReview();
    if (state.reviewIndex >= state.reviewFiltered.length) state.reviewIndex = Math.max(0, state.reviewFiltered.length - 1);
    const card = $('#reviewCard');
    const counts = { total: state.reviewFiltered.length, reviewed: state.reviewFiltered.filter(i => reviewStatus(i.id) !== 'unreviewed').length };
    $('#reviewMiniStats').innerHTML = `<div class="mini-stat"><strong>${fmt(counts.total)}</strong><span>Matching</span></div><div class="mini-stat"><strong>${fmt(counts.reviewed)}</strong><span>Reviewed</span></div>`;
    if (!state.reviewFiltered.length) {
      card.innerHTML = '<div class="empty-state"><div class="empty-icon">✓</div><h3>No matching candidates</h3><p>Change the filters or select another queue.</p></div>';
      return;
    }
    const item = state.reviewFiltered[state.reviewIndex], ann = state.annotations[item.id] || {}, doc = item.documentId ? docMap.get(item.documentId) : null;
    const mainText = item.sentence || item.context || item.surfaceForm || '';
    const flags = item.type === 'coded_language' ? [
      ['frequency', item.corpusFrequency], ['documents', item.documentFrequency]
    ] : [
      ['quotation', item.quotation], ['reported speech', item.reportedSpeech], ['negation', item.negation], ['passive', item.passive], ['question', item.question]
    ];
    card.innerHTML = `<div class="review-header"><div><p class="eyebrow">${esc(titleCase(item.type))}</p><h3 class="review-category">${esc(titleCase(item.category))}</h3></div><div class="review-counter">${fmt(state.reviewIndex + 1)} of ${fmt(state.reviewFiltered.length)}</div></div><div class="review-flags">${flags.map(([label,value]) => `<span class="flag ${value === true ? 'active' : ''}">${esc(label)}${typeof value === 'number' ? `: ${fmt(value)}` : ''}</span>`).join('')}</div><div class="review-text">${esc(mainText)}</div>${item.matchedTerms?.length ? `<p class="review-context"><strong>Matched terms:</strong> ${esc(item.matchedTerms.join(', '))}</p>` : ''}${item.type === 'coded_language' ? `<p class="review-context"><strong>Surface form:</strong> ${esc(item.surfaceForm)}<br><strong>Basis:</strong> ${esc(item.category)}</p>` : ''}${doc ? `<div class="review-document-link"><span><strong>${esc(doc.title)}</strong><br>${esc(dateLabel(doc.publishedAt))} · ${esc(doc.author)}</span><button data-open-doc="${esc(doc.id)}">Open document</button></div>` : ''}<div class="decision-row"><button class="decision ${ann.status === 'valid' ? 'selected' : ''}" data-status="valid">1 · Valid</button><button class="decision ${ann.status === 'reject' ? 'selected' : ''}" data-status="reject">2 · Reject</button><button class="decision ${ann.status === 'uncertain' ? 'selected' : ''}" data-status="uncertain">3 · Uncertain</button></div><label class="field"><span>Reviewer note</span><textarea id="reviewNote" rows="5" placeholder="Reason, ambiguity or context needed…">${esc(ann.note || '')}</textarea></label><div class="review-nav"><button id="reviewPrev">← Previous</button><span class="review-counter">Source status: ${esc(item.sourceStatus || 'unreviewed_candidate')}</span><button id="reviewNext">Next →</button></div>`;
    $$('.decision', card).forEach(btn => btn.addEventListener('click', () => setDecision(btn.dataset.status)));
    $('#reviewPrev').addEventListener('click', () => nextReview(-1)); $('#reviewNext').addEventListener('click', () => nextReview(1));
    $('[data-open-doc]', card)?.addEventListener('click', e => { selectDocument(e.currentTarget.dataset.openDoc); showView('explorer'); });
    $('#reviewNote').addEventListener('input', debounce(e => saveReviewNote(item.id, e.target.value), 200));
    updateReviewProgress();
  }

  function setDecision(status) {
    const item = state.reviewFiltered[state.reviewIndex]; if (!item) return;
    state.annotations[item.id] = { ...(state.annotations[item.id] || {}), status, reviewer: $('#reviewerName').value.trim(), updatedAt: new Date().toISOString(), queue: item.type, category: item.category, documentId: item.documentId || null };
    saveAnnotations(); renderReview(); toast(`Saved: ${titleCase(status)}`);
  }

  function saveReviewNote(id, note) {
    state.annotations[id] = { ...(state.annotations[id] || {}), note, reviewer: $('#reviewerName').value.trim(), updatedAt: new Date().toISOString() };
    saveAnnotations();
  }

  function nextReview(delta) {
    if (!state.reviewFiltered.length) return;
    state.reviewIndex = Math.max(0, Math.min(state.reviewFiltered.length - 1, state.reviewIndex + delta)); renderReview();
  }

  function exportAnnotations() {
    const rows = Object.entries(state.annotations).map(([id, ann]) => ({ id, ...ann }));
    const payload = { metadata: { exportedAt: new Date().toISOString(), corpusSha256: DATA.quality.security.sha256, dashboardVersion: '1.0' }, annotations: rows };
    downloadBlob(JSON.stringify(payload, null, 2), `pa_human_review_${new Date().toISOString().slice(0,10)}.json`, 'application/json');
    const csvHeader = ['id','queue','category','documentId','status','reviewer','note','updatedAt'];
    const csv = [csvHeader.join(','), ...rows.map(r => csvHeader.map(k => csvCell(r[k])).join(','))].join('\n');
    downloadBlob(csv, `pa_human_review_${new Date().toISOString().slice(0,10)}.csv`, 'text/csv');
    toast(`Exported ${fmt(rows.length)} annotations as JSON and CSV.`);
  }

  function csvCell(value) { const s = String(value ?? ''); return `"${s.replace(/"/g,'""')}"`; }
  function downloadBlob(content, filename, type) { const url = URL.createObjectURL(new Blob([content], { type })); const a = document.createElement('a'); a.href = url; a.download = filename; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }

  async function importAnnotations(file) {
    if (!file) return;
    try {
      const payload = JSON.parse(await file.text());
      const rows = Array.isArray(payload) ? payload : payload.annotations;
      if (!Array.isArray(rows)) throw new Error('No annotations array found');
      rows.forEach(row => { if (row.id) { const { id, ...rest } = row; state.annotations[id] = rest; } });
      saveAnnotations(); renderReview(); toast(`Imported ${fmt(rows.length)} annotations.`);
    } catch (err) { toast(`Import failed: ${err.message}`); }
  }

  function initQuality() {
    const s = DATA.quality.security;
    $('#integrityGrid').innerHTML = [
      ['Valid records', fmt(s.validRecords)], ['Parse errors', fmt(s.parseErrors)], ['Duplicate IDs', fmt(s.duplicateIds)], ['High-confidence hits', fmt(s.highConfidenceHits)], ['Contextual alerts', fmt(s.contextualHits)], ['Size', `${fmt(s.sizeBytes / 1024 / 1024, 2)} MB`]
    ].map(([label,value]) => `<div class="integrity-item"><strong>${esc(value)}</strong><span>${esc(label)}</span></div>`).join('');
    $('#securityAssessment').textContent = s.assessment;
    const q = DATA.quality.deduplication;
    $('#qualityList').innerHTML = [
      ['Strict UTF-8 and valid JSONL', 'Pass'], ['Exact duplicate groups', fmt(q.exact_duplicate_groups ?? 0)], ['Near-duplicate pairs', fmt(q.near_duplicate_pairs ?? 0)], ['Missing publication dates', fmt(DATA.summary.missingDates)], [`Dates after ${DATA.meta.referenceDate}`, fmt(DATA.summary.futureDates)], ['Automatic deletion', 'None']
    ].map(([label,value]) => `<div class="quality-item"><span>${esc(label)}</span><span>${esc(value)}</span></div>`).join('');
    const issues = DATA.documents.filter(d => d.dateFlag !== 'ok');
    $('#dateIssueTable').innerHTML = issues.map(d => `<tr><td><span class="status-pill">${esc(d.dateFlag)}</span></td><td>${esc(dateLabel(d.publishedAt))}</td><td>${esc(d.title)}</td><td>${esc(d.author)}</td><td><code>${esc(d.id)}</code></td></tr>`).join('');
    $('#hashBlock').innerHTML = [['MD5',s.md5],['SHA-1',s.sha1],['SHA-256',s.sha256]].map(([label,value]) => `<div class="hash-row"><strong>${label}</strong><code>${esc(value)}</code><button class="copy-button" data-copy="${esc(value)}">Copy</button></div>`).join('');
    $$('.copy-button').forEach(btn => btn.addEventListener('click', async () => { await navigator.clipboard.writeText(btn.dataset.copy); toast('Hash copied.'); }));
    $('#openDateFlags').addEventListener('click', () => { $('#dateFlagFilter').value = 'issue'; applyDocumentFilters(); showView('explorer'); });
  }

  function initFileInputs() {
    $('#articleFile').addEventListener('change', e => importArticles(e.target.files[0]));
  }

  function init() {
    $('#generatedAt').textContent = `Built ${new Date(DATA.meta.generatedAt).toLocaleDateString('en-GB')}`;
    initNavigation(); renderKpis(); updateReviewProgress(); renderOverviewCharts();
    initDocumentExplorer(); initNlp(); initReview(); initQuality(); initFileInputs();
    window.addEventListener('resize', debounce(() => { if (state.view === 'overview') renderOverviewCharts(); if (state.view === 'nlp') renderNlpTab(); }, 180));
  }

  init();
})();
