"""Agrupamiento de SupportLevel en zonas de confluencia y scoring (§6 de la spec 03).

Los elementos cercanos (≤ 0.5×ATR14) se agrupan en una `SupportZone`. El score suma
puntos con dedup por categoría: un elemento de la misma categoría suma como máximo una vez
por zona (SMA200 vale 2, el resto 1).
"""

import statistics

from puts_screener.config_supports import (
    CLUSTERING_TOLERANCE_ATR,
    DYNAMIC_CONFIRMERS,
    SCORE_OTHER_ELEMENT_POINTS,
    SCORE_SMA200_POINTS,
    ZONE_WIDTH_ATR_MULTIPLIER,
)
from puts_screener.models_support import SupportLevel, SupportZone

# Margen del 2% por arriba del spot: descarta elementos muy lejos por arriba antes de
# clusterizar (§6.1 paso 2). El filtro fino de proximidad lo aplica §7 después.
_SPOT_UPPER_MARGIN = 1.02


def compute_zone_score(elements: list[SupportLevel]) -> int:
    """Score de confluencia con dedup por categoría (§6.3, verbatim de la spec)."""
    categories_present = set()
    for e in elements:
        if e.element in ("sma_200w", "sma_200d"):
            categories_present.add("sma_200")
        elif e.element in ("fib_618", "fib_786"):
            categories_present.add("fibonacci")
        elif e.element.startswith("avwap_"):
            categories_present.add("avwap")
        else:
            categories_present.add(e.element)

    score = 0
    for cat in categories_present:
        score += SCORE_SMA200_POINTS if cat == "sma_200" else SCORE_OTHER_ELEMENT_POINTS
    return score


def _is_dynamic_confirmer(element: str) -> bool:
    """True si el elemento pertenece a una categoría confirmadora dinámica (avwap/hvn/divergence).

    Mapea las sub-variantes de AVWAP a su categoría "avwap" antes de chequear contra
    DYNAMIC_CONFIRMERS — el pseudocódigo literal de §6.1 no lo hace, pero el intent del SOP
    es que cualquier AVWAP cuente como confirmador.
    """
    category = "avwap" if element.startswith("avwap_") else element
    return category in DYNAMIC_CONFIRMERS


def cluster_into_zones(
    levels: list[SupportLevel], atr14_today: float, spot: float
) -> list[SupportZone]:
    """Agrupa levels en zonas, scorea cada una y las ordena (score desc, distance asc)."""
    eligible = sorted(
        (lvl for lvl in levels if lvl.price < spot * _SPOT_UPPER_MARGIN),
        key=lambda lvl: lvl.price,
    )
    if not eligible:
        return []

    tolerance = CLUSTERING_TOLERANCE_ATR * atr14_today
    clusters: list[list[SupportLevel]] = [[eligible[0]]]
    for lvl in eligible[1:]:
        if lvl.price - clusters[-1][-1].price <= tolerance:
            clusters[-1].append(lvl)
        else:
            clusters.append([lvl])

    half_width = ZONE_WIDTH_ATR_MULTIPLIER * atr14_today
    zones: list[SupportZone] = []
    for cluster in clusters:
        center = float(statistics.median([lvl.price for lvl in cluster]))
        zones.append(
            SupportZone(
                center_price=center,
                lower_bound=center - half_width,
                upper_bound=center + half_width,
                score=compute_zone_score(cluster),
                elements=list(cluster),
                has_dynamic_confirmer=any(_is_dynamic_confirmer(lvl.element) for lvl in cluster),
                distance_pct=(spot - center) / spot,
            )
        )

    zones.sort(key=lambda z: (-z.score, z.distance_pct))
    return zones
