# Spec 07 — Rediseño visual de cards + strikes heurísticos + mini-chart + narrativa

> Cuatro cambios en el HTML report que se entregan juntos porque comparten el refactor del layout: grilla full-width 1 col, mini-chart inline SVG, strikes heurísticos sugeridos, y narrativa técnica heurística por card. Primer puente al Paso 4 del SOP sin requerir cadena de opciones.

## 1. Objetivo

1. **Rediseño de la card** a grilla full-width (1 col) con split interno texto/chart 50/50, reordenando el contenido de spec 06 según jerarquía de uso diario.
2. **Mini-chart inline SVG** con precio diario últimos ~6 meses, zona de soporte sombreada y los 3 strikes como líneas horizontales.
3. **Strikes heurísticos** (aggressive/natural/conservative) computados desde zona + spot + ATR, redondeados a grilla típica por divisa.
4. **Narrativa técnica heurística** de 3 párrafos por card (situación, zona, qué mirar), generada con plantillas deterministas desde los campos ya disponibles.

El yield ≥1.5%/mes del SOP queda como nota textual a verificar en broker — sin cadena de opciones no se valida.

## 2. Scope

### En scope

- Módulo nuevo `strikes.py` con `compute_heuristic_strikes` y tabla de grillas por divisa (USD, EUR, CHF, GBP, GBp, fallback).
- Módulo nuevo `chart_svg.py` con `render_mini_chart_svg` que toma OHLCV diario + bounds + strikes + currency y devuelve string SVG.
- Módulo nuevo `narrative.py` con `build_narrative(candidate) -> str` heurístico determinista. Devuelve 3 párrafos: situación, zona, qué mirar. No persiste.
- Modelo nuevo `HeuristicStrikes` en `models_reports.py` (archivo nuevo).
- `reports_html._format_candidate` agrega 3 strikes (raw + formateado), `chart_svg` y `narrative_html` al dict.
- Template `report.html.j2` rediseñado: grilla 1 col full-width, card con split interno texto/chart 50/50, narrativa arriba del listado de elementos, banner full-width de strikes al final de cada card, sin truncado de la lista de elementos.
- Persistencia: 4 columnas nuevas en `candidates` (3 strikes + `strike_grid_unit`) con migración idempotente.
- CSV: 3 columnas nuevas al final (grid_unit solo a SQLite).
- Tests: cobertura de strikes en varios rangos/divisas + edges, smoke de SVG, narrativa por escenarios, integración del dict del candidato.

### Fuera de scope

- **Cadena de opciones**: yield, delta, premium, IV. Solo el texto "verificar yield ≥1.5%/mes en broker".
- **Chart interactivo**: tooltips, hover, zoom. SVG estático puro.
- **Series de MAs en el chart**: SMAs ya están listadas en los elementos. Superponerlas en 200px es ruido.
- **Pivots / anchors AVWAP en el chart**: no persistidos, recomputarlos en el renderer es trabajo grande. Diferido.
- **Múltiples zonas en el chart**: solo `best_zone`. Las demás `valid_zones` no se dibujan.
- **Backend LLM para la narrativa**: documentado en §11 como extensión futura. No se implementa hook ni branching en esta spec.
- **Persistencia de la narrativa**: es función pura de campos ya persistidos, regenerable en cualquier momento.
- **Watchlist personal**: spec 08.

## 3. Decisiones de parametrización

Constantes nuevas en `src/puts_screener/config_reports.py`.

### 3.1 Strikes

| Constante | Valor | Justificación |
|---|---|---|
| `STRIKE_ATR_MULTIPLIER` | `1.0` | Separación mínima entre strike y bound de zona. Con clustering compacto (≤4% ancho, spec 06), ATR×1.0 garantiza que aggressive y conservative no se peguen. |
| `STRIKE_GRID_USD` | `((25, 0.5), (100, 1.0), (250, 2.5), (float("inf"), 5.0))` | Grillas reales de strikes listables en US. |
| `STRIKE_GRID_EUR` | igual que USD | Ratio EUR/USD ≈ 1; brokers EU usan grillas similares. |
| `STRIKE_GRID_CHF` | igual que USD | Idem. |
| `STRIKE_GRID_GBP` | igual que USD | Tickers en libras enteras son raros en yfinance (casi todos van en GBp). |
| `STRIKE_GRID_GBP_PENCE` | `((2500, 50), (10000, 100), (25000, 250), (float("inf"), 500))` | Magnitudes ×100 sobre USD. Spot 300p → grilla 50p. Spot 7500p → 100p. |
| `STRIKE_GRID_FALLBACK_PCT` | `0.01` | Divisas no listadas (ZAc, ILA…): 1% del spot redondeado a 1 sig fig. Grosera pero defendible. |

