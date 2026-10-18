# -*- coding: utf-8 -*-
"""为「全部自选股」录制离线样本：行情（一次请求）+ 每只的日 K。

用法（需要网络）：
    python tools/record_all_fixtures.py

产物：
    fixtures/tencent_quote_all.txt           一次请求拿到的全部行情（GBK）
    fixtures/tencent_kline_<symbol>_day.json 每只日 K（主票 320 根，其余 120 根）
    fixtures/MANIFEST.json                   全量 SHA256 清单

这样断网首启时，47 只票都能出数据，而不是只有贵州茅台一只。
"""
import hashlib
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stock import storage  # noqa: E402
from stock.rules import tencent_symbol  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(BASE_DIR, "fixtures")
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36",
    "Referer": "https://gu.qq.com/",
}
KLINE_BARS = 120          # 其余票：够画图算指标，省体积
KLINE_BARS_MAIN = 320     # 演示主票保持与默认请求量一致
MAIN_CODE = "600519"


def fetch(url, timeout=25):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    os.makedirs(FIXTURES, exist_ok=True)
    codes = list(storage.DEFAULT_WATCHLIST)
    symbols = [tencent_symbol(c) for c in codes]
    print("自选股 %d 只，开始录制…" % len(codes))

    raw = fetch("https://qt.gtimg.cn/q=" + ",".join(symbols))
    quote_path = os.path.join(FIXTURES, "tencent_quote_all.txt")
    with open(quote_path, "wb") as f:
        f.write(raw)
    print("  行情  %8d B  %s" % (len(raw), os.path.basename(quote_path)))

    ok = fail = 0
    for code in codes:
        symbol = tencent_symbol(code)
        want = KLINE_BARS_MAIN if code == MAIN_CODE else KLINE_BARS
        name = "tencent_kline_%s_day.json" % symbol
        path = os.path.join(FIXTURES, name)
        url = ("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
               "?param=%s,day,,,%d,qfq" % (symbol, want))
        try:
            body = fetch(url)
            data = json.loads(body.decode("utf-8", "replace"))
            node = (data.get("data") or {}).get(symbol) or {}
            bars = node.get("qfqday") or node.get("day") or []
            if not bars:
                raise ValueError("没有 K 线数据")
            with open(path, "wb") as f:
                f.write(body)
            ok += 1
        except Exception as exc:  # noqa: BLE001
            fail += 1
            print("    FAIL %s: %s" % (code, str(exc)[:60]))
    print("  日K   成功 %d / %d（失败 %d）" % (ok, len(codes), fail))

    manifest = {}
    for name in sorted(os.listdir(FIXTURES)):
        full = os.path.join(FIXTURES, name)
        if name == "MANIFEST.json" or not os.path.isfile(full):
            continue
        manifest[name] = {"bytes": os.path.getsize(full), "sha256": sha256(full)}
    with open(os.path.join(FIXTURES, "MANIFEST.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    print("  MANIFEST %d 个文件" % len(manifest))
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
