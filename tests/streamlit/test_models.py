"""Tests de los dataclasses puros (spec 09 tanda 1)."""

from datetime import datetime

from puts_screener.streamlit_app.models import RunSummary


def test_run_summary_display_label_with_universes():
    rs = RunSummary(
        run_id="abc",
        started_at=datetime(2026, 5, 28, 17, 24),
        finished_at=None,
        universe_size=1007,
        candidates_passed=50,
        universes=("sp500", "nasdaq100", "stoxx600", "watchlist"),
    )
    assert (
        rs.display_label == "2026-05-28 17:24 — 50 candidatos (sp500+nasdaq100+stoxx600+watchlist)"
    )


def test_run_summary_display_label_without_universes():
    rs = RunSummary(
        run_id="abc",
        started_at=datetime(2026, 5, 28, 17, 24),
        finished_at=None,
        universe_size=0,
        candidates_passed=0,
        universes=(),
    )
    assert rs.display_label == "2026-05-28 17:24 — 0 candidatos"
