# Spec 02 — Universe Builder + Filtros del Paso 1 del SOP

> Construcción del universo de tickers candidatos (US + Europa), fetch paralelo de datos, cálculo de indicadores técnicos, clasificación T1–T4, y aplicación de filtros del Paso 1 del SOP.

## 1. Objetivo

Producir diariamente una lista rankeada de candidatos que pasan los filtros duros del Paso 1 del SOP y a los que se les puede asignar al menos un tipo de situación T1–T4. Esta lista es el **input** de la futura spec 03 (detección de soportes).

## 2. Scope

### En scope

- Universe builder dinámico desde Wikipedia (S&P 500 + Stoxx Europe 600)
- Fetch paralelo de datos por ticker (OHLCV diario, OHLCV semanal, profile, financials, analyst data, rating changes, earnings)
- Cálculo de indicadores técnicos: SMAs, RSI, MACD, ATR, HV Percentile
- Clasificación de situación T1–T4 (T5 omitido — es manual por naturaleza)
- Aplicación de filtros del Paso 1: Calidad/Liquidez, Valoración, Momento técnico, HV Percentile (sustituto de IV Percentile). La tendencia macro NO es filtro independiente — se chequea implícitamente en la clasificación T1–T4 (§6.2).
- Persistencia de snapshots en SQLite
- Output de la lista filtrada (en memoria, para el siguiente paso del pipeline)

### Fuera de scope

- Detección de soportes y scoring de confluencia (spec 03)
- Clasificación T5 (manual)
- Filtro de "catalizador no fundamental" en T2 (requiere lectura de news; queda como flag manual)
- Filtro de spread bid-ask de opciones (no hay opciones aún)
- Generación de reportes CSV/HTML (spec 04)
- Distinción entre eventos macro en ventana (spec 04 cubre Paso 3)

## 3. Decisiones de parametrización

El SOP usa lenguaje cualitativo en varios filtros. Las traducciones a código determinístico son:

| Constante (nombre en config_filters.py) | Valor / implementación operativa |
|---|---|
| **Filtros de calidad / liquidez (Paso 1)** | |
| `MIN_MARKET_CAP_USD` | `10_000_000_000` ($10B; del SOP) |
| `MIN_AVG_DAILY_VOLUME` | `1_000_000` acciones/día promedio últimos 3 meses |
| `MIN_FCF_TTM` | `0.0` (FCF positivo en TTM) |
| **Filtros de valoración** | |
| `MIN_PRICE_TARGET_UPSIDE` | `0.0` (price target ≥ spot; el SOP pide ">" estricto) |
| `MIN_RECOMMENDATION_BUY_RATIO` | `0.5` (mayoría Buy: `(strong_buy + buy) / total >= 0.5`) |
| `MAX_DOWNGRADES_6W` | `0` (sin downgrades en últimas 6 semanas; aplica solo a US) |
| **Filtros de momento técnico** | |
| `RSI_DAILY_THRESHOLD` | `50` (RSI diario actual < 50 con momentum positivo) |
| `RSI_DAILY_LOOKBACK_DAYS` | `3` (RSI_d_today > RSI_d_3d_ago) |
| `RSI_WEEKLY_THRESHOLD` | `50` (RSI semanal actual < 50 con momentum positivo) |
| `RSI_WEEKLY_LOOKBACK_WEEKS` | `2` (RSI_w_today > RSI_w_2w_ago) |
| `MACD_LOOKBACK_DAYS` | `3` (histograma_today > histograma_3d_ago) |
| `MACD_NEUTRAL_PCT_CHANGE` | `0.05` (cambio relativo del histograma <5% se considera neutral) |
| **Filtros de volatilidad (sustituto de IV Percentile)** | |
| `HV_PERCENTILE_MIN` | `30` (valor de HV Percentile 52w mínimo aceptable) |
| `HV_PERCENTILE_MAX` | `80` |
| **Clasificación T1–T4** | |
| `T2_DROP_PCT_5D` | `-0.10` (caída ≥10% en últimos 5 días hábiles) |
| `T3_LATERAL_DAYS` | `60` (días de lateralización mínima) |
| `T3_RANGE_COMPACTNESS` | `0.15` (`(max_60d - min_60d) / mean_60d <= 0.15`) |
| `T3_PRICE_FLOOR_FRACTION` | `0.3` (`close < min_60d + 0.3 * (max_60d - min_60d)`) |
| `T3_LATERAL_TOLERANCE` | `0.03` (\|SMA50W - SMA200W\| / SMA200W ≤ 3% = lateral tolerable) |
| `T4_LOOKBACK_DAYS` | `60` (ventana hacia atrás para detectar earnings pasados) |
| `T4_DROP_THRESHOLD` | `-0.05` (caída post-earnings ≤ -5%) |
| `T4_TOLERANCIA_TENDENCIA` | `0.97` (SMA50W ≥ SMA200W × 0.97) |
| `T4_RSI_MAX` | `55` (RSI_d en zona neutral-baja) |

