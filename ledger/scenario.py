"""The six-day window, the two accounts and the E1..E10 stream from the brief,
transcribed verbatim and kept in the brief's order (E10 after E9)."""
from __future__ import annotations

from .events import Event, EventKind
from .money import AED, BHD, Money

FIRST_DAY = 1
LAST_DAY = 6

ACCOUNTS = {
    "ACC-001": AED,
    "ACC-002": BHD,
}


def aed(text: str) -> Money:
    return Money.parse(text, AED)


def bhd(text: str) -> Money:
    return Money.parse(text, BHD)


K = EventKind

EVENTS = (
    Event("E1", 1, K.CREDIT, "ACC-001", value_date=1, amount=aed("1,200.00")),
    Event("E2", 1, K.DEBIT, "ACC-001", value_date=1, amount=aed("950.00")),
    Event("E3", 2, K.AUTHORIZATION, "ACC-001", value_date=2, amount=aed("200.00"), auth_id="Auth-A"),
    Event("E4", 3, K.CREDIT, "ACC-001", value_date=3, amount=aed("400.00")),
    Event("E5", 4, K.SETTLEMENT, "ACC-001", value_date=4, amount=aed("185.00"), auth_id="Auth-A"),
    # Auth-Z has no preceding authorization event.
    Event("E6", 4, K.SETTLEMENT, "ACC-001", value_date=4, amount=aed("180.00"), auth_id="Auth-Z"),
    # Booked Day 5, value-dated Day 2: back-valued three days.
    Event("E7", 5, K.DEBIT, "ACC-001", value_date=2, amount=aed("620.00")),
    # Auth-B is never settled inside the window.
    Event("E8", 5, K.AUTHORIZATION, "ACC-001", value_date=5, amount=aed("90.00"), auth_id="Auth-B"),
    Event("E9", 6, K.REVERSAL, "ACC-001", value_date=2, reverses="E7"),
    # Stamped Day 5 but listed after a Day 6 event: a late arrival.
    Event("E10", 5, K.CREDIT, "ACC-002", value_date=5, amount=bhd("10.000"), instalments=3),
)
