# WORKLOG

Times are local (IST, UTC+05:30), taken from `date` on the build machine at the
moment each entry was written. Entries are appended, never edited — the same rule
the ledger follows.

## 2026-10-18

**22:18–22:27 — Read the brief, traced the stream by hand before writing code.**
Folder created 22:18. Hand trace of ACC-001 by value date, with everything known
at end of Day 5 (E1, E2, E4, E5, E7; E6 rejected):

| value day | entries                | pre-fee close |
|-----------|------------------------|---------------|
| 1         | +1200.00 −950.00       | 250.00        |
| 2         | −620.00 (E7)           | −370.00       |
| 3         | +400.00                | 30.00         |
| 4         | −185.00 (Auth-A)       | −155.00       |
| 5         | —                      | −155.00       |

Things that fell out of the trace and shaped the design:
- E7 is booked Day 5 but value-dated Day 2, so the fee rule (defined on value
  date) has to look *backwards* at EOD, not just at "today".
- E7 makes Day 4 negative as well as Day 2, so acceptance criterion 2
  ("exactly one fee") is already in trouble.
- Auth-B (E8) is checked against −155.00, so it is declined. Criterion 5 is a
  conditional whose premise never comes true in this stream.
- 10.000 BHD / 3 is not representable at 3 dp. 3 × 3.334 = 10.002 (criterion 7
  mints 0.002 BHD).
- E10 is stamped Day 5 but listed after E9 (Day 6). The brief says "replayed in
  this order", so it is a late arrival, not a typo to sort away.

**22:27 — Toolchain check.** Python 3.9.6 (macOS system Python), git 2.50.1.
Decision: Python stdlib only (`decimal`, `dataclasses`, `unittest`) so the suite
runs with nothing installed. 3.9 means no `match`, no `slots=True`; use
`from __future__ import annotations` for `X | None` hints.

**22:27 — `git init -b main`.** Local only, no remote, per request.

**22:28 — Money as integer minor units.** `ledger/money.py`: `Money(currency, minor:int)`.
Chose ints over `Decimal` amounts so ledger arithmetic cannot round at all;
the only rounding call in the codebase will be `round_minor` for interest.
`Money.parse` raises on excess decimals (`"3.3334"` BHD) rather than rounding
— a silent round at the input boundary is how 0.002 BHD gets minted.
`allocate()` hands leftover minor units to the earliest parts:
10.000 BHD / 3 → 3.334, 3.333, 3.333. Event model + the E1..E10 stream
transcribed in `ledger/scenario.py` in the brief's order. 10 money tests green.

**22:31 — Engine: postings, authorizations, settlements, reversals.** `ledger/engine.py`.
Five append-only stores (journal, entries, holds, accruals, problems), private
lists exposed only as tuples. Two decisions made while writing it:
- Authorization state is *derived* (journal outcome + PLACE/RELEASE hold log),
  not a field that flips from ACTIVE to SETTLED. A mutable status field would
  have been the first "record mutated" in an append-only ledger.
- Every inbound event gets a journal record, including rejected ones — Auth-Z's
  settlement must be visible as "received and refused", not silently absent.
Settlement releases the whole hold (final settlement); over-settlement rejected
because no tolerance is given. 19 single-day unit tests green on first run.
EOD processing (fees, interest) not written yet.

**22:32 — End of day: fees, interest, capitalization.** `Ledger.close_day()`.
- Fees: every EOD re-walks Days 1..today in ascending order by value date, so a
  back-valued entry is caught on the EOD after it arrives. Fee id
  `FEE-<acct>-D<d>` with value_date d, booked_day = the EOD that found it.
  An existing fee for (account, d) blocks any second one.
- BHD has no fee in its own currency and no FX rate is given → ERROR, no fee.
  Charging "25.000 BHD" would be ~10x the AED fee in value.
- Interest: schedule recomputed from value-dated balances at every EOD with
  carry-forward rounding; differences appended as adjustment records.
  Capitalization asserts per-day net == schedule == credit, raises otherwise.
First smoke run of E1..E10 matched the hand trace: EOD5 ACC-001 −230.00 with
fees for D2, D4, D5; final 390.92 (0.92 interest); ACC-002 10.008.
Accrual trace for ACC-001 shows the Day 5 restatement claw-back
(D2 −0.10, D3 −0.26, D4 −0.19) and the Day 6 re-accrual after E9. 12 EOD tests green.

**22:33 — Replay driver and per-day report.** `python3 -m ledger`.
The driver owns the clock and closes every day before an event stamped for a
later day. E10 is *not* re-sorted: it is submitted while Day 6 is open, keeps
its Day 5 stamp and value date, and the ledger raises a late-arrival notice.
Each day prints events + outcomes, errors, notices, fees assessed in that EOD
run, authorization states, and for each account the value-date closing table
with a "was X" column whenever a back-valued entry restated a day that had
already been reported. End-of-window summary shows the restated view, the
accrual reconciliation, and every ledger entry in append order.
First full run reads correctly; renamed "before fees" column to "before EOD"
after seeing Day 6 (before 390.00, after 390.92 — that delta is capitalization,
not a fee) and added an interest-base column so the 390.00 base is visible.

