# -*- coding: utf-8 -*-
"""生成离线演示快照 static/demo.html（数据来自正在运行的服务，真实响应内联）。

用途：
  * 无网络/不想起服务时也能看到完整界面（只读，不能下单）；
  * 做视觉验收与截图。

用法（服务需先启动）：
    python tools/make_demo.py [--base http://127.0.0.1:8770]
"""
import argparse
import json
import os
import sys
import time
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(BASE_DIR, "static")
INDEX = os.path.join(STATIC, "index.html")
DEMO = os.path.join(STATIC, "demo.html")

ENDPOINTS = [
    "/api/state",
    "/api/kline?code={code}&limit=320",
    "/api/minute?code={code}",
    "/api/analysis?code={code}",
    "/api/portfolio",
    "/api/account",
    "/api/backtest?code=000001&short=5&long=20&cash=100000",
]


def get(base, path):
    with urllib.request.urlopen(base + path, timeout=40) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8770")
    ap.add_argument("--code", default="600519", help="要内联详情的股票代码")
    args = ap.parse_args()
    base = args.base.rstrip("/")

    data = {}
    code = args.code
    for path in ENDPOINTS:
        path = path.replace("{code}", code)
        try:
            data[path] = get(base, path)
            print("OK   %s" % path)
        except Exception as exc:  # noqa: BLE001 - 演示快照允许个别接口缺失
            data[path] = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
            print("SKIP %s (%s)" % (path, exc))

    payload = json.dumps(data, ensure_ascii=False)
    with open(INDEX, "r", encoding="utf-8") as f:
        html = f.read()

    banner = (
        '<div style="background:#3a2f13;border:1px solid #6b541f;color:#f0d17e;'
        'padding:8px 14px;border-radius:8px;margin:10px 20px 0;font-size:12px;">'
        '演示快照：数据是本次录制下来的真实响应（%s），不是实时行情；'
        '本页为只读，下单/保存不可用。要真用请双击「启动.cmd」。</div>'
        % time.strftime("%Y-%m-%d %H:%M:%S")
    )
    injected = ("<script>window.__DEMO__ = " + payload + ";</script>\n"
                "<script src=\"app.js\"></script>")
    if '<script src="app.js"></script>' not in html:
        raise SystemExit("index.html 里找不到 app.js 引用，无法注入")
    html = html.replace('<script src="app.js"></script>', injected)
    html = html.replace("<body>", "<body>\n" + banner, 1)
    with open(DEMO, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)
    print("\nwrote %s (%d bytes, %d endpoints inlined)"
          % (DEMO, os.path.getsize(DEMO), len([k for k, v in data.items() if v.get("ok")])))


if __name__ == "__main__":
    main()
