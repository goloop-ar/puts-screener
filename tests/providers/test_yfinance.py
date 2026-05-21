import json
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

from puts_screener.providers import cache, yfinance_provider
from puts_screener.providers.base import ProviderError
from puts_screener.providers.yfinance_provider import YFinanceProvider

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _mock_ticker(monkeypatch, ticker_mock):
    monkeypatch.setattr(yfinance_provider, "_get_ticker", lambda symbol: ticker_mock)


def _build_statement(periods, rows):
    columns = [pd.Timestamp(p) for p in periods]
    return pd.DataFrame(rows, index=columns).T


def test_get_ohlcv_happy(tmp_cache_root, monkeypatch):
    hist = pd.read_parquet(FIXTURES / "yfinance_aapl_history.parquet")
    tk = MagicMock()
    tk.history.return_value = hist
    _mock_ticker(monkeypatch, tk)
    provider = YFinanceProvider()
    df = provider.get_ohlcv("AAPL", date(2024, 1, 2), date(2024, 1, 5), "1d")
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert df.index.tz is None
    assert len(df) == 4


def test_get_ohlcv_empty_raises(tmp_cache_root, monkeypatch):
    tk = MagicMock()
    tk.history.return_value = pd.DataFrame()
    _mock_ticker(monkeypatch, tk)
    provider = YFinanceProvider()
    with pytest.raises(ProviderError):
        provider.get_ohlcv("AAPL", date(2024, 1, 2), date(2024, 1, 5), "1d")


def test_get_company_profile_happy(tmp_cache_root, monkeypatch):
    info = json.loads((FIXTURES / "yfinance_aapl_info.json").read_text())
    tk = MagicMock()
    tk.info = info
    _mock_ticker(monkeypatch, tk)
    provider = YFinanceProvider()
    profile = provider.get_company_profile("AAPL")
    assert profile.name == "Apple Inc."
    assert profile.sector == "Technology"
    assert profile.market_cap_usd == 3000000000000
    assert profile.avg_daily_volume_3m == 55000000


def test_get_company_profile_empty_raises(tmp_cache_root, monkeypatch):
    tk = MagicMock()
    tk.info = {}
    _mock_ticker(monkeypatch, tk)
    provider = YFinanceProvider()
    with pytest.raises(ProviderError):
        provider.get_company_profile("AAPL")


def test_get_financials_happy(tmp_cache_root, monkeypatch):
    payload = json.loads((FIXTURES / "yfinance_aapl_cashflow.json").read_text())
    tk = MagicMock()
    tk.cashflow = _build_statement(payload["periods"], payload["cashflow"])
    tk.financials = _build_statement(payload["periods"], payload["financials"])
    _mock_ticker(monkeypatch, tk)
    provider = YFinanceProvider()
    snap = provider.get_financials("AAPL")
    assert snap.free_cash_flow_ttm == 99584000000.0
    assert snap.total_revenue_ttm == 383285000000.0
    assert snap.fiscal_year_end == date(2023, 9, 30)
    assert snap.as_of is not None


def test_get_financials_missing_fcf(tmp_cache_root, monkeypatch):
    payload = json.loads((FIXTURES / "yfinance_aapl_cashflow.json").read_text())
    tk = MagicMock()
    tk.cashflow = _build_statement(
        payload["periods"], {"Operating Cash Flow": payload["cashflow"]["Operating Cash Flow"]}
    )
    tk.cash_flow = pd.DataFrame()
    tk.financials = _build_statement(payload["periods"], payload["financials"])
    _mock_ticker(monkeypatch, tk)
    provider = YFinanceProvider()
    snap = provider.get_financials("AAPL")
    assert snap.free_cash_flow_ttm is None
    assert snap.total_revenue_ttm == 383285000000.0


def test_get_upcoming_earnings_in_window(tmp_cache_root, monkeypatch):
    upcoming = date.today() + timedelta(days=10)
    tk = MagicMock()
    tk.calendar = {"Earnings Date": [upcoming]}
    _mock_ticker(monkeypatch, tk)
    provider = YFinanceProvider()
    event = provider.get_upcoming_earnings("AAPL", lookforward_days=60)
    assert event is not None
    assert event.date == upcoming


def test_get_upcoming_earnings_out_of_window(tmp_cache_root, monkeypatch):
    far = date.today() + timedelta(days=400)
    tk = MagicMock()
    tk.calendar = {"Earnings Date": [far]}
    _mock_ticker(monkeypatch, tk)
    provider = YFinanceProvider()
    assert provider.get_upcoming_earnings("AAPL", lookforward_days=60) is None


def test_ohlcv_cache_hit_skips_ticker(tmp_cache_root, sample_ohlcv_df, monkeypatch):
    cache.write_ohlcv("AAPL", "1d", sample_ohlcv_df)
    mock_get = MagicMock()
    monkeypatch.setattr(yfinance_provider, "_get_ticker", mock_get)
    provider = YFinanceProvider()
    start = sample_ohlcv_df.index[2].date()
    end = sample_ohlcv_df.index[8].date()
    df = provider.get_ohlcv("AAPL", start, end, "1d")
    assert not df.empty
    mock_get.assert_not_called()


def test_profile_cache_hit_skips_ticker(tmp_cache_root, monkeypatch):
    cached = {
        "ticker": "AAPL",
        "name": "Cached Co",
        "sector": "Tech",
        "industry": "X",
        "exchange": "NMS",
        "country": "US",
        "market_cap_usd": 1.0,
        "currency": "USD",
        "avg_daily_volume_3m": 1.0,
    }
    cache.write_cache("profile", "yfinance_AAPL", cached)
    mock_get = MagicMock()
    monkeypatch.setattr(yfinance_provider, "_get_ticker", mock_get)
    provider = YFinanceProvider()
    profile = provider.get_company_profile("AAPL")
    assert profile.name == "Cached Co"
    mock_get.assert_not_called()


def test_financials_cache_hit_skips_ticker(tmp_cache_root, monkeypatch):
    cached = {
        "ticker": "AAPL",
        "free_cash_flow_ttm": 1.0,
        "total_revenue_ttm": 2.0,
        "fiscal_year_end": "2023-09-30",
        "as_of": "2024-01-01",
    }
    cache.write_cache("financials", "yfinance_AAPL", cached)
    mock_get = MagicMock()
    monkeypatch.setattr(yfinance_provider, "_get_ticker", mock_get)
    provider = YFinanceProvider()
    snap = provider.get_financials("AAPL")
    assert snap.fiscal_year_end == date(2023, 9, 30)
    mock_get.assert_not_called()


def test_earnings_cache_hit_skips_ticker(tmp_cache_root, monkeypatch):
    cached = {
        "ticker": "AAPL",
        "date": "2024-02-01",
        "eps_estimate": 2.1,
        "eps_actual": None,
        "when": "amc",
    }
    cache.write_cache("earnings", "yfinance_AAPL", cached)
    mock_get = MagicMock()
    monkeypatch.setattr(yfinance_provider, "_get_ticker", mock_get)
    provider = YFinanceProvider()
    event = provider.get_upcoming_earnings("AAPL")
    assert event is not None
    assert event.date == date(2024, 2, 1)
    mock_get.assert_not_called()
