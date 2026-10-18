# -*- coding: utf-8 -*-
"""回测测试：均线交叉 + 费用，用可手算的序列断言成交点与资金曲线。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stock.backtest import run_ma_cross  # noqa: E402


def bars_from_closes(closes):
    """由收盘价造出最小可用 K 线（开=高=低=收），只为测策略逻辑。"""
    return [{"date": "2026-01-%02d" % (i + 1), "open": c, "close": c,
             "high": c, "low": c, "volume": 1000} for i, c in enumerate(closes)]


CLOSES = [10, 11, 12, 11, 10, 9, 10, 11, 12, 13]


class TestMacross(unittest.TestCase):
    def setUp(self):
        self.r = run_ma_cross(bars_from_closes(CLOSES), short=2, long=3,
                              cash=100_000.0, commission_rate=0.0003,
                              stamp_rate=0.0005, transfer_rate=0.00001)

    def test_equity_curve_covers_every_bar(self):
        self.assertEqual(len(self.r["equity"]), len(CLOSES))
        self.assertEqual([p["date"] for p in self.r["equity"]],
                         ["2026-01-%02d" % (i + 1) for i in range(len(CLOSES))])

    def test_two_crosses_give_two_trades(self):
        # SMA2 与 SMA3 在第 3 根金叉（12>11），第 5 根死叉（10.5<11），
        # 第 8 根再金叉（10.5>10），末尾按最后收盘价平仓 -> 2 笔
        self.assertEqual(len(self.r["trades"]), 2)
        first, second = self.r["trades"]
        self.assertEqual(first["entry_date"], "2026-01-03")
        self.assertAlmostEqual(first["entry_price"], 12.0, places=6)
        self.assertEqual(first["exit_date"], "2026-01-05")
        self.assertAlmostEqual(first["exit_price"], 10.0, places=6)
        self.assertEqual(second["entry_date"], "2026-01-08")
        self.assertAlmostEqual(second["entry_price"], 11.0, places=6)
        self.assertEqual(second["exit_date"], "2026-01-10")
        self.assertAlmostEqual(second["exit_price"], 13.0, places=6)

    def test_trades_pay_fees(self):
        for t in self.r["trades"]:
            self.assertGreater(t["fee"], 0.0)
            self.assertGreater(t["entry_amount"], 0.0)
            # pnl / gross_pnl 都按「分」取整，容差到分
            self.assertAlmostEqual(t["pnl"], t["gross_pnl"] - t["fee"], places=2)

    def test_share_count_is_whole_lots(self):
        # 100000 / 12 = 8333 -> 取整手 8300 股
        self.assertEqual(self.r["trades"][0]["shares"], 8300)

    def test_final_equity_matches_hand_computation(self):
        # 手算：买 8300@12 -> 金额 99600，费用 29.88+0.996=30.876
        #       卖 8300@10 -> 金额 83000，费用 24.9+41.5+0.83=67.23
        #       再买 7500@11 -> 金额 82500，费用 24.75+0.825=25.575
        #       末尾按 13 强制平仓 -> 金额 97500，费用 29.25+48.75+0.975=78.975
        #       （强制平仓同样要交卖出费用，这是第一版手算漏掉的一笔）
        cash = 100_000.0
        buy1 = 8300 * 12.0
        cash -= buy1 + (max(5.0, buy1 * 0.0003) + buy1 * 0.00001)
        sell1 = 8300 * 10.0
        cash += sell1 - (max(5.0, sell1 * 0.0003) + sell1 * 0.0005 + sell1 * 0.00001)
        buy2 = 7500 * 11.0
        cash -= buy2 + (max(5.0, buy2 * 0.0003) + buy2 * 0.00001)
        last = 7500 * 13.0
        cash += last - (max(5.0, last * 0.0003) + last * 0.0005 + last * 0.00001)
        expected = cash
        # 金额按「分」记账：断言四舍五入到分相等，且误差不超过半分
        self.assertAlmostEqual(self.r["final_equity"], round(expected, 2), places=2)
        self.assertLessEqual(abs(self.r["final_equity"] - expected), 0.005)

    def test_metrics_present(self):
        m = self.r["metrics"]
        for key in ("total_return", "max_drawdown", "win_rate", "trade_count"):
            self.assertIn(key, m)
        self.assertEqual(m["trade_count"], 2)
        self.assertGreaterEqual(m["max_drawdown"], 0.0)

    def test_no_signal_when_short_equals_long_window(self):
        r = run_ma_cross(bars_from_closes([10, 11, 12, 13, 14]), short=3, long=3)
        self.assertEqual(r["trades"], [])
        self.assertAlmostEqual(r["final_equity"], r["initial_equity"], places=6)

    def test_rejects_bad_params(self):
        with self.assertRaises(ValueError):
            run_ma_cross(bars_from_closes(CLOSES), short=0, long=3)

    # ---- 现实约束（涨跌停 / 滑点）----
    def test_limits_do_not_block_normal_bars(self):
        # 回归测试：解包写反时，正常行情会被当成涨停全部拒掉（曾经真的这样）。
        # 注意不要用 CLOSES：它里面有 10→11 这种「正好 +10%」的 bar，本来就该被拒。
        closes = [10, 10.5, 11, 10.8, 10.2, 9.9, 10.3, 10.9, 11.6, 12.2]
        r = run_ma_cross(bars_from_closes(closes), short=2, long=3,
                         cash=100_000.0, code="000001")
        self.assertEqual(len(r["trades"]), 2)
        self.assertEqual(r["skipped_buys"], 0)

    def test_limit_up_blocks_buy(self):
        # 第 4 根相对第 3 根 +10%（正好涨停），金叉发生在这一根 -> 买不进
        closes = [10, 10, 10, 11]
        r = run_ma_cross(bars_from_closes(closes), short=1, long=3,
                         cash=100_000.0, code="600519")
        self.assertEqual(r["trades"], [])
        self.assertEqual(r["skipped_buys"], 1)
        self.assertAlmostEqual(r["final_equity"], 100_000.0, places=2)

    def test_limit_down_delays_sell(self):
        # 死叉那天正好跌停（10.8 = 12 × 0.9）-> 当天卖不掉，次日才成交
        closes = [10, 11, 12, 12, 10.8, 10.8, 10.8]
        r = run_ma_cross(bars_from_closes(closes), short=2, long=3,
                         cash=100_000.0, code="600519")
        self.assertEqual(len(r["trades"]), 1)
        trade = r["trades"][0]
        self.assertEqual(trade["entry_date"], "2026-01-03")
        self.assertEqual(trade["exit_date"], "2026-01-06")
        self.assertEqual(r["delayed_sells"], 1)

    def test_slippage_moves_prices(self):
        r0 = run_ma_cross(bars_from_closes(CLOSES), short=2, long=3, cash=100_000.0)
        r1 = run_ma_cross(bars_from_closes(CLOSES), short=2, long=3,
                          cash=100_000.0, slippage_bps=100)  # 1%
        self.assertAlmostEqual(r1["trades"][0]["entry_price"], 12.12, places=2)
        self.assertLess(r1["final_equity"], r0["final_equity"])


if __name__ == "__main__":
    unittest.main()
