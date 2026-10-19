"""Currency-aware money held as integer minor units.

Every amount in the ledger is an ``int`` count of the currency's minor unit
(fils for both AED and BHD — 1/100 and 1/1000 respectively). Integer addition
is exact, so the only place rounding can ever happen is the explicit
``round_minor`` call used by interest accrual. Parsing refuses any input that
carries more decimals than the currency allows instead of silently rounding it.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import List

# One rounding mode for the whole ledger. See NUMBERS.md for why half-even.
ROUNDING = ROUND_HALF_EVEN


@dataclass(frozen=True)
class Currency:
    code: str
    exponent: int  # ISO 4217 minor-unit digits

    def __str__(self) -> str:
        return self.code


AED = Currency("AED", 2)
BHD = Currency("BHD", 3)


class CurrencyMismatch(ValueError):
    pass


class PrecisionError(ValueError):
    pass


@dataclass(frozen=True)
class Money:
    currency: Currency
    minor: int

    @classmethod
    def parse(cls, text: str, currency: Currency) -> Money:
        """Parse '1,200.00' into minor units, refusing excess precision."""
        value = Decimal(text.replace(",", ""))
        scaled = value.scaleb(currency.exponent)
        if scaled != scaled.to_integral_value():
            raise PrecisionError(
                f"{text} has more than {currency.exponent} decimals for {currency}"
            )
        return cls(currency, int(scaled))

    @classmethod
    def zero(cls, currency: Currency) -> Money:
        return cls(currency, 0)

    def _check(self, other: Money) -> None:
        if not isinstance(other, Money):
            raise TypeError(f"cannot combine Money with {type(other).__name__}")
        if other.currency != self.currency:
            raise CurrencyMismatch(f"{self.currency} vs {other.currency}")

    def __add__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.currency, self.minor + other.minor)

    def __sub__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.currency, self.minor - other.minor)

    def __neg__(self) -> Money:
        return Money(self.currency, -self.minor)

    def __lt__(self, other: Money) -> bool:
        self._check(other)
        return self.minor < other.minor

    def __le__(self, other: Money) -> bool:
        self._check(other)
        return self.minor <= other.minor

    @property
    def is_negative(self) -> bool:
        return self.minor < 0

    @property
    def is_positive(self) -> bool:
        return self.minor > 0

    def as_decimal(self) -> Decimal:
        return Decimal(self.minor).scaleb(-self.currency.exponent)

    def format(self) -> str:
        """'1,200.00' / '-370.00' / '3.334' — fixed at the currency's precision."""
        sign = "-" if self.minor < 0 else ""
        whole, frac = divmod(abs(self.minor), 10 ** self.currency.exponent)
        return f"{sign}{whole:,}.{frac:0{self.currency.exponent}d}"

    def __str__(self) -> str:
        return f"{self.currency} {self.format()}"


def sum_money(amounts, currency: Currency) -> Money:
    total = Money.zero(currency)
    for amount in amounts:
        total = total + amount
    return total


def allocate(total: Money, parts: int) -> List[Money]:
    """Split ``total`` into ``parts`` amounts that differ by at most one minor
    unit and sum exactly to ``total``. Leftover minor units go to the earliest
    parts, so 10.000 BHD / 3 -> [3.334, 3.333, 3.333]."""
    if parts < 1:
        raise ValueError("parts must be >= 1")
    sign = -1 if total.minor < 0 else 1
    base, leftover = divmod(abs(total.minor), parts)
    return [
        Money(total.currency, sign * (base + (1 if i < leftover else 0)))
        for i in range(parts)
    ]


def round_minor(value: Decimal) -> int:
    """Round a fractional count of minor units to a whole one."""
    return int(value.to_integral_value(rounding=ROUNDING))
