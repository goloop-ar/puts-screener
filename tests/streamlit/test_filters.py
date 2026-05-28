"""Tests de filters (spec 09 tanda 1)."""

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
    )


def test_apply_filters_empty_state_returns_all():
    rows = [_row("A"), _row("B"), _row("C")]
    result = apply_filters(rows, FilterState())
    assert [r.ticker for r in result] == ["A", "B", "C"]


def test_apply_filters_by_tier():
    rows = [_row("A", tipo="T1"), _row("B", tipo="T2"), _row("C", tipo="T1")]
    result = apply_filters(rows, FilterState(tier=frozenset({"T1"})))
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


def test_apply_filters_combines_multiple_criteria():
    rows = [
        _row("A", tipo="T1", sector="Tech", score=15.0, earnings=True),
        _row("B", tipo="T1", sector="Tech", score=15.0, earnings=False),
        _row("C", tipo="T2", sector="Tech", score=15.0, earnings=True),
        _row("D", tipo="T1", sector="Health", score=15.0, earnings=True),
        _row("E", tipo="T1", sector="Tech", score=5.0, earnings=True),
    ]
    state = FilterState(
        tier=frozenset({"T1"}),
        sector=frozenset({"Tech"}),
        score_min=10.0,
        requires_earnings_in_45d=True,
    )
    result = apply_filters(rows, state)
    assert [r.ticker for r in result] == ["A"]
