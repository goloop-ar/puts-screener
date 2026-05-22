import json
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock

import pandas as pd
import pytest
from yfinance.exceptions import YFRateLimitError

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


def test_get_financials_raises_provider_error_on_yfinance_failure(tmp_cache_root, monkeypatch):
    tk = MagicMock()
    type(tk).cashflow = PropertyMock(side_effect=RuntimeError("yf schema boom"))
    _mock_ticker(monkeypatch, tk)
    provider = YFinanceProvider()
    with pytest.raises(ProviderError):
        provider.get_financials("AAPL")


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


def test_get_upcoming_ex_dividend_in_window(tmp_cache_root, monkeypatch):
    upcoming = date.today() + timedelta(days=8)
    tk = MagicMock()
    tk.calendar = {"Ex-Dividend Date": upcoming}
    tk.dividends = pd.Series([0.24, 0.25], index=pd.to_datetime(["2025-11-01", "2026-02-01"]))
    _mock_ticker(monkeypatch, tk)
    provider = YFinanceProvider()
    event = provider.get_upcoming_ex_dividend("AAPL", lookforward_days=45)
    assert event is not None
    assert event.date == upcoming
    assert event.amount == 0.25


def test_get_upcoming_ex_dividend_out_of_window(tmp_cache_root, monkeypatch):
    far = date.today() + timedelta(days=400)
    tk = MagicMock()
    tk.calendar = {"Ex-Dividend Date": far}
    tk.dividends = pd.Series([0.25], index=pd.to_datetime(["2026-02-01"]))
    _mock_ticker(monkeypatch, tk)
    provider = YFinanceProvider()
    assert provider.get_upcoming_ex_dividend("AAPL", lookforward_days=45) is None


def test_get_upcoming_ex_dividend_empty_calendar(tmp_cache_root, monkeypatch):
    tk = MagicMock()
    tk.calendar = {}
    _mock_ticker(monkeypatch, tk)
    provider = YFinanceProvider()
    assert provider.get_upcoming_ex_dividend("AAPL") is None


def test_get_upcoming_ex_dividend_calendar_raises_returns_none(tmp_cache_root, monkeypatch):
    tk = MagicMock()
    type(tk).calendar = PropertyMock(side_effect=RuntimeError("yf boom"))
    _mock_ticker(monkeypatch, tk)
    provider = YFinanceProvider()
    assert provider.get_upcoming_ex_dividend("AAPL") is None


def test_ex_dividend_cache_hit_skips_ticker(tmp_cache_root, monkeypatch):
    cached = {"ticker": "AAPL", "date": "2026-02-01", "amount": 0.25}
    cache.write_cache("ex_dividend", "yfinance_AAPL", cached)
    mock_get = MagicMock()
    monkeypatch.setattr(yfinance_provider, "_get_ticker", mock_get)
    provider = YFinanceProvider()
    event = provider.get_upcoming_ex_dividend("AAPL")
    assert event is not None
    assert event.date == date(2026, 2, 1)
    assert event.amount == 0.25
    mock_get.assert_not_called()


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


def test_get_analyst_data_happy(tmp_cache_root, monkeypatch):
    tk = MagicMock()
    tk.info = {
        "recommendationMean": 1.95,
        "numberOfAnalystOpinions": 40,
        "targetMeanPrice": 308.0,
        "targetMedianPrice": 305.0,
        "targetHighPrice": 350.0,
        "targetLowPrice": 250.0,
    }
    tk.recommendations = pd.DataFrame(
        {
            "period": ["0m", "-1m"],
            "strongBuy": [20, 18],
            "buy": [15, 16],
            "hold": [5, 6],
            "sell": [1, 1],
            "strongSell": [0, 0],
        }
    )
    _mock_ticker(monkeypatch, tk)
    provider = YFinanceProvider()
    data = provider.get_analyst_data("AAPL")
    assert data.recommendation_mean == 1.95
    assert data.n_analysts == 40
    assert data.price_target_mean == 308.0
    assert data.strong_buy_count == 20
    assert data.buy_count == 15
    assert data.hold_count == 5
    assert data.sell_count == 1
    assert data.strong_sell_count == 0


def test_get_analyst_data_empty_raises(tmp_cache_root, monkeypatch):
    tk = MagicMock()
    tk.info = {}
    _mock_ticker(monkeypatch, tk)
    provider = YFinanceProvider()
    with pytest.raises(ProviderError):
        provider.get_analyst_data("AAPL")


