"""Tests de los 7 elementos del score de soportes (spec 03 §5).

Fixtures sintéticas en código. Los valores esperados están verificados a mano (números
explícitos en las aserciones), no recalculados con la fórmula del código.
"""

import re

import numpy as np
import pandas as pd
import pytest

from puts_screener.pivots import Pivot
from puts_screener.support_elements import (
    avwap_levels,
    divergence_levels,
    fib_levels,
    gap_levels,
    hvn_levels,
    polarity_levels,
    sma_200_levels,
)

TODAY = pd.Timestamp("2026-05-21")


def _daily(closes, highs=None, lows=None, volumes=None, end=TODAY):
    """Arma un OHLCV diario terminando en `end` a partir de arrays."""
    n = len(closes)
    idx = pd.bdate_range(end=end, periods=n)
    closes = np.asarray(closes, dtype=float)
    highs = closes if highs is None else np.asarray(highs, dtype=float)
    lows = closes if lows is None else np.asarray(lows, dtype=float)
    volumes = np.full(n, 1_000_000.0) if volumes is None else np.asarray(volumes, dtype=float)
    return pd.DataFrame(
        {"Open": closes, "High": highs, "Low": lows, "Close": closes, "Volume": volumes},
        index=idx,
    )


def _pivot(date, price, kind):
    return Pivot(date=pd.Timestamp(date), price=float(price), kind=kind, atr_at_pivot=2.0)


# --- SMA 200 (§5.1) ---


def test_sma_200_levels_constant_series():
    """210 semanas y 250 días constantes a 100 → SMA200W=100, EMA200D=100, 2 pts c/u."""
    weekly = _daily([100.0] * 210)
    daily = _daily([100.0] * 250)
    levels = sma_200_levels(daily, weekly)

    by_element = {lvl.element: lvl for lvl in levels}
    assert set(by_element) == {"sma_200w", "sma_200d"}
    assert by_element["sma_200w"].price == pytest.approx(100.0)
    assert by_element["sma_200d"].price == pytest.approx(100.0)
    assert by_element["sma_200w"].points == 2
    assert by_element["sma_200d"].points == 2


def test_sma_200_levels_ema_cross_check():
    """EMA200D contra referencia pandas.ewm(span=200); SMA200W contra rolling(200).mean()."""
    rng = np.random.default_rng(1)
    daily_closes = 100 + np.cumsum(rng.normal(0, 0.3, 400))
    weekly_closes = 100 + np.cumsum(rng.normal(0, 0.5, 220))
    daily = _daily(daily_closes)
    weekly = _daily(weekly_closes)

    levels = {lvl.element: lvl.price for lvl in sma_200_levels(daily, weekly)}
    expected_ema = pd.Series(daily_closes).ewm(span=200, adjust=False).mean().iloc[-1]
    expected_sma = pd.Series(weekly_closes).rolling(200).mean().iloc[-1]
    assert levels["sma_200d"] == pytest.approx(expected_ema)
    assert levels["sma_200w"] == pytest.approx(expected_sma)


def test_sma_200_levels_insufficient_data():
    """Menos de 200 semanas/días → sin niveles, sin excepción."""
    assert sma_200_levels(_daily([100.0] * 50), _daily([100.0] * 50)) == []


# --- Polaridad (§5.2) ---


def test_polarity_levels_only_broken_resistances():
    """Solo los pivots altos por debajo del close (ya superados) generan niveles."""
    daily = _daily([100.0] * 300)
    pivots = [
        _pivot("2026-03-01", 100.0, "high"),  # superado (100 < 120)
        _pivot("2026-03-15", 110.0, "high"),  # superado
        _pivot("2026-04-01", 130.0, "high"),  # NO superado (130 > 120)
        _pivot("2026-04-05", 95.0, "low"),  # ignorado (es low)
    ]
    levels = polarity_levels(daily, pivots, close_today=120.0)

    prices = sorted(lvl.price for lvl in levels)
    assert prices == [100.0, 110.0]
    assert all(lvl.element == "polarity" and lvl.points == 1 for lvl in levels)


def test_polarity_levels_excludes_old_pivots():
    """Pivot alto más viejo que 252 ruedas hábiles → excluido."""
    daily = _daily([100.0] * 300)
    pivots = [_pivot("2024-01-01", 100.0, "high")]  # >2 años atrás
    assert polarity_levels(daily, pivots, close_today=120.0) == []


