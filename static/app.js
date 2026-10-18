'use strict';

/* ---------------- 基础工具 ---------------- */
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));
const fmt = (v, d = 2) => (v === null || v === undefined || Number.isNaN(Number(v)))
  ? '—' : Number(v).toFixed(d);
const pct = (v) => (v === null || v === undefined || Number.isNaN(Number(v)))
  ? '—' : (Number(v) > 0 ? '+' : '') + Number(v).toFixed(2) + '%';
const dirCls = (v) => (Number(v) > 0 ? 'up' : (Number(v) < 0 ? 'down' : ''));
const esc = (s) => String(s === null || s === undefined ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

const app = {
  state: null,          // /api/state 的最新结果
  current: null,        // 当前个股代码
  bars: [],             // 当前个股 K 线
  analysis: null,       // 当前个股分析
  lastMeta: null,
  mode: 'day',          // day = 日K，minute = 分时
  period: 'day',        // day / week / month（K 线周期）
  filter: '',           // 自选股过滤关键字
  sortKey: '',          // 表头排序字段
  sortDir: 'desc',
  limitsOn: true,       // 显示涨跌停参考线
  costOn: true,         // 显示持仓成本线
  costOf(code) {
    const pf = (app.state && app.state.portfolio) || {};
    const positions = pf.positions || {};
    if (Array.isArray(positions)) {
      const row = positions.find((item) => item && item.code === code);
      return row ? Number(row.avg_cost) || 0 : 0;
    }
    const row = positions[code];          // 字典形态的 key 就是代码
    return row ? Number(row.avg_cost) || 0 : 0;
  },
  lastQuote: null,      // 最近一次行情（广播给其它标签用）
  minute: null,         // 分时数据 {date, prev_close, points}
  geomMinute: null,
};

// 详情页请求序号：只认最后一次请求的结果，避免慢返回的旧数据盖掉刚点的股票
let detailSeq = 0;

async function api(path, opts) {
  // 演示快照模式：static/demo.html 内联了录制好的响应，直接返回，不打扰网络。
  if (window.__DEMO__) {
    if ((!opts || !opts.method || opts.method === 'GET')
        && Object.prototype.hasOwnProperty.call(window.__DEMO__, path)) {
      return window.__DEMO__[path];
    }
    // 演示页里没内联的请求：明确说清楚，别让用户以为服务挂了，也别去 fetch（file:// 下必失败）
    return { ok: false, demoMissing: true,
             error: '演示快照没收录这个请求（只内联了部分股票的数据）。'
               + '要看实时数据，请双击「启动.cmd」后打开 http://127.0.0.1:8770/' };
  }
  try {
    const res = await fetch(path, opts);
    const text = await res.text();
    try { return JSON.parse(text); } catch (e) {
      return { ok: false, error: '非 JSON 响应：' + text.slice(0, 120) };
    }
  } catch (e) {
    const where = (window.location && window.location.origin) || '本地服务';
    return { ok: false, network: true,
             error: '连不上 ' + where + '（' + e.message + '）。'
               + '确认「启动.cmd」那个窗口还开着，然后刷新页面。' };
  }
}

/* ---------------- 指标（仅供画图；服务端另有实现并已测试） ---------------- */
function smaSeries(values, n) {
  const out = new Array(values.length).fill(null);
  let sum = 0;
  for (let i = 0; i < values.length; i += 1) {
    sum += values[i];
    if (i >= n) sum -= values[i - n];
    if (i >= n - 1) out[i] = sum / n;
  }
  return out;
}
function emaSeries(values, n) {
  const out = [];
  if (!values.length) return out;
  const a = 2 / (n + 1);
  out.push(values[0]);
  for (let i = 1; i < values.length; i += 1) out.push(out[i - 1] + a * (values[i] - out[i - 1]));
  return out;
}
function rsiSeries(values, n = 14) {
  const out = new Array(values.length).fill(null);
  if (values.length < n + 1) return out;
  let g = 0; let l = 0;
  for (let i = 1; i <= n; i += 1) {
    const d = values[i] - values[i - 1];
    if (d > 0) g += d; else l -= d;
  }
  g /= n; l /= n;
  const value = () => {
    if (g === 0 && l === 0) return 50;
    if (l === 0) return 100;
    return 100 - 100 / (1 + g / l);
  };
  out[n] = value();
  for (let i = n + 1; i < values.length; i += 1) {
    const d = values[i] - values[i - 1];
    g = (g * (n - 1) + (d > 0 ? d : 0)) / n;
    l = (l * (n - 1) + (d < 0 ? -d : 0)) / n;
    out[i] = value();
  }
  return out;
}
function macdSeries(values) {
  const fast = emaSeries(values, 12);
  const slow = emaSeries(values, 26);
  const dif = values.map((_, i) => fast[i] - slow[i]);
  const dea = emaSeries(dif, 9);
  const hist = dif.map((d, i) => (d - dea[i]) * 2);
  return { dif, dea, hist };
}

/* ---------------- 标签页 ---------------- */
function activateTab(name) {
  // 只切面板，不触发任何加载：避免和 loadDetail 互相递归
  try { localStorage.setItem('stock-last-tab', name); } catch (e) { /* 忽略 */ }
  $$('.tab').forEach((b) => b.classList.toggle('active', b.dataset.tab === name));
  $$('.panel').forEach((p) => p.classList.toggle('active', p.id === 'panel-' + name));
}

function switchTab(name) {
  activateTab(name);
  if (name === 'portfolio') loadPortfolio();
  if (name === 'account') loadAccount();
  if (name === 'detail' && app.current) {
    // 面板刚变可见，此时 clientWidth 才是对的：已有数据就重绘，没有才去拉
    if (app.bars && app.bars.length) {
      if (app.mode === 'minute' && app.minute) drawMinuteChart(app.minute);
      else drawPriceChart(app.bars);
    } else if (!app.detailLoading) {
      loadDetail(app.current, { silent: true });
    }
  }
}

/* ---------------- 顶部状态 ---------------- */
function renderMeta(meta) {
  const badge = $('#badge-source');
  badge.classList.remove('live', 'stale', 'demo');
  if (!meta) { badge.textContent = '未知'; return; }
  if (meta.demo) { badge.textContent = '演示数据（本地样本）'; badge.classList.add('demo'); }
  else if (meta.stale) { badge.textContent = '缓存数据'; badge.classList.add('stale'); }
  else { badge.textContent = '实时 · ' + (meta.source || '接口'); badge.classList.add('live'); }
  $('#badge-time').textContent = app.state && app.state.server_time
    ? '刷新于 ' + app.state.server_time : '';
}

/* ---------------- 自选股 ---------------- */
async function refresh() {
  const s = await api('/api/state');
  if (!s.ok) { $('#badge-source').textContent = '加载失败：' + (s.error || ''); return; }
  app.state = s;
  app.lastMeta = s.meta;
  renderMeta(s.meta);
  renderMarket(s.market);
  renderWatchlist();
  checkAlerts();
}

function renderMarket(m) {
  const el = $('#badge-market');
  if (!el) return;
  if (!m) { el.textContent = '—'; el.className = 'badge'; return; }
  const cls = m.status === 'trading' ? 'live'
    : (m.status === 'closed_data' ? 'stale' : '');
  el.textContent = m.label;
  el.className = 'badge' + (cls ? ' ' + cls : '');
}

/* ---------------- 体验增强的纯函数（有单测） ---------------- */
function limitPctOf(code, name) {
  // 与后端 rules.limit_pct 同口径：创业板/科创板 20%，ST 5%，其余 10%
  const c = String(code || '');

  if (/^(300|301|688)/.test(c)) return 0.20;
  if (/ST/i.test(String(name || ''))) return 0.05;
  return 0.10;
}

function aggregateBars(bars, period) {
  if (!bars || !bars.length || !period || period === 'day') return bars || [];
  const out = [];
  let cur = null;
  bars.forEach((b) => {
    const d = String(b.date || '');
    let key;
    if (period === 'week') {
      const dt = new Date(d + 'T00:00:00');
      dt.setDate(dt.getDate() - ((dt.getDay() + 6) % 7));   // 归到周一
      key = dt.toISOString().slice(0, 10);
    } else {
      key = d.slice(0, 7);                                   // 按月
    }
    if (!cur || cur.key !== key) {
      cur = { key: key, date: d, open: b.open, high: b.high, low: b.low,
              close: b.close, volume: b.volume || 0 };
      out.push(cur);
    } else {
      cur.date = d;
      cur.high = Math.max(cur.high, b.high);
      cur.low = Math.min(cur.low, b.low);
      cur.close = b.close;
      cur.volume = (cur.volume || 0) + (b.volume || 0);
    }
  });
  return out.map((row) => ({
    date: row.date, open: row.open, high: row.high, low: row.low,
    close: row.close, volume: row.volume,
  }));
}

function sortQuotes(list, key, dir) {
  const arr = (list || []).slice();
  if (!key) return arr;
  const sign = dir === 'asc' ? 1 : -1;
  arr.sort((a, b) => {
    const va = a[key];
    const vb = b[key];
    if (typeof va === 'string' || typeof vb === 'string') {
      return sign * String(va == null ? '' : va).localeCompare(String(vb == null ? '' : vb), 'zh');
    }
    return sign * ((Number(va) || 0) - (Number(vb) || 0));
  });
  return arr;
}

function matchQuote(q, keyword) {
  const k = String(keyword || '').trim().toLowerCase();
  if (!k) return true;
  return String(q.code || '').toLowerCase().includes(k)
    || String(q.name || '').toLowerCase().includes(k);
}

function ensureWatchRow(q) {
  const tbody = $('#watchlist-table tbody');
  let tr = tbody.querySelector('tr[data-code="' + q.code + '"]');
  if (!tr) {
    tr = document.createElement('tr');
    tr.dataset.code = q.code;
    tr.innerHTML = '<td class="c-code"></td><td class="c-name"></td>'
      + '<td class="num c-price"></td><td class="num c-change"></td><td class="num c-pct"></td>'
      + '<td class="num c-high"></td><td class="num c-low"></td><td class="num c-vol"></td>'
      + '<td><button class="btn" data-act="detail" data-code="' + q.code + '">看</button> '
      + '<button class="btn" data-act="remove" data-code="' + q.code + '">移除</button></td>';
    tr.addEventListener('click', (ev) => {
      if (ev.target.closest('button')) return;   // 点按钮时不要触发整行进个股
      loadDetail(tr.dataset.code);
    });
    tbody.appendChild(tr);
  }
  return tr;
}

// 增量更新：5 秒刷新只改文字，不重建表格（旧版整表 innerHTML 会闪、还会丢鼠标悬停）
function renderWatchlist(quotesIn) {
  const tbody = $('#watchlist-table tbody');
  const all = quotesIn || (app.state && app.state.quotes) || [];
  const quotes = sortQuotes(all.filter((q) => matchQuote(q, app.filter)),
    app.sortKey, app.sortDir);
  const seen = new Set();
  quotes.forEach((q) => {
    seen.add(q.code);
    const tr = ensureWatchRow(q);
    const cls = dirCls(q.change);
    const set = (sel, text, extraCls) => {
      const cell = tr.querySelector(sel);
      if (!cell) return;
      cell.textContent = text;
      if (extraCls !== undefined) cell.className = 'num ' + sel.slice(1) + ' ' + cls;
    };
    tr.querySelector('.c-code').textContent = q.code;
    tr.querySelector('.c-name').textContent = q.name;
    set('.c-price', fmt(q.price), true);
    set('.c-change', fmt(q.change), true);
    set('.c-pct', pct(q.change_pct), true);
    tr.querySelector('.c-high').textContent = fmt(q.high);
    tr.querySelector('.c-low').textContent = fmt(q.low);
    tr.querySelector('.c-vol').textContent = fmt(q.volume, 0);
  });
  Array.from(tbody.querySelectorAll('tr[data-code]')).forEach((tr) => {
    if (!seen.has(tr.dataset.code)) tr.remove();
  });
  // 按当前排序把行挪到正确位置（appendChild 会移动已有节点）
  quotes.forEach((q) => {
    const tr = tbody.querySelector('tr[data-code="' + q.code + '"]');
    if (tr) tbody.appendChild(tr);
  });
  const filterNote = $('#watch-filter-note');
  if (filterNote) {
    const total = (app.state && app.state.quotes ? app.state.quotes.length : quotes.length);
    filterNote.textContent = app.filter ? ('过滤出 ' + quotes.length + ' / ' + total + ' 只') : '';
  }
  let note = quotes.length
    ? `共 ${quotes.length} 只；行情时间 ${quotes[0].timestamp || '—'}（点「看」进个股）`
    : '自选股为空，用上面的搜索框加几只。';
  const mk = app.state && app.state.market;
  if (mk && mk.status !== 'trading') note += ` · ${mk.label}，显示的是最近一次收盘数据`;
  $('#watchlist-note').textContent = note;
}

async function addToWatchlist(code) {
  const list = ((app.state && app.state.watchlist) || []).slice();
  if (!list.includes(code)) list.push(code);
  const res = await api('/api/watchlist', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ codes: list }),
  });
  if (res.ok) refresh();
}

