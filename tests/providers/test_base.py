from datetime import date

import pytest

from puts_screener.providers.base import DataProvider, NotSupportedError


class OnlyOhlcvProvider(DataProvider):
    """Provider de prueba que solo overridea get_ohlcv."""

    name = "only_ohlcv"

    def get_ohlcv(self, ticker, start, end, interval="1d"):
        return "ohlcv-data"


def test_base_methods_raise_not_supported():
    provider = DataProvider()
    with pytest.raises(NotSupportedError):
        provider.get_ohlcv("AAPL", date(2024, 1, 1), date(2024, 2, 1))
    with pytest.raises(NotSupportedError):
        provider.get_company_profile("AAPL")
    with pytest.raises(NotSupportedError):
        provider.get_financials("AAPL")
    with pytest.raises(NotSupportedError):
        provider.get_analyst_data("AAPL")
    with pytest.raises(NotSupportedError):
        provider.get_rating_changes("AAPL")
    with pytest.raises(NotSupportedError):
        provider.get_upcoming_earnings("AAPL")


def test_supports_reports_overridden_methods():
    provider = OnlyOhlcvProvider()
    assert provider.supports("get_ohlcv") is True
    assert provider.supports("get_company_profile") is False


def test_supports_rejects_unknown_method():
    provider = OnlyOhlcvProvider()
    with pytest.raises(ValueError):
        provider.supports("get_nonexistent")
