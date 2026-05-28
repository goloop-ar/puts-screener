"""Tests de data_loader (spec 09 tanda 1). Usan el fixture `synthetic_db` del conftest."""

from datetime import date

import pytest

from puts_screener.streamlit_app.data_loader import (
    list_recent_runs,
    load_best_zone,
    load_candidate_detail,
    load_run_candidates,
)


def test_list_recent_runs_returns_desc_order(synthetic_db):
    runs = list_recent_runs(db_path=synthetic_db)
    assert len(runs) == 2
    assert runs[0].run_id == "run-2"
    assert runs[1].run_id == "run-1"


def test_list_recent_runs_respects_limit(synthetic_db):
    runs = list_recent_runs(limit=1, db_path=synthetic_db)
    assert len(runs) == 1
    assert runs[0].run_id == "run-2"


def test_list_recent_runs_parses_universes_json(synthetic_db):
    runs = list_recent_runs(db_path=synthetic_db)
    assert runs[0].universes == ("sp500", "nasdaq100")
    assert runs[1].universes == ("sp500",)


def test_load_run_candidates_returns_only_paso_2_passers(synthetic_db):
    rows = load_run_candidates("run-2", db_path=synthetic_db)
    tickers = [r.ticker for r in rows]
    assert "NOZONE" not in tickers  # pasa_paso_2=0
    # AAPL + MSFT + BARC.L + NOSCORE = 4
    assert len(rows) == 4


def test_load_run_candidates_orders_by_score_desc(synthetic_db):
    rows = load_run_candidates("run-2", db_path=synthetic_db)
    # BARC.L(15.0) > AAPL(10.5) > MSFT(8.0) > NOSCORE(None — al final por SQLite NULLs-last en DESC)
    assert [r.ticker for r in rows] == ["BARC.L", "AAPL", "MSFT", "NOSCORE"]


def test_load_run_candidates_includes_currency_from_country(synthetic_db):
    rows = load_run_candidates("run-2", db_path=synthetic_db)
    by_ticker = {r.ticker: r for r in rows}
    assert by_ticker["AAPL"].currency == "USD"  # United States
    assert by_ticker["MSFT"].currency == "USD"
    assert by_ticker["BARC.L"].currency == "GBp"  # United Kingdom
    assert by_ticker["NOSCORE"].currency == "EUR"  # France


def test_load_run_candidates_handles_candidate_without_zone(synthetic_db):
    rows = load_run_candidates("run-2", db_path=synthetic_db)
    nz = next(r for r in rows if r.ticker == "NOSCORE")
    assert nz.best_zone_score is None
    assert nz.best_zone_tier is None
    assert nz.best_zone_distance_pct is None


def test_load_best_zone_returns_zone_when_is_best_1(synthetic_db):
    zone = load_best_zone("run-2", "AAPL", db_path=synthetic_db)
    assert zone is not None
    assert zone.lower_bound == 193.0
    assert zone.upper_bound == 197.0
    assert zone.score == 10.5
    assert zone.has_dynamic_confirmer is True


def test_load_best_zone_returns_none_when_no_best(synthetic_db):
    assert load_best_zone("run-2", "NOSCORE", db_path=synthetic_db) is None
    assert load_best_zone("run-2", "DOESNOTEXIST", db_path=synthetic_db) is None


def test_load_best_zone_parses_elements_json(synthetic_db):
    zone = load_best_zone("run-2", "AAPL", db_path=synthetic_db)
    assert zone is not None
    assert len(zone.elements) == 2
    by_element = {e.element: e for e in zone.elements}
    assert "sma_200w" in by_element
    assert "polarity" in by_element
    assert by_element["polarity"].metadata == {"pivot_date": "2025-01-15"}
    assert by_element["sma_200w"].price == 193.0


def test_load_candidate_detail_combines_candidate_and_zone(synthetic_db):
    detail = load_candidate_detail("run-2", "AAPL", db_path=synthetic_db)
    assert detail.row.ticker == "AAPL"
    assert detail.best_zone is not None
    assert detail.best_zone.score == 10.5
    assert detail.row.best_zone_score == 10.5
    assert detail.strikes["natural"] == 200.0
    assert detail.strikes["aggressive"] == 205.0
    assert detail.sma_50w == 190.0
    assert detail.sma_200w == 180.0
    assert detail.atr_14 == 2.5
    assert detail.earnings_date == date(2026, 6, 10)


def test_load_candidate_detail_parses_json_fields(synthetic_db):
    detail = load_candidate_detail("run-2", "MSFT", db_path=synthetic_db)
    assert detail.eventos_macro == ({"date": "2026-06-15", "kind": "fomc", "description": "FOMC"},)
    assert detail.flags_legibles == ("Ex-dividend en 5 días ($0.75)",)
    assert detail.momentum_signals == ()
    assert detail.ex_div_date == date(2026, 6, 2)
    assert detail.ex_div_amount == 0.75


def test_load_candidate_detail_raises_when_ticker_missing(synthetic_db):
    with pytest.raises(ValueError, match="not found"):
        load_candidate_detail("run-2", "DOESNOTEXIST", db_path=synthetic_db)
