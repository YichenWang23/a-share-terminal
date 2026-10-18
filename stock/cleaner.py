# -*- coding: utf-8 -*-
"""K 线数据清洗与校验。

原则：
  * 能修的修（排序、去重），不能修的丢（OHLC 矛盾、坏价格），并逐条留痕；
  * 「能看出来有问题」但数据本身可用的，记 warning，不丢（异常收益、缺口、负量）；
  * 返回结构固定：{"ok": 无 error, "bars": 清洗后, "issues": [{level, code, message, date}]}
"""

REQUIRED = ("date", "open", "close", "high", "low", "volume")


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def clean_bars(bars, max_daily_return=0.5, gap_days=15):
    issues = []

    def add(level, code, message, date=None):
        issues.append({"level": level, "code": code, "message": message, "date": date})

    valid = []
    for i, b in enumerate(bars or []):
        if not isinstance(b, dict):
            add("error", "BAD_FIELD", "第 %d 条不是对象" % i)
            continue
        missing = [k for k in REQUIRED if k not in b]
        if missing:
            add("error", "BAD_FIELD", "第 %d 条缺字段: %s" % (i, ", ".join(missing)), b.get("date"))
            continue
        date = str(b["date"])[:10]
        o, c, h, l = _num(b["open"]), _num(b["close"]), _num(b["high"]), _num(b["low"])
        v = _num(b["volume"])
        if None in (o, c, h, l) or v is None:
            add("error", "BAD_FIELD", "第 %d 条含非数字字段" % i, date)
            continue
        if min(o, c, h, l) <= 0:
            add("error", "BAD_PRICE", "价格必须为正: open=%s close=%s" % (o, c), date)
            continue
        if h < max(o, c) or l > min(o, c) or l > h:
            add("error", "OHLC_INCONSISTENT",
                "OHLC 矛盾: open=%s close=%s high=%s low=%s" % (o, c, h, l), date)
            continue
        if v < 0:
            add("warning", "BAD_VOLUME", "成交量为负: %s" % v, date)
        valid.append({"date": date, "open": o, "close": c, "high": h, "low": l, "volume": v})

    # 按日期排序（字符串比较对 YYYY-MM-DD 成立）
    if valid and [b["date"] for b in valid] != sorted(b["date"] for b in valid):
        add("warning", "UNSORTED", "日期未升序，已重排")
        valid.sort(key=lambda b: b["date"])

    # 去重：同一天只留第一条
    seen = set()
    deduped = []
    for b in valid:
        if b["date"] in seen:
            add("warning", "DUPLICATE_DATE", "重复交易日，已保留第一条", b["date"])
            continue
        seen.add(b["date"])
        deduped.append(b)

    # 异常收益与日期缺口
    from datetime import date as _date

    def parse(d):
        try:
            y, m, dd = d.split("-")
            return _date(int(y), int(m), int(dd))
        except (ValueError, TypeError):
            return None

    for i in range(1, len(deduped)):
        prev, cur = deduped[i - 1], deduped[i]
        if prev["close"] > 0:
            ret = cur["close"] / prev["close"] - 1.0
            if abs(ret) > max_daily_return:
                add("warning", "EXTREME_RETURN",
                    "单日涨跌 %.2f%% 超出阈值 %.0f%%" % (ret * 100, max_daily_return * 100),
                    cur["date"])
        d1, d2 = parse(prev["date"]), parse(cur["date"])
        if d1 and d2 and (d2 - d1).days > gap_days:
            add("warning", "DATE_GAP",
                "日期缺口 %d 天（%s -> %s）" % ((d2 - d1).days, prev["date"], cur["date"]),
                cur["date"])

    ok = not any(i["level"] == "error" for i in issues)
    return {"ok": ok, "bars": deduped, "issues": issues}
