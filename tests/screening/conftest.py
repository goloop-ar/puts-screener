"""Fixtures comunes para los tests de screening."""

import numpy as np
import pandas as pd
import pytest

from puts_screener import universe_builder


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
