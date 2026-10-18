# -*- coding: utf-8 -*-
"""指标计算的测试：全部用可手算的固定样例，禁止「看起来对」。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stock.indicators import ema, macd, max_drawdown, rsi, sma  # noqa: E402


class TestSMA(unittest.TestCase):
    def test_window_three_on_ramp(self):
        self.assertEqual(sma([1, 2, 3, 4, 5], 3), [None, None, 2.0, 3.0, 4.0])

    def test_returns_none_until_window_filled(self):
        self.assertEqual(sma([5, 6], 3), [None, None])

    def test_rejects_non_positive_window(self):
        with self.assertRaises(ValueError):
            sma([1, 2, 3], 0)


class TestEMA(unittest.TestCase):
    def test_constant_series_stays_constant(self):
        self.assertEqual([round(x, 6) for x in ema([1, 1, 1, 1], 2)], [1.0, 1.0, 1.0, 1.0])

    def test_hand_computed_ramp(self):
        # alpha = 2/(2+1) = 2/3; seed = 1
        # e1 = 1 + 2/3*(2-1)      = 1.666667
        # e2 = 1.666667 + 2/3*(3-1.666667) = 2.555556
        # e3 = 2.555556 + 2/3*(4-2.555556) = 3.518519
        got = ema([1, 2, 3, 4], 2)
        self.assertAlmostEqual(got[0], 1.0, places=6)
        self.assertAlmostEqual(got[1], 1.666667, places=6)
        self.assertAlmostEqual(got[2], 2.555556, places=6)
        self.assertAlmostEqual(got[3], 3.518519, places=6)


class TestRSI(unittest.TestCase):
    def test_all_gains_is_100(self):
        closes = [float(i) for i in range(1, 20)]
        values = rsi(closes, 14)
        self.assertEqual(values[0], None)
        self.assertAlmostEqual(values[-1], 100.0, places=6)

    def test_all_losses_is_0(self):
        closes = [float(i) for i in range(20, 1, -1)]
        values = rsi(closes, 14)
        self.assertAlmostEqual(values[-1], 0.0, places=6)

    def test_alternating_hovers_around_50(self):
        # 涨一个点、跌一个点交替：Wilder 平滑下 RSI 会在 50 附近摆动（不是恰好 50）
        closes = []
        v = 100.0
        for i in range(40):
            v += 1.0 if i % 2 == 0 else -1.0
            closes.append(v)
        values = rsi(closes, 14)
        self.assertGreaterEqual(values[-1], 45.0)
        self.assertLessEqual(values[-1], 55.0)

    def test_length_matches_input(self):
        self.assertEqual(len(rsi([1, 2, 3, 4, 5], 3)), 5)


class TestMACD(unittest.TestCase):
    def test_constant_series_is_zero(self):
        line, signal, hist = macd([5.0] * 60)
        self.assertAlmostEqual(line[-1], 0.0, places=9)
        self.assertAlmostEqual(signal[-1], 0.0, places=9)
        self.assertAlmostEqual(hist[-1], 0.0, places=9)

    def test_uptrend_gives_positive_line(self):
        closes = [100.0 + i for i in range(120)]
        line, signal, hist = macd(closes)
        self.assertGreater(line[-1], 0.0)
        self.assertGreater(hist[-1], -1.0)

    def test_series_lengths_match_input(self):
        closes = [float(i) for i in range(50)]
        line, signal, hist = macd(closes, 12, 26, 9)
        self.assertEqual(len(line), 50)
        self.assertEqual(len(signal), 50)
        self.assertEqual(len(hist), 50)


class TestDrawdown(unittest.TestCase):
    def test_peak_to_trough(self):
        # 峰值 120 -> 谷底 90，回撤 = -0.25
        self.assertAlmostEqual(max_drawdown([100, 120, 90, 110]), -0.25, places=6)

    def test_monotonic_up_has_no_drawdown(self):
        self.assertAlmostEqual(max_drawdown([1, 2, 3, 4]), 0.0, places=9)


if __name__ == "__main__":
    unittest.main()
