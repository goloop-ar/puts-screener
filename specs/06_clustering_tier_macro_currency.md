# Spec 06 — Clustering compacto + score tier + macro banner + currency display

> Cuatro mejoras que viajan juntas porque tocan los mismos archivos: refactor del clustering para que las zonas sean angostas (y el score premie esa compacidad), tier 1-5 sobre el score crudo, banner global de macro events fuera de las cards, y fix del símbolo monetario que hoy es `$` hardcoded para todos los tickers (incluyendo EU/UK).

## 1. Objetivo

1. **Clustering compacto + bonus por densidad** — Cambiar la geometría de las zonas para que reflejen confluencia real (muchos elementos heavy en poco ancho de precio). Hoy el clustering permite chaining (5 niveles separados de a £5 dan zona de £20) y el ancho mostrado es ATR14 fijo, independiente de dónde están los elementos. Resultado: zonas anchas pasan como "confluencia" cuando en realidad son dos clusters distintos pegados.
2. **Score tier 1-5** — El score crudo (5.0–15.5+) requiere conocer techo y piso para interpretarlo. Capa de presentación que mapea el score crudo a una escala accionable de estrellas.
3. **Banner global de macro events** — Hoy FOMC/CPI aparecen duplicados en cada card. Factorizar fuera de la grilla a un banner único arriba del HTML.
4. **Currency display correcto** — Hoy todos los precios se renderizan con `$` hardcoded. El modelo ya captura `currency` desde yfinance pero el template lo ignora. Fix: pasar el campo y mapearlo a símbolo (o sufijo en el caso `GBp`).

## 2. Scope

### En scope

- Refactor de `zone_clustering.py`: nueva métrica híbrida de tolerance, gate post-clustering por ancho máximo absoluto, ancho de banda mostrada = envelope real de elementos (no ATR fijo).
- Multiplicador de densidad en `compute_zone_score`: el score crudo de hoy (suma de max por categoría) pasa a ser `score_base`, multiplicado por un factor de densidad dependiente del ancho y la cantidad de heavies.
- Campo `width_pct` derivado en `SupportZone` (computado al vuelo, no persistido).
- Score tier como propiedad derivada del score final: enum/string con 5 niveles.
- Refactor de `_format_candidate` + `write_html_report`: factorizar macro events fuera del per-card; pasar `currency` al contexto del template.
- Template `report.html.j2`: nueva sección `<section class="macro-banner">`, símbolo dinámico, tier visible en las cards.
- Calibración empírica de las nuevas constantes con data real persistida en `screening_history.db` antes de cerrar la spec.

### Fuera de scope

- **Rediseño UX completo de la card** (más grande, info reorganizada, mini-chart inline). Va en spec 07.
- **Strikes sugeridos heurísticos**. Va en spec 07.
- **Cambios al gate de validez** (`SCORE_MIN_VALID`, `MIN_HEAVY_ELEMENTS`, `ZONE_MIN_DISTANCE_PCT`, etc). No tocamos hasta tener varias corridas del cron para calibrar.
- **Volume Profile real** (POC/VAL). Fase 4.
- **Pivots persistidos**. Fase 5.
- **Cambios al schema de SQLite**. `width_pct` se computa al vuelo desde `lower_bound`/`upper_bound` ya persistidos. No requiere migración.

### Decisión fundamental: la zona ahora es el envelope real del cluster

Hoy: `bounds = center ± ATR14 * 0.5`. Banda fija ATR14, ignora dónde están los elementos.

Spec 06: `bounds = [min(elementos) - tiny_buffer, max(elementos) + tiny_buffer]`. La banda refleja la dispersión real del cluster. Una zona con 5 elementos en £2 va a mostrarse como £2 ancho, no como £6.

Esto cambia visualmente lo que ve el usuario en la card y cambia el cálculo de `distance_pct` (que pasa a calcularse contra el `upper_bound` real, no el `center_price`).

## 3. Decisiones de parametrización

### 3.1 Clustering (modifica `config_supports.py`)