def test_get_analyst_data_no_matching_period(tmp_cache_root, monkeypatch):
    tk = MagicMock()
    tk.info = {
        "recommendationMean": 2.5,
        "numberOfAnalystOpinions": 10,
        "targetMeanPrice": 100.0,
    }
    tk.recommendations = pd.DataFrame(
        {
            "period": ["-2m", "-3m"],
            "strongBuy": [5, 4],
            "buy": [3, 2],
            "hold": [2, 2],
            "sell": [0, 0],
            "strongSell": [0, 0],
        }
    )
    _mock_ticker(monkeypatch, tk)
    provider = YFinanceProvider()
    data = provider.get_analyst_data("AAPL")
    assert data.recommendation_mean == 2.5
    assert data.strong_buy_count == 0
    assert data.buy_count == 0
    assert data.hold_count == 0


def test_analyst_data_cache_hit_skips_ticker(tmp_cache_root, monkeypatch):
    cached = {
        "ticker": "AAPL",
        "price_target_mean": 1.0,
        "price_target_median": 2.0,
        "price_target_high": 3.0,
        "price_target_low": 0.5,
        "n_analysts": 10,
        "buy_count": 1,
        "hold_count": 2,
        "sell_count": 3,
        "strong_buy_count": 4,
        "strong_sell_count": 5,
        "recommendation_mean": 2.0,
        "as_of": "2024-01-01",
    }
    cache.write_cache("analyst", "yfinance_AAPL", cached)
    mock_get = MagicMock()
    monkeypatch.setattr(yfinance_provider, "_get_ticker", mock_get)
    provider = YFinanceProvider()
    data = provider.get_analyst_data("AAPL")
    assert data.recommendation_mean == 2.0
    assert data.strong_sell_count == 5
    mock_get.assert_not_called()


def test_get_rating_changes_happy(tmp_cache_root, monkeypatch):
    today = date.today()
    idx = pd.to_datetime(
        [
            today - timedelta(days=3),
            today - timedelta(days=10),
            today - timedelta(days=90),
        ]
    )
    df = pd.DataFrame(
        {
            "Firm": ["Morgan Stanley", "Goldman Sachs", "JPMorgan"],
            "ToGrade": ["Buy", "Hold", "Sell"],
            "FromGrade": ["Hold", "Buy", float("nan")],
            "Action": ["up", "down", "init"],
        },
        index=idx,
    )
    tk = MagicMock()
    tk.upgrades_downgrades = df
    _mock_ticker(monkeypatch, tk)
    provider = YFinanceProvider()
    changes = provider.get_rating_changes("AAPL", lookback_weeks=6)
    assert len(changes) == 2
    assert {c.action for c in changes} == {"upgrade", "downgrade"}
    first = next(c for c in changes if c.firm == "Morgan Stanley")
    assert first.action == "upgrade"
    assert first.to_grade == "Buy"


def test_get_rating_changes_empty_returns_list(tmp_cache_root, monkeypatch):
    tk = MagicMock()
    tk.upgrades_downgrades = pd.DataFrame()
    _mock_ticker(monkeypatch, tk)
    provider = YFinanceProvider()
    assert provider.get_rating_changes("ASML.AS") == []


def test_get_rating_changes_none_returns_list(tmp_cache_root, monkeypatch):
    tk = MagicMock()
    tk.upgrades_downgrades = None
    _mock_ticker(monkeypatch, tk)
    provider = YFinanceProvider()
    assert provider.get_rating_changes("ASML.AS") == []


def test_rating_changes_cache_hit_skips_ticker(tmp_cache_root, monkeypatch):
    cached = {
        "items": [
            {
                "ticker": "AAPL",
                "date": "2024-05-01",
                "action": "upgrade",
                "from_grade": "Hold",
                "to_grade": "Buy",
                "firm": "Morgan Stanley",
            }
        ]
    }
    cache.write_cache("ratings", "yfinance_AAPL_6", cached)
    mock_get = MagicMock()
    monkeypatch.setattr(yfinance_provider, "_get_ticker", mock_get)
    provider = YFinanceProvider()
    changes = provider.get_rating_changes("AAPL", lookback_weeks=6)
    assert len(changes) == 1
    assert changes[0].action == "upgrade"
    assert changes[0].date == date(2024, 5, 1)
    mock_get.assert_not_called()


