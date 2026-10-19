"""End-of-day rules on small synthetic streams: overdraft fees and interest."""
import unittest
from decimal import Decimal

from ledger.engine import EntryKind, Ledger, Rules, Severity, WindowClosed
from ledger.events import Event, EventKind
from ledger.money import AED, BHD, Money

K = EventKind


def aed(text):
    return Money.parse(text, AED)


def fees(lg, account="A"):
    return [(e.value_date, e.amount.format()) for e in lg.entries if e.kind is EntryKind.OVERDRAFT_FEE and e.account == account]


class OverdraftFees(unittest.TestCase):
    def test_fee_once_per_negative_day_even_across_repeated_eods(self):
        lg = Ledger({"A": AED})
        lg.submit(Event("d1", 1, K.DEBIT, "A", 1, amount=aed("10.00")))
        for _ in range(3):
            lg.close_day()
        # Day 1 -10, Day 2 -35, Day 3 -60: one fee per day, never a second for Day 1.
        self.assertEqual(fees(lg), [(1, "-25.00"), (2, "-25.00"), (3, "-25.00")])

    def test_no_fee_on_zero_or_positive_close(self):
        lg = Ledger({"A": AED})
        lg.submit(Event("c1", 1, K.CREDIT, "A", 1, amount=aed("10.00")))
        lg.submit(Event("d1", 1, K.DEBIT, "A", 1, amount=aed("10.00")))
        lg.close_day()
        self.assertEqual(fees(lg), [])

    def test_holds_do_not_trigger_fees(self):
        # Fees are on the ledger balance, not the available balance.
        lg = Ledger({"A": AED})
        lg.submit(Event("c1", 1, K.CREDIT, "A", 1, amount=aed("10.00")))
        lg.submit(Event("a1", 1, K.AUTHORIZATION, "A", 1, amount=aed("10.00"), auth_id="X"))
        lg.close_day()
        self.assertEqual(lg.available_balance("A", 1), aed("0.00"))
        self.assertEqual(fees(lg), [])

    def test_back_valued_debit_triggers_retroactive_fee_with_past_value_date(self):
        lg = Ledger({"A": AED})
        lg.submit(Event("c1", 1, K.CREDIT, "A", 1, amount=aed("100.00")))
        lg.close_day()
        lg.close_day()
        lg.submit(Event("c2", 3, K.CREDIT, "A", 3, amount=aed("500.00")))
        lg.submit(Event("d1", 3, K.DEBIT, "A", 2, amount=aed("150.00")))
        lg.close_day()
        fee = [e for e in lg.entries if e.kind is EntryKind.OVERDRAFT_FEE]
        self.assertEqual([(f.value_date, f.booked_day) for f in fee], [(2, 3)])

    def test_earlier_fee_counts_toward_later_days_balance(self):
        # Day 1 -10 -> fee -> -35; Day 2 credit 30 -> -5 only because of the fee.
        lg = Ledger({"A": AED})
        lg.submit(Event("d1", 1, K.DEBIT, "A", 1, amount=aed("10.00")))
        lg.close_day()
        lg.submit(Event("c1", 2, K.CREDIT, "A", 2, amount=aed("30.00")))
        lg.close_day()
        self.assertEqual(fees(lg), [(1, "-25.00"), (2, "-25.00")])

    def test_no_fee_without_a_same_currency_schedule(self):
        lg = Ledger({"B": BHD})
        lg.submit(Event("d1", 1, K.DEBIT, "B", 1, amount=Money.parse("1.000", BHD)))
        lg.close_day()
        lg.close_day()
        self.assertEqual(fees(lg, "B"), [])
        errors = [p for p in lg.problems if p.severity is Severity.ERROR]
        # One error per negative day, not repeated at every later EOD.
        self.assertEqual([(p.day, "Day 1" in p.message) for p in errors], [(1, True), (2, False)])


