"""Fixtures comunes para la suite de tests de puts_screener."""

import pandas as pd
import pytest


@pytest.fixture
def tmp_cache_root(tmp_path, monkeypatch):
    """Apunta cache.CACHE_ROOT a una carpeta temporal y la devuelve."""
    from puts_screener.providers import cache

    root = tmp_path / "cache"
    monkeypatch.setattr(cache, "CACHE_ROOT", root)
    return root


@pytest.fixture
def sample_ohlcv_df():
    """DataFrame OHLCV de 30 días hábiles continuos con valores plausibles."""
    idx = pd.bdate_range("2024-01-02", periods=30)
    n = len(idx)
    return pd.DataFrame(
        {
            "Open": [100.0 + i for i in range(n)],
            "High": [101.0 + i for i in range(n)],
            "Low": [99.0 + i for i in range(n)],
            "Close": [100.5 + i for i in range(n)],
            "Volume": [1_000_000 + i * 1_000 for i in range(n)],
        },
        index=idx,
    )


@pytest.fixture
def disable_cache(monkeypatch):
    """Activa CACHE_DISABLED=1 en el entorno para el test."""
    monkeypatch.setenv("CACHE_DISABLED", "1")
