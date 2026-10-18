# -*- coding: utf-8 -*-
"""探测各行情源在「Python 直连」下的可用性（一次性诊断工具）。

背景：web 抓取能通，但 urllib 直连东财的 quote/kline 会被 RemoteDisconnected 断开；
腾讯与东财的搜索接口正常。本脚本把候选源逐个试一遍，输出可用的主/备源，
供 stock/datasource.py 固定使用。输出刻意只用 ASCII，避免控制台 GBK 编码炸掉。

用法：python tools/probe_sources.py
"""
import json
import sys
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

SOURCES = [
    ("tencent_quote",  "https://qt.gtimg.cn/q=sh600519",
     {"Referer": "https://finance.qq.com/"}),
    ("tencent_kline",  "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
                       "?param=sh600519,day,,,320,qfq",
     {"Referer": "https://finance.qq.com/"}),
    ("sina_quote",     "https://hq.sinajs.cn/list=sh600519",
     {"Referer": "https://finance.sina.com.cn/"}),
    ("netease_hist",   "https://quotes.money.163.com/service/chddata.html"
                       "?code=0600519&start=20250101&end=20261017"
                       "&fields=TCLOSE;HIGH;LOW;TOPEN;VOTURNOVER",
     {}),
    ("em_quote",       "https://push2.eastmoney.com/api/qt/stock/get"
                       "?secid=1.600519&fields=f43,f57,f58,f169,f170", {}),
    ("em_kline",       "https://push2his.eastmoney.com/api/qt/stock/kline/get"
                       "?secid=1.600519&klt=101&fqt=1&beg=20250101&end=20500101"
                       "&fields1=f1,f2,f3&fields2=f51,f52,f53,f54,f55,f56,f57,f58", {}),
    ("em_search",      "https://searchapi.eastmoney.com/api/suggest/get"
                       "?input=%E8%8C%85%E5%8F%B0&type=14"
                       "&token=D43BF722C8E33BDC906FB84D85E326E8&count=5", {}),
]


def ascii_preview(raw, n=70):
    text = raw[:n].decode("utf-8", "replace")
    return text.encode("ascii", "backslashreplace").decode("ascii")


def probe(url, headers):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **headers})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return "OK", r.read()
    except urllib.error.HTTPError as e:
        return "HTTP %s" % e.code, b""
    except Exception as e:  # noqa: BLE001 - 诊断工具，记录全部异常
        return "FAIL %s" % type(e).__name__, b""


def main():
    report = {}
    for name, url, headers in SOURCES:
        status, raw = probe(url, headers)
        report[name] = {"url": url, "status": status, "bytes": len(raw),
                        "preview": ascii_preview(raw)}
        print("%-14s %-26s %7d  %s" % (name, status, len(raw), ascii_preview(raw, 50)))
    with open("tools/probe_report.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write("\n")
    ok = [k for k, v in report.items() if v["status"] == "OK"]
    print("\nWORKING:", ", ".join(ok) or "(none)")


if __name__ == "__main__":
    main()
