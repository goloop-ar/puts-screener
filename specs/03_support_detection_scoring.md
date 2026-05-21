# Spec 03 — Detección de Soportes y Scoring de Confluencia

> Implementación del Paso 2 del SOP. Recibe los `ScreenedCandidate` que pasaron el Paso 1, detecta zonas de soporte, calcula score de confluencia, valida con confirmador dinámico, y produce `SupportedCandidate` con la mejor zona seleccionada.

## 1. Objetivo

Sobre cada candidato que pasó el Paso 1, identificar zonas de soporte dentro del 10% por debajo del spot, scorearlas según los 7 elementos del SOP, exigir al menos un confirmador dinámico, y devolver los candidatos cuya mejor zona alcance score ≥ 3.

## 2. Scope

### En scope

- Detección de pivots (mínimos y máximos locales significativos) sobre OHLCV diario
- Cálculo de los 7 elementos del score: SMA200 (W o D), polaridad (resistencia rota), Fibonacci 61.8% y 78.6%, AVWAP (3 anclas), HVN aproximado (sin intradía), gap alcista no cerrado, divergencia RSI/MACD
- Agrupamiento de elementos en zonas mediante clustering por proximidad (ancho zona = ± 0.5×ATR14)
- Scoring de confluencia (SMA200 = 2 pts; resto = 1 pt; máximo 1 pt por categoría aunque haya redundancia)
- Validación con confirmador dinámico obligatorio (AVWAP, HVN o divergencia)
- Filtro de proximidad: zona por debajo del spot, a distancia ≤ 10%
- Selección de la zona de mayor score por candidato (persistir todas las válidas)
- Extensión del SQLite con tabla `support_zones`
- Pipeline que procesa solo los candidatos con `pasa_filtros_paso_1=True`

### Fuera de scope

- Volume Profile real con datos intradía (requiere data de minutos, postergado a Fase 4)
- Detección de zonas de consolidación como elemento independiente (capturadas implícitamente por HVN — ver §14)
- Selección de strike y gestión de salida (Paso 4 del SOP, fase futura)
- Reportes CSV/HTML (spec 04)

## 3. Decisiones de parametrización

Todas las constantes viven en `src/puts_screener/config_supports.py` (módulo separado de `config_filters.py` para mantener cohesión por feature).

| Constante | Valor | Justificación |
|---|---|---|
| **Detección de pivots** | | |
| `PIVOT_WINDOW_BARS` | `5` | Pivot = low/high menor/mayor que las 5 barras a cada lado. Balance ruido/significancia. |
| `PIVOT_MIN_DEPTH_ATR` | `1.0` | El pivot debe estar a ≥1×ATR14 del swing opuesto previo. Filtra micro-movimientos. |
| **Ventanas de "último"** | | |
| `LAST_SWING_LOOKBACK_DAYS` | `252` | 12 meses hábiles. Si no hay pivot significativo en esa ventana, el elemento queda inválido. |
| `LAST_PIVOT_HIGH_LOOKBACK_DAYS` | `252` | Idem para polaridad (resistencias rotas relevantes). |
| `AVWAP_EARNINGS_LOOKBACK_DAYS` | `252` | Si el último earnings es más viejo que 12 meses, AVWAP de earnings queda en None. |
| **Fibonacci** | | |
| `FIB_LEVELS` | `(0.618, 0.786)` | Solo los dos del SOP. Otros niveles ignorados. |
| **HVN aproximado** | | |
| `HVN_LOOKBACK_DAYS` | `252` | 12 meses para construir el volume profile aproximado. |
| `HVN_NUM_BUCKETS` | `50` | Granularidad del histograma de precios. |
| `HVN_PERCENTILE_THRESHOLD` | `80` | Buckets ≥ percentil 80 de volumen acumulado se consideran HVN. |
| **Gaps** | | |
| `GAP_LOOKBACK_DAYS` | `252` | Solo gaps en últimos 12 meses cuentan. |
| **Divergencias** | | |
| `DIVERGENCE_LOOKBACK_DAYS` | `60` | Solo divergencias entre pivots dentro de los últimos 60 días. |
| **Zonas** | | |
| `ZONE_WIDTH_ATR_MULTIPLIER` | `0.5` | Zona = precio ± 0.5×ATR14 (del SOP). |
| `CLUSTERING_TOLERANCE_ATR` | `0.5` | Dos elementos a ≤ 0.5×ATR se consideran misma zona. |
| **Filtro de proximidad** | | |
| `MAX_DISTANCE_TO_SUPPORT_PCT` | `0.10` | Zona debe estar a ≤ 10% por debajo del spot (del SOP). |
| `MIN_DISTANCE_TO_SUPPORT_PCT` | `0.0` | La zona puede estar al spot (distancia = 0); negativa (por encima) no aplica. |
| **Scoring** | | |
| `SCORE_MIN_VALID` | `3` | Mínimo del SOP para validar zona. |
| `SCORE_SMA200_POINTS` | `2` | SMA200 (W o D, lo que primero coincida) suma 2 pts. |
| `SCORE_OTHER_ELEMENT_POINTS` | `1` | Cada otro elemento suma 1 pt. |
| `DYNAMIC_CONFIRMERS` | `("avwap", "hvn", "divergence")` | Set de elementos considerados "confirmadores dinámicos". Al menos uno obligatorio. |

