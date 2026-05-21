import dataclasses

from puts_screener.filters_step1 import (
    apply_step1_filters,
    filter_hv_percentile,
    filter_momentum,
    filter_quality_liquidity,
    filter_valuation,
)


def _with_profile(candidate, **changes):
    candidate.profile = dataclasses.replace(candidate.profile, **changes)
    return candidate


def _with_financials(candidate, **changes):
    candidate.financials = dataclasses.replace(candidate.financials, **changes)
    return candidate


# --- quality / liquidity ---


def test_filter_quality_liquidity_passes(neutral_candidate):
    assert filter_quality_liquidity(neutral_candidate) == (True, None)


def test_filter_quality_liquidity_fails_low_market_cap(neutral_candidate):
    _with_profile(neutral_candidate, market_cap_usd=1e9)
    passes, reason = filter_quality_liquidity(neutral_candidate)
    assert passes is False
    assert "market cap" in reason


def test_filter_quality_liquidity_fails_low_volume(neutral_candidate):
    _with_profile(neutral_candidate, avg_daily_volume_3m=500_000)
    passes, reason = filter_quality_liquidity(neutral_candidate)
    assert passes is False
    assert "volume" in reason


def test_filter_quality_liquidity_fails_negative_fcf(neutral_candidate):
    _with_financials(neutral_candidate, free_cash_flow_ttm=-1e9)
    passes, reason = filter_quality_liquidity(neutral_candidate)
    assert passes is False
    assert "FCF" in reason


def test_filter_quality_liquidity_fails_none_values(neutral_candidate):
    _with_profile(neutral_candidate, market_cap_usd=None)
    passes, reason = filter_quality_liquidity(neutral_candidate)
    assert passes is False


# --- valuation ---


def test_filter_valuation_passes(neutral_candidate):
    assert filter_valuation(neutral_candidate) == (True, None)


def test_filter_valuation_fails_no_upside(neutral_candidate):
    neutral_candidate.price_target_upside_pct = -0.05
    passes, reason = filter_valuation(neutral_candidate)
    assert passes is False
    assert "upside" in reason


def test_filter_valuation_fails_low_buy_ratio(neutral_candidate):
    neutral_candidate.recommendation_buy_ratio = 0.3
    passes, reason = filter_valuation(neutral_candidate)
    assert passes is False
    assert "buy ratio" in reason


def test_filter_valuation_skips_downgrades_for_eu(neutral_candidate):
    _with_profile(neutral_candidate, country="United Kingdom")
    neutral_candidate.downgrades_6w_count = 5
    assert filter_valuation(neutral_candidate) == (True, None)


def test_filter_valuation_fails_downgrades_for_us(neutral_candidate):
    _with_profile(neutral_candidate, country="United States")
    neutral_candidate.downgrades_6w_count = 3
    passes, reason = filter_valuation(neutral_candidate)
    assert passes is False
    assert "downgrades" in reason


# --- momentum ---


def test_filter_momentum_passes_with_rsi_d(neutral_candidate):
    neutral_candidate.rsi_d = 40.0
    neutral_candidate.rsi_d_3d_ago = 35.0
    assert filter_momentum(neutral_candidate) == (True, None)


def test_filter_momentum_passes_with_rsi_w_only(neutral_candidate):
    neutral_candidate.rsi_d = 60.0  # no califica
    neutral_candidate.rsi_w = 45.0
    neutral_candidate.rsi_w_2w_ago = 42.0
    assert filter_momentum(neutral_candidate) == (True, None)


def test_filter_momentum_passes_with_macd_only(neutral_candidate):
    neutral_candidate.rsi_d = 60.0
    neutral_candidate.rsi_w = 60.0
    neutral_candidate.macd_state = "subiendo_negativo"
    assert filter_momentum(neutral_candidate) == (True, None)


def test_filter_momentum_fails_all_neutral(neutral_candidate):
    passes, reason = filter_momentum(neutral_candidate)
    assert passes is False
    assert "momento débil" in reason


# --- hv percentile ---


def test_filter_hv_percentile_passes(neutral_candidate):
    neutral_candidate.hv_percentile_52w = 50.0
    assert filter_hv_percentile(neutral_candidate) == (True, None)


def test_filter_hv_percentile_fails_too_low(neutral_candidate):
    neutral_candidate.hv_percentile_52w = 20.0
    passes, reason = filter_hv_percentile(neutral_candidate)
    assert passes is False
    assert "<" in reason


def test_filter_hv_percentile_fails_too_high(neutral_candidate):
    neutral_candidate.hv_percentile_52w = 85.0
    passes, reason = filter_hv_percentile(neutral_candidate)
    assert passes is False
    assert ">" in reason


# --- orquestador ---


def test_apply_step1_all_pass(neutral_candidate):
    # ajustar momentum para que pase (el resto ya pasa por default)
    neutral_candidate.rsi_d = 40.0
    neutral_candidate.rsi_d_3d_ago = 35.0
    result = apply_step1_filters(neutral_candidate)
    assert result.pasa_filtros_paso_1 is True
    assert result.motivos_rechazo == []


def test_apply_step1_collects_all_failures(neutral_candidate):
    _with_profile(neutral_candidate, market_cap_usd=1e9)  # quality fail
    neutral_candidate.recommendation_buy_ratio = 0.3  # valuation fail
    # momentum fail (RSI 60 neutral, MACD neutral por default)
    neutral_candidate.hv_percentile_52w = 50.0  # hv pasa
    result = apply_step1_filters(neutral_candidate)
    assert result.pasa_filtros_paso_1 is False
    assert len(result.motivos_rechazo) == 3
    prefijos = [m.split(":")[0] for m in result.motivos_rechazo]
    assert prefijos == ["quality_liquidity", "valuation", "momentum"]
