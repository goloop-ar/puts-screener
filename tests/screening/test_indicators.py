import numpy as np
import pandas as pd
import pytest

from puts_screener import indicators

_VALID_MACD_LABELS = {
    "subiendo_negativo",
    "subiendo_positivo",
    "bajando_positivo",
    "bajando_negativo",
    "neutral",
}


def _flat_df(value: float, periods: int = 60) -> pd.DataFrame:
    dates = pd.bdate_range(end="2026-05-21", periods=periods)
    close = pd.Series(value, index=dates, dtype=float)
    return pd.DataFrame(
        {"Open": close, "High": close, "Low": close, "Close": close, "Volume": 1_000_000}
    )


def test_sma_weekly(ohlcv_daily_long):
    weekly = ohlcv_daily_long["Close"].resample("W-FRI").last().dropna()
    expected = float(weekly.rolling(50).mean().iloc[-1])
    assert indicators.sma_weekly(ohlcv_daily_long, 50) == pytest.approx(expected)


def test_sma_weekly_insufficient_data(ohlcv_daily_short):
    with pytest.raises(ValueError):
        indicators.sma_weekly(ohlcv_daily_short, 50)


def test_rsi_daily_in_valid_range(ohlcv_daily_long):
    assert 0 <= indicators.rsi_daily(ohlcv_daily_long) <= 100


def test_rsi_daily_series_length(ohlcv_daily_long):
    series = indicators.rsi_daily_series(ohlcv_daily_long)
    assert len(series) == len(ohlcv_daily_long)
    assert not pd.isna(series.iloc[-1])


def test_rsi_weekly_differs_from_daily(ohlcv_daily_long):
    weekly = indicators.rsi_weekly(ohlcv_daily_long)
    assert 0 <= weekly <= 100
    assert weekly != indicators.rsi_daily(ohlcv_daily_long)


def test_rsi_monotonic_increasing_is_100():
    dates = pd.bdate_range(end="2026-05-21", periods=60)
    close = pd.Series(np.arange(100.0, 160.0, 1.0), index=dates)
    df = pd.DataFrame(
        {"Open": close, "High": close, "Low": close, "Close": close, "Volume": 1_000_000}
    )
    assert indicators.rsi_daily(df) == pytest.approx(100.0)


def test_rsi_constant_series_is_neutral_50():
    assert indicators.rsi_daily(_flat_df(100.0)) == pytest.approx(50.0)


def test_macd_state_returns_valid_label(ohlcv_daily_long):
    assert indicators.macd_state(ohlcv_daily_long) in _VALID_MACD_LABELS


def test_macd_state_zero_division_safe():
    assert indicators.macd_state(_flat_df(100.0)) == "neutral"


def test_atr_14_positive(ohlcv_daily_long):
    assert indicators.atr_14(ohlcv_daily_long) > 0


def test_hv_percentile_in_range(ohlcv_daily_long):
    assert 0 <= indicators.hv_percentile_52w(ohlcv_daily_long) <= 100


def test_hv_percentile_factor_100():
    rng = np.random.default_rng(0)
    n = 300
    dates = pd.bdate_range(end="2026-05-21", periods=n)
    returns = np.concatenate([rng.normal(0, 0.004, n - 25), rng.normal(0, 0.05, 25)])
    close = 100 * np.exp(np.cumsum(returns))
    df = pd.DataFrame(
        {
            "Open": close,
            "High": close * 1.001,
            "Low": close * 0.999,
            "Close": close,
            "Volume": 1_000_000,
        },
        index=dates,
    )
    # Volatilidad reciente muy alta → percentil cerca de 100 (no ~0.9 si faltara el ×100).
    assert indicators.hv_percentile_52w(df) >= 90


def test_hv_percentile_insufficient_data(ohlcv_daily_long):
    with pytest.raises(ValueError):
        indicators.hv_percentile_52w(ohlcv_daily_long.iloc[:100])
