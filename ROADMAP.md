# ROADMAP — puts-screener

> Documento vivo: estado actual, issues abiertos, próximos pasos. Actualizar al cierre de cada sesión.

**Última actualización**: 2026-05-21

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

### Estadísticas

- **Tests**: 315 verdes
- **Commits**: 73
- **Universo accesible**: 985 tickers (503 US S&P 500 + 482 EU STOXX 600)
- **Punto de entrada**: `python -m puts_screener.run`

---

## 2. En vuelo (issues abiertos)

Sin issues abiertos. Fase 1 completa, lista para validación empírica de Fase 1 entera y luego Fase 3 (GitHub Actions).

---

## 3. Próximos pasos (en orden)

### 3.1 Inmediato (próxima sesión)

Validación empírica del pipeline completo con `--limit 200`: confirmar que CSV + HTML se generan correctamente sobre muestra grande, que los flags binarios aparecen donde deberían, y que la performance del pipeline completo es razonable. Después de eso, arrancar Fase 3 (GitHub Actions + Pages) según §3.2.

### 3.2 Fase 3 — Producción

- GitHub Actions con cron diario post-cierre US.
- Publicación de HTML a GitHub Pages.
- Auto-commit de outputs al repo.
- Notificación Telegram opcional.

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

---

## 6. Convención para mantener este documento

- Al **cerrar una sesión**: actualizar §1 (estado actual marca lo completado), §2 (issues nuevos identificados), §3 (próximos pasos refinados), fecha "Última actualización" arriba.
- Al **arrancar una sesión nueva**: leerlo primero (junto con SPEC.md y CLAUDE.md). Es la entrada al contexto.
- **Issues en §2 que se cierran**: mover a §1 como "completado" o §5 si es decisión registrada.
- **Items de §4 que ascienden a prioridad**: mover a §3.