# --- Fibonacci (§5.3) ---


def test_fib_levels_with_high_pivot():
    """low=100, high=150 (posterior) → fib_618=119.1, fib_786=110.7."""
    daily = _daily([100.0] * 300)
    pivots = [
        _pivot("2026-04-01", 100.0, "low"),
        _pivot("2026-05-01", 150.0, "high"),
    ]
    levels = {lvl.element: lvl.price for lvl in fib_levels(daily, pivots, close_today=130.0)}
    assert levels["fib_618"] == pytest.approx(119.1)
    assert levels["fib_786"] == pytest.approx(110.7)


def test_fib_levels_uptrend_in_progress_uses_close():
    """Sin pivot alto posterior (subida en curso) → close_today=150 como techo."""
    daily = _daily([100.0] * 300)
    pivots = [_pivot("2026-04-01", 100.0, "low")]
    levels = {lvl.element: lvl.price for lvl in fib_levels(daily, pivots, close_today=150.0)}
    assert levels["fib_618"] == pytest.approx(119.1)
    assert levels["fib_786"] == pytest.approx(110.7)


def test_fib_levels_metadata_includes_pivot_prices():
    """metadata de fib incluye los precios del impulso (low_price/high_price)."""
    daily = _daily([100.0] * 300)
    pivots = [
        _pivot("2026-04-01", 100.0, "low"),
        _pivot("2026-05-01", 150.0, "high"),
    ]
    levels = fib_levels(daily, pivots, close_today=130.0)
    assert levels
    for lvl in levels:
        assert lvl.metadata["low_price"] == pytest.approx(100.0)
        assert lvl.metadata["high_price"] == pytest.approx(150.0)


def test_fib_levels_metadata_in_progress_high_price_is_close():
    """Subida en curso → high_price en metadata = close_today (techo del impulso)."""
    daily = _daily([100.0] * 300)
    pivots = [_pivot("2026-04-01", 100.0, "low")]
    levels = fib_levels(daily, pivots, close_today=150.0)
    assert levels
    for lvl in levels:
        assert lvl.metadata["low_price"] == pytest.approx(100.0)
        assert lvl.metadata["high_price"] == pytest.approx(150.0)


def test_fib_levels_no_low_pivot():
    """Sin pivot bajo en la ventana → []."""
    daily = _daily([100.0] * 300)
    pivots = [_pivot("2026-05-01", 150.0, "high")]
    assert fib_levels(daily, pivots, close_today=130.0) == []


def test_fib_levels_degenerate_high_below_low():
    """pivot_high.price < pivot_low.price → no fue impulso alcista → []."""
    daily = _daily([100.0] * 300)
    pivots = [
        _pivot("2026-04-01", 100.0, "low"),
        _pivot("2026-05-01", 90.0, "high"),
    ]
    assert fib_levels(daily, pivots, close_today=95.0) == []


# --- AVWAP (§5.4) ---


def test_avwap_levels_pivot_low_anchor():
    """5 barras (H=L=C) desde el ancla, volúmenes [400,100,100,100,100] → AVWAP=22.5."""
    closes = [10.0, 20.0, 30.0, 40.0, 50.0]
    volumes = [400.0, 100.0, 100.0, 100.0, 100.0]
    daily = _daily(closes, volumes=volumes)
    pivot = _pivot(daily.index[0], 10.0, "low")

    levels = avwap_levels(daily, [pivot], last_earnings_date=None)
    by_element = {lvl.element: lvl.price for lvl in levels}
    # AVWAP = (10*400 + 20*100 + 30*100 + 40*100 + 50*100) / 800 = 18000 / 800 = 22.5
    assert by_element["avwap_pivot_low"] == pytest.approx(22.5)
    assert "avwap_earnings" not in by_element  # earnings None → omitido
    assert "avwap_52w_high" not in by_element  # <252 barras → omitido


def test_avwap_levels_earnings_out_of_window_omitted():
    """Earnings hace ~13 meses → AVWAP de earnings omitido; el de pivot bajo se calcula."""
    closes = [10.0, 20.0, 30.0, 40.0, 50.0]
    daily = _daily(closes)
    pivot = _pivot(daily.index[0], 10.0, "low")
    old_earnings = daily.index[-1] - pd.Timedelta(days=400)

    levels = {lvl.element for lvl in avwap_levels(daily, [pivot], last_earnings_date=old_earnings)}
    assert "avwap_earnings" not in levels
    assert "avwap_pivot_low" in levels


