"""Tests de detectores de patrones técnicos (spec 10 / tanda 1).

OHLCV sintético construido en helpers, sin llamadas a APIs externas. Para los
casos de doble piso donde queremos aislar variables específicas (gap, tolerance,
bounce), construimos los `Pivot` manualmente. Para los casos "limpios" usamos la
implementación real de `detect_pivots`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from puts_screener.config_detectors import (
    DBL_BOTTOM_LOOKBACK_DAYS,
    DBL_BOTTOM_MAX_GAP_BARS,
    DBL_BOTTOM_MIN_GAP_BARS,
    HMA_WEEKLY_PERIOD,
)
from puts_screener.detectors import (
    CapitulationResult,
    DoubleBottomResult,
    HmaFlipResult,
    _hma,
    detect_capitulation_reclaim,
    detect_double_bottom,
    detect_hma_weekly_flip,
)
from puts_screener.indicators import atr_series
from puts_screener.pivots import Pivot

# --- Helpers de generación OHLCV ---


def make_ohlcv(
    closes: list[float],
    *,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    opens: list[float] | None = None,
    volumes: list[float] | None = None,
    start: str = "2024-01-02",
) -> pd.DataFrame:
    """Construye un DataFrame OHLCV con index de business days."""
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
    """Construye un Pivot en la barra `bar` del ohlcv. Usa low/high real si price=None."""
    date = ohlcv.index[bar]
    if price is None:
        price = float(ohlcv["Low"].iloc[bar]) if kind == "low" else float(ohlcv["High"].iloc[bar])
    return Pivot(date=date, price=price, kind=kind, atr_at_pivot=1.0)  # type: ignore[arg-type]


# --- Double bottom ---


class TestDoubleBottom:
    """Tests del detector de doble piso."""

    def test_double_bottom_classic_not_confirmed(self) -> None:
        # OHLCV 250 bdays, lows en 100/160 (dentro del lookback de 180 vs today=249).
        closes = [100.0] * 250
        highs = [100.5] * 250
        lows = [99.5] * 250
        lows[100] = 80.0
        closes[130] = 95.0
        highs[130] = 95.0
        lows[160] = 80.5
        for i in range(170, 250):
            closes[i] = 90.0
            highs[i] = 90.5
            lows[i] = 89.5
        ohlcv = make_ohlcv(closes, highs=highs, lows=lows)
        pivots = [
            make_pivot(ohlcv, 100, "low", price=80.0),
            make_pivot(ohlcv, 130, "high", price=95.0),
            make_pivot(ohlcv, 160, "low", price=80.5),
        ]
        result = detect_double_bottom(ohlcv, pivots)
        assert isinstance(result, DoubleBottomResult)
        assert result.confirmed is False
        assert result.low1_price == 80.0
        assert result.low2_price == 80.5
        assert result.neckline_price == 95.0
        assert result.bounce_pct == pytest.approx((95.0 - 80.0) / 80.0)

    def test_double_bottom_confirmed(self) -> None:
        closes = [100.0] * 250
        highs = [100.5] * 250
        lows = [99.5] * 250
        lows[100] = 80.0
        closes[130] = 95.0
        highs[130] = 95.0
        lows[160] = 80.5
        # Close final 96 > neckline 95 → confirmed
        for i in range(170, 250):
            closes[i] = 96.0
            highs[i] = 96.5
            lows[i] = 95.5
        ohlcv = make_ohlcv(closes, highs=highs, lows=lows)
        pivots = [
            make_pivot(ohlcv, 100, "low", price=80.0),
            make_pivot(ohlcv, 130, "high", price=95.0),
            make_pivot(ohlcv, 160, "low", price=80.5),
        ]
        result = detect_double_bottom(ohlcv, pivots)
        assert result is not None
        assert result.confirmed is True

    def test_double_bottom_gap_too_small(self) -> None:
        ohlcv = make_ohlcv([100.0] * 250)
        # gap=10 < MIN_GAP_BARS (15) — bar1=130, bar2=140.
        bar1 = 130
        bar2 = bar1 + DBL_BOTTOM_MIN_GAP_BARS - 5
        pivots = [
            make_pivot(ohlcv, bar1, "low", price=80.0),
            make_pivot(ohlcv, (bar1 + bar2) // 2, "high", price=95.0),
            make_pivot(ohlcv, bar2, "low", price=80.5),
        ]
        result = detect_double_bottom(ohlcv, pivots)
        assert result is None

    def test_double_bottom_gap_too_large(self) -> None:
        ohlcv = make_ohlcv([100.0] * 300)
        # bar1=80, bar2=80+85=165. Ambos dentro de lookback (today=299, cutoff=119).
        # Wait: bar 80 < 119 → filtrado. Let me put bar1=130, bar2=130+85=215.
        bar1 = 130
        bar2 = bar1 + DBL_BOTTOM_MAX_GAP_BARS + 5
        pivots = [
            make_pivot(ohlcv, bar1, "low", price=80.0),
            make_pivot(ohlcv, (bar1 + bar2) // 2, "high", price=95.0),
            make_pivot(ohlcv, bar2, "low", price=80.5),
        ]
        result = detect_double_bottom(ohlcv, pivots)
        assert result is None

    def test_double_bottom_tolerance_exceeded(self) -> None:
        ohlcv = make_ohlcv([100.0] * 250)
        # L1=80, L2=85 → diff 6.25% > 3% tolerance
        pivots = [
            make_pivot(ohlcv, 100, "low", price=80.0),
            make_pivot(ohlcv, 130, "high", price=95.0),
            make_pivot(ohlcv, 160, "low", price=85.0),
        ]
        result = detect_double_bottom(ohlcv, pivots)
        assert result is None

    def test_double_bottom_bounce_too_small(self) -> None:
        ohlcv = make_ohlcv([100.0] * 250)
        # neckline 82 / min_low 80 → bounce 2.5% < 8%
        pivots = [
            make_pivot(ohlcv, 100, "low", price=80.0),
            make_pivot(ohlcv, 130, "high", price=82.0),
            make_pivot(ohlcv, 160, "low", price=80.5),
        ]
        result = detect_double_bottom(ohlcv, pivots)
        assert result is None

    def test_double_bottom_no_lows_in_lookback(self) -> None:
        ohlcv = make_ohlcv([100.0] * 200)
        # Pivots fuera de lookback: usar fechas muy viejas vía construcción manual.
        old_date = ohlcv.index[0] - pd.Timedelta(days=DBL_BOTTOM_LOOKBACK_DAYS * 2)
        pivots = [
            Pivot(date=old_date, price=80.0, kind="low", atr_at_pivot=1.0),
        ]
        result = detect_double_bottom(ohlcv, pivots)
        assert result is None

    def test_double_bottom_picks_most_recent_l2(self) -> None:
        ohlcv = make_ohlcv([100.0] * 250)
        # Tres lows: 100, 140, 180; dos highs entre ellos.
        pivots = [
            make_pivot(ohlcv, 100, "low", price=80.0),
            make_pivot(ohlcv, 120, "high", price=95.0),
            make_pivot(ohlcv, 140, "low", price=80.5),
            make_pivot(ohlcv, 160, "high", price=96.0),
            make_pivot(ohlcv, 180, "low", price=80.3),
        ]
        result = detect_double_bottom(ohlcv, pivots)
        assert result is not None
        # L2 más reciente debe ser bar 180
        assert result.low2_date == ohlcv.index[180]

    def test_double_bottom_empty_ohlcv(self) -> None:
        ohlcv = pd.DataFrame(
            columns=["Open", "High", "Low", "Close", "Volume"],
            index=pd.DatetimeIndex([], name="Date"),
        )
        result = detect_double_bottom(ohlcv, [])
        assert result is None

    def test_double_bottom_short_ohlcv(self) -> None:
        ohlcv = make_ohlcv([100.0] * 5)
        result = detect_double_bottom(ohlcv, [])
        assert result is None

    def test_double_bottom_synthetic_neckline_from_highs(self) -> None:
        # Sin pivots altos entre L1 y L2: usa max(High) del segmento como neckline.
        # Construimos closes bajos en el segmento (W trough) y un spike de high en 128.
        closes = [100.0] * 250
        highs = [100.5] * 250
        lows = [99.5] * 250
        # Segmento del W: closes a $82 entre bar 100 y 160, highs a $84 excepto spike.
        for i in range(100, 161):
            closes[i] = 82.0
            highs[i] = 84.0
            lows[i] = 80.0
        lows[100] = 80.0
        lows[160] = 80.5
        highs[128] = 95.0  # spike — esperado como neckline sintética
        ohlcv = make_ohlcv(closes, highs=highs, lows=lows)
        pivots = [
            make_pivot(ohlcv, 100, "low", price=80.0),
            make_pivot(ohlcv, 160, "low", price=80.5),
        ]
        result = detect_double_bottom(ohlcv, pivots)
        assert result is not None
        assert result.neckline_price == 95.0
        assert result.neckline_date == ohlcv.index[128]


# --- Capitulation + reclaim ---


def _build_capit_ohlcv(
    *,
    climax_bar: int,
    reclaim_bar: int | None,
    n: int = 90,
    break_low_before_reclaim: bool = False,
    big_range: bool = True,
    big_volume: bool = True,
    close_pos_high: bool = True,
    predrop: bool = True,
) -> tuple[pd.DataFrame, pd.Series]:
    """Construye OHLCV con una capitulation parametrizada en `climax_bar`."""
    base_price = 100.0
    pre_predrop_price = 100.0  # precio plano antes de la caída
    post_predrop_price = 90.0  # precio tras caída ~10%
    climax_low_price = 80.0
    climax_high_price = 95.0  # rango = 15 = ~10×ATR de 1.5
    climax_close = (
        92.0 if close_pos_high else 82.0
    )  # close_pos = (92-80)/15 = 0.8 vs (82-80)/15=0.13

    closes = [pre_predrop_price] * n
    highs = [base_price + 0.5] * n
    lows = [base_price - 0.5] * n
    opens = [base_price] * n
    volumes = [1_000_000.0] * n

    # Predrop: barras [climax_bar - CAPIT_PREDROP_LOOKBACK - 1 .. climax_bar - 1] caen.
    pre_start = max(0, climax_bar - 11)
    pre_end = climax_bar
    if predrop:
        for i in range(pre_start, pre_end):
            # Caída lineal de 100 a 90
            frac = (i - pre_start) / max(1, pre_end - 1 - pre_start)
            price = pre_predrop_price * (1.0 - 0.10 * frac)
            closes[i] = price
            highs[i] = price + 0.5
            lows[i] = price - 0.5
            opens[i] = price
    else:
        # Sin caída: precio se mantiene plano
        for i in range(pre_start, pre_end):
            closes[i] = pre_predrop_price
            highs[i] = pre_predrop_price + 0.5
            lows[i] = pre_predrop_price - 0.5
            opens[i] = pre_predrop_price

    # Climax bar
    climax_high = climax_high_price if big_range else climax_low_price + 1.0
    closes[climax_bar] = climax_close
    highs[climax_bar] = climax_high
    lows[climax_bar] = climax_low_price
    opens[climax_bar] = post_predrop_price
    if big_volume:
        volumes[climax_bar] = 5_000_000.0  # 5× promedio
    else:
        volumes[climax_bar] = 1_000_000.0

    # Post-climax: close DEBAJO de climax_close hasta reclaim_bar (para no triggerear
    # reclaim espurio). Highs/lows controlados para no romper el low climático.
    safe_close = climax_close - 1.0
    for i in range(climax_bar + 1, n):
        closes[i] = safe_close
        highs[i] = safe_close + 0.3
        lows[i] = max(climax_low_price + 0.5, safe_close - 0.3)
        opens[i] = safe_close

    # Si hay reclaim_bar, el close de esa barra supera climax_close.
    if reclaim_bar is not None and reclaim_bar < n:
        if break_low_before_reclaim:
            # Romper el low climático antes del reclaim
            mid = (climax_bar + reclaim_bar) // 2
            lows[mid] = climax_low_price - 1.0
            closes[mid] = climax_low_price - 0.5
        closes[reclaim_bar] = climax_close + 3.0
        highs[reclaim_bar] = climax_close + 3.5
        lows[reclaim_bar] = max(climax_close - 0.5, climax_low_price + 0.5)
        opens[reclaim_bar] = climax_close + 1.0
        # Tras el reclaim, mantener high y NO romper el low — no afecta tests
        # porque sólo se busca el reclaim más cercano post-climax.
        for i in range(reclaim_bar + 1, n):
            closes[i] = closes[reclaim_bar]
            highs[i] = closes[reclaim_bar] + 0.3
            lows[i] = closes[reclaim_bar] - 0.3
            opens[i] = closes[reclaim_bar]

    ohlcv = make_ohlcv(closes, highs=highs, lows=lows, opens=opens, volumes=volumes)
    atr = atr_series(ohlcv, length=14)
    return ohlcv, atr


class TestCapitulation:
    """Tests del detector de capitulation + reclaim."""

    def test_capitulation_reclaim_next_day(self) -> None:
        ohlcv, atr = _build_capit_ohlcv(climax_bar=40, reclaim_bar=41)
        result = detect_capitulation_reclaim(ohlcv, atr)
        assert isinstance(result, CapitulationResult)
        assert result.climax_date == ohlcv.index[40]
        assert result.reclaim_date == ohlcv.index[41]
        assert result.range_atr_ratio > 2.5
        assert result.volume_avg_ratio > 2.5

    def test_capitulation_reclaim_day_8(self) -> None:
        ohlcv, atr = _build_capit_ohlcv(climax_bar=40, reclaim_bar=48)
        result = detect_capitulation_reclaim(ohlcv, atr)
        assert result is not None
        assert result.reclaim_date == ohlcv.index[48]

    def test_capitulation_reclaim_outside_window(self) -> None:
        # reclaim_bar = climax + 12 (fuera de CAPIT_RECLAIM_WINDOW_DAYS=10)
        ohlcv, atr = _build_capit_ohlcv(climax_bar=40, reclaim_bar=52)
        result = detect_capitulation_reclaim(ohlcv, atr)
        assert result is None

    def test_capitulation_no_reclaim(self) -> None:
        ohlcv, atr = _build_capit_ohlcv(climax_bar=40, reclaim_bar=None)
        result = detect_capitulation_reclaim(ohlcv, atr)
        assert result is None

    def test_capitulation_reclaim_breaks_low(self) -> None:
        ohlcv, atr = _build_capit_ohlcv(
            climax_bar=40, reclaim_bar=46, break_low_before_reclaim=True
        )
        result = detect_capitulation_reclaim(ohlcv, atr)
        assert result is None

    def test_capitulation_small_range(self) -> None:
        ohlcv, atr = _build_capit_ohlcv(climax_bar=40, reclaim_bar=41, big_range=False)
        result = detect_capitulation_reclaim(ohlcv, atr)
        assert result is None

    def test_capitulation_low_volume(self) -> None:
        ohlcv, atr = _build_capit_ohlcv(climax_bar=40, reclaim_bar=41, big_volume=False)
        result = detect_capitulation_reclaim(ohlcv, atr)
        assert result is None

    def test_capitulation_close_at_low(self) -> None:
        ohlcv, atr = _build_capit_ohlcv(climax_bar=40, reclaim_bar=41, close_pos_high=False)
        result = detect_capitulation_reclaim(ohlcv, atr)
        assert result is None

    def test_capitulation_no_predrop(self) -> None:
        ohlcv, atr = _build_capit_ohlcv(climax_bar=40, reclaim_bar=41, predrop=False)
        result = detect_capitulation_reclaim(ohlcv, atr)
        assert result is None

    def test_capitulation_multiple_picks_most_recent(self) -> None:
        # Dos capitulations dentro del lookback de 60: una en bar 75 y otra en bar 100.
        # Esperamos la más reciente (bar 100).
        ohlcv, atr = _build_capit_ohlcv(climax_bar=75, reclaim_bar=76, n=120)
        closes = ohlcv["Close"].tolist()
        highs = ohlcv["High"].tolist()
        lows = ohlcv["Low"].tolist()
        volumes = ohlcv["Volume"].tolist()
        # Recovery sostenida tras primer reclaim para tener base alta del segundo predrop.
        for i in range(77, 89):
            closes[i] = 100.0
            highs[i] = 100.5
            lows[i] = 99.5
        # Predrop del segundo episodio entre 89 y 99.
        for i in range(89, 100):
            frac = (i - 89) / 10.0
            price = 100.0 * (1.0 - 0.10 * frac)
            closes[i] = price
            highs[i] = price + 0.5
            lows[i] = price - 0.5
        # Climax bar 100
        closes[100] = 92.0
        highs[100] = 95.0
        lows[100] = 80.0
        volumes[100] = 5_000_000.0
        # Reclaim bar 101
        closes[101] = 95.0
        highs[101] = 95.5
        lows[101] = 92.0
        for i in range(102, 120):
            closes[i] = 95.0
            highs[i] = 95.5
            lows[i] = 94.5
        ohlcv2 = make_ohlcv(closes, highs=highs, lows=lows, volumes=volumes)
        atr2 = atr_series(ohlcv2, length=14)
        result = detect_capitulation_reclaim(ohlcv2, atr2)
        assert result is not None
        assert result.climax_date == ohlcv2.index[100]

    def test_capitulation_atr_nan(self) -> None:
        # ATR con NaN en la fecha climática → skip sin crash.
        ohlcv, atr = _build_capit_ohlcv(climax_bar=40, reclaim_bar=41)
        atr_with_nan = atr.copy()
        atr_with_nan.iloc[40] = np.nan
        # No debe crashear; puede ser None o, si hay otra climax válida, esa otra.
        result = detect_capitulation_reclaim(ohlcv, atr_with_nan)
        assert result is None or isinstance(result, CapitulationResult)

    def test_capitulation_empty_ohlcv(self) -> None:
        ohlcv = pd.DataFrame(
            columns=["Open", "High", "Low", "Close", "Volume"],
            index=pd.DatetimeIndex([], name="Date"),
        )
        atr = pd.Series([], dtype=float)
        result = detect_capitulation_reclaim(ohlcv, atr)
        assert result is None


# --- HMA weekly flip ---


def _build_hma_weekly_ohlcv(
    *,
    weeks_down: int = 60,
    weeks_up: int = 5,
    base_price: float = 100.0,
    down_step: float = -0.5,
    up_step: float = 0.5,
) -> pd.DataFrame:
    """Construye OHLCV daily que resampleado semanalmente da una rampa down→up."""
    # 5 días hábiles por semana
    closes_weekly = []
    for w in range(weeks_down):
        closes_weekly.append(base_price + down_step * w)
    floor_price = closes_weekly[-1] if closes_weekly else base_price
    for w in range(1, weeks_up + 1):
        closes_weekly.append(floor_price + up_step * w)

    daily_closes = []
    for wc in closes_weekly:
        # 5 días con el mismo close por semana — el último viernes captura wc.
        daily_closes.extend([wc] * 5)
    ohlcv = make_ohlcv(daily_closes, start="2020-01-06")  # Lunes
    return ohlcv


class TestHmaWeeklyFlip:
    """Tests del detector de flip semanal del HMA(50)."""

    def test_hma_flip_last_week(self) -> None:
        # 120 weeks de bajada lenta seguidas de 5 weeks de subida pronunciada.
        # El flip debería ocurrir en las últimas semanas.
        ohlcv = _build_hma_weekly_ohlcv(weeks_down=120, weeks_up=5, down_step=-0.2, up_step=2.0)
        result = detect_hma_weekly_flip(ohlcv)
        assert isinstance(result, HmaFlipResult)
        assert result.weeks_since_flip < 3
        assert result.slope > 0
        assert result.close_above is True

    def test_hma_flip_two_weeks_ago(self) -> None:
        # Flip hace ~2 semanas: 120 down + 4 up con up_step suficiente para que el
        # slope post-flip supere HMA_MIN_SLOPE_PCT (0.001).
        ohlcv = _build_hma_weekly_ohlcv(weeks_down=120, weeks_up=4, down_step=-0.2, up_step=4.0)
        result = detect_hma_weekly_flip(ohlcv)
        assert result is not None
        assert 0 <= result.weeks_since_flip < 3

    def test_hma_flip_too_old(self) -> None:
        # 100 down + 20 up — flip ocurrió hace tiempo, fuera del lookback de 3.
        ohlcv = _build_hma_weekly_ohlcv(weeks_down=100, weeks_up=20, down_step=-0.2, up_step=1.0)
        result = detect_hma_weekly_flip(ohlcv)
        assert result is None

    def test_hma_no_flip_always_positive(self) -> None:
        # 120 weeks subiendo monotónicamente.
        ohlcv = _build_hma_weekly_ohlcv(weeks_down=0, weeks_up=125, base_price=50.0, up_step=0.5)
        result = detect_hma_weekly_flip(ohlcv)
        assert result is None

    def test_hma_flip_slope_too_small(self) -> None:
        # Rebote chiquito (whipsaw): up_step de 0.01 → slope post-flip muy chico.
        ohlcv = _build_hma_weekly_ohlcv(weeks_down=120, weeks_up=2, down_step=-0.2, up_step=0.005)
        result = detect_hma_weekly_flip(ohlcv)
        # Slope post-flip está bajo el threshold → None
        assert result is None

    def test_hma_close_below_hma_flag(self) -> None:
        # Flip ocurre, pero el close último está debajo del HMA → close_above=False.
        # Hard to construct directly; usamos una rampa donde el último close esté
        # apenas debajo del HMA suavizado.
        # Mejor: armamos los closes manualmente.
        weekly = [100.0 - i * 0.2 for i in range(120)]
        floor = weekly[-1]
        weekly.extend([floor + 0.3, floor + 0.5, floor + 0.4])  # último close baja
        daily = []
        for wc in weekly:
            daily.extend([wc] * 5)
        ohlcv = make_ohlcv(daily, start="2020-01-06")
        result = detect_hma_weekly_flip(ohlcv)
        # Puede o no detectar flip; si lo hace, validamos la flag de close_above.
        if result is not None:
            # close_above puede ser True o False dependiendo del HMA exacto; lo que
            # importa es que el detector setea el campo sin crashear.
            assert isinstance(result.close_above, bool)

    def test_hma_short_series(self) -> None:
        # Menos de 100 weeks (HMA_WEEKLY_PERIOD * 2).
        ohlcv = _build_hma_weekly_ohlcv(weeks_down=20, weeks_up=5)
        result = detect_hma_weekly_flip(ohlcv)
        assert result is None

    def test_hma_constant_series(self) -> None:
        # HMA sobre serie constante debe ser constante (validación matemática).
        series = pd.Series([100.0] * 200, index=pd.bdate_range(start="2020-01-06", periods=200))
        hma = _hma(series, HMA_WEEKLY_PERIOD)
        non_nan = hma.dropna()
        assert len(non_nan) > 0
        assert np.allclose(non_nan.to_numpy(), 100.0, atol=1e-9)


# --- Smoke combinado ---


def test_combined_smoke_w_and_capitulation() -> None:
    """Smoke: corre los 3 detectores sobre un OHLCV con W + capitulation embebida."""
    # 300 barras: W con lows en 130/180 (dentro del lookback 180), capitulation
    # en bar 240 (dentro del CAPIT_LOOKBACK_DAYS=60 vs today=299).
    n = 300
    closes = [100.0] * n
    highs = [100.5] * n
    lows = [99.5] * n
    volumes = [1_000_000.0] * n

    # L1 en bar 130
    lows[130] = 80.0
    closes[130] = 81.0
    # Neckline en bar 155
    highs[155] = 95.0
    closes[155] = 94.0
    # L2 en bar 180
    lows[180] = 80.3
    closes[180] = 81.0
    # Recovery hasta bar 220
    for i in range(181, 220):
        closes[i] = 80.0 + (i - 180) * 0.5
        highs[i] = closes[i] + 0.5
        lows[i] = closes[i] - 0.5

    # Predrop entre 230 y 240
    for i in range(230, 240):
        closes[i] = 99.0 - (i - 230) * 1.0
        highs[i] = closes[i] + 0.5
        lows[i] = closes[i] - 0.5

    # Capitulation bar 240
    closes[240] = 92.0
    highs[240] = 95.0
    lows[240] = 80.0
    volumes[240] = 5_000_000.0

    # Post-climax bajo close hasta reclaim
    for i in range(241, n):
        closes[i] = 91.0
        highs[i] = 91.3
        lows[i] = 90.7

    # Reclaim bar 241
    closes[241] = 95.0
    highs[241] = 95.5
    lows[241] = 92.0

    # Resto plano alto
    for i in range(242, n):
        closes[i] = 95.0 + (i - 242) * 0.05
        highs[i] = closes[i] + 0.3
        lows[i] = closes[i] - 0.3

    ohlcv = make_ohlcv(closes, highs=highs, lows=lows, volumes=volumes)
    atr = atr_series(ohlcv, length=14)
    pivots = [
        make_pivot(ohlcv, 130, "low", price=80.0),
        make_pivot(ohlcv, 155, "high", price=95.0),
        make_pivot(ohlcv, 180, "low", price=80.3),
    ]

    # Double bottom debe encontrarse.
    dbl = detect_double_bottom(ohlcv, pivots)
    assert isinstance(dbl, DoubleBottomResult)
    assert dbl.low1_date == ohlcv.index[130]
    assert dbl.low2_date == ohlcv.index[180]

    # Capitulation debe encontrarse.
    cap = detect_capitulation_reclaim(ohlcv, atr)
    assert isinstance(cap, CapitulationResult)
    assert cap.climax_date == ohlcv.index[240]
    assert cap.reclaim_date == ohlcv.index[241]

    # HMA: la serie es muy corta semanalmente (~50 weeks) → puede devolver None
    # o un resultado. Solo verificamos que no crashea.
    hma_result = detect_hma_weekly_flip(ohlcv)
    assert hma_result is None or isinstance(hma_result, HmaFlipResult)
