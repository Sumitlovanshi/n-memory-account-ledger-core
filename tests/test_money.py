import unittest
from dataclasses import FrozenInstanceError
from decimal import Decimal

from ledger.money import (
    AED,
    BHD,
    CurrencyMismatch,
    Money,
    PrecisionError,
    allocate,
    round_minor,
)


class ParseAndFormat(unittest.TestCase):
    def test_parse_uses_each_currencys_own_precision(self):
        self.assertEqual(Money.parse("1,200.00", AED).minor, 120000)
        self.assertEqual(Money.parse("10.000", BHD).minor, 10000)
        self.assertEqual(Money.parse("0.000", BHD).minor, 0)

    def test_parse_refuses_excess_precision_instead_of_rounding(self):
        with self.assertRaises(PrecisionError):
            Money.parse("0.001", AED)
        with self.assertRaises(PrecisionError):
            Money.parse("3.3334", BHD)

    def test_format_is_fixed_to_currency_precision(self):
        self.assertEqual(Money(AED, -37000).format(), "-370.00")
        self.assertEqual(Money(AED, 120000).format(), "1,200.00")
        self.assertEqual(Money(BHD, 3334).format(), "3.334")
        self.assertEqual(Money(BHD, 8).format(), "0.008")
        self.assertEqual(str(Money(AED, 5)), "AED 0.05")


class Arithmetic(unittest.TestCase):
    def test_cross_currency_arithmetic_is_refused(self):
        with self.assertRaises(CurrencyMismatch):
            Money(AED, 100) + Money(BHD, 100)
        with self.assertRaises(CurrencyMismatch):
            Money(AED, 100) < Money(BHD, 100)

    def test_money_is_immutable(self):
        m = Money(AED, 100)
        with self.assertRaises(FrozenInstanceError):
            m.minor = 200


class Allocation(unittest.TestCase):
    def test_ten_bhd_in_three_parts_conserves_every_fils(self):
        parts = allocate(Money.parse("10.000", BHD), 3)
        self.assertEqual([p.format() for p in parts], ["3.334", "3.333", "3.333"])
        self.assertEqual(sum(p.minor for p in parts), 10000)

    def test_three_times_3_334_is_not_ten(self):
        # The arithmetic behind rejecting acceptance criterion 7.
        self.assertEqual(3 * Money.parse("3.334", BHD).minor, 10002)

    def test_negative_allocation_mirrors_positive(self):
        parts = allocate(Money(BHD, -10000), 3)
        self.assertEqual([p.minor for p in parts], [-3334, -3333, -3333])

    def test_even_split_has_no_remainder(self):
        self.assertEqual([p.minor for p in allocate(Money(AED, 900), 3)], [300, 300, 300])


class Rounding(unittest.TestCase):
    def test_half_even(self):
        self.assertEqual(round_minor(Decimal("18.5")), 18)
        self.assertEqual(round_minor(Decimal("19.5")), 20)
        self.assertEqual(round_minor(Decimal("18.6")), 19)
        self.assertEqual(round_minor(Decimal("0.2")), 0)


if __name__ == "__main__":
    unittest.main()
