# Spec 09 — Streamlit MVP solo-lectura (Fase 5)

> Web app local de solo-lectura para exploración interactiva de los runs persistidos en `screening_history.db`. Lista de candidatos filtrable + vista de detalle con chart Plotly (candlestick + 3 MAs + zona de soporte sombreada + spot + strikes). **No re-ejecuta el pipeline**: es una capa de visualización sobre los artefactos que el cron diario ya genera y commitea. Forma de uso: `streamlit run -m puts_screener.streamlit_app.app` cuando el usuario quiere explorar.

> **Estado**: documentación post-hoc del trabajo cerrado el 2026-05-28. Refleja el código real (4 commits: `4a56da0`, `039024c`, `4572542`, `657412d`). 501 tests verdes post-spec, smoke checklist 8/8 PASS.

## 1. Objetivo

Cerrar el gap entre los runs automáticos (cron diario que publica a GitHub Pages) y el análisis exploratorio que hoy requiere `git pull` + abrir CSV/HTML manualmente. La app permite:

- Elegir un run histórico desde un selector (último por default, hasta 30 runs).
- Listar los candidatos del run elegido en una tabla filtrable (tier, sector, score mínimo, presencia de earnings/ex-div/macro en 45d).
- Clickear una fila y ver detalle: chart interactivo con overlays del SOP + datos del Paso 1/2/3 + strikes heurísticos.
- Cambiar el periodo del chart (3/6/12/24 meses) sin re-cargar nada más.

Diferencial real sobre Pages: zoom, hover, overlays, y filtros en vivo sobre el set completo. Diferido a iteraciones futuras: panel de ejecución con thresholds editables, overlays adicionales (AVWAPs anclados, pivots, gaps, fibs).

## 2. Scope

### En scope

- Lectura de `screening_history.db` (runs, candidates, support_zones) — sin escrituras.
- Lectura de parquets de OHLCV cacheados en `data/cache/ohlcv/` — sin TTL (los runs históricos pueden ser viejos).
- Sidebar con: selector de run (default = último), filtros por tier (multiselect T1-T5), sector (multiselect derivado del run), score mínimo (slider 0-25), tres tri-state selectboxes (earnings/ex-div/macro en 45d).
- Tabla principal de candidatos del run filtrado, con selección de fila para abrir detalle.
- Vista de detalle: header `{ticker} — {tipo_T}`, toggle de periodo (3/6/12/24m, default 12), chart Plotly (candlestick + SMA200W + EMA200D + SMA50D + zona sombreada + spot dotted + strikes dashed), y tres columnas con Paso 1 / Paso 2 / Paso 3 + strikes.
- Caching por `@st.cache_data(ttl=300)` para queries a la DB.
- Sin tests automatizados de UI (Streamlit). Smoke checklist manual de 8 items vía `streamlit.testing.v1.AppTest`.

### Fuera de scope

- **Ejecución del pipeline desde la UI**: sin botón "correr screening", sin loader bloqueante. Diferido a Fase 5.5/6 una vez validada la utilidad de la vista de exploración. La rutina actual sigue siendo "el cron corre, yo abro la app".
- **Edición de thresholds** (config_filters, config_supports) desde la UI. Requiere persistencia YAML + validación + manejo de runs versionados. Trabajo significativo para ROI incierto antes de uso real.
- **Overlays adicionales del chart**: AVWAPs anclados (pivot_low / earnings / 52w_high), pivots detectados, gaps no rellenados, fibs (618/786). El set MVP (3 MAs + zona + spot + strikes) cubre lo que el SOP usa más; los demás se priorizan por uso real, no por hipótesis.
- **Persistencia de pivots históricos**: se recalculan al vuelo desde OHLCV cacheado. Cero migración de schema. Si backtesting (~2026-06-28) los necesita históricos, se reabre la decisión ahí.
- **Comparación entre runs** lado a lado (embudo run A vs run B, candidatos que aparecieron/desaparecieron). Útil pero no urgente para MVP.
- **Deploy remoto** (VPS, Streamlit Cloud, etc.): la app es local. Punto. Los runs ya están publicados en Pages para el caso "quiero ver desde el celular".
- **Multi-usuario / autenticación**: uso personal local.

## 3. Decisiones de parametrización

Constantes nuevas en `src/puts_screener/config_streamlit.py` (módulo nuevo).

