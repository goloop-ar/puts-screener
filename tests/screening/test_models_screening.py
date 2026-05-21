import dataclasses
from datetime import datetime

import pandas as pd
import pytest

from puts_screener.models_screening import ScreenedCandidate, TypeClassification
from puts_screener.providers.models import (
    AnalystData,
    CompanyProfile,
    FinancialSnapshot,
)


def _profile() -> CompanyProfile:
    return CompanyProfile(
        ticker="AAPL",
        name="Apple Inc.",
        sector="Technology",
        industry="Consumer Electronics",
        exchange="NMS",
        country="United States",
        market_cap_usd=3.0e12,
        currency="USD",
        avg_daily_volume_3m=5.0e7,
    )


def _financials() -> FinancialSnapshot:
    return FinancialSnapshot(
        ticker="AAPL",
        free_cash_flow_ttm=1.0e11,
        total_revenue_ttm=4.0e11,
        fiscal_year_end=None,
        as_of=None,
    )


def _analyst() -> AnalystData:
    return AnalystData(
        ticker="AAPL",
        price_target_mean=300.0,
        price_target_median=None,
        price_target_high=None,
        price_target_low=None,
        n_analysts=40,
    )


def _candidate() -> ScreenedCandidate:
    return ScreenedCandidate(
        ticker="AAPL",
        profile=_profile(),
        financials=_financials(),
        analyst=_analyst(),
        rating_changes_6w=[],
        upcoming_earnings=None,
        earnings_history=[],
        ohlcv_daily=pd.DataFrame(),
        ohlcv_weekly=pd.DataFrame(),
    )


def test_type_classification_is_frozen():
    tc = TypeClassification(tipo="T1", justificacion="uptrend")
    assert tc.tipo == "T1"
    assert tc.matches_multiple == []
    with pytest.raises(dataclasses.FrozenInstanceError):
        tc.tipo = "T2"


def test_screened_candidate_is_mutable():
    candidate = _candidate()
    assert candidate.pasa_filtros_paso_1 is False
    candidate.pasa_filtros_paso_1 = True
    candidate.motivos_rechazo.append("test")
    assert candidate.pasa_filtros_paso_1 is True
    assert candidate.motivos_rechazo == ["test"]


def test_defaults_applied():
    candidate = _candidate()
    assert candidate.classification is None
    assert candidate.spot == 0.0
    assert candidate.macd_state == "neutral"
    assert candidate.downgrades_6w_count == 0
    assert isinstance(candidate.fetched_at, datetime)


def test_mutable_defaults_are_independent():
    a = _candidate()
    b = _candidate()
    a.motivos_rechazo.append("solo_a")
    assert a.motivos_rechazo == ["solo_a"]
    assert b.motivos_rechazo == []

    tc1 = TypeClassification(tipo="T1", justificacion="x")
    tc2 = TypeClassification(tipo="T2", justificacion="y")
    tc1.matches_multiple.append("T3")
    assert tc1.matches_multiple == ["T3"]
    assert tc2.matches_multiple == []


def test_screened_candidate_has_momentum_score_default(neutral_candidate):
    """El campo momentum_score arranca en 0 y es mutable."""
    assert neutral_candidate.momentum_score == 0
    neutral_candidate.momentum_score = 3
    assert neutral_candidate.momentum_score == 3
