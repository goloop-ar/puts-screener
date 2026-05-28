"""Modelos de la capa de reportes (spec 07): strikes heurísticos sugeridos."""

from dataclasses import dataclass


@dataclass(frozen=True)
class HeuristicStrikes:
    """Tres strikes sugeridos derivados de zona + spot + ATR.

    Redondeados a grilla típica del exchange según la divisa. No se valida
    yield ni se consulta cadena de opciones — son sugerencias para que el
    humano verifique en su broker.
    """

    aggressive: float  # cerca del spot, mayor prima, mayor probabilidad de asignación
    natural: float  # centro de la zona
    conservative: float  # lejos de la zona, menor prima, menor riesgo
    grid_unit: float  # paso de grilla usado (para debug + persistencia)
