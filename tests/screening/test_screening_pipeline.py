import sqlite3
from unittest.mock import MagicMock

from puts_screener.providers.base import ProviderError
from puts_screener.providers.models import (
    AnalystData,
    CompanyProfile,
    FinancialSnapshot,
)
from puts_screener.screening_pipeline import run_screening


def _make_profile():
    return CompanyProfile(
        ticker="AAPL",
        name="Apple",
        sector="Tech",
        industry="Consumer Electronics",
        exchange="NMS",
        country="United States",
        market_cap_usd=50e9,
        currency="USD",
        avg_daily_volume_3m=5e6,
    )


def _make_financials():
    return FinancialSnapshot(
        ticker="AAPL",
        free_cash_flow_ttm=1e9,
        total_revenue_ttm=1e10,
        fiscal_year_end=None,
        as_of=None,
    )


def _make_analyst():
    return AnalystData(
        ticker="AAPL",
        price_target_mean=110.0,
        price_target_median=110.0,
        price_target_high=130.0,
        price_target_low=90.0,
        n_analysts=20,
        buy_count=10,
        hold_count=5,
        sell_count=2,
        strong_buy_count=5,
        strong_sell_count=0,
        recommendation_mean=2.0,
        as_of=None,
    )


def _mock_ds(ohlcv):
    ds = MagicMock()
    ds.get_ohlcv.return_value = ohlcv
    ds.get_company_profile.return_value = _make_profile()
    ds.get_financials.return_value = _make_financials()
    ds.get_analyst_data.return_value = _make_analyst()
    ds.get_rating_changes.return_value = []
    ds.get_upcoming_earnings.return_value = None
    ds.get_historical_earnings.return_value = []
    return ds


def test_pipeline_processes_single_ticker(ohlcv_daily_long):
    run_id, candidates = run_screening(
        ["AAPL"], _mock_ds(ohlcv_daily_long), max_workers=1, persist=False
    )
    assert run_id is None
    assert len(candidates) == 1
    c = candidates[0]
    assert c.classification is not None
    assert isinstance(c.pasa_filtros_paso_1, bool)
    assert 0 <= c.momentum_score <= 3


def test_pipeline_skips_tickers_with_no_ohlcv(ohlcv_daily_long):
    ds = _mock_ds(ohlcv_daily_long)
    ds.get_ohlcv.side_effect = ProviderError("no data")
    _run_id, candidates = run_screening(["AAPL"], ds, max_workers=1, persist=False)
    assert candidates == []


def test_pipeline_skips_tickers_with_insufficient_ohlcv(ohlcv_daily_long):
    ds = _mock_ds(ohlcv_daily_long.iloc[:100])
    _run_id, candidates = run_screening(["AAPL"], ds, max_workers=1, persist=False)
    assert candidates == []


def test_pipeline_handles_partial_data(ohlcv_daily_long):
    ds = _mock_ds(ohlcv_daily_long)
    ds.get_rating_changes.side_effect = ProviderError("ratings 403")
    _run_id, candidates = run_screening(["AAPL"], ds, max_workers=1, persist=False)
    assert len(candidates) == 1
    assert any("ratings" in e for e in candidates[0].errors)


def test_pipeline_persists_when_persist_true(ohlcv_daily_long, tmp_path):
    db = tmp_path / "screening.db"
    run_id, _candidates = run_screening(
        ["AAPL"], _mock_ds(ohlcv_daily_long), max_workers=1, persist=True, db_path=db
    )
    assert run_id is not None
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT * FROM runs").fetchall()
    conn.close()
    assert len(rows) == 1


def test_pipeline_no_persist_returns_none_run_id(ohlcv_daily_long):
    run_id, _candidates = run_screening(
        ["AAPL"], _mock_ds(ohlcv_daily_long), max_workers=1, persist=False
    )
    assert run_id is None
