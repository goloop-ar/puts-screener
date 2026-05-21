# Spec 01 — Data Providers

> Capa de abstracción sobre fuentes de datos. Toda la lógica de negocio del puts-screener accede a datos exclusivamente a través de esta capa.

## 1. Objetivo

Desacoplar la lógica de negocio (filtros, scoring, clasificación) de las APIs concretas. Implementar un orquestador con fallback automático y cache local.

## 2. Scope

### En scope

- Interfaz abstracta `DataProvider`
- Dataclasses de retorno tipadas
- Tres providers concretos: `StooqProvider`, `YFinanceProvider`, `FinnhubProvider`
- Orquestador `DataService` con fallback por método
- Cache local en disco con TTL
- Rate limiting básico para Finnhub
- Normalización de tickers entre formatos
- Tests unitarios con fixtures + smoke test manual

### Fuera de scope (futuro)

- Providers pagos (EODHD, FMP, fiscal.ai, IBKR)
- Async / concurrencia avanzada
- Cache compartido (Redis, BD)
- Reintentos exponenciales sofisticados

## 3. Modelos de datos

Todos en `src/puts_screener/providers/models.py` como dataclasses.

```python
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

@dataclass(frozen=True)
class CompanyProfile:
    ticker: str
    name: str
    sector: Optional[str]
    industry: Optional[str]
    exchange: Optional[str]
    country: Optional[str]
    market_cap_usd: Optional[float]
    currency: Optional[str]
    avg_daily_volume_3m: Optional[float]

@dataclass(frozen=True)
class FinancialSnapshot:
    ticker: str
    free_cash_flow_ttm: Optional[float]      # USD, último TTM
    total_revenue_ttm: Optional[float]
    fiscal_year_end: Optional[date]
    as_of: Optional[date]                    # cuándo se reportó

@dataclass(frozen=True)
class AnalystData:
    ticker: str
    price_target_mean: Optional[float]
    price_target_median: Optional[float]
    price_target_high: Optional[float]
    price_target_low: Optional[float]
    n_analysts: Optional[int]
    buy_count: int = 0
    hold_count: int = 0
    sell_count: int = 0
    strong_buy_count: int = 0
    strong_sell_count: int = 0
    recommendation_mean: Optional[float] = None   # 1=strong buy ... 5=strong sell
    as_of: Optional[date] = None

@dataclass(frozen=True)
class RatingChange:
    ticker: str
    date: date
    action: str                  # "downgrade" | "upgrade" | "initiation" | "reiterated"
    from_grade: Optional[str]
    to_grade: Optional[str]
    firm: Optional[str]

@dataclass(frozen=True)
class EarningsEvent:
    ticker: str
    date: date
    eps_estimate: Optional[float]
    eps_actual: Optional[float]
    when: Optional[str]          # "bmo" (before market open) | "amc" (after market close) | None

@dataclass(frozen=True)
class HistoricalEarningsEvent:
    ticker: str
    date: date  # fecha del earnings (puede ser hoy o pasado, NO futuro)
    eps_estimate: float | None
    eps_actual: float | None
    eps_surprise_pct: float | None  # (actual - estimate) / abs(estimate) * 100
    revenue_estimate: float | None  # opcional, puede no estar disponible
    revenue_actual: float | None
```

**OHLCV**: pandas DataFrame con columnas exactas `["Open", "High", "Low", "Close", "Volume"]` indexado por `DatetimeIndex` ascendente, sin huecos en días hábiles. No es dataclass porque pandas ya es el formato canónico.

## 4. Interfaz abstracta `DataProvider`

En `src/puts_screener/providers/base.py`:

```python
from abc import ABC
from datetime import date
import pandas as pd
from .models import CompanyProfile, FinancialSnapshot, AnalystData, RatingChange, EarningsEvent

class NotSupportedError(Exception):
    """El provider no soporta este método."""

class ProviderError(Exception):
    """Error genérico de provider (red, parsing, data faltante crítica)."""

class DataProvider(ABC):
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

    def get_upcoming_earnings(self, ticker: str, lookforward_days: int = 60) -> EarningsEvent | None:
        raise NotSupportedError(f"{self.name} no soporta get_upcoming_earnings")

    def get_historical_earnings(
        self, ticker: str, lookback_days: int = 365
    ) -> list[HistoricalEarningsEvent]:
        raise NotSupportedError(f"{self.name} no soporta get_historical_earnings")

    def supports(self, method_name: str) -> bool:
        """True si el provider implementa (override) el método."""
        # Implementación: comparar __qualname__ del método actual vs el de DataProvider
        ...
```