### 3.2 Mini-chart

| Constante | Valor | Justificación |
|---|---|---|
| `MINI_CHART_WIDTH` | `480` | Mitad de la card full-width con padding interno. |
| `MINI_CHART_HEIGHT` | `200` | Proporción 12:5 aprox, más resolución vertical aprovechando el ancho. |
| `MINI_CHART_LOOKBACK_DAYS` | `126` | ~6 meses hábiles. Contexto reciente sin saturar la línea. |
| `MINI_CHART_MIN_DAYS` | `30` | Bajo este umbral, no se dibuja chart (placeholder textual). |
| `MINI_CHART_PADDING_X` | `28` | Lateral: deja espacio a los labels Y. |
| `MINI_CHART_PADDING_Y` | `10` | Vertical: aire para que el path no toque borde. |
| `MINI_CHART_Y_EXTRA_PCT` | `0.05` | Margen vertical sobre el rango (closes ∪ bounds ∪ strikes). |
| `MINI_CHART_COLOR_ZONE` | `"#fbbf24"` | Amarillo con `fill-opacity 0.18`. Mismo flag-bg actual. |
| `MINI_CHART_COLOR_AGGRESSIVE` | `"#dc2626"` | Rojo. Más cerca del spot, mayor probabilidad de asignación. |
| `MINI_CHART_COLOR_NATURAL` | `"#f97316"` | Naranja. Centro de la zona. |
| `MINI_CHART_COLOR_CONSERVATIVE` | `"#16a34a"` | Verde. Más lejos, menor prima pero menor riesgo. |
| `MINI_CHART_SPOT_RADIUS` | `3.5` | Círculo destacado al final de la serie. |

Línea de precio y labels usan `currentColor` (hereda del CSS de la card → funciona en light y dark sin mediaqueries internas al SVG).

### 3.3 Layout / grilla principal

| Decisión | Valor | Justificación |
|---|---|---|
| `grid-template-columns` (main) | `1fr` | Una card por fila, full-width. Cada candidato merece atención individual; en runs típicos (10-30 cards) el scroll es manejable. |
| Split interno texto/chart | `grid-template-columns: minmax(0, 1fr) minmax(0, 1fr)` | 50/50 dentro de la card. El chart respira en ~480px de ancho. |
| Media query collapse split interno | `@media (max-width: 720px)` | Bajo 720px de viewport, split colapsa a 1 col (chart debajo del texto). |
| `max-width` del container | sin cambio (1100px) | Mantiene compat con header/footer/macro-banner. |
| Truncado de elementos | **eliminado** | Toda la lista de elementos se renderiza completa. Sin `[:8]`, sin "+N más". |

### 3.4 Jerarquía dentro de la card

ASCII de referencia:

```
┌─────────────────────────────────────────────────────────────────────────┐
│ TICKER [badges] sector exchange                              [T2 badge] │
│ ⭐⭐⭐⭐ Confluencia fuerte  ·  Score crudo 8.4                          │
│ Spot $100   Zona [$93–$95]   Distancia 5.0%                             │
├────────────────────────────────────────┬────────────────────────────────┤
│ ANÁLISIS                               │                                │
│ ┌────────────────────────────────────┐ │                                │
│ │ Situación. ...                      │ │                                │
│ │ Zona. ...                           │ │      [ MINI-CHART SVG ]        │
│ │ Qué mirar. ...                      │ │      (banda + 3 strikes        │
│ └────────────────────────────────────┘ │       precio 6m, spot final)   │
│                                        │                                │
│ Elementos (7):                         │                                │
│  - SMA200W @ $94.20                    │                                │
│  - polarity @ $93.80                   │                                │
│  - AVWAP_earnings @ $94.10             │                                │
│  - HVN @ $93.50                        │                                │
│  - FIB_618 @ $93.00                    │                                │
│  - FIB_500 @ $94.50                    │                                │
│  - GAP @ $92.80                        │                                │
│ RSI_d 42 · RSI_w 47 · MACD↑            │                                │
│ PT $115 (+15%) · Buy 78%               │                                │
├────────────────────────────────────────┴────────────────────────────────┤
│ STRIKES SUGERIDOS                       verificar yield ≥1.5%/mes broker│
│ ● Aggressive $98     ● Natural $94      ● Conservative $91              │
├─────────────────────────────────────────────────────────────────────────┤
│ [flags ticker-específicos: earnings en 12d, ex-div en 5d]               │
│ [momentum signals: divergencia rsi]                                     │
└─────────────────────────────────────────────────────────────────────────┘
```

