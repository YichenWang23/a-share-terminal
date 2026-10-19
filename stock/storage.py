# -*- coding: utf-8 -*-
"""本地状态：自选股、模拟盘、预警、设置。无数据库，一个 JSON 文件。

写入用「临时文件 + 原子替换」，避免半截文件把状态写坏。
"""
import json
import os
import time

from . import secrets

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
STATE_PATH = os.path.join(DATA_DIR, "state.json")

DEFAULT_WATCHLIST = [
    # ---- A 股·半导体与电子（科技核心）----
    "688981",  # 中芯国际（半导体制造）
    "688825",  # 长鑫科技（存储芯片）
    "002371",  # 北方华创（半导体设备）
    "603986",  # 兆易创新（存储/MCU）
    "002049",  # 紫光国微（特种芯片）
    "603501",  # 豪威集团（原韦尔股份，CMOS 图像传感器）
    # ---- A 股·软件与通信 ----
    "688111",  # 金山办公（WPS）
    "002230",  # 科大讯飞（AI 语音）
    "000063",  # 中兴通讯（通信设备）
    "600050",  # 中国联通（运营商）
    "688036",  # 传音控股（手机出海）
    # ---- A 股·新能源与汽车 ----
    "300750",  # 宁德时代（动力电池）
    "002594",  # 比亚迪（新能源车）
    "300274",  # 阳光电源（光伏逆变器）
    "600438",  # 通威股份（光伏硅料）
    "601012",  # 隆基绿能（光伏组件）
    "300014",  # 亿纬锂能（电池）
    "002460",  # 赣锋锂业（锂矿）
    "600104",  # 上汽集团（整车）
    "601633",  # 长城汽车（整车）
    "000625",  # 长安汽车（整车）
    "300124",  # 汇川技术（工控/伺服）
    "688169",  # 石头科技（扫地机器人）
    # ---- A 股·金融 ----
    "000001",  # 平安银行
    "600036",  # 招商银行
    "601398",  # 工商银行
    "601939",  # 建设银行
    "601318",  # 中国平安（保险）
    "601628",  # 中国人寿（保险）
    "600030",  # 中信证券
    "300059",  # 东方财富
    # ---- A 股·白酒与食品饮料 ----
    "600519",  # 贵州茅台
    "000858",  # 五粮液
    "000568",  # 泸州老窖
    "600809",  # 山西汾酒
    "002304",  # 洋河股份
    "000596",  # 古井贡酒
    "600600",  # 青岛啤酒
    "600887",  # 伊利股份
    "603288",  # 海天味业
    "000895",  # 双汇发展
    "002714",  # 牧原股份（生猪养殖）
    # ---- A 股·家电与消费 ----
    "000333",  # 美的集团
    "000651",  # 格力电器
    "600690",  # 海尔智家
    "002415",  # 海康威视（安防）
    "002236",  # 大华股份（安防）
    "002475",  # 立讯精密（消费电子）
    "601888",  # 中国中免（免税）
    # ---- A 股·医药 ----
    "600276",  # 恒瑞医药（创新药）
    "603259",  # 药明康德（CXO）
    "300760",  # 迈瑞医疗（医疗器械）
    "000538",  # 云南白药
    "600436",  # 片仔癀
    "300015",  # 爱尔眼科
    # ---- A 股·资源与能源 ----
    "601857",  # 中国石油
    "600028",  # 中国石化
    "601088",  # 中国神华（煤炭）
    "601899",  # 紫金矿业（有色）
    "600900",  # 长江电力（水电）
    "600941",  # 中国移动（运营商）
    # ---- A 股·基建与制造 ----
    "601668",  # 中国建筑
    "600031",  # 三一重工
    # ---- A 股·运输与地产 ----
    "601919",  # 中远海控（航运）
    "600048",  # 保利发展（地产）
    # ---- A 股·小众与传媒 ----
    "605300",  # 佳禾食品（奶茶原料）
    "002847",  # 盐津铺子
    "002216",  # 三全食品
    "300783",  # 三只松鼠
    # ---- A 股·知名民企 ----
    "300308",  # 中际旭创（光模块，民企）
    "002050",  # 三花智控（热管理，民企）
    "002271",  # 东方雨虹（防水材料，民企）
    "300433",  # 蓝思科技（消费电子玻璃，民企）
    "002032",  # 苏泊尔（小家电，民企）
    "002242",  # 九阳股份（小家电，民企）
    "603899",  # 晨光股份（文具，民企）
    "300661",  # 圣邦股份（模拟芯片，民企）
    "002812",  # 恩捷股份（隔膜，民企）
    "603605",  # 珀莱雅（美妆，民企）
    "688363",  # 华熙生物（医美/玻尿酸，民企）
    "300454",  # 深信服（网络安全，民企）
    "603027",  # 千禾味业（调味品，民企）
    "600660",  # 福耀玻璃（汽车玻璃，民营）
    "002352",  # 顺丰控股（快递，民营）
    "002241",  # 歌尔股份（声学/VR 代工，民营）
    "002624",  # 完美世界（游戏）
    "002027",  # 分众传媒（广告）
    # ---- A 股·补足到 100 只 ----
    "002557",  # 洽洽食品（瓜子零食，民企）
    "603866",  # 桃李面包（面包，民企）
    "603719",  # 良品铺子（零食，民企）
    "002867",  # 周大生（珠宝，民企）
    "600872",  # 中炬高新（酱油，民企）
    "600585",  # 海螺水泥（水泥，国企）
    "601766",  # 中国中车（高铁装备，国企）
    "601111",  # 中国国航（航空，国企）
    "601288",  # 农业银行（国有大行）
    "601728",  # 中国电信（运营商，国企）
    "000002",  # 万科A（地产，混合）
    "000725",  # 京东方A（面板，国企）
    # ---- 指数基金 ----
    "510300",  # 沪深300ETF
]