| Constante | Valor actual | Valor nuevo | Justificación |
|---|---|---|---|
| `CLUSTERING_TOLERANCE_ATR` | `0.5` | `0.4` | Tolerance entre niveles consecutivos del cluster. Bajado para reducir chaining sin eliminarlo del todo (algunos tickers volátiles legítimamente tienen elementos a 0.3-0.4 ATR de distancia que sí son la misma zona). |
| `CLUSTERING_TOLERANCE_MAX_PCT` | — (nuevo) | `0.01` | Cap absoluto al tolerance como % del spot. `tolerance_efectiva = min(ATR14 × 0.4, spot × 0.01)`. Para un stock con ATR14 grande pero spot alto, el % gana y mantiene la tolerance acotada. Para small caps el ATR gana. |
| `ZONE_MAX_WIDTH_PCT` | — (nuevo) | `0.04` | Post-clustering: si `(max - min) / center > 4%`, el cluster se considera demasiado disperso y **se rechaza completo** (no se forma zona). 4% es el techo de lo que clasificamos como "una zona" — más que eso son dos zonas distintas casualmente cerca. Calibrado contra el run de hoy: las zonas válidas hoy van de 2 a 7%; bajar a 4% recorta las anchas. |
| `ZONE_BUFFER_PCT` | — (nuevo) | `0.001` | Buffer pequeño que se suma a cada lado del envelope para no mostrar bounds idénticos a los precios extremos. Cosmético, no afecta lógica. |
| `ZONE_WIDTH_ATR_MULTIPLIER` | `0.5` | — (eliminado) | Reemplazado por el cálculo basado en envelope real. |

### 3.2 Density bonus (nuevo, en `config_supports.py`)

| Constante | Valor | Justificación |
|---|---|---|
| `MIN_WIDTH_FLOOR_PCT` | `0.005` | Floor para evitar división por casi-cero cuando el cluster es ultra-compacto (todos los elementos en <0.5% de ancho). Por debajo de esto, la densidad se computa como si el ancho fuera 0.5%. |
| `REFERENCE_DENSITY` | `100.0` | Densidad base (heavies por punto porcentual de ancho). Ejemplos: 2 heavies en 2% = densidad 100 (multiplicador neutro 1.0). 4 heavies en 2% = densidad 200 (bonus). 2 heavies en 5% = densidad 40 (penalización). |
| `DENSITY_BONUS_SLOPE` | `0.005` | Pendiente del multiplicador. `multiplier = 1.0 + (density - REFERENCE_DENSITY) * SLOPE`. Una zona con densidad 200 (vs ref 100) gana `(200-100) * 0.005 = 0.5` → multiplicador 1.5. |
| `MIN_DENSITY_MULTIPLIER` | `0.85` | Floor del multiplicador. Una zona muy ancha pierde como máximo 15% de su score. |
| `MAX_DENSITY_MULTIPLIER` | `1.5` | Cap del multiplicador. Una zona compacta gana como máximo 50% sobre su score base. |

Calibración: los valores arriba son **provisionales** — se ajustan tras correr el screener con el nuevo clustering y mirar la distribución empírica. Spec 06 cierra solo después de la calibración (ver §9 paso de validación).

### 3.3 Score tier (nuevo, en `config_supports.py`)

| Constante | Valor |
|---|---|
| `SCORE_TIER_THRESHOLDS` | `{5: 18.0, 4: 13.0, 3: 9.0, 2: 6.5, 1: 5.0}` |

Mapeo: si `score >= 18.0` → tier 5 (⭐⭐⭐⭐⭐). Si `score >= 13.0` → tier 4. Etc. **Provisional**, se recalibra post-validación junto con las constantes de densidad.

Labels human-readable (en `config_reports.py`):

```python
SCORE_TIER_LABELS = {
    5: ("⭐⭐⭐⭐⭐", "Confluencia excepcional"),
    4: ("⭐⭐⭐⭐", "Fuerte"),
    3: ("⭐⭐⭐", "Sólida"),
    2: ("⭐⭐", "Borderline"),
    1: ("⭐", "Mínimo viable"),
}
```

### 3.4 Currency mapping (nuevo, en `config_reports.py`)

