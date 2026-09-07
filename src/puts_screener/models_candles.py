"""Dataclasses de señales de velas dentro de zonas de soporte (spec 11 §4)."""

from dataclasses import dataclass
from typing import Literal

import pandas as pd

CandleKind = Literal[
    "wick_rejection",
    "body_reclaim_piercing",
    "body_reclaim_engulfing",
    "body_reclaim_morning_star",
    "bearish_engulfing",
    "bearish_dark_cloud",
    "bearish_momentum",
]

CandleDirection = Literal["bullish", "bearish"]


@dataclass(frozen=True)
class CandleSignal:
    """Patrón de vela detectado dentro (o al borde) de una zona de soporte validada."""

    kind: CandleKind
    direction: CandleDirection
    bar_date: pd.Timestamp
    bars_ago: int  # 0 = última barra
    body_atr: float  # tamaño del cuerpo en unidades de ATR14
    lower_wick_ratio: float  # mecha inferior / cuerpo (guardado contra div~0)
    upper_wick_ratio: float  # mecha superior / cuerpo (guardado contra div~0)
    in_zone: bool  # True si el valor de referencia cayó dentro de [lower, upper]
    distance_to_zone_atr: float  # 0.0 si in_zone; si no, distancia en ATR al borde más cercano


@dataclass(frozen=True)
class CandleAnalysis:
    """Resultado de evaluar los 3 detectores sobre una zona en la ventana de lookback."""

    signals: tuple[CandleSignal, ...]
    has_bullish_confirmation: bool  # ≥1 wick_rejection o body_reclaim_*
    has_bearish_breakdown: bool  # ≥1 bearish_*
    strongest_bullish: CandleSignal | None
