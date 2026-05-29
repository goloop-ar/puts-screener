"""Parámetros de la clasificación dual régimen + triggers (spec 10)."""

# --- Régimen ---
REGIME_LATERAL_TOLERANCE_PCT = 0.03  # |SMA50W - SMA200W| / SMA200W < 3%
REGIME_LATERAL_RANGE_DAYS = 60  # ventana para chequear rango compacto
REGIME_LATERAL_MAX_RANGE_PCT = 0.15  # (high60d - low60d) / low60d < 15%

# --- pullback_in_uptrend ---
# Reusa SCORE_MIN_VALID y MAX_DISTANCE_TO_SUPPORT_PCT de config_supports.
# No hay constantes propias.

# --- range_floor ---
RANGE_FLOOR_LOOKBACK_DAYS = 60  # mismo que REGIME_LATERAL
RANGE_FLOOR_BOTTOM_THIRD = 0.33  # close < min + 0.33 * (max - min)

# --- post_earnings_dip ---
POST_EARNINGS_LOOKBACK_DAYS = 60  # earnings en los últimos 60 días
POST_EARNINGS_DROP_PCT = -0.05  # caída en 2 días post-earnings >= 5%
POST_EARNINGS_DROP_WINDOW_DAYS = 2  # ventana post-earnings para medir el dip

# --- bullish_divergence ---
DIVERGENCE_LOOKBACK_DAYS = 60  # pivots de los últimos 60 días
DIVERGENCE_RSI_MAX = 45  # RSI en P2 < 45 para que sea útil

# --- Pesos de triggers (tabla §0.C del SOP v4) ---
TRIGGER_WEIGHTS: dict[str, float] = {
    "double_bottom_confirmed": 1.0,
    "capitulation_reclaim": 0.9,
    "pullback_in_uptrend": 0.7,
    "range_floor": 0.6,
    "post_earnings_dip": 0.6,
    "double_bottom_unconfirmed": 0.5,
    "hma_weekly_flip": 0.5,
    "bullish_divergence": 0.0,  # modificador, no compite por primary
}

# --- Compatibilidad con regímenes (tabla §0.B del SOP v4) ---
TRIGGER_REGIME_COMPAT: dict[str, frozenset[str]] = {
    "pullback_in_uptrend": frozenset({"uptrend"}),
    "double_bottom_confirmed": frozenset({"downtrend", "reversal"}),
    "double_bottom_unconfirmed": frozenset({"downtrend", "reversal"}),
    "capitulation_reclaim": frozenset({"downtrend", "reversal"}),
    "hma_weekly_flip": frozenset({"reversal"}),
    "range_floor": frozenset({"lateral"}),
    "post_earnings_dip": frozenset({"uptrend", "lateral", "reversal"}),
    "bullish_divergence": frozenset({"uptrend", "lateral", "downtrend", "reversal"}),
}

# --- Mapper legacy primary_trigger -> T (compat columna `tipo`) ---
PRIMARY_TRIGGER_TO_LEGACY_TIPO: dict[str, str] = {
    "pullback_in_uptrend": "T1",
    "double_bottom_confirmed": "T2",
    "double_bottom_unconfirmed": "T2",
    "capitulation_reclaim": "T2",
    "hma_weekly_flip": "T2",
    "range_floor": "T3",
    "post_earnings_dip": "T4",
}

# --- Labels legibles para composite_label ---
TRIGGER_LABELS: dict[str, str] = {
    "pullback_in_uptrend": "Pullback en tendencia",
    "double_bottom_confirmed": "Doble piso confirmado",
    "double_bottom_unconfirmed": "Doble piso en formación",
    "capitulation_reclaim": "Capitulación con reclaim",
    "hma_weekly_flip": "Cambio de régimen",
    "range_floor": "Piso de rango",
    "post_earnings_dip": "Dip post-earnings",
    "bullish_divergence": "divergencia",  # minúscula intencional, va como sufijo
}

REGIME_LABELS: dict[str, str] = {
    "uptrend": "Uptrend",
    "lateral": "Lateral",
    "downtrend": "Downtrend",
    "reversal": "Reversal",
}
