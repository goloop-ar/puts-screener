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

### Estadísticas

- **Tests**: 215 verdes
- **Commits**: 19
- **Universo accesible**: 985 tickers (503 US S&P 500 + 482 EU STOXX 600)
- **Punto de entrada**: `python -m puts_screener.run`

---

## 2. En vuelo (issues abiertos)

Sin issues abiertos. Lista para avanzar a spec 03.

---

## 3. Próximos pasos (en orden)

### 3.1 Inmediato (próxima sesión)

Arrancar spec 03 — Detección de soportes y scoring de confluencia (Paso 2 del SOP). El detalle ya está en §3.2.

### 3.2 Spec 03 — Detección de Soportes y Scoring (Paso 2 del SOP)

Es la parte algorítmicamente más densa del SOP. Cubre:
- Detección de pivots / swings significativos en OHLCV.
- Identificación del último impulso → niveles fib 61.8% y 78.6%.
- Resistencias rotas (polaridad).
- Gaps alcistas no cerrados.
- Anchored VWAP (desde último mínimo significativo y desde último earnings).
- HVN aproximado (histograma de volumen por bucket de precio).
- Divergencias RSI/MACD vs precio.
- Score de confluencia (suma ponderada).
- Filtro final: precio dentro del 10% de soporte con score ≥ 3.

**Entrada**: lista de `ScreenedCandidate` que pasaron Paso 1.
**Salida**: misma lista pero solo los que califican por soporte fuerte.

### 3.3 Spec 04 — Reportes y Eventos

- Generación de CSV detallado por corrida.
- HTML report top 20 con mini-charts.
- Paso 3 del SOP (check de eventos binarios completo).

### 3.4 Fase 3 — Producción

- GitHub Actions con cron diario post-cierre US.
- Publicación de HTML a GitHub Pages.
- Auto-commit de outputs al repo.
- Notificación Telegram opcional.

### 3.5 Fase 4 — Opciones (futuro lejano)

- Integración con data de opciones (paid).
- Paso 4 del SOP (selección de strike, delta, prima, yield, gestión de salida).
- Sustitución de HV Percentile por IV Percentile real.
- Posible integración con IBKR API.

---

## 4. Backlog / Futuro

Ideas anotadas en el camino pero no priorizadas:

- **Refactor**: deduplicar `_normalize_action` y `_ACTION_MAP` entre `finnhub_provider.py` y `yfinance_provider.py` (módulo compartido). Bajo dolor actual.
- **Validación cruzada de indicadores**: comparar RSI/MACD calculado vs TradingView en 5-10 tickers conocidos. Tolerancia <1%.
- **Backtesting del propio screening**: usar la historia persistida en SQLite para responder "los candidatos que aparecieron hace 60 días, ¿cómo evolucionaron?".
- **Soporte para más exchanges EU**: agregar Polonia, Grecia, Israel cuando aparezcan candidatos interesantes ahí (hoy quedan skipeados).
- **Volume Profile real con intradiario**: requiere data de minutos, no EOD. Postergar hasta Fase 4 (con IBKR o paid provider).
- **Activar Stooq como fallback de OHLCV**: requiere conseguir API key (captcha manual). Solo si yfinance empieza a fallar consistentemente.
- **Caracterizar el filtro de valoración (Issue 2.5 candidato)**: con HV y FCF aliviados, valuation pasó a ser el filtro que más rechaza (79/200 en run de validación). Si después de spec 03 el throughput queda bajo, desglosar sub-causas (upside vs buy ratio vs downgrades) y ajustar.
- **Extender SECTORS_FCF_FILTER_EXEMPT a Basic Materials/Industrials (Issue 2.6 candidato)**: el run de 200 dejó fuera 5 nombres por FCF≤0, de los cuales algunos son capital-intensivos en ciclo de capex (química, minería, autos). Decidir caso por caso con evidencia más amplia antes de extender.
- **Suavizar condición spot > SMA200W en T1 (Issue 2.7 candidato)**: 6 candidatos en el run de 200 quedaron fuera por estar apenas debajo de la 200W. Evaluar si correcciones que perforan brevemente la 200W deberían seguir clasificando como T1. Toca core de clasificación, requiere análisis cuidadoso.

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

---

## 6. Convención para mantener este documento

- Al **cerrar una sesión**: actualizar §1 (estado actual marca lo completado), §2 (issues nuevos identificados), §3 (próximos pasos refinados), fecha "Última actualización" arriba.
- Al **arrancar una sesión nueva**: leerlo primero (junto con SPEC.md y CLAUDE.md). Es la entrada al contexto.
- **Issues en §2 que se cierran**: mover a §1 como "completado" o §5 si es decisión registrada.
- **Items de §4 que ascienden a prioridad**: mover a §3.
