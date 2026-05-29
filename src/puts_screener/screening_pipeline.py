"""Pipeline de screening: orquesta el fetch paralelo, cálculo de indicadores,
clasificación, filtrado y persistencia para un universo completo de tickers.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from puts_screener.config_filters import (
    MACD_LOOKBACK_DAYS,
    MACD_NEUTRAL_PCT_CHANGE,
    RSI_DAILY_LOOKBACK_DAYS,
    RSI_WEEKLY_LOOKBACK_WEEKS,
)
from puts_screener.filters_step1 import apply_step1_filters, compute_momentum_score
from puts_screener.indicators import (
    atr_14,
    hv_percentile_52w,
    macd_state,
    rsi_daily,
    rsi_daily_series,
    rsi_weekly,
    rsi_weekly_series,
    sma_weekly,
)
from puts_screener.models_screening import ScreenedCandidate
from puts_screener.persistence import save_run
from puts_screener.providers.service import DataService

logger = logging.getLogger(__name__)

OHLCV_LOOKBACK_DAYS = 1500  # alineado con OHLCV_ROLLING_DAYS de spec 01
EARNINGS_LOOKBACK_DAYS = 90  # cubre T4_LOOKBACK_DAYS (60) con margen
_MIN_OHLCV_DAYS = 252  # mínimo para HV percentile / indicadores
_PROGRESS_EVERY = 50

# Parámetros del MACD para recomputar el histograma histórico (12/26/9).
_MACD_FAST = 12
_MACD_SLOW = 26
_MACD_SIGNAL = 9


def _fetch_all_data(ticker: str, data_service: DataService) -> dict:
    """Hace los 7 fetches por ticker. Campos que fallan quedan en None y en `_errors`."""
    today = date.today()
    start_ohlcv = today - timedelta(days=OHLCV_LOOKBACK_DAYS)

    data: dict = {"_errors": []}

    def _try(label, callable_):
        try:
            return callable_()
        except Exception as exc:
            msg = f"{label}: {type(exc).__name__}: {str(exc)[:80]}"
            data["_errors"].append(msg)
            logger.warning("[%s] %s", ticker, msg)
            return None

    data["ohlcv_daily"] = _try(
        "ohlcv_daily", lambda: data_service.get_ohlcv(ticker, start_ohlcv, today, "1d")
    )
    data["profile"] = _try("profile", lambda: data_service.get_company_profile(ticker))
    data["financials"] = _try("financials", lambda: data_service.get_financials(ticker))
    data["analyst"] = _try("analyst", lambda: data_service.get_analyst_data(ticker))
    data["rating_changes"] = _try(
        "ratings", lambda: data_service.get_rating_changes(ticker, lookback_weeks=6)
    )
    data["upcoming_earnings"] = _try(
        "upcoming_earnings", lambda: data_service.get_upcoming_earnings(ticker)
    )
    data["earnings_history"] = _try(
        "earnings_history",
        lambda: data_service.get_historical_earnings(ticker, lookback_days=EARNINGS_LOOKBACK_DAYS),
    )
    return data


def _compute_macd_hist_n_days_ago(ohlcv_d: pd.DataFrame, days: int) -> float:
    """Valor del histograma MACD hace `days` días (0.0 si no hay suficiente data)."""
    try:
        close = ohlcv_d["Close"]
        ema_fast = close.ewm(span=_MACD_FAST, adjust=False).mean()
        ema_slow = close.ewm(span=_MACD_SLOW, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=_MACD_SIGNAL, adjust=False).mean()
        histogram = macd_line - signal_line
        if len(histogram) > days:
            return float(histogram.iloc[-(days + 1)])
        return 0.0
    except (KeyError, IndexError, ValueError):
        return 0.0


def _build_candidate(ticker: str, raw: dict) -> ScreenedCandidate | None:
    """Construye un ScreenedCandidate desde la data cruda. None si falta data crítica."""
    if (
        raw["ohlcv_daily"] is None
        or raw["profile"] is None
        or raw["financials"] is None
        or raw["analyst"] is None
    ):
        logger.warning("[%s] missing critical data, skipping", ticker)
        return None

    ohlcv_d: pd.DataFrame = raw["ohlcv_daily"]
    if len(ohlcv_d) < _MIN_OHLCV_DAYS:
        logger.warning("[%s] insufficient OHLCV (%d days), skipping", ticker, len(ohlcv_d))
        return None

    ohlcv_w = (
        ohlcv_d.resample("W-FRI")
        .agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
        .dropna()
    )

    errors: list[str] = list(raw["_errors"])

    def _safe_compute(label, fn, default):
        try:
            return fn()
        except Exception as exc:
            errors.append(f"indicator {label}: {type(exc).__name__}: {str(exc)[:60]}")
            return default

    spot = float(ohlcv_d["Close"].iloc[-1])
    sma_50w_val = _safe_compute("sma_50w", lambda: sma_weekly(ohlcv_d, weeks=50), 0.0)
    sma_200w_val = _safe_compute("sma_200w", lambda: sma_weekly(ohlcv_d, weeks=200), 0.0)
    rsi_d_val = _safe_compute("rsi_d", lambda: rsi_daily(ohlcv_d), 0.0)
    rsi_d_series = _safe_compute("rsi_d_series", lambda: rsi_daily_series(ohlcv_d), pd.Series())
    rsi_w_val = _safe_compute("rsi_w", lambda: rsi_weekly(ohlcv_d), 0.0)
    rsi_w_series = _safe_compute("rsi_w_series", lambda: rsi_weekly_series(ohlcv_d), pd.Series())
    macd_state_val = _safe_compute(
        "macd_state",
        lambda: macd_state(
            ohlcv_d, lookback_days=MACD_LOOKBACK_DAYS, neutral_pct=MACD_NEUTRAL_PCT_CHANGE
        ),
        "neutral",
    )
    atr_val = _safe_compute("atr_14", lambda: atr_14(ohlcv_d), 0.0)
    hv_pct = _safe_compute("hv_percentile", lambda: hv_percentile_52w(ohlcv_d), 50.0)

    rsi_d_3d_ago = (
        float(rsi_d_series.iloc[-(RSI_DAILY_LOOKBACK_DAYS + 1)])
        if len(rsi_d_series) > RSI_DAILY_LOOKBACK_DAYS
        else rsi_d_val
    )
    rsi_w_2w_ago = (
        float(rsi_w_series.iloc[-(RSI_WEEKLY_LOOKBACK_WEEKS + 1)])
        if len(rsi_w_series) > RSI_WEEKLY_LOOKBACK_WEEKS
        else rsi_w_val
    )
    macd_hist_3d_ago = _compute_macd_hist_n_days_ago(ohlcv_d, MACD_LOOKBACK_DAYS)

    analyst = raw["analyst"]
    price_target = analyst.price_target_mean or 0.0
    price_target_upside = (price_target / spot - 1) if (price_target and spot > 0) else 0.0

    total_recs = (
        analyst.strong_buy_count
        + analyst.buy_count
        + analyst.hold_count
        + analyst.sell_count
        + analyst.strong_sell_count
    )
    buy_ratio = (
        (analyst.strong_buy_count + analyst.buy_count) / total_recs if total_recs > 0 else 0.0
    )

    six_weeks_ago = date.today() - timedelta(weeks=6)
    downgrades_count = sum(
        1
        for rc in (raw["rating_changes"] or [])
        if rc.action == "downgrade" and rc.date >= six_weeks_ago
    )

    return ScreenedCandidate(
        ticker=ticker,
        profile=raw["profile"],
        financials=raw["financials"],
        analyst=analyst,
        rating_changes_6w=raw["rating_changes"] or [],
        upcoming_earnings=raw["upcoming_earnings"],
        earnings_history=raw["earnings_history"] or [],
        ohlcv_daily=ohlcv_d,
        ohlcv_weekly=ohlcv_w,
        spot=spot,
        sma_50w=sma_50w_val,
        sma_200w=sma_200w_val,
        rsi_d=rsi_d_val,
        rsi_d_3d_ago=rsi_d_3d_ago,
        rsi_w=rsi_w_val,
        rsi_w_2w_ago=rsi_w_2w_ago,
        macd_state=macd_state_val,
        macd_hist_3d_ago=macd_hist_3d_ago,
        atr_14=atr_val,
        hv_percentile_52w=hv_pct,
        price_target_upside_pct=price_target_upside,
        recommendation_buy_ratio=buy_ratio,
        downgrades_6w_count=downgrades_count,
        fetched_at=datetime.now(),
        errors=errors,
    )


def _process_ticker(ticker: str, data_service: DataService) -> ScreenedCandidate | None:
    """Pipeline completo para un solo ticker. None si falta data crítica."""
    try:
        raw = _fetch_all_data(ticker, data_service)
        candidate = _build_candidate(ticker, raw)
        if candidate is None:
            return None
        # Spec 10: classification (régimen + triggers) corre post-Paso 2 en final_pipeline.
        apply_step1_filters(candidate)
        candidate.momentum_score = compute_momentum_score(candidate)
        return candidate
    except Exception:
        logger.exception("[%s] unexpected error in pipeline", ticker)
        return None


def _universe_tag(universe: list[str] | dict[str, set[str]], ticker: str) -> tuple[str, ...]:
    """Tag de pertenencia (tupla ordenada) para un ticker. Vacío si el universo es una lista."""
    if isinstance(universe, dict):
        return tuple(sorted(universe.get(ticker, set())))
    return ()


def run_screening(
    universe: list[str] | dict[str, set[str]],
    data_service: DataService,
    max_workers: int = 8,
    persist: bool = True,
    db_path: Path | None = None,
    requested_universes: list[str] | None = None,
) -> tuple[str | None, list[ScreenedCandidate]]:
    """Corre el screening completo sobre el universo en paralelo.

    Args:
        universe: o bien una lista de tickers (sin tag de universo), o un mapping
            ticker → set de universos. Con el mapping se propaga el tag a cada candidato.
        requested_universes: lista de universos solicitados al CLI; se persiste en
            `runs.universes_json` (no se deriva del mapping).

    Returns:
        (run_id, candidates). run_id es None si persist=False. `candidates` incluye
        todos los tickers procesados (pasen o no); los que fallaron data crítica no
        están en la lista pero cuentan en universe_size.
    """
    started_at = datetime.now()
    logger.info("Starting screening: %d tickers, %d workers", len(universe), max_workers)

    candidates: list[ScreenedCandidate] = []
    failed_count = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_ticker = {
            executor.submit(_process_ticker, ticker, data_service): ticker for ticker in universe
        }
        for i, future in enumerate(as_completed(future_to_ticker), 1):
            ticker = future_to_ticker[future]
            try:
                candidate = future.result()
            except Exception:
                logger.exception("[%s] unexpected pipeline error", ticker)
                failed_count += 1
                continue
            if candidate is None:
                failed_count += 1
                continue
            candidate.universes = _universe_tag(universe, ticker)
            candidates.append(candidate)
            if i % _PROGRESS_EVERY == 0:
                logger.info("Progress: %d / %d processed", i, len(universe))

    duration = (datetime.now() - started_at).total_seconds()
    passed = sum(1 for c in candidates if c.pasa_filtros_paso_1)
    high_momentum = sum(1 for c in candidates if c.momentum_score >= 2)

    logger.info("=" * 60)
    logger.info("Screening complete in %.1fs", duration)
    logger.info("  Universe size: %d", len(universe))
    logger.info("  Processed successfully: %d", len(candidates))
    logger.info("  Failed (critical data missing): %d", failed_count)
    logger.info("  Passed all filters: %d", passed)
    logger.info("  With momentum_score >= 2: %d", high_momentum)

    run_id: str | None = None
    if persist:
        run_id = save_run(
            candidates,
            universe_size=len(universe),
            started_at=started_at,
            db_path=db_path,
            requested_universes=requested_universes,
        )
        logger.info("  Run id: %s", run_id)

    return run_id, candidates
