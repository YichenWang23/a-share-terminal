# -*- coding: utf-8 -*-
"""Linux 兼容性：把 ctypes.windll 拿掉、平台改成 linux，确认服务端能导入并降级。"""
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CODE = """
import ctypes
import sys

# 模拟 Linux：没有 windll，platform 也不是 win
if hasattr(ctypes, 'windll'):
    del ctypes.windll
sys.platform = 'linux'

from stock import secrets
assert secrets.available() is False, 'Linux 下 DPAPI 必须不可用'
assert secrets.encrypt('sk-abc') == ('sk-abc', 'plain'), '应降级成明文模式'
assert secrets.decrypt('sk-abc', 'plain') == 'sk-abc'

# 服务端模块要能完整导入（这才是云服务器上真正会发生的）
import server  # noqa: F401
assert callable(server.lan_addresses)

# 账号/好友模块已移除，这里只确认核心模块可用
from stock import portfolio, rules, storage
assert hasattr(portfolio, 'Portfolio')
assert hasattr(rules, 'price_limits')
assert hasattr(storage, 'DEFAULT_WATCHLIST')
print('linux-compat-ok')
"""


class TestLinuxCompat(unittest.TestCase):
    def test_runs_without_windows_apis(self):
        proc = subprocess.run(
            [sys.executable, "-c", CODE],
            cwd=str(ROOT), capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertIn("linux-compat-ok", proc.stdout)


if __name__ == "__main__":
    unittest.main()
