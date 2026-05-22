"""Constantes parametrizables de la capa de reportes y eventos binarios (Paso 3, spec 04).

Cambiar un valor acá NO requiere tocar lógica. Ver §3 de specs/04_reports_binary_events.md.
"""

from pathlib import Path

# === Ventanas de eventos (DTE) ===
EVENTS_WINDOW_DAYS: int = 45  # ventana general del SOP Paso 3 (30-45 DTE)
EARNINGS_WINDOW_DAYS: int = 45  # earnings dentro de 45 días forward
EX_DIV_WINDOW_DAYS: int = 45  # ex-dividend dentro de 45 días forward
MACRO_WINDOW_DAYS: int = 45  # eventos macro dentro de 45 días forward

# === Reportes ===
REPORT_OUTPUT_DIR: Path = Path("output")  # destino de CSVs y HTMLs (se crea si no existe)
REPORT_FILENAME_PATTERN: str = "screening_{date}_{time}"  # sufijo timestamp evita sobrescritura
REPORT_LATEST_FILENAME: str = "screening_latest"  # copia de la última corrida para acceso rápido

# === Card en HTML ===
HTML_MAX_ELEMENTS_PER_CARD: int = 8  # si la zona tiene más, mostrar top 8 por puntos + "+N más"

# === Orden de cards ===
TYPE_PRIORITY: dict[str, int] = {"T1": 1, "T2": 2, "T4": 3, "T3": 4, "T5": 5}  # prioridad SOP §0
