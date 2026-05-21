"""Clasificación T1–T4 según el Paso 0 del SOP.

La función pública `classify(candidate)` recibe un ScreenedCandidate ya
populado con OHLCV, earnings_history e indicadores computados, y devuelve
un TypeClassification con el tipo asignado (o None) + justificación.

Decisión de firma: la spec 02 §6.1 define
`classify(ticker, ohlcv_daily, ohlcv_weekly, earnings_history, indicators)`, pero
como el ScreenedCandidate ya tiene todos esos campos adentro, usamos la firma
natural `classify(candidate)` — mismo patrón que los filtros del Paso 1 §7.1.

Prioridad de tipos cuando hay match múltiple: T1 > T2 > T4 > T3.
"""

import logging
from datetime import date, timedelta

import pandas as pd

from puts_screener.config_filters import (
    T2_DROP_PCT_5D,
    T3_LATERAL_DAYS,
    T3_LATERAL_TOLERANCE,
    T3_PRICE_FLOOR_FRACTION,
    T3_RANGE_COMPACTNESS,
    T4_DROP_THRESHOLD,
    T4_LOOKBACK_DAYS,
    T4_RSI_MAX,
    T4_TOLERANCIA_TENDENCIA,
)
from puts_screener.models_screening import ScreenedCandidate, TypeClassification

logger = logging.getLogger(__name__)

_PRIORITY_ORDER: tuple[str, ...] = ("T1", "T2", "T4", "T3")
_T2_MIN_DAYS = 6


def _check_t1(candidate: ScreenedCandidate) -> tuple[bool, str]:
    """T1 — Uptrend con soporte.

    Criterios (§6.2):
    - SMA50W > SMA200W (tendencia alcista confirmada).
    - close > SMA200W (precio por encima del soporte de largo plazo).

    El momento técnico se chequea en el filtro de momentum del Paso 1, no acá.
    """
    if candidate.sma_50w <= candidate.sma_200w:
        return False, "SMA50W no > SMA200W"
    if candidate.spot <= candidate.sma_200w:
        return False, "spot no > SMA200W"
    return True, (
        f"SMA50W ({candidate.sma_50w:.2f}) > SMA200W ({candidate.sma_200w:.2f}); "
        f"spot ({candidate.spot:.2f}) > SMA200W"
    )


def _check_t2(candidate: ScreenedCandidate) -> tuple[bool, str]:
    """T2 — Pánico / IV spike.

    Criterios (§6.2):
    - Caída ≥ T2_DROP_PCT_5D (default -10%) en últimos 5 días hábiles.
    - SMA50W > SMA200W o lateral_tolerable (no bajista).

    Usamos el MÁX de los últimos 5 días (excluyendo el actual) como referencia.
    """
    close = candidate.ohlcv_daily["Close"]
    if len(close) < _T2_MIN_DAYS:
        return False, "OHLCV insuficiente para T2 (<6 días)"

    close_today = float(close.iloc[-1])
    close_max_5d = float(close.iloc[-6:-1].max())
    drop_pct = (close_today / close_max_5d) - 1

    if drop_pct > T2_DROP_PCT_5D:
        return False, f"caída {drop_pct:.1%} no alcanza el threshold {T2_DROP_PCT_5D:.1%}"

    is_uptrend = candidate.sma_50w > candidate.sma_200w
    is_lateral = (
        abs(candidate.sma_50w - candidate.sma_200w) / candidate.sma_200w <= T3_LATERAL_TOLERANCE
    )
    if not (is_uptrend or is_lateral):
        return False, "tendencia bajista (SMA50W << SMA200W)"

    return True, f"caída {drop_pct:.1%} ≥ {T2_DROP_PCT_5D:.1%} y tendencia no bajista"


