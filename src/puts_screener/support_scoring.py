"""Validación y ranking de zonas de soporte (Paso 2 del SOP, §7 de la spec 03).

`analyze_supports` orquesta el análisis completo de un candidato: pivots → 7 elementos →
clustering → validación + selección de la mejor zona. `validate_and_rank` aísla la lógica
de §7.1/§7.2 para que sea testeable con zonas construidas a mano.
"""

import pandas as pd

from puts_screener.config_supports import (
    ELEMENT_WEIGHTS,
    HEAVY_ELEMENT_WEIGHT_THRESHOLD,
    MAX_DISTANCE_TO_SUPPORT_PCT,
    MIN_DISTANCE_TO_SUPPORT_PCT,
    MIN_HEAVY_ELEMENTS,
    SCORE_MIN_VALID,
    ZONE_MIN_DISTANCE_PCT,
)
from puts_screener.indicators import atr_series, macd_hist_series, rsi_daily_series
from puts_screener.models_screening import ScreenedCandidate
from puts_screener.models_support import SupportAnalysis, SupportLevel, SupportZone
from puts_screener.pivots import detect_pivots
from puts_screener.providers.service import DataService
from puts_screener.support_elements import (
    avwap_levels,
    divergence_levels,
    fib_levels,
    gap_levels,
    hvn_levels,
    polarity_levels,
    sma_50_levels,
    sma_200_levels,
)
from puts_screener.zone_clustering import _element_category, cluster_into_zones

# Motivos de rechazo literales (consistentes con persistencia y reportes).
REASON_LOW_SCORE = f"score < {SCORE_MIN_VALID}"
REASON_NO_CONFIRMER = "sin confirmador dinámico"
REASON_OUT_OF_RANGE = "fuera de rango de proximidad (>10% o por encima del spot)"


def _last_earnings_date(candidate: ScreenedCandidate) -> pd.Timestamp | None:
    """Fecha del earnings pasado más reciente (del historial). None si no hay."""
    if not candidate.earnings_history:
        return None
    latest = max(candidate.earnings_history, key=lambda e: e.date)
    return pd.Timestamp(latest.date)


def _num_categories(zone: SupportZone) -> int:
    return len({_element_category(e.element) for e in zone.elements})


def _rejection_reasons(zone: SupportZone) -> list[str]:
    """Motivos por los que la zona NO es válida (vacío si pasa las 4 reglas de §7.1).

    Orden: score → confirmador dinámico → distancia máxima/rango → distancia mínima.
    """
    reasons: list[str] = []
    if zone.score < SCORE_MIN_VALID:
        reasons.append(REASON_LOW_SCORE)
    if not zone.has_dynamic_confirmer:
        reasons.append(REASON_NO_CONFIRMER)
    if not (MIN_DISTANCE_TO_SUPPORT_PCT <= zone.distance_pct <= MAX_DISTANCE_TO_SUPPORT_PCT):
        reasons.append(REASON_OUT_OF_RANGE)
    if zone.distance_pct < ZONE_MIN_DISTANCE_PCT:
        reasons.append(
            f"zona muy cerca del spot ({zone.distance_pct:.1%} < "
            f"{ZONE_MIN_DISTANCE_PCT:.0%}), no accionable para 30-45 DTE"
        )
    heavy = [
        e
        for e in zone.elements
        if ELEMENT_WEIGHTS.get(e.element, 0.0) >= HEAVY_ELEMENT_WEIGHT_THRESHOLD
    ]
    if len(heavy) < MIN_HEAVY_ELEMENTS:
        reasons.append(
            f"solo {len(heavy)} elementos peso >= {HEAVY_ELEMENT_WEIGHT_THRESHOLD} "
            f"(requeridos {MIN_HEAVY_ELEMENTS})"
        )
    return reasons


def validate_and_rank(zones: list[SupportZone]) -> SupportAnalysis:
    """Separa zonas válidas de rechazadas y elige la mejor (§7.1, §7.2).

    Orden de la mejor zona: score desc, distance_pct asc, nº de categorías distintas desc.
    """
    valid_zones: list[SupportZone] = []
    rejected_zones: list[tuple[SupportZone, str]] = []
    for zone in zones:
        reasons = _rejection_reasons(zone)
        if reasons:
            rejected_zones.append((zone, " | ".join(reasons)))
        else:
            valid_zones.append(zone)

    valid_zones.sort(key=lambda z: (-z.score, z.distance_pct, -_num_categories(z)))
    best_zone = valid_zones[0] if valid_zones else None
    return SupportAnalysis(
        valid_zones=valid_zones, rejected_zones=rejected_zones, best_zone=best_zone
    )


def _compute_all_levels(candidate: ScreenedCandidate) -> tuple[list[SupportLevel], float, float]:
    """Calcula pivots + los 7 elementos. Devuelve (levels, atr14_today, spot)."""
    ohlcv = candidate.ohlcv_daily
    atr_s = atr_series(ohlcv)
    pivots = detect_pivots(ohlcv, atr_s)
    spot = candidate.spot
    rsi_s = rsi_daily_series(ohlcv)
    macd_s = macd_hist_series(ohlcv)
    last_earnings = _last_earnings_date(candidate)

    levels: list[SupportLevel] = []
    levels += sma_200_levels(ohlcv, candidate.ohlcv_weekly, spot)
    levels += sma_50_levels(ohlcv, spot)
    levels += polarity_levels(ohlcv, pivots, spot)
    levels += fib_levels(ohlcv, pivots, spot)
    levels += avwap_levels(ohlcv, pivots, last_earnings, spot)
    levels += hvn_levels(ohlcv, spot)
    levels += gap_levels(ohlcv, spot)
    levels += divergence_levels(ohlcv, pivots, rsi_s, macd_s, spot)
    return levels, float(atr_s.iloc[-1]), spot


def analyze_supports(candidate: ScreenedCandidate, data_service: DataService) -> SupportAnalysis:
    """Pipeline completo de análisis de soportes para un candidato (§7.3).

    `data_service` se acepta por firma de la spec; toda la data necesaria ya vive en el
    candidato (OHLCV, earnings_history), así que actualmente no se usa.
    """
    levels, atr14_today, spot = _compute_all_levels(candidate)
    zones = cluster_into_zones(levels, atr14_today, spot)
    analysis = validate_and_rank(zones)

    # Señal informativa (Etapa 4): divergencia de la best_zone, NO suma al score.
    best = analysis.best_zone
    candidate.momentum_signals = (
        tuple(
            e.metadata.get("oscillator", "divergence")
            for e in best.elements
            if e.element == "divergence"
        )
        if best is not None
        else ()
    )
    return analysis
