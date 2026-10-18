# -*- coding: utf-8 -*-
"""技术指标：SMA / EMA / RSI(Wilder) / MACD / 最大回撤。

约定：
  * 序列类函数输出长度与输入等长，数据不足的前缀用 None 占位（不填充假值）；
  * 输入按时间升序（最旧在前），最后一个元素是最新；
  * 不做任何「美化」（例如把 None 变成 0），调用方自己判断。
"""


def sma(values, window):
    """简单移动平均。window<=0 抛 ValueError。"""
    if window <= 0:
        raise ValueError("window must be positive")
    out = []
    total = 0.0
    for i, v in enumerate(values):
        total += v
        if i >= window:
            total -= values[i - window]
        out.append(total / window if i >= window - 1 else None)
    return out


def ema(values, window):
    """指数移动平均：alpha = 2/(window+1)，首值作种子。"""
    if window <= 0:
        raise ValueError("window must be positive")
    if not values:
        return []
    alpha = 2.0 / (window + 1.0)
    out = [float(values[0])]
    for v in values[1:]:
        out.append(out[-1] + alpha * (float(v) - out[-1]))
    return out


def rsi(closes, window=14):
    """Wilder RSI。数据不足 window+1 根时返回全 None。"""
    if window <= 0:
        raise ValueError("window must be positive")
    n = len(closes)
    out = [None] * n
    if n < window + 1:
        return out

    gains = []
    losses = []
    for i in range(1, n):
        diff = float(closes[i]) - float(closes[i - 1])
        gains.append(diff if diff > 0 else 0.0)
        losses.append(-diff if diff < 0 else 0.0)

    avg_gain = sum(gains[:window]) / window
    avg_loss = sum(losses[:window]) / window

    def value(g, l):
        if g == 0 and l == 0:
            return 50.0
        if l == 0:
            return 100.0
        rs = g / l
        return 100.0 - 100.0 / (1.0 + rs)

    out[window] = value(avg_gain, avg_loss)
    for i in range(window + 1, n):
        avg_gain = (avg_gain * (window - 1) + gains[i - 1]) / window
        avg_loss = (avg_loss * (window - 1) + losses[i - 1]) / window
        out[i] = value(avg_gain, avg_loss)
    return out


def macd(closes, fast=12, slow=26, signal=9):
    """返回 (DIF, DEA, 柱)。柱 = (DIF-DEA)*2，与常见行情软件口径一致。"""
    if not closes:
        return [], [], []
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    dif = [f - s for f, s in zip(ema_fast, ema_slow)]
    dea = ema(dif, signal)
    hist = [(d - e) * 2.0 for d, e in zip(dif, dea)]
    return dif, dea, hist


def max_drawdown(equity):
    """最大回撤，返回负数小数（如 -0.25 表示回撤 25%）；单调上升返回 0.0。"""
    if not equity:
        return 0.0
    peak = equity[0]
    worst = 0.0
    for v in equity:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (v - peak) / peak
            if dd < worst:
                worst = dd
    return worst
