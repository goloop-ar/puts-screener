"""Interfaz abstracta DataProvider y excepciones de la capa de providers."""

from abc import ABC
from datetime import date

import pandas as pd

from .models import (
    AnalystData,
    CompanyProfile,
    EarningsEvent,
    ExDividendEvent,
    FinancialSnapshot,
    HistoricalEarningsEvent,
    RatingChange,
)


class NotSupportedError(Exception):
    """El provider no soporta este método."""


class ProviderError(Exception):
    """Error genérico de provider (red, parsing, data faltante crítica)."""


_PROVIDER_METHODS = frozenset(
    {
        "get_ohlcv",
        "get_company_profile",
        "get_financials",
        "get_analyst_data",
        "get_rating_changes",
        "get_upcoming_earnings",
        "get_historical_earnings",
        "get_upcoming_ex_dividend",
    }
)


class DataProvider(ABC):  # noqa: B024
    """Contrato común a todas las fuentes de datos.

    Cada método no implementado por una subclase lanza NotSupportedError.
    Usar `supports()` para consultar capacidades en runtime.
    """

    name: str = "abstract"

    def get_ohlcv(self, ticker: str, start: date, end: date, interval: str = "1d") -> pd.DataFrame:
        raise NotSupportedError(f"{self.name} no soporta get_ohlcv")

    def get_company_profile(self, ticker: str) -> CompanyProfile:
        raise NotSupportedError(f"{self.name} no soporta get_company_profile")

    def get_financials(self, ticker: str) -> FinancialSnapshot:
        raise NotSupportedError(f"{self.name} no soporta get_financials")

    def get_analyst_data(self, ticker: str) -> AnalystData:
        raise NotSupportedError(f"{self.name} no soporta get_analyst_data")

    def get_rating_changes(self, ticker: str, lookback_weeks: int = 6) -> list[RatingChange]:
        raise NotSupportedError(f"{self.name} no soporta get_rating_changes")

    def get_upcoming_earnings(
        self, ticker: str, lookforward_days: int = 60
    ) -> EarningsEvent | None:
        raise NotSupportedError(f"{self.name} no soporta get_upcoming_earnings")

    def get_historical_earnings(
        self, ticker: str, lookback_days: int = 365
    ) -> list[HistoricalEarningsEvent]:
        raise NotSupportedError(f"{self.name} no soporta get_historical_earnings")

    def get_upcoming_ex_dividend(
        self, ticker: str, lookforward_days: int = 45
    ) -> ExDividendEvent | None:
        raise NotSupportedError(f"{self.name} no soporta get_upcoming_ex_dividend")

    def supports(self, method_name: str) -> bool:
        """Devuelve True si la subclase overridea `method_name`.

        Args:
            method_name: nombre de uno de los seis métodos del contrato.

        Raises:
            ValueError: si `method_name` no pertenece al contrato.
        """
        if method_name not in _PROVIDER_METHODS:
            raise ValueError(f"Método desconocido: {method_name}")
        own = getattr(type(self), method_name).__qualname__
        base = getattr(DataProvider, method_name).__qualname__
        return own != base