async function removeFromWatchlist(code) {
  const list = ((app.state && app.state.watchlist) || []).filter((c) => c !== code);
  const res = await api('/api/watchlist', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ codes: list }),
  });
  if (res.ok) refresh();
}

async function doSearch() {
  const q = $('#search-input').value.trim();
  if (!q) return;
  const box = $('#search-result');
  box.innerHTML = '<span class="muted small">搜索中…</span>';
  const res = await api('/api/search?q=' + encodeURIComponent(q));
  if (!res.ok || !(res.rows || []).length) {
    box.innerHTML = '<span class="muted small">没找到（接口不可达时只能按代码手输）</span>';
    return;
  }
  box.innerHTML = res.rows.map((r) => `
    <span class="hit">${esc(r.code)} ${esc(r.name)}
      <button class="btn" data-add="${r.code}">加自选</button>
    </span>`).join('');
}

/* ---------------- 个股 ---------------- */
function setDetailStatus(text, kind) {
  const el = $('#detail-status');
  if (!el) return;
  el.dataset.base = text || '';
  el.dataset.kind = kind || '';
  el.textContent = text || '';
  el.className = 'small ' + (kind === 'err' ? 'down' : (kind === 'ok' ? 'muted' : 'muted'));
}

function showDetailError(code, reason) {
  $('#detail-title').textContent = code + '：暂时拿不到数据';
  $('#detail-sub').textContent = '';
  setDetailStatus('原因：' + (reason || '未知') + '（上游偶发抖动很常见，点「重试」通常就好）', 'err');
  const btn = $('#btn-detail-retry');
  if (btn) btn.hidden = false;
  const legend = $('#chart-legend');
  if (legend) legend.innerHTML = '';
}

async function fetchDetail(code) {
  const delays = [0, 900, 1800];   // 首试 + 两次退避重试
  let last = '';
  for (let i = 0; i < delays.length; i += 1) {
    if (delays[i]) {
      setDetailStatus(`第 ${i + 1} 次重试中…（上次：${last}）`);
      await new Promise((resolve) => setTimeout(resolve, delays[i]));
    }
    const [k, a] = await Promise.all([
      api('/api/kline?code=' + encodeURIComponent(code) + '&limit=320'),
      api('/api/analysis?code=' + encodeURIComponent(code)),
    ]);
    if (k.ok && (k.bars || []).length) return { ok: true, k, a };
    if (k.demoMissing || k.network) return { ok: false, reason: k.error };
    last = (k.meta && k.meta.errors && k.meta.errors.join('；')) || k.error || '空数据';
  }
  return { ok: false, reason: last };
}

async function loadDetail(code, opts) {
  opts = opts || {};
  app.detailLoading = true;
  const seq = ++detailSeq;
  app.current = code;
  try { localStorage.setItem('stock-last-code', code); } catch (e) { /* 忽略 */ }
  if (!opts.silent) activateTab('detail');   // 只切面板，不递归
  try {
  $('#detail-title').textContent = '加载中…';
  setDetailStatus('正在获取行情…');
  const btn = $('#btn-detail-retry');
  if (btn) btn.hidden = true;

  const got = await fetchDetail(code);
  if (seq !== detailSeq) return;   // 期间又点了别的票：丢弃这次结果
  if (!got.ok) { showDetailError(code, got.reason); return; }

  const k = got.k;
  const a = got.a;
  app.bars = k.bars;
  app.analysis = a.ok ? a.analysis : null;
  renderDetail(a.ok ? a.quote : null, k);
  analysisFetchedAt = Date.now();
  setDetailStatus('已加载 ' + k.bars.length + ' 根 K 线 · 来源 '
    + ((k.meta && k.meta.source) || '?')
    + (k.meta && k.meta.cached ? '（缓存 ' + (k.meta.age || 0) + 's）' : '')
    + (k.meta && k.meta.stale ? '（离线缓存）' : ''), 'ok');
  if (app.mode === 'minute') loadMinute(code);
  else drawPriceChart(k.bars);
  renderAnalysis(app.analysis);
  } finally {
    app.detailLoading = false;
  }
}

function renderDetail(quote, k) {
  const last = (quote && quote.price) || k.bars[k.bars.length - 1].close;
  const change = quote ? quote.change : null;
  const changePct = quote ? quote.change_pct : null;
  $('#detail-title').textContent = quote
    ? `${quote.name} ${quote.code}` : k.code;
  $('#detail-sub').textContent = quote
    ? `行情时间 ${quote.timestamp || '—'} · 昨收 ${fmt(quote.prev_close)} · 涨停 ${fmt(quote.limit_up)} / 跌停 ${fmt(quote.limit_down)}`
    : '仅 K 线数据（行情接口不可达）';
  $('#detail-price').innerHTML = `<span class="${dirCls(change)}">${fmt(last)}</span>`
    + ` <span class="small ${dirCls(change)}">${fmt(change)} / ${pct(changePct)}</span>`;
  const issues = k.clean_issues || [];
  $('#chart-legend').innerHTML = [
    '<span>K 线 ' + (k.meta && k.meta.source ? k.meta.source : '') + '</span>',
    '<span>MA5</span><span>MA20</span><span>MA60</span>',
    `<span>${issues.length ? '数据校验：' + issues.length + ' 条提示（见控制台）' : '数据校验：通过'}</span>`,
  ].join('');
  if (issues.length) console.warn('数据校验提示', issues);
}

function renderAnalysis(ana) {
  if (!ana) {
    $('#ai-source').textContent = '不可用';
    $('#ai-stance').textContent = '';
    $('#ai-bullets').innerHTML = '<li>分析接口不可用</li>';
    $('#ai-risks').innerHTML = '';
    $('#ai-disclaimer').textContent = '';
    return;
  }
  const source = ana.source === 'llm'
    ? ('模型：' + (ana.model || '已配置'))
    : '规则引擎（本地）';
  $('#ai-source').textContent = source;
  const cls = ana.stance === '偏多' ? 'up' : (ana.stance === '偏空' ? 'down' : '');
  $('#ai-stance').innerHTML = `<span class="${cls}">${esc(ana.stance)}</span>`
    + ` <span class="muted small">规则分 ${ana.score}</span>`;
  // 模型解读单独一块：保留换行，标题写明是哪个模型
  const modelEl = $('#ai-model');
  if (modelEl) {
    if (ana.llm && ana.llm.ok && ana.llm.text) {
      modelEl.hidden = false;
      modelEl.innerHTML = '<div class="ai-model-head">大白话解读 · '
        + esc(ana.model || '模型') + '</div><div class="ai-model-text">'
        + esc(ana.llm.text) + '</div>';
    } else {
      modelEl.hidden = true;
      modelEl.innerHTML = '';
    }
  }
  const bullets = (ana.bullets || []).slice();
  if (ana.llm_note) bullets.unshift(ana.llm_note);
  $('#ai-bullets').innerHTML = bullets.map((b) => `<li>${esc(b)}</li>`).join('');
  $('#ai-risks').innerHTML = (ana.risks || []).map((r) => `<div>⚠ ${esc(r)}</div>`).join('');
  $('#ai-disclaimer').textContent = ana.disclaimer || '';
}

/* ---------------- 画图 ---------------- */
function setupCanvas(canvas, cssHeight) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth || 900;
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(cssHeight * dpr);
  canvas.style.height = cssHeight + 'px';
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, cssHeight);
  return { ctx, w, h: cssHeight };
}

