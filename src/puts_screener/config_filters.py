"""Constantes parametrizables del screening del Paso 1 del SOP.

Cambiar un threshold acá NO requiere cambiar lógica. Importable desde
cualquier módulo del paquete.
"""

from pathlib import Path

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
# Bajado de 0.5 a 0.45 (issue 2.5, 2026-05-21): 8 candidatos near-miss en [0.45, 0.5) con upside
# positivo (BP.L +10.8% buy 0.47, CHD +6.3% buy 0.48, etc.) fallaban por 0.02-0.03 puntos. El SOP
# dice "mayoría Buy"; 0.45 sigue siendo ligera mayoría (45% Buy vs 55% Hold/Sell). Los 36 con
# buy_ratio <0.3 siguen filtrados como rechazos legítimos.
MIN_RECOMMENDATION_BUY_RATIO: float = 0.45
# Subido de 0 a 1 (issue 2.5, 2026-05-21): un único downgrade en un nombre con consenso fuerte de
# compra (ADSK 0.91, CI 0.88, AMAT 0.79, BKR 0.73 fueron rechazados por 1 solo downgrade) es ruido
# institucional, no señal. El SOP dice "sin downgrades significativos"; 2+ ya es patrón filtrable.
MAX_DOWNGRADES_6W: int = 1

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
# Elevado de 80 a 90: HV (volatilidad realizada) está sistémicamente más alta que IV percentile
# en el universo actual. SPEC §2 marca HV como sustituto temporal — cuando se integre IV real
# (Fase 4), volver a 80 y aplicar excepción T2→90 del SOP.
HV_PERCENTILE_MAX: float = 90.0

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

# === Watchlist personal (spec 08) ===
WATCHLIST_FILE_PATH: Path = Path("data/watchlist.txt")
WATCHLIST_UNIVERSE_TAG: str = "watchlist"
WATCHLIST_COMMENT_PREFIX: str = "#"
