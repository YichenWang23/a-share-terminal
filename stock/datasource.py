# -*- coding: utf-8 -*-
"""行情数据源：腾讯为主、新浪为备、东财搜索查代码；带磁盘缓存与 fixtures 降级。

实测结论（见 tools/probe_report.json）：
  * 腾讯 qt.gtimg.cn 实时行情、web.ifzq.gtimg.cn 日 K —— 可用，且直接给涨停/跌停价；
  * 新浪 hq.sinajs.cn —— 可用，作为实时行情备用；
  * 东财 push2/push2his 的 quote/kline 在本机被 RemoteDisconnected 断开（不列为主源）；
  * 东财 searchapi —— 可用，用于按名称查代码。

降级链：实时接口 -> 磁盘缓存（标 stale）-> fixtures（标 demo）。
绝不把样本数据伪装成实时数据。
"""
import hashlib
import json
import os
import time
import urllib.parse
import urllib.request

from .rules import normalize_code, tencent_symbol

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(BASE_DIR, "fixtures")
CACHE_DIR = os.path.join(BASE_DIR, "data", "cache")

TENCENT_QUOTE = "https://qt.gtimg.cn/q="
TENCENT_KLINE = ("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
                 "?param=%s,day,,,%d,%s")
SINA_QUOTE = "https://hq.sinajs.cn/list="
TENCENT_MINUTE = "https://web.ifzq.gtimg.cn/appstock/app/minute/query?code=%s"
SINA_KLINE = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
              "CN_MarketData.getKLineData?symbol=%s&scale=240&ma=no&datalen=%d")
EM_SEARCH = ("https://searchapi.eastmoney.com/api/suggest/get?input=%s&type=14"
             "&token=D43BF722C8E33BDC906FB84D85E326E8&count=%d")


class FetchError(Exception):
    """上游请求失败；status 非空表示 HTTP 状态码（用于决定要不要重试）。"""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


    pass


