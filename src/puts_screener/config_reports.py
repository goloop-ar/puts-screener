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

# === Score tier labels (spec 06 §3.3; thresholds en config_supports.SCORE_TIER_THRESHOLDS) ===
SCORE_TIER_LABELS: dict[int, tuple[str, str]] = {
    5: ("⭐⭐⭐⭐⭐", "Confluencia excepcional"),
    4: ("⭐⭐⭐⭐", "Fuerte"),
    3: ("⭐⭐⭐", "Sólida"),
    2: ("⭐⭐", "Borderline"),
    1: ("⭐", "Mínimo viable"),
}

# === Currency display (spec 06 §3.4) ===
# divisor reservado para futuro (GBp→GBP sería 100); hoy 1 en todos.
CURRENCY_DISPLAY: dict[str, dict] = {
    "USD": {"prefix": "$", "suffix": "", "divisor": 1},
    "EUR": {"prefix": "€", "suffix": "", "divisor": 1},
    "GBP": {"prefix": "£", "suffix": "", "divisor": 1},
    "GBp": {"prefix": "", "suffix": "p", "divisor": 1},  # peniques: magnitud tal cual + sufijo p
    "CHF": {"prefix": "", "suffix": " CHF", "divisor": 1},
    "JPY": {"prefix": "¥", "suffix": "", "divisor": 1},
    "DKK": {"prefix": "", "suffix": " kr", "divisor": 1},
    "SEK": {"prefix": "", "suffix": " kr", "divisor": 1},
    "NOK": {"prefix": "", "suffix": " kr", "divisor": 1},
}
# fallback si currency es None o no está en CURRENCY_DISPLAY
CURRENCY_DEFAULT: dict = {"prefix": "$", "suffix": "", "divisor": 1}

# === Jurisdicción por tipo de evento macro (spec 06 §6.5) ===
JURISDICTION_BY_KIND: dict[str, str] = {
    "fomc": "US",
    "cpi": "US",
    "ppi": "US",
    "nfp": "US",
    "gdp": "US",
    "other": "—",
}