**Implementación**: todas estas constantes viven en `src/puts_screener/config_filters.py` como módulo de constantes (no clases). Los tests y el código de aplicación las importan directamente. Cambiar un threshold no requiere cambiar lógica — solo este archivo.

**Nota sobre "RSI saliendo de sobreventa"**: el SOP original menciona el umbral cualitativo "<35 recuperando". En la implementación operativa adoptamos `<50 con momentum positivo` (más generoso, captura rebotes tempranos antes de tocar 35). Si se quiere ser más estricto, bajar `RSI_DAILY_THRESHOLD` y `RSI_WEEKLY_THRESHOLD` a 35 en `config_filters.py`.

## 4. Universe Builder

### 4.1 Fuentes

- **S&P 500**: `https://en.wikipedia.org/wiki/List_of_S%26P_500_companies` — tabla con columna "Symbol".
- **Stoxx Europe 600**: `https://en.wikipedia.org/wiki/STOXX_Europe_600` — tabla con columna "Ticker" o "Symbol" (verificar en implementación).

### 4.2 Adaptación de tickers EU

Stoxx 600 lista tickers con sufijos de Bloomberg o de exchange local (varía por empresa). Hay que normalizarlos al formato canónico de yfinance:

- Símbolos terminados en `.L` (London) → mantener
- Bloomberg `XXX GR` (Xetra) → `XXX.DE`
- Bloomberg `XXX FP` (Paris) → `XXX.PA`
- etc.

Crear una función `_normalize_stoxx_ticker(raw: str) -> str | None`. Si no se puede mapear (mercado fuera de los 14 soportados), retornar `None` y skipear ese ticker.

### 4.3 Cache

- Path: `data/cache/universe/sp500.json` y `data/cache/universe/stoxx600.json`
- TTL: 7 días
- Estructura: `{"tickers": [...], "fetched_at": "2026-05-21T22:00:00Z", "source_url": "..."}`

### 4.4 API pública

```python
def build_universe(refresh: bool = False) -> list[str]:
    """Construye el universo combinado S&P 500 + Stoxx 600.
    
    Args:
        refresh: si True, ignora el cache y refetchea.
    
    Returns:
        Lista de tickers en formato canónico (yfinance), deduplicada, ordenada.
    """
```

## 5. Cálculo de indicadores técnicos

Todos en `src/puts_screener/indicators.py`. Funciones puras que reciben DataFrames y devuelven valores o Series.

### 5.1 SMA semanal

```python
def sma_weekly(ohlcv_daily: pd.DataFrame, weeks: int) -> float:
    """SMA de `weeks` semanas, computado sobre cierres semanales (último cierre de cada semana)."""
```

### 5.2 RSI

Usar `pandas_ta.rsi(close, length=14)`.

- `rsi_daily(ohlcv_d) -> float` — último valor.
- `rsi_daily_series(ohlcv_d, length=14) -> pd.Series` — toda la serie (para verificar pendiente).
- `rsi_weekly(ohlcv_d) -> float` — RSI sobre cierres semanales.

