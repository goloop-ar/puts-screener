# Spec 11 — Confirmación por velas + rediseño estructural de strikes

> Estado: propuesta. Fecha: 2026-09-07.
>
> **Nota de contrato**: `specs/10_*.md` no existe en el filesystem pese a que ROADMAP §1 marca
> "Spec 10 ✅ Cerrada". El código de spec 10 (`detectors.py`, `classification_v2.py`,
> `config_detectors.py`) existe y está integrado. Esta spec declara su contrato con esos módulos
> reconstruido desde el código real, no desde un doc. Ver §11, decisión D11.1.

---

## 1. Objetivo

Dos capacidades acopladas, medidas sobre el mismo dataset retroactivo:

1. **Confirmación por velas**: detectar patrones de reversal (y de perforación) en las últimas
   ruedas, condicionados a que ocurran *dentro de una zona de soporte ya validada por el Paso 2*.
   Hoy el pipeline sabe si el precio llegó a una zona buena, pero no sabe si la zona lo frenó.

2. **Rediseño estructural de strikes**: reemplazar los tres strikes heurísticos actuales
   (`zone_bound ± ATR×1.0` + redondeo a grilla) por strikes anclados a los elementos de soporte
   reales que ya se persisten en `support_zones.elements_json` (SMA200D/W, EMA200D, SMA50D,
   polaridad, AVWAP, HVN).

Las dos van juntas porque la hipótesis operativa que las une es una sola: **si la zona está
confirmada por una vela de reversal, se puede subir el strike (acercarlo al spot) sin degradar la
probabilidad de que aguante**. Eso es medible y esta spec lo mide antes de integrarlo.

### Regla metodológica de esta spec

El proyecto ya produjo tres detectores con 22 tests sintéticos verdes y **cero detecciones en
producción en 4.5 meses** (`capitulation_reclaim`, `range_floor`, y `post_earnings_dip` como
primary hasta agosto). La causa fue calibrar contra fixtures en vez de contra data real.

Esta spec invierte el orden: **detectores → medición empírica retroactiva → integración**. Ningún
detector se integra al pipeline productivo antes de tener su tasa de detección y su outcome
medidos sobre las 1145 best_zones históricas. Los criterios de outcome se **pre-registran en §3
antes de correr el backtest** para no elegir el criterio que produce el número que gusta.

---

## 2. Scope

### En scope

- Módulo `candle_patterns.py`: helpers de geometría de vela + 3 detectores, funciones puras.
- Módulo `strike_placement.py`: 3 variantes candidatas de colocación de strikes ancladas a
  estructura.
- Harness de backtest retroactivo sobre `screening_history.db` (85 runs, 1145 best_zones con
  strikes completos, 131 tickers, 2026-05-28 → 2026-09-07).
- Integración al pipeline de lo que el backtest valide: campo `candle_signals` en el modelo,
  persistencia, render en HTML/CSV, y reemplazo de `compute_heuristic_strikes` por la variante
  ganadora.
- Constantes nuevas en `config_candles.py` y extensión de `config_reports.py`.

### Fuera de scope

- **`range_floor`**: dispara 0 veces en 36 casos de `regime=lateral` (su única precondición de
  régimen). Es un bug propio con 30 candidatos perdidos en agosto. Requiere diagnóstico
  independiente, no un renglón acá. Ver ROADMAP §2.
- **32 zonas con `pasa_paso_2=1` y `regime IS NULL`**: bug de clasificación en 4 runs, 8 tickers
  cada uno. Issue separado. Se **excluyen** del dataset de backtest por contaminación.
- **Apertura de los gates del Paso 1** (mover `filter_momentum` y el techo de HV de gate duro a
  dimensión anotada). Depende de que la confirmación por velas esté validada como contrapeso.
  Candidata a spec 12.
