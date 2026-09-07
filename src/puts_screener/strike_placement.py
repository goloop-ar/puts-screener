"""Strikes estructurales anclados a elementos de soporte reales (spec 11 §3.3/§5/§6.5).

Tres variantes candidatas (A/B/C) sobre los `SupportLevel` "heavy" de la zona
(`ELEMENT_WEIGHTS >= HEAVY_ELEMENT_WEIGHT_THRESHOLD`). `compute_heuristic_strikes` (strikes.py)
NO se toca: sigue siendo el fallback cuando la zona no tiene anclas heavy, y la línea de base
del backtest de la tanda 2.
"""

import logging
from math import floor
from typing import Literal

from puts_screener.config_reports import STRUCTURAL_STRIKE_BUFFERS_ATR
from puts_screener.config_supports import ELEMENT_WEIGHTS, HEAVY_ELEMENT_WEIGHT_THRESHOLD
from puts_screener.models_reports import StructuralStrikes
from puts_screener.models_support import SupportLevel, SupportZone
from puts_screener.strikes import _grid_for_currency, compute_heuristic_strikes

logger = logging.getLogger(__name__)


def extract_heavy_anchors(zone: SupportZone) -> list[SupportLevel]:
    """Devuelve los SupportLevel de la zona con ELEMENT_WEIGHTS >= 2.5, ordenados por precio."""
    heavy = [
        e
        for e in zone.elements
        if ELEMENT_WEIGHTS.get(e.element, 0.0) >= HEAVY_ELEMENT_WEIGHT_THRESHOLD
    ]
    return sorted(heavy, key=lambda e: e.price)


def _floor_to_grid(value: float, grid_unit: float) -> float:
    # +1e-9: un valor exactamente sobre la grilla no debe caer al escalón anterior por error
    # de punto flotante (ej. 99.999999999997 en vez de 100.0).
    return floor(value / grid_unit + 1e-9) * grid_unit


def _enforce_order(
    conservative: float, natural: float, aggressive: float, spot: float, grid_unit: float
) -> tuple[float, float, float]:
    """Fuerza conservative < natural < aggressive < spot bajando el nivel más agresivo de cada
    par en conflicto (D11.7: hacia abajo siempre es conservador, nunca se sube un nivel)."""
    while aggressive >= spot:
        aggressive -= grid_unit
    while natural >= aggressive:
        natural -= grid_unit
    while conservative >= natural:
        conservative -= grid_unit
    return conservative, natural, aggressive


def _fallback(
    zone: SupportZone,
    spot: float,
    atr_14: float,
    currency: str,
    variant: Literal["A", "B", "C"],
) -> StructuralStrikes:
    heuristic = compute_heuristic_strikes(
        zone.lower_bound, zone.upper_bound, zone.center_price, spot, atr_14, currency
    )
    return StructuralStrikes(
        aggressive=heuristic.aggressive,
        natural=heuristic.natural,
        conservative=heuristic.conservative,
        grid_unit=heuristic.grid_unit,
        anchor_kind="fallback_atr",
        aggressive_anchor=None,
        conservative_anchor=None,
        variant=variant,
    )


def compute_structural_strikes(
    zone: SupportZone,
    spot: float,
    atr_14: float,
    currency: str,
    *,
    variant: Literal["A", "B", "C"] = "A",
) -> StructuralStrikes:
    """Calcula los 3 strikes anclados a los elementos heavy de la zona (spec 11 §6.5).

    Sin anclas heavy (no debería ocurrir post-gate MIN_HEAVY_ELEMENTS=2, pero las zonas
    pre-gate pueden carecer de ellas) cae a `compute_heuristic_strikes`, anchor_kind="fallback_atr".
    """
    anchors = extract_heavy_anchors(zone)
    if not anchors:
        return _fallback(zone, spot, atr_14, currency, variant)

    heavy_lowest = anchors[0]
    heavy_highest = anchors[-1]
    buffers = STRUCTURAL_STRIKE_BUFFERS_ATR[variant]

    conservative_anchor: str | None
    aggressive_anchor: str | None

    if variant == "A":
        conservative_raw = heavy_lowest.price - buffers["conservative"] * atr_14
        conservative_anchor = heavy_lowest.element
        natural_raw = zone.lower_bound - buffers["natural"] * atr_14
        aggressive_raw = heavy_highest.price - buffers["aggressive"] * atr_14
        aggressive_anchor = heavy_highest.element
        anchor_kind: Literal["heavy_element", "zone_bound", "fallback_atr"] = "heavy_element"
    elif variant == "B":
        conservative_raw = heavy_lowest.price - buffers["conservative"] * atr_14
        conservative_anchor = heavy_lowest.element
        natural_raw = heavy_lowest.price - buffers["natural"] * atr_14
        aggressive_raw = heavy_highest.price - buffers["aggressive"] * atr_14
        aggressive_anchor = heavy_highest.element
        anchor_kind = "heavy_element"
    else:  # "C" — híbrido zona/heavy
        if heavy_lowest.price <= zone.lower_bound:
            conservative_anchor = heavy_lowest.element
            conservative_base = heavy_lowest.price
        else:
            conservative_anchor = "zone_lower_bound"
            conservative_base = zone.lower_bound
        conservative_raw = conservative_base - buffers["conservative"] * atr_14
        natural_raw = zone.lower_bound - buffers["natural"] * atr_14
        aggressive_raw = zone.center_price - buffers["aggressive"] * atr_14
        aggressive_anchor = "zone_center_price"
        anchor_kind = "zone_bound"

    grid_unit = _grid_for_currency(currency, spot)
    conservative = _floor_to_grid(conservative_raw, grid_unit)
    natural = _floor_to_grid(natural_raw, grid_unit)
    aggressive = _floor_to_grid(aggressive_raw, grid_unit)

    conservative, natural, aggressive = _enforce_order(
        conservative, natural, aggressive, spot, grid_unit
    )

    if conservative <= 0:
        logger.warning(
            "Zona sin strikes estructurales computables (conservative<=0 tras enforcement de "
            "orden): variant=%s spot=%s atr_14=%s currency=%s",
            variant,
            spot,
            atr_14,
            currency,
        )
        return _fallback(zone, spot, atr_14, currency, variant)

    return StructuralStrikes(
        aggressive=aggressive,
        natural=natural,
        conservative=conservative,
        grid_unit=grid_unit,
        anchor_kind=anchor_kind,
        aggressive_anchor=aggressive_anchor,
        conservative_anchor=conservative_anchor,
        variant=variant,
    )
