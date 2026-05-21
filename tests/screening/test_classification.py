from datetime import date, timedelta

import numpy as np
import pandas as pd

from puts_screener.classification import classify
from puts_screener.providers.models import HistoricalEarningsEvent


def _ohlcv(values: list[float] | np.ndarray) -> pd.DataFrame:
    arr = np.asarray(values, dtype=float)
    dates = pd.bdate_range(end=date.today(), periods=len(arr))
    s = pd.Series(arr, index=dates)
    return pd.DataFrame({"Open": s, "High": s, "Low": s, "Close": s, "Volume": 1_000_000})


def _flat(price: float = 100.0, n: int = 70) -> pd.DataFrame:
    return _ohlcv(np.full(n, price, dtype=float))


def _with_drop(base: float = 100.0, drop_pct: float = -0.12, n: int = 70) -> pd.DataFrame:
    values = np.full(n, base, dtype=float)
    values[-1] = base * (1 + drop_pct)
    return _ohlcv(values)


def _alternating(low: float, high: float, n: int = 70) -> pd.DataFrame:
    # n par → último índice (n-1) impar → high (evita gatillar T2 por caída).
    values = np.array([low if i % 2 == 0 else high for i in range(n)], dtype=float)
    return _ohlcv(values)


def _post_earnings(earnings_date: date, pre: float = 100.0, post: float = 93.0, n: int = 70):
    dates = pd.bdate_range(end=date.today(), periods=n)
    earnings_ts = pd.Timestamp(earnings_date)
    values = [pre if d < earnings_ts else post for d in dates]
    s = pd.Series(values, index=dates, dtype=float)
    return pd.DataFrame({"Open": s, "High": s, "Low": s, "Close": s, "Volume": 1_000_000})


def _earnings(days_ago: int) -> HistoricalEarningsEvent:
    return HistoricalEarningsEvent(
        ticker="TEST",
        date=date.today() - timedelta(days=days_ago),
        eps_estimate=2.0,
        eps_actual=1.5,
        eps_surprise_pct=-25.0,
        revenue_estimate=None,
        revenue_actual=None,
    )


def test_classify_t1_happy_path(neutral_candidate):
    neutral_candidate.sma_50w = 120.0
    neutral_candidate.sma_200w = 100.0
    neutral_candidate.spot = 105.0
    neutral_candidate.ohlcv_daily = _flat(105.0)
    assert classify(neutral_candidate).tipo == "T1"


def test_classify_t1_fails_when_spot_below_sma200w(neutral_candidate):
    neutral_candidate.sma_50w = 120.0
    neutral_candidate.sma_200w = 100.0
    neutral_candidate.spot = 95.0
    neutral_candidate.ohlcv_daily = _flat(95.0)
    assert classify(neutral_candidate).tipo != "T1"


def test_classify_t2_happy_path(neutral_candidate):
    neutral_candidate.sma_50w = 110.0
    neutral_candidate.sma_200w = 100.0
    neutral_candidate.spot = 100.0  # no > SMA200W → T1 no matchea
    neutral_candidate.ohlcv_daily = _with_drop(100.0, -0.12)
    assert classify(neutral_candidate).tipo == "T2"


def test_classify_t2_fails_when_drop_insufficient(neutral_candidate):
    neutral_candidate.sma_50w = 110.0
    neutral_candidate.sma_200w = 100.0
    neutral_candidate.spot = 100.0
    neutral_candidate.ohlcv_daily = _with_drop(100.0, -0.05)
    assert classify(neutral_candidate).tipo != "T2"


def test_classify_t2_fails_when_downtrend(neutral_candidate):
    neutral_candidate.sma_50w = 80.0
    neutral_candidate.sma_200w = 100.0
    neutral_candidate.spot = 88.0
    neutral_candidate.ohlcv_daily = _with_drop(100.0, -0.12)
    assert classify(neutral_candidate).tipo != "T2"


def test_classify_t3_happy_path(neutral_candidate):
    neutral_candidate.sma_50w = 100.0
    neutral_candidate.sma_200w = 100.0
    neutral_candidate.spot = 97.2  # cerca del piso (floor = 97 + 0.3*3 = 97.9)
    neutral_candidate.ohlcv_daily = _alternating(97.0, 100.0)
    assert classify(neutral_candidate).tipo == "T3"


def test_classify_t3_fails_when_range_not_compact(neutral_candidate):
    neutral_candidate.sma_50w = 100.0
    neutral_candidate.sma_200w = 100.0
    neutral_candidate.spot = 82.0
    neutral_candidate.ohlcv_daily = _alternating(80.0, 100.0)
    assert classify(neutral_candidate).tipo != "T3"


def test_classify_t4_happy_path(neutral_candidate):
    neutral_candidate.sma_50w = 100.0
    neutral_candidate.sma_200w = 100.0
    neutral_candidate.spot = 98.0  # no > SMA200W → T1 no matchea
    neutral_candidate.rsi_d = 45.0
    neutral_candidate.earnings_history = [_earnings(days_ago=20)]
    neutral_candidate.ohlcv_daily = _post_earnings(date.today() - timedelta(days=20), 100.0, 93.0)
    assert classify(neutral_candidate).tipo == "T4"


def test_classify_t4_fails_without_earnings(neutral_candidate):
    neutral_candidate.sma_50w = 100.0
    neutral_candidate.sma_200w = 100.0
    neutral_candidate.spot = 98.0
    neutral_candidate.rsi_d = 45.0
    neutral_candidate.earnings_history = []
    neutral_candidate.ohlcv_daily = _post_earnings(date.today() - timedelta(days=20), 100.0, 93.0)
    assert classify(neutral_candidate).tipo != "T4"


def test_classify_t4_fails_when_drop_insufficient(neutral_candidate):
    neutral_candidate.sma_50w = 100.0
    neutral_candidate.sma_200w = 100.0
    neutral_candidate.spot = 98.0
    neutral_candidate.rsi_d = 45.0
    neutral_candidate.earnings_history = [_earnings(days_ago=20)]
    neutral_candidate.ohlcv_daily = _post_earnings(date.today() - timedelta(days=20), 100.0, 98.0)
    assert classify(neutral_candidate).tipo != "T4"


def test_classify_priority_t1_over_t2(neutral_candidate):
    neutral_candidate.sma_50w = 120.0
    neutral_candidate.sma_200w = 100.0
    neutral_candidate.spot = 105.0  # T1 ✓
    neutral_candidate.ohlcv_daily = _with_drop(100.0, -0.12)  # T2 ✓
    result = classify(neutral_candidate)
    assert result.tipo == "T1"
    assert "T2" in result.matches_multiple


def test_classify_priority_t2_over_t3(neutral_candidate):
    neutral_candidate.sma_50w = 100.0
    neutral_candidate.sma_200w = 100.0
    neutral_candidate.spot = 89.0  # cerca del piso del rango con caída
    neutral_candidate.ohlcv_daily = _with_drop(100.0, -0.12)
    result = classify(neutral_candidate)
    assert result.tipo == "T2"
    assert "T3" in result.matches_multiple


def test_classify_no_match(neutral_candidate):
    neutral_candidate.sma_50w = 100.0
    neutral_candidate.sma_200w = 100.0
    neutral_candidate.spot = 100.0
    neutral_candidate.ohlcv_daily = _flat(100.0)
    result = classify(neutral_candidate)
    assert result.tipo is None
    assert result.justificacion
