# Spec 04 — Reportes (CSV + HTML) y Eventos Binarios (Paso 3 del SOP)

> Implementación del Paso 3 del SOP (check de eventos binarios: earnings forward, ex-dividend, macro, M&A) y de la capa de reportes (CSV detallado + HTML estático con cards). Cierra Fase 1 del proyecto: a partir de acá tenemos screening completo end-to-end con output revisable por humano.

## 1. Objetivo

Dos cosas que viajan juntas:

1. Detectar eventos binarios en la ventana de 30-45 DTE para cada candidato que pasó el Paso 2, y reportarlos con flags visibles (no filtrar silenciosamente).
2. Generar dos outputs por corrida: un CSV detallado con una fila por candidato y un HTML estático con cards rankeadas para revisión rápida.

## 2. Scope

### En scope

- Detección de eventos binarios forward-looking (earnings, ex-dividend, macro hardcoded, M&A omitido por imposibilidad de data confiable).
- Calendario macro 2026 en archivo `data/macro_calendar.yaml`, mantenido manualmente.
- Modelo `FinalCandidate` que envuelve `SupportedCandidate` + `BinaryEventsReport`.
- Generación de CSV por corrida con todas las columnas necesarias para revisión humana.
- Generación de HTML estático con cards rankeadas por tipo + score + distancia.
- Persistencia: extensión de la tabla `candidates` con columnas de eventos binarios.
- Integración en `run.py`: Paso 1 → Paso 2 → Paso 3 → reportes.

### Fuera de scope

- M&A / spin-off / split detection (yfinance no provee data confiable).
- Mini-charts en el HTML (planificado, omitido en MVP).
- Filtros interactivos en HTML (postergado a Fase 2/3).
- Publicación a GitHub Pages (Fase 3).
- Notificación Telegram (Fase 2).

### Decisión fundamental: flag, no filter

El SOP dice "cancelar la operación" si hay earnings en ventana. El screener NO cancela — flagea. Razones:

- El screener es para revisión humana, no para ejecución directa.
- Filtrar silenciosamente esconde información que el humano necesita.
- El filtro duro se aplica cuando se automatize ejecución (fase futura), no en el screener.

Aplica a TODOS los eventos binarios. El humano que mira el reporte decide.

## 3. Decisiones de parametrización

Constantes en `src/puts_screener/config_reports.py`.

| Constante | Valor | Justificación |
|---|---|---|
| **Ventanas de eventos** | | |
| `EVENTS_WINDOW_DAYS` | `45` | Ventana del SOP Paso 3 (30-45 DTE). |
| `EARNINGS_WINDOW_DAYS` | `45` | Earnings dentro de 45 días forward. |
| `EX_DIV_WINDOW_DAYS` | `45` | Ex-dividend dentro de 45 días forward. |
| `MACRO_WINDOW_DAYS` | `45` | Macro events dentro de 45 días forward. |
| **Reportes** | | |
| `REPORT_OUTPUT_DIR` | `Path("output")` | Directorio para CSVs y HTMLs. Se crea si no existe. |
| `REPORT_FILENAME_PATTERN` | `"screening_{date}_{time}"` | Sufijo timestamp evita sobrescritura. |
| `REPORT_LATEST_FILENAME` | `"screening_latest"` | Copia de la última corrida para acceso rápido. |
| **Card en HTML** | | |
| `HTML_MAX_ELEMENTS_PER_CARD` | `8` | Si una zona tiene más de 8 elementos, mostrar top 8 por puntos y "+N más". |
| **Orden de cards** | | |
| `TYPE_PRIORITY` | `{"T1":1,"T2":2,"T4":3,"T3":4,"T5":5}` | Ordenamiento del SOP §0. |

## 4. Calendario macro

### 4.1 Archivo

Path: `data/macro_calendar.yaml` (commiteable; se mantiene manual).

Estructura:

