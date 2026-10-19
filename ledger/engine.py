"""The ledger core.

Five append-only stores, all private lists exposed only as tuples:

* ``journal``  — one record per inbound event with the outcome decided when it
                 was processed (POSTED / APPROVED / DECLINED / REJECTED).
* ``entries``  — ledger postings. Balances are folds over these, nothing else.
* ``holds``    — PLACE / RELEASE records. Authorization state is derived from
                 the journal plus this log; it is never stored and mutated.
* ``accruals`` — interest accrual memo records (original + restatement deltas).
* ``problems`` — errors and notices, with the day they were raised.

Nothing is ever updated or removed. A correction is a new record.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, Inexact, localcontext
from enum import Enum
from types import MappingProxyType
from typing import Dict, List, Mapping, Optional, Tuple

from .events import Event, EventKind
from .money import AED, Currency, Money, allocate, round_minor, sum_money


class EntryKind(str, Enum):
    CREDIT = "CREDIT"
    DEBIT = "DEBIT"
    SETTLEMENT = "SETTLEMENT"
    REVERSAL = "REVERSAL"
    OVERDRAFT_FEE = "OVERDRAFT_FEE"
    INTEREST = "INTEREST"


# Entries that came straight from an inbound event and may therefore be reversed.
REVERSIBLE = (EntryKind.CREDIT, EntryKind.DEBIT, EntryKind.SETTLEMENT)


@dataclass(frozen=True)
class Entry:
    seq: int
    id: str
    account: str
    kind: EntryKind
    amount: Money  # signed: credits > 0, debits < 0
    value_date: int
    booked_day: int  # processing day on which the entry was appended
    source: str  # originating event id, or "EOD-<day>"
    reverses: Optional[str] = None  # entry id this entry reverses
    memo: str = ""


class Outcome(str, Enum):
    POSTED = "POSTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class JournalRecord:
    seq: int
    event: Event
    processed_day: int
    outcome: Outcome
    detail: str


class HoldAction(str, Enum):
    PLACE = "PLACE"
    RELEASE = "RELEASE"


@dataclass(frozen=True)
class HoldRecord:
    seq: int
    auth_id: str
    account: str
    action: HoldAction
    amount: Money  # positive magnitude
    day: int
    source: str


@dataclass(frozen=True)
class AccrualRecord:
    seq: int
    account: str
    for_day: int
    amount: Money  # signed — a restatement can claw back an earlier accrual
    computed_on: int  # the EOD that produced it
    adjustment: bool


class Severity(str, Enum):
    ERROR = "ERROR"
    NOTICE = "NOTICE"


@dataclass(frozen=True)
class Problem:
    seq: int
    day: int
    severity: Severity
    source: str
    message: str


class AuthState(str, Enum):
    ACTIVE = "ACTIVE"  # approved, hold in place
    SETTLED = "SETTLED"
    DECLINED = "DECLINED"


class WindowClosed(RuntimeError):
    pass


class LedgerInvariantError(AssertionError):
    pass


def _default_fees() -> Mapping[Currency, Money]:
    return MappingProxyType({AED: Money(AED, 2500)})


@dataclass(frozen=True)
class Rules:
    first_day: int = 1
    last_day: int = 6
    # Fee schedule keyed by account currency. Only AED is given by the brief;
    # there is deliberately no FX conversion for other currencies.
    overdraft_fees: Mapping[Currency, Money] = field(default_factory=_default_fees)
    daily_rate: Decimal = Decimal("0.0004")  # 0.04 % per day


# --------------------------------------------------------------------------
# End-of-day snapshot. Built at close time so it shows what was known *then*.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RestatedDay:
    day: int
    before: Money  # closing balance before this EOD's fee run
    fee: Optional[Money]  # fee booked for this day during this run
    after: Money  # closing balance after this run


@dataclass(frozen=True)
class AccountClose:
    account: str
    currency: Currency
    restated: Tuple[RestatedDay, ...]
    ledger: Money
    holds: Money
    available: Money
    accrued_to_date: Money
    capitalized: Optional[Money]


@dataclass(frozen=True)
class AuthSnapshot:
    auth_id: str
    account: str
    state: AuthState
    detail: str


@dataclass(frozen=True)
class DayReport:
    day: int
    events: Tuple[JournalRecord, ...]
    problems: Tuple[Problem, ...]
    fees: Tuple[Entry, ...]
    accruals: Tuple[AccrualRecord, ...]
    auths: Tuple[AuthSnapshot, ...]
    accounts: Tuple[AccountClose, ...]


class Ledger:
    def __init__(self, accounts: Mapping[str, Currency], rules: Optional[Rules] = None):
        self.accounts: Mapping[str, Currency] = MappingProxyType(dict(accounts))
        self.rules = rules or Rules()
        self._journal: List[JournalRecord] = []
        self._entries: List[Entry] = []
        self._holds: List[HoldRecord] = []
        self._accruals: List[AccrualRecord] = []
        self._problems: List[Problem] = []
        self._seq = 0
        self._closed_through = self.rules.first_day - 1
        self._problem_keys: set = set()

    # ---------------------------------------------------------------- views

    @property
    def journal(self) -> Tuple[JournalRecord, ...]:
        return tuple(self._journal)

    @property
    def entries(self) -> Tuple[Entry, ...]:
        return tuple(self._entries)

    @property
    def holds(self) -> Tuple[HoldRecord, ...]:
        return tuple(self._holds)

    @property
    def accruals(self) -> Tuple[AccrualRecord, ...]:
        return tuple(self._accruals)

    @property
    def problems(self) -> Tuple[Problem, ...]:
        return tuple(self._problems)

    @property
    def current_day(self) -> int:
        """The open business day: events submitted now are processed on it."""
        return self._closed_through + 1

    @property
    def closed(self) -> bool:
        return self._closed_through >= self.rules.last_day

    def window(self) -> range:
        return range(self.rules.first_day, self.rules.last_day + 1)

    # -------------------------------------------------------------- appends

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _append_entry(self, **kw) -> Entry:
        entry = Entry(seq=self._next_seq(), booked_day=self.current_day, **kw)
        self._entries.append(entry)
        return entry

    def _problem(self, severity: Severity, source: str, message: str, key=None) -> None:
        if key is not None:
            if key in self._problem_keys:
                return
            self._problem_keys.add(key)
        self._problems.append(
            Problem(self._next_seq(), self.current_day, severity, source, message)
        )

    def _record(self, event: Event, outcome: Outcome, detail: str) -> JournalRecord:
        record = JournalRecord(self._next_seq(), event, self.current_day, outcome, detail)
        self._journal.append(record)
        if outcome is Outcome.REJECTED:
            self._problem(Severity.ERROR, event.id, detail)
        return record

    # -------------------------------------------------------------- queries

    def closing_balance(self, account: str, day: int, exclude: Tuple[EntryKind, ...] = ()) -> Money:
        """Sum of every entry on ``account`` with value_date <= ``day``."""
        return sum_money(
            (
                e.amount
                for e in self._entries
                if e.account == account and e.value_date <= day and e.kind not in exclude
            ),
            self.accounts[account],
        )

    def _authorization(self, auth_id: str) -> Optional[JournalRecord]:
        for record in self._journal:
            ev = record.event
            if (
                ev.kind is EventKind.AUTHORIZATION
                and ev.auth_id == auth_id
                and record.outcome in (Outcome.APPROVED, Outcome.DECLINED)
            ):
                return record
        return None

    def _hold_records(self, auth_id: str) -> List[HoldRecord]:
        return [h for h in self._holds if h.auth_id == auth_id]

    def auth_state(self, auth_id: str) -> Optional[AuthState]:
        record = self._authorization(auth_id)
        if record is None:
            return None
        if record.outcome is Outcome.DECLINED:
            return AuthState.DECLINED
        if any(h.action is HoldAction.RELEASE for h in self._hold_records(auth_id)):
            return AuthState.SETTLED
        return AuthState.ACTIVE

    def held_amount(self, auth_id: str) -> Optional[Money]:
        placed = [h for h in self._hold_records(auth_id) if h.action is HoldAction.PLACE]
        return placed[0].amount if placed else None

    def active_holds(self, account: str) -> Money:
        total = 0
        for h in self._holds:
            if h.account != account:
                continue
            total += h.amount.minor if h.action is HoldAction.PLACE else -h.amount.minor
        return Money(self.accounts[account], total)

    def available_balance(self, account: str, day: Optional[int] = None) -> Money:
        day = self.current_day if day is None else day
        return self.closing_balance(account, day) - self.active_holds(account)

    def auth_ids(self) -> List[str]:
        seen: List[str] = []
        for record in self._journal:
            ev = record.event
            if ev.kind is EventKind.AUTHORIZATION and ev.auth_id not in seen:
                if self._authorization(ev.auth_id) is not None:
                    seen.append(ev.auth_id)
        return seen

    def fee_for_day(self, account: str, day: int) -> Optional[Entry]:
        for e in self._entries:
            if e.kind is EntryKind.OVERDRAFT_FEE and e.account == account and e.value_date == day:
                return e
        return None

    def accrued(self, account: str, day: int) -> Money:
        """Net interest accrued for ``day`` (original record + any restatements)."""
        return sum_money(
            (a.amount for a in self._accruals if a.account == account and a.for_day == day),
            self.accounts[account],
        )

    # ------------------------------------------------------------ submission

    def submit(self, event: Event) -> JournalRecord:
        if self.closed:
            raise WindowClosed(f"window closed after Day {self.rules.last_day}; {event.id} not processed")
        reason = self._validate(event)
        if reason:
            return self._record(event, Outcome.REJECTED, reason)

        today = self.current_day
        if event.day < today:
            self._problem(
                Severity.NOTICE,
                event.id,
                f"late arrival: stamped Day {event.day} but received after Day {event.day} closed; "
                f"processed on Day {today}",
            )
        if event.value_date < today and event.kind is not EventKind.AUTHORIZATION:
            past = (
                f"Day {event.value_date}"
                if event.value_date == today - 1
                else f"Days {event.value_date}-{today - 1}"
            )
            self._problem(
                Severity.NOTICE,
                event.id,
                f"back-valued to Day {event.value_date} (processed Day {today}); "
                f"{past} re-evaluated for fees and interest at EOD",
            )

        handler = {
            EventKind.CREDIT: self._credit,
            EventKind.DEBIT: self._debit,
            EventKind.AUTHORIZATION: self._authorize,
            EventKind.SETTLEMENT: self._settle,
            EventKind.REVERSAL: self._reverse,
        }[event.kind]
        return handler(event)

    def _validate(self, event: Event) -> Optional[str]:
        if any(r.event.id == event.id for r in self._journal):
            return f"duplicate event id {event.id}; already processed"
        if event.account not in self.accounts:
            return f"unknown account {event.account}"
        first, last = self.rules.first_day, self.rules.last_day
        if not first <= event.day <= last:
            return f"stamped Day {event.day}, outside the Day {first}-{last} window"
        if event.day > self.current_day:
            return f"stamped Day {event.day} but the ledger is on Day {self.current_day}"
        if not first <= event.value_date <= last:
            return f"value date Day {event.value_date} is outside the Day {first}-{last} window"
        if event.kind is EventKind.REVERSAL:
            if not event.reverses:
                return "reversal does not name the event it reverses"
            return None
        if event.amount is None:
            return f"{event.kind.value} has no amount"
        currency = self.accounts[event.account]
        if event.amount.currency != currency:
            return f"amount in {event.amount.currency} but {event.account} is a {currency} account"
        if not event.amount.is_positive:
            return f"amount must be positive, got {event.amount.format()}"
        if event.kind in (EventKind.AUTHORIZATION, EventKind.SETTLEMENT) and not event.auth_id:
            return f"{event.kind.value} has no authorization id"
        if event.instalments < 1:
            return f"instalments must be >= 1, got {event.instalments}"
        if event.instalments > 1 and event.kind is not EventKind.CREDIT:
            return "only credits may be split into instalments"
        return None

    def _credit(self, event: Event) -> JournalRecord:
        parts = allocate(event.amount, event.instalments)
        ids = [event.id] if len(parts) == 1 else [f"{event.id}#{i}" for i in range(1, len(parts) + 1)]
        for entry_id, part in zip(ids, parts):
            self._append_entry(
                id=entry_id,
                account=event.account,
                kind=EntryKind.CREDIT,
                amount=part,
                value_date=event.value_date,
                source=event.id,
            )
        if len(parts) == 1:
            detail = f"credited {event.amount}"
        else:
            detail = (
                f"credited {event.amount} as {len(parts)} instalments "
                f"({' + '.join(p.format() for p in parts)})"
            )
        return self._record(event, Outcome.POSTED, detail)

    def _debit(self, event: Event) -> JournalRecord:
        # Booked debits are not authorizations: they post even if they overdraw.
        self._append_entry(
            id=event.id,
            account=event.account,
            kind=EntryKind.DEBIT,
            amount=-event.amount,
            value_date=event.value_date,
            source=event.id,
        )
        return self._record(event, Outcome.POSTED, f"debited {event.amount}")

    def _authorize(self, event: Event) -> JournalRecord:
        if self._authorization(event.auth_id) is not None:
            return self._record(
                event, Outcome.REJECTED, f"authorization id {event.auth_id} already used"
            )
        ledger = self.closing_balance(event.account, self.current_day)
        holds = self.active_holds(event.account)
        after = ledger - holds - event.amount
        working = (
            f"ledger {ledger.format()} - holds {holds.format()} - "
            f"{event.amount.format()} = {after.format()}"
        )
        if after.is_negative:
            return self._record(
                event, Outcome.DECLINED, f"{event.auth_id} declined: available after hold {working}"
            )
        self._holds.append(
            HoldRecord(
                self._next_seq(),
                event.auth_id,
                event.account,
                HoldAction.PLACE,
                event.amount,
                self.current_day,
                event.id,
            )
        )
        return self._record(
            event, Outcome.APPROVED, f"{event.auth_id} approved: available after hold {working}"
        )

    def _settle(self, event: Event) -> JournalRecord:
        auth = self._authorization(event.auth_id)
        if auth is None:
            return self._record(
                event,
                Outcome.REJECTED,
                f"settlement references {event.auth_id}, which has no authorization "
                f"in the ledger; nothing posted, no funds moved",
            )
        state = self.auth_state(event.auth_id)
        if state is AuthState.DECLINED:
            return self._record(
                event, Outcome.REJECTED, f"{event.auth_id} was declined; nothing to settle"
            )
        if state is AuthState.SETTLED:
            return self._record(
                event, Outcome.REJECTED, f"{event.auth_id} is already settled"
            )
        if auth.event.account != event.account:
            return self._record(
                event,
                Outcome.REJECTED,
                f"{event.auth_id} belongs to {auth.event.account}, not {event.account}",
            )
        held = self.held_amount(event.auth_id)
        if held < event.amount:
            return self._record(
                event,
                Outcome.REJECTED,
                f"settlement {event.amount.format()} exceeds hold {held.format()} on "
                f"{event.auth_id}; no over-settlement tolerance is defined",
            )
        self._append_entry(
            id=event.id,
            account=event.account,
            kind=EntryKind.SETTLEMENT,
            amount=-event.amount,
            value_date=event.value_date,
            source=event.id,
            memo=event.auth_id,
        )
        self._holds.append(
            HoldRecord(
                self._next_seq(),
                event.auth_id,
                event.account,
                HoldAction.RELEASE,
                held,
                self.current_day,
                event.id,
            )
        )
        unused = held - event.amount
        return self._record(
            event,
            Outcome.POSTED,
            f"{event.auth_id} settled for {event.amount}; hold {held.format()} released "
            f"({unused.format()} unused)",
        )

    def _reverse(self, event: Event) -> JournalRecord:
        target = event.reverses
        originals = [e for e in self._entries if e.source == target and e.kind in REVERSIBLE]
        if not originals:
            known = any(r.event.id == target for r in self._journal)
            why = "did not post to the ledger" if known else "is not in the ledger"
            return self._record(event, Outcome.REJECTED, f"cannot reverse {target}: it {why}")
        if any(o.account != event.account for o in originals):
            return self._record(
                event, Outcome.REJECTED, f"{target} was not posted to {event.account}"
            )
        original_ids = {o.id for o in originals}
        if any(e.reverses in original_ids for e in self._entries):
            return self._record(event, Outcome.REJECTED, f"{target} is already reversed")
        for i, original in enumerate(originals, start=1):
            self._append_entry(
                id=event.id if len(originals) == 1 else f"{event.id}#{i}",
                account=event.account,
                kind=EntryKind.REVERSAL,
                amount=-original.amount,
                value_date=event.value_date,
                source=event.id,
                reverses=original.id,
            )
        total = sum_money((-o.amount for o in originals), self.accounts[event.account])
        return self._record(
            event, Outcome.POSTED, f"reversed {target}: {total} back-valued to Day {event.value_date}"
        )

    # ------------------------------------------------------------ end of day

    def close_day(self) -> DayReport:
        """Run end-of-day for the open day and advance the clock.

        Order: (1) overdraft fees for every day up to today, re-evaluated by
        value date so back-valued entries are caught; (2) interest accrual
        schedule recomputed for every day up to today, deltas appended;
        (3) on the last day of the window, capitalize.
        """
        if self.closed:
            raise WindowClosed("window already closed")
        day = self.current_day
        before = {
            acct: {d: self.closing_balance(acct, d) for d in range(self.rules.first_day, day + 1)}
            for acct in sorted(self.accounts)
        }
        fees = self._assess_fees(day)
        accruals = self._accrue_interest(day)
        capitalized = self._capitalize(day) if day == self.rules.last_day else {}
        report = self._snapshot(day, before, fees, accruals, capitalized)
        self._closed_through = day
        return report

    def _assess_fees(self, day: int) -> List[Entry]:
        booked: List[Entry] = []
        for acct in sorted(self.accounts):
            currency = self.accounts[acct]
            # Ascending, so a fee booked for an earlier day is already in the
            # balance when a later day is tested (fees are entries too).
            for d in range(self.rules.first_day, day + 1):
                if self.fee_for_day(acct, d) is not None:
                    continue  # once per day per account, ever
                balance = self.closing_balance(acct, d)
                if not balance.is_negative:
                    continue
                fee = self.rules.overdraft_fees.get(currency)
                if fee is None:
                    self._problem(
                        Severity.ERROR,
                        f"EOD-{day}",
                        f"{acct} closed Day {d} at {balance} but no overdraft fee is defined "
                        f"in {currency} and no FX rate is given; fee not assessed",
                        key=("no-fee", acct, d),
                    )
                    continue
                if fee.currency != currency:
                    raise LedgerInvariantError(f"fee schedule for {currency} is in {fee.currency}")
                booked.append(
                    self._append_entry(
                        id=f"FEE-{acct}-D{d}",
                        account=acct,
                        kind=EntryKind.OVERDRAFT_FEE,
                        amount=-fee,
                        value_date=d,
                        source=f"EOD-{day}",
                        memo=f"Day {d} closed at {balance.format()}",
                    )
                )
        return booked

    def accrual_schedule(self, account: str, through: int) -> Dict[int, Money]:
        """Rounded interest for each day up to ``through`` on current knowledge.

        Carry-forward rounding: day d's accrual is round(cumulative raw to d)
        minus round(cumulative raw to d-1). The rounded days therefore always
        sum to round(total raw) — no residue exists to be discarded.
        Interest entries are excluded from the base: no compounding before
        capitalization.
        """
        currency = self.accounts[account]
        cumulative = Decimal(0)
        rounded_so_far = 0
        schedule: Dict[int, Money] = {}
        for d in range(self.rules.first_day, through + 1):
            base = self.closing_balance(account, d, exclude=(EntryKind.INTEREST,))
            if base.is_positive:
                # The raw product and running sum must be exact; if the Decimal
                # context ever ran out of digits, raise rather than round here.
                with localcontext() as ctx:
                    ctx.traps[Inexact] = True
                    cumulative += Decimal(base.minor) * self.rules.daily_rate
            rounded = round_minor(cumulative)
            schedule[d] = Money(currency, rounded - rounded_so_far)
            rounded_so_far = rounded
        return schedule

    def _accrue_interest(self, day: int) -> List[AccrualRecord]:
        written: List[AccrualRecord] = []
        for acct in sorted(self.accounts):
            for d, target in self.accrual_schedule(acct, day).items():
                if d == day:
                    delta, adjustment = target, False  # today's original accrual, even if zero
                else:
                    delta, adjustment = target - self.accrued(acct, d), True
                    if delta.minor == 0:
                        continue
                record = AccrualRecord(self._next_seq(), acct, d, delta, day, adjustment)
                self._accruals.append(record)
                written.append(record)
        return written

    def _capitalize(self, day: int) -> Dict[str, Money]:
        result: Dict[str, Money] = {}
        for acct in sorted(self.accounts):
            currency = self.accounts[acct]
            total = sum_money((a.amount for a in self._accruals if a.account == acct), currency)
            per_day = [self.accrued(acct, d) for d in self.window()]
            schedule = self.accrual_schedule(acct, day)
            # The non-negotiable: rounded daily accruals sum exactly to the credit.
            if sum_money(per_day, currency) != total or any(
                self.accrued(acct, d) != schedule[d] for d in self.window()
            ):
                raise LedgerInvariantError(f"{acct}: accrual records disagree with schedule")
            if total.is_negative:
                raise LedgerInvariantError(f"{acct}: negative interest {total}")
            if total.minor:
                self._append_entry(
                    id=f"INT-{acct}",
                    account=acct,
                    kind=EntryKind.INTEREST,
                    amount=total,
                    value_date=day,
                    source=f"EOD-{day}",
                    memo=f"capitalize Day {self.rules.first_day}-{day} accruals",
                )
            result[acct] = total
        return result

    def _snapshot(self, day, before, fees, accruals, capitalized) -> DayReport:
        fee_by_key = {(f.account, f.value_date): f.amount for f in fees}
        accounts = []
        for acct in sorted(self.accounts):
            currency = self.accounts[acct]
            restated = tuple(
                RestatedDay(d, before[acct][d], fee_by_key.get((acct, d)), self.closing_balance(acct, d))
                for d in range(self.rules.first_day, day + 1)
            )
            ledger = self.closing_balance(acct, day)
            holds = self.active_holds(acct)
            accrued = sum_money(
                (self.accrued(acct, d) for d in range(self.rules.first_day, day + 1)), currency
            )
            accounts.append(
                AccountClose(acct, currency, restated, ledger, holds, ledger - holds, accrued, capitalized.get(acct))
            )
        auths = []
        for auth_id in self.auth_ids():
            record = self._authorization(auth_id)
            state = self.auth_state(auth_id)
            if state is AuthState.SETTLED:
                release = next(h for h in self._hold_records(auth_id) if h.action is HoldAction.RELEASE)
                detail = f"hold {self.held_amount(auth_id).format()} released by {release.source}"
            elif state is AuthState.ACTIVE:
                detail = f"hold {self.held_amount(auth_id).format()} active"
            else:
                detail = record.detail.split(": ", 1)[-1]
            auths.append(AuthSnapshot(auth_id, record.event.account, state, detail))
        return DayReport(
            day=day,
            events=tuple(r for r in self._journal if r.processed_day == day),
            problems=tuple(p for p in self._problems if p.day == day),
            fees=tuple(fees),
            accruals=tuple(accruals),
            auths=tuple(auths),
            accounts=tuple(accounts),
        )
