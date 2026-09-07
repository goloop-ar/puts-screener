"""Strikes estructurales anclados a elementos de soporte reales (spec 11 §3.3/§5/§6.5).

Variantes A/B/C sobre los `SupportLevel` "heavy" de la zona (`ELEMENT_WEIGHTS >=
HEAVY_ELEMENT_WEIGHT_THRESHOLD`). Variantes D/E/F (tanda 2, agregadas tras el primer backtest):
el backtest mostró que en A/B/C el `aggressive` queda anclado DENTRO de la zona, así que "el
precio entra a la zona" y "se perfora aggressive" son casi el mismo evento — D/E/F bajan los 3
niveles a o por debajo de `lower_bound` para separar ambos eventos. `compute_heuristic_strikes`
(strikes.py) NO se toca: sigue siendo el fallback cuando la zona no tiene anclas heavy, y la
línea de base del backtest.
"""

import logging
from math import floor

from puts_screener.config_reports import (
    STRUCTURAL_STRIKE_BUFFERS_ATR,
    STRUCTURAL_STRIKE_F_NATURAL_HEAVY_ATR,
    STRUCTURAL_STRIKE_F_NATURAL_LOWER_BOUND_ATR,
)
from puts_screener.config_supports import ELEMENT_WEIGHTS, HEAVY_ELEMENT_WEIGHT_THRESHOLD
from puts_screener.models_reports import StrikeVariant, StructuralStrikes
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


def _min_base_anchor(zone: SupportZone, heavy_lowest: SupportLevel) -> tuple[float, str]:
    """min(lower_bound, heavy_lowest.price) + la etiqueta de cuál de los dos ganó (E/F, y el
    conservative de C). En la práctica lower_bound siempre es <= heavy_lowest (lower_bound =
    min de TODOS los elementos del cluster - buffer, así que nunca puede superar al mínimo de
    solo el subconjunto heavy) — pero el min() se calcula igual por si ese invariante no se
    sostiene en zonas pre-gate."""
    if heavy_lowest.price <= zone.lower_bound:
        return heavy_lowest.price, heavy_lowest.element
    return zone.lower_bound, "zone_lower_bound"


def _fallback(
    zone: SupportZone,
    spot: float,
    atr_14: float,
    currency: str,
    variant: StrikeVariant,
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
    variant: StrikeVariant = "A",
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
    anchor_kind: str

    if variant == "A":
        conservative_raw = heavy_lowest.price - buffers["conservative"] * atr_14
        conservative_anchor = heavy_lowest.element
        natural_raw = zone.lower_bound - buffers["natural"] * atr_14
        aggressive_raw = heavy_highest.price - buffers["aggressive"] * atr_14
        aggressive_anchor = heavy_highest.element
        anchor_kind = "heavy_element"
    elif variant == "B":
        conservative_raw = heavy_lowest.price - buffers["conservative"] * atr_14
        conservative_anchor = heavy_lowest.element
        natural_raw = heavy_lowest.price - buffers["natural"] * atr_14
        aggressive_raw = heavy_highest.price - buffers["aggressive"] * atr_14
        aggressive_anchor = heavy_highest.element
        anchor_kind = "heavy_element"
    elif variant == "C":  # híbrido zona/heavy
        conservative_base, conservative_anchor = _min_base_anchor(zone, heavy_lowest)
        conservative_raw = conservative_base - buffers["conservative"] * atr_14
        natural_raw = zone.lower_bound - buffers["natural"] * atr_14
        aggressive_raw = zone.center_price - buffers["aggressive"] * atr_14
        aggressive_anchor = "zone_center_price"
        anchor_kind = "zone_bound"
    elif variant == "D":  # escalonado por ATR desde lower_bound, sin usar heavy
        conservative_raw = zone.lower_bound - buffers["conservative"] * atr_14
        natural_raw = zone.lower_bound - buffers["natural"] * atr_14
        aggressive_raw = zone.lower_bound - buffers["aggressive"] * atr_14
        conservative_anchor = "zone_lower_bound"
        aggressive_anchor = "zone_lower_bound"
        anchor_kind = "zone_bound"
    elif variant == "E":  # anclado a min(lower_bound, heavy_lowest), los 3 niveles
        base, base_anchor = _min_base_anchor(zone, heavy_lowest)
        conservative_raw = base - buffers["conservative"] * atr_14
        natural_raw = base - buffers["natural"] * atr_14
        aggressive_raw = base - buffers["aggressive"] * atr_14
        conservative_anchor = base_anchor
        aggressive_anchor = base_anchor
        anchor_kind = "heavy_element" if base_anchor != "zone_lower_bound" else "zone_bound"
    else:  # "F" — híbrido zona/heavy con piso duro; natural es un min de dos anclas distintas
        base, base_anchor = _min_base_anchor(zone, heavy_lowest)
        conservative_raw = base - buffers["conservative"] * atr_14
        aggressive_raw = base - buffers["aggressive"] * atr_14
        natural_raw = min(
            zone.lower_bound - STRUCTURAL_STRIKE_F_NATURAL_LOWER_BOUND_ATR * atr_14,
            heavy_lowest.price - STRUCTURAL_STRIKE_F_NATURAL_HEAVY_ATR * atr_14,
        )
        conservative_anchor = base_anchor
        aggressive_anchor = base_anchor
        anchor_kind = "heavy_element" if base_anchor != "zone_lower_bound" else "zone_bound"

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
