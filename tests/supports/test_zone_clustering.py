"""Tests del clustering de zonas y scoring con dedup por categoría (spec 03 §6)."""

from puts_screener.models_support import SupportLevel
from puts_screener.zone_clustering import cluster_into_zones, compute_zone_score

ATR = 1.0  # tolerancia de cluster = 0.5×ATR = 0.5; ancho de zona = ±0.5
SPOT = 120.0


def _level(price, element, points=1, side="support"):
    return SupportLevel(price=price, element=element, points=points, side=side)


# --- separación de clusters ---


def test_far_apart_levels_form_separate_zones():
    levels = [_level(100.0, "hvn"), _level(110.0, "polarity")]
    zones = cluster_into_zones(levels, ATR, SPOT)
    assert len(zones) == 2
    assert {z.score for z in zones} == {2.0, 3.0}  # hvn=2.0, polarity=3.0


def test_close_levels_form_single_zone():
    """Elementos a ≤ 0.5×ATR → mismo cluster."""
    levels = [_level(100.0, "hvn"), _level(100.3, "polarity")]
    zones = cluster_into_zones(levels, ATR, SPOT)
    assert len(zones) == 1
    assert len(zones[0].elements) == 2


# --- dedup por categoría ---


def test_dedup_sma200_uses_max_weight():
    """SMA200W (3.0) + EMA200D (2.5) → categoría sma_200 aporta el máximo (3.0), no 5.5."""
    levels = [_level(100.0, "sma_200w"), _level(100.2, "ema_200d")]
    zones = cluster_into_zones(levels, ATR, SPOT)
    assert len(zones) == 1
    assert zones[0].score == 3.0


def test_dedup_fibonacci_fib618_weight():
    """FIB_618 (1.5) + FIB_786 (0.0) → categoría fibonacci aporta 1.5."""
    levels = [_level(100.0, "fib_618"), _level(100.3, "fib_786")]
    zones = cluster_into_zones(levels, ATR, SPOT)
    assert len(zones) == 1
    assert zones[0].score == 1.5


def test_dedup_avwap_max_weight():
    levels = [
        _level(100.0, "avwap_pivot_low"),
        _level(100.2, "avwap_earnings"),
        _level(100.4, "avwap_52w_high"),
    ]
    zones = cluster_into_zones(levels, ATR, SPOT)
    assert len(zones) == 1
    assert zones[0].score == 2.5  # max(2.5, 2.5, 2.0)
    assert zones[0].has_dynamic_confirmer is True


def test_mixed_confluence_weighted_score():
    """SMA200 (3.0) + fib_618 (1.5) + AVWAP (2.5) + HVN (2.0) = 9.0."""
    levels = [
        _level(100.0, "sma_200w"),
        _level(100.2, "fib_618"),
        _level(100.4, "avwap_pivot_low"),
        _level(100.5, "hvn"),
    ]
    zones = cluster_into_zones(levels, ATR, SPOT)
    assert len(zones) == 1
    assert zones[0].score == 9.0
    assert zones[0].has_dynamic_confirmer is True


def test_dedup_sma200_three_labels_max_weight():
    """SMA200W (3.0) + EMA200D (2.5) + SMA200D (3.0) → categoría sma_200 = 3.0."""
    levels = [
        _level(100.0, "sma_200w"),
        _level(100.1, "ema_200d"),
        _level(100.2, "sma_200d"),
    ]
    zones = cluster_into_zones(levels, ATR, SPOT)
    assert len(zones) == 1
    assert zones[0].score == 3.0


def test_dedup_sma50_three_labels_max_weight():
    """SMA50D (2.5) + SMA50W (2.0) + EMA50D (1.5) → categoría sma_50 = 2.5."""
    levels = [
        _level(100.0, "sma_50w"),
        _level(100.1, "sma_50d"),
        _level(100.2, "ema_50d"),
    ]
    zones = cluster_into_zones(levels, ATR, SPOT)
    assert len(zones) == 1
    assert zones[0].score == 2.5


def test_sma200_plus_sma50_plus_confirmer_weighted():
    """SMA200 (3.0) + SMA50 (2.5) + HVN (2.0) = 7.5."""
    levels = [
        _level(100.0, "sma_200w"),
        _level(100.2, "sma_50d"),
        _level(100.4, "hvn"),
    ]
    zones = cluster_into_zones(levels, ATR, SPOT)
    assert len(zones) == 1
    assert zones[0].score == 7.5
    assert zones[0].has_dynamic_confirmer is True


def test_divergence_does_not_add_to_score():
    """DIVERGENCIA (0.0) + HVN (2.0) + POLARIDAD (3.0) = 5.0; la divergencia no suma."""
    levels = [_level(100.0, "divergence"), _level(100.2, "hvn"), _level(100.4, "polarity")]
    zones = cluster_into_zones(levels, ATR, SPOT)
    assert len(zones) == 1
    assert zones[0].score == 5.0


def test_single_element_zone_scores_its_weight():
    levels = [_level(100.0, "hvn")]
    zones = cluster_into_zones(levels, ATR, SPOT)
    assert len(zones) == 1
    assert zones[0].score == 2.0


def test_unknown_element_contributes_zero():
    """Un label desconocido no aporta al score y no rompe."""
    assert compute_zone_score([_level(100.0, "no_existe")]) == 0.0
    mixed = [_level(100.0, "hvn"), _level(100.1, "no_existe")]
    assert compute_zone_score(mixed) == 2.0


# --- filtro por side (support vs resistance) ---


def test_resistance_side_levels_excluded():
    """Un nivel con side='resistance' (precio ≥ spot) se descarta antes de clusterizar."""
    levels = [_level(95.0, "hvn"), _level(103.0, "polarity", side="resistance")]
    zones = cluster_into_zones(levels, ATR, spot=100.0)
    assert len(zones) == 1
    assert zones[0].center_price == 95.0
    all_elements = [e.element for z in zones for e in z.elements]
    assert "polarity" not in all_elements


def test_only_support_side_levels_clustered():
    """De una mezcla mitad support / mitad resistance, solo los support entran al cluster."""
    levels = [
        _level(95.0, "hvn", side="support"),
        _level(96.0, "fib_618", side="support"),
        _level(105.0, "polarity", side="resistance"),
        _level(106.0, "gap_unfilled", side="resistance"),
    ]
    zones = cluster_into_zones(levels, ATR, spot=100.0)
    clustered = {e.element for z in zones for e in z.elements}
    assert clustered == {"hvn", "fib_618"}
    assert all(e.side == "support" for z in zones for e in z.elements)


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
    assert zones[0].score == 9.0  # 3.0 + 1.5 + 2.5 + 2.0
    assert zones[0].center_price < 100.0  # la de mayor score va primera pese a estar más lejos


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
        _level(100.0, "sma_200w"),
        _level(100.0, "ema_200d"),  # misma categoría sma_200 → max(3.0, 2.5) = 3.0
        _level(100.0, "fib_618"),
        _level(100.0, "fib_786"),  # misma categoría fibonacci → max(1.5, 0.0) = 1.5
        _level(100.0, "divergence"),  # peso 0.0 → no aporta
    ]
    assert compute_zone_score(elements) == 4.5  # 3.0 (sma_200) + 1.5 (fibonacci) + 0.0
