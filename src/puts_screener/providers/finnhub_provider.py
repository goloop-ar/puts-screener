"""Provider basado en Finnhub: perfil, analistas, rating changes y earnings."""

import dataclasses
import logging
from datetime import UTC, date, datetime, timedelta

import finnhub

from .base import DataProvider, ProviderError
from .cache import get_cached, write_cache
from .config import get_finnhub_api_key
from .models import AnalystData, CompanyProfile, EarningsEvent, RatingChange
from .rate_limit import RateLimiter
from .tickers import to_finnhub

logger = logging.getLogger(__name__)

_MILLIONS = 1e6
_ACTION_MAP = {
    "down": "downgrade",
    "up": "upgrade",
    "init": "initiation",
    "main": "reiterated",
    "reit": "reiterated",
}


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def _epoch_to_date(epoch: float | None) -> date | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=UTC).date()


def _normalize_action(action: str | None) -> str:
    if not action:
        return ""
    return _ACTION_MAP.get(action.strip().lower(), action)


def _compute_recommendation_mean(
    strong_buy: int, buy: int, hold: int, sell: int, strong_sell: int
) -> float | None:
    total = strong_buy + buy + hold + sell + strong_sell
    if total <= 0:
        return None
    weighted = 1 * strong_buy + 2 * buy + 3 * hold + 4 * sell + 5 * strong_sell
    return weighted / total


def _analyst_from_cache(data: dict) -> AnalystData:
    return AnalystData(
        ticker=data["ticker"],
        price_target_mean=data["price_target_mean"],
        price_target_median=data["price_target_median"],
        price_target_high=data["price_target_high"],
        price_target_low=data["price_target_low"],
        n_analysts=data["n_analysts"],
        buy_count=data["buy_count"],
        hold_count=data["hold_count"],
        sell_count=data["sell_count"],
        strong_buy_count=data["strong_buy_count"],
        strong_sell_count=data["strong_sell_count"],
        recommendation_mean=data["recommendation_mean"],
        as_of=_parse_date(data["as_of"]),
    )


def _ratings_from_cache(data: dict) -> list[RatingChange]:
    return [
        RatingChange(
            ticker=item["ticker"],
            date=_parse_date(item["date"]),
            action=item["action"],
            from_grade=item["from_grade"],
            to_grade=item["to_grade"],
            firm=item["firm"],
        )
        for item in data["items"]
    ]


def _earnings_from_cache(data: dict) -> EarningsEvent:
    return EarningsEvent(
        ticker=data["ticker"],
        date=_parse_date(data["date"]),
        eps_estimate=data["eps_estimate"],
        eps_actual=data["eps_actual"],
        when=data["when"],
    )


