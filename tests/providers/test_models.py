import dataclasses
from datetime import date

import pytest

from puts_screener.providers.models import (
    AnalystData,
    CompanyProfile,
    EarningsEvent,
    ExDividendEvent,
    FinancialSnapshot,
    RatingChange,
)


def test_company_profile_instantiation():
    profile = CompanyProfile(
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
    assert profile.ticker == "AAPL"
    assert profile.market_cap_usd == 3.0e12


def test_company_profile_is_frozen():
    profile = CompanyProfile(
        ticker="AAPL",
        name="Apple",
        sector=None,
        industry=None,
        exchange=None,
        country=None,
        market_cap_usd=None,
        currency=None,
        avg_daily_volume_3m=None,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        profile.ticker = "MSFT"


def test_analyst_data_defaults():
    analyst = AnalystData(
        ticker="AAPL",
        price_target_mean=None,
        price_target_median=None,
        price_target_high=None,
        price_target_low=None,
        n_analysts=None,
    )
    assert analyst.buy_count == 0
    assert analyst.strong_sell_count == 0
    assert analyst.recommendation_mean is None
    assert analyst.as_of is None


def test_financial_snapshot_is_frozen():
    snapshot = FinancialSnapshot(
        ticker="AAPL",
        free_cash_flow_ttm=None,
        total_revenue_ttm=None,
        fiscal_year_end=None,
        as_of=None,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.ticker = "MSFT"


def test_rating_change_fields():
    change = RatingChange(
        ticker="AAPL",
        date=date(2024, 1, 2),
        action="downgrade",
        from_grade="Buy",
        to_grade="Hold",
        firm="Foo Securities",
    )
    assert change.action == "downgrade"
    assert change.date == date(2024, 1, 2)


def test_earnings_event_fields():
    event = EarningsEvent(
        ticker="AAPL",
        date=date(2024, 2, 1),
        eps_estimate=1.5,
        eps_actual=None,
        when="amc",
    )
    assert event.when == "amc"
    assert event.eps_estimate == 1.5


def test_ex_dividend_event_fields():
    event = ExDividendEvent(ticker="AAPL", date=date(2024, 2, 1), amount=0.24)
    assert event.ticker == "AAPL"
    assert event.date == date(2024, 2, 1)
    assert event.amount == 0.24


def test_ex_dividend_event_is_frozen():
    event = ExDividendEvent(ticker="AAPL", date=date(2024, 2, 1), amount=None)
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.ticker = "MSFT"
