"""Los 7 elementos del score de soportes (Paso 2 del SOP, §5 de la spec 03).

Cada función recibe data ya disponible (OHLCV, pivots precalculados, series de osciladores)
y devuelve `list[SupportLevel]` (vacía si el elemento no aplica). Ninguna levanta excepción
por histórico corto: ante data insuficiente devuelven `[]` para que el pipeline procese
candidatos con poco histórico sin romperse.

Decisiones de implementación (no explícitas en la spec):
- Las ventanas "de los últimos N días" son N días HÁBILES (ruedas), derivadas del índice del
  OHLCV vía `_date_cutoff` (no `pd.Timedelta` calendario). Unifica el criterio con HVN/gap,
  que ya usaban `.iloc[-N:]`. "Hoy" es siempre `ohlcv_daily.index[-1]`.
- Las fechas en `metadata` se guardan como ISO strings para que la capa de persistencia
  (Tanda 3) pueda serializarlas a JSON sin conversión adicional.
"""

import numpy as np
import pandas as pd

from puts_screener.config_supports import (
    AVWAP_52W_HIGH_LOOKBACK_DAYS,
    AVWAP_EARNINGS_LOOKBACK_DAYS,
    DIVERGENCE_LOOKBACK_DAYS,
    FIB_LEVELS,
    GAP_LOOKBACK_DAYS,
    HVN_LOOKBACK_DAYS,
    HVN_NUM_BUCKETS,
    HVN_PERCENTILE_THRESHOLD,
    LAST_PIVOT_HIGH_LOOKBACK_DAYS,
    LAST_SWING_LOOKBACK_DAYS,
    SCORE_OTHER_ELEMENT_POINTS,
    SCORE_SMA200_POINTS,
)
from puts_screener.models_support import SupportLevel
from puts_screener.pivots import Pivot

_SMA_WEEKS = 200
_EMA_DAYS = 200


def _date_cutoff(ohlcv_daily: pd.DataFrame, business_days: int) -> pd.Timestamp:
    """Fecha de corte = índice[-business_days] del OHLCV (N ruedas hábiles atrás).

    Si el histórico tiene menos de `business_days` filas, devuelve el primer índice disponible.
    """
    if len(ohlcv_daily) >= business_days:
        return ohlcv_daily.index[-business_days]
    return ohlcv_daily.index[0]


def _last_low_pivot_in_window(pivots: list[Pivot], ohlcv_daily: pd.DataFrame) -> Pivot | None:
    """Último pivot bajo (más reciente) dentro de la ventana de swing. None si no hay."""
    cutoff = _date_cutoff(ohlcv_daily, LAST_SWING_LOOKBACK_DAYS)
    lows = [p for p in pivots if p.kind == "low" and p.date >= cutoff]
    if not lows:
        return None
    return max(lows, key=lambda p: p.date)


def sma_200_levels(ohlcv_daily: pd.DataFrame, ohlcv_weekly: pd.DataFrame) -> list[SupportLevel]:
    """SMA200 semanal y EMA200 diaria como niveles de soporte (2 pts cada uno).

    El SOP asigna 2 puntos si UNO de los dos coincide con la zona; el dedup por categoría
    del clustering (§6.3) evita duplicar puntos si ambos caen en la misma zona.
    """
    levels: list[SupportLevel] = []

    weekly_close = ohlcv_weekly["Close"]
    if len(weekly_close) >= _SMA_WEEKS:
        sma_200w = float(weekly_close.rolling(_SMA_WEEKS).mean().iloc[-1])
        levels.append(SupportLevel(price=sma_200w, element="sma_200w", points=SCORE_SMA200_POINTS))

    daily_close = ohlcv_daily["Close"]
    if len(daily_close) >= _EMA_DAYS:
        ema_200d = float(daily_close.ewm(span=_EMA_DAYS, adjust=False).mean().iloc[-1])
        levels.append(SupportLevel(price=ema_200d, element="sma_200d", points=SCORE_SMA200_POINTS))

    return levels


