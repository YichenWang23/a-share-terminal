# -*- coding: utf-8 -*-
"""A 股交易规则：代码/市场、涨跌停、整手、佣金/印花税/过户费。

费率（测试里是硬编码手算基准）：
  * 佣金 0.03%，单笔最低 5 元（买卖都收）
  * 印花税 0.05%，只卖出收
  * 过户费 0.001%，买卖都收
涨跌停：
  * 主板 ±10%；创业板 300/301、科创板 688 ±20%；ST ±5%（需调用方显式传 is_st）

fee_detail(..., rounding=False) 供回测使用：不做分位取整，避免累计误差掩盖策略差异。
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext

COMMISSION_RATE = 0.0003
MIN_COMMISSION = 5.0
STAMP_RATE = 0.0005
TRANSFER_RATE = 0.00001

SH_PREFIXES = ("5", "6", "9")
SZ_PREFIXES = ("0", "1", "2", "3")


def round2(value):
    """四舍五入到分（Decimal 半进位，避免二进制浮点的 0.005 陷阱）。

    默认 Decimal 上下文只有 28 位精度，1e300 这种数 quantize 会抛
    InvalidOperation；这里按数值位数临时放宽精度，并显式拒绝 NaN/Inf。
    """
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("不是合法数字")
    if not dec.is_finite():
        raise ValueError("必须是有限数")
    sign, digits, exp = dec.as_tuple()   # 1e300 的有效位只有 1 个，量级在 exp 里
    need = len(digits) + max(0, exp) + 4
    with localcontext() as ctx:
        ctx.prec = max(28, need)
        return float(dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def normalize_code(raw):
    """把 'sh600519' / 'SH600519' / ' 600519 ' 统一成裸代码。"""
    text = str(raw).strip()
    if text.lower().startswith(("sh", "sz", "bj", "hk")):
        text = text[2:]
    return text.strip()


def market_of(code):
    """返回 'sh' / 'sz'。"""
    c = normalize_code(code)
    if not c:
        return "sz"
    if c[0] in SH_PREFIXES:
        return "sh"
    if c[0] in SZ_PREFIXES:
        return "sz"
    return "sh" if c.startswith(("6", "9")) else "sz"


def tencent_symbol(code):
    c = normalize_code(code)
    return market_of(c) + c


def is_st_name(name):
    """从证券名称判断是否 ST / *ST（退市风险警示）。

    数据源没有独立的 ST 标志位，但 A 股名称规范里 ST 一定在开头，
    所以用名称前缀判断比让用户手填可靠。
    """
    n = str(name or "").replace(" ", "").upper()
    return n.startswith("ST") or n.startswith("*ST")


def limit_pct(code, is_st=False):
    """涨跌停幅度。

    注意：创业板(300/301)与科创板(688)注册制后即便 ST 也是 20%，
    只有主板 ST 才收窄到 5%。
    """
    c = normalize_code(code)
    if c.startswith(("300", "301", "688")):
        return 0.20
    if is_st:
        return 0.05
    return 0.10


def price_limits(code, prev_close, is_st=False):
    """(跌停价, 涨停价)，按分四舍五入。

    用 Decimal 从十进制字符串起算，避免 1.65*0.9 = 1.4849999… 被错误截到 1.48。
    """
    prev = Decimal(str(float(prev_close)))
    pct = Decimal(str(limit_pct(code, is_st=is_st)))
    low = (prev * (Decimal("1") - pct)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    high = (prev * (Decimal("1") + pct)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(low), float(high)


def commission(amount, rounding=True, rate=COMMISSION_RATE, minimum=MIN_COMMISSION):
    value = max(minimum, float(amount) * rate)
    return round2(value) if rounding else value


def stamp_duty(amount, is_sell, rounding=True, rate=STAMP_RATE):
    if not is_sell:
        return 0.0
    value = float(amount) * rate
    return round2(value) if rounding else value


def transfer_fee(amount, rounding=True, rate=TRANSFER_RATE):
    value = float(amount) * rate
    return round2(value) if rounding else value


def fee_detail(amount, is_sell, rounding=True, commission_rate=COMMISSION_RATE,
               min_commission=MIN_COMMISSION, stamp_rate=STAMP_RATE,
               transfer_rate=TRANSFER_RATE):
    """每笔费用明细；前端、模拟盘、回测共用这一份，不各算一遍。"""
    c = commission(amount, rounding=rounding, rate=commission_rate, minimum=min_commission)
    s = stamp_duty(amount, is_sell, rounding=rounding, rate=stamp_rate)
    t = transfer_fee(amount, rounding=rounding, rate=transfer_rate)
    total = c + s + t
    return {"commission": c, "stamp": s, "transfer": t,
            "total": round2(total) if rounding else total}


def total_fee(amount, is_sell, rounding=True):
    return fee_detail(amount, is_sell, rounding=rounding)["total"]
