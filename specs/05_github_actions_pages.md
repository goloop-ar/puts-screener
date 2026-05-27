# Spec 05 — GitHub Actions cron + GitHub Pages publishing (Fase 3)

> Automatización del run diario en GitHub Actions: ejecuta el pipeline post-cierre US, persiste outputs e histórico al repo, publica latest + histórico navegable a GitHub Pages. Cierra Fase 3 del proyecto: el screener corre solo sin intervención humana, con output accesible desde browser.

## 1. Objetivo

Tres cosas que viajan juntas:

1. Workflow de GitHub Actions con cron diario que dispara el pipeline completo (`python -m puts_screener.run` sobre los tres universos) y commitea los outputs al repo.
2. Cache persistente entre runs de `data/cache/` (OHLCV provider cache) para reducir wall-time y rate-limit hits.
3. Sitio en GitHub Pages con la última corrida como home + histórico navegable autogenerado, deployado vía `actions/deploy-pages` (sin contaminar el árbol del repo con duplicados).

## 2. Scope

### En scope

- Workflow YAML en `.github/workflows/daily-screening.yml` con cron + `workflow_dispatch`.
- Cache de Actions sobre `data/cache/` con key por run_id + restore-keys de fallback.
- Script `publish_pages` que toma el contenido de `output/` y arma el bundle del sitio (latest + histórico navegable + CSVs descargables).
- Template Jinja2 nuevo para el índice del histórico (`history.html.j2`).
- Commit automático de `output/screening_*` y `data/screening_history.db` al `main` con identidad `github-actions[bot]`.
- Push con rebase + retry para evitar falla por race con push manual.
- `.gitattributes` para tratar la DB como binario.
- README breve documentando dónde está publicado el sitio y cómo correr manual el workflow.

### Fuera de scope

- **Telegram / notificaciones**: spec separada (06) una vez que Pages esté estable.
- **Finnhub en Actions**: solo yfinance por ahora. Si el skip rate se vuelve insoportable, se agrega como API key en Secrets en una iteración futura.
- **CI de tests**: pytest no corre en el workflow del cron. Si se quiere CI, va en otro workflow (`tests.yml`).
- **Retención automática del histórico**: si la DB o `output/` crece demasiado en 6 meses, se limpia manual. No hay rotación automática.
- **Auto-merge de PRs / dependabot**: fuera.
- **Filtros interactivos en el sitio publicado**: el HTML que se sirve es el mismo estático que ya genera spec 04. Interactividad va con Fase 5 (web app local).

### Decisión fundamental: dos artefactos paralelos

El repo persiste el histórico **commiteado** (`output/` + `data/screening_history.db`). El sitio en Pages republica el **mismo** histórico desde un artifact temporal. La fuente canónica es el repo; Pages es solo una vista. Esto permite:

- Backtesting futuro contra `screening_history.db` (capacidad ya prometida en backlog).
- Reset del sitio sin perder data: borrar el deploy de Pages no afecta el histórico.
- Inspección con `git log -- output/` para ver runs históricos.

## 3. Decisiones de parametrización

Constantes nuevas en `src/puts_screener/config_publishing.py` (módulo nuevo).

| Constante | Valor | Justificación |
|---|---|---|
| **Bundle de Pages** | | |
| `PAGES_OUTPUT_DIR` | `Path("docs-build")` | Directorio temporal donde se construye el bundle. Gitignored (no se commitea). |
| `PAGES_HISTORY_SUBDIR` | `"history"` | Subdirectorio del bundle para los archivos timestamped. |
| `PAGES_INDEX_FILENAME` | `"index.html"` | Home del sitio = copia de `screening_latest.html`. |
| `PAGES_HISTORY_FILENAME` | `"history.html"` | Índice navegable del histórico. |
| `PAGES_LATEST_CSV_FILENAME` | `"screening_latest.csv"` | CSV del último run, linkeado desde index para download. |
| **Filename pattern parsing** | | |
| `REPORT_FILENAME_REGEX` | `r"^screening_(\d{4}-\d{2}-\d{2})_(\d{4})\.(html\|csv)$"` | Captura `(date, HHMM, ext)` de los timestamped. Match estricto, ignora cualquier otro archivo en `output/`. |
| **History sort** | | |
| `HISTORY_SORT_DESCENDING` | `True` | Más reciente primero en el índice. |

