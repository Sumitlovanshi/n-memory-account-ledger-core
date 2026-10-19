"""Inbound event records. Frozen: once an event exists it is never changed."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .money import Money


class EventKind(str, Enum):
    CREDIT = "CREDIT"
    DEBIT = "DEBIT"
    AUTHORIZATION = "AUTHORIZATION"
    SETTLEMENT = "SETTLEMENT"
    REVERSAL = "REVERSAL"


@dataclass(frozen=True)
class Event:
    """One line of the inbound stream.

    ``day`` is the day stamped on the event (the "Booked" column of the brief);
    ``value_date`` is the day the money counts from. Amounts are positive
    magnitudes — the kind decides the sign of the resulting ledger entry.
    """

    id: str
    day: int
    kind: EventKind
    account: str
    value_date: int
    amount: Optional[Money] = None
    auth_id: Optional[str] = None
    reverses: Optional[str] = None
    instalments: int = 1
