"""The brief's E1..E10 stream, replayed end to end.

One test class per acceptance criterion. Criteria 2, 6, 7 and 8 are rejected
(see REJECTED.md); their tests assert what the ledger does instead and why the
criterion as written cannot hold.
"""
import unittest
from decimal import Decimal

from ledger.engine import AuthState, EntryKind, Ledger, Outcome, Severity
from ledger.money import AED, BHD, Money, round_minor
from ledger.replay import replay
from ledger.report import render_day, render_summary
from ledger.scenario import ACCOUNTS, EVENTS


def aed(text):
    return Money.parse(text, AED)


def bhd(text):
    return Money.parse(text, BHD)


def run(events=EVENTS, before_close=None):
    ledger = Ledger(ACCOUNTS)
    reports = replay(events, ledger, before_close)
    return ledger, reports


def without(*ids):
    return tuple(e for e in EVENTS if e.id not in ids)


def fees(ledger, account="ACC-001"):
    return [e for e in ledger.entries if e.kind is EntryKind.OVERDRAFT_FEE and e.account == account]


def account_close(report, account):
    return next(a for a in report.accounts if a.account == account)


class Criterion1_Day2ClosingAtEndOfDay5(unittest.TestCase):
    """ACCEPTED: Day 2 closing, evaluated at end of Day 5 before any fee, is -370.00."""

    def test_day2_is_minus_370_before_the_day5_fee_run(self):
        seen = {}

        def probe(day, ledger):
            if day == 5:
                seen["day2"] = ledger.closing_balance("ACC-001", 2)
                seen["fees"] = len(fees(ledger))

        run(before_close=probe)
        self.assertEqual(seen["day2"], aed("-370.00"))
        self.assertEqual(seen["fees"], 0)

    def test_day5_report_shows_the_same_pre_fee_figure(self):
        _, reports = run()
        row = account_close(reports[4], "ACC-001").restated[1]
        self.assertEqual((row.day, row.before), (2, aed("-370.00")))


class Criterion2_E7FeeCount(unittest.TestCase):
    """REJECTED: 'E7 causes exactly one overdraft fee, on Day 2'. It causes three."""

    def test_e7_causes_fees_on_days_2_4_and_5(self):
        ledger, _ = run()
        self.assertEqual([(f.value_date, f.amount) for f in fees(ledger)],
                         [(2, aed("-25.00")), (4, aed("-25.00")), (5, aed("-25.00"))])
        self.assertEqual({f.booked_day for f in fees(ledger)}, {5})

    def test_without_e7_there_are_no_fees_at_all(self):
        # Counterfactual: drop E7 and its reversal E9. Every fee is attributable to E7.
        ledger, _ = run(without("E7", "E9"))
        self.assertEqual(fees(ledger), [])

    def test_day4_goes_negative_even_if_the_day2_fee_were_ignored(self):
        # 1200 - 950 - 620 + 400 - 185 = -155: Day 4 is negative on E7 alone.
        seen = {}
        run(before_close=lambda d, lg: seen.setdefault(d, lg.closing_balance("ACC-001", 4)))
        self.assertEqual(seen[5], aed("-155.00"))


class Criterion3_AuthASettlement(unittest.TestCase):
    """ACCEPTED: the Day 4 settlement of Auth-A must be accepted."""

    def test_e5_posts_185_and_releases_the_whole_200_hold(self):
        ledger, reports = run()
        e5 = next(r for r in ledger.journal if r.event.id == "E5")
        self.assertIs(e5.outcome, Outcome.POSTED)
        entry = next(e for e in ledger.entries if e.source == "E5")
        self.assertEqual((entry.amount, entry.value_date), (aed("-185.00"), 4))
        self.assertIs(ledger.auth_state("Auth-A"), AuthState.SETTLED)
        self.assertEqual(account_close(reports[3], "ACC-001").holds, aed("0.00"))

    def test_settlement_stands_although_restated_day2_would_have_declined_auth_a(self):
        # At EOD 5 Day 2 restates to -395.00; 200.00 would not have been approved
        # on that balance. Approvals are decisions taken on what was known; they
        # are not retroactively revoked, and the settlement is not unwound.
        ledger, reports = run()
        self.assertEqual(account_close(reports[4], "ACC-001").restated[1].after, aed("-395.00"))
        self.assertIs(ledger.auth_state("Auth-A"), AuthState.SETTLED)
        self.assertFalse(any(e.reverses == "E5" for e in ledger.entries))