def _http_get_once(url, headers=None, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as exc:
        raise FetchError("HTTPError: %s" % exc, status=exc.code) from exc
    except Exception as exc:  # noqa: BLE001 - 统一包装成 FetchError
        raise FetchError("%s: %s" % (type(exc).__name__, exc)) from exc


def http_get(url, headers=None, timeout=12, attempts=None, backoff=None):
    """带重试的上游请求：偶发失败自动重试，仍失败才抛 FetchError（带最后一次原因）。"""
    attempts = FETCH_ATTEMPTS if attempts is None else max(1, int(attempts))
    backoff = FETCH_BACKOFF if backoff is None else float(backoff)
    last = None
    for i in range(attempts):
        try:
            return _http_get_once(url, headers, timeout)
        except FetchError as exc:
            last = exc
            status = getattr(exc, "status", None)
            if status in (400, 401, 403, 404, 429, 501):
                break          # 确定性失败，重试只是白等
            if i < attempts - 1 and backoff > 0:
                time.sleep(backoff * (i + 1))
    raise last if last else FetchError("unknown fetch error")


def _f(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# 解析：全部是纯函数，测试用 fixtures 直接喂字节
# --------------------------------------------------------------------------
def parse_tencent_quotes(raw):
    """解析 v_sh600519="..." 形式（GBK），返回行情列表。"""
    text = raw.decode("gbk", "replace")
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("v_") or "=" not in line:
            continue
        head, _, rest = line.partition("=")
        payload = rest.strip().rstrip(";").strip()
        if not payload.startswith('"'):
            continue
        parts = payload.strip('"').split("~")
        if len(parts) < 50:
            continue
        code = normalize_code(parts[2])
        price = _f(parts[3])
        prev = _f(parts[4])
        if not code or price is None or prev is None:
            continue
        ts = parts[30]
        stamp = ""
        if len(ts) >= 14 and ts[:8].isdigit():
            stamp = "%s-%s-%s %s:%s:%s" % (ts[0:4], ts[4:6], ts[6:8],
                                           ts[8:10], ts[10:12], ts[12:14])
        out.append({
            "code": code, "symbol": head[2:], "name": parts[1],
            "price": price, "prev_close": prev, "open": _f(parts[5]),
            "high": _f(parts[33]), "low": _f(parts[34]),
            "volume": _f(parts[6]), "amount": _f(parts[37]),
            "change": _f(parts[31]), "change_pct": _f(parts[32]),
            "turnover": _f(parts[38]), "pe": _f(parts[39]), "pb": _f(parts[46]),
            "limit_up": _f(parts[47]), "limit_down": _f(parts[48]),
            "timestamp": stamp, "date": stamp[:10], "source": "tencent",
        })
    return out


def parse_tencent_kline(raw):
    """解析 fqkline 响应，返回 [{date,open,close,high,low,volume}]。"""
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return []
    node_root = data.get("data") or {}
    if not isinstance(node_root, dict):
        return []
    for node in node_root.values():
        if not isinstance(node, dict):
            continue
        for field in ("qfqday", "day", "hfqday"):
            rows = node.get(field)
            if not isinstance(rows, list) or not rows:
                continue
            bars = []
            for row in rows:
                if not isinstance(row, list) or len(row) < 6:
                    continue
                o, c, h, l, v = _f(row[1]), _f(row[2]), _f(row[3]), _f(row[4]), _f(row[5])
                if None in (o, c, h, l):
                    continue
                bars.append({"date": str(row[0])[:10], "open": o, "close": c,
                             "high": h, "low": l, "volume": v if v is not None else 0.0})
            if bars:
                return bars
    return []


def parse_sina_kline(raw):
    """解析新浪日 K（JSON 数组，字段是字符串），返回同 tencent 的 bars 结构。

    新浪是备用源：腾讯被限流（HTTP 501/超时）时顶上，保证 K 线不断供。
    """
    try:
        rows = json.loads(raw.decode("utf-8", "replace"))
    except (ValueError, UnicodeDecodeError):
        return []
    if not isinstance(rows, list):
        return []
    bars = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        o = _f(row.get("open"))
        c = _f(row.get("close"))
        h = _f(row.get("high"))
        l = _f(row.get("low"))
        v = _f(row.get("volume"))
        day = str(row.get("day") or "")[:10]
        if None in (o, c, h, l) or not day:
            continue
        bars.append({"date": day, "open": o, "close": c, "high": h, "low": l,
                     "volume": v if v is not None else 0.0})
    return bars


def parse_tencent_minute(raw):
    """解析分时数据：每行 "HHMM 价格 累计量 累计额"。

    返回 {"date", "prev_close", "points": [{time, price, volume, cum_volume, avg_price}]}。
    成交量单位是「手」，均价 = 累计成交额 / (累计量 × 100)。
    """
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {"date": "", "prev_close": None, "points": []}
    node_root = data.get("data") or {}
    if not isinstance(node_root, dict):
        return {"date": "", "prev_close": None, "points": []}
    for symbol, node in node_root.items():
        if not isinstance(node, dict):
            continue
        inner = node.get("data")
        if not isinstance(inner, dict):
            continue
        rows = inner.get("data")
        if not isinstance(rows, list) or not rows:
            continue
        raw_date = str(inner.get("date") or "")
        date = "%s-%s-%s" % (raw_date[:4], raw_date[4:6], raw_date[6:8]) \
            if len(raw_date) >= 8 and raw_date[:8].isdigit() else ""
        prev_close = None
        qt = node.get("qt") or {}
        arr = qt.get(symbol) if isinstance(qt, dict) else None
        if isinstance(arr, list) and len(arr) > 4:
            try:
                prev_close = float(arr[4])
            except (TypeError, ValueError):
                prev_close = None
        points = []
        cum_prev = 0.0
        for row in rows:
            parts = str(row).split()
            if len(parts) < 4:
                continue
            hhmm = parts[0]
            if len(hhmm) < 4 or not hhmm.isdigit():
                continue
            try:
                price = float(parts[1])
                cum_vol = float(parts[2])
                cum_amt = float(parts[3])
            except ValueError:
                continue
            if price <= 0:
                continue
            volume = max(0.0, cum_vol - cum_prev)
            cum_prev = cum_vol
            avg = (cum_amt / (cum_vol * 100.0)) if cum_vol > 0 else price
            points.append({"time": hhmm[:2] + ":" + hhmm[2:4], "price": price,
                           "volume": volume, "cum_volume": cum_vol,
                           "avg_price": round(avg, 3)})
        if points:
            return {"date": date, "prev_close": prev_close, "points": points}
    return {"date": "", "prev_close": None, "points": []}


def parse_sina_quotes(raw):
    """解析 var hq_str_sh600519="名称,今开,昨收,现价,..."（GBK）。"""
    text = raw.decode("gbk", "replace")
    out = []
    for line in text.splitlines():
        if "=" not in line or '"' not in line:
            continue
        head, _, rest = line.partition("=")
        symbol = head.replace("var hq_str_", "").strip()
        payload = rest.strip().rstrip(";").strip().strip('"')
        parts = payload.split(",")
        if len(parts) < 32 or not parts[0]:
            continue
        code = normalize_code(symbol)
        price, prev = _f(parts[3]), _f(parts[2])
        if price is None or prev is None:
            continue
        change = price - prev
        out.append({
            "code": code, "symbol": symbol, "name": parts[0],
            "price": price, "prev_close": prev, "open": _f(parts[1]),
            "high": _f(parts[4]), "low": _f(parts[5]),
            "volume": _f(parts[8]), "amount": _f(parts[9]),
            "change": round(change, 3),
            "change_pct": round(change / prev * 100.0, 3) if prev else 0.0,
            "turnover": None, "pe": None, "pb": None,
            "limit_up": None, "limit_down": None,
            "timestamp": "%s %s" % (parts[30], parts[31]), "date": parts[30],
            "source": "sina",
        })
    return out


def parse_em_search(raw):
    """解析东财搜索建议，返回 [{code,name,symbol,market}]。"""
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return []
    rows = ((data.get("QuotationCodeTable") or {}).get("Data")) or []
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = normalize_code(row.get("Code", ""))
        if not code:
            continue
        quote_id = str(row.get("QuoteID", ""))
        symbol = tencent_symbol(code) if "." not in quote_id else (
            ("sh" if quote_id.split(".", 1)[0] == "1" else "sz") + code)
        out.append({"code": code, "name": row.get("Name", ""),
                    "symbol": symbol, "market": symbol[:2],
                    "type": row.get("SecurityTypeName", "")})
    return out


# --------------------------------------------------------------------------
# 缓存
# --------------------------------------------------------------------------
# TTL（秒）：页面上 5 秒一刷时，多个标签页/多人同时开也只会每 TTL 打一次上游接口。
QUOTE_TTL = float(os.environ.get("STOCK_QUOTE_TTL", "3"))
KLINE_TTL = float(os.environ.get("STOCK_KLINE_TTL", "30"))
SEARCH_TTL = float(os.environ.get("STOCK_SEARCH_TTL", "3600"))
MINUTE_TTL = float(os.environ.get("STOCK_MINUTE_TTL", "15"))

# 上游偶发抖动很常见（限流/连接被掐），一次失败就告诉用户「拿不到」体验很差：
# 默认重试 3 次、退避 0.6s/1.2s，仍失败才降级并报原因。
FETCH_ATTEMPTS = max(1, int(os.environ.get("STOCK_FETCH_ATTEMPTS", "3")))
FETCH_BACKOFF = float(os.environ.get("STOCK_FETCH_BACKOFF", "0.6"))

# 数据源熔断：某个源刚失败（如腾讯 K 线 501），接下来一段时间直接跳过它，
# 不用每只票都白等一次超时/退避。
_SOURCE_DOWN_UNTIL = {}
DOWN_COOLDOWN = float(os.environ.get("STOCK_DOWN_COOLDOWN", "60"))


def source_down(name):
    return time.time() < _SOURCE_DOWN_UNTIL.get(name, 0.0)


def mark_source_down(name, cooldown=None):
    _SOURCE_DOWN_UNTIL[name] = time.time() + (cooldown or DOWN_COOLDOWN)



class Cache:
    def __init__(self, dirpath=None):
        self.dir = dirpath or CACHE_DIR

    def _path(self, key):
        """缓存文件路径。

        不能直接用 key 拼文件名：自选股一多，「所有代码拼起来」会超过 Windows
        260 字符路径上限，open() 直接 OSError(22)。这里保留可读前缀 + 哈希后缀，
        既避免超长，也不会撞名。
        """
        raw = str(key)
        slug = "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in raw)[:48]
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
        return os.path.join(self.dir, "%s-%s.json" % (slug, digest))

    def get(self, key):
        path = self._path(key)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def put(self, key, payload, source="unknown"):
        os.makedirs(self.dir, exist_ok=True)
        item = {"fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "ts": time.time(), "source": source, "payload": payload}
        tmp = self._path(key) + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(item, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, self._path(key))
        return item["fetched_at"]

    def get_fresh(self, key, ttl):
        """返回 (条目, 年龄秒)。超过 ttl 或没有缓存时返回 (None, None)。"""
        item = self.get(key)
        if not item or not item.get("payload"):
            return None, None
        age = time.time() - float(item.get("ts") or 0)
        if 0 <= age <= ttl:
            return item, age
        return None, None


def _fixture(name):
    path = os.path.join(FIXTURES, name)
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return f.read()


# --------------------------------------------------------------------------
# 高层接口（带降级）
# --------------------------------------------------------------------------
def _online(allow_network):
    """环境变量 STOCK_OFFLINE=1 时强制走缓存/样本（用于验证降级链）。"""
    if str(os.environ.get("STOCK_OFFLINE", "")).strip() in ("1", "true", "yes"):
        return False
    return bool(allow_network)


def get_quotes(codes, cache=None, allow_network=True):
    codes = [normalize_code(c) for c in codes if normalize_code(c)]
    cache = cache or Cache()
    key = "quotes_" + "_".join(sorted(codes))
    errors = []

    if _online(allow_network) and codes:
        item, age = cache.get_fresh(key, QUOTE_TTL)
        if item is not None:
            return {"quotes": item["payload"],
                    "meta": {"source": item.get("source", "cache"), "stale": False,
                             "demo": False, "cached": True, "age": round(age, 1),
                             "errors": errors}}
        symbols = ",".join(tencent_symbol(c) for c in codes)
        try:
            rows = parse_tencent_quotes(http_get(TENCENT_QUOTE + symbols,
                                                 {"Referer": "https://finance.qq.com/"}))
            if rows:
                cache.put(key, rows, source="tencent")
                return {"quotes": rows, "meta": {"source": "tencent", "stale": False,
                                                 "demo": False, "errors": errors}}
        except FetchError as exc:
            errors.append("tencent: %s" % exc)
        try:
            rows = parse_sina_quotes(http_get(SINA_QUOTE + symbols,
                                              {"Referer": "https://finance.sina.com.cn/"}))
            if rows:
                cache.put(key, rows, source="sina")
                return {"quotes": rows, "meta": {"source": "sina", "stale": False,
                                                 "demo": False, "errors": errors}}
        except FetchError as exc:
            errors.append("sina: %s" % exc)

    cached = cache.get(key)
    if cached and cached.get("payload"):
        return {"quotes": cached["payload"],
                "meta": {"source": "cache", "stale": True, "demo": False,
                         "fetched_at": cached.get("fetched_at"), "errors": errors}}

    # 离线回落：优先用「全部自选股」的样本，再退到单票样本
    for name in ("tencent_quote_all.txt", "tencent_quote_sh600519.txt"):
        raw = _fixture(name)
        if not raw:
            continue
        rows = [r for r in parse_tencent_quotes(raw) if r["code"] in codes]
        if rows:
            return {"quotes": rows,
                    "meta": {"source": "fixture", "stale": True, "demo": True,
                             "errors": errors}}
    return {"quotes": [], "meta": {"source": "none", "stale": True, "demo": False,
                                   "errors": errors}}


def get_kline(code, limit=320, cache=None, allow_network=True, fqt="qfq"):
    code = normalize_code(code)
    cache = cache or Cache()
    lim = max(1, int(limit))
    fqt = fqt if fqt in ("qfq", "hfq", "bfq") else "qfq"
    # 腾讯接口：不复权传空串（返回 day 键），后复权 hfq、前复权 qfq
    fqt_param = "" if fqt == "bfq" else fqt
    key = "kline_%s_day_%d_%s" % (code, int(limit), fqt)
    errors = []

    if _online(allow_network):
        item, age = cache.get_fresh(key, KLINE_TTL)
        if item is not None:
            return {"bars": item["payload"][-lim:],
                    "meta": {"source": item.get("source", "cache"), "stale": False,
                             "demo": False, "cached": True, "age": round(age, 1),
                             "errors": errors}}
        if not source_down("tencent_kline"):
            try:
                url = TENCENT_KLINE % (tencent_symbol(code), int(limit), fqt_param)
                bars = parse_tencent_kline(http_get(url, {"Referer": "https://finance.qq.com/"}))[-lim:]
                if bars:
                    cache.put(key, bars, source="tencent")
                    return {"bars": bars, "meta": {"source": "tencent", "stale": False,
                                                   "demo": False, "adjust": fqt,
                                                   "errors": errors}}
            except FetchError as exc:
                errors.append("tencent: %s" % exc)
                # 501/403/429 这类说明这个源当前不可用：熔断一会儿，别再逐只白等
                if getattr(exc, "status", None) in (403, 429, 501):
                    mark_source_down("tencent_kline")
        if not source_down("sina_kline"):
            try:
                url = SINA_KLINE % (tencent_symbol(code), int(limit))
                bars = parse_sina_kline(http_get(url, {"Referer": "https://finance.sina.com.cn/"}))[-lim:]
                if bars:
                    cache.put(key, bars, source="sina")
                    return {"bars": bars, "meta": {"source": "sina", "stale": False,
                                                   "demo": False, "adjust": fqt,
                                                   "errors": errors}}
            except FetchError as exc:
                errors.append("sina: %s" % exc)
                mark_source_down("sina_kline")

    cached = cache.get(key)
    if cached and cached.get("payload"):
        return {"bars": cached["payload"][-lim:],
                "meta": {"source": "cache", "stale": True, "demo": False,
                         "fetched_at": cached.get("fetched_at"), "errors": errors}}

    raw = _fixture("tencent_kline_%s_day.json" % tencent_symbol(code))
    if not raw:
        sina_raw = _fixture("sina_kline_%s_day.json" % tencent_symbol(code))
        if sina_raw:
            bars = parse_sina_kline(sina_raw)[-lim:]
            if bars:
                return {"bars": bars,
                        "meta": {"source": "fixture", "stale": True, "demo": True,
                                 "adjust": fqt, "errors": errors}}
    if raw:
        return {"bars": parse_tencent_kline(raw)[-lim:],
                "meta": {"source": "fixture", "stale": True, "demo": True, "errors": errors}}
    return {"bars": [], "meta": {"source": "none", "stale": True, "demo": False,
                                 "errors": errors}}


def get_minute(code, cache=None, allow_network=True):
    """分时数据（当日逐分钟），TTL 15 秒。"""
    code = normalize_code(code)
    cache = cache or Cache()
    key = "minute_%s" % code
    errors = []

    if _online(allow_network):
        item, age = cache.get_fresh(key, MINUTE_TTL)
        if item is not None:
            return {"data": item["payload"],
                    "meta": {"source": item.get("source", "cache"), "stale": False,
                             "demo": False, "cached": True, "age": round(age, 1),
                             "errors": errors}}
        try:
            url = TENCENT_MINUTE % tencent_symbol(code)
            data = parse_tencent_minute(http_get(url, {"Referer": "https://finance.qq.com/"}))
            if data["points"]:
                cache.put(key, data, source="tencent")
                return {"data": data, "meta": {"source": "tencent", "stale": False,
                                               "demo": False, "errors": errors}}
        except FetchError as exc:
            errors.append("tencent: %s" % exc)

    cached = cache.get(key)
    if cached and cached.get("payload"):
        return {"data": cached["payload"],
                "meta": {"source": "cache", "stale": True, "demo": False,
                         "fetched_at": cached.get("fetched_at"), "errors": errors}}

    raw = _fixture("tencent_minute_sh600519.json") if code == "600519" else None
    if raw:
        return {"data": parse_tencent_minute(raw),
                "meta": {"source": "fixture", "stale": True, "demo": True,
                         "errors": errors}}
    return {"data": {"date": "", "prev_close": None, "points": []},
            "meta": {"source": "none", "stale": True, "demo": False, "errors": errors}}


def search(keyword, cache=None, allow_network=True):
    keyword = str(keyword or "").strip()
    if not keyword:
        return {"rows": [], "meta": {"source": "none", "stale": True, "errors": []}}
    cache = cache or Cache()
    key = "search_" + keyword
    errors = []
    if _online(allow_network):
        item, age = cache.get_fresh(key, SEARCH_TTL)
        if item is not None:
            return {"rows": item["payload"],
                    "meta": {"source": item.get("source", "cache"), "stale": False,
                             "demo": False, "cached": True, "age": round(age, 1),
                             "errors": errors}}
        try:
            url = EM_SEARCH % (urllib.parse.quote(keyword), 10)
            rows = parse_em_search(http_get(url))
            if rows:
                cache.put(key, rows, source="eastmoney")
                return {"rows": rows, "meta": {"source": "eastmoney", "stale": False,
                                               "demo": False, "errors": errors}}
        except FetchError as exc:
            errors.append("eastmoney: %s" % exc)
    cached = cache.get(key)
    if cached and cached.get("payload"):
        return {"rows": cached["payload"],
                "meta": {"source": "cache", "stale": True, "demo": False,
                         "fetched_at": cached.get("fetched_at"), "errors": errors}}
    return {"rows": [], "meta": {"source": "none", "stale": True, "demo": False,
                                 "errors": errors}}