def polarity_levels(
    ohlcv_daily: pd.DataFrame, pivots: list[Pivot], close_today: float
) -> list[SupportLevel]:
    """Resistencias rotas: pivots altos recientes que el precio ya superó (1 pt c/u)."""
    cutoff = _date_cutoff(ohlcv_daily, LAST_PIVOT_HIGH_LOOKBACK_DAYS)
    levels: list[SupportLevel] = []
    for pivot in pivots:
        if pivot.kind == "high" and pivot.date >= cutoff and pivot.price < close_today:
            levels.append(
                SupportLevel(
                    price=pivot.price,
                    element="polarity",
                    points=SCORE_OTHER_ELEMENT_POINTS,
                    metadata={"pivot_date": pivot.date.isoformat()},
                )
            )
    return levels


def fib_levels(
    ohlcv_daily: pd.DataFrame, pivots: list[Pivot], close_today: float
) -> list[SupportLevel]:
    """Retrocesos 61.8% y 78.6% del último impulso alcista significativo (§5.3).

    Devuelve [] si no hay pivot bajo en la ventana o si el "impulso" no fue alcista.
    Si no hay pivot alto posterior al último bajo (subida en curso), usa `close_today`.
    """
    pivot_low_last = _last_low_pivot_in_window(pivots, ohlcv_daily)
    if pivot_low_last is None:
        return []

    cutoff = _date_cutoff(ohlcv_daily, LAST_SWING_LOOKBACK_DAYS)
    highs_after = [
        p for p in pivots if p.kind == "high" and p.date >= cutoff and p.date > pivot_low_last.date
    ]
    if highs_after:
        pivot_high_last = max(highs_after, key=lambda p: p.date)
        high_price = pivot_high_last.price
        high_date = pivot_high_last.date.isoformat()
    else:  # subida en curso: proyectar fibs sobre lo subido hasta hoy
        high_price = close_today
        high_date = ohlcv_daily.index[-1].isoformat()

    low_price = pivot_low_last.price
    if high_price <= low_price:
        return []

    swing_range = high_price - low_price
    metadata = {
        "low_date": pivot_low_last.date.isoformat(),
        "high_date": high_date,
        "low_price": low_price,
        "high_price": high_price,
    }
    fib_618 = high_price - FIB_LEVELS[0] * swing_range
    fib_786 = high_price - FIB_LEVELS[1] * swing_range
    return [
        SupportLevel(
            price=fib_618, element="fib_618", points=SCORE_OTHER_ELEMENT_POINTS, metadata=metadata
        ),
        SupportLevel(
            price=fib_786, element="fib_786", points=SCORE_OTHER_ELEMENT_POINTS, metadata=metadata
        ),
    ]


def _avwap_from(ohlcv: pd.DataFrame, anchor_date: pd.Timestamp) -> float | None:
    """AVWAP desde `anchor_date` hasta el final del histórico. None si no hay data/volumen."""
    sub = ohlcv.loc[anchor_date:]
    if sub.empty:
        return None
    typical = (sub["High"] + sub["Low"] + sub["Close"]) / 3
    volume = sub["Volume"]
    total_volume = float(volume.sum())
    if total_volume <= 0:
        return None
    return float((typical * volume).sum() / total_volume)