Flags y momentum signals quedan al fondo (no son la conclusión accionable; los strikes sí). El bloque de strikes es full-width dentro de la card. La narrativa abre la columna izquierda del split, arriba del listado de elementos.

## 4. Modelos

### 4.1 `HeuristicStrikes` — `src/puts_screener/models_reports.py` (nuevo)

```python
@dataclass(frozen=True)
class HeuristicStrikes:
    """Tres strikes sugeridos derivados de la zona + spot + ATR.

    Redondeados a grilla típica del exchange según la divisa. No se valida
    yield ni se consulta cadena de opciones — son sugerencias para que el
    humano verifique en su broker.
    """
    aggressive: float       # cerca del spot, mayor prima, mayor asignación
    natural: float          # centro de la zona
    conservative: float     # lejos de la zona, menor prima, menor riesgo
    grid_unit: float        # paso de grilla usado (debug + persistencia)
```

`models_reports.py` es archivo nuevo. Convive con `models_final.py`, `models_support.py`, etc.

### 4.2 Claves nuevas en el dict que recibe el template

Agregadas por `_format_candidate`:

| Clave | Tipo | Contenido |
|---|---|---|
| `strike_aggressive` | `float` | Strike numérico crudo. |
| `strike_natural` | `float` | Idem. |
| `strike_conservative` | `float` | Idem. |
| `strike_aggressive_formatted` | `str` | Con divisa, p.ej. `"$98"` / `"94p"`. Usa `format_price` de spec 06. |
| `strike_natural_formatted` | `str` | Idem. |
| `strike_conservative_formatted` | `str` | Idem. |
| `chart_svg` | `str` | SVG completo listo para incrustar con `\|safe`. `""` si insuficiente. |
| `chart_placeholder` | `str` | Mensaje si `chart_svg == ""`. P.ej. `"Histórico insuficiente para chart"`. |

**Claves planas, no sub-dict.** El `HeuristicStrikes` se usa internamente y para persistir, no se pasa al template como objeto. Sigue el patrón actual de `_format_candidate`.

### 4.3 Clave nueva para la narrativa

`_format_candidate` también agrega:

| Clave | Tipo | Contenido |
|---|---|---|
| `narrative_html` | `str` | HTML pre-formateado con 3 `<p>` (situación, zona, qué mirar). Cada `<p>` arranca con un `<strong>` (etiqueta del párrafo). Inyectado al template con `\|safe`. |

El template no necesita lógica de párrafos: `build_narrative` ya devuelve markup listo.

## 5. APIs públicas

```python
# strikes.py
def compute_heuristic_strikes(
    zone_lower_bound: float,
    zone_upper_bound: float,
    zone_center_price: float,
    spot: float,
    atr_14: float,
    currency: str,
) -> HeuristicStrikes: ...

# chart_svg.py
def render_mini_chart_svg(
    ohlcv_daily: pd.DataFrame,
    zone_lower_bound: float,
    zone_upper_bound: float,
    strikes: HeuristicStrikes,
    currency: str,
) -> str:
    """String SVG completo, o "" si len(ohlcv_daily) < MINI_CHART_MIN_DAYS."""

# narrative.py
def build_narrative(candidate: FinalCandidate) -> str:
    """3 párrafos HTML describiendo situación, zona y qué mirar.

    Función pura. No persiste. Si algún campo es None o la situación no
    aplica, omite limpio las oraciones afectadas — nunca deja placeholders
    huérfanos.
    """
```

