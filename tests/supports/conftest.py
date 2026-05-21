"""Fixtures comunes para los tests de soportes (Paso 2)."""

import numpy as np
import pandas as pd
import pytest

from puts_screener.models_screening import ScreenedCandidate
from puts_screener.providers.models import AnalystData, CompanyProfile, FinancialSnapshot

_WEEKLY_AGG = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}


def _build_candidate(
    ohlcv_daily,
    *,
    ticker="TEST",
    spot=None,
    pasa_filtros_paso_1=True,
    earnings_history=None,
):
    """Arma un ScreenedCandidate mínimo a partir de un OHLCV diario."""
    weekly = ohlcv_daily.resample("W-FRI").agg(_WEEKLY_AGG).dropna()
    profile = CompanyProfile(
        ticker=ticker,
        name="Test Co",
        sector="Technology",
        industry="Software",
        exchange="NMS",
        country="United States",
        market_cap_usd=50e9,
        currency="USD",
        avg_daily_volume_3m=5e6,
    )
    financials = FinancialSnapshot(
        ticker=ticker,
        free_cash_flow_ttm=1e9,
        total_revenue_ttm=1e10,
        fiscal_year_end=None,
        as_of=None,
    )
    analyst = AnalystData(
        ticker=ticker,
        price_target_mean=None,
        price_target_median=None,
        price_target_high=None,
        price_target_low=None,
        n_analysts=10,
    )
    candidate = ScreenedCandidate(
        ticker=ticker,
        profile=profile,
        financials=financials,
        analyst=analyst,
        rating_changes_6w=[],
        upcoming_earnings=None,
        earnings_history=earnings_history or [],
        ohlcv_daily=ohlcv_daily,
        ohlcv_weekly=weekly,
        spot=spot if spot is not None else float(ohlcv_daily["Close"].iloc[-1]),
    )
    candidate.pasa_filtros_paso_1 = pasa_filtros_paso_1
    return candidate


@pytest.fixture
def candidate_factory():
    """Devuelve el constructor de candidatos para que cada test arme el suyo."""
    return _build_candidate


@pytest.fixture
def ascending_ohlcv():
    """OHLCV de 50 días estrictamente ascendente (sin pivots ni gaps → análisis vacío)."""
    n = 50
    idx = pd.bdate_range(end="2026-05-21", periods=n)
    close = np.array([100.0 + i for i in range(n)])
    return pd.DataFrame(
        {
            "Open": close,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": 1_000_000,
        },
        index=idx,
    )