def avwap_levels(
    ohlcv_daily: pd.DataFrame,
    pivots: list[Pivot],
    last_earnings_date: pd.Timestamp | None,
) -> list[SupportLevel]:
    """Hasta 3 AVWAPs: desde último pivot bajo, último earnings y máximo de 52w (1 pt c/u).

    Cada ancla inválida (None, fuera de ventana o sin data) se omite; las otras siguen
    siendo válidas.
    """
    levels: list[SupportLevel] = []

    pivot_low_last = _last_low_pivot_in_window(pivots, ohlcv_daily)
    if pivot_low_last is not None:
        value = _avwap_from(ohlcv_daily, pivot_low_last.date)
        if value is not None:
            levels.append(
                SupportLevel(
                    price=value,
                    element="avwap_pivot_low",
                    points=SCORE_OTHER_ELEMENT_POINTS,
                    metadata={"anchor_date": pivot_low_last.date.isoformat()},
                )
            )

    if last_earnings_date is not None:
        earnings_ts = pd.Timestamp(last_earnings_date)
        if earnings_ts >= _date_cutoff(ohlcv_daily, AVWAP_EARNINGS_LOOKBACK_DAYS):
            value = _avwap_from(ohlcv_daily, earnings_ts)
            if value is not None:
                levels.append(
                    SupportLevel(
                        price=value,
                        element="avwap_earnings",
                        points=SCORE_OTHER_ELEMENT_POINTS,
                        metadata={"anchor_date": earnings_ts.isoformat()},
                    )
                )

    if len(ohlcv_daily) >= AVWAP_52W_HIGH_LOOKBACK_DAYS:
        window = ohlcv_daily.iloc[-AVWAP_52W_HIGH_LOOKBACK_DAYS:]
        anchor_date = window["High"].idxmax()
        value = _avwap_from(ohlcv_daily, anchor_date)
        if value is not None:
            levels.append(
                SupportLevel(
                    price=value,
                    element="avwap_52w_high",
                    points=SCORE_OTHER_ELEMENT_POINTS,
                    metadata={"anchor_date": pd.Timestamp(anchor_date).isoformat()},
                )
            )

    return levels


def _bucket_index(price: float, price_min: float, delta: float, num_buckets: int) -> int:
    """Índice del bucket que contiene `price`, clamp a [0, num_buckets-1]."""
    if delta <= 0:
        return 0
    return max(0, min(int((price - price_min) / delta), num_buckets - 1))


def hvn_levels(ohlcv_daily: pd.DataFrame) -> list[SupportLevel]:
    """High Volume Nodes aproximados (§5.5): histograma de volumen por bucket de precio.

    El volumen diario se reparte proporcionalmente entre los buckets que toca el rango
    High-Low (o 100% al bucket del close si el día no tiene rango). Buckets contiguos por
    encima del percentil 80 se mergean en un único nivel.
    """
    if len(ohlcv_daily) < HVN_LOOKBACK_DAYS:
        return []

    sub = ohlcv_daily.iloc[-HVN_LOOKBACK_DAYS:]
    highs = sub["High"].to_numpy(dtype=float)
    lows = sub["Low"].to_numpy(dtype=float)
    closes = sub["Close"].to_numpy(dtype=float)
    volumes = sub["Volume"].to_numpy(dtype=float)

    price_min = float(lows.min())
    price_max = float(highs.max())
    if price_max <= price_min:
        return []
    delta = (price_max - price_min) / HVN_NUM_BUCKETS

    volume_by_bucket = np.zeros(HVN_NUM_BUCKETS)
    for hi, lo, close, vol in zip(highs, lows, closes, volumes, strict=True):
        if hi <= lo:  # día sin rango → 100% al bucket del close
            volume_by_bucket[_bucket_index(close, price_min, delta, HVN_NUM_BUCKETS)] += vol
            continue
        span = hi - lo
        for k in range(HVN_NUM_BUCKETS):
            bucket_lo = price_min + k * delta
            overlap = min(hi, bucket_lo + delta) - max(lo, bucket_lo)
            if overlap > 0:
                volume_by_bucket[k] += (overlap / span) * vol

    cutoff = np.percentile(volume_by_bucket, HVN_PERCENTILE_THRESHOLD)
    is_hvn = volume_by_bucket >= cutoff

    levels: list[SupportLevel] = []
    k = 0
    while k < HVN_NUM_BUCKETS:
        if not is_hvn[k]:
            k += 1
            continue
        start = k
        while k < HVN_NUM_BUCKETS and is_hvn[k]:
            k += 1
        range_lo = price_min + start * delta
        range_hi = price_min + k * delta  # k es el primer bucket NO-hvn (exclusivo)
        mid = (range_lo + range_hi) / 2
        levels.append(
            SupportLevel(
                price=float(mid),
                element="hvn",
                points=SCORE_OTHER_ELEMENT_POINTS,
                metadata={
                    "bucket_start": start,
                    "bucket_end": k - 1,
                    "bucket_lower_price": float(range_lo),
                    "bucket_upper_price": float(range_hi),
                    "bucket_width": float(delta),
                },
            )
        )
    return levels


