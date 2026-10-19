# account-ledger

An in-memory account ledger core in Python. There is no web layer, persistence, UI or
database. It replays the brief's six-day event stream (E1..E10, two accounts) and prints,
for each day: the closing ledger balance, fee assessments, authorization states and
errors.

* Python **3.9+**, **standard library only**. Nothing to install.
* Local repository; no remote is configured.

## Run it

Replay the stream and print every day, then the end-of-window summary:

```bash
python3 -m ledger
```

Run the full test suite. It reports **72 tests, 1 failure**. The failure is
intentional (see "The failing test" below):

```bash
python3 -m unittest -v
```

Run everything except the intentional failure (71 tests, all pass):

```bash
python3 -m unittest tests.test_money tests.test_postings tests.test_end_of_day tests.test_scenario
```

## Results at a glance

| | D1 | D2 | D3 | D4 | D5 | D6 |
|---|---|---|---|---|---|---|
| ACC-001 closing, **as known that day** | 250.00 | 250.00 | 650.00 | 465.00 | −230.00 | 390.92 |
| ACC-001 closing, **restated at end** | 250.00 | 225.00 | 625.00 | 415.00 | 390.00 | 390.92 |
| ACC-001 overdraft fee (value day) | | 25.00 | | 25.00 | 25.00 | |
| ACC-001 interest accrual | 0.10 | 0.09 | 0.25 | 0.17 | 0.15 | 0.16 → **0.92** capitalized |
| ACC-002 closing, as known that day | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 10.008 |
| ACC-002 closing, restated | 0.000 | 0.000 | 0.000 | 0.000 | 10.000 | 10.008 |
| Authorizations | | Auth-A ACTIVE | Auth-A ACTIVE | Auth-A SETTLED | Auth-B DECLINED | — |
| Errors | | | | E6 rejected (Auth-Z) | | |

* The three fees are all assessed at **EOD 5**, when the back-valued E7 arrives. Each is
  value-dated to the day that was negative.
* E9 (Day 6) reverses E7 but not the fees, so ACC-001 ends 75.10 below a history without
  E7.
* E10 is a late arrival. It is stamped Day 5 but listed after the Day 6 event E9, so it
  is processed on Day 6 and restates ACC-002's Day 5.

## Reading the output

Each day prints one block. Day 5 is the interesting one (abridged):

```
DAY 5 — end of day
Events processed
  E7   DEBIT         ACC-001  AED 620.00     value D2  stamped D5       POSTED
  E8   AUTHORIZATION ACC-001  AED 90.00      value D5  stamped D5       DECLINED
       Auth-B declined: available after hold ledger -155.00 - holds 0.00 - 90.00 = -245.00
Errors
  (none)
Notices
  E7: back-valued to Day 2 (processed Day 5); Days 2-4 re-evaluated for fees and interest at EOD
Fee assessments (this EOD run)
  FEE-ACC-001-D2   AED -25.00  value D2  booked D5  — Day 2 closed at -370.00
  FEE-ACC-001-D4   AED -25.00  value D4  booked D5  — Day 4 closed at -180.00
  FEE-ACC-001-D5   AED -25.00  value D5  booked D5  — Day 5 closed at -205.00
Authorizations
  Auth-A  ACC-001  SETTLED   hold 200.00 released by E5
  Auth-B  ACC-001  DECLINED  available after hold ledger -155.00 - holds 0.00 - 90.00 = -245.00
ACC-001 (AED)  closing ledger -230.00   active holds 0.00   available -230.00
    day    before EOD       fee    after EOD   restated?
    D1         250.00                 250.00
    D2        -370.00    -25.00      -395.00   was 250.00
    D3          30.00                   5.00   was 650.00
    D4        -155.00    -25.00      -205.00   was 465.00
    D5        -155.00    -25.00      -230.00
    interest records: D2 adj -0.10, D3 adj -0.26, D4 adj -0.19, D5 0.00   accrued to date 0.10
```

* **Events processed**: each event handled that day, its outcome (POSTED, APPROVED,
  DECLINED or REJECTED) and the working behind it. `stamped D5 LATE` marks an event
  processed after its stamped day had closed.
* **Errors**: rejections only. A decline is a business outcome and is shown under
  Authorizations.