def _check_t3(candidate: ScreenedCandidate) -> tuple[bool, str]:
    """T3 — Rango lateral.

    Criterios (§6.2):
    - lateral_tolerable: |SMA50W - SMA200W| / SMA200W ≤ T3_LATERAL_TOLERANCE (3%).
    - Lateralización ≥ T3_LATERAL_DAYS (60d): (max - min) / mean ≤ T3_RANGE_COMPACTNESS (15%).
    - Precio cerca del piso: close < min + T3_PRICE_FLOOR_FRACTION * (max - min).
    """
    if candidate.sma_200w <= 0:
        return False, "SMA200W inválido"

    lateral_tolerance = abs(candidate.sma_50w - candidate.sma_200w) / candidate.sma_200w
    if lateral_tolerance > T3_LATERAL_TOLERANCE:
        return False, f"no lateral (tolerance {lateral_tolerance:.1%} > {T3_LATERAL_TOLERANCE:.1%})"

    close = candidate.ohlcv_daily["Close"]
    if len(close) < T3_LATERAL_DAYS:
        return False, f"OHLCV insuficiente para T3 (<{T3_LATERAL_DAYS} días)"

    window = close.iloc[-T3_LATERAL_DAYS:]
    rng_min = float(window.min())
    rng_max = float(window.max())
    rng_mean = float(window.mean())
    if rng_mean <= 0:
        return False, "rango con mean ≤ 0 (data anómala)"

    compactness = (rng_max - rng_min) / rng_mean
    if compactness > T3_RANGE_COMPACTNESS:
        return False, f"rango no compacto ({compactness:.1%} > {T3_RANGE_COMPACTNESS:.1%})"

    floor_threshold = rng_min + T3_PRICE_FLOOR_FRACTION * (rng_max - rng_min)
    if candidate.spot >= floor_threshold:
        return False, f"spot ({candidate.spot:.2f}) lejos del piso ({floor_threshold:.2f})"

    return True, (
        f"lateral {lateral_tolerance:.1%}, rango compacto {compactness:.1%}, "
        f"spot {candidate.spot:.2f} cerca del piso {rng_min:.2f}"
    )


def _check_t4(candidate: ScreenedCandidate) -> tuple[bool, str]:
    """T4 — Post-earnings dip.

    Criterios (§6.2):
    - Hubo earnings en últimos T4_LOOKBACK_DAYS días (60).
    - Caída post-earnings ≤ T4_DROP_THRESHOLD (-5%): close del día siguiente vs día previo.
    - SMA50W ≥ SMA200W * T4_TOLERANCIA_TENDENCIA (0.97) — no bajista.
    - RSI_d < T4_RSI_MAX (55) — zona neutral-baja.
    """
    if not candidate.earnings_history:
        return False, "sin earnings históricos"

    today = date.today()
    cutoff = today - timedelta(days=T4_LOOKBACK_DAYS)
    recent_earnings = [e for e in candidate.earnings_history if cutoff <= e.date <= today]
    if not recent_earnings:
        return False, f"sin earnings en últimos {T4_LOOKBACK_DAYS} días"

    last_earnings_date = max(e.date for e in recent_earnings)
    close = candidate.ohlcv_daily["Close"]
    earnings_ts = pd.Timestamp(last_earnings_date)

    pre_mask = close.index < earnings_ts
    if not pre_mask.any():
        return False, "sin OHLCV pre-earnings"
    close_pre = float(close[pre_mask].iloc[-1])

    post_mask = close.index > earnings_ts
    if not post_mask.any():
        return False, "sin OHLCV post-earnings"
    close_post = float(close[post_mask].iloc[0])

    drop_pct = (close_post - close_pre) / close_pre
    if drop_pct > T4_DROP_THRESHOLD:
        return False, f"caída post-earnings {drop_pct:.1%} no alcanza {T4_DROP_THRESHOLD:.1%}"

    if candidate.sma_50w < candidate.sma_200w * T4_TOLERANCIA_TENDENCIA:
        return False, "tendencia bajista (SMA50W << SMA200W * 0.97)"

    if candidate.rsi_d >= T4_RSI_MAX:
        return False, f"RSI_d ({candidate.rsi_d:.1f}) ≥ {T4_RSI_MAX}"

    return True, (
        f"earnings {last_earnings_date} dropeó {drop_pct:.1%} "
        f"(pre {close_pre:.2f} → post {close_post:.2f}); RSI_d {candidate.rsi_d:.1f}"
    )


def classify(candidate: ScreenedCandidate) -> TypeClassification:
    """Clasifica el candidato en T1–T4 según los criterios del Paso 0 del SOP.

    Returns:
        TypeClassification con tipo ("T1".."T4" o None), justificación legible y
        `matches_multiple` (otros tipos que también matchearon, para auditoría).

    Prioridad cuando hay múltiples matches: T1 > T2 > T4 > T3.

    Nota: NO computa indicadores (los lee del candidato), evitando el doble cómputo
    que la spec 02 §6.1 menciona.
    """
    checks = {
        "T1": _check_t1(candidate),
        "T2": _check_t2(candidate),
        "T3": _check_t3(candidate),
        "T4": _check_t4(candidate),
    }
    matches = [tipo for tipo, (ok, _) in checks.items() if ok]

    if not matches:
        first = _PRIORITY_ORDER[0]
        return TypeClassification(
            tipo=None,
            justificacion=f"sin match. Ejemplo {first}: {checks[first][1]}",
            matches_multiple=[],
        )

    for tipo in _PRIORITY_ORDER:
        if tipo in matches:
            others = [m for m in matches if m != tipo]
            return TypeClassification(
                tipo=tipo, justificacion=checks[tipo][1], matches_multiple=others
            )

    return TypeClassification(tipo=None, justificacion="error interno", matches_multiple=[])
