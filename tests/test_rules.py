# -*- coding: utf-8 -*-
"""A 股规则的测试：整手、涨跌停、佣金/印花税/过户费，全部手算对账。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stock.rules import (  # noqa: E402
    commission, is_st_name, limit_pct, market_of, normalize_code, price_limits,
    round2,
    stamp_duty, tencent_symbol, total_fee, transfer_fee,
)

COMMISSION_RATE = 0.0003
STAMP_RATE = 0.0005
TRANSFER_RATE = 0.00001


class TestCodeHelpers(unittest.TestCase):
    def test_normalize_strips_prefix_and_spaces(self):
        for raw in ("600519", "sh600519", "SH600519", " 600519 "):
            self.assertEqual(normalize_code(raw), "600519")

    def test_market_of(self):
        self.assertEqual(market_of("600519"), "sh")
        self.assertEqual(market_of("000001"), "sz")
        self.assertEqual(market_of("300750"), "sz")
        self.assertEqual(market_of("688111"), "sh")

    def test_tencent_symbol(self):
        self.assertEqual(tencent_symbol("600519"), "sh600519")
        self.assertEqual(tencent_symbol("000001"), "sz000001")


class TestPriceLimits(unittest.TestCase):
    def test_main_board_10_percent(self):
        self.assertEqual(price_limits("600519", 100.0), (90.0, 110.0))
        self.assertEqual(price_limits("000001", 100.0), (90.0, 110.0))

    def test_chinext_and_star_20_percent(self):
        self.assertEqual(price_limits("300750", 100.0), (80.0, 120.0))
        self.assertEqual(price_limits("301111", 100.0), (80.0, 120.0))
        self.assertEqual(price_limits("688111", 100.0), (80.0, 120.0))

    def test_st_5_percent_when_flagged(self):
        self.assertEqual(price_limits("600519", 100.0, is_st=True), (95.0, 105.0))

    def test_rounds_to_two_decimals(self):
        low, high = price_limits("600519", 10.005)
        self.assertEqual(low, 9.0)
        self.assertEqual(high, 11.01)  # 10.005*1.1 = 11.0055 -> round 11.01

    def test_limit_price_half_up_edge(self):
        # 1.65 * 0.9 = 1.485，四舍五入到分应是 1.49（浮点会给出 1.4849999... 变成 1.48）
        self.assertEqual(price_limits("600519", 1.65), (1.49, 1.82))

    def test_st_only_shrinks_main_board(self):
        # 创业板/科创板注册制后 ST 也是 20%，只有主板 ST 才是 5%
        self.assertAlmostEqual(limit_pct("300750", is_st=True), 0.20)
        self.assertAlmostEqual(limit_pct("688111", is_st=True), 0.20)
        self.assertAlmostEqual(limit_pct("600519", is_st=True), 0.05)

    def test_limit_pct_values(self):
        self.assertAlmostEqual(limit_pct("600519"), 0.10)
        self.assertAlmostEqual(limit_pct("300750"), 0.20)
        self.assertAlmostEqual(limit_pct("688111"), 0.20)
        self.assertAlmostEqual(limit_pct("600519", is_st=True), 0.05)


class TestStName(unittest.TestCase):
    def test_recognises_st_prefix(self):
        self.assertTrue(is_st_name("ST海航"))
        self.assertTrue(is_st_name("*ST长生"))
        self.assertTrue(is_st_name("st 某某"))

    def test_normal_names_are_not_st(self):
        for name in ("贵州茅台", "平安银行", "沪深300ETF", "", None):
            self.assertFalse(is_st_name(name), name)


class TestFees(unittest.TestCase):
    def test_round2_survives_huge_numbers(self):
        # 默认 Decimal 精度只有 28 位，1e300 以前会抛 InvalidOperation（表现为 500）
        self.assertAlmostEqual(round2(1e300) / 1e300, 1.0, places=6)
        self.assertEqual(round2(0.005), 0.01)
        with self.assertRaises(ValueError):
            round2(float("nan"))
    def test_commission_floor_is_5_yuan(self):
        self.assertAlmostEqual(commission(10000.0), 5.0, places=6)   # 3.0 -> 5
        self.assertAlmostEqual(commission(100000.0), 30.0, places=6)  # 30.0
        self.assertAlmostEqual(commission(1000.0), 5.0, places=6)

    def test_stamp_duty_only_on_sell(self):
        self.assertAlmostEqual(stamp_duty(100000.0, is_sell=True), 50.0, places=6)
        self.assertAlmostEqual(stamp_duty(100000.0, is_sell=False), 0.0, places=6)

    def test_transfer_fee_both_sides(self):
        self.assertAlmostEqual(transfer_fee(100000.0), 1.0, places=6)

    def test_total_fee_buy_and_sell(self):
        # 买：佣金 30 + 印花 0 + 过户 1 = 31
        self.assertAlmostEqual(total_fee(100000.0, is_sell=False), 31.0, places=6)
        # 卖：佣金 30 + 印花 50 + 过户 1 = 81
        self.assertAlmostEqual(total_fee(100000.0, is_sell=True), 81.0, places=6)

    def test_total_fee_small_amount_uses_floor(self):
        # 金额 1000：佣金 5(下限) + 印花 0 + 过户 0.01 = 5.01
        self.assertAlmostEqual(total_fee(1000.0, is_sell=False), 5.01, places=6)


if __name__ == "__main__":
    unittest.main()
