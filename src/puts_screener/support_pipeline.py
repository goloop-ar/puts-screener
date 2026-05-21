"""Pipeline del Paso 2: detección de soportes en paralelo sobre los candidatos del Paso 1.

Procesa solo los `ScreenedCandidate` con `pasa_filtros_paso_1=True`. Errores aislados por
candidato (un ticker que rompe no tumba la corrida). Ver §9 de la spec 03.
"""

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from puts_screener.models_screening import ScreenedCandidate
from puts_screener.models_support import SupportAnalysis, SupportedCandidate
from puts_screener.persistence import save_support_analysis
from puts_screener.providers.service import DataService
from puts_screener.support_scoring import analyze_supports

logger = logging.getLogger(__name__)

_EMPTY_ANALYSIS = SupportAnalysis(valid_zones=[], rejected_zones=[], best_zone=None)


def _process_candidate(
    candidate: ScreenedCandidate, data_service: DataService
) -> SupportedCandidate:
    """Analiza un candidato. Si rompe, devuelve SupportedCandidate con error y pasa_paso_2=False."""
    try:
        analysis = analyze_supports(candidate, data_service)
        return SupportedCandidate(
            screened=candidate,
            analysis=analysis,
            pasa_paso_2=analysis.best_zone is not None,
        )
    except Exception as exc:
        msg = f"{type(exc).__name__}: {str(exc)[:120]}"
        logger.warning("[%s] support detection failed: %s", candidate.ticker, msg)
        return SupportedCandidate(
            screened=candidate,
            analysis=SupportAnalysis(valid_zones=[], rejected_zones=[], best_zone=None),
            pasa_paso_2=False,
            errors=[msg],
        )


def run_support_detection(
    screened_candidates: list[ScreenedCandidate],
    data_service: DataService,
    max_workers: int = 8,
    persist: bool = True,
    run_id: str | None = None,
) -> tuple[str | None, list[SupportedCandidate]]:
    """Corre el Paso 2 sobre los candidatos que pasaron el Paso 1 (§9).

    Returns:
        (run_id, supported_candidates). Si `persist=True` y `run_id` viene None, se crea un
        UUID nuevo; si viene con valor, se reutiliza (espeja al Paso 1).
    """
    eligible = [c for c in screened_candidates if c.pasa_filtros_paso_1]
    started_at = datetime.now()
    logger.info(
        "Starting support detection: %d eligible candidates, %d workers",
        len(eligible),
        max_workers,
    )

    supported: list[SupportedCandidate] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_process_candidate, c, data_service): c for c in eligible}
        for future in as_completed(futures):
            supported.append(future.result())

    passed = sum(1 for s in supported if s.pasa_paso_2)
    duration = (datetime.now() - started_at).total_seconds()
    logger.info("=" * 60)
    logger.info("Support detection complete in %.1fs", duration)
    logger.info("  Eligible (passed Paso 1): %d", len(eligible))
    logger.info("  Passed Paso 2 (best_zone found): %d", passed)

    result_run_id = run_id
    if persist:
        if result_run_id is None:
            result_run_id = str(uuid.uuid4())
        save_support_analysis(result_run_id, supported)
        logger.info("  Run id: %s", result_run_id)

    return result_run_id, supported
