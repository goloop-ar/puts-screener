"""Provider basado en yfinance: OHLCV, perfil, financials y earnings."""

import dataclasses
import logging
import random
import time
from datetime import date, datetime, timedelta

import pandas as pd
import requests
import yfinance as yf
from yfinance.exceptions import YFRateLimitError

from .base import DataProvider, ProviderError
from .cache import get_cached, merge_ohlcv, read_ohlcv_raw, write_cache, write_ohlcv
from .config import OHLCV_REFRESH_DAYS, is_cache_disabled
from .models import (
    AnalystData,
    CompanyProfile,
    EarningsEvent,
    ExDividendEvent,
    FinancialSnapshot,
    HistoricalEarningsEvent,
    RatingChange,
)
from .tickers import to_yfinance

logger = logging.getLogger(__name__)

_CANONICAL_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]

# Errores transitorios de yfinance que vale la pena reintentar (429, red).
_TRANSIENT_EXCEPTIONS = (
    YFRateLimitError,
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
)
# Substrings que delatan errores transitorios sin tipo dedicado (401 Invalid Crumb, etc.).
_TRANSIENT_MESSAGE_MARKERS = ("invalid crumb", "401", "429", "too many requests", "rate limit")


def _is_transient(exc: Exception) -> bool:
    """True si el error es transitorio (rate limit, crumb inválido, red) y conviene reintentar."""
    if isinstance(exc, _TRANSIENT_EXCEPTIONS):
        return True
    msg = str(exc).lower()
    return any(marker in msg for marker in _TRANSIENT_MESSAGE_MARKERS)


def _with_retry(fn, *, method: str, max_attempts: int, base_delay: float):
    """Ejecuta fn() reintentando solo errores transitorios, con backoff exponencial + jitter.

    Backoff: base_delay * 2**(intento-1), con jitter ±25%. Errores NO transitorios (KeyError,
    schema, etc.) se propagan en el primer intento sin esperar. Si se agotan los reintentos,
    propaga la última excepción (que el método convierte en ProviderError o degrada).
    """
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception as exc:
            transient = _is_transient(exc)
            if not transient or attempt == max_attempts:
                if transient:
                    logger.warning(
                        "Retries exhausted (%d/%d) for %s, propagating %s",
                        attempt,
                        max_attempts,
                        method,
                        type(exc).__name__,
                    )
                raise
            delay = base_delay * (2 ** (attempt - 1)) * random.uniform(0.75, 1.25)
            logger.info(
                "Retry %d/%d for %s after %.1fs due to %s",
                attempt,
                max_attempts,
                method,
                delay,
                type(exc).__name__,
            )
            time.sleep(delay)
    raise AssertionError("unreachable")  # pragma: no cover


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


def _ex_dividend_from_cache(data: dict) -> ExDividendEvent:
    return ExDividendEvent(
        ticker=data["ticker"],
        date=_parse_date(data["date"]),
        amount=data["amount"],
    )


def _latest_dividend_amount(tk) -> float | None:
    """Monto del dividendo más reciente desde `Ticker.dividends` (Series). None si no disponible."""
    try:
        dividends = tk.dividends
    except Exception:  # noqa: BLE001 — yfinance puede tirar errores silenciosos
        return None
    if dividends is None or not hasattr(dividends, "empty") or dividends.empty:
        return None
    return _clean_float(dividends.iloc[-1])


_ACTION_MAP = {
    "up": "upgrade",
    "down": "downgrade",
    "init": "initiation",
    "main": "reiterated",
    "reit": "reiterated",
}
_ZERO_COUNTS = {"strongBuy": 0, "buy": 0, "hold": 0, "sell": 0, "strongSell": 0}


def _normalize_action(action: str | None) -> str:
    if not action:
        return ""
    key = action.strip().lower()
    return _ACTION_MAP.get(key, key)


def _clean_str(value: object) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value)
    return text or None


def _clean_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_count(value: object) -> int:
    if value is None or pd.isna(value):
        return 0
    return int(value)