```yaml
# Calendario macro 2026 — fechas conocidas relevantes para el SOP Paso 3.
# Mantenido manualmente. Actualizar cada noviembre para el año siguiente.
# Fuentes oficiales: FOMC calendar (federalreserve.gov), BLS economic releases calendar.

events:
  - date: 2026-01-28
    kind: fomc
    description: "FOMC Statement and Press Conference"
  - date: 2026-02-11
    kind: cpi
    description: "CPI release (January 2026 data)"
  # ... etc
```

### 4.2 API

```python
@dataclass(frozen=True)
class MacroEvent:
    date: date
    kind: Literal["fomc", "cpi", "ppi", "nfp", "gdp", "other"]
    description: str

def load_macro_calendar(path: Path = Path("data/macro_calendar.yaml")) -> list[MacroEvent]:
    """Carga el calendario macro. Si el archivo no existe o está vacío, devuelve [].
    
    El caller decide si la falta de calendario es problema (e.g. logger warning).
    """
```

### 4.3 Mantenimiento

El archivo es commiteable. Crear initial con fechas reales de 2026 (FOMC, CPI, principales) — instrucción para el implementador: buscar fechas en federalreserve.gov y bls.gov antes de poblar el archivo. Si el archivo se crea vacío inicialmente, el resto del pipeline funciona pero `eventos_macro_en_ventana` siempre será False — se anota como TODO de mantenimiento.

## 5. Paso 3 — Eventos binarios

Módulo `src/puts_screener/binary_events.py`.

### 5.1 Modelo

```python
@dataclass(frozen=True)
class BinaryEventsReport:
    # Earnings
    earnings_date: date | None
    dias_a_earnings: int | None
    earnings_en_45d: bool
    
    # Ex-dividend
    ex_div_date: date | None
    dias_a_ex_div: int | None
    ex_div_en_45d: bool
    ex_div_amount: float | None
    
    # Macro
    eventos_macro: list[MacroEvent]  # eventos dentro de la ventana
    eventos_macro_en_45d: bool
    
    # Resumen
    tiene_eventos_binarios: bool  # True si cualquiera de los flags duros está activo
    flags_legibles: list[str]  # ["Earnings en 12 días (2026-06-02)", "Ex-div en 8 días ($0.50)", ...]
```

### 5.2 Detección de cada evento

#### 5.2.1 Earnings forward

Usa `data_service.get_upcoming_earnings(ticker, lookforward_days=EARNINGS_WINDOW_DAYS)`. Si devuelve un `EarningsEvent`:

- `earnings_date = event.date`
- `dias_a_earnings = (event.date - today).days`
- `earnings_en_45d = 0 <= dias_a_earnings <= EARNINGS_WINDOW_DAYS`

Si devuelve `None`: los tres campos quedan en `None` / `False`.

#### 5.2.2 Ex-dividend

Usar `yfinance.Ticker(ticker).calendar.get("Ex-Dividend Date")` o equivalente. Implementación específica vive en `YFinanceProvider.get_upcoming_ex_dividend(ticker, lookforward_days)` que devuelve:

```python
@dataclass(frozen=True)
class ExDividendEvent:
    ticker: str
    date: date
    amount: float | None  # USD por share, puede no estar disponible
```

Si yfinance no devuelve fecha o devuelve fecha pasada, devolver `None`. La interfaz `DataProvider` se extiende con `get_upcoming_ex_dividend` (default raise NotSupportedError).

#### 5.2.3 Macro

```python
def check_macro_events(
    today: date,
    calendar: list[MacroEvent],
    window_days: int = MACRO_WINDOW_DAYS,
) -> list[MacroEvent]:
    """Devuelve eventos del calendario dentro de [today, today + window_days]."""
    return [e for e in calendar if today <= e.date <= today + timedelta(days=window_days)]
```

#### 5.2.4 M&A — omitido

No implementar en MVP. Anotar como issue futuro en ROADMAP §4 al cerrar la spec.

### 5.3 Función principal

```python
def check_binary_events(
    ticker: str,
    today: date,
    data_service: DataService,
    macro_calendar: list[MacroEvent],
) -> BinaryEventsReport:
    """Chequea todos los eventos binarios para el ticker.
    
    Errores aislados: si get_upcoming_earnings falla, ese campo queda en None.
    No se propaga al resto del análisis.
    """
```

