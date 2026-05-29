"""Clasificación dual régimen + triggers (spec 10).

Reemplaza el sistema legacy T1-T5 de classification.py. La función
classify_candidate corre DESPUÉS del Paso 2 de soportes, no antes — el
trigger `pullback_in_uptrend` necesita el `best_zone` con score y distancia.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import pandas as pd

from puts_screener.config_classification_v2 import (
    DIVERGENCE_LOOKBACK_DAYS,
    DIVERGENCE_RSI_MAX,
    POST_EARNINGS_DROP_PCT,
    POST_EARNINGS_DROP_WINDOW_DAYS,
    POST_EARNINGS_LOOKBACK_DAYS,
    PRIMARY_TRIGGER_TO_LEGACY_TIPO,
    RANGE_FLOOR_BOTTOM_THIRD,
    RANGE_FLOOR_LOOKBACK_DAYS,
    REGIME_LABELS,
    REGIME_LATERAL_MAX_RANGE_PCT,
    REGIME_LATERAL_RANGE_DAYS,
    REGIME_LATERAL_TOLERANCE_PCT,
    TRIGGER_LABELS,
    TRIGGER_REGIME_COMPAT,
    TRIGGER_WEIGHTS,
)
from puts_screener.config_supports import (
    MAX_DISTANCE_TO_SUPPORT_PCT,
    SCORE_MIN_VALID,
)
from puts_screener.detectors import (
    detect_capitulation_reclaim,
    detect_double_bottom,
    detect_hma_weekly_flip,
)
from puts_screener.pivots import Pivot

Regime = Literal["uptrend", "lateral", "downtrend", "reversal"]


@dataclass(frozen=True)
class RegimeEvaluation:
    """Resultado de la evaluación de régimen jerárquica."""

    regime: Regime
    sma_50w: float | None
    sma_200w: float | None
    range_60d_pct: float | None  # solo si se calculó (lateral check)
    hma_flip_active: bool  # solo True si regime == "reversal"


@dataclass(frozen=True)
class TriggerHit:
    """Un trigger que dio positivo para el candidato."""

    name: str
    weight: float
    metadata: dict[str, Any]  # info específica del trigger


@dataclass(frozen=True)
class ClassificationResult:
    """Output completo de classify_candidate: régimen + triggers + label + legacy tipo."""

    regime: Regime
    triggers: tuple[str, ...]  # nombres ordenados por peso desc
    primary_trigger: str | None
    composite_label: str
    trigger_metadata: dict[str, dict[str, Any]] = field(default_factory=dict)
    legacy_tipo: str | None = None  # mapeo para columna `tipo` legacy


# --- Régimen ---


def evaluate_regime(
    ohlcv: pd.DataFrame,
    sma_50w: float | None,
    sma_200w: float | None,
    *,
    today: pd.Timestamp | None = None,
) -> RegimeEvaluation:
    """Asigna régimen jerárquico al ticker.

    Orden de evaluación:
    1. Si HMA50W flip reciente AND close > HMA50W → reversal.
    2. Si |sma_50w - sma_200w| / sma_200w < tolerance AND rango60d compacto → lateral.
    3. Si sma_50w > sma_200w → uptrend.
    4. Else → downtrend.

    Si sma_50w o sma_200w son None, se cae directo a downtrend (sin info de tendencia).
    """
    # 1. Reversal: HMA50W flipeó reciente AND close > HMA50W.
    hma_flip = detect_hma_weekly_flip(ohlcv, today=today)
    hma_flip_active = hma_flip is not None and hma_flip.close_above
    if hma_flip_active:
        return RegimeEvaluation(
            regime="reversal",
            sma_50w=sma_50w,
            sma_200w=sma_200w,
            range_60d_pct=None,
            hma_flip_active=True,
        )

    # Sin tendencia conocida → fallback a downtrend (conservador).
    if sma_50w is None or sma_200w is None or sma_200w == 0:
        return RegimeEvaluation(
            regime="downtrend",
            sma_50w=sma_50w,
            sma_200w=sma_200w,
            range_60d_pct=None,
            hma_flip_active=False,
        )

    # 2. Lateral: smas casi iguales AND rango compacto.
    sma_diff_pct = abs(sma_50w - sma_200w) / sma_200w
    range_60d_pct: float | None = None
    if sma_diff_pct < REGIME_LATERAL_TOLERANCE_PCT and not ohlcv.empty:
        window = ohlcv.iloc[-REGIME_LATERAL_RANGE_DAYS:]
        if len(window) >= REGIME_LATERAL_RANGE_DAYS:
            high_60d = float(window["High"].max())
            low_60d = float(window["Low"].min())
            if low_60d > 0:
                range_60d_pct = (high_60d - low_60d) / low_60d
                if range_60d_pct < REGIME_LATERAL_MAX_RANGE_PCT:
                    return RegimeEvaluation(
                        regime="lateral",
                        sma_50w=sma_50w,
                        sma_200w=sma_200w,
                        range_60d_pct=range_60d_pct,
                        hma_flip_active=False,
                    )

    # 3. Uptrend vs 4. Downtrend.
    regime: Regime = "uptrend" if sma_50w > sma_200w else "downtrend"
    return RegimeEvaluation(
        regime=regime,
        sma_50w=sma_50w,
        sma_200w=sma_200w,
        range_60d_pct=range_60d_pct,
        hma_flip_active=False,
    )


# --- Triggers ---


def evaluate_pullback_in_uptrend(
    *,
    regime: Regime,
    best_zone_score: float | None,
    best_zone_distance_pct: float | None,
) -> TriggerHit | None:
    """pullback_in_uptrend: régimen uptrend + best_zone con score válido + distancia OK."""
    if regime not in TRIGGER_REGIME_COMPAT["pullback_in_uptrend"]:
        return None
    if best_zone_score is None or best_zone_distance_pct is None:
        return None
    if best_zone_score < SCORE_MIN_VALID:
        return None
    if best_zone_distance_pct > MAX_DISTANCE_TO_SUPPORT_PCT:
        return None
    return TriggerHit(
        name="pullback_in_uptrend",
        weight=TRIGGER_WEIGHTS["pullback_in_uptrend"],
        metadata={
            "best_zone_score": best_zone_score,
            "best_zone_distance_pct": best_zone_distance_pct,
        },
    )


def evaluate_range_floor(
    ohlcv: pd.DataFrame,
    *,
    regime: Regime,
    today: pd.Timestamp | None = None,
) -> TriggerHit | None:
    """range_floor: régimen lateral + close actual en tercio inferior del rango 60d."""
    if regime not in TRIGGER_REGIME_COMPAT["range_floor"]:
        return None
    if ohlcv.empty:
        return None
    df = ohlcv if today is None else ohlcv.loc[:today]
    if len(df) < RANGE_FLOOR_LOOKBACK_DAYS:
        return None
    window = df.iloc[-RANGE_FLOOR_LOOKBACK_DAYS:]
    rng_min = float(window["Low"].min())
    rng_max = float(window["High"].max())
    if rng_max <= rng_min:
        return None
    close_today = float(df["Close"].iloc[-1])
    threshold = rng_min + RANGE_FLOOR_BOTTOM_THIRD * (rng_max - rng_min)
    if close_today >= threshold:
        return None
    return TriggerHit(
        name="range_floor",
        weight=TRIGGER_WEIGHTS["range_floor"],
        metadata={
            "range_min": rng_min,
            "range_max": rng_max,
            "close": close_today,
            "threshold": threshold,
        },
    )


def evaluate_post_earnings_dip(
    ohlcv: pd.DataFrame,
    earnings_dates: list[pd.Timestamp],
    upcoming_earnings_in_window: bool,
    *,
    regime: Regime,
    today: pd.Timestamp | None = None,
) -> TriggerHit | None:
    """post_earnings_dip: earnings reciente con dip ≥5% en 2 días post + sin earnings 30-45 DTE."""
    if regime not in TRIGGER_REGIME_COMPAT["post_earnings_dip"]:
        return None
    if upcoming_earnings_in_window:
        return None
    if ohlcv.empty or not earnings_dates:
        return None

    df = ohlcv if today is None else ohlcv.loc[:today]
    if df.empty:
        return None
    today_ts = df.index[-1]
    cutoff = today_ts - pd.Timedelta(days=POST_EARNINGS_LOOKBACK_DAYS)
    recent = [d for d in earnings_dates if cutoff <= d <= today_ts]
    if not recent:
        return None

    # Tomar el earnings más reciente y medir el dip en POST_EARNINGS_DROP_WINDOW_DAYS post.
    last_earnings = max(recent)
    pre_mask = df.index < last_earnings
    if not pre_mask.any():
        return None
    close_pre = float(df["Close"][pre_mask].iloc[-1])
    post_df = df[df.index > last_earnings]
    if len(post_df) < POST_EARNINGS_DROP_WINDOW_DAYS:
        return None
    close_post = float(post_df["Close"].iloc[POST_EARNINGS_DROP_WINDOW_DAYS - 1])
    if close_pre <= 0:
        return None
    drop = (close_post - close_pre) / close_pre
    if drop > POST_EARNINGS_DROP_PCT:
        return None
    return TriggerHit(
        name="post_earnings_dip",
        weight=TRIGGER_WEIGHTS["post_earnings_dip"],
        metadata={
            "earnings_date": last_earnings,
            "close_pre": close_pre,
            "close_post": close_post,
            "drop_pct": drop,
        },
    )


def evaluate_bullish_divergence(
    ohlcv: pd.DataFrame,
    rsi_d: pd.Series,
    pivots: list[Pivot],
    *,
    today: pd.Timestamp | None = None,
) -> TriggerHit | None:
    """bullish_divergence: P2.price < P1.price + RSI P2 > RSI P1 + RSI P2 < 45.

    Toma los dos pivots bajos más recientes dentro de DIVERGENCE_LOOKBACK_DAYS.
    """
    if ohlcv.empty or rsi_d.empty:
        return None
    today_ts = today if today is not None else ohlcv.index[-1]
    cutoff = today_ts - pd.Timedelta(days=DIVERGENCE_LOOKBACK_DAYS)

    lows = [p for p in pivots if p.kind == "low" and cutoff <= p.date <= today_ts]
    if len(lows) < 2:
        return None
    lows = sorted(lows, key=lambda p: p.date)
    p1, p2 = lows[-2], lows[-1]
    if p2.price >= p1.price:
        return None
    try:
        rsi_p1 = float(rsi_d.loc[p1.date])
        rsi_p2 = float(rsi_d.loc[p2.date])
    except KeyError:
        return None
    if pd.isna(rsi_p1) or pd.isna(rsi_p2):
        return None
    if rsi_p2 <= rsi_p1:
        return None
    if rsi_p2 >= DIVERGENCE_RSI_MAX:
        return None
    return TriggerHit(
        name="bullish_divergence",
        weight=TRIGGER_WEIGHTS["bullish_divergence"],
        metadata={
            "p1_date": p1.date,
            "p1_price": p1.price,
            "p1_rsi": rsi_p1,
            "p2_date": p2.date,
            "p2_price": p2.price,
            "p2_rsi": rsi_p2,
        },
    )


# --- Selector + label ---


def select_primary_trigger(triggers: list[TriggerHit]) -> TriggerHit | None:
    """Devuelve el trigger con mayor peso entre los que tienen weight > 0.

    Tie-breaker: orden de inserción (estable). bullish_divergence (weight=0) nunca gana.
    """
    candidates = [t for t in triggers if t.weight > 0]
    if not candidates:
        return None
    # max() con key respeta el primero en caso de empate (orden de iteración).
    best_idx = 0
    best_weight = candidates[0].weight
    for i in range(1, len(candidates)):
        if candidates[i].weight > best_weight:
            best_idx = i
            best_weight = candidates[i].weight
    return candidates[best_idx]


def build_composite_label(
    regime: Regime,
    primary: TriggerHit | None,
    has_divergence: bool,
) -> str:
    """Formato: '{Régimen}: {Trigger primario}[ + divergencia]' / 'sin trigger' si None."""
    regime_label = REGIME_LABELS.get(regime, regime)
    if primary is None:
        return f"{regime_label}: sin trigger"
    trigger_label = TRIGGER_LABELS.get(primary.name, primary.name)
    suffix = f" + {TRIGGER_LABELS['bullish_divergence']}" if has_divergence else ""
    return f"{regime_label}: {trigger_label}{suffix}"


# --- Orquestador ---


def classify_candidate(
    *,
    ohlcv: pd.DataFrame,
    pivots: list[Pivot],
    atr: pd.Series,
    rsi_d: pd.Series,
    sma_50w: float | None,
    sma_200w: float | None,
    best_zone_score: float | None,
    best_zone_distance_pct: float | None,
    earnings_dates: list[pd.Timestamp],
    upcoming_earnings_in_window: bool,
    today: pd.Timestamp | None = None,
) -> ClassificationResult:
    """Orquesta régimen + 7 triggers + selección primaria + label compuesto + legacy mapper."""
    regime_eval = evaluate_regime(ohlcv, sma_50w, sma_200w, today=today)
    regime = regime_eval.regime

    hits: list[TriggerHit] = []

    # 1. pullback_in_uptrend (solo en uptrend).
    pullback = evaluate_pullback_in_uptrend(
        regime=regime,
        best_zone_score=best_zone_score,
        best_zone_distance_pct=best_zone_distance_pct,
    )
    if pullback is not None:
        hits.append(pullback)

    # 2. double_bottom (confirmed | unconfirmed).
    if regime in TRIGGER_REGIME_COMPAT["double_bottom_confirmed"]:
        dbl = detect_double_bottom(ohlcv, pivots, today=today)
        if dbl is not None:
            name = "double_bottom_confirmed" if dbl.confirmed else "double_bottom_unconfirmed"
            hits.append(
                TriggerHit(
                    name=name,
                    weight=TRIGGER_WEIGHTS[name],
                    metadata={
                        "low1_date": dbl.low1_date,
                        "low1_price": dbl.low1_price,
                        "low2_date": dbl.low2_date,
                        "low2_price": dbl.low2_price,
                        "neckline_price": dbl.neckline_price,
                        "bounce_pct": dbl.bounce_pct,
                        "confirmed": dbl.confirmed,
                    },
                )
            )

    # 3. capitulation_reclaim.
    if regime in TRIGGER_REGIME_COMPAT["capitulation_reclaim"]:
        cap = detect_capitulation_reclaim(ohlcv, atr, today=today)
        if cap is not None:
            hits.append(
                TriggerHit(
                    name="capitulation_reclaim",
                    weight=TRIGGER_WEIGHTS["capitulation_reclaim"],
                    metadata={
                        "climax_date": cap.climax_date,
                        "climax_low": cap.climax_low,
                        "reclaim_date": cap.reclaim_date,
                        "range_atr_ratio": cap.range_atr_ratio,
                        "volume_avg_ratio": cap.volume_avg_ratio,
                    },
                )
            )

    # 4. hma_weekly_flip (solo en reversal — el régimen ya verificó el flip).
    if regime in TRIGGER_REGIME_COMPAT["hma_weekly_flip"] and regime_eval.hma_flip_active:
        hits.append(
            TriggerHit(
                name="hma_weekly_flip",
                weight=TRIGGER_WEIGHTS["hma_weekly_flip"],
                metadata={"hma_flip_active": True},
            )
        )

    # 5. range_floor.
    range_hit = evaluate_range_floor(ohlcv, regime=regime, today=today)
    if range_hit is not None:
        hits.append(range_hit)

    # 6. post_earnings_dip.
    earn_hit = evaluate_post_earnings_dip(
        ohlcv,
        earnings_dates,
        upcoming_earnings_in_window,
        regime=regime,
        today=today,
    )
    if earn_hit is not None:
        hits.append(earn_hit)

    # 7. bullish_divergence (modificador, no compite por primary).
    div_hit = evaluate_bullish_divergence(ohlcv, rsi_d, pivots, today=today)
    if div_hit is not None:
        hits.append(div_hit)

    primary = select_primary_trigger(hits)
    has_divergence = div_hit is not None

    # Triggers ordenados por peso desc (para presentación). Tie-breaker = orden inserción.
    triggers_sorted = sorted(hits, key=lambda t: -t.weight)
    trigger_names = tuple(t.name for t in triggers_sorted)
    trigger_metadata = {t.name: t.metadata for t in hits}

    label = build_composite_label(regime, primary, has_divergence)
    legacy_tipo = PRIMARY_TRIGGER_TO_LEGACY_TIPO.get(primary.name) if primary else None

    return ClassificationResult(
        regime=regime,
        triggers=trigger_names,
        primary_trigger=primary.name if primary else None,
        composite_label=label,
        trigger_metadata=trigger_metadata,
        legacy_tipo=legacy_tipo,
    )
