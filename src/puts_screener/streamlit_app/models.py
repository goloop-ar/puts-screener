"""Dataclasses puros para la app Streamlit (spec 09 §X — tanda 1).

Inmutables (frozen) y sin dependencia de streamlit / plotly. Pensados para ser
construidos por `data_loader` y filtrados por `filters`. La vista los renderiza
sin transformaciones adicionales.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from puts_screener.models_support import SupportZone


@dataclass(frozen=True)
class RunSummary:
    """Metadatos de un run para listar en el selector."""

    run_id: str
    started_at: datetime
    finished_at: datetime | None
    universe_size: int
    candidates_passed: int
    universes: tuple[str, ...]

    @property
    def display_label(self) -> str:
        """Etiqueta human-readable: '2026-05-28 17:24 — 50 candidatos (sp500+nasdaq100)'.

        Si `universes` está vacía, omite el paréntesis.
        """
        ts = self.started_at.strftime("%Y-%m-%d %H:%M")
        base = f"{ts} — {self.candidates_passed} candidatos"
        if not self.universes:
            return base
        return f"{base} ({'+'.join(self.universes)})"


@dataclass(frozen=True)
class CandidateRow:
    """Fila resumida de un candidato para la lista filtrable.

    Campos derivados del JOIN candidates ⨝ support_zones(is_best=1). Para
    candidates con `pasa_paso_2=1` pero sin best_zone (edge case), los tres
    `best_zone_*` quedan en None.
    """

    ticker: str
    tipo_T: str
    spot: float
    sector: str
    country: str
    momentum_score: int
    universes: tuple[str, ...]
    best_zone_score: float | None
    best_zone_tier: int | None
    best_zone_distance_pct: float | None
    earnings_en_45d: bool
    ex_div_en_45d: bool
    tiene_eventos_macro_en_45d: bool
    strike_natural: float | None
    currency: str


@dataclass(frozen=True)
class CandidateDetail:
    """Detalle completo de un candidato para la vista de chart + tabla."""

    row: CandidateRow
    best_zone: "SupportZone | None"
    spot: float
    sma_50w: float | None
    sma_200w: float | None
    rsi_d: float | None
    rsi_w: float | None
    atr_14: float | None
    hv_percentile_52w: float | None
    market_cap: float | None
    earnings_date: date | None
    ex_div_date: date | None
    ex_div_amount: float | None
    eventos_macro: tuple[dict, ...]
    strikes: dict[str, float | None]
    flags_legibles: tuple[str, ...]
    momentum_signals: tuple[str, ...]