### 5.4 Flags legibles

`flags_legibles` se construye con strings cortos en español, en orden de severidad:

- "Earnings en N días (YYYY-MM-DD)"
- "Ex-dividend en N días ($X.XX)" si amount disponible, sino "Ex-dividend en N días"
- "Evento macro: KIND en N días (DESCRIPTION)" — uno por evento macro

`tiene_eventos_binarios = earnings_en_45d or ex_div_en_45d or eventos_macro_en_45d`.

## 6. Modelo `FinalCandidate`

`src/puts_screener/models_final.py`:

```python
@dataclass
class FinalCandidate:
    supported: SupportedCandidate  # incluye screened + analysis del Paso 2
    binary_events: BinaryEventsReport
    fetched_at: datetime
    errors: list[str]  # errores del Paso 3, no fatales
    
    @property
    def ticker(self) -> str:
        return self.supported.screened.ticker
    
    @property
    def passes_all_steps(self) -> bool:
        """True si pasó Paso 1 Y Paso 2. El Paso 3 NO filtra (decisión §2)."""
        return self.supported.pasa_paso_2
```

Composición sobre herencia, espeja `SupportedCandidate`.

## 7. Generación de CSV

Módulo `src/puts_screener/reports_csv.py`.

### 7.1 Columnas

Una fila por candidato que pasó Paso 1 + Paso 2. Orden exacto:

1. `ticker`
2. `exchange`
3. `sector`
4. `country`
5. `market_cap`
6. `tipo_T`
7. `justificacion_tipo`
8. `spot`
9. `zona_min`
10. `zona_max`
11. `zona_centro`
12. `distancia_pct`
13. `score_soporte`
14. `n_elementos`
15. `elementos_score` (lista textual: "EMA200D | AVWAP_earnings | FIB_618 | HVN | POLARIDAD")
16. `confirmador_dinamico` (bool)
17. `rsi_diario`
18. `rsi_semanal`
19. `macd_estado`
20. `momentum_score`
21. `sma50w_sobre_sma200w` (bool)
22. `hv_percentile_52w`
23. `price_target_consensus`
24. `price_target_upside_pct`
25. `recommendation_mean`
26. `recommendation_buy_ratio`
27. `downgrades_6w`
28. `earnings_date`
29. `dias_a_earnings`
30. `earnings_en_45d`
31. `ex_div_date`
32. `dias_a_ex_div`
33. `ex_div_en_45d`
34. `ex_div_amount`
35. `eventos_macro_en_45d`
36. `eventos_macro_count`
37. `tiene_eventos_binarios`
38. `flags_legibles` (lista textual separada por " | ")
39. `fetched_at`

### 7.2 API

```python
def write_csv_report(
    final_candidates: list[FinalCandidate],
    output_dir: Path = REPORT_OUTPUT_DIR,
    timestamp: datetime | None = None,
) -> Path:
    """Escribe el CSV de la corrida. Devuelve el path del archivo escrito.
    
    Genera dos archivos:
    1. screening_YYYY-MM-DD_HHMM.csv (timestamped, no se sobrescribe)
    2. screening_latest.csv (copia/overwrite del más reciente)
    """
```

Solo candidatos con `passes_all_steps=True` se incluyen. Los rechazados quedan en SQLite, no en el CSV.

### 7.3 Ordenamiento

Mismo que el HTML (§8.3): por prioridad de tipo asc, score desc, distance_pct asc.

## 8. Generación de HTML

Módulo `src/puts_screener/reports_html.py`.

### 8.1 Stack

- Jinja2 para templating.
- Template HTML en `src/puts_screener/templates/report.html.j2`.
- CSS embebido en el template (no archivos separados — un solo HTML autocontenido).

### 8.2 Estructura del template

