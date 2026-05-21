"""Orquestador de providers con fallback por método."""

import logging
from datetime import date

import pandas as pd

from .base import DataProvider, NotSupportedError, ProviderError
from .models import (
    AnalystData,
    CompanyProfile,
    EarningsEvent,
    FinancialSnapshot,
    RatingChange,
)

logger = logging.getLogger(__name__)


class AllProvidersFailedError(ProviderError):
    """Todos los providers configurados para el método fallaron o no soportaban."""


class DataService:
    """Orquesta múltiples DataProviders con fallback por método.

    Para cada método del DataProvider, recibe una lista ordenada de providers.
    Itera en orden: primer éxito gana. Si todos fallan, lanza
    AllProvidersFailedError envolviendo el último error útil.
    """

    def __init__(
        self,
        ohlcv_providers: list[DataProvider],
        profile_providers: list[DataProvider],
        financials_providers: list[DataProvider],
        analyst_providers: list[DataProvider],
        rating_providers: list[DataProvider],
        earnings_providers: list[DataProvider],
    ) -> None:
        self._ohlcv = ohlcv_providers
        self._profile = profile_providers
        self._financials = financials_providers
        self._analyst = analyst_providers
        self._rating = rating_providers
        self._earnings = earnings_providers

    def get_ohlcv(self, ticker: str, start: date, end: date, interval: str = "1d") -> pd.DataFrame:
        return self._call_with_fallback(
            "get_ohlcv",
            self._ohlcv,
            ticker,
            lambda p: p.get_ohlcv(ticker, start, end, interval),
        )

    def get_company_profile(self, ticker: str) -> CompanyProfile:
        return self._call_with_fallback(
            "get_company_profile",
            self._profile,
            ticker,
            lambda p: p.get_company_profile(ticker),
        )

    def get_financials(self, ticker: str) -> FinancialSnapshot:
        return self._call_with_fallback(
            "get_financials",
            self._financials,
            ticker,
            lambda p: p.get_financials(ticker),
        )

    def get_analyst_data(self, ticker: str) -> AnalystData:
        return self._call_with_fallback(
            "get_analyst_data",
            self._analyst,
            ticker,
            lambda p: p.get_analyst_data(ticker),
        )

    def get_rating_changes(self, ticker: str, lookback_weeks: int = 6) -> list[RatingChange]:
        return self._call_with_fallback(
            "get_rating_changes",
            self._rating,
            ticker,
            lambda p: p.get_rating_changes(ticker, lookback_weeks),
        )

    def get_upcoming_earnings(
        self, ticker: str, lookforward_days: int = 60
    ) -> EarningsEvent | None:
        # get_upcoming_earnings puede retornar None legítimamente (no hay earnings
        # en ventana). Tratamos None como "éxito sin earnings", NO como fallo.
        return self._call_with_fallback(
            "get_upcoming_earnings",
            self._earnings,
            ticker,
            lambda p: p.get_upcoming_earnings(ticker, lookforward_days),
            allow_none=True,
        )

    def _call_with_fallback(
        self,
        method_name: str,
        providers: list[DataProvider],
        ticker: str,
        call: callable,
        allow_none: bool = False,
    ):
        if not providers:
            raise AllProvidersFailedError(f"No providers configured for {method_name}")

        last_error: Exception | None = None
        for provider in providers:
            if not provider.supports(method_name):
                logger.debug(
                    "skip %s for %s: not supported by %s",
                    method_name,
                    ticker,
                    provider.name,
                )
                continue
            try:
                result = call(provider)
                if result is None and not allow_none:
                    last_error = ProviderError(
                        f"{provider.name} returned None for {method_name}({ticker})"
                    )
                    logger.warning(str(last_error))
                    continue
                logger.info("%s for %s served by %s", method_name, ticker, provider.name)
                return result
            except (ProviderError, NotSupportedError) as exc:
                last_error = exc
                logger.warning(
                    "%s for %s failed on %s: %s",
                    method_name,
                    ticker,
                    provider.name,
                    exc,
                )
                continue
            except Exception as exc:
                # Errores no esperados (red, parsing): los tratamos como fallo
                # recuperable para no romper el fallback, pero los logueamos.
                last_error = exc
                logger.warning(
                    "%s for %s unexpected error on %s: %s (%s)",
                    method_name,
                    ticker,
                    provider.name,
                    exc,
                    type(exc).__name__,
                )
                continue

        raise AllProvidersFailedError(
            f"All providers failed for {method_name}({ticker})"
        ) from last_error
