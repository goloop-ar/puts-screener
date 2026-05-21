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

### Estadísticas

- **Tests**: 212 verdes
- **Commits**: 16
- **Universo accesible**: 985 tickers (503 US S&P 500 + 482 EU STOXX 600)
- **Punto de entrada**: `python -m puts_screener.run`

---

## 2. En vuelo (issues abiertos)

### 2.1 FCF negativo para bancos

**Contexto**: en el smoke test de 7 tickers, JPM (T1 candidato fuerte) fue rechazado por `filter_quality_liquidity` con razón "FCF TTM (-14.7B) ≤ 0". El SOP excluye empresas con FCF negativo, pero los bancos no se miden con FCF tradicional (su modelo de negocio es distinto: el "cash flow" de un banco viene de depósitos, préstamos, trading).

**Opciones consideradas**:
- (a) Skipear el chequeo de FCF cuando `profile.sector == "Financial Services"` o similar.
- (b) Eximir solo a sub-sectores específicos (bancos, aseguradoras, no fintechs).
- (c) Usar una métrica alternativa para financieros (ROE, ROA, NIM) — más trabajo.
- (d) Aceptar la pérdida y excluir financieros del MVP.

**Estado**: pendiente decisión.

### 2.2 HV Percentile excluyendo demasiado

**Contexto**: en el smoke de 7 tickers, 3 fueron rechazados por `HV > 80` (SAP.DE 88.9, NESN.SW 89.7, NVDA 95.2). El SOP excluye IVP > 80 por "evento binario probable", pero T2 (pánico) se dispara justamente cuando la volatilidad está alta.

**Opciones consideradas**:
- (a) Subir el techo de 80 a 90 (más permisivo).
- (b) Eximir del filtro HV a candidatos de tipo T2 (T2 esperá HV alto).
- (c) Hacer el filtro HV "soft" (advertencia en lugar de rechazo), filtrar al ranking final.

**Estado**: pendiente decisión. Requiere data empírica de muestra más grande antes de decidir.

### 2.3 Validación con muestra más grande

Antes de tocar thresholds (issues 2.1 y 2.2), correr `python -m puts_screener.run --limit 50 --no-persist` para ver:
- Tasa de aprobación real (cuántos candidatos pasan de 50).
- Distribución de motivos_rechazo (cuáles son los filtros que más rechazan).
- Distribución de momentum_score entre los que pasan.

Esto debería ser el **primer paso del próximo día de trabajo**, antes de cualquier decisión.

---

## 3. Próximos pasos (en orden)

### 3.1 Inmediato (próxima sesión)

1. **Validar con `--limit 50 --no-persist`** — recopilar evidencia empírica.
2. **Decidir issues 2.1 y 2.2** con criterio basado en la evidencia.
3. **Implementar ajustes** (un mini-prompt por cada decisión).
4. **Smoke test del pipeline completo** post-ajustes.

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

---

## 6. Convención para mantener este documento

- Al **cerrar una sesión**: actualizar §1 (estado actual marca lo completado), §2 (issues nuevos identificados), §3 (próximos pasos refinados), fecha "Última actualización" arriba.
- Al **arrancar una sesión nueva**: leerlo primero (junto con SPEC.md y CLAUDE.md). Es la entrada al contexto.
- **Issues en §2 que se cierran**: mover a §1 como "completado" o §5 si es decisión registrada.
- **Items de §4 que ascienden a prioridad**: mover a §3.
