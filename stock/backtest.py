# -*- coding: utf-8 -*-
"""均线交叉回测：金叉买入、死叉卖出，按整手成交并扣真实费用。

可选的现实约束（默认开启「涨跌停不可成交」，滑点默认 0）：
  * respect_limits：涨停买不进、跌停卖不出。跌停当天先挂单，后续哪天不在跌停就成交；
  * slippage_bps：按基点计的滑点，买入价 ×(1+slip)、卖出价 ×(1-slip)。

费用与模拟盘共用 rules.fee_detail（rounding=False，避免累计取整掩盖策略差异）。
"""
from .indicators import max_drawdown, sma
from .rules import (COMMISSION_RATE, MIN_COMMISSION, STAMP_RATE, TRANSFER_RATE,
                    fee_detail, price_limits, round2)


def _fee(amount, is_sell, commission_rate, min_commission, stamp_rate, transfer_rate):
    detail = fee_detail(amount, is_sell, rounding=False,
                        commission_rate=commission_rate, min_commission=min_commission,
                        stamp_rate=stamp_rate, transfer_rate=transfer_rate)
    return detail["total"]


def run_ma_cross(bars, short=5, long=20, cash=100_000.0,
                 commission_rate=COMMISSION_RATE, min_commission=MIN_COMMISSION,
                 stamp_rate=STAMP_RATE, transfer_rate=TRANSFER_RATE,
                 code=None, is_st=False, slippage_bps=0.0, respect_limits=True):
    """code 不为空且 respect_limits=True 时，按 A 股涨跌停约束成交。"""
    if short <= 0 or long <= 0:
        raise ValueError("short/long must be positive")
    slip = max(0.0, float(slippage_bps or 0.0)) / 10000.0
    use_limits = bool(respect_limits and code)

    empty = {"ok": True, "trades": [], "equity": [], "initial_equity": round2(float(cash)),
             "final_equity": round2(float(cash)),
             "metrics": {"total_return": 0.0, "max_drawdown": 0.0,
                         "win_rate": 0.0, "trade_count": 0},
             "skipped_buys": 0, "delayed_sells": 0, "forced_close": False,
             "params": {"short": short, "long": long, "slippage_bps": slippage_bps,
                        "respect_limits": bool(respect_limits)}}
    if not bars:
        return empty

    closes = [float(b["close"]) for b in bars]
    dates = [b["date"] for b in bars]
    fast = sma(closes, short)
    slow = sma(closes, long)

    cash_now = float(cash)
    shares = 0
    open_trade = None
    trades = []
    equity = []
    skipped_buys = 0
    delayed_sells = 0
    want_sell = False
    forced_close = False

    def limits_at(i):
        if not use_limits:
            return None, None
        prev_close = closes[i - 1] if i > 0 else closes[i]
        return price_limits(code, prev_close, is_st=is_st)

    def do_sell(i, sell_price):
        nonlocal cash_now, shares, open_trade
        amount = shares * sell_price
        fee = _fee(amount, True, commission_rate, min_commission, stamp_rate, transfer_rate)
        cash_now += amount - fee
        gross = (sell_price - open_trade["entry_price"]) * shares
        total_fee = open_trade["entry_fee"] + fee
        trades.append({**open_trade,
                       "exit_date": dates[i], "exit_price": round2(sell_price),
                       "exit_amount": round2(amount), "exit_fee": fee,
                       "fee": total_fee, "gross_pnl": round2(gross),
                       "pnl": round2(gross - total_fee),
                       "return_pct": round2((gross - total_fee)
                                            / open_trade["entry_amount"] * 100.0)})
        shares = 0
        open_trade = None

    for i, close in enumerate(closes):
        limits = limits_at(i)                     # (跌停, 涨停)，别解包反了
        limit_down_i = limits[0] if limits else None

        # 1) 昨天（或更早）挂起、因跌停没卖掉的单子：今天不在跌停就成交
        if shares > 0 and want_sell:
            if not (use_limits and limit_down_i is not None
                    and close <= limit_down_i + 1e-9):
                do_sell(i, close * (1.0 - slip))
                want_sell = False

        # 2) 信号判断
        if i > 0:
            cs, cl = fast[i], slow[i]
            ps, pl = fast[i - 1], slow[i - 1]
            if cs is not None and cl is not None:
                if ps is None or pl is None:
                    up = cs > cl
                    down = cs < cl
                else:
                    up = cs > cl and ps <= pl
                    down = cs < cl and ps >= pl

                if shares == 0 and up:
                    limit_up_i = limits_at(i)[1] if use_limits else None
                    if use_limits and limit_up_i is not None and close >= limit_up_i - 1e-9:
                        skipped_buys += 1  # 涨停买不进：放弃这次信号，不追
                    else:
                        buy_price = close * (1.0 + slip)
                        lots = int(cash_now / buy_price / 100) if buy_price > 0 else 0
                        qty = lots * 100
                        if qty > 0:
                            amount = qty * buy_price
                            fee = _fee(amount, False, commission_rate, min_commission,
                                       stamp_rate, transfer_rate)
                            if amount + fee <= cash_now + 1e-9:
                                cash_now -= amount + fee
                                shares = qty
                                open_trade = {"entry_date": dates[i],
                                              "entry_price": round2(buy_price),
                                              "shares": qty,
                                              "entry_amount": round2(amount),
                                              "entry_fee": fee}
                elif shares > 0 and down and not want_sell:
                    if (use_limits and limit_down_i is not None
                            and close <= limit_down_i + 1e-9):
                        want_sell = True   # 跌停卖不出：挂起，等能卖的那天
                        delayed_sells += 1
                    else:
                        do_sell(i, close * (1.0 - slip))

        equity.append({"date": dates[i], "close": close,
                       "cash": round2(cash_now + shares * close), "shares": shares})

    # 3) 末尾强制平仓（同样计费、计滑点）
    if shares > 0:
        forced_close = True
        do_sell(len(closes) - 1, closes[-1] * (1.0 - slip))
        equity[-1]["cash"] = round2(cash_now)
        equity[-1]["shares"] = 0

    final_equity = cash_now
    curve = [e["cash"] for e in equity]
    wins = sum(1 for t in trades if t["pnl"] > 0)
    metrics = {
        "total_return": round((final_equity / float(cash) - 1.0) * 100.0, 4) if cash else 0.0,
        "max_drawdown": round(abs(max_drawdown(curve)) * 100.0, 4),
        "win_rate": round(wins / len(trades) * 100.0, 2) if trades else 0.0,
        "trade_count": len(trades),
    }
    return {"ok": True, "trades": trades, "equity": equity,
            "initial_equity": round2(float(cash)), "final_equity": round2(final_equity),
            "metrics": metrics, "skipped_buys": skipped_buys,
            "delayed_sells": delayed_sells, "forced_close": forced_close,
            "params": {"short": short, "long": long,
                       "commission_rate": commission_rate, "stamp_rate": stamp_rate,
                       "transfer_rate": transfer_rate, "slippage_bps": slippage_bps,
                       "respect_limits": bool(respect_limits), "code": code}}
