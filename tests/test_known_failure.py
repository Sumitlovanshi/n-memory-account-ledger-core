"""THE ONE FAILING TEST — written against my own design, left red on purpose.

It is not marked @expectedFailure: the brief asks for a failing test, and an
expected-failure marker would turn it green and hide it in the summary line.
Run the green suite without it with:  python3 -m unittest tests.test_money \
tests.test_postings tests.test_end_of_day tests.test_scenario
"""
import unittest
from decimal import Decimal

from ledger.engine import EntryKind, Ledger
from ledger.money import Money, round_minor
from ledger.replay import replay
from ledger.scenario import ACCOUNTS, EVENTS


class DailyAccrualAudit(unittest.TestCase):
    def test_each_days_accrual_can_be_checked_from_that_days_balance_alone(self):
        # The property an auditor or customer will reach for first: "interest for
        # day d is round(closing balance of day d x 0.04 %)". You should be able
        # to tick off any single statement line with a calculator.
        ledger = Ledger(ACCOUNTS)
        replay(EVENTS, ledger)
        currency = ACCOUNTS["ACC-001"]

        expected, actual = [], []
        for d in ledger.window():
            base = ledger.closing_balance("ACC-001", d, exclude=(EntryKind.INTEREST,))
            raw = Decimal(base.minor) * ledger.rules.daily_rate if base.is_positive else Decimal(0)
            expected.append(Money(currency, round_minor(raw)).format())
            actual.append(ledger.accrued("ACC-001", d).format())

        # FAILS on Day 5:  expected 0.16, ledger says 0.15.
        #   expected: ['0.10', '0.09', '0.25', '0.17', '0.16', '0.16']   sum 0.93
        #   actual:   ['0.10', '0.09', '0.25', '0.17', '0.15', '0.16']   sum 0.92
        #
        # WHY: the ledger uses carry-forward rounding. Day d accrues
        # round(cumulative raw to d) - round(cumulative raw to d-1). By the end of
        # Day 4 the true cumulative is 0.606, booked as 0.61 — 0.004 ahead. Day 5's
        # raw 0.156 brings the cumulative to 0.762, booked 0.76, so Day 5 gets
        # 0.76 - 0.61 = 0.15. Day 5 is "paying back" Day 4's rounding.
        #
        # WHAT IT REVEALS:
        # 1. A day's accrual is not a function of that day's balance. It depends on
        #    the rounding residue of every earlier day, so no single statement line
        #    is verifiable on its own. A customer recomputing Day 5 will find 0.01
        #    "missing" and they will be right by the obvious rule.
        # 2. Restatements ripple further than the balance change. A back-valued
        #    entry that moves Day 2's residue can shift +/-0.01 between later days
        #    whose balances did not change at all, producing adjustment records
        #    that the balance history does not explain. (In this stream E7/E9 touch
        #    every later day anyway, which hides it; pinned on a synthetic stream in
        #    tests/test_end_of_day.py::Interest::test_restating_one_day_moves_...)
        # 3. The non-negotiable rule is satisfied *because* of this: the rounded
        #    days sum to 0.92 = capitalized = round(true 0.918). Making this test
        #    pass (round each day alone) capitalizes 0.93 — overpaying 0.012 AED,
        #    with error that grows with window length — and on a BHD 1.250 balance
        #    (0.5 fils/day, an exact half-even tie) pays 0.000 instead of 0.003.
        #    See tests/test_end_of_day.py::Interest.
        #
        # DECISION: keep carry-forward; keep this test red as a standing
        # disclosure. The real fix is presentational, not arithmetic: statements
        # should print the cumulative column (0.10, 0.19, 0.44, 0.61, 0.76, 0.92)
        # so every line is checkable as a difference of two rounded cumulatives.
        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
