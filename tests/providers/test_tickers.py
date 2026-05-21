import pytest

from puts_screener.providers import tickers

_EU_EXPECTED = {
    ".L": "uk",
    ".DE": "de",
    ".PA": "fr",
    ".MI": "it",
    ".MC": "es",
    ".AS": "nl",
    ".SW": "ch",
    ".CO": "dk",
    ".ST": "se",
    ".HE": "fi",
    ".OL": "no",
    ".BR": "be",
    ".LS": "pt",
    ".VI": "at",
}


def test_to_stooq_us():
    assert tickers.to_stooq("AAPL") == "aapl.us"


def test_to_stooq_known_europe():
    assert tickers.to_stooq("VOW3.DE") == "vow3.de"
    assert tickers.to_stooq("ASML.AS") == "asml.nl"
    assert tickers.to_stooq("NESN.SW") == "nesn.ch"
    assert tickers.to_stooq("SAN.MC") == "san.es"


@pytest.mark.parametrize(("suffix", "country"), list(_EU_EXPECTED.items()))
def test_to_stooq_all_eu_suffixes(suffix, country):
    assert tickers.to_stooq(f"FOO{suffix}") == f"foo.{country}"


def test_to_stooq_unsupported_suffix_raises():
    with pytest.raises(ValueError):
        tickers.to_stooq("TICKER.TO")


def test_to_yfinance_identity():
    assert tickers.to_yfinance("ASML.AS") == "ASML.AS"


def test_to_finnhub_identity():
    assert tickers.to_finnhub("AAPL") == "AAPL"
    assert tickers.to_finnhub("ASML.AS") == "ASML.AS"


def test_is_us_ticker():
    assert tickers.is_us_ticker("AAPL") is True
    assert tickers.is_us_ticker("ASML.AS") is False
