# -*- coding: utf-8 -*-
"""一键自检：单元测试 + 关键数字独立重算 +（服务在跑时）接口冒烟。

用法：
    python tools/selfcheck.py

返回码：0 = 全过；1 = 有失败。
"""
import os
import shutil
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


def run(name, args, need_server=False):
    print("=" * 64)
    print("[%s] %s" % (name, " ".join(args)))
    started = time.time()
    proc = subprocess.run(args, cwd=BASE, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    elapsed = time.time() - started
    tail = (proc.stdout or "").strip().splitlines()[-3:]
    for line in tail:
        print("   " + line)
    if proc.returncode != 0 and (proc.stderr or "").strip():
        print("   stderr: " + proc.stderr.strip().splitlines()[-1])
    print("   -> exit=%d  %.1fs" % (proc.returncode, elapsed))
    return proc.returncode


def server_up(port=8770):
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/api/health" % port, timeout=3) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def main():
    codes = []
    codes.append(run("单元测试", [PY, "-m", "unittest", "discover", "-s", "tests"]))
    codes.append(run("关键数字独立重算", [PY, "tools/verify_numbers.py"]))
    node = shutil.which("node")
    if node:
        codes.append(run("前端图表更新逻辑", [node, "--test", "tests/test_frontend_logic.mjs"]))
    else:
        print("=" * 64)
        print("[前端图表更新逻辑] 跳过：没找到 node")
    if server_up():
        codes.append(run("接口冒烟", [PY, "tools/smoke_api.py"]))
    else:
        print("=" * 64)
        print("[接口冒烟] 跳过：127.0.0.1:8770 没有服务在跑（先 python server.py）")
    failed = [c for c in codes if c != 0]
    print("=" * 64)
    print("SELFCHECK %s（%d 项，失败 %d）"
          % ("PASS" if not failed else "FAIL", len(codes), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
