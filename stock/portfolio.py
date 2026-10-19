# -*- coding: utf-8 -*-
"""模拟盘：按 A 股真实规则记账（整手、T+1、涨跌停、费用、盈亏）。

不接券商、不下真单——这里只有本地 JSON 账本。
"""
import datetime
import math

from .rules import fee_detail, normalize_code, price_limits, round2

EPS = 1e-9


def today_str():
    return datetime.date.today().isoformat()


MAX_SHARES = 1_000_000_000


def _parse_price_shares(price, shares):
    """把外部输入变成 (价格, 股数)，不合格返回原因码。

    这里刻意拒绝：非数字、NaN、inf、非正价格、非整数股数、超大股数。
    没有这一步，NaN 会顺着金额一路把现金污染成 NaN。
    """
    try:
        price_f = float(price)
        shares_f = float(shares)
    except (TypeError, ValueError):
        return None, None, "BAD_INPUT"
    if not math.isfinite(price_f) or price_f <= 0:
        return None, None, "BAD_PRICE"
    if (not math.isfinite(shares_f) or not shares_f.is_integer()
            or shares_f <= 0 or shares_f > MAX_SHARES):
        return None, None, "BAD_SHARES"
    return price_f, int(shares_f), None


class Portfolio:
    def __init__(self, cash=350_000.0, day=None):
        self.cash = float(cash)
        self.day = day or today_str()
        self.positions = {}      # code -> {code,name,shares,available,avg_cost,fees_paid}
        self.realized_pnl = 0.0
        self.trades = []

    # -------- 日切与 T+1 --------
    def roll_day(self, day):
        """进入新交易日：把昨仓全部置为可卖（T+1 解锁）。"""
        if day and day > self.day:
            for p in self.positions.values():
                p["available"] = p["shares"]
            self.day = day

    @staticmethod
    def _fail(reason, **extra):
        return {"ok": False, "reason": reason, **extra}

    def _limit_reason(self, code, price, prev_close, is_st):
        if prev_close is None:
            return None
        low, high = price_limits(code, prev_close, is_st=is_st)
        if price < low - EPS or price > high + EPS:
            return "PRICE_LIMIT"
        return None

    # -------- 买入 --------
    def buy(self, code, price, shares, name=None, prev_close=None, is_st=False):
        code = normalize_code(code)
        price, shares, why = _parse_price_shares(price, shares)
        if why:
            return self._fail(why)
        if shares % 100 != 0:
            return self._fail("LOT_SIZE", hint="买入必须是 100 股的整数倍")
        reason = self._limit_reason(code, price, prev_close, is_st)
        if reason:
            low, high = price_limits(code, prev_close, is_st=is_st)
            return self._fail(reason, hint="价格须在 %.2f ~ %.2f 之间（涨跌停）" % (low, high))

        amount = round2(price * shares)
        fees = fee_detail(amount, is_sell=False)
        need = amount + fees["total"]
        if need > self.cash + EPS:
            return self._fail("INSUFFICIENT_CASH",
                              hint="需要 %.2f，可用 %.2f" % (need, self.cash))

        self.cash = round2(self.cash - need)
        pos = self.positions.get(code)
        if pos is None:
            pos = {"code": code, "name": name or code, "shares": 0, "available": 0,
                   "avg_cost": 0.0, "fees_paid": 0.0}
            self.positions[code] = pos
        if name:
            pos["name"] = name
        prev_cost = pos["avg_cost"] * pos["shares"]
        pos["shares"] += shares
        pos["avg_cost"] = round2((prev_cost + amount) / pos["shares"])
        pos["fees_paid"] = round2(pos["fees_paid"] + fees["total"])

        trade = {"day": self.day, "code": code, "name": pos["name"], "side": "buy",
                 "price": price, "shares": shares, "amount": amount,
                 "fee": fees["total"], "fee_detail": fees}
        self.trades.append(trade)
        return {"ok": True, "trade": trade, "cash": self.cash}

    # -------- 卖出 --------
    def sell(self, code, price, shares, prev_close=None, is_st=False):
        code = normalize_code(code)
        price, shares, why = _parse_price_shares(price, shares)
        if why:
            return self._fail(why)
        pos = self.positions.get(code)
        if pos is None or pos["shares"] <= 0:
            return self._fail("INSUFFICIENT_SHARES")
        if shares > pos["shares"]:
            return self._fail("INSUFFICIENT_SHARES",
                              hint="持仓 %d 股，卖出 %d 股" % (pos["shares"], shares))
        if shares > pos["available"]:
            return self._fail("T_PLUS_1", hint="今日买入的 %d 股不可卖" % (pos["shares"] - pos["available"]))
        if price <= 0:
            return self._fail("BAD_PRICE")
        reason = self._limit_reason(code, price, prev_close, is_st)
        if reason:
            low, high = price_limits(code, prev_close, is_st=is_st)
            return self._fail(reason, hint="价格须在 %.2f ~ %.2f 之间（涨跌停）" % (low, high))

        amount = round2(price * shares)
        fees = fee_detail(amount, is_sell=True)
        shares_before = pos["shares"]
        fee_alloc = pos["fees_paid"] * (shares / float(shares_before))
        cost_out = pos["avg_cost"] * shares + fee_alloc

        self.cash = round2(self.cash + amount - fees["total"])
        self.realized_pnl = round2(self.realized_pnl + (amount - fees["total"]) - cost_out)

        pos["shares"] -= shares
        pos["available"] -= shares
        pos["fees_paid"] = round2(pos["fees_paid"] - fee_alloc)
        if pos["shares"] <= 0:
            del self.positions[code]

        trade = {"day": self.day, "code": code, "name": pos.get("name", code) if pos else code,
                 "side": "sell", "price": price, "shares": shares, "amount": amount,
                 "fee": fees["total"], "fee_detail": fees, "realized_pnl": self.realized_pnl}
        self.trades.append(trade)
        return {"ok": True, "trade": trade, "cash": self.cash}

    # -------- 快照 --------
    def snapshot(self, prices=None):
        prices = prices or {}
        rows = []
        market_value = 0.0
        floating = 0.0
        for code, p in sorted(self.positions.items()):
            last = float(prices.get(code, p["avg_cost"]))
            value = last * p["shares"]
            cost = p["avg_cost"] * p["shares"] + p["fees_paid"]
            pnl = value - cost
            market_value += value
            floating += pnl
            rows.append({
                "code": code, "name": p["name"], "shares": p["shares"],
                "available": p["available"], "avg_cost": round2(p["avg_cost"]),
                "last": round2(last), "market_value": round2(value),
                "pnl": round2(pnl),
                "pnl_pct": round2(pnl / cost * 100.0) if cost > 0 else 0.0,
            })
        total = self.cash + market_value
        return {"day": self.day, "cash": round2(self.cash),
                "market_value": round2(market_value), "total": round2(total),
                "floating_pnl": round2(floating),
                "realized_pnl": round2(self.realized_pnl),
                "positions": rows, "trade_count": len(self.trades)}

    # -------- 持久化 --------
    def to_dict(self):
        return {"cash": self.cash, "day": self.day,
                "positions": self.positions, "realized_pnl": self.realized_pnl,
                "trades": self.trades[-500:]}

    @classmethod
    def from_dict(cls, data):
        p = cls(cash=data.get("cash", 350_000.0), day=data.get("day"))
        p.positions = data.get("positions", {}) or {}
        p.realized_pnl = float(data.get("realized_pnl", 0.0))
        p.trades = data.get("trades", []) or []
        return p