class Interest(unittest.TestCase):
    def run_window(self, lg):
        while not lg.closed:
            lg.close_day()

    def test_negative_and_zero_days_accrue_nothing(self):
        lg = Ledger({"A": AED})
        lg.submit(Event("d1", 1, K.DEBIT, "A", 1, amount=aed("10.00")))
        self.run_window(lg)
        self.assertEqual([lg.accrued("A", d).minor for d in lg.window()], [0] * 6)
        self.assertFalse(any(e.kind is EntryKind.INTEREST for e in lg.entries))

    def test_carry_forward_sum_equals_rounded_true_total(self):
        # 465.00 for six days: raw 0.186/day, true total 1.116 -> 1.12.
        # Rounding each day alone would give 6 x 0.19 = 1.14.
        lg = Ledger({"A": AED})
        lg.submit(Event("c1", 1, K.CREDIT, "A", 1, amount=aed("465.00")))
        self.run_window(lg)
        daily = [lg.accrued("A", d).minor for d in lg.window()]
        self.assertEqual(daily, [19, 18, 19, 18, 19, 19])
        self.assertEqual(sum(daily), 112)
        interest = [e for e in lg.entries if e.kind is EntryKind.INTEREST]
        self.assertEqual([(e.amount.minor, e.value_date) for e in interest], [(112, 6)])

    def test_restating_one_day_moves_accruals_on_untouched_days(self):
        # Pins the side effect described in tests/test_known_failure.py point 2.
        # Back-valued +15 on Day 2 and -15 on Day 3 change Day 2's balance only,
        # yet the carry-forward residue moves 0.01s around Days 3-5.
        lg = Ledger({"A": AED})
        lg.submit(Event("c1", 1, K.CREDIT, "A", 1, amount=aed("10.00")))
        for _ in range(3):
            lg.close_day()
        before = [lg.accrued("A", d).minor for d in (1, 2, 3)]
        lg.submit(Event("x1", 4, K.CREDIT, "A", 2, amount=aed("15.00")))
        lg.submit(Event("x2", 4, K.DEBIT, "A", 3, amount=aed("15.00")))
        self.run_window(lg)
        balances = [lg.closing_balance("A", d, exclude=(EntryKind.INTEREST,)).format() for d in lg.window()]
        self.assertEqual(balances, ["10.00", "25.00", "10.00", "10.00", "10.00", "10.00"])
        self.assertEqual(before, [0, 1, 0])
        self.assertEqual([lg.accrued("A", d).minor for d in lg.window()], [0, 1, 1, 0, 1, 0])

    def test_interest_is_not_compounded_inside_the_window(self):
        lg = Ledger({"A": AED})
        lg.submit(Event("c1", 1, K.CREDIT, "A", 1, amount=aed("1000.00")))
        self.run_window(lg)
        self.assertEqual(lg.closing_balance("A", 6), aed("1002.40"))  # 6 x 0.40

    def test_bhd_accrues_at_three_decimals(self):
        lg = Ledger({"B": BHD})
        lg.submit(Event("c1", 1, K.CREDIT, "B", 1, amount=Money.parse("1.250", BHD)))
        self.run_window(lg)
        # raw 0.0005/day -> cumulative 0.0005, 0.0010, ... rounds to 0.003 total.
        self.assertEqual(lg.closing_balance("B", 6), Money.parse("1.253", BHD))

    def test_rate_is_a_rule_not_a_literal(self):
        lg = Ledger({"A": AED}, Rules(daily_rate=Decimal("0.0002")))
        lg.submit(Event("c1", 1, K.CREDIT, "A", 1, amount=aed("1000.00")))
        self.run_window(lg)
        self.assertEqual(lg.closing_balance("A", 6), aed("1001.20"))

    def test_raw_interest_arithmetic_refuses_to_round_silently(self):
        # Guard, not a scenario: squeeze the Decimal context so the raw product
        # cannot be held exactly. The accrual must raise, not quietly round.
        from decimal import Inexact, localcontext

        lg = Ledger({"A": AED})
        lg.submit(Event("c1", 1, K.CREDIT, "A", 1, amount=aed("123,456.78")))
        with localcontext() as ctx:
            ctx.prec = 6
            ctx.traps[Inexact] = False
            with self.assertRaises(Inexact):
                lg.accrual_schedule("A", 1)
        self.assertEqual(lg.accrual_schedule("A", 1)[1], aed("49.38"))

    def test_window_closes_after_last_day(self):
        lg = Ledger({"A": AED})
        self.run_window(lg)
        with self.assertRaises(WindowClosed):
            lg.submit(Event("c1", 6, K.CREDIT, "A", 6, amount=aed("1.00")))
        with self.assertRaises(WindowClosed):
            lg.close_day()


if __name__ == "__main__":
    unittest.main()