```html
<!DOCTYPE html>
<html>
<head>
  <title>Screening {{ run_date }}</title>
  <style>/* CSS embebido aquí */</style>
</head>
<body>
  <header>
    <h1>Screening {{ run_date }}</h1>
    <p>Universo: {{ universe_size }} · Pasan Paso 1: {{ n_paso_1 }} · Pasan Paso 2: {{ n_paso_2 }}</p>
  </header>
  <main>
    {% for candidate in candidates %}
      <article class="card {{ candidate.tipo_T_lower }}">
        ... (estructura de §8.4)
      </article>
    {% endfor %}
  </main>
  <footer>
    Generado: {{ generated_at }} · puts-screener v{{ version }}
  </footer>
</body>
</html>
```

### 8.3 Ordenamiento de cards

Mismo que el CSV:
1. Prioridad de tipo asc (T1 primero, luego T2, T4, T3).
2. Score desc.
3. Distance_pct asc.

### 8.4 Contenido de cada card

```html
<article class="card t1">
  <header>
    <strong class="ticker">{{ ticker }}</strong>
    <span class="sector">{{ sector }}</span>
    <span class="exchange">{{ exchange }}</span>
    <span class="badge type-{{ tipo_T_lower }}">{{ tipo_T }}</span>
  </header>
  
  <section class="zone">
    <div class="metric">
      <span class="label">Spot</span>
      <span class="value">${{ spot }}</span>
    </div>
    <div class="metric">
      <span class="label">Zona</span>
      <span class="value">[${{ zona_min }} - ${{ zona_max }}]</span>
    </div>
    <div class="metric">
      <span class="label">Score</span>
      <span class="value score-{{ score }}">{{ score }}</span>
    </div>
    <div class="metric">
      <span class="label">Distancia</span>
      <span class="value">{{ distancia_pct }}%</span>
    </div>
  </section>
  
  <section class="elements">
    <h4>Elementos ({{ n_elementos }})</h4>
    <ul>
      {% for element in elements[:8] %}
        <li>{{ element.label }} @ ${{ element.price }}</li>
      {% endfor %}
      {% if n_elementos > 8 %}
        <li class="more">+{{ n_elementos - 8 }} más</li>
      {% endif %}
    </ul>
  </section>
  
  <section class="indicators">
    <div>RSI_d: {{ rsi_d }} · RSI_w: {{ rsi_w }} · MACD: {{ macd_estado }} · Momentum: {{ momentum_score }}</div>
    <div>PT: ${{ price_target }} ({{ pt_upside_pct }}%) · Buy: {{ buy_ratio }}% · Downgrades: {{ downgrades }}</div>
  </section>
  
  {% if flags_legibles %}
  <section class="flags warning">
    <h4>⚠ Flags</h4>
    <ul>
      {% for flag in flags_legibles %}
        <li>{{ flag }}</li>
      {% endfor %}
    </ul>
  </section>
  {% endif %}
</article>
```

### 8.5 Estilo CSS

Diseño limpio, legible, no decorativo:
- Tema claro por default (dark mode opcional con `prefers-color-scheme`).
- Cards con borde sutil, padding generoso.
- Badge de tipo coloreado: T1 verde, T2 naranja, T3 gris, T4 azul, T5 violeta.
- Sección de flags con fondo amarillo claro y borde naranja para que llame la atención.
- Tipografía: system fonts (no Google Fonts, simplicidad).

Diseño responsivo (mobile-first no es necesario, pero que no se rompa en pantallas chicas).

### 8.6 API

```python
def write_html_report(
    final_candidates: list[FinalCandidate],
    run_metadata: dict,  # run_id, universe_size, n_paso_1, n_paso_2, etc.
    output_dir: Path = REPORT_OUTPUT_DIR,
    timestamp: datetime | None = None,
) -> Path:
    """Genera el HTML report. Devuelve el path del archivo escrito.
    
    Genera dos archivos:
    1. screening_YYYY-MM-DD_HHMM.html
    2. screening_latest.html
    """
```

## 9. Pipeline orquestador

Módulo `src/puts_screener/final_pipeline.py` (o extender `run.py` directamente):

