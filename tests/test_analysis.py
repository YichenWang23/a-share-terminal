# -*- coding: utf-8 -*-
"""规则引擎分析测试：固定输入必须给出固定结论，且绝不冒充模型输出。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stock.analysis import rule_engine  # noqa: E402


def make_bars(closes):
    return [{"date": "2026-01-%02d" % ((i % 28) + 1), "open": c, "close": c,
             "high": c * 1.01, "low": c * 0.99, "volume": 1000.0}
            for i, c in enumerate(closes)]


def quote(price, prev_close=None):
    pc = prev_close if prev_close is not None else price
    return {"code": "600519", "name": "贵州茅台", "price": price,
            "prev_close": pc, "high": price, "low": price,
            "change": price - pc, "change_pct": (price - pc) / pc * 100 if pc else 0.0,
            "limit_up": pc * 1.1, "limit_down": pc * 0.9}


class TestRuleEngine(unittest.TestCase):
    def test_uptrend_is_bullish(self):
        closes = [100.0 + i for i in range(80)]
        r = rule_engine(quote(closes[-1]), make_bars(closes))
        self.assertEqual(r["source"], "rule-engine")
        self.assertGreater(r["score"], 0)
        self.assertEqual(r["stance"], "偏多")
        self.assertTrue(r["disclaimer"])

    def test_downtrend_is_bearish(self):
        closes = [200.0 - i for i in range(80)]
        r = rule_engine(quote(closes[-1]), make_bars(closes))
        self.assertLess(r["score"], 0)
        self.assertEqual(r["stance"], "偏空")

    def test_flat_is_neutral(self):
        closes = [100.0] * 80
        r = rule_engine(quote(100.0), make_bars(closes))
        self.assertEqual(r["stance"], "中性")
        self.assertLessEqual(abs(r["score"]), 15)

    def test_points_have_required_keys(self):
        closes = [100.0 + i for i in range(80)]
        r = rule_engine(quote(closes[-1]), make_bars(closes))
        names = {p["key"] for p in r["points"]}
        for key in ("trend", "rsi", "macd", "volume", "position"):
            self.assertIn(key, names)
        for p in r["points"]:
            self.assertIn("label", p)
            self.assertIn("verdict", p)

    def test_short_history_is_flagged_not_crashed(self):
        r = rule_engine(quote(100.0), make_bars([100.0, 101.0, 102.0]))
        self.assertTrue(r["insufficient_history"])
        self.assertIn("历史", "".join(r["bullets"]))

    def test_deterministic(self):
        closes = [100.0 + (i % 5) for i in range(80)]
        a = rule_engine(quote(closes[-1]), make_bars(closes))
        b = rule_engine(quote(closes[-1]), make_bars(closes))
        self.assertEqual(a, b)

    def test_never_claims_to_be_a_model(self):
        closes = [100.0 + i for i in range(80)]
        r = rule_engine(quote(closes[-1]), make_bars(closes))
        self.assertEqual(r["source"], "rule-engine")
        self.assertNotIn("大模型", r["source"])
        self.assertIn("不构成", r["disclaimer"])

    def test_limit_up_position_flagged(self):
        # 收盘等于涨停价：应把「位置」判为追高风险
        closes = [100.0] * 79 + [110.0]
        r = rule_engine(quote(110.0, prev_close=100.0), make_bars(closes))
        pos = {p["key"]: p for p in r["points"]}["position"]
        self.assertIn("涨停", pos["verdict"] + pos["label"])


if __name__ == "__main__":
    unittest.main()