```python
def rsi_weekly_series(ohlcv_daily: pd.DataFrame, length: int = 14) -> pd.Series:
    """RSI sobre cierres semanales, serie completa (para cálculo de pendiente)."""
```

### 5.3 MACD

`pandas_ta.macd(close, fast=12, slow=26, signal=9)`.

- `macd_state(ohlcv_d) -> Literal["subiendo_negativo", "subiendo_positivo", "bajando_positivo", "bajando_negativo", "neutral"]`
- La lógica:
  - `hist_today = histogram[-1]`, `hist_3d_ago = histogram[-4]`
  - Si `abs(hist_3d_ago) < 1e-9`: el histograma estaba en cero, comparar valores absolutos del actual: si `abs(hist_today) < 1e-9` → "neutral", si no → usar signo del actual y dirección "subiendo" o "bajando" según `hist_today > 0`.
  - Sino: si `abs(hist_today - hist_3d_ago) / abs(hist_3d_ago) < MACD_NEUTRAL_PCT_CHANGE` → "neutral".
  - Sino: dirección por signo de `hist_today - hist_3d_ago`, combinada con signo del histograma actual.

### 5.4 ATR

`pandas_ta.atr(high, low, close, length=14)` → último valor.

### 5.5 HV Percentile

Implementación propia (no es estándar de pandas-ta):

```python
def hv_percentile_52w(ohlcv_daily: pd.DataFrame) -> float:
    """Percentil de la volatilidad histórica 20d actual vs la ventana 52w.
    
    HV20 = std(log_returns) * sqrt(252) sobre últimos 20 días hábiles.
    Se calcula la serie HV20 sobre los últimos 252 días hábiles
    (rolling window de 20 days).
    El percentil es: count(HV20 <= HV20_today) / 252 * 100 → escala 0-100.
    
    Returns:
        Percentil entre 0 y 100. Si no hay suficiente data, raise ValueError.
    """
```

## 6. Clasificación de situación T1–T4

Módulo `src/puts_screener/classification.py`.

### 6.1 Función principal

```python
@dataclass(frozen=True)
class TypeClassification:
    tipo: str  # "T1" | "T2" | "T3" | "T4" | None
    justificacion: str  # texto humano-leíble
    matches_multiple: list[str]  # otros tipos que también matchearon (para auditoría)


def classify(
    ticker: str,
    ohlcv_daily: pd.DataFrame,
    ohlcv_weekly: pd.DataFrame,
    earnings_history: list[HistoricalEarningsEvent],
    indicators: dict,  # ya computados por el pipeline (§9 paso b)
) -> TypeClassification:
```

**Importante**: `classify` NO computa indicadores. Recibe el dict `indicators` ya populado por el pipeline (§9 paso b). Evita el doble cómputo.

### 6.2 Lógica por tipo

**T1 — Uptrend con soporte:**
- `SMA50W > SMA200W` (tendencia alcista confirmada).
- Precio actual por encima del soporte de largo plazo: `close > SMA200W`.
- Momento técnico positivo: RSI diario o semanal con momentum positivo desde nivel bajo (ver filtros §7 — el chequeo concreto vive ahí).

**T2 — Pánico / IV spike:**
- Caída ≥10% en últimos 5 días (según parametrización §3)
- `SMA50W > SMA200W` o `lateral_tolerable` (no bajista)

**T3 — Rango lateral:**
- `lateral_tolerable` (SMA50W ≈ SMA200W ±3%)
- Lateralización ≥60 días (rango compacto)
- Precio cerca del piso del rango: `close < (min_60d + 0.3 * (max_60d - min_60d))`

**T4 — Post-earnings dip:**
- Hubo un earnings en los últimos `T4_LOOKBACK_DAYS` días (default 60).
- Caída post-earnings: `(close_post_earnings - close_pre_earnings) / close_pre_earnings <= T4_DROP_THRESHOLD` (default -0.05, es decir -5%).
  - `close_post_earnings` = close del día siguiente hábil al earnings (o del mismo día si fue AMC y tomamos el cierre siguiente).
  - `close_pre_earnings` = close del día previo al earnings.
