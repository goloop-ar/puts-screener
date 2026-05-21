"""Normalización de tickers entre el formato canónico interno y cada provider.

El formato canónico interno es estilo yfinance: US sin sufijo (`AAPL`) y Europa
con sufijo de exchange (`ASML.AS`, `VOW3.DE`).
"""

SUPPORTED_EU_SUFFIXES = (
    ".L",
    ".DE",
    ".PA",
    ".MI",
    ".MC",
    ".AS",
    ".SW",
    ".CO",
    ".ST",
    ".HE",
    ".OL",
    ".BR",
    ".LS",
    ".VI",
)

_YFINANCE_TO_STOOQ_COUNTRY = {
    ".L": "uk",
    ".DE": "de",
    ".PA": "fr",
    ".MI": "it",
    ".MC": "es",
    ".AS": "nl",
    ".SW": "ch",
    ".CO": "dk",
    ".ST": "se",
    ".HE": "fi",
    ".OL": "no",
    ".BR": "be",
    ".LS": "pt",
    ".VI": "at",
}


def is_us_ticker(ticker: str) -> bool:
    """True si el ticker no termina en un sufijo de exchange europeo soportado."""
    return not ticker.endswith(SUPPORTED_EU_SUFFIXES)


def to_stooq(ticker: str) -> str:
    """Convierte un ticker canónico al formato de símbolo de Stooq.

    US (sin punto) → `aapl.us`; Europa → `{base}.{country}` según la tabla de
    mapping yfinance → Stooq.

    Raises:
        ValueError: si el ticker tiene un sufijo de exchange no soportado.
    """
    base, dot, suffix_part = ticker.rpartition(".")
    if not dot:
        return f"{ticker.lower()}.us"
    suffix = f".{suffix_part}"
    country = _YFINANCE_TO_STOOQ_COUNTRY.get(suffix)
    if country is None:
        raise ValueError(f"Unsupported ticker for Stooq: {ticker}")
    return f"{base.lower()}.{country}"


def to_yfinance(ticker: str) -> str:
    """Identidad: el formato canónico interno ya es el de yfinance."""
    return ticker


def to_finnhub(ticker: str) -> str:
    """Convierte un ticker canónico al formato de Finnhub.

    Por ahora es identidad para US y Europa: Finnhub acepta el ticker con sufijo
    en la mayoría de sus endpoints free. Esto puede requerir ajuste por endpoint
    específico cuando se implemente FinnhubProvider.
    """
    return ticker
