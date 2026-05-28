"""Tests de chart.build_chart_payload + chart.build_plotly_figure (spec 09 tanda 2).

Fixtures sintéticas: 1500 business days (~6 años) para que SMA200W tenga histórico
suficiente al inicio del rango truncado (test 3). Monkeypatching de `read_ohlcv_raw`
vía `chart.read_ohlcv_raw` (no la real del módulo cache).
"""

import numpy as np
import pandas as pd
import pytest

from puts_screener.models_support import SupportLevel, SupportZone
from puts_screener.streamlit_app import chart
from puts_screener.streamlit_app.chart import (
    ChartPayload,
    build_chart_payload,
    build_plotly_figure,
)
from puts_screener.streamlit_app.models import CandidateDetail, CandidateRow


@pytest.fixture
def large_ohlcv():
    """1500 business days (~6 años), Close monotónico creciente."""
    idx = pd.bdate_range(end="2024-06-28", periods=1500)
    closes = 100.0 + np.arange(1500, dtype=float) * 0.5
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes + 1.0,
            "Low": closes - 1.0,
            "Close": closes,
            "Volume": [1_000_000] * 1500,
        },
        index=idx,
    )


def _candidate_row(ticker="TEST", currency="USD"):
    return CandidateRow(
        ticker=ticker,
        tipo_T="T1",
        spot=850.0,
        sector="Technology",
        country="United States",
        momentum_score=1,
        universes=("sp500",),
        best_zone_score=10.0,
        best_zone_tier=3,
        best_zone_distance_pct=0.02,
        earnings_en_45d=False,
        ex_div_en_45d=False,
        tiene_eventos_macro_en_45d=False,
        strike_natural=820.0,
        currency=currency,
    )


def _zone():
    return SupportZone(
        center_price=820.0,
        lower_bound=810.0,
        upper_bound=830.0,
        score=10.0,
        elements=[SupportLevel(price=820.0, element="sma_200w")],
        has_dynamic_confirmer=True,
        distance_pct=0.02,
    )


def _detail_with_zone(strikes=None):
    if strikes is None:
        strikes = {
            "aggressive": 845.0,
            "natural": 820.0,
            "conservative": 795.0,
            "grid_unit": 5.0,
        }
    return CandidateDetail(
        row=_candidate_row(),
        best_zone=_zone(),
        spot=850.0,
        sma_50w=830.0,
        sma_200w=750.0,
        rsi_d=40.0,
        rsi_w=45.0,
        atr_14=10.0,
        hv_percentile_52w=50.0,
        market_cap=1e12,
        earnings_date=None,
        ex_div_date=None,
        ex_div_amount=None,
        eventos_macro=(),
        strikes=strikes,
        flags_legibles=(),
        momentum_signals=(),
    )


def _detail_without_zone():
    return CandidateDetail(
        row=_candidate_row(),
        best_zone=None,
        spot=850.0,
        sma_50w=None,
        sma_200w=None,
        rsi_d=None,
        rsi_w=None,
        atr_14=None,
        hv_percentile_52w=None,
        market_cap=None,
        earnings_date=None,
        ex_div_date=None,
        ex_div_amount=None,
        eventos_macro=(),
        strikes={
            "aggressive": None,
            "natural": None,
            "conservative": None,
            "grid_unit": None,
        },
        flags_legibles=(),
        momentum_signals=(),
    )


def _payload(zone_lower=810.0, zone_upper=830.0, strikes=None):
    """Builder de ChartPayload sin pasar por build_chart_payload (para tests de la figura)."""
    if strikes is None:
        strikes = {"aggressive": 845.0, "natural": 820.0, "conservative": 795.0}
    idx = pd.bdate_range(end="2024-06-28", periods=130)
    closes = 800.0 + np.arange(130, dtype=float) * 0.5
    ohlcv = pd.DataFrame(
        {"Open": closes, "High": closes + 1.0, "Low": closes - 1.0, "Close": closes},
        index=idx,
    )
    return ChartPayload(
        ticker="TEST",
        currency="USD",
        ohlcv=ohlcv,
        sma_200w=pd.Series(820.0, index=idx),
        ema_200d=pd.Series(810.0, index=idx),
        sma_50d=pd.Series(795.0, index=idx),
        zone_lower=zone_lower,
        zone_upper=zone_upper,
        spot=850.0,
        strikes=strikes,
    )