| Constante | Valor | Justificación |
|---|---|---|
| `STREAMLIT_PAGE_TITLE` | `"Puts Screener"` | Título del browser tab + sidebar. |
| `STREAMLIT_PAGE_ICON` | `"📉"` | Favicon emoji. |
| `STREAMLIT_DEFAULT_CHART_MONTHS` | `12` | Default del toggle de periodo. Cubre 1 año de price action, suficiente para evaluar la zona de soporte sin perder detalle reciente. |
| `STREAMLIT_CHART_MONTH_OPTIONS` | `(3, 6, 12, 24)` | Opciones del toggle. 3m para zoom táctico, 24m para tendencia secular. |
| `STREAMLIT_CHART_HEIGHT_PX` | `600` | Altura del chart en píxeles. Razonable en monitores 1080p+ sin scroll vertical en el detalle. |
| `STREAMLIT_ZONE_BAND_COLOR` | `"rgba(0, 180, 0, 0.18)"` | Verde traslúcido para la banda de zona (semánticamente "soporte"). |
| `STREAMLIT_ZONE_BAND_OPACITY` | `0.18` | Reservado para futuras iteraciones (override de opacidad sin tocar el color). |
| `STREAMLIT_MA_COLORS` | `{"SMA200W": "#FF6B35", "EMA200D": "#004E89", "SMA50D": "#9B59B6"}` | Naranja / azul / violeta — distinguibles en chart con candles verde/rojo, contrastan con la banda verde. |
| `STREAMLIT_STRIKE_COLORS` | `{"aggressive": "#E74C3C", "natural": "#F39C12", "conservative": "#27AE60"}` | Rojo / naranja / verde por agresividad. Coherente con la semántica de riesgo. |
| `STREAMLIT_SPOT_LINE_COLOR` | `"#555"` | Gris neutro. El spot es referencia, no foco visual. |
| `STREAMLIT_CANDLE_INCREASING` | `"#26A69A"` | Verde-teal estándar para candles alcistas (TradingView-like). |
| `STREAMLIT_CANDLE_DECREASING` | `"#EF5350"` | Rojo estándar para bajistas. |
| `STREAMLIT_DB_QUERY_CACHE_TTL_SECONDS` | `300` | 5 minutos. Suficiente para evitar re-hitear la DB en cada rerun de filtros sin servir data stale tras un cron nuevo. |
| `STREAMLIT_OHLCV_CACHE_TTL_SECONDS` | `300` | Mismo TTL que queries de DB. Reservado para futura cacheo de parquets (no usado hoy). |
| `STREAMLIT_SIDEBAR_RUN_LIMIT` | `30` | Tope de runs históricos en el selector. 30 runs ≈ 6 semanas de cron diario. |

## 4. Modelos / dataclasses

Cinco dataclasses frozen, todas en `src/puts_screener/streamlit_app/`.

### 4.1 `models.py`

```python
@dataclass(frozen=True)
class RunSummary:
    """Metadatos de un run para listar en el selector."""
    run_id: str
    started_at: datetime
    finished_at: datetime | None
    universe_size: int
    candidates_passed: int
    universes: tuple[str, ...]

    @property
    def display_label(self) -> str:
        """Ej: '2026-05-28 17:24 — 50 candidatos (sp500+nasdaq100+stoxx600+watchlist)'."""

@dataclass(frozen=True)
class CandidateRow:
    """Fila resumida de un candidato para la lista filtrable.

    Campos derivados del JOIN candidates ⨝ support_zones(is_best=1). Para
    candidates con pasa_paso_2=1 pero sin best_zone (edge case), los tres
    best_zone_* quedan en None.
    """
    ticker: str
    tipo_T: str
    spot: float
    sector: str
    country: str
    momentum_score: int
    universes: tuple[str, ...]
    best_zone_score: float | None
    best_zone_tier: int | None
    best_zone_distance_pct: float | None
    earnings_en_45d: bool
    ex_div_en_45d: bool
    tiene_eventos_macro_en_45d: bool
    strike_natural: float | None
    currency: str

@dataclass(frozen=True)
class CandidateDetail:
    """Detalle completo para la vista de chart + tabla."""
    row: CandidateRow
    best_zone: SupportZone | None
    spot: float
    sma_50w: float | None
    sma_200w: float | None
    rsi_d: float | None
    rsi_w: float | None
    atr_14: float | None
    hv_percentile_52w: float | None
    market_cap: float | None
    earnings_date: date | None
    ex_div_date: date | None
    ex_div_amount: float | None
    eventos_macro: tuple[dict, ...]
    strikes: dict[str, float | None]
    flags_legibles: tuple[str, ...]
    momentum_signals: tuple[str, ...]
```

