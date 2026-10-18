// tests/test_frontend_logic.mjs
// 验证「5 秒刷新到底更新了图表没有」——不靠肉眼，直接把 app.js 放进桩 DOM 里跑。
//
// 运行（单行，结尾什么都别接）：
//   node --test tests/test_frontend_logic.mjs
//
// 覆盖：
//   1) patchLastBar：同一交易日只改最后一根；更旧的数据不覆盖；更新的日期追加新一根
//   2) patchMinute：分时模式下更新最后一点价格
//   3) 价格没变时不动数据（避免无意义重绘）
//   4) 画图函数在桩环境下不抛错（证明更新路径能走完）

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP = path.join(HERE, '..', 'static', 'app.js');

const ctxStub = new Proxy({}, {
  get(_t, key) {
    if (key === 'measureText') return () => ({ width: 10 });
    if (key === 'canvas') return {};
    return () => {};
  },
  set() { return true; },
});

function fakeEl() {
  const classes = new Set();
  return {
    classList: {
      add(...names) { names.forEach((n) => classes.add(n)); },
      remove(...names) { names.forEach((n) => classes.delete(n)); },
      toggle(name, force) {
        const on = force === undefined ? !classes.has(name) : !!force;
        if (on) classes.add(name); else classes.delete(name);
        return on;
      },
      contains(name) { return classes.has(name); },
    },
    style: {}, dataset: {}, textContent: '', innerHTML: '', value: '', checked: false,
    clientWidth: 800, width: 0, height: 0, hidden: false, offsetHeight: 20,
    _listeners: Object.create(null),
    addEventListener(type, fn) {
      (this._listeners[type] || (this._listeners[type] = [])).push(fn);
    },
    removeEventListener(type, fn) {
      const list = this._listeners[type] || [];
      const i = list.indexOf(fn);
      if (i >= 0) list.splice(i, 1);
    },
    dispatch(type, ev) {
      (this._listeners[type] || []).slice().forEach((fn) => fn(ev || { target: this }));
    },
    appendChild() {}, remove() {}, focus() {}, blur() {},
    querySelector() { return fakeEl(); },
    querySelectorAll() { return []; },
    closest() { return null; },
    getContext() { return ctxStub; },
    getBoundingClientRect() { return { left: 0, top: 0, width: 800, height: 400 }; },
  };
}

function loadApp() {
  const source = readFileSync(APP, 'utf8');
  const docCache = new Map();
  const sandbox = {
    document: {
      // 同一个选择器返回同一个元素：按钮高亮 / 表头 class 才测得出来
      // 同一个选择器返回同一个元素，按钮高亮状态才测得出来
      querySelector: (sel) => {
        if (!docCache.has(sel)) docCache.set(sel, fakeEl());
        return docCache.get(sel);
      },
      // 表头：给 5 个可排序字段造桩元素（markSortHeader 靠 querySelectorAll 取）
      querySelectorAll: (sel) => {
        if (sel.indexOf('th[data-sort]') >= 0) {
          return ['code', 'name', 'price', 'change', 'change_pct'].map((key) => {
            const el = docCache.get('th-' + key) || fakeEl();
            docCache.set('th-' + key, el);
            el.dataset.sort = key;
            return el;
          });
        }
        return [];
      },
      createElement: () => fakeEl(),
      _listeners: Object.create(null),
      addEventListener(type, fn) {
        (this._listeners[type] || (this._listeners[type] = [])).push(fn);
      },
      removeEventListener(type, fn) {
        const list = this._listeners[type] || [];
        const i = list.indexOf(fn);
        if (i >= 0) list.splice(i, 1);
      },
      dispatch(type, ev) {
        (this._listeners[type] || []).slice().forEach((fn) => fn(ev || {}));
      },
    },
    window: { addEventListener() {}, innerWidth: 1200, devicePixelRatio: 1, confirm: () => false },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    requestAnimationFrame: (fn) => setTimeout(fn, 0),
    setTimeout, clearTimeout, setInterval, clearInterval,
    console, Math, Date, JSON, Number, String, Boolean, Array, Object, Promise, isNaN,
    parseInt, parseFloat, encodeURIComponent, decodeURIComponent, URLSearchParams,
    BroadcastChannel: undefined,
    fetch: () => Promise.reject(new Error('no network in test')),
  };
  // 暴露被测函数：在源码末尾返回
  const wrapped = `${source}\n;return { app, patchLastBar, patchMinute, fmt, pct, dirCls, limitPctOf, aggregateBars, sortQuotes, matchQuote, setPeriod, switchChartMode, markSortHeader, document, window, loadDetail, redrawCurrentChart, showConfirm, renderAnalysis, splashSeries, finishSplash, BOOT_STEPS, renderBootStep, bootAdvance, bootState, showWelcome, WELCOME_TEXT, WELCOME_LINES, GUIDE_PAGES, guideNav, openGuide, renderGuidePage, get api() { return api; }, setApi(fn) { api = fn; } };`;
  const keys = Object.keys(sandbox);
  const values = keys.map((k) => sandbox[k]);
  // eslint-disable-next-line no-new-func
  const factory = new Function(...keys, wrapped);
  return factory(...values);
}