```python
CURRENCY_DISPLAY = {
    "USD": {"prefix": "$", "suffix": "", "divisor": 1},
    "EUR": {"prefix": "€", "suffix": "", "divisor": 1},
    "GBP": {"prefix": "£", "suffix": "", "divisor": 1},
    "GBp": {"prefix": "",  "suffix": "p", "divisor": 1},  # peniques: magnitud tal cual + sufijo p
    "CHF": {"prefix": "",  "suffix": " CHF", "divisor": 1},
    "JPY": {"prefix": "¥", "suffix": "", "divisor": 1},
    "DKK": {"prefix": "",  "suffix": " kr", "divisor": 1},
    "SEK": {"prefix": "",  "suffix": " kr", "divisor": 1},
    "NOK": {"prefix": "",  "suffix": " kr", "divisor": 1},
}
CURRENCY_DEFAULT = {"prefix": "$", "suffix": "", "divisor": 1}  # fallback si currency es None o no listada
```

`divisor` reservado para futuro: si en algún momento decidimos mostrar peniques como libras, `GBp.divisor` pasa a 100. Por ahora 1 en todos.

## 4. Modelos modificados

### `SupportZone` — `models_support.py`

Nuevo campo derivado (no se persiste, computado al vuelo):

```python
@dataclass(frozen=True)
class SupportZone:
    # ... campos existentes ...
    
    @property
    def width(self) -> float:
        """Ancho de la zona en unidades de precio."""
        return self.upper_bound - self.lower_bound
    
    @property
    def width_pct(self) -> float:
        """Ancho de la zona como porcentaje del center_price."""
        return self.width / self.center_price if self.center_price > 0 else 0.0
    
    @property
    def n_heavy_elements(self) -> int:
        """Cantidad de elementos individuales con peso >= HEAVY_ELEMENT_WEIGHT_THRESHOLD."""
        return sum(1 for e in self.elements if ELEMENT_WEIGHTS.get(e.element, 0.0) >= HEAVY_ELEMENT_WEIGHT_THRESHOLD)
    
    @property
    def score_tier(self) -> int:
        """Tier 1-5 derivado del score final. Helper para display."""
        for tier in sorted(SCORE_TIER_THRESHOLDS.keys(), reverse=True):
            if self.score >= SCORE_TIER_THRESHOLDS[tier]:
                return tier
        return 1  # piso (zona válida tiene score >= 5.0 que ya es tier 1)
```

### `SupportLevel`

Sin cambios (el campo `points` vestigial sigue intacto — backlog para limpieza futura).

## 5. APIs públicas

### `zone_clustering.py`

```python
def cluster_into_zones(
    levels: list[SupportLevel],
    spot: float,
    atr14: float,
) -> list[SupportZone]:
    """
    Agrupa niveles de soporte en zonas usando single-linkage con tolerance híbrida
    y cap absoluto al ancho final. El cluster se rechaza si excede ZONE_MAX_WIDTH_PCT.
    
    Cambios respecto a la versión previa:
      - tolerance = min(CLUSTERING_TOLERANCE_ATR * atr14, spot * CLUSTERING_TOLERANCE_MAX_PCT)
      - Post-clustering: gate por ancho máximo. Si max(prices) - min(prices) > 
        ZONE_MAX_WIDTH_PCT * center, el cluster se descarta (no se forma zona).
      - bounds de la zona = envelope real de los elementos del cluster ± ZONE_BUFFER_PCT * center.
      - El center_price pasa a ser (lower_bound + upper_bound) / 2 (centro del envelope, 
        no media ponderada de elementos).
    """

def compute_zone_score(
    elements: list[SupportLevel],
    *,
    zone_width_pct: float,
    n_heavy_elements: int,
) -> float:
    """
    Cambios respecto a la versión previa:
      - Mantiene el cálculo base (suma de max-por-categoría) como score_base.
      - Aplica multiplicador de densidad: score_final = score_base * density_multiplier(...).
      - density_multiplier ∈ [MIN_DENSITY_MULTIPLIER, MAX_DENSITY_MULTIPLIER].
    """

def density_multiplier(n_heavy: int, width_pct: float) -> float:
    """Función pura del multiplicador. Expuesta para testabilidad."""
```

Los call sites de `compute_zone_score` (hoy en `cluster_into_zones`) reciben los nuevos kwargs derivados del envelope ya computado.

### `reports_html.py`

