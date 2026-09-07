"""Modelos de la capa de reportes: strikes heurísticos y estructurales sugeridos."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class HeuristicStrikes:
    """Tres strikes sugeridos derivados de zona + spot + ATR (spec 07).

    Redondeados a grilla típica del exchange según la divisa. No se valida
    yield ni se consulta cadena de opciones — son sugerencias para que el
    humano verifique en su broker.
    """

    aggressive: float  # cerca del spot, mayor prima, mayor probabilidad de asignación
    natural: float  # centro de la zona
    conservative: float  # lejos de la zona, menor prima, menor riesgo
    grid_unit: float  # paso de grilla usado (para debug + persistencia)


StrikeVariant = Literal["A", "B", "C", "D", "E", "F"]
# A/B/C (spec 11 §3.3): permiten que aggressive quede DENTRO de la zona (ancla al heavy más
# alto o al center_price). D/E/F (tanda 2, corrida post-backtest): los 3 niveles quedan en o
# debajo de lower_bound, para que "el precio entró a la zona" y "se perforó aggressive" dejen
# de ser casi el mismo evento.


@dataclass(frozen=True)
class StructuralStrikes:
    """Tres strikes anclados a elementos de soporte reales (spec 11 §3.3/§6.5)."""

    aggressive: float
    natural: float
    conservative: float
    grid_unit: float
    anchor_kind: Literal["heavy_element", "zone_bound", "fallback_atr"]
    aggressive_anchor: str | None  # etiqueta del elemento ancla, ej. "sma_200w"
    conservative_anchor: str | None
    variant: StrikeVariant
