# -*- coding: utf-8 -*-
"""录制真实行情响应，作为离线测试与降级演示的样本（一次性开发工具）。

用法（需要联网，只跑一次）：
    python tools/record_fixtures.py

产物：fixtures/*（原始字节，不改写）+ fixtures/MANIFEST.json（URL/时间/SHA256）。

为什么存原始字节：
  * 测试要能离线跑，不能依赖当天行情；
  * 接口改格式时，用旧样本能立刻区分「解析坏了」还是「接口变了」。

选源依据见 tools/probe_report.json：本机 Python 直连东财 quote/kline 会被
RemoteDisconnected 断开，腾讯/新浪/东财搜索可用，故以此为准。
"""
import hashlib
import json
import os
import sys
import time
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(BASE, "fixtures")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

JOBS = [
    ("tencent_quote_sh600519.txt",
     "https://qt.gtimg.cn/q=sh600519,sz000001,sz300750,sh510300",
     {"Referer": "https://finance.qq.com/"}),
    ("tencent_kline_sh600519_day.json",
     "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
     "?param=sh600519,day,,,320,qfq",
     {"Referer": "https://finance.qq.com/"}),
    ("sina_quote_sh600519.txt",
     "https://hq.sinajs.cn/list=sh600519,sz000001",
     {"Referer": "https://finance.sina.com.cn/"}),
    ("tencent_minute_sh600519.json",
     "https://web.ifzq.gtimg.cn/appstock/app/minute/query?code=sh600519",
     {"Referer": "https://finance.qq.com/"}),
    ("em_search_maotai.json",
     "https://searchapi.eastmoney.com/api/suggest/get?input=%E8%8C%85%E5%8F%B0"
     "&type=14&token=D43BF722C8E33BDC906FB84D85E326E8&count=10",
     {}),
]


def fetch(url, headers):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **headers})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def main():
    os.makedirs(FIX, exist_ok=True)
    manifest = []
    for name, url, headers in JOBS:
        raw = fetch(url, headers)
        with open(os.path.join(FIX, name), "wb") as f:
            f.write(raw)
        item = {"file": name, "url": url, "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        manifest.append(item)
        print("%-38s %8d bytes  %s" % (name, len(raw), item["sha256"]))
    with open(os.path.join(FIX, "MANIFEST.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"recorded_at": time.strftime("%Y-%m-%d %H:%M:%S"), "items": manifest},
                  f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("\nmanifest -> fixtures/MANIFEST.json")


if __name__ == "__main__":
    main()