Helpers privados en `strikes.py`:

- `_grid_for_currency(currency: str, spot: float) -> float`
- `_round_to_grid(value: float, grid_unit: float) -> float`
- `_fallback_grid(spot: float) -> float`

## 6. Algoritmos

### 6.1 Strikes

```
compute_heuristic_strikes(lower, upper, center, spot, atr, currency):
    grid = _grid_for_currency(currency, spot)

    aggressive_raw   = max(upper, spot - atr * STRIKE_ATR_MULTIPLIER)
    natural_raw      = center
    conservative_raw = lower - atr * STRIKE_ATR_MULTIPLIER

    return HeuristicStrikes(
        aggressive   = _round_to_grid(aggressive_raw, grid),
        natural      = _round_to_grid(natural_raw, grid),
        conservative = _round_to_grid(conservative_raw, grid),
        grid_unit    = grid,
    )

_grid_for_currency(currency, spot):
    table = {
        "USD": STRIKE_GRID_USD,
        "EUR": STRIKE_GRID_EUR,
        "CHF": STRIKE_GRID_CHF,
        "GBP": STRIKE_GRID_GBP,
        "GBp": STRIKE_GRID_GBP_PENCE,
    }.get(currency)
    if table is None: return _fallback_grid(spot)
    for threshold, grid in table:
        if spot < threshold: return grid
    return table[-1][1]  # defensive

_fallback_grid(spot):
    if spot <= 0: return 0.01
    raw = spot * STRIKE_GRID_FALLBACK_PCT
    magnitude = 10 ** floor(log10(raw))
    return round(raw / magnitude) * magnitude  # 1 sig fig

_round_to_grid(value, grid):
    return round(value / grid) * grid
```

**Edge: strikes colapsados.** Si por compactness de zona dos strikes redondean al mismo valor, se dejan así. Refleja la realidad de la grilla del broker; el humano interpreta "zona chica para diferenciar". No se hace anti-colapso (sería overfitting).

**Edge: zona muy cerca del spot.** Si `spot - ATR < upper_bound`, `aggressive = upper_bound` (la zona ya está suficientemente cerca; no acercamos más). Esto es el `max(...)` del cálculo.

### 6.2 Mini-chart SVG

```
render_mini_chart_svg(ohlcv, lower, upper, strikes, currency):
    n = min(len(ohlcv), MINI_CHART_LOOKBACK_DAYS)
    if n < MINI_CHART_MIN_DAYS: return ""

    closes = ohlcv["Close"].tail(n).tolist()
    dates  = ohlcv.index[-n:]

    # Y range: closes ∪ bounds ∪ strikes con margen
    ys = closes + [lower, upper, strikes.aggressive, strikes.natural, strikes.conservative]
    y_min_raw, y_max_raw = min(ys), max(ys)
    span = y_max_raw - y_min_raw
    y_min = y_min_raw - span * MINI_CHART_Y_EXTRA_PCT
    y_max = y_max_raw + span * MINI_CHART_Y_EXTRA_PCT

    W, H = MINI_CHART_WIDTH, MINI_CHART_HEIGHT
    PX, PY = MINI_CHART_PADDING_X, MINI_CHART_PADDING_Y
    plot_w, plot_h = W - 2*PX, H - 2*PY

    def x(i):    return PX + (i / (n - 1)) * plot_w
    def y(p):    return PY + (1 - (p - y_min) / (y_max - y_min)) * plot_h

    # 1. Banda zona
    band = '<rect x="{PX}" y="{y(upper)}" width="{plot_w}"
             height="{y(lower) - y(upper)}" fill="{ZONE_COLOR}" fill-opacity="0.18"/>'

    # 2. Líneas de strikes (dashed, 3 colores)
    for (strike, color) in [(aggressive, RED), (natural, ORANGE), (conservative, GREEN)]:
        '<line x1="{PX}" x2="{PX+plot_w}" y1="{y(strike)}" y2="{y(strike)}"
               stroke="{color}" stroke-width="1.2" stroke-dasharray="3 3"/>'

    # 3. Polyline del precio
    points = " ".join(f"{x(i):.1f},{y(c):.1f}" for i, c in enumerate(closes))
    '<polyline points="{points}" fill="none" stroke="currentColor"
               stroke-width="1.4" opacity="0.85"/>'

    # 4. Spot point al final
    '<circle cx="{x(n-1)}" cy="{y(closes[-1])}" r="{SPOT_R}" fill="currentColor"/>'

    # 5. Labels Y min/max (esquinas izquierdas, font-size 8, opacity 0.55)
    # 6. Labels fecha first/"hoy" (esquinas inferiores, opacity 0.45)

    return f'<svg viewBox="0 0 {W} {H}" xmlns="..." role="img" aria-label="...">...</svg>'
```