const F = loadApp();

function resetBars() {
  F.app.bars = [
    { date: '2026-10-16', open: 10, close: 10.5, high: 11, low: 9.5, volume: 100 },
    { date: '2026-10-17', open: 10.5, close: 11, high: 11.2, low: 10.4, volume: 120 },
  ];
  F.app.hover = null;
}

test('fmt / pct / dirCls 基本行为', () => {
  assert.equal(F.fmt(1.234, 2), '1.23');
  assert.equal(F.fmt(null), '—');
  assert.equal(F.pct(1.2), '+1.20%');
  assert.equal(F.pct(-0.5), '-0.50%');
  assert.equal(F.dirCls(1), 'up');
  assert.equal(F.dirCls(-1), 'down');
  assert.equal(F.dirCls(0), '');
});

test('patchLastBar：同一交易日更新最后一根（开高低收/量）', () => {
  resetBars();
  F.patchLastBar({ price: 12, high: 12.2, low: 9.4, volume: 200,
                   timestamp: '2026-10-17 14:00:00' });
  const last = F.app.bars[F.app.bars.length - 1];
  assert.equal(F.app.bars.length, 2, '不该新增 K 线');
  assert.equal(last.close, 12);
  assert.equal(last.high, 12.2);
  assert.equal(last.low, 9.4);
  assert.equal(last.volume, 200);
});

test('patchLastBar：更旧日期的行情不会倒着覆盖历史', () => {
  resetBars();
  const before = JSON.stringify(F.app.bars);
  F.patchLastBar({ price: 99, timestamp: '2026-10-15 15:00:00' });
  assert.equal(JSON.stringify(F.app.bars), before, '旧数据必须被忽略');
});

test('patchLastBar：更新的交易日会追加新的一根', () => {
  resetBars();
  F.patchLastBar({ price: 12.3, high: 12.5, low: 12.0, volume: 50,
                   timestamp: '2026-10-20 09:31:00' });
  const last = F.app.bars[F.app.bars.length - 1];
  assert.equal(F.app.bars.length, 3);
  assert.equal(last.date, '2026-10-20');
  assert.equal(last.close, 12.3);
});

test('patchLastBar：价格没变就不动数据（避免无意义重绘）', () => {
  resetBars();
  const before = JSON.stringify(F.app.bars);
  F.patchLastBar({ price: 11, timestamp: '2026-10-17 14:00:00' });
  assert.equal(JSON.stringify(F.app.bars), before);
});