```python
def _format_candidate(fc: FinalCandidate) -> dict:
    """
    Cambios:
      - flags_legibles ahora SOLO incluye earnings + ex-div (no eventos macro).
      - Nuevo campo en el dict: 'currency' (string) y 'currency_display' (dict con prefix/suffix).
      - Nuevo campo: 'score_tier' (int 1-5) y 'score_tier_stars' + 'score_tier_label' (strings).
      - Nuevo campo: 'spot_formatted', 'zona_min_formatted', 'zona_max_formatted', 
        'price_target_formatted' (strings con currency aplicada).
    """

def _format_macro_events_for_banner(events: list[MacroEvent], today: date) -> list[dict]:
    """
    Nueva función. Toma los eventos macro en ventana y los formatea para el banner global.
    Returns list of dicts: {date, days_until, kind, description, jurisdiction}.
    jurisdiction se infiere del kind (fomc→US, cpi→US por default, etc).
    """

def write_html_report(
    candidates: list[FinalCandidate],
    macro_events: list[MacroEvent],  # ← nuevo argumento
    timestamp: datetime,
    output_dir: Path,
    template_path: Path | None = None,
) -> tuple[Path, Path]:
    """
    Cambios:
      - Nuevo argumento `macro_events` (lista de MacroEvent en la ventana).
      - Pasa al template el contexto del banner además del de las cards.
    """
```

### `binary_events.py`

```python
def check_binary_events(
    candidate: ...,
    today: date,
    macro_calendar: list[MacroEvent],
    *,
    earnings_window_days: int = EARNINGS_WINDOW_DAYS,
    ex_div_window_days: int = EX_DIV_WINDOW_DAYS,
    macro_window_days: int = MACRO_WINDOW_DAYS,
) -> BinaryEventsReport:
    """
    Cambios:
      - flags_legibles ahora SOLO contiene flags PER-CANDIDATO (earnings + ex-div), 
        NO eventos macro. Los macro se reportan a nivel run, no per-card.
      - El campo macro_events_in_window del report sigue existiendo y poblándose 
        (para persistencia + lectura programática), pero NO se renderiza per-card.
    """
```

### `final_pipeline.py` — call site del write_html_report

Update mínimo: pasar la lista de macro events del run al `write_html_report`.

## 6. Algoritmos

### 6.1 Clustering nuevo

```
Input: levels: list[SupportLevel] ordenados por price asc; spot; atr14.

1. tolerance = min(CLUSTERING_TOLERANCE_ATR * atr14, spot * CLUSTERING_TOLERANCE_MAX_PCT)
2. Greedy single-linkage (igual que hoy):
   clusters: list[list[SupportLevel]] = []
   for lvl in levels:
     if not clusters or lvl.price - clusters[-1][-1].price > tolerance:
       clusters.append([lvl])
     else:
       clusters[-1].append(lvl)
3. Para cada cluster:
   a. min_price = min(e.price for e in cluster)
   b. max_price = max(e.price for e in cluster)
   c. raw_width = max_price - min_price
   d. center = (min_price + max_price) / 2
   e. width_pct = raw_width / center
   f. GATE: if width_pct > ZONE_MAX_WIDTH_PCT → descartar cluster (no forma zona).
   g. Dedup por categoría: ya se hace en compute_zone_score (sin cambios).
   h. buffer = ZONE_BUFFER_PCT * center
   i. lower_bound = min_price - buffer
   j. upper_bound = max_price + buffer
   k. n_heavy = count(e in cluster where ELEMENT_WEIGHTS[e.element] >= HEAVY_ELEMENT_WEIGHT_THRESHOLD)
   l. final_width_pct = (upper_bound - lower_bound) / center
   m. score = compute_zone_score(elements=cluster, zone_width_pct=final_width_pct, n_heavy_elements=n_heavy)
   n. Construir SupportZone(...).
4. Sort por score desc, distance_pct asc (tiebreak).
```

### 6.2 Density multiplier

```python
def density_multiplier(n_heavy: int, width_pct: float) -> float:
    if n_heavy <= 0:
        return 1.0  # no debería pasar — gate de heavy elements >=2 lo evita
    
    width_floored = max(width_pct, MIN_WIDTH_FLOOR_PCT)
    density = n_heavy / width_floored
    multiplier = 1.0 + (density - REFERENCE_DENSITY) * DENSITY_BONUS_SLOPE
    return max(MIN_DENSITY_MULTIPLIER, min(multiplier, MAX_DENSITY_MULTIPLIER))
```

