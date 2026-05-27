"""Constantes de la capa de publicación a GitHub Pages (Fase 3, spec 05 §3).

Las constantes operativas del workflow (cron, timeout, cache keys, retries) viven en el YAML
`.github/workflows/daily-screening.yml`, no acá. Ver §3 de specs/05_github_actions_pages.md.
"""

from pathlib import Path

# === Bundle de Pages ===
PAGES_OUTPUT_DIR: Path = Path("docs-build")  # directorio temporal del bundle (gitignored)
PAGES_HISTORY_SUBDIR: str = "history"  # subdir del bundle para los archivos timestamped
PAGES_INDEX_FILENAME: str = "index.html"  # home = copia de screening_latest.html
PAGES_HISTORY_FILENAME: str = "history.html"  # índice navegable del histórico
PAGES_LATEST_CSV_FILENAME: str = "screening_latest.csv"  # CSV del último run, linkeado del index

# === Filename pattern parsing ===
# Captura (date, HHMM, ext) de los timestamped. Match estricto: ignora cualquier otro archivo
# de output/ (incluidos screening_latest.*).
REPORT_FILENAME_REGEX: str = r"^screening_(\d{4}-\d{2}-\d{2})_(\d{4})\.(html|csv)$"

# === History sort ===
HISTORY_SORT_DESCENDING: bool = True  # más reciente primero en el índice
