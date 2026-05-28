"""Fixtures para los tests de streamlit_app (spec 09 tanda 1).

Construye una DB sintética con 2 runs y 5 candidatos (3 con best_zone, 1 sin
best_zone, 1 sin pasar Paso 2) para ejercitar los distintos paths de data_loader.
Usa `_connect` de persistence para que el schema y las migraciones se apliquen
automáticamente.
"""

import json

import pytest

from puts_screener.persistence import _connect


def _insert(conn, table, **values):
    cols = ", ".join(values.keys())
    placeholders = ", ".join(f":{c}" for c in values)
    conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})", values)


def _candidate_defaults(**override):
    defaults = {
        "tipo_T": "T1",
        "pasa_filtros_paso_1": 1,
        "pasa_paso_2": 1,
        "spot": 100.0,
        "sector": "Technology",
        "country": "United States",
        "fetched_at": "2026-05-28T11:30:00",
        "momentum_score": 0,
        "earnings_en_45d": 0,
        "ex_div_en_45d": 0,
        "eventos_macro_en_45d": 0,
        "universes_json": json.dumps([]),
        "momentum_signals_json": json.dumps([]),
        "eventos_macro_json": json.dumps([]),
        "flags_legibles_json": json.dumps([]),
    }
    defaults.update(override)
    return defaults


def _zone_defaults(**override):
    defaults = {
        "zone_id": 0,
        "is_best": 1,
        "is_valid": 1,
        "center_price": 100.0,
        "lower_bound": 99.0,
        "upper_bound": 101.0,
        "score": 10.0,
        "distance_pct": 0.0,
        "has_dynamic_confirmer": 1,
        "elements_json": json.dumps([]),
        "rejection_reason": None,
    }
    defaults.update(override)
    return defaults


@pytest.fixture
def synthetic_db(tmp_path):
    """DB con 2 runs + 5 candidatos (3 con best_zone, 1 NOSCORE, 1 NOZONE)."""
    db = tmp_path / "synthetic.db"
    with _connect(db) as conn:
        # Run 1 (viejo)
        _insert(
            conn,
            "runs",
            run_id="run-1",
            started_at="2026-05-27T19:00:00",
            finished_at="2026-05-27T19:30:00",
            universe_size=100,
            candidates_passed=5,
            status="completed",
            universes_json=json.dumps(["sp500"]),
        )
        # Run 2 (reciente)
        _insert(
            conn,
            "runs",
            run_id="run-2",
            started_at="2026-05-28T11:00:00",
            finished_at="2026-05-28T11:30:00",
            universe_size=200,
            candidates_passed=10,
            status="completed",
            universes_json=json.dumps(["sp500", "nasdaq100"]),
        )

        # AAPL: T1 US Tech score=10.5 + earnings_45d
        _insert(
            conn,
            "candidates",
            **_candidate_defaults(
                run_id="run-2",
                ticker="AAPL",
                spot=200.0,
                momentum_score=2,
                earnings_en_45d=1,
                universes_json=json.dumps(["sp500", "nasdaq100"]),
                momentum_signals_json=json.dumps(["rsi"]),
                flags_legibles_json=json.dumps(["Earnings en 10 días"]),
                earnings_date="2026-06-10",
                strike_aggressive=205.0,
                strike_natural=200.0,
                strike_conservative=195.0,
                strike_grid_unit=1.0,
                sma_50w=190.0,
                sma_200w=180.0,
                rsi_d=45.0,
                rsi_w=50.0,
                atr_14=2.5,
                hv_percentile_52w=60.0,
                market_cap=3.5e12,
            ),
        )
        _insert(
            conn,
            "support_zones",
            **_zone_defaults(
                run_id="run-2",
                ticker="AAPL",
                center_price=195.0,
                lower_bound=193.0,
                upper_bound=197.0,
                score=10.5,
                distance_pct=0.015,
                elements_json=json.dumps(
                    [
                        {
                            "price": 193.0,
                            "element": "sma_200w",
                            "points": 0.0,
                            "metadata": {},
                        },
                        {
                            "price": 196.0,
                            "element": "polarity",
                            "points": 0.0,
                            "metadata": {"pivot_date": "2025-01-15"},
                        },
                    ]
                ),
            ),
        )

        # MSFT: T1 US Tech score=8.0 + ex_div_45d + macro_45d
        _insert(
            conn,
            "candidates",
            **_candidate_defaults(
                run_id="run-2",
                ticker="MSFT",
                spot=400.0,
                momentum_score=1,
                ex_div_en_45d=1,
                eventos_macro_en_45d=1,
                universes_json=json.dumps(["sp500"]),
                eventos_macro_json=json.dumps(
                    [{"date": "2026-06-15", "kind": "fomc", "description": "FOMC"}]
                ),
                flags_legibles_json=json.dumps(["Ex-dividend en 5 días ($0.75)"]),
                ex_div_date="2026-06-02",
                ex_div_amount=0.75,
                strike_aggressive=405.0,
                strike_natural=400.0,
                strike_conservative=395.0,
                strike_grid_unit=1.0,
            ),
        )
        _insert(
            conn,
            "support_zones",
            **_zone_defaults(
                run_id="run-2",
                ticker="MSFT",
                center_price=395.0,
                lower_bound=393.0,
                upper_bound=397.0,
                score=8.0,
                distance_pct=0.0125,
                elements_json=json.dumps(
                    [{"price": 394.0, "element": "hvn", "points": 0.0, "metadata": {}}]
                ),
            ),
        )

        # BARC.L: T2 UK Financial score=15.0 sin eventos
        _insert(
            conn,
            "candidates",
            **_candidate_defaults(
                run_id="run-2",
                ticker="BARC.L",
                tipo_T="T2",
                spot=2000.0,
                sector="Financial Services",
                country="United Kingdom",
                universes_json=json.dumps(["stoxx600"]),
                strike_aggressive=2100.0,
                strike_natural=2000.0,
                strike_conservative=1900.0,
                strike_grid_unit=50.0,
            ),
        )
        _insert(
            conn,
            "support_zones",
            **_zone_defaults(
                run_id="run-2",
                ticker="BARC.L",
                center_price=1950.0,
                lower_bound=1900.0,
                upper_bound=2000.0,
                score=15.0,
                distance_pct=0.0,
                elements_json=json.dumps(
                    [{"price": 1925.0, "element": "polarity", "points": 0.0, "metadata": {}}]
                ),
            ),
        )

        # NOZONE: pasa_paso_2=0 — no debe aparecer en load_run_candidates
        _insert(
            conn,
            "candidates",
            **_candidate_defaults(
                run_id="run-2",
                ticker="NOZONE",
                spot=100.0,
                pasa_paso_2=0,
                sector="Health Care",
                universes_json=json.dumps(["sp500"]),
            ),
        )

        # NOSCORE: pasa_paso_2=1 PERO sin support_zones row (edge case LEFT JOIN)
        _insert(
            conn,
            "candidates",
            **_candidate_defaults(
                run_id="run-2",
                ticker="NOSCORE",
                spot=50.0,
                sector="Industrials",
                country="France",
                momentum_score=1,
                universes_json=json.dumps(["stoxx600"]),
                strike_aggressive=52.0,
                strike_natural=50.0,
                strike_conservative=48.0,
                strike_grid_unit=0.5,
            ),
        )

    return db
