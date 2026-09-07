"""Tests de detectores de confirmación por velas (spec 11 / tanda 1).

OHLCV sintético construido a mano, ATR pasado como serie constante (no vía atr_series)
para que los ratios de body/wick sean exactos y fáciles de verificar. Sin llamadas a
APIs externas.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from puts_screener.candle_patterns import (
    _bar_geometry,
    analyze_candles,
    detect_bearish_breakdown,
    detect_body_reclaim,
    detect_wick_rejection,
)
from puts_screener.config_candles import CANDLE_ZONE_PROXIMITY_ATR
from puts_screener.models_candles import CandleAnalysis, CandleSignal
from puts_screener.models_support import SupportLevel, SupportZone

# --- Helpers ---


def make_ohlcv(
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    *,
    start: str = "2024-01-02",
) -> pd.DataFrame:
    """Construye un DataFrame OHLCV con index de business days a partir de listas explícitas."""
    n = len(closes)
    idx = pd.bdate_range(start=start, periods=n)
    return pd.DataFrame(
        {
            "Open": opens,
            "High": highs,
            "Low": lows,
            "Close": closes,
            "Volume": [1_000_000.0] * n,
        },
        index=idx,
    )


def make_atr(ohlcv: pd.DataFrame, value: float = 1.0) -> pd.Series:
    """ATR constante sobre el index del ohlcv — aísla los tests de EWM de atr_series."""
    return pd.Series(value, index=ohlcv.index)


def make_zone(lower: float, upper: float, *, score: float = 10.0) -> SupportZone:
    center = (lower + upper) / 2
    return SupportZone(
        center_price=center,
        lower_bound=lower,
        upper_bound=upper,
        score=score,
        elements=[SupportLevel(price=center, element="sma_200w")],
        has_dynamic_confirmer=True,
        distance_pct=0.02,
    )


ZONE = make_zone(95.0, 100.0)


# --- Geometría base (§6.1) ---


class TestBarGeometry:
    def test_basic_green_bar(self) -> None:
        geo = _bar_geometry(open_=100.0, high=105.0, low=98.0, close=103.0, atr=2.0)
        assert geo.body == pytest.approx(3.0)
        assert geo.body_atr == pytest.approx(1.5)
        assert geo.upper_wick == pytest.approx(2.0)
        assert geo.lower_wick == pytest.approx(2.0)
        assert geo.is_green is True

    def test_doji_no_div_by_zero(self) -> None:
        # body=0 -> denom guardado = max(0, atr*0.05) = 0.1
        # upper_wick = 101 - max(100,100) = 1.0; lower_wick = min(100,100) - 99 = 1.0
        geo = _bar_geometry(open_=100.0, high=101.0, low=99.0, close=100.0, atr=2.0)
        assert geo.body == pytest.approx(0.0)
        assert math.isfinite(geo.lower_wick_ratio)
        assert math.isfinite(geo.upper_wick_ratio)
        assert geo.lower_wick_ratio == pytest.approx(1.0 / 0.1)
        assert geo.upper_wick_ratio == pytest.approx(1.0 / 0.1)

    def test_no_wicks(self) -> None:
        geo = _bar_geometry(open_=100.0, high=103.0, low=100.0, close=103.0, atr=2.0)
        assert geo.upper_wick == pytest.approx(0.0)
        assert geo.lower_wick == pytest.approx(0.0)

    def test_red_bar_is_not_green(self) -> None:
        geo = _bar_geometry(open_=103.0, high=104.0, low=100.0, close=101.0, atr=1.0)
        assert geo.is_green is False


# --- wick_rejection (§6.2) ---


class TestWickRejection:
    def test_hammer_canonico_detects(self) -> None:
        ohlcv = make_ohlcv(opens=[99.0], highs=[100.2], lows=[96.0], closes=[100.0])
        atr = make_atr(ohlcv, 1.0)
        signals = detect_wick_rejection(ohlcv, atr, ZONE)
        assert len(signals) == 1
        assert signals[0].kind == "wick_rejection"
        assert signals[0].direction == "bullish"
        assert signals[0].in_zone is True

    def test_hammer_rojo_tambien_detecta(self) -> None:
        # Color del cuerpo no importa: hammer rojo sigue siendo hammer.
        ohlcv = make_ohlcv(opens=[100.0], highs=[100.1], lows=[96.0], closes=[99.5])
        atr = make_atr(ohlcv, 1.0)
        signals = detect_wick_rejection(ohlcv, atr, ZONE)
        assert len(signals) == 1
        assert signals[0].direction == "bullish"

    def test_ratio_1_4_rechaza(self) -> None:
        # lower_wick=1.4, body=1.0 -> ratio=1.4 < WICK_REJECTION_MIN_RATIO (1.5)
        ohlcv = make_ohlcv(opens=[99.0], highs=[100.1], lows=[97.6], closes=[100.0])
        atr = make_atr(ohlcv, 1.0)
        signals = detect_wick_rejection(ohlcv, atr, ZONE)
        assert signals == []

    def test_mecha_superior_larga_rechaza(self) -> None:
        # lower_wick ratio=3.0 (ok) pero upper_wick ratio=1.5 > MAX_UPPER_RATIO (1.0)
        ohlcv = make_ohlcv(opens=[99.0], highs=[101.5], lows=[96.0], closes=[100.0])
        atr = make_atr(ohlcv, 1.0)
        signals = detect_wick_rejection(ohlcv, atr, ZONE)
        assert signals == []

    def test_doji_cuerpo_cero_no_crashea_y_rechaza(self) -> None:
        # body_atr=0 < WICK_REJECTION_MIN_BODY_ATR (0.05) -> rechaza en el primer gate.
        ohlcv = make_ohlcv(opens=[100.0], highs=[101.0], lows=[99.0], closes=[100.0])
        atr = make_atr(ohlcv, 1.0)
        signals = detect_wick_rejection(ohlcv, atr, ZONE)
        assert signals == []


class TestZoneProximityGate:
    """Gate de proximidad (§3.2): mismo patrón, solo cambia la posición vs la zona."""

    _BASE = dict(open_=99.0, high=100.2, low=96.0, close=100.0)

    def _shifted_bar(self, shift: float) -> pd.DataFrame:
        return make_ohlcv(
            opens=[self._BASE["open_"] - shift],
            highs=[self._BASE["high"] - shift],
            lows=[self._BASE["low"] - shift],
            closes=[self._BASE["close"] - shift],
        )

    def test_dentro_de_zona_detecta(self) -> None:
        ohlcv = self._shifted_bar(0.0)  # low=96, dentro de [95, 100]
        atr = make_atr(ohlcv, 1.0)
        signals = detect_wick_rejection(ohlcv, atr, ZONE)
        assert len(signals) == 1
        assert signals[0].in_zone is True
        assert signals[0].distance_to_zone_atr == pytest.approx(0.0)

    def test_a_0_5_atr_fuera_detecta_borde_inclusivo(self) -> None:
        ohlcv = self._shifted_bar(1.5)  # low=94.5, 0.5 ATR por debajo de lower_bound=95
        atr = make_atr(ohlcv, 1.0)
        signals = detect_wick_rejection(ohlcv, atr, ZONE)
        assert len(signals) == 1
        assert signals[0].in_zone is False
        assert signals[0].distance_to_zone_atr == pytest.approx(CANDLE_ZONE_PROXIMITY_ATR)

    def test_a_0_6_atr_fuera_rechaza(self) -> None:
        ohlcv = self._shifted_bar(1.6)  # low=94.4, 0.6 ATR por debajo de lower_bound=95
        atr = make_atr(ohlcv, 1.0)
        signals = detect_wick_rejection(ohlcv, atr, ZONE)
        assert signals == []


# --- body_reclaim (§6.3) ---


class TestBodyReclaim:
    def test_engulfing_detects(self) -> None:
        ohlcv = make_ohlcv(
            opens=[100.0, 97.0],
            highs=[100.2, 101.2],
            lows=[96.0, 96.5],
            closes=[97.0, 101.0],
        )
        atr = make_atr(ohlcv, 1.0)
        signals = detect_body_reclaim(ohlcv, atr, ZONE)
        assert len(signals) == 1
        assert signals[0].kind == "body_reclaim_engulfing"
        assert signals[0].direction == "bullish"

    def test_piercing_al_51_pct_detecta(self) -> None:
        # prev body=3 (100->97). threshold = 100 - 0.5*3 = 98.5. close=98.53 (>threshold, <100).
        ohlcv = make_ohlcv(
            opens=[100.0, 97.2],
            highs=[100.2, 98.7],
            lows=[96.0, 96.8],
            closes=[97.0, 98.53],
        )
        atr = make_atr(ohlcv, 1.0)
        signals = detect_body_reclaim(ohlcv, atr, ZONE)
        assert len(signals) == 1
        assert signals[0].kind == "body_reclaim_piercing"

    def test_piercing_al_49_pct_rechaza(self) -> None:
        # close=98.47 < threshold 98.5 -> ni piercing ni engulfing.
        ohlcv = make_ohlcv(
            opens=[100.0, 97.1],
            highs=[100.2, 98.6],
            lows=[96.0, 96.8],
            closes=[97.0, 98.47],
        )
        atr = make_atr(ohlcv, 1.0)
        signals = detect_body_reclaim(ohlcv, atr, ZONE)
        assert signals == []

    def test_morning_star_3_velas_detecta(self) -> None:
        # i-2 roja cuerpo real (100->97), i-1 cuerpo chico (indecision), i verde > midpoint(98.5).
        ohlcv = make_ohlcv(
            opens=[100.0, 97.0, 97.3],
            highs=[100.2, 97.5, 99.2],
            lows=[96.5, 96.8, 97.0],
            closes=[97.0, 97.2, 99.0],
        )
        atr = make_atr(ohlcv, 1.0)
        signals = detect_body_reclaim(ohlcv, atr, ZONE)
        assert len(signals) == 1
        assert signals[0].kind == "body_reclaim_morning_star"

    def test_previa_roja_cuerpo_despreciable_rechaza(self) -> None:
        # prev body=0.1, body_atr=0.1 < BODY_RECLAIM_PREV_MIN_BODY_ATR (0.15) -> no cuenta.
        ohlcv = make_ohlcv(
            opens=[100.0, 99.9],
            highs=[100.1, 101.2],
            lows=[99.5, 99.5],
            closes=[99.9, 101.0],
        )
        atr = make_atr(ohlcv, 1.0)
        signals = detect_body_reclaim(ohlcv, atr, ZONE)
        assert signals == []


# --- bearish_breakdown (§6.4) ---


class TestBearishBreakdown:
    def test_engulfing_bajista_detects(self) -> None:
        ohlcv = make_ohlcv(
            opens=[97.0, 100.0],
            highs=[100.2, 100.3],
            lows=[96.8, 95.5],
            closes=[100.0, 96.0],
        )
        atr = make_atr(ohlcv, 1.0)
        signals = detect_bearish_breakdown(ohlcv, atr, ZONE)
        kinds = {s.kind for s in signals}
        assert "bearish_engulfing" in kinds
        assert all(s.direction == "bearish" for s in signals)

    def test_dark_cloud_aislado_detects(self) -> None:
        # prev green 97->100 (body=3, midpoint=98.5). close=98.0: < midpoint pero >= open_prev(97)
        # -> dark_cloud si, engulfing no (98.0 no es < 97).
        ohlcv = make_ohlcv(
            opens=[97.0, 100.0],
            highs=[100.2, 100.1],
            lows=[96.8, 97.5],
            closes=[100.0, 98.0],
        )
        atr = make_atr(ohlcv, 1.0)
        signals = detect_bearish_breakdown(ohlcv, atr, ZONE)
        kinds = {s.kind for s in signals}
        assert "bearish_dark_cloud" in kinds
        assert "bearish_engulfing" not in kinds

    def test_momentum_2_1x_detecta(self) -> None:
        zone_wide = make_zone(90.0, 105.0)
        ohlcv = make_ohlcv(
            opens=[100.0, 101.0, 102.0, 103.0],
            highs=[101.1, 102.1, 103.1, 103.2],
            lows=[99.8, 100.8, 101.8, 100.5],
            closes=[101.0, 102.0, 103.0, 100.9],  # body=2.1, avg previo=1.0 -> 2.1x
        )
        atr = make_atr(ohlcv, 1.0)
        signals = detect_bearish_breakdown(ohlcv, atr, zone_wide, lookback_bars=1)
        kinds = {s.kind for s in signals}
        assert "bearish_momentum" in kinds

    def test_momentum_1_9x_rechaza(self) -> None:
        zone_wide = make_zone(90.0, 105.0)
        ohlcv = make_ohlcv(
            opens=[100.0, 101.0, 102.0, 103.0],
            highs=[101.1, 102.1, 103.1, 103.2],
            lows=[99.8, 100.8, 101.8, 100.9],
            closes=[101.0, 102.0, 103.0, 101.1],  # body=1.9, avg previo=1.0 -> 1.9x
        )
        atr = make_atr(ohlcv, 1.0)
        signals = detect_bearish_breakdown(ohlcv, atr, zone_wide, lookback_bars=1)
        kinds = {s.kind for s in signals}
        assert "bearish_momentum" not in kinds

    def test_vela_bajista_por_encima_de_zona_rechaza_por_gate(self) -> None:
        # Patron fuerte (engulfing-shaped) pero close=102 > zone.upper_bound=100 -> gate rechaza.
        ohlcv = make_ohlcv(
            opens=[103.0, 108.0],
            highs=[108.2, 108.3],
            lows=[102.8, 101.5],
            closes=[108.0, 102.0],
        )
        atr = make_atr(ohlcv, 1.0)
        signals = detect_bearish_breakdown(ohlcv, atr, ZONE)
        assert signals == []


# --- Bordes ---


class TestEdgeCases:
    def test_ohlcv_vacio_no_crashea(self) -> None:
        empty = pd.DataFrame(
            columns=["Open", "High", "Low", "Close", "Volume"],
            index=pd.DatetimeIndex([], name="Date"),
        )
        empty_atr = pd.Series([], dtype=float)
        assert detect_wick_rejection(empty, empty_atr, ZONE) == []
        assert detect_body_reclaim(empty, empty_atr, ZONE) == []
        assert detect_bearish_breakdown(empty, empty_atr, ZONE) == []
        analysis = analyze_candles(empty, empty_atr, ZONE)
        assert analysis.signals == ()
        assert analysis.has_bullish_confirmation is False
        assert analysis.has_bearish_breakdown is False
        assert analysis.strongest_bullish is None

    def test_menos_barras_que_lookback_no_crashea(self) -> None:
        # Solo 1 barra disponible; lookback_bars default=3 -> bars_ago 1,2 quedan fuera de rango.
        ohlcv = make_ohlcv(opens=[99.0], highs=[100.2], lows=[96.0], closes=[100.0])
        atr = make_atr(ohlcv, 1.0)
        signals = detect_wick_rejection(ohlcv, atr, ZONE)
        assert len(signals) == 1
        assert signals[0].bars_ago == 0

    def test_atr_con_nan_se_saltea_sin_crashear(self) -> None:
        ohlcv = make_ohlcv(opens=[99.0], highs=[100.2], lows=[96.0], closes=[100.0])
        atr = pd.Series([np.nan], index=ohlcv.index)
        signals = detect_wick_rejection(ohlcv, atr, ZONE)
        assert signals == []


# --- analyze_candles (integración liviana de este módulo) ---


class TestAnalyzeCandles:
    def test_consolida_señal_alcista(self) -> None:
        ohlcv = make_ohlcv(opens=[99.0], highs=[100.2], lows=[96.0], closes=[100.0])
        atr = make_atr(ohlcv, 1.0)
        analysis = analyze_candles(ohlcv, atr, ZONE)
        assert isinstance(analysis, CandleAnalysis)
        assert analysis.has_bullish_confirmation is True
        assert analysis.has_bearish_breakdown is False
        assert analysis.strongest_bullish is not None
        assert isinstance(analysis.strongest_bullish, CandleSignal)

    def test_consolida_señal_bajista(self) -> None:
        ohlcv = make_ohlcv(
            opens=[97.0, 100.0],
            highs=[100.2, 100.3],
            lows=[96.8, 95.5],
            closes=[100.0, 96.0],
        )
        atr = make_atr(ohlcv, 1.0)
        analysis = analyze_candles(ohlcv, atr, ZONE)
        assert analysis.has_bearish_breakdown is True

    def test_sin_señales(self) -> None:
        # Vela neutra, cuerpo chico, sin mechas relevantes, lejos de cualquier gate.
        ohlcv = make_ohlcv(opens=[150.0], highs=[150.3], lows=[149.8], closes=[150.1])
        atr = make_atr(ohlcv, 1.0)
        analysis = analyze_candles(ohlcv, atr, ZONE)
        assert analysis.signals == ()
        assert analysis.has_bullish_confirmation is False
        assert analysis.has_bearish_breakdown is False
        assert analysis.strongest_bullish is None