def test_avwap_levels_earnings_in_window_included():
    """Earnings dentro de la ventana → AVWAP de earnings presente."""
    closes = [10.0, 20.0, 30.0, 40.0, 50.0]
    daily = _daily(closes)
    earnings = daily.index[1]  # reciente, dentro de ventana

    levels = {lvl.element for lvl in avwap_levels(daily, [], last_earnings_date=earnings)}
    assert "avwap_earnings" in levels


# --- HVN (§5.5) ---


def test_hvn_levels_detects_volume_node():
    """252 días con volumen masivo concentrado cerca de 100 → aparece un HVN ahí."""
    rng = np.random.default_rng(3)
    n = 252
    # Base: precios repartidos en [80,120] con volumen chico.
    closes = np.linspace(80.0, 120.0, n)
    volumes = np.full(n, 1_000_000.0)
    # Inyecta 40 días pegados a 100 con volumen enorme.
    spike_idx = rng.choice(n, size=40, replace=False)
    closes[spike_idx] = 100.0
    volumes[spike_idx] = 200_000_000.0
    daily = _daily(closes, volumes=volumes)

    levels = hvn_levels(daily)
    assert levels  # no vacío
    assert all(lvl.element == "hvn" and lvl.points == 1 for lvl in levels)
    assert min(abs(lvl.price - 100.0) for lvl in levels) < 2.0


def test_hvn_levels_contiguous_buckets_merge_into_one():
    """Volumen concentrado en una franja angosta y contigua → UN solo nivel cerca del centro."""
    n = 252
    # Todos los días con close en [99.5, 100.5]: buckets centrales contiguos dominan.
    closes = np.full(n, 100.0)
    closes[0] = 99.5  # fija price_min
    closes[1] = 100.5  # fija price_max
    daily = _daily(closes)

    levels = hvn_levels(daily)
    assert len(levels) == 1
    assert levels[0].price == pytest.approx(100.0, abs=0.1)


def test_hvn_levels_metadata_includes_bucket_range():
    """metadata de hvn incluye rango de precio del bucket y el ancho del bucket."""
    n = 252
    closes = np.full(n, 100.0)
    closes[0] = 99.5  # fija price_min
    closes[1] = 100.5  # fija price_max
    daily = _daily(closes)

    levels = hvn_levels(daily)
    assert len(levels) == 1
    md = levels[0].metadata
    expected_width = (100.5 - 99.5) / 50  # (max_52w - min_52w) / HVN_NUM_BUCKETS
    assert md["bucket_width"] == pytest.approx(expected_width)
    assert md["bucket_lower_price"] <= levels[0].price <= md["bucket_upper_price"]
    span = md["bucket_upper_price"] - md["bucket_lower_price"]
    assert span == pytest.approx((md["bucket_end"] - md["bucket_start"] + 1) * md["bucket_width"])


def test_hvn_levels_insufficient_data():
    """Menos de 252 días → []."""
    assert hvn_levels(_daily([100.0] * 100)) == []


# --- Gaps (§5.6) ---


def test_gap_levels_unfilled_gap_detected():
    """Gap up en D (high[D-1]=100, low[D]=110) sin cierre posterior → nivel en 105."""
    highs = [101.0, 101.0, 100.0, 112.0, 113.0, 114.0]
    lows = [99.0, 99.0, 98.0, 110.0, 111.0, 112.0]
    closes = [100.0, 100.0, 99.0, 111.0, 112.0, 113.0]
    daily = _daily(closes, highs=highs, lows=lows)

    levels = gap_levels(daily)
    assert len(levels) == 1
    assert levels[0].price == pytest.approx(105.0)  # (100 + 110) / 2
    assert levels[0].element == "gap_unfilled"


