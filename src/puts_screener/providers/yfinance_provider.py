"""Provider basado en yfinance: OHLCV, perfil, financials y earnings."""

import dataclasses
import logging
from datetime import date, datetime, timedelta

import pandas as pd
import yfinance as yf

from .base import DataProvider, ProviderError
from .cache import get_cached, read_ohlcv_slice, write_cache, write_ohlcv
from .models import CompanyProfile, EarningsEvent, FinancialSnapshot
from .tickers import to_yfinance

logger = logging.getLogger(__name__)

_CANONICAL_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


def _get_ticker(symbol: str) -> yf.Ticker:
    """Factory de `yf.Ticker`, aislada para poder mockearla en tests."""
    return yf.Ticker(symbol)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def _to_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return pd.Timestamp(value).date()
    except (ValueError, TypeError):
        return None


def _extract_row_latest(df: pd.DataFrame | None, row_label: str) -> float | None:
    """Devuelve el valor más reciente (primera columna) de una fila, o None."""
    if df is None or not hasattr(df, "index") or df.empty or row_label not in df.index:
        return None
    value = df.loc[row_label].iloc[0]
    if pd.isna(value):
        return None
    return float(value)


def _latest_column_date(df: pd.DataFrame | None) -> date | None:
    if df is None or not hasattr(df, "columns") or len(df.columns) == 0:
        return None
    return _to_date(df.columns[0])


def _financials_from_cache(data: dict) -> FinancialSnapshot:
    return FinancialSnapshot(
        ticker=data["ticker"],
        free_cash_flow_ttm=data["free_cash_flow_ttm"],
        total_revenue_ttm=data["total_revenue_ttm"],
        fiscal_year_end=_parse_date(data["fiscal_year_end"]),
        as_of=_parse_date(data["as_of"]),
    )


def _earnings_from_cache(data: dict) -> EarningsEvent:
    return EarningsEvent(
        ticker=data["ticker"],
        date=_parse_date(data["date"]),
        eps_estimate=data["eps_estimate"],
        eps_actual=data["eps_actual"],
        when=data["when"],
    )


class YFinanceProvider(DataProvider):
    """Wrapper sobre yfinance.

    La conversión de moneda del market cap es responsabilidad del caller.
    """

    name = "yfinance"

    def get_ohlcv(self, ticker: str, start: date, end: date, interval: str = "1d") -> pd.DataFrame:
        cached = read_ohlcv_slice(ticker, interval, start, end)
        if cached is not None:
            logger.info("yfinance cache hit for %s [%s]", ticker, interval)
            return cached

        tk = _get_ticker(to_yfinance(ticker))
        df = tk.history(start=start, end=end, interval=interval, auto_adjust=False)
        if df is None or df.empty:
            raise ProviderError(f"yfinance returned no OHLCV for {ticker}")

        if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        for column in _CANONICAL_COLUMNS:
            if column not in df.columns:
                df[column] = float("nan")
        df = df[_CANONICAL_COLUMNS]
        write_ohlcv(ticker, interval, df)
        return df

    def get_company_profile(self, ticker: str) -> CompanyProfile:
        cache_key = f"yfinance_{ticker}"
        cached = get_cached("profile", cache_key)
        if cached is not None:
            return CompanyProfile(**cached)

        info = _get_ticker(to_yfinance(ticker)).info or {}
        name = info.get("longName") or info.get("shortName") or ticker
        if name == ticker:
            raise ProviderError(f"yfinance returned empty info for {ticker}")

        profile = CompanyProfile(
            ticker=ticker,
            name=name,
            sector=info.get("sector"),
            industry=info.get("industry"),
            exchange=info.get("exchange"),
            country=info.get("country"),
            market_cap_usd=info.get("marketCap"),
            currency=info.get("currency"),
            avg_daily_volume_3m=info.get("averageDailyVolume3Month"),
        )
        write_cache("profile", cache_key, dataclasses.asdict(profile))
        return profile

    def get_financials(self, ticker: str) -> FinancialSnapshot:
        cache_key = f"yfinance_{ticker}"
        cached = get_cached("financials", cache_key)
        if cached is not None:
            return _financials_from_cache(cached)

        tk = _get_ticker(to_yfinance(ticker))
        cashflow = tk.cashflow
        fcf = _extract_row_latest(cashflow, "Free Cash Flow")
        if fcf is None:
            fcf = _extract_row_latest(getattr(tk, "cash_flow", None), "Free Cash Flow")
        financials = tk.financials
        revenue = _extract_row_latest(financials, "Total Revenue")
        fiscal_year_end = _latest_column_date(cashflow)
        if fiscal_year_end is None:
            fiscal_year_end = _latest_column_date(financials)

        snapshot = FinancialSnapshot(
            ticker=ticker,
            free_cash_flow_ttm=fcf,
            total_revenue_ttm=revenue,
            fiscal_year_end=fiscal_year_end,
            as_of=date.today(),
        )
        write_cache("financials", cache_key, dataclasses.asdict(snapshot))
        return snapshot

    def get_upcoming_earnings(
        self, ticker: str, lookforward_days: int = 60
    ) -> EarningsEvent | None:
        cache_key = f"yfinance_{ticker}"
        cached = get_cached("earnings", cache_key)
        if cached is not None:
            return _earnings_from_cache(cached)

        calendar = _get_ticker(to_yfinance(ticker)).calendar or {}
        raw_dates = calendar.get("Earnings Date")
        if raw_dates is None:
            return None
        if not isinstance(raw_dates, list):
            raw_dates = [raw_dates]

        today = date.today()
        horizon = today + timedelta(days=lookforward_days)
        in_window = sorted(
            parsed
            for parsed in (_to_date(value) for value in raw_dates)
            if parsed is not None and today <= parsed <= horizon
        )
        if not in_window:
            return None

        event = EarningsEvent(
            ticker=ticker,
            date=in_window[0],
            eps_estimate=None,
            eps_actual=None,
            when=None,
        )
        write_cache("earnings", cache_key, dataclasses.asdict(event))
        return event