### 4.2 `filters.py`

```python
@dataclass(frozen=True)
class FilterState:
    """Estado de los filtros. Vacíos / None significa 'no filtrar por ese criterio'."""
    tier: frozenset[str] = frozenset()
    sector: frozenset[str] = frozenset()
    score_min: float = 0.0
    requires_earnings_in_45d: bool | None = None
    requires_ex_div_in_45d: bool | None = None
    requires_macro_in_45d: bool | None = None
```

### 4.3 `chart.py`

```python
@dataclass(frozen=True)
class ChartPayload:
    """Datos pre-calculados listos para el render del chart."""
    ticker: str
    currency: str
    ohlcv: pd.DataFrame
    sma_200w: pd.Series
    ema_200d: pd.Series
    sma_50d: pd.Series
    zone_lower: float | None
    zone_upper: float | None
    spot: float
    strikes: dict[str, float | None]
```

## 5. APIs públicas

### 5.1 `indicators.py` — helpers de series (Tanda 0)

```python
def sma_daily_series(ohlcv: pd.DataFrame, length: int) -> pd.Series:
    """Series completa de SMA diaria sobre Close. Las primeras length-1 son NaN."""

def ema_daily_series(ohlcv: pd.DataFrame, length: int) -> pd.Series:
    """Series completa de EMA diaria sobre Close (span=length, adjust=False).
    Si len(ohlcv) < length, devuelve Series llena de NaN del mismo largo
    (consistente con ema_daily scalar que retorna None)."""

def sma_weekly_series(ohlcv: pd.DataFrame, weeks: int) -> pd.Series:
    """Series semanal sobre Close resampled a W-FRI. Las primeras weeks-1 son NaN.
    IMPORTANTE: el caller debe reindexar al index diario si quiere alinear con un
    chart diario. Esta función NO lo hace."""
```

### 5.2 `providers/cache.py` — lectura sin TTL (Tanda 0)

```python
def read_ohlcv_raw(ticker: str, interval: str = "1d") -> pd.DataFrame | None:
    """Lee el parquet de OHLCV cacheado SIN chequeo de TTL.

    Para uso de apps de solo-lectura sobre runs históricos. Devuelve None si el
    parquet no existe. NO valida edad del archivo."""
```

### 5.3 `streamlit_app/data_loader.py` (Tanda 1)

```python
def list_recent_runs(limit: int = 30, db_path: Path | None = None) -> list[RunSummary]:
    """Lista los últimos `limit` runs ordenados por started_at descendente."""

def load_run_candidates(run_id: str, db_path: Path | None = None) -> list[CandidateRow]:
    """JOIN LEFT con support_zones(is_best=1). Solo incluye los que pasaron Paso 2.
    Candidatos con pasa_paso_2=1 sin best_zone (edge case) van al final con
    best_zone_*=None. Vacío si el run no existe."""

def load_best_zone(
    run_id: str, ticker: str, db_path: Path | None = None
) -> SupportZone | None:
    """Devuelve la best zone reconstruida, o None. Usa idx_support_zones_best."""

def load_candidate_detail(
    run_id: str, ticker: str, db_path: Path | None = None
) -> CandidateDetail:
    """Combina la fila de candidates + la best_zone + JSON parseados.

    Raises:
        ValueError: si no existe (run_id, ticker)."""
```

### 5.4 `streamlit_app/filters.py` (Tanda 1)

```python
def apply_filters(rows: list[CandidateRow], state: FilterState) -> list[CandidateRow]:
    """Aplica los filtros del FilterState. Preserva el orden de entrada (score desc).

    Semántica:
    - tier/sector: si el set es vacío, no filtra; sino exige pertenencia.
    - score_min: si > 0, exige best_zone_score >= score_min (None se excluyen).
      Si == 0, no filtra y los None se incluyen.
    - requires_*_in_45d: si None, ignora; si True/False, exige match exacto."""
```

### 5.5 `streamlit_app/chart.py` (Tanda 2 + Tanda 3 refactor)

```python
def build_chart_payload(detail: CandidateDetail, months: int) -> ChartPayload | None:
    """Lee OHLCV del cache, calcula las 3 MAs sobre la serie COMPLETA, trunca al periodo.

    Las MAs se calculan SIEMPRE sobre ohlcv_full (no sobre la ventana mostrada):
    así SMA200W tiene valores válidos desde el inicio del rango visible siempre que
    el cache tenga suficiente histórico.

    Returns:
        ChartPayload con OHLCV + 3 MAs alineadas al index diario, bounds y strikes.
        None si el parquet de OHLCV no existe (ticker no fue cacheado)."""

def build_plotly_figure(payload: ChartPayload) -> go.Figure:
    """Construye un go.Figure declarativo. Función pura, no toca Streamlit.

    Capas (de fondo a frente): candlestick, 3 MAs, banda de zona (rect),
    línea de spot (dotted), 3 strikes (dashed). Strikes con value None se saltean."""
```