def test_gap_levels_filled_gap_not_detected():
    """Mismo gap pero una barra posterior perfora high[D-1]=100 (low=99) → no detectado."""
    highs = [101.0, 100.0, 112.0, 113.0, 101.0, 100.0]
    lows = [99.0, 98.0, 110.0, 111.0, 99.0, 98.0]  # índice 4: low=99 <= 100 → cierra
    closes = [100.0, 99.0, 111.0, 112.0, 100.0, 99.0]
    daily = _daily(closes, highs=highs, lows=lows)

    assert gap_levels(daily) == []


# --- Divergencia (§5.7) ---


def test_divergence_levels_detected_on_rsi():
    """Dos pivots bajos recientes, p2 más bajo que p1, RSI sube → divergencia en p2.price."""
    daily = _daily([100.0] * 60)
    p1_date = daily.index[-30]
    p2_date = daily.index[-5]
    pivots = [_pivot(p1_date, 95.0, "low"), _pivot(p2_date, 90.0, "low")]
    rsi = pd.Series(40.0, index=daily.index)
    rsi.loc[p1_date] = 30.0
    rsi.loc[p2_date] = 35.0  # RSI más alto en el nuevo mínimo
    macd = pd.Series(0.0, index=daily.index)  # MACD sin divergencia

    levels = divergence_levels(daily, pivots, rsi, macd, close_today=90.0)
    assert len(levels) == 1
    assert levels[0].price == pytest.approx(90.0)
    assert levels[0].element == "divergence"
    assert levels[0].metadata["oscillator"] == "rsi"


def test_divergence_levels_rejected_when_oscillators_also_fall():
    """p2 más bajo pero RSI y MACD también más bajos → sin divergencia."""
    daily = _daily([100.0] * 60)
    p1_date = daily.index[-30]
    p2_date = daily.index[-5]
    pivots = [_pivot(p1_date, 95.0, "low"), _pivot(p2_date, 90.0, "low")]
    rsi = pd.Series(40.0, index=daily.index)
    rsi.loc[p1_date] = 35.0
    rsi.loc[p2_date] = 30.0  # RSI más bajo
    macd = pd.Series(0.0, index=daily.index)
    macd.loc[p1_date] = 1.0
    macd.loc[p2_date] = -1.0  # MACD más bajo

    assert divergence_levels(daily, pivots, rsi, macd, close_today=90.0) == []


def test_divergence_levels_needs_two_pivots():
    """Menos de 2 pivots bajos en la ventana → []."""
    daily = _daily([100.0] * 60)
    pivots = [_pivot(daily.index[-5], 90.0, "low")]
    rsi = pd.Series(40.0, index=daily.index)
    macd = pd.Series(0.0, index=daily.index)
    assert divergence_levels(daily, pivots, rsi, macd, close_today=90.0) == []


# --- formato de fechas en metadata ---

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def test_metadata_dates_are_date_only():
    """Todas las fechas en metadata son YYYY-MM-DD (sin parte de tiempo)."""
    daily = _daily([100.0] * 300)
    pivots = [
        _pivot("2026-04-01", 100.0, "low"),
        _pivot("2026-05-01", 150.0, "high"),
    ]

    for lvl in polarity_levels(daily, pivots, close_today=160.0):
        assert _DATE_RE.match(lvl.metadata["pivot_date"]), lvl.metadata["pivot_date"]

    for lvl in fib_levels(daily, pivots, close_today=130.0):
        assert _DATE_RE.match(lvl.metadata["low_date"]), lvl.metadata["low_date"]
        assert _DATE_RE.match(lvl.metadata["high_date"]), lvl.metadata["high_date"]

    gap_daily = _daily(
        [100.0, 100.0, 99.0, 111.0, 112.0, 113.0],
        highs=[101.0, 101.0, 100.0, 112.0, 113.0, 114.0],
        lows=[99.0, 99.0, 98.0, 110.0, 111.0, 112.0],
    )
    gaps = gap_levels(gap_daily)
    assert gaps
    for lvl in gaps:
        assert _DATE_RE.match(lvl.metadata["gap_date"]), lvl.metadata["gap_date"]

    av_daily = _daily([10.0, 20.0, 30.0, 40.0, 50.0])
    av_pivot = _pivot(av_daily.index[0], 10.0, "low")
    avwaps = avwap_levels(av_daily, [av_pivot], last_earnings_date=None)
    assert avwaps
    for lvl in avwaps:
        assert _DATE_RE.match(lvl.metadata["anchor_date"]), lvl.metadata["anchor_date"]
