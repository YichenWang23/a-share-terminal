# -*- coding: utf-8 -*-
"""默认配置测试：初始资金 20 万、自选股覆盖多个板块。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stock import storage  # noqa: E402
from stock.portfolio import Portfolio  # noqa: E402

EXPECTED_CASH = 200_000.0


class TestDefaults(unittest.TestCase):
    def test_portfolio_default_cash_is_200k(self):
        self.assertEqual(Portfolio().cash, EXPECTED_CASH)

    def test_default_state_cash_is_200k(self):
        self.assertEqual(storage.DEFAULT_STATE["portfolio"]["cash"], EXPECTED_CASH)

    def test_watchlist_is_broad_enough(self):
        codes = storage.DEFAULT_STATE["watchlist"]
        self.assertGreaterEqual(len(codes), 80, "自选股至少 80 只（当前 88）")
        # 必须覆盖：主板、创业板、科创板、ETF
        self.assertIn("600519", codes)   # 沪主板
        self.assertIn("000001", codes)   # 深主板
        self.assertIn("300750", codes)   # 创业板
        self.assertIn("688981", codes)   # 科创板
        self.assertTrue(any(c.startswith(("51", "58", "15", "16")) for c in codes), "要有一只 ETF")

    def test_requested_stocks_are_present(self):
        codes = storage.DEFAULT_STATE["watchlist"]
        self.assertIn("002624", codes, "完美世界")
        self.assertIn("688825", codes, "长鑫科技（长鑫存储未单独上市）")

    def test_private_enterprises_present(self):
        codes = storage.DEFAULT_STATE["watchlist"]
        # 用户要求「私企多来一点」：这几家民营代表必须在池
        for code, name in (("600660", "福耀玻璃"), ("002352", "顺丰控股"),
                           ("002241", "歌尔股份")):
            self.assertIn(code, codes, "缺少民营代表 %s" % name)

    def test_non_tech_sectors_covered(self):
        codes = set(storage.DEFAULT_STATE["watchlist"])
        # 非科技：伊利(乳制品)、长江电力(水电)、中国神华(煤炭)、恒瑞(医药)、保利(地产)、中国建筑(建筑)
        for code in ("600887", "600900", "601088", "600276", "600048", "601668"):
            self.assertIn(code, codes, "缺少非科技板块代表 %s" % code)

    def test_watchlist_has_no_duplicates(self):
        codes = storage.DEFAULT_STATE["watchlist"]
        self.assertEqual(len(codes), len(set(codes)))


if __name__ == "__main__":
    unittest.main()
