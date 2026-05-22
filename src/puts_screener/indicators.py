"""Indicadores técnicos: funciones puras sobre OHLCV (sin pandas_ta).

RSI y ATR usan el suavizado de Wilder (EWM con alpha=1/length, adjust=False).
MACD usa EMAs 12/26/9. HV Percentile usa volatilidad histórica 20d anualizada.

Casos degenerados de RSI:
- avg_loss == 0 y avg_gain > 0  → RSI = 100 (tendencia pura al alza).
- avg_loss == 0 y avg_gain == 0 (serie constante) → RSI = 50 (neutral, por convención).

El suavizado por EWM no genera NaN de warmup: las series de RSI/MACD tienen el
mismo largo que el input (los primeros valores son menos confiables, no NaN).
"""

import numpy as np
import pandas as pd

_RSI_LENGTH = 14
_ATR_LENGTH = 14
_MACD_FAST = 12
_MACD_SLOW = 26
_MACD_SIGNAL = 9
_TRADING_DAYS_YEAR = 252
_HV_WINDOW = 20
_HV_PERCENTILE_WINDOW = 252
_HV_MIN_DATA = _HV_WINDOW + _HV_PERCENTILE_WINDOW  # 272
_WEEKLY_RULE = "W-FRI"
_NEUTRAL_RSI = 50.0
_MAX_RSI = 100.0
_EPS = 1e-9


def _weekly_close(ohlcv_daily: pd.DataFrame) -> pd.Series:
    return ohlcv_daily["Close"].resample(_WEEKLY_RULE).last().dropna()


def _rsi_series(close: pd.Series, length: int) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.mask((avg_loss == 0) & (avg_gain > 0), _MAX_RSI)
    rsi = rsi.mask((avg_loss == 0) & (avg_gain == 0), _NEUTRAL_RSI)
    return rsi


def sma_weekly(ohlcv_daily: pd.DataFrame, weeks: int) -> float:
    """SMA de `weeks` semanas computado sobre cierres semanales (resample W-FRI).

    Raises:
        ValueError: si hay menos de `weeks` semanas de data.
    """
    weekly = _weekly_close(ohlcv_daily)
    if len(weekly) < weeks:
        raise ValueError(f"sma_weekly: se necesitan {weeks} semanas, hay {len(weekly)}")
    return float(weekly.rolling(weeks).mean().iloc[-1])


def sma_daily(ohlcv_daily: pd.DataFrame, length: int) -> float | None:
    """SMA simple sobre cierres diarios. None si hay menos de `length` días."""
    close = ohlcv_daily["Close"]
    if len(close) < length:
        return None
    return float(close.rolling(length).mean().iloc[-1])


def ema_daily(ohlcv_daily: pd.DataFrame, length: int) -> float | None:
    """EMA sobre cierres diarios (adjust=False). None si hay menos de `length` días."""
    close = ohlcv_daily["Close"]
    if len(close) < length:
        return None
    return float(close.ewm(span=length, adjust=False).mean().iloc[-1])


def rsi_daily(ohlcv_daily: pd.DataFrame, length: int = _RSI_LENGTH) -> float:
    """Último valor del RSI sobre cierres diarios."""
    return float(_rsi_series(ohlcv_daily["Close"], length).iloc[-1])


def rsi_daily_series(ohlcv_daily: pd.DataFrame, length: int = _RSI_LENGTH) -> pd.Series:
    """Serie completa de RSI sobre cierres diarios (para cálculo de pendiente)."""
    return _rsi_series(ohlcv_daily["Close"], length)


def rsi_weekly(ohlcv_daily: pd.DataFrame, length: int = _RSI_LENGTH) -> float:
    """Último valor del RSI sobre cierres semanales (resample W-FRI)."""
    return float(_rsi_series(_weekly_close(ohlcv_daily), length).iloc[-1])


def rsi_weekly_series(ohlcv_daily: pd.DataFrame, length: int = _RSI_LENGTH) -> pd.Series:
    """Serie completa de RSI sobre cierres semanales."""
    return _rsi_series(_weekly_close(ohlcv_daily), length)


def _macd_histogram(close: pd.Series) -> pd.Series:
    ema_fast = close.ewm(span=_MACD_FAST, adjust=False).mean()
    ema_slow = close.ewm(span=_MACD_SLOW, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=_MACD_SIGNAL, adjust=False).mean()
    return macd_line - signal_line


def macd_hist_series(ohlcv_daily: pd.DataFrame) -> pd.Series:
    """Serie completa del histograma MACD (12/26/9) — para detección de divergencias."""
    return _macd_histogram(ohlcv_daily["Close"])


def macd_state(
    ohlcv_daily: pd.DataFrame,
    lookback_days: int = 3,
    neutral_pct: float = 0.05,
) -> str:
    """Estado del histograma MACD (12/26/9).

    Returns:
        Uno de: "subiendo_negativo", "subiendo_positivo", "bajando_positivo",
        "bajando_negativo", "neutral".
    """
    hist = _macd_histogram(ohlcv_daily["Close"])
    hist_today = float(hist.iloc[-1])
    hist_prev = float(hist.iloc[-lookback_days - 1])

    if abs(hist_prev) < _EPS:
        if abs(hist_today) < _EPS:
            return "neutral"
        direction = "subiendo" if hist_today > 0 else "bajando"
    elif abs(hist_today - hist_prev) / abs(hist_prev) < neutral_pct:
        return "neutral"
    else:
        direction = "subiendo" if hist_today > hist_prev else "bajando"

    sign = "positivo" if hist_today >= 0 else "negativo"
    return f"{direction}_{sign}"


def atr_series(ohlcv_daily: pd.DataFrame, length: int = _ATR_LENGTH) -> pd.Series:
    """Serie completa del ATR (Wilder) — para detección de pivots y clustering de zonas."""
    high = ohlcv_daily["High"]
    low = ohlcv_daily["Low"]
    prev_close = ohlcv_daily["Close"].shift(1)
    true_range = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return true_range.ewm(alpha=1 / length, adjust=False).mean()


def atr_14(ohlcv_daily: pd.DataFrame) -> float:
    """Último valor del ATR de 14 días (Wilder)."""
    return float(atr_series(ohlcv_daily, _ATR_LENGTH).iloc[-1])


def hv_percentile_52w(ohlcv_daily: pd.DataFrame) -> float:
    """Percentil de la volatilidad histórica 20d actual vs la ventana 52w.

    HV20 = std(log_returns) * sqrt(252) sobre ventana rolling de 20 días hábiles.
    El percentil es: count(HV20_serie <= HV20_today) / 252 * 100 (escala 0-100).

    Raises:
        ValueError: si hay menos de 272 días de data (20 para HV20 + 252 para percentil).
    """
    close = ohlcv_daily["Close"]
    if len(close) < _HV_MIN_DATA:
        raise ValueError(f"hv_percentile_52w: se necesitan {_HV_MIN_DATA} días, hay {len(close)}")
    log_returns = np.log(close / close.shift(1)).dropna()
    hv20_series = (log_returns.rolling(_HV_WINDOW).std() * np.sqrt(_TRADING_DAYS_YEAR)).dropna()
    hv20_today = hv20_series.iloc[-1]
    hv20_window = hv20_series.iloc[-_HV_PERCENTILE_WINDOW:]
    return float((hv20_window <= hv20_today).sum() / len(hv20_window) * 100)