**Nota sobre ventanas de earnings**: aunque `get_upcoming_earnings` mira por defecto 60 días hacia adelante (margen), el filtro del SOP usa una ventana de 45 días (alineado al Paso 3). La capa de aplicación deriva tres campos a partir del `EarningsEvent` retornado: `earnings_date` (date | None), `dias_a_earnings` (int | None) y `earnings_en_45d` (bool).

## 5. Providers concretos

### 5.1 `StooqProvider` (`providers/stooq.py`)

- **Soporta**: `get_ohlcv`
- **Base URL**: `https://stooq.com/q/d/l/?s={symbol}&i={interval_code}&d1={start}&d2={end}`
- **Interval mapping**: `1d` → `d`, `1wk` → `w`, `1mo` → `m`
- **Auth**: ninguna
- **Símbolo**: ver §7 (normalización de tickers)
- **Implementación**: `requests.get`, parsear CSV con `pandas.read_csv` desde el response
- **Errores**: si el CSV viene vacío o con cabecera "No data", lanzar `ProviderError`
- **Cache**: sí, ver §8

### 5.2 `YFinanceProvider` (`providers/yfinance_provider.py`)

- **Soporta**: `get_ohlcv`, `get_company_profile`, `get_financials`, `get_analyst_data`, `get_rating_changes`, `get_upcoming_earnings`, `get_historical_earnings`.
- **Wrapper**: `yfinance.Ticker`
- **Detalles**:
  - `get_ohlcv` → `Ticker.history(start=..., end=..., interval=...)`. Renombrar columnas a las canónicas.
  - `get_company_profile` → `Ticker.info` (frágil, usar `.get()` con defaults, nunca acceso directo por `[]`). Mapear: `sector`, `industry`, `marketCap` → `market_cap_usd`, `exchange`, `country`, `currency`, `averageDailyVolume3Month` → `avg_daily_volume_3m`.
  - `get_financials` → `Ticker.cashflow` para FCF (Free Cash Flow row TTM), `Ticker.financials` para revenue TTM. Si la fila no existe, retornar el snapshot con `None`.
  - `get_upcoming_earnings` → `Ticker.calendar` con la fecha más cercana en el futuro dentro de `lookforward_days`.
- **Manejo de errores**: yfinance silenciosamente devuelve DataFrames vacíos o dicts incompletos. Validar y propagar como `ProviderError` con mensaje claro.
- **Cache**: sí.

#### `get_analyst_data`

- Cache: `get_cached("analyst", f"yfinance_{ticker}")`.
- Lee `tk.info` para `recommendationMean`, `numberOfAnalystOpinions`, `targetMeanPrice`/`Median`/`High`/`Low`.
- Lee `tk.recommendations` (DataFrame con filas por mes); toma la fila `period == "0m"` (fallback `"-1m"`, sino counts = 0) para los counts `strongBuy`/`buy`/`hold`/`sell`/`strongSell`.
- `recommendation_mean` viene directo de yfinance (no se computa).
- Si los tres campos (mean, n_analysts, target_mean) son todos None → `ProviderError`.

#### `get_rating_changes`

- Cache: `get_cached("ratings", f"yfinance_{ticker}_{lookback_weeks}")`.
- Lee `tk.upgrades_downgrades` (DataFrame indexado por `GradeDate`).
- Si es None o vacío → devuelve `[]` (NO error). yfinance no provee esta data para tickers EU.
- Filtra por `index >= today - lookback_weeks`.
- Normaliza `Action`: `"up"`→`"upgrade"`, `"down"`→`"downgrade"`, `"init"`→`"initiation"`, `"main"`/`"reit"`→`"reiterated"`.

#### `get_historical_earnings`

- Cache: `get_cached("earnings_history", f"yfinance_{ticker}_{lookback_days}")`.
- Lee `tk.earnings_dates` (DataFrame indexado por fecha).
- Filtra solo fechas ≤ hoy AND ≥ hoy - lookback_days.
- Mapea: `eps_estimate` ← `EPS Estimate`, `eps_actual` ← `Reported EPS`, `eps_surprise_pct` ← `Surprise(%)`.
- NaN → None.
- Si yfinance devuelve None o vacío → `[]` (no error). Earnings vacío es legítimo.
- Cache write (lista envuelta como `{"items": [...]}`).

