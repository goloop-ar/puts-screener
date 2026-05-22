"""Factory para construir un DataService con la configuración por defecto del proyecto."""

import logging

from .finnhub_provider import FinnhubProvider
from .service import DataService
from .yfinance_provider import YFinanceProvider

logger = logging.getLogger(__name__)


def build_default_data_service() -> DataService:
    """Construye el DataService con el orden de fallback por defecto del proyecto.

    Stack actual (post-smoke-test 2026-05-21):
    - OHLCV: yfinance único (Stooq quedó fuera por requerimiento de API key desde marzo 2026).
    - Profile: yfinance primario, Finnhub fallback (Finnhub free funciona solo para US).
    - Financials: yfinance único (Finnhub no lo provee en free).
    - Analyst data: yfinance primario, Finnhub fallback (Finnhub free roto en price_target).
    - Rating changes: yfinance único (Finnhub free roto en upgrade_downgrade).
    - Earnings: yfinance primario, Finnhub fallback.
    - Ex-dividend: yfinance único (Finnhub/Stooq no lo soportan).

    Finnhub se autodesactiva si FINNHUB_API_KEY no está seteada.
    """
    # Retry de errores transitorios (429/401/red) en métodos críticos: 3 intentos, backoff base 2s.
    yf = YFinanceProvider(max_attempts=3, base_delay=2.0)
    fh = FinnhubProvider()

    return DataService(
        ohlcv_providers=[yf],
        profile_providers=[yf, fh],
        financials_providers=[yf],
        analyst_providers=[yf, fh],
        rating_providers=[yf],
        earnings_providers=[yf, fh],
        historical_earnings_providers=[yf],
        ex_div_providers=[yf],
    )
