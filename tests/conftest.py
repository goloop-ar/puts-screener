"""Fixtures comunes y bootstrap del path de `src` para la suite de tests.

`src` se agrega a `sys.path` acá (en lugar de instalar el paquete) para que
`pytest -v` corra desde la raíz sin un paso de instalación editable. La inserción
ocurre al importar este conftest, antes de que pytest importe los módulos de test.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


@pytest.fixture
def tmp_cache_root(tmp_path, monkeypatch):
    """Apunta cache.CACHE_ROOT a una carpeta temporal y la devuelve."""
    from puts_screener.providers import cache

    root = tmp_path / "cache"
    monkeypatch.setattr(cache, "CACHE_ROOT", root)
    return root


@pytest.fixture
def sample_ohlcv_df():
    """DataFrame OHLCV de 30 días hábiles continuos con valores plausibles."""
    idx = pd.bdate_range("2024-01-02", periods=30)
    n = len(idx)
    return pd.DataFrame(
        {
            "Open": [100.0 + i for i in range(n)],
            "High": [101.0 + i for i in range(n)],
            "Low": [99.0 + i for i in range(n)],
            "Close": [100.5 + i for i in range(n)],
            "Volume": [1_000_000 + i * 1_000 for i in range(n)],
        },
        index=idx,
    )


@pytest.fixture
def disable_cache(monkeypatch):
    """Activa CACHE_DISABLED=1 en el entorno para el test."""
    monkeypatch.setenv("CACHE_DISABLED", "1")
