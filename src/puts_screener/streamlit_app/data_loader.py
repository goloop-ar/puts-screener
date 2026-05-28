"""Lectura de runs/candidatos/best zones desde screening_history.db (spec 09 §X).

Todas las funciones son read-only: nunca escriben a la DB. Aceptan `db_path` opcional
(útil en tests); si None, resuelven vía `persistence._get_db_path()` que respeta
`PUTS_SCREENER_DB_PATH` env.
"""

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

from puts_screener.config_supports import SCORE_TIER_THRESHOLDS
from puts_screener.models_support import SupportLevel, SupportZone
from puts_screener.persistence import _get_db_path
from puts_screener.streamlit_app.models import CandidateDetail, CandidateRow, RunSummary

# Mapeo país (formato `CompanyProfile.country` de yfinance, full English name) → divisa
# nativa del exchange. UK queda en GBp (peniques) consistente con spec 06 §3.4.
_COUNTRY_TO_CURRENCY: dict[str, str] = {
    "United States": "USD",
    "United Kingdom": "GBp",
    "Germany": "EUR",
    "France": "EUR",
    "Netherlands": "EUR",
    "Spain": "EUR",
    "Italy": "EUR",
    "Switzerland": "CHF",
    "Sweden": "SEK",
    "Norway": "NOK",
    "Denmark": "DKK",
    "Finland": "EUR",
    "Belgium": "EUR",
    "Austria": "EUR",
    "Ireland": "EUR",
    "Portugal": "EUR",
}
_DEFAULT_CURRENCY = "USD"


def _open(db_path: Path | None) -> sqlite3.Connection:
    """Abre conexión read-only-friendly con Row factory; sin setup de schema."""
    path = db_path or _get_db_path()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _score_to_tier(score: float) -> int:
    """Mapea un score float a su tier 1-5 según `SCORE_TIER_THRESHOLDS` (config_supports).

    Réplica de `SupportZone.score_tier` @property para uso en queries que no reconstruyen
    el dataclass completo (load_run_candidates).
    """
    for tier in sorted(SCORE_TIER_THRESHOLDS.keys(), reverse=True):
        if score >= SCORE_TIER_THRESHOLDS[tier]:
            return tier
    return 1


def _currency_from_country(country: str | None) -> str:
    """Devuelve la divisa correspondiente al país. Default USD si no está mapeado."""
    return _COUNTRY_TO_CURRENCY.get(country or "", _DEFAULT_CURRENCY)


def list_recent_runs(limit: int = 30, db_path: Path | None = None) -> list[RunSummary]:
    """Lista los últimos `limit` runs ordenados por `started_at` descendente."""
    conn = _open(db_path)
    try:
        rows = conn.execute(
            "SELECT run_id, started_at, finished_at, universe_size, candidates_passed, "
            "universes_json FROM runs ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    return [
        RunSummary(
            run_id=r["run_id"],
            started_at=datetime.fromisoformat(r["started_at"]),
            finished_at=datetime.fromisoformat(r["finished_at"]) if r["finished_at"] else None,
            universe_size=r["universe_size"],
            candidates_passed=r["candidates_passed"] or 0,
            universes=tuple(json.loads(r["universes_json"])) if r["universes_json"] else (),
        )
        for r in rows
    ]


def load_run_candidates(run_id: str, db_path: Path | None = None) -> list[CandidateRow]:
    """Lista de `CandidateRow` del run, ordenada por score desc (NULLs al final).

    JOIN LEFT con `support_zones(is_best=1)`: candidates con `pasa_paso_2=1` pero sin
    best_zone (edge case) aparecen al final con `best_zone_*=None`. Solo incluye los
    que pasaron Paso 2 (`pasa_paso_2=1`). Vacío si el run no existe.
    """
    conn = _open(db_path)
    try:
        rows = conn.execute(
            "SELECT c.*, "
            "z.score AS z_score, z.distance_pct AS z_distance_pct "
            "FROM candidates c "
            "LEFT JOIN support_zones z "
            "  ON c.run_id = z.run_id AND c.ticker = z.ticker AND z.is_best = 1 "
            "WHERE c.run_id = ? AND c.pasa_paso_2 = 1 "
            "ORDER BY z.score DESC, c.ticker ASC",
            (run_id,),
        ).fetchall()
    finally:
        conn.close()

    results: list[CandidateRow] = []
    for r in rows:
        z_score = r["z_score"]
        if z_score is not None:
            score = float(z_score)
            tier: int | None = _score_to_tier(score)
            distance: float | None = float(r["z_distance_pct"])
        else:
            score = None
            tier = None
            distance = None

        results.append(
            CandidateRow(
                ticker=r["ticker"],
                tipo_T=r["tipo_T"] or "",
                spot=r["spot"],
                sector=r["sector"] or "",
                country=r["country"] or "",
                momentum_score=r["momentum_score"] or 0,
                universes=tuple(json.loads(r["universes_json"])) if r["universes_json"] else (),
                best_zone_score=score,
                best_zone_tier=tier,
                best_zone_distance_pct=distance,
                earnings_en_45d=bool(r["earnings_en_45d"]),
                ex_div_en_45d=bool(r["ex_div_en_45d"]),
                tiene_eventos_macro_en_45d=bool(r["eventos_macro_en_45d"]),
                strike_natural=r["strike_natural"],
                currency=_currency_from_country(r["country"]),
            )
        )
    return results