def test_get_historical_earnings_happy_path(tmp_cache_root, monkeypatch):
    today = date.today()
    idx = pd.to_datetime(
        [
            today - timedelta(days=10),
            today - timedelta(days=100),
            today + timedelta(days=30),
        ]
    )
    df = pd.DataFrame(
        {
            "EPS Estimate": [2.0, 1.9, 2.2],
            "Reported EPS": [2.3, 1.85, float("nan")],
            "Surprise(%)": [15.0, -2.6, float("nan")],
        },
        index=idx,
    )
    tk = MagicMock()
    tk.earnings_dates = df
    _mock_ticker(monkeypatch, tk)
    provider = YFinanceProvider()
    events = provider.get_historical_earnings("AAPL", lookback_days=365)
    assert len(events) == 2
    assert all(e.date <= today for e in events)
    assert events[0].date == today - timedelta(days=10)
    assert events[0].eps_actual == 2.3
    assert events[0].eps_surprise_pct == 15.0
    assert events[1].date == today - timedelta(days=100)


def test_get_historical_earnings_empty(tmp_cache_root, monkeypatch):
    tk = MagicMock()
    tk.earnings_dates = None
    _mock_ticker(monkeypatch, tk)
    provider = YFinanceProvider()
    assert provider.get_historical_earnings("AAPL") == []


def test_get_historical_earnings_filters_by_lookback(tmp_cache_root, monkeypatch):
    today = date.today()
    idx = pd.to_datetime(
        [
            today - timedelta(days=10),
            today - timedelta(days=100),
            today - timedelta(days=400),
        ]
    )
    df = pd.DataFrame(
        {
            "EPS Estimate": [2.0, 1.9, 1.5],
            "Reported EPS": [2.3, 1.85, 1.4],
            "Surprise(%)": [15.0, -2.6, -6.7],
        },
        index=idx,
    )
    tk = MagicMock()
    tk.earnings_dates = df
    _mock_ticker(monkeypatch, tk)
    provider = YFinanceProvider()
    events = provider.get_historical_earnings("AAPL", lookback_days=365)
    assert len(events) == 2
    assert all(e.date >= today - timedelta(days=365) for e in events)


def test_get_historical_earnings_cache_hit(tmp_cache_root, monkeypatch):
    cached = {
        "items": [
            {
                "ticker": "AAPL",
                "date": "2024-02-01",
                "eps_estimate": 2.1,
                "eps_actual": 2.3,
                "eps_surprise_pct": 9.5,
                "revenue_estimate": None,
                "revenue_actual": None,
            }
        ]
    }
    cache.write_cache("earnings_history", "yfinance_AAPL_365", cached)
    mock_get = MagicMock()
    monkeypatch.setattr(yfinance_provider, "_get_ticker", mock_get)
    provider = YFinanceProvider()
    events = provider.get_historical_earnings("AAPL")
    assert len(events) == 1
    assert events[0].date == date(2024, 2, 1)
    assert events[0].eps_surprise_pct == 9.5
    mock_get.assert_not_called()


# --- retry de errores transitorios (_with_retry) ---


def test_with_retry_succeeds_after_one_429(monkeypatch):
    monkeypatch.setattr(yfinance_provider.time, "sleep", lambda _s: None)
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] == 1:
            raise YFRateLimitError()
        return "OK"

    result = yfinance_provider._with_retry(fn, method="test", max_attempts=3, base_delay=2.0)
    assert result == "OK"
    assert calls["n"] == 2


def test_with_retry_propagates_after_exhausting(monkeypatch):
    monkeypatch.setattr(yfinance_provider.time, "sleep", lambda _s: None)

    def fn():
        raise YFRateLimitError()

    with pytest.raises(YFRateLimitError):
        yfinance_provider._with_retry(fn, method="test", max_attempts=3, base_delay=2.0)


def test_with_retry_does_not_retry_keyerror(monkeypatch):
    sleeps = []
    monkeypatch.setattr(yfinance_provider.time, "sleep", lambda s: sleeps.append(s))
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise KeyError("Earnings Date")

    with pytest.raises(KeyError):
        yfinance_provider._with_retry(fn, method="test", max_attempts=3, base_delay=2.0)
    assert calls["n"] == 1  # un solo intento, sin reintento
    assert sleeps == []  # sin delays


def test_with_retry_delay_schedule(monkeypatch):
    sleeps = []
    monkeypatch.setattr(yfinance_provider.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(yfinance_provider.random, "uniform", lambda _a, _b: 1.0)  # sin jitter

    def fn():
        raise YFRateLimitError()

    with pytest.raises(YFRateLimitError):
        yfinance_provider._with_retry(fn, method="test", max_attempts=3, base_delay=2.0)
    assert sleeps == [2.0, 4.0]  # 2s tras intento 1, 4s tras intento 2; intento 3 terminal