## 4. Detección de pivots

Módulo `src/puts_screener/pivots.py`.

### 4.1 Definición operativa

Un **pivot bajo** en la barra `i` es válido si:

1. `low[i] < low[j]` para todo `j` ∈ `[i-N, i+N] \ {i}`, donde `N = PIVOT_WINDOW_BARS`.
2. La profundidad respecto al swing opuesto previo cumple: `(swing_high_prev - low[i]) >= PIVOT_MIN_DEPTH_ATR × ATR14[i]`.
   - `swing_high_prev` = último pivot alto confirmado antes de `i`. Si no hay (es el primer swing del histórico), usar `max(high[max(0, i-N*4):i])` como aproximación.

**Pivot alto**: simétrico (`high[i] > high[j]`, y `low[i] - swing_low_prev >= PIVOT_MIN_DEPTH_ATR × ATR14[i]`).

### 4.2 Caso borde: pivots no confirmados

Las últimas `N` barras del histórico no pueden ser pivot porque no hay `N` barras a la derecha. Esto es esperado y correcto — son pivots no confirmados todavía. La detección solo considera pivots confirmados.

### 4.3 API


```python
@dataclass(frozen=True)
class Pivot:
    date: pd.Timestamp
    price: float
    kind: Literal["low", "high"]
    atr_at_pivot: float  # ATR14 al momento del pivot — útil para clustering posterior

def detect_pivots(ohlcv_daily: pd.DataFrame, atr14_series: pd.Series) -> list[Pivot]:
    """Devuelve todos los pivots confirmados en el histórico, ordenados por fecha."""
```



`atr14_series` se pasa precalculado (el pipeline ya lo computa para indicadores).

## 5. Elementos del score

Módulo `src/puts_screener/support_elements.py`. Cada función devuelve `list[SupportLevel]` o `None`.


```python
@dataclass(frozen=True)
class SupportLevel:
    price: float                              # nivel de precio del elemento
    element: str                              # "sma_200w" | "sma_200d" | "fib_618" | "fib_786" | "polarity" | "avwap_pivot_low" | "avwap_earnings" | "avwap_52w_high" | "hvn" | "gap_unfilled" | "divergence"
    points: int                               # SMA200=2, resto=1
    metadata: dict                            # info auxiliar (e.g. fecha del pivot ancla, valor del gap)
```



### 5.1 SMA 200 (semanal o diaria)


```python
def sma_200_levels(ohlcv_daily: pd.DataFrame, ohlcv_weekly: pd.DataFrame) -> list[SupportLevel]:
    """Devuelve hasta 2 SupportLevel: SMA200W y EMA200D si están definidas.
    
    El SOP asigna 2 puntos si UNO de los dos coincide con la zona. La asignación
    de puntos no se duplica al pasar por el clustering (§6.3).
    """
```



- `sma_200w` = SMA de 200 cierres semanales del último cierre disponible.
- `sma_200d` = EMA de 200 días daily (el SOP dice "SMA 200 Semanal o EMA 200 Diaria"). EMA, no SMA.

### 5.2 Polaridad (resistencia rota)


```python
def polarity_levels(
    pivots: list[Pivot],
    close_today: float,
    today: pd.Timestamp,
) -> list[SupportLevel]:
    """Pivots altos de los últimos LAST_PIVOT_HIGH_LOOKBACK_DAYS que el precio ya superó."""
```