Constantes operativas del workflow viven en el YAML, no en Python:

| Constante (YAML) | Valor | Justificación |
|---|---|---|
| `cron` | `"0 22 * * 1-5"` | 22:00 UTC, lun-vie. En DST = 18:00 ET (2h post-cierre); en winter = 17:00 ET (1h post-cierre). yfinance tiene close en ambos casos. |
| `timeout-minutes` | `45` | Provisional. Holgado contra el smoke (~15 min según baseline post-hardening universo 985). Subir si runs reales se acercan. |
| `concurrency.group` | `screening-cron` | Serializa runs. Evita race si un manual dispatch se solapa con el cron. |
| `concurrency.cancel-in-progress` | `false` | No descartar runs a la mitad. |
| `cache.key` (yfinance cache) | `"cache-yfinance-v1-${{ github.run_id }}"` | Key única por run garantiza save (cache de Actions no sobrescribe keys). |
| `cache.restore-keys` | `"cache-yfinance-v1-"` | Prefix matching: restaura el más reciente. Si se rompe el formato del cache, se bumpea `v1`→`v2` y todos los runs anteriores quedan ignorados sin tocar nada más. |
| `push.max-retries` | `3` | Suficiente para absorber race con push manual al `main`. |
| `push.retry-delay-seconds` | `5` | Pausa entre intentos. |

## 4. Modelos / dataclasses

Nuevos en `src/puts_screener/models_publishing.py`:

```python
from dataclasses import dataclass
from datetime import date
from pathlib import Path

@dataclass(frozen=True)
class HistoryEntry:
    """Una entrada del histórico parseada desde el filesystem.

    Representa un par (html, csv?) de una corrida pasada. El CSV puede no existir
    si solo se generó HTML, aunque en el pipeline actual siempre van juntos.
    """
    run_date: date
    run_time: str          # "HHMM", string, no datetime (sin segundos)
    html_filename: str     # nombre relativo dentro de output/, ej "screening_2026-05-22_2200.html"
    csv_filename: str | None  # idem; None si no hay CSV gemelo

    @property
    def display_label(self) -> str:
        """Etiqueta human-readable: '2026-05-22 22:00 UTC'."""
        ...

    @property
    def sort_key(self) -> tuple[date, str]:
        """Para ordenamiento determinista."""
        return (self.run_date, self.run_time)


@dataclass(frozen=True)
class PagesBundle:
    """Resultado de armar el bundle de Pages. Para logging y tests."""
    bundle_dir: Path
    index_html: Path
    history_html: Path
    latest_csv: Path | None
    history_entries: tuple[HistoryEntry, ...]
```

Sin cambios a modelos existentes.

## 5. APIs públicas

Módulo nuevo `src/puts_screener/publish_pages.py`. Punto de entrada: `python -m puts_screener.publish_pages [--output OUTPUT] [--bundle BUNDLE]`.

```python
def discover_history(output_dir: Path) -> list[HistoryEntry]:
    """Escanea output_dir buscando archivos que matchean REPORT_FILENAME_REGEX.

    Empareja .html con su .csv gemelo (mismo date+time). Si solo existe uno
    de los dos, igual genera HistoryEntry con el que esté presente. Ignora
    silenciosamente cualquier otro archivo (incluidos screening_latest.*).

    Returns:
        Lista ordenada según HISTORY_SORT_DESCENDING.
    """

def render_history_index(
    entries: list[HistoryEntry],
    template_path: Path,
    site_base_url: str = "",
) -> str:
    """Renderiza el HTML del índice del histórico.

    site_base_url se prepende a cada link relativo (útil para Pages servido
    desde un subpath). En default "" funciona para el root del sitio.
    """

def build_pages_bundle(
    output_dir: Path,
    bundle_dir: Path,
    *,
    template_path: Path | None = None,
    site_base_url: str = "",
) -> PagesBundle:
    """Construye el bundle completo en bundle_dir.

    Pasos:
      1. Limpia bundle_dir si existe (rm -rf) y la recrea vacía.
      2. Copia screening_latest.html → bundle_dir/index.html.
      3. Copia screening_latest.csv → bundle_dir/screening_latest.csv (si existe).
      4. discover_history(output_dir) → lista de HistoryEntry.
      5. Para cada entry: copia los archivos timestamped → bundle_dir/history/.
      6. Renderiza history.html y lo escribe en bundle_dir/.

    Returns:
        PagesBundle con paths absolutos y lista de entries procesadas.
    """

def main(argv: list[str] | None = None) -> int:
    """Entry point CLI. Returns exit code."""
```

