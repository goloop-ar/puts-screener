"""Tests de persistencia de soportes: round-trip, migración idempotente y orden (spec 03 §10)."""

import sqlite3

import numpy as np
import pandas as pd

from puts_screener.models_support import (
    SupportAnalysis,
    SupportedCandidate,
    SupportLevel,
    SupportZone,
)
from puts_screener.persistence import load_support_zones, save_support_analysis


def _tiny_ohlcv():
    idx = pd.bdate_range(end="2026-05-21", periods=5)
    close = np.full(5, 100.0)
    return pd.DataFrame(
        {"Open": close, "High": close + 1, "Low": close - 1, "Close": close, "Volume": 1_000_000},
        index=idx,
    )


def _zone(center, score, *, confirmer, distance, elements):
    return SupportZone(
        center_price=center,
        lower_bound=center - 1.0,
        upper_bound=center + 1.0,
        score=score,
        elements=elements,
        has_dynamic_confirmer=confirmer,
        distance_pct=distance,
    )


def test_round_trip(tmp_path, candidate_factory):
    db = tmp_path / "supports.db"
    valid = _zone(
        95.0,
        4,
        confirmer=True,
        distance=0.05,
        elements=[
            SupportLevel(
                price=95.0, element="hvn", points=1, metadata={"bucket_start": 1, "bucket_end": 2}
            ),
            SupportLevel(price=95.2, element="sma_200w", points=2),
        ],
    )
    rejected = _zone(
        80.0,
        2,
        confirmer=False,
        distance=0.20,
        elements=[
            SupportLevel(
                price=80.0, element="polarity", points=1, metadata={"pivot_date": "2026-01-01"}
            )
        ],
    )
    analysis = SupportAnalysis(
        valid_zones=[valid],
        rejected_zones=[(rejected, "score < 3 | sin confirmador dinámico")],
        best_zone=valid,
    )
    sc = SupportedCandidate(
        screened=candidate_factory(_tiny_ohlcv(), ticker="TEST"),
        analysis=analysis,
        pasa_paso_2=True,
    )

    save_support_analysis("run1", [sc], db_path=db)
    loaded = load_support_zones("run1", ticker="TEST", db_path=db)

    assert loaded == [valid, rejected]  # válida primero (zone_id=0), luego rechazada


def test_idempotent_migration(tmp_path, candidate_factory):
    db = tmp_path / "supports.db"
    sc = SupportedCandidate(
        screened=candidate_factory(_tiny_ohlcv(), ticker="X"),
        analysis=SupportAnalysis(valid_zones=[], rejected_zones=[], best_zone=None),
        pasa_paso_2=False,
    )

    save_support_analysis("run1", [sc], db_path=db)
    save_support_analysis("run1", [sc], db_path=db)  # segunda vez: no debe romper

    conn = sqlite3.connect(db)
    cols = [row[1] for row in conn.execute("PRAGMA table_info(candidates)").fetchall()]
    conn.close()
    assert cols.count("pasa_paso_2") == 1  # columna agregada una sola vez


def test_zones_saved_ordered_best_first(tmp_path, candidate_factory):
    db = tmp_path / "supports.db"
    best = _zone(
        98.0,
        5,
        confirmer=True,
        distance=0.03,
        elements=[SupportLevel(price=98.0, element="hvn", points=1)],
    )
    second = _zone(
        90.0,
        3,
        confirmer=True,
        distance=0.10,
        elements=[SupportLevel(price=90.0, element="hvn", points=1)],
    )
    analysis = SupportAnalysis(valid_zones=[best, second], rejected_zones=[], best_zone=best)
    sc = SupportedCandidate(
        screened=candidate_factory(_tiny_ohlcv(), ticker="TEST"),
        analysis=analysis,
        pasa_paso_2=True,
    )

    save_support_analysis("run1", [sc], db_path=db)

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT zone_id, is_best, score FROM support_zones WHERE run_id='run1' ORDER BY zone_id"
    ).fetchall()
    conn.close()

    assert [r["zone_id"] for r in rows] == [0, 1]
    assert rows[0]["is_best"] == 1 and rows[0]["score"] == 5
    assert rows[1]["is_best"] == 0 and rows[1]["score"] == 3