### 5.6 `streamlit_app/views.py` (Tanda 3)

```python
@st.cache_data(ttl=STREAMLIT_DB_QUERY_CACHE_TTL_SECONDS)
def _cached_list_runs() -> list[RunSummary]: ...

@st.cache_data(ttl=STREAMLIT_DB_QUERY_CACHE_TTL_SECONDS)
def _cached_run_candidates(run_id: str) -> list[CandidateRow]: ...

@st.cache_data(ttl=STREAMLIT_DB_QUERY_CACHE_TTL_SECONDS)
def _cached_candidate_detail(run_id: str, ticker: str) -> CandidateDetail: ...

def render_sidebar_run_selector() -> str:
    """Sidebar: título + selector de run. Devuelve el run_id seleccionado."""

def render_sidebar_filters(rows: list[CandidateRow]) -> FilterState:
    """Sidebar: filtros derivados de los rows del run actual. Devuelve FilterState."""

def render_candidates_table(rows: list[CandidateRow]) -> str | None:
    """Tabla principal con candidatos filtrados (st.dataframe con on_select='rerun',
    selection_mode='single-row', key='candidates_table').
    Devuelve el ticker de la fila seleccionada o None."""

def render_candidate_detail(detail: CandidateDetail) -> None:
    """Vista de detalle: header → toggle de periodo → chart Plotly → tres
    columnas (Paso 1 / Paso 2 / Paso 3 + strikes)."""
```

### 5.7 `streamlit_app/app.py` (Tanda 3)

```python
def main() -> None:
    """Entrypoint Streamlit. Compone sidebar + tabla + detalle."""
```

## 6. Algoritmos

### 6.1 Cálculo de series MAs ANTES de truncar (clave del chart)

```
build_chart_payload(detail, months):
    ohlcv_full = read_ohlcv_raw(detail.row.ticker, "1d")
    if ohlcv_full is None:
        return None

    # 1. Series completas sobre la serie original (sin truncar).
    sma_200w_weekly = sma_weekly_series(ohlcv_full, weeks=200)
    sma_200w_full = sma_200w_weekly.reindex(ohlcv_full.index, method="ffill")
    ema_200d_full = ema_daily_series(ohlcv_full, length=200)
    sma_50d_full = sma_daily_series(ohlcv_full, length=50)

    # 2. Truncar al periodo pedido (DateOffset, no timedelta).
    cutoff = ohlcv_full.index[-1] - pd.DateOffset(months=months)
    ohlcv = ohlcv_full[ohlcv_full.index >= cutoff]
    sma_200w = sma_200w_full[sma_200w_full.index >= cutoff]
    ema_200d = ema_200d_full[ema_200d_full.index >= cutoff]
    sma_50d = sma_50d_full[sma_50d_full.index >= cutoff]

    # 3. Bounds de la best_zone si existe.
    zone_lower, zone_upper = (zone.lower_bound, zone.upper_bound) if zone else (None, None)

    return ChartPayload(...)
```

Por qué calcular sobre `ohlcv_full` y truncar después: SMA200W necesita ~1000 business days de warmup; si truncamos primero a 12 meses (~252 bdays), la SMA200W queda NaN en toda la ventana visible. Calcular sobre el cache completo (típicamente 1500 bdays = ~6 años) garantiza valores válidos desde el inicio del rango mostrado.

### 6.2 Construcción del go.Figure declarativo