- **99 constituyentes delisted de STOXX 600**: deuda de rotación de índice, no toca esta spec.
- Selección de delta/prima real (requiere cadena de opciones — Fase 4).
- Patrones de continuación (bull flag, rising three methods): son `pullback_in_uptrend`, ya
  existe. Ver D11.4.
- Patrones de indecisión (doji, spinning top) aislados: no accionables. Ver D11.4.

---

## 3. Decisiones de parametrización

### 3.1 Geometría de velas

| Constante | Valor | Justificación |
| --- | --- | --- |
| `WICK_REJECTION_MIN_RATIO` | `1.5` | Mecha inferior ≥1.5× cuerpo. El material de referencia sugiere 2.0, calibrado para reversales dramáticos post-caída. Nuestra población real es 64% `pullback_in_uptrend` sobre zona validada, donde el rechazo es más suave. 2.0 nos daría el cuarto detector mudo. |
| `WICK_REJECTION_MAX_UPPER_RATIO` | `1.0` | Mecha superior ≤ cuerpo. Sin este filtro, un spinning top califica como hammer. |
| `WICK_REJECTION_MIN_BODY_ATR` | `0.05` | Cuerpo mínimo en unidades de ATR14. Evita que un doji de cuerpo ~0 dé ratio infinito y califique siempre. |
| `BODY_RECLAIM_PIERCING_PCT` | `0.50` | Cierre por encima del 50% del cuerpo rojo previo. Umbral clásico del piercing pattern. |
| `BODY_RECLAIM_PREV_MIN_BODY_ATR` | `0.15` | La vela roja previa debe tener cuerpo real. Reclamar un doji no es reclamar nada. |
| `MORNING_STAR_MAX_MIDDLE_BODY_ATR` | `0.30` | Cuerpo de la vela del medio en el patrón de 3 velas. Sin exigir gaps (ver D11.5). |
| `BEARISH_MOMENTUM_BODY_MULTIPLIER` | `2.0` | Cuerpo ≥2× el promedio de los 3 cuerpos previos. Único umbral del material de referencia que es cuantificable sin ambigüedad. |
| `BEARISH_ENGULFING_MIN_BODY_ATR` | `0.15` | Cuerpo mínimo del engulfing bajista. |

### 3.2 Gate de contexto (aplica a los 3 detectores)

| Constante | Valor | Justificación |
| --- | --- | --- |
| `CANDLE_LOOKBACK_BARS` | `3` | Ventana de búsqueda hacia atrás desde la última barra. El cron corre diario; 3 ruedas cubre el fin de semana largo sin volver la señal rancia. |
| `CANDLE_ZONE_PROXIMITY_ATR` | `0.5` | El mínimo de la vela debe caer dentro de `[lower_bound, upper_bound]` o a ≤0.5×ATR14 por fuera. **Sin este gate el detector es ruido puro** — un hammer a 8% de la zona no dice nada sobre la zona. |

### 3.3 Variantes candidatas de colocación de strikes

Las tres se computan sobre los mismos anclajes: los `SupportLevel` de `elements_json` con
`ELEMENT_WEIGHTS[element] >= 2.5` (los "heavy": `sma_200d`, `sma_200w`, `polarity`, `ema_200d`,
`sma_50d`, `avwap_pivot_low`, `avwap_earnings`).

| Variante | conservative | natural | aggressive |
| --- | --- | --- | --- |
| **A — Anclaje heavy** | debajo del heavy más bajo, −0.25×ATR | debajo de `lower_bound`, −0.25×ATR | debajo del heavy más alto dentro de la zona |
| **B — Anclaje heavy con colchón ATR** | heavy más bajo −0.5×ATR | heavy más bajo | heavy más alto −0.1×ATR |
| **C — Híbrido zona/heavy** | `min(lower_bound, heavy más bajo)` −0.5×ATR | `lower_bound` −0.1×ATR | `center_price` de la zona |

