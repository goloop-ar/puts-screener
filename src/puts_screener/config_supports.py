"""Constantes parametrizables de la detección de soportes y scoring (Paso 2 del SOP).

Módulo separado de `config_filters.py` para mantener cohesión por feature. Cambiar un
threshold acá NO requiere tocar lógica. Ver §3 de `specs/03_support_detection_scoring.md`.
"""

# === Detección de pivots ===
PIVOT_WINDOW_BARS: int = 5  # pivot = low/high extremo vs N barras a cada lado
PIVOT_MIN_DEPTH_ATR: float = 1.0  # profundidad mínima vs swing opuesto previo (en ATR14)

# === Ventanas de "último" (12 meses hábiles) ===
LAST_SWING_LOOKBACK_DAYS: int = 252  # ventana para el último impulso/swing significativo
LAST_PIVOT_HIGH_LOOKBACK_DAYS: int = 252  # ventana para resistencias rotas (polaridad)
AVWAP_EARNINGS_LOOKBACK_DAYS: int = 252  # earnings más viejo que esto → AVWAP earnings = None
AVWAP_52W_HIGH_LOOKBACK_DAYS: int = 252  # ventana para el ancla "último máximo 52w" del AVWAP

# === Fibonacci ===
FIB_LEVELS: tuple[float, float] = (0.618, 0.786)  # solo los dos retrocesos del SOP

# === HVN aproximado ===
HVN_LOOKBACK_DAYS: int = 252  # ventana para el volume profile aproximado
HVN_NUM_BUCKETS: int = 50  # granularidad del histograma de precios
HVN_PERCENTILE_THRESHOLD: float = 80.0  # buckets ≥ este percentil de volumen son HVN

# === Gaps ===
GAP_LOOKBACK_DAYS: int = 252  # solo gaps de los últimos 12 meses cuentan

# === Divergencias ===
DIVERGENCE_LOOKBACK_DAYS: int = 60  # divergencias entre pivots dentro de esta ventana

# === Zonas (spec 06: tolerance híbrida + envelope real) ===
CLUSTERING_TOLERANCE_ATR: float = 0.4  # base del tolerance entre niveles consecutivos (× ATR14)
CLUSTERING_TOLERANCE_MAX_PCT: float = 0.01  # cap del tolerance: min(ATR×factor, spot×esto)
ZONE_MAX_WIDTH_PCT: float = 0.04  # gate post-cluster: descarta cluster si supera este % del centro
ZONE_BUFFER_PCT: float = 0.001  # buffer cosmético a cada lado del envelope (no afecta lógica)

# === Filtro de proximidad ===
MAX_DISTANCE_TO_SUPPORT_PCT: float = 0.10  # zona a ≤ 10% por debajo del spot
MIN_DISTANCE_TO_SUPPORT_PCT: float = 0.0  # zona puede estar al spot; por encima no aplica

ZONE_MIN_DISTANCE_PCT: float = 0.03
"""Distancia mínima de la zona al spot. Zonas a < 3% no son accionables
para venta de puts 30-45 DTE — el strike caería dentro o muy cerca del
dinero, sin margen para que el precio respete el soporte antes del vencimiento."""

# === Scoring (Etapa 4: pesos diferenciados por elemento) ===
ELEMENT_WEIGHTS: dict[str, float] = {
    "sma_200d": 3.0,
    "sma_200w": 3.0,
    "polarity": 3.0,
    "ema_200d": 2.5,
    "sma_50d": 2.5,
    "avwap_pivot_low": 2.5,
    "avwap_earnings": 2.5,
    "avwap_52w_high": 2.0,
    "sma_50w": 2.0,
    "hvn": 2.0,
    "ema_50d": 1.5,
    "fib_618": 1.5,
    "gap_unfilled": 1.0,
    "fib_786": 0.0,  # informativo, no suma
    "divergence": 0.0,  # informativo, no suma; sigue siendo confirmador dinámico
}
"""Peso de cada elemento en el score de la zona. Float para granularidad."""

HEAVY_ELEMENT_WEIGHT_THRESHOLD: float = 2.5
"""Umbral para el gate estructural: cuenta como 'pesado' un elemento con peso ≥ este valor."""

MIN_HEAVY_ELEMENTS: int = 2
"""Mínimo de elementos individuales (no categorías) con peso ≥ HEAVY_ELEMENT_WEIGHT_THRESHOLD
para que una zona sea válida."""

SCORE_MIN_VALID: float = 5.0
"""Umbral mínimo de score numérico para zona válida. Provisional; calibrar empíricamente
con runs reales. Va junto con el gate estructural MIN_HEAVY_ELEMENTS."""

DYNAMIC_CONFIRMERS: tuple[str, ...] = ("avwap", "hvn", "divergence")  # ≥ 1 obligatorio

# === Density bonus (spec 06 §3.2; provisional, calibrar post-validación) ===
MIN_WIDTH_FLOOR_PCT: float = 0.005  # floor de ancho (fracción) p/ evitar div por ~0
REFERENCE_DENSITY: float = 100.0  # densidad base (heavies / fracción de ancho) → multiplicador 1.0
DENSITY_BONUS_SLOPE: float = 0.005  # multiplier = 1.0 + (density - REFERENCE_DENSITY) * slope
MIN_DENSITY_MULTIPLIER: float = 0.85  # floor del multiplicador (zona ancha pierde máx 15%)
MAX_DENSITY_MULTIPLIER: float = 1.5  # cap del multiplicador (zona compacta gana máx 50%)

# === Score tier (spec 06 §3.3; labels human-readable en config_reports, tanda 2) ===
SCORE_TIER_THRESHOLDS: dict[int, float] = {5: 18.0, 4: 13.0, 3: 9.0, 2: 6.5, 1: 5.0}
"""score >= 18 → tier 5; >= 13 → 4; >= 9 → 3; >= 6.5 → 2; >= 5 → 1. Provisional."""
