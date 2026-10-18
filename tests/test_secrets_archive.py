# -*- coding: utf-8 -*-
"""API key 加密与成交归档测试。"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stock import secrets, storage  # noqa: E402


class TestSecrets(unittest.TestCase):
    def test_empty_key_stays_empty(self):
        self.assertEqual(secrets.encrypt(""), ("", "empty"))
        self.assertEqual(secrets.decrypt("", "empty"), "")

    def test_roundtrip_or_skip(self):
        if not secrets.available():
            self.skipTest("本机没有 DPAPI，跳过加密往返测试")
        token, mode = secrets.encrypt("sk-abc-123456")
        self.assertEqual(mode, "dpapi")
        self.assertNotIn("sk-abc-123456", token)
        self.assertEqual(secrets.decrypt(token, mode), "sk-abc-123456")

    def test_set_key_clears_plaintext(self):
        cfg = {"api_key": "sk-plain"}
        secrets.set_key(cfg, "sk-xyz-789")
        self.assertEqual(cfg["api_key"], "", "明文必须被清掉")
        self.assertTrue(cfg["api_key_enc"])
        self.assertEqual(secrets.get_key(cfg), "sk-xyz-789")

    def test_get_key_handles_legacy_plain(self):
        self.assertEqual(secrets.get_key({"api_key": "sk-legacy"}), "sk-legacy")


class TestTradeArchive(unittest.TestCase):
    def test_overflow_is_archived(self):
        tmp = tempfile.mkdtemp(prefix="stock-arch-")
        trades = [{"i": i} for i in range(520)]
        kept, archived = storage.archive_trades(trades, keep=500, arch_dir=tmp)
        self.assertEqual(archived, 20)
        self.assertEqual(len(kept), 500)
        files = [f for f in os.listdir(tmp) if f.endswith(".json")]
        self.assertEqual(len(files), 1)
        with open(os.path.join(tmp, files[0]), "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(len(data), 20)
        self.assertEqual(data[0]["i"], 0)
        self.assertEqual(kept[0]["i"], 20)

    def test_under_limit_untouched(self):
        kept, archived = storage.archive_trades([{"i": 1}], keep=500,
                                                arch_dir=tempfile.mkdtemp())
        self.assertEqual((len(kept), archived), (1, 0))

    def test_second_archive_appends(self):
        tmp = tempfile.mkdtemp(prefix="stock-arch2-")
        storage.archive_trades([{"i": i} for i in range(510)], keep=500, arch_dir=tmp)
        storage.archive_trades([{"i": i} for i in range(520)], keep=500, arch_dir=tmp)  # 再溢出 20 条
        files = [f for f in os.listdir(tmp) if f.endswith(".json")]
        with open(os.path.join(tmp, files[0]), "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(len(data), 30)


if __name__ == "__main__":
    unittest.main()
