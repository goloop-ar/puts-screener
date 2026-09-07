"""Parámetros de la clasificación dual régimen + triggers (spec 10, revisado en spec 12)."""

# --- Régimen ---
REGIME_LATERAL_TOLERANCE_PCT = 0.03  # |SMA50W - SMA200W| / SMA200W < 3%
REGIME_LATERAL_RANGE_DAYS = 60  # ventana para chequear rango compacto
REGIME_LATERAL_MAX_RANGE_PCT = 0.15  # (high60d - low60d) / low60d < 15%

# --- zone_proximity (spec 12; unifica los retirados pullback_in_uptrend y range_floor) ---
# Reusa SCORE_MIN_VALID y MAX_DISTANCE_TO_SUPPORT_PCT de config_supports.
# No hay constantes propias — ver spec 12 §3 y §11 D12.1 (el origen del bug de range_floor era
# justamente una constante propia, RANGE_FLOOR_BOTTOM_THIRD, chocando con ZONE_MIN_DISTANCE_PCT).

# --- post_earnings_dip ---
POST_EARNINGS_LOOKBACK_DAYS = 60  # earnings en los últimos 60 días
POST_EARNINGS_DROP_PCT = -0.05  # caída en 2 días post-earnings >= 5%
POST_EARNINGS_DROP_WINDOW_DAYS = 2  # ventana post-earnings para medir el dip

# --- bullish_divergence ---
DIVERGENCE_LOOKBACK_DAYS = 60  # pivots de los últimos 60 días
DIVERGENCE_RSI_MAX = 45  # RSI en P2 < 45 para que sea útil

# --- Pesos de triggers (tabla §0.C del SOP v4, revisada en spec 12 §11 D12.6) ---
TRIGGER_WEIGHTS: dict[str, float] = {
    "double_bottom_confirmed": 1.0,
    "capitulation_reclaim": 0.9,
    "post_earnings_dip": 0.6,
    "double_bottom_unconfirmed": 0.5,
    "hma_weekly_flip": 0.5,
    # zone_proximity: trigger genérico de posición, no nombra una causa (spec 12 D12.6). Peso
    # deliberadamente el más bajo entre los que compiten por primary — cede ante cualquier trigger
    # que sí nombre una causa (estructura o evento), gana solo cuando ninguno disparó.
    "zone_proximity": 0.4,
    "bullish_divergence": 0.0,  # modificador, no compite por primary
}

# --- Compatibilidad con regímenes (tabla §0.B del SOP v4, revisada en spec 12) ---
TRIGGER_REGIME_COMPAT: dict[str, frozenset[str]] = {
    "double_bottom_confirmed": frozenset({"downtrend", "reversal"}),
    "double_bottom_unconfirmed": frozenset({"downtrend", "reversal"}),
    "capitulation_reclaim": frozenset({"downtrend", "reversal"}),
    "hma_weekly_flip": frozenset({"reversal"}),
    "post_earnings_dip": frozenset({"uptrend", "lateral", "reversal"}),
    # zone_proximity (spec 12): régimen puramente descriptivo, no gatea este trigger — los 4
    # valores están acá por consistencia con el patrón defensivo de los demás evaluadores, pero
    # en la práctica el chequeo de compatibilidad es un no-op.
    "zone_proximity": frozenset({"uptrend", "lateral", "downtrend", "reversal"}),
    "bullish_divergence": frozenset({"uptrend", "lateral", "downtrend", "reversal"}),
}

# --- Mapper legacy primary_trigger -> T (compat columna `tipo`) ---
# zone_proximity NO está acá: dispara en los 4 regímenes, así que su T legacy se resuelve en
# classify_candidate vía _ZONE_PROXIMITY_LEGACY_TIPO_BY_REGIME (spec 12 §6.3), no con una entrada
# fija de este dict.
PRIMARY_TRIGGER_TO_LEGACY_TIPO: dict[str, str] = {
    "double_bottom_confirmed": "T2",
    "double_bottom_unconfirmed": "T2",
    "capitulation_reclaim": "T2",
    "hma_weekly_flip": "T2",
    "post_earnings_dip": "T4",
}

# --- Labels legibles para composite_label ---
TRIGGER_LABELS: dict[str, str] = {
    "double_bottom_confirmed": "Doble piso confirmado",
    "double_bottom_unconfirmed": "Doble piso en formación",
    "capitulation_reclaim": "Capitulación con reclaim",
    "hma_weekly_flip": "Cambio de régimen",
    "post_earnings_dip": "Dip post-earnings",
    "zone_proximity": "Proximidad a zona",
    "bullish_divergence": "divergencia",  # minúscula intencional, va como sufijo
}

REGIME_LABELS: dict[str, str] = {
    "uptrend": "Uptrend",
    "lateral": "Lateral",
    "downtrend": "Downtrend",
    "reversal": "Reversal",
}
