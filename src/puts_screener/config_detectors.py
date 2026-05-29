"""Parámetros de los detectores de patrones técnicos (spec 10)."""

# --- Doble piso (W pattern) ---
DBL_BOTTOM_LOOKBACK_DAYS = 180  # 9 meses hábiles
DBL_BOTTOM_MIN_GAP_BARS = 15  # mínimo entre los dos lows (filtra ruido)
DBL_BOTTOM_MAX_GAP_BARS = 80  # máximo (más allá es otra estructura)
DBL_BOTTOM_LOW_TOLERANCE = 0.03  # |L2 - L1| / L1 < 3%
DBL_BOTTOM_MIN_BOUNCE_PCT = 0.08  # rebote intermedio ≥ 8%

# --- Capitulation + reclaim ---
CAPIT_LOOKBACK_DAYS = 60  # ventana de búsqueda de vela climática
CAPIT_RANGE_ATR_MULTIPLIER = 2.5  # rango > 2.5×ATR14
CAPIT_VOLUME_AVG_MULTIPLIER = 2.5  # volumen > 2.5×promedio 20d
CAPIT_CLOSE_POS_MIN = 0.66  # cierre en tercio superior del rango
CAPIT_PREDROP_LOOKBACK = 10  # ventana para medir caída previa
CAPIT_PREDROP_PCT = -0.08  # caída ≥ 8% en 10 días previos
CAPIT_RECLAIM_WINDOW_DAYS = 10  # ventana para confirmar reclaim

# --- HMA weekly flip ---
HMA_WEEKLY_PERIOD = 50  # período del HMA semanal
HMA_FLIP_LOOKBACK_WEEKS = 3  # flip debe ser de las últimas 3 velas semanales
HMA_MIN_SLOPE_PCT = 0.001  # filtro de magnitud post-flip (0.1%)
