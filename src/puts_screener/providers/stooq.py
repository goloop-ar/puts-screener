"""Provider de OHLCV vía Stooq (CSV público, sin auth)."""

import logging
from datetime import date
from io import StringIO

import pandas as pd
import requests

from .base import DataProvider, ProviderError
from .cache import read_ohlcv_slice, write_ohlcv
from .tickers import to_stooq

logger = logging.getLogger(__name__)

_INTERVAL_MAP = {"1d": "d", "1wk": "w", "1mo": "m"}
_CANONICAL_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]
_HTTP_OK = 200
_STOOQ_DATE_FORMAT = "%Y%m%d"


class StooqProvider(DataProvider):
    """Descarga OHLCV histórico desde Stooq. Solo soporta `get_ohlcv`."""

    name = "stooq"

    def __init__(self, base_url: str = "https://stooq.com/q/d/l/", timeout: int = 10):
        self.base_url = base_url
        self.timeout = timeout

    def get_ohlcv(self, ticker: str, start: date, end: date, interval: str = "1d") -> pd.DataFrame:
        interval_code = _INTERVAL_MAP.get(interval)
        if interval_code is None:
            raise ValueError(f"Unsupported interval for Stooq: {interval}")
        symbol = to_stooq(ticker)

        cached = read_ohlcv_slice(ticker, interval, start, end)
        if cached is not None:
            logger.info("Stooq cache hit for %s [%s]", ticker, interval)
            return cached
        logger.info("Stooq cache miss for %s [%s], fetching from network", ticker, interval)

        url = (
            f"{self.base_url}?s={symbol}&i={interval_code}"
            f"&d1={start.strftime(_STOOQ_DATE_FORMAT)}&d2={end.strftime(_STOOQ_DATE_FORMAT)}"
        )
        try:
            response = requests.get(url, timeout=self.timeout)
        except requests.RequestException as exc:
            logger.warning("Stooq request error for %s: %s", ticker, exc)
            raise ProviderError(f"Stooq request failed for {ticker}: {exc}") from exc

        if response.status_code != _HTTP_OK:
            raise ProviderError(f"Stooq returned status {response.status_code} for {ticker}")

        df = self._parse_csv(response.text, ticker)
        write_ohlcv(ticker, interval, df)
        return df

    @staticmethod
    def _parse_csv(text: str, ticker: str) -> pd.DataFrame:
        stripped = text.strip()
        if not stripped or "No data" in stripped.splitlines()[0]:
            raise ProviderError(f"Stooq returned no data for {ticker}")

        df = pd.read_csv(StringIO(text))
        if df.empty or "Date" not in df.columns:
            raise ProviderError(f"Stooq returned no data for {ticker}")

        df["Date"] = pd.to_datetime(df["Date"])
        df = df.set_index("Date").sort_index()
        for column in _CANONICAL_COLUMNS:
            if column not in df.columns:
                df[column] = float("nan")
        return df[_CANONICAL_COLUMNS]
