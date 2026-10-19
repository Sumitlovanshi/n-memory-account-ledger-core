"""python3 -m ledger — replay the E1..E10 stream and print every day."""
from __future__ import annotations

from .engine import Ledger
from .replay import replay
from .report import render_day, render_summary
from .scenario import ACCOUNTS, EVENTS


def main() -> None:
    ledger = Ledger(ACCOUNTS)
    reports = replay(EVENTS, ledger)
    previous = None
    for report in reports:
        print(render_day(report, previous))
        print()
        previous = report
    print(render_summary(ledger))


if __name__ == "__main__":
    main()