```python
def run_final_pipeline(
    universe: list[str],
    data_service: DataService,
    persist: bool = True,
    generate_reports: bool = True,
    max_workers: int = 8,
) -> tuple[str, list[FinalCandidate]]:
    """Pipeline completo Paso 1 → Paso 2 → Paso 3 → reportes.
    
    1. run_screening (Paso 1)
    2. run_support_detection (Paso 2)
    3. Para cada SupportedCandidate con pasa_paso_2=True: check_binary_events
    4. Si generate_reports=True: write_csv_report + write_html_report
    5. Si persist=True: save_binary_events_columns
    """
```

`run.py` se actualiza para llamar a `run_final_pipeline` por default.

### 9.1 Nuevos flags CLI

- `--skip-reports`: no genera CSV ni HTML.
- `--skip-binary-events`: no corre Paso 3 (útil para debug).
- `--macro-calendar PATH`: override del path del calendario macro.

Los existentes (`--limit N`, `--no-persist`, `--skip-support-detection`) se mantienen.

## 10. Persistencia

### 10.1 Extensión de tabla `candidates`

Migración idempotente (chequeo con `PRAGMA table_info` antes del `ALTER TABLE`):

```sql
ALTER TABLE candidates ADD COLUMN earnings_date TEXT;        -- ISO YYYY-MM-DD or NULL
ALTER TABLE candidates ADD COLUMN dias_a_earnings INTEGER;
ALTER TABLE candidates ADD COLUMN earnings_en_45d INTEGER;   -- 0/1
ALTER TABLE candidates ADD COLUMN ex_div_date TEXT;
ALTER TABLE candidates ADD COLUMN dias_a_ex_div INTEGER;
ALTER TABLE candidates ADD COLUMN ex_div_en_45d INTEGER;
ALTER TABLE candidates ADD COLUMN ex_div_amount REAL;
ALTER TABLE candidates ADD COLUMN eventos_macro_en_45d INTEGER;
ALTER TABLE candidates ADD COLUMN eventos_macro_json TEXT;   -- JSON array
ALTER TABLE candidates ADD COLUMN tiene_eventos_binarios INTEGER;
ALTER TABLE candidates ADD COLUMN flags_legibles_json TEXT;
```

### 10.2 API

```python
def save_binary_events(
    run_id: str,
    final_candidates: list[FinalCandidate],
) -> None:
    """Actualiza las columnas de eventos binarios para los tickers procesados."""
```

## 11. Tests

### 11.1 Unitarios

**`test_binary_events.py`**:
- Earnings dentro de 45 días → flag True, dias_a_earnings correcto.
- Earnings fuera de 45 días → flag False, dias_a_earnings calculado.
- Sin earnings → todos los campos None.
- Ex-dividend con amount → flag True, amount correcto.
- Ex-dividend sin amount (yfinance no lo devuelve) → flag True, amount None.
- Macro events: dado un calendario fixture y today, devuelve solo los eventos en ventana.
- `flags_legibles` construye strings correctos en orden de severidad.

**`test_macro_calendar.py`**:
- Carga de YAML válido → lista de MacroEvent.
- Archivo vacío → lista vacía.
- Archivo no existe → lista vacía sin error.
- YAML malformado → raise apropiado.

**`test_reports_csv.py`**:
- Genera CSV con header correcto y filas correctas dados fixtures.
- Genera ambos archivos (timestamped + latest).
- Manejo de campos None: representados como string vacío, no "None".
- Ordenamiento correcto por tipo + score + distancia.

**`test_reports_html.py`**:
- Genera HTML válido (parseable con BeautifulSoup) dados fixtures.
- Contiene todos los tickers esperados.
- Sección de flags aparece solo si hay flags.
- Cards ordenadas correctamente.

**`test_persistence_binary_events.py`**:
- Round-trip de columnas nuevas en `candidates`.
- Migración idempotente: correr `save_binary_events` dos veces no rompe.

### 11.2 Integración

**`test_final_pipeline.py`**:
- 3 candidatos fixture con diferentes situaciones de eventos binarios.
- Pipeline completo corre, genera CSV + HTML + persiste.
- Smoke test: archivos generados existen y son no-vacíos.

