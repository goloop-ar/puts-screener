"""Tests del clustering de zonas y scoring (spec 03 §6 + spec 06: envelope + density bonus).

Firma nueva (spec 06): cluster_into_zones(levels, spot, atr14).
tolerance = min(CLUSTERING_TOLERANCE_ATR×atr14, spot×CLUSTERING_TOLERANCE_MAX_PCT).
score = score_base (dedup max-por-categoría) × density_multiplier(n_heavy, width_pct).
"""

import pytest

from puts_screener.config_supports import MAX_DENSITY_MULTIPLIER, MIN_DENSITY_MULTIPLIER
from puts_screener.models_support import SupportLevel
from puts_screener.zone_clustering import (
    cluster_into_zones,
    compute_zone_score,
    density_multiplier,
)

ATR = 1.0  # tolerance = min(0.4×ATR, spot×0.01); con spot=120 → min(0.4, 1.2) = 0.4
SPOT = 120.0


def _level(price, element, side="support"):
    return SupportLevel(price=price, element=element, side=side)


def _base_score(elements):
    """score_base aislado: n_heavy_elements=0 fuerza multiplicador neutro (1.0)."""
    return compute_zone_score(elements, zone_width_pct=0.02, n_heavy_elements=0)


# --- score base / dedup por categoría (vía compute_zone_score, multiplicador neutro) ---


def test_dedup_sma200_uses_max_weight():
    """SMA200W (3.0) + EMA200D (2.5) → categoría sma_200 aporta el máximo (3.0), no 5.5."""
    assert _base_score([_level(100.0, "sma_200w"), _level(100.2, "ema_200d")]) == 3.0


def test_dedup_fibonacci_fib618_weight():
    """FIB_618 (1.5) + FIB_786 (0.0) → categoría fibonacci aporta 1.5."""
    assert _base_score([_level(100.0, "fib_618"), _level(100.3, "fib_786")]) == 1.5


def test_dedup_avwap_max_weight():
    levels = [
        _level(100.0, "avwap_pivot_low"),
        _level(100.2, "avwap_earnings"),
        _level(100.4, "avwap_52w_high"),
    ]
    assert _base_score(levels) == 2.5  # max(2.5, 2.5, 2.0)


def test_mixed_confluence_weighted_score():
    """SMA200 (3.0) + fib_618 (1.5) + AVWAP (2.5) + HVN (2.0) = 9.0 (base)."""
    levels = [
        _level(100.0, "sma_200w"),
        _level(100.2, "fib_618"),
        _level(100.4, "avwap_pivot_low"),
        _level(100.5, "hvn"),
    ]
    assert _base_score(levels) == 9.0


def test_dedup_sma200_three_labels_max_weight():
    """SMA200W (3.0) + EMA200D (2.5) + SMA200D (3.0) → categoría sma_200 = 3.0."""
    levels = [_level(100.0, "sma_200w"), _level(100.1, "ema_200d"), _level(100.2, "sma_200d")]
    assert _base_score(levels) == 3.0


def test_dedup_sma50_three_labels_max_weight():
    """SMA50D (2.5) + SMA50W (2.0) + EMA50D (1.5) → categoría sma_50 = 2.5."""
    levels = [_level(100.0, "sma_50w"), _level(100.1, "sma_50d"), _level(100.2, "ema_50d")]
    assert _base_score(levels) == 2.5


def test_sma200_plus_sma50_plus_confirmer_weighted():
    """SMA200 (3.0) + SMA50 (2.5) + HVN (2.0) = 7.5 (base)."""
    levels = [_level(100.0, "sma_200w"), _level(100.2, "sma_50d"), _level(100.4, "hvn")]
    assert _base_score(levels) == 7.5


def test_divergence_does_not_add_to_score():
    """DIVERGENCIA (0.0) + HVN (2.0) + POLARIDAD (3.0) = 5.0; la divergencia no suma."""
    levels = [_level(100.0, "divergence"), _level(100.2, "hvn"), _level(100.4, "polarity")]
    assert _base_score(levels) == 5.0


def test_unknown_element_contributes_zero():
    """Un label desconocido no aporta al score y no rompe."""
    assert _base_score([_level(100.0, "no_existe")]) == 0.0
    assert _base_score([_level(100.0, "hvn"), _level(100.1, "no_existe")]) == 2.0