DEFAULT_CASH = 350_000.0

DEFAULT_STATE = {
    "watchlist": DEFAULT_WATCHLIST,
    "portfolio": {"cash": DEFAULT_CASH, "day": None, "positions": {},
                  "realized_pnl": 0.0, "trades": []},
    "alerts": [],
    "account": {"flows": [], "snapshots": [], "next_id": 1, "wallet": 0.0},
    "settings": {
        "llm": {
            "enabled": False,
            "base_url": "https://api.deepseek.com/chat/completions",
            "model": "deepseek-chat",
            "api_key": "",
            "api_key_enc": "",
            "api_key_mode": "",
            "note": "填 key 并勾选启用后，AI 面板会调用真实模型；否则使用本地规则引擎。key 用 Windows DPAPI 加密存本机。",
        }
    },
    "updated_at": None,
}


TRADE_KEEP = 500


def archive_trades(trades, keep=TRADE_KEEP, arch_dir=None):
    """成交记录超过 keep 条时，把最老的写进归档文件，只留在内存里最近 keep 条。

    返回 (保留的成交, 归档条数)。归档文件按天命名，追加写入。
    """
    trades = list(trades or [])
    if len(trades) <= keep:
        return trades, 0
    overflow, kept = trades[:-keep], trades[-keep:]
    arch_dir = arch_dir or DATA_DIR
    os.makedirs(arch_dir, exist_ok=True)
    name = "trades-archive-%s.json" % time.strftime("%Y%m%d")
    path = os.path.join(arch_dir, name)
    existing = []
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except (OSError, ValueError):
            existing = []
    existing.extend(overflow)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)
    return kept, len(overflow)


def _migrate_account(state):
    """老状态没有账户系统：用「现金 + 持仓成本」当开户本金，收益从 0 起算。

    已有账户但没有钱包字段的，也要补上钱包（默认 15 万），否则前端读不到余额。
    """
    from . import account as account_mod
    acct = state.get("account") or {}
    if acct.get("flows"):
        account_mod.ensure_wallet(acct)
        state["account"] = acct
        return state
    pf = state.get("portfolio") or {}
    cash = float(pf.get("cash") or 0.0)
    cost = 0.0
    for pos in (pf.get("positions") or {}).values():
        try:
            cost += float(pos.get("avg_cost") or 0.0) * int(pos.get("shares") or 0)
        except (TypeError, ValueError):
            continue
    base_amt = round(cash + cost, 2)
    state["account"] = account_mod.default_account(
        base_amt, day=time.strftime("%Y-%m-%d"))
    return state


def _migrate_keys(state):
    """老版本把明文 key 存在 settings.llm.api_key：迁移成密文并清掉明文。"""
    cfg = ((state.get("settings") or {}).get("llm") or {})
    plain = str(cfg.get("api_key") or "").strip()
    if plain and not cfg.get("api_key_enc"):
        secrets.set_key(cfg, plain)
        state["settings"]["llm"] = cfg
    return state


def _merge(base, given):
    out = dict(base)
    for k, v in (given or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load(path=None):
    path = path or STATE_PATH
    if not os.path.exists(path):
        return json.loads(json.dumps(DEFAULT_STATE))
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _migrate_account(_migrate_keys(_merge(DEFAULT_STATE, json.load(f))))
    except (OSError, ValueError):
        # 文件坏了不能让整个系统起不来：退到默认状态，并把坏文件改名留档
        try:
            os.replace(path, path + ".broken-%d" % int(time.time()))
        except OSError:
            pass
        return json.loads(json.dumps(DEFAULT_STATE))


def save(state, path=None):
    path = path or STATE_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    state = dict(state)
    # 成交记录超长就归档，避免 state.json 无限膨胀
    portfolio = dict(state.get("portfolio") or {})
    if portfolio.get("trades"):
        kept, archived = archive_trades(portfolio["trades"],
                                        arch_dir=os.path.dirname(path) or DATA_DIR)
        if archived:
            portfolio["trades"] = kept
            state["portfolio"] = portfolio
    state["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)
    return state["updated_at"]