### 11.3 Smoke test manual

`src/puts_screener/smoke_test_final.py`:
- 10 tickers hardcoded.
- Pipeline completo con persistencia y reportes.
- Imprime path de los archivos generados para inspección visual.

## 12. Criterios de aceptación

- [ ] `data/macro_calendar.yaml` creado con fechas reales 2026 (FOMC + CPI mínimo).
- [ ] `check_binary_events` retorna `BinaryEventsReport` correcto para los 3 tipos de eventos.
- [ ] CSV generado tiene 39 columnas en orden exacto.
- [ ] HTML generado se ve correctamente en Chrome/Firefox/Safari.
- [ ] Migración idempotente de tabla `candidates` con 11 columnas nuevas.
- [ ] `python -m puts_screener.run --limit 20` corre pipeline completo sin error.
- [ ] Smoke test corre limpio en <2 min para 10 tickers.
- [ ] `pytest -v` con todos los tests verdes.
- [ ] `ruff check src/ tests/` y `ruff format --check` limpios.

## 13. Archivos a crear/modificar

```
src/puts_screener/
├── binary_events.py            # nuevo
├── reports_csv.py              # nuevo
├── reports_html.py             # nuevo
├── models_final.py             # nuevo
├── final_pipeline.py           # nuevo (o extender run.py)
├── config_reports.py           # nuevo
├── templates/
│   └── report.html.j2          # nuevo
├── smoke_test_final.py         # nuevo
├── persistence.py              # modificar (columnas nuevas, save_binary_events)
└── run.py                      # modificar (llama a final_pipeline)

src/puts_screener/providers/
├── base.py                     # modificar (agregar get_upcoming_ex_dividend abstracto)
└── yfinance_provider.py        # modificar (implementar get_upcoming_ex_dividend)

data/
└── macro_calendar.yaml         # nuevo (commiteable, mantenido manual)

tests/
└── final/
    ├── __init__.py
    ├── test_binary_events.py
    ├── test_macro_calendar.py
    ├── test_reports_csv.py
    ├── test_reports_html.py
    ├── test_persistence_binary_events.py
    └── test_final_pipeline.py
```

Dependencias nuevas: `jinja2`, `pyyaml`. Agregar a `requirements.txt`.

## 14. Decisiones registradas

- **Flag, no filter**: el screener no cancela candidatos con eventos binarios. Solo flagea. La cancelación dura se aplicará cuando se automatize ejecución (Fase 4+).
- **Calendario macro hardcoded**: no hay endpoint confiable en yfinance ni en finnhub free para fechas macro. Calendario manual en YAML, mantenido anualmente. Trade-off conocido: si el archivo está desactualizado, los eventos macro no se detectan.
- **M&A omitido**: yfinance no provee data confiable. Issue para spec futura.
- **Una fila por candidato en CSV**: la mejor zona se reporta; las zonas adicionales viven en SQLite para análisis posterior. CSV es resumen ejecutivo, no dump completo.
- **Sin mini-charts en HTML MVP**: complejidad alta, valor marginal (el humano tiene TradingView abierto). Postergado.
- **Sin interactividad en HTML**: HTML estático puro. Filtros/ordenamiento se hacen pre-generación. JS solo si aparece demanda real.
- **`FinalCandidate` por composición**: mismo patrón que `SupportedCandidate` → `ScreenedCandidate`. Pirámide de capas.
- **Eventos binarios persistidos en `candidates`, no tabla nueva**: relación 1:1 con candidato, no justifica tabla separada. Columnas nuevas con migración idempotente.
- **Timestamps en filenames**: `screening_YYYY-MM-DD_HHMM` evita sobrescritura. `screening_latest` se actualiza con la última corrida para acceso rápido.
- **Top N omitido — todos los que pasen se muestran**: SPEC.md original decía "top 20", pero la validación de 200 mostró que típicamente pasan 10-30 candidatos. Mostrar todos.
- **Ordenamiento por tipo + score + distancia**: prioridad del SOP §0. T1 primero, luego T2, T4, T3 (T5 sería último pero está omitido del screener).
