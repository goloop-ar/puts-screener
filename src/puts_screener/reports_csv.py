"""Generación del CSV detallado por corrida (§7 de spec 04).

Una fila por candidato que pasó Paso 1 + Paso 2. 40 columnas en el orden exacto de §7.1
(la 40, `universes`, se agregó AL FINAL en Etapa 1 para no romper el orden previo).
Los helpers de label de elemento y de ordenamiento se comparten con `reports_html`.
"""

import csv
import logging
import shutil
from datetime import datetime
from pathlib import Path

from puts_screener.config_reports import (
    REPORT_FILENAME_PATTERN,
    REPORT_LATEST_FILENAME,
    REPORT_OUTPUT_DIR,
    TYPE_PRIORITY,
)
from puts_screener.models_final import FinalCandidate

logger = logging.getLogger(__name__)

# Mapeo de element name (interno) → label legible para reportes (§7.1 ejemplo).
_ELEMENT_LABELS = {
    "sma_200w": "SMA200W",
    "ema_200d": "EMA200D",
    "sma_200d": "SMA200D",
    "sma_50d": "SMA50D",
    "sma_50w": "SMA50W",
    "ema_50d": "EMA50D",
    "fib_618": "FIB_618",
    "fib_786": "FIB_786",
    "avwap_pivot_low": "AVWAP_pivot_low",
    "avwap_earnings": "AVWAP_earnings",
    "avwap_52w_high": "AVWAP_52w_high",
    "hvn": "HVN",
    "gap_unfilled": "GAP",
    "polarity": "POLARIDAD",
    "divergence": "DIVERGENCIA",
}

CSV_COLUMNS: tuple[str, ...] = (
    "ticker",
    "exchange",
    "sector",
    "country",
    "market_cap",
    "tipo_T",
    "justificacion_tipo",
    "spot",
    "zona_min",
    "zona_max",
    "zona_centro",
    "distancia_pct",
    "score_soporte",
    "n_elementos",
    "elementos_score",
    "confirmador_dinamico",
    "rsi_diario",
    "rsi_semanal",
    "macd_estado",
    "momentum_score",
    "sma50w_sobre_sma200w",
    "hv_percentile_52w",
    "price_target_consensus",
    "price_target_upside_pct",
    "recommendation_mean",
    "recommendation_buy_ratio",
    "downgrades_6w",
    "earnings_date",
    "dias_a_earnings",
    "earnings_en_45d",
    "ex_div_date",
    "dias_a_ex_div",
    "ex_div_en_45d",
    "ex_div_amount",
    "eventos_macro_en_45d",
    "eventos_macro_count",
    "tiene_eventos_binarios",
    "flags_legibles",
    "fetched_at",
    "universes",
    "momentum_signals",
)


def element_label(element: str) -> str:
    """Label legible de un elemento de soporte (fallback: el nombre en mayúsculas)."""
    return _ELEMENT_LABELS.get(element, element.upper())


def _sort_key(fc: FinalCandidate) -> tuple[int, int, float]:
    screened = fc.supported.screened
    zone = fc.supported.analysis.best_zone
    tipo = screened.classification.tipo if screened.classification else None
    return (
        TYPE_PRIORITY.get(tipo, 99),
        -(zone.score if zone else 0),
        zone.distance_pct if zone else 0.0,
    )


def sort_final_candidates(candidates: list[FinalCandidate]) -> list[FinalCandidate]:
    """Ordena por prioridad de tipo asc, score desc, distance_pct asc (§7.3 / §8.3)."""
    return sorted(candidates, key=_sort_key)


def _iso_or_none(value) -> str | None:
    return value.isoformat() if value is not None else None


def _build_row(fc: FinalCandidate) -> dict:
    screened = fc.supported.screened
    profile = screened.profile
    analyst = screened.analyst
    classification = screened.classification
    zone = fc.supported.analysis.best_zone
    be = fc.binary_events

    row = {
        "ticker": fc.ticker,
        "exchange": profile.exchange,
        "sector": profile.sector,
        "country": profile.country,
        "market_cap": profile.market_cap_usd,
        "tipo_T": classification.tipo if classification else None,
        "justificacion_tipo": classification.justificacion if classification else None,
        "spot": screened.spot,
        "zona_min": zone.lower_bound,
        "zona_max": zone.upper_bound,
        "zona_centro": zone.center_price,
        "distancia_pct": zone.distance_pct,
        "score_soporte": f"{zone.score:.1f}",
        "n_elementos": len(zone.elements),
        "elementos_score": " | ".join(element_label(e.element) for e in zone.elements),
        "confirmador_dinamico": zone.has_dynamic_confirmer,
        "rsi_diario": screened.rsi_d,
        "rsi_semanal": screened.rsi_w,
        "macd_estado": screened.macd_state,
        "momentum_score": screened.momentum_score,
        "sma50w_sobre_sma200w": screened.sma_50w > screened.sma_200w,
        "hv_percentile_52w": screened.hv_percentile_52w,
        "price_target_consensus": analyst.price_target_mean,
        "price_target_upside_pct": screened.price_target_upside_pct,
        "recommendation_mean": analyst.recommendation_mean,
        "recommendation_buy_ratio": screened.recommendation_buy_ratio,
        "downgrades_6w": screened.downgrades_6w_count,
        "earnings_date": _iso_or_none(be.earnings_date),
        "dias_a_earnings": be.dias_a_earnings,
        "earnings_en_45d": be.earnings_en_45d,
        "ex_div_date": _iso_or_none(be.ex_div_date),
        "dias_a_ex_div": be.dias_a_ex_div,
        "ex_div_en_45d": be.ex_div_en_45d,
        "ex_div_amount": be.ex_div_amount,
        "eventos_macro_en_45d": be.eventos_macro_en_45d,
        "eventos_macro_count": len(be.eventos_macro),
        "tiene_eventos_binarios": be.tiene_eventos_binarios,
        "flags_legibles": " | ".join(be.flags_legibles),
        "fetched_at": _iso_or_none(fc.fetched_at),
        "universes": "|".join(screened.universes),
        "momentum_signals": "|".join(screened.momentum_signals),
    }
    # None → "" (no "None"), explícito para no depender del comportamiento del módulo csv.
    return {key: ("" if value is None else value) for key, value in row.items()}


def write_csv_report(
    final_candidates: list[FinalCandidate],
    output_dir: Path = REPORT_OUTPUT_DIR,
    timestamp: datetime | None = None,
) -> Path:
    """Escribe el CSV de la corrida (timestamped + latest). Devuelve el path timestamped."""
    timestamp = timestamp or datetime.now()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    included = sort_final_candidates([fc for fc in final_candidates if fc.passes_all_steps])

    stem = REPORT_FILENAME_PATTERN.format(date=f"{timestamp:%Y-%m-%d}", time=f"{timestamp:%H%M}")
    timestamped = output_dir / f"{stem}.csv"
    latest = output_dir / f"{REPORT_LATEST_FILENAME}.csv"

    with timestamped.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for fc in included:
            writer.writerow(_build_row(fc))

    shutil.copyfile(timestamped, latest)
    logger.info("CSV report written: %s (%d candidates)", timestamped, len(included))
    return timestamped
