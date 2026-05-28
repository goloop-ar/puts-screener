"""Strikes heurísticos sugeridos por candidato (spec 07 §5-§6).

Tres strikes (aggressive/natural/conservative) anclados a la zona de soporte, con el ATR
como unidad de separación mínima y redondeo a la grilla típica del exchange según divisa.
Funciones puras: no consultan cadena de opciones ni validan yield.
"""

from math import floor, log10

from puts_screener.config_reports import (
    STRIKE_ATR_MULTIPLIER,
    STRIKE_GRID_CHF,
    STRIKE_GRID_EUR,
    STRIKE_GRID_FALLBACK_PCT,
    STRIKE_GRID_GBP,
    STRIKE_GRID_GBP_PENCE,
    STRIKE_GRID_USD,
)
from puts_screener.models_reports import HeuristicStrikes

_GRID_BY_CURRENCY: dict[str, tuple[tuple[float, float], ...]] = {
    "USD": STRIKE_GRID_USD,
    "EUR": STRIKE_GRID_EUR,
    "CHF": STRIKE_GRID_CHF,
    "GBP": STRIKE_GRID_GBP,
    "GBp": STRIKE_GRID_GBP_PENCE,
}


def _fallback_grid(spot: float) -> float:
    if spot <= 0:
        return 0.01
    raw = spot * STRIKE_GRID_FALLBACK_PCT
    magnitude = 10 ** floor(log10(raw))
    return round(raw / magnitude) * magnitude


def _grid_for_currency(currency: str, spot: float) -> float:
    table = _GRID_BY_CURRENCY.get(currency)
    if table is None:
        return _fallback_grid(spot)
    for threshold, grid in table:
        # Techo inclusivo: el spot en el límite cae en la grilla más fina (ej. 100 → 1.0).
        if spot <= threshold:
            return grid
    return table[-1][1]  # defensive: la última fila siempre tiene threshold inf


def _round_to_grid(value: float, grid_unit: float) -> float:
    # round-half-up determinista; evita el banker's rounding de round() en .5 exactos.
    return floor(value / grid_unit + 0.5) * grid_unit


def compute_heuristic_strikes(
    zone_lower_bound: float,
    zone_upper_bound: float,
    zone_center_price: float,
    spot: float,
    atr_14: float,
    currency: str,
) -> HeuristicStrikes:
    """Computa los tres strikes sugeridos anclados a la zona.

    Args:
        zone_lower_bound: borde inferior de la best_zone.
        zone_upper_bound: borde superior de la best_zone.
        zone_center_price: centro del envelope de la zona.
        spot: precio actual del subyacente.
        atr_14: ATR de 14 períodos, unidad de separación mínima.
        currency: código de divisa para elegir la grilla del exchange.

    Returns:
        HeuristicStrikes con los tres strikes redondeados a grilla y el grid_unit usado.
    """
    grid = _grid_for_currency(currency, spot)
    aggressive_raw = max(zone_upper_bound, spot - atr_14 * STRIKE_ATR_MULTIPLIER)
    natural_raw = zone_center_price
    conservative_raw = zone_lower_bound - atr_14 * STRIKE_ATR_MULTIPLIER
    return HeuristicStrikes(
        aggressive=_round_to_grid(aggressive_raw, grid),
        natural=_round_to_grid(natural_raw, grid),
        conservative=_round_to_grid(conservative_raw, grid),
        grid_unit=grid,
    )
