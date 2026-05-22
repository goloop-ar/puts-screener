"""Tests de validación y ranking de zonas (spec 03 §7)."""

from puts_screener.models_support import SupportLevel, SupportZone
from puts_screener.support_scoring import (
    REASON_NO_CONFIRMER,
    REASON_OUT_OF_RANGE,
    analyze_supports,
    validate_and_rank,
)


def _zone(score, *, confirmer, distance_pct, elements=None, center=95.0):
    """SupportZone con campos controlados (elements default = un HVN)."""
    if elements is None:
        elements = [SupportLevel(price=center, element="hvn", points=1)]
    return SupportZone(
        center_price=center,
        lower_bound=center - 1.0,
        upper_bound=center + 1.0,
        score=score,
        elements=elements,
        has_dynamic_confirmer=confirmer,
        distance_pct=distance_pct,
    )


def test_zone_score3_with_confirmer_is_valid():
    zone = _zone(3, confirmer=True, distance_pct=0.05)
    analysis = validate_and_rank([zone])
    assert analysis.valid_zones == [zone]
    assert analysis.rejected_zones == []
    assert analysis.best_zone is zone


def test_zone_without_dynamic_confirmer_rejected():
    """Score 5 alto pero sin AVWAP/HVN/divergencia → rechazada por confirmador."""
    elements = [
        SupportLevel(price=95.0, element="sma_200w", points=2),
        SupportLevel(price=95.1, element="fib_618", points=1),
        SupportLevel(price=95.2, element="polarity", points=1),
        SupportLevel(price=95.3, element="gap_unfilled", points=1),
    ]
    zone = _zone(5, confirmer=False, distance_pct=0.05, elements=elements)
    analysis = validate_and_rank([zone])
    assert analysis.valid_zones == []
    assert analysis.best_zone is None
    assert analysis.rejected_zones[0][1] == REASON_NO_CONFIRMER


def test_zone_out_of_proximity_rejected():
    """Score 3 + confirmador pero a 12% del spot → rechazada por proximidad."""
    zone = _zone(3, confirmer=True, distance_pct=0.12)
    analysis = validate_and_rank([zone])
    assert analysis.valid_zones == []
    assert analysis.rejected_zones[0][1] == REASON_OUT_OF_RANGE


def test_best_zone_same_score_closer_wins():
    far = _zone(3, confirmer=True, distance_pct=0.08, center=90.0)
    near = _zone(3, confirmer=True, distance_pct=0.04, center=96.0)  # ≥ 3% para pasar el gate
    analysis = validate_and_rank([far, near])
    assert analysis.best_zone is near
    assert analysis.valid_zones == [near, far]


def test_zone_too_close_to_spot_rejected():
    """Score 5 + confirmador pero a 2% del spot → rechazada por distancia mínima (< 3%)."""
    zone = _zone(5, confirmer=True, distance_pct=0.02)
    analysis = validate_and_rank([zone])
    assert analysis.valid_zones == []
    assert analysis.best_zone is None
    assert "muy cerca del spot" in analysis.rejected_zones[0][1]


def test_zone_far_enough_from_spot_valid():
    """Score 5 + confirmador a 5% del spot → válida."""
    zone = _zone(5, confirmer=True, distance_pct=0.05)
    analysis = validate_and_rank([zone])
    assert analysis.valid_zones == [zone]
    assert analysis.best_zone is zone


def test_zone_at_exact_min_distance_valid():
    """distance_pct == 3% exacto → válida (el gate es >=, no >)."""
    zone = _zone(3, confirmer=True, distance_pct=0.03)
    analysis = validate_and_rank([zone])
    assert analysis.valid_zones == [zone]
    assert analysis.best_zone is zone


def test_best_zone_tiebreak_by_category_diversity():
    """Mismo score y misma distancia → gana la de más categorías distintas."""
    fewer = _zone(
        3,
        confirmer=True,
        distance_pct=0.05,
        center=95.0,
        elements=[
            SupportLevel(price=95.0, element="hvn", points=1),
            SupportLevel(price=95.1, element="polarity", points=1),
        ],
    )
    more = _zone(
        3,
        confirmer=True,
        distance_pct=0.05,
        center=95.0,
        elements=[
            SupportLevel(price=95.0, element="hvn", points=1),
            SupportLevel(price=95.1, element="polarity", points=1),
            SupportLevel(price=95.2, element="gap_unfilled", points=1),
        ],
    )
    analysis = validate_and_rank([fewer, more])
    assert analysis.best_zone is more


def test_analyze_supports_empty_on_short_history(candidate_factory, ascending_ohlcv):
    """OHLCV ascendente de 50 días → ninguna zona válida ni best_zone (no rompe).

    Con las MAs de 50 (Etapa 3) un histórico de 50 ruedas sí produce SMA50D/EMA50D, pero
    solas (categoría sma_50 = 1 pt, sin confirmador dinámico) no forman una zona válida.
    """
    candidate = candidate_factory(ascending_ohlcv)
    analysis = analyze_supports(candidate, data_service=None)
    assert analysis.valid_zones == []
    assert analysis.best_zone is None
