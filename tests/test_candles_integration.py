"""Tests de integración de spec 11 (tanda 3): analyze_candles sobre zona reconstruida +
persistencia idempotente + round-trip de candle_signals_json (§8)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

import pandas as pd

from puts_screener.candle_patterns import analyze_candles, has_bearish_kind, has_bullish_kind
from puts_screener.models_screening import ScreenedCandidate
from puts_screener.models_support import (
    SupportAnalysis,
    SupportedCandidate,
    SupportLevel,
    SupportZone,
)
from puts_screener.persistence import save_run, save_support_analysis
from puts_screener.providers.models import AnalystData, CompanyProfile, FinancialSnapshot

ZONE = SupportZone(
    center_price=98.5,
    lower_bound=95.0,
    upper_bound=100.0,
    score=10.0,
    elements=[
        SupportLevel(price=97.0, element="sma_200d"),
        SupportLevel(price=99.0, element="ema_200d"),
    ],
    has_dynamic_confirmer=True,
    distance_pct=0.03,
)


def _make_ohlcv(opens, highs, lows, closes) -> pd.DataFrame:
    idx = pd.bdate_range("2024-01-02", periods=len(closes))
    return pd.DataFrame(
        {"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": 1_000_000.0},
        index=idx,
    )


class TestAnalyzeCandlesOnReconstructedZone:
    def test_consolida_hammer_dentro_de_zona(self) -> None:
        # Reconstruye la zona desde JSON (round-trip), como haría un caller sobre data persistida.
        elements_json = json.dumps(
            [
                {"price": e.price, "element": e.element, "metadata": e.metadata}
                for e in ZONE.elements
            ]
        )
        reconstructed = SupportZone(
            center_price=ZONE.center_price,
            lower_bound=ZONE.lower_bound,
            upper_bound=ZONE.upper_bound,
            score=ZONE.score,
            elements=[
                SupportLevel(price=e["price"], element=e["element"], metadata=e["metadata"])
                for e in json.loads(elements_json)
            ],
            has_dynamic_confirmer=ZONE.has_dynamic_confirmer,
            distance_pct=ZONE.distance_pct,
        )

        ohlcv = _make_ohlcv(
            opens=[100.0, 99.0],
            highs=[100.2, 99.1],
            lows=[99.8, 96.0],  # mecha larga hasta 96, dentro de [95,100]
            closes=[99.9, 98.9],  # cuerpo pequeño, cierre alto -> hammer
        )
        atr = pd.Series(1.0, index=ohlcv.index)

        analysis = analyze_candles(ohlcv, atr, reconstructed)

        assert analysis.has_bullish_confirmation is True
        assert analysis.has_bearish_breakdown is False
        assert analysis.strongest_bullish is not None
        assert analysis.strongest_bullish.kind == "wick_rejection"
        assert any(s.kind == "wick_rejection" for s in analysis.signals)


def _build_supported(ticker: str, candle_signals: tuple[str, ...]) -> SupportedCandidate:
    """SupportedCandidate mínimo para ejercitar save_run/save_support_analysis sin depender del
    fixture de tests/final/conftest.py (fuera de scope para tests/, no es visible acá)."""
    profile = CompanyProfile(
        ticker=ticker,
        name=f"{ticker} Inc.",
        sector="Technology",
        industry="Software",
        exchange="NMS",
        country="United States",
        market_cap_usd=50e9,
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
        ticker=ticker, price_target_mean=110.0, price_target_median=None, price_target_high=None,
        price_target_low=None, n_analysts=20, recommendation_mean=2.0,
    )
    screened = ScreenedCandidate(
        ticker=ticker,
        profile=profile,
        financials=financials,
        analyst=analyst,
        rating_changes_6w=[],
        upcoming_earnings=None,
        earnings_history=[],
        ohlcv_daily=_make_ohlcv([100.0], [100.0], [100.0], [100.0]),
        ohlcv_weekly=_make_ohlcv([100.0], [100.0], [100.0], [100.0]),
        spot=100.0,
        atr_14=2.0,
        candle_signals=candle_signals,
    )
    analysis = SupportAnalysis(valid_zones=[ZONE], rejected_zones=[], best_zone=ZONE)
    return SupportedCandidate(screened=screened, analysis=analysis, pasa_paso_2=True)


class TestPersistenciaIdempotente:
    def test_dos_corridas_no_duplican_ni_pisan(self, tmp_path) -> None:
        db = tmp_path / "candles.db"
        supported = _build_supported("CDL", ("wick_rejection", "body_reclaim_engulfing"))

        run_id = save_run(
            [supported.screened], universe_size=1, started_at=datetime.now(), db_path=db
        )
        save_support_analysis(run_id, [supported], db_path=db)
        save_support_analysis(run_id, [supported], db_path=db)  # 2da corrida: idempotente

        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM candidates WHERE run_id = ? AND ticker = ?", (run_id, "CDL")
        ).fetchall()
        conn.close()

        assert len(rows) == 1  # no duplicó la fila
        row = dict(rows[0])
        assert row["candle_bullish_confirmation"] == 1
        assert row["candle_bearish_breakdown"] == 0

    def test_round_trip_candle_signals_json(self, tmp_path) -> None:
        db = tmp_path / "candles2.db"
        kinds = ("bearish_engulfing", "wick_rejection")
        supported = _build_supported("RT", kinds)

        run_id = save_run(
            [supported.screened], universe_size=1, started_at=datetime.now(), db_path=db
        )
        save_support_analysis(run_id, [supported], db_path=db)

        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        row = dict(
            conn.execute(
                "SELECT * FROM candidates WHERE run_id = ? AND ticker = ?", (run_id, "RT")
            ).fetchone()
        )
        conn.close()

        assert set(json.loads(row["candle_signals_json"])) == set(kinds)
        assert row["candle_bullish_confirmation"] == 1  # wick_rejection presente
        assert row["candle_bearish_breakdown"] == 1  # bearish_engulfing presente
        assert has_bullish_kind(kinds) is True
        assert has_bearish_kind(kinds) is True
