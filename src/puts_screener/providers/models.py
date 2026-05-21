"""Dataclasses tipadas que representan la data devuelta por los providers."""

from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass(frozen=True)
class CompanyProfile:
    ticker: str
    name: str
    sector: Optional[str]
    industry: Optional[str]
    exchange: Optional[str]
    country: Optional[str]
    market_cap_usd: Optional[float]
    currency: Optional[str]
    avg_daily_volume_3m: Optional[float]


@dataclass(frozen=True)
class FinancialSnapshot:
    ticker: str
    free_cash_flow_ttm: Optional[float]  # USD, último TTM
    total_revenue_ttm: Optional[float]
    fiscal_year_end: Optional[date]
    as_of: Optional[date]  # cuándo se reportó


@dataclass(frozen=True)
class AnalystData:
    ticker: str
    price_target_mean: Optional[float]
    price_target_median: Optional[float]
    price_target_high: Optional[float]
    price_target_low: Optional[float]
    n_analysts: Optional[int]
    buy_count: int = 0
    hold_count: int = 0
    sell_count: int = 0
    strong_buy_count: int = 0
    strong_sell_count: int = 0
    recommendation_mean: Optional[float] = None  # 1=strong buy ... 5=strong sell
    as_of: Optional[date] = None


@dataclass(frozen=True)
class RatingChange:
    ticker: str
    date: date
    action: str  # "downgrade" | "upgrade" | "initiation" | "reiterated"
    from_grade: Optional[str]
    to_grade: Optional[str]
    firm: Optional[str]


@dataclass(frozen=True)
class EarningsEvent:
    ticker: str
    date: date
    eps_estimate: Optional[float]
    eps_actual: Optional[float]
    when: Optional[
        str
    ]  # "bmo" (before market open) | "amc" (after market close) | None
