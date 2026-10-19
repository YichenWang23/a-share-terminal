# -*- coding: utf-8 -*-
"""服务端测试：真起一个 HTTP 服务（离线模式），打真实请求验证行为。

隔离措施：把 datasource.CACHE_DIR 与 storage.STATE_PATH 指到临时目录，
不会碰用户的 data/state.json 与真实缓存。
"""
import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

# 必须在导入 server 之前设置：让 datasource 走 fixtures（演示）而不是真网络
os.environ["STOCK_OFFLINE"] = "1"

import server  # noqa: E402
from stock import datasource, storage  # noqa: E402


class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="stock-server-")
        cls._old_state = storage.STATE_PATH
        cls._old_cache = datasource.CACHE_DIR
        storage.STATE_PATH = os.path.join(cls.tmp, "state.json")
        datasource.CACHE_DIR = os.path.join(cls.tmp, "cache")

        class QuietHandler(server.Handler):
            def log_message(self, fmt, *args):
                pass

        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        storage.STATE_PATH = cls._old_state
        datasource.CACHE_DIR = cls._old_cache
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        # 每个用例都从干净状态开始，避免测试之间互相污染
        # 钱包默认是 0；钱包相关的用例需要一个非零基数，这里统一给 15 万
        import copy
        st = copy.deepcopy(storage.DEFAULT_STATE)
        # 用 default_account 建（自带开户流水），否则 _migrate_account 会重建账户、把钱包冲回 0
        from stock import account as account_mod
        st["account"] = account_mod.default_account(350_000.0, wallet=150_000.0)
        storage.save(st)

    def request(self, method, path, body=None, raw=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        headers = {}
        data = None
        if raw is not None:
            data = raw
            headers["Content-Type"] = "application/json"
        elif body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=data, headers=headers)
        resp = conn.getresponse()
        payload = resp.read()
        status = resp.status
        conn.close()
        return status, payload

    def as_json(self, payload):
        return json.loads(payload.decode("utf-8"))

    # ---------- 基础 ----------
    def test_health(self):
        status, payload = self.request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(self.as_json(payload)["ok"])

    def test_static_index(self):
        status, payload = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"<!DOCTYPE html>", payload)

    def test_static_assets(self):
        for path, marker in (("/app.js", b"function"), ("/style.css", b"--bg")):
            status, payload = self.request("GET", path)
            self.assertEqual(status, 200, path)
            self.assertIn(marker, payload, path)

    # ---------- 安全 ----------
    def test_path_traversal_is_blocked(self):
        for path in ("/../server.py", "/..%2fserver.py", "/../AGENTS.md",
                     "/%2e%2e/server.py"):
            status, payload = self.request("GET", path)
            self.assertEqual(status, 404, path)

    def test_unknown_api_is_404(self):
        status, _ = self.request("GET", "/api/nope")
        self.assertEqual(status, 404)

    def test_bad_json_is_400(self):
        status, payload = self.request("POST", "/api/order", raw=b"{not json")
        self.assertEqual(status, 400)
        self.assertIn("JSON", self.as_json(payload)["error"])

    # ---------- 业务 ----------
    def test_demo_mode_blocks_orders(self):
        status, payload = self.request("POST", "/api/order",
                                       {"code": "600519", "side": "buy", "shares": 100})
        body = self.as_json(payload)
        self.assertEqual(status, 409)
        self.assertEqual(body["reason"], "DEMO_MODE")

    def test_unknown_order_side_rejected(self):
        status, payload = self.request("POST", "/api/order",
                                       {"code": "600519", "side": "hold", "shares": 100})
        self.assertEqual(status, 400, payload)

    def test_state_has_watchlist_even_offline(self):
        status, payload = self.request("GET", "/api/state")
        body = self.as_json(payload)
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(len(body["watchlist"]), len(storage.DEFAULT_STATE["watchlist"]))
        self.assertTrue(body["meta"]["demo"], "离线时应标 demo=true，不能冒充实时")

    # ---------- 参数校验：坏参数必须 400，不能 500 ----------
    def test_non_object_json_body_rejected(self):
        for raw in (b"[]", b'"x"', b"null", b"123"):
            status, payload = self.request("POST", "/api/order", raw=raw)
            self.assertEqual(status, 400, "%r 应为 400：%s" % (raw, payload))

    def test_oversized_body_rejected(self):
        big = json.dumps({"code": "600519", "side": "buy", "shares": 100,
                          "pad": "x" * 300_000}).encode()
        status, payload = self.request("POST", "/api/order", raw=big)
        self.assertEqual(status, 413, payload)

    def test_order_rejects_bad_code(self):
        status, payload = self.request("POST", "/api/order",
                                       {"code": "abc", "side": "buy", "shares": 100})
        self.assertEqual(status, 400, payload)

    def test_kline_rejects_bad_limit(self):
        for q in ("limit=0", "limit=-5", "limit=abc", "limit=100000"):
            status, payload = self.request("GET", "/api/kline?code=600519&" + q)
            self.assertEqual(status, 400, "%s 应为 400：%s" % (q, payload))

    def test_backtest_rejects_bad_params(self):
        for q in ("cash=nan", "cash=-1", "short=0&long=20", "short=20&long=5",
                  "slippage=-5", "fqt=xx"):
            status, payload = self.request("GET", "/api/backtest?code=600519&" + q)
            self.assertEqual(status, 400, "%s 应为 400：%s" % (q, payload))

    def test_rejects_bad_code_format(self):
        for path in ("/api/kline?code=abc", "/api/backtest?code=abc",
                     "/api/analysis?code=abc", "/api/minute?code=abc"):
            status, payload = self.request("GET", path)
            self.assertEqual(status, 400, "%s 应为 400：%s" % (path, payload))

    def test_flow_rejects_absurd_amount(self):
        status, payload = self.request("POST", "/api/account/flow",
                                       {"type": "deposit", "amount": 1e300})
        self.assertEqual(status, 400, payload)
    # ---------- 重置 ----------
    def test_reset_restores_all_data(self):
        """重置 = 所有数据回到初始：持仓/成交/流水/曲线/预警/自选/钱包。"""
        from stock import account as account_mod
        from stock.portfolio import Portfolio
        pf = Portfolio(cash=100000.0, day="2026-10-17")
        pf.buy("000001", price=11.5, shares=100, name="平安银行", prev_close=11.5)
        st = storage.load()
        st["portfolio"] = pf.to_dict()
        st["account"] = account_mod.default_account(200000.0, wallet=140000.0)
        st["alerts"] = [{"id": 1, "code": "600519", "op": "above", "price": 2000}]
        st["watchlist"] = ["600519"]
        storage.save(st)

        dirty = self.as_json(self.request("GET", "/api/account")[1])
        self.assertTrue(dirty["allocation"]["items"], "先得真的有持仓")
        self.assertEqual(dirty["summary"]["wallet"], 140000.0)

        status, payload = self.request("POST", "/api/portfolio/reset", {})
        self.assertEqual(status, 200, payload)

        acc = self.as_json(self.request("GET", "/api/account")[1])
        self.assertEqual(acc["summary"]["wallet"], 0.0, "钱包必须回到 0")
        self.assertEqual(acc["summary"]["cash"], 350000.0, "证券现金必须回到 35 万")
        self.assertEqual(acc["allocation"]["items"], [], "持仓必须清空")
        self.assertEqual(len(acc["flows"]), 1, "流水只留开户那一条")

        state = self.as_json(self.request("GET", "/api/state")[1])
        self.assertEqual(len(state["watchlist"]), len(storage.DEFAULT_WATCHLIST),
                         "自选必须恢复默认")
        self.assertEqual(state.get("alerts") or [], [], "预警必须清空")

        port = self.as_json(self.request("GET", "/api/portfolio")[1])
        self.assertEqual(port.get("trades") or [], [], "成交记录必须清空")

    # ---------- 钱包 ----------
    def test_wallet_in_account_summary(self):
        status, payload = self.request("GET", "/api/account")
        body = self.as_json(payload)
        self.assertEqual(status, 200)
        self.assertEqual(body["summary"]["wallet"], 150000.0)
        self.assertAlmostEqual(body["summary"]["net_worth"],
                               body["summary"]["total"] + 150000.0, places=2)

    def test_deposit_moves_money_out_of_wallet(self):
        status, payload = self.request("POST", "/api/account/flow",
                                       {"type": "deposit", "amount": 100000, "note": "测试"})
        body = self.as_json(payload)
        self.assertEqual(status, 200, payload)
        self.assertEqual(body["summary"]["wallet"], 50000.0)
        # 入金不虚增收益
        self.assertEqual(body["summary"]["total_return_pct"], 0.0)

    def test_deposit_beyond_wallet_rejected(self):
        status, payload = self.request("POST", "/api/account/flow",
                                       {"type": "deposit", "amount": 999999})
        self.assertEqual(status, 400, payload)
        self.assertIn("钱包余额", self.as_json(payload)["error"])

    def test_withdraw_puts_money_back_into_wallet(self):
        self.request("POST", "/api/account/flow",
                     {"type": "deposit", "amount": 10000})
        status, payload = self.request("POST", "/api/account/flow",
                                       {"type": "withdraw", "amount": 4000})
        body = self.as_json(payload)
        self.assertEqual(status, 200, payload)
        self.assertEqual(body["summary"]["wallet"], 144000.0)

    def test_nan_and_inf_amounts_rejected(self):
        for bad in ("nan", "inf", "1e309"):
            status, payload = self.request("POST", "/api/account/flow",
                                           {"type": "deposit", "amount": bad})
            self.assertEqual(status, 400, "金额 %r 应被拒：%s" % (bad, payload))
        status, payload = self.request("GET", "/api/account")
        cash = self.as_json(payload)["summary"]["cash"]
        self.assertEqual(cash, cash, "现金不能变成 NaN")

    # ---------- 诊断 ----------
    def test_diag_returns_structured_checks(self):
        status, payload = self.request("GET", "/api/diag")
        body = self.as_json(payload)
        self.assertEqual(status, 200)
        names = [c["name"] for c in body.get("checks", [])]
        self.assertEqual(names, ["行情", "日K", "搜索", "分时"])
        for check in body["checks"]:
            self.assertIn("ok", check)
            self.assertIn("ms", check)
        self.assertIn("cache_files", body)
        self.assertIn("python", body)

    # ---------- 设置与密钥 ----------
    def test_api_key_is_never_returned_plain(self):
        secret = "sk-test-1234567890abcdef"
        status, payload = self.request("POST", "/api/settings",
                                       {"llm": {"enabled": True, "api_key": secret,
                                                "model": "deepseek-chat"}})
        self.assertEqual(status, 200, payload)
        status, payload = self.request("GET", "/api/settings")
        body = self.as_json(payload)
        self.assertEqual(status, 200)
        self.assertNotIn(secret.encode(), payload, "接口绝不能回显明文 key")
        self.assertTrue(body["llm"]["has_key"])
        self.assertIn("****", body["llm"]["api_key_masked"])
        # 清掉，避免影响后续测试
        self.request("POST", "/api/settings", {"llm": {"clear_key": True}})

    def test_concurrent_writes_do_not_error(self):
        errors = []

        def worker(i):
            status, _ = self.request("POST", "/api/settings",
                                     {"llm": {"model": "m-%d" % i}})
            if status != 200:
                errors.append(status)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