Los tres niveles se redondean **hacia abajo** a la grilla de la divisa (`STRIKE_GRID_*` en
`config_reports.py`, sin cambios). Redondear hacia abajo siempre es conservador: nunca acerca el
strike al spot por efecto del redondeo.

**Fallback** cuando la zona no tiene elementos heavy (no debería ocurrir — el gate estructural
exige `MIN_HEAVY_ELEMENTS=2` — pero las zonas de mayo pre-gate pueden tenerlo): caer a la lógica
actual `zone_bound ± ATR×1.0`, marcando `anchor_kind="fallback_atr"`.

### 3.4 Criterios de outcome — PRE-REGISTRADOS

Fijados antes de correr el backtest. **No se modifican después de ver resultados.** Cualquier
cambio posterior se registra como decisión fechada con su justificación.

| Concepto | Definición operativa |
| --- | --- |
| Ventana primaria | **45 días hábiles** desde `candidates.fetched_at`. Es el techo de la ventana del SOP (30–45 DTE). |
| Ventanas secundarias | 30 y 60 días hábiles. Se **reportan** pero no deciden la calibración. |
| "El strike aguantó" | El **cierre** diario nunca quedó por debajo del strike en toda la ventana. Cierre, no mínimo intradía: una mecha que perfora y recupera no asigna. |
| "El strike se perforó" | Al menos un cierre por debajo del strike en la ventana. |
| Zona con confirmación | `wick_rejection` o `body_reclaim` detectado en las 3 ruedas previas a `fetched_at`, con el gate de proximidad cumplido. |
| Zona sin confirmación | Ninguno de los dos, y tampoco `bearish_breakdown`. |
| Zona con perforación | `bearish_breakdown` detectado. Se reporta como grupo aparte, no se mezcla con "sin confirmación". |

### 3.5 Targets de calibración

| Strike | Tasa de aguante mínima a 45d | Justificación |
| --- | --- | --- |
| `aggressive` | **≥70%** | El SOP opera en delta 0.20–0.30 ≈ 70–80% de probabilidad de expirar OTM. Un strike con 50% de aguante es delta ~0.50, at-the-money: fuera de la ventana del SOP por definición, no "agresivo dentro de ella". |
| `natural` | **≥80%** | Centro de la ventana del SOP. |
| `conservative` | **≥88%** | Delta ~0.12–0.15, la punta defensiva. |

La variante A/B/C ganadora es la que **cumple los tres targets simultáneamente** con el
`aggressive` más alto (mayor prima para el mismo aguante). Si ninguna los cumple, se corre el
buffer de ATR hacia abajo en incrementos de 0.1 hasta que la variante más cercana los alcance, y
eso se registra como calibración.

---

## 4. Modelos / dataclasses

```python
# src/puts_screener/models_candles.py

from dataclasses import dataclass
from typing import Literal

CandleKind = Literal[
    "wick_rejection",
    "body_reclaim_piercing",
    "body_reclaim_engulfing",
    "body_reclaim_morning_star",
    "bearish_engulfing",
    "bearish_dark_cloud",
    "bearish_momentum",
]

CandleDirection = Literal["bullish", "bearish"]


@dataclass(frozen=True)
class CandleSignal:
    """Patrón de vela detectado dentro (o al borde) de una zona de soporte validada."""

    kind: CandleKind
    direction: CandleDirection
    bar_date: pd.Timestamp
    bars_ago: int                      # 0 = última barra
    body_atr: float                    # tamaño del cuerpo en unidades de ATR14
    lower_wick_ratio: float            # mecha inferior / cuerpo
    upper_wick_ratio: float            # mecha superior / cuerpo
    in_zone: bool                      # True si el low cayó dentro de [lower, upper]
    distance_to_zone_atr: float        # 0.0 si in_zone; si no, distancia en ATR


@dataclass(frozen=True)
class CandleAnalysis:
    """Resultado de evaluar los 3 detectores sobre una zona en la ventana de lookback."""

    signals: tuple[CandleSignal, ...]
    has_bullish_confirmation: bool     # ≥1 wick_rejection o body_reclaim_*
    has_bearish_breakdown: bool        # ≥1 bearish_*
    strongest_bullish: CandleSignal | None
```

