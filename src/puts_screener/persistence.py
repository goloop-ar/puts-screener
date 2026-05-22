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

from puts_screener.models_final import FinalCandidate
from puts_screener.models_screening import ScreenedCandidate
from puts_screener.models_support import SupportedCandidate, SupportLevel, SupportZone

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

CREATE TABLE IF NOT EXISTS support_zones (
    run_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    zone_id INTEGER NOT NULL,
    is_best INTEGER NOT NULL,
    center_price REAL NOT NULL,
    lower_bound REAL NOT NULL,
    upper_bound REAL NOT NULL,
    score INTEGER NOT NULL,
    distance_pct REAL NOT NULL,
    has_dynamic_confirmer INTEGER NOT NULL,
    elements_json TEXT NOT NULL,
    is_valid INTEGER NOT NULL,
    rejection_reason TEXT,
    PRIMARY KEY (run_id, ticker, zone_id),
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_support_zones_best ON support_zones(run_id, is_best);
CREATE INDEX IF NOT EXISTS idx_support_zones_valid ON support_zones(run_id, is_valid);
"""

_SUPPORT_ZONE_COLUMNS = (
    "run_id",
    "ticker",
    "zone_id",
    "is_best",
    "center_price",
    "lower_bound",
    "upper_bound",
    "score",
    "distance_pct",
    "has_dynamic_confirmer",
    "elements_json",
    "is_valid",
    "rejection_reason",
)
_UPSERT_SUPPORT_ZONE_SQL = (
    f"INSERT OR REPLACE INTO support_zones ({', '.join(_SUPPORT_ZONE_COLUMNS)}) "
    f"VALUES ({', '.join(['?'] * len(_SUPPORT_ZONE_COLUMNS))})"
)

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

# Columnas de eventos binarios (Paso 3, spec 04) actualizadas por save_binary_events.
_BINARY_EVENT_COLUMNS = (
    "earnings_date",
    "dias_a_earnings",
    "earnings_en_45d",
    "ex_div_date",
    "dias_a_ex_div",
    "ex_div_en_45d",
    "ex_div_amount",
    "eventos_macro_en_45d",
    "eventos_macro_json",
    "tiene_eventos_binarios",
    "flags_legibles_json",
)
_UPDATE_BINARY_EVENTS_SQL = (
    "UPDATE candidates SET "
    + ", ".join(f"{col} = ?" for col in _BINARY_EVENT_COLUMNS)
    + " WHERE run_id = ? AND ticker = ?"
)


def _get_db_path() -> Path:
    """Resuelve el path del DB respetando PUTS_SCREENER_DB_PATH."""
    env_path = os.getenv("PUTS_SCREENER_DB_PATH")
    return Path(env_path) if env_path else DEFAULT_DB_PATH


# Columnas agregadas a `candidates` por specs posteriores a la creación de la tabla.
# Migración idempotente: un solo PRAGMA + ALTER de las que falten (§10.1 spec 04).
_CANDIDATE_MIGRATION_COLUMNS: dict[str, str] = {
    "pasa_paso_2": "INTEGER",  # spec 03
    "earnings_date": "TEXT",  # spec 04 — eventos binarios (ISO YYYY-MM-DD o NULL)
    "dias_a_earnings": "INTEGER",
    "earnings_en_45d": "INTEGER",
    "ex_div_date": "TEXT",
    "dias_a_ex_div": "INTEGER",
    "ex_div_en_45d": "INTEGER",
    "ex_div_amount": "REAL",
    "eventos_macro_en_45d": "INTEGER",
    "eventos_macro_json": "TEXT",
    "tiene_eventos_binarios": "INTEGER",
    "flags_legibles_json": "TEXT",
}


def _migrate_candidate_columns(conn: sqlite3.Connection) -> None:
    """Agrega las columnas faltantes a `candidates` (un PRAGMA, ALTER solo de las que falten)."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(candidates)").fetchall()}
    for column, sql_type in _CANDIDATE_MIGRATION_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE candidates ADD COLUMN {column} {sql_type}")