## 6. Algoritmos paso-a-paso

### 6.1 `discover_history`

```
1. Si output_dir no existe → return [].
2. entries_by_key: dict[(date, str), dict] = {}
3. Para cada archivo en output_dir.iterdir() (no recursivo):
     a. match = re.fullmatch(REPORT_FILENAME_REGEX, archivo.name)
     b. Si no matchea → continue.
     c. (date_str, hhmm, ext) = match.groups()
     d. key = (date.fromisoformat(date_str), hhmm)
     e. entries_by_key.setdefault(key, {})[ext] = archivo.name
4. result: list[HistoryEntry] = []
   Para cada (key, files) en entries_by_key:
     result.append(HistoryEntry(
         run_date=key[0],
         run_time=key[1],
         html_filename=files.get("html"),
         csv_filename=files.get("csv"),
     ))
   Filtrar los que tengan html_filename=None (sin HTML no es entrada válida).
5. Ordenar por sort_key, reverse=HISTORY_SORT_DESCENDING.
6. Return result.
```

Edge cases:
- Archivos como `screening_latest.html` no matchean el regex (no tienen timestamp) → ignorados.
- Archivos sueltos como `notes.txt` no matchean → ignorados.
- Si hay solo .csv sin .html para una fecha → la entry se filtra en paso 4.

### 6.2 `build_pages_bundle`

```
1. Si bundle_dir existe → shutil.rmtree(bundle_dir).
2. bundle_dir.mkdir(parents=True).
3. (bundle_dir / "history").mkdir().
4. screening_latest.html en output/ → copy → bundle_dir / "index.html".
   Si no existe → log warning y crear un index.html placeholder con
   "Esperando primer run" (no levantar exception: permite deploy inicial vacío).
5. screening_latest.csv → copy → bundle_dir / "screening_latest.csv" (si existe).
6. entries = discover_history(output_dir).
7. Para cada entry en entries:
     - Copy output_dir / entry.html_filename → bundle_dir / "history" / entry.html_filename.
     - Si entry.csv_filename: copy → bundle_dir / "history" / entry.csv_filename.
8. history_html = render_history_index(entries, template_path, site_base_url).
9. Escribir history_html → bundle_dir / "history.html".
10. Return PagesBundle(...).
```

### 6.3 Template `history.html.j2`

Estructura mínima (Jinja2):

```html+jinja
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <title>Histórico — Puts Screener</title>
  <style>/* reuso de estilos de spec 04 si conviene, o algo mínimo propio */</style>
</head>
<body>
  <header>
    <h1>Histórico de corridas</h1>
    <p><a href="{{ site_base_url }}/index.html">← Volver al último run</a></p>
  </header>
  <main>
    {% if entries %}
    <table>
      <thead><tr><th>Fecha</th><th>Hora UTC</th><th>HTML</th><th>CSV</th></tr></thead>
      <tbody>
      {% for e in entries %}
        <tr>
          <td>{{ e.run_date.isoformat() }}</td>
          <td>{{ e.run_time[:2] }}:{{ e.run_time[2:] }}</td>
          <td><a href="{{ site_base_url }}/history/{{ e.html_filename }}">HTML</a></td>
          <td>{% if e.csv_filename %}<a href="{{ site_base_url }}/history/{{ e.csv_filename }}">CSV</a>{% else %}—{% endif %}</td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
    {% else %}
    <p>Sin corridas registradas todavía.</p>
    {% endif %}
  </main>
</body>
</html>
```

El template vive en `src/puts_screener/templates/history.html.j2`. Reuso del directorio actual (donde ya viven los templates de spec 04).

## 7. Workflow YAML completo

Path: `.github/workflows/daily-screening.yml`.

