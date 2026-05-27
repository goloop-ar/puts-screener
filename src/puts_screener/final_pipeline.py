"""Pipeline final: encadena Paso 1 → Paso 2 → Paso 3 y genera reportes (§9 de spec 04).

El Paso 3 corre sobre TODOS los SupportedCandidate (no solo los que pasaron Paso 2): los flags
de eventos binarios también informan sobre los que no calificaron por soporte. Los reportes
filtran por `passes_all_steps` internamente.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path

from puts_screener.binary_events import BinaryEventsReport, check_binary_events, check_macro_events
from puts_screener.macro_calendar import MacroEvent, load_macro_calendar
from puts_screener.models_final import FinalCandidate
from puts_screener.models_support import SupportedCandidate
from puts_screener.persistence import save_binary_events
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
    final_candidates: list[FinalCandidate] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(_process_binary_events, s, data_service, today, macro_calendar)
            for s in supported
        ]
        for future in as_completed(futures):
            final_candidates.append(future.result())

    n_paso_1 = sum(1 for c in screened if c.pasa_filtros_paso_1)
    n_paso_2 = sum(1 for fc in final_candidates if fc.passes_all_steps)
    flagged = sum(1 for fc in final_candidates if fc.binary_events.tiene_eventos_binarios)

    logger.info("=" * 60)
    logger.info("PIPELINE SUMMARY (Paso 1 → 2 → 3)")
    logger.info("  Universe: %d", len(universe))
    logger.info("  Passed Paso 1 (filtros): %d", n_paso_1)
    logger.info("  Passed Paso 2 (soporte fuerte): %d", n_paso_2)
    logger.info("  Con eventos binarios flageados: %d", flagged)

    if persist and run_id is not None:
        save_binary_events(run_id, final_candidates)

    if generate_reports:
        timestamp = datetime.now()
        run_metadata = {
            "run_id": run_id,
            "universe_size": len(universe),
            "n_paso_1": n_paso_1,
            "n_paso_2": n_paso_2,
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