### 5.3 `FinnhubProvider` (`providers/finnhub_provider.py`)

- **Soporta**: `get_company_profile`, `get_analyst_data`, `get_rating_changes`, `get_upcoming_earnings`
- **Wrapper**: `finnhub.Client(api_key=...)`
- **Auth**: API key desde env var `FINNHUB_API_KEY` (cargada via `python-dotenv`). Si falta, el provider se deshabilita: en el `__init__` log warning, todos los métodos lanzan `ProviderError("API key missing")`.
- **Endpoints**:
  - `get_company_profile` → `client.company_profile2(symbol=...)`. Mapeo: `marketCapitalization` viene en millones USD → multiplicar × 1e6.
  - `get_analyst_data` → `client.recommendation_trends(symbol=...)` (más reciente) + `client.price_target(symbol=...)`. Combinar en un solo `AnalystData`.
    - `recommendation_mean` se **computa** desde los counts (Finnhub no lo provee directo):  
      `mean = (1·strong_buy + 2·buy + 3·hold + 4·sell + 5·strong_sell) / total_count`  
      Si `total_count == 0`, queda `None`.
  - `get_rating_changes` → `client.upgrade_downgrade(symbol=..., from_=..., to=...)` con rango = hoy - lookback_weeks. Mapear acciones.
  - `get_upcoming_earnings` → `client.earnings_calendar(_from=hoy, to=hoy+lookforward_days, symbol=...)`.
- **Rate limit**: 60 req/min en free tier. Usar `RateLimiter` (§9) en cada llamada.
- **Cache**: sí.

## 6. Orquestador `DataService` (`providers/service.py`)

```python
class DataService:
    """
    Orquesta múltiples providers con fallback por método.
    Configurable por orden de prioridad por capacidad.
    """
    def __init__(
        self,
        ohlcv_providers: list[DataProvider],
        profile_providers: list[DataProvider],
        financials_providers: list[DataProvider],
        analyst_providers: list[DataProvider],
        rating_providers: list[DataProvider],
        earnings_providers: list[DataProvider],
    ): ...

    def get_ohlcv(self, ticker, start, end, interval="1d") -> pd.DataFrame:
        # intenta en orden; primer éxito gana; si todos fallan, propaga el último error
        ...
    # idem para los demás
```

**Comportamiento esperado del fallback**:

- Itera providers en orden.
- Cada llamada se envuelve en `try/except (ProviderError, NotSupportedError, RequestException)`.
- Si falla, log con nivel WARNING incluyendo nombre del provider y razón.
- Si todos fallan, log ERROR y propaga el último error.
- Si tiene éxito, log INFO con `provider_used`.

**Factory recomendada** (`providers/factory.py` o helper en `service.py`):

```python
def build_default_data_service() -> DataService:
    yf = YFinanceProvider()
    fh = FinnhubProvider()  # se autodeshabilita si no hay key
    return DataService(
        ohlcv_providers=[yf],
        profile_providers=[yf, fh],
        financials_providers=[yf],
        analyst_providers=[yf, fh],
        rating_providers=[yf],
        earnings_providers=[yf, fh],
    )
```

## 7. Normalización de tickers (`providers/tickers.py`)

**Formato canónico interno**: estilo yfinance.

- US: sin sufijo. `AAPL`, `MSFT`, `NVDA`.
- Europa (sufijos soportados en MVP):
  - `.L` — London (LSE)
  - `.DE` — Xetra
  - `.PA` — Paris (Euronext)
  - `.MI` — Milán (Borsa Italiana)
  - `.MC` — Madrid (BME)
  - `.AS` — Ámsterdam (Euronext)
  - `.SW` — SIX Swiss Exchange
  - `.CO` — Copenhague
  - `.ST` — Estocolmo
  - `.HE` — Helsinki
  - `.OL` — Oslo
  - `.BR` — Bruselas
  - `.LS` — Lisboa
  - `.VI` — Viena

**Conversores por provider**:

- Stooq:
  - US: minúsculas + `.us` → `AAPL` ⇒ `aapl.us`
  - Europa: tabla de mapping. `VOW3.DE` ⇒ `vow3.de`, `ASML.AS` ⇒ `asml.nl`, `NESN.SW` ⇒ `nesn.ch`, `SAN.MC` ⇒ `san.es`, etc. **Definir la tabla completa de mapping yfinance → Stooq en el código**, con un test que la cubra.
