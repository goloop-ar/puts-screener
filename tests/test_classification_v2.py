"""Tests de classification_v2 (spec 10 / tanda 2).

OHLCV sintético + pivots/atr/rsi construidos manualmente. Sin APIs externas.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from puts_screener.classification_v2 import (
    ClassificationResult,
    RegimeEvaluation,
    TriggerHit,
    build_composite_label,
    classify_candidate,
    evaluate_bullish_divergence,
    evaluate_post_earnings_dip,
    evaluate_pullback_in_uptrend,
    evaluate_range_floor,
    evaluate_regime,
    select_primary_trigger,
)
from puts_screener.indicators import atr_series, rsi_daily_series
from puts_screener.pivots import Pivot

# --- Helpers ---


def make_ohlcv(
    closes: list[float],
    *,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    opens: list[float] | None = None,
    volumes: list[float] | None = None,
    start: str = "2024-01-02",
) -> pd.DataFrame:
    n = len(closes)
    idx = pd.bdate_range(start=start, periods=n)
    closes_arr = np.array(closes, dtype=float)
    if highs is None:
        highs = (closes_arr * 1.005).tolist()
    if lows is None:
        lows = (closes_arr * 0.995).tolist()
    if opens is None:
        opens = closes_arr.tolist()
    if volumes is None:
        volumes = [1_000_000.0] * n
    return pd.DataFrame(
        {
            "Open": opens,
            "High": highs,
            "Low": lows,
            "Close": closes_arr,
            "Volume": volumes,
        },
        index=idx,
    )


def make_pivot(ohlcv: pd.DataFrame, bar: int, kind: str, *, price: float | None = None) -> Pivot:
    date = ohlcv.index[bar]
    if price is None:
        price = float(ohlcv["Low"].iloc[bar]) if kind == "low" else float(ohlcv["High"].iloc[bar])
    return Pivot(date=date, price=price, kind=kind, atr_at_pivot=1.0)  # type: ignore[arg-type]


def _build_hma_weekly_ohlcv(
    weeks_down: int,
    weeks_up: int,
    *,
    base: float = 100.0,
    down_step: float = -0.2,
    up_step: float = 4.0,
) -> pd.DataFrame:
    """Daily OHLCV cuyo resample W-FRI da una rampa down→up que produce HMA flip reciente."""
    closes_weekly: list[float] = [base + down_step * w for w in range(weeks_down)]
    floor = closes_weekly[-1] if closes_weekly else base
    closes_weekly.extend([floor + up_step * w for w in range(1, weeks_up + 1)])
    daily: list[float] = []
    for wc in closes_weekly:
        daily.extend([wc] * 5)
    return make_ohlcv(daily, start="2020-01-06")


# --- evaluate_regime (8 tests) ---


class TestRegime:
    def test_regime_uptrend(self) -> None:
        ohlcv = make_ohlcv([100.0] * 250)
        result = evaluate_regime(ohlcv, sma_50w=110.0, sma_200w=100.0)
        assert result.regime == "uptrend"
        assert result.hma_flip_active is False

    def test_regime_downtrend(self) -> None:
        ohlcv = make_ohlcv([100.0] * 250)
        result = evaluate_regime(ohlcv, sma_50w=90.0, sma_200w=110.0)
        assert result.regime == "downtrend"

    def test_regime_lateral(self) -> None:
        # SMAs casi iguales (diff 1%) + rango compacto 60d (closes en [98, 102]).
        closes = [100.0 + (i % 3 - 1) * 0.5 for i in range(250)]  # rango chico ~1%
        ohlcv = make_ohlcv(closes)
        result = evaluate_regime(ohlcv, sma_50w=100.0, sma_200w=99.5)
        assert result.regime == "lateral"
        assert result.range_60d_pct is not None
        assert result.range_60d_pct < 0.15

    def test_regime_lateral_falls_to_trend_when_range_wide(self) -> None:
        # SMAs casi iguales pero rango60d > 15% en los últimos 60 bars → cae a uptrend.
        closes = [100.0] * 190 + [100.0 + i * 1.0 for i in range(60)]
        ohlcv = make_ohlcv(closes)
        result = evaluate_regime(ohlcv, sma_50w=100.0, sma_200w=99.5)
        assert result.regime == "uptrend"

    def test_regime_reversal_via_hma_flip(self) -> None:
        # HMA flip reciente + close > HMA50W. Construimos OHLCV largo down→up.
        ohlcv = _build_hma_weekly_ohlcv(weeks_down=120, weeks_up=5, down_step=-0.2, up_step=2.0)
        result = evaluate_regime(ohlcv, sma_50w=80.0, sma_200w=90.0)
        assert result.regime == "reversal"
        assert result.hma_flip_active is True

    def test_regime_reversal_overrides_uptrend(self) -> None:
        # HMA flip + sma_50w > sma_200w → reversal gana (chequeo jerárquico #1).
        ohlcv = _build_hma_weekly_ohlcv(weeks_down=120, weeks_up=5, down_step=-0.2, up_step=2.0)
        result = evaluate_regime(ohlcv, sma_50w=120.0, sma_200w=100.0)
        assert result.regime == "reversal"

    def test_regime_falls_to_downtrend_when_smas_none(self) -> None:
        ohlcv = make_ohlcv([100.0] * 250)
        result = evaluate_regime(ohlcv, sma_50w=None, sma_200w=None)
        assert result.regime == "downtrend"
        result2 = evaluate_regime(ohlcv, sma_50w=100.0, sma_200w=None)
        assert result2.regime == "downtrend"

    def test_regime_short_ohlcv_no_lateral(self) -> None:
        # OHLCV < 60 días → no se puede chequear rango lateral. Cae a tendencia.
        ohlcv = make_ohlcv([100.0] * 30)
        result = evaluate_regime(ohlcv, sma_50w=100.5, sma_200w=99.5)
        assert result.regime == "uptrend"
        assert result.range_60d_pct is None


# --- evaluate_pullback_in_uptrend (3 tests) ---


class TestPullbackInUptrend:
    def test_pullback_hit_in_uptrend(self) -> None:
        hit = evaluate_pullback_in_uptrend(
            regime="uptrend", best_zone_score=10.0, best_zone_distance_pct=0.05
        )
        assert isinstance(hit, TriggerHit)
        assert hit.name == "pullback_in_uptrend"
        assert hit.weight == 0.7

    def test_pullback_none_in_downtrend(self) -> None:
        hit = evaluate_pullback_in_uptrend(
            regime="downtrend", best_zone_score=10.0, best_zone_distance_pct=0.05
        )
        assert hit is None

    def test_pullback_none_without_best_zone(self) -> None:
        hit = evaluate_pullback_in_uptrend(
            regime="uptrend", best_zone_score=None, best_zone_distance_pct=None
        )
        assert hit is None

    def test_pullback_none_when_score_below_min(self) -> None:
        # SCORE_MIN_VALID = 5.0
        hit = evaluate_pullback_in_uptrend(
            regime="uptrend", best_zone_score=3.0, best_zone_distance_pct=0.05
        )
        assert hit is None


# --- evaluate_range_floor (3 tests) ---


class TestRangeFloor:
    def test_range_floor_hit_in_lateral_at_bottom(self) -> None:
        # Últimos 60d con rango 80→100 (highs hasta 100, lows hasta 80), close último = 82.
        closes = [100.0] * 200
        # En los últimos 60d alternamos para forzar rng_min=80 y rng_max=100.
        last_60 = [80.0 if i % 5 == 0 else (100.0 if i % 7 == 0 else 90.0) for i in range(59)]
        last_60.append(82.0)  # close último en tercio inferior
        closes.extend(last_60)
        ohlcv = make_ohlcv(closes)
        hit = evaluate_range_floor(ohlcv, regime="lateral")
        assert isinstance(hit, TriggerHit)
        assert hit.name == "range_floor"

    def test_range_floor_none_in_uptrend(self) -> None:
        closes = [100.0] * 200 + [80.0] * 60
        ohlcv = make_ohlcv(closes)
        hit = evaluate_range_floor(ohlcv, regime="uptrend")
        assert hit is None

    def test_range_floor_none_when_close_in_middle(self) -> None:
        # Rango 80-100, close=95 → tercio superior.
        closes = [80.0, 100.0] * 100 + [95.0] * 60
        ohlcv = make_ohlcv(closes)
        hit = evaluate_range_floor(ohlcv, regime="lateral")
        assert hit is None


# --- evaluate_post_earnings_dip (3 tests) ---


class TestPostEarningsDip:
    def test_post_earnings_dip_hit(self) -> None:
        # Build closes con dip post-earnings ANTES de hacer el OHLCV.
        # Detector mide en post.iloc[POST_EARNINGS_DROP_WINDOW_DAYS-1] = post.iloc[1] = bar 232.
        closes = [100.0] * 250
        closes[229] = 100.0  # pre-earnings
        closes[230] = 95.0  # earnings day
        closes[231] = 93.0  # day 1 post
        closes[232] = 92.0  # day 2 post — el que mide el evaluator
        ohlcv = make_ohlcv(closes)
        earnings_date = ohlcv.index[230]
        hit = evaluate_post_earnings_dip(
            ohlcv,
            earnings_dates=[earnings_date],
            upcoming_earnings_in_window=False,
            regime="uptrend",
        )
        assert isinstance(hit, TriggerHit)
        assert hit.name == "post_earnings_dip"

    def test_post_earnings_dip_none_when_upcoming(self) -> None:
        closes = [100.0] * 250
        closes[230] = 95.0
        closes[231] = 92.0
        ohlcv = make_ohlcv(closes)
        earnings_date = ohlcv.index[230]
        hit = evaluate_post_earnings_dip(
            ohlcv,
            earnings_dates=[earnings_date],
            upcoming_earnings_in_window=True,
            regime="uptrend",
        )
        assert hit is None

    def test_post_earnings_dip_none_in_downtrend(self) -> None:
        closes = [100.0] * 250
        closes[230] = 95.0
        closes[231] = 92.0
        ohlcv = make_ohlcv(closes)
        earnings_date = ohlcv.index[230]
        hit = evaluate_post_earnings_dip(
            ohlcv,
            earnings_dates=[earnings_date],
            upcoming_earnings_in_window=False,
            regime="downtrend",
        )
        assert hit is None


# --- evaluate_bullish_divergence (3 tests) ---


class TestBullishDivergence:
    def test_divergence_hit(self) -> None:
        # Pivots dentro de DIVERGENCE_LOOKBACK_DAYS=60 calendar (~42 bdays).
        # 250 bars, today=bar 249. Cutoff ~bar 207. Usamos bars 220 y 245.
        closes = [100.0] * 250
        closes[220] = 90.0
        closes[245] = 85.0
        ohlcv = make_ohlcv(closes)
        rsi = pd.Series([50.0] * 250, index=ohlcv.index)
        rsi.iloc[220] = 30.0
        rsi.iloc[245] = 40.0
        pivots = [
            make_pivot(ohlcv, 220, "low", price=90.0),
            make_pivot(ohlcv, 245, "low", price=85.0),
        ]
        hit = evaluate_bullish_divergence(ohlcv, rsi, pivots)
        assert isinstance(hit, TriggerHit)
        assert hit.weight == 0.0  # modificador
        assert hit.name == "bullish_divergence"

    def test_divergence_none_when_higher_low(self) -> None:
        ohlcv = make_ohlcv([100.0] * 250)
        rsi = pd.Series([50.0] * 250, index=ohlcv.index)
        rsi.iloc[220] = 30.0
        rsi.iloc[245] = 40.0
        pivots = [
            make_pivot(ohlcv, 220, "low", price=85.0),
            make_pivot(ohlcv, 245, "low", price=90.0),  # HL en precio
        ]
        hit = evaluate_bullish_divergence(ohlcv, rsi, pivots)
        assert hit is None

    def test_divergence_none_when_rsi_above_max(self) -> None:
        ohlcv = make_ohlcv([100.0] * 250)
        rsi = pd.Series([50.0] * 250, index=ohlcv.index)
        rsi.iloc[220] = 40.0
        rsi.iloc[245] = 55.0  # > 45
        pivots = [
            make_pivot(ohlcv, 220, "low", price=90.0),
            make_pivot(ohlcv, 245, "low", price=85.0),
        ]
        hit = evaluate_bullish_divergence(ohlcv, rsi, pivots)
        assert hit is None


# --- select_primary_trigger (4 tests) ---


class TestSelectPrimary:
    def test_single_trigger(self) -> None:
        triggers = [TriggerHit("pullback_in_uptrend", 0.7, {})]
        result = select_primary_trigger(triggers)
        assert result is not None
        assert result.name == "pullback_in_uptrend"

    def test_picks_highest_weight(self) -> None:
        triggers = [
            TriggerHit("range_floor", 0.6, {}),
            TriggerHit("double_bottom_confirmed", 1.0, {}),
            TriggerHit("hma_weekly_flip", 0.5, {}),
        ]
        result = select_primary_trigger(triggers)
        assert result is not None
        assert result.name == "double_bottom_confirmed"

    def test_only_divergence_returns_none(self) -> None:
        triggers = [TriggerHit("bullish_divergence", 0.0, {})]
        assert select_primary_trigger(triggers) is None

    def test_empty_list_returns_none(self) -> None:
        assert select_primary_trigger([]) is None


# --- build_composite_label (5 tests) ---


class TestCompositeLabel:
    def test_uptrend_pullback(self) -> None:
        primary = TriggerHit("pullback_in_uptrend", 0.7, {})
        label = build_composite_label("uptrend", primary, has_divergence=False)
        assert label == "Uptrend: Pullback en tendencia"

    def test_downtrend_double_bottom_with_divergence(self) -> None:
        primary = TriggerHit("double_bottom_confirmed", 1.0, {})
        label = build_composite_label("downtrend", primary, has_divergence=True)
        assert label == "Downtrend: Doble piso confirmado + divergencia"

    def test_reversal_capitulation(self) -> None:
        primary = TriggerHit("capitulation_reclaim", 0.9, {})
        label = build_composite_label("reversal", primary, has_divergence=False)
        assert label == "Reversal: Capitulación con reclaim"

    def test_lateral_range_floor(self) -> None:
        primary = TriggerHit("range_floor", 0.6, {})
        label = build_composite_label("lateral", primary, has_divergence=False)
        assert label == "Lateral: Piso de rango"

    def test_no_primary_trigger(self) -> None:
        label = build_composite_label("uptrend", None, has_divergence=False)
        assert label == "Uptrend: sin trigger"


# --- classify_candidate integración (5 tests) ---


class TestClassifyCandidate:
    def test_uptrend_with_pullback(self) -> None:
        ohlcv = make_ohlcv([100.0] * 250)
        atr = atr_series(ohlcv)
        rsi = pd.Series([50.0] * 250, index=ohlcv.index)
        result = classify_candidate(
            ohlcv=ohlcv,
            pivots=[],
            atr=atr,
            rsi_d=rsi,
            sma_50w=110.0,
            sma_200w=100.0,
            best_zone_score=10.0,
            best_zone_distance_pct=0.05,
            earnings_dates=[],
            upcoming_earnings_in_window=False,
        )
        assert isinstance(result, ClassificationResult)
        assert result.regime == "uptrend"
        assert result.primary_trigger == "pullback_in_uptrend"
        assert result.legacy_tipo == "T1"

    def test_downtrend_with_double_bottom_confirmed(self) -> None:
        # Construir un W confirmado + sma_50w < sma_200w (downtrend).
        closes = [100.0] * 250
        highs = [100.5] * 250
        lows = [99.5] * 250
        lows[100] = 80.0
        closes[130] = 95.0
        highs[130] = 95.0
        lows[160] = 80.5
        for i in range(170, 250):
            closes[i] = 96.0
            highs[i] = 96.5
            lows[i] = 95.5
        ohlcv = make_ohlcv(closes, highs=highs, lows=lows)
        atr = atr_series(ohlcv)
        rsi = pd.Series([50.0] * 250, index=ohlcv.index)
        pivots = [
            make_pivot(ohlcv, 100, "low", price=80.0),
            make_pivot(ohlcv, 130, "high", price=95.0),
            make_pivot(ohlcv, 160, "low", price=80.5),
        ]
        result = classify_candidate(
            ohlcv=ohlcv,
            pivots=pivots,
            atr=atr,
            rsi_d=rsi,
            sma_50w=90.0,
            sma_200w=110.0,
            best_zone_score=None,
            best_zone_distance_pct=None,
            earnings_dates=[],
            upcoming_earnings_in_window=False,
        )
        assert result.regime == "downtrend"
        assert result.primary_trigger == "double_bottom_confirmed"
        assert result.legacy_tipo == "T2"

    def test_reversal_with_hma_flip(self) -> None:
        # HMA flip reciente — produce régimen reversal y hma_weekly_flip como trigger.
        ohlcv = _build_hma_weekly_ohlcv(weeks_down=120, weeks_up=5, down_step=-0.2, up_step=2.0)
        atr = atr_series(ohlcv)
        rsi = pd.Series([50.0] * len(ohlcv), index=ohlcv.index)
        result = classify_candidate(
            ohlcv=ohlcv,
            pivots=[],
            atr=atr,
            rsi_d=rsi,
            sma_50w=80.0,
            sma_200w=90.0,
            best_zone_score=None,
            best_zone_distance_pct=None,
            earnings_dates=[],
            upcoming_earnings_in_window=False,
        )
        assert result.regime == "reversal"
        # primary será hma_weekly_flip (capitulation no se construyó).
        assert result.primary_trigger == "hma_weekly_flip"
        assert result.legacy_tipo == "T2"

    def test_lateral_with_range_floor_plus_divergence(self) -> None:
        # Régimen lateral exige rango60d < 15% AND smas casi iguales.
        # range_floor exige close < min + 0.33*(max-min).
        # Settling: high=100, low=88 → range_pct=13.6% < 15% (lateral OK).
        # Last close=89: threshold = 88 + 0.33*12 = 91.96 → close=89 < 91.96 (range_floor fires).
        closes = [99.5 + (i % 3 - 1) * 0.2 for i in range(200)]
        last_60_close = [94.0] * 60
        last_60_close[20] = 90.0  # bar 220 (pivot bajo 1)
        last_60_close[45] = 89.0  # bar 245 (pivot bajo 2, LL)
        last_60_close[-1] = 89.0  # close último en tercio inferior
        closes.extend(last_60_close)
        highs = [c * 1.005 for c in closes]
        lows = [c * 0.995 for c in closes]
        # Últimos 60: rango compacto pero suficiente para range_floor.
        for i in range(200, 260):
            highs[i] = 100.0
            lows[i] = 88.0
        ohlcv = make_ohlcv(closes, highs=highs, lows=lows)
        atr = atr_series(ohlcv)
        rsi = pd.Series([50.0] * 260, index=ohlcv.index)
        rsi.iloc[220] = 30.0
        rsi.iloc[245] = 42.0
        pivots = [
            make_pivot(ohlcv, 220, "low", price=90.0),
            make_pivot(ohlcv, 245, "low", price=89.0),
        ]
        result = classify_candidate(
            ohlcv=ohlcv,
            pivots=pivots,
            atr=atr,
            rsi_d=rsi,
            sma_50w=100.0,
            sma_200w=99.5,
            best_zone_score=None,
            best_zone_distance_pct=None,
            earnings_dates=[],
            upcoming_earnings_in_window=False,
        )
        assert result.regime == "lateral"
        assert result.primary_trigger == "range_floor"
        assert "bullish_divergence" in result.triggers
        assert "+ divergencia" in result.composite_label

    def test_no_triggers_returns_none_primary(self) -> None:
        # Uptrend sin best_zone, sin pivots, sin earnings: ningún trigger prende.
        ohlcv = make_ohlcv([100.0] * 250)
        atr = atr_series(ohlcv)
        rsi = pd.Series([50.0] * 250, index=ohlcv.index)
        result = classify_candidate(
            ohlcv=ohlcv,
            pivots=[],
            atr=atr,
            rsi_d=rsi,
            sma_50w=110.0,
            sma_200w=100.0,
            best_zone_score=None,  # sin best_zone → pullback no prende
            best_zone_distance_pct=None,
            earnings_dates=[],
            upcoming_earnings_in_window=False,
        )
        assert result.regime == "uptrend"
        assert result.primary_trigger is None
        assert result.legacy_tipo is None
        assert "sin trigger" in result.composite_label


# Smoke: verificar que evaluate_regime con OHLCV real-ish corre sin crash.
def test_evaluate_regime_smoke_with_atr_rsi() -> None:
    closes = [100.0 + np.sin(i / 10) * 5 for i in range(250)]
    ohlcv = make_ohlcv(closes)
    atr = atr_series(ohlcv)
    rsi = rsi_daily_series(ohlcv)
    assert len(atr) == len(ohlcv)
    assert len(rsi) == len(ohlcv)
    result = evaluate_regime(ohlcv, sma_50w=102.0, sma_200w=100.0)
    assert isinstance(result, RegimeEvaluation)
