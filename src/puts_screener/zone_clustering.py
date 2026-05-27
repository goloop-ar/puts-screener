"""Agrupamiento de SupportLevel en zonas de confluencia y scoring (§6 spec 03 + spec 06).

Spec 06: tolerance híbrida (min de ATR×factor y %spot), gate post-cluster por ancho máximo
absoluto, bounds = envelope real de los elementos (no ATR fijo), y multiplicador de densidad
sobre el score base (premia clusters compactos con muchos heavies, penaliza los anchos).
"""

from puts_screener.config_supports import (
    CLUSTERING_TOLERANCE_ATR,
    CLUSTERING_TOLERANCE_MAX_PCT,
    DENSITY_BONUS_SLOPE,
    DYNAMIC_CONFIRMERS,
    ELEMENT_WEIGHTS,
    HEAVY_ELEMENT_WEIGHT_THRESHOLD,
    MAX_DENSITY_MULTIPLIER,
    MIN_DENSITY_MULTIPLIER,
    MIN_WIDTH_FLOOR_PCT,
    REFERENCE_DENSITY,
    ZONE_BUFFER_PCT,
    ZONE_MAX_WIDTH_PCT,
)
from puts_screener.models_support import SupportLevel, SupportZone


def _element_category(element: str) -> str:
    """Categoría de dedup del elemento (sma_200/sma_50/fibonacci/avwap o el propio label)."""
    if element in ("sma_200w", "ema_200d", "sma_200d"):
        return "sma_200"
    if element in ("sma_50w", "sma_50d", "ema_50d"):
        return "sma_50"
    if element in ("fib_618", "fib_786"):
        return "fibonacci"
    if element.startswith("avwap_"):
        return "avwap"
    return element


def density_multiplier(n_heavy: int, width_pct: float) -> float:
    """Multiplicador de densidad del score (§6.2). Función pura, clipeada a [MIN, MAX].

    densidad = n_heavy / max(width_pct, floor). multiplier = 1 + (densidad - ref) * slope,
    clipeado a [MIN_DENSITY_MULTIPLIER, MAX_DENSITY_MULTIPLIER].
    """
    if n_heavy <= 0:
        return 1.0  # no debería pasar — el gate de heavy >= 2 lo evita
    width_floored = max(width_pct, MIN_WIDTH_FLOOR_PCT)
    density = n_heavy / width_floored
    multiplier = 1.0 + (density - REFERENCE_DENSITY) * DENSITY_BONUS_SLOPE
    return max(MIN_DENSITY_MULTIPLIER, min(multiplier, MAX_DENSITY_MULTIPLIER))


def compute_zone_score(
    elements: list[SupportLevel],
    *,
    zone_width_pct: float,
    n_heavy_elements: int,
) -> float:
    """Score ponderado con dedup por categoría × multiplicador de densidad (§6.2).

    score_base = suma del máximo peso (ELEMENT_WEIGHTS) por categoría presente. El resultado
    se multiplica por `density_multiplier(n_heavy_elements, zone_width_pct)`.
    """
    category_max_weight: dict[str, float] = {}
    for e in elements:
        cat = _element_category(e.element)
        weight = ELEMENT_WEIGHTS.get(e.element, 0.0)
        if weight > category_max_weight.get(cat, 0.0):
            category_max_weight[cat] = weight
    score_base = sum(category_max_weight.values())
    return score_base * density_multiplier(n_heavy_elements, zone_width_pct)


def _is_dynamic_confirmer(element: str) -> bool:
    """True si el elemento es confirmador dinámico (avwap/hvn/divergence)."""
    category = "avwap" if element.startswith("avwap_") else element
    return category in DYNAMIC_CONFIRMERS


def _count_heavy(elements: list[SupportLevel]) -> int:
    """Cantidad de elementos con peso >= HEAVY_ELEMENT_WEIGHT_THRESHOLD."""
    return sum(
        1 for e in elements if ELEMENT_WEIGHTS.get(e.element, 0.0) >= HEAVY_ELEMENT_WEIGHT_THRESHOLD
    )


def cluster_into_zones(levels: list[SupportLevel], spot: float, atr14: float) -> list[SupportZone]:
    """Agrupa niveles support en zonas (single-linkage, tolerance híbrida) y scorea (§6.1).

    Solo entran los `side == "support"`. `tolerance = min(ATR14×factor, spot×pct)`. Post-cluster,
    si el envelope (max-min) supera ZONE_MAX_WIDTH_PCT del centro, el cluster se descarta. Los
    bounds son el envelope real ± buffer cosmético; el center es el punto medio del envelope;
    `distance_pct` se mide contra `upper_bound` (borde superior real, no el centro).
    """
    eligible = sorted(
        (lvl for lvl in levels if lvl.side == "support"),
        key=lambda lvl: lvl.price,
    )
    if not eligible:
        return []

    tolerance = min(CLUSTERING_TOLERANCE_ATR * atr14, spot * CLUSTERING_TOLERANCE_MAX_PCT)
    clusters: list[list[SupportLevel]] = [[eligible[0]]]
    for lvl in eligible[1:]:
        if lvl.price - clusters[-1][-1].price > tolerance:
            clusters.append([lvl])
        else:
            clusters[-1].append(lvl)

    zones: list[SupportZone] = []
    for cluster in clusters:
        prices = [lvl.price for lvl in cluster]
        min_price, max_price = min(prices), max(prices)
        center = (min_price + max_price) / 2
        if center <= 0:
            continue
        # Gate: envelope crudo (sin buffer) más ancho que el máximo → se descarta el cluster.
        if (max_price - min_price) / center > ZONE_MAX_WIDTH_PCT:
            continue

        buffer = ZONE_BUFFER_PCT * center
        lower_bound = min_price - buffer
        upper_bound = max_price + buffer
        center_price = (lower_bound + upper_bound) / 2
        width_pct = (upper_bound - lower_bound) / center_price if center_price > 0 else 0.0
        n_heavy = _count_heavy(cluster)
        zones.append(
            SupportZone(
                center_price=center_price,
                lower_bound=lower_bound,
                upper_bound=upper_bound,
                score=compute_zone_score(
                    cluster, zone_width_pct=width_pct, n_heavy_elements=n_heavy
                ),
                elements=list(cluster),
                has_dynamic_confirmer=any(_is_dynamic_confirmer(lvl.element) for lvl in cluster),
                distance_pct=(spot - upper_bound) / spot,
            )
        )

    zones.sort(key=lambda z: (-z.score, z.distance_pct))
    return zones
