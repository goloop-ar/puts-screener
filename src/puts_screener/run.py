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
from datetime import datetime
from pathlib import Path

from puts_screener.final_pipeline import run_final_pipeline
from puts_screener.providers.factory import build_default_data_service
from puts_screener.screening_pipeline import run_screening
from puts_screener.universe_builder import SUPPORTED_UNIVERSES, build_universe

LOG_DIR = Path("logs")
_CONSOLE_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
_FILE_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s"


def _configure_logging(log_dir: Path = LOG_DIR, timestamp: datetime | None = None) -> Path:
    """Logging dual: consola (INFO, stderr, sin cambios) + archivo (DEBUG, más verboso).

    Adjunta ambos handlers al logger raíz; como todos los loggers (la app y third-party
    como yfinance/urllib3/requests) propagan al raíz por default, todo termina también en
    el archivo. Devuelve el path del log.
    """
    timestamp = timestamp or datetime.now()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"screening_{timestamp:%Y-%m-%d_%H%M}.log"

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)  # gating fino por handler

    console = logging.StreamHandler()  # stderr
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(_CONSOLE_FORMAT))

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(_FILE_FORMAT))

    root.addHandler(console)
    root.addHandler(file_handler)
    return log_path


def _parse_universes(value: str) -> list[str]:
    """Parsea el CSV de `--universe` a una lista validada. Lanza ArgumentTypeError si falla."""
    names = [v.strip().lower() for v in value.split(",") if v.strip()]
    if not names:
        raise argparse.ArgumentTypeError(
            f"--universe vacío. Válidos: {', '.join(SUPPORTED_UNIVERSES)}"
        )
    invalid = [n for n in names if n not in SUPPORTED_UNIVERSES]
    if invalid:
        raise argparse.ArgumentTypeError(
            f"universo(s) inválido(s): {', '.join(invalid)}. "
            f"Válidos: {', '.join(SUPPORTED_UNIVERSES)}"
        )
    return names


def build_arg_parser() -> argparse.ArgumentParser:
    """Construye el parser de CLI (extraído para poder testearlo sin correr el pipeline)."""
    parser = argparse.ArgumentParser(description="Daily puts screener")
    parser.add_argument("--no-persist", action="store_true", help="Don't save to SQLite (dry run)")
    parser.add_argument(
        "--universe",
        type=_parse_universes,
        default=["sp500"],
        help=(
            "Universos a screenear, CSV. Soportados: "
            f"{', '.join(SUPPORTED_UNIVERSES)} (default: sp500). "
            "Ej: --universe sp500,nasdaq100"
        ),
    )
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
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()

    log_path = _configure_logging()
    logger = logging.getLogger(__name__)
    logger.info("Logging to %s", log_path)

    logger.info("Building universe...")
    universe = build_universe(universes=args.universe, refresh=args.refresh_universe)
    logger.info("Universos: %s → %d tickers únicos", ", ".join(args.universe), len(universe))

    if args.limit:
        # Recorta a los primeros N tickers (orden alfabético del dict) preservando los tags.
        universe = dict(list(universe.items())[: args.limit])
        logger.info("Limited to first %d tickers (--limit)", len(universe))

    data_service = build_default_data_service()

    if args.skip_support_detection:
        # Solo Paso 1: la spec no contempla "Paso 1 + Paso 3" sin Paso 2.
        run_id, _ = run_screening(
            universe=universe,
            data_service=data_service,
            max_workers=args.max_workers,
            persist=not args.no_persist,
            requested_universes=args.universe,
        )
    else:
        run_id, _ = run_final_pipeline(
            universe=universe,
            data_service=data_service,
            persist=not args.no_persist,
            generate_reports=not args.skip_reports,
            max_workers=args.max_workers,
            macro_calendar_path=Path(args.macro_calendar),
            requested_universes=args.universe,
        )

    if run_id:
        logger.info("Results in data/screening_history.db, run_id=%s", run_id)
    else:
        logger.info("Dry run completed (no persistence)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
