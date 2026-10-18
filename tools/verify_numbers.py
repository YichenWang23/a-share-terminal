# -*- coding: utf-8 -*-
"""关键数字独立重算：换一条代码路径复算，与主实现逐项对比（工作区硬规矩第 2 条）。

覆盖：
  1. 指标：用另一套写法重算 MA / RSI / MACD，与 stock.indicators 对比；
  2. 费用：用手写公式重算佣金/印花税/过户费，与 stock.rules 对比；
  3. 回测：只用成交记录里的金额与费用重算期末资金，与引擎内部记账对比；
  4. 模拟盘：从成交记录重算现金，与快照现金对比；
  5. 跨源一致性：录制样本里「日 K 最后一根收盘」与「实时行情最新价」必须相等；
  6. 规则分：按 analysis.py 里写死的打分表独立复算，与引擎输出对比。

用法：python tools/verify_numbers.py
返回码：0 = 全部一致；1 = 有不一致（逐条打印差异）。
"""
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
FIX = os.path.join(BASE, "fixtures")

from stock import analysis, backtest, datasource, rules  # noqa: E402
from stock.indicators import macd, rsi, sma  # noqa: E402
from stock.portfolio import Portfolio  # noqa: E402


def read_fixture(name):
    with open(os.path.join(FIX, name), "rb") as f:
        return f.read()


class Checker:
    def __init__(self):
        self.results = []

    def close(self, name, a, b, tol=1e-9):
        ok = abs(float(a) - float(b)) <= tol
        self.results.append((name, ok, "%r vs %r (tol=%g)" % (a, b, tol)))
        print("%-52s %s" % (name, "PASS" if ok else "FAIL"))
        if not ok:
            print("      %r vs %r  tol=%g" % (a, b, tol))

    def equal(self, name, a, b):
        ok = a == b
        self.results.append((name, ok, "%r vs %r" % (a, b)))
        print("%-52s %s" % (name, "PASS" if ok else "FAIL"))
        if not ok:
            print("      %r vs %r" % (a, b))


# ---------------- 1) 指标：另一套实现 ----------------
def alt_sma(values, n):
    return [None if i + 1 < n else sum(values[i + 1 - n:i + 1]) / n for i in range(len(values))]


def alt_ema(values, n):
    a = 2.0 / (n + 1.0)
    out = []
    for i, v in enumerate(values):
        out.append(v if i == 0 else out[-1] + a * (v - out[-1]))
    return out


def alt_rsi(closes, n=14):
    """不用递归平滑的写法：先把涨跌序列切段，再逐段套 Wilder。"""
    out = [None] * len(closes)
    if len(closes) < n + 1:
        return out
    diffs = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    ups = [d if d > 0 else 0.0 for d in diffs]
    downs = [(-d) if d < 0 else 0.0 for d in diffs]
    gain = sum(ups[:n]) / n
    loss = sum(downs[:n]) / n
    for idx in range(n, len(closes)):
        if idx > n:
            gain = (gain * (n - 1) + ups[idx - 1]) / n
            loss = (loss * (n - 1) + downs[idx - 1]) / n
        out[idx] = 50.0 if (gain == 0 and loss == 0) else (
            100.0 if loss == 0 else 100.0 - 100.0 / (1.0 + gain / loss))
    return out


def check_indicators(c):
    bars = datasource.parse_tencent_kline(read_fixture("tencent_kline_sh600519_day.json"))
    closes = [b["close"] for b in bars]
    print("== 1) 指标（n=%d 根真实 K 线） ==" % len(closes))

    mine = sma(closes, 20)
    alt = alt_sma(closes, 20)
    # 主实现用「增量累加和」，独立实现用「整窗直接求和」，末位浮点会有 ~1e-12 的差，
    # 所以这里比最大偏差而不是逐点相等；偏差超过 1e-9 才算真问题。
    diffs = [abs(mine[i] - alt[i]) for i in range(len(closes))
             if mine[i] is not None and alt[i] is not None]
    c.close("MA20：两种实现最大偏差", max(diffs), 0.0, tol=1e-9)

    m_rsi = rsi(closes, 14)
    a_rsi = alt_rsi(closes, 14)
    diff = max(abs((m_rsi[i] or 0) - (a_rsi[i] or 0)) for i in range(len(closes)))
    c.close("RSI14：两种实现最大偏差", diff, 0.0, tol=1e-9)

    dif, dea, hist = macd(closes)
    fast, slow = alt_ema(closes, 12), alt_ema(closes, 26)
    dif_alt = [f - s for f, s in zip(fast, slow)]
    c.close("MACD DIF：主实现与独立实现末值", dif[-1], dif_alt[-1], tol=1e-9)
    c.close("MA20 末值（对独立实现）", mine[-1], alt[-1], tol=1e-9)


# ---------------- 2) 费用：手写公式 ----------------
def check_fees(c):
    print("== 2) 费用（手写公式重算） ==")
    for amount, is_sell, note in [(1150.0, False, "平安银行 100 股 @11.50"),
                                  (132900.0, False, "茅台 100 股 @1329"),
                                  (131000.0, True, "卖出 131000")]:
        commission = max(5.0, round(amount * 0.0003, 2))
        stamp = round(amount * 0.0005, 2) if is_sell else 0.0
        transfer = round(amount * 0.00001, 2)
        hand = round(commission + stamp + transfer, 2)
        got = rules.fee_detail(amount, is_sell)
        c.close("费用合计 %s" % note, got["total"], hand, tol=1e-9)
        c.close("  佣金 %s" % note, got["commission"], commission, tol=1e-9)
        c.close("  印花 %s" % note, got["stamp"], stamp, tol=1e-9)


