"""Punto de entrada principal del screening diario.

Uso:
    python -m puts_screener.run
    python -m puts_screener.run --no-persist
    python -m puts_screener.run --refresh-universe
    python -m puts_screener.run --skip-reports
    python -m puts_screener.run --macro-calendar path/to/calendar.yaml
"""

import argparse
import logging
import sys
from pathlib import Path

from puts_screener.final_pipeline import run_final_pipeline
from puts_screener.providers.factory import build_default_data_service
from puts_screener.screening_pipeline import run_screening
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
        help="Run only Paso 1 (no Paso 2/3 ni reportes)",
    )
    parser.add_argument(
        "--skip-reports", action="store_true", help="Don't generate CSV/HTML reports"
    )
    parser.add_argument(
        "--macro-calendar",
        type=str,
        default="data/macro_calendar.yaml",
        help="Path to the macro calendar YAML",
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

    if args.skip_support_detection:
        # Solo Paso 1: la spec no contempla "Paso 1 + Paso 3" sin Paso 2.
        run_id, _ = run_screening(
            universe=universe,
            data_service=data_service,
            max_workers=args.max_workers,
            persist=not args.no_persist,
        )
    else:
        run_id, _ = run_final_pipeline(
            universe=universe,
            data_service=data_service,
            persist=not args.no_persist,
            generate_reports=not args.skip_reports,
            max_workers=args.max_workers,
            macro_calendar_path=Path(args.macro_calendar),
        )

    if run_id:
        logger.info("Results in data/screening_history.db, run_id=%s", run_id)
    else:
        logger.info("Dry run completed (no persistence)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
