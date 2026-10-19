# -*- coding: utf-8 -*-
"""账户系统测试：净入金、收益率、权重、快照去重与上限。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stock import account  # noqa: E402


def snap(cash, positions, day="2026-10-17"):
    mv = sum(p["market_value"] for p in positions)
    floating = sum(p.get("pnl") or 0 for p in positions)
    return {"day": day, "cash": cash, "market_value": mv, "total": cash + mv,
            "floating_pnl": floating, "realized_pnl": 0.0, "positions": positions}


def pos(code, value, pnl=0.0):
    return {"code": code, "name": code, "shares": 100,
            "market_value": value, "pnl": pnl, "pnl_pct": 0.0}


class TestFlows(unittest.TestCase):
    def test_default_account_opens_with_cash(self):
        acct = account.default_account(200000.0, day="2026-10-17")
        self.assertEqual(account.net_deposit(acct), 200000.0)
        self.assertEqual(len(account.flows(acct)), 1)

    def test_deposit_and_withdraw(self):
        acct = account.default_account(200000.0)
        account.add_flow(acct, "deposit", 50000)
        account.add_flow(acct, "withdraw", 30000)
        self.assertEqual(account.net_deposit(acct), 220000.0)

    def test_rejects_bad_amounts(self):
        acct = account.default_account(0)
        for bad in (0, -100, "abc"):
            with self.assertRaises(ValueError):
                account.add_flow(acct, "deposit", bad)
        with self.assertRaises(ValueError):
            account.add_flow(acct, "transfer", 100)


class TestWallet(unittest.TestCase):
    def test_default_wallet_is_zero(self):
        # 本金全部在证券账户，钱包从 0 开始
        acct = account.default_account(350000.0)
        self.assertEqual(account.wallet_balance(acct), 0.0)

    def test_old_account_gets_wallet_filled(self):
        acct = {"flows": [], "snapshots": [], "next_id": 1}
        self.assertEqual(account.wallet_balance(acct), 0.0)
        self.assertIn("wallet", acct)

    def test_net_worth_includes_wallet(self):
        acct = account.default_account(350000.0)
        s = account.summary(acct, snap(350000.0, []))
        self.assertEqual(s["wallet"], 0.0)
        self.assertEqual(s["net_worth"], 350000.0)

    def test_position_pct_of_net_worth(self):
        acct = account.default_account(350000.0)
        s = account.summary(acct, snap(100000.0, [pos("600519", 100000.0)]))
        # 净资产 = 10万现金 + 10万持仓 + 0 钱包 = 20万，持仓占 50%
        self.assertAlmostEqual(s["position_pct_of_net"], 50.0, places=2)

    def test_non_finite_amounts_are_rejected(self):
        acct = account.default_account(0)
        for bad in ("nan", "inf", float("nan"), float("inf"), 1e309):
            with self.assertRaises(ValueError):
                account.add_flow(acct, "deposit", bad)


class TestSummary(unittest.TestCase):
    def setUp(self):
        self.acct = account.default_account(200000.0, day="2026-10-17")

    def test_flat_account_has_zero_return(self):
        s = account.summary(self.acct, snap(200000.0, []))
        self.assertEqual(s["total"], 200000.0)
        self.assertEqual(s["total_pnl"], 0.0)
        self.assertEqual(s["total_return_pct"], 0.0)

    def test_profit_is_measured_against_net_deposit(self):
        # 20 万本金，持仓市值 210000（现金 0）-> 总收益 +5%
        s = account.summary(self.acct, snap(0.0, [pos("600519", 210000.0, 10000.0)]))
        self.assertEqual(s["total"], 210000.0)
        self.assertEqual(s["total_pnl"], 10000.0)
        self.assertEqual(s["total_return_pct"], 5.0)

    def test_later_deposit_does_not_fake_a_profit(self):
        account.add_flow(self.acct, "deposit", 100000.0)
        s = account.summary(self.acct, snap(300000.0, []))
        self.assertEqual(s["net_deposit"], 300000.0)
        self.assertEqual(s["total_pnl"], 0.0)
        self.assertEqual(s["total_return_pct"], 0.0)


class TestAllocation(unittest.TestCase):
    def setUp(self):
        self.acct = account.default_account(200000.0)

    def test_weights_sum_to_100(self):
        s = snap(50000.0, [pos("600519", 90000.0), pos("000001", 60000.0)])
        alloc = account.allocation(self.acct, s)
        total_pct = alloc["cash_pct"] + sum(i["weight"] for i in alloc["items"])
        self.assertAlmostEqual(total_pct, 100.0, places=1)
        self.assertAlmostEqual(alloc["cash_pct"], 25.0, places=2)

    def test_items_sorted_by_weight_desc(self):
        s = snap(0.0, [pos("A", 10000.0), pos("B", 30000.0)])
        alloc = account.allocation(self.acct, s)
        self.assertEqual([i["code"] for i in alloc["items"]], ["B", "A"])

    def test_all_cash_when_no_positions(self):
        alloc = account.allocation(self.acct, snap(200000.0, []))
        self.assertEqual(alloc["cash_pct"], 100.0)
        self.assertEqual(alloc["items"], [])

    def test_empty_account_does_not_crash(self):
        alloc = account.allocation(self.acct, snap(0.0, []))
        self.assertEqual(alloc["cash_pct"], 0.0)


class TestSnapshots(unittest.TestCase):
    def setUp(self):
        self.acct = account.default_account(200000.0)

    def test_one_snapshot_per_day(self):
        self.assertTrue(account.record_snapshot(self.acct, "2026-10-17", snap(200000.0, [])))
        self.assertFalse(account.record_snapshot(self.acct, "2026-10-17", snap(200000.0, [])))
        self.assertEqual(len(account.equity_curve(self.acct)), 1)

    def test_same_day_change_updates(self):
        account.record_snapshot(self.acct, "2026-10-17", snap(200000.0, []))
        self.assertTrue(account.record_snapshot(self.acct, "2026-10-17", snap(201000.0, [])))
        curve = account.equity_curve(self.acct)
        self.assertEqual(len(curve), 1)
        self.assertEqual(curve[0]["total"], 201000.0)

    def test_curve_is_sorted_and_capped(self):
        for i in range(300):
            account.record_snapshot(self.acct, "2025-%02d-%02d" % (1 + i % 12, 1 + i % 28),
                                    snap(200000.0 + i, []))
        curve = account.equity_curve(self.acct)
        self.assertLessEqual(len(curve), account.MAX_SNAPSHOTS)
        self.assertEqual(curve, sorted(curve, key=lambda s: s["date"]))


if __name__ == "__main__":
    unittest.main()
