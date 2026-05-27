"""Tests de format_price (spec 06 §6.4)."""

from puts_screener.formatting import format_price


def test_format_price_usd():
    assert format_price(150.23, "USD") == "$150.23"


def test_format_price_gbp_pence():
    assert format_price(453.55, "GBp") == "453.55p"


def test_format_price_eur():
    assert format_price(82.10, "EUR") == "€82.10"


def test_format_price_chf():
    assert format_price(100.0, "CHF") == "100.00 CHF"


def test_format_price_none_fallback():
    assert format_price(42.00, None) == "$42.00"