function drawPriceChart(allBars, hover) {
  const canvas = $('#chart');
  if (!canvas || !allBars.length) return;
  const height = 420;   // 不做移动端适配（spec 非目标），固定桌面高度
  const { ctx, w, h } = setupCanvas(canvas, height);
  const bars = aggregateBars(allBars, app.period);   // 周/月 K 由日 K 聚合而来
  const view = bars.slice(-120);
  const closesAll = bars.map((b) => b.close);
  const ma5 = smaSeries(closesAll, 5).slice(-view.length);
  const ma20 = smaSeries(closesAll, 20).slice(-view.length);
  const ma60 = smaSeries(closesAll, 60).slice(-view.length);
  const { dif, dea, hist } = macdSeries(closesAll);
  const difV = dif.slice(-view.length);
  const deaV = dea.slice(-view.length);
  const histV = hist.slice(-view.length);
  const rsiV = rsiSeries(closesAll, 14).slice(-view.length);

  const left = 6;
  const right = 62;
  const priceTop = 6;
  const priceBottom = h * 0.56;
  const volTop = h * 0.60;
  const volBottom = h * 0.71;
  const macdTop = h * 0.75;
  const macdBottom = h * 0.87;
  const rsiTop = h * 0.91;
  const rsiBottom = h - 22;
  const plotW = w - left - right;
  const step = plotW / view.length;
  const bw = Math.max(1.5, step * 0.62);

  const hi = Math.max(...view.map((b) => b.high));
  const lo = Math.min(...view.map((b) => b.low));
  const pad = (hi - lo) * 0.04 || 1;
  const yPrice = (v) => priceBottom - (v - (lo - pad)) / ((hi + pad) - (lo - pad)) * (priceBottom - priceTop);
  const xOf = (i) => left + i * step + step / 2;

  // 网格 + 价格刻度
  ctx.font = '11px "Microsoft YaHei", sans-serif';
  ctx.strokeStyle = '#232b35';
  ctx.fillStyle = '#8b98a5';
  for (let k = 0; k <= 4; k += 1) {
    const v = (lo - pad) + ((hi + pad) - (lo - pad)) * (k / 4);
    const y = yPrice(v);
    ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(left + plotW, y); ctx.stroke();
    ctx.fillText(fmt(v), left + plotW + 6, y + 4);
  }

  // 涨跌停参考线（只在日 K，且用上一根收盘算）+ 持仓成本线
  if (app.period === 'day' && app.limitsOn && view.length >= 2) {
    const prevClose = view[view.length - 2].close;
    const pct = limitPctOf(app.current, (app.lastQuote && app.lastQuote.name) || '');
    [['涨停', prevClose * (1 + pct), '#ff5252'], ['跌停', prevClose * (1 - pct), '#26a69a']]
      .forEach((pair) => {
        const y = yPrice(pair[1]);
        if (y < priceTop || y > priceBottom) return;
        ctx.strokeStyle = pair[2]; ctx.globalAlpha = 0.5; ctx.setLineDash([4, 4]);
        ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(left + plotW, y); ctx.stroke();
        ctx.globalAlpha = 1; ctx.setLineDash([]);
        ctx.fillStyle = pair[2]; ctx.fillText(pair[0] + ' ' + fmt(pair[1]), left + 2, y - 3);
      });
  }
  const cost = app.costOf(app.current);
  if (app.costOn && cost > 0) {
    const y = yPrice(cost);
    if (y >= priceTop && y <= priceBottom) {
      ctx.strokeStyle = '#f0d17e'; ctx.setLineDash([2, 3]);
      ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(left + plotW, y); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = '#f0d17e'; ctx.fillText('成本 ' + fmt(cost), left + 2, y + 12);
    }
  }

  // K 线
  view.forEach((b, i) => {
    const up = b.close >= b.open;
    ctx.strokeStyle = up ? '#ff5252' : '#26a69a';
    ctx.fillStyle = up ? '#ff5252' : '#26a69a';
    const x = xOf(i);
    ctx.beginPath();
    ctx.moveTo(x, yPrice(b.high));
    ctx.lineTo(x, yPrice(b.low));
    ctx.stroke();
    const y1 = yPrice(Math.max(b.open, b.close));
    const y2 = yPrice(Math.min(b.open, b.close));
    ctx.fillRect(x - bw / 2, y1, bw, Math.max(1, y2 - y1));
  });

  // 均线
  const drawLine = (series, color) => {
    ctx.strokeStyle = color; ctx.lineWidth = 1.2; ctx.beginPath();
    let started = false;
    series.forEach((v, i) => {
      if (v === null || Number.isNaN(v)) return;
      const x = xOf(i); const y = yPrice(v);
      if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
    });
    ctx.stroke();
  };
  drawLine(ma5, '#f0d17e');
  drawLine(ma20, '#7aa2f7');
  drawLine(ma60, '#c99cf5');

  // 成交量
  const vmax = Math.max(...view.map((b) => b.volume || 0)) || 1;
  view.forEach((b, i) => {
    const up = b.close >= b.open;
    ctx.fillStyle = up ? 'rgba(255,82,82,0.55)' : 'rgba(38,166,154,0.55)';
    const hgt = ((b.volume || 0) / vmax) * (volBottom - volTop);
    ctx.fillRect(xOf(i) - bw / 2, volBottom - hgt, bw, hgt);
  });
  ctx.fillStyle = '#8b98a5';
  ctx.fillText('成交量', left + 2, volTop - 3);

  // MACD
  const mMax = Math.max(1e-6, ...histV.map((v) => Math.abs(v)));
  const yMacd = (v) => (macdTop + macdBottom) / 2 - (v / mMax) * ((macdBottom - macdTop) / 2);
  ctx.strokeStyle = '#232b35';
  ctx.beginPath(); ctx.moveTo(left, yMacd(0)); ctx.lineTo(left + plotW, yMacd(0)); ctx.stroke();
  histV.forEach((v, i) => {
    ctx.fillStyle = v >= 0 ? 'rgba(255,82,82,0.8)' : 'rgba(38,166,154,0.8)';
    const y = yMacd(v);
    ctx.fillRect(xOf(i) - bw / 2, Math.min(y, yMacd(0)), bw, Math.abs(y - yMacd(0)) || 1);
  });
  const yMacdLine = (v) => yMacd(v);
  const drawMacdLine = (series, color) => {
    ctx.strokeStyle = color; ctx.lineWidth = 1.1; ctx.beginPath();
    let started = false;
    series.forEach((v, i) => {
      const x = xOf(i); const y = yMacdLine(v);
      if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
    });
    ctx.stroke();
  };
  drawMacdLine(difV, '#f0d17e');
  drawMacdLine(deaV, '#7aa2f7');
  ctx.fillStyle = '#8b98a5';
  ctx.fillText('MACD(12,26,9)', left + 2, macdTop - 3);

  // RSI
  const yRsi = (v) => rsiBottom - (v / 100) * (rsiBottom - rsiTop);
  ctx.strokeStyle = '#232b35';
  [30, 70].forEach((lvl) => {
    ctx.beginPath(); ctx.moveTo(left, yRsi(lvl)); ctx.lineTo(left + plotW, yRsi(lvl)); ctx.stroke();
  });
  ctx.strokeStyle = '#c99cf5'; ctx.lineWidth = 1.2; ctx.beginPath();
  let started = false;
  rsiV.forEach((v, i) => {
    if (v === null) return;
    const x = xOf(i); const y = yRsi(v);
    if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.fillStyle = '#8b98a5';
  ctx.fillText('RSI(14)', left + 2, rsiTop - 3);
  ctx.fillText('70', left + plotW + 6, yRsi(70) + 4);
  ctx.fillText('30', left + plotW + 6, yRsi(30) + 4);

  // 日期刻度（底部）
  ctx.fillStyle = '#6b7785';
  ctx.font = '11px "Microsoft YaHei", sans-serif';
  for (let k = 0; k < 6; k += 1) {
    const idx = Math.round((view.length - 1) * k / 5);
    if (!view[idx]) continue;
    const label = String(view[idx].date).slice(5);
    const x = Math.min(Math.max(xOf(idx) - 16, left), left + plotW - 34);
    ctx.fillText(label, x, h - 6);
  }

  // 记录几何信息，供十字光标与悬浮提示使用
  app.geom = {
    left, plotW, step, view,
    priceTop, priceBottom, rsiTop, rsiBottom,
    yPrice, yRsi, ma5, ma20, ma60, rsiV, difV, deaV, histV,
  };

  // 十字光标（鼠标位置）
  if (hover !== null && hover !== undefined && view[hover]) {
    const b = view[hover];
    const x = xOf(hover);
    const y = yPrice(b.close);
    ctx.strokeStyle = 'rgba(230,237,243,0.55)';
    ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(x, priceTop); ctx.lineTo(x, rsiBottom); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(left + plotW, y); ctx.stroke();
    ctx.setLineDash([]);
    const label = fmt(b.close);
    const wLabel = ctx.measureText(label).width + 10;
    ctx.fillStyle = '#2f81f7';
    ctx.fillRect(left + plotW + 2, y - 9, wLabel, 18);
    ctx.fillStyle = '#fff';
    ctx.fillText(label, left + plotW + 6, y + 4);
  }
}

function drawEquityChart(curve) {
  const canvas = $('#bt-chart');
  if (!canvas || !curve.length) return;
  const { ctx, w, h } = setupCanvas(canvas, 220);
  const left = 6; const right = 68; const top = 10; const bottom = h - 10;
  const plotW = w - left - right;
  const values = curve.map((p) => p.cash);
  const hi = Math.max(...values); const lo = Math.min(...values);
  const pad = (hi - lo) * 0.08 || 1;
  const y = (v) => bottom - (v - (lo - pad)) / ((hi + pad) - (lo - pad)) * (bottom - top);
  const step = plotW / Math.max(1, values.length - 1);
  ctx.strokeStyle = '#232b35';
  for (let k = 0; k <= 3; k += 1) {
    const v = (lo - pad) + ((hi + pad) - (lo - pad)) * (k / 3);
    const yy = y(v);
    ctx.beginPath(); ctx.moveTo(left, yy); ctx.lineTo(left + plotW, yy); ctx.stroke();
    ctx.fillStyle = '#8b98a5';
    ctx.font = '11px "Microsoft YaHei", sans-serif';
    ctx.fillText(fmt(v, 0), left + plotW + 6, yy + 4);
  }
  ctx.strokeStyle = '#7aa2f7'; ctx.lineWidth = 1.6; ctx.beginPath();
  values.forEach((v, i) => {
    const x = left + i * step;
    if (i === 0) ctx.moveTo(x, y(v)); else ctx.lineTo(x, y(v));
  });
  ctx.stroke();
  ctx.fillStyle = '#8b98a5';
  ctx.fillText('资金曲线', left + 2, top);
}

/* ---------------- 下单 ---------------- */
async function submitOrder() {
  const msg = $('#order-msg');
  if (!app.current) { msg.className = 'msg err'; msg.textContent = '先在自选股里选一只票'; return; }
  const side = $('#order-side').value;
  const sharesRaw = String($('#order-shares').value).trim();
  const shares = Number(sharesRaw);
  const priceRaw = String($('#order-price').value).trim();
  if (!Number.isInteger(shares) || shares <= 0) {
    msg.className = 'msg err';
    msg.textContent = '股数必须是正整数（100 的整数倍）';
    return;
  }
  const body = { code: app.current, side, shares };
  if (priceRaw) {
    const p = Number(priceRaw);
    if (!Number.isFinite(p) || p <= 0) {
      msg.className = 'msg err';
      msg.textContent = '价格必须是正数，或留空按最新价';
      return;
    }
    body.price = p;
  }
  msg.className = 'msg'; msg.textContent = '提交中…';
  const res = await api('/api/order', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (res.ok) {
    const t = res.trade || {};
    msg.className = 'msg ok';
    msg.textContent = `成交：${side === 'buy' ? '买入' : '卖出'} ${t.shares} 股 @ ${fmt(t.price)}，`
      + `金额 ${fmt(t.amount)}，费用 ${fmt(t.fee)}（佣金 ${fmt(t.fee_detail && t.fee_detail.commission)} / `
      + `印花 ${fmt(t.fee_detail && t.fee_detail.stamp)} / 过户 ${fmt(t.fee_detail && t.fee_detail.transfer)}）`;
    refresh();
  } else {
    const map = {
      LOT_SIZE: '买入必须是 100 股的整数倍',
      T_PLUS_1: 'T+1：今天买入的股票今天不能卖',
      PRICE_LIMIT: '价格超出涨跌停范围',
      INSUFFICIENT_CASH: '可用资金不足',
      INSUFFICIENT_SHARES: '持仓不足',
      BAD_SHARES: '股数不合法',
      DEMO_MODE: '当前是演示数据，不能下单',
    };
    msg.className = 'msg err';
    msg.textContent = '拒单：' + (map[res.reason] || res.reason || res.error || '未知原因')
      + (res.hint ? '（' + res.hint + '）' : '');
  }
}

/* ---------------- 持仓 ---------------- */
async function loadPortfolio() {
  const res = await api('/api/portfolio');
  if (!res.ok) return;
  const p = res.portfolio;
  $('#pf-total').textContent = fmt(p.total);
  $('#pf-cash').textContent = fmt(p.cash);
  $('#pf-mv').textContent = fmt(p.market_value);
  const fl = $('#pf-float');
  fl.textContent = fmt(p.floating_pnl);
  fl.className = dirCls(p.floating_pnl);
  const rl = $('#pf-real');
  rl.textContent = fmt(p.realized_pnl);
  rl.className = dirCls(p.realized_pnl);

  $('#pf-table tbody').innerHTML = (p.positions || []).map((r) => `
    <tr>
      <td>${esc(r.code)}</td><td>${esc(r.name)}</td>
      <td class="num">${r.shares}</td><td class="num">${r.available}</td>
      <td class="num">${fmt(r.avg_cost)}</td><td class="num">${fmt(r.last)}</td>
      <td class="num">${fmt(r.market_value)}</td>
      <td class="num">${fmt(p.total > 0 ? (r.market_value / p.total * 100) : 0)}%</td>
      <td class="num ${dirCls(r.pnl)}">${fmt(r.pnl)}</td>
      <td class="num ${dirCls(r.pnl)}">${fmt(r.pnl_pct)}%</td>
    </tr>`).join('') || '<tr><td colspan="10" class="muted">还没有持仓（模拟盘初始 20 万）</td></tr>';

  $('#trades-table tbody').innerHTML = (res.trades || []).slice().reverse().map((t) => `
    <tr>
      <td>${esc(t.day)}</td><td>${esc(t.code)}</td>
      <td class="${t.side === 'buy' ? 'up' : 'down'}">${t.side === 'buy' ? '买入' : '卖出'}</td>
      <td class="num">${fmt(t.price)}</td><td class="num">${t.shares}</td>
      <td class="num">${fmt(t.amount)}</td><td class="num">${fmt(t.fee)}</td>
    </tr>`).join('') || '<tr><td colspan="7" class="muted">还没有成交</td></tr>';
}



/* ---------------- 开机启动动画（科幻访问认证） ---------------- */
let splashRaf = null;
let splashStart = 0;
let bootStep = 0;
let bootFinished = false;
let bootVerifying = false;

const BOOT_STEPS = [
  {
    title: '身份核验',
    desc: '请确认你是本机操作员。系统会用这个身份记录模拟交易，不与任何真实账户关联。',
    btn: '确认身份', log: '身份核验通过 · OPERATOR-LOCAL', verify: '正在比对本地密钥…', ms: 1100,
  },
  {
    title: '行情数据授权',
    desc: '本系统会访问公网行情接口（腾讯为主、新浪备用），只在你点击时请求。数据可能延迟，不保证实时。',
    btn: '授予访问权限', log: '行情数据访问已授权 · READ-ONLY', verify: '正在建立只读通道…', ms: 1300,
  },
  {
    title: '风险告知',
    desc: '这是模拟盘：不接券商、不下真实订单、不碰真钱；AI 解读与分析结果均不构成投资建议。',
    btn: '我已了解并进入', log: '风险确认完成 · ACK', verify: '正在写入授权记录…', ms: 1000,
  },
];

/* --- 背景：代码雨 / 雷达 / 网格 / 蜡烛 / 粒子 --- */
function splashSeed() {
  let s = 20261018;
  return () => { s = (s * 1103515245 + 12345) % 2147483648; return s / 2147483648; };
}

function splashSeries(n) {
  const count = n || 18;
  const base = [42, 47, 45, 52, 58, 54, 61, 67, 63, 70, 76, 72, 80, 86, 82, 90, 96, 103, 99, 108];
  return base.slice(0, count).map((cv, i) => {
    const open = i === 0 ? cv - 4 : base[i - 1];
    return { open: open, close: cv, high: Math.max(open, cv) + 2 + (i % 4),
             low: Math.min(open, cv) - 2 - (i % 3), up: cv >= open };
  });
}

const splashBars = splashSeries(18);
const SPLASH_CHARS = '01ABCDEF0123456789<>/\\|=+-*';
const splashRain = (() => {
  const rnd = splashSeed();
  return Array.from({ length: 54 }, () => ({
    x: rnd(), y: rnd(), speed: 0.05 + rnd() * 0.12,
    len: 4 + Math.floor(rnd() * 7), alpha: 0.10 + rnd() * 0.28,
  }));
})();
const splashDots = (() => {
  const rnd = splashSeed();
  return Array.from({ length: 40 }, () => ({
    x: rnd(), y: rnd(), r: 0.6 + rnd() * 1.6, speed: 0.15 + rnd() * 0.45,
  }));
})();

function startSplash() {
  const el = $('#splash');
  const canvas = $('#splash-canvas');
  if (!el || !canvas) return;
  const ctx = canvas.getContext('2d');
  splashStart = performance.now();
  const fixed = typeof window.__SPLASH_T__ === 'number' ? window.__SPLASH_T__ : null;

  const draw = (now) => {
    if (!el.isConnected) return;
    const t = fixed === null ? Math.min(1, (now - splashStart) / 2400) : fixed;
    const clock = fixed === null ? (now - splashStart) / 1000 : fixed * 3;
    const w = canvas.clientWidth || window.innerWidth;
    const h = canvas.clientHeight || window.innerHeight;
    const dpr = window.devicePixelRatio || 1;
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    ctx.clearRect(0, 0, w, h);

    // 1) 代码雨
    ctx.font = '12px Consolas, monospace';
    splashRain.forEach((col) => {
      const x = col.x * w;
      const y0 = ((col.y + clock * col.speed) % 1) * h;
      for (let k = 0; k < col.len; k += 1) {
        const y = y0 + k * 14;
        if (y > h - 20) continue;
        const idx = (Math.floor(col.x * 97) + k + Math.floor(clock * 6)) % SPLASH_CHARS.length;
        ctx.globalAlpha = col.alpha * (1 - k / col.len);
        ctx.fillStyle = k === 0 ? '#bff0ff' : '#4d9fd8';
        ctx.fillText(SPLASH_CHARS[idx], x, y);
      }
    });
    ctx.globalAlpha = 1;

    // 2) 雷达（右上）
    const cx = w * 0.82;
    const cy = h * 0.30;
    const R = Math.min(w, h) * 0.16;
    for (let i = 1; i <= 3; i += 1) {
      ctx.strokeStyle = 'rgba(90,180,255,.10)';
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.arc(cx, cy, (R * i) / 3, 0, Math.PI * 2); ctx.stroke();
    }
    const sweep = (clock * 1.5) % (Math.PI * 2);
    const grad = ctx.createConicGradient ? ctx.createConicGradient(sweep, cx, cy) : null;
    if (grad) {
      grad.addColorStop(0, 'rgba(120,200,255,.32)');
      grad.addColorStop(0.12, 'rgba(120,200,255,0)');
      grad.addColorStop(1, 'rgba(120,200,255,0)');
      ctx.fillStyle = grad;
      ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.fill();
    } else {
      ctx.strokeStyle = 'rgba(120,200,255,.35)';
      ctx.beginPath(); ctx.moveTo(cx, cy);
      ctx.lineTo(cx + Math.cos(sweep) * R, cy + Math.sin(sweep) * R); ctx.stroke();
    }
    ctx.fillStyle = 'rgba(160,230,255,.8)';
    [[0.3, 0.4], [0.7, 0.2], [0.55, 0.75]].forEach((p) => {
      ctx.beginPath();
      ctx.arc(cx - R / 2 + p[0] * R, cy - R / 2 + p[1] * R, 1.8, 0, Math.PI * 2);
      ctx.fill();
    });

    // 3) 全息网格（底部）
    ctx.strokeStyle = 'rgba(70,130,200,.10)';
    for (let i = 0; i < 8; i += 1) {
      const y = h * (0.72 + i * 0.035) + ((clock * 6) % 12);
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
    }
    for (let i = 0; i <= 10; i += 1) {
      const x = (w * i) / 10;
      ctx.beginPath(); ctx.moveTo(x, h * 0.72); ctx.lineTo(w / 2 + (x - w / 2) * 2.4, h); ctx.stroke();
    }

    // 4) K 线墙
    const wallCount = 64;
    const wallStep = w / wallCount;
    for (let i = 0; i < wallCount; i += 1) {
      const appear = Math.max(0, Math.min(1, t * wallCount - i));
      if (appear <= 0) break;
      const sv = ((i * 37) % 53) / 53;
      const x = i * wallStep + wallStep / 2;
      const mid = h * 0.72 + Math.sin(i * 0.7) * h * 0.035;
      const bodyH = (0.015 + sv * 0.05) * h;
      ctx.globalAlpha = 0.03 + 0.04 * appear;
      ctx.fillStyle = (i % 3) !== 0 ? '#ff5252' : '#26a69a';
      ctx.fillRect(x - Math.max(3, wallStep * 0.4) / 2, mid - bodyH / 2,
                   Math.max(3, wallStep * 0.4), bodyH);
    }
    ctx.globalAlpha = 1;

    // 5) 中央走势
    const padX = w * 0.20;
    const top = h * 0.66;
    const bottom = h * 0.90;
    const plotW = w - padX * 2;
    const step = plotW / splashBars.length;
    const bw = Math.max(7, step * 0.46);
    const hi = Math.max(...splashBars.map((b) => b.high));
    const lo = Math.min(...splashBars.map((b) => b.low));
    const yOf = (v) => bottom - ((v - lo) / (hi - lo)) * (bottom - top);
    const easeOut = (v) => 1 - Math.pow(1 - Math.max(0, Math.min(1, v)), 3);
    const shown = Math.min(splashBars.length, Math.ceil(t * splashBars.length));
    const points = [];
    for (let i = 0; i < shown; i += 1) {
      const b = splashBars[i];
      const grow = easeOut(t * splashBars.length - i);
      // 有机感：每根蜡烛带自己的呼吸相位，整体像活着的行情
      const bob = Math.sin(clock * 1.7 + i * 0.75) * 3.2 * t;
      const x = padX + i * step + step / 2;
      const tick = Math.sin(clock * 5 + i * 2.1);
      const flash = tick > 0.9 ? 1 : 0;
      ctx.globalAlpha = (0.62 + 0.18 * (tick * 0.5 + 0.5)) * grow;
      ctx.strokeStyle = b.up ? '#ff5b5b' : '#2ad3b6';
      ctx.fillStyle = b.up ? '#ff5b5b' : '#2ad3b6';
      ctx.shadowColor = b.up ? 'rgba(255,90,90,.65)' : 'rgba(42,211,182,.65)';
      ctx.shadowBlur = flash ? 14 : 0;
      const midY = yOf(b.close) + bob;
      const hiY = yOf(b.high) + bob;
      const loY = yOf(b.low) + bob;
      ctx.beginPath();
      ctx.moveTo(x, midY - (midY - hiY) * grow);
      ctx.lineTo(x, midY + (loY - midY) * grow);
      ctx.lineWidth = 1.6;
      ctx.stroke();
      const bt = yOf(Math.max(b.open, b.close)) + bob;
      const bb = yOf(Math.min(b.open, b.close)) + bob;
      const bodyH = Math.max(2, (bb - bt) * grow);
      ctx.fillRect(x - bw / 2, midY - bodyH / 2, bw, bodyH);
      ctx.shadowBlur = 0;
      ctx.globalAlpha = 1;
      points.push([x, midY]);
    }
    if (points.length) {
      // 第一层：宽而淡的辉光（模拟镜头发散）
      ctx.strokeStyle = 'rgba(122,162,247,.28)';
      ctx.lineWidth = 7; ctx.shadowColor = 'rgba(122,162,247,.85)'; ctx.shadowBlur = 26;
      ctx.beginPath();
      points.forEach((p, i) => { if (i === 0) ctx.moveTo(p[0], p[1]); else ctx.lineTo(p[0], p[1]); });
      ctx.stroke();
      // 第二层：细而亮的实线
      ctx.strokeStyle = 'rgba(196,226,255,.95)';
      ctx.lineWidth = 1.6; ctx.shadowColor = 'rgba(160,210,255,.9)'; ctx.shadowBlur = 11;
      ctx.beginPath();
      points.forEach((p, i) => { if (i === 0) ctx.moveTo(p[0], p[1]); else ctx.lineTo(p[0], p[1]); });
      ctx.stroke();
      const head = points[points.length - 1];
      const g2 = ctx.createRadialGradient(head[0], head[1], 0, head[0], head[1], 24);
      g2.addColorStop(0, 'rgba(160,220,255,.9)');
      g2.addColorStop(1, 'rgba(122,162,247,0)');
      ctx.fillStyle = g2; ctx.beginPath(); ctx.arc(head[0], head[1], 24, 0, Math.PI * 2); ctx.fill();
      ctx.shadowBlur = 0;
      // 沿线的流动光点
      const run = ((clock * 0.35) % 1) * (points.length - 1);
      const ri = Math.floor(run);
      const frac = run - ri;
      const p1 = points[ri];
      const p2 = points[Math.min(points.length - 1, ri + 1)];
      const rx = p1[0] + (p2[0] - p1[0]) * frac;
      const ry = p1[1] + (p2[1] - p1[1]) * frac;
      const g3 = ctx.createRadialGradient(rx, ry, 0, rx, ry, 12);
      g3.addColorStop(0, 'rgba(230,250,255,.95)');
      g3.addColorStop(1, 'rgba(122,162,247,0)');
      ctx.fillStyle = g3; ctx.beginPath(); ctx.arc(rx, ry, 12, 0, Math.PI * 2); ctx.fill();
    }

    // 6) 粒子
    splashDots.forEach((p) => {
      const y = (p.y - t * p.speed * 0.4);
      const yy = (y < 0 ? y + 1 : y) * h;
      const near = p.r > 1.6;          // 大颗粒当"近景"，画得更虚更淡
      ctx.globalAlpha = (near ? 0.10 : 0.20) * Math.min(1, t * 2);
      ctx.fillStyle = near ? '#cfe6ff' : '#9fd0ff';
      ctx.beginPath(); ctx.arc(p.x * w, yy, near ? p.r * 1.9 : p.r, 0, Math.PI * 2); ctx.fill();
    });
    ctx.globalAlpha = 1;

    if (fixed === null) splashRaf = requestAnimationFrame(draw);
  };

  cancelAnimationFrame(splashRaf);
  splashRaf = requestAnimationFrame(draw);
  startBootLog();
}

/* ---- 认证序列 ---- */
function bootLogLine(text) {
  const box = $('#boot-log');
  if (!box) return;
  Array.prototype.forEach.call(box.querySelectorAll('.boot-cursor'), (n) => n.remove());
  const line = document.createElement('div');
  line.className = 'boot-line';
  line.innerHTML = text;
  box.appendChild(line);
  const cur = document.createElement('div');
  cur.className = 'boot-line boot-cursor';
  cur.textContent = '▌';
  box.appendChild(cur);
  box.scrollTop = box.scrollHeight;
}

function startBootLog() {
  const lines = [
    '> DEEP SEA DATA TERMINAL <span class="key">v1.0</span> · 安全启动',
    '> 校验引导程序签名 ................ <span class="ok">[ OK ]</span>',
    '> 初始化加密信道 .................. <span class="ok">[ OK ]</span>',
    '> 挂载行情引擎（腾讯 / 新浪）....... <span class="ok">[ OK ]</span>',
    '> 加载 K 线缓存索引 ................ <span class="ok">[ OK ]</span>',
    '> 加载本地模拟账户 ................ <span class="ok">[ OK ]</span>',
    '> 检查交易规则（整手 / T+1 / 涨跌停）<span class="ok">[ OK ]</span>',
    '> 自检自选股清单（100 只）.......... <span class="ok">[ OK ]</span>',
    '> 启动风险控制模块 ................ <span class="ok">[ OK ]</span>',
    '> 访问权限：<span class="key">UNVERIFIED</span> · 需要人工确认',
  ];
  const quick = typeof window.__BOOT_STEP__ === 'number';
  lines.forEach((text, i) => {
    if (quick) { bootLogLine(text); return; }
    setTimeout(() => bootLogLine(text), 160 + i * 260);
  });
  const delay = quick ? 0 : 160 + lines.length * 260;
  setTimeout(() => renderBootStep(quick ? window.__BOOT_STEP__ : 0), delay);
}

function renderBootStep(index) {
  const card = $('#boot-card');
  if (!card) return;
  bootStep = Math.min(index, BOOT_STEPS.length - 1);
  bootVerifying = false;
  const step = BOOT_STEPS[bootStep];
  card.hidden = false;
  $('#boot-step-no').textContent = 'STEP ' + String(bootStep + 1).padStart(2, '0')
    + ' / ' + String(BOOT_STEPS.length).padStart(2, '0');
  $('#boot-step-title').textContent = step.title;
  $('#boot-step-desc').textContent = step.desc;
  const btn = $('#boot-btn');
  btn.textContent = step.btn;
  btn.disabled = false;
  btn.onclick = () => bootAdvance();
  const verify = $('#boot-verify');
  if (verify) verify.innerHTML = '';
  const prog = $('#boot-progress');
  if (prog) {
    prog.innerHTML = BOOT_STEPS.map((_, i) => (
      '<i class="' + (i < bootStep ? 'on' : (i === bootStep ? 'now' : '')) + '"></i>'
    )).join('');
  }
}

function bootAdvance(opts) {
  if (bootFinished || bootVerifying) return;
  const step = BOOT_STEPS[bootStep];
  if (!step) return finishSplash();
  const instant = !!(opts && opts.instant);
  const btn = $('#boot-btn');
  const verify = $('#boot-verify');
  bootVerifying = true;
  if (btn) { btn.disabled = true; btn.textContent = '校验中…'; }
  bootLogLine('> ' + step.verify + ' <span class="key">…</span>');
  if (verify) {
    verify.innerHTML = '<span>' + step.verify + '</span><span class="bar"><i></i></span>';
    const bar = verify.querySelector('.bar i');
    if (bar) setTimeout(() => { bar.style.width = '100%'; }, 20);
  }
  const finish = () => {
    bootVerifying = false;
    bootLogLine('> ' + step.log + ' ........ <span class="ok">[ OK ]</span>');
    if (bootStep < BOOT_STEPS.length - 1) { renderBootStep(bootStep + 1); return; }
    const card = $('#boot-card');
    if (card) card.hidden = true;
    const stamp = $('#boot-stamp');
    if (stamp) stamp.hidden = false;
    bootFinished = true;
    setTimeout(showWelcome, 3000);   // 授权完成 3 秒后清屏
  };
  if (instant) { finish(); return; }
  setTimeout(finish, step.ms || 1000);
}


const WELCOME_TEXT = '欢迎你，天才交易员';
const WELCOME_LINES = ['天下英雄如过江之鲫', '皆以凡人之力，与顶级资本搏杀', WELCOME_TEXT];

/* 按真实墨迹范围校正水平居中：
   letter-spacing 会给最后一字多留一格，中文标点（。）的墨迹又偏左，
   单纯 text-align:center 看着会歪，这里量一次再补偿。 */
function centerInk(line) {
  if (!line) return;
  try {
    line.style.marginLeft = '';
    const range = document.createRange();
    range.selectNodeContents(line);
    const box = range.getBoundingClientRect();
    if (!box.width) return;
    const offset = (box.left + box.right) / 2 - window.innerWidth / 2;
    if (Math.abs(offset) > 0.5) {
      line.style.marginLeft = (-offset).toFixed(1) + 'px';
    }
  } catch (e) { /* 测量失败就不校正，不影响显示 */ }
}

function showWelcome() {
  const el = $('#splash');
  const box = $('#welcome');
  if (!el || !box) return finishSplash();
  el.classList.add('welcome-stage');   // 认证 UI 整体淡出，只剩黑底
  box.hidden = false;

  const lines = Array.from(box.querySelectorAll('.welcome-line'));
  const sub = box.querySelector('.welcome-sub');
  const only = typeof window.__WELCOME_STEP__ === 'number' ? window.__WELCOME_STEP__ : null;

  // 预览模式：只显示指定的一句
  if (only !== null) {
    lines.forEach((ln, i) => {
      ln.classList.toggle('show', i === only);
      if (i === only) centerInk(ln);
    });
    if (sub) sub.classList.toggle('show', only === lines.length - 1);
    return;
  }

  // 正式流程：一句淡出 -> 下一句淡入
  const HOLD = 1500;   // 每句停留
  const FADE = 700;    // 淡入淡出时长
  let t = 350;
  lines.forEach((ln, i) => {
    setTimeout(() => { ln.classList.add('show'); centerInk(ln); }, t);
    t += HOLD;
    setTimeout(() => ln.classList.remove('show'), t);
    t += FADE;
  });
  if (sub) setTimeout(() => sub.classList.add('show'), t + 200);
  setTimeout(finishSplash, t + 2200);
}

function bootState() {
  return { step: bootStep, finished: bootFinished };
}

function finishSplash() {
  const el = $('#splash');
  if (!el || el.classList.contains('done')) return;
  if (splashRaf) cancelAnimationFrame(splashRaf);
  splashRaf = null;
  el.classList.add('done');
  setTimeout(() => { el.style.display = 'none'; }, 620);
  setTimeout(() => { if (typeof maybeOfferGuide === 'function') maybeOfferGuide(); }, 900);
}

/* ---------------- 新手指导书 ---------------- */
const GUIDE_PAGES = [
  { type: 'cover' },
  {
    type: 'text', title: '什么时候能买卖', sub: 'A 股交易时间（北京时间）',
    body: `
      <ul>
        <li><b>9:15–9:25</b>　开盘集合竞价（9:20 之后不能撤单）</li>
        <li><b>9:30–11:30</b>　上午连续竞价</li>
        <li><b>13:00–14:57</b>　下午连续竞价</li>
        <li><b>14:57–15:00</b>　收盘集合竞价</li>
        <li>周六、周日与<b>法定节假日</b>休市，无夜盘</li>
      </ul>
      <div class="warn">非交易时段本系统显示「最近收盘」，用的是最近一次收盘价，不会假装实时。</div>`,
  },
  {
    type: 'text', title: '一次买多少', sub: '买卖单位与价格',
    body: `
      <ul>
        <li><b>买入</b>必须 <b>100 股</b>的整数倍（1 手 = 100 股）</li>
        <li><b>卖出</b>可以卖零股：不足 100 股的零股要一次性卖掉</li>
        <li>报价最小变动 <b>0.01 元</b></li>
        <li>例：买 300 股可以，买 150 股不行</li>
      </ul>
      <div class="warn">本系统下单会按同样规则校验，不是「想买多少买多少」。</div>`,
  },
  {
    type: 'text', title: '一天最多涨多少', sub: '涨跌停制度',
    body: `
      <table>
        <tr><th>板块</th><th>代码特征</th><th>涨跌幅限制</th></tr>
        <tr><td>沪深主板</td><td>60xxxx / 00xxxx</td><td>±10%</td></tr>
        <tr><td>创业板</td><td>30xxxx</td><td>±20%</td></tr>
        <tr><td>科创板</td><td>688xxx</td><td>±20%</td></tr>
        <tr><td>主板 ST / *ST</td><td>名称含 ST</td><td>±5%</td></tr>
      </table>
      <div class="warn">涨停价 = 昨收 ×(1+幅度)，四舍五入到分。打到涨停经常买不进、跌停卖不出。</div>`,
  },
  {
    type: 'text', title: '今天买，明天才能卖', sub: 'T+1 与资金',
    body: `
      <ul>
        <li><b>T+1</b>：今天买入的股票，<b>下一个交易日</b>才能卖出</li>
        <li>卖出得到的钱<b>当天可以继续买</b>，第二天才能取走</li>
        <li>本系统用「钱包（银行卡）↔ 证券账户」模拟这套资金流转</li>
        <li>钱包初始 <b>15 万</b>，证券账户初始 <b>20 万</b></li>
      </ul>`,
  },
  {
    type: 'text', title: '交易要交多少钱', sub: '费用（本系统按此计算）',
    body: `
      <table>
        <tr><th>项目</th><th>费率</th><th>收取方向</th></tr>
        <tr><td>佣金</td><td>成交额 × 0.03%，<b>最低 5 元</b></td><td>买、卖都收</td></tr>
        <tr><td>印花税</td><td>成交额 × 0.05%</td><td>仅卖出</td></tr>
        <tr><td>过户费</td><td>成交额 × 0.001%</td><td>买、卖都收</td></tr>
      </table>
      <div class="warn">买 100 股 @11.50 ≈ 1150 元，佣金按最低 5 元收——小额交易其实很贵。</div>`,
  },
  {
    type: 'text', title: '这个系统怎么用', sub: '看盘 / 账户 / 回测 / 预警',
    body: `
      <ul>
        <li><b>自选股</b>：88 只示例，可点表头排序、输入关键字过滤</li>
        <li><b>个股</b>：日 / 周 / 月 K 与分时，5 秒刷新（可关），可开涨跌停与成本线</li>
        <li><b>账户</b>：钱包 + 证券账户、持仓权重占比、资产曲线、入金/出金</li>
        <li><b>回测</b>：均线策略，可设滑点与涨跌停约束</li>
        <li><b>预警</b>：价格上穿/下穿提醒</li>
      </ul>
      <div class="warn">这是模拟盘：不接券商、不下真单、不碰真钱；分析结果不构成投资建议。</div>`,
  },
  { type: 'end' },
];

let guideIndex = 0;

function guideNav(current, delta, total) {
  const next = current + delta;
  if (next < 0) return 0;
  if (next > total - 1) return total - 1;
  return next;
}

function renderGuidePage() {
  const box = $('#guide-page');
  if (!box) return;
  const page = GUIDE_PAGES[guideIndex] || GUIDE_PAGES[0];
  if (page.type === 'cover') {
    box.innerHTML = '<div class="guide-cover">'
      + '<img src="guide-cover.png" alt="封面">'
      + '<div class="band"><h2>新手指导书</h2>'
      + '<p>A 股基本规则 · 90 秒上手 · 左右方向键也能翻页</p></div></div>';
  } else if (page.type === 'end') {
    box.innerHTML = '<div class="guide-end">'
      + '<img src="guide-end.png" alt="尾页">'
      + '<div class="band">如果哪天你看到这个表情……<br>'
      + '说明该回来重读第 4 页（涨跌停）了。<br>'
      + '<span class="muted">本指导书仅供入门，不构成投资建议。</span></div></div>';
  } else {
    box.innerHTML = '<div class="guide-text"><h2>' + page.title + '</h2>'
      + '<p class="sub">' + page.sub + '</p>' + page.body + '</div>';
  }
  const ind = $('#guide-ind');
  if (ind) ind.textContent = (guideIndex + 1) + ' / ' + GUIDE_PAGES.length;
  const prev = $('#guide-prev');
  const next = $('#guide-next');
  if (prev) prev.disabled = guideIndex === 0;
  if (next) next.disabled = guideIndex === GUIDE_PAGES.length - 1;
  box.scrollTop = 0;
}

function openGuide(start) {
  guideIndex = Math.max(0, Math.min(GUIDE_PAGES.length - 1, start || 0));
  renderGuidePage();
  const el = $('#guide');
  if (el) el.hidden = false;
}

function closeGuide() {
  const el = $('#guide');
  if (el) el.hidden = true;
  try { localStorage.setItem('stock-guide-seen', '1'); } catch (e) { /* 忽略 */ }
}

function guideStep(delta) {
  const target = guideNav(guideIndex, delta, GUIDE_PAGES.length);
  if (target === guideIndex) return;
  guideIndex = target;
  renderGuidePage();
}

function maybeOfferGuide() {
  let seen = '';
  try { seen = localStorage.getItem('stock-guide-seen') || ''; } catch (e) { seen = ''; }
  if (seen === '1') return;
  showConfirm({
    title: '第一次用？',
    body: '要不要先花 90 秒看一遍《新手指导书》？<br>'
      + '里面讲清楚 A 股的开盘时间、一次买多少、涨跌停、T+1 和交易费用。<br><br>'
      + '<span class="muted">随时可以在右上角点「指导书」重新打开。</span>',
    okText: '看指导书',
    cancelText: '直接开始',
  }).then((ok) => {
    try { localStorage.setItem('stock-guide-seen', '1'); } catch (e) { /* 忽略 */ }
    if (ok) openGuide(0);
  });
}

async function bindGuide() {
  if ($('#btn-guide')) $('#btn-guide').addEventListener('click', () => openGuide(0));
  if ($('#guide-prev')) $('#guide-prev').addEventListener('click', () => guideStep(-1));
  if ($('#guide-next')) $('#guide-next').addEventListener('click', () => guideStep(1));
  if ($('#guide-close')) $('#guide-close').addEventListener('click', closeGuide);
  if ($('#guide')) {
    $('#guide').addEventListener('click', (ev) => { if (ev.target.id === 'guide') closeGuide(); });
  }
  document.addEventListener('keydown', (ev) => {
    const el = $('#guide');
    if (!el || el.hidden) return;
    if (ev.key === 'ArrowLeft') guideStep(-1);
    else if (ev.key === 'ArrowRight') guideStep(1);
    else if (ev.key === 'Escape') closeGuide();
  });
}

/* ---------------- 确认弹窗 ---------------- */
function showConfirm(opts) {
  return new Promise((resolve) => {
    const mask = $('#modal');
    if (!mask) { resolve(window.confirm(opts.title + '\n' + (opts.body || ''))); return; }
    $('#modal-title').textContent = opts.title || '确认';
    $('#modal-body').innerHTML = opts.body || '';
    const ok = $('#modal-ok');
    const cancel = $('#modal-cancel');
    ok.textContent = opts.okText || '确定';
    if (cancel) cancel.textContent = opts.cancelText || '取消';
    ok.className = 'btn ' + (opts.danger ? 'danger' : 'primary');
    mask.hidden = false;
    const close = (value) => {
      mask.hidden = true;
      ok.removeEventListener('click', onOk);
      cancel.removeEventListener('click', onCancel);
      mask.removeEventListener('click', onMask);
      document.removeEventListener('keydown', onKey);
      resolve(value);
    };
    const onOk = () => close(true);
    const onCancel = () => close(false);
    const onMask = (ev) => { if (ev.target === mask) close(false); };
    const onKey = (ev) => { if (ev.key === 'Escape') close(false); };
    ok.addEventListener('click', onOk);
    cancel.addEventListener('click', onCancel);
    mask.addEventListener('click', onMask);
    document.addEventListener('keydown', onKey);
    ok.focus();
  });
}

async function resetPortfolio() {
  const ok = await showConfirm({
    title: '重置所有数据？',
    okText: '确定重置',
    danger: true,
    body: [
      '确定后，所有数据将恢复为初始状态：',
      '• 持仓与成交记录清空，证券现金回到 <b>20 万</b>',
      '• 钱包（银行卡）回到 <b>15 万</b>',
      '• 资金流水与资产曲线清空',
      '• 价格预警全部删除',
      '• 自选股恢复为默认 88 只',
      '',
      '此操作不可撤销。',
    ].join('<br>'),
  });
  if (!ok) return;
  const res = await api('/api/portfolio/reset', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ cash: 200000 }),
  });
  loadPortfolio();
  refresh();
}