def test_compute_zone_score_dedup_across_categories():
    elements = [
        _level(100.0, "sma_200w"),
        _level(100.0, "ema_200d"),  # misma categoría sma_200 → max(3.0, 2.5) = 3.0
        _level(100.0, "fib_618"),
        _level(100.0, "fib_786"),  # misma categoría fibonacci → max(1.5, 0.0) = 1.5
        _level(100.0, "divergence"),  # peso 0.0 → no aporta
    ]
    assert _base_score(elements) == 4.5  # 3.0 (sma_200) + 1.5 (fibonacci) + 0.0


# --- density multiplier (función pura) ---


def test_density_multiplier_neutral_at_reference():
    """2 heavies en 2% width → densidad 100 (referencia) → multiplicador 1.0."""
    assert density_multiplier(2, 0.02) == 1.0


def test_density_multiplier_floors_at_min():
    """1 heavy en 10% width → densidad 10 → multiplicador clipeado al floor."""
    assert density_multiplier(1, 0.10) == MIN_DENSITY_MULTIPLIER


def test_density_multiplier_caps_at_max():
    """6 heavies en 0.5% width → densidad enorme → multiplicador clipeado al cap."""
    assert density_multiplier(6, 0.005) == MAX_DENSITY_MULTIPLIER


def test_compute_zone_score_applies_density_bonus():
    """Zona compacta con muchos heavies → score final > score base."""
    elements = [_level(100.0, "sma_200w"), _level(100.1, "polarity")]  # base = 6.0, 2 heavies
    score = compute_zone_score(elements, zone_width_pct=0.01, n_heavy_elements=2)
    assert score == pytest.approx(9.0)  # 6.0 × 1.5 (cap)
    assert score > 6.0


def test_compute_zone_score_applies_density_penalty():
    """Zona ancha → score final < score base (multiplicador clipeado al floor 0.85)."""
    elements = [_level(100.0, "sma_200w"), _level(105.0, "polarity")]  # base = 6.0, 2 heavies
    score = compute_zone_score(elements, zone_width_pct=0.10, n_heavy_elements=2)
    assert score == pytest.approx(6.0 * MIN_DENSITY_MULTIPLIER)  # 5.1
    assert score < 6.0


# --- clustering: geometría, tolerance, gate, orden ---


def test_far_apart_levels_form_separate_zones():
    levels = [_level(100.0, "hvn"), _level(110.0, "polarity")]
    zones = cluster_into_zones(levels, SPOT, ATR)
    assert len(zones) == 2
    assert {z.elements[0].element for z in zones} == {"hvn", "polarity"}


def test_close_levels_form_single_zone():
    """Elementos a ≤ tolerance (0.3 ≤ 0.4) → mismo cluster."""
    levels = [_level(100.0, "hvn"), _level(100.3, "polarity")]
    zones = cluster_into_zones(levels, SPOT, ATR)
    assert len(zones) == 1
    assert len(zones[0].elements) == 2


def test_single_element_zone_scores_its_weight():
    """HVN solo (peso 2.0, no heavy → multiplicador neutro) → score 2.0."""
    zones = cluster_into_zones([_level(100.0, "hvn")], SPOT, ATR)
    assert len(zones) == 1
    assert zones[0].score == 2.0


def test_clustering_tolerance_uses_min_of_atr_and_pct():
    """El cap % gana sobre el ATR cuando el spot es bajo (separa niveles cercanos)."""
    # atr=10 → 0.4×10 = 4.0; spot=100 → 100×0.01 = 1.0; tolerance = min(4.0, 1.0) = 1.0.
    levels = [_level(98.0, "hvn"), _level(99.5, "polarity")]  # 1.5 de separación > 1.0
    zones = cluster_into_zones(levels, spot=100.0, atr14=10.0)
    assert len(zones) == 2  # con tolerance ATR-pura (4.0) habrían sido 1 zona


