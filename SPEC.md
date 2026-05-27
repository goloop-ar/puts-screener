# SPEC — Puts Screener

> Automatización del screening diario de acciones para venta sistemática de puts, basada en el documento `SOP Venta Puts v3`.

## 1. Propósito

Identificar diariamente acciones de mercados US y Europa que cumplan los criterios definidos en los Pasos 0, 1 y 2 del SOP, y producir un reporte rankeado de candidatos para revisión humana.

## 2. Scope

### Incluido (fase actual)

- Paso 0: Clasificación de situación de entrada (T1–T5)
- Paso 1: Screening (Calidad, Liquidez del subyacente, Tendencia macro, Valoración, Momento técnico)
- Paso 2: Identificación de soportes y scoring de confluencia
- Paso 3: Check de eventos binarios completo
- Filtro final: precio actual dentro del 10% de un soporte con score ≥ 5.0 y ≥2 elementos de peso ≥2.5 (gate estructural compuesto)
- Output: CSV detallado + HTML report top 20 + persistencia SQLite

### Excluido por ahora (fases futuras)

- Paso 4: Selección de strike, delta, prima, yield, gestión de salida
- Todo lo relacionado a opciones (IV, IV Percentile, Greeks, cadena)
- Ejecución de órdenes

### Sustitución temporal

El filtro de IV Percentile (52w) del SOP se reemplaza en esta fase por **HV Percentile (52w)** calculado desde OHLCV puro. Cuando se integre data de opciones, se reemplaza por IV real.

## 3. Stack tecnológico

- Python 3.11+
- Fuentes de datos (stack free, diseñado para swap):
  - **OHLCV histórico**: yfinance (único en el stack default desde 2026-05-21; Stooq quedó fuera por requerimiento de API key)
  - **Fundamentals (Market Cap, FCF, sector)**: yfinance primario, Finnhub como fallback opcional
  - **Analistas (price target, recommendations) + Earnings + Rating changes**: yfinance primario, Finnhub como fallback opcional para US
- Cálculos técnicos: numpy/pandas puro + lógica propia
- Persistencia: SQLite local (committed al repo)
- Reportes: HTML estático + CSV
- Orquestación final: GitHub Actions con cron diario post-cierre US (Fase 3 ✅)

### Diseño para swap

Todas las fuentes de data se implementan detrás de una interfaz abstracta `DataProvider`. La lógica de negocio nunca llama directo a yfinance/Stooq/Finnhub. Esto permite migrar a EODHD, FMP, fiscal.ai o IBKR en el futuro sin reescribir nada.

### Limitaciones conocidas del stack free

- **Stooq requiere API key desde marzo 2026**. Implementado pero fuera del default. Se puede reactivar agregando la key al `.env`.
- **Finnhub free está degradado**: `price_target` y `upgrade_downgrade` devuelven 403; tickers EU devuelven 403 en todos los endpoints. Solo sirve como fallback para `recommendation_trends` y `company_profile2` en US.
- **Rating changes para tickers EU no están disponibles** en yfinance (devuelve lista vacía). El filtro del SOP "downgrades últimas 6 semanas" se aplicará solo a tickers US en la práctica.
- **Datos delayed** (no real-time). Para batch diario post-cierre es suficiente.

## 4. Output esperado

Por cada corrida diaria:

### 4.1 CSV detallado (`output/screening_YYYY-MM-DD_HHMM.csv`)

Una fila por candidato que pasa todos los filtros. Columnas mínimas:

- `ticker`, `exchange`, `sector`, `market_cap`
- `tipo_T` (T1–T5), `justificacion_tipo`
- `precio_spot`, `zona_soporte_min`, `zona_soporte_max`, `distancia_a_soporte_pct`
- `score_soporte`, `elementos_score` (lista textual de qué sumó)
- `rsi_diario`, `rsi_semanal`, `macd_estado`
- `sma50w_sobre_sma200w` (bool)
- `price_target_consensus`, `price_target_upside_pct`, `recommendation_mean`
- `downgrades_6w`
- `earnings_date` (fecha o NULL)
- `dias_a_earnings` (int o NULL)
- `earnings_en_45d` (bool)
- `hv_percentile_52w`

### 4.2 HTML report (`output/screening_YYYY-MM-DD_HHMM.html`)

