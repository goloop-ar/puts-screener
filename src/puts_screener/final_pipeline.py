"""Pipeline final: encadena Paso 1 → Paso 2 → Paso 3 y genera reportes (§9 de spec 04).

El Paso 3 corre sobre TODOS los SupportedCandidate (no solo los que pasaron Paso 2): los flags
de eventos binarios también informan sobre los que no calificaron por soporte. Los reportes
filtran por `passes_all_steps` internamente.
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from puts_screener.binary_events import BinaryEventsReport, check_binary_events, check_macro_events
from puts_screener.classification_v2 import classify_candidate
from puts_screener.indicators import atr_series, rsi_daily_series
from puts_screener.macro_calendar import MacroEvent, load_macro_calendar
from puts_screener.models_final import FinalCandidate
from puts_screener.models_screening import TypeClassification
from puts_screener.models_support import SupportedCandidate
from puts_screener.persistence import save_binary_events, save_classification
from puts_screener.pivots import detect_pivots
from puts_screener.providers.service import DataService
from puts_screener.reports_csv import write_csv_report
from puts_screener.reports_html import write_html_report
from puts_screener.screening_pipeline import run_screening
from puts_screener.support_pipeline import run_support_detection

logger = logging.getLogger(__name__)

_VERSION = "0.1"
_DEFAULT_MACRO_CALENDAR = Path("data/macro_calendar.yaml")


def _empty_binary_report() -> BinaryEventsReport:
    return BinaryEventsReport(
        earnings_date=None,
        dias_a_earnings=None,
        earnings_en_45d=False,
        ex_div_date=None,
        dias_a_ex_div=None,
        ex_div_en_45d=False,
        ex_div_amount=None,
        eventos_macro=[],
        eventos_macro_en_45d=False,
        tiene_eventos_binarios=False,
        flags_legibles=[],
    )


def _process_binary_events(
    supported: SupportedCandidate,
    data_service: DataService,
    today: date,
    macro_calendar: list[MacroEvent],
) -> FinalCandidate:
    """Corre el Paso 3 para un candidato. Si rompe, devuelve un reporte vacío con error."""
    ticker = supported.screened.ticker
    try:
        currency = supported.screened.profile.currency
        report = check_binary_events(ticker, today, data_service, macro_calendar, currency=currency)
        return FinalCandidate(
            supported=supported, binary_events=report, fetched_at=datetime.now(), errors=[]
        )
    except Exception as exc:  # noqa: BLE001 — aislamiento por candidato, no rompe el pipeline
        msg = f"{type(exc).__name__}: {str(exc)[:120]}"
        logger.warning("[%s] check_binary_events failed: %s", ticker, msg)
        return FinalCandidate(
            supported=supported,
            binary_events=_empty_binary_report(),
            fetched_at=datetime.now(),
            errors=[msg],
        )


def _classify_supported(
    supported: list[SupportedCandidate],
    today_ts: pd.Timestamp,
) -> None:
    """Aplica classify_candidate sobre los SupportedCandidate que pasaron Paso 2.

    Muta in-place el `screened` con regime/triggers/primary/label/tipo (vía
    classification) + trigger_metadata_json. Errores aislados por candidato.
    """
    for sc in supported:
        if not sc.pasa_paso_2:
            continue
        screened = sc.screened
        try:
            ohlcv = screened.ohlcv_daily
            atr = atr_series(ohlcv)
            rsi = rsi_daily_series(ohlcv)
            pivots = detect_pivots(ohlcv, atr)
            best = sc.analysis.best_zone
            earnings_dates = [pd.Timestamp(e.date) for e in (screened.earnings_history or [])]
            # upcoming_earnings_in_window: el Paso 3 todavía no corrió. Conservador: False.
            result = classify_candidate(
                ohlcv=ohlcv,
                pivots=pivots,
                atr=atr,
                rsi_d=rsi,
                sma_50w=screened.sma_50w if screened.sma_50w else None,
                sma_200w=screened.sma_200w if screened.sma_200w else None,
                best_zone_score=best.score if best is not None else None,
                best_zone_distance_pct=best.distance_pct if best is not None else None,
                earnings_dates=earnings_dates,
                upcoming_earnings_in_window=False,
                today=today_ts,
            )
            screened.regime = result.regime
            screened.triggers = result.triggers
            screened.primary_trigger = result.primary_trigger
            screened.composite_label = result.composite_label
            screened.trigger_metadata_json = json.dumps(result.trigger_metadata, default=str)
            # Backcompat: poblar classification.tipo para reportes/persistencia legacy.
            screened.classification = TypeClassification(
                tipo=result.legacy_tipo,
                justificacion=result.composite_label,
                matches_multiple=[],
            )
        except Exception as exc:  # noqa: BLE001 — aislamiento por candidato
            msg = f"classify_candidate: {type(exc).__name__}: {str(exc)[:100]}"
            logger.warning("[%s] %s", screened.ticker, msg)
            screened.errors.append(msg)


def run_final_pipeline(
    universe: list[str] | dict[str, set[str]],
    data_service: DataService,
    persist: bool = True,
    generate_reports: bool = True,
    max_workers: int = 8,
    macro_calendar_path: Path = _DEFAULT_MACRO_CALENDAR,
    requested_universes: list[str] | None = None,
) -> tuple[str | None, list[FinalCandidate]]:
    """Corre el pipeline completo Paso 1 → 2 → 3 y (opcionalmente) genera reportes y persiste."""
    macro_calendar = load_macro_calendar(macro_calendar_path)

    run_id, screened = run_screening(
        universe,
        data_service,
        max_workers=max_workers,
        persist=persist,
        requested_universes=requested_universes,
    )
    run_id, supported = run_support_detection(
        screened, data_service, max_workers=max_workers, persist=persist, run_id=run_id
    )

    today = date.today()
    today_ts = pd.Timestamp(today)

    # Spec 10: clasificación dual (régimen + triggers) post-Paso 2 y antes del Paso 3.
    # Solo se aplica a candidatos que pasaron Paso 2 (best_zone válida).
    _classify_supported(supported, today_ts)

    if persist and run_id is not None:
        classified_for_save = [s.screened for s in supported if s.pasa_paso_2]
        save_classification(run_id, classified_for_save)

    # Filtro: solo los que tienen primary_trigger pasan a Paso 3 y reportes.
    supported_for_step3 = [
        s for s in supported if s.pasa_paso_2 and s.screened.primary_trigger is not None
    ]

    final_candidates: list[FinalCandidate] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(_process_binary_events, s, data_service, today, macro_calendar)
            for s in supported_for_step3
        ]
        for future in as_completed(futures):
            final_candidates.append(future.result())

    n_paso_1 = sum(1 for c in screened if c.pasa_filtros_paso_1)
    n_paso_2 = sum(1 for s in supported if s.pasa_paso_2)
    n_classified = sum(1 for s in supported if s.pasa_paso_2 and s.screened.primary_trigger)
    n_final = sum(1 for fc in final_candidates if fc.passes_all_steps)
    flagged = sum(1 for fc in final_candidates if fc.binary_events.tiene_eventos_binarios)

    logger.info("=" * 60)
    logger.info("PIPELINE SUMMARY (Paso 1 → 2 → clasificación → 3)")
    logger.info("  Universe: %d", len(universe))
    logger.info("  Passed Paso 1 (filtros): %d", n_paso_1)
    logger.info("  Passed Paso 2 (soporte fuerte): %d", n_paso_2)
    logger.info("  Con primary_trigger (spec 10): %d", n_classified)
    logger.info("  Passed all steps (Paso 3): %d", n_final)
    logger.info("  Con eventos binarios flageados: %d", flagged)

    if persist and run_id is not None:
        save_binary_events(run_id, final_candidates)

    if generate_reports:
        timestamp = datetime.now()
        run_metadata = {
            "run_id": run_id,
            "universe_size": len(universe),
            "n_paso_1": n_paso_1,
            "n_paso_2": n_final,  # candidatos que terminan en el reporte (passes_all_steps)
            "generated_at": timestamp.isoformat(timespec="seconds"),
            "version": _VERSION,
        }
        macro_window = check_macro_events(today, macro_calendar)
        csv_path = write_csv_report(final_candidates, timestamp=timestamp)
        html_path = write_html_report(
            final_candidates, run_metadata, timestamp=timestamp, macro_events=macro_window
        )
        logger.info("  CSV report:  %s", csv_path)
        logger.info("  HTML report: %s", html_path)

    return run_id, final_candidates
