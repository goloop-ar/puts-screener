"""Cache local en disco para respuestas de providers, con TTL por categoría."""

import json
import time
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from . import config

CACHE_ROOT = Path("data/cache")

TTL_HOURS = {
    "ohlcv": 24,
    "profile": 24 * 7,
    "financials": 24 * 7,
    "analyst": 24,
    "ratings": 24,
    "earnings": 24,
    "earnings_history": 24,
}

OHLCV_ROLLING_DAYS = 1500  # ~6 años hábiles, suficiente para SMA200W (200 semanas ≈ 1400 días)

_SECONDS_PER_HOUR = 3600
_PARQUET_CATEGORIES = frozenset({"ohlcv"})


def cache_path(category: str, *parts: str) -> Path:
    """Construye el path de cache para una categoría y sus componentes."""
    return CACHE_ROOT.joinpath(category, *parts)


def is_fresh(path: Path, ttl_hours: int) -> bool:
    """True si el archivo existe y su mtime está dentro del TTL."""
    if not path.exists():
        return False
    age_seconds = time.time() - path.stat().st_mtime
    return age_seconds < ttl_hours * _SECONDS_PER_HOUR


def read_json(path: Path) -> dict | None:
    """Lee un dict desde un archivo JSON, o None si no existe."""
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, data: dict) -> None:
    """Escribe un dict a disco como JSON, creando directorios si hace falta."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, default=str)


def read_parquet(path: Path) -> pd.DataFrame | None:
    """Lee un DataFrame desde un archivo parquet, o None si no existe."""
    if not path.exists():
        return None
    return pd.read_parquet(path)


def write_parquet(path: Path, df: pd.DataFrame) -> None:
    """Escribe un DataFrame a disco como parquet, creando directorios si hace falta."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)


def get_cached(category: str, key: str) -> dict | pd.DataFrame | None:
    """Devuelve el contenido cacheado si está fresh, sino None.

    El formato (parquet vs JSON) se decide por la categoría. Devuelve None si el
    cache está deshabilitado por la env var CACHE_DISABLED.
    """
    if config.is_cache_disabled():
        return None
    path = cache_path(category, key)
    if not is_fresh(path, TTL_HOURS[category]):
        return None
    if category in _PARQUET_CATEGORIES:
        return read_parquet(path)
    return read_json(path)


def write_cache(category: str, key: str, data: Any) -> None:
    """Persiste data a cache. DataFrames → parquet, dicts → JSON.

    No-op si el cache está deshabilitado por la env var CACHE_DISABLED.
    """
    if config.is_cache_disabled():
        return
    path = cache_path(category, key)
    if isinstance(data, pd.DataFrame):
        write_parquet(path, data)
    else:
        write_json(path, data)


def read_ohlcv_slice(ticker: str, interval: str, start: date, end: date) -> pd.DataFrame | None:
    """Devuelve el slice [start, end] del OHLCV cacheado si lo cubre, sino None.

    Devuelve None (miss) si el cache no existe, está stale, está vacío, o el
    rango pedido no cae completamente dentro de la ventana cacheada — señal para
    que el caller haga un refetch completo.
    """
    if config.is_cache_disabled():
        return None
    path = cache_path("ohlcv", f"{ticker}_{interval}.parquet")
    if not is_fresh(path, TTL_HOURS["ohlcv"]):
        return None
    df = read_parquet(path)
    if df is None or df.empty:
        return None
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    if start_ts < df.index.min() or end_ts > df.index.max():
        return None
    return df.loc[start_ts:end_ts]


def write_ohlcv(ticker: str, interval: str, df: pd.DataFrame) -> None:
    """Persiste el DataFrame OHLCV completo.

    La ventana rolling (OHLCV_ROLLING_DAYS) es responsabilidad del provider; la
    capa de cache solo escribe lo que recibe. No-op si CACHE_DISABLED.
    """
    if config.is_cache_disabled():
        return
    path = cache_path("ohlcv", f"{ticker}_{interval}.parquet")
    write_parquet(path, df)
