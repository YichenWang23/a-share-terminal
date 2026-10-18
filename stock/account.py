# -*- coding: utf-8 -*-
"""个人账户：资金流水（入金/出金）、总资产与收益率、持仓权重、资产快照。

和 Portfolio 的分工：
  * Portfolio 只管「在这个账户里怎么买卖」；
  * Account 只管「这个账户本身」——初始本金、累计入金、总收益率、资产配置、历史净值。

收益口径：总收益 = 总资产 − 净入金（入金 − 出金），而不是拿「涨了多少」瞎猜。
"""
import math
import time

KIND_DEPOSIT = "deposit"
KIND_WITHDRAW = "withdraw"
KINDS = (KIND_DEPOSIT, KIND_WITHDRAW)

MAX_SNAPSHOTS = 240

# 钱包 = 假的银行卡：入金从这里扣、出金回到这里，永远不能为负。
DEFAULT_WALLET = 150_000.0


def default_account(cash=0.0, day=None, wallet=DEFAULT_WALLET):
    """新账户：一条开户入金流水 + 一个钱包余额（假的银行卡）。"""
    day = day or time.strftime("%Y-%m-%d")
    acct = {"flows": [], "snapshots": [], "next_id": 1,
            "wallet": round(float(wallet), 2)}
    if cash:
        add_flow(acct, KIND_DEPOSIT, cash, day=day, note="开户初始资金")
    return acct


def ensure_wallet(acct, default=DEFAULT_WALLET):
    """老账户没有钱包字段时补一个，保证钱包一定存在。"""
    if acct.get("wallet") is None:
        acct["wallet"] = round(float(default), 2)
    return acct


def wallet_balance(acct):
    return round(float(ensure_wallet(acct).get("wallet") or 0.0), 2)


def flows(acct):
    return list((acct or {}).get("flows") or [])


def net_deposit(acct):
    """净入金 = Σ入金 − Σ出金。"""
    total = 0.0
    for f in flows(acct):
        try:
            amount = float(f.get("amount") or 0)
        except (TypeError, ValueError):
            continue
        total += amount if f.get("type") == KIND_DEPOSIT else -amount
    return round(total, 2)


def add_flow(acct, kind, amount, day=None, note=""):
    """记账一笔入金/出金（只记流水，不动现金；现金由调用方调整）。"""
    if kind not in KINDS:
        raise ValueError("kind 必须是 deposit 或 withdraw")
    try:
        raw = float(amount)
    except (TypeError, ValueError):
        raise ValueError("金额必须是数字")
    # NaN / Infinity 会被 float() 正常接受，但一旦写进账本，现金就变成 NaN，
    # 之后所有比较都恒为 False（连「余额不足」都拦不住）。必须在入口挡掉。
    if not math.isfinite(raw):
        raise ValueError("金额必须是有限数（不能是 NaN 或 Infinity）")
    amount = round(raw, 2)
    if amount <= 0:
        raise ValueError("金额必须为正数")
    day = day or time.strftime("%Y-%m-%d")
    nid = int(acct.get("next_id") or (len(flows(acct)) + 1))
    flow = {"id": nid, "day": day, "type": kind,
            "amount": amount, "note": str(note or "")[:60]}
    acct.setdefault("flows", []).append(flow)
    acct["next_id"] = nid + 1
    return flow


def summary(acct, snap):
    """账户概览。snap 是 Portfolio.snapshot() 的结果。"""
    cash = float(snap.get("cash") or 0.0)
    market_value = float(snap.get("market_value") or 0.0)
    total = float(snap.get("total") if snap.get("total") is not None
                  else cash + market_value)
    net = net_deposit(acct)
    pnl = round(total - net, 2)
    wallet = wallet_balance(acct)
    net_worth = round(total + wallet, 2)
    return {
        "cash": round(cash, 2),
        "market_value": round(market_value, 2),
        "total": round(total, 2),
        "net_deposit": net,
        "floating_pnl": round(float(snap.get("floating_pnl") or 0.0), 2),
        "realized_pnl": round(float(snap.get("realized_pnl") or 0.0), 2),
        "total_pnl": pnl,
        "total_return_pct": round(pnl / net * 100.0, 2) if net > 0 else 0.0,
        "position_count": len(snap.get("positions") or []),
        "day": snap.get("day"),
        "wallet": wallet,
        "net_worth": net_worth,
        "position_pct_of_net": (round(market_value / net_worth * 100.0, 2)
                                if net_worth > 0 else 0.0),
    }


def allocation(acct, snap):
    """资产配置：现金 + 每只股票占总资产的比例（合计 100%）。"""
    cash = float(snap.get("cash") or 0.0)
    total = float(snap.get("total") or 0.0)
    if total <= 0:
        total = cash + float(snap.get("market_value") or 0.0)
    items = []
    for pos in snap.get("positions") or []:
        value = float(pos.get("market_value") or 0.0)
        weight = (value / total * 100.0) if total > 0 else 0.0
        items.append({"code": pos.get("code"), "name": pos.get("name"),
                      "shares": pos.get("shares"),
                      "market_value": round(value, 2),
                      "pnl": pos.get("pnl"), "pnl_pct": pos.get("pnl_pct"),
                      "weight": round(weight, 2)})
    items.sort(key=lambda x: -x["weight"])
    cash_pct = round(cash / total * 100.0, 2) if total > 0 else 0.0
    return {"total": round(total, 2), "cash": round(cash, 2),
            "cash_pct": cash_pct, "invested_pct": round(100.0 - cash_pct, 2),
            "items": items}


def record_snapshot(acct, day, snap):
    """每天最多记一条资产快照（同日覆盖），最多保留 MAX_SNAPSHOTS 条。

    返回 True 表示新增/更新了数据（调用方据此决定是否落盘）。
    """
    if not day:
        return False
    row = {"date": str(day)[:10],
           "total": round(float(snap.get("total") or 0.0), 2),
           "cash": round(float(snap.get("cash") or 0.0), 2),
           "market_value": round(float(snap.get("market_value") or 0.0), 2)}
    snaps = acct.setdefault("snapshots", [])
    for i, item in enumerate(snaps):
        if item.get("date") == row["date"]:
            if item.get("total") == row["total"] and item.get("cash") == row["cash"]:
                return False
            snaps[i] = row
            return True
    snaps.append(row)
    snaps.sort(key=lambda s: s.get("date", ""))
    if len(snaps) > MAX_SNAPSHOTS:
        del snaps[:len(snaps) - MAX_SNAPSHOTS]
    return True


def equity_curve(acct):
    """资产曲线数据点（升序）。"""
    return sorted(list((acct or {}).get("snapshots") or []), key=lambda s: s.get("date", ""))
