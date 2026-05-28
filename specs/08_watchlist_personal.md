# Spec 08 — Watchlist personal

> Archivo local con tickers personales que se mergean al universo evaluado. Permite trackear nombres fuera de los tres universos predefinidos (sp500, nasdaq100, stoxx600): IPOs recientes, mid-caps, picks especulativos. La watchlist NO bypasea los gates del SOP — solo extiende qué tickers se evalúan; los criterios de filtrado siguen siendo los mismos para todos.

## 1. Objetivo

Sumar un cuarto universo, `watchlist`, alimentado por un archivo de texto local (`data/watchlist.txt`, gitignored). Los tickers de la watchlist:

- Se incluyen en el universo cuando se pasa `--universe watchlist` (solo o combinado con otros universos).
- Pasan por los mismos filtros del Paso 1, Paso 2 y Paso 3 que el resto.
- Cuando pasan todos los gates, aparecen en el reporte con un badge `watchlist` adicional al lado del ticker.
- Si un ticker de watchlist coincide con uno ya presente en otro universo (ej. CRWV en watchlist + sp500), se evalúa una sola vez y el badge `watchlist` se **suma** a los demás badges (pipe-separated en CSV/persistencia, badge visual en HTML).

## 2. Scope

### En scope

- Lectura de `data/watchlist.txt` con parsing tolerante (comentarios, líneas vacías, case-insensitive).
- Nuevo valor `watchlist` para el flag `--universe` (ya existente, acepta CSV).
- Mergeo del watchlist al diccionario `{ticker: set(universos)}` que ya maneja `universe_builder` (Etapa 1 del rework de scoring).
- Badge `watchlist` en HTML cards (mismo estilo que sp500/nasdaq100/stoxx600).
- Columna CSV `universes` ya existente (pipe-separated) recibe el tag `watchlist` adicional cuando aplica.
- `data/watchlist.txt` agregado a `.gitignore`.
- `data/watchlist.txt.example` commiteado con plantilla comentada.
- Manejo robusto de archivo faltante / corrupto (warnings, no fatal).
- Tests: parsing del archivo, mergeo con otros universos, dedup correcto, propagación del tag.

### Fuera de scope

- **Validación de tickers contra Wikipedia/oficiales**: si el usuario pone `XXXXX`, yfinance va a fallar al fetch y el ticker aparece como `motivo_de_rechazo: data_fetch_failed`. Feedback natural sin lógica de validación adicional.
- **Sección "watchlist rechazados"** en el reporte HTML mostrando los tickers de watchlist que no pasaron filtros con sus motivos. La info se persiste en SQLite (`universe.motivo_de_rechazo` ya existe), renderearla es feature adicional. YAGNI por ahora.
- **Override de gates del SOP** para forzar que watchlist siempre aparezca. Decisión deliberada: la watchlist solo extiende el universo, no relaja filtros (ver §11).
- **Múltiples archivos de watchlist** (ej. `watchlist_us.txt`, `watchlist_eu.txt`). Un solo archivo es suficiente para uso personal.
- **Sincronización entre máquinas**: el archivo es local. Si querés sincronizarlo entre máquinas, usá un mecanismo aparte (Dropbox, gist privado, sync manual).
- **TTL / refresh del cache de watchlist**: el archivo se lee fresh cada run, sin cache (es un .txt chico).

## 3. Decisiones de parametrización

Constantes nuevas en `src/puts_screener/config_filters.py` (módulo del universe builder).

| Constante | Valor | Justificación |
|---|---|---|
| `WATCHLIST_FILE_PATH` | `Path("data/watchlist.txt")` | Path relativo al working dir. Convención: `data/` ya alberga archivos de configuración local (macro_calendar.yaml, screening_history.db). |
| `WATCHLIST_UNIVERSE_TAG` | `"watchlist"` | Tag para el diccionario `{ticker: set(universos)}` y para badges/CSV. Mismo formato que los demás (lowercase, sin espacios). |
| `WATCHLIST_COMMENT_PREFIX` | `"#"` | Líneas que empiezan con `#` se ignoran. |

## 4. Modelos / dataclasses

Sin modelos nuevos. La watchlist es solo una fuente de strings (tickers) que se mergean al diccionario existente.

## 5. APIs públicas