test('patchMinute：分时模式下更新最后一点价格', () => {
  F.app.mode = 'minute';
  F.app.minute = { date: '2026-10-17', prev_close: 10,
    points: [{ time: '09:30', price: 10, avg_price: 10, volume: 1, cum_volume: 1 },
             { time: '09:31', price: 10.2, avg_price: 10.1, volume: 2, cum_volume: 3 }] };
  F.patchMinute({ price: 10.8 });
  assert.equal(F.app.minute.points[1].price, 10.8);
  F.app.mode = 'day';
});

test('patchMinute：非分时模式不碰分时数据', () => {
  F.app.mode = 'day';
  F.app.minute = { points: [{ time: '09:30', price: 10 }] };
  F.patchMinute({ price: 99 });
  assert.equal(F.app.minute.points[0].price, 10);
});

// ---------------- 体验增强的纯函数 ----------------
test('limitPctOf：主板 10%、创业板/科创板 20%、ST 5%', () => {
  assert.equal(F.limitPctOf('600519', '贵州茅台'), 0.10);
  assert.equal(F.limitPctOf('000001', '平安银行'), 0.10);
  assert.equal(F.limitPctOf('300750', '宁德时代'), 0.20);
  assert.equal(F.limitPctOf('301000', '某创业板'), 0.20);
  assert.equal(F.limitPctOf('688981', '中芯国际'), 0.20);
  assert.equal(F.limitPctOf('600519', 'ST 某股'), 0.05);
  assert.equal(F.limitPctOf('600519', ''), 0.10);
});

test('aggregateBars：日 K 聚合成周 K（开高低收量都对）', () => {
  const bars = [
    { date: '2026-10-12', open: 10, high: 11, low: 9.5, close: 10.5, volume: 100 },
    { date: '2026-10-13', open: 10.5, high: 12, low: 10.4, close: 11.5, volume: 200 },
    { date: '2026-10-14', open: 11.5, high: 11.8, low: 11.0, close: 11.2, volume: 150 },
    { date: '2026-10-15', open: 11.2, high: 11.4, low: 10.8, close: 11.0, volume: 50 },
    { date: '2026-10-16', open: 11.0, high: 11.1, low: 10.6, close: 10.9, volume: 80 },
    { date: '2026-10-19', open: 10.9, high: 11.6, low: 10.7, close: 11.4, volume: 120 },
  ];
  const week = F.aggregateBars(bars, 'week');
  assert.equal(week.length, 2);
  assert.equal(week[0].open, 10);          // 首日开盘
  assert.equal(week[0].close, 10.9);       // 末日收盘
  assert.equal(week[0].high, 12);          // 周内最高
  assert.equal(week[0].low, 9.5);          // 周内最低
  assert.equal(week[0].volume, 580);       // 成交量累加
  assert.equal(week[1].open, 10.9);
});

test('aggregateBars：按月聚合 / day 原样返回', () => {
  const bars = [
    { date: '2026-09-28', open: 1, high: 2, low: 0.5, close: 1.5, volume: 10 },
    { date: '2026-09-30', open: 1.5, high: 2.5, low: 1.2, close: 2.0, volume: 20 },
    { date: '2026-10-08', open: 2.0, high: 3.0, low: 1.9, close: 2.8, volume: 30 },
  ];
  const month = F.aggregateBars(bars, 'month');
  assert.equal(month.length, 2);
  assert.equal(month[0].close, 2.0);
  assert.equal(month[0].volume, 30);
  assert.equal(F.aggregateBars(bars, 'day').length, 3);
  assert.equal(F.aggregateBars(null, 'week').length, 0);
});

