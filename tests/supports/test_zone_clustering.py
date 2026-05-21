"""Tests del clustering de zonas y scoring con dedup por categoría (spec 03 §6)."""

from puts_screener.models_support import SupportLevel
from puts_screener.zone_clustering import cluster_into_zones, compute_zone_score

ATR = 1.0  # tolerancia de cluster = 0.5×ATR = 0.5; ancho de zona = ±0.5
SPOT = 120.0


def _level(price, element, points=1):
    return SupportLevel(price=price, element=element, points=points)


# --- separación de clusters ---


def test_far_apart_levels_form_separate_zones():
    levels = [_level(100.0, "hvn"), _level(110.0, "polarity")]
    zones = cluster_into_zones(levels, ATR, SPOT)
    assert len(zones) == 2
    assert {z.score for z in zones} == {1}


def test_close_levels_form_single_zone():
    """Elementos a ≤ 0.5×ATR → mismo cluster."""
    levels = [_level(100.0, "hvn"), _level(100.3, "polarity")]
    zones = cluster_into_zones(levels, ATR, SPOT)
    assert len(zones) == 1
    assert len(zones[0].elements) == 2


# --- dedup por categoría ---


def test_dedup_sma200_counts_two_not_four():
    levels = [_level(100.0, "sma_200w", points=2), _level(100.2, "sma_200d", points=2)]
    zones = cluster_into_zones(levels, ATR, SPOT)
    assert len(zones) == 1
    assert zones[0].score == 2  # categoría sma_200 una sola vez (no 4)


def test_dedup_fibonacci_counts_one_not_two():
    levels = [_level(100.0, "fib_618"), _level(100.3, "fib_786")]
    zones = cluster_into_zones(levels, ATR, SPOT)
    assert len(zones) == 1
    assert zones[0].score == 1


def test_dedup_avwap_counts_one_not_three():
    levels = [
        _level(100.0, "avwap_pivot_low"),
        _level(100.2, "avwap_earnings"),
        _level(100.4, "avwap_52w_high"),
    ]
    zones = cluster_into_zones(levels, ATR, SPOT)
    assert len(zones) == 1
    assert zones[0].score == 1
    assert zones[0].has_dynamic_confirmer is True


def test_mixed_confluence_scores_five():
    """SMA200 (2) + fib (1) + AVWAP (1) + HVN (1) en la misma zona = 5."""
    levels = [
        _level(100.0, "sma_200w", points=2),
        _level(100.2, "fib_618"),
        _level(100.4, "avwap_pivot_low"),
        _level(100.5, "hvn"),
    ]
    zones = cluster_into_zones(levels, ATR, SPOT)
    assert len(zones) == 1
    assert zones[0].score == 5
    assert zones[0].has_dynamic_confirmer is True


# --- filtro de spot ---


def test_levels_above_spot_margin_ignored():
    """Elemento con price > spot×1.02 se descarta antes de clusterizar."""
    levels = [_level(95.0, "hvn"), _level(103.0, "polarity")]  # spot=100 → 102 es el techo
    zones = cluster_into_zones(levels, ATR, spot=100.0)
    assert len(zones) == 1
    assert zones[0].center_price == 95.0
    all_elements = [e.element for z in zones for e in z.elements]
    assert "polarity" not in all_elements


# --- ordenamiento ---


def test_zones_sorted_by_score_desc():
    levels = [
        # zona lejana con score 5
        _level(90.0, "sma_200w", points=2),
        _level(90.2, "fib_618"),
        _level(90.4, "avwap_pivot_low"),
        _level(90.5, "hvn"),
        # zona cercana con score 3
        _level(110.0, "hvn"),
        _level(110.3, "polarity"),
        _level(110.5, "gap_unfilled"),
    ]
    zones = cluster_into_zones(levels, ATR, SPOT)
    assert len(zones) == 2
    assert zones[0].score == 5
    assert zones[0].center_price < 100.0  # la de score 5 va primera pese a estar más lejos


def test_zones_same_score_sorted_by_distance():
    """Mismo score → la más cercana al spot primero."""
    levels = [_level(100.0, "hvn"), _level(110.0, "hvn")]
    zones = cluster_into_zones(levels, ATR, SPOT)
    assert len(zones) == 2
    assert zones[0].center_price == 110.0  # más cerca de spot=120
    assert zones[1].center_price == 100.0


# --- compute_zone_score directo ---


def test_compute_zone_score_dedup_across_categories():
    elements = [
        _level(100.0, "sma_200w", points=2),
        _level(100.0, "sma_200d", points=2),  # misma categoría → no duplica
        _level(100.0, "fib_618"),
        _level(100.0, "fib_786"),  # misma categoría → no duplica
        _level(100.0, "divergence"),
    ]
    assert compute_zone_score(elements) == 2 + 1 + 1  # sma_200 + fibonacci + divergence
