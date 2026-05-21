"""Dataclasses tipadas que representan la data devuelta por los providers."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class CompanyProfile:
    ticker: str
    name: str
    sector: str | None
    industry: str | None
    exchange: str | None
    country: str | None
    market_cap_usd: float | None
    currency: str | None
    avg_daily_volume_3m: float | None


@dataclass(frozen=True)
class FinancialSnapshot:
    ticker: str
    free_cash_flow_ttm: float | None  # USD, último TTM
    total_revenue_ttm: float | None
    fiscal_year_end: date | None
    as_of: date | None  # cuándo se reportó


@dataclass(frozen=True)
class AnalystData:
    ticker: str
    price_target_mean: float | None
    price_target_median: float | None
    price_target_high: float | None
    price_target_low: float | None
    n_analysts: int | None
    buy_count: int = 0
    hold_count: int = 0
    sell_count: int = 0
    strong_buy_count: int = 0
    strong_sell_count: int = 0
    recommendation_mean: float | None = None  # 1=strong buy ... 5=strong sell
    as_of: date | None = None


@dataclass(frozen=True)
class RatingChange:
    ticker: str
    date: date
    action: str  # "downgrade" | "upgrade" | "initiation" | "reiterated"
    from_grade: str | None
    to_grade: str | None
    firm: str | None


@dataclass(frozen=True)
class EarningsEvent:
    ticker: str
    date: date
    eps_estimate: float | None
    eps_actual: float | None
    when: str | None  # "bmo" (before market open) | "amc" (after market close) | None


@dataclass(frozen=True)
class HistoricalEarningsEvent:
    ticker: str
    date: date  # fecha del earnings (puede ser hoy o pasado, NO futuro)
    eps_estimate: float | None
    eps_actual: float | None
    eps_surprise_pct: float | None  # (actual - estimate) / abs(estimate) * 100
    revenue_estimate: float | None  # opcional, puede no estar disponible
    revenue_actual: float | None