Ejemplos numéricos:
- 2 heavies, width 2%: density = 100. multiplier = 1.0 + (100-100)*0.005 = 1.0. Neutro.
- 4 heavies, width 2%: density = 200. multiplier = 1.0 + 0.5 = 1.5. Cap arriba.
- 2 heavies, width 4%: density = 50. multiplier = 1.0 + (-50)*0.005 = 0.75 → clip a 0.85. Floor.
- 5 heavies, width 1%: density = 500. multiplier = clip(1.0 + 2.0, 0.85, 1.5) = 1.5.

### 6.3 Score tier

```python
def score_to_tier(score: float) -> int:
    for tier in sorted(SCORE_TIER_THRESHOLDS.keys(), reverse=True):
        if score >= SCORE_TIER_THRESHOLDS[tier]:
            return tier
    return 1
```

### 6.4 Currency formatting

```python
def format_price(value: float, currency: str | None) -> str:
    """
    Formatea un precio con el símbolo monetario correcto.
    Ejemplos:
      format_price(150.23, "USD") → "$150.23"
      format_price(453.55, "GBp") → "453.55p"
      format_price(82.10, "EUR")  → "€82.10"
      format_price(42.00, None)   → "$42.00" (fallback USD)
    """
    cfg = CURRENCY_DISPLAY.get(currency, CURRENCY_DEFAULT)
    adjusted = value / cfg["divisor"]
    return f"{cfg['prefix']}{adjusted:.2f}{cfg['suffix']}"
```

`_format_candidate` la usa para `spot_formatted`, `zona_min_formatted`, etc. El template ya recibe los strings pre-formateados y solo los inserta.

### 6.5 Macro events para banner

```python
def _format_macro_events_for_banner(events: list[MacroEvent], today: date) -> list[dict]:
    """Ordenados por fecha asc. Solo eventos forward (>=today)."""
    JURISDICTION_BY_KIND = {
        "fomc": "US", "cpi": "US", "ppi": "US", "nfp": "US", "gdp": "US",
        "other": "—",
    }
    formatted = []
    for e in sorted(events, key=lambda x: x.date):
        if e.date < today:
            continue
        formatted.append({
            "date": e.date.isoformat(),
            "days_until": (e.date - today).days,
            "kind": e.kind,
            "kind_display": e.kind.upper(),
            "description": e.description,
            "jurisdiction": JURISDICTION_BY_KIND.get(e.kind, "—"),
        })
    return formatted
```

`JURISDICTION_BY_KIND` queda en `config_reports.py` como constante para mantenerla extensible (cuando agreguemos eventos EU se suman acá sin tocar la lógica).

## 7. Cambios en HTML

### 7.1 Nueva sección "macro-banner" en `report.html.j2`

Va arriba de la grilla de cards, debajo del header del run:

```html+jinja
{% if macro_events %}
<section class="macro-banner">
  <h2>Eventos macro próximos (ventana 45 días)</h2>
  <ul>
  {% for ev in macro_events %}
    <li>
      <span class="macro-date">{{ ev.date }}</span>
      <span class="macro-days">en {{ ev.days_until }} días</span>
      <span class="macro-kind macro-kind-{{ ev.kind }}">{{ ev.kind_display }}</span>
      <span class="macro-jurisdiction">{{ ev.jurisdiction }}</span>
      <span class="macro-desc">{{ ev.description }}</span>
    </li>
  {% endfor %}
  </ul>
</section>
{% endif %}
```

CSS mínimo en el `<style>` del template (mantener consistente con el resto):

```css
.macro-banner { background: #fff3cd; border: 1px solid #ffc107; padding: 12px 16px; margin: 16px 0; border-radius: 6px; }
.macro-banner h2 { font-size: 1.1em; margin: 0 0 8px 0; }
.macro-banner ul { list-style: none; padding: 0; margin: 0; }
.macro-banner li { display: flex; gap: 12px; padding: 4px 0; align-items: center; flex-wrap: wrap; }
.macro-date { font-weight: 600; }
.macro-days { color: #856404; }
.macro-kind { padding: 2px 8px; border-radius: 4px; background: #ffc107; font-size: 0.85em; font-weight: 600; }
.macro-jurisdiction { padding: 1px 6px; border-radius: 3px; background: #f0f0f0; font-size: 0.85em; }
```

### 7.2 Tier en la card

Donde hoy el template muestra `<span class="value">{{ c.score }}</span>` para SCORE, agregar arriba o al lado:

```html+jinja
<div class="tier">
  <span class="tier-stars">{{ c.score_tier_stars }}</span>
  <span class="tier-label">{{ c.score_tier_label }}</span>
</div>
<div class="score-raw">Score crudo: {{ c.score }}</div>
```

Visualmente: estrellas grandes prominentes, número crudo chico abajo.

### 7.3 Currency en spot/zona/PT

Reemplazos en el template (no se ven los precios crudos, solo los `_formatted`):

| Antes | Después |
|---|---|
| `${{ c.spot }}` | `{{ c.spot_formatted }}` |
| `[${{ c.zona_min }} - ${{ c.zona_max }}]` | `[{{ c.zona_min_formatted }} - {{ c.zona_max_formatted }}]` |
| `${{ element.price }}` | `{{ element.price_formatted }}` (cada element ya viene con su `price_formatted` desde el helper) |
| `PT: ${{ c.price_target }}` | `PT: {{ c.price_target_formatted }}` |

Y en `binary_events.py:108`:

| Antes | Después |
|---|---|
| `f"Ex-dividend en {dias} días (${ex_div_amount:.2f})"` | `f"Ex-dividend en {dias} días ({format_price(ex_div_amount, currency)})"` |

`format_price` se importa en `binary_events.py` desde un módulo compartido (ver §11) o se inyecta. La currency del candidato ya está disponible vía `candidate.profile.currency`.

## 8. Persistencia

**Sin cambios al schema.** `width_pct`, `n_heavy_elements`, `score_tier` son todos derivables al vuelo desde campos ya persistidos (`lower_bound`, `upper_bound`, `center_price`, `score`, `elements`).

Si en el futuro se vuelve necesario filtrar/ordenar por tier en SQL, se puede agregar la columna sin migración costosa. Por ahora, derivar.

## 9. Tests

### 9.1 Unit — clustering (`tests/supports/test_zone_clustering.py`)

Tests existentes (17) — varios van a romper porque el ancho de zona cambió de "ATR fijo" a "envelope real". Hay que ajustar las asserts. Por cada test que rompa, decidir:
- Si era assert sobre `lower_bound`/`upper_bound` literal: ajustar valor esperado (debería caer cerca de los precios de los elementos).
- Si era assert sobre tamaño de la zona o cantidad de clusters: revisar si el cambio rompe la intención o solo el número exacto.

Tests nuevos a agregar:
- `test_clustering_tolerance_uses_min_of_atr_and_pct`: levels con ATR grande y spot alto → tolerance dominada por el cap %.
- `test_clustering_rejects_cluster_wider_than_max_pct`: 5 levels en chain de 5% ancho → cluster descartado (cero zonas).
- `test_zone_bounds_match_element_envelope`: 3 levels a 100/101/102 → bounds = [100-buf, 102+buf], no centro±ATR.
- `test_density_multiplier_neutral_at_reference`: 2 heavies en 2% width → multiplier == 1.0.
- `test_density_multiplier_floors_at_min`: 1 heavy en 10% width → multiplier == MIN_DENSITY_MULTIPLIER.
- `test_density_multiplier_caps_at_max`: 6 heavies en 0.5% width → multiplier == MAX_DENSITY_MULTIPLIER.
- `test_compute_zone_score_applies_density_bonus`: zona compacta saca score > base.
- `test_compute_zone_score_applies_density_penalty`: zona ancha saca score < base (clip a min).

### 9.2 Unit — scoring (`tests/supports/test_support_scoring.py`)

Los 13 tests existentes deberían sobrevivir intactos en su mayoría (operan sobre gates que no cambian). Revisar uno por uno; ajustar solo si el nuevo cómputo del score cambia el valor esperado en algún test específico.

### 9.3 Unit — reports

- `tests/test_reports_html.py` (si existe) o nuevo: 
  - `test_format_price_usd`, `test_format_price_gbp_pence`, `test_format_price_eur`, `test_format_price_chf`, `test_format_price_none_fallback`.
  - `test_format_macro_events_for_banner_sorts_by_date`, `test_format_macro_events_for_banner_excludes_past`, `test_format_macro_events_for_banner_includes_jurisdiction`.
  - `test_format_candidate_includes_currency_formatted_fields`, `test_format_candidate_excludes_macro_from_flags_legibles`.

### 9.4 Unit — binary events

