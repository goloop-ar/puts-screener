"""Filtros del Paso 1 del SOP.

Cada filtro es una función pura que recibe un ScreenedCandidate y devuelve
(passes, rejection_reason). Se aplican vía `apply_step1_filters()`, que actualiza
`pasa_filtros_paso_1` y agrega entradas a `motivos_rechazo`.

La tendencia macro NO es filtro independiente — se chequea en la clasificación
T1-T4 (§6.2 de la spec).
"""

import logging
from collections.abc import Callable

from puts_screener.config_filters import (
    HV_PERCENTILE_MAX,
    HV_PERCENTILE_MIN,
    MAX_DOWNGRADES_6W,
    MIN_AVG_DAILY_VOLUME,
    MIN_FCF_TTM,
    MIN_MARKET_CAP_USD,
    MIN_PRICE_TARGET_UPSIDE,
    MIN_RECOMMENDATION_BUY_RATIO,
    RSI_DAILY_THRESHOLD,
    RSI_OVERBOUGHT_THRESHOLD,
    RSI_WEEKLY_THRESHOLD,
    SECTORS_FCF_FILTER_EXEMPT,
)
from puts_screener.models_screening import ScreenedCandidate

logger = logging.getLogger(__name__)

# Países "EU" para skipear el filtro de downgrades (yfinance no provee la data).
_EU_COUNTRIES: frozenset[str] = frozenset(
    {
        "United Kingdom",
        "Germany",
        "France",
        "Switzerland",
        "Sweden",
        "Spain",
        "Netherlands",
        "Italy",
        "Finland",
        "Belgium",
        "Norway",
        "Denmark",
        "Austria",
        "Portugal",
        "Ireland",
        "Luxembourg",
        "Bermuda",
        # Variantes que yfinance/Finnhub pueden devolver:
        "GB",
        "DE",
        "FR",
        "CH",
        "SE",
        "ES",
        "NL",
        "IT",
        "FI",
        "BE",
        "NO",
        "DK",
        "AT",
        "PT",
        "IE",
        "LU",
        "BM",
    }
)


def _is_eu_ticker(candidate: ScreenedCandidate) -> bool:
    """True si el candidato es de un mercado EU (para skipear filtros US-only)."""
    country = candidate.profile.country
    return country is not None and country in _EU_COUNTRIES


def filter_quality_liquidity(candidate: ScreenedCandidate) -> tuple[bool, str | None]:
    """Calidad y liquidez: market cap, volumen promedio 3m y FCF TTM positivos."""
    mc = candidate.profile.market_cap_usd
    if mc is None or mc < MIN_MARKET_CAP_USD:
        return False, f"market cap ({mc}) < {MIN_MARKET_CAP_USD:.0f}"

    vol = candidate.profile.avg_daily_volume_3m
    if vol is None or vol < MIN_AVG_DAILY_VOLUME:
        return False, f"avg daily volume ({vol}) < {MIN_AVG_DAILY_VOLUME:.0f}"

    fcf = candidate.financials.free_cash_flow_ttm
    sector = candidate.profile.sector
    if sector not in SECTORS_FCF_FILTER_EXEMPT and (fcf is None or fcf <= MIN_FCF_TTM):
        return False, f"FCF TTM ({fcf}) ≤ {MIN_FCF_TTM}"

    return True, None


def filter_valuation(candidate: ScreenedCandidate) -> tuple[bool, str | None]:
    """Valoración: upside del price target, mayoría Buy y sin downgrades 6w (US)."""
    if candidate.price_target_upside_pct <= MIN_PRICE_TARGET_UPSIDE:
        return False, (
            f"price target upside ({candidate.price_target_upside_pct:.1%}) "
            f"≤ {MIN_PRICE_TARGET_UPSIDE:.1%}"
        )

    if candidate.recommendation_buy_ratio < MIN_RECOMMENDATION_BUY_RATIO:
        return False, (
            f"buy ratio ({candidate.recommendation_buy_ratio:.2f}) < {MIN_RECOMMENDATION_BUY_RATIO}"
        )

    if not _is_eu_ticker(candidate) and candidate.downgrades_6w_count > MAX_DOWNGRADES_6W:
        return False, f"{candidate.downgrades_6w_count} downgrades en 6w > {MAX_DOWNGRADES_6W}"

    return True, None