test('sortQuotes：数值降序/升序、字符串按中文排序', () => {
  const rows = [
    { code: '600519', name: '贵州茅台', change_pct: 1.2 },
    { code: '000001', name: '平安银行', change_pct: -0.8 },
    { code: '300750', name: '宁德时代', change_pct: 2.5 },
  ];
  assert.deepEqual(F.sortQuotes(rows, 'change_pct', 'desc').map((r) => r.code),
    ['300750', '600519', '000001']);
  assert.deepEqual(F.sortQuotes(rows, 'change_pct', 'asc').map((r) => r.code),
    ['000001', '600519', '300750']);
  assert.deepEqual(F.sortQuotes(rows, 'code', 'asc').map((r) => r.code),
    ['000001', '300750', '600519']);
  assert.deepEqual(F.sortQuotes(rows, '', 'desc').map((r) => r.code),
    ['600519', '000001', '300750'], '没排序字段时保持原顺序');
});

test('matchQuote：按代码或名称过滤，空关键字全匹配', () => {
  const q = { code: '600519', name: '贵州茅台' };
  assert.equal(F.matchQuote(q, ''), true);
  assert.equal(F.matchQuote(q, '6005'), true);
  assert.equal(F.matchQuote(q, '茅台'), true);
  assert.equal(F.matchQuote(q, '平安'), false);
  assert.equal(F.matchQuote(q, '  '), true);
});

test('costOf：positions 是数组时也能取到持仓成本', () => {
  F.app.state = { portfolio: { positions: [{ code: '600519', avg_cost: 1300.5 }] } };
  assert.equal(F.app.costOf('600519'), 1300.5);
  assert.equal(F.app.costOf('000001'), 0);
  F.app.state = { portfolio: { positions: { '600519': { avg_cost: 1200 } } } };
  assert.equal(F.app.costOf('600519'), 1200, '字典形态也要支持');
});

// ---------------- DOM 级：按钮高亮与周期状态 ----------------
test('setPeriod：切换周期会把高亮切到对应按钮', () => {
  resetBars();
  F.app.current = '600519';
  F.setPeriod('week');
  assert.equal(F.app.period, 'week');
  assert.equal(F.app.mode, 'day');
  assert.equal(F.document.querySelector('#btn-week').classList.contains('active-mode'), true);
  assert.equal(F.document.querySelector('#btn-day').classList.contains('active-mode'), false);
  F.setPeriod('month');
  assert.equal(F.document.querySelector('#btn-month').classList.contains('active-mode'), true);
  assert.equal(F.document.querySelector('#btn-week').classList.contains('active-mode'), false);
});

test('switchChartMode：从周/月切回日 K 会重置周期（否则按钮和图对不上）', () => {
  resetBars();
  F.app.current = '600519';
  F.setPeriod('month');
  assert.equal(F.app.period, 'month');
  F.switchChartMode('day');
  assert.equal(F.app.period, 'day');
  assert.equal(F.document.querySelector('#btn-day').classList.contains('active-mode'), true);
  assert.equal(F.document.querySelector('#btn-month').classList.contains('active-mode'), false);
});

test('markSortHeader：排序字段与方向反映到表头 class', () => {
  F.app.sortKey = 'change_pct';
  F.app.sortDir = 'desc';
  F.markSortHeader();
  const th = F.document.querySelectorAll('#watchlist-table th[data-sort]')
    .find((el) => el.dataset.sort === 'change_pct');
  assert.equal(th.classList.contains('sorted-desc'), true);
  assert.equal(th.classList.contains('sorted-asc'), false);
  F.app.sortDir = 'asc';
  F.markSortHeader();
  assert.equal(th.classList.contains('sorted-asc'), true);
  assert.equal(th.classList.contains('sorted-desc'), false);
});


