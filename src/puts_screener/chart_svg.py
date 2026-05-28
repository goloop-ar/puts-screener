"""Mini-chart SVG inline para las cards del HTML report (spec 07 §3.2 / §6.2).

Render server-side: precio diario de los últimos ~6 meses, banda de la zona de soporte
y los 3 strikes sugeridos como líneas punteadas. La línea de precio, el punto del spot
y los labels usan `currentColor`, así heredan el color del CSS de la card (funciona en
light y dark sin lógica extra). Función pura: no toca disco ni red.
"""

import pandas as pd

from puts_screener.config_reports import (
    MINI_CHART_COLOR_AGGRESSIVE,
    MINI_CHART_COLOR_CONSERVATIVE,
    MINI_CHART_COLOR_NATURAL,
    MINI_CHART_COLOR_ZONE,
    MINI_CHART_HEIGHT,
    MINI_CHART_LOOKBACK_DAYS,
    MINI_CHART_MIN_DAYS,
    MINI_CHART_PADDING_X,
    MINI_CHART_PADDING_Y,
    MINI_CHART_SPOT_RADIUS,
    MINI_CHART_WIDTH,
    MINI_CHART_Y_EXTRA_PCT,
)
from puts_screener.formatting import format_price
from puts_screener.models_reports import HeuristicStrikes

_MONTH_ABBR_ES: dict[int, str] = {
    1: "ene",
    2: "feb",
    3: "mar",
    4: "abr",
    5: "may",
    6: "jun",
    7: "jul",
    8: "ago",
    9: "sep",
    10: "oct",
    11: "nov",
    12: "dic",
}


def _format_y_label(value: float, currency: str) -> str:
    """Label del eje Y.

    Reusa `format_price` (spec 06) para que el prefijo/sufijo por divisa sea idéntico al
    resto del reporte ($ / € / £ / sufijo 'p' para GBp, etc.). Mantiene los 2 decimales de
    `format_price`; en pence eso da p.ej. "500.00p" (consistencia > brevedad).
    """
    return format_price(value, currency)


def _format_date_es(date: pd.Timestamp) -> str:
    """Fecha corta en español, p.ej. "12 mar" (mes manual para evitar el locale del CI)."""
    return f"{date.day} {_MONTH_ABBR_ES[date.month]}"


def render_mini_chart_svg(
    ohlcv_daily: pd.DataFrame,
    zone_lower_bound: float,
    zone_upper_bound: float,
    strikes: HeuristicStrikes,
    currency: str,
) -> str:
    """SVG inline con precio diario, banda de zona y 3 strikes punteados.

    Devuelve "" si len(ohlcv_daily) < MINI_CHART_MIN_DAYS o si el DataFrame
    es inválido (sin columna Close, span de precios = 0, etc.).

    Args:
        ohlcv_daily: OHLCV diario con índice de fechas y columna "Close".
        zone_lower_bound: borde inferior de la best_zone.
        zone_upper_bound: borde superior de la best_zone.
        strikes: strikes heurísticos a dibujar como líneas horizontales.
        currency: divisa para formatear los labels del eje Y.

    Returns:
        String SVG completo, o "" si no hay data suficiente o válida.
    """
    n = min(len(ohlcv_daily), MINI_CHART_LOOKBACK_DAYS)
    if n < MINI_CHART_MIN_DAYS or "Close" not in ohlcv_daily.columns:
        return ""

    closes = ohlcv_daily["Close"].tail(n).tolist()
    dates = ohlcv_daily.index[-n:]

    ys_all = closes + [
        zone_lower_bound,
        zone_upper_bound,
        strikes.aggressive,
        strikes.natural,
        strikes.conservative,
    ]
    y_min_raw, y_max_raw = min(ys_all), max(ys_all)
    span = y_max_raw - y_min_raw
    if span == 0:
        return ""
    y_min = y_min_raw - span * MINI_CHART_Y_EXTRA_PCT
    y_max = y_max_raw + span * MINI_CHART_Y_EXTRA_PCT

    w, h = MINI_CHART_WIDTH, MINI_CHART_HEIGHT
    px, py = MINI_CHART_PADDING_X, MINI_CHART_PADDING_Y
    plot_w = w - 2 * px
    plot_h = h - 2 * py

    def x(i: int) -> float:
        return px + (i / (n - 1)) * plot_w

    def y(p: float) -> float:
        return py + (1 - (p - y_min) / (y_max - y_min)) * plot_h

    aria = "Precio últimos 6 meses con zona de soporte y strikes sugeridos"
    parts: list[str] = [
        f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" '
        f'role="img" aria-label="{aria}">'
    ]

    # Banda de la zona de soporte (y(upper) < y(lower) porque el eje está invertido).
    parts.append(
        f'<rect x="{px:.1f}" y="{y(zone_upper_bound):.1f}" width="{plot_w:.1f}" '
        f'height="{y(zone_lower_bound) - y(zone_upper_bound):.1f}" '
        f'fill="{MINI_CHART_COLOR_ZONE}" fill-opacity="0.18"/>'
    )

    # Líneas horizontales de los 3 strikes (punteadas).
    for strike, color in (
        (strikes.aggressive, MINI_CHART_COLOR_AGGRESSIVE),
        (strikes.natural, MINI_CHART_COLOR_NATURAL),
        (strikes.conservative, MINI_CHART_COLOR_CONSERVATIVE),
    ):
        parts.append(
            f'<line x1="{px:.1f}" x2="{px + plot_w:.1f}" '
            f'y1="{y(strike):.1f}" y2="{y(strike):.1f}" '
            f'stroke="{color}" stroke-width="1.2" stroke-dasharray="3 3"/>'
        )

    # Polyline del precio.
    points = " ".join(f"{x(i):.1f},{y(c):.1f}" for i, c in enumerate(closes))
    parts.append(
        f'<polyline points="{points}" fill="none" stroke="currentColor" '
        f'stroke-width="1.4" opacity="0.85"/>'
    )

    # Punto destacado en el último close (spot).
    parts.append(
        f'<circle cx="{x(n - 1):.1f}" cy="{y(closes[-1]):.1f}" '
        f'r="{MINI_CHART_SPOT_RADIUS}" fill="currentColor"/>'
    )

    # Labels Y: máximo (arriba) y mínimo (abajo) en la esquina izquierda.
    parts.append(
        f'<text x="2" y="{py + 8:.1f}" font-size="8" fill="currentColor" opacity="0.55">'
        f"{_format_y_label(y_max_raw, currency)}</text>"
    )
    parts.append(
        f'<text x="2" y="{h - py:.1f}" font-size="8" fill="currentColor" opacity="0.55">'
        f"{_format_y_label(y_min_raw, currency)}</text>"
    )

    # Labels de fecha: primera fecha (izquierda) y "hoy" (derecha) en el borde inferior.
    parts.append(
        f'<text x="{px:.1f}" y="{h - 1:.1f}" font-size="8" fill="currentColor" opacity="0.45">'
        f"{_format_date_es(dates[0])}</text>"
    )
    parts.append(
        f'<text x="{px + plot_w:.1f}" y="{h - 1:.1f}" font-size="8" fill="currentColor" '
        f'opacity="0.45" text-anchor="end">hoy</text>'
    )

    parts.append("</svg>")
    return "\n".join(parts)
