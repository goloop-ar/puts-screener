"""Tests del mini-chart SVG (spec 07 §8.2). Funciones puras, DataFrames sintéticos."""

import numpy as np
import pandas as pd

from puts_screener.chart_svg import render_mini_chart_svg
from puts_screener.models_reports import HeuristicStrikes


def _make_ohlcv(n_days: int, base_price: float = 100.0) -> pd.DataFrame:
    dates = pd.date_range(end="2026-05-26", periods=n_days, freq="B")
    closes = base_price + np.linspace(0, 5, n_days)
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes * 1.01,
            "Low": closes * 0.99,
            "Close": closes,
            "Volume": [1_000_000] * n_days,
        },
        index=dates,
    )


def _make_strikes(aggressive=98.0, natural=94.0, conservative=91.0, grid_unit=1.0):
    return HeuristicStrikes(aggressive, natural, conservative, grid_unit)


def _points_attr(svg: str) -> str:
    start = svg.index('points="') + len('points="')
    end = svg.index('"', start)
    return svg[start:end]


def test_render_chart_typical():
    svg = render_mini_chart_svg(_make_ohlcv(180), 93.0, 95.0, _make_strikes(), "USD")
    assert svg.startswith("<svg")
    assert 'viewBox="0 0 480 200"' in svg
    assert svg.count("<polyline") == 1
    assert svg.count("<line ") == 3
    assert svg.count("<rect") == 1
    assert svg.count("<circle") == 1
    assert svg.count("stroke-dasharray") >= 3


def test_render_chart_short_history():
    svg = render_mini_chart_svg(_make_ohlcv(50), 93.0, 95.0, _make_strikes(), "USD")
    assert svg != ""
    assert len(_points_attr(svg).split(" ")) == 50


def test_render_chart_insufficient():
    assert render_mini_chart_svg(_make_ohlcv(20), 93.0, 95.0, _make_strikes(), "USD") == ""


def test_render_chart_empty_ohlcv():
    assert render_mini_chart_svg(pd.DataFrame(), 93.0, 95.0, _make_strikes(), "USD") == ""


def test_render_chart_y_labels_currency_usd():
    svg = render_mini_chart_svg(_make_ohlcv(180), 93.0, 95.0, _make_strikes(), "USD")
    assert "$" in svg


def test_render_chart_y_labels_currency_gbp_pence():
    svg = render_mini_chart_svg(
        _make_ohlcv(180, base_price=500.0),
        490.0,
        510.0,
        _make_strikes(520.0, 500.0, 480.0, 50.0),
        "GBp",
    )
    assert "p" in svg
    assert "$" not in svg


def test_render_chart_strike_lines_dashed():
    svg = render_mini_chart_svg(_make_ohlcv(180), 93.0, 95.0, _make_strikes(), "USD")
    assert svg.count("stroke-dasharray") == 3
