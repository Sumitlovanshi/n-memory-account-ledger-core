# REJECTED

Part 1 lists the acceptance criteria I refuse, with the arithmetic. Part 2 covers the
criteria I examined and accepted, so the reasoning on both sides is visible. Part 3
lists the approaches I abandoned, each marked by when it was dropped.

Every figure below comes from `python3 -m ledger` or the tests named.

---

## Part 1 — Criteria refused

### Criterion 2 — "E7 causes exactly one overdraft fee to be assessed, on Day 2."

**Refused. E7 causes three fees, on Days 2, 4 and 5.**

E7 is a 620.00 debit value-dated Day 2. A back-valued debit lowers the closing balance of
*its value day and every day after it*, not just its own day. At EOD 5, walking forward
by value date:

| day | before EOD 5 | fee | after |
|-----|--------------|-----|-------|
| 2 | 1200 − 950 − 620 = **−370.00** | −25.00 | −395.00 |
| 3 | −395.00 + 400.00 = **+5.00** | — | 5.00 |
| 4 | 5.00 − 185.00 = **−180.00** | −25.00 | −205.00 |
| 5 | **−205.00** | −25.00 | −230.00 |

* Day 4 is negative **on E7 alone**: 1200 − 950 − 620 + 400 − 185 = −155.00, even if the
  Day 2 fee is ignored. So the criterion fails whether or not fees cascade.
* Without E7 (and its reversal E9) the same stream produces **no fees at all**, so all
  three are caused by E7.
* Day 6 is not charged only because E9 arrives on Day 6, before EOD 6 runs.

Probably intended trap: treating the value date as the only day affected.
Tests: `Criterion2_E7FeeCount` (three fee days, the no-E7 counterfactual has zero, Day 4
is at −155.00 before any fee).

### Criterion 6 — "After E9, all balances and fees return to their pre-E7 values."

**Refused. E9 reverses E7's 620.00, and nothing else.**

1. **The ledger is append-only.** E7, E9 and the three fee entries all remain. E9 is a
   compensating entry for E7 only. The fees are separate entries that no rule reverses
   (AMBIGUITIES §B6). Before E7 there were zero fees; after E9 there are three
   (75.00).
2. **Balances don't return.** Compared with a history in which E7 never happened, ACC-001
   is lower by value day as follows:

   | D1 | D2 | D3 | D4 | D5 | D6 |
   |----|----|----|----|----|----|
   | 0.00 | 25.00 | 25.00 | 50.00 | 75.00 | **75.10** |

   That is 25.00 for each fee from its value day on, plus 0.10 less interest (0.92 vs
   1.02), because the fees reduced the positive balances that interest is paid on.
3. **Authorizations don't return.** Auth-B was declined *because of* E7 (−245.00). In the
   no-E7 history it is approved (465.00 − 90.00 ≥ 0) and would hold 90.00. A real-time
   decline that the merchant has already seen can't be retroactively turned into an
   approval.