class Criterion4_UnknownAuthorization(unittest.TestCase):
    """ACCEPTED: a settlement for an authorization not in the ledger is rejected; no funds leave."""

    def test_e6_is_rejected_journaled_and_posts_nothing(self):
        ledger, reports = run()
        e6 = next(r for r in ledger.journal if r.event.id == "E6")
        self.assertIs(e6.outcome, Outcome.REJECTED)
        self.assertFalse(any(e.source == "E6" for e in ledger.entries))
        self.assertEqual(account_close(reports[3], "ACC-001").ledger, aed("465.00"))

    def test_e6_is_reported_as_an_error_on_day_4(self):
        _, reports = run()
        errors = [(r.day, p.source) for r in reports for p in r.problems if p.severity is Severity.ERROR]
        self.assertEqual(errors, [(4, "E6")])

    def test_auth_z_is_not_treated_as_an_authorization(self):
        ledger, _ = run()
        self.assertIsNone(ledger.auth_state("Auth-Z"))
        self.assertEqual(ledger.auth_ids(), ["Auth-A", "Auth-B"])


class Criterion5_AuthBHold(unittest.TestCase):
    """ACCEPTED, but vacuous here: 'if Auth-B is approved...' — it is not approved.
    The hold property itself is checked on Auth-A (and in test_postings)."""

    def test_auth_b_is_declined_and_places_no_hold(self):
        ledger, _ = run()
        e8 = next(r for r in ledger.journal if r.event.id == "E8")
        self.assertIs(e8.outcome, Outcome.DECLINED)
        self.assertIn("= -245.00", e8.detail)
        self.assertFalse(any(h.auth_id == "Auth-B" for h in ledger.holds))
        self.assertIs(ledger.auth_state("Auth-B"), AuthState.DECLINED)

    def test_auth_a_hold_reduced_available_not_ledger(self):
        _, reports = run()
        day2 = account_close(reports[1], "ACC-001")
        self.assertEqual((day2.ledger, day2.holds, day2.available),
                         (aed("250.00"), aed("200.00"), aed("50.00")))


class Criterion6_ReversalRestoresEverything(unittest.TestCase):
    """REJECTED: 'after E9, all balances and fees return to their pre-E7 values'."""

    def test_e7_and_e9_both_remain_and_fees_are_not_undone(self):
        ledger, _ = run()
        ids = [e.id for e in ledger.entries]
        self.assertIn("E7", ids)
        self.assertIn("E9", ids)
        self.assertEqual(len(fees(ledger)), 3)

    def test_balances_end_75_10_below_the_no_e7_counterfactual(self):
        actual, _ = run()
        never, _ = run(without("E7", "E9"))
        gap = [
            (never.closing_balance("ACC-001", d) - actual.closing_balance("ACC-001", d)).format()
            for d in actual.window()
        ]
        # 25.00 per fee from its value day on, plus 0.10 less interest by Day 6.
        self.assertEqual(gap, ["0.00", "25.00", "25.00", "50.00", "75.00", "75.10"])

    def test_auth_b_decline_is_not_undone(self):
        actual, _ = run()
        never, _ = run(without("E7", "E9"))
        self.assertIs(never.auth_state("Auth-B"), AuthState.ACTIVE)
        self.assertIs(actual.auth_state("Auth-B"), AuthState.DECLINED)


class Criterion7_BhdInstalments(unittest.TestCase):
    """REJECTED: 'each instalment must be BHD 3.334' — that credits 10.002."""

    def test_instalments_conserve_the_instructed_total(self):
        ledger, _ = run()
        parts = [e.amount for e in ledger.entries if e.source == "E10"]
        self.assertEqual(parts, [bhd("3.334"), bhd("3.333"), bhd("3.333")])
        self.assertEqual(sum(p.minor for p in parts), bhd("10.000").minor)
        self.assertEqual({e.value_date for e in ledger.entries if e.source == "E10"}, {5})

    def test_criterion_as_written_would_mint_two_fils(self):
        self.assertEqual(3 * bhd("3.334").minor - bhd("10.000").minor, 2)


class Criterion8_AccrualRemainder(unittest.TestCase):
    """REJECTED: 'if rounded accruals do not sum to the capitalized total, the
    remainder is discarded'. The design makes that case impossible."""

    def test_rounded_daily_accruals_sum_exactly_to_each_capitalization(self):
        ledger, _ = run()
        for account in ACCOUNTS:
            daily = sum(ledger.accrued(account, d).minor for d in ledger.window())
            credit = [e for e in ledger.entries if e.account == account and e.kind is EntryKind.INTEREST]
            self.assertEqual([c.amount.minor for c in credit], [daily], account)

    def test_capitalized_total_is_the_correctly_rounded_true_total(self):
        ledger, _ = run()
        for account, expected in (("ACC-001", aed("0.92")), ("ACC-002", bhd("0.008"))):
            raw = sum(
                Decimal(max(ledger.closing_balance(account, d, exclude=(EntryKind.INTEREST,)).minor, 0))
                * ledger.rules.daily_rate
                for d in ledger.window()
            )
            self.assertEqual(Money(expected.currency, round_minor(raw)), expected)
            self.assertEqual(sum((ledger.accrued(account, d) for d in ledger.window()), Money.zero(expected.currency)), expected)