# --- build_chart_payload ---


def test_build_chart_payload_returns_none_when_ohlcv_missing(monkeypatch):
    monkeypatch.setattr(chart, "read_ohlcv_raw", lambda *a, **kw: None)
    assert build_chart_payload(_detail_with_zone(), months=6) is None


def test_build_chart_payload_truncates_to_months(monkeypatch, large_ohlcv):
    monkeypatch.setattr(chart, "read_ohlcv_raw", lambda *a, **kw: large_ohlcv)
    payload = build_chart_payload(_detail_with_zone(), months=6)
    assert payload is not None
    # 6 meses calendario ≈ 130 ± 5 business days
    assert 120 <= len(payload.ohlcv) <= 135


def test_build_chart_payload_computes_full_series_then_truncates(monkeypatch, large_ohlcv):
    monkeypatch.setattr(chart, "read_ohlcv_raw", lambda *a, **kw: large_ohlcv)
    payload = build_chart_payload(_detail_with_zone(), months=3)
    assert payload is not None
    # SMA200W truncada a 3 meses debe tener valores NO-NaN al inicio del rango mostrado
    # (calculada sobre los 1500 días completos antes de truncar; si hubiera sido sobre
    # los 65 bdays del rango mostrado, todas las filas serían NaN porque no llega a 200 weeks).
    assert pd.notna(payload.sma_200w.iloc[0])


def test_build_chart_payload_includes_zone_bounds_when_present(monkeypatch, large_ohlcv):
    monkeypatch.setattr(chart, "read_ohlcv_raw", lambda *a, **kw: large_ohlcv)
    payload = build_chart_payload(_detail_with_zone(), months=6)
    assert payload.zone_lower == 810.0
    assert payload.zone_upper == 830.0


def test_build_chart_payload_zone_bounds_none_when_no_best_zone(monkeypatch, large_ohlcv):
    monkeypatch.setattr(chart, "read_ohlcv_raw", lambda *a, **kw: large_ohlcv)
    payload = build_chart_payload(_detail_without_zone(), months=6)
    assert payload.zone_lower is None
    assert payload.zone_upper is None


# --- build_plotly_figure ---


def test_build_plotly_figure_has_candlestick_trace():
    fig = build_plotly_figure(_payload())
    candlestick_traces = [t for t in fig.data if t.type == "candlestick"]
    assert len(candlestick_traces) == 1
    assert candlestick_traces[0].name == "TEST"


def test_build_plotly_figure_has_three_ma_traces():
    fig = build_plotly_figure(_payload())
    line_traces = [t for t in fig.data if getattr(t, "mode", None) == "lines"]
    found = {t.name for t in line_traces}
    assert found == {"SMA200W", "EMA200D", "SMA50D"}


def test_build_plotly_figure_adds_zone_band_when_zone_present():
    fig = build_plotly_figure(_payload())
    rects = [s for s in fig.layout.shapes if s.type == "rect"]
    assert len(rects) == 1
    assert rects[0].y0 == 810.0
    assert rects[0].y1 == 830.0


def test_build_plotly_figure_skips_zone_band_when_zone_none():
    fig = build_plotly_figure(_payload(zone_lower=None, zone_upper=None))
    rects = [s for s in fig.layout.shapes if s.type == "rect"]
    assert len(rects) == 0


def test_build_plotly_figure_adds_strike_lines():
    fig = build_plotly_figure(_payload())
    # 1 hline de spot + 3 hlines de strikes = 4 líneas
    lines = [s for s in fig.layout.shapes if s.type == "line"]
    assert len(lines) == 4


def test_build_plotly_figure_skips_none_strikes():
    strikes = {"aggressive": None, "natural": 820.0, "conservative": None}
    fig = build_plotly_figure(_payload(strikes=strikes))
    # 1 hline de spot + 1 hline de natural = 2 líneas
    lines = [s for s in fig.layout.shapes if s.type == "line"]
    assert len(lines) == 2


def test_build_plotly_figure_layout_basics():
    fig = build_plotly_figure(_payload())
    assert fig.layout.height == 600
    assert fig.layout.hovermode == "x unified"
    assert fig.layout.xaxis.rangeslider.visible is False
