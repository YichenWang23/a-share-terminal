# -*- coding: utf-8 -*-
"""缓存 TTL 测试：新鲜缓存优先、过期失效、来源被记录。"""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stock.datasource import Cache  # noqa: E402


class TestCacheTTL(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="stock-cache-")
        self.cache = Cache(self.dir)

    def test_long_key_stays_within_windows_path_limit(self):
        # 回归测试：自选股变多后，把全部代码拼进缓存文件名会超过 Windows 260 字符上限，
        # open() 直接 OSError(22)，接口 500。文件名必须被压短且仍能读回。
        key = "quotes_" + "_".join("%06d" % i for i in range(80))
        self.cache.put(key, {"ok": True}, source="tencent")
        self.assertEqual(self.cache.get(key)["payload"], {"ok": True})
        name = os.path.basename(self.cache._path(key))
        self.assertLess(len(name), 80, "缓存文件名太长：%s" % name)

    def test_different_keys_do_not_collide_after_hashing(self):
        a = "quotes_" + "0" * 100
        b = "quotes_" + "0" * 99 + "1"
        self.cache.put(a, {"v": "a"})
        self.cache.put(b, {"v": "b"})
        self.assertEqual(self.cache.get(a)["payload"]["v"], "a")
        self.assertEqual(self.cache.get(b)["payload"]["v"], "b")
    def test_put_then_get_is_fresh(self):
        self.cache.put("quotes_600519", [{"code": "600519", "price": 1.0}], source="tencent")
        item, age = self.cache.get_fresh("quotes_600519", 60)
        self.assertIsNotNone(item)
        self.assertEqual(item["payload"][0]["code"], "600519")
        self.assertEqual(item["source"], "tencent")
        self.assertLess(age, 5)

    def test_expired_entry_is_not_fresh(self):
        self.cache.put("k", [1], source="tencent")
        path = self.cache._path("k")
        with open(path, "r", encoding="utf-8") as f:
            item = json.load(f)
        item["ts"] = time.time() - 100
        with open(path, "w", encoding="utf-8") as f:
            json.dump(item, f)
        fresh, age = self.cache.get_fresh("k", 3)
        self.assertIsNone(fresh)
        self.assertIsNone(age)

    def test_missing_key_is_not_fresh(self):
        self.assertEqual(self.cache.get_fresh("nope", 10), (None, None))

    def test_missing_ts_never_fresh(self):
        self.cache.put("k", [1], source="tencent")
        path = self.cache._path("k")
        with open(path, "r", encoding="utf-8") as f:
            item = json.load(f)
        item.pop("ts", None)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(item, f)
        self.assertEqual(self.cache.get_fresh("k", 3600), (None, None))


if __name__ == "__main__":
    unittest.main()