def gap_levels(ohlcv_daily: pd.DataFrame) -> list[SupportLevel]:
    """Gaps alcistas no cerrados en los últimos GAP_LOOKBACK_DAYS (§5.6, 1 pt c/u)."""
    sub = ohlcv_daily.iloc[-GAP_LOOKBACK_DAYS:]
    if len(sub) < 2:
        return []

    highs = sub["High"].to_numpy(dtype=float)
    lows = sub["Low"].to_numpy(dtype=float)
    dates = sub.index
    total = len(sub)

    levels: list[SupportLevel] = []
    for d in range(1, total):
        gap_lower = highs[d - 1]
        gap_upper = lows[d]
        if gap_upper <= gap_lower:  # no es gap alcista
            continue
        closed = bool((lows[d + 1 :] <= gap_lower).any())
        if closed:
            continue
        mid = (gap_lower + gap_upper) / 2
        levels.append(
            SupportLevel(
                price=float(mid),
                element="gap_unfilled",
                points=SCORE_OTHER_ELEMENT_POINTS,
                metadata={
                    "gap_date": dates[d].isoformat(),
                    "gap_lower": float(gap_lower),
                    "gap_upper": float(gap_upper),
                },
            )
        )
    return levels


def _series_asof(series: pd.Series, date: pd.Timestamp) -> float | None:
    """Valor de `series` en `date` vía `.asof()` (último ≤). None si no hay o es NaN."""
    try:
        value = series.asof(date)
    except (KeyError, TypeError):
        return None
    if pd.isna(value):
        return None
    return float(value)


def divergence_levels(
    ohlcv_daily: pd.DataFrame,
    pivots: list[Pivot],
    rsi_series: pd.Series,
    macd_hist_series: pd.Series,
    close_today: float,
) -> list[SupportLevel]:
    """Divergencia alcista entre los dos pivots bajos más recientes (§5.7, 0 o 1 nivel).

    Precio hace nuevo mínimo (p2 < p1) mientras RSI o histograma MACD sube. El nivel
    "ancla" en p2.price. Lookups de osciladores vía `.asof()` por desalineación de índices.
    """
    cutoff = _date_cutoff(ohlcv_daily, DIVERGENCE_LOOKBACK_DAYS)
    low_pivots = sorted(
        (p for p in pivots if p.kind == "low" and p.date >= cutoff), key=lambda p: p.date
    )
    if len(low_pivots) < 2:
        return []

    p1, p2 = low_pivots[-2], low_pivots[-1]
    if p2.price >= p1.price:  # no hay nuevo mínimo
        return []

    rsi1, rsi2 = _series_asof(rsi_series, p1.date), _series_asof(rsi_series, p2.date)
    macd1, macd2 = _series_asof(macd_hist_series, p1.date), _series_asof(macd_hist_series, p2.date)
    rsi_div = rsi1 is not None and rsi2 is not None and rsi2 > rsi1
    macd_div = macd1 is not None and macd2 is not None and macd2 > macd1
    if not (rsi_div or macd_div):
        return []

    oscillator = "both" if rsi_div and macd_div else ("rsi" if rsi_div else "macd")
    return [
        SupportLevel(
            price=p2.price,
            element="divergence",
            points=SCORE_OTHER_ELEMENT_POINTS,
            metadata={
                "oscillator": oscillator,
                "p1_date": p1.date.isoformat(),
                "p2_date": p2.date.isoformat(),
            },
        )
    ]