```python
# src/puts_screener/models_reports.py  (extensión de HeuristicStrikes existente)

@dataclass(frozen=True)
class StructuralStrikes:
    """Tres strikes anclados a elementos de soporte reales (reemplaza HeuristicStrikes)."""

    aggressive: float
    natural: float
    conservative: float
    grid_unit: float
    anchor_kind: Literal["heavy_element", "zone_bound", "fallback_atr"]
    aggressive_anchor: str | None      # etiqueta del elemento ancla, ej. "sma_200w"
    conservative_anchor: str | None
    variant: Literal["A", "B", "C"]
```

`ScreenedCandidate` gana un campo:

```python
candle_signals: tuple[str, ...] = ()   # kinds detectados, para persistencia/reporte
```

---

## 5. APIs públicas

```python
# src/puts_screener/candle_patterns.py

def detect_wick_rejection(
    ohlcv: pd.DataFrame,
    atr: pd.Series,
    zone: SupportZone,
    *,
    lookback_bars: int = CANDLE_LOOKBACK_BARS,
    today: pd.Timestamp | None = None,
) -> list[CandleSignal]:
    """Detecta velas de rechazo por mecha inferior (hammer / dragonfly doji) en la zona."""


def detect_body_reclaim(
    ohlcv: pd.DataFrame,
    atr: pd.Series,
    zone: SupportZone,
    *,
    lookback_bars: int = CANDLE_LOOKBACK_BARS,
    today: pd.Timestamp | None = None,
) -> list[CandleSignal]:
    """Detecta reclaim del cuerpo previo: piercing, engulfing alcista o morning star."""


def detect_bearish_breakdown(
    ohlcv: pd.DataFrame,
    atr: pd.Series,
    zone: SupportZone,
    *,
    lookback_bars: int = CANDLE_LOOKBACK_BARS,
    today: pd.Timestamp | None = None,
) -> list[CandleSignal]:
    """Detecta perforación con convicción: engulfing bajista, dark cloud o vela de momentum."""


def analyze_candles(
    ohlcv: pd.DataFrame,
    atr: pd.Series,
    zone: SupportZone,
    *,
    today: pd.Timestamp | None = None,
) -> CandleAnalysis:
    """Corre los 3 detectores y consolida el resultado. Punto de entrada del módulo."""
```

```python
# src/puts_screener/strike_placement.py

def compute_structural_strikes(
    zone: SupportZone,
    spot: float,
    atr_14: float,
    currency: str,
    *,
    variant: Literal["A", "B", "C"] = "A",
) -> StructuralStrikes:
    """Calcula los 3 strikes anclados a los elementos heavy de la zona."""


def extract_heavy_anchors(zone: SupportZone) -> list[SupportLevel]:
    """Devuelve los SupportLevel de la zona con ELEMENT_WEIGHTS >= 2.5, ordenados por precio."""
```

**Firma preservada**: `compute_heuristic_strikes` no se borra en la Tanda 1. Queda como fallback y
para reproducir el output histórico. Se retira recién en la Tanda 3, si el backtest valida el
reemplazo.

---

## 6. Algoritmos

### 6.1 Geometría base (helper compartido)

Para una barra con `(open, high, low, close)` y `atr` de esa barra:

```
body        = abs(close - open)
body_atr    = body / atr
upper_wick  = high - max(open, close)
lower_wick  = min(open, close) - low
range_bar   = high - low
```

Ratios de mecha se computan contra `max(body, atr * WICK_REJECTION_MIN_BODY_ATR)` para evitar
división por ~0 en velas doji.

### 6.2 `detect_wick_rejection`