- `test_check_binary_events_flags_legibles_no_macro`: aunque haya FOMC en ventana, `flags_legibles` solo trae earnings/ex-div.
- `test_check_binary_events_macro_events_in_window_still_populated`: el campo del report sigue poblándose para consumo programático/persistencia.

### 9.5 Smoke test manual

Tras implementar:
1. `python -m puts_screener.run --universe sp500 --limit 50`
2. Abrir `output/screening_latest.html` y verificar:
   - Banner macro arriba con FOMC + CPI (no en cada card).
   - Cards con tier (estrellas + label) visible.
   - Símbolos monetarios correctos (US con `$`, EU con `€`, UK `.L` con `p`).
   - Zonas más angostas que antes.

### 9.6 Calibración empírica (paso obligatorio antes de cerrar la spec)

Tras los pasos 9.1-9.5:
1. Correr `python -m puts_screener.run --universe sp500,nasdaq100,stoxx600` (run completo, ~15 min con cache caliente).
2. Query SQL al run nuevo: distribución de `score`, `width_pct`, `n_heavy_elements`, `score_tier` de las zonas válidas.
3. Mirar la distribución y decidir:
   - ¿Hay candidatos? Si quedan 0, las constantes están demasiado estrictas — bajar `ZONE_MAX_WIDTH_PCT` o subir `MAX_DENSITY_MULTIPLIER`.
   - ¿Cuántos quedan en cada tier? Si todos son tier 1-2, bajar los thresholds. Si todos son tier 5, subirlos.
4. Ajustar las constantes provisionales (§3.2 y §3.3) y re-correr una vez más.
5. Tras la calibración final, actualizar los valores en la spec y en el código.

## 10. Criterios de aceptación

- [ ] `zone_clustering.py` refactorizado: tolerance híbrida, gate por ancho máximo, bounds = envelope.
- [ ] `compute_zone_score` con multiplicador de densidad aplicado.
- [ ] `density_multiplier` función pura testeada con 4+ casos.
- [ ] `SupportZone` con properties `width`, `width_pct`, `n_heavy_elements`, `score_tier`.
- [ ] `config_supports.py` con las constantes nuevas. `config_reports.py` con `CURRENCY_DISPLAY`, `CURRENCY_DEFAULT`, `SCORE_TIER_LABELS`, `JURISDICTION_BY_KIND`.
- [ ] `_format_candidate` ya no incluye macro events en `flags_legibles`. Incluye campos `_formatted` con currency aplicada.
- [ ] `write_html_report` recibe y propaga `macro_events`.
- [ ] `report.html.j2` con banner macro arriba, tier visible en cards, símbolos dinámicos.
- [ ] Tests viejos ajustados; tests nuevos pasan.
- [ ] Smoke test manual: HTML renderiza correctamente con BARC.L mostrando `p` (no `$`), banner macro sin duplicación en cards, tier estrellas visible.
- [ ] Calibración empírica completada y constantes ajustadas en código.
- [ ] Suite total verde (>= 383 + nuevos tests).
- [ ] Spec actualizada con los valores definitivos de constantes post-calibración.

## 11. Archivos a crear / modificar

```
puts-screener/
├── specs/
│   └── 06_clustering_tier_macro_currency.md     [NEW — esta spec]
├── src/puts_screener/
│   ├── config_supports.py                       [MOD: agregar constantes §3.1, §3.2, §3.3]
│   ├── config_reports.py                        [MOD: agregar SCORE_TIER_LABELS, CURRENCY_DISPLAY, JURISDICTION_BY_KIND]
│   ├── models_support.py                        [MOD: agregar properties a SupportZone]
│   ├── zone_clustering.py                       [MOD: refactor clustering + score con density bonus]
│   ├── binary_events.py                         [MOD: sacar macro de flags_legibles]
│   ├── reports_html.py                          [MOD: _format_candidate + write_html_report + helpers]
│   ├── formatting.py                            [NEW: format_price helper compartido]
│   └── templates/
│       └── report.html.j2                       [MOD: banner macro + tier + currency display]
└── tests/
    ├── supports/
    │   ├── test_zone_clustering.py              [MOD: ajustar asserts + nuevos tests]
    │   └── test_support_scoring.py              [MOD: revisar si requiere ajuste]
    ├── test_reports_html.py                     [NEW o MOD si existe]
    └── test_binary_events.py                    [MOD: tests nuevos para flags_legibles sin macro]
```