# ---------------- 3) 回测：只用成交记录重算期末资金 ----------------
def check_backtest(c):
    print("== 3) 回测（从成交记录反推资金） ==")
    bars = datasource.parse_tencent_kline(read_fixture("tencent_kline_sh600519_day.json"))
    cash0 = 1_000_000.0
    r = backtest.run_ma_cross(bars, short=5, long=20, cash=cash0)
    cash = cash0
    for t in r["trades"]:
        cash -= t["entry_amount"] + t["entry_fee"]
        cash += t["exit_amount"] - t["exit_fee"]
    c.close("期末资金 = 初值 - 买入(金额+费用) + 卖出(金额-费用)",
            r["final_equity"], round(cash, 2), tol=1e-9)
    # pnl / gross_pnl 按「分」取整，允许 1 分以内的舍入差
    c.equal("逐笔 pnl = 毛利 - 费用（分位舍入内）", all(
        abs(t["pnl"] - (t["gross_pnl"] - t["fee"])) <= 0.0101 for t in r["trades"]), True)
    c.equal("成交股数都是 100 的整数倍", all(t["shares"] % 100 == 0 for t in r["trades"]), True)


# ---------------- 4) 模拟盘：从成交记录重算现金 ----------------
def check_portfolio(c):
    print("== 4) 模拟盘（从成交记录重算现金） ==")
    p = Portfolio(cash=1_000_000.0, day="2026-10-19")
    p.buy("600519", price=1300.0, shares=100, prev_close=1300.0)
    p.roll_day("2026-10-20")
    p.sell("600519", price=1310.0, shares=100, prev_close=1300.0)
    cash = 1_000_000.0
    for t in p.trades:
        if t["side"] == "buy":
            cash -= t["amount"] + t["fee"]
        else:
            cash += t["amount"] - t["fee"]
    c.close("快照现金 = 从成交记录反推的现金", p.snapshot({})["cash"], round(cash, 2), tol=1e-9)
    c.close("已实现盈亏 = 毛利 - 两笔费用",
            p.realized_pnl, 1000.0 - p.trades[0]["fee"] - p.trades[1]["fee"], tol=1e-9)


# ---------------- 5) 跨源一致性：K 线收盘 vs 实时价 ----------------
def check_cross_source(c):
    print("== 5) 跨源一致性（K 线 vs 实时行情） ==")
    bars = datasource.parse_tencent_kline(read_fixture("tencent_kline_sh600519_day.json"))
    quotes = datasource.parse_tencent_quotes(read_fixture("tencent_quote_sh600519.txt"))
    q = next(x for x in quotes if x["code"] == "600519")
    c.close("最新一根 K 线收盘 = 实时行情最新价", bars[-1]["close"], q["price"], tol=1e-6)
    c.equal("最新 K 线日期 = 行情时间戳的日期", bars[-1]["date"], q["timestamp"][:10])
    c.close("涨停价 = 昨收×1.1（四舍五入到分）", q["limit_up"],
            rules.round2(q["prev_close"] * 1.1), tol=1e-9)


# ---------------- 6) 规则分：按打分表独立复算 ----------------
def check_score(c):
    print("== 6) 规则引擎打分（按文档口径独立复算） ==")
    bars = datasource.parse_tencent_kline(read_fixture("tencent_kline_sh600519_day.json"))
    quotes = datasource.parse_tencent_quotes(read_fixture("tencent_quote_sh600519.txt"))
    q = next(x for x in quotes if x["code"] == "600519")
    res = analysis.rule_engine(q, bars)

    closes = [b["close"] for b in bars]
    price = q["price"]
    ma5, ma20, ma60 = sma(closes, 5)[-1], sma(closes, 20)[-1], sma(closes, 60)[-1]
    r = rsi(closes, 14)[-1]
    h = macd(closes)[2][-1]
    vols = [b["volume"] for b in bars]
    vol_ratio = vols[-1] / (sum(vols[-21:-1]) / 20.0) if len(vols) >= 21 else 0.0
    chg = q["change_pct"]

    score = 0
    score += 30 if price > ma20 else (-30 if price < ma20 else 0)
    score += 15 if ma20 > ma60 else (-15 if ma20 < ma60 else 0)
    score += 10 if price > ma5 else (-10 if price < ma5 else 0)
    if r is not None:
        if r > 70: score -= 15
        elif r >= 55: score += 10
        elif r >= 45: pass
        elif r >= 30: score -= 10
        else: score += 10
    if h is not None:
        if h > 0: score += 15
        elif h < 0: score -= 15
    if vol_ratio > 1.5 and chg > 0: score += 10
    elif vol_ratio > 1.5 and chg < 0: score -= 10
    if q.get("limit_up") and price >= q["limit_up"] * 0.999: score -= 10
    elif q.get("limit_down") and price <= q["limit_down"] * 1.001: score += 5
    elif chg > 5: score -= 5
    elif chg < -5: score += 5

    c.equal("规则分 = 打分表独立复算", res["score"], score)
    c.equal("结论与分数阈值一致（±25）",
            res["stance"], "偏多" if score >= 25 else ("偏空" if score <= -25 else "中性"))


def main():
    c = Checker()
    check_indicators(c)
    check_fees(c)
    check_backtest(c)
    check_portfolio(c)
    check_cross_source(c)
    check_score(c)
    failed = [r for r in c.results if not r[1]]
    print("\n%d checks, %d passed, %d failed" % (len(c.results),
                                                 len(c.results) - len(failed), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