**Notas:**

- `format_price` (existente, spec 06) para los labels Y con divisa correcta.
- `polyline` no `path`: ~126 puntos × ~12 chars = ~1.5KB por chart. Con 30 cards → ~50KB extra en el HTML. Aceptable.
- `currentColor` hereda del CSS de la card; el SVG se renderiza correctamente en light y dark mode sin lógica adicional.
- Mes en el label de fecha: usar mapa manual `_MONTH_ABBR_ES = {1: "ene", 2: "feb", ...}` para evitar diferencia local/CI (Actions corre en inglés por default).

### 6.3 Narrativa heurística

Tres helpers privados, uno por párrafo. Cada uno devuelve un `<p>` o `""` si no hay nada significativo que decir (caso raro, casi siempre hay material).

```
build_narrative(fc):
    p1 = _narrative_situation(fc)
    p2 = _narrative_zone(fc)
    p3 = _narrative_what_to_watch(fc)
    return "\n".join(p for p in [p1, p2, p3] if p)
```

**`_narrative_situation`** — describe el contexto T1-T5:

- Lee `classification.tipo` y `classification.justificacion` (ya existentes).
- Mapa fijo `_TIPO_DESCRIPTION = {"T1": "tendencia alcista intacta con pullback a soporte", "T2": "pánico de mercado o spike de IV", "T3": "lateralización en zona técnica", "T4": "post-earnings dip con tendencia intacta", "T5": "wheel/acumulación"}`.
- Inyecta señales de momentum: si `rsi_d < 50` y `rsi_d > rsi_d_3d_ago` → "RSI diario en {rsi_d:.0f} con giro al alza desde {rsi_d_3d_ago:.0f}". Si `macd_state == "rising"` → "MACD virando a positivo". Si ambos faltan, se omite la oración de momentum.
- Cierra con flag de sobrecompra si aplica: si `rsi_d >= 70` → "atención: RSI diario en zona de sobrecompra ({rsi_d:.0f})" (caso raro porque el filtro del Paso 1 lo excluye, pero defensivo).

**`_narrative_zone`** — describe la confluencia:

- Width pct de la zona → calificativo: `width_pct < 0.02` = "compacta", `< 0.035` = "ajustada", `>= 0.035` = "amplia".
- Tier label (ya disponible: `tier_label`) → "confluencia X".
- Lista de los elementos heavy (peso ≥2.5): mapea cada uno a una frase contextual.
  - `sma_200w` / `sma_200d` / `ema_200d` → "la SMA200 como referencia institucional de largo plazo".
  - `polarity` → "una resistencia rota previamente que ahora opera como soporte".
  - `avwap_pivot_low` / `avwap_earnings` / `avwap_52w_high` → "el AVWAP desde {anchor} como precio promedio de acumulación reciente". El `anchor` se deriva del label.
  - `hvn` → "un nodo de alto volumen en la zona (acumulación previa)".
  - `sma_50w` / `sma_50d` / `ema_50d` → "la SMA50 como soporte de mediano plazo".
  - Dedup por categoría: si hay SMA200W + EMA200D + SMA200D heavy, una sola mención de "SMA200".
- Concatena con "anclada en {n} elementos heavy: ..." si hay 2+. Si hay 1 solo heavy (raro post-gate estructural), "anclada en {heavy}".
- Cierra con la distancia: "El precio está a {distance_pct}% del techo de la zona, dentro del rango operable" si `distance_pct < 0.08`, sino "al límite del rango operable ({distance_pct}%)".

**`_narrative_what_to_watch`** — qué vigilar:

