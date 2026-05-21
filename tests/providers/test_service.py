import logging
from datetime import date

import pandas as pd
import pytest

from puts_screener.providers.base import DataProvider, NotSupportedError, ProviderError
from puts_screener.providers.factory import build_default_data_service
from puts_screener.providers.finnhub_provider import FinnhubProvider
from puts_screener.providers.models import EarningsEvent
from puts_screener.providers.service import AllProvidersFailedError, DataService
from puts_screener.providers.yfinance_provider import YFinanceProvider

_FAIL = "FAIL"
_NOT_SUPPORTED = "NOT_SUPPORTED"
_UNEXPECTED = "UNEXPECTED"

_START = date(2024, 1, 1)
_END = date(2024, 1, 2)


class FakeProvider(DataProvider):
    """Provider mock configurable para tests de orquestación.

    Cada `*_result` puede ser un valor concreto, None, o uno de los sentinels
    "FAIL" / "NOT_SUPPORTED" / "UNEXPECTED".
    """

    def __init__(
        self,
        name,
        *,
        ohlcv=None,
        profile=None,
        financials=None,
        analyst=None,
        rating=None,
        earnings=None,
    ):
        self.name = name
        self._results = {
            "get_ohlcv": ohlcv,
            "get_company_profile": profile,
            "get_financials": financials,
            "get_analyst_data": analyst,
            "get_rating_changes": rating,
            "get_upcoming_earnings": earnings,
        }
        self.call_log: list[str] = []

    def supports(self, method_name: str) -> bool:
        result = self._results.get(method_name)
        return not (isinstance(result, str) and result == _NOT_SUPPORTED)

    def _serve(self, method: str):
        self.call_log.append(method)
        result = self._results[method]
        if isinstance(result, str):
            if result == _FAIL:
                raise ProviderError(f"{self.name} forced failure")
            if result == _NOT_SUPPORTED:
                raise NotSupportedError(f"{self.name} doesn't support {method}")
            if result == _UNEXPECTED:
                raise RuntimeError(f"{self.name} unexpected error")
        return result

    def get_ohlcv(self, ticker, start, end, interval="1d"):
        return self._serve("get_ohlcv")

    def get_company_profile(self, ticker):
        return self._serve("get_company_profile")

    def get_financials(self, ticker):
        return self._serve("get_financials")

    def get_analyst_data(self, ticker):
        return self._serve("get_analyst_data")

    def get_rating_changes(self, ticker, lookback_weeks=6):
        return self._serve("get_rating_changes")

    def get_upcoming_earnings(self, ticker, lookforward_days=60):
        return self._serve("get_upcoming_earnings")


def _service(**kwargs) -> DataService:
    defaults = {
        "ohlcv_providers": [],
        "profile_providers": [],
        "financials_providers": [],
        "analyst_providers": [],
        "rating_providers": [],
        "earnings_providers": [],
    }
    defaults.update(kwargs)
    return DataService(**defaults)


def _df(value: float) -> pd.DataFrame:
    return pd.DataFrame({"Close": [value]})


def _event() -> EarningsEvent:
    return EarningsEvent(
        ticker="AAPL", date=date(2024, 2, 1), eps_estimate=None, eps_actual=None, when=None
    )


def test_first_success_skips_rest():
    df = _df(1.0)
    first = FakeProvider("first", ohlcv=df)
    second = FakeProvider("second", ohlcv=_df(2.0))
    svc = _service(ohlcv_providers=[first, second])
    result = svc.get_ohlcv("AAPL", _START, _END)
    assert result is df
    assert first.call_log == ["get_ohlcv"]
    assert second.call_log == []


def test_fallback_on_provider_error():
    df = _df(2.0)
    first = FakeProvider("first", ohlcv=_FAIL)
    second = FakeProvider("second", ohlcv=df)
    svc = _service(ohlcv_providers=[first, second])
    result = svc.get_ohlcv("AAPL", _START, _END)
    assert result is df
    assert first.call_log == ["get_ohlcv"]
    assert second.call_log == ["get_ohlcv"]


def test_fallback_on_unexpected_error():
    df = _df(3.0)
    first = FakeProvider("first", ohlcv=_UNEXPECTED)
    second = FakeProvider("second", ohlcv=df)
    svc = _service(ohlcv_providers=[first, second])
    result = svc.get_ohlcv("AAPL", _START, _END)
    assert result is df
    assert first.call_log == ["get_ohlcv"]
    assert second.call_log == ["get_ohlcv"]


def test_all_fail_raises_with_cause():
    first = FakeProvider("first", ohlcv=_FAIL)
    second = FakeProvider("second", ohlcv=_FAIL)
    svc = _service(ohlcv_providers=[first, second])
    with pytest.raises(AllProvidersFailedError) as excinfo:
        svc.get_ohlcv("AAPL", _START, _END)
    assert isinstance(excinfo.value.__cause__, ProviderError)


def test_unsupported_provider_skipped_without_call():
    df = _df(5.0)
    first = FakeProvider("first", ohlcv=_NOT_SUPPORTED)
    second = FakeProvider("second", ohlcv=df)
    svc = _service(ohlcv_providers=[first, second])
    result = svc.get_ohlcv("AAPL", _START, _END)
    assert result is df
    assert first.call_log == []
    assert second.call_log == ["get_ohlcv"]


def test_empty_providers_raises():
    svc = _service(ohlcv_providers=[])
    with pytest.raises(AllProvidersFailedError):
        svc.get_ohlcv("AAPL", _START, _END)


def test_earnings_none_is_success():
    first = FakeProvider("first", earnings=None)
    second = FakeProvider("second", earnings=_event())
    svc = _service(earnings_providers=[first, second])
    result = svc.get_upcoming_earnings("AAPL")
    assert result is None
    assert first.call_log == ["get_upcoming_earnings"]
    assert second.call_log == []


def test_ohlcv_none_is_failure():
    df = _df(8.0)
    first = FakeProvider("first", ohlcv=None)
    second = FakeProvider("second", ohlcv=df)
    svc = _service(ohlcv_providers=[first, second])
    result = svc.get_ohlcv("AAPL", _START, _END)
    assert result is df
    assert first.call_log == ["get_ohlcv"]
    assert second.call_log == ["get_ohlcv"]


def test_factory_builds_service_with_correct_types():
    svc = build_default_data_service()
    assert isinstance(svc, DataService)
    assert [type(p) for p in svc._ohlcv] == [YFinanceProvider]
    assert isinstance(svc._profile[0], YFinanceProvider)
    assert isinstance(svc._profile[1], FinnhubProvider)
    assert isinstance(svc._financials[0], YFinanceProvider)
    assert isinstance(svc._analyst[0], YFinanceProvider)
    assert isinstance(svc._analyst[1], FinnhubProvider)
    assert isinstance(svc._rating[0], YFinanceProvider)
    assert [type(p) for p in svc._rating] == [YFinanceProvider]
    assert isinstance(svc._earnings[0], YFinanceProvider)
    assert isinstance(svc._earnings[1], FinnhubProvider)


def test_logging_warning_then_info(caplog):
    df = _df(10.0)
    first = FakeProvider("first", ohlcv=_FAIL)
    second = FakeProvider("second", ohlcv=df)
    svc = _service(ohlcv_providers=[first, second])
    with caplog.at_level(logging.INFO, logger="puts_screener.providers.service"):
        svc.get_ohlcv("AAPL", _START, _END)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    infos = [r for r in caplog.records if r.levelno == logging.INFO]
    assert any("failed on first" in r.getMessage() for r in warnings)
    assert any("served by second" in r.getMessage() for r in infos)
