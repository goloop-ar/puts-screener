# ROADMAP — puts-screener

> Documento vivo: estado actual, issues abiertos, próximos pasos. Actualizar al cierre de cada sesión.

**Última actualización**: 2026-05-27

---

## 1. Estado actual

### Capa de Data Providers (spec 01) ✅ Cerrada

- [x] Interfaz abstracta `DataProvider` + dataclasses tipadas
- [x] Tres providers concretos: `StooqProvider`, `YFinanceProvider`, `FinnhubProvider`
- [x] Orquestador `DataService` con fallback por método
- [x] Cache local en disco con TTL (parquet + JSON)
- [x] Rate limiting para Finnhub
- [x] Normalización de tickers para US + 14 exchanges EU
- [x] Extensión retroactiva: `get_historical_earnings` (necesario para T4) + `OHLCV_ROLLING_DAYS=1500`
- [x] Smoke test contra APIs reales: 4 tickers, todos OK
- [x] Stack final: yfinance primario, Finnhub fallback opcional para US, Stooq fuera del default

### Universe Builder + Filtros Paso 1 (spec 02) ✅ Cerrada

- [x] **Tanda 1**: `config_filters` (24 constantes), `models_screening` (2 dataclasses), `universe_builder` (985 tickers reales), `indicators` (RSI/MACD/ATR/SMA/HV en numpy puro, sin pandas_ta)
- [x] **Tanda 2**: `classification` (T1-T4 con prioridad T1>T2>T4>T3, matches múltiples), `filters_step1` (4 filtros + momentum_score 0-3)
- [x] **Tanda 3**: `screening_pipeline` (paralelo 8 workers), `persistence` (SQLite), `run.py` (entry point), `smoke_test_screening`
- [x] Fix de dependencia: `lxml` agregado para `get_historical_earnings`
- [x] Smoke test del pipeline: 7 tickers en 15s, MSFT pasó filtros

### Refinamientos post-spec 02 ✅

- [x] Exención de FCF para sectores capital-intensivos (Utilities, Financial Services, Real Estate). Issue 2.1 cerrado.
- [x] Gate de clasificación T1-T4 al final de `apply_step1_filters` (alinea con spec 02 §1). Issue 2.4 cerrado.
- [x] Techo HV elevado de 80 a 90 con nota de reversión cuando se integre IV real. Issue 2.2 cerrado.

### Spec 03 — Detección de soportes y scoring (Paso 2) ✅ Cerrada

- [x] **Tanda 1**: módulo de constantes (`config_supports`), 4 dataclasses (`SupportLevel`, `SupportZone`, `SupportAnalysis`, `SupportedCandidate`), detección de pivots con filtro de profundidad por ATR.
- [x] **Tanda 2**: 7 elementos del score (SMA200, polaridad, fibs, AVWAP triple anclaje, HVN aproximado, gap, divergencia) + clustering por proximidad con dedup por categoría.
- [x] **Tanda 3**: validación y ranking de zonas, pipeline paralelo, persistencia con tabla `support_zones` + migración idempotente de `candidates.pasa_paso_2`, integración en `run.py`, smoke test.
- [x] **Cleanup intermedio**: ventanas de lookback unificadas a días hábiles (helper `_date_cutoff`), constante 52w movida a `config_supports`, fix de `has_dynamic_confirmer` para sub-variantes de AVWAP.
- [x] **Validación empírica**: run `--limit 200` sin persistir → 33 pasan Paso 1, 23 pasan Paso 2 (69.7%), 7 con score ≥ 6. Persistencia real con dos runs consecutivos verificada (migración idempotente funciona).

### Spec 04 — Reportes (CSV + HTML) + Eventos binarios (Paso 3) ✅ Cerrada

- [x] **Tanda 1**: `config_reports`, `MacroEvent` + `load_macro_calendar` (YAML parsing), `BinaryEventsReport` + `check_binary_events` con earnings y macro funcionales (ex-div stubbed).
- [x] **Tanda 2**: extensión retroactiva de `DataProvider` con `get_upcoming_ex_dividend` implementado en `YFinanceProvider`, integración real en `check_binary_events`, modelo `FinalCandidate`.
- [x] **Tanda 3a**: reportes CSV (39 columnas) + HTML estático con cards coloreadas por tipo (template Jinja2 + writer).
- [x] **Tanda 3b**: `final_pipeline` encadenando Paso 1 → 2 → 3 + reportes, persistencia con 11 columnas nuevas en `candidates` + migración idempotente generalizada, integración en `run.py` con flags `--skip-reports` y `--macro-calendar`, smoke test.
- [x] **Calendario macro 2026** poblado con 20 eventos verificados (8 FOMC + 12 CPI) desde federalreserve.gov y bls.gov.
- [x] **Validación funcional con yfinance vivo**: ex-dividend real detectado (JNJ $1.30, JPM $1.50, KO $0.53), reportes generados correctamente, persistencia idempotente verificada (37 columnas en `candidates`, sin duplicación).

### Fase 1 — MVP local ✅ COMPLETA

Pipeline end-to-end funcional: universe builder (985 tickers US+EU) → filtros del Paso 1 (calidad, valoración, momentum, HV) → clasificación T1-T4 → detección de soportes con confluencia de 7 elementos → eventos binarios (earnings, ex-dividend, macro) → reportes CSV+HTML + persistencia SQLite. Punto de entrada: `python -m puts_screener.run`.

### Etapa 1 del rework de scoring (ROADMAP §3.5) ✅ Cerrada (2026-05-22)

Segmentación de universos: tres universos predefinidos (`sp500`, `nasdaq100`, `stoxx600`) con dedup interno y tag por pertenencia.

- [x] Nuevo fetcher `_fetch_nasdaq100` desde Wikipedia.
- [x] `build_universe` refactorizado: ahora recibe `list[str]` de universos y devuelve `dict[str, set[str]]` (ticker → set de universos a los que pertenece).
- [x] Modelo: `ScreenedCandidate.universes: tuple[str, ...]` propagado por todo el pipeline.
- [x] Persistencia: columnas nuevas `candidates.universes_json` y `runs.universes_json` con migración idempotente.
- [x] CLI: flag `--universe` (default `sp500`), acepta CSV (ej. `--universe sp500,nasdaq100`).
- [x] Reportes: CSV columna 40 `universes` (pipe-separated, ordenada alfabéticamente). HTML con badges grises al lado del ticker.
- [x] 27 tests nuevos (342 verdes totales). Commit `84cfe90`.
- [x] Validación funcional con `--limit 50`:
  - `--universe sp500` → 503 tickers, 8 candidatos finales, todos taggeados `sp500`.
  - `--universe sp500,nasdaq100` → **516 tickers únicos** (dedup verificado: no son 603), 8 candidatos finales con mezcla correcta: `nasdaq100|sp500` (APP, ABNB, AMAT), `nasdaq100` solo (ALNY), `sp500` solo (ACGL, APO, ALL, ABBV).

