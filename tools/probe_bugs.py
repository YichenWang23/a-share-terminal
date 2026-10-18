# -*- coding: utf-8 -*-
"""坏输入探测：把明显不该通过的东西扔给每个接口，看会不会 500 / 污染状态。

用法（服务需在跑）：
    python tools/probe_bugs.py [--base http://127.0.0.1:8770]

判定：
  * 任何 5xx 记 FAIL（服务端不该崩）
  * 明确非法的请求如果返回 200 且真的改了状态，记 FAIL
  * 跑完后核对账本不变量（现金/钱包有限、权重合计 100%）
"""
import argparse
import json
import math
import pathlib
import shutil
import sys
import urllib.error
import urllib.request

BAD = []
STATE = pathlib.Path(__file__).resolve().parent.parent / "data" / "state.json"
BACKUP = STATE.with_suffix(".json.probe-backup")


def backup_state():
    """探测会碰到下单接口：先备份账本，跑完复原，绝不留下痕迹。"""
    if STATE.exists():
        shutil.copy2(STATE, BACKUP)
        return True
    return False


def restore_state(have_backup):
    if have_backup and BACKUP.exists():
        shutil.copy2(BACKUP, STATE)
        BACKUP.unlink()
        print("账本已复原（探测前的 state.json 原样写回）")


def call(base, method, path, body=None, raw=None, timeout=40):
    data = None
    headers = {}
    if raw is not None:
        data = raw
        headers["Content-Type"] = "application/json"
    elif body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        return 0, "%s: %s" % (type(exc).__name__, exc)


def expect(name, base, method, path, allowed_max=499, body=None, raw=None):
    status, text = call(base, method, path, body=body, raw=raw)
    ok = 200 <= status <= allowed_max and status != 0
    if not ok:
        BAD.append(name)
    print("%-42s HTTP %-4s %s" % (name, status, "ok" if ok else "FAIL " + text[:90]))
    return status, text


