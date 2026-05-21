"""Smoke test manual del pipeline completo. Hace llamadas reales a APIs.

Uso:
    python -m puts_screener.smoke_test_screening

Requiere conexión a internet. Tarda 1-3 minutos.
"""

import logging
import sys

from puts_screener.providers.factory import build_default_data_service
from puts_screener.screening_pipeline import run_screening

SMOKE_UNIVERSE = ["AAPL", "NVDA", "MSFT", "JPM", "ASML.AS", "NESN.SW", "SAP.DE"]


def run_smoke() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    data_service = build_default_data_service()

    # NO persistimos (smoke test, no contamina el DB).
    _run_id, candidates = run_screening(
        universe=SMOKE_UNIVERSE,
        data_service=data_service,
        max_workers=4,
        persist=False,
    )

    print()
    header = (
        f"{'TICKER':<10} {'TIPO':<6} {'PASA':<6} {'SCORE':<6} {'SPOT':<10} {'MOTIVOS_RECHAZO':<40}"
    )
    print(header)
    print("-" * 100)
    for c in sorted(candidates, key=lambda x: (-x.momentum_score, x.ticker)):
        tipo = c.classification.tipo if c.classification else "-"
        pasa = "YES" if c.pasa_filtros_paso_1 else "NO"
        motivos = "; ".join(c.motivos_rechazo[:2])[:40] if c.motivos_rechazo else ""
        row = (
            f"{c.ticker:<10} {tipo or '-':<6} {pasa:<6} "
            f"{c.momentum_score:<6} {c.spot:<10.2f} {motivos:<40}"
        )
        print(row)

    return 0


if __name__ == "__main__":
    sys.exit(run_smoke())
