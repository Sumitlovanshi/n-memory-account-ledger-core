# NUMBERS

Every number the ledger uses. **Given** means it comes from the brief; **chosen** means
I picked it. For each one: why this value, and what happens at half of it.

The "at half" results come from replaying E1..E10 with only that constant changed. I
didn't estimate them. Baseline end state: ACC-001 **390.92 AED** (fees on Days 2, 4, 5;
interest 0.92), ACC-002 **10.008 BHD**, E6 rejected, Auth-B declined.

## Summary

| #  | Constant | Value | Source | What half of it does to this stream |
|----|----------|-------|--------|-------------------------------------|
| 1  | Overdraft fee | AED 25.00 (2,500 fils) | given | Same 3 fees; ACC-001 ends 428.47. *Doubling* adds a 4th fee |
| 2  | Fees per account per value day | 1 | given | — (a count, not a magnitude; see below) |
| 3  | Fee for a BHD account | none | chosen | — (there is no value to halve; see below) |
| 4  | Daily interest rate | 0.04 % = `Decimal("0.0004")` | given | Interest 0.46 / 0.004; nothing else moves |
| 5  | Minor units | AED 2 dp, BHD 3 dp | given (ISO 4217) | — (properties of the currencies) |
| 6  | Rounding unit | 1 minor unit | follows from 5 | — |
| 7  | Rounding mode | `ROUND_HALF_EVEN` | chosen | No exact ties in this stream, so `HALF_UP` would print the same |
| 8  | Rounding method | carry-forward (round the running total) | chosen | Per-day rounding gives 0.93, not 0.92 |
| 9  | Window | Days 1–6 | given | Days 1–3: E5..E10 rejected, ACC-001 ends 650.46 |
| 10 | Approval threshold | available after hold ≥ 0.00 | given | — (zero has no half) |
| 11 | Instalments in E10 | 3, remainder fils to #1 | given / chosen | — |
| 12 | Settlement over-hold tolerance | 0 % | chosen | — |
| 13 | Hold expiry | none inside the window | chosen | No effect at any expiry ≥ 2 days |
| 14 | Back-valuation limit | the whole window | chosen | A 3-day cap would reject E9 |
| 15 | Decimal precision for raw interest | caller's context (default 28), `Inexact` trapped | chosen | 14 digits would still be exact |

## 1. Overdraft fee: AED 25.00 (given)

Stored as `Money(AED, 2500)`, which is an integer count of fils, so 25.00 can never become
24.999…

What this value controls is one margin. After E7, Day 3's closing balance is
`1200 − 950 − 620 − fee + 400 = 30.00 − fee`, because the Day 2 fee is value-dated Day 2
and so counts on Day 3 (AMBIGUITIES §B3).

| fee   | Day 3 closing | fee days     | ACC-001 Day 6 | interest |
|-------|---------------|--------------|---------------|----------|
| 12.50 | +17.50        | 2, 4, 5      | 428.47        | 0.97     |
| **25.00** | **+5.00** | **2, 4, 5**  | **390.92**    | **0.92** |
| 30.00 | 0.00 (zero is not negative) | 2, 4, 5 | 375.90 | 0.90 |
| 30.01 | −0.01         | 2, **3**, 4, 5 | 345.81      | 0.85     |
| 50.00 | −20.00        | 2, **3**, 4, 5 | 265.74      | 0.74     |

**At half:** the fee count stays at three and only the amounts change. **At double:** a
fourth fee appears, charged on Day 3 purely because of the Day 2 fee (fee-on-fee). The
5.00 margin on Day 3 is the most fragile number in the scenario, and it decides whether
acceptance criterion 2 is wrong by two fees or by three.

## 2. One fee per account per value day (given)

Enforced as "no second `OVERDRAFT_FEE` entry for the same (account, value_date), ever".
Halving doesn't apply to a count. The alternative I checked was "once per EOD run for
each negative day". Here that gives the same answer, because no day is negative at two
different EOD runs: EOD 5 finds Days 2, 4 and 5; at EOD 6 all days are positive. The
repeated-EOD case is pinned in `test_fee_once_per_negative_day_even_across_repeated_eods`.

## 3. Overdraft fee for a BHD account: none (chosen)

The brief gives the fee only in AED and gives no FX rate. Options I considered:

* **Charge 25.000 BHD.** At the USD pegs (AED 3.6725, BHD 0.376) that is about AED 244,
  roughly 10× the stated fee. Even half of it (12.500 BHD ≈ AED 122) is about 5×.
* **Convert.** About BHD 2.560 at the pegs, but that is an FX rate the brief doesn't give,
  and a ledger core should not invent one.
* **Don't assess, and log an ERROR** naming the account and day. **Chosen.** ACC-002
  never goes negative in this stream, so this only shows up in
  `test_no_fee_without_a_same_currency_schedule`.

## 4. Daily interest: 0.04 % per day (given)

`Decimal("0.0004")` is built from a string. A float `0.0004` is really
0.000400000000000000019… The rate is per day, simple. Every day in the window counts, so
no 360/365 day-count convention applies. For scale: 0.04 %/day is about 14.6 % a year
simple.

**At half (0.02 %):** ACC-001 interest is 0.46 and ACC-002 is 0.004, exactly half,
because nothing near a rounding tie moves. No fee, authorization or rejection changes,
because interest never pushes a day across zero here. At double (0.08 %) the totals are
1.84 and 0.016.

## 5–6. Precision: AED 2 dp, BHD 3 dp; rounding unit is one minor unit (given)

