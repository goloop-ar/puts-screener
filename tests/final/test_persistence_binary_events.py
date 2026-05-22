"""Tests de persistencia de eventos binarios en candidates (spec 04 §10)."""

import json
import sqlite3
from datetime import date, datetime

from puts_screener.macro_calendar import MacroEvent
from puts_screener.persistence import _BINARY_EVENT_COLUMNS, save_binary_events, save_run


def _persist(final_candidates, db):
    """Crea las filas de candidates (save_run) y luego actualiza sus eventos binarios."""
    screened = [fc.supported.screened for fc in final_candidates]
    run_id = save_run(screened, universe_size=len(screened), started_at=datetime.now(), db_path=db)
    save_binary_events(run_id, final_candidates, db_path=db)
    return run_id


def _read(db, run_id, ticker):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM candidates WHERE run_id = ? AND ticker = ?", (run_id, ticker)
    ).fetchone()
    conn.close()
    return dict(row)


def test_round_trip_all_columns(tmp_path, final_candidate_factory):
    db = tmp_path / "binev.db"
    macro = [MacroEvent(date=date(2026, 6, 17), kind="fomc", description="FOMC")]
    fc = final_candidate_factory(
        ticker="AAA",
        earnings_date=date(2026, 6, 2),
        dias_a_earnings=12,
        earnings_en_45d=True,
        ex_div_date=date(2026, 5, 29),
        ex_div_amount=0.25,
        macro_events=macro,
        flags=["Earnings en 12 días (2026-06-02)", "Evento macro: fomc en 27 días (FOMC)"],
    )
    run_id = _persist([fc], db)
    row = _read(db, run_id, "AAA")

    assert row["earnings_date"] == "2026-06-02"
    assert row["dias_a_earnings"] == 12
    assert row["earnings_en_45d"] == 1
    assert row["ex_div_date"] == "2026-05-29"
    assert row["ex_div_amount"] == 0.25
    assert row["ex_div_en_45d"] == 1  # el factory marca en_45d cuando hay amount
    assert row["eventos_macro_en_45d"] == 1
    assert row["tiene_eventos_binarios"] == 1
    assert json.loads(row["eventos_macro_json"]) == [
        {"date": "2026-06-17", "kind": "fomc", "description": "FOMC"}
    ]
    assert json.loads(row["flags_legibles_json"]) == [
        "Earnings en 12 días (2026-06-02)",
        "Evento macro: fomc en 27 días (FOMC)",
    ]


def test_none_fields_persist_as_null(tmp_path, final_candidate_factory):
    db = tmp_path / "binev.db"
    fc = final_candidate_factory(ticker="NUL", earnings_date=None, ex_div_date=None)
    run_id = _persist([fc], db)
    row = _read(db, run_id, "NUL")
    assert row["earnings_date"] is None
    assert row["ex_div_date"] is None
    assert row["ex_div_amount"] is None
    assert json.loads(row["eventos_macro_json"]) == []
    assert json.loads(row["flags_legibles_json"]) == []


def test_idempotent_migration_and_update(tmp_path, final_candidate_factory):
    db = tmp_path / "binev.db"
    fc = final_candidate_factory(
        ticker="IDEM", earnings_date=date(2026, 6, 2), earnings_en_45d=True
    )
    run_id = _persist([fc], db)
    save_binary_events(run_id, [fc], db_path=db)  # segunda vez: no debe romper ni duplicar

    conn = sqlite3.connect(db)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(candidates)").fetchall()]
    n_rows = conn.execute(
        "SELECT COUNT(*) FROM candidates WHERE run_id = ? AND ticker = ?", (run_id, "IDEM")
    ).fetchone()[0]
    conn.close()

    for col in _BINARY_EVENT_COLUMNS:
        assert cols.count(col) == 1  # cada columna agregada una sola vez
    assert n_rows == 1  # UPDATE no duplica filas


def test_persists_even_when_not_passing_paso_2(tmp_path, final_candidate_factory):
    db = tmp_path / "binev.db"
    fc = final_candidate_factory(
        ticker="NOPASS",
        passes=False,
        earnings_date=date(2026, 5, 26),
        earnings_en_45d=True,
        flags=["Earnings en 5 días (2026-05-26)"],
    )
    run_id = _persist([fc], db)
    row = _read(db, run_id, "NOPASS")

    assert row["pasa_paso_2"] is None  # no se corrió save_support_analysis en este test
    assert row["earnings_date"] == "2026-05-26"
    assert row["earnings_en_45d"] == 1
    assert row["tiene_eventos_binarios"] == 1
