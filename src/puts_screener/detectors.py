"""Detectores de patrones técnicos de reversión / bottom (spec 10)."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from puts_screener.config_detectors import (
    CAPIT_CLOSE_POS_MIN,
    CAPIT_LOOKBACK_DAYS,
    CAPIT_PREDROP_LOOKBACK,
    CAPIT_PREDROP_PCT,
    CAPIT_RANGE_ATR_MULTIPLIER,
    CAPIT_RECLAIM_WINDOW_DAYS,
    CAPIT_VOLUME_AVG_MULTIPLIER,
    DBL_BOTTOM_LOOKBACK_DAYS,
    DBL_BOTTOM_LOW_TOLERANCE,
    DBL_BOTTOM_MAX_GAP_BARS,
    DBL_BOTTOM_MIN_BOUNCE_PCT,
    DBL_BOTTOM_MIN_GAP_BARS,
    HMA_FLIP_LOOKBACK_WEEKS,
    HMA_MIN_SLOPE_PCT,
    HMA_WEEKLY_PERIOD,
)
from puts_screener.pivots import Pivot


@dataclass(frozen=True)
class DoubleBottomResult:
    """Doble piso detectado. `confirmed=True` si close actual > neckline."""

    confirmed: bool
    low1_date: pd.Timestamp
    low1_price: float
    low2_date: pd.Timestamp
    low2_price: float
    neckline_date: pd.Timestamp
    neckline_price: float
    bounce_pct: float  # (neckline - min(L1,L2)) / min(L1,L2)


@dataclass(frozen=True)
class CapitulationResult:
    """Vela climática con reclaim posterior confirmado."""

    climax_date: pd.Timestamp
    climax_low: float
    climax_close: float
    reclaim_date: pd.Timestamp
    reclaim_close: float
    range_atr_ratio: float
    volume_avg_ratio: float


@dataclass(frozen=True)
class HmaFlipResult:
    """Flip reciente del HMA semanal de pendiente negativa a positiva."""

    flip_date: pd.Timestamp  # fecha de la vela semanal donde ocurrió el flip
    weeks_since_flip: int  # 0 si flipeó esta misma semana
    hma_value: float  # valor del HMA en la última vela
    slope: float  # pendiente actual (frac, no %)
    close_above: bool  # close_weekly[-1] > hma[-1]


# --- Double bottom ---


def detect_double_bottom(
    ohlcv: pd.DataFrame,
    pivots: list[Pivot],
    *,
    today: pd.Timestamp | None = None,
) -> DoubleBottomResult | None:
    """Detecta el doble piso más reciente en los últimos DBL_BOTTOM_LOOKBACK_DAYS.

    Busca pares (L1, L2) de pivots bajos que cumplan: gap de barras en
    [MIN_GAP, MAX_GAP], tolerancia de precios, y rebote intermedio ≥ MIN_BOUNCE_PCT.
    La neckline es el pivot alto más alto entre L1 y L2 (o sintético desde el high
    máximo si no hay pivots altos en el medio). Devuelve el par con L2 más reciente.
    `confirmed` indica si el close actual rompió la neckline al alza.
    """
    if ohlcv.empty or not pivots:
        return None

    today_ts = _resolve_today(ohlcv, today)
    if today_ts is None:
        return None

    index = ohlcv.index
    today_bar = _bar_index(index, today_ts)
    if today_bar is None:
        return None
    cutoff_bar = max(0, today_bar - DBL_BOTTOM_LOOKBACK_DAYS)

    # Bar-based lookback evita inconsistencias entre días hábiles y calendario.
    lows = []
    for p in pivots:
        if p.kind != "low" or p.date > today_ts:
            continue
        b = _bar_index(index, p.date)
        if b is None or b < cutoff_bar:
            continue
        lows.append(p)
    if len(lows) < 2:
        return None

    highs_pivots = [p for p in pivots if p.kind == "high" and p.date <= today_ts]
    high_series = ohlcv["High"]

    best: tuple[pd.Timestamp, DoubleBottomResult] | None = None

    for i, low1 in enumerate(lows):
        bar1 = _bar_index(index, low1.date)
        if bar1 is None:
            continue
        for low2 in lows[i + 1 :]:
            bar2 = _bar_index(index, low2.date)
            if bar2 is None:
                continue
            gap = bar2 - bar1
            if gap < DBL_BOTTOM_MIN_GAP_BARS or gap > DBL_BOTTOM_MAX_GAP_BARS:
                continue
            if abs(low2.price - low1.price) / low1.price >= DBL_BOTTOM_LOW_TOLERANCE:
                continue

            # Neckline: pivot alto entre L1 y L2 con mayor price, o sintético.
            highs_between = [p for p in highs_pivots if low1.date < p.date < low2.date]
            if highs_between:
                neckline_pivot = max(highs_between, key=lambda p: p.price)
                neckline_date = neckline_pivot.date
                neckline_price = neckline_pivot.price
            else:
                segment = high_series.iloc[bar1 : bar2 + 1]
                if segment.empty:
                    continue
                neckline_price = float(segment.max())
                neckline_date = segment.idxmax()

            min_low = min(low1.price, low2.price)
            if min_low <= 0:
                continue
            bounce_pct = (neckline_price - min_low) / min_low
            if bounce_pct < DBL_BOTTOM_MIN_BOUNCE_PCT:
                continue

            close_today = _close_at(ohlcv, today_ts)
            if close_today is None:
                continue
            confirmed = close_today > neckline_price

            result = DoubleBottomResult(
                confirmed=confirmed,
                low1_date=low1.date,
                low1_price=low1.price,
                low2_date=low2.date,
                low2_price=low2.price,
                neckline_date=neckline_date,
                neckline_price=neckline_price,
                bounce_pct=bounce_pct,
            )
            if best is None or low2.date > best[0]:
                best = (low2.date, result)

    return best[1] if best is not None else None


# --- Capitulation + reclaim ---


def detect_capitulation_reclaim(
    ohlcv: pd.DataFrame,
    atr: pd.Series,
    *,
    today: pd.Timestamp | None = None,
) -> CapitulationResult | None:
    """Detecta la vela climática + reclaim más reciente en los últimos CAPIT_LOOKBACK_DAYS.

    Una vela climática combina: rango > 2.5×ATR14, volumen > 2.5×avg20d, cierre en
    el tercio superior del rango, y caída previa ≥ 8% en los 10 días anteriores.
    El reclaim exige close[t'] > close[climax] dentro de la ventana de reclaim sin
    romper el low climático en el camino. Devuelve la combinación más reciente.
    """
    if ohlcv.empty:
        return None
    if atr.empty:
        return None

    today_ts = _resolve_today(ohlcv, today)
    if today_ts is None:
        return None

    index = ohlcv.index
    today_bar = _bar_index(index, today_ts)
    if today_bar is None:
        return None

    lookback_cutoff_bar = max(0, today_bar - CAPIT_LOOKBACK_DAYS)
    last_climax_bar = today_bar - CAPIT_RECLAIM_WINDOW_DAYS
    if last_climax_bar < lookback_cutoff_bar:
        return None

    high = ohlcv["High"].to_numpy(dtype=float)
    low = ohlcv["Low"].to_numpy(dtype=float)
    close = ohlcv["Close"].to_numpy(dtype=float)
    volume = ohlcv["Volume"].to_numpy(dtype=float)

    best: CapitulationResult | None = None
    best_reclaim_bar = -1

    # Iteramos del más reciente al más viejo para favorecer la capitulation más nueva.
    for t in range(last_climax_bar, lookback_cutoff_bar - 1, -1):
        if t - CAPIT_PREDROP_LOOKBACK - 1 < 0:
            continue
        range_t = high[t] - low[t]
        if range_t <= 0:
            continue
        atr_t = _atr_at_bar(atr, index[t])
        if atr_t is None or atr_t <= 0:
            continue
        if t - 20 < 0:
            continue
        vol_avg_20 = float(np.mean(volume[t - 20 : t]))
        if vol_avg_20 <= 0 or np.isnan(vol_avg_20):
            continue
        close_pos = (close[t] - low[t]) / range_t
        predrop_close = close[t - 1]
        lookback_close = close[t - 1 - CAPIT_PREDROP_LOOKBACK]
        if lookback_close <= 0:
            continue
        predrop = predrop_close / lookback_close - 1.0

        if range_t <= CAPIT_RANGE_ATR_MULTIPLIER * atr_t:
            continue
        if volume[t] <= CAPIT_VOLUME_AVG_MULTIPLIER * vol_avg_20:
            continue
        if close_pos <= CAPIT_CLOSE_POS_MIN:
            continue
        if predrop >= CAPIT_PREDROP_PCT:
            continue

        # Buscar reclaim en [t+1, t+CAPIT_RECLAIM_WINDOW_DAYS] sin romper low[t].
        climax_low = low[t]
        climax_close = close[t]
        reclaim_bar = -1
        for tp in range(t + 1, min(t + 1 + CAPIT_RECLAIM_WINDOW_DAYS, today_bar + 1)):
            if low[tp] <= climax_low:
                # rompió el low climático en el camino
                break
            if close[tp] > climax_close:
                reclaim_bar = tp
                break
        if reclaim_bar < 0:
            continue

        result = CapitulationResult(
            climax_date=index[t],
            climax_low=float(climax_low),
            climax_close=float(climax_close),
            reclaim_date=index[reclaim_bar],
            reclaim_close=float(close[reclaim_bar]),
            range_atr_ratio=float(range_t / atr_t),
            volume_avg_ratio=float(volume[t] / vol_avg_20),
        )
        # Más reciente = mayor reclaim_bar. Como iteramos t descendente y buscamos
        # el primer reclaim de cada t, comparamos por reclaim_bar.
        if reclaim_bar > best_reclaim_bar:
            best = result
            best_reclaim_bar = reclaim_bar

    return best


# --- HMA weekly flip ---


def detect_hma_weekly_flip(
    ohlcv: pd.DataFrame,
    *,
    today: pd.Timestamp | None = None,
) -> HmaFlipResult | None:
    """Detecta flip reciente del HMA(50) semanal de pendiente negativa a positiva.

    Resamplea OHLCV a W-FRI, calcula HMA(50), busca el último flip donde slope[t-1]<0,
    slope[t]>0 y slope[t]>HMA_MIN_SLOPE_PCT. Devuelve None si el flip está fuera de
    las últimas HMA_FLIP_LOOKBACK_WEEKS velas semanales o si no hay flip.
    """
    if ohlcv.empty:
        return None

    today_ts = _resolve_today(ohlcv, today)
    if today_ts is None:
        return None

    df = ohlcv.loc[:today_ts]
    if df.empty:
        return None

    weekly_close = df["Close"].resample("W-FRI").last().dropna()
    if len(weekly_close) < HMA_WEEKLY_PERIOD * 2:
        return None

    hma = _hma(weekly_close, HMA_WEEKLY_PERIOD).dropna()
    if len(hma) < 3:
        return None

    hma_prev = hma.shift(1)
    slope = (hma - hma_prev) / hma_prev
    slope = slope.dropna()
    if len(slope) < 2:
        return None

    flip_bar = -1
    slope_values = slope.to_numpy()
    # Buscar el flip más reciente: slope[t-1]<0 y slope[t]>0 y slope[t]>min_slope.
    for i in range(len(slope_values) - 1, 0, -1):
        if slope_values[i - 1] < 0 and slope_values[i] > 0 and slope_values[i] > HMA_MIN_SLOPE_PCT:
            flip_bar = i
            break
    if flip_bar < 0:
        return None

    weeks_since_flip = (len(slope_values) - 1) - flip_bar
    if weeks_since_flip >= HMA_FLIP_LOOKBACK_WEEKS:
        return None

    flip_date = slope.index[flip_bar]
    hma_value = float(hma.iloc[-1])
    last_slope = float(slope_values[-1])
    last_close = float(weekly_close.iloc[-1])
    close_above = last_close > hma_value

    return HmaFlipResult(
        flip_date=flip_date,
        weeks_since_flip=int(weeks_since_flip),
        hma_value=hma_value,
        slope=last_slope,
        close_above=close_above,
    )


# --- helpers internos ---


def _resolve_today(ohlcv: pd.DataFrame, today: pd.Timestamp | None) -> pd.Timestamp | None:
    """Devuelve el timestamp efectivo de hoy: el provisto o la última barra del df."""
    if today is None:
        if ohlcv.empty:
            return None
        return ohlcv.index[-1]
    # Si today no coincide con un índice, buscamos la última fila <= today.
    if today in ohlcv.index:
        return today
    valid = ohlcv.index[ohlcv.index <= today]
    if len(valid) == 0:
        return None
    return valid[-1]


def _bar_index(index: pd.Index, date: pd.Timestamp) -> int | None:
    """Posición entera de `date` en `index` (None si no existe)."""
    try:
        loc = index.get_loc(date)
    except KeyError:
        return None
    if isinstance(loc, (slice, np.ndarray)):
        return None
    return int(loc)


def _close_at(ohlcv: pd.DataFrame, date: pd.Timestamp) -> float | None:
    """Close de `date` (None si no existe)."""
    if date not in ohlcv.index:
        return None
    return float(ohlcv.loc[date, "Close"])


def _atr_at_bar(atr: pd.Series, date: pd.Timestamp) -> float | None:
    """ATR en `date`. None si la fecha no está o el valor es NaN."""
    if date not in atr.index:
        return None
    value = atr.loc[date]
    if pd.isna(value):
        return None
    return float(value)


def _wma(series: pd.Series, period: int) -> pd.Series:
    """Weighted moving average con pesos lineales 1..period."""
    weights = np.arange(1, period + 1, dtype=float)
    weights /= weights.sum()
    return series.rolling(window=period).apply(lambda x: float(np.dot(x, weights)), raw=True)


def _hma(series: pd.Series, period: int) -> pd.Series:
    """Hull Moving Average. HMA(n) = WMA(2*WMA(n/2) - WMA(n), sqrt(n))."""
    half = max(2, period // 2)
    sqrt_n = max(2, int(round(math.sqrt(period))))
    wma_half = _wma(series, half)
    wma_full = _wma(series, period)
    raw = 2 * wma_half - wma_full
    return _wma(raw, sqrt_n)