Para cada barra `i` en las últimas `lookback_bars`:

1. `body_atr >= WICK_REJECTION_MIN_BODY_ATR`, si no → skip.
2. `lower_wick / body >= WICK_REJECTION_MIN_RATIO`, si no → skip.
3. `upper_wick / body <= WICK_REJECTION_MAX_UPPER_RATIO`, si no → skip.
4. **Gate de contexto**: `low` de la barra dentro de `[zone.lower_bound, zone.upper_bound]`, o
   `distancia_al_borde <= CANDLE_ZONE_PROXIMITY_ATR * atr`. Si no → skip.
5. Emitir `CandleSignal(kind="wick_rejection", direction="bullish", ...)`.

El color del cuerpo (verde/rojo) **no** se chequea: un hammer rojo sigue siendo hammer. El
contexto lo da la zona, no el color.

### 6.3 `detect_body_reclaim`

Para cada barra `i`:

1. La barra previa `i-1` debe ser roja con `body_atr >= BODY_RECLAIM_PREV_MIN_BODY_ATR`.
2. La barra `i` debe ser verde.
3. Clasificar por umbral, en orden de fuerza:
   - `close_i > open_{i-1}` → `body_reclaim_engulfing`
   - `close_i > open_{i-1} - BODY_RECLAIM_PIERCING_PCT * body_{i-1}` → `body_reclaim_piercing`
   - si no → skip
4. **Variante morning star** (3 velas): `i-2` roja con cuerpo real, `i-1` con
   `body_atr <= MORNING_STAR_MAX_MIDDLE_BODY_ATR`, `i` verde cerrando por encima del 50% del
   cuerpo de `i-2` → `body_reclaim_morning_star`.
5. Gate de contexto: se evalúa sobre el `low` **mínimo del patrón** (2 o 3 barras), no solo de la
   última.
6. Emitir señal. Si una misma barra califica como engulfing y morning star, se emite la de mayor
   fuerza (engulfing > morning_star > piercing) y se descarta la otra.

### 6.4 `detect_bearish_breakdown`

Para cada barra `i`, cualquiera de:

- **Engulfing bajista**: `i-1` verde con cuerpo real, `i` roja, `close_i < open_{i-1}`.
- **Dark cloud**: `i-1` verde, `i` roja, `close_i < open_{i-1} + 0.5 * body_{i-1}`.
- **Vela de momentum bajista**: `i` roja con
  `body_i >= BEARISH_MOMENTUM_BODY_MULTIPLIER * mean(body_{i-1}, body_{i-2}, body_{i-3})`.

Gate de contexto **distinto**: la vela debe cerrar **dentro o por debajo** de la zona
(`close <= zone.upper_bound`). Una vela bajista por encima de la zona no la está perforando.

### 6.5 `compute_structural_strikes`

1. `anchors = extract_heavy_anchors(zone)` — ordenados ascendente por precio.
2. Si `anchors` está vacío → fallback a `compute_heuristic_strikes`, `anchor_kind="fallback_atr"`.
3. Aplicar la fórmula de la variante (§3.3) para los 3 niveles.
4. Redondear cada nivel **hacia abajo** a la grilla de la divisa.
5. **Invariante**: `conservative < natural < aggressive < spot`. Si el redondeo colapsa dos
   niveles en el mismo valor de grilla, bajar el más conservador un `grid_unit`. Si eso viola
   `conservative > 0`, marcar la zona como sin strikes computables y loguear.
6. Emitir `StructuralStrikes` con las etiquetas de los elementos ancla.

### 6.6 Harness de backtest

Sobre `scratch/backtest_dataset.csv` (1145 filas), filtrando `regime IS NOT NULL` (excluye las 32
contaminadas → 1113 filas):

