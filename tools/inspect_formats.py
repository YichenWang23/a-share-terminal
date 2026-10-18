# -*- coding: utf-8 -*-
"""打印真实响应里的字段位置，供解析代码照着写（一次性诊断工具）。

用法：python tools/inspect_formats.py
"""
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(BASE, "fixtures")


def show_tencent_quote():
    raw = open(os.path.join(FIX, "tencent_quote_sh600519.txt"), "rb").read()
    text = raw.decode("gbk", "replace")
    print("=== tencent quote fields (GBK) ===")
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("v_"):
            continue
        code = line.split("=", 1)[0][2:]
        payload = line.split('"', 2)[1]
        parts = payload.split("~")
        print("\n-- %s (%d fields) --" % (code, len(parts)))
        for i, p in enumerate(parts):
            print("  [%2d] %s" % (i, p))


def show_tencent_kline():
    raw = open(os.path.join(FIX, "tencent_kline_sh600519_day.json"), "rb").read()
    data = json.loads(raw.decode("utf-8"))
    node = data["data"]["sh600519"]
    print("\n=== tencent kline keys ===")
    for k, v in node.items():
        if isinstance(v, list):
            print("  %-10s list[%d]  first=%s  last=%s" % (k, len(v), v[0], v[-1]))
        else:
            print("  %-10s %r" % (k, v))


def show_sina_quote():
    raw = open(os.path.join(FIX, "sina_quote_sh600519.txt"), "rb").read()
    text = raw.decode("gbk", "replace")
    print("\n=== sina quote fields (GBK) ===")
    for line in text.splitlines():
        if "=" not in line:
            continue
        code = line.split("=", 1)[0].replace("var hq_str_", "").strip()
        payload = line.split('"', 2)[1] if '"' in line else ""
        parts = payload.split(",")
        print("\n-- %s (%d fields) --" % (code, len(parts)))
        for i, p in enumerate(parts):
            print("  [%2d] %s" % (i, p))


def show_em_search():
    raw = open(os.path.join(FIX, "em_search_maotai.json"), "rb").read()
    data = json.loads(raw.decode("utf-8"))
    rows = data.get("QuotationCodeTable", {}).get("Data") or []
    print("\n=== em search rows=%d ===" % len(rows))
    if rows:
        for k, v in rows[0].items():
            print("  %-18s %r" % (k, v))


if __name__ == "__main__":
    show_tencent_quote()
    show_tencent_kline()
    show_sina_quote()
    show_em_search()