* **Notices**: back-valued and late events, i.e. reasons that past days may be restated.
* **Fee assessments**: fees booked by *this* EOD run. `value D2 booked D5` means a Day 2
  overdraft discovered on Day 5. The memo shows the balance at the moment that day was
  tested, which already includes fees booked earlier in the same run. That is why Day 4
  reads −180.00 there but −155.00 in the "before EOD" column.
* **Authorizations**: the state of every authorization at this EOD. State is derived
  from the records, never stored.
* **Account table**: one row per day so far, by value date, as known at this EOD.
  *before EOD* is the balance before this run's fees, *after EOD* the balance after
  them (and, on Day 6, after capitalization). `was X` flags a day whose figure changed
  since the previous day's printout. Criterion 1's −370.00 is the D2 "before EOD" figure
  here.
* **Interest records**: accrual records written by this run. `adj` marks a restatement
  of an earlier day, appended rather than edited.

After Day 6, the **END OF WINDOW** section prints the restated view (closing balance,
fee, interest base and accrual for each value day), checks that the rounded daily
accruals equal the capitalized credit, and lists every ledger entry in append order.

## Design in one screen

* **Money** (`ledger/money.py`) is an integer count of minor units per currency (AED
  1/100, BHD 1/1000). Ledger arithmetic never rounds. The only rounding call is
  `round_minor`, used by interest.
* **Five append-only stores** (`ledger/engine.py`): journal (each inbound event and its
  outcome), entries (postings), holds (PLACE/RELEASE), accruals, and problems. All are
  private lists exposed as tuples of frozen dataclasses. Balances, available balance and
  authorization state are all *folds* over these stores. A correction is always a new
  record.
* **End of day** (`Ledger.close_day`), in order:
  1. Re-walk Days 1..today by value date and book a fee for any negative day that has
     none.
  2. Recompute the carry-forward interest schedule and append deltas.
  3. On Day 6, capitalize, checking that the daily accruals sum to the credit.
* **Replay driver** (`ledger/replay.py`): processes events in the given order and closes
  each day before an event stamped for a later day. It never re-sorts.

## Repository layout

```
ledger/
  money.py      Currency, Money (int minor units), allocate(), round_minor()
  events.py     inbound Event record
  scenario.py   accounts, window, and E1..E10 exactly as in the brief
  engine.py     Ledger: stores, submission rules, end of day, snapshots
  replay.py     the clock / driver
  report.py     text rendering
  __main__.py   python3 -m ledger
tests/
  test_money.py         parsing, formatting, allocation, rounding
  test_postings.py      single-day postings, holds, settlements, reversals
  test_end_of_day.py    fees and interest on synthetic streams
  test_scenario.py      E1..E10: one class per acceptance criterion, day-by-day pins, append-only
  test_known_failure.py the one intentionally failing test
```

## The failing test

`tests/test_known_failure.py` asserts that each day's interest equals
`round(that day's balance × 0.04 %)`, which is what a customer checking their statement
would do. It fails on **Day 5**, where the ledger shows 0.15 and the per-day rule gives
0.16. The ledger rounds the running total rather than each day (carry-forward), so a
day's figure depends on the rounding left over from earlier days. That is what makes
the capitalized 0.92 equal the true 0.918 correctly rounded (per-day rounding gives
0.93). The inline comments explain what this reveals and why the test stays red. It is
deliberately not marked `@expectedFailure`.

## Documents

* [NUMBERS.md](NUMBERS.md): every constant, why that value, and what happens at half of
  it (computed, not estimated).
* [AMBIGUITIES.md](AMBIGUITIES.md): each ambiguity and the reading chosen.
* [REJECTED.md](REJECTED.md): criteria 2, 6, 7 and 8 refused with arithmetic, the
  accepted ones justified, and abandoned approaches.
* [WORKLOG.md](WORKLOG.md): a timestamped build log.

## Known limitations

* Fees are not refunded when the debit that caused them is reversed (AMBIGUITIES §B6).
  After E9 the customer is 75.00 out of pocket until an explicit refund, which this core
  has no event type for.
* The literal fee rule permits fee-on-fee. A fee above 30.00 would charge Day 3 only
  because of Day 2's fee (NUMBERS §1).
* No hold expiry, no over-settlement tolerance, no FX, and no force-post or suspense
  handling.
* Balances are recomputed by scanning all entries (O(n) per query). That is fine for a
  replay of this size, but not an indexing strategy.