```yaml
name: Daily screening

on:
  schedule:
    - cron: "0 22 * * 1-5"   # 22:00 UTC lun-vie (1-2h post-cierre US según DST)
  workflow_dispatch:          # permite disparo manual desde la UI

# Required for actions/deploy-pages
permissions:
  contents: write   # commit + push de outputs
  pages: write      # deploy a Pages
  id-token: write   # OIDC para deploy-pages

concurrency:
  group: screening-cron
  cancel-in-progress: false

jobs:
  screen:
    runs-on: ubuntu-latest
    timeout-minutes: 45
    environment:
      name: github-pages
      url: ${{ steps.deploy.outputs.page_url }}

    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          fetch-depth: 0   # historial completo para rebase en push

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Restore yfinance cache
        id: cache-restore
        uses: actions/cache@v4
        with:
          path: data/cache
          key: cache-yfinance-v1-${{ github.run_id }}
          restore-keys: |
            cache-yfinance-v1-

      - name: Run screening pipeline
        run: python -m puts_screener.run --universe sp500,nasdaq100,stoxx600

      - name: Build Pages bundle
        run: python -m puts_screener.publish_pages --output output --bundle docs-build

      - name: Commit outputs and DB
        env:
          GIT_AUTHOR_NAME: "github-actions[bot]"
          GIT_AUTHOR_EMAIL: "41898282+github-actions[bot]@users.noreply.github.com"
          GIT_COMMITTER_NAME: "github-actions[bot]"
          GIT_COMMITTER_EMAIL: "41898282+github-actions[bot]@users.noreply.github.com"
        run: |
          set -euo pipefail
          git add output/screening_* data/screening_history.db
          if git diff --staged --quiet; then
            echo "No changes to commit."
          else
            git commit -m "chore(daily): screening run $(date -u +'%Y-%m-%d %H:%M UTC')"
            for attempt in 1 2 3; do
              if git pull --rebase origin main && git push origin main; then
                exit 0
              fi
              echo "Push attempt $attempt failed, retrying in 5s..."
              sleep 5
            done
            echo "All push attempts failed."
            exit 1
          fi

      - name: Upload Pages artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: docs-build

      - name: Deploy to GitHub Pages
        id: deploy
        uses: actions/deploy-pages@v4
```

Notas:
- **Orden de pasos críticos**: build del bundle ANTES de commit. Si el commit falla, igual hay artifact para deploy (Pages ve la corrida, repo no).
- **Si la corrida no produce cambios** (cron en feriado US o el screener falla sin generar nuevos archivos): no se commitea, pero el bundle se construye igual sobre el `output/` existente (más antiguo) y Pages republica idempotente. Sin daño.
- **`fetch-depth: 0`**: necesario para que `git pull --rebase` tenga referencia. Puede bajar a 1 si nunca se va a rebasear, pero el costo es mínimo en un repo de este tamaño.
- **`actions/cache@v4`**: key con `run_id` garantiza save siempre. `restore-keys` con prefix toma el más reciente. Si invalidamos el formato del cache en el futuro, bumpear `v1`→`v2` en ambas keys y los caches viejos quedan huérfanos hasta que GitHub los purgue (7 días sin uso).
- **`environment: github-pages`**: requerido por `deploy-pages`. Hay que crear el environment en Settings la primera vez (o aceptarlo del primer run).

### 7.1 Configuración manual en GitHub (one-time)

Estos pasos van al README de la spec, son humanos:

1. **Settings → Pages → Source**: `GitHub Actions` (no `Deploy from a branch`).
2. **Settings → Actions → General → Workflow permissions**: `Read and write permissions` (ya cubierto por `permissions:` del workflow, pero el toggle global tiene que estar habilitado).
3. **Settings → Environments → github-pages**: aceptar el environment cuando el primer run lo cree, o crearlo a mano.

## 8. Persistencia

### 8.1 Cambios en el repo

| Archivo | Cambio | Razón |
|---|---|---|
| `data/screening_history.db` | Empieza a estar trackeado | Decisión §1: histórico commiteado para backtesting. |
| `output/screening_*` | Empiezan a estar trackeados | Idem. |
| `.gitattributes` | Nuevo archivo | Marcar la DB como binario (evita diffs ruidosos). |
| `.gitignore` | Sumar `docs-build/` | Bundle temporal, no se commitea. |

### 8.2 `.gitattributes` (nuevo)

```
*.db binary
*.parquet binary
```

(El `.parquet` ya es relevante por el provider cache, aunque hoy esté gitignored. Anticipa el caso si en algún momento se commitea data parqueteada para snapshots.)