@contextmanager
def _connect(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Abre la conexión, crea el schema si hace falta y commitea al salir."""
    path = db_path or _get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_SCHEMA_SQL)
        _migrate_candidate_columns(conn)
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


def _elements_to_json(zone: SupportZone) -> str:
    """Serializa los SupportLevel de una zona a JSON (metadata ya tiene fechas ISO)."""
    return json.dumps(
        [
            {"price": e.price, "element": e.element, "points": e.points, "metadata": e.metadata}
            for e in zone.elements
        ]
    )


def _ordered_zones(sc: SupportedCandidate) -> list[tuple[SupportZone, bool, str | None]]:
    """Zonas en orden best→worst: válidas primero (ya rankeadas) y luego rechazadas."""
    ordered: list[tuple[SupportZone, bool, str | None]] = [
        (zone, True, None) for zone in sc.analysis.valid_zones
    ]
    ordered += [(zone, False, reason) for zone, reason in sc.analysis.rejected_zones]
    return ordered


def save_support_analysis(
    run_id: str,
    supported_candidates: list[SupportedCandidate],
    db_path: Path | None = None,
) -> None:
    """Persiste TODAS las zonas (válidas y rechazadas) y actualiza candidates.pasa_paso_2.

    zone_id = 0,1,2... en orden de mejor a peor. is_best=1 solo para zone_id=0 si es válida.
    Idempotente: re-correr con el mismo run_id reemplaza filas (INSERT OR REPLACE).
    """
    with _connect(db_path) as conn:
        for sc in supported_candidates:
            ticker = sc.screened.ticker
            for zone_id, (zone, is_valid, reason) in enumerate(_ordered_zones(sc)):
                is_best = 1 if (zone_id == 0 and is_valid) else 0
                conn.execute(
                    _UPSERT_SUPPORT_ZONE_SQL,
                    (
                        run_id,
                        ticker,
                        zone_id,
                        is_best,
                        zone.center_price,
                        zone.lower_bound,
                        zone.upper_bound,
                        zone.score,
                        zone.distance_pct,
                        1 if zone.has_dynamic_confirmer else 0,
                        _elements_to_json(zone),
                        1 if is_valid else 0,
                        reason,
                    ),
                )
            conn.execute(
                "UPDATE candidates SET pasa_paso_2 = ? WHERE run_id = ? AND ticker = ?",
                (1 if sc.pasa_paso_2 else 0, run_id, ticker),
            )

    logger.info(
        "Saved support analysis for run %s: %d candidates", run_id, len(supported_candidates)
    )


def load_support_zones(
    run_id: str,
    ticker: str | None = None,
    db_path: Path | None = None,
) -> list[SupportZone]:
    """Reconstruye SupportZone desde SQLite. Si ticker es None, devuelve todas las del run."""
    query = "SELECT * FROM support_zones WHERE run_id = ?"
    params: list = [run_id]
    if ticker is not None:
        query += " AND ticker = ?"
        params.append(ticker)
    query += " ORDER BY ticker ASC, zone_id ASC"

    with _connect(db_path) as conn:
        rows = conn.execute(query, params).fetchall()

    zones: list[SupportZone] = []
    for row in rows:
        elements = [
            SupportLevel(
                price=e["price"],
                element=e["element"],
                points=e["points"],
                metadata=e.get("metadata", {}),
            )
            for e in json.loads(row["elements_json"])
        ]
        zones.append(
            SupportZone(
                center_price=row["center_price"],
                lower_bound=row["lower_bound"],
                upper_bound=row["upper_bound"],
                score=row["score"],
                elements=elements,
                has_dynamic_confirmer=bool(row["has_dynamic_confirmer"]),
                distance_pct=row["distance_pct"],
            )
        )
    return zones


def _macro_events_to_json(report) -> str:
    return json.dumps(
        [
            {"date": e.date.isoformat(), "kind": e.kind, "description": e.description}
            for e in report.eventos_macro
        ]
    )


def save_binary_events(
    run_id: str,
    final_candidates: list[FinalCandidate],
    db_path: Path | None = None,
) -> None:
    """Actualiza las 11 columnas de eventos binarios en `candidates` para los tickers procesados.

    Política "persistir todo": se actualiza incluso a candidatos que no pasaron el Paso 2.
    Idempotente: re-correr con el mismo run_id sobrescribe los mismos valores (UPDATE por PK).
    """
    with _connect(db_path) as conn:
        for fc in final_candidates:
            be = fc.binary_events
            conn.execute(
                _UPDATE_BINARY_EVENTS_SQL,
                (
                    be.earnings_date.isoformat() if be.earnings_date is not None else None,
                    be.dias_a_earnings,
                    1 if be.earnings_en_45d else 0,
                    be.ex_div_date.isoformat() if be.ex_div_date is not None else None,
                    be.dias_a_ex_div,
                    1 if be.ex_div_en_45d else 0,
                    be.ex_div_amount,
                    1 if be.eventos_macro_en_45d else 0,
                    _macro_events_to_json(be),
                    1 if be.tiene_eventos_binarios else 0,
                    json.dumps(be.flags_legibles),
                    run_id,
                    fc.ticker,
                ),
            )

    logger.info("Saved binary events for run %s: %d candidates", run_id, len(final_candidates))
