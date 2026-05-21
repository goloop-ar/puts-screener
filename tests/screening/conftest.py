"""Fixtures comunes para los tests de screening."""

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from puts_screener import universe_builder
from puts_screener.models_screening import ScreenedCandidate
from puts_screener.providers.models import (
    AnalystData,
    CompanyProfile,
    FinancialSnapshot,
)


@pytest.fixture
def ohlcv_daily_long():
    """OHLCV diario de 1500 días hábiles, random-walk realista, semilla fija.

    Suficiente para todos los indicadores (SMA200W, HV Percentile 52w, etc.).
    """
    rng = np.random.default_rng(42)
    n = 1500
    dates = pd.bdate_range(end="2026-05-21", periods=n)
    returns = rng.normal(0.0005, 0.015, n)
    close = 100 * np.exp(np.cumsum(returns))
    high = close * (1 + np.abs(rng.normal(0, 0.005, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.005, n)))
    open_ = close * (1 + rng.normal(0, 0.003, n))
    volume = rng.integers(1_000_000, 10_000_000, n)
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=dates,
    )


@pytest.fixture
def ohlcv_daily_short():
    """OHLCV de 30 días hábiles — para tests sin necesidad de mucho histórico."""
    rng = np.random.default_rng(7)
    n = 30
    dates = pd.bdate_range(end="2026-05-21", periods=n)
    close = 100 + np.cumsum(rng.normal(0, 0.5, n))
    return pd.DataFrame(
        {
            "Open": close,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": rng.integers(1_000_000, 5_000_000, n),
        },
        index=dates,
    )


@pytest.fixture
def tmp_universe_cache(tmp_path, monkeypatch):
    """Apunta el cache del universe builder a una carpeta temporal."""
    cache_dir = tmp_path / "universe"
    monkeypatch.setattr(universe_builder, "_CACHE_DIR", cache_dir)
    return cache_dir


@pytest.fixture
def neutral_candidate(ohlcv_daily_long):
    """Candidato base con valores neutrales. Cada test lo modifica al gusto.

    Armado para NO matchear ningún tipo y pasar quality/valoración/HV por default
    (momentum NO pasa por default: RSI=60, MACD neutral).
    """
    profile = CompanyProfile(
        ticker="TEST",
        name="Test Co",
        sector="Tech",
        industry="Software",
        exchange="NMS",
        country="United States",
        market_cap_usd=50e9,
        currency="USD",
        avg_daily_volume_3m=5e6,
    )
    financials = FinancialSnapshot(
        ticker="TEST",
        free_cash_flow_ttm=1e9,
        total_revenue_ttm=10e9,
        fiscal_year_end=None,
        as_of=None,
    )
    analyst = AnalystData(
        ticker="TEST",
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
    return ScreenedCandidate(
        ticker="TEST",
        profile=profile,
        financials=financials,
        analyst=analyst,
        rating_changes_6w=[],
        upcoming_earnings=None,
        earnings_history=[],
        ohlcv_daily=ohlcv_daily_long,
        ohlcv_weekly=ohlcv_daily_long,
        spot=100.0,
        sma_50w=100.0,
        sma_200w=100.0,
        rsi_d=60.0,
        rsi_d_3d_ago=60.0,
        rsi_w=60.0,
        rsi_w_2w_ago=60.0,
        macd_state="neutral",
        macd_hist_3d_ago=0.0,
        atr_14=1.5,
        hv_percentile_52w=50.0,
        price_target_upside_pct=0.10,
        recommendation_buy_ratio=0.75,
        downgrades_6w_count=0,
        fetched_at=datetime.now(),
    )