// ---------------- 详情页竞态 ----------------
test('loadDetail 的请求序号：慢返回的旧请求必须被丢弃', async () => {
  // 桩掉网络：A 慢（80ms）、B 快（5ms），先发 A 再发 B
  const realApi = F.api;
  const delays = { 600519: 80, 601857: 5 };
  const sandboxApi = async (path) => {
    const m = /code=(\d{6})/.exec(path);
    const code = m ? m[1] : '';
    await new Promise((r) => setTimeout(r, delays[code] || 1));
    const px = code === '601857' ? 9.9 : 1.5;   // 用不同价格区分数据来源
    return { ok: true,
             bars: [{ date: '2026-10-16', open: px, high: px, low: px, close: px, volume: 1 }],
             analysis: { score: 0, source: 'rule-engine' },
             quote: { code: code, price: px } };
  };
  F.setApi(sandboxApi);
  const a = F.loadDetail('600519');
  const b = F.loadDetail('601857');
  await Promise.all([a, b]);
  F.setApi(realApi);
  assert.equal(F.app.current, '601857', '最后一次点击的股票必须胜出');
  assert.equal(F.app.bars[0].close, 9.9,
    '渲染出来的必须是 601857 的数据，不能被慢返回的 600519 覆盖');
});


// ---------------- 演示快照模式 ----------------
test('演示页里没内联的请求：明确提示，不再误报服务没在跑', async () => {
  const saved = F.window.__DEMO__;
  F.window.__DEMO__ = { '/api/state': { ok: true, watchlist: [] } };
  const res = await F.api('/api/kline?code=601857&limit=320');
  F.window.__DEMO__ = saved;
  assert.equal(res.ok, false);
  assert.equal(res.demoMissing, true, '要标成「演示快照缺数据」，而不是网络失败');
  assert.ok(String(res.error).includes('演示快照'), '错误文案要点明原因：' + res.error);
  assert.ok(!String(res.error).includes('服务是否还在运行'), '不能误导成服务挂了');
});


// ---------------- 详情页：不许递归/重试爆炸 ----------------
test('详情请求失败时不会无限递归（最多一次请求链）', async () => {
  const realApi = F.api;
  let calls = 0;
  F.setApi(async () => { calls += 1; return { ok: false, network: true, error: '服务没起来' }; });
  F.app.bars = [];
  await F.loadDetail('601857', { force: true });
  F.setApi(realApi);
  // 一次尝试 = K线 + 分析 两个请求；网络类错误不该进入下一轮重试
  assert.ok(calls <= 2, '网络类错误不该重试，实际请求 ' + calls + ' 次');
  assert.equal(F.app.detailLoading, false, '失败后必须释放加载标记');
});






// ---------------- 确认弹窗交互 ----------------
test('showConfirm：默认隐藏，点「确定重置」返回 true 并关闭', async () => {
  const modal = F.document.querySelector('#modal');
  const ok = F.document.querySelector('#modal-ok');
  const cancel = F.document.querySelector('#modal-cancel');
  modal.hidden = true;

  const p = F.showConfirm({ title: '重置所有数据？', body: '<b>x</b>', okText: '确定重置', danger: true });
  assert.equal(modal.hidden, false, '打开弹窗后不能还是隐藏的');
  assert.equal(ok.textContent, '确定重置');
  assert.ok(String(ok.className).includes('danger'), '危险操作要红色样式');

  ok.dispatch('click');
  assert.equal(await p, true, '点确定应 resolve(true)');
  assert.equal(modal.hidden, true, '点完必须关掉弹窗');

  const p2 = F.showConfirm({ title: 't', body: 'b' });
  cancel.dispatch('click');
  assert.equal(await p2, false, '点取消应 resolve(false)');
  assert.equal(modal.hidden, true);
});


// ---------------- 新手指导书 ----------------
test('GUIDE_PAGES：8 页，首页封面、末页尾图、中间是规则', () => {
  assert.equal(F.GUIDE_PAGES.length, 8);
  assert.equal(F.GUIDE_PAGES[0].type, 'cover');
  assert.equal(F.GUIDE_PAGES[7].type, 'end');
  const textPages = F.GUIDE_PAGES.filter((p) => p.type === 'text');
  assert.equal(textPages.length, 6, '规则页应有 6 页');
  // 关键规则都覆盖到
  const all = textPages.map((p) => p.title + p.body).join('');
  for (const kw of ['9:15', '100 股', '±10%', 'T+1', '佣金', '模拟盘']) {
    assert.ok(all.includes(kw), '指导书缺少关键内容：' + kw);
  }
});