Algoritmo:
1. Filtrar `pivots` por `kind == "high"` y `pivot.date >= today - LAST_PIVOT_HIGH_LOOKBACK_DAYS`.
2. Filtrar por `pivot.price < close_today` (el precio ya rompió esa resistencia).
3. Cada uno genera un `SupportLevel(price=pivot.price, element="polarity", points=1, metadata={"pivot_date": ...})`.

### 5.3 Fibonacci 61.8% y 78.6%


```python
def fib_levels(
    pivots: list[Pivot],
    close_today: float,
    today: pd.Timestamp,
) -> list[SupportLevel]:
    """Niveles 61.8% y 78.6% del último impulso alcista significativo.
    
    Devuelve [] si no se puede identificar un impulso válido.
    """
```



Algoritmo de identificación del **último impulso alcista**:
1. Filtrar `pivots` dentro de `LAST_SWING_LOOKBACK_DAYS` desde hoy.
2. Identificar el último pivot bajo `pivot_low_last` (el más reciente en el tiempo).
3. Identificar el último pivot alto `pivot_high_last` que cumpla `pivot_high_last.date > pivot_low_last.date`.
4. Casos borde:
   - Si no existe `pivot_low_last` en la ventana → `return []` (sin impulso identificable).
   - Si no existe `pivot_high_last` posterior al `pivot_low_last` (estamos en plena subida sin pivot alto confirmado todavía) → usar `close_today` como `pivot_high_last.price` y `today` como fecha. **Justificación**: el impulso está en curso, los fibs se proyectan sobre lo subido hasta ahora.
   - Si `pivot_high_last.price <= pivot_low_last.price` → `return []` (no fue impulso alcista; data corrupta o ruido).
5. Calcular:
   - `swing_range = high_price - low_price`
   - `fib_618 = high_price - 0.618 × swing_range`
   - `fib_786 = high_price - 0.786 × swing_range`
6. Devolver dos `SupportLevel` con elemento `"fib_618"` y `"fib_786"`.

### 5.4 Anchored VWAP (3 anclas)


```python
def avwap_levels(
    ohlcv_daily: pd.DataFrame,
    pivots: list[Pivot],
    last_earnings_date: pd.Timestamp | None,
    today: pd.Timestamp,
) -> list[SupportLevel]:
    """Hasta 3 AVWAPs: desde último pivot bajo, último earnings, último máximo 52w."""
```



**Fórmula AVWAP** desde fecha ancla `t0`:


```
typical_price[t] = (high[t] + low[t] + close[t]) / 3
AVWAP[t] = Σ(typical_price[i] × volume[i]) for i in [t0, t] / Σ(volume[i]) for i in [t0, t]
```



El valor que se persiste es `AVWAP[today]` — la línea evoluciona pero solo importa dónde está hoy.

**Anclas**:
1. **Último pivot bajo significativo**: el `pivot_low_last` ya identificado en §5.3.
   - Si está fuera de `LAST_SWING_LOOKBACK_DAYS` → ancla inválida, no se calcula.
2. **Último earnings**: `last_earnings_date` (viene del `HistoricalEarningsEvent` más reciente del candidato).
   - Si es `None` o `today - last_earnings_date > AVWAP_EARNINGS_LOOKBACK_DAYS` → ancla inválida.
3. **Último máximo de 52 semanas**: la fecha del `high` máximo en los últimos 252 días hábiles.
   - Siempre existe si hay ≥ 252 días de data. Si no hay suficiente data → ancla inválida.

Devolver un `SupportLevel` por ancla válida.

### 5.5 HVN aproximado


```python
def hvn_levels(ohlcv_daily: pd.DataFrame) -> list[SupportLevel]:
    """High Volume Nodes aproximados desde OHLCV diario."""
```



