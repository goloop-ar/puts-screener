from datetime import date
from pathlib import Path

import pytest
import responses

from puts_screener.providers import cache
from puts_screener.providers.base import NotSupportedError, ProviderError
from puts_screener.providers.stooq import StooqProvider

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
_STOOQ_URL = "https://stooq.com/q/d/l/"


@responses.activate
def test_get_ohlcv_happy_path(tmp_cache_root):
    body = (FIXTURES / "stooq_aapl_daily.csv").read_text()
    responses.add(responses.GET, _STOOQ_URL, body=body, status=200)
    provider = StooqProvider()
    df = provider.get_ohlcv("AAPL", date(2024, 1, 2), date(2024, 1, 4), "1d")
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert len(df) == 3
    assert df.index.is_monotonic_increasing
    assert df.iloc[0]["Close"] == 185.5


@responses.activate
def test_no_data_raises_provider_error(tmp_cache_root):
    body = (FIXTURES / "stooq_empty.csv").read_text()
    responses.add(responses.GET, _STOOQ_URL, body=body, status=200)
    provider = StooqProvider()
    with pytest.raises(ProviderError):
        provider.get_ohlcv("AAPL", date(2024, 1, 2), date(2024, 1, 4), "1d")


@responses.activate
def test_http_error_raises_provider_error(tmp_cache_root):
    responses.add(responses.GET, _STOOQ_URL, body="server error", status=500)
    provider = StooqProvider()
    with pytest.raises(ProviderError):
        provider.get_ohlcv("AAPL", date(2024, 1, 2), date(2024, 1, 4), "1d")


def test_invalid_interval_raises_value_error(tmp_cache_root):
    provider = StooqProvider()
    with pytest.raises(ValueError):
        provider.get_ohlcv("AAPL", date(2024, 1, 2), date(2024, 1, 4), "5m")


def test_unsupported_ticker_propagates_value_error(tmp_cache_root):
    provider = StooqProvider()
    with pytest.raises(ValueError):
        provider.get_ohlcv("X.TO", date(2024, 1, 2), date(2024, 1, 4), "1d")


@responses.activate
def test_cache_hit_skips_network(tmp_cache_root, sample_ohlcv_df):
    cache.write_ohlcv("AAPL", "1d", sample_ohlcv_df)
    provider = StooqProvider()
    start = sample_ohlcv_df.index[2].date()
    end = sample_ohlcv_df.index[10].date()
    df = provider.get_ohlcv("AAPL", start, end, "1d")
    assert not df.empty
    assert len(responses.calls) == 0


def test_company_profile_not_supported(tmp_cache_root):
    provider = StooqProvider()
    with pytest.raises(NotSupportedError):
        provider.get_company_profile("AAPL")