1 archivo nuevo en src (`formatting.py`), 1 archivo nuevo en tests (si no existe `test_reports_html.py`), 1 spec nueva. Resto modificaciones.

`formatting.py` se justifica porque `format_price` lo usan `reports_html.py` Y `binary_events.py` — evitar circular import. Si ya hay un módulo "utils" o "helpers" en el proyecto, va ahí en vez de crear uno nuevo (Claude Code lo decide tras ver el código).

## 12. Decisiones registradas

- **2026-05-27 — Spec 06, clustering con tolerance híbrida ATR/% spot**: `tolerance = min(0.4*ATR14, 0.01*spot)`. Resuelve el caso de stocks con ATR alto + spot alto donde el ATR puro daba clusters demasiado anchos. Para small caps el ATR sigue dominando.
- **2026-05-27 — Spec 06, gate post-clustering por ancho máximo absoluto**: `ZONE_MAX_WIDTH_PCT=0.04`. Si el envelope del cluster excede 4% del center, se descarta. Evita que el single-linkage greedy forme "zonas" anchas por chaining.
- **2026-05-27 — Spec 06, bounds de zona = envelope real**: reemplaza el `center ± ATR/2` fijo. La banda mostrada al usuario refleja dónde están realmente los elementos del cluster. `distance_pct` ahora se computa contra `upper_bound` real, no contra `center_price`.
- **2026-05-27 — Spec 06, density multiplier sobre score base**: el score crudo (suma max-por-categoría) se multiplica por un factor `[0.85, 1.5]` dependiente de heavies/ancho. Premia zonas compactas con muchos heavies, penaliza zonas anchas con pocos.
- **2026-05-27 — Spec 06, score tier 1-5 derivado del score final**: capa de presentación sobre el score crudo. Tier 5 = ≥18.0 (excepcional con bonus), tier 1 = ≥5.0 (mínimo viable). Thresholds provisionales, recalibrar post-validación.
- **2026-05-27 — Spec 06, macro events factorizados a banner global**: hoy se duplicaban en `flags_legibles` de cada card. Pasan a sección dedicada arriba del HTML, único listado por run. Per-card solo quedan flags ticker-específicos (earnings + ex-div).
- **2026-05-27 — Spec 06, currency display dinámico vía `currency` del modelo**: el modelo `CompanyProfile` ya capturaba `currency` desde yfinance pero `_format_candidate` lo descartaba. Spec 06 lo propaga al template vía strings pre-formateados (`spot_formatted`, etc) usando un helper `format_price` compartido.
- **2026-05-27 — Spec 06, GBp se muestra como sufijo `p` (peniques) sin conversión a libras**: yfinance retorna magnitudes en peniques para LSE; convertir a libras requeriría dividir todos los valores numéricos (incluyendo zonas y targets) y eso toca otros lugares. Más simple y menos error-prone: dejar la magnitud tal cual y agregar el sufijo "p". El usuario UK sabe interpretarlo. Reversible bumpeando `GBp.divisor` a 100 si en el futuro queremos libras.
- **2026-05-27 — Spec 06, jurisdicción inferida del kind del evento macro**: simple mapeo `kind → jurisdiction` en constante. Hoy todos los eventos son US, pero la estructura queda lista para sumar eventos EU/UK sin refactorizar.
- **2026-05-27 — Spec 06, calibración empírica como paso obligatorio antes de cerrar**: las constantes de densidad y tier thresholds son provisionales. Spec 06 no cierra hasta haber corrido el screener post-implementación, mirado la distribución empírica, y ajustado los valores. Sin esto, los thresholds son adivinanzas.
- **2026-05-27 — Spec 06, sin cambios al schema SQLite**: `width_pct`, `n_heavy_elements`, `score_tier` se derivan al vuelo. Evita migración. Si en el futuro hace falta filtrar por tier en SQL, se agrega columna sin costo significativo.
- **2026-05-27 — Spec 06, rediseño UX visual completo deferido a spec 07**: la spec 06 cubre lógica + display mínimo (currency, tier, banner). El rediseño completo de la card (más grande, info reorganizada, mini-chart inline, strikes sugeridos) va en spec 07 — alcance separado, iteración visual propia.