```python
# universe_builder.py (extensión)

def load_watchlist(
    file_path: Path = WATCHLIST_FILE_PATH,
) -> set[str]:
    """Lee data/watchlist.txt y devuelve set de tickers normalizados a uppercase.

    Returns:
        Set de tickers. Vacío si el archivo no existe (con warning logueado).

    Comportamiento:
    - Líneas vacías → ignoradas.
    - Líneas que empiezan con '#' → ignoradas (comentarios).
    - Líneas con espacios → strip y normalizadas a uppercase.
    - Líneas con caracteres no válidos para un ticker (espacios internos,
      caracteres no alfanuméricos excepto '.', '-', '/') → warning + skip.
    """

def build_universe(
    universes: list[str],
    refresh: bool = False,
    watchlist_path: Path = WATCHLIST_FILE_PATH,
) -> dict[str, set[str]]:
    """(Existente, extendida) Si 'watchlist' está en la lista de universes,
    mergear los tickers del archivo.

    El resto del comportamiento permanece igual: cada ticker mapea a un set
    de universos a los que pertenece; los duplicados entre universos se
    dedupean automáticamente con el set merge.
    """
```

`load_watchlist` es función nueva. `build_universe` se extiende con el parámetro opcional `watchlist_path` (default usa la constante) y la rama nueva para procesar `"watchlist"` cuando viene en `universes`.

## 6. Algoritmo

### 6.1 Parsing de `data/watchlist.txt`

```
load_watchlist(file_path):
    if not file_path.exists():
        logger.warning(f"{file_path} no encontrado, watchlist vacía")
        return set()

    tickers = set()
    invalid_lines = 0
    with open(file_path, encoding="utf-8") as f:
        for line_num, raw in enumerate(f, start=1):
            line = raw.strip()

            # Skip vacías y comentarios
            if not line: continue
            if line.startswith(WATCHLIST_COMMENT_PREFIX): continue

            # Validar formato
            candidate = line.upper()
            if not _is_valid_ticker(candidate):
                logger.warning(
                    f"{file_path}:{line_num} ticker inválido '{line}', omitido"
                )
                invalid_lines += 1
                continue

            tickers.add(candidate)

    logger.info(
        f"Watchlist cargada: {len(tickers)} tickers de {file_path} "
        f"({invalid_lines} líneas inválidas omitidas)"
    )
    return tickers

_is_valid_ticker(s):
    # Permitir letras, dígitos, punto (para .L, .DE, etc.), guión, barra.
    # Sin espacios internos.
    if not s: return False
    if " " in s or "\t" in s: return False
    if not all(c.isalnum() or c in ".-/" for c in s): return False
    return True
```

### 6.2 Mergeo en `build_universe`

```
build_universe(universes, refresh=False, watchlist_path=WATCHLIST_FILE_PATH):
    result: dict[str, set[str]] = {}

    for u in universes:
        if u == "sp500":
            tickers = _fetch_sp500(refresh=refresh)
            for t in tickers: result.setdefault(t, set()).add("sp500")
        elif u == "nasdaq100":
            tickers = _fetch_nasdaq100(refresh=refresh)
            for t in tickers: result.setdefault(t, set()).add("nasdaq100")
        elif u == "stoxx600":
            tickers = _fetch_stoxx600(refresh=refresh)
            for t in tickers: result.setdefault(t, set()).add("stoxx600")
        elif u == "watchlist":
            tickers = load_watchlist(watchlist_path)
            for t in tickers: result.setdefault(t, set()).add("watchlist")
        else:
            raise ValueError(f"Universo desconocido: {u}")

    return result
```

El comportamiento de dedup ya existe (es lo que la Etapa 1 del rework de scoring estableció): un ticker presente en sp500 + watchlist queda como `{"sp500", "watchlist"}` automáticamente por el `set.add`.

## 7. Persistencia y reportes

### 7.1 Persistencia

Sin cambios al schema. La columna `candidates.universes_json` ya existe (spec post-Etapa 1 del rework de scoring) y serializa el set de universos como JSON list ordenada alfabéticamente. Los tickers de watchlist quedan con `["watchlist"]` o `["sp500", "watchlist"]` etc. según corresponda.

### 7.2 CSV

Sin cambios. La columna `universes` ya existe (pipe-separated, ordenada alfabéticamente). Ejemplos de valores:

- `watchlist` (ticker solo en watchlist)
- `sp500|watchlist` (ticker en ambos)
- `nasdaq100|sp500|watchlist` (en los tres)

### 7.3 HTML