```
build_plotly_figure(payload):
    fig = go.Figure()

    # 1. Candlestick (capa de fondo)
    fig.add_trace(go.Candlestick(x, open, high, low, close,
        increasing_line_color=STREAMLIT_CANDLE_INCREASING,
        decreasing_line_color=STREAMLIT_CANDLE_DECREASING))

    # 2. 3 MAs como Scatter mode='lines'
    for label, series in [("SMA200W", sma_200w), ("EMA200D", ema_200d), ("SMA50D", sma_50d)]:
        fig.add_trace(go.Scatter(x=series.index, y=series.values, mode="lines",
            line={"color": STREAMLIT_MA_COLORS[label], "width": 1.5}, name=label))

    # 3. Banda de zona (solo si zone_lower y zone_upper no son None)
    if zone_lower is not None and zone_upper is not None:
        fig.add_hrect(y0=zone_lower, y1=zone_upper,
            fillcolor=STREAMLIT_ZONE_BAND_COLOR, line_width=0,
            annotation_text="Zona", annotation_position="top left")

    # 4. Spot dotted
    fig.add_hline(y=spot, line_dash="dot", line_color=STREAMLIT_SPOT_LINE_COLOR, ...)

    # 5. 3 strikes dashed (skip si None)
    for kind in ("aggressive", "natural", "conservative"):
        value = strikes.get(kind)
        if value is None: continue
        fig.add_hline(y=value, line_dash="dash", line_color=STREAMLIT_STRIKE_COLORS[kind], ...)

    # 6. Layout
    fig.update_layout(height=STREAMLIT_CHART_HEIGHT_PX,
        xaxis_rangeslider_visible=False, hovermode="x unified", ...)

    return fig
```

### 6.3 Filtros (`apply_filters`)

Iteración lineal sobre `rows`, preserva orden de entrada (score desc desde la query). Para cada fila aplica los 6 gates en cascada con `continue`. Set vacío en tier/sector = no filtrar. `score_min == 0` = incluir filas con `best_zone_score is None`; `score_min > 0` = excluirlas.

### 6.4 Mapeo país → divisa

`_COUNTRY_TO_CURRENCY` privado en `data_loader.py`. Claves son `CompanyProfile.country` de yfinance en inglés completo ("United States", "United Kingdom", "Germany", "France", "Netherlands", "Spain", "Italy", "Switzerland", "Sweden", "Norway", "Denmark", "Finland", "Belgium", "Austria", "Ireland", "Portugal"). UK queda en GBp (peniques) consistente con spec 06 §3.4. Default `USD` para países no mapeados.

### 6.5 Score → tier

`_score_to_tier(score)` privado en `data_loader.py` réplica `SupportZone.score_tier` @property usando `SCORE_TIER_THRESHOLDS` de `config_supports`. Iterar tiers en orden descendente y devolver el primer match. Necesario en `load_run_candidates` que no reconstruye SupportZone (solo lee `support_zones.score` vía LEFT JOIN).

## 7. Persistencia y reportes

**Sin cambios de schema.** La app es solo-lectura. Lee de:

- `runs` (run_id, started_at, finished_at, universe_size, candidates_passed, universes_json)
- `candidates` (42 columnas, todas existentes pre-spec-09)
- `support_zones` con `is_best=1` (índice `idx_support_zones_best` ya existente)
- `data/cache/ohlcv/<TICKER>_<INTERVAL>.parquet` (881 files al momento del cierre)

Decisión deliberada: `load_best_zone` **no toca persistence.py**, hace su propio query `WHERE is_best=1` y reconstruye `SupportZone` localmente. Razón: el helper existente `load_support_zones` devuelve TODAS las zonas y no preserva el flag `is_best` en el dataclass reconstruido. Modificarlo arriesgaba romper las garantías de idempotencia validadas en spec 03. Ver §11.

## 8. Tests

47 tests nuevos en Tandas 0-2. Tanda 3 no agrega tests automatizados; valida con smoke checklist manual.

### 8.1 `tests/indicators/test_series_helpers.py` (Tanda 0, 7 tests)

- `test_sma_daily_series_returns_full_series`: shape match con OHLCV, primeras `length-1` son NaN.
- `test_sma_daily_series_short_input_returns_all_nan`: input < length → todo NaN.
- `test_ema_daily_series_returns_full_series`: shape match, valores reales.
- `test_ema_daily_series_short_input_returns_all_nan`: input < length → todo NaN.
- `test_sma_weekly_series_returns_weekly_index`: index semanal (W-FRI).
- `test_sma_weekly_series_short_input_returns_all_nan`: weeks > samples → todo NaN.
- `test_sma_weekly_series_with_real_window`: test con 250 weeks de datos.

### 8.2 `tests/providers/test_cache_raw.py` (Tanda 0, 3 tests)

- `test_read_ohlcv_raw_returns_none_when_missing`: archivo inexistente → None.
- `test_read_ohlcv_raw_reads_stale_cache`: archivo viejo (> TTL) → devuelve DataFrame (no None como `read_ohlcv_slice`).
- `test_read_ohlcv_raw_respects_cache_disabled`: con `CACHE_DISABLED=1` → sigue leyendo (no chequea config).