**22:34 — Acceptance tests for the full stream.** `tests/test_scenario.py`, one
class per brief criterion plus day-by-day pins and an append-only prefix test
(16 snapshots: 10 submits + 6 EODs; every store at every snapshot is a prefix
of itself at the next). 28 tests, all green on first run — which made me
distrust them, so I mutation-checked with a throwaway script (not committed):
- fees evaluated for "today" only (no back-valuation) → 12 failures.
- independent per-day rounding instead of carry-forward → 6 failures.
Unexpected find from the second mutation: a BHD 1.250 balance accrues exactly
0.5 fils/day. Rounded per day with half-even that is 0.000 every day → zero
interest against a true 0.003. Carry-forward gives 0.003. Strongest argument
yet for carry-forward; goes in NUMBERS.md.
Counterfactual (no E7/E9) vs actual end state: 0.00 / 25.00 / 25.00 / 50.00 /
75.00 / 75.10 by value day — the 75.10 is three fees plus 0.10 lost interest.
In that counterfactual Auth-B is *approved* (465.00 − 90.00 ≥ 0).

**22:36 — The one failing test.** `tests/test_known_failure.py`. Considered four
candidates against my own design:
(a) reversal does not make the customer whole (fees stay) — rejected as the
    pick because it is just criterion 6 restated, and I argue 6 is wrong;
(b) as-at Day 5 report differs from the restated view — inherent, not a flaw;
(c) fee-on-fee cascade (a fee > 30.00 would make Day 3 negative and charge
    again) — real, but needs a synthetic stream to show;
(d) a day's interest is not reproducible from that day's balance — real, on
    the brief's own data, and caused by a choice I made (carry-forward).
Picked (d). Fails on Day 5: ledger 0.15, per-day rule 0.16. Not marked
`@expectedFailure` — that would turn it green. Annotation claim 2 (a
restatement can move 0.01s between days whose balances did not change) was a
hunch when I wrote it; checked it on a synthetic stream before committing —
true: restating only Day 2 moved Days 3/4/5 from [0,1,0] to [1,0,1] fils.
Pinned that as a passing test. Suite: 71 tests, 1 failure (the intended one);
the other 70 pass.

**22:37 — Sensitivity runs for NUMBERS.md; found and closed a silent-rounding gap.**
Wrote a throwaway script that replays the stream with each constant changed
(not committed; results copied into NUMBERS.md). Notable: the fee has a cliff
at exactly 30.00 → 30.01 — above it the Day 2 fee alone drags Day 3 below zero
(30.00 − fee) and a fourth fee is charged. At 25.00 the margin is 5.00.
While writing the Decimal-precision line I realised the raw-interest multiply
used whatever Decimal context the caller had, and would round *silently* if
that context ran short of digits. That is exactly the "no rounding except at
round_minor" promise broken. Wrapped the multiply/accumulate in a local
context that traps `Inexact`, plus a guard test that squeezes precision to 6
and expects a raise. 72 tests, 1 failure (the intended one).

**22:41 — NUMBERS, AMBIGUITIES, REJECTED, README.**
- NUMBERS.md: 15 constants. Each "at half" figure was taken from the
  sensitivity replay, not estimated. One I had not thought about until I
  halved it: a back-valuation cap at half the window (3 days) admits E7
  (3 days back) but rejects E9 (4 days back), which would leave the customer
  permanently 620.00 down. Recorded as the reason for "no cap".
- AMBIGUITIES.md: 45 items in 8 sections (time/order, fees, interest,
  authorizations, reversal, instalments, append-only, criterion wording).
- REJECTED.md: refuses criteria 2, 6, 7, 8 with the arithmetic; accepts 1, 3,
  4 (caveat: real schemes force-post unmatched clearing) and 5 (true but
  vacuous — Auth-B is declined); 3 approaches abandoned mid-build, 9 at
  design time, each labelled as such.
- Verified every test name cited in the docs exists (scripted grep) and the
  README's counts against a real run: 72 tests, 1 failure; 71 green without it.

**22:41 — Final verification.** Fresh `git clone` of the repo into a scratch
directory: `python3 -m ledger` prints the same report, and `python3 -m unittest`
gives 72 tests, 1 failure (the intended one). Working tree clean, no remote
configured (kept local as asked).
Correction to the previous entry (appended, not edited — same rule as the
ledger): AMBIGUITIES.md has **46** items, not 45. I miscounted by hand;
`grep -cE '^\*\*[A-H][0-9]+\.' AMBIGUITIES.md` → 46.
Elapsed: about 22:18 → 22:41.