Por cada fila:
1. Cargar OHLCV del ticker desde cache.
2. Truncar a `fetched_at` (**sin lookahead**: la detección solo ve barras ≤ fecha de detección).
3. Reconstruir el `SupportZone` desde las columnas persistidas + `elements_json`.
4. Correr `analyze_candles` → `has_bullish_confirmation` / `has_bearish_breakdown`.
5. Computar las 3 variantes de strikes (A/B/C) sobre esa zona.
6. Tomar la ventana posterior (45 días hábiles) y evaluar aguante de cada strike de cada variante,
   más los strikes históricos originales como línea de base.
7. Emitir fila de resultados.

**Salidas del harness:**
- Tasa de aguante por strike × variante × ventana (30/45/60).
- Tasa de aguante **cruzada por confirmación**: `aggressive` con confirmación vs `conservative`
  sin confirmación. **Esta es la pregunta principal de la spec.**
- Tasa de detección de cada `CandleKind` (para descartar detectores mudos).
- Poder predictivo de `bearish_breakdown` sobre perforación.

---

## 7. Persistencia

Columnas nuevas en `candidates`, vía el patrón idempotente existente
(`_CANDIDATE_MIGRATION_COLUMNS` + `_migrate_columns`, invocado en `_connect()`):

```python
_CANDIDATE_MIGRATION_COLUMNS: dict[str, str] = {
    ...,
    # spec 11 — confirmación por velas
    "candle_signals_json": "TEXT DEFAULT '[]'",
    "candle_bullish_confirmation": "INTEGER DEFAULT 0",
    "candle_bearish_breakdown": "INTEGER DEFAULT 0",
    # spec 11 — strikes estructurales
    "strike_variant": "TEXT",
    "strike_anchor_kind": "TEXT",
    "strike_aggressive_anchor": "TEXT",
    "strike_conservative_anchor": "TEXT",
}
```

Las 4 columnas de strikes existentes (`strike_aggressive`, `strike_natural`,
`strike_conservative`, `strike_grid_unit`) **se reutilizan**: pasan a contener los valores
estructurales. `strike_variant` distingue los runs viejos (`NULL` = heurístico legacy) de los
nuevos.

Persistencia vía un `UPDATE ... WHERE run_id = ? AND ticker = ?` por candidato, replicando el
patrón de `save_classification`. No se toca `_SCHEMA_SQL`.

---

## 8. Tests

### Unitarios — `tests/test_candle_patterns.py`

- Geometría: body/wick/ratios sobre barras construidas a mano, incluyendo doji (cuerpo ~0) y
  barra sin mechas.
- `wick_rejection`: hammer canónico; hammer rojo (debe detectar); ratio 1.4 (debe rechazar);
  mecha superior larga (debe rechazar); doji de cuerpo 0 (no debe dar ratio infinito).
- `body_reclaim`: engulfing; piercing al 51% (detecta) y al 49% (rechaza); morning star de 3
  velas; previa roja de cuerpo despreciable (rechaza).
- `bearish_breakdown`: engulfing bajista; dark cloud; vela de momentum 2.1× (detecta) y 1.9×
  (rechaza); vela bajista por encima de la zona (rechaza por gate).
- **Gate de proximidad**: mismo patrón dentro de zona (detecta) y a 0.6 ATR (rechaza). Test
  explícito, es el gate que evita el ruido.
- Bordes: OHLCV vacío, menos barras que `lookback_bars`, ATR con NaN.

### Unitarios — `tests/test_strike_placement.py`

- `extract_heavy_anchors` filtra por peso ≥2.5 y ordena por precio.
- Cada variante A/B/C produce el orden `conservative < natural < aggressive < spot`.
- Redondeo a grilla siempre hacia abajo, para las 4 grillas de divisa (USD/EUR/GBP/GBP_pence).
- Colapso de grilla: dos niveles caen en el mismo valor → se separa un `grid_unit`.
- Zona sin elementos heavy → fallback y `anchor_kind="fallback_atr"`.

### Integración — `tests/test_candles_integration.py`