def _recommendation_counts(recs: pd.DataFrame | None) -> dict:
    """Extrae los counts de la fila más reciente ("0m", luego "-1m") o ceros."""
    if recs is None or not hasattr(recs, "columns") or recs.empty or "period" not in recs.columns:
        return dict(_ZERO_COUNTS)
    for period in ("0m", "-1m"):
        match = recs[recs["period"] == period]
        if not match.empty:
            row = match.iloc[0]
            return {key: _as_count(row.get(key)) for key in _ZERO_COUNTS}
    return dict(_ZERO_COUNTS)


def _analyst_from_cache(data: dict) -> AnalystData:
    return AnalystData(
        ticker=data["ticker"],
        price_target_mean=data["price_target_mean"],
        price_target_median=data["price_target_median"],
        price_target_high=data["price_target_high"],
        price_target_low=data["price_target_low"],
        n_analysts=data["n_analysts"],
        buy_count=data["buy_count"],
        hold_count=data["hold_count"],
        sell_count=data["sell_count"],
        strong_buy_count=data["strong_buy_count"],
        strong_sell_count=data["strong_sell_count"],
        recommendation_mean=data["recommendation_mean"],
        as_of=_parse_date(data["as_of"]),
    )


def _ratings_from_cache(data: dict) -> list[RatingChange]:
    return [
        RatingChange(
            ticker=item["ticker"],
            date=_parse_date(item["date"]),
            action=item["action"],
            from_grade=item["from_grade"],
            to_grade=item["to_grade"],
            firm=item["firm"],
        )
        for item in data["items"]
    ]


def _historical_earnings_from_cache(data: dict) -> list[HistoricalEarningsEvent]:
    return [
        HistoricalEarningsEvent(
            ticker=item["ticker"],
            date=_parse_date(item["date"]),
            eps_estimate=item["eps_estimate"],
            eps_actual=item["eps_actual"],
            eps_surprise_pct=item["eps_surprise_pct"],
            revenue_estimate=item["revenue_estimate"],
            revenue_actual=item["revenue_actual"],
        )
        for item in data["items"]
    ]


