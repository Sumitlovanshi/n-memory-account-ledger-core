"""Drive a ledger through an event stream in the order given.

The driver owns the business clock: before an event stamped for a later day
is submitted, every day before it is closed. An event stamped for a day that is
already closed (E10) is not re-ordered — it is processed on the open day and
the ledger flags it as a late arrival.
"""
from __future__ import annotations

from typing import Callable, Iterable, List, Optional

from .engine import DayReport, Ledger
from .events import Event

BeforeClose = Callable[[int, Ledger], None]


def replay(
    events: Iterable[Event],
    ledger: Ledger,
    before_close: Optional[BeforeClose] = None,
) -> List[DayReport]:
    reports: List[DayReport] = []

    def close() -> None:
        if before_close is not None:
            before_close(ledger.current_day, ledger)
        reports.append(ledger.close_day())

    for event in events:
        while ledger.current_day < event.day <= ledger.rules.last_day:
            close()
        ledger.submit(event)
    while not ledger.closed:
        close()
    return reports