/* ---------------- 回测 ---------------- */
async function runBacktest() {
  const params = new URLSearchParams({
    code: $('#bt-code').value.trim(),
    short: $('#bt-short').value,
    long: $('#bt-long').value,
    cash: $('#bt-cash').value,
    fqt: ($('#bt-fqt') || {}).value || 'qfq',
    slippage: ($('#bt-slip') || {}).value || '0',
    respect: ($('#bt-respect') && $('#bt-respect').checked) ? '1' : '0',
  });
  $('#bt-metrics').innerHTML = '<span class="muted small">回测中…</span>';
  $('#bt-trades tbody').innerHTML = '';
  $('#bt-note').textContent = '';
  const res = await api('/api/backtest?' + params.toString());
  if (!res.ok) {
    $('#bt-metrics').innerHTML = `<span class="muted small">失败：${esc(res.error || '')}</span>`;
    return;
  }
  const r = res.result;
  const m = r.metrics;
  $('#bt-metrics').innerHTML = [
    ['总收益率', m.total_return + '%', m.total_return],
    ['最大回撤', m.max_drawdown + '%', -m.max_drawdown],
    ['胜率', m.win_rate + '%', 0],
    ['交易次数', m.trade_count, 0],
    ['期末资金', fmt(r.final_equity), 0],
  ].map(([k, v, d]) => `<div class="metric"><span>${k}</span><b class="${dirCls(d)}">${v}</b></div>`).join('');
  $('#bt-note').textContent = (res.notes || []).join(' ')
    || `数据来源 ${res.meta.source}${res.meta.stale ? '（缓存）' : ''}；区间 ${r.equity[0].date} ~ ${r.equity[r.equity.length - 1].date}；`
       + '按整手成交并扣佣金/印花税/过户费。';
  drawEquityChart(r.equity || []);
  $('#bt-trades tbody').innerHTML = (r.trades || []).map((t) => `
    <tr>
      <td>${esc(t.entry_date)}</td><td class="num">${fmt(t.entry_price)}</td>
      <td>${esc(t.exit_date)}</td><td class="num">${fmt(t.exit_price)}</td>
      <td class="num">${t.shares}</td><td class="num">${fmt(t.gross_pnl)}</td>
      <td class="num">${fmt(t.fee)}</td>
      <td class="num ${dirCls(t.pnl)}">${fmt(t.pnl)}</td>
      <td class="num ${dirCls(t.return_pct)}">${fmt(t.return_pct)}%</td>
    </tr>`).join('') || '<tr><td colspan="9" class="muted">没有产生交易（可能是资金不足一手或区间内没有交叉）</td></tr>';
}

