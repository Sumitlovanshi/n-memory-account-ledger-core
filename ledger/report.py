"""Plain-text rendering of day reports and the end-of-window summary."""
from __future__ import annotations

from typing import Dict, List, Optional

from .engine import DayReport, EntryKind, Ledger, Severity
from .money import Money

RULE = "=" * 78


def _amount(event) -> str:
    return str(event.amount) if event.amount is not None else ""


def render_day(report: DayReport, previous: Optional[DayReport] = None) -> str:
    out: List[str] = [RULE, f"DAY {report.day} — end of day", RULE]

    out.append("Events processed")
    if not report.events:
        out.append("  (none)")
    for r in report.events:
        ev = r.event
        stamp = f"stamped D{ev.day}" + (" LATE" if ev.day < r.processed_day else "")
        out.append(
            f"  {ev.id:<4} {ev.kind.value:<13} {ev.account}  {_amount(ev):<14} "
            f"value D{ev.value_date}  {stamp:<16} {r.outcome.value}"
        )
        out.append(f"       {r.detail}")

    errors = [p for p in report.problems if p.severity is Severity.ERROR]
    notices = [p for p in report.problems if p.severity is Severity.NOTICE]
    out.append("Errors")
    out.extend(f"  {p.source}: {p.message}" for p in errors) if errors else out.append("  (none)")
    if notices:
        out.append("Notices")
        out.extend(f"  {p.source}: {p.message}" for p in notices)

    out.append("Fee assessments (this EOD run)")
    if not report.fees:
        out.append("  (none)")
    for f in report.fees:
        out.append(
            f"  {f.id:<16} {f.amount}  value D{f.value_date}  booked D{f.booked_day}  — {f.memo}"
        )

    out.append("Authorizations")
    if not report.auths:
        out.append("  (none yet)")
    for a in report.auths:
        out.append(f"  {a.auth_id:<7} {a.account}  {a.state.value:<9} {a.detail}")

    prev: Dict[tuple, str] = {}
    if previous is not None:
        for acc in previous.accounts:
            for row in acc.restated:
                prev[(acc.account, row.day)] = row.after.format()

    for acc in report.accounts:
        out.append(
            f"{acc.account} ({acc.currency})  closing ledger {acc.ledger.format()}   "
            f"active holds {acc.holds.format()}   available {acc.available.format()}"
        )
        out.append("    value-date closing balances as known at this EOD")
        out.append(f"    {'day':<4} {'before EOD':>12} {'fee':>9} {'after EOD':>12}   restated?")
        for row in acc.restated:
            fee = row.fee.format() if row.fee is not None else ""
            was = prev.get((acc.account, row.day))
            flag = f"was {was}" if was is not None and was != row.after.format() else ""
            out.append(
                f"    D{row.day:<3} {row.before.format():>12} {fee:>9} {row.after.format():>12}   {flag}"
            )
        accruals = [a for a in report.accruals if a.account == acc.account]
        parts = [
            f"D{a.for_day} {'adj ' if a.adjustment else ''}{a.amount.format()}" for a in accruals
        ]
        out.append(
            f"    interest records: {', '.join(parts) or '(none)'}   accrued to date "
            f"{acc.accrued_to_date.format()}"
        )
        if acc.capitalized is not None:
            out.append(f"    interest capitalized at end of Day {report.day}: {acc.capitalized.format()}")
    return "\n".join(out)


def render_summary(ledger: Ledger) -> str:
    out: List[str] = [
        RULE,
        "END OF WINDOW — restated value-date view (every event known)",
        RULE,
    ]
    for acct in sorted(ledger.accounts):
        currency = ledger.accounts[acct]
        out.append(f"{acct} ({currency})")
        out.append(f"    {'day':<4} {'closing':>12} {'fee':>9} {'int. base':>12} {'accrual':>9}")
        total = 0
        for d in ledger.window():
            fee = ledger.fee_for_day(acct, d)
            accrued = ledger.accrued(acct, d)
            total += accrued.minor
            base = ledger.closing_balance(acct, d, exclude=(EntryKind.INTEREST,))
            out.append(
                f"    D{d:<3} {ledger.closing_balance(acct, d).format():>12} "
                f"{fee.amount.format() if fee else '':>9} {base.format():>12} {accrued.format():>9}"
            )
        capitalized = [e for e in ledger.entries if e.account == acct and e.kind is EntryKind.INTEREST]
        cap_minor = sum(e.amount.minor for e in capitalized)
        check = "OK" if cap_minor == total else "MISMATCH"
        out.append(
            f"    sum of rounded daily accruals {_fmt(total, currency)} = capitalized "
            f"{_fmt(cap_minor, currency)}  [{check}]"
        )

    out.append("    (int. base = closing excluding the capitalization credit itself)")
    out.append("Ledger entries (append order; nothing is ever edited or removed)")
    out.append("  #seq is one sequence shared by all five stores, so gaps are records in other stores")
    for e in ledger.entries:
        extra = f"reverses {e.reverses}" if e.reverses else e.memo
        out.append(
            f"  #{e.seq:<3} {e.id:<16} {e.account}  {e.kind.value:<13} {e.amount.format():>10}  "
            f"value D{e.value_date}  booked D{e.booked_day}  {extra}"
        )
    return "\n".join(out)


def _fmt(minor: int, currency) -> str:
    return Money(currency, minor).format()
