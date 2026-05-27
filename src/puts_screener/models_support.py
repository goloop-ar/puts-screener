"""Dataclasses del análisis de soportes (Paso 2 del SOP).

`SupportLevel`, `SupportZone` y `SupportAnalysis` son inmutables (frozen). `SupportedCandidate`
envuelve por composición al `ScreenedCandidate` del Paso 1 y NO es frozen, espejando a
`ScreenedCandidate` (los pasos posteriores pueden anotarlo).
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from puts_screener.config_supports import (
    ELEMENT_WEIGHTS,
    HEAVY_ELEMENT_WEIGHT_THRESHOLD,
    SCORE_TIER_THRESHOLDS,
)
from puts_screener.models_screening import ScreenedCandidate


@dataclass(frozen=True)
class SupportLevel:
    """Un nivel de soporte individual aportado por uno de los 7 elementos del score."""

    price: float
    element: str  # "sma_200w" | "ema_200d" | "fib_618" | ... (ver §5 de la spec 03)
    metadata: dict = field(default_factory=dict)  # info auxiliar (fecha del pivot ancla, etc.)
    # Soporte (price < spot) vs resistencia (price ≥ spot). Solo los soporte entran al clustering.
    side: Literal["support", "resistance"] = "support"
    # Vestigial (Etapa 4): el peso real vive en ELEMENT_WEIGHTS keyed por `element`. Se conserva
    # por compatibilidad de persistencia (elements_json). Default 0.0; algunos tests lo setean.
    points: float = 0.0


@dataclass(frozen=True)
class SupportZone:
    """Cluster de SupportLevel; bounds = envelope real de los elementos ± buffer (spec 06)."""

    center_price: float  # centro del envelope: (lower_bound + upper_bound) / 2
    lower_bound: float  # min(precios del cluster) - buffer
    upper_bound: float  # max(precios del cluster) + buffer
    score: float  # score_base (suma max-por-categoría) × density_multiplier (spec 06)
    elements: list[SupportLevel]  # elementos que componen la zona
    has_dynamic_confirmer: bool  # True si tiene avwap, hvn o divergence
    distance_pct: float  # (spot - upper_bound) / spot — contra el borde superior real (spec 06)

    @property
    def width(self) -> float:
        """Ancho de la zona en unidades de precio."""
        return self.upper_bound - self.lower_bound

    @property
    def width_pct(self) -> float:
        """Ancho de la zona como fracción del center_price."""
        return self.width / self.center_price if self.center_price > 0 else 0.0

    @property
    def n_heavy_elements(self) -> int:
        """Cantidad de elementos individuales con peso >= HEAVY_ELEMENT_WEIGHT_THRESHOLD."""
        return sum(
            1
            for e in self.elements
            if ELEMENT_WEIGHTS.get(e.element, 0.0) >= HEAVY_ELEMENT_WEIGHT_THRESHOLD
        )

    @property
    def score_tier(self) -> int:
        """Tier 1-5 derivado del score final (capa de presentación)."""
        for tier in sorted(SCORE_TIER_THRESHOLDS.keys(), reverse=True):
            if self.score >= SCORE_TIER_THRESHOLDS[tier]:
                return tier
        return 1  # piso (zona válida tiene score >= 5.0 = tier 1)


@dataclass(frozen=True)
class SupportAnalysis:
    """Resultado del análisis de soportes de un candidato (§7.3)."""

    valid_zones: list[SupportZone]  # zonas que pasaron las 3 reglas de §7.1
    rejected_zones: list[tuple[SupportZone, str]]  # zona + motivo de rechazo
    best_zone: SupportZone | None  # primera de valid_zones según orden de §7.2


@dataclass
class SupportedCandidate:
    """Candidato del Paso 1 enriquecido con el análisis de soportes del Paso 2.

    Composición, no herencia: mantiene el output del Paso 1 inmutable y accesible
    vía `supported.screened.ticker`, etc.
    """

    screened: ScreenedCandidate
    analysis: SupportAnalysis
    pasa_paso_2: bool  # True si analysis.best_zone is not None
    fetched_at: datetime = field(default_factory=datetime.now)
    errors: list[str] = field(default_factory=list)  # errores no fatales del análisis
