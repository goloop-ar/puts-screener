"""Smoke test del Paso 2 (detección de soportes) contra APIs reales.

Uso: python -m puts_screener.smoke_test_supports

Corre el Paso 1 + Paso 2 sobre 10 tickers (sin persistir) e imprime una tabla con las
zonas válidas detectadas por candidato.
"""

import logging

from puts_screener.providers.factory import build_default_data_service
from puts_screener.screening_pipeline import run_screening
from puts_screener.support_pipeline import run_support_detection

_FALLBACK_TICKERS = [
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

    _, candidates = run_screening(_FALLBACK_TICKERS, data_service, max_workers=8, persist=False)
    _, supported = run_support_detection(candidates, data_service, max_workers=8, persist=False)

    header = f"{'ticker':<8}{'n_zonas_val':>12}{'mejor_score':>12}{'dist_pct':>10}  elementos"
    print(f"\n{header}")
    print("-" * 78)
    for s in sorted(supported, key=lambda x: x.screened.ticker):
        best = s.analysis.best_zone
        n_valid = len(s.analysis.valid_zones)
        if best is not None:
            score = str(best.score)
            dist = f"{best.distance_pct:.1%}"
            elements = ",".join(sorted({e.element for e in best.elements}))
        else:
            score, dist, elements = "-", "-", "(sin zona válida)"
        print(f"{s.screened.ticker:<8}{n_valid:>12}{score:>12}{dist:>10}  {elements}")

    print(f"\nPaso 1: {len(candidates)} procesados | Paso 2: {len(supported)} analizados")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