Algoritmo:
1. Tomar las últimas `HVN_LOOKBACK_DAYS` filas (252).
2. Determinar rango global: `price_min = min(low)`, `price_max = max(high)`.
3. Generar `HVN_NUM_BUCKETS` (50) buckets uniformes entre `price_min` y `price_max`. Bucket `k` cubre `[price_min + k×Δ, price_min + (k+1)×Δ]` con `Δ = (price_max - price_min) / 50`.
4. Para cada día `d`: distribuir `volume[d]` proporcionalmente entre los buckets que toca el rango `[low[d], high[d]]`. La proporción asignada a un bucket es: `(overlap_con_bucket / (high[d] - low[d])) × volume[d]`. Si `high[d] == low[d]` (caso degenerado, sin rango), asignar el 100% al bucket que contiene `close[d]`.
5. Acumular volumen por bucket → array `volume_by_bucket` de 50 elementos.
6. Identificar buckets en el percentil ≥ `HVN_PERCENTILE_THRESHOLD` (80): valor de corte = `np.percentile(volume_by_bucket, 80)`.
7. Para cada bucket HVN, generar un `SupportLevel` con `price = punto_medio_del_bucket`, `element = "hvn"`, `points = 1`.

**Caso borde**: si hay buckets HVN contiguos (e.g. buckets 12-13-14 todos por encima del threshold), generar **un solo** `SupportLevel` con el precio medio del rango contiguo. Evita inflar el conteo.

### 5.6 Gap alcista no cerrado


```python
def gap_levels(ohlcv_daily: pd.DataFrame) -> list[SupportLevel]:
    """Gaps alcistas no cerrados en últimos GAP_LOOKBACK_DAYS."""
```



Algoritmo:
1. Tomar las últimas `GAP_LOOKBACK_DAYS` filas (252).
2. Para cada día `d` en el rango (`d >= 1`):
   - `gap_up = low[d] > high[d-1]`
   - Si `gap_up`: el gap va de `high[d-1]` (límite inferior) a `low[d]` (límite superior).
3. Para cada gap detectado, verificar si fue cerrado: `gap_cerrado = any(low[k] <= high[d-1] for k in range(d+1, len(ohlcv)))`. Si el precio nunca volvió a tocar `high[d-1]` en barras posteriores, el gap está **no cerrado**.
4. Para cada gap no cerrado, generar un `SupportLevel` con `price = (high[d-1] + low[d]) / 2` (punto medio del gap), `element = "gap_unfilled"`, `points = 1`.

### 5.7 Divergencia alcista RSI/MACD


```python
def divergence_levels(
    ohlcv_daily: pd.DataFrame,
    pivots: list[Pivot],
    rsi_series: pd.Series,
    macd_hist_series: pd.Series,
    close_today: float,
) -> list[SupportLevel]:
    """Detecta divergencia alcista en los últimos DIVERGENCE_LOOKBACK_DAYS."""
```



Algoritmo:
1. Filtrar pivots bajos en últimos `DIVERGENCE_LOOKBACK_DAYS` (60) días.
2. Si hay menos de 2 pivots bajos en la ventana → no hay divergencia detectable. Return `[]`.
3. Tomar los **dos pivots más recientes**: `p1` (más viejo) y `p2` (más reciente).
4. Condición de divergencia alcista:
   - `p2.price < p1.price` (precio hace nuevo mínimo)
   - Y al menos uno de:
     - `rsi_series.loc[p2.date] > rsi_series.loc[p1.date]` (RSI más alto en el nuevo mínimo)
     - `macd_hist_series.loc[p2.date] > macd_hist_series.loc[p1.date]` (histograma MACD más alto)
5. Si se cumple, generar **un solo** `SupportLevel`:
   - `price = p2.price` (la divergencia "ancla" en el último mínimo)
   - `element = "divergence"`, `points = 1`
   - `metadata = {"oscillator": "rsi" | "macd" | "both", "p1_date": ..., "p2_date": ...}`

**Caso borde**: si las fechas de los pivots no coinciden exactamente con índices de `rsi_series` (puede pasar en weekly vs daily), usar `.asof()` de pandas. Si el lookup falla → no hay divergencia, return `[]`.

## 6. Agrupamiento de elementos en zonas

Módulo `src/puts_screener/zone_clustering.py`.

### 6.1 Algoritmo de clustering


```python
@dataclass(frozen=True)
class SupportZone:
    center_price: float                       # mediana de los precios de los elementos
    lower_bound: float                        # center - 0.5×ATR14
    upper_bound: float                        # center + 0.5×ATR14
    score: int                                # suma de points (con dedup por categoría)
    elements: list[SupportLevel]              # elementos que componen la zona
    has_dynamic_confirmer: bool               # True si tiene avwap, hvn o divergence
    distance_pct: float                       # (spot - center_price) / spot
```



