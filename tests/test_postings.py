"""Single-day unit tests for postings, authorizations, settlements, reversals.
Everything here happens on Day 1 so no end-of-day processing is involved."""
import unittest
from dataclasses import FrozenInstanceError

from ledger.engine import AuthState, Ledger, Outcome, Severity
from ledger.events import Event, EventKind
from ledger.money import AED, BHD, Money

K = EventKind


def aed(text):
    return Money.parse(text, AED)


def new_ledger():
    return Ledger({"A": AED, "B": BHD})


def credit(ledger, eid, amount, value_date=1):
    return ledger.submit(Event(eid, 1, K.CREDIT, "A", value_date, amount=aed(amount)))


class Postings(unittest.TestCase):
    def test_credit_and_debit_move_ledger_balance(self):
        lg = new_ledger()
        credit(lg, "c1", "100.00")
        lg.submit(Event("d1", 1, K.DEBIT, "A", 1, amount=aed("30.00")))
        self.assertEqual(lg.closing_balance("A", 1), aed("70.00"))

    def test_booked_debit_may_overdraw(self):
        # Only authorizations are gated on available balance.
        lg = new_ledger()
        r = lg.submit(Event("d1", 1, K.DEBIT, "A", 1, amount=aed("30.00")))
        self.assertIs(r.outcome, Outcome.POSTED)
        self.assertEqual(lg.closing_balance("A", 1), aed("-30.00"))

    def test_rejections_are_journaled_not_dropped(self):
        lg = new_ledger()
        r = lg.submit(Event("x", 1, K.CREDIT, "A", 1, amount=Money.parse("1.000", BHD)))
        self.assertIs(r.outcome, Outcome.REJECTED)
        self.assertEqual(len(lg.journal), 1)
        self.assertEqual(lg.entries, ())
        self.assertEqual([p.severity for p in lg.problems], [Severity.ERROR])

    def test_duplicate_event_id_is_rejected(self):
        lg = new_ledger()
        credit(lg, "c1", "10.00")
        r = credit(lg, "c1", "10.00")
        self.assertIs(r.outcome, Outcome.REJECTED)
        self.assertEqual(lg.closing_balance("A", 1), aed("10.00"))

    def test_value_date_outside_window_is_rejected(self):
        lg = new_ledger()
        r = credit(lg, "c1", "10.00", value_date=7)
        self.assertIs(r.outcome, Outcome.REJECTED)

    def test_entries_are_immutable_and_views_are_copies(self):
        lg = new_ledger()
        credit(lg, "c1", "10.00")
        with self.assertRaises(FrozenInstanceError):
            lg.entries[0].amount = aed("99.00")
        with self.assertRaises(AttributeError):
            lg.entries.append(None)


class Authorizations(unittest.TestCase):
    def test_hold_reduces_available_but_not_ledger(self):
        # The property in acceptance criterion 5, exercised on an approval that happens.
        lg = new_ledger()
        credit(lg, "c1", "100.00")
        r = lg.submit(Event("a1", 1, K.AUTHORIZATION, "A", 1, amount=aed("60.00"), auth_id="X"))
        self.assertIs(r.outcome, Outcome.APPROVED)
        self.assertEqual(lg.closing_balance("A", 1), aed("100.00"))
        self.assertEqual(lg.available_balance("A"), aed("40.00"))
        self.assertIs(lg.auth_state("X"), AuthState.ACTIVE)

    def test_available_exactly_zero_is_approved(self):
        lg = new_ledger()
        credit(lg, "c1", "100.00")
        r = lg.submit(Event("a1", 1, K.AUTHORIZATION, "A", 1, amount=aed("100.00"), auth_id="X"))
        self.assertIs(r.outcome, Outcome.APPROVED)
        self.assertEqual(lg.available_balance("A"), aed("0.00"))

    def test_one_fils_short_is_declined_and_places_no_hold(self):
        lg = new_ledger()
        credit(lg, "c1", "100.00")
        r = lg.submit(Event("a1", 1, K.AUTHORIZATION, "A", 1, amount=aed("100.01"), auth_id="X"))
        self.assertIs(r.outcome, Outcome.DECLINED)
        self.assertEqual(lg.holds, ())
        self.assertIs(lg.auth_state("X"), AuthState.DECLINED)
        # A decline is a business outcome, not an error.
        self.assertEqual(lg.problems, ())

    def test_existing_holds_count_against_new_authorizations(self):
        lg = new_ledger()
        credit(lg, "c1", "100.00")
        lg.submit(Event("a1", 1, K.AUTHORIZATION, "A", 1, amount=aed("60.00"), auth_id="X"))
        r = lg.submit(Event("a2", 1, K.AUTHORIZATION, "A", 1, amount=aed("50.00"), auth_id="Y"))
        self.assertIs(r.outcome, Outcome.DECLINED)