test('guideNav：翻到边界就停住，不越界', () => {
  assert.equal(F.guideNav(0, -1, 8), 0, '第一页再往前还是第一页');
  assert.equal(F.guideNav(7, 1, 8), 7, '最后一页再往后还是最后一页');
  assert.equal(F.guideNav(3, 1, 8), 4);
  assert.equal(F.guideNav(3, -1, 8), 2);
  assert.equal(F.guideNav(0, 1, 1), 0, '只有一页时不越界');
});

test('openGuide：打开后页码与按钮状态正确', () => {
  const modal = F.document.querySelector('#guide');
  if (!modal) return;   // 沙箱里没有指导书结构就跳过
  F.openGuide(0);
  assert.equal(modal.hidden, false);
});


test('renderGuidePage：三种页型都渲染出正确内容', () => {
  const box = F.document.querySelector('#guide-page');
  F.openGuide(0);
  assert.ok(box.innerHTML.includes('guide-cover'), '封面页应有封面容器');
  assert.ok(box.innerHTML.includes('新手指导书'), '封面应叠标题');
  assert.ok(box.innerHTML.includes('guide-cover.png'), '封面应引用封面图');

  F.openGuide(1);
  assert.ok(box.innerHTML.includes('什么时候能买卖'), '第 2 页应是交易时间');
  assert.ok(box.innerHTML.includes('9:15'), '交易时间要写集合竞价');

  F.openGuide(3);
  assert.ok(box.innerHTML.includes('涨跌停'), '第 4 页应是涨跌停');
  assert.ok(box.innerHTML.includes('±20%'), '要写创业板/科创板 20%');

  F.openGuide(5);
  assert.ok(box.innerHTML.includes('佣金'), '第 6 页应是费用');

  F.openGuide(7);
  assert.ok(box.innerHTML.includes('guide-end'), '最后一页应是尾图');
  assert.ok(box.innerHTML.includes('guide-end.png'));

  const ind = F.document.querySelector('#guide-ind');
  assert.equal(ind.textContent, '8 / 8', '末页页码应为 8 / 8');
});


// ---------------- AI 解读渲染 ----------------
test('模型解读渲染：成功时显示大白话块，失败时隐藏', () => {
  const box = F.document.querySelector('#ai-model');
  F.renderAnalysis({
    stance: '中性', score: 10, bullets: ['规则一'], risks: ['风险一'],
    disclaimer: '仅供参考', source: 'llm', model: 'deepseek-chat',
    llm: { ok: true, text: '短期偏弱，但还没到慌的时候。' },
  });
  assert.equal(box.hidden, false, '模型成功时解读块应显示');
  assert.ok(box.innerHTML.includes('大白话解读'), '要有「大白话解读」标题');
  assert.ok(box.innerHTML.includes('deepseek-chat'), '要标出模型名');
  assert.ok(box.innerHTML.includes('短期偏弱'), '要展示模型正文');

  F.renderAnalysis({
    stance: '偏空', score: -30, bullets: [], risks: [], disclaimer: '',
    source: 'rule-engine', llm: { ok: false, error: '连接超时' }, llm_note: '模型调用失败，已回落本地规则引擎：连接超时',
  });
  assert.equal(box.hidden, true, '模型失败时应隐藏解读块');
  const bullets = F.document.querySelector('#ai-bullets');
  assert.ok(String(bullets.innerHTML).includes('回落'), '失败原因要出现在列表里');
});


