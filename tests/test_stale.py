# -*- coding: utf-8 -*-
"""降级链路测试：网络失败时走缓存，并标注 stale=True（不是 demo）。

对应验收标准 3：「无网络时自动回落到缓存并标注 stale=true」。
之前只测过 demo（fixtures）分支，缓存降级这一半没有证据——这里补上。
"""
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stock import datasource  # noqa: E402
from stock.datasource import Cache  # noqa: E402


def age_cache(cache, key, seconds=9999):
    """把缓存的时间戳改老，模拟「缓存已过期」。"""
    path = cache._path(key)
    with open(path, "r", encoding="utf-8") as f:
        item = json.load(f)
    item["ts"] = time.time() - seconds
    with open(path, "w", encoding="utf-8") as f:
        json.dump(item, f, ensure_ascii=False)


class TestStaleFallback(unittest.TestCase):
    def setUp(self):
        self.cache = Cache(tempfile.mkdtemp(prefix="stock-stale-"))
        # test_server 在导入时把 STOCK_OFFLINE 设成了全局，这里显式声明「在线」，
        # 才能走到「网络失败 → 缓存降级」这条路
        self.online = mock.patch.object(datasource, "_online", return_value=True)
        self.online.start()
        self.addCleanup(self.online.stop)

    def test_quotes_fall_back_to_cache_and_mark_stale(self):
        key = "quotes_600519"
        self.cache.put(key, [{"code": "600519", "name": "贵州茅台", "price": 1329.0}],
                       source="tencent")
        age_cache(self.cache, key)
        with mock.patch.object(datasource, "http_get",
                               side_effect=datasource.FetchError("network down")):
            res = datasource.get_quotes(["600519"], cache=self.cache, allow_network=True)
        self.assertEqual(res["meta"]["source"], "cache", res["meta"])
        self.assertTrue(res["meta"]["stale"], "缓存降级必须标 stale=True")
        self.assertFalse(res["meta"]["demo"], "缓存是真实数据，不能标成演示样本")
        self.assertEqual(res["quotes"][0]["price"], 1329.0)
        self.assertTrue(any("down" in e for e in res["meta"]["errors"]),
                        "失败原因要留在 errors 里")

    def test_kline_falls_back_to_cache_and_mark_stale(self):
        key = "kline_600519_day_120_qfq"
        bars = [{"date": "2026-10-16", "open": 1.0, "high": 2.0, "low": 0.5,
                 "close": 1.5, "volume": 10.0}]
        self.cache.put(key, bars, source="tencent")
        age_cache(self.cache, key)
        with mock.patch.object(datasource, "http_get",
                               side_effect=datasource.FetchError("network down")):
            res = datasource.get_kline("600519", limit=120, cache=self.cache,
                                       allow_network=True)
        self.assertEqual(res["meta"]["source"], "cache", res["meta"])
        self.assertTrue(res["meta"]["stale"])
        self.assertFalse(res["meta"]["demo"])
        self.assertEqual(len(res["bars"]), 1)

    def test_fresh_cache_is_not_marked_stale(self):
        # 对照组：TTL 内的缓存直接命中，不该标 stale
        key = "quotes_600519"
        self.cache.put(key, [{"code": "600519", "name": "贵州茅台", "price": 1329.0}],
                       source="tencent")
        res = datasource.get_quotes(["600519"], cache=self.cache, allow_network=True)
        self.assertFalse(res["meta"]["stale"])
        self.assertEqual(res["meta"]["source"], "tencent")


if __name__ == "__main__":
    unittest.main()