class FinnhubProvider(DataProvider):
    """Wrapper sobre el SDK de Finnhub. Se autodeshabilita si falta la API key."""

    name = "finnhub"

    def __init__(self, api_key: str | None = None, max_per_minute: int = 55):
        self.api_key = api_key or get_finnhub_api_key()
        self._enabled = bool(self.api_key)
        if not self._enabled:
            logger.warning("FinnhubProvider: API key missing, provider disabled")
            self._client = None
            self._rate_limiter = None
            return
        self._client = finnhub.Client(api_key=self.api_key)
        self._rate_limiter = RateLimiter(max_per_minute)

    def _ensure_enabled(self) -> None:
        if not self._enabled:
            raise ProviderError("FinnhubProvider disabled (API key missing)")

    def _call(self, func, label: str, **kwargs):
        """Aplica rate limiting y envuelve errores del SDK como ProviderError."""
        self._rate_limiter.wait_for_slot()
        try:
            return func(**kwargs)
        except Exception as exc:
            raise ProviderError(f"Finnhub call {label} failed: {exc}") from exc

    def get_company_profile(self, ticker: str) -> CompanyProfile:
        self._ensure_enabled()
        cache_key = f"finnhub_{ticker}"
        cached = get_cached("profile", cache_key)
        if cached is not None:
            return CompanyProfile(**cached)

        data = self._call(
            self._client.company_profile2, "company_profile2", symbol=to_finnhub(ticker)
        )
        if not data:
            raise ProviderError(f"Finnhub returned empty profile for {ticker}")

        market_cap = data.get("marketCapitalization")
        profile = CompanyProfile(
            ticker=ticker,
            name=data.get("name"),
            sector=data.get("finnhubIndustry"),
            industry=data.get("finnhubIndustry"),
            exchange=data.get("exchange"),
            country=data.get("country"),
            market_cap_usd=market_cap * _MILLIONS if market_cap is not None else None,
            currency=data.get("currency"),
            avg_daily_volume_3m=None,
        )
        write_cache("profile", cache_key, dataclasses.asdict(profile))
        return profile

    def get_analyst_data(self, ticker: str) -> AnalystData:
        self._ensure_enabled()
        cache_key = f"finnhub_{ticker}"
        cached = get_cached("analyst", cache_key)
        if cached is not None:
            return _analyst_from_cache(cached)

        symbol = to_finnhub(ticker)
        trends = (
            self._call(self._client.recommendation_trends, "recommendation_trends", symbol=symbol)
            or []
        )
        target = self._call(self._client.price_target, "price_target", symbol=symbol) or {}
        if not trends and not target:
            raise ProviderError(f"Finnhub returned no analyst data for {ticker}")

        latest = trends[0] if trends else {}
        strong_buy = latest.get("strongBuy", 0)
        buy = latest.get("buy", 0)
        hold = latest.get("hold", 0)
        sell = latest.get("sell", 0)
        strong_sell = latest.get("strongSell", 0)

        data = AnalystData(
            ticker=ticker,
            price_target_mean=target.get("targetMean"),
            price_target_median=target.get("targetMedian"),
            price_target_high=target.get("targetHigh"),
            price_target_low=target.get("targetLow"),
            n_analysts=target.get("numberOfAnalysts"),
            buy_count=buy,
            hold_count=hold,
            sell_count=sell,
            strong_buy_count=strong_buy,
            strong_sell_count=strong_sell,
            recommendation_mean=_compute_recommendation_mean(
                strong_buy, buy, hold, sell, strong_sell
            ),
            as_of=date.today(),
        )
        write_cache("analyst", cache_key, dataclasses.asdict(data))
        return data

    def get_rating_changes(self, ticker: str, lookback_weeks: int = 6) -> list[RatingChange]:
        self._ensure_enabled()
        cache_key = f"finnhub_{ticker}_{lookback_weeks}"
        cached = get_cached("ratings", cache_key)
        if cached is not None:
            return _ratings_from_cache(cached)

        today = date.today()
        from_ = (today - timedelta(weeks=lookback_weeks)).isoformat()
        to_ = today.isoformat()
        raw = (
            self._call(
                self._client.upgrade_downgrade,
                "upgrade_downgrade",
                symbol=to_finnhub(ticker),
                from_=from_,
                to=to_,
            )
            or []
        )

        changes = [
            RatingChange(
                ticker=ticker,
                date=_epoch_to_date(item.get("gradeTime")),
                action=_normalize_action(item.get("action")),
                from_grade=item.get("fromGrade"),
                to_grade=item.get("toGrade"),
                firm=item.get("company"),
            )
            for item in raw
        ]
        write_cache("ratings", cache_key, {"items": [dataclasses.asdict(c) for c in changes]})
        return changes

    def get_upcoming_earnings(
        self, ticker: str, lookforward_days: int = 60
    ) -> EarningsEvent | None:
        self._ensure_enabled()
        cache_key = f"finnhub_{ticker}"
        cached = get_cached("earnings", cache_key)
        if cached is not None:
            return _earnings_from_cache(cached)

        today = date.today()
        horizon = today + timedelta(days=lookforward_days)
        payload = (
            self._call(
                self._client.earnings_calendar,
                "earnings_calendar",
                _from=today.isoformat(),
                to=horizon.isoformat(),
                symbol=to_finnhub(ticker),
            )
            or {}
        )
        entries = payload.get("earningsCalendar") or []
        if not entries:
            return None

        entry = entries[0]
        event = EarningsEvent(
            ticker=ticker,
            date=_parse_date(entry.get("date")),
            eps_estimate=entry.get("epsEstimate"),
            eps_actual=entry.get("epsActual"),
            when=entry.get("hour"),
        )
        write_cache("earnings", cache_key, dataclasses.asdict(event))
        return event
