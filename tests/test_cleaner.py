# -*- coding: utf-8 -*-
"""数据清洗测试：重复日、OHLC 矛盾、异常收益、缺口、坏字段。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stock.cleaner import clean_bars  # noqa: E402


def bar(date, o, c, h, l, v=1000):
    return {"date": date, "open": o, "close": c, "high": h, "low": l, "volume": v}


def codes(result):
    return {i["code"] for i in result["issues"]}


class TestCleaner(unittest.TestCase):
    def test_clean_input_passes_without_issues(self):
        bars = [bar("2026-01-05", 10, 10.5, 10.6, 9.9),
                bar("2026-01-06", 10.5, 10.8, 11.0, 10.4)]
        r = clean_bars(bars)
        self.assertTrue(r["ok"])
        self.assertEqual(r["issues"], [])
        self.assertEqual(len(r["bars"]), 2)

    def test_duplicate_date_is_flagged_and_collapsed(self):
        bars = [bar("2026-01-05", 10, 10.5, 10.6, 9.9),
                bar("2026-01-05", 10, 10.7, 10.8, 9.9)]
        r = clean_bars(bars)
        self.assertIn("DUPLICATE_DATE", codes(r))
        self.assertEqual(len(r["bars"]), 1)

    def test_unsorted_dates_are_sorted(self):
        bars = [bar("2026-01-06", 10.5, 10.8, 11.0, 10.4),
                bar("2026-01-05", 10, 10.5, 10.6, 9.9)]
        r = clean_bars(bars)
        self.assertIn("UNSORTED", codes(r))
        self.assertEqual([b["date"] for b in r["bars"]], ["2026-01-05", "2026-01-06"])

    def test_ohlc_inconsistency_is_an_error_and_dropped(self):
        # high 10.0 < close 10.5 -> 矛盾
        bars = [bar("2026-01-05", 10, 10.5, 10.0, 9.9),
                bar("2026-01-06", 10.5, 10.8, 11.0, 10.4)]
        r = clean_bars(bars)
        self.assertFalse(r["ok"])
        self.assertIn("OHLC_INCONSISTENT", codes(r))
        self.assertEqual(len(r["bars"]), 1)

    def test_low_above_high_is_error(self):
        bars = [bar("2026-01-05", 10, 10.0, 10.5, 10.6)]
        r = clean_bars(bars)
        self.assertFalse(r["ok"])

    def test_non_positive_price_is_error(self):
        bars = [bar("2026-01-05", 10, 0, 10.5, 9.9)]
        r = clean_bars(bars)
        self.assertFalse(r["ok"])
        self.assertIn("BAD_PRICE", codes(r))

    def test_negative_volume_is_warning_not_error(self):
        bars = [bar("2026-01-05", 10, 10.5, 10.6, 9.9, v=-5)]
        r = clean_bars(bars)
        self.assertTrue(r["ok"])
        self.assertIn("BAD_VOLUME", codes(r))

    def test_extreme_daily_return_is_warning(self):
        bars = [bar("2026-01-05", 10, 10.0, 10.2, 9.9),
                bar("2026-01-06", 10.0, 20.0, 20.1, 9.9)]  # +100%
        r = clean_bars(bars)
        self.assertTrue(r["ok"])
        self.assertIn("EXTREME_RETURN", codes(r))

    def test_calendar_gap_is_warning(self):
        bars = [bar("2026-01-05", 10, 10.5, 10.6, 9.9),
                bar("2026-02-10", 10.5, 10.8, 11.0, 10.4)]  # 36 天
        r = clean_bars(bars)
        self.assertTrue(r["ok"])
        self.assertIn("DATE_GAP", codes(r))

    def test_missing_field_is_error(self):
        r = clean_bars([{"date": "2026-01-05", "open": 10, "close": 10.5}])
        self.assertFalse(r["ok"])
        self.assertIn("BAD_FIELD", codes(r))

    def test_empty_input(self):
        r = clean_bars([])
        self.assertTrue(r["ok"])
        self.assertEqual(r["bars"], [])


if __name__ == "__main__":
    unittest.main()
