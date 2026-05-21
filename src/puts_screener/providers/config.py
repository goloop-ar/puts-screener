"""Carga de configuración desde entorno / archivo .env."""

import os

from dotenv import load_dotenv

load_dotenv()

_CACHE_DISABLED_TRUTHY = ("1", "true", "True", "yes")


def get_finnhub_api_key() -> str | None:
    """Devuelve la API key de Finnhub, o None si no está seteada o está vacía."""
    key = os.environ.get("FINNHUB_API_KEY")
    if not key:
        return None
    return key


def is_cache_disabled() -> bool:
    """True si la env var CACHE_DISABLED indica un valor verdadero."""
    return os.environ.get("CACHE_DISABLED", "") in _CACHE_DISABLED_TRUTHY
