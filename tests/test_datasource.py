# -*- coding: utf-8 -*-
"""数据源解析测试：用 fixtures 里的真实响应离线断言字段映射。"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from stock.datasource import (parse_sina_kline,   # noqa: E402
    parse_em_search, parse_sina_quotes, parse_tencent_kline, parse_tencent_minute,
    parse_tencent_quotes,
)

FIX = os.path.join(ROOT, "fixtures")


def raw(name):
    with open(os.path.join(FIX, name), "rb") as f:
        return f.read()


class TestTencentQuote(unittest.TestCase):
    def setUp(self):
        self.rows = parse_tencent_quotes(raw("tencent_quote_sh600519.txt"))
        self.by_code = {r["code"]: r for r in self.rows}

    def test_parses_all_requested_symbols(self):
        self.assertEqual(len(self.rows), 4)
        self.assertEqual(set(self.by_code), {"600519", "000001", "300750", "510300"})

    def test_maotai_fields(self):
        q = self.by_code["600519"]
        self.assertEqual(q["name"], "贵州茅台")
        self.assertAlmostEqual(q["price"], 1329.00, places=2)
        self.assertAlmostEqual(q["prev_close"], 1312.97, places=2)
        self.assertAlmostEqual(q["open"], 1311.57, places=2)
        self.assertAlmostEqual(q["high"], 1329.88, places=2)
        self.assertAlmostEqual(q["low"], 1301.68, places=2)
        self.assertAlmostEqual(q["change"], 16.03, places=2)
        self.assertAlmostEqual(q["change_pct"], 1.22, places=2)
        self.assertAlmostEqual(q["limit_up"], 1444.27, places=2)
        self.assertAlmostEqual(q["limit_down"], 1181.67, places=2)
        self.assertEqual(q["timestamp"], "2026-10-16 16:14:47")
        self.assertEqual(q["source"], "tencent")

    def test_market_prefixes(self):
        self.assertEqual(self.by_code["600519"]["symbol"], "sh600519")
        self.assertEqual(self.by_code["000001"]["symbol"], "sz000001")
        self.assertEqual(self.by_code["300750"]["symbol"], "sz300750")
        self.assertEqual(self.by_code["510300"]["symbol"], "sh510300")

    def test_bad_payload_returns_empty(self):
        self.assertEqual(parse_tencent_quotes(b"not a quote"), [])
        self.assertEqual(parse_tencent_quotes(b'v_pv_none="";'), [])


class TestTencentKline(unittest.TestCase):
    def setUp(self):
        self.bars = parse_tencent_kline(raw("tencent_kline_sh600519_day.json"))

    def test_bar_count_and_bounds(self):
        self.assertEqual(len(self.bars), 320)
        self.assertEqual(self.bars[0]["date"], "2025-06-23")
        self.assertEqual(self.bars[-1]["date"], "2026-10-16")

    def test_last_bar_values(self):
        last = self.bars[-1]
        self.assertAlmostEqual(last["open"], 1311.57, places=2)
        self.assertAlmostEqual(last["close"], 1329.00, places=2)
        self.assertAlmostEqual(last["high"], 1329.88, places=2)
        self.assertAlmostEqual(last["low"], 1301.68, places=2)
        self.assertAlmostEqual(last["volume"], 38502.0, places=2)

    def test_ohlc_consistency_holds(self):
        for b in self.bars:
            self.assertGreaterEqual(b["high"], max(b["open"], b["close"]))
            self.assertLessEqual(b["low"], min(b["open"], b["close"]))

    def test_bad_payload_returns_empty(self):
        self.assertEqual(parse_tencent_kline(b"{}"), [])
        self.assertEqual(parse_tencent_kline(b'{"data":{}}'), [])


class TestSinaQuote(unittest.TestCase):
    def setUp(self):
        self.rows = parse_sina_quotes(raw("sina_quote_sh600519.txt"))

    def test_parses_two_symbols(self):
        self.assertEqual(len(self.rows), 2)
        q = {r["code"]: r for r in self.rows}["600519"]
        self.assertEqual(q["name"], "贵州茅台")
        self.assertAlmostEqual(q["price"], 1329.0, places=2)
        self.assertAlmostEqual(q["prev_close"], 1312.97, places=2)
        self.assertEqual(q["date"], "2026-10-16")
        self.assertEqual(q["source"], "sina")

    def test_empty_payload(self):
        self.assertEqual(parse_sina_quotes(b'var hq_str_sh600519="";'), [])


class TestTencentMinute(unittest.TestCase):
    def setUp(self):
        self.d = parse_tencent_minute(raw("tencent_minute_sh600519.json"))

    def test_date_and_bounds(self):
        self.assertEqual(self.d["date"], "2026-10-16")
        self.assertGreater(len(self.d["points"]), 200)
        self.assertEqual(self.d["points"][0]["time"], "09:30")

    def test_last_point_matches_close(self):
        last = self.d["points"][-1]
        self.assertAlmostEqual(last["price"], 1329.0, places=2)
        self.assertGreater(last["cum_volume"], 30000)

    def test_average_price_formula(self):
        # 从 fixture 原始行独立复算：均价 = 累计成交额 / (累计量 × 100)
        import json as _json
        raw_rows = _json.loads(raw("tencent_minute_sh600519.json").decode("utf-8"))
        node = raw_rows["data"]["sh600519"]["data"]["data"]
        parts = node[-1].split()
        cum_vol, cum_amt = float(parts[2]), float(parts[3])
        expected = round(cum_amt / (cum_vol * 100.0), 3)
        self.assertAlmostEqual(self.d["points"][-1]["avg_price"], expected, places=2)

    def test_volumes_sum_to_cumulative(self):
        total = sum(p["volume"] for p in self.d["points"])
        self.assertAlmostEqual(total, self.d["points"][-1]["cum_volume"], places=0)

    def test_garbage_input(self):
        self.assertEqual(parse_tencent_minute(b"not json")["points"], [])


class TestEastmoneySearch(unittest.TestCase):
    def test_finds_maotai(self):
        rows = parse_em_search(raw("em_search_maotai.json"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["code"], "600519")
        self.assertEqual(rows[0]["name"], "贵州茅台")
        self.assertEqual(rows[0]["symbol"], "sh600519")

    def test_garbage_returns_empty(self):
        self.assertEqual(parse_em_search(b"not json"), [])



class TestSinaKline(unittest.TestCase):
    def test_parse_sina_kline(self):
        raw = ('[{"day":"2026-10-15","open":"10.0","high":"10.8","low":"9.9",'
               '"close":"10.5","volume":"12000"},'
               '{"day":"2026-10-16","open":"10.5","high":"11.2","low":"10.4",'
               '"close":"11.0","volume":"9000"}]').encode()
        bars = parse_sina_kline(raw)
        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[0]["date"], "2026-10-15")
        self.assertAlmostEqual(bars[1]["close"], 11.0)
        self.assertAlmostEqual(bars[1]["volume"], 9000.0)
        self.assertEqual(parse_sina_kline(b"not json"), [])

if __name__ == "__main__":
    unittest.main()
