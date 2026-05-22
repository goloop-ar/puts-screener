"""Dataclasses del screening: clasificación y candidato con indicadores."""

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from puts_screener.providers.models import (
    AnalystData,
    CompanyProfile,
    EarningsEvent,
    FinancialSnapshot,
    HistoricalEarningsEvent,
    RatingChange,
)


@dataclass(frozen=True)
class TypeClassification:
    """Resultado de la clasificación T1–T4."""

    tipo: str | None  # "T1", "T2", "T3", "T4", o None si no califica
    justificacion: str
    matches_multiple: list[str] = field(default_factory=list)


@dataclass
class ScreenedCandidate:
    """Candidato del screening con toda la data y los indicadores computados.

    NO es frozen: los filtros mutan `pasa_filtros_paso_1` y `motivos_rechazo`.
    """

    # Identidad
    ticker: str

    # Data cruda (de providers)
    profile: CompanyProfile
    financials: FinancialSnapshot
    analyst: AnalystData
    rating_changes_6w: list[RatingChange]
    upcoming_earnings: EarningsEvent | None
    earnings_history: list[HistoricalEarningsEvent]
    ohlcv_daily: pd.DataFrame
    ohlcv_weekly: pd.DataFrame

    # Clasificación
    classification: TypeClassification | None = None

    # Indicadores técnicos (computados)
    spot: float = 0.0
    sma_50w: float = 0.0
    sma_200w: float = 0.0
    rsi_d: float = 0.0
    rsi_d_3d_ago: float = 0.0
    rsi_w: float = 0.0
    rsi_w_2w_ago: float = 0.0
    macd_state: str = "neutral"
    macd_hist_3d_ago: float = 0.0
    momentum_score: int = 0  # 0-3: cuenta señales positivas. Informativo, no filtra.
    atr_14: float = 0.0
    hv_percentile_52w: float = 0.0

    # Métricas de valoración
    price_target_upside_pct: float = 0.0
    recommendation_buy_ratio: float = 0.0
    downgrades_6w_count: int = 0

    # Resultado del filtrado
    pasa_filtros_paso_1: bool = False
    motivos_rechazo: list[str] = field(default_factory=list)

    # Pertenencia a universos (tupla ordenada alfabéticamente, ej. ("nasdaq100", "sp500"))
    universes: tuple[str, ...] = ()

    # Señales informativas de momentum (Etapa 4): "rsi"/"macd"/"both" si la best_zone tiene
    # divergencia. No filtra; distinto de `momentum_score` (int del Paso 1).
    momentum_signals: tuple[str, ...] = ()

    # Metadatos
    fetched_at: datetime = field(default_factory=datetime.now)
    errors: list[str] = field(default_factory=list)