class Settlements(unittest.TestCase):
    def setUp(self):
        self.lg = new_ledger()
        credit(self.lg, "c1", "100.00")
        self.lg.submit(Event("a1", 1, K.AUTHORIZATION, "A", 1, amount=aed("60.00"), auth_id="X"))

    def settle(self, eid, amount, auth_id="X"):
        return self.lg.submit(
            Event(eid, 1, K.SETTLEMENT, "A", 1, amount=aed(amount), auth_id=auth_id)
        )

    def test_under_settlement_posts_amount_and_releases_whole_hold(self):
        r = self.settle("s1", "55.00")
        self.assertIs(r.outcome, Outcome.POSTED)
        self.assertEqual(self.lg.closing_balance("A", 1), aed("45.00"))
        self.assertEqual(self.lg.active_holds("A"), aed("0.00"))
        self.assertIs(self.lg.auth_state("X"), AuthState.SETTLED)

    def test_unknown_authorization_is_rejected_and_moves_no_funds(self):
        r = self.settle("s1", "10.00", auth_id="nope")
        self.assertIs(r.outcome, Outcome.REJECTED)
        self.assertEqual(self.lg.closing_balance("A", 1), aed("100.00"))
        self.assertEqual(self.lg.active_holds("A"), aed("60.00"))

    def test_second_settlement_is_rejected(self):
        self.settle("s1", "55.00")
        r = self.settle("s2", "5.00")
        self.assertIs(r.outcome, Outcome.REJECTED)

    def test_over_settlement_is_rejected(self):
        r = self.settle("s1", "60.01")
        self.assertIs(r.outcome, Outcome.REJECTED)
        self.assertIs(self.lg.auth_state("X"), AuthState.ACTIVE)

    def test_settling_a_declined_authorization_is_rejected(self):
        self.lg.submit(Event("a2", 1, K.AUTHORIZATION, "A", 1, amount=aed("500.00"), auth_id="Y"))
        r = self.settle("s1", "1.00", auth_id="Y")
        self.assertIs(r.outcome, Outcome.REJECTED)


class Reversals(unittest.TestCase):
    def test_reversal_appends_a_compensating_entry(self):
        lg = new_ledger()
        lg.submit(Event("d1", 1, K.DEBIT, "A", 1, amount=aed("30.00")))
        r = lg.submit(Event("r1", 1, K.REVERSAL, "A", 1, reverses="d1"))
        self.assertIs(r.outcome, Outcome.POSTED)
        self.assertEqual([e.id for e in lg.entries], ["d1", "r1"])
        self.assertEqual(lg.entries[1].reverses, "d1")
        self.assertEqual(lg.closing_balance("A", 1), aed("0.00"))

    def test_double_reversal_is_rejected(self):
        lg = new_ledger()
        lg.submit(Event("d1", 1, K.DEBIT, "A", 1, amount=aed("30.00")))
        lg.submit(Event("r1", 1, K.REVERSAL, "A", 1, reverses="d1"))
        r = lg.submit(Event("r2", 1, K.REVERSAL, "A", 1, reverses="d1"))
        self.assertIs(r.outcome, Outcome.REJECTED)

    def test_reversing_something_that_never_posted_is_rejected(self):
        lg = new_ledger()
        lg.submit(Event("a1", 1, K.AUTHORIZATION, "A", 1, amount=aed("1.00"), auth_id="X"))
        self.assertIs(lg.submit(Event("r1", 1, K.REVERSAL, "A", 1, reverses="a1")).outcome, Outcome.REJECTED)
        self.assertIs(lg.submit(Event("r2", 1, K.REVERSAL, "A", 1, reverses="zz")).outcome, Outcome.REJECTED)

    def test_reversing_an_instalment_credit_reverses_every_instalment(self):
        lg = new_ledger()
        lg.submit(Event("c1", 1, K.CREDIT, "B", 1, amount=Money.parse("10.000", BHD), instalments=3))
        lg.submit(Event("r1", 1, K.REVERSAL, "B", 1, reverses="c1"))
        self.assertEqual(lg.closing_balance("B", 1), Money(BHD, 0))
        self.assertEqual(len(lg.entries), 6)


if __name__ == "__main__":
    unittest.main()