Algoritmo:
1. Recibir lista de todos los `SupportLevel` calculados (los 7 elementos juntos).
2. Filtrar: solo elementos con `price < spot × 1.02` (margen del 2% por si la zona engloba el spot por arriba; el filtro final de proximidad refina después). Esto evita procesar elementos muy lejos por arriba del spot.
3. Ordenar por `price` ascendente.
4. Recorrer la lista: si el siguiente elemento está a ≤ `CLUSTERING_TOLERANCE_ATR × atr14_today` del anterior, mismo cluster; si no, nueva zona.
5. Para cada cluster:
   - `center_price = median(elements.price)`
   - `lower_bound = center_price - ZONE_WIDTH_ATR_MULTIPLIER × atr14_today`
   - `upper_bound = center_price + ZONE_WIDTH_ATR_MULTIPLIER × atr14_today`
   - `score = compute_zone_score(elements)` — ver §6.3
   - `has_dynamic_confirmer = any(e.element in DYNAMIC_CONFIRMERS for e in elements)`
   - `distance_pct = (spot - center_price) / spot`

### 6.2 Categorías para deduplicación

Un elemento puede aparecer múltiples veces (e.g. dos HVN cercanos, fib_618 y fib_786 que caen al mismo precio). Para el score, **un elemento de la misma categoría suma como máximo una vez por zona**, salvo SMA200 que tiene su lógica propia.

Categorías:
- `"sma_200"` (incluye `sma_200w` y `sma_200d`): suma 2 pts si **cualquiera** de los dos cae en la zona. No suma 4 si caen ambos. **Justificación**: el SOP dice "Asignar 2 puntos si alguno de los dos coincide con la zona".
- `"fibonacci"` (incluye `fib_618` y `fib_786`): suma 1 pt si cualquiera cae. No 2 si caen ambos.
- `"avwap"` (incluye los 3 anclajes): suma 1 pt si cualquiera cae.
- Cada uno de los otros (`polarity`, `hvn`, `gap_unfilled`, `divergence`): suma 1 pt si está presente.

### 6.3 Función de score


```python
def compute_zone_score(elements: list[SupportLevel]) -> int:
    categories_present = set()
    for e in elements:
        if e.element in ("sma_200w", "sma_200d"):
            categories_present.add("sma_200")
        elif e.element in ("fib_618", "fib_786"):
            categories_present.add("fibonacci")
        elif e.element.startswith("avwap_"):
            categories_present.add("avwap")
        else:
            categories_present.add(e.element)
    
    score = 0
    for cat in categories_present:
        score += SCORE_SMA200_POINTS if cat == "sma_200" else SCORE_OTHER_ELEMENT_POINTS
    return score
```



### 6.4 API


```python
def cluster_into_zones(
    levels: list[SupportLevel],
    atr14_today: float,
    spot: float,
) -> list[SupportZone]:
    """Agrupa levels en zonas y calcula score de cada una.
    Devuelve zonas ordenadas por score desc, luego por distance_pct asc (cercanas primero).
    """
```



## 7. Validación y filtrado de zonas

Módulo `src/puts_screener/support_scoring.py`.

### 7.1 Reglas

Una zona es **válida** si:
1. `score >= SCORE_MIN_VALID` (3 puntos mínimo).
2. `has_dynamic_confirmer == True` (al menos un confirmador entre AVWAP/HVN/divergencia).
3. `0 <= distance_pct <= MAX_DISTANCE_TO_SUPPORT_PCT` (0 a 10% por debajo del spot).

Si una zona pasa las 3, queda en `valid_zones`. Si falla alguna, queda en `rejected_zones` con motivo.

### 7.2 Selección de zona "mejor"

La mejor zona es la primera de `valid_zones` ordenadas por:
1. `score` descendente.
2. `distance_pct` ascendente (cuanto más cerca del spot, mejor — más probabilidad de testeo).
3. (Desempate final, raro) Mayor número de categorías distintas representadas.

### 7.3 API