### 8.3 `.gitignore` (delta)

Agregar al final:

```
# Pages bundle temporal (regenerable por publish_pages)
docs-build/
```

### 8.4 Esquema SQLite

Sin cambios. La DB existente se commitea tal cual.

## 9. Tests

### 9.1 Unit (`tests/test_publish_pages.py`)

- `test_discover_history_empty_dir`: directorio vacío → `[]`.
- `test_discover_history_only_latest`: solo `screening_latest.html` y `screening_latest.csv` → `[]` (no matchean el regex).
- `test_discover_history_paired_html_csv`: 3 pares timestamped → 3 entries, ordenadas descendente.
- `test_discover_history_html_only`: HTML timestamped sin CSV gemelo → entry con `csv_filename=None`.
- `test_discover_history_csv_only`: CSV timestamped sin HTML gemelo → entry filtrada (no aparece).
- `test_discover_history_ignores_garbage`: archivos arbitrarios (`notes.txt`, `screening_invalid.html`, etc.) → ignorados.
- `test_render_history_index_with_entries`: smoke del template render con 2 entries → HTML válido contiene los timestamps.
- `test_render_history_index_empty`: lista vacía → HTML con "Sin corridas registradas".
- `test_build_pages_bundle_full`: directorio temp con latest + 2 timestamped → bundle armado correcto (estructura de archivos + content de index.html).
- `test_build_pages_bundle_no_latest`: sin `screening_latest.html` → placeholder, no exception.
- `test_build_pages_bundle_clean_rebuild`: bundle_dir preexistente con basura → se limpia antes de rebuild.

### 9.2 Smoke test manual

Antes del primer push del workflow, validar local:

```bash
# Asumiendo output/ poblado con runs reales:
python -m puts_screener.publish_pages --output output --bundle docs-build
# Verificar:
ls docs-build/                    # index.html, history.html, history/, screening_latest.csv
ls docs-build/history/            # los timestamped que estuvieran en output/
python -m http.server -d docs-build 8000
# Abrir http://localhost:8000 — debe renderizar el HTML del último run.
# Abrir http://localhost:8000/history.html — debe listar las corridas con links funcionales.
```

### 9.3 Workflow

No se testea automáticamente (no hay CI del CI). Validación humana:

1. Primer `workflow_dispatch` manual desde la UI.
2. Verificar que el job termine verde, los outputs aparezcan commiteados, y Pages publique.
3. Después de eso, esperar al primer cron real (próximo día hábil 22:00 UTC).

## 10. Criterios de aceptación

- [ ] `.github/workflows/daily-screening.yml` existe, valida con `actionlint` (si está instalado) sin errores.
- [ ] `src/puts_screener/publish_pages.py` con las 3 funciones públicas + `main` + entry point `__main__`.
- [ ] `src/puts_screener/models_publishing.py` con `HistoryEntry` + `PagesBundle`.
- [ ] `src/puts_screener/config_publishing.py` con las constantes de §3.
- [ ] `src/puts_screener/templates/history.html.j2` renderiza correctamente con Jinja2.
- [ ] `.gitattributes` y `.gitignore` actualizados.
- [ ] Los 11 tests de §9.1 pasan en verde.
- [ ] Smoke local (§9.2) genera bundle correcto.
- [ ] README actualizado con: link al sitio publicado (cuando esté), instrucciones para disparar manual el workflow, instrucciones one-time de configuración GitHub (§7.1).
- [ ] Primer `workflow_dispatch` manual completa verde, commitea outputs, y Pages publica el sitio accesible vía browser.
- [ ] Primer cron real (día hábil siguiente) completa verde sin intervención.
- [ ] Total de tests del proyecto suben sin que ninguno se rompa (de 372 a 383).

## 11. Archivos a crear / modificar

```
puts-screener/
├── .github/
│   └── workflows/
│       └── daily-screening.yml          [NEW]
├── .gitattributes                       [NEW]
├── .gitignore                           [MOD: + docs-build/]
├── README.md                            [MOD: sección Fase 3]
├── data/
│   └── screening_history.db             [NEW en tracking — no nuevo en disco]
├── output/
│   ├── screening_latest.html            [NEW en tracking]
│   ├── screening_latest.csv             [NEW en tracking]
│   └── screening_*_*.{html,csv}         [NEW en tracking, append por run]
├── specs/
│   └── 05_github_actions_pages.md       [NEW — esta spec]
├── src/puts_screener/
│   ├── config_publishing.py             [NEW]
│   ├── models_publishing.py             [NEW]
│   ├── publish_pages.py                 [NEW]
│   └── templates/
│       └── history.html.j2              [NEW]
└── tests/
    └── test_publish_pages.py            [NEW]
```