Sin cambios al template más allá de heredar el mecanismo existente: el bloque `{% for u in c.universes %}<span class="universe-badge">{{ u }}</span>{% endfor %}` ya renderiza un badge por universo. Al sumar `"watchlist"` al set, automáticamente aparece un badge `watchlist` al lado de los demás.

**Decisión de estilo del badge:** mismo estilo que los badges existentes (fondo gris `#e2e5ea`, texto `#44505f`, font-size 0.7rem, peso 600). Sin distinción visual adicional. El usuario sabe que es suyo el ticker — no necesita resaltado.

Si en el futuro se quiere destacar `watchlist` con color distinto, es un cambio CSS de una línea (`.universe-badge.watchlist { background: #fef3c7; }` por ejemplo). Diferido hasta que se justifique.

## 8. Tests

### 8.1 `tests/test_watchlist.py` (nuevo, ~10)

Tests deterministas con archivos temporales (`tmp_path` fixture de pytest).

- `test_load_watchlist_typical`: archivo con 5 tickers válidos, un comentario, una línea vacía → set con los 5 tickers normalizados a uppercase.
- `test_load_watchlist_missing_file`: file_path inexistente → set vacío, warning logueado.
- `test_load_watchlist_lowercase_normalized`: archivo con `crwv\nbarc.l\n` → `{"CRWV", "BARC.L"}`.
- `test_load_watchlist_dedup_within_file`: archivo con `CRWV\ncrwv\nCRWV\n` → `{"CRWV"}` (set dedupea).
- `test_load_watchlist_comments_ignored`: líneas que arrancan con `#` → omitidas.
- `test_load_watchlist_empty_lines_ignored`: líneas vacías y solo whitespace → omitidas.
- `test_load_watchlist_invalid_ticker_skipped`: línea con espacios internos (`A B`) o caracteres raros (`A@B`) → omitida con warning, otras válidas se mantienen.
- `test_load_watchlist_european_tickers`: `BARC.L`, `ABI.BR`, `ASML.AS` → todos cargados (los puntos son válidos).
- `test_load_watchlist_empty_file`: archivo existe pero vacío → set vacío sin warnings.
- `test_load_watchlist_only_comments`: archivo solo con líneas de comentario → set vacío.

### 8.2 `tests/test_universe_builder.py` (extender, +5)

Reusar fixtures existentes y mockeos de `_fetch_sp500` / `_fetch_nasdaq100` / `_fetch_stoxx600`.

- `test_build_universe_watchlist_only`: `build_universe(["watchlist"], watchlist_path=tmp)` con archivo de 3 tickers → dict con 3 entradas, cada una con `{"watchlist"}`.
- `test_build_universe_watchlist_combined_with_sp500`: 3 tickers de watchlist, sp500 mockeado con 2 tickers (uno coincide) → dict con 4 entradas; el coincidente tiene `{"sp500", "watchlist"}`, los demás tienen uno solo.
- `test_build_universe_unknown_universe_raises`: `build_universe(["foo"])` → `ValueError`.
- `test_build_universe_watchlist_missing_file_returns_empty_set`: pasar `--universe watchlist` con archivo inexistente → dict vacío, warning logueado, sin excepción.
- `test_build_universe_watchlist_dedup_across_universes`: ticker T1 en watchlist + sp500 + nasdaq100 mockeados → dict tiene T1 una sola vez con `{"sp500", "nasdaq100", "watchlist"}`.

### 8.3 `tests/test_reports_csv.py` (extender, +1)

- `test_csv_universes_column_includes_watchlist`: candidato con `universes=("sp500", "watchlist")` → fila CSV columna `universes` contiene `"sp500|watchlist"` (ordenada alfabéticamente).

### 8.4 `tests/final/test_reports_html.py` (extender, +1)

- `test_html_renders_watchlist_badge`: candidato con `"watchlist"` en universes → HTML contiene `<span class="universe-badge">watchlist</span>`.

### 8.5 Smoke test manual

```bash
# 1. Crear data/watchlist.txt con un puñado de tickers (mezcla US + EU)
cat > data/watchlist.txt << 'EOF'
# Watchlist de prueba
CRWV
ARM
BARC.L
EOF

# 2. Correr screener con --universe watchlist (solo watchlist, rápido)
python -m puts_screener.run --universe watchlist

# 3. Verificar en output/screening_latest.html:
#    - Si alguno pasa los filtros, aparece con badge "watchlist" al lado del ticker.
#    - Si ninguno pasa, el reporte queda con 0 cards (esperado y correcto).

# 4. Combinado:
python -m puts_screener.run --universe sp500,watchlist --limit 50
# Verificar que tickers de sp500 aparecen sin badge watchlist, y si CRWV/ARM/BARC
# pasaran, aparecerían con badge watchlist.
```

