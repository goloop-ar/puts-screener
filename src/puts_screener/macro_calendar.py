"""Carga del calendario macro (eventos FOMC/CPI/etc.) desde YAML. Ver §4 de spec 04.

El archivo `data/macro_calendar.yaml` se mantiene a mano. Esta capa solo lo parsea y valida.
"""

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal, get_args

import yaml

logger = logging.getLogger(__name__)

MacroKind = Literal["fomc", "cpi", "ppi", "nfp", "gdp", "other"]
_VALID_KINDS: frozenset[str] = frozenset(get_args(MacroKind))

_DEFAULT_CALENDAR_PATH = Path("data/macro_calendar.yaml")


@dataclass(frozen=True)
class MacroEvent:
    """Un evento macro conocido (fecha + tipo + descripción legible)."""

    date: date
    kind: MacroKind
    description: str


def load_macro_calendar(path: Path = _DEFAULT_CALENDAR_PATH) -> list[MacroEvent]:
    """Carga el calendario macro desde YAML.

    - Archivo inexistente → `[]` con `logging.warning` (el caller decide si es problema).
    - Archivo vacío o sin `events` (o `events` vacío) → `[]` sin warning.

    Raises:
        ValueError: si el YAML está malformado, si un `kind` no es válido, o si una `date`
            no parsea como ISO YYYY-MM-DD.
    """
    if not path.exists():
        logger.warning("Macro calendar file not found at %s", path)
        return []

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"Macro calendar YAML malformed: {exc}") from exc

    if not raw:
        return []
    entries = raw.get("events")
    if not entries:
        return []

    events: list[MacroEvent] = []
    for entry in entries:
        kind = entry["kind"]
        if kind not in _VALID_KINDS:
            raise ValueError(
                f"Macro calendar: invalid kind {kind!r} (valid: {sorted(_VALID_KINDS)})"
            )
        # PyYAML autoconvierte fechas ISO a `date`; str() + fromisoformat normaliza ambos casos
        # (date ya parseado o string suelto) y deja que fromisoformat valide el formato.
        event_date = date.fromisoformat(str(entry["date"]))
        events.append(
            MacroEvent(date=event_date, kind=kind, description=entry.get("description", ""))
        )
    return events