- `analyze_candles` sobre un `SupportZone` reconstruido, verificando consolidación de señales.
- Persistencia idempotente: dos corridas sobre el mismo run no duplican ni pisan.
- Round-trip de `candle_signals_json`.

### Smoke manual

```bash
python -m puts_screener.run --universe sp500 --limit 50 --no-persist
python scratch/backtest_candles.py --window 45 --variant A,B,C
```

---

## 9. Criterios de aceptación

**Tanda 1 — Detectores**
- [ ] Los 3 detectores implementados, funciones puras, sin dependencia del pipeline.
- [ ] Suite verde, sin regresiones sobre los 582 tests existentes.
- [ ] **Tasa de detección sobre las 1113 zonas del dataset reportada por `CandleKind`.**
- [ ] **Ningún `CandleKind` con tasa <2% o >40%.** Fuera de ese rango se recalibra el umbral
      correspondiente *antes* de pasar a Tanda 2. Este criterio existe porque tres detectores
      previos pasaron sus tests sintéticos y nunca dispararon en producción.

**Tanda 2 — Backtest**
- [ ] Harness corre sobre las 1113 filas sin lookahead (verificado con test explícito de que la
      detección no ve barras posteriores a `fetched_at`).
- [ ] Tabla de aguante por strike × variante × ventana (30/45/60).
- [ ] Tabla cruzada confirmación × aguante del `aggressive`.
- [ ] Al menos una variante cumple los tres targets de §3.5, o queda documentada la calibración
      del buffer que la hace cumplirlos.
- [ ] Grupo de control (36 zonas `regime IS NOT NULL AND primary_trigger IS NULL`) reportado
      aparte, **con la advertencia explícita de que N=36 solo permite señal direccional**.

**Tanda 3 — Integración**
- [ ] `candle_signals` en el modelo, persistido y renderizado en HTML y CSV.
- [ ] Variante ganadora reemplaza a `compute_heuristic_strikes` en el pipeline.
- [ ] Card HTML muestra el elemento ancla de cada strike (ej. "aggressive: debajo de SMA200W").
- [ ] Decisión explícita y registrada: la confirmación por velas queda como **anotación** (peso
      0.0) o asciende a **gate**. Se decide con la tabla de Tanda 2, no antes.
- [ ] ROADMAP §1/§2/§3/§5 + contadores reales actualizados y commiteados.

---

## 10. Archivos a crear / modificar

```
src/puts_screener/
├── candle_patterns.py          [NUEVO]  3 detectores + helpers de geometría
├── config_candles.py           [NUEVO]  constantes §3.1 + §3.2
├── models_candles.py           [NUEVO]  CandleSignal, CandleAnalysis
├── strike_placement.py         [NUEVO]  variantes A/B/C + extract_heavy_anchors
├── models_reports.py           [MOD]    + StructuralStrikes
├── models_screening.py         [MOD]    + ScreenedCandidate.candle_signals
├── config_reports.py           [MOD]    + buffers ATR por variante
├── final_pipeline.py           [MOD]    llamada a analyze_candles post-Paso 2
├── persistence.py              [MOD]    + 7 columnas de migración, + save_candle_analysis
├── reports_csv.py              [MOD]    + columnas de señales y anclas
├── reports_html.py             [MOD]    + señales en card, ancla en strikes-banner
└── templates/report.html.j2    [MOD]    render de señales + anclas

tests/
├── test_candle_patterns.py     [NUEVO]
├── test_strike_placement.py    [NUEVO]
└── test_candles_integration.py [NUEVO]

scratch/
└── backtest_candles.py         [NUEVO]  harness, gitignored, no productivo

specs/
└── 11_candle_confirmation_strikes.md   [NUEVO]  este doc
```

---

## 11. Decisiones registradas

