"""Punto de entrada principal del screening diario.

Uso:
    python -m puts_screener.run
    python -m puts_screener.run --no-persist
    python -m puts_screener.run --refresh-universe
"""

import argparse
import logging
import sys

from puts_screener.providers.factory import build_default_data_service
from puts_screener.screening_pipeline import run_screening
from puts_screener.support_pipeline import run_support_detection
from puts_screener.universe_builder import build_universe


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily puts screener")
    parser.add_argument("--no-persist", action="store_true", help="Don't save to SQLite (dry run)")
    parser.add_argument(
        "--refresh-universe", action="store_true", help="Force refresh universe cache"
    )
    parser.add_argument("--max-workers", type=int, default=8, help="Parallel workers (default: 8)")
    parser.add_argument(
        "--limit", type=int, default=None, help="Limit universe to N tickers (for testing)"
    )
    parser.add_argument(
        "--skip-support-detection",
        action="store_true",
        help="Skip Paso 2 (support detection); run only Paso 1 filters",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    logger = logging.getLogger(__name__)

    logger.info("Building universe...")
    universe = build_universe(refresh=args.refresh_universe)
    logger.info("Universe: %d tickers", len(universe))

    if args.limit:
        universe = universe[: args.limit]
        logger.info("Limited to first %d tickers (--limit)", len(universe))

    data_service = build_default_data_service()

    run_id, candidates = run_screening(
        universe=universe,
        data_service=data_service,
        max_workers=args.max_workers,
        persist=not args.no_persist,
    )

    if not args.skip_support_detection:
        run_id, supported = run_support_detection(
            screened_candidates=candidates,
            data_service=data_service,
            max_workers=args.max_workers,
            persist=not args.no_persist,
            run_id=run_id,
        )
        n_paso_2 = sum(1 for s in supported if s.pasa_paso_2)
        logger.info("=" * 60)
        logger.info("PIPELINE SUMMARY")
        logger.info(
            "  Passed Paso 1 (filtros): %d", sum(1 for c in candidates if c.pasa_filtros_paso_1)
        )
        logger.info("  Passed Paso 2 (soporte fuerte): %d", n_paso_2)

    if run_id:
        logger.info("Results in data/screening_history.db, run_id=%s", run_id)
    else:
        logger.info("Dry run completed (no persistence)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