- Stop estructural: "Si el precio cierra debajo del conservative (${strike_conservative}), conviene revisar la tesis."
- Earnings en ventana: si `binary_events.earnings_en_45d` → "Earnings en {dias_a_earnings} días — considerar dimensionar la posición para evento o evitar strikes que asignen alrededor del reporte."
- Ex-div en ventana: si `binary_events.ex_div_en_45d` → "Ex-dividend en {dias_a_ex_div} días (${ex_div_amount}) — riesgo de asignación temprana del put si la opción queda ITM en esa fecha."
- Macro: si hay `macro_events` global afectando ventana → "Eventos macro en ventana ({n}): {kinds}." (info ya está en el banner pero conviene reforzar en card por contexto local).
- Si nada de lo anterior aplica: "Sin eventos binarios ni macro en ventana — situación técnica limpia."

## 7. Persistencia

`candidates`: 4 columnas nuevas.

```sql
ALTER TABLE candidates ADD COLUMN strike_aggressive REAL;
ALTER TABLE candidates ADD COLUMN strike_natural REAL;
ALTER TABLE candidates ADD COLUMN strike_conservative REAL;
ALTER TABLE candidates ADD COLUMN strike_grid_unit REAL;
```

Migración idempotente vía el mecanismo existente (chequear `PRAGMA table_info`, agregar si falta). Schema final: 41 columnas previas + 4 nuevas = 45.

CSV: 3 columnas al final (`strike_aggressive`, `strike_natural`, `strike_conservative`). `strike_grid_unit` queda solo en SQLite (debug).

La narrativa **no se persiste**. Es función pura de campos ya persistidos.

## 8. Tests

### 8.1 `tests/test_strikes.py` (nuevo, ~10)

- `test_strike_grid_usd_under_25` / `_under_100` / `_under_250` / `_above_250`: grilla correcta por rango.
- `test_strike_grid_gbp_pence`: spot=300, currency="GBp" → grid=50.
- `test_strike_grid_fallback`: spot=1000, currency="ZAc" → grid no nulo, ≈10.
- `test_compute_strikes_typical`: spot=100, atr=2, zone=[93,95] → aggressive=98, natural=94, conservative=91.
- `test_compute_strikes_zone_close_to_spot`: spot=100, atr=2, zone=[96,97] → aggressive=98, natural=97, conservative=94.
- `test_compute_strikes_wide_zone`: spot=100, atr=2, zone=[88,92] → aggressive=98 (cap por ATR), natural=90, conservative=86.
- `test_compute_strikes_low_price`: spot=15, atr=0.5, zone=[13,14] → grid 0.5 aplicada.
- `test_compute_strikes_collapsed`: zona tan compacta que natural y aggressive coinciden post-redondeo → ambos iguales, sin ajuste.

### 8.2 `tests/test_chart_svg.py` (nuevo, ~6)

- `test_render_chart_typical`: OHLCV 180 días → string contiene `<svg`, `<polyline`, 3 `<line` (strikes), 1 `<rect` (banda), 1 `<circle` (spot). Verificar `viewBox="0 0 480 200"`.
- `test_render_chart_short_history`: OHLCV 50 días → dibuja con 50 puntos.
- `test_render_chart_insufficient`: OHLCV 20 días → devuelve `""`.
- `test_render_chart_empty_ohlcv`: df vacío → `""`.
- `test_render_chart_y_labels_currency`: labels Y formateados con la divisa correcta (USD vs GBp).
- `test_render_chart_strike_lines_dashed`: las `<line>` tienen `stroke-dasharray`.

### 8.3 `tests/test_reports_html.py` (extender, +3)

- `test_format_candidate_includes_strikes`: dict contiene `strike_aggressive` + `_formatted` (×3).
- `test_format_candidate_includes_chart_svg`: dict contiene `chart_svg` no vacío con OHLCV normal.
- `test_format_candidate_chart_placeholder_when_short_history`: con OHLCV degenerado, `chart_svg == ""` y `chart_placeholder` tiene mensaje.

### 8.4 `tests/test_persistence.py` (extender, +2)

- `test_migrate_adds_strike_columns`: schema viejo migra a nuevo sin pérdida.
- `test_persist_candidate_with_strikes`: persistir y leer back los 4 valores.

