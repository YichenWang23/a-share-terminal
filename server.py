# -*- coding: utf-8 -*-
"""本地服务：静态页面 + 行情代理 + 模拟盘 + 回测 + 分析。

为什么必须有它：浏览器从 file:// 直连行情接口会被 CORS 拦死，必须由本地进程代抓。
只用 Python 标准库（http.server / urllib），不装任何第三方包。

启动：
    python server.py            # 起服务并自动开浏览器
    python server.py --no-browser
    python server.py --port 8771
"""
import argparse
import json
import re
import math
import os
import socket
import sys
import time
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from stock import (account, analysis, backtest, cleaner, datasource, llm,  # noqa: E402
                   market, secrets, storage)
from stock.portfolio import Portfolio  # noqa: E402
from stock.banner import banner  # noqa: E402
from stock.rules import is_st_name, normalize_code, round2  # noqa: E402

STATIC_DIR = os.path.join(BASE_DIR, "static")

# 所有 POST 串行化：它们都是「读 state.json → 改 → 写回」，
# 并发下单/预警同时来时不加锁会丢写。
WRITE_LOCK = threading.RLock()
MIME = {
    ".webmanifest": "application/manifest+json",
    ".ico": "image/x-icon",
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
}


def today():
    return time.strftime("%Y-%m-%d")


def load_portfolio(state):
    p = Portfolio.from_dict(state.get("portfolio") or {})
    p.roll_day(today())
    return p



def lan_addresses():
    """本机局域网地址；**默认路由那张网卡排第一**（通常就是家里 WiFi）。

    过滤 127.*（本机）与 169.254.*（链路本地，连不上）。
    """
    import ipaddress

    primary = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        primary = sock.getsockname()[0]
        sock.close()
    except OSError:
        primary = None

    found = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except OSError:
        pass
    if primary:
        found.add(primary)

    def usable(ip):
        try:
            addr = ipaddress.IPv4Address(ip)
        except ValueError:
            return False
        return not (addr.is_loopback or addr.is_link_local)

    others = sorted(ip for ip in found if usable(ip) and ip != primary)
    if primary and usable(primary):
        return [primary] + others
    return others


def price_map(quotes):
    """{code: 最新价}。注意只取价格数字，不要把整条行情对象传进快照。"""
    return {q["code"]: q["price"] for q in (quotes or []) if q.get("price") is not None}


def quote_price_map(codes):
    """把一组代码换成 {code: price}，拿不到行情就给空 dict。"""
    codes = [c for c in (codes or []) if c]
    if not codes:
        return {}
    res = datasource.get_quotes(list(codes))
    return price_map(res["quotes"])

def mask_key(key):
    key = (key or "").strip()
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return key[:4] + "****" + key[-4:]


def public_settings(state):
    cfg = state.get("settings", {}).get("llm", {})
    key = secrets.get_key(cfg)
    return {"llm": {"enabled": bool(cfg.get("enabled")),
                    "base_url": cfg.get("base_url", ""),
                    "model": cfg.get("model", ""),
                    "api_key_masked": mask_key(key),
                    "has_key": bool(key),
                    "key_mode": cfg.get("api_key_mode") or ("plain" if key else "")},
            "market": market.market_status()}


