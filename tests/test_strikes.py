"""Tests de strikes heurísticos (spec 07 §8.1). Funciones puras, sin mocks."""

from puts_screener.models_reports import HeuristicStrikes
from puts_screener.strikes import _grid_for_currency, compute_heuristic_strikes


def test_grid_usd_under_25():
    assert _grid_for_currency("USD", 20) == 0.5


def test_grid_usd_under_100():
    assert _grid_for_currency("USD", 80) == 1.0


def test_grid_usd_under_250():
    assert _grid_for_currency("USD", 200) == 2.5


def test_grid_usd_above_250():
    assert _grid_for_currency("USD", 500) == 5.0


def test_grid_gbp_pence_typical():
    assert _grid_for_currency("GBp", 300.0) == 50.0


def test_grid_fallback_unknown_currency():
    grid = _grid_for_currency("ZAc", 1000)
    assert grid > 0
    assert grid == 10  # 1% de 1000 = 10, redondeado a 1 sig fig


def test_compute_typical():
    s = compute_heuristic_strikes(93.0, 95.0, 94.0, 100.0, 2.0, "USD")
    assert s == HeuristicStrikes(aggressive=98.0, natural=94.0, conservative=91.0, grid_unit=1.0)


def test_compute_zone_close_to_spot():
    s = compute_heuristic_strikes(96.0, 97.0, 96.5, 100.0, 2.0, "USD")
    assert s.aggressive == 98.0  # cap por ATR: max(97, 100-2) = 98
    assert s.natural == 97.0  # 96.5 redondea a 97 con grilla 1
    assert s.conservative == 94.0
    assert s.grid_unit == 1.0


def test_compute_wide_zone():
    s = compute_heuristic_strikes(88.0, 92.0, 90.0, 100.0, 2.0, "USD")
    assert s.aggressive == 98.0  # cap por ATR: max(92, 98) = 98
    assert s.natural == 90.0
    assert s.conservative == 86.0


def test_compute_collapsed_strikes_zona_compacta():
    s = compute_heuristic_strikes(49.5, 49.7, 49.6, 50.0, 0.3, "USD")
    assert s.aggressive == s.natural  # colapso aceptado, sin anti-colapso
    assert s.conservative != s.natural  # conservative se diferencia
    assert s.conservative < s.natural