Output del run rápido SP500-only ahora en ~12s (vs ~14 min del universo completo). Habilita iteración rápida del refactor de scoring siguiente.

### Etapa 2 del rework de scoring (ROADMAP §3.5) ✅ Cerrada (2026-05-22)

Fix de polaridad + gate de distancia mínima + rename `sma_200d`→`ema_200d`.

- [x] `SupportLevel.side: Literal["support", "resistance"]` derivado de `price < spot`.
- [x] `cluster_into_zones` filtra `side=='support'`. Eliminado `_SPOT_UPPER_MARGIN`.
- [x] `support_scoring` rechaza zonas con `distance_pct < ZONE_MIN_DISTANCE_PCT (0.03)`.
- [x] Rename literal `sma_200d` → `ema_200d` (la EMA siempre estuvo mal nombrada).
- [x] Categoría `sma_200` en `compute_zone_score`: `(sma_200w, ema_200d)`.
- [x] Validación empírica (--limit 50): 4 candidatos finales (vs 8 pre-Etapa 2). APP/AMAT/ACGL/APO cayeron por dist < 3%. Confirma que elementos overhead inflados pre-fix se removieron correctamente.

Commit `6b15b94`. 347 tests verdes.

### Etapa 3 del rework de scoring (ROADMAP §3.5) ✅ Cerrada (2026-05-22)

Agregar SMA200D real + SMA50D + SMA50W + EMA50D como elementos de soporte.

- [x] Nuevas helpers en `indicators.py`: `sma_daily`, `ema_daily` (devuelven `None` si insuficiente data).
- [x] `sma_200_levels` extendida: ahora genera hasta 3 levels (SMA200W + EMA200D + SMA200D real).
- [x] Nueva `sma_50_levels`: SMA50D + SMA50W + EMA50D (reutiliza `sma_weekly` existente con `weeks=50`).
- [x] `compute_zone_score`: categoría `sma_200` agrupa los 3 labels de 200; nueva categoría `sma_50` agrupa los 3 de 50.
- [x] Pesos sin cambios (SMA200=2, resto=1) — la ponderación diferenciada es Etapa 4.
- [x] DYNAMIC_CONFIRMERS intacto (las MAs nuevas no son confirmadores).
- [x] Validación empírica (--limit 50): 5 candidatos finales con scores 3-7. Scores 5 confirman dedup correcta (sma_200 con SMA200D + SMA200W + EMA200D dedupean a 2 pts, no 6).

Commit `6bad46e`. 358 tests verdes.

### Etapa 4 del rework de scoring (ROADMAP §3.5) ✅ Cerrada (2026-05-22)

Ponderación diferenciada + gate estructural + sacar DIVERGENCIA/FIB_786 del score.

- [x] `ELEMENT_WEIGHTS` dict con pesos float 0.0-3.0 por elemento.
- [x] `compute_zone_score` → `float`. Por categoría aplica el MAX peso entre elementos presentes (dedup conserva el peso del más fuerte).
- [x] DIVERGENCIA y FIB_786 con peso 0.0 (informativos). DIVERGENCIA sigue siendo confirmador dinámico.
- [x] Gate estructural nuevo: zona requiere ≥2 elementos individuales con peso ≥ 2.5 (MIN_HEAVY_ELEMENTS=2, HEAVY_ELEMENT_WEIGHT_THRESHOLD=2.5).
- [x] SCORE_MIN_VALID: 3 → 5.0 (float, provisional para calibración).
- [x] Nuevo campo `ScreenedCandidate.momentum_signals: tuple[str, ...]` con flags de divergencia (rsi/macd/both) de la best_zone, sin afectar score.
- [x] Persistencia: nueva columna `candidates.momentum_signals_json` con migración idempotente. `support_zones.score` queda INTEGER en schema pero SQLite acepta REAL transparente.
- [x] CSV columna 41 `momentum_signals`. Score formateado con 1 decimal ("10.0").
- [x] HTML: sección de "Señales de momentum" por card si hay divergence; elementos ordenados por ELEMENT_WEIGHTS descendente.

**Validación empírica a escala (--limit 200):**

- 48/200 (24%) pasaron Paso 1.
- 13/200 (6.5%) pasaron Paso 2 con best_zone válida.
- Distribución de scores: rango 5.5 - 15.5, mediana ~10.0 (cluster en composición arquetípica sma_200+sma_50+hvn+polarity).
- Distribución de distancias: 54% en 3-5%, 23% en 5-7%, 23% en 7-10%.
- 100% T1 (régimen actual alcista; T2/T3/T4 esperables en regímenes distintos — no es bug).
- Wall-time 36s para 200 tickers.
- Caso testigo del fix (AXON): cayó por gate estructural — sus elementos eran DIVERGENCIA + GAP + FIB_786 + FIB_618 (suma 2.5, 0 heavy elements). Era el bug original que el rework apuntaba a resolver.

**Conclusión:** thresholds bien calibrados, no requieren ajuste.

Commit `218eff7`. 372 tests verdes.

### Rework de scoring (ROADMAP §3.5) ✅ COMPLETO (Etapas 1-4)

Pipeline de Paso 2 reescrito desde primeros principios: polaridad corregida, MAs reales completas (SMA200D/W/EMA200D/SMA50D/W/EMA50D), ponderación por elemento, gates de validez compuestos (score numérico + estructural + distancia mín/máx + side + confirmador dinámico). Output estructuralmente más fuerte y selectivo que la versión previa: 6.5% de los tickers pasan vs ~30% pre-rework, con scores que reflejan confluencia real y no doble-conteo.

Etapas 5 y 6 del plan original cerradas como no-implementadas:
- Etapa 5 (filtro de swing range en fibs): ❌ descartada (2026-05-22). Etapa 4 ya neutralizó el problema (FIB_786 peso 0.0, FIB_618 peso 1.5 no califica como heavy); validado N=200. Ver §3.5/§5.
- Etapa 6 (Volume Profile real con intradía): ⏸️ postergada a Fase 4 (data de opciones / IBKR / paid providers).

### Hardening yfinance + observabilidad ✅ (2026-05-22)

Endurecimiento de la capa de data tras diagnosticar 55.8% de skip rate a universo completo (985):

- [x] **fix(yfinance): blindar accesos frágiles a schema upstream** — `499e69a`. Try/except
  defensivo en campos que yfinance puede cambiar de forma; preserva el skip cuando falta data crítica.
