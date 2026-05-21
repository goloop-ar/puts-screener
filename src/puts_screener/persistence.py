"""Capa de persistencia de runs y candidatos en SQLite.

Path por default: data/screening_history.db
Override via env: PUTS_SCREENER_DB_PATH
"""

import json
import logging
import os
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from puts_screener.models_screening import ScreenedCandidate

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path("data/screening_history.db")

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    universe_size INTEGER NOT NULL,
    candidates_passed INTEGER,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS candidates (
    run_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    tipo_T TEXT,
    pasa_filtros_paso_1 INTEGER NOT NULL,
    spot REAL,
    sma_50w REAL,
    sma_200w REAL,
    rsi_d REAL,
    rsi_d_3d_ago REAL,
    rsi_w REAL,
    rsi_w_2w_ago REAL,
    macd_state TEXT,
    macd_hist_3d_ago REAL,
    momentum_score INTEGER,
    atr_14 REAL,
    hv_percentile_52w REAL,
    price_target_upside_pct REAL,
    recommendation_buy_ratio REAL,
    downgrades_6w_count INTEGER,
    market_cap REAL,
    sector TEXT,
    country TEXT,
    fetched_at TEXT NOT NULL,
    motivos_rechazo TEXT,
    errors TEXT,
    PRIMARY KEY (run_id, ticker),
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_candidates_pasa ON candidates(pasa_filtros_paso_1, run_id);
CREATE INDEX IF NOT EXISTS idx_candidates_ticker ON candidates(ticker);
CREATE INDEX IF NOT EXISTS idx_candidates_tipo ON candidates(tipo_T, run_id);
"""

_CANDIDATE_COLUMNS = (
    "run_id",
    "ticker",
    "tipo_T",
    "pasa_filtros_paso_1",
    "spot",
    "sma_50w",
    "sma_200w",
    "rsi_d",
    "rsi_d_3d_ago",
    "rsi_w",
    "rsi_w_2w_ago",
    "macd_state",
    "macd_hist_3d_ago",
    "momentum_score",
    "atr_14",
    "hv_percentile_52w",
    "price_target_upside_pct",
    "recommendation_buy_ratio",
    "downgrades_6w_count",
    "market_cap",
    "sector",
    "country",
    "fetched_at",
    "motivos_rechazo",
    "errors",
)
_INSERT_CANDIDATE_SQL = (
    f"INSERT INTO candidates ({', '.join(_CANDIDATE_COLUMNS)}) "
    f"VALUES ({', '.join(['?'] * len(_CANDIDATE_COLUMNS))})"
)


def _get_db_path() -> Path:
    """Resuelve el path del DB respetando PUTS_SCREENER_DB_PATH."""
    env_path = os.getenv("PUTS_SCREENER_DB_PATH")
    return Path(env_path) if env_path else DEFAULT_DB_PATH


@contextmanager
def _connect(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Abre la conexión, crea el schema si hace falta y commitea al salir."""
    path = db_path or _get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_SCHEMA_SQL)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _candidate_row(run_id: str, c: ScreenedCandidate) -> tuple:
    """Aplana un ScreenedCandidate a la tupla de valores para el INSERT."""
    return (
        run_id,
        c.ticker,
        c.classification.tipo if c.classification else None,
        1 if c.pasa_filtros_paso_1 else 0,
        c.spot,
        c.sma_50w,
        c.sma_200w,
        c.rsi_d,
        c.rsi_d_3d_ago,
        c.rsi_w,
        c.rsi_w_2w_ago,
        c.macd_state,
        c.macd_hist_3d_ago,
        c.momentum_score,
        c.atr_14,
        c.hv_percentile_52w,
        c.price_target_upside_pct,
        c.recommendation_buy_ratio,
        c.downgrades_6w_count,
        c.profile.market_cap_usd,
        c.profile.sector,
        c.profile.country,
        c.fetched_at.isoformat(),
        json.dumps(c.motivos_rechazo),
        json.dumps(c.errors),
    )


def save_run(
    candidates: list[ScreenedCandidate],
    universe_size: int,
    started_at: datetime,
    db_path: Path | None = None,
) -> str:
    """Persiste una corrida completa y devuelve el run_id (UUID)."""
    run_id = str(uuid.uuid4())
    passed = sum(1 for c in candidates if c.pasa_filtros_paso_1)

    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO runs "
            "(run_id, started_at, finished_at, universe_size, candidates_passed, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                run_id,
                started_at.isoformat(),
                datetime.now().isoformat(),
                universe_size,
                passed,
                "completed",
            ),
        )
        for candidate in candidates:
            conn.execute(_INSERT_CANDIDATE_SQL, _candidate_row(run_id, candidate))

    logger.info("Saved run %s: %d candidates, %d passed", run_id, len(candidates), passed)
    return run_id


def list_runs(limit: int = 30, db_path: Path | None = None) -> list[dict]:
    """Lista las últimas N corridas con metadatos."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_run_candidates(
    run_id: str,
    only_passed: bool = False,
    db_path: Path | None = None,
) -> list[dict]:
    """Devuelve los candidatos de una corrida como dicts planos (sin reconstruir OHLCV)."""
    query = "SELECT * FROM candidates WHERE run_id = ?"
    if only_passed:
        query += " AND pasa_filtros_paso_1 = 1"
    query += " ORDER BY momentum_score DESC, ticker ASC"

    with _connect(db_path) as conn:
        rows = conn.execute(query, (run_id,)).fetchall()

    result = []
    for row in rows:
        d = dict(row)
        d["motivos_rechazo"] = json.loads(d["motivos_rechazo"]) if d["motivos_rechazo"] else []
        d["errors"] = json.loads(d["errors"]) if d["errors"] else []
        d["pasa_filtros_paso_1"] = bool(d["pasa_filtros_paso_1"])
        result.append(d)
    return result
