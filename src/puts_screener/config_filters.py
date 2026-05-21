"""Constantes parametrizables del screening del Paso 1 del SOP.

Cambiar un threshold acá NO requiere cambiar lógica. Importable desde
cualquier módulo del paquete.
"""

# === Filtros de calidad / liquidez (Paso 1) ===
MIN_MARKET_CAP_USD: float = 10_000_000_000.0
MIN_AVG_DAILY_VOLUME: float = 1_000_000.0
MIN_FCF_TTM: float = 0.0
# Sectores capital-intensivos o con estructura financiera distinta — el FCF tradicional no es
# proxy válido de salud operativa. Se les skipea el chequeo de FCF≤0 manteniendo intactos market
# cap y volumen.
SECTORS_FCF_FILTER_EXEMPT: set[str] = {"Utilities", "Financial Services", "Real Estate"}

# === Filtros de valoración ===
MIN_PRICE_TARGET_UPSIDE: float = 0.0
MIN_RECOMMENDATION_BUY_RATIO: float = 0.5
MAX_DOWNGRADES_6W: int = 0

# === Filtros de momento técnico ===
RSI_OVERBOUGHT_THRESHOLD: float = 70.0
RSI_DAILY_THRESHOLD: float = 50.0
RSI_DAILY_LOOKBACK_DAYS: int = 3
RSI_WEEKLY_THRESHOLD: float = 50.0
RSI_WEEKLY_LOOKBACK_WEEKS: int = 2
MACD_LOOKBACK_DAYS: int = 3
MACD_NEUTRAL_PCT_CHANGE: float = 0.05

# === Filtros de volatilidad ===
HV_PERCENTILE_MIN: float = 30.0
HV_PERCENTILE_MAX: float = 80.0

# === Clasificación T1–T4 ===
T2_DROP_PCT_5D: float = -0.10
T3_LATERAL_DAYS: int = 60
T3_RANGE_COMPACTNESS: float = 0.15
T3_PRICE_FLOOR_FRACTION: float = 0.3
T3_LATERAL_TOLERANCE: float = 0.03
T4_LOOKBACK_DAYS: int = 60
T4_DROP_THRESHOLD: float = -0.05
T4_TOLERANCIA_TENDENCIA: float = 0.97
T4_RSI_MAX: float = 55.0