- yfinance: formato canónico es el nativo, identidad.
- Finnhub: US sin sufijo igual que canónico. Europa: usar el ticker tal cual pero algunos exchanges requieren prefijos distintos (chequear endpoints concretos en docs Finnhub, documentar en el código).

Exponer:

```python
def to_stooq(ticker: str) -> str: ...
def to_yfinance(ticker: str) -> str: ...
def to_finnhub(ticker: str) -> str: ...
```

## 8. Caching (`providers/cache.py`)

**Ubicación**: `data/cache/`

**Layout**:

```
data/cache/
├── ohlcv/{ticker}_{interval}.parquet
├── profile/{provider}/{ticker}.json
├── financials/{provider}/{ticker}.json
├── analyst/{provider}/{ticker}.json
├── ratings/{provider}/{ticker}.json
├── earnings/{provider}/{ticker}.json
└── earnings_history/{provider}/{ticker}_{lookback_days}.json
```

**TTL por tipo**:

| Tipo | TTL |
|---|---|
| ohlcv | 24h (después del cierre del día) |
| profile | 7 días |
| financials | 7 días |
| analyst | 24h |
| ratings | 24h |
| earnings | 24h |
| earnings_history | 24h |

**Política específica de OHLCV**: el archivo `ohlcv/{ticker}_{interval}.parquet` contiene una ventana rolling de los **últimos N días hábiles desde la última fetch** (N=1500 por default, ≈6 años hábiles, suficiente para SMA200W: 200 semanas ≈ 1400 días). Comportamiento de `get_ohlcv(ticker, start, end, interval)`:

1. Si el cache existe, está fresh (TTL 24h) y `[start, end]` cae dentro del rango cacheado: devolver `cache.df.loc[start:end]`.
2. En otro caso: refetch los últimos N días desde el provider, persistir, devolver slice de `[start, end]`.

El cache key **no** incluye `start`/`end`. La ventana es interna del cache.

**API**:

```python
def get_cached(path: Path, ttl_hours: int) -> Any | None:
    """Devuelve el contenido si existe y está fresh, sino None."""

def write_cache(path: Path, data: Any) -> None:
    """Escribe data a disco. JSON para dicts, parquet para DataFrames."""
```

**Comportamiento**: cada provider chequea cache antes de la llamada de red. Si fresh, devuelve. Si stale o miss, llama, persiste y devuelve.

**Override**: variable de entorno `CACHE_DISABLED=1` desactiva todo cache (útil para debugging).

## 9. Rate limiting (`providers/rate_limit.py`)

Token bucket simple, thread-safe:

```python
class RateLimiter:
    def __init__(self, max_per_minute: int): ...
    def wait_for_slot(self) -> None:
        """Bloquea hasta que haya cupo disponible."""
```

Implementación: cola de timestamps de las últimas N llamadas; antes de cada llamada, si la más vieja está dentro del minuto, `sleep` hasta que salga.

Configuración inicial: Finnhub free tier = 60/min. Conservadoramente usar 55 para dejar margen.

## 10. Configuración (`providers/config.py`)

- Carga `.env` con `python-dotenv` (silencioso si no existe).
- Lee `FINNHUB_API_KEY` y `CACHE_DISABLED`.
- Expone constantes/getters.

`.env.example` en la raíz del repo con:

```
FINNHUB_API_KEY=
CACHE_DISABLED=0
```

`.env` (real) en gitignore (ya está cubierto por la regla `.env`).

## 11. Tests

### Estructura

```
tests/
├── conftest.py
├── providers/
│   ├── test_models.py
│   ├── test_stooq.py
│   ├── test_yfinance.py
│   ├── test_finnhub.py
│   ├── test_service.py
│   ├── test_cache.py
│   ├── test_rate_limit.py
│   └── test_tickers.py
└── fixtures/
    ├── stooq_aapl_daily.csv
    ├── yfinance_aapl_info.json
    ├── finnhub_aapl_profile.json
    ├── finnhub_aapl_recommendation.json
    ├── finnhub_aapl_price_target.json
    ├── finnhub_aapl_upgrade_downgrade.json
    └── finnhub_aapl_earnings.json
```

### Reglas