**D11.1 — Contrato reconstruido desde código, no desde spec 10.** `specs/10_*.md` no existe en
disco pese a estar marcada cerrada en ROADMAP. Las firmas de `detectors.py`, `models_support.py` y
el orden de `final_pipeline.py` que esta spec asume fueron leídos del código real. Si spec 10 se
reconstruye alguna vez como documento, verificar que no contradiga lo asumido acá.

**D11.2 — Detectores antes que integración, con tasa de detección como criterio de aceptación.**
Invierte el orden usado en spec 10, que produjo tres detectores con tests verdes y cero
detecciones reales. La regla generalizable: **ningún detector nuevo se integra sin tasa de
detección medida sobre data real.** Debería aplicar a specs futuras.

**D11.3 — Umbrales calibrados para pullback en uptrend, no para capitulación.** 64% de la
población histórica es `pullback_in_uptrend`. Los umbrales del material de referencia (mecha 2×,
caída previa fuerte) están pensados para reversales dramáticos, que es justo la población que el
Paso 1 filtra sistemáticamente (evidencia: IQV, JD.L, MCG.L llegaron a 5/5 en
`capitulation_reclaim` y ninguno pasó Paso 1). Calibrar para el caso dramático produciría el
cuarto detector mudo.

**D11.4 — Catálogo reducido a 3 familias, no ~20 patrones nombrados.** Hammer = hanging man =
dragonfly doji (misma geometría, distinto contexto, y el contexto ya lo da la zona). Shooting star
= inverted hammer. Engulfing y piercing son el mismo eje con distinto umbral. Bull flag y rising
three methods son `pullback_in_uptrend`, ya existe. Runaway gap es `gap_unfilled`, ya es elemento
de score. Doji y spinning top señalan indecisión, no accionables. Implementar 20 nombres separados
sería inventar 20 juegos de umbrales sin data que los respalde.

**D11.5 — Sin requisito de gap en morning star.** El patrón canónico exige gaps entre cuerpos. En
equities líquidas de gran capitalización (nuestro universo: cap ≥$10B, volumen ≥1M) los gaps
intradiarios son raros fuera de earnings. Exigirlos volvería el detector inerte. Se conserva la
condición de cuerpo chico en la vela del medio, que es la que carga la semántica de indecisión.

**D11.6 — Target del `aggressive` en 70%, no 50%.** El pedido original fue "mínimo 50% de
acierto". 50% de aguante equivale a delta ~0.50 (at-the-money), fuera de la ventana 0.20–0.30 del
SOP. 70% es el piso consistente con delta 0.30. Reversible si el backtest muestra que la prima
extra compensa el riesgo adicional, pero entonces sería una decisión de cambiar la ventana de
delta del SOP, no de calibrar un strike.

**D11.7 — Redondeo de grilla siempre hacia abajo.** Redondear al más cercano puede acercar el
strike al spot por efecto del redondeo, degradando la probabilidad de aguante sin que ninguna
decisión de diseño lo haya querido. Hacia abajo es siempre conservador.

**D11.8 — Las 32 zonas con `regime IS NULL` se excluyen del backtest.** Tienen `pasa_paso_2=1` y
strikes poblados pero nunca fueron clasificadas, en 4 runs de 8 tickers cada uno. Es un bug de
clasificación, no una categoría analítica. Mezclarlas con el grupo de control (36 clasificadas sin
trigger) contaminaría la comparación. Issue separado para ROADMAP §2.

**D11.9 — Criterios de outcome pre-registrados en §3.4.** Fijados antes de correr el backtest,
explícitamente para evitar elegir el criterio de "aguantó vs rompió" después de ver qué número
favorece la hipótesis. Cualquier cambio posterior se registra fechado y justificado.

**D11.10 — Cierre por sobre mínimo intradía como criterio de perforación.** Una mecha que perfora
el strike y recupera en el día no gatilla asignación en un put europeo ni, en la práctica, en uno
americano fuera de vencimiento. Usar el mínimo sobreestimaría las perforaciones.
