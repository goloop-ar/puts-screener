"""Universe builder: combina S&P 500 + Stoxx Europe 600 desde Wikipedia.

El parsing usa bs4 con el parser builtin de Python (no `pd.read_html`, que
requiere lxml/html5lib no instalados). La columna exacta de cada tabla depende
del estado de Wikipedia y puede requerir ajuste.
"""

import json
import logging
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from puts_screener.providers import config
from puts_screener.providers.tickers import SUPPORTED_EU_SUFFIXES

logger = logging.getLogger(__name__)

_SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
_STOXX600_URL = "https://en.wikipedia.org/wiki/STOXX_Europe_600"
_SOURCE_URLS = {"sp500": _SP500_URL, "stoxx600": _STOXX600_URL}

_CACHE_DIR = Path("data/cache/universe")
_CACHE_TTL_SECONDS = 7 * 24 * 3600
_HTTP_TIMEOUT = 20
_HTTP_OK = 200
_USER_AGENT = "puts-screener/0.1 (universe builder)"

# Sufijo de exchange Bloomberg → sufijo canónico de yfinance.
_BLOOMBERG_TO_YF = {
    "GR": ".DE",
    "FP": ".PA",
    "LN": ".L",
    "IM": ".MI",
    "SM": ".MC",
    "NA": ".AS",
    "SW": ".SW",
    "DC": ".CO",
    "SS": ".ST",
    "FH": ".HE",
    "NO": ".OL",
    "BB": ".BR",
    "PL": ".LS",
    "AV": ".VI",
}

# Mapeo Country (Wikipedia STOXX 600) -> sufijo yfinance.
# Cubre 99% de STOXX 600. Países fuera de este dict se skipean.
_STOXX_COUNTRY_TO_SUFFIX: dict[str, str] = {
    "United Kingdom": ".L",
    "France": ".PA",
    "Germany": ".DE",
    "Switzerland": ".SW",
    "Sweden": ".ST",
    "Spain": ".MC",
    "Netherlands": ".AS",
    "Italy": ".MI",
    "Finland": ".HE",
    "Belgium": ".BR",
    "Norway": ".OL",
    "Denmark": ".CO",
    "Austria": ".VI",
    "Portugal": ".LS",
    # Casos especiales: empresa registrada en un país pero cotiza en otro.
    "Ireland": ".L",  # mayoría cotiza en London
    "Luxembourg": ".AS",  # mayoría cotiza en Amsterdam
    "Bermuda": ".L",  # típicamente listadas en London
    # Países no mapeados (Poland, Greece, Israel, etc.): skip.
}


def build_universe(refresh: bool = False) -> list[str]:
    """Combina S&P 500 + Stoxx 600 con cache de 7 días.

    Args:
        refresh: si True, ignora cache y refetchea.

    Returns:
        Lista deduplicada y ordenada de tickers en formato canónico (yfinance).
    """
    sp500 = _fetch_with_cache("sp500", _fetch_sp500, refresh)
    stoxx = _fetch_with_cache("stoxx600", _fetch_stoxx600, refresh)
    return sorted(set(sp500) | set(stoxx))


def _fetch_sp500() -> list[str]:
    """S&P 500: primera tabla con columna 'Symbol'. `.` → `-` (canónico yfinance)."""
    html = _http_get(_SP500_URL)
    raw = _parse_table_column(html, ("Symbol",))
    return [s.strip().upper().replace(".", "-") for s in raw if s.strip()]


def _fetch_stoxx600() -> list[str]:
    """Fetchea constituyentes de STOXX 600 desde Wikipedia.

    Lee la tabla con columnas (Ticker, Company, ICB Sector, Country, ...) — en la
    versión actual de Wikipedia es la tabla ~index 2 de la página. Construye el
    ticker yfinance combinando Ticker + sufijo derivado de Country.

    Returns:
        Lista de tickers en formato yfinance (ej. "VOD.L", "SAP.DE", "ASML.AS").
        Los tickers cuyo país no está en `_STOXX_COUNTRY_TO_SUFFIX` se skipean.
    """
    html = _http_get(_STOXX600_URL)
    soup = BeautifulSoup(html, "html.parser")

    constituents_table = None
    ticker_idx = country_idx = -1
    for table in soup.find_all("table"):
        first_row = table.find("tr")
        if first_row is None:
            continue
        headers = [th.get_text(strip=True) for th in first_row.find_all("th")]
        if "Ticker" in headers and "Country" in headers:
            constituents_table = table
            ticker_idx = headers.index("Ticker")
            country_idx = headers.index("Country")
            break

    if constituents_table is None:
        raise ValueError("No constituents table found in STOXX 600 Wikipedia page")

    tickers: list[str] = []
    skipped_count = 0
    for row in constituents_table.find_all("tr")[1:]:
        cells = row.find_all("td")
        if len(cells) <= max(ticker_idx, country_idx):
            continue
        raw_ticker = cells[ticker_idx].get_text(strip=True)
        country = cells[country_idx].get_text(strip=True)
        if not raw_ticker:
            continue
        normalized = _normalize_stoxx_ticker_v2(raw_ticker, country)
        if normalized is None:
            skipped_count += 1
            continue
        tickers.append(normalized)

    if skipped_count > 0:
        logger.info(
            "STOXX 600: skipped %d tickers (country outside supported exchanges)",
            skipped_count,
        )
    return tickers


