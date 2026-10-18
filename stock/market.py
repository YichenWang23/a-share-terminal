# -*- coding: utf-8 -*-
"""开市/休市状态判定。

只能按「星期 + 交易时段 + 行情日期」判断，**无法识别法定节假日**（没有节假日日历），
所以节假日会显示成「非交易时段」，但行情时间戳会暴露真实数据日期——不假装实时。
"""
import datetime

SESSIONS = (
    ((9, 30), (11, 30)),
    ((13, 0), (15, 0)),
)


def is_trading_day(day):
    """周一至周五算交易日（不含法定节假日判断）。"""
    return day.weekday() < 5


def _minutes(dt):
    return dt.hour * 60 + dt.minute


def market_status(now=None, quote_date=None):
    """返回 {"status", "label", "quote_date", "stale_days"}。

    status: trading / lunch / preopen / closed / weekend / closed_data
    """
    now = now or datetime.datetime.now()
    today = now.date()
    today_str = today.isoformat()
    stale_days = None
    if quote_date:
        try:
            qd = datetime.date.fromisoformat(str(quote_date)[:10])
            stale_days = (today - qd).days
        except (ValueError, TypeError):
            qd = None
    else:
        qd = None

    if qd is not None and qd < today:
        return {"status": "closed_data", "label": "最近收盘 %s" % qd.isoformat(),
                "quote_date": qd.isoformat(), "stale_days": stale_days}
    if not is_trading_day(today):
        return {"status": "weekend", "label": "非交易日（周末）",
                "quote_date": today_str, "stale_days": stale_days}

    m = _minutes(now)
    if m < _minutes(datetime.datetime.combine(today, datetime.time(9, 30))):
        label = "未开盘"
        status = "preopen"
    elif _minutes(datetime.datetime.combine(today, datetime.time(9, 30))) <= m < \
            _minutes(datetime.datetime.combine(today, datetime.time(11, 30))):
        status, label = "trading", "交易中"
    elif _minutes(datetime.datetime.combine(today, datetime.time(11, 30))) <= m < \
            _minutes(datetime.datetime.combine(today, datetime.time(13, 0))):
        status, label = "lunch", "午间休市"
    elif _minutes(datetime.datetime.combine(today, datetime.time(13, 0))) <= m < \
            _minutes(datetime.datetime.combine(today, datetime.time(15, 0))):
        status, label = "trading", "交易中"
    else:
        status, label = "closed", "已收盘"
    return {"status": status, "label": label, "quote_date": today_str,
            "stale_days": stale_days}