- SMA50W >= SMA200W * `T4_TOLERANCIA_TENDENCIA` (default 0.97, no bajista).
- RSI_d < `T4_RSI_MAX` (default 55, zona neutral-baja).

### 6.3 Priorización

Si múltiples tipos matchean, asignar según el orden: **T1 > T2 > T4 > T3**. El campo `matches_multiple` registra los otros que también aplicaban.

## 7. Filtros del Paso 1

Módulo `src/puts_screener/filters_step1.py`.

### 7.1 Estructura

Cada filtro es una función pura con la siguiente firma:

```python
def filter_<name>(candidate: ScreenedCandidate) -> tuple[bool, str | None]:
    """
    Args:
        candidate: ya populado con profile, financials, analyst, indicadores computados.
    Returns:
        (passes, rejection_reason). `rejection_reason` debe ser None si passes=True.
    """
```

Cada filtro lee los campos del `ScreenedCandidate` que necesita. No hay inputs separados por filtro.

Lista de filtros:

1. `filter_quality_liquidity` — chequea `profile.market_cap_usd`, `profile.avg_daily_volume_3m`, `financials.free_cash_flow_ttm`.
2. `filter_valuation` — chequea `analyst.price_target_mean`, `recommendation_buy_ratio`, `downgrades_6w_count`. El chequeo de downgrades se omite si `profile.country` indica EU (yfinance no provee la data).
3. `filter_momentum` — pasa si **al menos una** de las siguientes condiciones es verdadera:
   - **RSI diario con momentum positivo**: `rsi_d < RSI_DAILY_THRESHOLD AND rsi_d_today > rsi_d[-RSI_DAILY_LOOKBACK_DAYS-1]`
   - **RSI semanal con momentum positivo**: `rsi_w < RSI_WEEKLY_THRESHOLD AND rsi_w_today > rsi_w[-RSI_WEEKLY_LOOKBACK_WEEKS-1]`
   - **O** MACD subiendo desde negativo (ver §5.3 `macd_state`).
4. `filter_hv_percentile` — chequea `hv_percentile_52w` ∈ [`HV_PERCENTILE_MIN`, `HV_PERCENTILE_MAX`].

**Nota**: la tendencia macro NO es un filtro independiente — está chequeada implícitamente en la clasificación T1–T4 (§6.2). Si un ticker pasa la clasificación, su tendencia ya cumple lo que corresponde a su tipo.

### 7.2 Aplicación

```python
def apply_step1_filters(candidate: ScreenedCandidate) -> ScreenedCandidate:
    """Aplica todos los filtros y actualiza `pasa_filtros_paso_1` y `motivos_rechazo`."""
```

Un candidato pasa si **todos** los filtros aplicables a su tipo retornan `True`.

## 8. Modelo `ScreenedCandidate`

En `src/puts_screener/models_screening.py`:

```python
@dataclass
class ScreenedCandidate:
    # Identidad
    ticker: str
    
    # Data cruda
    profile: CompanyProfile
    financials: FinancialSnapshot
    analyst: AnalystData
    rating_changes_6w: list[RatingChange]
    earnings_event: EarningsEvent | None
    ohlcv_daily: pd.DataFrame
    ohlcv_weekly: pd.DataFrame
    
    # Clasificación
    classification: TypeClassification | None  # None si error en classify
    
    # Indicadores técnicos (computados, cacheables)
    spot: float
    sma_50w: float
    sma_200w: float
    rsi_d: float
    rsi_d_3d_ago: float
    rsi_w: float
    rsi_w_2w_ago: float
    macd_state: str
    macd_hist_3d_ago: float
    atr_14: float
    hv_percentile_52w: float
    
    # Métricas de valoración
    price_target_upside_pct: float
    recommendation_buy_ratio: float  # ratio (strong_buy + buy) / total
    downgrades_6w_count: int
    
    # Resultado
    pasa_filtros_paso_1: bool
    motivos_rechazo: list[str]
    
    # Metadatos
    fetched_at: datetime
    errors: list[str]  # errores no fatales durante el fetch/computo
```

