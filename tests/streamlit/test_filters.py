"""Tests de filters (spec 09 tanda 1 + spec 10 tanda 3)."""

from puts_screener.streamlit_app.filters import FilterState, apply_filters
from puts_screener.streamlit_app.models import CandidateRow


def _row(
    ticker="AAA",
    tipo="T1",
    sector="Tech",
    score: float | None = 10.0,
    earnings=False,
    ex_div=False,
    macro=False,
    regime: str | None = "uptrend",
    primary_trigger: str | None = "pullback_in_uptrend",
    wheel_candidate: bool = False,
) -> CandidateRow:
    return CandidateRow(
        ticker=ticker,
        tipo_T=tipo,
        spot=100.0,
        sector=sector,
        country="United States",
        momentum_score=0,
        universes=("sp500",),
        best_zone_score=score,
        best_zone_tier=3 if score is not None else None,
        best_zone_distance_pct=0.05 if score is not None else None,
        earnings_en_45d=earnings,
        ex_div_en_45d=ex_div,
        tiene_eventos_macro_en_45d=macro,
        strike_natural=100.0,
        currency="USD",
        regime=regime,
        primary_trigger=primary_trigger,
        composite_label=f"{regime.title()}: ..." if regime else "",
        wheel_candidate=wheel_candidate,
    )


def test_apply_filters_empty_state_returns_all():
    rows = [_row("A"), _row("B"), _row("C")]
    result = apply_filters(rows, FilterState())
    assert [r.ticker for r in result] == ["A", "B", "C"]


def test_apply_filters_by_regime():
    # spec 10: filtro por régimen reemplaza filtro por T1-T5.
    rows = [
        _row("A", regime="uptrend"),
        _row("B", regime="downtrend"),
        _row("C", regime="uptrend"),
    ]
    result = apply_filters(rows, FilterState(regime=frozenset({"uptrend"})))
    assert [r.ticker for r in result] == ["A", "C"]


def test_apply_filters_by_primary_trigger():
    rows = [
        _row("A", primary_trigger="pullback_in_uptrend"),
        _row("B", primary_trigger="double_bottom_confirmed"),
        _row("C", primary_trigger="pullback_in_uptrend"),
    ]
    result = apply_filters(rows, FilterState(primary_trigger=frozenset({"pullback_in_uptrend"})))
    assert [r.ticker for r in result] == ["A", "C"]


def test_apply_filters_by_sector():
    rows = [_row("A", sector="Tech"), _row("B", sector="Health"), _row("C", sector="Tech")]
    result = apply_filters(rows, FilterState(sector=frozenset({"Health"})))
    assert [r.ticker for r in result] == ["B"]


def test_apply_filters_by_score_min_excludes_lower():
    rows = [_row("A", score=5.0), _row("B", score=12.0), _row("C", score=8.0)]
    result = apply_filters(rows, FilterState(score_min=10.0))
    assert [r.ticker for r in result] == ["B"]


def test_apply_filters_score_min_zero_includes_none_score():
    rows = [_row("A", score=None), _row("B", score=5.0)]
    result = apply_filters(rows, FilterState(score_min=0.0))
    assert [r.ticker for r in result] == ["A", "B"]


def test_apply_filters_score_min_positive_excludes_none_score():
    rows = [_row("A", score=None), _row("B", score=5.0)]
    result = apply_filters(rows, FilterState(score_min=1.0))
    assert [r.ticker for r in result] == ["B"]


def test_apply_filters_binary_flag_true():
    rows = [_row("A", earnings=True), _row("B", earnings=False)]
    result = apply_filters(rows, FilterState(requires_earnings_in_45d=True))
    assert [r.ticker for r in result] == ["A"]


def test_apply_filters_binary_flag_false():
    rows = [_row("A", earnings=True), _row("B", earnings=False)]
    result = apply_filters(rows, FilterState(requires_earnings_in_45d=False))
    assert [r.ticker for r in result] == ["B"]


def test_apply_filters_binary_flag_none_ignored():
    rows = [_row("A", earnings=True), _row("B", earnings=False)]
    result = apply_filters(rows, FilterState(requires_earnings_in_45d=None))
    assert [r.ticker for r in result] == ["A", "B"]


def test_apply_filters_wheel_only():
    # spec 10: filtro wheel_only mostrando solo candidatos marcados.
    rows = [
        _row("A", wheel_candidate=True),
        _row("B", wheel_candidate=False),
        _row("C", wheel_candidate=True),
    ]
    result = apply_filters(rows, FilterState(wheel_only=True))
    assert [r.ticker for r in result] == ["A", "C"]


def test_apply_filters_legacy_run_excluded_by_regime_filter():
    # Runs históricos: regime=None. Si el filtro regime está activo, quedan fuera.
    rows = [
        _row("A", regime="uptrend"),
        _row("B", regime=None),
    ]
    result = apply_filters(rows, FilterState(regime=frozenset({"uptrend"})))
    assert [r.ticker for r in result] == ["A"]


def test_apply_filters_combines_multiple_criteria():
    rows = [
        _row("A", regime="uptrend", sector="Tech", score=15.0, earnings=True),
        _row("B", regime="uptrend", sector="Tech", score=15.0, earnings=False),
        _row("C", regime="downtrend", sector="Tech", score=15.0, earnings=True),
        _row("D", regime="uptrend", sector="Health", score=15.0, earnings=True),
        _row("E", regime="uptrend", sector="Tech", score=5.0, earnings=True),
    ]
    state = FilterState(
        regime=frozenset({"uptrend"}),
        sector=frozenset({"Tech"}),
        score_min=10.0,
        requires_earnings_in_45d=True,
    )
    result = apply_filters(rows, state)
    assert [r.ticker for r in result] == ["A"]
