import dataclasses

from puts_screener.filters_step1 import (
    apply_step1_filters,
    compute_momentum_score,
    filter_hv_percentile,
    filter_momentum,
    filter_quality_liquidity,
    filter_valuation,
)
from puts_screener.models_screening import TypeClassification


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


def test_filter_quality_liquidity_exempts_fcf_for_utilities(neutral_candidate):
    _with_profile(neutral_candidate, sector="Utilities")
    _with_financials(neutral_candidate, free_cash_flow_ttm=-1e9)
    # market cap y volumen siguen OK (defaults del neutral) → debe pasar pese a FCF<0
    assert filter_quality_liquidity(neutral_candidate) == (True, None)


def test_filter_quality_liquidity_keeps_fcf_for_non_exempt_sector(neutral_candidate):
    _with_profile(neutral_candidate, sector="Technology")
    _with_financials(neutral_candidate, free_cash_flow_ttm=-1e9)
    passes, reason = filter_quality_liquidity(neutral_candidate)
    assert passes is False
    assert "FCF" in reason


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


def test_filter_valuation_passes_single_downgrade(neutral_candidate):
    """1 downgrade (US) ahora PASA — umbral subido de 0 a 1 (issue 2.5)."""
    _with_profile(neutral_candidate, country="United States")
    neutral_candidate.downgrades_6w_count = 1
    assert filter_valuation(neutral_candidate) == (True, None)


def test_filter_valuation_fails_two_downgrades(neutral_candidate):
    """2 downgrades (US) sigue fallando — el umbral sigue activo para 2+."""
    _with_profile(neutral_candidate, country="United States")
    neutral_candidate.downgrades_6w_count = 2
    passes, reason = filter_valuation(neutral_candidate)
    assert passes is False
    assert "downgrades" in reason


def test_filter_valuation_passes_buy_ratio_046(neutral_candidate):
    """buy_ratio 0.46 ahora PASA — umbral bajado de 0.5 a 0.45 (issue 2.5)."""
    neutral_candidate.recommendation_buy_ratio = 0.46
    assert filter_valuation(neutral_candidate) == (True, None)


def test_filter_valuation_fails_buy_ratio_044(neutral_candidate):
    """buy_ratio 0.44 sigue fallando — el umbral sigue activo para <0.45."""
    neutral_candidate.recommendation_buy_ratio = 0.44
    passes, reason = filter_valuation(neutral_candidate)
    assert passes is False
    assert "buy ratio" in reason


# --- momentum (gate de sobrecompra) ---


def test_filter_momentum_passes_neutral_rsi(neutral_candidate):
    """RSI_d=60, RSI_w=60 (ambos < 70) — pasa."""
    passes, reason = filter_momentum(neutral_candidate)
    assert passes is True
    assert reason is None


def test_filter_momentum_passes_low_rsi(neutral_candidate):
    """RSI bajo (sin chequeo de momentum positivo) — pasa igual."""
    neutral_candidate.rsi_d = 35.0
    neutral_candidate.rsi_w = 40.0
    passes, _ = filter_momentum(neutral_candidate)
    assert passes is True


def test_filter_momentum_fails_rsi_d_overbought(neutral_candidate):
    neutral_candidate.rsi_d = 72.0
    passes, reason = filter_momentum(neutral_candidate)
    assert passes is False
    assert "RSI_d" in reason
    assert "sobrecomprado" in reason


def test_filter_momentum_fails_rsi_w_overbought(neutral_candidate):
    neutral_candidate.rsi_w = 75.0
    passes, reason = filter_momentum(neutral_candidate)
    assert passes is False
    assert "RSI_w" in reason


def test_filter_momentum_fails_at_exact_threshold(neutral_candidate):
    """RSI exactamente en 70 — la comparación es >=, falla."""
    neutral_candidate.rsi_d = 70.0
    passes, _ = filter_momentum(neutral_candidate)
    assert passes is False


# --- momentum_score (informativo) ---


def test_momentum_score_zero_neutral(neutral_candidate):
    assert compute_momentum_score(neutral_candidate) == 0