## 9. Criterios de aceptación

- [ ] `load_watchlist` existe en `universe_builder.py` con la firma de §5.
- [ ] `build_universe` acepta `"watchlist"` como universo y lo mergea correctamente.
- [ ] `config_filters.py` tiene `WATCHLIST_FILE_PATH`, `WATCHLIST_UNIVERSE_TAG`, `WATCHLIST_COMMENT_PREFIX`.
- [ ] `.gitignore` agrega `data/watchlist.txt`.
- [ ] `data/watchlist.txt.example` commiteado con plantilla de uso.
- [ ] ~17 tests nuevos en verde. Total sube de 436 a ~453 sin romper ninguno existente.
- [ ] Smoke manual (§8.5) funciona end-to-end.
- [ ] Archivo `data/watchlist.txt` inexistente no rompe el run (warning + sigue).

## 10. Archivos a crear / modificar

```
puts-screener/
├── .gitignore                                [MOD: + data/watchlist.txt]
├── data/
│   └── watchlist.txt.example                 [NEW]
├── specs/
│   └── 08_watchlist_personal.md              [NEW — esta spec]
├── src/puts_screener/
│   ├── config_filters.py                     [MOD: + 3 constantes]
│   └── universe_builder.py                   [MOD: + load_watchlist + rama "watchlist" en build_universe]
└── tests/
    ├── test_universe_builder.py              [MOD: + 5 tests]
    ├── test_watchlist.py                     [NEW]
    ├── test_reports_csv.py                   [MOD: + 1 test]
    └── final/
        └── test_reports_html.py              [MOD: + 1 test]
```

1 archivo nuevo en src/, 2 modificados. 1 spec nueva. 1 archivo nuevo en data/ (example), 1 .gitignore modificado. 2 tests nuevos, 3 modificados.

## 11. Decisiones registradas

- **2026-05-28 — Spec 08, mismo gate del SOP para watchlist**: la watchlist solo extiende qué tickers se evalúan; NO bypasea filtros del Paso 1/2/3. Razón: mantener la propiedad "todo lo que aparece en el reporte es accionable según el SOP". Si CRWV no tiene zona válida hoy, no querés operarlo igual. Descartado el comportamiento alternativo "watchlist siempre aparece" por mezclar responsabilidades (universo = qué evaluar; SOP = criterios de calidad).
- **2026-05-28 — Spec 08, sin sección "rechazados de watchlist" en HTML**: feature adicional para mostrar tickers de watchlist evaluados pero no pasados, con motivo. La info ya se persiste (`universe.motivo_de_rechazo`), pero renderearla es trabajo adicional sin demanda comprobada. YAGNI hasta que el usuario lo pida explícitamente tras 2-3 semanas de uso.
- **2026-05-28 — Spec 08, badge `watchlist` mismo estilo que los demás**: gris neutro, sin destaque visual especial. El usuario sabe que es suyo el ticker, no necesita resaltarse. Reversible con 1 línea de CSS si se justifica.
- **2026-05-28 — Spec 08, archivo gitignored + ejemplo commiteado**: la watchlist es personal. Patrón estándar de configuración local (igual que `.env`). El `.example` permite a otros clones (o un futuro yo en otra máquina) ver la convención sin imponer una lista específica.
- **2026-05-28 — Spec 08, sin validación de tickers contra fuentes oficiales**: yfinance falla naturalmente con tickers inválidos (`data_fetch_failed`), y eso ya se persiste con motivo. Agregar validación previa duplicaría lógica sin valor.
- **2026-05-28 — Spec 08, parsing tolerante (comments, vacías, case-insensitive)**: el archivo es editado a mano por humano. Soportar comentarios permite organizar la lista. Líneas inválidas se skipean con warning, no abortan el run.
- **2026-05-28 — Spec 08, lectura fresh cada run (sin cache)**: el archivo es chico (decenas de líneas), parsearlo cuesta microsegundos. Cachear introduciría problemas de stale data si el usuario lo edita entre runs.
- **2026-05-28 — Spec 08, valor `"watchlist"` para el flag `--universe`**: integración natural con el mecanismo existente (que ya acepta CSV). Default sigue siendo `sp500`; sin breaking change para usuarios actuales del flag.