```python
@dataclass(frozen=True)
class SupportAnalysis:
    valid_zones: list[SupportZone]            # todas las que pasaron las 3 reglas
    rejected_zones: list[tuple[SupportZone, str]]  # zona + motivo de rechazo
    best_zone: SupportZone | None             # primera de valid_zones según orden de §7.2

def analyze_supports(
    candidate: ScreenedCandidate,
    data_service: DataService,
) -> SupportAnalysis:
    """Pipeline completo de análisis de soportes para un candidato.
    
    1. Calcula pivots desde candidate.ohlcv_daily
    2. Calcula los 7 elementos (§5)
    3. Clusterea en zonas (§6)
    4. Valida y rankea (§7.1, §7.2)
    """
```



## 8. Modelo `SupportedCandidate`

En `src/puts_screener/models_support.py`:


```python
@dataclass
class SupportedCandidate:
    screened: ScreenedCandidate               # candidato del Paso 1 (composición, no herencia)
    analysis: SupportAnalysis                 # resultado completo del Paso 2
    pasa_paso_2: bool                         # True si analysis.best_zone is not None
    fetched_at: datetime
    errors: list[str]                         # errores no fatales del análisis
```



**Composición vs herencia**: `SupportedCandidate` envuelve a `ScreenedCandidate` (no hereda). Mantiene el output del Paso 1 inmutable y accesible (`supported.screened.ticker`, etc.).

## 9. Pipeline orquestador

Módulo `src/puts_screener/support_pipeline.py`.


```python
def run_support_detection(
    screened_candidates: list[ScreenedCandidate],
    data_service: DataService,
    max_workers: int = 8,
    persist: bool = True,
    run_id: str | None = None,
) -> tuple[str | None, list[SupportedCandidate]]:
    """Corre el Paso 2 sobre candidatos que pasaron el Paso 1.
    
    1. Filtra a screened_candidates con pasa_filtros_paso_1=True (los rechazados se ignoran).
    2. Para cada candidato en paralelo (ThreadPoolExecutor):
       a. Computa pivots, ATR, RSI series, MACD series
       b. Calcula elementos (§5)
       c. Cluster + score (§6)
       d. Validación + selección (§7)
    3. Si persist=True, escribe en SQLite (ver §10). El run_id se reutiliza del Paso 1 si se pasa.
    4. Returns (run_id, supported_candidates).
    """
```



**Reutilización de indicadores**: el pipeline ya tiene `candidate.atr_14` calculado del Paso 1. No re-calcular. Para RSI/MACD necesitamos las **series completas** (no solo el valor de hoy), así que sí hay que recalcularlas — son baratas.

**Manejo de errores**: errores aislados por candidato. Si falla la detección para un ticker, `SupportedCandidate` queda con `pasa_paso_2=False` y `errors=[mensaje]`. No rompe el pipeline.

## 10. Persistencia: tabla `support_zones`

Extender `src/puts_screener/persistence.py`.

### 10.1 Esquema


```sql
CREATE TABLE IF NOT EXISTS support_zones (
    run_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    zone_id INTEGER NOT NULL,                 -- 0, 1, 2... orden de rank dentro del ticker
    is_best INTEGER NOT NULL,                 -- 0/1; True si es la zona seleccionada
    center_price REAL NOT NULL,
    lower_bound REAL NOT NULL,
    upper_bound REAL NOT NULL,
    score INTEGER NOT NULL,
    distance_pct REAL NOT NULL,
    has_dynamic_confirmer INTEGER NOT NULL,
    elements_json TEXT NOT NULL,              -- JSON array con elementos completos
    is_valid INTEGER NOT NULL,                -- 0/1; pasó las 3 reglas de §7.1
    rejection_reason TEXT,                    -- NULL si is_valid=1
    PRIMARY KEY (run_id, ticker, zone_id),
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE INDEX idx_support_zones_best ON support_zones(run_id, is_best);
CREATE INDEX idx_support_zones_valid ON support_zones(run_id, is_valid);
```



También agregar columna a `candidates`:


```sql
ALTER TABLE candidates ADD COLUMN pasa_paso_2 INTEGER;  -- NULL si no se corrió Paso 2; 0/1 si sí
```



### 10.2 API


```python
def save_support_analysis(
    run_id: str,
    supported_candidates: list[SupportedCandidate],
) -> None:
    """Persiste todas las zonas (válidas y rechazadas) y actualiza candidates.pasa_paso_2."""

def load_support_zones(run_id: str, ticker: str | None = None) -> list[SupportZone]:
    """Reconstruye zonas desde SQLite. Si ticker es None, devuelve todas del run."""
```