### 8.3 `tests/streamlit/test_models.py` (Tanda 1, 2 tests)

- `test_run_summary_display_label_with_universes`.
- `test_run_summary_display_label_without_universes`.

### 8.4 `tests/streamlit/test_data_loader.py` (Tanda 1, 13 tests)

- `test_list_recent_runs_orders_by_started_at_desc`.
- `test_list_recent_runs_respects_limit`.
- `test_list_recent_runs_empty_db`.
- `test_load_run_candidates_includes_only_paso_2_passers`.
- `test_load_run_candidates_orders_by_score_desc`.
- `test_load_run_candidates_handles_missing_best_zone`.
- `test_load_run_candidates_includes_currency_from_country`.
- `test_load_run_candidates_nonexistent_run_returns_empty`.
- `test_load_best_zone_returns_reconstructed_zone`.
- `test_load_best_zone_returns_none_when_no_zone`.
- `test_load_candidate_detail_combines_all_fields`.
- `test_load_candidate_detail_with_no_best_zone`.
- `test_load_candidate_detail_raises_on_missing`.

### 8.5 `tests/streamlit/test_filters.py` (Tanda 1, 10 tests)

- `test_apply_filters_empty_state_returns_all_rows`.
- `test_apply_filters_tier_set`.
- `test_apply_filters_sector_set`.
- `test_apply_filters_score_min_excludes_below_and_none`.
- `test_apply_filters_score_min_zero_includes_none`.
- `test_apply_filters_requires_earnings_true`.
- `test_apply_filters_requires_earnings_false`.
- `test_apply_filters_requires_ex_div`.
- `test_apply_filters_requires_macro`.
- `test_apply_filters_preserves_order`.

### 8.6 `tests/streamlit/test_chart.py` (Tanda 2, 12 tests)

- `test_build_chart_payload_returns_none_when_ohlcv_missing`.
- `test_build_chart_payload_truncates_to_months`.
- `test_build_chart_payload_computes_full_series_then_truncates` (clave: SMA200W tiene valores no-NaN al inicio del rango truncado a 3m).
- `test_build_chart_payload_includes_zone_bounds_when_present`.
- `test_build_chart_payload_zone_bounds_none_when_no_best_zone`.
- `test_build_plotly_figure_has_candlestick_trace`.
- `test_build_plotly_figure_has_three_ma_traces`.
- `test_build_plotly_figure_adds_zone_band_when_zone_present`.
- `test_build_plotly_figure_skips_zone_band_when_zone_none`.
- `test_build_plotly_figure_adds_strike_lines` (4 lines: 1 spot + 3 strikes).
- `test_build_plotly_figure_skips_none_strikes` (None se salta).
- `test_build_plotly_figure_layout_basics` (height, hovermode, rangeslider invisible).

### 8.7 Tanda 3 — sin tests automatizados

Decisión registrada: testar UI de Streamlit con AppTest tiene limitaciones internas conocidas (`Dataframe.select_rows` no existe; `Selectbox.set_value` falla con frozen-dataclass options; format_func+set_value en radio rompe `index()`). Mantener tests útiles requeriría inversión desproporcionada. La validación es el smoke checklist manual de 8 items.

### 8.8 Smoke checklist manual (8 items)

Corrido vía `streamlit.testing.v1.AppTest` + helpers directos para los items que el framework no puede exercitar. Resultado al cierre: **8/8 PASS**.

```bash
# Levantar la app
.venv/Scripts/python.exe -m streamlit run src/puts_screener/streamlit_app/app.py
```

1. [x] App levanta sin error (sin excepciones, sin tracebacks en consola).
2. [x] Sidebar muestra selector de run con label legible ("YYYY-MM-DD HH:MM — N candidatos (universos)").
3. [x] Tabla principal lista candidatos del último run.
4. [x] Filtros (tier, sector, score) reducen la lista en vivo.
5. [x] Click en una fila abre vista de detalle.
6. [x] Chart muestra candle + 3 MAs + zona + spot + strikes.
7. [x] Toggle de periodo (3/6/12/24m) refresca el chart sin error.
8. [x] Cambiar de run en sidebar refresca todo.

**Si algún ítem falla**: NO commitear. Arreglar primero.

## 9. Criterios de aceptación