NO es `frozen=True` porque los filtros mutan `pasa_filtros_paso_1` y `motivos_rechazo`.

## 9. Pipeline orquestador

Módulo `src/puts_screener/screening_pipeline.py`.

```python
def run_screening(
    universe: list[str],
    data_service: DataService,
    max_workers: int = 8,
    persist: bool = True,
) -> tuple[str | None, list[ScreenedCandidate]]:
    """Corre el screening completo sobre el universo.
    
    1. Para cada ticker en paralelo (ThreadPoolExecutor con max_workers):
       a. Fetch all data (6 calls al data_service)
       b. Compute indicators
       c. Classify (T1-T4)
       d. Apply step 1 filters
    2. Si `persist=True`, guarda en SQLite (ver §10).
    3. Returns (run_id, candidates). run_id es None si persist=False, sino el UUID de la corrida.
    """
```

Errores en un ticker no rompen el pipeline — se loguean y el `ScreenedCandidate` queda con `errors=[...]` y `pasa_filtros_paso_1=False`.

## 10. Persistencia (SQLite)

Path: `data/screening_history.db`

### 10.1 Esquema

```sql
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    universe_size INTEGER NOT NULL,
    candidates_passed INTEGER,
    status TEXT NOT NULL  -- 'running' | 'completed' | 'failed'
);

CREATE TABLE IF NOT EXISTS candidates (
    run_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    tipo_T TEXT,                       -- derivado de classification.tipo
    pasa_filtros_paso_1 INTEGER NOT NULL,  -- 0/1
    spot REAL,
    sma_50w REAL,
    sma_200w REAL,
    rsi_d REAL,
    rsi_d_3d_ago REAL,
    rsi_w REAL,
    rsi_w_2w_ago REAL,
    macd_state TEXT,
    macd_hist_3d_ago REAL,
    atr_14 REAL,
    hv_percentile_52w REAL,
    price_target_upside_pct REAL,
    recommendation_buy_ratio REAL,
    downgrades_6w_count INTEGER,
    market_cap REAL,                   -- bajado de candidate.profile.market_cap_usd
    sector TEXT,                       -- bajado de candidate.profile.sector
    country TEXT,                      -- bajado de candidate.profile.country
    fetched_at TEXT NOT NULL,          -- ISO timestamp
    motivos_rechazo TEXT,              -- JSON array
    errors TEXT,                       -- JSON array
    PRIMARY KEY (run_id, ticker),
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE INDEX idx_candidates_pasa ON candidates(pasa_filtros_paso_1, run_id);
CREATE INDEX idx_candidates_ticker ON candidates(ticker);
CREATE INDEX idx_candidates_tipo ON candidates(tipo_T, run_id);
```

### 10.2 API

```python
def save_run(candidates: list[ScreenedCandidate], universe_size: int) -> str:
    """Persiste la corrida completa. Devuelve el run_id (UUID)."""

def load_run(run_id: str) -> list[ScreenedCandidate]:
    """Reconstruye candidatos desde SQLite. NO restaura OHLCV (regenerable)."""

def list_runs(limit: int = 30) -> list[dict]:
    """Lista metadatos de las últimas corridas."""
```

**Mapeo dataclass → SQLite**:
- `market_cap` se baja de `candidate.profile.market_cap_usd`
- `sector` se baja de `candidate.profile.sector`
- `country` se baja de `candidate.profile.country`
- `tipo_T` se deriva de `candidate.classification.tipo` (None si classification es None)
- Los campos `motivos_rechazo` y `errors` se serializan con `json.dumps`

No guardamos OHLCV en SQLite (vive en el cache de parquet). Si necesitamos OHLCV de una corrida vieja, refetcheamos desde el cache (que ya cubre los 1500 días rolling).

**Nota**: el cache OHLCV cubre 1500 días hábiles rolling (≈6 años), suficiente para SMA200W (~1400 días).

## 11. Tests

### 11.1 Unitarios (sin red)

