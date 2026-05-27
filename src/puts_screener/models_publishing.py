"""Dataclasses de la capa de publicación a GitHub Pages (Fase 3, spec 05 §4)."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class HistoryEntry:
    """Una entrada del histórico parseada desde el filesystem.

    Representa un par (html, csv?) de una corrida pasada. El CSV puede no existir si solo se
    generó HTML, aunque en el pipeline actual siempre van juntos.
    """

    run_date: date
    run_time: str  # "HHMM", string, no datetime (sin segundos)
    html_filename: str  # nombre relativo dentro de output/, ej "screening_2026-05-22_2200.html"
    csv_filename: str | None  # idem; None si no hay CSV gemelo

    @property
    def display_label(self) -> str:
        """Etiqueta human-readable: '2026-05-22 22:00 UTC'."""
        return f"{self.run_date.isoformat()} {self.run_time[:2]}:{self.run_time[2:]} UTC"

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
