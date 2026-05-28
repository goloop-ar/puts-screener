"""Tests de helpers de series para indicadores (spec 09 tanda 0).

Fixtures sintéticas con close determinístico (monotónico creciente). Validan que las
series matchean al scalar equivalente en el último índice, que la longitud y el index
se preservan, y que el comportamiento de "insuficiente data" es consistente con los
scalars.
"""

import numpy as np
import pandas as pd
import pytest

from puts_screener.indicators import (
    ema_daily_series,
    sma_daily,
    sma_daily_series,
    sma_weekly,
    sma_weekly_series,
)


def _ohlcv(n_days: int, base: float = 100.0) -> pd.DataFrame:
    idx = pd.bdate_range("2024-01-02", periods=n_days)
    closes = base + np.arange(n_days, dtype=float)
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes + 0.5,
            "Low": closes - 0.5,
            "Close": closes,
            "Volume": [1_000_000] * n_days,
        },
        index=idx,
    )


def test_sma_daily_series_length_matches_input():
    df = _ohlcv(100)
    s = sma_daily_series(df, length=20)
    assert len(s) == len(df)
    assert s.index.equals(df.index)


def test_sma_daily_series_first_length_minus_1_are_nan():
    df = _ohlcv(100)
    s = sma_daily_series(df, length=20)
    assert s.iloc[:19].isna().all()
    assert s.iloc[19:].notna().all()


def test_sma_daily_series_value_matches_scalar_at_last_index():
    df = _ohlcv(100)
    series_last = sma_daily_series(df, length=50).iloc[-1]
    scalar = sma_daily(df, length=50)
    assert scalar is not None
    assert series_last == pytest.approx(scalar)


def test_ema_daily_series_smooths_close():
    df = _ohlcv(100)
    s = ema_daily_series(df, length=20)
    # close monotónico creciente → ema monotónica no-decreciente.
    diffs = s.diff().dropna()
    assert (diffs >= 0).all()


def test_ema_daily_series_returns_all_nan_when_insufficient_data():
    df = _ohlcv(10)  # menos filas que length=20
    s = ema_daily_series(df, length=20)
    assert len(s) == len(df)
    assert s.isna().all()


def test_sma_weekly_series_uses_friday_closes():
    df = _ohlcv(300)  # ~60 semanas
    s = sma_weekly_series(df, weeks=10)
    # Index semanal anclado a viernes (weekday() == 4).
    assert all(ts.weekday() == 4 for ts in s.index)


def test_sma_weekly_series_value_matches_scalar_at_last_index():
    df = _ohlcv(300)  # ~60 semanas, suficiente para weeks=50
    series_last_valid = sma_weekly_series(df, weeks=50).dropna().iloc[-1]
    scalar = sma_weekly(df, weeks=50)
    assert series_last_valid == pytest.approx(scalar)