class Handler(BaseHTTPRequestHandler):
    server_version = "StockSystem/1.0"

    # ---------- 基础设施 ----------
    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), fmt % args))

    def _send(self, code, payload, ctype="application/json; charset=utf-8"):
        raw = payload if isinstance(payload, bytes) else \
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, payload, code=200):
        self._send(code, payload)

    def _err(self, code, message):
        self._json({"ok": False, "error": message}, code)

    # ---------- 路由 ----------
    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        if parsed.path.startswith("/api/"):
            try:
                return self.api_get(parsed.path, qs)
            except BadRequest as exc:
                return self._err(400, str(exc))
            except Exception:  # noqa: BLE001 - 日志留全，响应不泄露内部
                traceback.print_exc()
                return self._err(500, "服务内部错误（详情见服务端窗口日志）")
        return self.serve_static(parsed.path)

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_POST_BODY:
            self.rfile.read(min(length, 4096))
            return self._err(413, "请求体过大（上限 256KB）")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            return self._err(400, "请求体不是合法 JSON")
        if not isinstance(body, dict):
            return self._err(400, "请求体必须是 JSON 对象（不能是数组/字符串/null）")
        try:
            with WRITE_LOCK:
                return self.api_post(parsed.path, body)
        except BadRequest as exc:
            return self._err(400, str(exc))
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            return self._err(500, "服务内部错误（详情见服务端窗口日志）")

    def serve_static(self, path):
        rel = path.lstrip("/") or "index.html"
        full = os.path.normpath(os.path.join(STATIC_DIR, rel))
        if not full.startswith(STATIC_DIR) or not os.path.isfile(full):
            return self._err(404, "not found: %s" % path)
        ext = os.path.splitext(full)[1].lower()
        with open(full, "rb") as f:
            data = f.read()
        self._send(200, data, MIME.get(ext, "application/octet-stream"))

    # ---------- GET API ----------
    def api_get(self, path, qs):
        first = lambda k, d=None: (qs.get(k) or [d])[0]  # noqa: E731

        if path == "/api/health":
            return self._json({"ok": True, "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                               "version": self.server_version})

        if path == "/api/diag":
            started = time.time()
            checks = []

            def add(name, ok, detail, ms, source=None, errors=None):
                checks.append({"name": name, "ok": bool(ok), "detail": detail,
                               "ms": ms, "source": source, "errors": errors or []})

            def timed(name, fn, key):
                t0 = time.time()
                try:
                    res = fn()
                    items = res.get(key) or []
                    meta = res.get("meta") or {}
                    add(name, bool(items), "%d 条" % len(items),
                        round((time.time() - t0) * 1000, 1),
                        meta.get("source"), meta.get("errors"))
                except Exception as exc:  # noqa: BLE001 - 诊断要如实记录任何异常
                    add(name, False, "%s: %s" % (type(exc).__name__, exc),
                        round((time.time() - t0) * 1000, 1))

            timed("行情", lambda: datasource.get_quotes(["600519"], allow_network=True), "quotes")
            timed("日K", lambda: datasource.get_kline("600519", limit=120, allow_network=True), "bars")
            timed("搜索", lambda: datasource.search("茅台", allow_network=True), "rows")
            t0 = time.time()
            try:
                m = datasource.get_minute("600519", allow_network=True)
                pts = ((m.get("data") or {}).get("points")) or []
                add("分时", bool(pts), "%d 个点" % len(pts),
                    round((time.time() - t0) * 1000, 1), (m.get("meta") or {}).get("source"))
            except Exception as exc:  # noqa: BLE001
                add("分时", False, "%s: %s" % (type(exc).__name__, exc),
                    round((time.time() - t0) * 1000, 1))
            try:
                cache_files = len([f for f in os.listdir(datasource.CACHE_DIR)
                                   if f.endswith(".json")])
            except OSError:
                cache_files = 0
            return self._json({"ok": all(c["ok"] for c in checks), "checks": checks,
                               "cache_files": cache_files,
                               "elapsed_ms": round((time.time() - started) * 1000, 1),
                               "python": sys.version.split()[0],
                               "server_time": time.strftime("%Y-%m-%d %H:%M:%S")})

        if path == "/api/state":
            state = storage.load()
            res = datasource.get_quotes(state["watchlist"])
            p = load_portfolio(state)
            snap = p.snapshot(price_map(res["quotes"]))
            return self._json({"ok": True, "watchlist": state["watchlist"],
                               "quotes": res["quotes"], "meta": res["meta"],
                               "portfolio": snap, "alerts": state["alerts"],
                               "settings": public_settings(state),
                               "market": market.market_status(
                                   quote_date=(res["quotes"][0].get("date")
                                               if res["quotes"] else None)),
                               "server_time": time.strftime("%Y-%m-%d %H:%M:%S")})

        if path == "/api/quote":
            codes = [c for c in (first("codes", "") or "").split(",") if c.strip()]
            if not codes:
                return self._err(400, "缺少 codes 参数")
            res = datasource.get_quotes(codes)
            return self._json({"ok": True, **res})

        if path == "/api/kline":
            code = code_param(qs)
            limit = num_param(qs, "limit", 320, int, lo=1, hi=1000, label="limit")
            res = datasource.get_kline(code, limit=limit)
            issues = cleaner.clean_bars(res["bars"])
            return self._json({"ok": True, "code": code, "bars": issues["bars"],
                               "clean_issues": issues["issues"], "clean_ok": issues["ok"],
                               "meta": res["meta"]})

        if path == "/api/minute":
            code = code_param(qs)
            res = datasource.get_minute(code)
            return self._json({"ok": True, "code": code,
                               "data": res["data"], "meta": res["meta"]})

        if path == "/api/search":
            q = first("q", "")
            res = datasource.search(q)
            return self._json({"ok": True, **res})

        if path == "/api/account":
            state = storage.load()
            p = load_portfolio(state)
            held = list(((state.get("portfolio") or {}).get("positions") or {}).keys())
            qres = datasource.get_quotes(held) if held else {
                "quotes": [], "meta": {"source": "none", "stale": False, "demo": False}}
            snap = p.snapshot(price_map(qres["quotes"]))
            acct = account.ensure_wallet(state.setdefault("account", {}))
            # 快照限流：账户页 5 秒轮询时不要每次都写盘，30 秒最多落一次
            now_ts = time.time()
            if now_ts - float(acct.get("snap_ts") or 0) >= 30:
                if account.record_snapshot(acct, today(), snap):
                    acct["snap_ts"] = now_ts
                    with WRITE_LOCK:
                        storage.save(state)
            return self._json({"ok": True,
                               "summary": account.summary(acct, snap),
                               "allocation": account.allocation(acct, snap),
                               "curve": account.equity_curve(acct),
                               "flows": account.flows(acct)[-100:],
                               "portfolio": snap,
                               "meta": qres["meta"],
                               "server_time": time.strftime("%Y-%m-%d %H:%M:%S")})

        if path == "/api/portfolio":
            state = storage.load()
            res = datasource.get_quotes([p for p in (state.get("portfolio") or {})
                                         .get("positions", {})])
            p = load_portfolio(state)
            return self._json({"ok": True,
                               "portfolio": p.snapshot(price_map(res["quotes"])),
                               "trades": p.trades[-50:], "meta": res["meta"]})

        if path == "/api/settings":
            return self._json({"ok": True, **public_settings(storage.load())})

        if path == "/api/analysis":
            code = code_param(qs)
            state = storage.load()
            qres = datasource.get_quotes([code])
            quote = (qres["quotes"] or [{}])[0]
            kres = datasource.get_kline(code, limit=320)
            issues = cleaner.clean_bars(kres["bars"])
            result = analysis.rule_engine(quote, issues["bars"])
            cfg = state.get("settings", {}).get("llm", {})
            if cfg.get("enabled"):
                p = load_portfolio(state)
                position = None
                if code in p.positions:
                    row = [r for r in p.snapshot({code: quote.get("price")})["positions"]
                           if r["code"] == code]
                    position = row[0] if row else None
                prompt = llm.build_prompt({**quote, "metrics": result["metrics"],
                                           "rule_engine": result, "position": position})
                result["llm"] = llm.call_llm(cfg, prompt)
                if result["llm"].get("ok"):
                    result["source"] = "llm"
                    result["model"] = result["llm"].get("model")
                else:
                    result["llm_note"] = "模型调用失败，已回落本地规则引擎：%s" % \
                        result["llm"].get("error")
            return self._json({"ok": True, "analysis": result, "quote": quote,
                               "clean_issues": issues["issues"],
                               "meta": {"quote": qres["meta"], "kline": kres["meta"]}})

        if path == "/api/backtest":
            code = code_param(qs)
            short = num_param(qs, "short", 5, int, lo=1, hi=250, label="短期均线")
            long_ = num_param(qs, "long", 20, int, lo=2, hi=250, label="长期均线")
            cash = num_param(qs, "cash", 100000.0, float, lo=1.0, hi=1e12, label="初始资金")
            slippage = num_param(qs, "slippage", 0.0, float, lo=0.0, hi=1000.0,
                                 label="滑点(基点)")
            fqt = (first("fqt", "qfq") or "qfq").strip().lower()
            if fqt not in ("qfq", "hfq", "bfq"):
                return self._err(400, "fqt 只能是 qfq / hfq / bfq")
            respect = str(first("respect", "1")).lower() not in ("0", "false", "no")
            if short >= long_:
                return self._err(400, "短期均线必须小于长期均线（收到 %d / %d）"
                                 % (short, long_))
            kres = datasource.get_kline(code, limit=500, fqt=fqt)
            if not kres["bars"]:
                return self._err(502, "拿不到 %s 的 K 线（接口不可达且无缓存）" % code)
            result = backtest.run_ma_cross(
                kres["bars"], short=short, long=long_, cash=cash,
                code=code, slippage_bps=slippage, respect_limits=respect)
            notes = []
            if not result["trades"] and kres["bars"]:
                first_close = float(kres["bars"][0]["close"])
                if first_close * 100 > cash:
                    notes.append("初始资金 %.0f 元买不起一手（100 股约需 %.0f 元），"
                                 "所以没有产生交易；把资金调大或换只票再试。"
                                 % (cash, first_close * 100))
            adjust_note = {"qfq": "前复权（默认）：信号连续，但历史价会在每次分红后重算，跨除权日结果可能变化",
                           "hfq": "后复权：含分红再投资、历史价固定，但价格被放大，整手资金的绝对金额会失真",
                           "bfq": "不复权：价格即真实可成交价，但不含分红收益"}.get(fqt, "")
            notes.append("复权口径：" + adjust_note)
            notes.append("回测假设：按收盘价成交、整手买入、含佣金/印花税/过户费；"
                         "滑点 %.1f 个基点；涨跌停约束%s。"
                         % (slippage, "开启（涨停不追、跌停挂单等能卖）" if respect else "关闭"))
            if result.get("skipped_buys"):
                notes.append("因涨停未能买入 %d 次。" % result["skipped_buys"])
            if result.get("delayed_sells"):
                notes.append("因跌停延迟卖出 %d 次。" % result["delayed_sells"])
            return self._json({"ok": True, "code": code, "result": result,
                               "notes": notes, "adjust": fqt, "meta": kres["meta"]})

        return self._err(404, "未知接口: %s" % path)

    # ---------- POST API ----------
    def api_post(self, path, body):
        state = storage.load()

        if path == "/api/watchlist":
            codes = body.get("codes")
            if codes is None:
                return self._err(400, "缺少 codes")
            clean = []
            for c in codes:
                c = normalize_code(c)
                if c and c not in clean:
                    clean.append(c)
            state["watchlist"] = clean[:50]
            storage.save(state)
            return self._json({"ok": True, "watchlist": state["watchlist"]})

        if path == "/api/order":
            code = normalize_code(body.get("code", ""))
            if not CODE_RE.match(code or ""):
                return self._err(400, "代码格式不对：应为 6 位数字（如 600519）")
            side = (body.get("side") or "").lower()
            if side not in ("buy", "sell"):
                return self._err(400, "side 必须是 buy 或 sell")
            qres = datasource.get_quotes([code])
            quote = (qres["quotes"] or [{}])[0]
            if (qres.get("meta") or {}).get("demo"):
                return self._json({"ok": False, "reason": "DEMO_MODE",
                                   "hint": "当前行情来自本地录制样本（演示模式），"
                                           "不能下单，避免用假数据造出幽灵成交"}, 409)
            price = body.get("price")
            price_source = "user"
            if price in (None, "", 0):
                price = quote.get("price")
                price_source = "quote"
            if price is None:
                return self._err(502, "拿不到行情且未指定价格")
            p = load_portfolio(state)
            is_st = is_st_name(quote.get("name")) or bool(body.get("is_st"))
            kwargs = {"prev_close": quote.get("prev_close"), "is_st": is_st}
            if side == "buy":
                result = p.buy(code, price, body.get("shares"), name=quote.get("name"), **kwargs)
            else:
                result = p.sell(code, price, body.get("shares"), **kwargs)
            result["price_source"] = price_source
            result["quote_meta"] = qres["meta"]
            if result.get("ok"):
                state["portfolio"] = p.to_dict()
                storage.save(state)
            result["portfolio"] = p.snapshot(price_map(qres["quotes"]))
            return self._json(result, 200 if result.get("ok") else 409)

        if path == "/api/account/flow":
            kind = body.get("type")
            if kind not in account.KINDS:
                return self._err(400, "type 必须是 deposit 或 withdraw")
            try:
                raw = float(body.get("amount"))
            except (TypeError, ValueError):
                return self._err(400, "金额必须是数字")
            # NaN/Infinity 会被 float() 正常接受；一旦写进账本，现金就变 NaN，
            # 之后所有「余额不足」比较都恒为 False。必须在入口拦住。
            if not math.isfinite(raw) or raw <= 0:
                return self._err(400, "金额必须是有限正数（不能是 NaN / Infinity）")
            if raw > 1e12:
                return self._err(400, "金额过大（上限 1e12）")
            amount = round2(raw)
            if amount <= 0:
                return self._err(400, "金额必须为正数")

            p = load_portfolio(state)
            acct = account.ensure_wallet(state.setdefault("account", {}))
            wallet = account.wallet_balance(acct)
            if kind == account.KIND_DEPOSIT:
                # 入金 = 从钱包转到证券账户
                if amount > wallet + 1e-6:
                    return self._err(400, "钱包余额 %.2f，不足以入金 %.2f" % (wallet, amount))
                acct["wallet"] = round2(wallet - amount)
                p.cash = round2(p.cash + amount)
                note = body.get("note") or "钱包 → 证券账户"
            else:
                # 出金 = 从证券账户转回钱包
                if not math.isfinite(p.cash) or amount > p.cash + 1e-6:
                    return self._err(400, "证券账户现金 %.2f，不足以出金 %.2f"
                                     % (p.cash, amount))
                p.cash = round2(p.cash - amount)
                acct["wallet"] = round2(wallet + amount)
                note = body.get("note") or "证券账户 → 钱包"

            account.add_flow(acct, kind, amount, day=today(), note=note)
            state["portfolio"] = p.to_dict()
            storage.save(state)
            snap = p.snapshot({})
            return self._json({"ok": True, "flow": account.flows(acct)[-1],
                               "summary": account.summary(acct, snap),
                               "allocation": account.allocation(acct, snap),
                               "curve": account.equity_curve(acct),
                               "flows": account.flows(acct)[-100:],
                               "portfolio": snap})

        if path == "/api/portfolio/reset":
            try:
                cash = float(body.get("cash") or 200_000.0)
            except (TypeError, ValueError):
                return self._err(400, "初始资金必须是数字")
            if not math.isfinite(cash) or cash <= 0:
                return self._err(400, "初始资金必须为正数")
            # 「重置」= 所有数据回到初始状态：模拟盘、钱包、资金流水、资产曲线、预警、自选股
            state["portfolio"] = Portfolio(cash=cash, day=today()).to_dict()
            state["account"] = account.default_account(cash, wallet=account.DEFAULT_WALLET)
            state["alerts"] = []
            state["watchlist"] = list(storage.DEFAULT_WATCHLIST)
            storage.save(state)
            p2 = load_portfolio(state)
            snap = p2.snapshot({})
            return self._json({"ok": True,
                               "portfolio": snap,
                               "account": account.summary(state["account"], snap),
                               "wallet": account.wallet_balance(state["account"]),
                               "watchlist": list(state["watchlist"])})

        if path == "/api/alerts":
            action = body.get("action")
            alerts = state.get("alerts") or []
            if action == "add":
                code = normalize_code(body.get("code", ""))
                op = body.get("op")
                try:
                    price = float(body.get("price"))
                except (TypeError, ValueError):
                    return self._err(400, "price 必须是数字")
                if not code or op not in ("above", "below") or price <= 0:
                    return self._err(400, "需要 code / op(above|below) / price>0")
                alerts.append({"id": int(time.time() * 1000), "code": code,
                               "op": op, "price": price,
                               "created": time.strftime("%Y-%m-%d %H:%M:%S")})
            elif action == "remove":
                try:
                    target = int(body.get("id"))
                except (TypeError, ValueError):
                    return self._err(400, "id 必须是整数")
                alerts = [a for a in alerts if a.get("id") != target]
            else:
                return self._err(400, "action 必须是 add 或 remove")
            state["alerts"] = alerts
            storage.save(state)
            return self._json({"ok": True, "alerts": alerts})

        if path == "/api/settings":
            given = body.get("llm") or {}
            cfg = state["settings"]["llm"]
            for key in ("enabled", "base_url", "model"):
                if key in given:
                    cfg[key] = given[key]
            if given.get("api_key"):
                secrets.set_key(cfg, str(given["api_key"]).strip())
            if given.get("clear_key"):
                cfg["api_key"] = ""
                cfg["api_key_enc"] = ""
                cfg["api_key_mode"] = ""
            cfg["enabled"] = bool(cfg.get("enabled"))
            state["settings"]["llm"] = cfg
            storage.save(state)
            return self._json({"ok": True, **public_settings(state)})

        return self._err(404, "未知接口: %s" % path)


MAX_POST_BODY = 256 * 1024   # 请求体上限 256KB
CODE_RE = re.compile(r"^\d{6}$")


def code_param(qs):
    """代码必须是 6 位数字；格式不对直接 400，不要拿去打网络接口。"""
    code = normalize_code((qs.get("code") or [""])[0])
    if not code:
        raise BadRequest("缺少 code 参数")
    if not CODE_RE.match(code):
        raise BadRequest("代码格式不对：应为 6 位数字（如 600519），收到 %r" % code)
    return code


class BadRequest(Exception):
    """参数不合法 —— 一律 400，不要冒泡成 500。"""


def num_param(qs, name, default, cast=float, lo=None, hi=None, label=None):
    """严格解析数值参数：非数字 / NaN / Infinity / 越界 => BadRequest(400)。"""
    raw = (qs.get(name) or [None])[0]
    label = label or name
    if raw is None or raw == "":
        return default
    try:
        value = cast(raw)
    except (TypeError, ValueError):
        raise BadRequest("%s 必须是数字（收到 %r）" % (label, raw))
    if cast is float and not math.isfinite(value):
        raise BadRequest("%s 必须是有限数，不能是 NaN / Infinity" % label)
    if lo is not None and value < lo:
        raise BadRequest("%s 不能小于 %s（收到 %s）" % (label, lo, value))
    if hi is not None and value > hi:
        raise BadRequest("%s 不能大于 %s（收到 %s）" % (label, hi, value))
    return value


class SingleInstanceServer(ThreadingHTTPServer):
    """不允许端口复用：重复启动必须直接报错，而不是和旧实例抢同一个端口。"""

    allow_reuse_address = False
    daemon_threads = True



def _ensure_streams():
    """pythonw / 无控制台启动时 stdout、stderr 是 None，日志写入会抛异常并断连接。

    这里把它们重定向到 data/server.log，既避免崩溃，又保留排查线索。
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    log_dir = os.path.join(BASE_DIR, "data")
    try:
        os.makedirs(log_dir, exist_ok=True)
        log = open(os.path.join(log_dir, "server.log"), "a", encoding="utf-8", buffering=1)  # noqa: SIM115
    except OSError:
        log = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    if sys.stdout is None:
        sys.stdout = log
    if sys.stderr is None:
        sys.stderr = log


def main(argv=None):
    _ensure_streams()
    parser = argparse.ArgumentParser(description="A 股本地股票系统")
    parser.add_argument("--port", type=int, default=int(os.environ.get("STOCK_PORT", 8770)))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)

    if os.environ.get("STOCK_NO_BANNER") != "1":
        try:
            banner(animate=True)
        except Exception:  # noqa: BLE001 - 动画失败不能影响启动
            pass
    try:
        server = SingleInstanceServer((args.host, args.port), Handler)
    except OSError as exc:
        url = "http://%s:%d/" % (args.host, args.port)
        print("启动失败：端口 %d 已被占用（%s）。" % (args.port, exc))
        print("可能已经有一个股票系统在跑：直接在浏览器打开 %s" % url)
        print("如果占用端口的是别的程序，换一个端口：python server.py --port 8771")
        return 2
    url = "http://%s:%d/" % (args.host, args.port)
    print("=" * 60)
    print("A股本地股票系统已启动：%s" % url)
    if args.host in ("0.0.0.0", ""):
        addrs = lan_addresses()
        if addrs:
            print("  同学访问地址：http://%s:%d/  （同一 WiFi 下）" % (addrs[0], args.port))
            for ip in addrs[1:]:
                print("    其他网卡：http://%s:%d/" % (ip, args.port))
        else:
            print("  没检测到局域网地址，检查一下网络连接")
    print("这个窗口就是服务本体，运行期间请勿关闭；停止请按 Ctrl+C。")
    print("数据源：腾讯行情/K线为主，新浪备用，东财搜索查代码；断网时用缓存或样本（页面会标注）")
    print("=" * 60)
    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001 - 打不开浏览器不影响服务
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
