"""Smoke test manual de providers. Hace llamadas reales a APIs.

Uso:
    python -m puts_screener.smoke_test_providers

Requiere:
    - Conexión a internet
    - Opcional: FINNHUB_API_KEY en .env (sino, Finnhub se reporta como disabled)
"""

import logging
from datetime import date, timedelta

from puts_screener.providers.factory import build_default_data_service

logger = logging.getLogger(__name__)

TICKERS = ["AAPL", "NVDA", "ASML.AS", "NESN.SW"]


def run_smoke_test() -> int:
    """Corre el smoke test. Devuelve 0 si todo OK, 1 si hubo errores críticos.

    "Crítico" = al menos un método falló para un ticker que esperábamos exitoso.
    Si Finnhub está deshabilitado por falta de key, los métodos que solo lo tienen
    a él fallan esperablemente y no cuentan como crítico.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    svc = build_default_data_service()

    end = date.today()
    start = end - timedelta(days=30)

    rows: list[dict] = []
    critical_failures = 0

    for ticker in TICKERS:
        for method_name, callable_, requires_finnhub in [
            ("ohlcv", lambda t: svc.get_ohlcv(t, start, end), False),
            ("profile", lambda t: svc.get_company_profile(t), False),
            ("financ.", lambda t: svc.get_financials(t), False),
            ("analyst", lambda t: svc.get_analyst_data(t), True),
            ("ratings", lambda t: svc.get_rating_changes(t), True),
            ("earnings", lambda t: svc.get_upcoming_earnings(t), False),
        ]:
            result = _try(callable_, ticker)
            rows.append({"ticker": ticker, "method": method_name, **result})
            if result["status"] == "FAIL" and not requires_finnhub:
                critical_failures += 1

    _print_table(rows)

    print(f"\nCritical failures: {critical_failures}")
    return 0 if critical_failures == 0 else 1


def _try(callable_, ticker: str) -> dict:
    try:
        result = callable_(ticker)
        return {"status": "OK", "summary": _summarize(result), "error": ""}
    except Exception as exc:
        msg = str(exc)[:80]
        return {"status": "FAIL", "summary": "", "error": msg}


def _summarize(result) -> str:
    """Resumen corto del resultado para la tabla."""
    import pandas as pd

    if result is None:
        return "None"
    if isinstance(result, pd.DataFrame):
        return f"DataFrame {result.shape[0]}r x {result.shape[1]}c"
    if isinstance(result, list):
        return f"list len={len(result)}"
    return f"{type(result).__name__}(...)"


def _print_table(rows: list[dict]) -> None:
    """Imprime una tabla simple alineada."""
    headers = ["ticker", "method", "status", "summary", "error"]
    widths = {h: max(len(h), max(len(str(r[h])) for r in rows)) for h in headers}

    def fmt_row(r):
        return "  ".join(str(r[h]).ljust(widths[h]) for h in headers)

    print()
    print(fmt_row({h: h.upper() for h in headers}))
    print("-" * (sum(widths.values()) + 2 * (len(headers) - 1)))
    for r in rows:
        print(fmt_row(r))


if __name__ == "__main__":
    import sys

    sys.exit(run_smoke_test())