/* ---------------- 预警 ---------------- */
function renderAlerts() {
  const alerts = (app.state && app.state.alerts) || [];
  const quotes = {};
  ((app.state && app.state.quotes) || []).forEach((q) => { quotes[q.code] = q; });
  $('#alerts-table tbody').innerHTML = alerts.map((a) => {
    const q = quotes[a.code];
    const price = q ? q.price : null;
    const hit = price !== null && (a.op === 'above' ? price >= a.price : price <= a.price);
    return `<tr>
      <td>${esc(a.code)}</td>
      <td>${a.op === 'above' ? '上穿' : '下穿'}</td>
      <td class="num">${fmt(a.price)}</td>
      <td class="num">${fmt(price)}</td>
      <td class="${hit ? 'up' : 'muted'}">${price === null ? '无行情' : (hit ? '已触发' : '未触发')}</td>
      <td class="muted small">${esc(a.created)}</td>
      <td><button class="btn" data-del="${a.id}">删除</button></td>
    </tr>`;
  }).join('') || '<tr><td colspan="7" class="muted">还没有预警</td></tr>';
}

function checkAlerts() {
  renderAlerts();
  const alerts = (app.state && app.state.alerts) || [];
  const quotes = {};
  ((app.state && app.state.quotes) || []).forEach((q) => { quotes[q.code] = q; });
  alerts.forEach((a) => {
    const q = quotes[a.code];
    if (!q || q.price === null || q.price === undefined) return;
    const hit = a.op === 'above' ? q.price >= a.price : q.price <= a.price;
    if (hit) {
      const msg = `预警：${q.name}(${a.code}) 现价 ${q.price} `
        + `${a.op === 'above' ? '已上穿' : '已下穿'} ${a.price}`;
      console.info(msg);
      $('#badge-source').title = msg;
    }
  });
}

