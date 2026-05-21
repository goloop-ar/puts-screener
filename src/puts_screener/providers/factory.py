"""Factory para construir un DataService con la configuración por defecto del proyecto."""

import logging

from .finnhub_provider import FinnhubProvider
from .service import DataService
from .stooq import StooqProvider
from .yfinance_provider import YFinanceProvider

logger = logging.getLogger(__name__)


def build_default_data_service() -> DataService:
    """Construye el DataService con el orden de fallback por defecto del proyecto.

    Returns:
        DataService configurado con Stooq, yfinance y Finnhub.
        Finnhub se autodesactiva si FINNHUB_API_KEY no está seteada.
    """
    stooq = StooqProvider()
    yf = YFinanceProvider()
    fh = FinnhubProvider()  # se autodeshabilita si no hay key

    return DataService(
        ohlcv_providers=[stooq, yf],
        profile_providers=[yf, fh],
        financials_providers=[yf],
        analyst_providers=[fh],
        rating_providers=[fh],
        earnings_providers=[fh, yf],
    )
