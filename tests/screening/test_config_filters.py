from puts_screener import config_filters as cfg

_EXPECTED_CONSTANTS = {
    "MIN_MARKET_CAP_USD": float,
    "MIN_AVG_DAILY_VOLUME": float,
    "MIN_FCF_TTM": float,
    "MIN_PRICE_TARGET_UPSIDE": float,
    "MIN_RECOMMENDATION_BUY_RATIO": float,
    "MAX_DOWNGRADES_6W": int,
    "RSI_OVERBOUGHT_THRESHOLD": float,
    "RSI_DAILY_THRESHOLD": float,
    "RSI_DAILY_LOOKBACK_DAYS": int,
    "RSI_WEEKLY_THRESHOLD": float,
    "RSI_WEEKLY_LOOKBACK_WEEKS": int,
    "MACD_LOOKBACK_DAYS": int,
    "MACD_NEUTRAL_PCT_CHANGE": float,
    "HV_PERCENTILE_MIN": float,
    "HV_PERCENTILE_MAX": float,
    "T2_DROP_PCT_5D": float,
    "T3_LATERAL_DAYS": int,
    "T3_RANGE_COMPACTNESS": float,
    "T3_PRICE_FLOOR_FRACTION": float,
    "T3_LATERAL_TOLERANCE": float,
    "T4_LOOKBACK_DAYS": int,
    "T4_DROP_THRESHOLD": float,
    "T4_TOLERANCIA_TENDENCIA": float,
    "T4_RSI_MAX": float,
}


def test_all_expected_constants_exist():
    for name in _EXPECTED_CONSTANTS:
        assert hasattr(cfg, name), f"falta la constante {name}"


def test_constant_types():
    for name, expected_type in _EXPECTED_CONSTANTS.items():
        value = getattr(cfg, name)
        assert isinstance(value, expected_type), f"{name} no es {expected_type}"


def test_sanity_values():
    assert cfg.MIN_MARKET_CAP_USD > 0
    assert cfg.MIN_AVG_DAILY_VOLUME > 0
    assert 0 < cfg.MIN_RECOMMENDATION_BUY_RATIO < 1
    assert cfg.MAX_DOWNGRADES_6W >= 0
    assert 0 <= cfg.HV_PERCENTILE_MIN < cfg.HV_PERCENTILE_MAX <= 100
    assert cfg.T2_DROP_PCT_5D < 0
    assert cfg.T4_DROP_THRESHOLD < 0
    assert 0 < cfg.T4_TOLERANCIA_TENDENCIA < 1
    assert 0 < cfg.T3_PRICE_FLOOR_FRACTION < 1
    assert cfg.RSI_OVERBOUGHT_THRESHOLD > cfg.RSI_DAILY_THRESHOLD
    assert cfg.RSI_OVERBOUGHT_THRESHOLD <= 100.0
