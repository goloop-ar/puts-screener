# Puts Screener

Automatización del screening diario de acciones para venta sistemática de puts en mercados US y Europa.

Ver [`SPEC.md`](SPEC.md) para detalles del proyecto y [`CLAUDE.md`](CLAUDE.md) para reglas de desarrollo.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuración

Copiá `.env.example` a `.env` y completá las variables si tenés las API keys:

```powershell
Copy-Item .env.example .env
```

Variables soportadas:

- `FINNHUB_API_KEY`: API key de Finnhub. Si está vacía, el provider de Finnhub se desactiva automáticamente y los métodos que dependen solo de él (analyst data, rating changes) no van a estar disponibles. Free tier: https://finnhub.io
- `CACHE_DISABLED`: `0` (default) o `1` para desactivar todo el cache. Útil para debugging.

## Smoke test de providers

Para validar que los providers están funcionando contra APIs reales (no es un test de pytest, es un script manual):

```powershell
.\.venv\Scripts\python.exe -m puts_screener.smoke_test_providers
```

Hace llamadas reales a Stooq, Yahoo Finance y (si hay key) Finnhub, sobre los tickers `AAPL`, `NVDA`, `ASML.AS`, `NESN.SW`, e imprime una tabla con el resultado por método.

## Uso

```bash
python -m puts_screener.run
```

Outputs en `output/` y `data/`.

## Estado

En desarrollo activo. Fase 1 (MVP local).
