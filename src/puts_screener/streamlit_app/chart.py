"""Construcción del payload y figura Plotly para el chart de un candidato (spec 09 §X).

Función pura: no toca Streamlit. `build_chart_payload` lee OHLCV cacheado, recompone
las 3 MAs sobre la serie completa y trunca al periodo pedido. `build_plotly_figure`
construye un `go.Figure` declarativo con candlestick + 3 MAs + banda de zona + spot +
strikes. La presentación final (rendering en Streamlit) es responsabilidad de la vista
en Tanda 3.
"""

from dataclasses import dataclass

import pandas as pd
import plotly.graph_objects as go

from puts_screener.config_streamlit import (
    STREAMLIT_CANDLE_DECREASING,
    STREAMLIT_CANDLE_INCREASING,
    STREAMLIT_CHART_HEIGHT_PX,
    STREAMLIT_MA_COLORS,
    STREAMLIT_SPOT_LINE_COLOR,
    STREAMLIT_STRIKE_COLORS,
    STREAMLIT_ZONE_BAND_COLOR,
)
from puts_screener.formatting import format_price
from puts_screener.indicators import (
    ema_daily_series,
    sma_daily_series,
    sma_weekly_series,
)
from puts_screener.providers.cache import read_ohlcv_raw
from puts_screener.streamlit_app.models import CandidateDetail


@dataclass(frozen=True)
class ChartPayload:
    """Datos pre-calculados listos para el render del chart."""

    ticker: str
    currency: str
    ohlcv: pd.DataFrame
    sma_200w: pd.Series
    ema_200d: pd.Series
    sma_50d: pd.Series
    zone_lower: float | None
    zone_upper: float | None
    spot: float
    strikes: dict[str, float | None]


def build_chart_payload(detail: CandidateDetail, months: int) -> ChartPayload | None:
    """Lee OHLCV del cache, calcula las 3 MAs sobre la serie completa, trunca al periodo.

    Las MAs se calculan SIEMPRE sobre `ohlcv_full` (no sobre la ventana mostrada): así
    SMA200W tiene valores válidos desde el inicio del rango visible siempre que el cache
    tenga suficiente histórico.

    Args:
        detail: candidato con ticker, best_zone, spot, strikes y currency.
        months: cantidad de meses calendario hacia atrás desde el último cierre disponible.

    Returns:
        ChartPayload con OHLCV + 3 MAs alineadas al index diario, bounds y strikes.
        None si el parquet de OHLCV no existe (ticker no fue cacheado).
    """
    ohlcv_full = read_ohlcv_raw(detail.row.ticker, "1d")
    if ohlcv_full is None:
        return None

    # 1. Series completas sobre la serie original (sin truncar).
    sma_200w_weekly = sma_weekly_series(ohlcv_full, weeks=200)
    sma_200w_full = sma_200w_weekly.reindex(ohlcv_full.index, method="ffill")
    ema_200d_full = ema_daily_series(ohlcv_full, length=200)
    sma_50d_full = sma_daily_series(ohlcv_full, length=50)

    # 2. Truncar al periodo pedido.
    cutoff = ohlcv_full.index[-1] - pd.DateOffset(months=months)
    ohlcv = ohlcv_full[ohlcv_full.index >= cutoff]
    sma_200w = sma_200w_full[sma_200w_full.index >= cutoff]
    ema_200d = ema_200d_full[ema_200d_full.index >= cutoff]
    sma_50d = sma_50d_full[sma_50d_full.index >= cutoff]

    # 3. Bounds de la best_zone si existe.
    zone = detail.best_zone
    zone_lower = zone.lower_bound if zone is not None else None
    zone_upper = zone.upper_bound if zone is not None else None

    return ChartPayload(
        ticker=detail.row.ticker,
        currency=detail.row.currency,
        ohlcv=ohlcv,
        sma_200w=sma_200w,
        ema_200d=ema_200d,
        sma_50d=sma_50d,
        zone_lower=zone_lower,
        zone_upper=zone_upper,
        spot=detail.spot,
        strikes=detail.strikes,
    )


def build_plotly_figure(payload: ChartPayload) -> go.Figure:
    """Construye un `go.Figure` declarativo. Función pura, no toca Streamlit.

    Capas (de fondo a frente): candlestick, 3 MAs, banda de zona (rect),
    línea de spot (dotted), 3 strikes (dashed). Strikes con value None se saltean.
    """
    fig = go.Figure()

    fig.add_trace(
        go.Candlestick(
            x=payload.ohlcv.index,
            open=payload.ohlcv["Open"],
            high=payload.ohlcv["High"],
            low=payload.ohlcv["Low"],
            close=payload.ohlcv["Close"],
            name=payload.ticker,
            increasing_line_color=STREAMLIT_CANDLE_INCREASING,
            decreasing_line_color=STREAMLIT_CANDLE_DECREASING,
        )
    )

    for label, series in (
        ("SMA200W", payload.sma_200w),
        ("EMA200D", payload.ema_200d),
        ("SMA50D", payload.sma_50d),
    ):
        fig.add_trace(
            go.Scatter(
                x=series.index,
                y=series.values,
                mode="lines",
                line={"color": STREAMLIT_MA_COLORS[label], "width": 1.5},
                name=label,
            )
        )

    if payload.zone_lower is not None and payload.zone_upper is not None:
        fig.add_hrect(
            y0=payload.zone_lower,
            y1=payload.zone_upper,
            fillcolor=STREAMLIT_ZONE_BAND_COLOR,
            line_width=0,
            annotation_text="Zona",
            annotation_position="top left",
        )

    fig.add_hline(
        y=payload.spot,
        line_dash="dot",
        line_color=STREAMLIT_SPOT_LINE_COLOR,
        annotation_text=f"Spot {format_price(payload.spot, payload.currency)}",
        annotation_position="right",
    )

    for kind in ("aggressive", "natural", "conservative"):
        value = payload.strikes.get(kind)
        if value is None:
            continue
        fig.add_hline(
            y=value,
            line_dash="dash",
            line_color=STREAMLIT_STRIKE_COLORS[kind],
            annotation_text=f"{kind} {format_price(value, payload.currency)}",
            annotation_position="right",
        )

    fig.update_layout(
        height=STREAMLIT_CHART_HEIGHT_PX,
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
        title=f"{payload.ticker} ({payload.currency})",
        margin={"l": 40, "r": 40, "t": 50, "b": 40},
        showlegend=True,
    )

    return fig