def invariants(base):
    print("\n--- 账本不变量 ---")
    status, text = call(base, "GET", "/api/account")
    try:
        data = json.loads(text)
    except ValueError:
        BAD.append("account-not-json")
        print("account 返回不是 JSON")
        return
    s = data["summary"]
    checks = {
        "现金有限": math.isfinite(s["cash"]),
        "钱包有限": math.isfinite(s["wallet"]),
        "持仓市值有限": math.isfinite(s["market_value"]),
        "净资产 = 钱包 + 总资产": abs(s["net_worth"] - (s["wallet"] + s["total"])) < 0.02,
        "权重合计 ≈ 100%": abs((data["allocation"]["cash_pct"]
                                + sum(i["weight"] for i in data["allocation"]["items"])) - 100) < 0.5,
        "现金 >= 0": s["cash"] >= 0,
        "钱包 >= 0": s["wallet"] >= 0,
    }
    for k, v in checks.items():
        if not v:
            BAD.append(k)
        print("  %-22s %s" % (k, "OK" if v else "FAIL"))
    print("  现金 %.2f | 钱包 %.2f | 净资产 %.2f | 收益率 %.2f%%"
          % (s["cash"], s["wallet"], s["net_worth"], s["total_return_pct"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8770")
    args = ap.parse_args()
    b = args.base.rstrip("/")
    have_backup = backup_state()
    print("（已备份账本，跑完会复原）\n"
          if have_backup else "（账本不存在，跳过备份）\n")

    print("=== 行情/K线/分时：非法参数 ===")
    expect("kline 无 code", b, "GET", "/api/kline")
    expect("kline code=abc", b, "GET", "/api/kline?code=abc")
    expect("kline code=999999", b, "GET", "/api/kline?code=999999")
    expect("kline limit=0", b, "GET", "/api/kline?code=600519&limit=0")
    expect("kline limit=-5", b, "GET", "/api/kline?code=600519&limit=-5")
    expect("kline limit=abc", b, "GET", "/api/kline?code=600519&limit=abc")
    expect("kline limit=100000", b, "GET", "/api/kline?code=600519&limit=100000")
    expect("minute code=abc", b, "GET", "/api/minute?code=abc")
    expect("analysis code=", b, "GET", "/api/analysis?code=")
    expect("quote 空 codes", b, "GET", "/api/quote?codes=")
    expect("quote code=abc", b, "GET", "/api/quote?codes=abc")
    expect("quote 重复 code", b, "GET", "/api/quote?codes=600519,600519")

    print("\n=== 搜索 ===")
    expect("search 空 q", b, "GET", "/api/search?q=")
    expect("search 超长 q", b, "GET", "/api/search?q=" + "A" * 500)
    expect("search 特殊字符", b, "GET", "/api/search?q=%3Cscript%3E")

    print("\n=== 回测参数 ===")
    expect("backtest code=abc", b, "GET", "/api/backtest?code=abc")
    expect("backtest short=0", b, "GET", "/api/backtest?code=600519&short=0&long=20")
    expect("backtest short>long", b, "GET", "/api/backtest?code=600519&short=20&long=5")
    expect("backtest cash=nan", b, "GET", "/api/backtest?code=600519&cash=nan")
    expect("backtest cash=-1", b, "GET", "/api/backtest?code=600519&cash=-1")
    expect("backtest slippage=-5", b, "GET", "/api/backtest?code=600519&slippage=-5")
    expect("backtest fqt=xx", b, "GET", "/api/backtest?code=600519&fqt=xx")

    print("\n=== 下单：非法参数 ===")
    for name, payload in [
        ("order shares=0", {"code": "600519", "side": "buy", "shares": 0}),
        ("order shares=-100", {"code": "600519", "side": "buy", "shares": -100}),
        ("order shares=100.5", {"code": "600519", "side": "buy", "shares": 100.5}),
        ("order shares=1e9", {"code": "600519", "side": "buy", "shares": 1e9}),
        ("order shares=nan", {"code": "600519", "side": "buy", "shares": "nan"}),
        ("order price=nan", {"code": "600519", "side": "buy", "shares": 100, "price": "nan"}),
        ("order side=xx", {"code": "600519", "side": "xx", "shares": 100}),
        ("order code=abc", {"code": "abc", "side": "buy", "shares": 100}),
    ]:
        status, text = expect(name, b, "POST", "/api/order", allowed_max=499, body=payload)
        if status == 200 and '"ok": true' in text.replace(" ", ""):
            BAD.append(name + "（非法却成功）")

    print("\n=== 钱包转账：非法金额 ===")
    for name, payload in [
        ("flow amount=0.001", {"type": "deposit", "amount": 0.001}),
        ("flow amount=1e300", {"type": "deposit", "amount": 1e300}),
        ("flow type=xx", {"type": "xx", "amount": 100}),
        ("flow amount=nan", {"type": "deposit", "amount": "nan"}),
        ("flow amount=-1", {"type": "deposit", "amount": -1}),
    ]:
        expect(name, b, "POST", "/api/account/flow", allowed_max=499, body=payload)

    print("\n=== 协议层：坏 JSON / 路径 / 超大 body ===")
    expect("坏 JSON", b, "POST", "/api/order", raw=b"{not json")
    expect("路径穿越 ../../", b, "GET", "/../../../../etc/passwd")
    expect("未知接口", b, "GET", "/api/nope")
    # 只用非法 side，确保即使没被体积上限拦住也不会真成交
    expect("超大 body 300KB", b, "POST", "/api/order", allowed_max=499,
           raw=json.dumps({"code": "600519", "side": "xx", "shares": 100,
                           "pad": "x" * 300_000}).encode())
    expect("非对象 body []", b, "POST", "/api/order", allowed_max=499, raw=b"[]")
    expect("非对象 body null", b, "POST", "/api/order", allowed_max=499, raw=b"null")

    invariants(b)
    restore_state(have_backup)

    print("\n=== 结论 ===")
    if BAD:
        print("发现 %d 个问题：" % len(BAD))
        for item in BAD:
            print("  - " + item)
        return 1
    print("全部通过：没有 5xx，也没有非法输入改坏账本。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
