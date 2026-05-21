# SPEC — Puts Screener

> Automatización del screening diario de acciones para venta sistemática de puts, basada en el documento `SOP Venta Puts v3`.

## 1. Propósito

Identificar diariamente acciones de mercados US y Europa que cumplan los criterios definidos en los Pasos 0, 1 y 2 del SOP, y producir un reporte rankeado de candidatos para revisión humana.

## 2. Scope

### Incluido (fase actual)

- Paso 0: Clasificación de situación de entrada (T1–T5)
- Paso 1: Screening (Calidad, Liquidez del subyacente, Tendencia macro, Valoración, Momento técnico)
- Paso 2: Identificación de soportes y scoring de confluencia
- Filtro final: precio actual dentro del 10% de un soporte con score ≥ 3
- Output: CSV detallado + HTML report top 20 + persistencia SQLite

### Excluido por ahora (fases futuras)

- Paso 3: Check de eventos binarios completo
- Paso 4: Selección de strike, delta, prima, yield, gestión de salida
- Todo lo relacionado a opciones (IV, IV Percentile, Greeks, cadena)
- Ejecución de órdenes

### Sustitución temporal

El filtro de IV Percentile (52w) del SOP se reemplaza en esta fase por **HV Percentile (52w)** calculado desde OHLCV puro. Cuando se integre data de opciones, se reemplaza por IV real.

## 3. Stack tecnológico

- Python 3.11+
- Fuentes de datos (stack free, diseñado para swap):
  - **OHLCV histórico**: Stooq (primario, estable), yfinance (fallback)
  - **Fundamentals (Market Cap, FCF, sector)**: yfinance (primario), Finnhub (complementario)
  - **Analistas + Earnings**: Finnhub free tier (60 req/min)
- Cálculos técnicos: pandas-ta + lógica propia
- Persistencia: SQLite local (committed al repo)
- Reportes: HTML estático + CSV
- Orquestación final: GitHub Actions con cron diario post-cierre US (Fase 3)

### Diseño para swap

Todas las fuentes de data se implementan detrás de una interfaz abstracta `DataProvider`. La lógica de negocio nunca llama directo a yfinance/Stooq/Finnhub. Esto permite migrar a EODHD, FMP, fiscal.ai o IBKR en el futuro sin reescribir nada.

## 4. Output esperado

Por cada corrida diaria:

### 4.1 CSV detallado (`output/screening_YYYY-MM-DD.csv`)

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

### 4.2 HTML report (`output/screening_YYYY-MM-DD.html`)

Top 20 rankeado por score de soporte desc + prioridad de tipo (T1 > T2 > T4 > T3 > T5). Para cada candidato:

- Card con ticker, sector, tipo T, score, precio spot, distancia a soporte
- Justificación textual de por qué califica
- Idealmente: mini-chart de precio diario últimos 6 meses con zona de soporte sombreada (puede ir a Fase 2)

### 4.3 Persistencia SQLite (`data/screening_history.db`)

Tablas:

- `runs` — `run_id`, `timestamp`, `universo_size`, `candidates_count`, `status`
- `candidates` — `run_id`, `ticker`, todos los campos del CSV
- `universe` — `run_id`, `ticker`, `motivo_de_rechazo` (opcional, debugging)

## 5. Arquitectura general

```
GitHub Actions cron (22:00 ART L-V)
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
   7. Filtro final             → distancia ≤ 10% + score ≥ 3
            │
            ▼
   8. Reportes + persistencia
```

## 6. Fases del proyecto

### Fase 1 — MVP local (actual)

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

### Fase 3 — Producción

- GitHub Actions workflow con cron
- Publicación de HTML a GitHub Pages
- Auto-commit de outputs al repo

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
| Score de soporte | Puntuación de confluencia en una zona (mín. 3 para validar) |
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
