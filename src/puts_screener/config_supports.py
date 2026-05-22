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

# === Zonas ===
ZONE_WIDTH_ATR_MULTIPLIER: float = 0.5  # zona = centro ± este múltiplo de ATR14
CLUSTERING_TOLERANCE_ATR: float = 0.5  # elementos a ≤ este múltiplo de ATR son misma zona

# === Filtro de proximidad ===
MAX_DISTANCE_TO_SUPPORT_PCT: float = 0.10  # zona a ≤ 10% por debajo del spot
MIN_DISTANCE_TO_SUPPORT_PCT: float = 0.0  # zona puede estar al spot; por encima no aplica

ZONE_MIN_DISTANCE_PCT: float = 0.03
"""Distancia mínima de la zona al spot. Zonas a < 3% no son accionables
para venta de puts 30-45 DTE — el strike caería dentro o muy cerca del
dinero, sin margen para que el precio respete el soporte antes del vencimiento."""

# === Scoring ===
SCORE_MIN_VALID: int = 3  # mínimo del SOP para validar una zona
SCORE_SMA200_POINTS: int = 2  # SMA200 (W o D) suma 2 pts
SCORE_OTHER_ELEMENT_POINTS: int = 1  # cada otro elemento suma 1 pt
DYNAMIC_CONFIRMERS: tuple[str, ...] = ("avwap", "hvn", "divergence")  # ≥ 1 obligatorio
