# -*- coding: utf-8 -*-
"""候选股票验真：行情能拿到、K 线能拿到、名称对得上。

用法：python tools/verify_candidates.py
输出：每个代码一行结论，最后给出可直接入选的代码列表。
"""
import json
import sys
import urllib.request

BASE_DIR = __import__("os").path.dirname(__import__("os").path.dirname(
    __import__("os").path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from stock import storage  # noqa: E402

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36",
    "Referer": "https://gu.qq.com/",
}

# 候选：代码 -> 期望名称（只写确定的名气票）
CANDIDATES = {
    "000651": "格力电器", "600690": "海尔智家", "600600": "青岛啤酒",
    "000895": "双汇发展", "002714": "牧原股份", "603345": "安井食品",
    "002557": "洽洽食品", "600872": "中炬高新", "600809": "山西汾酒",
    "002304": "洋河股份", "000596": "古井贡酒", "603369": "今世缘",
    "601288": "农业银行", "601988": "中国银行", "601939": "建设银行",
    "601166": "兴业银行", "600000": "浦发银行", "601601": "中国太保",
    "601628": "中国人寿", "601688": "华泰证券", "600999": "招商证券",
    "600050": "中国联通", "601728": "中国电信", "000063": "中兴通讯",
    "002230": "科大讯飞", "603986": "兆易创新", "002049": "紫光国微",
    "002371": "北方华创", "603501": "韦尔股份", "688111": "金山办公",
    "688036": "传音控股", "688169": "石头科技", "300124": "汇川技术",
    "002236": "大华股份", "600438": "通威股份", "300274": "阳光电源",
    "002460": "赣锋锂业", "300014": "亿纬锂能", "600104": "上汽集团",
    "601633": "长城汽车", "000625": "长安汽车", "002050": "三花智控",
    "300760": "迈瑞医疗", "000538": "云南白药", "600436": "片仔癀",
    "300015": "爱尔眼科", "603259": "药明康德", "600019": "宝钢股份",
    "600585": "海螺水泥", "601225": "陕西煤业", "601600": "中国铝业",
    "601111": "中国国航", "601006": "大秦铁路", "601919": "中远海控",
    "601985": "中国核电", "601390": "中国中铁", "601766": "中国中车",
    "600048": "保利发展", "002027": "分众传媒", "600028": "中国石化",
}


def symbol(code):
    return ("sh" if code[0] in "56" else ("sz" if code[0] in "03" else "bj")) + code


def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
        return r.read()


def norm(name):
    return str(name).replace(" ", "").replace("Ａ", "A").replace("Ａ", "A")


def main():
    have = set(storage.DEFAULT_WATCHLIST)
    ok, skipped, bad = [], [], []
    for code, want in CANDIDATES.items():
        if code in have:
            skipped.append(code)
            continue
        sym = symbol(code)
        try:
            raw = fetch("https://qt.gtimg.cn/q=" + sym).decode("gbk", "replace")
            parts = raw.split("~")
            name = norm(parts[1]) if len(parts) > 2 else ""
            price = float(parts[3]) if len(parts) > 3 and parts[3] else 0
            body = fetch("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
                         "?param=%s,day,,,120,qfq" % sym)
            data = json.loads(body.decode("utf-8", "replace")).get("data") or {}
            node = data.get(sym) or {}
            bars = node.get("qfqday") or node.get("day") or []
            good = price > 0 and bool(bars) and norm(want) == name
            line = "%-8s %-8s %8.2f  K线%3d  %s" % (code, name, price, len(bars),
                                                    "OK" if good else "FAIL")
            if good:
                ok.append(code)
            else:
                bad.append((code, name, want, len(bars)))
            print(line)
        except Exception as exc:  # noqa: BLE001
            bad.append((code, "ERR", want, 0))
            print("%-8s %-8s %8s  %s" % (code, "ERR", "-", str(exc)[:40]))

    print()
    print("通过 %d 只 | 已在池中跳过 %d 只 | 失败 %d 只" % (len(ok), len(skipped), len(bad)))
    if bad:
        print("失败明细:", bad)
    print()
    print("可入选（前 48 只）:")
    print(",".join(ok[:48]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
