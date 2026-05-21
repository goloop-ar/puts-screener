import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from puts_screener.providers import cache, rate_limit
from puts_screener.providers.base import NotSupportedError, ProviderError
from puts_screener.providers.finnhub_provider import FinnhubProvider

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _load(name):
    return json.loads((FIXTURES / name).read_text())


def _enabled_provider():
    provider = FinnhubProvider(api_key="test_key")
    provider._client = MagicMock()
    return provider


class _FakeTime:
    def __init__(self):
        self.now = 1000.0
        self.sleeps: list[float] = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def test_disabled_provider_raises(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    provider = FinnhubProvider()
    assert provider._enabled is False
    with pytest.raises(ProviderError):
        provider.get_company_profile("AAPL")
    with pytest.raises(ProviderError):
        provider.get_analyst_data("AAPL")
    with pytest.raises(ProviderError):
        provider.get_rating_changes("AAPL")
    with pytest.raises(ProviderError):
        provider.get_upcoming_earnings("AAPL")


def test_company_profile_happy(tmp_cache_root):
    provider = _enabled_provider()
    provider._client.company_profile2.return_value = _load("finnhub_aapl_profile.json")
    profile = provider.get_company_profile("AAPL")
    assert profile.name == "Apple Inc"
    assert profile.sector == "Technology"
    assert profile.industry == "Technology"
    assert profile.market_cap_usd == 3_000_000 * 1e6
    assert profile.avg_daily_volume_3m is None


def test_company_profile_empty_raises(tmp_cache_root):
    provider = _enabled_provider()
    provider._client.company_profile2.return_value = {}
    with pytest.raises(ProviderError):
        provider.get_company_profile("AAPL")


def test_analyst_data_happy(tmp_cache_root):
    provider = _enabled_provider()
    provider._client.recommendation_trends.return_value = _load("finnhub_aapl_recommendation.json")
    provider._client.price_target.return_value = _load("finnhub_aapl_price_target.json")
    data = provider.get_analyst_data("AAPL")
    assert data.price_target_mean == 215.0
    assert data.n_analysts == 30
    assert data.strong_buy_count == 20
    assert data.recommendation_mean == pytest.approx(87 / 46)


def test_analyst_data_zero_counts(tmp_cache_root):
    provider = _enabled_provider()
    provider._client.recommendation_trends.return_value = [
        {"strongBuy": 0, "buy": 0, "hold": 0, "sell": 0, "strongSell": 0}
    ]
    provider._client.price_target.return_value = _load("finnhub_aapl_price_target.json")
    data = provider.get_analyst_data("AAPL")
    assert data.recommendation_mean is None
    assert data.price_target_mean == 215.0


def test_rating_changes_mapping(tmp_cache_root):
    provider = _enabled_provider()
    provider._client.upgrade_downgrade.return_value = _load("finnhub_aapl_upgrade_downgrade.json")
    changes = provider.get_rating_changes("AAPL", lookback_weeks=6)
    assert len(changes) == 2
    assert changes[0].action == "upgrade"
    assert changes[0].firm == "Morgan Stanley"
    assert changes[0].date == date(2024, 1, 3)
    assert changes[1].action == "downgrade"
    assert changes[1].date == date(2023, 12, 31)
    # el SDK de Finnhub usa el kwarg `_from` (no `from_`)
    _, kwargs = provider._client.upgrade_downgrade.call_args
    assert "_from" in kwargs
    assert "from_" not in kwargs


def test_upcoming_earnings_happy(tmp_cache_root):
    provider = _enabled_provider()
    provider._client.earnings_calendar.return_value = _load("finnhub_aapl_earnings.json")
    event = provider.get_upcoming_earnings("AAPL")
    assert event is not None
    assert event.date == date(2024, 2, 1)
    assert event.eps_estimate == 2.1
    assert event.eps_actual is None
    assert event.when == "amc"


def test_upcoming_earnings_empty(tmp_cache_root):
    provider = _enabled_provider()
    provider._client.earnings_calendar.return_value = {"earningsCalendar": []}
    assert provider.get_upcoming_earnings("AAPL") is None


def test_rate_limit_blocks_third_call(monkeypatch, disable_cache):
    fake = _FakeTime()
    monkeypatch.setattr(rate_limit, "time", fake)
    provider = FinnhubProvider(api_key="test_key", max_per_minute=2)
    provider._client = MagicMock()
    provider._client.company_profile2.return_value = _load("finnhub_aapl_profile.json")
    provider.get_company_profile("AAPL")
    provider.get_company_profile("AAPL")
    assert fake.sleeps == []
    provider.get_company_profile("AAPL")
    assert len(fake.sleeps) == 1
    assert fake.sleeps[0] > 0


def test_profile_cache_hit_skips_client(tmp_cache_root):
    provider = _enabled_provider()
    cached = {
        "ticker": "AAPL",
        "name": "Cached",
        "sector": "Tech",
        "industry": "Tech",
        "exchange": "NASDAQ",
        "country": "US",
        "market_cap_usd": 1.0,
        "currency": "USD",
        "avg_daily_volume_3m": None,
    }
    cache.write_cache("profile", "finnhub_AAPL", cached)
    profile = provider.get_company_profile("AAPL")
    assert profile.name == "Cached"
    provider._client.company_profile2.assert_not_called()


def test_get_ohlcv_not_supported():
    provider = _enabled_provider()
    with pytest.raises(NotSupportedError):
        provider.get_ohlcv("AAPL", date(2024, 1, 1), date(2024, 2, 1))


def test_get_financials_not_supported():
    provider = _enabled_provider()
    with pytest.raises(NotSupportedError):
        provider.get_financials("AAPL")