class YFinanceProvider(DataProvider):
    """Wrapper sobre yfinance.

    La conversión de moneda del market cap es responsabilidad del caller. Los métodos
    críticos (ohlcv/profile/financials/analyst) reintentan errores transitorios (429/401/red)
    con backoff antes de fallar; los no-críticos degradan a [] / None sin reintentar.
    """

    name = "yfinance"

    def __init__(self, max_attempts: int = 3, base_delay: float = 2.0):
        self.max_attempts = max_attempts
        self.base_delay = base_delay

    def get_ohlcv(self, ticker: str, start: date, end: date, interval: str = "1d") -> pd.DataFrame:
        """OHLCV con cache + refetch incremental de últimas N=OHLCV_REFRESH_DAYS barras.

        Política (decisión 2026-05-29, ver ROADMAP §5):
        - Cache miss → fetch full range [start, end], persistir, devolver.
        - Cache hit → refetch últimas N barras, mergear sobre cache, persistir, devolver slice.
        - Refetch falla → fallback al cache stale con warning (modo degradado).

        Esto garantiza que cada call devuelva data hasta el último cierre disponible
        en yfinance, sin perder eficiencia para la ventana histórica.
        """
        cache_active = not is_cache_disabled()
        cached = read_ohlcv_raw(ticker, interval) if cache_active else None

        if cached is None or cached.empty:
            # Cache miss: fetch full + persistir.
            df = self._fetch_full(ticker, start, end, interval)
            if cache_active:
                write_ohlcv(ticker, interval, df)
            return df

        # Cache hit: refetch incremental + merge.
        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end)
        try:
            recent = self._fetch_recent(ticker, interval, days=OHLCV_REFRESH_DAYS)
            if recent is not None and not recent.empty:
                merged = merge_ohlcv(cached, recent)
                write_ohlcv(ticker, interval, merged)
                logger.info(
                    "yfinance cache refreshed for %s [%s] (last bar: %s)",
                    ticker,
                    interval,
                    merged.index[-1].date(),
                )
                return merged.loc[start_ts:end_ts]
            # Recent vacío (feriado/weekend): no actualizar cache, devolver slice.
            logger.info("yfinance recent fetch empty for %s, using cached", ticker)
        except Exception as exc:
            logger.warning(
                "OHLCV refresh failed for %s: %s. Returning cached data (last bar: %s)",
                ticker,
                exc,
                cached.index[-1].date() if not cached.empty else "n/a",
            )
        return cached.loc[start_ts:end_ts]

    def _fetch_full(self, ticker: str, start: date, end: date, interval: str) -> pd.DataFrame:
        """Fetch del rango completo desde yfinance con retry. Raises ProviderError si vacío."""
        df = _with_retry(
            lambda: _get_ticker(to_yfinance(ticker)).history(
                start=start, end=end, interval=interval, auto_adjust=False
            ),
            method=f"get_ohlcv({ticker})",
            max_attempts=self.max_attempts,
            base_delay=self.base_delay,
        )
        if df is None or df.empty:
            raise ProviderError(f"yfinance returned no OHLCV for {ticker}")
        return self._canonicalize(df)

    def _fetch_recent(self, ticker: str, interval: str, days: int) -> pd.DataFrame | None:
        """Fetch últimas `days` barras desde yfinance. Reusa retry/backoff. None si vacío."""
        df = _with_retry(
            lambda: _get_ticker(to_yfinance(ticker)).history(
                period=f"{days}d", interval=interval, auto_adjust=False
            ),
            method=f"get_ohlcv_recent({ticker})",
            max_attempts=self.max_attempts,
            base_delay=self.base_delay,
        )
        if df is None or df.empty:
            return None
        return self._canonicalize(df)

    @staticmethod
    def _canonicalize(df: pd.DataFrame) -> pd.DataFrame:
        """Normaliza el DataFrame de yfinance: drop tz, columnas canónicas, mismo orden."""
        if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        for column in _CANONICAL_COLUMNS:
            if column not in df.columns:
                df[column] = float("nan")
        return df[_CANONICAL_COLUMNS]

    def get_company_profile(self, ticker: str) -> CompanyProfile:
        cache_key = f"yfinance_{ticker}"
        cached = get_cached("profile", cache_key)
        if cached is not None:
            return CompanyProfile(**cached)

        info = (
            _with_retry(
                lambda: _get_ticker(to_yfinance(ticker)).info,
                method=f"get_company_profile({ticker})",
                max_attempts=self.max_attempts,
                base_delay=self.base_delay,
            )
            or {}
        )
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

        def _fetch():
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
            return fcf, revenue, fiscal_year_end

        try:
            fcf, revenue, fiscal_year_end = _with_retry(
                _fetch,
                method=f"get_financials({ticker})",
                max_attempts=self.max_attempts,
                base_delay=self.base_delay,
            )
        except Exception as exc:
            logger.warning("yfinance get_financials failed for %s: %s", ticker, exc)
            raise ProviderError(f"yfinance get_financials failed for {ticker}: {exc}") from exc

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

        try:
            calendar = _get_ticker(to_yfinance(ticker)).calendar or {}
        except Exception as exc:  # noqa: BLE001 — yfinance frágil a cambios de schema
            logger.warning("yfinance get_upcoming_earnings failed for %s: %s", ticker, exc)
            return None
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

    def get_upcoming_ex_dividend(
        self, ticker: str, lookforward_days: int = 45
    ) -> ExDividendEvent | None:
        cache_key = f"yfinance_{ticker}"
        cached = get_cached("ex_dividend", cache_key)
        if cached is not None:
            return _ex_dividend_from_cache(cached)

        try:
            tk = _get_ticker(to_yfinance(ticker))
            calendar = tk.calendar or {}
            raw_dates = calendar.get("Ex-Dividend Date")
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

            amount = _latest_dividend_amount(tk)
            event = ExDividendEvent(ticker=ticker, date=in_window[0], amount=amount)
            write_cache("ex_dividend", cache_key, dataclasses.asdict(event))
            return event
        except Exception as exc:  # noqa: BLE001 — coherente con manejo silencioso de yfinance
            logger.warning("yfinance get_upcoming_ex_dividend failed for %s: %s", ticker, exc)
            return None

    def get_analyst_data(self, ticker: str) -> AnalystData:
        cache_key = f"yfinance_{ticker}"
        cached = get_cached("analyst", cache_key)
        if cached is not None:
            return _analyst_from_cache(cached)

        def _fetch():
            tk = _get_ticker(to_yfinance(ticker))
            return (tk.info or {}), tk.recommendations

        info, recommendations = _with_retry(
            _fetch,
            method=f"get_analyst_data({ticker})",
            max_attempts=self.max_attempts,
            base_delay=self.base_delay,
        )
        price_target_mean = info.get("targetMeanPrice")
        n_analysts = info.get("numberOfAnalystOpinions")
        recommendation_mean = info.get("recommendationMean")
        if recommendation_mean is None and n_analysts is None and price_target_mean is None:
            raise ProviderError(f"yfinance returned empty analyst data for {ticker}")

        counts = _recommendation_counts(recommendations)
        data = AnalystData(
            ticker=ticker,
            price_target_mean=price_target_mean,
            price_target_median=info.get("targetMedianPrice"),
            price_target_high=info.get("targetHighPrice"),
            price_target_low=info.get("targetLowPrice"),
            n_analysts=n_analysts,
            buy_count=counts["buy"],
            hold_count=counts["hold"],
            sell_count=counts["sell"],
            strong_buy_count=counts["strongBuy"],
            strong_sell_count=counts["strongSell"],
            recommendation_mean=recommendation_mean,
            as_of=date.today(),
        )
        write_cache("analyst", cache_key, dataclasses.asdict(data))
        return data

    def get_rating_changes(self, ticker: str, lookback_weeks: int = 6) -> list[RatingChange]:
        cache_key = f"yfinance_{ticker}_{lookback_weeks}"
        cached = get_cached("ratings", cache_key)
        if cached is not None:
            return _ratings_from_cache(cached)

        df = _get_ticker(to_yfinance(ticker)).upgrades_downgrades
        if df is None or not hasattr(df, "empty") or df.empty:
            return []

        if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
            df = df.copy()
            df.index = df.index.tz_localize(None)
        cutoff = pd.Timestamp(date.today() - timedelta(weeks=lookback_weeks))
        recent = df[df.index >= cutoff]

        changes = [
            RatingChange(
                ticker=ticker,
                date=_to_date(idx),
                action=_normalize_action(_clean_str(row.get("Action"))),
                from_grade=_clean_str(row.get("FromGrade")),
                to_grade=_clean_str(row.get("ToGrade")),
                firm=_clean_str(row.get("Firm")),
            )
            for idx, row in recent.iterrows()
        ]
        write_cache("ratings", cache_key, {"items": [dataclasses.asdict(c) for c in changes]})
        return changes

    def get_historical_earnings(
        self, ticker: str, lookback_days: int = 365
    ) -> list[HistoricalEarningsEvent]:
        cache_key = f"yfinance_{ticker}_{lookback_days}"
        cached = get_cached("earnings_history", cache_key)
        if cached is not None:
            return _historical_earnings_from_cache(cached)

        try:
            df = _get_ticker(to_yfinance(ticker)).earnings_dates
        except Exception as exc:  # noqa: BLE001 — yfinance frágil a cambios de schema
            logger.warning("yfinance get_historical_earnings failed for %s: %s", ticker, exc)
            return []
        if df is None or not hasattr(df, "empty") or df.empty:
            return []

        if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
            df = df.copy()
            df.index = df.index.tz_localize(None)
        today = date.today()
        cutoff = pd.Timestamp(today - timedelta(days=lookback_days))
        today_ts = pd.Timestamp(today)
        recent = df[(df.index >= cutoff) & (df.index <= today_ts)].sort_index(ascending=False)

        events = [
            HistoricalEarningsEvent(
                ticker=ticker,
                date=_to_date(idx),
                eps_estimate=_clean_float(row.get("EPS Estimate")),
                eps_actual=_clean_float(row.get("Reported EPS")),
                eps_surprise_pct=_clean_float(row.get("Surprise(%)")),
                revenue_estimate=_clean_float(row.get("Revenue Estimate")),
                revenue_actual=_clean_float(row.get("Revenue Actual")),
            )
            for idx, row in recent.iterrows()
        ]
        write_cache(
            "earnings_history", cache_key, {"items": [dataclasses.asdict(e) for e in events]}
        )
        return events