def filter_momentum(candidate: ScreenedCandidate) -> tuple[bool, str | None]:
    """Momento técnico — gate excluyente de sobrecompra.

    Falla si RSI_d o RSI_w están en zona de sobrecompra (>= RSI_OVERBOUGHT_THRESHOLD).

    Para venta de puts, estar sobrecomprado es el riesgo real (corrección probable
    que acerca el strike). Las señales positivas de momentum (RSI saliendo de
    sobreventa, MACD subiendo) NO se chequean acá — se cuentan aparte en
    `compute_momentum_score()` y se persisten en `candidate.momentum_score` para
    priorización posterior, pero no filtran.
    """
    if candidate.rsi_d >= RSI_OVERBOUGHT_THRESHOLD:
        return False, f"RSI_d sobrecomprado ({candidate.rsi_d:.1f} ≥ {RSI_OVERBOUGHT_THRESHOLD})"
    if candidate.rsi_w >= RSI_OVERBOUGHT_THRESHOLD:
        return False, f"RSI_w sobrecomprado ({candidate.rsi_w:.1f} ≥ {RSI_OVERBOUGHT_THRESHOLD})"

    # Éxito: log con el score que tendría (preview del valor que el pipeline persiste).
    preview_score = compute_momentum_score(candidate)
    logger.info(
        "filter_momentum: %s passes (momentum_score will be %d)",
        candidate.ticker,
        preview_score,
    )
    return True, None


def filter_hv_percentile(candidate: ScreenedCandidate) -> tuple[bool, str | None]:
    """HV Percentile 52w dentro de [HV_PERCENTILE_MIN, HV_PERCENTILE_MAX]."""
    hv = candidate.hv_percentile_52w
    if hv < HV_PERCENTILE_MIN:
        return False, f"HV percentile {hv:.1f} < {HV_PERCENTILE_MIN}"
    if hv > HV_PERCENTILE_MAX:
        return False, f"HV percentile {hv:.1f} > {HV_PERCENTILE_MAX}"
    return True, None


# Filtros en orden de aplicación (más baratos primero).
_FILTERS: tuple[tuple[str, Callable[[ScreenedCandidate], tuple[bool, str | None]]], ...] = (
    ("quality_liquidity", filter_quality_liquidity),
    ("valuation", filter_valuation),
    ("momentum", filter_momentum),
    ("hv_percentile", filter_hv_percentile),
)


def apply_step1_filters(candidate: ScreenedCandidate) -> ScreenedCandidate:
    """Aplica los 4 filtros del Paso 1 + el gate de clasificación, y muta el candidato.

    Setea `pasa_filtros_paso_1` y agrega un motivo por cada filtro fallido. NO corta
    en el primer fallo: corre todos para que `motivos_rechazo` tenga la lista completa.
    Gate final (spec 02 §1): si el candidato no clasifica en T1–T4, no pasa.
    """
    all_pass = True
    for name, fn in _FILTERS:
        passes, reason = fn(candidate)
        if not passes:
            all_pass = False
            candidate.motivos_rechazo.append(f"{name}: {reason}")

    # Gate de clasificación (spec 02 §1): candidato final = pasa filtros AND clasifica en T1–T4.
    if candidate.classification is None or candidate.classification.tipo is None:
        all_pass = False
        candidate.motivos_rechazo.append("sin clasificación T1–T4")

    candidate.pasa_filtros_paso_1 = all_pass
    return candidate


def compute_momentum_score(candidate: ScreenedCandidate) -> int:
    """Cuenta señales positivas de momentum. Rango: 0 a 3.

    Señales (cada una vale 1):
    - RSI_d saliendo de <50 y subiendo: `rsi_d < RSI_DAILY_THRESHOLD AND rsi_d > rsi_d_3d_ago`.
    - RSI_w saliendo de <50 y subiendo: `rsi_w < RSI_WEEKLY_THRESHOLD AND rsi_w > rsi_w_2w_ago`.
    - MACD subiendo: `macd_state` empieza con "subiendo".

    NO filtra. El pipeline (Tanda 3) llama a esta función después de los filtros y
    asigna el resultado a `candidate.momentum_score` para uso posterior (priorización
    en el reporte, scoring de soportes en spec 03).
    """
    score = 0
    if candidate.rsi_d < RSI_DAILY_THRESHOLD and candidate.rsi_d > candidate.rsi_d_3d_ago:
        score += 1
    if candidate.rsi_w < RSI_WEEKLY_THRESHOLD and candidate.rsi_w > candidate.rsi_w_2w_ago:
        score += 1
    if candidate.macd_state.startswith("subiendo"):
        score += 1
    return score
