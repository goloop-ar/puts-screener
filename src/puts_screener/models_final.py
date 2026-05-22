"""Modelo del candidato final: SupportedCandidate + eventos binarios del Paso 3 (§6 spec 04)."""

from dataclasses import dataclass
from datetime import datetime

from puts_screener.binary_events import BinaryEventsReport
from puts_screener.models_support import SupportedCandidate


@dataclass
class FinalCandidate:
    """Candidato del Paso 2 enriquecido con el reporte de eventos binarios del Paso 3.

    Composición sobre herencia (espeja `SupportedCandidate` → `ScreenedCandidate`). El Paso 3
    NO filtra (decisión §2): `passes_all_steps` depende solo de Pasos 1 y 2.
    """

    supported: SupportedCandidate
    binary_events: BinaryEventsReport
    fetched_at: datetime
    errors: list[str]

    @property
    def ticker(self) -> str:
        return self.supported.screened.ticker

    @property
    def passes_all_steps(self) -> bool:
        """True si pasó Paso 1 Y Paso 2. El Paso 3 NO filtra (decisión §2)."""
        return self.supported.pasa_paso_2