- `test_indicators.py`: con OHLCV sintético de fixture, verificar SMAs, RSI, MACD, ATR, HV Percentile.
- `test_classification.py`: 4 fixtures de OHLCV simulando cada arquetipo T1–T4, verificar clasificación.
- `test_filters_step1.py`: cada filtro probado con candidate sintético que pasa y que no.
- `test_universe_builder.py`: mockear `requests.get` con HTML de Wikipedia capturado, verificar parsing.
- `test_persistence.py`: round-trip de save/load con SQLite en memoria.

### 11.2 Integración

- `test_screening_pipeline.py`: con `DataService` mockeado que devuelve fixtures conocidas, correr el pipeline para 3 tickers (uno que pasa T1, uno que pasa T2, uno que no pasa) y verificar el output completo.

### 11.3 Smoke test

`src/puts_screener/smoke_test_screening.py`:
- Toma un universo chico hardcoded (10 tickers de S&P 500).
- Corre el pipeline con el `DataService` real.
- Imprime tabla con: ticker, tipo_T, pasa, motivos_rechazo.

## 12. Criterios de aceptación

- [ ] Universe builder devuelve ~1100 tickers únicos
- [ ] Indicators module pasa tests con valores conocidos
- [ ] Classification asigna T1–T4 correctamente en fixtures sintéticas
- [ ] Filters retornan razones de rechazo legibles
- [ ] Pipeline corre en paralelo y los errores aislados por ticker no rompen la corrida
- [ ] SQLite round-trip funciona
- [ ] Smoke test corre limpio para 10 tickers en <2 minutos
- [ ] `pytest -v` pasa con 0 errores
- [ ] `ruff check` limpio

## 13. Archivos a crear

```
src/puts_screener/
├── universe_builder.py
├── indicators.py
├── classification.py
├── filters_step1.py
├── screening_pipeline.py
├── models_screening.py
├── persistence.py
├── config_filters.py
└── smoke_test_screening.py

tests/screening/
├── __init__.py
├── test_universe_builder.py
├── test_indicators.py
├── test_classification.py
├── test_filters_step1.py
├── test_persistence.py
├── test_screening_pipeline.py
└── fixtures/
    ├── wikipedia_sp500_sample.html
    ├── wikipedia_stoxx600_sample.html
    ├── ohlcv_uptrend.parquet
    ├── ohlcv_panic_drop.parquet
    ├── ohlcv_sideways.parquet
    └── ohlcv_postearnings.parquet
```

## 14. Decisiones registradas

- **T5 omitido**: el SOP describe T5 como "querés ser dueño del papel a ese precio". Eso es una decisión humana/de tesis, no detectable automáticamente. Se cubre desde un workflow manual fuera del screener.
- **"Catalizador no fundamental" en T2**: simplificado a detección técnica pura (caída ≥10%). El juicio sobre la naturaleza del catalizador queda como tarea de revisión humana.
- **HV Percentile en vez de IV Percentile**: ya documentado en SPEC.md como sustituto temporal hasta integrar data de opciones.
- **Downgrades 6w para EU**: el filtro se desactiva para tickers EU (yfinance no provee la data). El candidato pasa el filtro de Valoración por default en ese caso.
- **Paralelismo con 8 workers**: número conservador. yfinance no tiene rate limit duro publicado pero responde mal con >10 conexiones simultáneas.
- **2026-05-22 — RSI threshold operativo**: el SOP cualitativo dice "<35 recuperando". La implementación adopta `<50 con momentum positivo` (más generoso, captura rebotes tempranos). Ajustable en `config_filters.py`.
- **2026-05-22 — Tendencia macro implícita en clasificación**: eliminado el filtro independiente; la clasificación T1–T4 ya gateó por tendencia, no se duplica.
- **2026-05-22 — Filtros con firma uniforme**: todos los filtros del Paso 1 reciben un `ScreenedCandidate` completo, no inputs separados. Simplifica composición y testing.
- **2026-05-22 — `classify` no recomputa indicadores**: recibe dict ya populado por el pipeline. Evita doble cómputo.
