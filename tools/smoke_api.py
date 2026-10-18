# -*- coding: utf-8 -*-
"""接口冒烟测试：对着已经跑起来的本地服务打真实请求，逐条断言。

用法（服务需先启动）：
    python tools/smoke_api.py [--base http://127.0.0.1:8770]

返回码 0 = 全过；非 0 = 有断言失败（失败项会逐条打印）。
"""
import argparse
import json
import sys
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass


def call(base, path, payload=None, method=None):
    url = base + path
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method=method or ("POST" if data else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8770")
    args = ap.parse_args()
    base = args.base.rstrip("/")

    results = []

    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))
        print("%-42s %s  %s" % (name, "PASS" if ok else "FAIL", detail))

    # 1) 健康检查
    code, body = call(base, "/api/health")
    check("health 200", code == 200 and body.get("ok"), "HTTP %s" % code)

    # 2) 自选股状态：6 只、来自真实接口
    code, body = call(base, "/api/state")
    quotes = body.get("quotes") or []
    meta = body.get("meta") or {}
    check("state 返回至少 12 只自选", code == 200 and len(quotes) >= 12,
          "http=%s quotes=%d source=%s" % (code, len(quotes), meta.get("source")))
    check("state 行情来源非样本", meta.get("source") in ("tencent", "sina"),
          "source=%s stale=%s demo=%s" % (meta.get("source"), meta.get("stale"), meta.get("demo")))
    moutai = next((q for q in quotes if q["code"] == "600519"), None)
    check("茅台字段完整（含涨跌停价）",
          bool(moutai and moutai.get("price") and moutai.get("limit_up") and moutai.get("limit_down")),
          "price=%s up=%s down=%s" % ((moutai or {}).get("price"),
                                      (moutai or {}).get("limit_up"),
                                      (moutai or {}).get("limit_down")))

    # 3) K 线 + 清洗
    code, body = call(base, "/api/kline?code=600519&limit=120")
    bars = body.get("bars") or []
    check("kline 200 且有 120 根", code == 200 and len(bars) == 120, "bars=%d" % len(bars))
    check("kline 清洗无 error", body.get("clean_ok") is True,
          "issues=%d" % len(body.get("clean_issues") or []))

    # 4) 规则引擎分析
    code, body = call(base, "/api/analysis?code=600519")
    ana = body.get("analysis") or {}
    check("analysis 可用", code == 200 and ana.get("source") in ("rule-engine", "llm"),
          "source=%s stance=%s score=%s" % (ana.get("source"), ana.get("stance"), ana.get("score")))
    if ana.get("source") == "llm":
        check("模型解读有正文", bool((ana.get("llm") or {}).get("text")),
              "len=%d" % len((ana.get("llm") or {}).get("text") or ""))
    check("analysis 带免责声明", "不构成" in (ana.get("disclaimer") or ""), "")

    # 5) 拒单：非整手
    code, body = call(base, "/api/order", {"code": "600519", "side": "buy", "shares": 150})
    check("拒单 LOT_SIZE(150股)", code == 409 and body.get("reason") == "LOT_SIZE",
          "http=%s reason=%s" % (code, body.get("reason")))

    # 6) 拒单：超涨停
    code, body = call(base, "/api/order", {"code": "600519", "side": "buy",
                                           "shares": 100, "price": 2000})
    check("拒单 PRICE_LIMIT(2000元)", code == 409 and body.get("reason") == "PRICE_LIMIT",
          "http=%s reason=%s" % (code, body.get("reason")))

    # 7) 正常买入（按行情价）
    code, body = call(base, "/api/order", {"code": "000001", "side": "buy", "shares": 100})
    ok_buy = code == 200 and body.get("ok") is True
    check("买入成功且带费用明细", ok_buy and (body.get("trade") or {}).get("fee_detail"),
          "price=%s fee=%s" % ((body.get("trade") or {}).get("price"),
                               (body.get("trade") or {}).get("fee")))

    # 8) T+1：当日卖出必须被拒
    code, body = call(base, "/api/order", {"code": "000001", "side": "sell", "shares": 100})
    check("拒单 T_PLUS_1(当日卖出)", code == 409 and body.get("reason") == "T_PLUS_1",
          "http=%s reason=%s" % (code, body.get("reason")))

    # 9) 回测：平安银行资金够一手，应产生交易
    code, body = call(base, "/api/backtest?code=000001&short=5&long=20&cash=100000")
    metrics = (body.get("result") or {}).get("metrics") or {}
    check("回测产生交易", code == 200 and metrics.get("trade_count", 0) > 0,
          "trades=%s win_rate=%s" % (metrics.get("trade_count"), metrics.get("win_rate")))

    # 10) 回测：茅台资金不够一手，应给出提示而不是假装成交
    code, body = call(base, "/api/backtest?code=600519&short=5&long=20&cash=100000")
    m2 = (body.get("result") or {}).get("metrics") or {}
    notes = body.get("notes") or []
    check("资金不足一手的回测给出提示",
          m2.get("trade_count") == 0 and bool(notes),
          "notes=%s" % (notes[:1] if notes else []))

    # 11) 账户系统：概览、权重合计、出金拒绝
    code, body = call(base, "/api/account")
    alloc = body.get("allocation") or {}
    total_pct = (alloc.get("cash_pct") or 0) + sum(
        i.get("weight") or 0 for i in (alloc.get("items") or []))
    check("account 可用且权重合计≈100%",
          code == 200 and bool(body.get("summary")) and abs(total_pct - 100) < 0.5,
          "total=%.2f cash=%.2f%%" % ((body.get("summary") or {}).get("total") or 0,
                                      alloc.get("cash_pct") or 0))
    code, body = call(base, "/api/account/flow",
                      {"type": "withdraw", "amount": 999999999})
    check("超额出金被拒 400", code == 400, "http=%s" % code)

    failed = [r for r in results if not r[1]]
    print("\n%d checks, %d passed, %d failed" % (len(results), len(results) - len(failed), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
