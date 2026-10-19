# -*- coding: utf-8 -*-
"""断网首启契约：零缓存 + 无网络时，全部自选股都能出样本数据。

对应 spec 的失败模式：「无网络首次启动 → 用 fixtures 样本进入演示模式」。
之前只录了 600519 一只，导致断网时 21/22 只显示「拿不到」——这里把它钉住。
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stock import datasource, storage  # noqa: E402
from stock.datasource import Cache  # noqa: E402


def empty_cache():
    return Cache(tempfile.mkdtemp(prefix="stock-offline-"))


class TestOfflineFixtures(unittest.TestCase):
    def setUp(self):
        self.codes = list(storage.DEFAULT_WATCHLIST)

    def test_every_watchlist_stock_has_quote_fixture(self):
        res = datasource.get_quotes(self.codes, cache=empty_cache(), allow_network=False)
        got = {q["code"] for q in res["quotes"]}
        missing = [c for c in self.codes if c not in got]
        self.assertEqual(missing, [], "断网时这些票没有行情样本：%s" % missing)
        self.assertEqual(res["meta"]["source"], "fixture")
        self.assertTrue(res["meta"]["demo"], "样本数据必须标成演示模式")

    def test_every_watchlist_stock_has_kline_fixture(self):
        missing = []
        for code in self.codes:
            res = datasource.get_kline(code, limit=120, cache=empty_cache(),
                                       allow_network=False)
            if not res["bars"]:
                missing.append(code)
                continue
            self.assertTrue(res["meta"]["demo"], "%s 的样本没标 demo" % code)
        self.assertEqual(missing, [], "断网时这些票没有 K 线样本：%s" % missing)

    def test_offline_quotes_are_real_prices(self):
        res = datasource.get_quotes(["600519", "002624"], cache=empty_cache(),
                                    allow_network=False)
        prices = {q["code"]: q["price"] for q in res["quotes"]}
        self.assertEqual(set(prices), {"600519", "002624"})
        for code, price in prices.items():
            self.assertGreater(price, 0, "%s 的样本价格不合法" % code)


if __name__ == "__main__":
    unittest.main()


class TestKlineLimit(unittest.TestCase):
    def test_kline_returns_exact_limit(self):
        # 腾讯接口会多给一根（含今天这根未收盘的），接口必须按请求根数截断
        for limit in (5, 50, 120):
            res = datasource.get_kline("600519", limit=limit, allow_network=False)
            self.assertEqual(len(res["bars"]), limit, "limit=%d 应返回 %d 根" % (limit, limit))


if __name__ == "__main__":
    unittest.main()