- [x] `config_streamlit.py` existe con las 15 constantes de §3.
- [x] 3 helpers nuevos en `indicators.py` (`sma_daily_series`, `ema_daily_series`, `sma_weekly_series`).
- [x] `read_ohlcv_raw` existe en `providers/cache.py` sin TTL.
- [x] `streamlit_app/` paquete creado con `__init__.py`, `models.py`, `data_loader.py`, `filters.py`, `chart.py`, `views.py`, `app.py`.
- [x] `requirements.txt` agrega `streamlit>=1.39` y `plotly>=5.24` bajo `# Fase 5 — UI local (spec 09)`.
- [x] README sección "Fase 5 — App local (solo-lectura)" agregada con comandos `bash`/`powershell`.
- [x] 47 tests nuevos en verde. Total 454 (post-spec 08) → 501.
- [x] Smoke checklist 8/8 PASS.
- [x] Sin tocar `persistence.py`, `indicators.py` salvo +3 funciones, `cache.py` salvo +1 función, ni pipeline.
- [x] Sin hardcodear paths absolutos.
- [x] App es solo-lectura: no se inicia el screening desde la UI.

## 10. Archivos a crear / modificar

```
puts-screener/
├── README.md                                                  [MOD: + sección Fase 5]
├── requirements.txt                                           [MOD: + streamlit, plotly]
├── specs/
│   └── 09_streamlit_mvp.md                                    [NEW — esta spec]
├── src/puts_screener/
│   ├── config_streamlit.py                                    [NEW]
│   ├── indicators.py                                          [MOD: + 3 series helpers]
│   ├── providers/
│   │   └── cache.py                                           [MOD: + read_ohlcv_raw]
│   └── streamlit_app/
│       ├── __init__.py                                        [NEW]
│       ├── models.py                                          [NEW]
│       ├── data_loader.py                                     [NEW]
│       ├── filters.py                                         [NEW]
│       ├── chart.py                                           [NEW]
│       ├── views.py                                           [NEW]
│       └── app.py                                             [NEW]
└── tests/
    ├── indicators/
    │   ├── __init__.py                                        [NEW]
    │   └── test_series_helpers.py                             [NEW — 7 tests]
    ├── providers/
    │   └── test_cache_raw.py                                  [NEW — 3 tests]
    └── streamlit/
        ├── __init__.py                                        [NEW]
        ├── conftest.py                                        [NEW — synthetic_db fixture]
        ├── test_models.py                                     [NEW — 2 tests]
        ├── test_data_loader.py                                [NEW — 13 tests]
        ├── test_filters.py                                    [NEW — 10 tests]
        └── test_chart.py                                      [NEW — 12 tests]
```

10 archivos nuevos en src/ (1 config + 1 package marker + 6 modules en streamlit_app), 2 modificados (indicators.py, cache.py). 6 archivos nuevos en tests/ (2 package markers + 4 test files + 1 conftest). 2 docs modificados (README, requirements). 1 spec nueva.

## 11. Decisiones registradas