### 8.5 Smoke test manual

```bash
python -m puts_screener.run --limit 50
# Abrir output/screening_latest.html y verificar:
# - Desktop: 1 col full-width, cada card con split texto/chart 50/50
# - Narrativa visible arriba del listado de elementos, 3 párrafos
# - Listado de elementos completo (sin "+N más")
# - SVG renderiza con banda amarilla, 3 líneas punteadas (roja/naranja/verde), precio, círculo final
# - Bloque "STRIKES SUGERIDOS" full-width al fondo de cada card
# - Dark mode (system preference): chart legible, banda visible
# - Mobile (DevTools <720px): split colapsa, chart debajo del texto
```

### 8.6 `tests/test_narrative.py` (nuevo, ~10)

- `test_narrative_t1_full`: candidato T1 con momentum positivo + 4 heavies + earnings en 10d → output contiene "tendencia alcista", "SMA200", "Earnings en 10 días", 3 párrafos.
- `test_narrative_t2_panico`: candidato T2 → contiene "pánico" o "spike de IV".
- `test_narrative_zone_compact_vs_wide`: width 1.2% → "compacta". Width 3.8% → "amplia".
- `test_narrative_omits_momentum_when_missing`: candidato con rsi_d_3d_ago == rsi_d → sin oración de momentum, párrafo bien formado.
- `test_narrative_clean_no_events`: candidato sin earnings ni macro → "situación técnica limpia".
- `test_narrative_multiple_events`: candidato con earnings + ex-div + macro → menciona los tres.
- `test_narrative_dedup_sma200`: heavies incluyen sma_200w + ema_200d + sma_200d → una sola mención de SMA200.
- `test_narrative_avwap_anchor_from_label`: heavy `avwap_earnings` → mención de "AVWAP desde earnings".
- `test_narrative_distance_at_edge`: distance_pct 8.5% → "al límite del rango operable".
- `test_narrative_html_structure`: output es exactamente 3 `<p>` con `<strong>` inicial cada uno.

## 9. Criterios de aceptación

- [ ] `strikes.py`, `chart_svg.py`, `narrative.py`, `models_reports.py` existen con las funciones/clases de §5.
- [ ] `config_reports.py` extendido con las constantes de §3.1 y §3.2.
- [ ] `_format_candidate` agrega las 9 claves nuevas al dict (3 strikes raw + 3 formatted + chart_svg + chart_placeholder + narrative_html).
- [ ] `report.html.j2` rediseñado: grilla 1 col full-width, split interno 50/50, narrativa arriba de elementos, listado completo sin truncado, banner strikes full-width, jerarquía de §3.4.
- [ ] `persistence.py` migra y persiste las 4 columnas nuevas.
- [ ] `reports_csv.py` agrega 3 columnas (`strike_grid_unit` solo a SQLite).
- [ ] ~32 tests nuevos en verde. Total sube de 404 a ~436 sin romper ninguno existente.
- [ ] Smoke manual (§8.5) renderiza correcto en light/dark y desktop/mobile.
- [ ] SVG válido sin warnings de consola en Chrome y Firefox.
- [ ] `narrative.py` existe con `build_narrative` y 3 helpers privados.
- [ ] Layout en 1 columna full-width, sin truncado de elementos, narrativa visible arriba del listado de elementos.

## 10. Archivos a crear / modificar

```
puts-screener/
├── specs/
│   └── 07_visual_cards_redesign.md           [NEW — esta spec]
├── src/puts_screener/
│   ├── chart_svg.py                          [NEW]
│   ├── config_reports.py                     [MOD: + constantes §3.1 y §3.2]
│   ├── models_reports.py                     [NEW]
│   ├── narrative.py                          [NEW]
│   ├── persistence.py                        [MOD: migración + persist 4 cols]
│   ├── reports_csv.py                        [MOD: + 3 cols CSV]
│   ├── reports_html.py                       [MOD: _format_candidate]
│   ├── strikes.py                            [NEW]
│   └── templates/
│       └── report.html.j2                    [MOD: grilla 1 col full-width + split + narrativa + banner strikes + sin truncado]
└── tests/
    ├── test_chart_svg.py                     [NEW]
    ├── test_narrative.py                     [NEW]
    ├── test_persistence.py                   [MOD: + 2 tests]
    ├── test_reports_html.py                  [MOD: + 3 tests]
    └── test_strikes.py                       [NEW]
```

