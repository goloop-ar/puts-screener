"""Smoke test del pipeline final (Paso 1 → 2 → 3 + reportes) contra APIs reales.

Uso: python -m puts_screener.smoke_test_final

Corre el pipeline completo sobre 10 tickers SIN persistir, genera los reportes en `output/`
e imprime una tabla por candidato + los paths de los archivos generados.
"""

import logging

from puts_screener.config_reports import REPORT_LATEST_FILENAME, REPORT_OUTPUT_DIR
from puts_screener.final_pipeline import run_final_pipeline
from puts_screener.providers.factory import build_default_data_service

_TICKERS = [
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "META",
    "NVDA",
    "JPM",
    "JNJ",
    "PG",
    "KO",
]


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s | %(message)s")
    data_service = build_default_data_service()

    _, finals = run_final_pipeline(_TICKERS, data_service, persist=False, generate_reports=True)

    header = (
        f"{'ticker':<8}{'paso3?':>8}{'tipo':>6}{'score':>7}{'dist':>8}{'flags?':>8}  flags_legibles"
    )
    print(f"\n{header}")
    print("-" * 92)
    for fc in sorted(finals, key=lambda x: x.ticker):
        screened = fc.supported.screened
        zone = fc.supported.analysis.best_zone
        be = fc.binary_events
        passes = "YES" if fc.passes_all_steps else "no"
        tipo = screened.classification.tipo if screened.classification else "-"
        score = str(zone.score) if zone else "-"
        dist = f"{zone.distance_pct:.1%}" if zone else "-"
        has_flags = "YES" if be.tiene_eventos_binarios else "no"
        flags = " | ".join(be.flags_legibles)
        print(
            f"{fc.ticker:<8}{passes:>8}{tipo or '-':>6}{score:>7}{dist:>8}{has_flags:>8}  {flags}"
        )

    csv_latest = (REPORT_OUTPUT_DIR / f"{REPORT_LATEST_FILENAME}.csv").resolve()
    html_latest = (REPORT_OUTPUT_DIR / f"{REPORT_LATEST_FILENAME}.html").resolve()
    print(f"\nProcesados: {len(finals)}")
    print(f"CSV:  {csv_latest}")
    print(f"HTML: {html_latest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
