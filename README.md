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

## Fase 3 — Producción (GitHub Actions + Pages)

El screening corre solo en GitHub Actions (cron diario post-cierre US) y publica el resultado a
GitHub Pages: el último run como home + un histórico navegable. Workflow:
[`.github/workflows/daily-screening.yml`](.github/workflows/daily-screening.yml). Detalle en
[`specs/05_github_actions_pages.md`](specs/05_github_actions_pages.md).

### Correr el workflow manualmente

En GitHub: pestaña **Actions** → workflow **Daily screening** → botón **Run workflow** (usa el
trigger `workflow_dispatch`). El cron automático corre a las **22:00 UTC, lunes a viernes**
(1-2 h post-cierre US según DST).

### Configuración one-time en GitHub (§7.1 de la spec)

Una sola vez, en **Settings** del repo:

1. **Pages → Source**: elegir `GitHub Actions` (NO `Deploy from a branch`).
2. **Actions → General → Workflow permissions**: `Read and write permissions` (el toggle global
   tiene que estar habilitado; el workflow ya declara los `permissions:` que necesita).
3. **Environments → `github-pages`**: aceptar/crear el environment cuando el primer run lo cree.

### Dónde queda el sitio

El sitio está publicado en `https://goloop-ar.github.io/puts-screener/`. `index.html` es el último
run; `history.html` lista el histórico con links a cada corrida (HTML + CSV).

El histórico canónico vive **commiteado en el repo** (`output/screening_*` + `data/screening_history.db`);
Pages es solo una vista que se reconstruye en cada deploy desde `output/` vía
`python -m puts_screener.publish_pages`.

## Fase 5 — App local (solo-lectura)

Web app local para exploración interactiva de los runs persistidos en
`screening_history.db`. No re-ejecuta el pipeline — es una capa de
visualización sobre los artefactos ya generados.

### Cómo correrla

```bash
.venv/Scripts/python.exe -m streamlit run src/puts_screener/streamlit_app/app.py
```

O en macOS/Linux:

```bash
.venv/bin/python -m streamlit run src/puts_screener/streamlit_app/app.py
```

Streamlit abre el navegador automáticamente en http://localhost:8501.

### Qué muestra

- Sidebar: selector de run (default = último) + filtros por tier, sector,
  score mínimo y eventos binarios.
- Tabla principal de candidatos del run elegido.
- Vista de detalle por candidato: chart interactivo con candlestick + MAs
  (SMA200W, EMA200D, SMA50D) + zona de soporte sombreada + spot + strikes,
  datos del Paso 1/2/3 y strikes heurísticos.

## Estado

En desarrollo activo. Fase 1 (MVP local) completa; Fase 3 (automatización + Pages) en
implementación.