Cards rankeadas por prioridad de tipo (T1 > T2 > T4 > T3 > T5), luego score de soporte desc y distancia asc. Sin tope de cantidad (todos los que pasan Paso 2). Para cada candidato:

- Card con ticker, sector, tipo T, tier de confluencia (estrellas + label) con score crudo debajo, precio spot formateado por divisa, distancia a soporte. Eventos macro globales (FOMC, CPI) en banner único arriba de la grilla; eventos ticker-específicos (earnings, ex-div) flageados per-card.
- Justificación textual de por qué califica
- Idealmente: mini-chart de precio diario últimos 6 meses con zona de soporte sombreada (puede ir a Fase 2)

### 4.3 Persistencia SQLite (`data/screening_history.db`)

Tablas:

- `runs` — `run_id`, `timestamp`, `universo_size`, `candidates_count`, `status`
- `candidates` — `run_id`, `ticker`, todos los campos del CSV
- `universe` — `run_id`, `ticker`, `motivo_de_rechazo` (opcional, debugging)

## 5. Arquitectura general

```
GitHub Actions cron (22:00 UTC L-V)
            │
            ▼
   1. Universe Builder         → universo cap>$10B, vol>1M
            │
            ▼
   2. Data Fetchers (paralelo) → OHLCV 2y, fundamentals, analistas, earnings
            │
            ▼
   3. Filtros Paso 1            → Calidad, Valoración, Tendencia macro
            │
            ▼
   4. Cálculo técnico          → SMA, RSI, MACD, ATR, fibs, pivots
            │
            ▼
   5. Clasificación T1-T5
            │
            ▼
   6. Detección de soportes + scoring de confluencia
            │
            ▼
   7. Filtro final             → distancia ≤ 10% + score ≥ 5.0 + gate estructural ≥2 heavies
            │
            ▼
   8. Reportes + persistencia
```

## 6. Fases del proyecto

### Fase 1 — MVP local (✅ completa)

- Estructura del proyecto ← este paso
- Data providers (Stooq + yfinance + Finnhub) con interfaz abstracta
- Universe builder
- Filtros del Paso 1
- Cálculo de indicadores técnicos
- Detección de soportes y scoring de confluencia
- Clasificación T1–T5
- Output CSV + HTML básico + SQLite
- Correr localmente con `python -m puts_screener.run`

### Fase 2 — Refinamiento

- Mini-charts en el HTML
- Métricas de calidad del screening
- Telegram bot opcional para notificación

### Fase 3 — Producción (✅ implementada, spec 05, 2026-05-27)

- GitHub Actions workflow con cron
- Publicación de HTML a GitHub Pages
- Auto-commit de outputs al repo
- Sitio publicado: https://goloop-ar.github.io/puts-screener/

### Fase 4 — Opciones (futuro)

- Integración de Paso 3 (eventos binarios completos)
- Paso 4 (strike, delta, prima, yield, gestión de salida)
- Posible integración con IBKR API
- Sustitución de HV Percentile por IV Percentile real

## 7. Glosario

| Término | Definición |
| --- | --- |
| DTE | Days To Expiration |
| T1–T5 | Tipos de situación de entrada del Paso 0 del SOP |
| Score de soporte | Score ponderado: suma del peso máximo por categoría de elemento (SMA200, polaridad, AVWAP, etc.) multiplicado por un factor de densidad [0.85, 1.5] que premia confluencias compactas. Mín. 5.0 + ≥2 elementos heavy (peso ≥2.5) para validar. Tier 1-5 derivado del score final para display (⭐ a ⭐⭐⭐⭐⭐). |
| HVN | High Volume Node — zona de alta densidad en Volume Profile |
| AVWAP | Anchored VWAP — VWAP desde un punto ancla en el tiempo |
| IV Percentile | Percentil de Implied Volatility en ventana de 52w |
| HV Percentile | Percentil de Historical Volatility (sustituto temporal) |
| Confirmador dinámico | AVWAP, HVN o divergencia RSI/MACD — requerido para validar zona |
| Polaridad | Conversión de resistencia rota en soporte futuro |
| SOP | Standard Operating Procedure — documento maestro de la estrategia |

## 8. Referencias

- Documento maestro: `SOP Venta Puts v3.docx` (fuera del repo, en el knowledge del usuario)
- Specs implementables: ver carpeta `specs/`