These are facts about the currencies, so there is nothing to halve. What I chose is how
amounts are stored: as **integer minor units** (`Money.minor: int`). Ledger addition is
then exact by construction. Half a fils cannot exist anywhere, and there is only one
place a fractional amount can turn into a whole one: `round_minor`, which only the
interest code calls. `Money.parse` *refuses* inputs with too many decimals
(`"3.3334"` BHD raises). It does not round them.

## 7. Rounding mode: half-even (chosen)

There are no exact ties in the stream. ACC-001's running raw interest is 10.0, 19.0,
44.0, 60.6, 76.2, 91.8 fils; ACC-002's is 4.0, 8.0. So `ROUND_HALF_UP` would print the
same. I chose half-even because it has no upward bias on ties. With carry-forward
(item 8), rounding is applied to the running total, so the mode can move a single day by
at most one fils and never changes the total by more than half a fils.

The tie case shows that the *method* matters more than the mode. A BHD 1.250 balance
accrues exactly 0.5 fils a day (true total 0.003 over six days):

| method + mode | daily fils | total |
|---|---|---|
| per-day, half-even | 0,0,0,0,0,0 | **0.000** |
| per-day, half-up   | 1,1,1,1,1,1 | **0.006** |
| carry-forward, half-even (chosen) | 0,1,1,0,0,1 | **0.003** |

## 8. Rounding method: carry-forward (chosen)

Day *d* accrues `round(Σ raw₁..d) − round(Σ raw₁..d−1)`. The rounded days always add up
to `round(Σ raw)`, so the capitalized credit is the correctly rounded true interest and
there is never a remainder (which is why criterion 8 is rejected). Error bound: within
½ fils of the true total for **any** window length. Per-day rounding is only bounded by
½ fils × the number of days (up to 3 fils, or 0.03 AED, over six days).

On the brief's data: true 0.918 → carry-forward **0.92**, per-day **0.93**. The cost is
that a single day can't be checked on its own (Day 5 shows 0.15, not 0.16). That is the
deliberately failing test.

## 9. Window: Days 1–6 (given)

**At half (Days 1–3):** E5..E10 are stamped after the window and rejected as
out-of-window. ACC-001 ends Day 3 at 650.46 (0.46 interest), with no fees and no Auth-B.
Capitalization happens at the end of the window, so it moves with the window.

## 10. Approval threshold: available after the hold ≥ 0.00 (given)

The boundary is inclusive. It is tested at exactly 0.00 (approved) and at −0.01 (declined).
* Auth-A: 250.00 − 0 − 200.00 = **50.00** of headroom. It would be approved for any hold up to 250.00.
* Auth-B: −155.00 − 0 − 90.00 = **−245.00**. With the ledger already below zero, no positive hold passes.

## 11. E10 instalments: 3, leftover fils to instalment 1 (count given, placement chosen)

10,000 fils = 3 × 3,333 + 1. The extra fils goes to the first instalment:
**3.334 + 3.333 + 3.333 = 10.000**. Putting it on the last instalment would be just as
valid. All three share value date Day 5, so the placement affects no balance on any day.
Criterion 7's 3 × 3.334 = 10.002 creates 2 fils from nothing.

## 12. Over-settlement tolerance: 0 % (chosen)

Card schemes allow settlement above the authorized amount for some merchant types, but
the brief gives no tolerance, so a settlement above the hold is rejected. E5 settles
185.00 against a 200.00 hold and the remaining 15.00 is released. Nothing in the stream
settles above its hold.

## 13. Hold expiry: none inside the window (chosen)

Auth-A lived from Day 2 to Day 4, so any expiry of 2 days or more leaves the stream
unchanged, including half of a typical week-long expiry. Auth-B never placed a hold.
Expiry isn't modelled at all; see AMBIGUITIES §D9.

## 14. Back-valuation limit: the whole window (chosen)

E7 reaches back 3 days (booked Day 5, value Day 2) and E9 reaches back 4 days (booked
Day 6, value Day 2). **A cap at half the window (3 days)** would accept E7 and reject E9.
The erroneous 620.00 debit would then stand and the customer would never get it back. So
there is no cap below the window.

## 15. Decimal precision for raw interest (chosen: left at the context default, 28)

`minor × 0.0004` has four decimal places. The largest raw figure in the stream, 91.8000
fils, needs 6 significant digits. **At half (14 digits)** everything is still exact until
cumulative raw interest reaches 10¹⁰ fils (10⁸ AED of interest in six days), so halving is
harmless. I left the context alone because changing the global Decimal context would leak
into any code that embeds this ledger. The multiply-and-accumulate runs in a local context
that **traps `Inexact`**, so a shortfall raises instead of rounding silently
(`test_raw_interest_arithmetic_refuses_to_round_silently`).

## Numbers the stream produces (for cross-checking the printout)

| figure | value | where it comes from |
|---|---|---|
| Day 2 closing at EOD 5, before fees | −370.00 | 1200 − 950 − 620 |
| Day 4 closing at EOD 5, before fees | −155.00 | E7 alone makes Day 4 negative |
| Auth-B available after hold | −245.00 | −155.00 − 0 − 90.00 |
| Day 3 margin after the Day 2 fee | +5.00 | 30.00 − 25.00 |
| Fees charged because of E7 | 3 × 25.00 = 75.00 | Days 2, 4, 5, booked at EOD 5 |
| Gap vs. a no-E7 history at Day 6 | 75.10 | 75.00 in fees + 0.10 less interest (1.02 vs 0.92) |
| ACC-001 interest | 0.92 | true 0.918; per-day rounding would give 0.93 |
| ACC-002 interest | 0.008 | 10.000 × 0.0004 × 2 days, exact |
