"""Tests de la narrativa heurística (spec 07 §8.6). Funciones puras, candidatos sintéticos."""

from datetime import date, datetime

import pandas as pd

from puts_screener.binary_events import BinaryEventsReport
from puts_screener.macro_calendar import MacroEvent
from puts_screener.models_final import FinalCandidate
from puts_screener.models_screening import ScreenedCandidate, TypeClassification
from puts_screener.models_support import (
    SupportAnalysis,
    SupportedCandidate,
    SupportLevel,
    SupportZone,
)
from puts_screener.narrative import build_narrative
from puts_screener.providers.models import AnalystData, CompanyProfile, FinancialSnapshot


def _tiny_ohlcv() -> pd.DataFrame:
    idx = pd.bdate_range("2026-01-01", periods=1)
    return pd.DataFrame(
        {"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [1.0], "Volume": [1]}, index=idx
    )


def _make_zone(
    score=14.0,  # 14.0 → score_tier == 4 (SCORE_TIER_THRESHOLDS); el tier es property derivada
    lower=93.0,
    upper=95.0,
    center=94.0,
    distance_pct=0.05,
    heavy_elements=("sma_200w", "polarity", "avwap_earnings", "hvn"),
) -> SupportZone:
    elements = [SupportLevel(price=center, element=name) for name in heavy_elements]
    return SupportZone(
        center_price=center,
        lower_bound=lower,
        upper_bound=upper,
        score=score,
        elements=elements,
        has_dynamic_confirmer=True,
        distance_pct=distance_pct,
    )


def _make_binary(earnings_in, ex_div_in, macro_in_window) -> BinaryEventsReport:
    macro = (
        [MacroEvent(date=date(2026, 6, 10), kind="fomc", description="FOMC")]
        if macro_in_window
        else []
    )
    return BinaryEventsReport(
        earnings_date=date(2026, 6, 1) if earnings_in is not None else None,
        dias_a_earnings=earnings_in,
        earnings_en_45d=earnings_in is not None,
        ex_div_date=date(2026, 6, 1) if ex_div_in is not None else None,
        dias_a_ex_div=ex_div_in,
        ex_div_en_45d=ex_div_in is not None,
        ex_div_amount=0.50 if ex_div_in is not None else None,
        eventos_macro=macro,
        eventos_macro_en_45d=bool(macro),
        tiene_eventos_binarios=bool(earnings_in or ex_div_in or macro),
        flags_legibles=[],
    )


def _make_candidate(
    ticker="AAPL",
    tipo="T1",
    currency="USD",
    spot=100.0,
    atr=2.0,
    rsi_d=42.0,
    rsi_d_3d_ago=38.0,
    rsi_w=47.0,
    macd_state="subiendo_positivo",
    zone=None,
    earnings_in=None,
    ex_div_in=None,
    macro_in_window=False,
) -> FinalCandidate:
    zone = zone if zone is not None else _make_zone()
    profile = CompanyProfile(
        ticker=ticker,
        name=f"{ticker} Inc.",
        sector="Technology",
        industry="Software",
        exchange="NMS",
        country="United States",
        market_cap_usd=5e10,
        currency=currency,
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
        ticker=ticker,
        price_target_mean=120.0,
        price_target_median=None,
        price_target_high=None,
        price_target_low=None,
        n_analysts=20,
        recommendation_mean=2.0,
    )
    screened = ScreenedCandidate(
        ticker=ticker,
        profile=profile,
        financials=financials,
        analyst=analyst,
        rating_changes_6w=[],
        upcoming_earnings=None,
        earnings_history=[],
        ohlcv_daily=_tiny_ohlcv(),
        ohlcv_weekly=_tiny_ohlcv(),
        classification=TypeClassification(tipo=tipo, justificacion=f"motivo {tipo}"),
        spot=spot,
        rsi_d=rsi_d,
        rsi_d_3d_ago=rsi_d_3d_ago,
        rsi_w=rsi_w,
        macd_state=macd_state,
        atr_14=atr,
    )
    analysis = SupportAnalysis(valid_zones=[zone], rejected_zones=[], best_zone=zone)
    supported = SupportedCandidate(screened=screened, analysis=analysis, pasa_paso_2=True)
    binary = _make_binary(earnings_in, ex_div_in, macro_in_window)
    return FinalCandidate(
        supported=supported,
        binary_events=binary,
        fetched_at=datetime(2026, 5, 27, 16, 0),
        errors=[],
    )


def test_narrative_t1_full():
    zone = _make_zone(heavy_elements=("sma_200w", "polarity", "avwap_earnings", "hvn"))
    out = build_narrative(_make_candidate(tipo="T1", zone=zone, earnings_in=10))
    assert "tendencia alcista" in out
    assert "SMA200" in out
    assert "Earnings en 10 días" in out
    assert out.count("<p>") == 3


def test_narrative_t2_panico():
    out = build_narrative(_make_candidate(tipo="T2"))
    assert "pánico" in out or "spike de IV" in out


def test_narrative_zone_compact_vs_wide():
    compact = build_narrative(
        _make_candidate(zone=_make_zone(lower=99.4, upper=100.6, center=100.0))
    )
    assert "compacta" in compact
    wide = build_narrative(_make_candidate(zone=_make_zone(lower=98.1, upper=101.9, center=100.0)))
    assert "amplia" in wide


def test_narrative_omits_momentum_when_missing():
    out = build_narrative(_make_candidate(rsi_d=42.0, rsi_d_3d_ago=42.0, macd_state="neutral"))
    assert "RSI diario" not in out
    assert "MACD virando" not in out


def test_narrative_clean_no_events():
    out = build_narrative(_make_candidate(earnings_in=None, ex_div_in=None, macro_in_window=False))
    assert "situación técnica limpia" in out


def test_narrative_multiple_events():
    out = build_narrative(_make_candidate(earnings_in=10, ex_div_in=5, macro_in_window=True))
    assert "Earnings en 10 días" in out
    assert "Ex-dividend en 5 días" in out
    assert "Eventos macro en ventana" in out


def test_narrative_dedup_sma200():
    zone = _make_zone(heavy_elements=("sma_200w", "ema_200d", "sma_200d"))
    out = build_narrative(_make_candidate(zone=zone))
    assert out.count("SMA200") == 1


def test_narrative_avwap_anchor_from_label():
    zone = _make_zone(heavy_elements=("sma_200w", "avwap_earnings"))
    out = build_narrative(_make_candidate(zone=zone))
    assert "AVWAP desde earnings" in out


def test_narrative_distance_at_edge():
    out = build_narrative(_make_candidate(zone=_make_zone(distance_pct=0.085)))
    assert "al límite del rango operable" in out


def test_narrative_html_structure():
    out = build_narrative(_make_candidate())
    assert out.startswith("<p>")
    assert out.endswith("</p>")
    assert out.count("<p>") == 3
    assert out.count("</p>") == 3
    for para in out.split("\n"):
        assert para.startswith("<p><strong>")
