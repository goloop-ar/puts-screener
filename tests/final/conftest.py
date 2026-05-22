"""Fixtures para los tests de reportes (spec 04): factory de FinalCandidate armado a mano."""

from datetime import datetime

import pandas as pd
import pytest

from puts_screener.binary_events import BinaryEventsReport
from puts_screener.models_final import FinalCandidate
from puts_screener.models_screening import ScreenedCandidate, TypeClassification
from puts_screener.models_support import (
    SupportAnalysis,
    SupportedCandidate,
    SupportLevel,
    SupportZone,
)
from puts_screener.providers.models import AnalystData, CompanyProfile, FinancialSnapshot

_DEFAULT_ELEMENTS = [
    ("ema_200d", 99.0, 2),
    ("avwap_earnings", 98.6, 1),
    ("fib_618", 98.2, 1),
    ("hvn", 97.8, 1),
]


def _tiny_ohlcv() -> pd.DataFrame:
    idx = pd.bdate_range("2026-01-01", periods=1)
    return pd.DataFrame(
        {"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [1.0], "Volume": [1]}, index=idx
    )


def _build_test_final_candidate(
    *,
    ticker="TEST",
    tipo="T1",
    score=5,
    distance_pct=0.03,
    passes=True,
    elements=None,
    has_dynamic_confirmer=True,
    flags=None,
    macro_events=None,
    sector="Technology",
    exchange="NMS",
    country="United States",
    spot=100.0,
    market_cap=50e9,
    price_target_mean=110.0,
    recommendation_mean=2.0,
    rsi_d=55.0,
    rsi_w=58.0,
    macd_state="subiendo_positivo",
    momentum_score=2,
    earnings_date=None,
    dias_a_earnings=None,
    earnings_en_45d=False,
    ex_div_date=None,
    ex_div_amount=None,
    fetched_at=None,
    universes=(),
) -> FinalCandidate:
    """Construye un FinalCandidate completo con defaults razonables; overridear lo necesario."""
    elements = _DEFAULT_ELEMENTS if elements is None else elements
    flags = flags or []
    macro_events = macro_events or []
    fetched_at = fetched_at or datetime(2026, 5, 21, 16, 30)

    profile = CompanyProfile(
        ticker=ticker,
        name=f"{ticker} Inc.",
        sector=sector,
        industry="Software",
        exchange=exchange,
        country=country,
        market_cap_usd=market_cap,
        currency="USD",
        avg_daily_volume_3m=5e6,
    )
    financials = FinancialSnapshot(
        ticker=ticker,
        free_cash_flow_ttm=1e9,
        total_revenue_ttm=1e10,
        fiscal_year_end=None,
        as_of=None,
    )
    analyst = AnalystData(
        ticker=ticker,
        price_target_mean=price_target_mean,
        price_target_median=None,
        price_target_high=None,
        price_target_low=None,
        n_analysts=20,
        recommendation_mean=recommendation_mean,
    )
    screened = ScreenedCandidate(
        ticker=ticker,
        profile=profile,
        financials=financials,
        analyst=analyst,
        rating_changes_6w=[],
        upcoming_earnings=None,
        earnings_history=[],
        ohlcv_daily=_tiny_ohlcv(),
        ohlcv_weekly=_tiny_ohlcv(),
        classification=TypeClassification(tipo=tipo, justificacion=f"motivo {tipo}"),
        spot=spot,
        sma_50w=spot * 0.95,
        sma_200w=spot * 0.90,
        rsi_d=rsi_d,
        rsi_w=rsi_w,
        macd_state=macd_state,
        momentum_score=momentum_score,
        hv_percentile_52w=50.0,
        price_target_upside_pct=0.10,
        recommendation_buy_ratio=0.75,
        downgrades_6w_count=0,
        universes=tuple(universes),
    )

    support_levels = [
        SupportLevel(price=price, element=name, points=points) for name, price, points in elements
    ]
    center = spot * (1 - distance_pct)
    if passes:
        zone = SupportZone(
            center_price=center,
            lower_bound=center - 1.0,
            upper_bound=center + 1.0,
            score=score,
            elements=support_levels,
            has_dynamic_confirmer=has_dynamic_confirmer,
            distance_pct=distance_pct,
        )
        analysis = SupportAnalysis(valid_zones=[zone], rejected_zones=[], best_zone=zone)
    else:
        analysis = SupportAnalysis(valid_zones=[], rejected_zones=[], best_zone=None)

    supported = SupportedCandidate(screened=screened, analysis=analysis, pasa_paso_2=passes)
    binary_events = BinaryEventsReport(
        earnings_date=earnings_date,
        dias_a_earnings=dias_a_earnings,
        earnings_en_45d=earnings_en_45d,
        ex_div_date=ex_div_date,
        dias_a_ex_div=None,
        ex_div_en_45d=ex_div_amount is not None,
        ex_div_amount=ex_div_amount,
        eventos_macro=macro_events,
        eventos_macro_en_45d=bool(macro_events),
        tiene_eventos_binarios=bool(flags),
        flags_legibles=flags,
    )
    return FinalCandidate(
        supported=supported, binary_events=binary_events, fetched_at=fetched_at, errors=[]
    )


@pytest.fixture
def final_candidate_factory():
    """Devuelve el constructor de FinalCandidate para que cada test arme el suyo."""
    return _build_test_final_candidate