// ---------------- 图表重绘必须跟随模式 ----------------
test('redrawCurrentChart：分时模式绝不跳回 K 线图', () => {
  F.app.bars = [{ date: '2026-10-16', open: 10, high: 11, low: 9.5, close: 10.5, volume: 100 }];
  F.app.minute = {
    date: '2026-10-16', prev_close: 10,
    points: [
      { time: '09:30', price: 10.0, avg_price: 10.0, volume: 5, cum_volume: 5 },
      { time: '09:31', price: 10.2, avg_price: 10.1, volume: 3, cum_volume: 8 },
    ],
  };
  F.app.period = 'month';   // 复现用户场景：之前点过月 K
  F.app.mode = 'minute';
  assert.equal(F.redrawCurrentChart(), 'minute', '分时模式应重画分时图');

  F.app.mode = 'day';
  assert.equal(F.redrawCurrentChart(), 'day', '日K模式应重画K线');

  F.app.minute = null;
  F.app.mode = 'minute';
  assert.equal(F.redrawCurrentChart(), 'day', '没有分时数据时退回K线，不能白屏');

  F.app.bars = [];
  assert.equal(F.redrawCurrentChart(), 'none', '什么都没有时什么都不画');
});


// ---------------- 开机启动动画 ----------------
test('splashSeries：动画数据形状固定、有多空交替', () => {
  const s = F.splashSeries();
  assert.equal(s.length, 18, '固定 18 根蜡烛');
  assert.equal(s[0].up, true, '开头是阳线');
  for (const b of s) {
    assert.ok(b.high >= Math.max(b.open, b.close), '最高价不能低于实体');
    assert.ok(b.low <= Math.min(b.open, b.close), '最低价不能高于实体');
    assert.equal(typeof b.up, 'boolean');
  }
  assert.ok(s.some((b) => b.up) && s.some((b) => !b.up), '要有涨有跌才像行情');
});

test('finishSplash：结束后动画隐藏', async () => {
  const el = F.document.querySelector('#splash');
  el.classList.remove('done');
  F.finishSplash();
  await new Promise((r) => setTimeout(r, 400));
  assert.equal(el.classList.contains('done'), true, 'finishSplash 后应加 done 类');
  F.finishSplash();   // 幂等：重复调用不报错
});


// ---------------- 访问认证序列 ----------------
test('认证序列：三步，必须点完才进系统', () => {
  assert.equal(F.BOOT_STEPS.length, 3, '三步授权');
  const titles = F.BOOT_STEPS.map((s) => s.title).join('|');
  assert.ok(titles.includes('身份核验') && titles.includes('授权') && titles.includes('风险'), titles);
  F.renderBootStep(0);
  assert.deepEqual(F.bootState(), { step: 0, finished: false });
  // instant=true：跳过「校验中」的动画等待，直接断言状态机
  F.bootAdvance({ instant: true });
  assert.equal(F.bootState().step, 1, '点一次进入第二步');
  F.bootAdvance({ instant: true });
  assert.equal(F.bootState().step, 2, '再点进入第三步');
  assert.equal(F.bootState().finished, false, '最后一步之前不能算完成');
  F.bootAdvance({ instant: true });
  assert.equal(F.bootState().finished, true, '第三次点击后进入系统');
  // 校验只在三步内：每一步都带 verify 文案与耗时
  for (const s of F.BOOT_STEPS) {
    assert.ok(s.verify && s.ms >= 800, '每步都要有校验过程：' + s.title);
  }
});


// ---------------- 欢迎语收尾 ----------------
test('欢迎语：文案固定，进入欢迎阶段会淡出认证 UI', () => {
  assert.equal(F.WELCOME_TEXT, '欢迎你，天才交易员');
  assert.deepEqual(F.WELCOME_LINES, [
    '天下英雄如过江之鲫',
    '皆以凡人之力，与顶级资本搏杀',
    '欢迎你，天才交易员',
  ], '三句顺序固定');
  const splash = F.document.querySelector('#splash');
  splash.classList.remove('welcome-stage');
  const box = F.document.querySelector('#welcome');
  box.hidden = true;
  F.showWelcome();
  assert.equal(splash.classList.contains('welcome-stage'), true, '要切换到欢迎阶段');
  assert.equal(box.hidden, false, '欢迎语要显示出来');
});
