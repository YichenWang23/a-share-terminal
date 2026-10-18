# -*- coding: utf-8 -*-
"""模拟盘测试：整手、T+1、涨跌停、费用与盈亏，全部按手算数字断言。"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stock.portfolio import Portfolio  # noqa: E402


class TestBuySell(unittest.TestCase):
    def setUp(self):
        self.p = Portfolio(cash=1_000_000.0, day="2026-10-19")

    def test_buy_charges_fees_and_locks_for_t_plus_1(self):
        r = self.p.buy("600519", price=1300.0, shares=100, name="贵州茅台")
        self.assertTrue(r["ok"], r)
        # 金额 130000：佣金 39.0、过户 1.3、印花 0 -> 40.3
        self.assertAlmostEqual(r["trade"]["fee_detail"]["commission"], 39.0, places=6)
        self.assertAlmostEqual(r["trade"]["fee_detail"]["transfer"], 1.3, places=6)
        self.assertAlmostEqual(r["trade"]["fee_detail"]["stamp"], 0.0, places=6)
        self.assertAlmostEqual(r["trade"]["fee"], 40.3, places=6)
        self.assertAlmostEqual(r["cash"], 1_000_000.0 - 130_000.0 - 40.3, places=6)
        pos = self.p.snapshot({"600519": 1300.0})["positions"][0]
        self.assertEqual(pos["shares"], 100)
        self.assertEqual(pos["available"], 0)  # T+1

    def test_same_day_sell_rejected(self):
        self.p.buy("600519", price=1300.0, shares=100)
        r = self.p.sell("600519", price=1320.0, shares=100)
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "T_PLUS_1")

    def test_sell_after_roll_day_charges_stamp_duty(self):
        self.p.buy("600519", price=1300.0, shares=100)
        self.p.roll_day("2026-10-20")
        r = self.p.sell("600519", price=1310.0, shares=100)
        self.assertTrue(r["ok"], r)
        # 金额 131000：佣金 39.3、印花 65.5、过户 1.31 -> 106.11
        self.assertAlmostEqual(r["trade"]["fee_detail"]["commission"], 39.3, places=6)
        self.assertAlmostEqual(r["trade"]["fee_detail"]["stamp"], 65.5, places=6)
        self.assertAlmostEqual(r["trade"]["fee_detail"]["transfer"], 1.31, places=6)
        self.assertAlmostEqual(r["trade"]["fee"], 106.11, places=6)
        expected_cash = 1_000_000.0 - 130_000.0 - 40.3 + 131_000.0 - 106.11
        self.assertAlmostEqual(r["cash"], expected_cash, places=6)
        self.assertEqual(r["cash"], r["cash"])  # 非 NaN
        self.assertEqual(len(self.p.snapshot({"600519": 1310.0})["positions"]), 0)

    def test_realized_pnl_after_round_trip(self):
        self.p.buy("600519", price=1300.0, shares=100)
        self.p.roll_day("2026-10-20")
        self.p.sell("600519", price=1310.0, shares=100)
        # 毛利 1000，费用 40.3 + 106.11 -> 净 853.59
        self.assertAlmostEqual(self.p.realized_pnl, 853.59, places=6)


class TestRejections(unittest.TestCase):
    def setUp(self):
        self.p = Portfolio(cash=1_000_000.0, day="2026-10-19")

    def test_nan_and_inf_price_rejected(self):
        for bad in (float("nan"), float("inf"), 0, -5):
            r = self.p.buy("600519", price=bad, shares=100)
            self.assertFalse(r["ok"], "价格 %r 应被拒" % bad)
            self.assertEqual(r["reason"], "BAD_PRICE")
        # 现金绝不能被污染成 NaN
        self.assertFalse(math.isnan(self.p.cash))

    def test_fractional_shares_rejected(self):
        r = self.p.buy("600519", price=100.0, shares=100.7)
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "BAD_SHARES")
        self.assertEqual(self.p.snapshot({})["positions"], [])

    def test_absurd_share_count_rejected(self):
        r = self.p.buy("600519", price=1.0, shares=10 ** 12)
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "BAD_SHARES")

    def test_nan_price_rejected_on_sell(self):
        self.p.buy("600519", price=100.0, shares=100)
        self.p.roll_day("2026-10-20")
        r = self.p.sell("600519", price=float("nan"), shares=100)
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "BAD_PRICE")

    def test_lot_size_must_be_100(self):
        r = self.p.buy("600519", price=1300.0, shares=150)
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "LOT_SIZE")

    def test_zero_or_negative_shares_rejected(self):
        for bad in (0, -100):
            r = self.p.buy("600519", price=1300.0, shares=bad)
            self.assertFalse(r["ok"])
            self.assertEqual(r["reason"], "BAD_SHARES")

    def test_price_above_limit_up_rejected(self):
        # 昨收 100 -> 主板上限 110
        r = self.p.buy("600519", price=111.0, shares=100, prev_close=100.0)
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "PRICE_LIMIT")

    def test_price_below_limit_down_rejected(self):
        r = self.p.buy("600519", price=89.0, shares=100, prev_close=100.0)
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "PRICE_LIMIT")

    def test_insufficient_cash(self):
        poor = Portfolio(cash=1000.0, day="2026-10-19")
        r = poor.buy("600519", price=1300.0, shares=100)
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "INSUFFICIENT_CASH")

    def test_sell_more_than_available(self):
        self.p.buy("600519", price=1300.0, shares=100)
        self.p.roll_day("2026-10-20")
        r = self.p.sell("600519", price=1310.0, shares=200)
        self.assertFalse(r["ok"])
        self.assertIn(r["reason"], ("INSUFFICIENT_SHARES", "LOT_SIZE"))


class TestSnapshot(unittest.TestCase):
    def test_unrealized_pnl_uses_cost_plus_buy_fee(self):
        p = Portfolio(cash=1_000_000.0, day="2026-10-19")
        p.buy("600519", price=1300.0, shares=100)
        snap = p.snapshot({"600519": 1320.0})
        pos = snap["positions"][0]
        self.assertAlmostEqual(pos["avg_cost"], 1300.0, places=6)
        self.assertAlmostEqual(pos["market_value"], 132_000.0, places=6)
        # 浮盈 = 2000 - 40.3(买入费用) = 1959.7；成本口径含买入费用
        self.assertAlmostEqual(pos["pnl"], 1959.7, places=6)
        self.assertAlmostEqual(snap["market_value"], 132_000.0, places=6)
        self.assertAlmostEqual(snap["total"], snap["cash"] + 132_000.0, places=6)

    def test_state_round_trip(self):
        p = Portfolio(cash=500_000.0, day="2026-10-19")
        p.buy("000001", price=11.5, shares=1000, name="平安银行")
        restored = Portfolio.from_dict(p.to_dict())
        self.assertAlmostEqual(restored.cash, p.cash, places=6)
        self.assertEqual(restored.positions["000001"]["shares"], 1000)


if __name__ == "__main__":
    unittest.main()