- Tests **unitarios sin red**. Para Stooq mockear `requests.get` con `responses`. Para yfinance mockear `yf.Ticker` con `unittest.mock`. Para Finnhub mockear el cliente.
- Fixtures = capturas reales (mínimas) en `tests/fixtures/`. Generadas inicialmente con un script aparte; commiteadas como data de test.
- Cada provider tiene tests de:
  - Caso feliz por método soportado
  - Métodos no soportados lanzan `NotSupportedError`
  - Ticker inválido / data vacía → `ProviderError`
  - Cache hit vs miss
- `DataService` test: orquestación, fallback (primer provider falla, segundo responde), todos fallan → propaga error.
- `RateLimiter` test: con `max_per_minute=2` y `freezegun` o `time.monotonic` mockeado, verificar que la tercera llamada bloquea.
- Marker `@pytest.mark.live` para tests con llamadas reales (no corren por default).

### Smoke test manual

`src/puts_screener/smoke_test_providers.py`:

- Toma una lista hardcodeada: `["AAPL", "NVDA", "ASML.AS", "NESN.SW"]`.
- Construye `DataService` con `build_default_data_service()`.
- Por cada ticker pide: OHLCV últimos 30 días, profile, financials, analyst data, rating changes, earnings.
- Imprime tabla con los resultados (qué se obtuvo, qué falló, qué provider se usó).
- Corre con: `python -m puts_screener.smoke_test_providers`.

## 12. Criterios de aceptación

- [ ] Estructura de archivos creada según §13
- [ ] Modelos en `models.py` con type hints completos
- [ ] Tres providers implementados con sus métodos soportados
- [ ] `DataService` con fallback funcionando
- [ ] Cache en parquet/JSON con TTL
- [ ] RateLimiter para Finnhub
- [ ] Normalización de tickers para US + 14 exchanges europeos
- [ ] Suite de tests pasa: `pytest -v` con 0 errores
- [ ] `ruff check src/ tests/` sin issues
- [ ] Smoke test corre limpio para los 4 tickers de referencia
- [ ] README actualizado con sección de "Configuración" mencionando `.env.example`

## 13. Archivos a crear/modificar

```
src/puts_screener/
├── providers/
│   ├── __init__.py
│   ├── base.py
│   ├── models.py
│   ├── stooq.py
│   ├── yfinance_provider.py
│   ├── finnhub_provider.py
│   ├── service.py
│   ├── factory.py
│   ├── cache.py
│   ├── rate_limit.py
│   ├── tickers.py
│   └── config.py
└── smoke_test_providers.py

tests/
├── conftest.py
├── providers/
│   ├── __init__.py
│   ├── test_models.py
│   ├── test_stooq.py
│   ├── test_yfinance.py
│   ├── test_finnhub.py
│   ├── test_service.py
│   ├── test_cache.py
│   ├── test_rate_limit.py
│   └── test_tickers.py
└── fixtures/
    └── (capturadas durante implementación)

.env.example  (raíz)
```

## 14. Decisiones registradas

- **Sync vs async**: sync. Para batch diario con paralelismo opcional vía thread pool, alcanza. Async se considera si la corrida pasa de 30 min.
- **Cache en disco vs memoria**: disco. Sobrevive a reinicios y a GitHub Actions ephemeral runners (cuando lleguemos a esa fase, el repo lleva el cache).
- **Manejo de Europa**: cobertura inicial 14 exchanges. Si aparecen necesidades de Stoxx no cubiertos (Praga, Varsovia, Atenas), se agregan a la tabla.
- **Tickers ADR**: por ahora se tratan como US. Los duals listings europeos se identifican por el sufijo.
- **Post-smoke-test 2026-05-21**: Stooq removido del default por cambio a API key en marzo 2026. yfinance asumió el rol de provider primario en todos los métodos. Finnhub queda como fallback opcional solo para US. Stooq sigue implementado y testeado para uso futuro.
- **Rating changes en EU**: yfinance no provee `upgrades_downgrades` para tickers europeos. El método retorna lista vacía sin error. El filtro de "downgrades 6w" del SOP se aplicará efectivamente solo a tickers US.
- **Extensión retroactiva 2026-05-22**: Agregado `get_historical_earnings` para soportar la detección de T4 (post-earnings dip) en spec 02. Implementado solo en yfinance por ahora; Finnhub free no expone ese endpoint.
- **`OHLCV_ROLLING_DAYS` bumpeado de 800 a 1500 días**: necesario para que SMA200W (200 semanas ≈ 1400 días hábiles) se pueda calcular con el cache.