- [x] **feat(logging): persistir logs a archivo en logs/** — `7bfe5f4`. FileHandler DEBUG (utf-8)
  + consola INFO; captura yfinance/urllib3/requests. Habilita post-mortem por run. `logs/` en `.gitignore`.
- [x] **feat(yfinance): retry con backoff exponencial para errores transitorios** — `88480a6`.
  `_with_retry` intra-provider (max_attempts=3, base_delay=2.0, jitter ±25%) en los 4 métodos
  críticos; reintenta solo 429/401/red, no schema.

**Métricas empíricas (universo 985):**

| Run | Estado | Skip rate | Wall-time |
|---|---|---:|---:|
| `cd0080c3` | baseline (pre-fixes) | 55.8% | ~32 min |
| `7a41268c` | post defensive-fixes | 45.5% | ~17 min |
| `cdaadca1` | post retry | **38.5%** | ~14 min |

- Output del Paso 2 estabilizado en **~62 candidatos**: no se mueve aunque entre más data (el embudo
  se angosta en gates de Paso 1 y en validez de soporte, no en cobertura de data).
- Errores residuales: **80% `YFRateLimitError`** (transitorios, el retry los absorbe) / **20%
  `TypeError` de schema** (no retriables — requieren más blindaje defensivo).

### Spec 05 — GitHub Actions + Pages (Fase 3) ✅ Cerrada (2026-05-27)

Automatización completa del run diario en GitHub Actions con publicación a GitHub Pages.

- [x] **Tanda 1**: módulos Python (`config_publishing`, `models_publishing`, `publish_pages`) + template `history.html.j2` + 11 tests (383 verdes totales). Commit `d4fb3e5`.
- [x] **Tanda 2**: workflow YAML (`.github/workflows/daily-screening.yml`) con cron `0 22 * * 1-5`, `actions/cache@v4` para OHLCV cache, `actions/deploy-pages` artifact-based, push con rebase+retry, `.gitignore` += `docs-build/`. README sección "Fase 3 — Producción". Smoke local del bundle verificado (HTTP 200 en index + history, grep matchea contenido). Commit `aafb686`.
- [x] **Tanda 3**: tracking inicial de `output/screening_*.{html,csv}` (28 archivos, 13 pares timestamped + latest) y `data/screening_history.db` (3.4 MB, tratado como binario por `.gitattributes` preexistente). Commit `197bddc`.
- [x] **Baseline de embudo en universo completo** (998 tickers únicos sp500+nasdaq100+stoxx600, wall-time 12m16s local con cache caliente): 670 procesados / 328 sin data crítica → 131 Paso 1 (13.1%) → 39 Paso 2 (3.9%) → 131 con flags binarios. Más bajo que el 6.5% Paso 2 sobre sp500-only (run de 200) — esperable por STOXX 600 con data EU faltante.

**Pendiente humano** (no automatizable): setup one-time en GitHub Settings (Pages source = GitHub Actions, workflow permissions = read/write, environment `github-pages`) + primer `workflow_dispatch` manual + push de los 4 commits locales (`b49a950`, `d4fb3e5`, `aafb686`, `197bddc`).

### Spec 06 — Clustering compacto + tier + macro banner + currency (Fase 1.5) ✅ Cerrada (2026-05-27)

Cuatro mejoras coordinadas sobre el output del screener:

- [x] **Tanda 1 — Clustering**: tolerance híbrida (`min(ATR×0.4, spot×1%)`), gate por ancho máximo absoluto (`ZONE_MAX_WIDTH_PCT=0.04`), bounds = envelope real de elementos (no ATR fijo). `compute_zone_score` con multiplicador de densidad (`MIN=0.85`, `MAX=1.5`). Properties nuevas en `SupportZone`: `width`, `width_pct`, `n_heavy_elements`, `score_tier`. 26 tests (17 ajustados + 9 nuevos). 392 verdes totales. Commit `0957a95`.

- [x] **Tanda 2 — Display layer**: `format_price(value, currency)` helper en `formatting.py`. Macro events factorizados a banner global en HTML (no per-card). Score tier (estrellas + label) en cada card. Currency display dinámico (`$`, `€`, `£`, `p` para GBp, etc) desde `CompanyProfile.currency`. 404 tests verdes. Commit `b1a2f33`.

- [x] **Tanda 3 — Calibración empírica**: run completo del universo combinado con código spec 06. Decisión: **no ajustar constantes**. Razones: (a) rate-limiting de yfinance contaminó ~530 de 751 skips en este run específico, muestra no representativa para calibrar; (b) tier shape observado (T5=1, T4=4, T3=4, T2=4, T1=0) es razonable para N=13; (c) la validación real son los crones reales en GitHub Actions (cache caliente, menos rate-limit). Sin commit de constantes.

**Baseline empírico (run d303ab2e, sesgado por rate-limiting):**
- Universo 998 → procesado 247 → Paso 1: 45 → Paso 2: 13
- Top 3 por tier: BARC.L (T5, score 19.13), CL (T4, 16.43), CNP (T4, 15.00)
- Width median: 1.71%, max: 4.15%. Distance median: 5.89%.
- 13/13 best zones tienen confirmador dinámico.
- 6/13 candidatos saturan el cap del density multiplier (×1.5) — observación para watch, no fix.

### Spec 07 — Rediseño visual de cards + strikes + mini-chart + narrativa ✅ Cerrada (2026-05-27)

Implementación en 4 tandas:

- [x] **Tanda 1**: `strikes.py` + `models_reports.py` con `HeuristicStrikes` + constantes de grillas por divisa en `config_reports.py`. 10 tests, commit `4558115`.
- [x] **Tanda 2**: `chart_svg.py` con `render_mini_chart_svg` (SVG inline 480×200, banda de zona + 3 strikes punteados + polyline 126 días + spot final) + constantes `MINI_CHART_*`. 7 tests, commit `97f3c20`. Reusa `format_price` de `formatting.py` (spec 06).
- [x] **Tanda 3**: `narrative.py` heurístico determinista con 3 párrafos por card (Situación / Zona / Qué mirar). Función pura, no persiste. 10 tests, commit `e3993ff`.
- [x] **Tanda 4a**: integración en `_format_candidate` (reports_html.py) — el dict gana 9 claves nuevas (3 strikes raw + 3 formatted + chart_svg + chart_placeholder + narrative_html). 3 tests, commit `eee4785`. Cleanup: la narrativa quedó sin mencionar el tier (gramática rara con labels reales; ya está en el header).
- [x] **Tanda 4b**: rediseño del template `report.html.j2` (grilla 1 col full-width, `card-split` 50/50 texto+chart, narrativa arriba de elementos, lista completa sin truncado, `strikes-banner` full-width). Migración SQLite (4 columnas: `strike_aggressive`, `strike_natural`, `strike_conservative`, `strike_grid_unit`) en `save_support_analysis`. CSV: 3 columnas al final (grid_unit solo en SQLite). 2 tests de persistencia + 2 tests preexistentes actualizados (CSV pasó de 41 a 44 columnas; truncado de HTML eliminado). Commit `cb80292`.

**Validación empírica (smoke `--limit 50`):**
- Wall-time: 13.2s, EXIT=0, sin warnings.
- Embudo: Universo 50 → Paso 1: 8 → Paso 2: 1 candidato.
- HTML: 14 KB. SVG por card: ~2.5 KB (orden esperado, levemente mayor que la estimación de spec por labels Y/X y aria-label).
- Estructuras renderizadas: card-split, strikes-banner con 3 dots aggressive/natural/conservative + yield-note, narrative con 3 `<p>`, mini-chart con SVG real. Sin placeholder, sin "+N más".

**Tests:** 404 (post-spec-06) → 436 (post-spec-07). +32 tests nuevos.

### Estadísticas

- **Tests**: 404 verdes
- **Commits**: 101
- **Universo accesible**: 985 tickers (503 US S&P 500 + 482 EU STOXX 600)
- **Punto de entrada**: `python -m puts_screener.run`

---

## 2. En vuelo (issues abiertos)

**Sin issues abiertos.**

**Pendiente humano para activar spec 07 en producción** (no bloquea código local):
- Push de los 7 commits locales de spec 07 (6 de implementación + 1 de cierre docs).
- Observar primer cron real con código spec 07 (próximo día hábil 22:00 UTC). Mirar con varias cards en lugar de una sola del smoke: legibilidad del split texto/chart, distribución de strikes contra zona en variedad de tickers, longitud típica de la narrativa.

Próximo bloque de trabajo en código: Fase 5 (web app local con Streamlit + charts interactivos) o Fase 4 (data de opciones, futuro lejano).

---

## 3. Próximos pasos (en orden)

### 3.1 Inmediato (próxima sesión)

Validar spec 07 en producción (ver §2 "Pendiente humano"). Una vez verificado al menos 1 cron con código spec 07 en condiciones normales, decidir próximo bloque: Spec 08 (watchlist personal), Spec 06bis (recalibración si la distribución de scores/tiers lo justifica), Spec Telegram, o Fase 5 (web app local con Streamlit).

### 3.2 Fase 3 — Producción

**Estado: ✅ Implementada en spec 05. Pendiente activación humana (ver §2).**

- GitHub Actions con cron diario post-cierre US. → ✅ (cron `0 22 * * 1-5` lun-vie).
- Publicación de HTML a GitHub Pages. → ✅ (`actions/deploy-pages` artifact-based).
- Auto-commit de outputs al repo. → ✅ (`output/screening_*` + `data/screening_history.db`).
- Notificación Telegram opcional. → ⏸️ Deferido a spec 06 (post-validación de Pages).

### 3.3 Fase 4 — Opciones (futuro lejano)

- Integración con data de opciones (paid).
- Paso 4 del SOP (selección de strike, delta, prima, yield, gestión de salida).
- Sustitución de HV Percentile por IV Percentile real.
- Posible integración con IBKR API.

### 3.4 Fase 5 — Web app local (futuro)

Interfaz web local para reemplazar el HTML estático actual y dar control interactivo del pipeline. No bloquea Fase 3 (automatización) ni Fase 4 (opciones); puede arrancar en paralelo cuando haya capacidad.

Capacidades objetivo:
- **Panel de configuración**: editar thresholds desde la UI (filtros del Paso 1, ventana de eventos binarios, parámetros de detección de soportes) sin tocar archivos config_*.py. Persistencia de los ajustes en YAML o tabla de SQLite.
- **Botón "Correr screening"**: dispara el pipeline con los thresholds activos, muestra progreso (Paso 1 → 2 → 3 → reportes) y resultados al terminar.
- **Vista de candidatos con charts interactivos**: por cada candidato, mostrar el chart de precio (6-12 meses daily) con overlays:
  - Zona de soporte sombreada (lower/upper bounds del best_zone).
  - EMAs/SMAs (200D, 50D, etc).
  - AVWAPs anclados (desde pivot bajo, earnings, 52w high).
  - Pivots significativos marcados.
  - Gaps no cerrados destacados.
  - Niveles fib del último impulso.
- **Historial de corridas**: vista de runs pasados desde SQLite, comparación entre runs.
- **Filtros interactivos en la vista de resultados**: por tipo T, por score mínimo, por sector, por presencia/ausencia de flags binarios.

Decisiones a tomar cuando arranque:
- Stack: Streamlit (Python puro, rápido de hacer, estilo limitado) vs FastAPI + React/Vue (más trabajo, totalmente custom, deployable). Default propuesto: Streamlit para el MVP, migrar a FastAPI+React si aparece necesidad de UX más rica.
- Charts: TradingView Lightweight Charts (gratis, look profesional) vs Plotly (integración nativa con Streamlit, customizable) vs Recharts (si React). Default propuesto: depende del stack elegido.
- Modo de ejecución: bloqueante (UI muestra loader durante la corrida, ~4 min) vs background con cola de tareas (Celery/RQ). Default propuesto: bloqueante para uso personal local; cola si en algún momento se hace multi-usuario.
- Persistencia de configuración: archivos YAML separados vs tabla nueva en SQLite vs reescritura directa de los config_*.py. Default propuesto: YAML, espeja el patrón ya usado en data/macro_calendar.yaml.
- Persistir pivots detectados en SQLite (hoy se calculan al vuelo en Paso 2 pero no se persisten — necesarios para que los charts los muestren sin recálculo).

Pre-requisito de data: la mayor parte de lo necesario ya existe (OHLCV en cache local, zonas en SQLite, elementos con metadata). Únicos gaps: pivots no persistidos y elementos del score sin tracking de fecha (algunos sí lo tienen vía metadata, otros no).

### 3.5 Rework del scoring de soportes + segmentación de universos (prioridad alta)

Backlog priorizado en este orden. La numeración "Etapa N" es interna a este plan (no confundir con
las Fases de producto de §3.2–3.4).

**Etapa 1 — Segmentación de universos** ✅ Cerrada (2026-05-22, commit `84cfe90`).
- Flag `--universe=sp500|nasdaq100|stoxx600` (default: `sp500`).
- Composición desde listas oficiales actualizables.
- Deduplicación si se combinan universos, con etiqueta por pertenencia.
- Outputs separados por universo.
- Objetivo: runs de validación en 6-8 min (solo S&P 500) en lugar de 14 min (985 tickers).

**Etapa 2 — Fix de polaridad + pre-filtro + misnaming** ✅ Cerrada (2026-05-22, commit `6b15b94`).
- `_SPOT_UPPER_MARGIN` de 1.02 → 1.00 (solo niveles bajo el spot entran al clustering).
- Campo `side` en `SupportLevel`: `support` / `resistance` / `neutral`.
- Solo elementos `side=support` cuentan para el score.
- Renombrar `sma_200d` → `ema_200d` en código y DB.
- `ZONE_MIN_DISTANCE_PCT = 0.03`: zonas a menos del 3% del spot no son accionables para 30-45 DTE.

**Etapa 3 — Agregar medias móviles** ✅ Cerrada (2026-05-22, commit `6bad46e`).
- SMA200D real (rolling mean diario, 200 velas).
- SMA50D (rolling mean diario, 50 velas).
- SMA50W (rolling mean semanal, 50 velas).
- EMA50D (exponencial diario, span=50).

**Etapa 4 — Ponderación y umbrales** ✅ Cerrada (2026-05-22, commit `218eff7`).
- Pesos propuestos: SMA200D real 3.0 · SMA200W 3.0 · POLARIDAD 3.0 · EMA200D 2.5 · SMA50D 2.5 ·
  AVWAP_pivot_low 2.5 · AVWAP_earnings 2.5 · 52-week low 2.0 · SMA50W 2.0 · HVN/POC 2.0 · EMA50D 1.5 ·
  FIB_618 1.5 · GAP (no rellenado, >X%) 1.0.
- DIVERGENCIA: sacar del score → mover a sección de señales de momentum.
- FIB_786: sacar del score.
- Umbrales (pendiente calibración post-implementación): requerir ≥2 elementos de peso ≥2.5 para
  zona válida; recalibrar `SCORE_MIN_VALID` con el sistema ponderado.

**Etapa 5 — Fibs con filtro de rango mínimo** ❌ Descartada (2026-05-22).

Validación empírica N=200 post-Etapa 4 confirmó que el bug original (fibs de swings chicos generan confluencia artificial) está completamente mitigado por la ponderación: FIB_786 peso 0.0 no contribuye al score, FIB_618 peso 1.5 nunca califica como heavy element (gate ≥2.5). En el bottom 5 del run de validación (scores 5.5-9.5), ningún candidato depende de fibs para validarse — todos pasan por confluencia real de SMA/AVWAP/POLARIDAD/HVN. Implementar Etapa 5 agregaría una constante `MIN_SWING_RANGE_PCT`, lógica de filtro y tests, sin mejorar output, performance ni correctitud. Decisión: NO implementar.
- Requerir `swing_range > X%` del precio para computar FIB_618.
- Objetivo: eliminar fibs de swings chicos en rango que generan confluencia artificial.

**Etapa 6 (backlog) — Value Area Low (Volume Profile completo)** ⏸️ Postergada a Fase 4 (requiere data intradía).
- Postergado para segunda iteración.
- Reemplazar HVN genérico por POC real + VAL.

---

## 4. Backlog / Futuro

Ideas anotadas en el camino pero no priorizadas:

- **Refactor**: deduplicar `_normalize_action` y `_ACTION_MAP` entre `finnhub_provider.py` y `yfinance_provider.py` (módulo compartido). Bajo dolor actual.
- **Validación cruzada de indicadores**: comparar RSI/MACD calculado vs TradingView en 5-10 tickers conocidos. Tolerancia <1%.
- **Backtesting del propio screening**: usar la historia persistida en SQLite para responder "los candidatos que aparecieron hace 60 días, ¿cómo evolucionaron?".
- **Soporte para más exchanges EU**: agregar Polonia, Grecia, Israel cuando aparezcan candidatos interesantes ahí (hoy quedan skipeados).
- **Volume Profile real con intradiario**: requiere data de minutos, no EOD. Postergar hasta Fase 4 (con IBKR o paid provider).
- **Activar Stooq como fallback de OHLCV**: requiere conseguir API key (captcha manual). Solo si yfinance empieza a fallar consistentemente.
- **Asimetría US/EU por chequeo de downgrades (issue conceptual abierto)**: yfinance no provee data de rating changes para tickers EU, por lo que el filtro de downgrades efectivamente no aplica a EU. Hoy un nombre EU pasa `filter_valuation` más fácil que un equivalente US. Con `MAX_DOWNGRADES_6W=1` la asimetría se atenúa (solo nombres con 2+ downgrades caen). Solución estructural: integrar data de ratings EU vía otro provider (paid). Spec futura.
- **Extender SECTORS_FCF_FILTER_EXEMPT a Basic Materials/Industrials (Issue 2.6 candidato)**: el run de 200 dejó fuera 5 nombres por FCF≤0, de los cuales algunos son capital-intensivos en ciclo de capex (química, minería, autos). Decidir caso por caso con evidencia más amplia antes de extender.
- **Suavizar condición spot > SMA200W en T1 (Issue 2.7 candidato)**: 6 candidatos en el run de 200 quedaron fuera por estar apenas debajo de la 200W. Evaluar si correcciones que perforan brevemente la 200W deberían seguir clasificando como T1. Toca core de clasificación, requiere análisis cuidadoso.
- **Divergencia RSI/MACD aparece en 0% de las best_zones (validación spec 03)**: coherente con el filtro previo de no-sobrecompra que excluye candidatos en corrección profunda. No es bug del código sino consecuencia del pipeline. Si se baja en el futuro el threshold de tendencia, revisar si las divergencias emergen como elemento útil.
- **EMA200D domina sobre SMA200W como elemento de score (12 vs 3 apariciones en run de 200)**: coherente con T1 saludable (cerca de EMA200D pero por encima de SMA200W). No requiere acción, anotado por trazabilidad.
- **Mejorar HVN con datos intradía (Fase 4)**: la aproximación uniforme actual cumple el MVP. Para mejorar la precisión del Volume Profile, integrar datos de minutos cuando se sume un provider con esa capacidad (e.g. IBKR, paid).
- **Paso 3 corre sobre todos los Paso-1-passers, no solo Paso-2-passers (decisión de implementación spec 04 vs spec original)**: la spec §9 decía `pasa_paso_2=True` como condición para correr Paso 3; en implementación se cambió a correr sobre todos los Paso-1-passers para tener flags binarios incluso de candidatos sin soporte fuerte. Esto es información útil para el humano. Si en algún momento se quiere optimizar costo, este es un knob para apagar.
- **`ex_div_amount` aproximado desde `Ticker.dividends.iloc[-1]` (yfinance)**: el calendar de yfinance trae la fecha ex-dividend pero no el amount, así que se infiere del dividendo más reciente histórico. Asunción: el próximo ex-div pagará un monto similar al último. Generalmente cierto para blue chips, pero puede fallar en empresas con cambios de política de dividendos.
- **Encoding Windows cp1252 en stdout**: caracteres acentuados (e.g. 'días') aparecen como mojibake en consola Windows. Los archivos CSV/HTML quedan en UTF-8 correctamente. Solo afecta display de consola, no datos. Si molesta, se puede forzar UTF-8 en stdout con `sys.stdout.reconfigure(encoding='utf-8')` al inicio de `run.py`.
- **Endurecer firma de `run_screening` / `run_final_pipeline` (dict-only)**: hoy aceptan `list[str] | dict[str,set]` por backward-compat con smoke tests y stubs. El path de producción (`run.py`) pasa el dict y todo funciona, pero un caller futuro que pase lista heredaría `universes=()` silenciosamente. Bajo riesgo (un solo caller productivo), pero conviene endurecer cuando alguna spec posterior toque esos modules.
- **Threshold `ZONE_MIN_DISTANCE_PCT=0.03` en Etapa 2 — observación previa**: el run de validación de Etapa 1 mostró que 2 de 8 candidatos finales (APP 2.6%, ABNB borderline 3.5%) están cerca o debajo del threshold planificado. Si Etapa 2 lo implementa tal cual, podríamos perder ~25% del output. Validar empíricamente post-implementación; si el output queda muy seco, considerar bajar a 0.02 o 0.015.
- **`points` field vestigial en `SupportLevel`** (post-Etapa 4): el campo quedó como `float = 0.0` por blast-radius. El peso real vive en `ELEMENT_WEIGHTS` keyed por element. Riesgo bajo de drift; aprovechar cuando alguna spec posterior toque `support_elements.py`.
- **`ema_daily` exige `len < length → None`** (post-Etapa 3): conceptualmente una EMA produce valores desde el primer dato, no requiere warmup. Decidido como `None` por consistencia con `sma_daily`. No es problema para uso real (OHLCV de producción siempre >200 días). Revisar si en el futuro se agregan tickers con histórico corto.
- **`reports_csv._ELEMENT_LABELS` sin fallback `sma_200d` (legacy)**: post-Etapa 2 se renombró sin dejar fallback. Si en el futuro se hace un "reimprimir reporte de run viejo" (no existe hoy), el rendering de registros con `sma_200d` legacy caería al default.
- **Endurecer firma `run_screening`/`run_final_pipeline` a dict-only**: hoy aceptan `list[str] | dict[str,set]` por compat con smoke tests. Path productivo siempre pasa dict.
- **Sesgo a T1=100% en régimen alcista actual**: validación con --limit 200 sobre S&P 500 dio 13/13 T1. Esperable, pero anotar para confirmar en régimen distinto (T2 debería aparecer en pánicos, T4 en correcciones post-earnings, T3 en lateralizaciones macro).
- **Calibración futura de `SCORE_MIN_VALID` y `MIN_HEAVY_ELEMENTS`**: thresholds provisionales 5.0 y 2 fijados con muestra de 200. Con varias corridas históricas semanales sobre el universo completo, definir si el output es estable o requiere ajuste.
- **Watchlist personal extendiendo el universo (spec 08 candidata)**: archivo `data/watchlist.txt` con un ticker por línea, mergeable al universo configurado. Permite trackear nombres fuera de sp500/nasdaq100/stoxx600 (ej. CRWV, otros IPOs recientes, mid-caps con buen setup). Trade-off conocido: stocks con histórico corto (<4 años) no pueden calcular SMA200W, lo que limita su techo de score (heavies pesan SMA200D/W con peso 3.0). Útil igual: el ticker entra al universo y se evalúa con lo que tiene; el humano decide.
- **Saturación del density multiplier en cap 1.5 (post-spec-06 watch)**: en el run de Tanda 3 calibración, 6 de 13 best zones pegaron el cap superior del multiplier (×1.5). El multiplier diferencia poco entre las zonas más densas (todas saturan). Si la observación se confirma en crones reales sin rate-limiting, considerar subir `REFERENCE_DENSITY` (de 100 a ~150) y/o `MAX_DENSITY_MULTIPLIER` (de 1.5 a ~1.75) para ampliar el rango lineal.
- **T1 (banda 5.0-6.5) estructuralmente vacío (post-spec-06 watch)**: una zona con score base 5.0 multiplicado por ≥1.0 ya cae en T2 (≥7.5). T1 solo se alcanza con multiplier <1.0, que requiere densidad <100 — rara post-clustering compacto. No es bug; es consecuencia del diseño multiplier. Aceptable: tier 1 sigue siendo "raro" como debe ser.
- **Gate de ancho silencioso (post-spec-06 observabilidad)**: `ZONE_MAX_WIDTH_PCT` descarta clusters con un `continue` en `cluster_into_zones` antes de persistir, sin loguear. No medible a posteriori cuántos clusters descartó. Si en algún momento se sospecha que descarta demasiado o demasiado poco, instrumentar un log o contador en el módulo. Bajo dolor actual.
- **SVG por card más pesado de lo estimado en spec (post-spec-07 watch)**: el SVG real es ~2.5KB vs ~1.5KB que estimaba spec 07 §6.2 (labels Y/X + aria-label sumaron). Con 30 cards eso son ~75KB extra en el HTML (~150KB total estimado), no 50KB. Sigue siendo aceptable. Observar tamaño del HTML en crones reales con cards completas; si se vuelve problemático (>500KB) optimizar truncando precisión de coords o eliminando labels redundantes.
- **Caso ACGL 2026-05-27 (post-spec-07 referencia)**: ACGL salió como T1 con zona compacta $93.35–$95.32 y score 6 en el run del 2026-05-26; al día siguiente cayó -4.16% intra-día rompiendo el conservative. La zona estaba correctamente identificada (confirmada por chart), score 6 era tier medio (no "invulnerable"), y los flags macro (FOMC 26d + CPI 19d) estaban presentes. El screener funcionó como diseñado — el stop estructural del SOP (cierre debajo del conservative → revisar tesis) es la respuesta correcta a este tipo de evento idiosincrático. Útil conservar como caso histórico para evaluar narrativa de spec 07 y, más adelante, para análisis sistemático sobre `screening_history.db` (cuántas zonas detectadas rompieron vs aguantaron, qué patrón discriminador adicional podría existir).

---

## 5. Decisiones de diseño registradas (resumen)

Para no buscarlas en specs:

- **Stack free + diseñado para swap**: yfinance primario, Finnhub opcional, Stooq desactivado.
- **GitHub Actions como runtime objetivo** (Fase 3): no servidor propio.
- **HV Percentile sustituye IV Percentile** hasta integrar opciones.
- **Momentum invertido**: gate de sobrecompra (RSI ≥ 70 falla); señales positivas en `momentum_score` informativo.
- **T5 omitido**: decisión manual, no detectable automáticamente.
- **Persistir todo (pasen o no)**: para backtesting futuro del propio screening.
- **Indicadores a mano**: numpy/pandas puro, sin `pandas_ta` (problemas con numpy 2 / pandas 3).
- **Parsing de Wikipedia con `bs4` + `html.parser`** (builtin), no `pandas.read_html` (requería lxml en su momento; ahora lo agregamos pero ya está hecho con bs4).
- **Universe builder con cache 7 días**: Wikipedia es estable, no hace falta refetch diario.
- **2026-05-21 — Exención de FCF por sector (Utilities, Financial Services, Real Estate)**: el filtro de FCF≤0 del SOP no es proxy válido de salud en sectores capital-intensivos o con estructura financiera distinta. Reversible/extensible vía `SECTORS_FCF_FILTER_EXEMPT` en `config_filters.py`.
- **2026-05-21 — Gate de clasificación T1-T4 al final del Paso 1**: un candidato sin tipo asignado se rechaza con motivo "sin clasificación T1-T4". Cierra un gap entre spec 02 §1 y la implementación previa.
- **2026-05-21 — Techo HV elevado de 80 a 90 hasta integrar IV real**: la HV (volatilidad realizada) corre estructuralmente más alta que IV percentile en el universo actual; mantener el techo en 80 generaba 22 falsos rechazos en run de 50. Reversible cuando se integre data de opciones (Fase 4).
- **2026-05-21 — Spec 03 §6.1, `has_dynamic_confirmer` corregido en implementación**: el pseudocódigo de la spec usa `e.element in DYNAMIC_CONFIRMERS` con `DYNAMIC_CONFIRMERS = ('avwap', 'hvn', 'divergence')`, pero los elementos AVWAP se llaman `avwap_pivot_low`/`avwap_earnings`/`avwap_52w_high`. La implementación introdujo el helper `_is_dynamic_confirmer()` que mapea sub-variantes de AVWAP a la categoría 'avwap' antes de chequear, consistente con `compute_zone_score`. Sin esto, ninguna zona confirmada solo por AVWAP pasaría la validación de §7.
- **2026-05-21 — Spec 03 ventanas de lookback unificadas a días hábiles**: el documento usa '252 días' como shorthand de '12 meses hábiles'. La implementación inicial mezcló días calendario (`Timedelta`) en algunas funciones con `.iloc[-252:]` en otras. Se unificó a 252 días hábiles derivando el corte del índice del OHLCV (helper `_date_cutoff`). Las constantes en `config_supports` mantienen el nombre `_DAYS` pero su semántica operativa es 'días hábiles' (≈12 meses).
- **2026-05-21 — Spec 03, `data_service` en `analyze_supports`**: mantenido en la firma por fidelidad a la spec aunque no se use hoy (toda la data viene del `candidate`). Hook reservado para evolución futura (e.g. validar IV real cuando se integre data de opciones en Fase 4).
- **2026-05-21 — Spec 03, `atr_series` extraída de `atr_14`**: refactor sin cambio de comportamiento. `atr_14` ahora delega en `atr_series(...).iloc[-1]`. Permite reuso para detección de pivots y clustering.
- **2026-05-21 — Spec 03, persistencia idempotente verificada en DB real**: dos runs consecutivos sin error de columna duplicada, columna `pasa_paso_2` única en `candidates`, tabla `support_zones` poblada correctamente con `run_id` separado por corrida.
- **2026-05-21 — Spec 04, Paso 3 corre sobre todos los Paso-1-passers (no solo Paso-2-passers)**: override de la spec original. Los flags binarios son información útil aunque el candidato no tenga soporte fuerte. Los reportes filtran por `passes_all_steps`, así que solo Paso-2-passers aparecen en CSV/HTML, pero los flags se computan y persisten para todos.
- **2026-05-21 — Spec 04, migración SQLite generalizada**: un solo `PRAGMA table_info` + dict de columnas esperadas + `ALTER` de las faltantes. Más eficiente que PRAGMA+ALTER por columna y más fácil de extender en specs futuras.
- **2026-05-21 — Spec 04, `ex_div_amount` aproximado**: el calendar de yfinance no trae amount; se aproxima desde `dividends.iloc[-1]` (último dividendo histórico). Trade-off aceptable para MVP; refinable en Fase 4 con providers de opciones.
- **2026-05-21 — Issue 2.5 cerrado, `MAX_DOWNGRADES_6W` subido de 0 a 1**: la caracterización empírica de `filter_valuation` sobre 200 tickers mostró que 4 de 5 rechazos exclusivos por downgrades eran blue chips con consenso fuerte de compra (ADSK 0.91 buy, CI 0.88, AMAT 0.79, BKR 0.73) rechazados por un único downgrade. El SOP dice "sin downgrades significativos"; un downgrade aislado es ruido institucional. 2+ downgrades sigue siendo patrón filtrable. Reduce además el sesgo US/EU (EU exento del chequeo por falta de data en yfinance).
- **2026-05-21 — Issue 2.5 cerrado, `MIN_RECOMMENDATION_BUY_RATIO` bajado de 0.5 a 0.45**: 8 candidatos near-miss en [0.45, 0.5) con upside positivo (BP.L +10.8% buy 0.47, CHD +6.3% buy 0.48, etc.) fallaban por 0.02-0.03 puntos. El SOP exige "mayoría Buy"; 0.45 sigue siendo ligera mayoría (45% Buy vs 55% Hold/Sell). Los 36 candidatos con buy_ratio <0.3 siguen filtrados como rechazos legítimos.
- **2026-05-22 — Etapa 1 cerrada con `list | dict` en pipelines (no dict-only puro)**: la spec original decía "recibe el dict y pasa el tag", pero 8+ callers existentes (smoke tests + tests de pipeline) pasan listas y la spec no los listaba para actualizar. Decisión pragmática: `run_screening` y `run_final_pipeline` aceptan ambos; si llega dict, derivan tags; si llega lista, `universes=()`. `run.py` siempre pasa dict, así que producción siempre etiqueta. Endurecimiento a dict-only queda en backlog (§4) para una iteración futura cuando se justifique tocar esos modules por otra razón.
- **2026-05-22 — Caches de universo gitignored (sp500.json, nasdaq100.json, stoxx600.json)**: los tres son regenerables vía `build_universe(..., refresh=True)` (Wikipedia es estable y el fetch toma segundos). No se commitean porque (a) tienen TTL de 7 días y se desactualizan, (b) son derivables del código sin pérdida, (c) gitignored es el patrón estándar para caches. Inconsistencia previa (suponer que sp500/stoxx600 estaban commiteados) corregida sin commitear nada nuevo.
- **2026-05-22 — Etapa 2: `side` binario sobre `SupportLevel`**: derivado de `price < spot`. Resistance NO entra al clustering. Reemplaza el viejo `_SPOT_UPPER_MARGIN=1.02` que tenía el bug confirmado en RTX.
- **2026-05-22 — Etapa 3: dedup SMA200 con 3 labels y nueva categoría SMA50**: `sma_200 = {sma_200w, ema_200d, sma_200d}` (todos suman 2 pts dedupeados pre-Etapa 4; con peso máx post-Etapa 4). `sma_50 = {sma_50d, sma_50w, ema_50d}` análogo.
- **2026-05-22 — Etapa 4: `compute_zone_score` ahora aplica MAX peso por categoría, no suma**: cuando una zona tiene SMA200W (3.0) + EMA200D (2.5) + SMA200D (3.0) dentro de la misma categoría sma_200, aporta 3.0 (max), no 8.5 (suma). Preserva la intención de dedup pero respeta la jerarquía de pesos diferenciados.
- **2026-05-22 — Etapa 4: gate estructural compuesto con gate numérico**: una zona necesita `score >= 5.0` AND `>= 2 elementos individuales con peso >= 2.5`. Diseñado para rechazar tanto zonas con score-inflado por acumulación de pesos chicos como zonas con un solo elemento heavy aislado. Validación a escala (n=200) confirma calibración correcta.
- **2026-05-22 — Etapa 5 del rework descartada (no implementada)**: post-validación N=200, el bug que motivaba Etapa 5 (fibs inflados por swings chicos) está mitigado por la ponderación de Etapa 4 (FIB_786=0.0, FIB_618=1.5 no califica como heavy). Implementarla agregaría complejidad sin valor. Si en el futuro se identifica un caso real donde fibs vuelvan a inflar score, reabrir.
- **2026-05-27 — Spec 05, Pages servido vía `actions/deploy-pages` con artifact**: descartadas `docs/` commiteado y rama `gh-pages`. Bundle vive en `docs-build/` (gitignored, temporal), se sube como artifact por run. Mantiene el árbol limpio y es el patrón actual recomendado por GitHub.
- **2026-05-27 — Spec 05, cache OHLCV con `actions/cache@v4`**: key por `run_id` garantiza save, `restore-keys` con prefix restaura el más reciente. Invalidación manual via bump de version (`v1`→`v2`) en el key.
- **2026-05-27 — Spec 05, DB commiteada al repo + binario en `.gitattributes`**: habilita backtesting futuro contra el propio histórico. Trade-off de crecimiento monotónico aceptado (~50-100 KB/run, manejable por años). `.gitattributes` preexistía con `*.db binary` y `*.parquet binary` — la spec lo listaba como [NEW] pero estaba [EXISTING] con contenido exacto, no requirió cambios.
- **2026-05-27 — Spec 05, histórico navegable autogenerado en `history.html`**: el índice se construye en cada deploy desde `output/`. Sin esto, el histórico solo sería accesible vía `git log` perdiendo el valor de Pages.
- **2026-05-27 — Spec 05, cron en 22:00 UTC lun-vie**: cubre cierre US en DST (18:00 ET) y winter (17:00 ET). Sin manejo explícito de feriados US (output similar al día previo, no hay daño).
- **2026-05-27 — Spec 05, Telegram diferido a spec 06**: superficie de la spec inicial ya significativa (workflow + Pages + caching + commit + permisos). Telegram entra una vez que Pages esté validado en producción.
- **2026-05-27 — Spec 05, Finnhub no en Actions inicialmente**: skip rate 38.5% post-hardening con yfinance solo es aceptable. Sumar Finnhub es PR chico si se vuelve problema (API key en Secrets).
- **2026-05-27 — Spec 05, sin CI de tests en `daily-screening.yml`**: workflow productivo, no CI. CI de tests va en workflow separado si se quiere; mezclar tests + run alarga wall-time del cron sin razón.
- **2026-05-27 — Spec 05, `timeout-minutes: 45` provisional**: holgado contra smoke ~12m local. Margen 1.8-2.2x sobre worst case esperado con cache frío en CI. Subir si runs reales se acercan al techo.
- **2026-05-27 — Spec 05, filename pattern con regex estricto** (`screening_YYYY-MM-DD_HHMM.(html|csv)`): solo archivos que matchean entran al histórico. Cualquier basura en `output/` (incluido `screening_latest.*`) es ignorada por el discover, aunque `latest.*` sí se copia explícitamente al bundle como home.
- **2026-05-27 — Anotación factual (no decisión)**: el timestamp de los nombres viene de `datetime.now()` local. En Actions corre UTC (`_2200` consistente); local en runs manuales del usuario va a tener timestamp local. No bloqueante, no ambiguo (la fecha resuelve). Cambiar a UTC explícito en `config_reports.REPORT_FILENAME_PATTERN` lo arreglaría si en el futuro molesta.
- **2026-05-27 — Spec 06, clustering compacto + density multiplier**: tolerance híbrida `min(ATR×0.4, spot×1%)`, gate por ancho máximo 4%, bounds = envelope real (no ATR fijo). `compute_zone_score` con factor de densidad `[0.85, 1.5]`. Premia confluencia compacta de heavies, penaliza zonas anchas. `REFERENCE_DENSITY=100`, `SLOPE=0.005`.
- **2026-05-27 — Spec 06, distance_pct ahora se mide contra upper_bound** (no contra center_price). El upper es lo que toca primero el precio si baja, métrica más fiel al riesgo del strike.
- **2026-05-27 — Spec 06, calibración Tanda 3 cerrada sin cambios a constantes**: el run de validación tuvo rate-limiting masivo de yfinance (~530 de 751 skips transitorios), muestra no representativa. Tier shape observado (T5=1, T4=4, T3=4, T2=4, T1=0) es razonable. La validación real son los crones de GitHub Actions con cache caliente. Recalibrar solo después de 2-3 crones limpios si la distribución se ve mal.
- **2026-05-27 — Spec 06, GBp display como sufijo "p" sin conversión a libras**: yfinance retorna magnitudes de LSE en peniques; convertir requeriría dividir todos los valores numéricos (zonas, targets) y eso toca múltiples lugares. Más simple: mantener magnitud, agregar sufijo "p". Reversible bumpeando `GBp.divisor` a 100 en config_reports si en el futuro queremos libras.
- **2026-05-27 — Spec 07 cerrada en código**: 4 tandas, 32 tests nuevos, 6 archivos nuevos en src + 4 modificados, decisiones registradas en spec 07 §11 + patch de Tandas 1-4 aplicado al cierre. Pendiente activación en producción vía cron.

---

## 6. Convención para mantener este documento

- Al **cerrar una sesión**: actualizar §1 (estado actual marca lo completado), §2 (issues nuevos identificados), §3 (próximos pasos refinados), fecha "Última actualización" arriba.
- Al **arrancar una sesión nueva**: leerlo primero (junto con SPEC.md y CLAUDE.md). Es la entrada al contexto.
- **Issues en §2 que se cierran**: mover a §1 como "completado" o §5 si es decisión registrada.
- **Items de §4 que ascienden a prioridad**: mover a §3.