def _normalize_stoxx_ticker(raw: str, exchange_hint: str | None = None) -> str | None:
    """Normaliza un ticker de Stoxx 600 (formato Bloomberg o sufijo punto) a yfinance.

    NOTA: la función activa en el flujo principal es `_normalize_stoxx_ticker_v2`
    (Ticker + Country). Esta se mantiene por si Wikipedia vuelve al formato Bloomberg.

    Soporta forma Bloomberg (`SAP GR` → `SAP.DE`) y forma con sufijo punto
    (`ASML.AS`). Devuelve None si el exchange no está soportado.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None

    if " " in text:
        base, _, suffix = text.rpartition(" ")
        yf_suffix = _BLOOMBERG_TO_YF.get(suffix.upper())
        if yf_suffix is None or not base.strip():
            return None
        return f"{base.strip().upper()}{yf_suffix}"

    if "." in text:
        base, _, suffix = text.rpartition(".")
        dot_suffix = f".{suffix.upper()}"
        if dot_suffix in SUPPORTED_EU_SUFFIXES and base:
            return f"{base.upper()}{dot_suffix}"
        return None

    return None


def _normalize_stoxx_ticker_v2(raw_ticker: str, country: str) -> str | None:
    """Normaliza un ticker de STOXX 600 al formato yfinance usando el país.

    Función activa en el flujo principal (`_fetch_stoxx600`).

    Reglas:
    - Espacios internos en el ticker → guion (class shares: "VOLV B" → "VOLV-B").
    - Sufijo derivado de `country` via `_STOXX_COUNTRY_TO_SUFFIX`.
    - País no mapeado → None (caller debe skipear).

    Examples:
        >>> _normalize_stoxx_ticker_v2("ZURN", "Switzerland")
        'ZURN.SW'
        >>> _normalize_stoxx_ticker_v2("VOLV B", "Sweden")
        'VOLV-B.ST'
        >>> _normalize_stoxx_ticker_v2("LPP", "Poland")
    """
    suffix = _STOXX_COUNTRY_TO_SUFFIX.get(country)
    if suffix is None:
        return None
    base = raw_ticker.upper().replace(" ", "-")
    return f"{base}{suffix}"


def _http_get(url: str) -> str:
    response = requests.get(url, timeout=_HTTP_TIMEOUT, headers={"User-Agent": _USER_AGENT})
    if response.status_code != _HTTP_OK:
        raise ValueError(f"HTTP {response.status_code} al obtener {url}")
    return response.text


def _parse_table_column(html: str, column_candidates: tuple[str, ...]) -> list[str]:
    """Extrae los valores de la primera tabla HTML cuya cabecera tenga una columna dada."""
    soup = BeautifulSoup(html, "html.parser")
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        headers = [cell.get_text(strip=True) for cell in rows[0].find_all(["th", "td"])]
        col_index = next(
            (i for i, header in enumerate(headers) if header in column_candidates), None
        )
        if col_index is None:
            continue
        values = []
        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) > col_index:
                text = cells[col_index].get_text(strip=True)
                if text:
                    values.append(text)
        if values:
            return values
    raise ValueError(f"No se encontró tabla con columna en {column_candidates}")


def _cache_path(name: str) -> Path:
    return _CACHE_DIR / f"{name}.json"


def _read_universe_cache(name: str) -> list[str] | None:
    if config.is_cache_disabled():
        return None
    path = _cache_path(name)
    if not path.exists():
        return None
    if time.time() - path.stat().st_mtime >= _CACHE_TTL_SECONDS:
        return None
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh).get("tickers")


def _write_universe_cache(name: str, tickers: list[str], source_url: str) -> None:
    if config.is_cache_disabled():
        return
    path = _cache_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "tickers": tickers,
        "fetched_at": datetime.now().isoformat(),
        "source_url": source_url,
    }
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)


def _fetch_with_cache(name: str, fetcher: Callable[[], list[str]], refresh: bool) -> list[str]:
    if not refresh:
        cached = _read_universe_cache(name)
        if cached is not None:
            logger.info("universe cache hit for %s (%d tickers)", name, len(cached))
            return cached
    tickers = fetcher()
    _write_universe_cache(name, tickers, _SOURCE_URLS.get(name, ""))
    return tickers
