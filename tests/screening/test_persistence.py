import sqlite3
from datetime import datetime

import pandas as pd

from puts_screener.models_screening import ScreenedCandidate, TypeClassification
from puts_screener.persistence import get_run_candidates, list_runs, save_run
from puts_screener.providers.models import (
    AnalystData,
    CompanyProfile,
    FinancialSnapshot,
)


def _candidate(
    ticker="AAPL",
    *,
    momentum_score=0,
    passes=True,
    tipo="T1",
    motivos=None,
    errors=None,
):
    return ScreenedCandidate(
        ticker=ticker,
        profile=CompanyProfile(
            ticker=ticker,
            name="X",
            sector="Tech",
            industry="Y",
            exchange="NMS",
            country="United States",
            market_cap_usd=50e9,
            currency="USD",
            avg_daily_volume_3m=5e6,
        ),
        financials=FinancialSnapshot(
            ticker=ticker,
            free_cash_flow_ttm=1e9,
            total_revenue_ttm=1e10,
            fiscal_year_end=None,
            as_of=None,
        ),
        analyst=AnalystData(
            ticker=ticker,
            price_target_mean=110.0,
            price_target_median=None,
            price_target_high=None,
            price_target_low=None,
            n_analysts=10,
        ),
        rating_changes_6w=[],
        upcoming_earnings=None,
        earnings_history=[],
        ohlcv_daily=pd.DataFrame(),
        ohlcv_weekly=pd.DataFrame(),
        classification=TypeClassification(tipo=tipo, justificacion="test"),
        momentum_score=momentum_score,
        pasa_filtros_paso_1=passes,
        motivos_rechazo=motivos if motivos is not None else [],
        errors=errors if errors is not None else [],
    )


def test_save_run_and_list(tmp_path):
    db = tmp_path / "test.db"
    run_id = save_run([_candidate()], universe_size=1, started_at=datetime.now(), db_path=db)
    runs = list_runs(db_path=db)
    assert len(runs) == 1
    assert runs[0]["run_id"] == run_id
    assert runs[0]["universe_size"] == 1
    assert runs[0]["candidates_passed"] == 1
    assert runs[0]["status"] == "completed"


def test_save_run_persists_all_fields(tmp_path):
    db = tmp_path / "test.db"
    c = _candidate(ticker="AAPL", momentum_score=2, passes=True, tipo="T1")
    c.spot = 123.45
    c.hv_percentile_52w = 55.0
    run_id = save_run([c], universe_size=1, started_at=datetime.now(), db_path=db)

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM candidates WHERE run_id=?", (run_id,)).fetchone()
    conn.close()

    assert row["ticker"] == "AAPL"
    assert row["tipo_T"] == "T1"
    assert row["pasa_filtros_paso_1"] == 1
    assert row["momentum_score"] == 2
    assert row["spot"] == 123.45
    assert row["hv_percentile_52w"] == 55.0
    assert row["market_cap"] == 50e9
    assert row["country"] == "United States"


def test_get_run_candidates_returns_data(tmp_path):
    db = tmp_path / "test.db"
    cands = [
        _candidate("AAA", passes=True),
        _candidate("BBB", passes=True),
        _candidate("CCC", passes=False),
    ]
    run_id = save_run(cands, universe_size=3, started_at=datetime.now(), db_path=db)

    assert len(get_run_candidates(run_id, db_path=db)) == 3
    passed = get_run_candidates(run_id, only_passed=True, db_path=db)
    assert len(passed) == 2
    assert all(c["pasa_filtros_paso_1"] for c in passed)


def test_get_run_candidates_ordered_by_momentum(tmp_path):
    db = tmp_path / "test.db"
    cands = [
        _candidate("LOW", momentum_score=0),
        _candidate("MID", momentum_score=2),
        _candidate("HIGH", momentum_score=3),
    ]
    run_id = save_run(cands, universe_size=3, started_at=datetime.now(), db_path=db)

    result = get_run_candidates(run_id, db_path=db)
    assert [c["momentum_score"] for c in result] == [3, 2, 0]
    assert [c["ticker"] for c in result] == ["HIGH", "MID", "LOW"]


def test_motivos_rechazo_and_errors_serialized_as_json(tmp_path):
    db = tmp_path / "test.db"
    c = _candidate(
        passes=False,
        motivos=["quality_liquidity: low cap", "valuation: no upside"],
        errors=["ratings: 403"],
    )
    run_id = save_run([c], universe_size=1, started_at=datetime.now(), db_path=db)

    result = get_run_candidates(run_id, db_path=db)
    assert result[0]["motivos_rechazo"] == ["quality_liquidity: low cap", "valuation: no upside"]
    assert result[0]["errors"] == ["ratings: 403"]


def test_env_var_overrides_db_path(tmp_path, monkeypatch):
    custom = tmp_path / "custom.db"
    monkeypatch.setenv("PUTS_SCREENER_DB_PATH", str(custom))
    save_run([_candidate()], universe_size=1, started_at=datetime.now())
    assert custom.exists()