def test_clustering_rejects_cluster_wider_than_max_pct():
    """5 niveles encadenados que abarcan > 4% del centro → cluster descartado (cero zonas)."""
    # spot=110, atr=5 → tolerance = min(2.0, 1.1) = 1.1; niveles a 1.0 encadenan.
    levels = [
        _level(p, "polarity") for p in (95.0, 96.0, 97.0, 98.0, 99.0)
    ]  # span 4 / center 97 = 4.1%
    zones = cluster_into_zones(levels, spot=110.0, atr14=5.0)
    assert zones == []


def test_zone_bounds_match_element_envelope():
    """3 niveles a 100/101/102 → bounds = [min-buffer, max+buffer], NO centro±ATR."""
    # spot=200, atr=5 → tolerance=2.0; niveles a 1.0 encadenan; span 2% (< 4%).
    levels = [_level(100.0, "polarity"), _level(101.0, "hvn"), _level(102.0, "sma_200w")]
    zones = cluster_into_zones(levels, spot=200.0, atr14=5.0)
    assert len(zones) == 1
    z = zones[0]
    buffer = 0.001 * 101.0
    assert z.lower_bound == pytest.approx(100.0 - buffer)
    assert z.upper_bound == pytest.approx(102.0 + buffer)
    assert z.center_price == pytest.approx(101.0)


def test_zone_flags_dynamic_confirmer():
    """has_dynamic_confirmer True si hay avwap/hvn/divergence; False si solo SMAs."""
    with_avwap = cluster_into_zones([_level(100.0, "avwap_pivot_low")], SPOT, ATR)
    assert with_avwap[0].has_dynamic_confirmer is True
    only_sma = cluster_into_zones([_level(100.0, "sma_200w")], SPOT, ATR)
    assert only_sma[0].has_dynamic_confirmer is False


# --- filtro por side (support vs resistance) ---


def test_resistance_side_levels_excluded():
    """Un nivel con side='resistance' (precio ≥ spot) se descarta antes de clusterizar."""
    levels = [_level(95.0, "hvn"), _level(103.0, "polarity", side="resistance")]
    zones = cluster_into_zones(levels, spot=100.0, atr14=ATR)
    assert len(zones) == 1
    assert zones[0].center_price == pytest.approx(95.0)
    assert "polarity" not in [e.element for z in zones for e in z.elements]


def test_only_support_side_levels_clustered():
    """De una mezcla support/resistance, solo los support entran al clustering."""
    levels = [
        _level(95.0, "hvn", side="support"),
        _level(96.0, "fib_618", side="support"),
        _level(105.0, "polarity", side="resistance"),
        _level(106.0, "gap_unfilled", side="resistance"),
    ]
    zones = cluster_into_zones(levels, spot=100.0, atr14=ATR)
    clustered = {e.element for z in zones for e in z.elements}
    assert clustered == {"hvn", "fib_618"}
    assert all(e.side == "support" for z in zones for e in z.elements)


# --- ordenamiento ---


def test_zones_sorted_by_score_desc():
    """La zona de mayor score va primera, aunque esté más lejos del spot."""
    levels = [
        # cluster lejano, base alto (sma_200 + fib + avwap + hvn = 9.0), compacto
        _level(90.0, "sma_200w"),
        _level(90.2, "fib_618"),
        _level(90.4, "avwap_pivot_low"),
        _level(90.5, "hvn"),
        # cluster cercano, base más bajo (hvn + polarity + gap = 6.0)
        _level(110.0, "hvn"),
        _level(110.3, "polarity"),
        _level(110.5, "gap_unfilled"),
    ]
    zones = cluster_into_zones(levels, SPOT, ATR)
    assert len(zones) == 2
    assert zones[0].score > zones[1].score
    assert zones[0].center_price < 100.0  # el de mayor score, pese a estar más lejos


def test_zones_same_score_sorted_by_distance():
    """Mismo score → la más cercana al spot primero (por distance_pct asc)."""
    levels = [_level(100.0, "hvn"), _level(110.0, "hvn")]  # ambos base 2.0, n_heavy 0 → score 2.0
    zones = cluster_into_zones(levels, SPOT, ATR)
    assert len(zones) == 2
    assert zones[0].score == zones[1].score
    assert zones[0].center_price == pytest.approx(110.0)  # más cerca de spot=120
    assert zones[1].center_price == pytest.approx(100.0)
