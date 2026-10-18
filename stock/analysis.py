# -*- coding: utf-8 -*-
"""AI 建议的「规则引擎」实现（默认来源，完全离线、结果可复现）。

打分口径（可核对，不含玄学）：
    趋势  价格>MA20 +30 / <MA20 -30；MA20>MA60 +15 / 反之 -15；价格>MA5 +10 / 反之 -10
    RSI   >70 -15（超买）；55~70 +10；45~55 0；30~45 -10；<30 +10（超卖反弹）
    MACD  柱>0 +15；柱<0 -15
    量能  量比>1.5 且上涨 +10 / 且下跌 -10
    位置  涨停附近 -10（追高风险）；跌停附近 +5；单日涨幅>5% -5；跌幅>5% +5
    stance：score >= 25 偏多；<= -25 偏空；其余中性

这里是规则，不是模型。界面必须标注来源（source=rule-engine）。
"""

DISCLAIMER = ("本页分析由本地规则引擎根据历史行情计算，仅供参考，不构成任何投资建议；"
              "股市有风险，决策请自行判断。")


def _last(seq):
    for v in reversed(seq or []):
        if v is not None:
            return v
    return None


def _mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else 0.0


def rule_engine(quote, bars):
    from .indicators import macd, rsi, sma

    quote = quote or {}
    bars = bars or []
    closes = [float(b["close"]) for b in bars]
    volumes = [float(b.get("volume") or 0.0) for b in bars]
    price = quote.get("price")
    price = float(price) if price is not None else (closes[-1] if closes else 0.0)
    change_pct = quote.get("change_pct")
    change_pct = float(change_pct) if change_pct is not None else 0.0

    ma5 = _last(sma(closes, 5)) if len(closes) >= 5 else None
    ma20 = _last(sma(closes, 20)) if len(closes) >= 20 else None
    ma60 = _last(sma(closes, 60)) if len(closes) >= 60 else None
    rsi_value = _last(rsi(closes, 14)) if len(closes) >= 15 else None
    dif, dea, hist = macd(closes) if closes else ([], [], [])
    macd_hist = _last(hist)
    macd_dif = _last(dif)

    vol_ratio = 0.0
    if len(volumes) >= 21:
        base = _mean(volumes[-21:-1])
        if base > 0:
            vol_ratio = volumes[-1] / base

    score = 0
    points = []

    # ---- 趋势 ----
    if ma20 is None:
        trend_verdict = "数据不足（少于 20 根）"
    elif price > ma20 and ma60 is not None and ma20 > ma60:
        trend_verdict = "多头排列（价 > MA20 > MA60）"
    elif price < ma20 and ma60 is not None and ma20 < ma60:
        trend_verdict = "空头排列（价 < MA20 < MA60）"
    else:
        trend_verdict = "震荡（价格与均线纠缠）"
    if ma20 is not None:
        score += 30 if price > ma20 else (-30 if price < ma20 else 0)
        if ma60 is not None:
            score += 15 if ma20 > ma60 else (-15 if ma20 < ma60 else 0)
        if ma5 is not None:
            score += 10 if price > ma5 else (-10 if price < ma5 else 0)
    points.append({"key": "trend", "label": "趋势",
                   "value": "MA5 %s / MA20 %s / MA60 %s" % (
                       _fmt(ma5), _fmt(ma20), _fmt(ma60)),
                   "verdict": trend_verdict})

    # ---- RSI ----
    if rsi_value is None:
        rsi_verdict = "数据不足"
    elif rsi_value > 70:
        rsi_verdict, score = "超买（涨幅透支）", score - 15
    elif rsi_value >= 55:
        rsi_verdict, score = "偏强", score + 10
    elif rsi_value >= 45:
        rsi_verdict = "中性"
    elif rsi_value >= 30:
        rsi_verdict, score = "偏弱", score - 10
    else:
        rsi_verdict, score = "超卖（可能有反弹）", score + 10
    points.append({"key": "rsi", "label": "RSI(14)",
                   "value": _fmt(rsi_value, 1), "verdict": rsi_verdict})

    # ---- MACD ----
    if macd_hist is None:
        macd_verdict = "数据不足"
    elif macd_hist > 0:
        macd_verdict, score = "红柱（DIF 在 DEA 上方）", score + 15
    elif macd_hist < 0:
        macd_verdict, score = "绿柱（DIF 在 DEA 下方）", score - 15
    else:
        macd_verdict = "零轴附近"
    points.append({"key": "macd", "label": "MACD",
                   "value": "DIF %s / 柱 %s" % (_fmt(macd_dif, 3), _fmt(macd_hist, 3)),
                   "verdict": macd_verdict})

    # ---- 量能 ----
    if vol_ratio <= 0:
        volume_verdict = "无成交量数据"
    elif vol_ratio > 1.5 and change_pct > 0:
        volume_verdict, score = "放量上涨", score + 10
    elif vol_ratio > 1.5 and change_pct < 0:
        volume_verdict, score = "放量下跌", score - 10
    elif vol_ratio < 0.6:
        volume_verdict = "缩量"
    else:
        volume_verdict = "量能平稳"
    points.append({"key": "volume", "label": "量能",
                   "value": "量比 %s" % _fmt(vol_ratio, 2) if vol_ratio > 0 else "—",
                   "verdict": volume_verdict})

    # ---- 位置（涨跌停 / 短线涨幅） ----
    limit_up = quote.get("limit_up")
    limit_down = quote.get("limit_down")
    if limit_up and price >= float(limit_up) * 0.999:
        position_verdict, score = "涨停附近（追高风险）", score - 10
    elif limit_down and price <= float(limit_down) * 1.001:
        position_verdict, score = "跌停附近（反弹博弈）", score + 5
    elif change_pct > 5:
        position_verdict, score = "短线涨幅较大", score - 5
    elif change_pct < -5:
        position_verdict, score = "短线跌幅较大", score + 5
    else:
        position_verdict = "位置中性"
    points.append({"key": "position", "label": "位置",
                   "value": "当日 %+.2f%%" % change_pct, "verdict": position_verdict})

    # ---- 结论 ----
    if score >= 25:
        stance = "偏多"
    elif score <= -25:
        stance = "偏空"
    else:
        stance = "中性"

    insufficient = len(bars) < 60
    bullets = []
    if insufficient:
        bullets.append("历史数据不足（仅 %d 根 K 线），结论参考价值有限。" % len(bars))
    bullets.append("趋势：%s。" % trend_verdict)
    bullets.append("动量：RSI(14) = %s，%s。" % (_fmt(rsi_value, 1), rsi_verdict))
    bullets.append("MACD：%s。" % macd_verdict)
    bullets.append("量能：%s（量比 %s）。" % (volume_verdict, _fmt(vol_ratio, 2)))
    bullets.append("位置：%s。" % position_verdict)
    bullets.append("综合判定：%s（规则分 %d，阈值 ±25）。" % (stance, score))

    risks = []
    if rsi_value is not None and rsi_value > 70:
        risks.append("RSI 超买，短线回撤风险上升。")
    if limit_up and price >= float(limit_up) * 0.999:
        risks.append("已接近涨停价，次日开盘波动可能较大。")
    if insufficient:
        risks.append("样本不足 60 根，均线与 MACD 的统计意义有限。")

    return {
        "source": "rule-engine",
        "stance": stance,
        "score": score,
        "points": points,
        "bullets": bullets,
        "risks": risks,
        "disclaimer": DISCLAIMER,
        "insufficient_history": insufficient,
        "metrics": {
            "price": round(price, 3),
            "change_pct": round(change_pct, 3),
            "ma5": _round(ma5), "ma20": _round(ma20), "ma60": _round(ma60),
            "rsi": _round(rsi_value, 1),
            "dif": _round(macd_dif, 4), "dea": _round(_last(dea), 4),
            "macd_hist": _round(macd_hist, 4),
            "vol_ratio": _round(vol_ratio, 2),
            "bars": len(bars),
        },
    }


def _fmt(value, digits=2):
    return "—" if value is None else ("%.*f" % (digits, value))


def _round(value, digits=2):
    return None if value is None else round(float(value), digits)