class DayByDay(unittest.TestCase):
    """What the per-day printout says, pinned."""

    def setUp(self):
        self.ledger, self.reports = run()

    def test_closing_ledger_balance_as_known_at_each_eod(self):
        self.assertEqual(
            [account_close(r, "ACC-001").ledger.format() for r in self.reports],
            ["250.00", "250.00", "650.00", "465.00", "-230.00", "390.92"],
        )
        self.assertEqual(
            [account_close(r, "ACC-002").ledger.format() for r in self.reports],
            ["0.000", "0.000", "0.000", "0.000", "0.000", "10.008"],
        )

    def test_restated_closing_balance_by_value_day(self):
        self.assertEqual(
            [self.ledger.closing_balance("ACC-001", d).format() for d in self.ledger.window()],
            ["250.00", "225.00", "625.00", "415.00", "390.00", "390.92"],
        )
        self.assertEqual(
            [self.ledger.closing_balance("ACC-002", d).format() for d in self.ledger.window()],
            ["0.000", "0.000", "0.000", "0.000", "10.000", "10.008"],
        )

    def test_fee_assessments_per_eod(self):
        self.assertEqual([[f.id for f in r.fees] for r in self.reports],
                         [[], [], [], [], ["FEE-ACC-001-D2", "FEE-ACC-001-D4", "FEE-ACC-001-D5"], []])

    def test_authorization_states_per_eod(self):
        self.assertEqual(
            [[(a.auth_id, a.state.value) for a in r.auths] for r in self.reports],
            [
                [],
                [("Auth-A", "ACTIVE")],
                [("Auth-A", "ACTIVE")],
                [("Auth-A", "SETTLED")],
                [("Auth-A", "SETTLED"), ("Auth-B", "DECLINED")],
                [("Auth-A", "SETTLED"), ("Auth-B", "DECLINED")],
            ],
        )

    def test_daily_accruals(self):
        self.assertEqual([self.ledger.accrued("ACC-001", d).format() for d in self.ledger.window()],
                         ["0.10", "0.09", "0.25", "0.17", "0.15", "0.16"])
        self.assertEqual([self.ledger.accrued("ACC-002", d).format() for d in self.ledger.window()],
                         ["0.000", "0.000", "0.000", "0.000", "0.004", "0.004"])

    def test_e10_is_a_late_arrival_processed_on_day_6(self):
        e10 = next(r for r in self.ledger.journal if r.event.id == "E10")
        self.assertEqual((e10.event.day, e10.processed_day, e10.event.value_date), (5, 6, 5))
        notices = [p.message for p in self.reports[5].problems if p.source == "E10"]
        self.assertTrue(any(m.startswith("late arrival") for m in notices))

    def test_output_is_deterministic(self):
        def render():
            ledger, reports = run()
            return "\n".join(render_day(r) for r in reports) + render_summary(ledger)

        self.assertEqual(render(), render())


class AppendOnly(unittest.TestCase):
    """The ledger is append-only: every store at any moment is a prefix of itself later."""

    def test_every_store_only_ever_grows_by_appending(self):
        ledger = Ledger(ACCOUNTS)
        snapshots = []

        def snap():
            snapshots.append((ledger.journal, ledger.entries, ledger.holds, ledger.accruals, ledger.problems))

        for event in EVENTS:
            while ledger.current_day < event.day:
                ledger.close_day()
                snap()
            ledger.submit(event)
            snap()
        while not ledger.closed:
            ledger.close_day()
            snap()

        for earlier, later in zip(snapshots, snapshots[1:]):
            for before, after in zip(earlier, later):
                self.assertEqual(after[: len(before)], before)
        self.assertEqual(len(snapshots), 16)  # 10 events + 6 EODs

    def test_reversal_and_restatement_add_records_instead_of_editing(self):
        ledger, _ = run()
        e7 = next(e for e in ledger.entries if e.id == "E7")
        self.assertEqual((e7.amount, e7.value_date, e7.booked_day), (aed("-620.00"), 2, 5))
        clawbacks = [a for a in ledger.accruals if a.adjustment and a.amount.is_negative]
        self.assertEqual([(a.for_day, a.amount.format()) for a in clawbacks],
                         [(2, "-0.10"), (3, "-0.26"), (4, "-0.19")])


if __name__ == "__main__":
    unittest.main()
