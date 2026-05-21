# CLAUDE.md — Reglas operativas del proyecto

> Este archivo te da el contexto del proyecto. Leelo siempre antes de empezar cualquier tarea.

## Antes de cualquier trabajo

1. Leé `SPEC.md` para entender visión, scope, output esperado y vocabulario.
2. Si la tarea está asociada a una spec específica en `specs/NN_xxx.md`, leéla completa.
3. Si algo no está claro o ambiguo, **preguntá antes de codear**. No asumas.

## Stack y versiones

- Python 3.11+
- Package manager: `pip` con `venv` estándar (no poetry/uv salvo que el usuario lo pida explícitamente)
- Testing: `pytest`
- Linting + format: `ruff` (todo-en-uno)
- Core data: `pandas`, `numpy`
- Indicadores técnicos: `pandas-ta`
- HTTP: `requests`
- Templating HTML: `jinja2` (cuando llegue el momento)

## Estructura del proyecto

```
puts-screener/
├── SPEC.md
├── CLAUDE.md
├── README.md
├── requirements.txt
├── specs/               # Specs implementables, una por feature
├── src/puts_screener/   # Todo el código de la app vive acá
├── tests/               # Tests con pytest, espejando src/
├── data/                # SQLite + caches (se commitea)
└── output/              # CSVs y HTMLs generados (se commitea)
```

Nada de código de aplicación en la raíz.

## Reglas de código

- Type hints en funciones públicas siempre que se pueda.
- Docstrings cortos en funciones no triviales, estilo Google.
- No comentarios obvios. Comentar el "por qué", no el "qué".
- Una función = una responsabilidad. Si pasa de 40 líneas, partila.
- Imports al tope agrupados: stdlib, third-party, local.
- No magic numbers. Constantes con nombre.
- Manejo de errores explícito en llamadas a APIs externas (timeouts, retries, fallbacks).

## Reglas de testing

- Cada feature nueva viene con tests.
- Tests en `tests/`, espejando estructura de `src/`.
- Tests deterministas: usar fixtures con data fija, no llamadas live a APIs.
- Para APIs externas: mockear con `responses` o `pytest-mock`.
- Correr tests: `pytest -v` desde la raíz.
- Cobertura objetivo: lógica de negocio crítica (scoring, clasificación, detección de soportes) debe estar testeada.

## Datos sensibles

- API keys NUNCA en el código.
- Desarrollo local: `.env` con `python-dotenv`. `.env` debe estar en `.gitignore`.
- En GitHub Actions: GitHub Secrets.

## Convención de commits

Conventional commits:

- `feat: add Stooq OHLCV provider`
- `fix: handle missing FCF in yfinance response`
- `refactor: extract pivot detection module`
- `test: add support scoring tests`
- `chore: bump pandas-ta`
- `docs: update SPEC with phase 2 scope`

Un commit = un cambio lógico. No commits gigantes mezclando cosas.

## Cuándo preguntar antes de actuar

- Instalar dependencias nuevas que no están en `requirements.txt`
- Modificar `SPEC.md` o `CLAUDE.md`
- Crear archivos fuera del scope de la tarea actual
- Refactors grandes que tocan múltiples módulos
- Cambiar interfaces ya usadas por otros módulos
- Borrar archivos

## Cuándo NO preguntar (avanzá directo)

- Implementar lo que pide la spec actual
- Agregar tests
- Fix de typos en docstrings/comentarios
- Formatear con ruff

## Principio de diseño clave

Todas las fuentes de data van detrás de una clase abstracta `DataProvider`. La lógica de negocio (scoring, clasificación, filtros) nunca llama directo a yfinance/Stooq/Finnhub. Esto se define formalmente en `specs/01_data_providers.md`.

## Al terminar una tarea, reportá

- Qué hiciste (resumen 2-3 líneas)
- Archivos creados/modificados (lista)
- Cómo testear lo hecho (comando concreto)
- Decisiones que tomaste y por qué (si aplica)
- Cosas que quedaron pendientes o ambiguas

## Comandos útiles

```bash
# Setup inicial (primera vez)
python -m venv .venv
source .venv/bin/activate         # macOS/Linux
# .venv\Scripts\activate          # Windows
pip install -r requirements.txt

# Tests
pytest -v

# Formato + lint
ruff format src/ tests/
ruff check src/ tests/

# Correr el screener (cuando exista)
python -m puts_screener.run
```
