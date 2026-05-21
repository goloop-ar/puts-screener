"""Tests de detección de pivots (spec 03 §4).

Las series OHLCV se generan sintéticamente con numpy para control total. El ATR se pasa
como Series constante cuando su valor exacto no importa para el caso.
"""

import numpy as np
import pandas as pd

from puts_screener.pivots import Pivot, detect_pivots


def _ohlcv(highs: np.ndarray, lows: np.ndarray) -> pd.DataFrame:
    """Arma un OHLCV diario mínimo (Open/Close/Volume son relleno; pivots usa High/Low)."""
    idx = pd.bdate_range("2024-01-01", periods=len(highs))
    mid = (highs + lows) / 2
    return pd.DataFrame(
        {"Open": mid, "High": highs, "Low": lows, "Close": mid, "Volume": 1_000_000},
        index=idx,
    )


def _const_atr(df: pd.DataFrame, value: float) -> pd.Series:
    return pd.Series(value, index=df.index)


def test_detect_clear_low_pivot():
    """V limpia con el mínimo en el medio (índice 12), profundidad >> 1×ATR."""
    n = 25
    lows = np.array([abs(i - 12) + 90.0 for i in range(n)])
    highs = lows + 2.0
    df = _ohlcv(highs, lows)
    atr = _const_atr(df, 2.0)

    pivots = detect_pivots(df, atr)
    low_pivots = [p for p in pivots if p.kind == "low"]

    assert len(low_pivots) == 1
    pivot = low_pivots[0]
    assert pivot.date == df.index[12]
    assert pivot.price == 90.0
    assert pivot.atr_at_pivot == 2.0


def test_detect_clear_high_pivot():
    """Λ limpia con el máximo en el medio (índice 12), profundidad >> 1×ATR."""
    n = 25
    highs = np.array([110.0 - abs(i - 12) for i in range(n)])
    lows = highs - 2.0
    df = _ohlcv(highs, lows)
    atr = _const_atr(df, 2.0)

    pivots = detect_pivots(df, atr)
    high_pivots = [p for p in pivots if p.kind == "high"]

    assert len(high_pivots) == 1
    pivot = high_pivots[0]
    assert pivot.date == df.index[12]
    assert pivot.price == 110.0
    assert pivot.atr_at_pivot == 2.0


def test_monotonic_series_no_pivots():
    """Serie estrictamente ascendente → ningún extremo local estricto → sin pivots."""
    n = 30
    lows = np.array([100.0 + i for i in range(n)])
    highs = lows + 1.0
    df = _ohlcv(highs, lows)
    atr = _const_atr(df, 2.0)

    pivots = detect_pivots(df, atr)

    assert pivots == []


def test_pivot_insufficient_depth_rejected():
    """Mínimo local válido pero a <1×ATR del swing alto previo → rechazado por profundidad."""
    n = 25
    # V muy poco profunda: caída total ~1.7 desde el máximo previo.
    lows = np.array([99.0 + 0.1 * abs(i - 12) for i in range(n)])
    highs = lows + 0.5
    df = _ohlcv(highs, lows)
    atr = _const_atr(df, 10.0)  # umbral de profundidad = 10 >> 1.7

    pivots = detect_pivots(df, atr)
    low_pivots = [p for p in pivots if p.kind == "low"]

    assert low_pivots == []


def test_pivots_in_last_n_bars_ignored():
    """V cuyo mínimo cae en las últimas N barras (índice 22 de 25) → no confirmado."""
    n = 25
    lows = np.array([abs(i - 22) + 90.0 for i in range(n)])
    highs = lows + 2.0
    df = _ohlcv(highs, lows)
    atr = _const_atr(df, 2.0)

    pivots = detect_pivots(df, atr)
    low_pivots = [p for p in pivots if p.kind == "low"]

    assert low_pivots == []


def test_pivots_sorted_by_date():
    """Sinusoide con varios swings → múltiples pivots devueltos en orden de fecha ascendente."""
    n = 60
    base = 100.0 + 15.0 * np.sin(2 * np.pi * np.arange(n) / 20.0)
    highs = base + 0.5
    lows = base - 0.5
    df = _ohlcv(highs, lows)
    atr = _const_atr(df, 2.0)

    pivots = detect_pivots(df, atr)

    assert len(pivots) >= 2
    assert all(isinstance(p, Pivot) for p in pivots)
    dates = [p.date for p in pivots]
    assert dates == sorted(dates)