**Política**: persistimos **todas** las zonas (válidas e inválidas) — espeja la política del Paso 1 de persistir todo para análisis posterior.

## 11. Tests

### 11.1 Unitarios

**`test_pivots.py`** — fixtures sintéticas:
- Serie con un pivot bajo claro a la mitad → detectado.
- Serie monótona ascendente → 0 pivots bajos confirmados.
- Pivot bajo con profundidad < `PIVOT_MIN_DEPTH_ATR` → no detectado.
- Caso borde: pivot en las últimas N barras → no detectado (correctamente).

**`test_support_elements.py`** — una fixture por elemento:
- `sma_200_levels`: data con SMA200W y EMA200D conocidas, verificar valores.
- `polarity_levels`: pivots altos pasados que el precio superó → niveles devueltos.
- `fib_levels`: impulso conocido, verificar 61.8 y 78.6 calculados a mano.
- `fib_levels` con caso "subida en curso" (sin pivot alto posterior) → usar spot.
- `avwap_levels`: data sintética con typical_price y volume controlados, verificar AVWAP calculado a mano.
- `hvn_levels`: data con un cluster claro de volumen en un rango → bucket detectado como HVN.
- `gap_levels`: data con un gap up + sin cierre → detectado; gap up + cierre posterior → no detectado.
- `divergence_levels`: pivots con precio bajando y RSI subiendo → divergencia detectada.

**`test_zone_clustering.py`**:
- Elementos lejos entre sí → zonas separadas.
- Elementos cerca (≤ 0.5×ATR) → mismo cluster.
- Caso dedup: SMA200W + SMA200D en mismo cluster → suma 2 pts, no 4.
- Caso dedup: fib_618 + fib_786 en mismo cluster → suma 1 pt, no 2.

**`test_support_scoring.py`**:
- Zona score 3 + confirmador dinámico → válida.
- Zona score 5 sin confirmador dinámico → rechazada con motivo "sin confirmador dinámico".
- Zona score 3 fuera del 10% → rechazada con motivo "fuera de rango de proximidad".
- Selección de mejor zona: misma score, ranking por distance_pct.

**`test_persistence_supports.py`**:
- Round-trip de `SupportedCandidate` → SQLite → reconstrucción.
- Migración de schema: tabla `support_zones` se crea correctamente.

### 11.2 Integración

**`test_support_pipeline.py`**: con `DataService` mockeado y 3 candidatos de fixture:
- Uno con zona válida score ≥ 3 + confirmador → pasa.
- Uno con zonas pero todas sin confirmador dinámico → no pasa.
- Uno sin pivots significativos en la ventana → no pasa, sin error.

### 11.3 Smoke test

`src/puts_screener/smoke_test_supports.py`:
- Toma 10 tickers que pasaron el Paso 1 en el último run (o hardcoded como fallback).
- Corre `run_support_detection`.
- Imprime tabla: ticker, n_zonas_válidas, mejor_score, distancia_pct, elementos.

## 12. Criterios de aceptación

- [ ] Pivots detectados sobre fixture conocida con resultados verificables a mano.
- [ ] Cada uno de los 7 elementos tiene tests con cálculo manual de referencia.
- [ ] Clustering deduplica correctamente categorías (test específico).
- [ ] Confirmador dinámico es obligatorio (test que verifica rechazo sin él).
- [ ] Distance filter: zonas por encima del spot o a > 10% se rechazan.
- [ ] Pipeline corre en paralelo y errores aislados por ticker no rompen la corrida.
- [ ] SQLite round-trip funciona con la nueva tabla.
- [ ] Smoke test corre limpio en < 1 min para 10 tickers.
- [ ] `pytest -v` pasa con 0 errores.
- [ ] `ruff check src/ tests/` limpio.

## 13. Archivos a crear/modificar