def load_best_zone(
    run_id: str,
    ticker: str,
    db_path: Path | None = None,
) -> SupportZone | None:
    """Devuelve la best zone del `(run_id, ticker)` reconstruida, o None.

    Usa el índice `idx_support_zones_best ON (run_id, is_best)`. Réplica de la lógica
    de reconstrucción de `persistence.load_support_zones` pero filtrando por `is_best=1`
    (el helper existente devuelve TODAS las zonas y no preserva el flag).
    """
    conn = _open(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM support_zones WHERE run_id = ? AND ticker = ? AND is_best = 1",
            (run_id, ticker),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return None

    elements = [
        SupportLevel(
            price=e["price"],
            element=e["element"],
            points=e.get("points", 0.0),
            metadata=e.get("metadata", {}),
        )
        for e in json.loads(row["elements_json"])
    ]
    return SupportZone(
        center_price=row["center_price"],
        lower_bound=row["lower_bound"],
        upper_bound=row["upper_bound"],
        score=row["score"],
        elements=elements,
        has_dynamic_confirmer=bool(row["has_dynamic_confirmer"]),
        distance_pct=row["distance_pct"],
    )


def load_candidate_detail(
    run_id: str,
    ticker: str,
    db_path: Path | None = None,
) -> CandidateDetail:
    """Combina la fila de `candidates` + la best_zone reconstruida + JSON parseados.

    Raises:
        ValueError: si no existe el `(run_id, ticker)` en candidates.
    """
    conn = _open(db_path)
    try:
        r = conn.execute(
            "SELECT * FROM candidates WHERE run_id = ? AND ticker = ?",
            (run_id, ticker),
        ).fetchone()
    finally:
        conn.close()

    if r is None:
        raise ValueError(f"ticker {ticker!r} not found in run {run_id!r}")

    best_zone = load_best_zone(run_id, ticker, db_path)
    universes = tuple(json.loads(r["universes_json"])) if r["universes_json"] else ()
    currency = _currency_from_country(r["country"])

    if best_zone is not None:
        best_zone_score: float | None = float(best_zone.score)
        best_zone_tier: int | None = best_zone.score_tier
        best_zone_distance_pct: float | None = best_zone.distance_pct
    else:
        best_zone_score = None
        best_zone_tier = None
        best_zone_distance_pct = None

    row = CandidateRow(
        ticker=r["ticker"],
        tipo_T=r["tipo_T"] or "",
        spot=r["spot"],
        sector=r["sector"] or "",
        country=r["country"] or "",
        momentum_score=r["momentum_score"] or 0,
        universes=universes,
        best_zone_score=best_zone_score,
        best_zone_tier=best_zone_tier,
        best_zone_distance_pct=best_zone_distance_pct,
        earnings_en_45d=bool(r["earnings_en_45d"]),
        ex_div_en_45d=bool(r["ex_div_en_45d"]),
        tiene_eventos_macro_en_45d=bool(r["eventos_macro_en_45d"]),
        strike_natural=r["strike_natural"],
        currency=currency,
    )

    eventos_macro = tuple(json.loads(r["eventos_macro_json"])) if r["eventos_macro_json"] else ()
    flags = tuple(json.loads(r["flags_legibles_json"])) if r["flags_legibles_json"] else ()
    momentum = tuple(json.loads(r["momentum_signals_json"])) if r["momentum_signals_json"] else ()

    return CandidateDetail(
        row=row,
        best_zone=best_zone,
        spot=r["spot"],
        sma_50w=r["sma_50w"],
        sma_200w=r["sma_200w"],
        rsi_d=r["rsi_d"],
        rsi_w=r["rsi_w"],
        atr_14=r["atr_14"],
        hv_percentile_52w=r["hv_percentile_52w"],
        market_cap=r["market_cap"],
        earnings_date=date.fromisoformat(r["earnings_date"]) if r["earnings_date"] else None,
        ex_div_date=date.fromisoformat(r["ex_div_date"]) if r["ex_div_date"] else None,
        ex_div_amount=r["ex_div_amount"],
        eventos_macro=eventos_macro,
        strikes={
            "aggressive": r["strike_aggressive"],
            "natural": r["strike_natural"],
            "conservative": r["strike_conservative"],
            "grid_unit": r["strike_grid_unit"],
        },
        flags_legibles=flags,
        momentum_signals=momentum,
    )
