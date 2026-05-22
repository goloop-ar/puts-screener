"""Tests de validación y ranking de zonas (spec 03 §7 + Etapa 4: pesos + gate estructural)."""

from puts_screener.models_support import SupportLevel, SupportZone
from puts_screener.support_scoring import (
    REASON_NO_CONFIRMER,
    REASON_OUT_OF_RANGE,
    analyze_supports,
    validate_and_rank,
)


def _lvl(element, price=95.0):
    return SupportLevel(price=price, element=element)


def _zone(score, *, confirmer, distance_pct, elements=None, center=95.0):
    """SupportZone con campos controlados.

    Default elements = 2 elementos pesados (SMA200W + EMA200D, peso 3.0 y 2.5) para que el
    gate estructural (MIN_HEAVY_ELEMENTS=2) pase salvo que el test pase sus propios elementos.
    El `score` se pasa explícito (no se recomputa de los elementos).
    """
    if elements is None:
        elements = [_lvl("sma_200w", center), _lvl("ema_200d", center)]
    return SupportZone(
        center_price=center,
        lower_bound=center - 1.0,
        upper_bound=center + 1.0,
        score=score,
        elements=elements,
        has_dynamic_confirmer=confirmer,
        distance_pct=distance_pct,
    )


def test_zone_valid_when_all_gates_pass():
    zone = _zone(5.0, confirmer=True, distance_pct=0.05)
    analysis = validate_and_rank([zone])
    assert analysis.valid_zones == [zone]
    assert analysis.rejected_zones == []
    assert analysis.best_zone is zone


def test_zone_without_dynamic_confirmer_rejected():
    """Score alto + 2 pesados, pero sin AVWAP/HVN/divergencia → rechazada por confirmador."""
    elements = [_lvl("sma_200w"), _lvl("polarity"), _lvl("fib_618"), _lvl("gap_unfilled")]
    zone = _zone(6.0, confirmer=False, distance_pct=0.05, elements=elements)
    analysis = validate_and_rank([zone])
    assert analysis.valid_zones == []
    assert analysis.best_zone is None
    assert analysis.rejected_zones[0][1] == REASON_NO_CONFIRMER


def test_zone_out_of_proximity_rejected():
    """Score OK + confirmador pero a 12% del spot → rechazada por proximidad."""
    zone = _zone(5.0, confirmer=True, distance_pct=0.12)
    analysis = validate_and_rank([zone])
    assert analysis.valid_zones == []
    assert analysis.rejected_zones[0][1] == REASON_OUT_OF_RANGE


def test_zone_too_close_to_spot_rejected():
    """Score OK + confirmador pero a 2% del spot → rechazada por distancia mínima (< 3%)."""
    zone = _zone(5.0, confirmer=True, distance_pct=0.02)
    analysis = validate_and_rank([zone])
    assert analysis.valid_zones == []
    assert "muy cerca del spot" in analysis.rejected_zones[0][1]


def test_zone_far_enough_from_spot_valid():
    zone = _zone(5.0, confirmer=True, distance_pct=0.05)
    analysis = validate_and_rank([zone])
    assert analysis.best_zone is zone


def test_zone_at_exact_min_distance_valid():
    """distance_pct == 3% exacto → válida (el gate es >=, no >)."""
    zone = _zone(5.0, confirmer=True, distance_pct=0.03)
    analysis = validate_and_rank([zone])
    assert analysis.valid_zones == [zone]


def test_zone_rejected_below_min_score():
    """Score 4.5 < SCORE_MIN_VALID (5.0) → rechazada por score aunque lo demás esté OK."""
    zone = _zone(4.5, confirmer=True, distance_pct=0.05)
    analysis = validate_and_rank([zone])
    assert analysis.valid_zones == []
    assert analysis.best_zone is None


def test_zone_rejected_insufficient_heavy_elements():
    """Score alto + confirmador, pero solo 1 elemento de peso >= 2.5 → gate estructural."""
    zone = _zone(
        6.0,
        confirmer=True,
        distance_pct=0.05,
        elements=[_lvl("sma_200w"), _lvl("hvn")],  # sma_200w pesado (3.0); hvn no (2.0)
    )
    analysis = validate_and_rank([zone])
    assert analysis.valid_zones == []
    assert "peso >= 2.5" in analysis.rejected_zones[0][1]


def test_zone_valid_with_two_heavy_elements():
    zone = _zone(
        6.0,
        confirmer=True,
        distance_pct=0.05,
        elements=[_lvl("sma_200w"), _lvl("ema_200d")],  # 3.0 + 2.5 → 2 pesados
    )
    analysis = validate_and_rank([zone])
    assert analysis.valid_zones == [zone]


def test_zone_valid_with_divergence_confirmer():
    """DIVERGENCIA confirma (peso 0, no suma); el score lo aportan SMA200W + POLARIDAD."""
    zone = _zone(
        6.0,
        confirmer=True,
        distance_pct=0.05,
        elements=[_lvl("sma_200w"), _lvl("polarity"), _lvl("divergence")],
    )
    analysis = validate_and_rank([zone])
    assert analysis.valid_zones == [zone]


def test_best_zone_same_score_closer_wins():
    far = _zone(5.0, confirmer=True, distance_pct=0.08, center=90.0)
    near = _zone(5.0, confirmer=True, distance_pct=0.04, center=96.0)
    analysis = validate_and_rank([far, near])
    assert analysis.best_zone is near
    assert analysis.valid_zones == [near, far]


def test_best_zone_tiebreak_by_category_diversity():
    """Mismo score y misma distancia → gana la de más categorías distintas."""
    fewer = _zone(
        5.0,
        confirmer=True,
        distance_pct=0.05,
        elements=[_lvl("sma_200w"), _lvl("polarity")],  # 2 categorías
    )
    more = _zone(
        5.0,
        confirmer=True,
        distance_pct=0.05,
        elements=[_lvl("sma_200w"), _lvl("polarity"), _lvl("hvn")],  # 3 categorías
    )
    analysis = validate_and_rank([fewer, more])
    assert analysis.best_zone is more


def test_analyze_supports_empty_on_short_history(candidate_factory, ascending_ohlcv):
    """OHLCV ascendente de 50 días → ninguna zona válida ni best_zone (no rompe).

    Con las MAs de 50 (Etapa 3) un histórico de 50 ruedas sí produce SMA50D/EMA50D, pero
    solas (categoría sma_50, sin confirmador dinámico ni 2 elementos pesados) no son válidas.
    """
    candidate = candidate_factory(ascending_ohlcv)
    analysis = analyze_supports(candidate, data_service=None)
    assert analysis.valid_zones == []
    assert analysis.best_zone is None
