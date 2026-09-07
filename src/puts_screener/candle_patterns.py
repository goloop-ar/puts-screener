"""Detectores de confirmación por velas dentro de zonas de soporte validadas (spec 11).

Tres familias: rechazo por mecha (`wick_rejection`), reclamo de cuerpo (`body_reclaim_*`,
alcistas) y perforación con convicción (`bearish_*`). Funciones puras, no tocan el pipeline.
Reusan `atr_series` de `indicators.py` (no recalculan ATR) y `SupportZone` de
`models_support.py` para el gate de contexto — sin este gate el detector es ruido puro.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from puts_screener.config_candles import (
    BEARISH_ENGULFING_MIN_BODY_ATR,
    BEARISH_MOMENTUM_BODY_MULTIPLIER,
    BODY_RECLAIM_PIERCING_PCT,
    BODY_RECLAIM_PREV_MIN_BODY_ATR,
    CANDLE_LOOKBACK_BARS,
    CANDLE_ZONE_PROXIMITY_ATR,
    MORNING_STAR_MAX_MIDDLE_BODY_ATR,
    WICK_REJECTION_MAX_UPPER_RATIO,
    WICK_REJECTION_MIN_BODY_ATR,
    WICK_REJECTION_MIN_RATIO,
)
from puts_screener.models_candles import CandleAnalysis, CandleSignal
from puts_screener.models_support import SupportZone


@dataclass(frozen=True)
class _BarGeometry:
    """Geometría de una barra individual, normalizada por ATR."""

    body: float  # |close - open|, unidades de precio
    body_atr: float  # body / atr
    upper_wick: float
    lower_wick: float
    lower_wick_ratio: float  # lower_wick / max(body, atr * WICK_REJECTION_MIN_BODY_ATR)
    upper_wick_ratio: float  # upper_wick / max(body, atr * WICK_REJECTION_MIN_BODY_ATR)
    is_green: bool  # close >= open


# --- Geometría base (§6.1) ---


def _bar_geometry(open_: float, high: float, low: float, close: float, atr: float) -> _BarGeometry:
    """Geometría de una barra. Ratios de mecha guardados contra ~0 para evitar div/0 en dojis."""
    body = abs(close - open_)
    body_atr = body / atr if atr > 0 else 0.0
    upper_wick = high - max(open_, close)
    lower_wick = min(open_, close) - low
    denom = max(body, atr * WICK_REJECTION_MIN_BODY_ATR)
    lower_wick_ratio = lower_wick / denom if denom > 0 else 0.0
    upper_wick_ratio = upper_wick / denom if denom > 0 else 0.0
    return _BarGeometry(
        body=body,
        body_atr=body_atr,
        upper_wick=upper_wick,
        lower_wick=lower_wick,
        lower_wick_ratio=lower_wick_ratio,
        upper_wick_ratio=upper_wick_ratio,
        is_green=close >= open_,
    )


def _resolve_today(ohlcv: pd.DataFrame, today: pd.Timestamp | None) -> pd.Timestamp | None:
    """Timestamp de "hoy": el provisto (recortado a la última fila <=), o la última barra."""
    if ohlcv.empty:
        return None
    if today is None:
        return ohlcv.index[-1]
    if today in ohlcv.index:
        return today
    valid = ohlcv.index[ohlcv.index <= today]
    if len(valid) == 0:
        return None
    return valid[-1]


def _today_bar_index(ohlcv: pd.DataFrame, today: pd.Timestamp | None) -> int | None:
    """Posición entera de la barra "hoy", o None si no hay barra válida."""
    today_ts = _resolve_today(ohlcv, today)
    if today_ts is None:
        return None
    try:
        loc = ohlcv.index.get_loc(today_ts)
    except KeyError:
        return None
    if isinstance(loc, slice):
        return None
    return int(loc)


def _atr_at(atr: pd.Series, date: pd.Timestamp) -> float | None:
    """ATR en `date`. None si la fecha no está o el valor es NaN — evita crashear el detector."""
    if date not in atr.index:
        return None
    value = atr.loc[date]
    if pd.isna(value):
        return None
    return float(value)


def _geometry_at(ohlcv: pd.DataFrame, atr: pd.Series, bar: int) -> _BarGeometry | None:
    """Geometría de la barra en la posición `bar`. None si está fuera de rango o ATR es NaN."""
    if bar < 0 or bar >= len(ohlcv):
        return None
    atr_val = _atr_at(atr, ohlcv.index[bar])
    if atr_val is None or atr_val <= 0:
        return None
    row = ohlcv.iloc[bar]
    return _bar_geometry(
        float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"]), atr_val
    )


def _zone_proximity(value: float, zone: SupportZone, atr: float | None) -> tuple[bool, float]:
    """True+0.0 si `value` cae dentro de la zona; si no, (False, distancia en ATR al borde)."""
    if zone.lower_bound <= value <= zone.upper_bound:
        return True, 0.0
    if atr is None or atr <= 0:
        return False, float("inf")
    if value < zone.lower_bound:
        distance = (zone.lower_bound - value) / atr
    else:
        distance = (value - zone.upper_bound) / atr
    return False, distance


# --- Wick rejection (§6.2) ---


def detect_wick_rejection(
    ohlcv: pd.DataFrame,
    atr: pd.Series,
    zone: SupportZone,
    *,
    lookback_bars: int = CANDLE_LOOKBACK_BARS,
    today: pd.Timestamp | None = None,
) -> list[CandleSignal]:
    """Detecta velas de rechazo por mecha inferior (hammer / dragonfly doji) en la zona.

    El color del cuerpo no se chequea: un hammer rojo sigue siendo hammer. El contexto
    lo da la zona (gate de proximidad), no el color de la vela.
    """
    if ohlcv.empty or atr.empty:
        return []
    today_bar = _today_bar_index(ohlcv, today)
    if today_bar is None:
        return []

    signals: list[CandleSignal] = []
    lows = ohlcv["Low"]
    for bars_ago in range(lookback_bars):
        bar = today_bar - bars_ago
        geo = _geometry_at(ohlcv, atr, bar)
        if geo is None:
            continue
        if geo.body_atr < WICK_REJECTION_MIN_BODY_ATR:
            continue
        if geo.lower_wick_ratio < WICK_REJECTION_MIN_RATIO:
            continue
        if geo.upper_wick_ratio > WICK_REJECTION_MAX_UPPER_RATIO:
            continue

        low_value = float(lows.iloc[bar])
        atr_val = _atr_at(atr, ohlcv.index[bar])
        in_zone, distance_atr = _zone_proximity(low_value, zone, atr_val)
        if not in_zone and distance_atr > CANDLE_ZONE_PROXIMITY_ATR:
            continue

        signals.append(
            CandleSignal(
                kind="wick_rejection",
                direction="bullish",
                bar_date=ohlcv.index[bar],
                bars_ago=bars_ago,
                body_atr=geo.body_atr,
                lower_wick_ratio=geo.lower_wick_ratio,
                upper_wick_ratio=geo.upper_wick_ratio,
                in_zone=in_zone,
                distance_to_zone_atr=distance_atr,
            )
        )
    return signals


# --- Body reclaim (§6.3) ---


def detect_body_reclaim(
    ohlcv: pd.DataFrame,
    atr: pd.Series,
    zone: SupportZone,
    *,
    lookback_bars: int = CANDLE_LOOKBACK_BARS,
    today: pd.Timestamp | None = None,
) -> list[CandleSignal]:
    """Detecta reclaim del cuerpo previo: piercing, engulfing alcista o morning star.

    Si una misma barra califica para más de un patrón, se emite el de mayor fuerza
    (engulfing > morning_star > piercing) y se descarta el resto.
    """
    if ohlcv.empty or atr.empty:
        return []
    today_bar = _today_bar_index(ohlcv, today)
    if today_bar is None:
        return []

    opens = ohlcv["Open"]
    closes = ohlcv["Close"]
    lows = ohlcv["Low"]

    signals: list[CandleSignal] = []
    for bars_ago in range(lookback_bars):
        bar = today_bar - bars_ago
        curr = _geometry_at(ohlcv, atr, bar)
        if curr is None or not curr.is_green:
            continue
        curr_close = float(closes.iloc[bar])

        candidates: list[tuple[int, str, tuple[int, ...]]] = []

        prev = _geometry_at(ohlcv, atr, bar - 1)
        if prev is not None:
            prev_open = float(opens.iloc[bar - 1])
            prev_close = float(closes.iloc[bar - 1])
            is_prev_red = prev_close < prev_open
            if is_prev_red and prev.body_atr >= BODY_RECLAIM_PREV_MIN_BODY_ATR:
                if curr_close > prev_open:
                    candidates.append((3, "body_reclaim_engulfing", (bar - 1, bar)))
                elif curr_close > prev_open - BODY_RECLAIM_PIERCING_PCT * prev.body:
                    candidates.append((1, "body_reclaim_piercing", (bar - 1, bar)))

        far = _geometry_at(ohlcv, atr, bar - 2)
        mid = _geometry_at(ohlcv, atr, bar - 1)
        if far is not None and mid is not None:
            far_open = float(opens.iloc[bar - 2])
            far_close = float(closes.iloc[bar - 2])
            is_far_red = far_close < far_open
            midpoint = (far_open + far_close) / 2.0
            if (
                is_far_red
                and far.body_atr >= BODY_RECLAIM_PREV_MIN_BODY_ATR
                and mid.body_atr <= MORNING_STAR_MAX_MIDDLE_BODY_ATR
                and curr_close > midpoint
            ):
                candidates.append((2, "body_reclaim_morning_star", (bar - 2, bar - 1, bar)))

        if not candidates:
            continue
        _, kind, pattern_bars = max(candidates, key=lambda c: c[0])

        # Gate de contexto sobre el low mínimo del patrón (2 o 3 barras), no solo la última.
        low_value = min(float(lows.iloc[b]) for b in pattern_bars)
        atr_val = _atr_at(atr, ohlcv.index[bar])
        in_zone, distance_atr = _zone_proximity(low_value, zone, atr_val)
        if not in_zone and distance_atr > CANDLE_ZONE_PROXIMITY_ATR:
            continue

        signals.append(
            CandleSignal(
                kind=kind,  # type: ignore[arg-type]
                direction="bullish",
                bar_date=ohlcv.index[bar],
                bars_ago=bars_ago,
                body_atr=curr.body_atr,
                lower_wick_ratio=curr.lower_wick_ratio,
                upper_wick_ratio=curr.upper_wick_ratio,
                in_zone=in_zone,
                distance_to_zone_atr=distance_atr,
            )
        )
    return signals


# --- Bearish breakdown (§6.4) ---


def detect_bearish_breakdown(
    ohlcv: pd.DataFrame,
    atr: pd.Series,
    zone: SupportZone,
    *,
    lookback_bars: int = CANDLE_LOOKBACK_BARS,
    today: pd.Timestamp | None = None,
) -> list[CandleSignal]:
    """Detecta perforación con convicción: engulfing bajista, dark cloud o vela de momentum.

    Gate de contexto distinto al de los detectores alcistas: la vela debe cerrar dentro o
    por debajo de la zona (`close <= zone.upper_bound`). Una vela bajista por encima de la
    zona no la está perforando.

    Exclusividad mutua (fix post-tanda-1): dark_cloud contiene matemáticamente a engulfing
    (su umbral es más laxo — cualquier cierre que satisface engulfing satisface dark_cloud).
    Por barra se emite UNA sola señal, la más fuerte: engulfing > dark_cloud > momentum. Sin
    esto, atribuir poder predictivo por kind en el backtest queda contaminado.
    """
    if ohlcv.empty or atr.empty:
        return []
    today_bar = _today_bar_index(ohlcv, today)
    if today_bar is None:
        return []

    opens = ohlcv["Open"]
    closes = ohlcv["Close"]

    signals: list[CandleSignal] = []
    for bars_ago in range(lookback_bars):
        bar = today_bar - bars_ago
        curr = _geometry_at(ohlcv, atr, bar)
        if curr is None or curr.is_green:
            continue
        curr_close = float(closes.iloc[bar])
        if curr_close > zone.upper_bound:
            continue

        candidates: list[tuple[int, str]] = []

        prev = _geometry_at(ohlcv, atr, bar - 1)
        if prev is not None:
            prev_open = float(opens.iloc[bar - 1])
            prev_close = float(closes.iloc[bar - 1])
            if prev_close >= prev_open:  # i-1 verde
                if (
                    prev.body_atr >= BODY_RECLAIM_PREV_MIN_BODY_ATR
                    and curr.body_atr >= BEARISH_ENGULFING_MIN_BODY_ATR
                    and curr_close < prev_open
                ):
                    candidates.append((3, "bearish_engulfing"))
                if curr_close < prev_open + 0.5 * prev.body:
                    candidates.append((2, "bearish_dark_cloud"))

        prev1 = prev
        prev2 = _geometry_at(ohlcv, atr, bar - 2)
        prev3 = _geometry_at(ohlcv, atr, bar - 3)
        if prev1 is not None and prev2 is not None and prev3 is not None:
            avg_body = (prev1.body + prev2.body + prev3.body) / 3.0
            if avg_body > 0 and curr.body >= BEARISH_MOMENTUM_BODY_MULTIPLIER * avg_body:
                candidates.append((1, "bearish_momentum"))

        if not candidates:
            continue
        _, kind = max(candidates, key=lambda c: c[0])

        atr_val = _atr_at(atr, ohlcv.index[bar])
        in_zone, distance_atr = _zone_proximity(curr_close, zone, atr_val)

        signals.append(
            CandleSignal(
                kind=kind,  # type: ignore[arg-type]
                direction="bearish",
                bar_date=ohlcv.index[bar],
                bars_ago=bars_ago,
                body_atr=curr.body_atr,
                lower_wick_ratio=curr.lower_wick_ratio,
                upper_wick_ratio=curr.upper_wick_ratio,
                in_zone=in_zone,
                distance_to_zone_atr=distance_atr,
            )
        )
    return signals


# --- Orquestador ---


def analyze_candles(
    ohlcv: pd.DataFrame,
    atr: pd.Series,
    zone: SupportZone,
    *,
    today: pd.Timestamp | None = None,
) -> CandleAnalysis:
    """Corre los 3 detectores y consolida el resultado. Punto de entrada del módulo.

    `strongest_bullish`: la señal alcista más reciente (menor `bars_ago`); empate se
    rompe por mayor `body_atr`.
    """
    wick_signals = detect_wick_rejection(ohlcv, atr, zone, today=today)
    reclaim_signals = detect_body_reclaim(ohlcv, atr, zone, today=today)
    breakdown_signals = detect_bearish_breakdown(ohlcv, atr, zone, today=today)

    bullish_signals = tuple(wick_signals) + tuple(reclaim_signals)
    all_signals = bullish_signals + tuple(breakdown_signals)

    strongest_bullish = (
        min(bullish_signals, key=lambda s: (s.bars_ago, -s.body_atr)) if bullish_signals else None
    )

    return CandleAnalysis(
        signals=all_signals,
        has_bullish_confirmation=len(bullish_signals) > 0,
        has_bearish_breakdown=len(breakdown_signals) > 0,
        strongest_bullish=strongest_bullish,
    )


_BEARISH_KIND_PREFIX = "bearish_"
# Todo CandleKind bajista arranca con este prefijo (bearish_engulfing/dark_cloud/momentum); los
# alcistas (wick_rejection, body_reclaim_*) no. Deriva los flags booleanos de persistencia/reporte
# a partir de `ScreenedCandidate.candle_signals` sin tener que re-correr analyze_candles.


def has_bullish_kind(kinds: tuple[str, ...]) -> bool:
    """True si `kinds` (ej. `candle_signals`) contiene algún kind alcista."""
    return any(not k.startswith(_BEARISH_KIND_PREFIX) for k in kinds)


def has_bearish_kind(kinds: tuple[str, ...]) -> bool:
    """True si `kinds` (ej. `candle_signals`) contiene algún kind bajista."""
    return any(k.startswith(_BEARISH_KIND_PREFIX) for k in kinds)
