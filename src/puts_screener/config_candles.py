"""Parámetros de geometría de velas y gate de contexto (spec 11 §3.1 + §3.2)."""

# === Geometría de velas (§3.1) ===
WICK_REJECTION_MIN_RATIO = 1.5
# Mecha inferior ≥1.5× cuerpo. El material de referencia sugiere 2.0, calibrado para
# reversales dramáticos post-caída. Nuestra población real es 64% pullback_in_uptrend
# sobre zona validada, donde el rechazo es más suave. 2.0 daría el cuarto detector mudo.
WICK_REJECTION_MAX_UPPER_RATIO = 1.0
# Mecha superior ≤ cuerpo. Sin este filtro, un spinning top califica como hammer.
WICK_REJECTION_MIN_BODY_ATR = 0.05
# Cuerpo mínimo en unidades de ATR14. Evita que un doji de cuerpo ~0 dé ratio infinito.
BODY_RECLAIM_PIERCING_PCT = 0.50
# Cierre por encima del 50% del cuerpo rojo previo. Umbral clásico del piercing pattern.
BODY_RECLAIM_PREV_MIN_BODY_ATR = 0.15
# La vela roja previa debe tener cuerpo real. Reclamar un doji no es reclamar nada.
MORNING_STAR_MAX_MIDDLE_BODY_ATR = 0.30
# Cuerpo de la vela del medio en el patrón de 3 velas. Sin exigir gaps (D11.5).
BEARISH_MOMENTUM_BODY_MULTIPLIER = 2.0
# Cuerpo ≥2× el promedio de los 3 cuerpos previos. Único umbral cuantificable sin ambigüedad.
BEARISH_ENGULFING_MIN_BODY_ATR = 0.15
# Cuerpo mínimo del engulfing bajista.

# === Gate de contexto — aplica a los 3 detectores (§3.2) ===
CANDLE_LOOKBACK_BARS = 3
# Ventana de búsqueda hacia atrás desde la última barra. El cron corre diario; 3 ruedas
# cubre el fin de semana largo sin volver la señal rancia.
CANDLE_ZONE_PROXIMITY_ATR = 0.5
# El mínimo de la vela debe caer dentro de [lower_bound, upper_bound] o a ≤0.5×ATR14 por
# fuera. Sin este gate el detector es ruido puro — un hammer a 8% de la zona no dice nada.