5 archivos nuevos en `src/`, 4 modificados. 3 tests nuevos, 2 modificados. 1 spec nueva.

## 11. Decisiones registradas

- **2026-05-27 — Spec 07, strikes opción C (anclados a zona con ATR como unidad mínima)**: descartadas A (% off spot fijos: desconecta de la zona) y B (100% bounds: con clustering compacto los strikes quedan pegados). C ancla a la zona pero el ATR garantiza separación proporcional a la volatilidad. Redondeo a grilla típica por divisa hace los valores listables en broker.
- **2026-05-27 — Spec 07, grilla full-width 1 col**: descartadas 2 cols y 3 cols. Una card por fila aprovecha el ancho para chart más legible (480×200), narrativa cómoda y lista de elementos sin truncar. Scroll vertical asumido (runs típicos 10-30 cards).
- **2026-05-27 — Spec 07, sin truncado de elementos**: eliminado `[:8]` y "+N más". Cards full-width pueden absorber listas completas. Información completa sobre densidad visual.
- **2026-05-27 — Spec 07, mini-chart SVG inline server-side**: descartados canvas/JS (no compone con HTML estático de Pages) e imagen rasterizada (path en disco, regenerar, peso). SVG inline se mete con `\|safe`. Tamaño 480×200, ~1.5KB/chart, ~50KB extra con 30 cards.
- **2026-05-27 — Spec 07, chart sin SMAs ni anchors marcados**: las SMAs ya están textuales en los elementos heavies. Anchors AVWAP no están persistidos. Mantener el chart limpio prioriza lo único que el texto no puede expresar: la trayectoria reciente.
- **2026-05-27 — Spec 07, strikes pasados como claves planas al template**: el `HeuristicStrikes` dataclass se usa internamente y para persistencia; el template recibe primitivas. Sigue el patrón actual de `_format_candidate`.
- **2026-05-27 — Spec 07, strikes colapsados se dejan como caen**: si tras redondear a grilla dos strikes coinciden, no se ajustan. Refleja la realidad de la grilla del broker.
- **2026-05-27 — Spec 07, persistir `strike_grid_unit` solo en SQLite**: facilita debug si la grilla cambia entre versiones. CSV se mantiene limpio y enfocado al consumo humano.
- **2026-05-27 — Spec 07, mes en español manual en SVG**: evita diferencia local (Windows en español) vs CI (Linux Actions en inglés). Pequeño costo de mantenimiento, garantiza consistencia visual.
- **2026-05-27 — Spec 07, yield 1.5%/mes como nota textual, no validable**: sin cadena de opciones no se computa. El SOP lo pide; nuestra implementación lo refleja como instrucción al humano debajo de los strikes.
- **2026-05-27 — Spec 07, OHLCV ya disponible en `screened.ohlcv_daily`**: hallazgo de la inspección. Sin re-fetch, el chart se construye desde memoria. Patrón ya usado por el resto del renderer; no requiere nuevo contenedor.
- **2026-05-27 — Spec 07, narrativa heurística determinista (opción A)**: descartado LLM (opción B) por costo recurrente, no determinismo, latencia en cron, choque con regla de tests deterministas. La heurística da 80% del valor con cero costo operativo.
- **2026-05-27 — Spec 07, narrativa no persiste**: es función pura de campos ya persistidos en `candidates`. Regenerable en cualquier momento sin pérdida. Evita inflar la DB.
- **2026-05-27 — Spec 07, `narrative.py` retorna HTML pre-formateado**: el template recibe `narrative_html` listo para `\|safe`. Mantiene el template "puramente presentacional" (regla del proyecto) y la lógica de mapeo en código testeable.
- **Extensión futura — Backend LLM opcional**: cuando exista criterio de uso (1-2 semanas con la heurística), se puede agregar `NARRATIVE_BACKEND=anthropic|gemini|groq` como env var. La función `build_narrative` se mantiene como interfaz; solo cambia la implementación. Tests del backend LLM van con mocks. No implementado.
