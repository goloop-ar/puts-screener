"""Dataclasses del análisis de soportes (Paso 2 del SOP).

`SupportLevel`, `SupportZone` y `SupportAnalysis` son inmutables (frozen). `SupportedCandidate`
envuelve por composición al `ScreenedCandidate` del Paso 1 y NO es frozen, espejando a
`ScreenedCandidate` (los pasos posteriores pueden anotarlo).
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from puts_screener.models_screening import ScreenedCandidate


@dataclass(frozen=True)
class SupportLevel:
    """Un nivel de soporte individual aportado por uno de los 7 elementos del score."""

    price: float
    element: str  # "sma_200w" | "ema_200d" | "fib_618" | ... (ver §5 de la spec 03)
    points: int  # SMA200=2, resto=1
    metadata: dict = field(default_factory=dict)  # info auxiliar (fecha del pivot ancla, etc.)
    # Soporte (price < spot) vs resistencia (price ≥ spot). Solo los soporte entran al clustering.
    side: Literal["support", "resistance"] = "support"


@dataclass(frozen=True)
class SupportZone:
    """Cluster de SupportLevel cercanos (± 0.5×ATR14) con su score de confluencia."""

    center_price: float  # mediana de los precios de los elementos
    lower_bound: float  # center - 0.5×ATR14
    upper_bound: float  # center + 0.5×ATR14
    score: int  # suma de points con dedup por categoría (§6.3)
    elements: list[SupportLevel]  # elementos que componen la zona
    has_dynamic_confirmer: bool  # True si tiene avwap, hvn o divergence
    distance_pct: float  # (spot - center_price) / spot


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