```
src/puts_screener/
├── pivots.py                          # nuevo
├── support_elements.py                # nuevo
├── zone_clustering.py                 # nuevo
├── support_scoring.py                 # nuevo
├── models_support.py                  # nuevo
├── support_pipeline.py                # nuevo
├── config_supports.py                 # nuevo
├── persistence.py                     # modificar: agregar tabla support_zones + alter candidates
├── smoke_test_supports.py             # nuevo
└── run.py                             # modificar: encadenar Paso 1 → Paso 2 cuando flag activo

tests/supports/
├── __init__.py
├── test_pivots.py
├── test_support_elements.py
├── test_zone_clustering.py
├── test_support_scoring.py
├── test_support_pipeline.py
├── test_persistence_supports.py
└── fixtures/
    ├── ohlcv_with_clean_pivot.parquet
    ├── ohlcv_with_gap.parquet
    ├── ohlcv_with_divergence.parquet
    └── ohlcv_with_hvn_cluster.parquet
```


## 14. Decisiones registradas

- **`SupportedCandidate` por composición, no herencia**: envuelve a `ScreenedCandidate` para mantener el output del Paso 1 inmutable y accesible. Espeja la separación por capas que ya tenemos en specs 01 (data) → 02 (screening) → 03 (soportes).
- **Solo procesar los que pasaron Paso 1**: los rechazados se persistieron para análisis del propio screening, no para procesarlos en pasos posteriores. Optimización + claridad conceptual.
- **Ventana de 12 meses (252 días) para "último"**: aplicada a `LAST_SWING_LOOKBACK_DAYS`, `LAST_PIVOT_HIGH_LOOKBACK_DAYS`, `AVWAP_EARNINGS_LOOKBACK_DAYS`, `HVN_LOOKBACK_DAYS`, `GAP_LOOKBACK_DAYS`. Niveles más viejos no aplican a la situación técnica actual. Reversible vía constantes.
- **Pivots con `N=5` + filtro de profundidad ATR**: balance ruido/significancia. Para 2 años de daily da del orden de 10-20 pivots, suficiente para fibs y polaridad.
- **AVWAP con 3 anclas (pivot bajo, earnings, 52w high)**: se agregó el 52w high al SOP original (que solo menciona pivot bajo y earnings). El precio promedio desde el techo es referencia institucional fuerte. Si ninguna ancla es válida, el elemento `avwap` no se suma — la zona puede igual ser válida si tiene HVN o divergencia.
- **HVN aproximado sin intradía**: implementación basada en distribuir el volumen diario proporcionalmente entre buckets que el rango High-Low toca. Aproximación gruesa pero defendible; mejor que omitir el elemento. Cuando se integre data de minutos (Fase 4), reemplazar por Volume Profile real.
- **Divergencia: RSI o MACD, no acumulable**: el SOP dice "RSI o MACD". Si cualquiera muestra divergencia, el elemento `divergence` suma 1 pt. Tener ambos no suma 2. El metadata registra cuál (o "both") para diagnóstico.
- **Polaridad sin ponderación por frescura**: una resistencia rota hace 11 meses y otra hace 2 meses suman lo mismo (1 pt cada una si caen en zona). Ponderación temporal es complicación que el SOP no pide.
- **Consolidación omitida como elemento independiente**: el SOP la menciona junto con gaps, pero la consolidación está capturada implícitamente por HVN (acumulación = mucho volumen en rango chico). Evita doble-conteo conceptual. Anotado en backlog si se necesita explícito.
- **Clustering por proximidad ≤ 0.5×ATR**: define la zona del SOP. Dos elementos a menos de medio ATR se consideran misma confluencia. La mediana se elige sobre el promedio para robustez ante outliers.
- **Categorías para dedup en scoring**: SMA200, fibonacci y avwap deduplican (un elemento de la categoría suma una vez por zona, sin importar si hay sub-variantes). El resto suma directo. Refleja la intención del SOP ("alguno de los dos" para SMA200) y evita inflar score artificialmente.
- **Confirmador dinámico OBLIGATORIO**: zona sin AVWAP, HVN o divergencia se descarta, sin importar el score. Es el criterio de calidad del SOP.
- **Persistir todas las zonas (válidas y rechazadas)**: misma política del Paso 1 con candidatos. Permite backtesting del proceso de selección.
- **Caso borde "subida en curso" en fibs**: si no hay pivot alto posterior al último pivot bajo (estamos en plena suba), usar `close_today` como cierre del impulso. Los fibs se proyectan sobre lo ya subido.
- **Pivots no confirmados de las últimas N barras**: se ignoran. Correcto y esperado: un pivot requiere N barras a derecha para confirmar.