- **2026-05-28 — Spec 09, stack Streamlit**: Python puro, integración nativa con SQLite + parquet existentes, rápido de ensamblar. FastAPI+React queda como opción si en algún momento se necesita UX más rica o multi-usuario — no es hoy.
- **2026-05-28 — Spec 09, modo solo-lectura sin botón de ejecución**: el diferencial real sobre Pages es exploración interactiva (zoom, hover, overlays, filtros), que no requiere disparar el pipeline. El panel de ejecución con thresholds editables es la mitad del trabajo de Fase 5 (persistencia YAML, manejo de runs en UI, validación de inputs) y se diseña mejor después de validar la vista de exploración. Diferido a Fase 5.5/6.
- **2026-05-28 — Spec 09, pivots no se persisten, se recalculan al vuelo**: el costo de cómputo es trivial frente al render de Streamlit, evita migración de schema y tabla extra de mantenimiento. Si backtesting (§3.6 ROADMAP) requiere pivots históricos, se reabre la decisión ahí — no acá.
- **2026-05-28 — Spec 09, overlays MVP del chart = zona + SMA200W + EMA200D + SMA50D**: 7 overlays simultáneos (set completo: + AVWAPs + pivots + gaps + fibs) es ruido visual antes que insight, sobre todo en pantallas chicas. Las MAs principales son lo más usado en el SOP. Los overlays adicionales se priorizan por uso real una vez que la app esté funcionando — adivinar prioridades hoy es malgastar diseño.
- **2026-05-28 — Spec 09, periodo default 12m, opciones (3,6,12,24)**: 12m cubre un año de price action sin perder detalle reciente. 3m para zoom táctico (estructura intra-año), 24m para tendencia secular (validar contexto del SOP). Excluido 1m (demasiado corto para evaluar zonas de soporte) y 60m+ (la zona típica del SOP no requiere histórico tan largo).
- **2026-05-28 — Spec 09, candlestick (no line/area)**: el SOP usa price action (cuerpos, mechas, gaps) para validar zonas; line/area pierde esa info. Plotly soporta candlestick nativo, costo nulo.
- **2026-05-28 — Spec 09, último run como default**: la rutina diaria es "el cron corrió, qué hay nuevo". Default al último run minimiza clicks. El selector permite cambiar a runs históricos cuando se quiere comparar.
- **2026-05-28 — Spec 09, sidebar dropdown para runs (no tabs/grid)**: 30 runs en sidebar caben sin scroll; con tabs o grid sería pantalla completa para algo secundario al detalle del candidato. Dropdown minimiza superficie visual sin perder navegabilidad.
- **2026-05-28 — Spec 09, filtros se aplican en memoria sobre rows ya cargados**: el cache de `_cached_run_candidates(run_id)` se hidrata una vez por run (TTL 300s) y los filtros corren `apply_filters` en Python puro sobre la lista resultante. Cero queries adicionales por filtro. Streamlit re-renderiza la tabla en cada cambio de widget, pero el cómputo es O(n_candidatos) sobre listas chicas (<100 típicamente).
- **2026-05-28 — Spec 09, helper de país→divisa usa nombres completos en inglés** (no ISO 2-letras): el material de chat usaba 'US', 'GB', etc., pero `candidates.country` guarda el `CompanyProfile.country` de yfinance ("United States", "United Kingdom"). El mapping privado `_COUNTRY_TO_CURRENCY` en `data_loader.py` quedó con claves de nombre completo. Pequeña sorpresa atrapada en revisión empírica contra la DB real.
- **2026-05-28 — Spec 09, `load_best_zone` replica reconstrucción sin tocar persistence.py**: `load_support_zones` existente devuelve TODAS las zonas sin preservar el flag `is_best` en el dataclass reconstruido. Para evitar modificar persistence.py (con sus garantías de idempotencia ya validadas en spec 03), `load_best_zone` hace su propio query `WHERE is_best=1` usando el índice `idx_support_zones_best` y reconstruye el SupportZone. Trade-off aceptado: duplicación de reconstrucción a cambio de aislamiento del módulo crítico.
- **2026-05-28 — Spec 09, `width="stretch"` en `st.dataframe` y `st.plotly_chart`**: el parámetro `use_container_width=True` está deprecado en Streamlit tras 2025-12-31; hoy (2026-05-28) genera DeprecationWarning. Reemplazado por el nuevo API `width="stretch"`. Cosmético pero necesario para evitar ruido en consola.
- **2026-05-28 — Spec 09, keys explícitas en widgets**: agregadas `key="candidates_table"` (st.dataframe) y `key="period_radio"` (st.radio del toggle) para que `streamlit.testing.v1.AppTest` pueda drive el estado de selección desde session_state. AppTest tiene limitaciones internas (`Dataframe.select_rows` no existe; `Selectbox.set_value` falla con frozen dataclass options). Las keys son la salida estándar para testear via session_state directo. Patrón replicable en otros widgets si se necesita testear más superficie.
- **2026-05-28 — Spec 09, sin tests automatizados de UI**: la superficie a testear (rendering Streamlit, interacciones de widgets, state machine de selección) tiene fricciones conocidas con AppTest. El costo de mantener tests frágiles supera el beneficio. Decisión: validar con smoke checklist manual de 8 items vía AppTest + helpers directos. Si en el futuro la UI se vuelve más compleja (panel de ejecución, edición de config), reabrir.
- **2026-05-28 — Spec 09, ChartPayload congelado entre `build_chart_payload` y `build_plotly_figure`**: el separar la lógica de cómputo de la lógica de presentación permite (a) testear `build_chart_payload` sin Plotly, (b) testear `build_plotly_figure` con payloads sintéticos, (c) cachear el payload si el cómputo se vuelve caro. Hoy el cómputo es trivial; el split es defensivo para futuras iteraciones (overlays adicionales).
- **2026-05-28 — Spec 09 cierre, Fase 5 MVP terminada en 4 tandas**: scope sellado al inicio (5 decisiones: Streamlit, solo-lectura, bloqueante diferido, pivots al vuelo, overlays MVP) ejecutó sin re-aperturas. 501 tests verdes (de 454 pre-spec), smoke 8/8, sin issues abiertos. Próxima iteración esperando 1-2 semanas de uso real para priorizar entre overlays adicionales, panel de ejecución, y backtesting.
