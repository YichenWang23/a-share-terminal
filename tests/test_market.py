# -*- coding: utf-8 -*-
"""开市状态测试：用固定时间点断言，不依赖当前机器时间。"""
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stock.market import market_status  # noqa: E402

MONDAY_10 = datetime.datetime(2026, 10, 19, 10, 0)
SATURDAY_10 = datetime.datetime(2026, 10, 17, 10, 0)


class TestMarketStatus(unittest.TestCase):
    def test_trading_morning(self):
        self.assertEqual(market_status(now=MONDAY_10)["status"], "trading")

    def test_trading_afternoon(self):
        d = datetime.datetime(2026, 10, 19, 14, 0)
        self.assertEqual(market_status(now=d)["status"], "trading")

    def test_lunch_break(self):
        d = datetime.datetime(2026, 10, 19, 12, 0)
        self.assertEqual(market_status(now=d)["status"], "lunch")

    def test_preopen(self):
        d = datetime.datetime(2026, 10, 19, 9, 0)
        self.assertEqual(market_status(now=d)["status"], "preopen")

    def test_after_close(self):
        d = datetime.datetime(2026, 10, 19, 16, 0)
        self.assertEqual(market_status(now=d)["status"], "closed")

    def test_weekend(self):
        self.assertEqual(market_status(now=SATURDAY_10)["status"], "weekend")

    def test_old_quote_date_wins(self):
        r = market_status(now=MONDAY_10, quote_date="2026-10-16")
        self.assertEqual(r["status"], "closed_data")
        self.assertIn("2026-10-16", r["label"])
        self.assertEqual(r["stale_days"], 3)

    def test_label_always_present(self):
        for now in (MONDAY_10, SATURDAY_10):
            self.assertTrue(market_status(now=now)["label"])


if __name__ == "__main__":
    unittest.main()
