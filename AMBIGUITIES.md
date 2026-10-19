# AMBIGUITIES

Every point where the brief allowed more than one reading, the reading I implemented, and
why. Where the choice is pinned by a test, the test is named. Section letters are
referenced from NUMBERS.md and REJECTED.md.

---

## A. Time and ordering

**A1. "Day" column vs `value_date`.**
The column headed *Booked* is the day the event is stamped and processed. `value_date`
is the day the money counts from. Balances, fees and interest all use value date. The
booked day only decides *when* the ledger learns about something. Each entry stores both:
`value_date` and `booked_day` (the day it was appended).

**A2. E10 is stamped Day 5 but listed after E9 (Day 6).**
Two readings: (a) the list is just grouped by account, so sort by day and process E10 on
Day 5; (b) the brief says "replayed **in this order**", so E10 really arrives after Day 6
has started. **Chosen: (b).** The driver doesn't re-sort. E10 is processed while Day 6 is
open, keeps its Day 5 stamp and value date, and raises a `late arrival` notice. Effects:
the Day 5 printout shows ACC-002 at 0.000; the Day 6 printout restates Day 5 to 10.000
("was 0.000"); Day 5's interest (0.004) is added as an adjustment at EOD 6. The final
value-dated figures are the same under either reading. Only the as-known-at-Day-5 view
differs. Re-sorting would hide a real-world condition the ledger needs to handle anyway.
(`test_e10_is_a_late_arrival_processed_on_day_6`)

**A3. When end-of-day runs.**
After the last event stamped for a day, before the first event of the next day, and for
Day 6 after the final event. Fees and interest run as an EOD batch, not on each posting.
As a result, E8 (Auth-B) is checked against −155.00, before the fees for Days 2, 4 and 5
are booked at EOD 5. If fees were posted immediately on E7, the balance would be −205.00.
Auth-B is declined either way.

**A4. Back-valued entries.**
Allowed anywhere inside the window. A notice is raised and every earlier day is
re-evaluated at the next EOD. No cap below the window (NUMBERS §14: a 3-day cap would
reject E9).

**A5. Future value dates.**
Allowed inside the window. They count from their value day, so they are excluded from
today's balance and from authorization checks. None occur in the stream.

**A6. Which "closing ledger balance" to print per day.**
There are two honest answers: the balance *as known at that EOD*, and the balance
*restated* once every event is known. Day 2 is 250.00 at EOD 2, −395.00 at EOD 5 and
225.00 at the end. The daily printout shows the as-known view, with a "was X" flag
whenever a day already reported has changed. The end-of-window summary shows the
restated view.

---

## B. Overdraft fees