11 archivos nuevos, 3 modificados. Sin tocar lógica de pipeline existente.

## 12. Decisiones registradas

- **2026-05-22 — Pages servido vía `actions/deploy-pages` con artifact**: descartadas las alternativas `docs/` commiteado en `main` y rama `gh-pages` dedicada. El bundle vive en `docs-build/` (gitignored, temporal) y se sube como artifact en cada run. Mantiene el árbol del repo limpio (output/ es fuente canónica, no se duplica) y es el patrón actual recomendado por GitHub para sitios estáticos sin SSR.
- **2026-05-22 — Cache de OHLCV con `actions/cache@v4`, key por `run_id` + `restore-keys` prefix**: garantiza save (key única evita conflict) + restaura el más reciente (prefix matching). Invalidación manual del cache se hace bumpeando la versión en el key (`v1`→`v2`). No hay invalidación por TTL desde Actions porque el provider ya tiene su propia lógica de TTL en disco.
- **2026-05-22 — DB commiteada al repo + `.gitattributes` para tratarla como binario**: habilita backtesting futuro contra el propio histórico del screening (ya prometido en backlog §4). Aceptado el trade-off de crecimiento monotónico de la DB; estimado <100KB/run, manejable por años antes de necesitar rotación.
- **2026-05-22 — Histórico navegable autogenerado en `history.html`, no en el repo**: el HTML se construye en cada deploy desde los archivos de `output/`. El template vive en `src/puts_screener/templates/`; el script en `publish_pages.py`. Reuso de Jinja2 (ya en deps por spec 04). Sin un módulo dedicado, el histórico solo sería accesible vía `git log`, perdiendo el valor de Pages.
- **2026-05-22 — Cron en 22:00 UTC lun-vie**: cubre el cierre US en ambas mitades del año (DST = 18:00 ET, winter = 17:00 ET). yfinance tiene el close en ambos casos. Sin manejo explícito de feriados US: en feriado, el output será similar al del día previo, no hay daño (los flags binarios y zonas se recalculan pero el OHLCV es idéntico).
- **2026-05-22 — Telegram diferido a spec 06**: la spec inicial ya tiene superficie significativa (workflow + Pages + caching + commit automático + permisos). Telegram entra una vez que el ciclo automático esté validado en producción.
- **2026-05-22 — Finnhub no en Actions inicialmente**: skip rate 38.5% post-hardening con yfinance solo es aceptable. Si se vuelve problema, sumarlo es un PR chico (API key en Secrets + flag en el step de `run`). No bloqueante para Fase 3.
- **2026-05-22 — Sin CI de tests en este workflow**: el `daily-screening.yml` es de producción, no CI. Si se quiere CI, va en `tests.yml` separado. Mezclar tests + run productivo en el mismo workflow alarga el wall-time del cron sin razón (los tests ya corren local pre-commit).
- **2026-05-22 — `timeout-minutes: 45` provisional**: holgado contra el smoke esperado (~15 min según baseline post-hardening). Subir si runs reales se acercan al techo. Bajar es premature optimization.
- **2026-05-22 — Filename pattern parsing con regex estricto**: solo archivos que matchean `screening_YYYY-MM-DD_HHMM.(html|csv)` entran al histórico. Cualquier otro archivo en `output/` (incluido `screening_latest.*` y archivos manualmente colocados ahí) es ignorado. Robusto a basura sin requerir cleanup explícito.
- **Anotación factual (no decisión)**: el timestamp de los nombres es `datetime.now()` (local), que en Actions corre UTC. En el histórico del repo todos los runs del cron van a tener `_2200`. Runs manuales locales mezclados van a tener timestamps locales. No es ambiguo (la fecha resuelve), no es bloqueante. Si en el futuro molesta, cambiar a UTC explícito en `config_reports.REPORT_FILENAME_PATTERN` lo resuelve con una línea.
