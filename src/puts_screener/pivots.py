"""Detección de pivots (mínimos/máximos locales significativos) sobre OHLCV diario.

Un pivot bajo/alto requiere `PIVOT_WINDOW_BARS` barras a cada lado siendo extremo estricto,
y una profundidad mínima respecto al swing opuesto previo (filtro ATR). Las últimas N barras
se ignoran por no estar confirmadas (§4.2 de la spec 03).
"""

from dataclasses import dataclass
from typing import Literal

import pandas as pd

from puts_screener.config_supports import PIVOT_MIN_DEPTH_ATR, PIVOT_WINDOW_BARS


@dataclass(frozen=True)
class Pivot:
    """Pivot confirmado: extremo local que superó el filtro de profundidad."""

    date: pd.Timestamp
    price: float
    kind: Literal["low", "high"]
    atr_at_pivot: float  # ATR14 al momento del pivot — útil para clustering posterior


def _atr_at(atr14_series: pd.Series, date: pd.Timestamp) -> float:
    """ATR14 en `date`. Lookup exacto; si la fecha no existe, cae a `.asof()` (último ≤)."""
    try:
        return float(atr14_series.loc[date])
    except KeyError:
        return float(atr14_series.asof(date))


def _last_pivot_price(pivots: list[Pivot], kind: str) -> float | None:
    """Precio del último pivot confirmado del `kind` pedido, o None si no hay."""
    for pivot in reversed(pivots):
        if pivot.kind == kind:
            return pivot.price
    return None


def detect_pivots(ohlcv_daily: pd.DataFrame, atr14_series: pd.Series) -> list[Pivot]:
    """Devuelve todos los pivots confirmados del histórico, ordenados por fecha ascendente.

    Un pivot bajo en la barra `i` exige `low[i]` estrictamente menor a las N barras a cada
    lado y `(swing_high_prev - low[i]) >= PIVOT_MIN_DEPTH_ATR × ATR14[i]`. El pivot alto es
    simétrico. `swing_*_prev` es el último pivot opuesto confirmado antes de `i`; si no hay,
    se aproxima con el extremo de las últimas `N*4` barras (§4.1). Las últimas N barras se
    omiten por no estar confirmadas (§4.2).
    """
    n = PIVOT_WINDOW_BARS
    highs = ohlcv_daily["High"].to_numpy(dtype=float)
    lows = ohlcv_daily["Low"].to_numpy(dtype=float)
    index = ohlcv_daily.index
    total = len(index)

    pivots: list[Pivot] = []
    if total <= 2 * n:
        return pivots

    for i in range(n, total - n):
        window_lows = lows[i - n : i + n + 1]
        window_highs = highs[i - n : i + n + 1]
        is_low = (window_lows < lows[i]).sum() == 0 and (window_lows == lows[i]).sum() == 1
        is_high = (window_highs > highs[i]).sum() == 0 and (window_highs == highs[i]).sum() == 1

        if not (is_low or is_high):
            continue

        atr_i = _atr_at(atr14_series, index[i])

        if is_low:
            swing_high_prev = _last_pivot_price(pivots, "high")
            if swing_high_prev is None:
                swing_high_prev = float(highs[max(0, i - n * 4) : i].max())
            if swing_high_prev - lows[i] >= PIVOT_MIN_DEPTH_ATR * atr_i:
                pivots.append(
                    Pivot(date=index[i], price=float(lows[i]), kind="low", atr_at_pivot=atr_i)
                )
        else:  # is_high
            swing_low_prev = _last_pivot_price(pivots, "low")
            if swing_low_prev is None:
                swing_low_prev = float(lows[max(0, i - n * 4) : i].min())
            if highs[i] - swing_low_prev >= PIVOT_MIN_DEPTH_ATR * atr_i:
                pivots.append(
                    Pivot(date=index[i], price=float(highs[i]), kind="high", atr_at_pivot=atr_i)
                )

    return pivots