**B1. Retroactive assessment.**
The rule defines the closing balance by value date ("all entries with value_date ≤ that
day"). Criterion 1 evaluates Day 2's balance at the end of Day 5. Read together, a
back-valued debit must be able to cause a fee for a past day. **Chosen:** every EOD
re-walks Days 1..today in ascending order and books a fee for any day that is negative
and has no fee yet. (`test_back_valued_debit_triggers_retroactive_fee_with_past_value_date`)

**B2. "Booked with value_date equal to the day assessed."**
"The day assessed" could mean the day whose balance was tested (Day 2) or the EOD that ran
the test (Day 5). **Chosen: the day tested.** The Day 2 fee has value date Day 2 and
booked day Day 5. Otherwise a Day 2 overdraft would count as a Day 5 fee, and "once per
day" would be keyed to the wrong day.

**B3. Do earlier fees count toward later days' balances?**
Fees are entries, and the rule says "all entries", so yes. Day 3 at EOD 5 is
−395.00 + 400.00 = **5.00**, not 30.00. In this stream it makes no difference, since
both are positive. It matters near the cliff: any fee above 30.00 would make Day 3
negative purely because of the Day 2 fee (NUMBERS §1). That is a fee-on-fee spiral,
which the literal rule permits. I implemented the literal rule and flagged it here rather
than adding a consumer-protection exception the brief doesn't ask for.
(`test_earlier_fee_counts_toward_later_days_balance`)

**B4. Is zero negative?**
No. A closing balance of exactly 0.00 is not charged (the fee-30.00 sensitivity run
leaves Day 3 at 0.00 with no fee). (`test_no_fee_on_zero_or_positive_close`)

**B5. AED fee on a BHD account.**
The rule says "per account" but gives the fee only in AED. **Chosen:** the fee schedule
is keyed by currency. With no BHD entry, no fee is assessed and an ERROR is logged once
per account-day. No FX rate is invented (NUMBERS §3). ACC-002 never goes negative, so the
stream doesn't exercise this. (`test_no_fee_without_a_same_currency_schedule`)

**B6. Are fees refunded when the debit that caused them is reversed?**
The rule says when a fee is assessed and says nothing about refunds. Two designs:
(A) fees are final, and a refund would be its own explicit event; (B) at each EOD,
automatically reverse any fee whose day is no longer negative. **Chosen: (A).** (B) is a
product policy the brief doesn't state. It would also make the fee outcome depend on
events days later, which sits badly with "assessed once". Consequence: after E9 the
customer is 75.00 worse off than if E7 had never happened. That is the main reason
criterion 6 is rejected, and the most customer-visible limitation of this design.
Operationally it is a manual fee refund.

**B7. Day 6 fee vs capitalization.**
The capitalization credit is value-dated Day 6, so it is part of Day 6's balance, and the
credit depends on Day 6's accrual. **Chosen:** EOD order is fees → accrual →
capitalization, so the Day 6 fee test uses the balance before capitalization. Not
exercised (Day 6 is +390.00).

**B8. Ledger balance vs available balance for fees.**
The rule says ledger balance. Holds never trigger a fee.
(`test_holds_do_not_trigger_fees`)

---

## C. Interest

**C1. How "rounded daily accruals" are formed.**
Either round each day on its own, or round the running total and take differences
(carry-forward). Both can be made to "sum exactly" if the capitalized total is defined as
their sum, but they produce different totals: 0.93 vs 0.92 for ACC-001, against a true
0.918. **Chosen: carry-forward** (NUMBERS §8). The price is the failing test.

**C2. Rounding mode.** Half-even (NUMBERS §7). No ties occur in the stream.

**C3. Interest base.**
The closing ledger balance by value date, *including* fees (they are entries) and
*excluding* the capitalization credit itself. There is no compounding inside the window
because accruals capitalize only at the end of Day 6.
(`test_interest_is_not_compounded_inside_the_window`)

**C4. "Positive balances only."**
Zero and negative days accrue 0. No debit interest is charged on negative days, since the
brief doesn't mention it. (`test_negative_and_zero_days_accrue_nothing`)

**C5. Back-valued entries and interest already accrued.**
Accruals are append-only memo records. Each EOD recomputes the schedule for Days 1..today
from the current value-dated balances and appends a delta for any day that changed. At
EOD 5 this claws back Day 2 −0.10, Day 3 −0.26 and Day 4 −0.19. At EOD 6 it re-accrues
them after E9. The capitalized total reflects the final value-dated balances.

**C6. Day 6.**
Day 6 accrues on 390.00, the balance before the capitalization credit. The printed Day 6
closing balance, 390.92, includes the credit. The summary shows both (the "int. base"
column).

**C7. Zero capitalization.**
If an account accrued nothing, no zero-amount entry is posted. Not exercised: both
accounts accrue.

---

## D. Authorizations, holds, settlements

**D1. Which ledger balance an authorization is checked against.**
Every entry known at processing time with value date ≤ the processing day. Future-dated
credits don't count. An authorization's own `value_date` isn't used, because a hold has
no value date.

**D2. "At or above zero."** Inclusive: exactly 0.00 is approved.
(`test_available_exactly_zero_is_approved`)

**D3. Is a decline an error?**
No. A decline is a business outcome, shown under *Authorizations*, not under *Errors*.
Only rejections (bad or unprocessable input) are errors.

**D4. Partial settlement.**
Auth-A holds 200.00 and settles for 185.00. Either the settlement is final and the 15.00
is released, or 15.00 stays held for a later clearing. **Chosen: final.** The whole hold
is released, since the brief shows one settlement per authorization.

**D5. Over-settlement.**
Rejected, because no tolerance is given (NUMBERS §12). Not in the stream.

**D6. Settlement with no matching authorization (Auth-Z).**
In real card schemes a clearing record without a matching authorization (a "force post")
does happen. The issuer usually has to post it and then dispute it through chargeback,
and the scheme moves the money between banks either way. This core has no scheme, no
suspense account and no chargeback flow. Posting E6 would let 180.00 leave the account on
nobody's authority, and dropping it silently would lose the record. **Chosen:** reject,
keep E6 in the journal as REJECTED, and print it as the Day 4 error. This matches
criterion 4, which is therefore accepted (REJECTED.md, part 2). A production system would
route it to an exceptions queue instead.

**D7. "Not present in the ledger" (criterion 4 wording).**
Authorizations are not postings: a hold doesn't touch the ledger balance. I read "the
ledger" as the whole append-only record (journal and hold log), and that is where Auth-A
and Auth-B appear and Auth-Z doesn't.

**D8. Settling a declined or already-settled authorization.**
Both are rejected. Auth-B is "present" (as a decline) but has nothing to settle.

**D9. Hold expiry.**
Not specified, and not modelled. Holds stay active until settled. No effect on this
stream (NUMBERS §13). At the end of the window Auth-B is DECLINED, not "expired".

**D10. Approvals aren't revisited after back-valuation.**
At EOD 5, Day 2 restates to −395.00, a balance on which Auth-A's 200.00 would have been
declined. Auth-A was approved on what was known at the time and has already settled. It
isn't revoked and E5 isn't unwound. (This is criterion 3's real test:
`test_settlement_stands_although_restated_day2_would_have_declined_auth_a`.)

**D11. Booked debits and the available-balance rule.**
The approval rule applies to *authorizations*. E2 and E7 are booked debits and post even
when they overdraw. That is how E7 can drive Day 2 to −370.00.
(`test_booked_debit_may_overdraw`)

---

## E. Reversal (E9)

**E1. What E9 reverses.**
Only E7's posting: one compensating entry of +620.00, value Day 2, with
`reverses = "E7"`. It doesn't reverse the three fees E7 caused, and it can't undo
Auth-B's decline (B6, D10).

**E2. Reversal value date.**
The brief gives Day 2, the same as the original, so E7 and E9 cancel on every day from
Day 2. If a reversal had a later value date, the days in between would stay negative.
Not exercised.

**E3. What can be reversed.**
Only postings created by an inbound event (credit, debit, settlement), in full, once, on
the same account. Reversing something that never posted (an authorization, a rejected
event) is rejected, as is a second reversal. Reversing a multi-instalment credit reverses
every instalment. (`Reversals` in `tests/test_postings.py`)

---

## F. Instalments (E10)

**F1. "Three equal instalments" of 10.000 BHD.**
This is impossible at 3 dp. The options:
* 3 × 3.334 = 10.002, which creates 2 fils (criterion 7);
* 3 × 3.333 = 9.999, which loses 1 fils;
* reject E10 because "equal" can't be met, which loses a legitimate credit;
* as near-equal as possible while keeping the total: **3.334 + 3.333 + 3.333. Chosen.**

The total is the invariant that matters, and "equal" is honoured to within one fils.

**F2. Which instalment gets the extra fils.** The first (NUMBERS §11). No balance on any
day is affected.

**F3. Same value date?**
"Posted as three instalments" could suggest spreading them over several days. The brief
gives one value date (Day 5), so all three are value-dated Day 5. They are numbered
`E10#1..3` and share source E10.

---

## G. Append-only and records

**G1. What counts as an "event record".**
Everything: inbound events and their outcomes (journal), postings, hold PLACE/RELEASE,
accrual records, and errors/notices. Nothing has an update or delete path. All stores are
private lists exposed as tuples of frozen dataclasses. Authorization state
(ACTIVE/SETTLED/DECLINED) is *derived* from the records, not stored, because a status
field that changes would be a mutation. (`AppendOnly` in `tests/test_scenario.py`
snapshots all five stores after every event and EOD and checks that each snapshot is a
prefix of the next.)

**G2. Rejected events are recorded, not dropped.** E6 is in the journal as REJECTED.

**G3. Duplicate event ids are rejected**, so replaying the same stream twice into one
ledger has no effect the second time.

**G4. Opening balances 0.00 / 0.000** are represented by the absence of entries. No
zero-amount opening entry is posted.

**G5. Sequence numbers.**
One `seq` counter is shared by all five stores, giving a total order across them. A
store's own seq numbers therefore have gaps. The printout says so.

---

## H. Wording of the acceptance criteria

**H1. Criterion 1, "before any fee is assessed".**
I read this as "before the EOD 5 fee run". No fee existed before then anyway (Days 1–4
were positive when they closed). The test checks the balance *and* that the fee count is
zero at that moment.

**H2. Criterion 5, "If Auth-B is approved…".**
The premise is false: Auth-B is declined (−245.00). The conditional is true as a
statement about holds, but this stream can't exercise it, so it's tested on Auth-A
(Day 2: ledger 250.00, holds 200.00, available 50.00) and on a synthetic approval.

**H3. Criterion 6, "pre-E7 values".**
I read "pre-E7" as a history in which E7 (and therefore E9) never happened. The
alternative, "the values printed at EOD 4", gives the same comparison for Days 1–4.