async function addAlert() {
  const body = {
    action: 'add',
    code: $('#al-code').value.trim(),
    op: $('#al-op').value,
    price: parseFloat($('#al-price').value),
  };
  const res = await api('/api/alerts', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (res.ok) { app.state.alerts = res.alerts; renderAlerts(); refresh(); }
}

async function removeAlert(id) {
  const res = await api('/api/alerts', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'remove', id }),
  });
  if (res.ok) { app.state.alerts = res.alerts; renderAlerts(); }
}

/* ---------------- 设置 ---------------- */
function renderSettings() {
  const s = (app.state && app.state.settings && app.state.settings.llm) || {};
  $('#llm-enabled').checked = !!s.enabled;
  $('#llm-model').value = s.model || 'deepseek-chat';
  $('#llm-url').value = s.base_url || '';
  $('#llm-key').value = '';
  $('#llm-status').textContent = s.has_key
    ? ('已保存 key：' + (s.api_key_masked || '****')) : '未配置 key（当前用本地规则引擎）';
}

async function saveLlm(clearKey) {
  const body = { llm: {
    enabled: $('#llm-enabled').checked,
    model: $('#llm-model').value.trim(),
    base_url: $('#llm-url').value.trim(),
  } };
  if (clearKey) body.llm.clear_key = true;
  else {
    const key = $('#llm-key').value.trim();
    if (key) body.llm.api_key = key;
  }
  const res = await api('/api/settings', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (res.ok) {
    app.state.settings = res;
    renderSettings();
    $('#llm-status').textContent = '已保存；' + ($('#llm-enabled').checked
      ? '下次分析会先调用模型（失败自动回落规则引擎）' : '当前使用本地规则引擎');
  } else {
    $('#llm-status').textContent = '保存失败：' + (res.error || '');
  }
}

/* ---------------- 事件绑定 ---------------- */
function bind() {
  $$('.tab').forEach((b) => b.addEventListener('click', () => switchTab(b.dataset.tab)));
  $('#btn-refresh').addEventListener('click', refresh);
  $('#btn-search').addEventListener('click', doSearch);
  $('#search-input').addEventListener('keydown', (e) => { if (e.key === 'Enter') doSearch(); });
  $('#search-result').addEventListener('click', (e) => {
    const btn = e.target.closest('[data-add]');
    if (btn) addToWatchlist(btn.dataset.add);
  });
  $('#watchlist-table').addEventListener('click', (e) => {
    const btn = e.target.closest('button');
    if (!btn) return;
    if (btn.dataset.act === 'detail') loadDetail(btn.dataset.code);
    if (btn.dataset.act === 'remove') removeFromWatchlist(btn.dataset.code);
  });
  $('#btn-order').addEventListener('click', submitOrder);
  $('#btn-reset').addEventListener('click', resetPortfolio);
  $('#btn-backtest').addEventListener('click', runBacktest);
  $('#btn-alert-add').addEventListener('click', addAlert);
  $('#alerts-table').addEventListener('click', (e) => {
    const btn = e.target.closest('[data-del]');
    if (btn) removeAlert(Number(btn.dataset.del));
  });
  $('#btn-llm-save').addEventListener('click', () => saveLlm(false));
  $('#btn-llm-clear').addEventListener('click', () => saveLlm(true));
  const chartCanvas = $('#chart');
  chartCanvas.addEventListener('mousemove', (e) => {
    if (app.mode === 'minute') onMinuteMove(e.clientX, e.clientY);
    else onChartMove(e);
  });
  chartCanvas.addEventListener('mouseleave', () => {
    app.hover = null;
    hideTip();
    redrawCurrentChart();   // 分时模式就重画分时，别跳回日/周/月 K
  });
  if ($('#btn-detail-retry')) {
    $('#btn-detail-retry').addEventListener('click', () => {
      if (app.current) loadDetail(app.current);
    });
  }
  if ($('#btn-diag')) $('#btn-diag').addEventListener('click', runDiag);
  if ($('#btn-deposit')) $('#btn-deposit').addEventListener('click', () => accountFlow('deposit'));
  if ($('#watch-filter')) {
    $('#watch-filter').addEventListener('input', (e) => {
      app.filter = e.target.value || '';
      renderWatchlist();
    });
  }
  $$('#watchlist-table th[data-sort]').forEach((th) => {
    th.addEventListener('click', () => {
      const key = th.dataset.sort;
      if (app.sortKey === key) app.sortDir = app.sortDir === 'desc' ? 'asc' : 'desc';
      else { app.sortKey = key; app.sortDir = (key === 'code' || key === 'name') ? 'asc' : 'desc'; }
      markSortHeader();
      renderWatchlist();
    });
  });
  ['week', 'month'].forEach((p) => {
    const btn = $('#btn-' + p);
    if (btn) btn.addEventListener('click', () => setPeriod(p));
  });
  if ($('#chk-limits')) {
    $('#chk-limits').addEventListener('change', (e) => {
      app.limitsOn = e.target.checked; redrawCurrentChart();
    });
  }
  if ($('#chk-cost')) {
    $('#chk-cost').addEventListener('change', (e) => {
      app.costOn = e.target.checked; redrawCurrentChart();
    });
  }
  document.addEventListener('keydown', onHotkey);
  bindGuide();
  if ($('#btn-withdraw')) $('#btn-withdraw').addEventListener('click', () => accountFlow('withdraw'));
  if ($('#btn-day')) $('#btn-day').addEventListener('click', () => switchChartMode('day'));
  if ($('#btn-minute')) $('#btn-minute').addEventListener('click', () => switchChartMode('minute'));
  $('#live-toggle').addEventListener('change', () => {
    if ($('#live-toggle').checked) startLive(); else stopLive();
  });
  window.addEventListener('resize', () => { redrawCurrentChart(); });
}

async function boot() {
  bind();
  startSplash();
  if ($('#boot-skip')) $('#boot-skip').addEventListener('click', finishSplash);
  // 浏览器只允许用户操作后进入全屏：第一次点击/按键时尝试全屏一次
  const goFullscreen = () => {
    const el = $('#splash');
    if (!el || el.classList.contains('done')) return;
    const root = document.documentElement;
    if (document.fullscreenElement || !root.requestFullscreen) return;
    // 启动器用 --start-fullscreen 打开时窗口本来就满屏了，别再来一次 DOM 全屏造成闪烁
    if (window.innerHeight >= (screen.availHeight || screen.height) - 2) return;
    root.requestFullscreen().catch(() => {});
  };
  $('#splash').addEventListener('pointerdown', goFullscreen, { passive: true });
  document.addEventListener('keydown', goFullscreen, { passive: true });
  await refresh();
  if (app.state && app.state.settings) renderSettings();
  // 恢复上次停留的股票/标签页（第一次用还是停在自选股）
  const wl = (app.state && app.state.watchlist) || [];
  let lastCode = '';
  let lastTab = '';
  try { lastCode = localStorage.getItem('stock-last-code') || ''; } catch (e) { lastCode = ''; }
  try { lastTab = localStorage.getItem('stock-last-tab') || ''; } catch (e) { lastTab = ''; }
  const target = wl.includes(lastCode) ? lastCode : wl[0];
  if (target) loadDetail(target, { silent: true });
  if (lastTab && lastTab !== 'watchlist') switchTab(lastTab);
  maybeOfferGuide();
  markSortHeader();
  if ($('#live-toggle') && $('#live-toggle').checked) startLive();
}

/* ---------------- 十字光标 / 悬浮提示 / 实时刷新 ---------------- */
// 鼠标移动用 requestAnimationFrame 节流：每帧最多重绘一次，避免掉帧
let hoverRaf = null;
let hoverEvent = null;

function onChartMove(e) {
  hoverEvent = { clientX: e.clientX, clientY: e.clientY };
  if (hoverRaf) return;
  hoverRaf = requestAnimationFrame(() => {
    hoverRaf = null;
    const ev = hoverEvent;
    const g = app.geom;
    if (!g || !g.view || !g.view.length || !ev) return;
    const canvas = $('#chart');
    const rect = canvas.getBoundingClientRect();
    const x = ev.clientX - rect.left;
    const idx = Math.floor((x - g.left) / g.step);
    if (idx < 0 || idx >= g.view.length) { hideTip(); return; }
    app.hover = idx;
    drawPriceChart(app.bars, idx);
    showTip(ev.clientX, ev.clientY, idx);
  });
}

function showTip(clientX, clientY, idx) {
  const g = app.geom;
  const tip = $('#chart-tip');
  const bar = g && g.view[idx];
  if (!bar || !tip) return;
  const rows = [
    ['日期', bar.date],
    ['开', fmt(bar.open)], ['高', fmt(bar.high)],
    ['低', fmt(bar.low)], ['收', fmt(bar.close)],
    ['量(手)', fmt(bar.volume, 0)],
    ['MA5', fmt(g.ma5[idx])], ['MA20', fmt(g.ma20[idx])], ['MA60', fmt(g.ma60[idx])],
    ['RSI', fmt(g.rsiV[idx], 1)],
  ];
  tip.innerHTML = rows.map(([k, v]) => `<div class="kv"><span>${k}</span><b>${v}</b></div>`).join('');
  tip.hidden = false;
  const wrap = tip.parentElement.getBoundingClientRect();
  let left = clientX - wrap.left + 16;
  let top = clientY - wrap.top + 12;
  if (left + 150 > wrap.width) left = Math.max(4, wrap.width - 154);
  if (top + tip.offsetHeight > wrap.height) top = Math.max(4, top - tip.offsetHeight - 26);
  tip.style.left = left + 'px';
  tip.style.top = top + 'px';
}

function hideTip() {
  const tip = $('#chart-tip');
  if (tip) tip.hidden = true;
}

function renderQuoteHead(quote) {
  if (!quote) return;
  const cls = dirCls(quote.change);
  $('#detail-price').innerHTML = `<span class="${cls}">${fmt(quote.price)}</span>`
    + ` <span class="small ${cls}">${fmt(quote.change)} / ${pct(quote.change_pct)}</span>`;
  const sub = $('#detail-sub');
  if (sub) {
    sub.textContent = `行情时间 ${quote.timestamp || '—'} · 昨收 ${fmt(quote.prev_close)}`
      + ` · 涨停 ${fmt(quote.limit_up)} / 跌停 ${fmt(quote.limit_down)}`;
  }
}

function patchLastBar(quote) {
  if (!quote || !app.bars.length || quote.price === null || quote.price === undefined) return;
  const prevClose = app.bars[app.bars.length - 1].close;
  if (prevClose === quote.price) return;   // 价格没变就不重绘
  const day = String(quote.timestamp || '').slice(0, 10);
  const last = app.bars[app.bars.length - 1];
  if (day && day === last.date) {
    last.close = quote.price;
    if (quote.high) last.high = Math.max(last.high, quote.high);
    if (quote.low) last.low = Math.min(last.low, quote.low);
    if (quote.volume) last.volume = quote.volume;
  } else if (day && day > last.date) {
    // 只有行情日期比最后一根更晚才追加；缓存/滞后行情不能倒着插进历史
    app.bars.push({ date: day, open: quote.open || quote.price, close: quote.price,
                    high: quote.high || quote.price, low: quote.low || quote.price,
                    volume: quote.volume || 0 });
  }
  drawPriceChart(app.bars, app.hover);
}

let liveTimer = null;
let leaderTimer = null;

async function liveTick() {
  if (!app.state) return;
  // 多标签页时只有 leader 去请求，其余标签靠 BroadcastChannel 收结果
  if (channel && !isLeader) return;
  await refresh();
  if (app.current) {
    const q = await api('/api/quote?codes=' + encodeURIComponent(app.current));
    const quote = (q.quotes || [])[0];
    app.lastQuote = quote || null;
    if (quote) {
      renderQuoteHead(quote);
      if (app.mode === 'minute') await refreshMinute(quote);
      else patchLastBar(quote);
      markChartUpdated(quote.timestamp);
    }
  }
  broadcastState();   // 行情也一起广播，非主标签的图才会跟着动
  // 当前所在页也一起刷新（持仓/账户），否则停在那页数字会僵住
  if (isPanelActive('portfolio')) await loadPortfolio();
  else if (isPanelActive('account')) await loadAccount();
  // AI 建议 60 秒更新一次（规则引擎很快，真模型才有成本）
  maybeRefreshAnalysis();
}

function startLive() {
  stopLive();
  electLeader();
  leaderTimer = setInterval(electLeader, 3000);
  liveTimer = setInterval(liveTick, 5000);
  $('#badge-time').title = channel
    ? '每 5 秒一次；多标签页时只有主标签请求，其余标签共享结果'
    : '每 5 秒拉一次行情（只在页面打开时）';
}

function stopLive() {
  if (liveTimer) { clearInterval(liveTimer); liveTimer = null; }
  if (leaderTimer) { clearInterval(leaderTimer); leaderTimer = null; }
}

/* ---------------- 分时图 ---------------- */
/* 按当前模式重画：分时 -> 分时图，日/周/月 -> K 线图。返回实际画的是哪种，便于测试。 */
function redrawCurrentChart() {
  if (app.mode === 'minute' && app.minute && (app.minute.points || []).length) {
    drawMinuteChart(app.minute);
    return 'minute';
  }
  if (app.bars && app.bars.length) {
    drawPriceChart(app.bars);
    return 'day';
  }
  return 'none';
}

function switchChartMode(mode) {
  app.mode = mode;
  if (mode === 'day') app.period = 'day';   // 从周/月切回来时重置，别让按钮和图对不上
  ['day', 'week', 'month', 'minute'].forEach((p) => {
    const btn = $('#btn-' + p);
    if (!btn) return;
    const active = p === 'minute' ? mode === 'minute' : (mode === 'day' && p === app.period);
    btn.classList.toggle('active-mode', active);
  });
  const note = $('#chart-mode-note');
  if (note) {
    note.textContent = mode === 'day'
      ? (periodLabel() + '：最近 120 根') : '分时：当日逐分钟（09:30–15:00）';
  }
  hideTip();
  if (!app.current) return;
  if (mode === 'day') { app.hover = null; drawPriceChart(app.bars); }
  else { loadMinute(app.current); }
}

let minuteFetchedAt = 0;

async function loadMinute(code, opts) {
  opts = opts || {};
  if (!opts.quiet) $('#chart-mode-note').textContent = '分时加载中…';
  const res = await api('/api/minute?code=' + encodeURIComponent(code));
  if (!res.ok || !res.data || !(res.data.points || []).length) {
    $('#chart-mode-note').textContent = '分时数据拿不到（接口不可达且无缓存）';
    return;
  }
  app.minute = res.data;
  minuteFetchedAt = Date.now();
  $('#chart-mode-note').textContent = '分时：' + (res.data.date || '')
    + ' · ' + res.data.points.length + ' 个点 · 来源 ' + (res.meta && res.meta.source);
  drawMinuteChart(res.data);
}

// 分时刷新：每 30 秒整体重拉一次（这样才会补上新的分钟），其余 5 秒只改最后一点的价格
async function refreshMinute(quote) {
  if (Date.now() - minuteFetchedAt > 30000) {
    await loadMinute(app.current, { quiet: true });
    return;
  }
  patchMinute(quote);
}

function drawMinuteChart(data) {
  const canvas = $('#chart');
  const pts = (data && data.points) || [];
  if (!canvas || !pts.length) return;
  const { ctx, w, h } = setupCanvas(canvas, 420);
  const left = 6; const right = 62;
  const top = 10; const bottom = h * 0.72;
  const volTop = h * 0.76; const volBottom = h * 0.90;
  const plotW = w - left - right;
  const prevClose = Number(data.prev_close) || pts[0].price;
  const prices = pts.map((p) => p.price).concat(pts.map((p) => p.avg_price || p.price));
  let hi = Math.max.apply(null, prices.concat([prevClose]));
  let lo = Math.min.apply(null, prices.concat([prevClose]));
  const pad = (hi - lo) * 0.12 || 0.01;
  hi += pad; lo -= pad;
  const yPrice = (v) => bottom - (v - lo) / (hi - lo) * (bottom - top);
  const step = plotW / Math.max(1, pts.length - 1);
  const xOf = (i) => left + i * step;

  ctx.font = '11px "Microsoft YaHei", sans-serif';
  ctx.strokeStyle = '#232b35';
  ctx.fillStyle = '#8b98a5';
  for (let k = 0; k <= 4; k += 1) {
    const v = lo + (hi - lo) * (k / 4);
    const y = yPrice(v);
    ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(left + plotW, y); ctx.stroke();
    ctx.fillText(fmt(v), left + plotW + 6, y + 4);
  }
  ctx.strokeStyle = 'rgba(230,237,243,0.35)';
  ctx.setLineDash([5, 4]);
  ctx.beginPath(); ctx.moveTo(left, yPrice(prevClose)); ctx.lineTo(left + plotW, yPrice(prevClose)); ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillText('昨收 ' + fmt(prevClose), left + 2, yPrice(prevClose) - 4);

  const up = pts[pts.length - 1].price >= prevClose;
  ctx.strokeStyle = up ? '#ff5252' : '#26a69a';
  ctx.lineWidth = 1.6;
  ctx.beginPath();
  pts.forEach((p, i) => {
    const x = xOf(i); const y = yPrice(p.price);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.strokeStyle = '#f0d17e';
  ctx.lineWidth = 1.1;
  ctx.beginPath();
  pts.forEach((p, i) => {
    const x = xOf(i); const y = yPrice(p.avg_price || p.price);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();

  const vmax = Math.max.apply(null, pts.map((p) => p.volume || 0)) || 1;
  pts.forEach((p, i) => {
    const hgt = ((p.volume || 0) / vmax) * (volBottom - volTop);
    ctx.fillStyle = (p.price >= prevClose) ? 'rgba(255,82,82,0.5)' : 'rgba(38,166,154,0.5)';
    ctx.fillRect(xOf(i) - 1, volBottom - hgt, Math.max(1, step * 0.7), hgt);
  });
  ctx.fillStyle = '#8b98a5';
  ctx.fillText('成交量', left + 2, volTop - 3);

  ['09:30', '10:30', '11:30', '14:00', '15:00'].forEach((label) => {
    const idx = pts.findIndex((p) => p.time >= label);
    if (idx < 0) return;
    const x = Math.min(Math.max(xOf(idx) - 14, left), left + plotW - 30);
    ctx.fillText(label, x, h - 6);
  });

  app.geomMinute = { left, plotW, step, pts, yPrice };
}

function onMinuteMove(clientX, clientY) {
  const g = app.geomMinute;
  if (!g) return;
  const rect = $('#chart').getBoundingClientRect();
  const idx = Math.round((clientX - rect.left - g.left) / g.step);
  if (idx < 0 || idx >= g.pts.length) { hideTip(); return; }
  const p = g.pts[idx];
  const tip = $('#chart-tip');
  if (!tip) return;
  tip.innerHTML = [
    ['时间', p.time], ['价格', fmt(p.price)], ['均价', fmt(p.avg_price)],
    ['分钟量(手)', fmt(p.volume, 0)], ['累计量(手)', fmt(p.cum_volume, 0)],
  ].map(([k, v]) => `<div class="kv"><span>${k}</span><b>${v}</b></div>`).join('');
  tip.hidden = false;
  const wrap = tip.parentElement.getBoundingClientRect();
  let left = clientX - wrap.left + 16;
  let top = clientY - wrap.top + 12;
  if (left + 150 > wrap.width) left = Math.max(4, wrap.width - 154);
  if (top + tip.offsetHeight > wrap.height) top = Math.max(4, top - tip.offsetHeight - 26);
  tip.style.left = left + 'px';
  tip.style.top = top + 'px';
}

/* ---------------- 多标签页：选主 + 广播 ---------------- */
const TAB_ID = Math.random().toString(36).slice(2);
let isLeader = false;
let channel = null;
try { channel = new BroadcastChannel('stock-system'); } catch (e) { channel = null; }

function electLeader() {
  const now = Date.now();
  let cur = null;
  try { cur = JSON.parse(localStorage.getItem('stock-leader') || 'null'); } catch (e) { cur = null; }
  if (!cur || cur.id === TAB_ID || now - (Number(cur.ts) || 0) > 12000) {
    cur = { id: TAB_ID, ts: now };
    try { localStorage.setItem('stock-leader', JSON.stringify(cur)); } catch (e) { /* 忽略 */ }
  }
  isLeader = cur.id === TAB_ID;
}

function broadcastState() {
  if (!channel || !app.state) return;
  try {
    channel.postMessage({ type: 'tick', state: app.state,
                          code: app.current, quote: app.lastQuote || null });
  } catch (e) { /* 忽略 */ }
}

if (channel) {
  channel.onmessage = (ev) => {
    const msg = ev.data || {};
    if (msg.type !== 'tick' || isLeader || !msg.state) return;
    app.state = msg.state;
    app.lastMeta = msg.state.meta;
    renderMeta(msg.state.meta);
    renderMarket(msg.state.market);
    renderWatchlist();
    checkAlerts();
    // 主标签把行情一起广播过来，非主标签的图也能跟着动
    if (msg.quote && msg.code && msg.code === app.current) {
      renderQuoteHead(msg.quote);
      if (app.mode === 'minute') patchMinute(msg.quote);
      else patchLastBar(msg.quote);
    }
  };
}

function patchMinute(quote) {
  if (!app.minute || !(app.minute.points || []).length || !quote) return;
  if (app.mode !== 'minute') return;
  const lastPoint = app.minute.points[app.minute.points.length - 1];
  if (lastPoint.price === quote.price) return;   // 价格没变不重绘
  lastPoint.price = quote.price;
  drawMinuteChart(app.minute);
}

/* ---------------- 实时刷新辅助 ---------------- */
function isPanelActive(name) {
  const el = $('#panel-' + name);
  return !!(el && el.classList.contains('active'));
}

function markChartUpdated(timestamp) {
  const el = $('#detail-status');
  if (!el || el.dataset.kind !== 'ok') return;   // 出错时不要覆盖失败原因
  const now = new Date();
  const hh = String(now.getHours()).padStart(2, '0');
  const mm = String(now.getMinutes()).padStart(2, '0');
  const ss = String(now.getSeconds()).padStart(2, '0');
  if (!el.dataset.base) el.dataset.base = el.textContent || '';
  if (!el.dataset.base) return;
  el.textContent = el.dataset.base + ' · 行情 ' + (timestamp || '') + ' · 刷新 ' + hh + ':' + mm + ':' + ss;
}

let analysisFetchedAt = 0;

function maybeRefreshAnalysis() {
  if (!isPanelActive('detail')) return;
  if (!app.current) return;
  if (Date.now() - analysisFetchedAt < 60000) return;
  analysisFetchedAt = Date.now();
  api('/api/analysis?code=' + encodeURIComponent(app.current)).then((res) => {
    if (!res || !res.ok || !app.current) return;
    app.analysis = res.analysis;
    renderAnalysis(res.analysis);
  }).catch(() => { /* 分析失败不打断看盘 */ });
}

/* ---------------- 个人账户 ---------------- */
const ALLOC_COLORS = ['#7aa2f7', '#f0d17e', '#c99cf5', '#26a69a', '#ff5252',
  '#f0b37e', '#9ece6a', '#7dcfff', '#bb9af7', '#e0af68'];

async function loadAccount() {
  const res = await api('/api/account');
  if (!res || !res.ok) {
    const box = $('#acct-cards');
    if (box) box.innerHTML = '<span class="muted small">账户数据暂时拿不到：'
      + esc((res && res.error) || '未知原因') + '</span>';
    return;
  }
  renderAccount(res);
}

function renderAccount(res) {
  const s = res.summary || {};
  const a = res.allocation || { items: [], cash_pct: 0 };
  const curve = res.curve || [];

  const cards = [
    ['钱包余额（银行卡）', fmt(s.wallet), 0],
    ['证券账户现金', fmt(s.cash), 0],
    ['持仓市值', fmt(s.market_value), 0],
    ['证券账户总资产', fmt(s.total), 0],
    ['净资产（含钱包）', fmt(s.net_worth), 0],
    ['总收益', fmt(s.total_pnl), s.total_pnl],
    ['总收益率', (Number(s.total_return_pct) > 0 ? '+' : '') + fmt(s.total_return_pct) + '%', s.total_return_pct],
    ['持仓占净资产', fmt(s.position_pct_of_net) + '%', 0],
  ];
  const box = $('#acct-cards');
  if (box) {
    box.innerHTML = cards.map(([k, v, d]) => (
      `<div class="metric"><span>${k}</span><b class="${dirCls(d)}">${v}</b></div>`
    )).join('');
  }

  // 配置条 + 图例
  const segs = (a.items || []).map((it, i) => (
    { label: it.name || it.code, pct: Number(it.weight) || 0, color: ALLOC_COLORS[i % ALLOC_COLORS.length] }
  ));
  segs.push({ label: '现金', pct: Number(a.cash_pct) || 0, color: '#3b4654' });
  const bar = $('#alloc-bar');
  if (bar) {
    bar.innerHTML = segs.filter((x) => x.pct > 0).map((x) => (
      `<div class="alloc-seg" style="width:${x.pct}%;background:${x.color}" title="${esc(x.label)} ${fmt(x.pct)}%"></div>`
    )).join('');
  }
  const legend = $('#alloc-legend');
  if (legend) {
    legend.innerHTML = segs.map((x) => (
      `<span><i style="background:${x.color}"></i>${esc(x.label)} ${fmt(x.pct)}%</span>`
    )).join('');
  }

  const allocBody = $('#alloc-table tbody');
  if (allocBody) {
    const rows = (a.items || []).map((it, i) => `
      <tr>
        <td><i style="display:inline-block;width:9px;height:9px;border-radius:2px;background:${ALLOC_COLORS[i % ALLOC_COLORS.length]};margin-right:6px"></i>${esc(it.name)} <span class="muted small">${esc(it.code)}</span></td>
        <td class="num">${fmt(it.market_value)}</td>
        <td class="num">${fmt(it.weight)}%</td>
        <td class="num ${dirCls(it.pnl)}">${fmt(it.pnl)}</td>
      </tr>`).join('');
    const cashRow = `<tr><td><i style="display:inline-block;width:9px;height:9px;border-radius:2px;background:#3b4654;margin-right:6px"></i>现金</td>
      <td class="num">${fmt(a.cash)}</td><td class="num">${fmt(a.cash_pct)}%</td><td class="num">—</td></tr>`;
    allocBody.innerHTML = (rows + cashRow)
      || '<tr><td colspan="4" class="muted">还没有持仓</td></tr>';
  }

  drawAccountChart(curve);
  const note = $('#acct-note');
  if (note) {
    note.textContent = curve.length
      ? `共 ${curve.length} 个数据点（${curve[0].date} ~ ${curve[curve.length - 1].date}）`
        + (res.meta && res.meta.source ? ` · 行情来源 ${res.meta.source}` : '')
      : '还没有历史数据点；每天首次打开账户会自动记录。';
  }

  const flowBody = $('#flows-table tbody');
  if (flowBody) {
    const flows = (res.flows || []).slice().reverse();
    flowBody.innerHTML = flows.map((f) => `
      <tr>
        <td>${esc(f.day)}</td>
        <td class="${f.type === 'deposit' ? 'up' : 'down'}">${f.type === 'deposit' ? '入金 钱包→证券' : '出金 证券→钱包'}</td>
        <td class="num ${f.type === 'deposit' ? 'up' : 'down'}">${f.type === 'deposit' ? '+' : '-'}${fmt(f.amount)}</td>
        <td class="muted small">${esc(f.note || '')}</td>
      </tr>`).join('') || '<tr><td colspan="4" class="muted">还没有资金流水</td></tr>';
  }
}

function drawAccountChart(curve) {
  const canvas = $('#acct-chart');
  if (!canvas) return;
  const { ctx, w, h } = setupCanvas(canvas, 220);
  if (!curve || !curve.length) {
    ctx.fillStyle = '#8b98a5';
    ctx.font = '12px "Microsoft YaHei", sans-serif';
    ctx.fillText('还没有数据点（每天首次打开账户会自动记录）', 12, h / 2);
    return;
  }
  const left = 6; const right = 72; const top = 12; const bottom = h - 22;
  const plotW = w - left - right;
  const values = curve.map((p) => Number(p.total) || 0);
  const hi = Math.max.apply(null, values);
  const lo = Math.min.apply(null, values);
  const pad = (hi - lo) * 0.1 || Math.max(1, hi * 0.01);
  const y = (v) => bottom - (v - (lo - pad)) / ((hi + pad) - (lo - pad)) * (bottom - top);
  ctx.font = '11px "Microsoft YaHei", sans-serif';
  ctx.strokeStyle = '#232b35';
  ctx.fillStyle = '#8b98a5';
  for (let k = 0; k <= 3; k += 1) {
    const v = (lo - pad) + ((hi + pad) - (lo - pad)) * (k / 3);
    const yy = y(v);
    ctx.beginPath(); ctx.moveTo(left, yy); ctx.lineTo(left + plotW, yy); ctx.stroke();
    ctx.fillText(fmt(v, 0), left + plotW + 6, yy + 4);
  }
  const step = plotW / Math.max(1, curve.length - 1);
  ctx.strokeStyle = '#7aa2f7';
  ctx.lineWidth = 1.6;
  ctx.beginPath();
  values.forEach((v, i) => {
    const x = left + i * step;
    if (i === 0) ctx.moveTo(x, y(v)); else ctx.lineTo(x, y(v));
  });
  ctx.stroke();
  ctx.fillStyle = '#8b98a5';
  const marks = Math.min(5, curve.length);
  for (let k = 0; k < marks; k += 1) {
    const idx = Math.round((curve.length - 1) * k / Math.max(1, marks - 1));
    const x = Math.min(Math.max(left + idx * step - 20, left), left + plotW - 40);
    ctx.fillText(String(curve[idx].date).slice(5), x, h - 6);
  }
}

async function accountFlow(kind) {
  const msg = $('#flow-msg');
  const amount = Number($('#flow-amount').value);
  if (!Number.isFinite(amount) || amount <= 0) {
    if (msg) { msg.className = 'msg err'; msg.textContent = '金额必须为正数'; }
    return;
  }
  const res = await api('/api/account/flow', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ type: kind, amount: amount, note: $('#flow-note').value.trim() }),
  });
  if (!res || !res.ok) {
    if (msg) { msg.className = 'msg err'; msg.textContent = (res && res.error) || '操作失败'; }
    return;
  }
  if (msg) {
    msg.className = 'msg ok';
    msg.textContent = (kind === 'deposit' ? '入金' : '出金') + ' ' + fmt(amount)
      + ' 成功 · 钱包 ' + fmt(res.summary.wallet)
      + ' · 证券现金 ' + fmt(res.summary.cash);
  }
  renderAccount(res);
  refresh();
  if ($('#panel-portfolio') && $('#panel-portfolio').classList.contains('active')) loadPortfolio();
}

/* ---------------- 周期切换 / 排序标记 / 快捷键 / Toast ---------------- */
function periodLabel() {
  if (app.period === 'week') return '周 K';
  if (app.period === 'month') return '月 K';
  return '日 K';
}

function setPeriod(period) {
  app.period = period;
  app.mode = 'day';
  ['day', 'week', 'month', 'minute'].forEach((p) => {
    const btn = $('#btn-' + p);
    if (btn) btn.classList.toggle('active-mode',
      p === (period === 'day' ? 'day' : period) || (p === 'day' && period === 'day'));
  });
  const note = $('#chart-mode-note');
  if (note) note.textContent = periodLabel() + '：最近 120 根（由日 K 聚合）';
  if (app.bars.length) drawPriceChart(app.bars);
}

function markSortHeader() {
  $$('#watchlist-table th[data-sort]').forEach((th) => {
    th.classList.remove('sorted-asc', 'sorted-desc');
    if (th.dataset.sort === app.sortKey) {
      th.classList.add(app.sortDir === 'asc' ? 'sorted-asc' : 'sorted-desc');
    }
  });
}

function onHotkey(ev) {
  const tag = (ev.target && ev.target.tagName) || '';
  if (tag === 'INPUT' || tag === 'TEXTAREA') return;   // 输入框里别抢键
  // 指导书 / 确认弹窗打开时不抢方向键，否则会在弹层背后偷偷切换股票
  const guideEl = $('#guide');
  const modalEl = $('#modal');
  if ((guideEl && !guideEl.hidden) || (modalEl && !modalEl.hidden)) return;
  if (ev.key === 'Escape' && isPanelActive('detail')) { switchTab('watchlist'); return; }
  if (!isPanelActive('detail')) return;
  if (ev.key !== 'ArrowLeft' && ev.key !== 'ArrowRight') return;
  const list = (app.state && app.state.watchlist) || [];
  if (!list.length) return;
  const idx = list.indexOf(app.current);
  const next = ev.key === 'ArrowRight' ? idx + 1 : idx - 1;
  if (next < 0 || next >= list.length) return;
  loadDetail(list[next]);
}

let toastTimer = null;
function toast(msg, kind) {
  const el = $('#toast');
  if (!el) return;
  el.textContent = msg;
  el.className = 'toast' + (kind ? ' ' + kind : '');
  el.hidden = false;
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 2600);
}

/* ---------------- 数据源诊断 ---------------- */
async function runDiag() {
  const status = $('#diag-status');
  const out = $('#diag-out');
  if (!status || !out) return;
  status.textContent = '诊断中（会真的请求一次上游）…';
  out.hidden = true;
  const res = await api('/api/diag');
  if (!res || !res.checks) {
    status.textContent = '诊断接口不可用：' + ((res && res.error) || '无响应');
    return;
  }
  out.hidden = false;
  out.textContent = (res.checks || []).map((c) => (
    (c.ok ? '✓ ' : '✗ ') + c.name + '：' + c.detail + ' · ' + c.ms + 'ms'
    + (c.source ? ' · ' + c.source : '')
    + ((c.errors && c.errors.length) ? ' · ' + c.errors.join('; ') : '')
  )).join('\n') + '\n———\n缓存文件 ' + (res.cache_files || 0) + ' 个 · 实测总耗时 '
    + (res.elapsed_ms || 0) + 'ms · Python ' + (res.python || '?');
  status.textContent = res.ok ? '全部正常' : '有失败项（见下方）';
}

document.addEventListener('DOMContentLoaded', boot);