def test_momentum_score_one_rsi_d_only(neutral_candidate):
    neutral_candidate.rsi_d = 40.0
    neutral_candidate.rsi_d_3d_ago = 35.0
    assert compute_momentum_score(neutral_candidate) == 1


def test_momentum_score_one_rsi_w_only(neutral_candidate):
    neutral_candidate.rsi_w = 45.0
    neutral_candidate.rsi_w_2w_ago = 42.0
    assert compute_momentum_score(neutral_candidate) == 1


def test_momentum_score_one_macd_only(neutral_candidate):
    neutral_candidate.macd_state = "subiendo_negativo"
    assert compute_momentum_score(neutral_candidate) == 1


def test_momentum_score_two(neutral_candidate):
    neutral_candidate.rsi_d = 40.0
    neutral_candidate.rsi_d_3d_ago = 35.0
    neutral_candidate.macd_state = "subiendo_positivo"
    assert compute_momentum_score(neutral_candidate) == 2


def test_momentum_score_three_full(neutral_candidate):
    neutral_candidate.rsi_d = 40.0
    neutral_candidate.rsi_d_3d_ago = 35.0
    neutral_candidate.rsi_w = 45.0
    neutral_candidate.rsi_w_2w_ago = 42.0
    neutral_candidate.macd_state = "subiendo_positivo"
    assert compute_momentum_score(neutral_candidate) == 3


def test_momentum_score_rsi_d_not_active_when_above_threshold(neutral_candidate):
    """RSI_d = 55 (≥ 50) NO suma aunque venga subiendo."""
    neutral_candidate.rsi_d = 55.0
    neutral_candidate.rsi_d_3d_ago = 50.0
    assert compute_momentum_score(neutral_candidate) == 0


def test_momentum_score_rsi_d_not_active_when_falling(neutral_candidate):
    """RSI_d bajo pero bajando NO suma."""
    neutral_candidate.rsi_d = 35.0
    neutral_candidate.rsi_d_3d_ago = 40.0
    assert compute_momentum_score(neutral_candidate) == 0


def test_momentum_score_macd_bajando_not_active(neutral_candidate):
    neutral_candidate.macd_state = "bajando_negativo"
    assert compute_momentum_score(neutral_candidate) == 0


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
    neutral_candidate.hv_percentile_52w = 95.0  # > 90 (techo elevado de 80 a 90)
    passes, reason = filter_hv_percentile(neutral_candidate)
    assert passes is False
    assert ">" in reason


# --- orquestador ---


def test_apply_step1_all_pass(neutral_candidate):
    # neutral_candidate ya pasa los 4 filtros (RSI 60 < 70 → momentum OK por default).
    neutral_candidate.classification = TypeClassification(tipo="T1", justificacion="x")
    result = apply_step1_filters(neutral_candidate)
    assert result.pasa_filtros_paso_1 is True
    assert result.motivos_rechazo == []


def test_apply_step1_collects_all_failures(neutral_candidate):
    # Clasifica (T1) para aislar los fallos de los 4 filtros del gate de clasificación.
    neutral_candidate.classification = TypeClassification(tipo="T1", justificacion="x")
    _with_profile(neutral_candidate, market_cap_usd=1e9)  # quality fail
    neutral_candidate.recommendation_buy_ratio = 0.3  # valuation fail
    neutral_candidate.rsi_d = 75.0  # momentum fail (sobrecompra)
    neutral_candidate.hv_percentile_52w = 50.0  # hv pasa
    result = apply_step1_filters(neutral_candidate)
    assert result.pasa_filtros_paso_1 is False
    assert len(result.motivos_rechazo) == 3
    prefijos = [m.split(":")[0] for m in result.motivos_rechazo]
    assert prefijos == ["quality_liquidity", "valuation", "momentum"]


def test_apply_step1_fails_without_classification(neutral_candidate):
    # Pasa los 4 filtros pero no clasifica → el gate final lo rechaza (spec 02 §1).
    neutral_candidate.classification = None
    result = apply_step1_filters(neutral_candidate)
    assert result.pasa_filtros_paso_1 is False
    assert "sin clasificación T1–T4" in result.motivos_rechazo