4. Even with automatic fee refunds (design B, which I didn't build), the fee records
   (assessed + refunded) and the Auth-B decline would still differ. In an append-only
   ledger "return to pre-E7" can at best mean *net balances*, never the records.

Tests: `Criterion6_ReversalRestoresEverything`.

### Criterion 7 — "The three BHD instalments in E10 must each be BHD 3.334."

**Refused. That credits 10.002 BHD for a 10.000 BHD instruction.**

3 × 3.334 = 10.002, which creates 0.002 BHD (2 fils) from nothing. At 3 dp, 10.000 can't
be split into three equal parts: 10.000 / 3 = 3.333… The ledger keeps the instructed
total and makes the parts as equal as possible: **3.334 + 3.333 + 3.333 = 10.000**
(AMBIGUITIES §F1).
Tests: `Criterion7_BhdInstalments`, `test_three_times_3_334_is_not_ten`.

### Criterion 8 — "If the rounded daily interest accruals do not sum to the capitalized total, the remainder is discarded."

**Refused. It contradicts a non-negotiable rule, and the design makes the case impossible.**

The brief says the rounded daily accruals **must** sum exactly to the capitalized total.
A rule for what to do when they don't is a rule for breaking that requirement. Discarding
the remainder means one of two things, and both are defects:
* the credit differs from the sum of the daily lines, which breaks the rule; or
* the difference disappears from the ledger: money lost or created with no entry.

The ledger uses carry-forward rounding, so the daily figures are built to sum to the
correctly rounded true total and no remainder ever exists: ACC-001 0.92 (true 0.918),
ACC-002 0.008. Capitalization *checks* this and raises `LedgerInvariantError` on any
mismatch instead of discarding anything.
Tests: `Criterion8_AccrualRemainder`.

---

## Part 2 — Criteria examined and accepted

| # | Criterion | Verdict | Why |
|---|-----------|---------|-----|
| 1 | Day 2 closing, at end of Day 5 before any fee, is −370.00 | **Accepted** | 1200.00 − 950.00 − 620.00. No fee existed before EOD 5. `Criterion1_*` |
| 3 | The Day 4 settlement of Auth-A must be accepted | **Accepted** | Auth-A was validly approved on Day 2 (available 50.00) and 185.00 ≤ 200.00. The trap is the reverse: restated with E7, Day 2 is −395.00 and Auth-A *would* have been declined, but approvals are decisions made on what was known and are not revoked retroactively (AMBIGUITIES §D10). `Criterion3_*` |
| 4 | A settlement for an authorization not in the ledger is rejected; funds don't leave | **Accepted, with a caveat** | E6 is rejected, journaled and printed as the Day 4 error, and nothing posts. Caveat: in real card schemes an unmatched clearing ("force post") is usually posted and disputed, not refused. This core has no scheme or suspense model, so rejection is the only safe choice (AMBIGUITIES §D6). `Criterion4_*` |
| 5 | If Auth-B is approved, its hold reduces available but not ledger balance | **Accepted, vacuous here** | True as a statement about holds, but its premise never holds: Auth-B is **declined** (−155.00 − 90.00 = −245.00). So the property is tested where it applies: Auth-A on Day 2 (ledger 250.00, available 50.00) and a synthetic approval. I didn't reject it because a conditional with a false premise is not *wrong*, only unexercised. `Criterion5_*`, `test_hold_reduces_available_but_not_ledger` |

---

## Part 3 — Approaches abandoned

### Abandoned mid-build (in the commit history and WORKLOG)

1. **Raw interest computed in the caller's Decimal context, unguarded.**
   The first version of `accrual_schedule` multiplied in whatever context was active, so
   too little precision would have *rounded silently*. That breaks the promise that
   rounding happens only in `round_minor`. I found it while writing NUMBERS §15. It now
   runs in a local context that traps `Inexact`, with a guard test. Commit
   "Trap inexact Decimal arithmetic…".
2. **Labelling the per-day table column "before fees".**
   The first full printout showed Day 6 going from 390.00 to 390.92 under a column called
   "before fees". The difference is capitalization, not a fee. I renamed the columns to
   before EOD / after EOD and added an interest-base column to the summary, so the 390.00
   base is visible next to the 390.92 closing balance.
3. **Failing-test candidates (a) to (c)** (WORKLOG, the failing-test entry). (a), "the
   reversal doesn't make the customer whole", was dropped because it is criterion 6
   restated, which I argue is wrong as written. (b), "the as-at report differs from the
   restated one", is inherent to value dating, not a flaw. (c), the fee-on-fee cascade,
   is real but needs a synthetic stream. I chose (d), "a day's interest can't be
   checked from that day's balance", because it shows up on the brief's own data and
   comes from a choice I made.

### Abandoned at design time, before the code that would have used them

4. **A mutable authorization status field** (`status = SETTLED`). That would be a
   mutated record. Replaced by deriving the state from the journal and the hold log.
5. **Sorting the stream by day.** It would quietly "fix" E10 and hide the late-arrival
   path. The brief says "in this order".
6. **Assessing fees only for "today" at each EOD.** That misses back-valued debits
   entirely (no fee would ever be charged for Day 2 or Day 4). A mutation run of exactly
   this design fails 12 tests.
7. **Rounding each day's interest on its own.** It gives 0.93 against a true 0.918, and
   on a BHD 1.250 balance (an exact 0.5-fils tie every day) it pays **nothing** under
   half-even. A mutation run fails 6 tests. Replaced by carry-forward.
8. **Automatic fee refund when the triggering debit is reversed** (design B). It invents
   a policy and makes fee outcomes depend on later events. Kept as a documented
   limitation (AMBIGUITIES §B6).
9. **Force-posting Auth-Z's settlement.** Realistic for card schemes but needs a
   suspense or chargeback model the core doesn't have (AMBIGUITIES §D6).
10. **Rejecting E10 because "equal" is impossible.** Over-literal: it throws away a
    legitimate 10.000 BHD credit to protect a word. Replaced by an allocation that keeps
    the total.
11. **Decimal amounts throughout.** Replaced by integer minor units, so ledger arithmetic
    can't round at all and only interest crosses the fractional boundary.
12. **Revoking approvals when back-valued entries restate the day they were made**
    (Auth-A). That would retroactively decline a payment the merchant already completed
    and contradict criterion 3.
