"""Tests del pipeline del Paso 2 (spec 03 §9)."""

import numpy as np
import pandas as pd

from puts_screener import support_pipeline
from puts_screener.models_support import SupportAnalysis, SupportLevel, SupportZone
from puts_screener.support_pipeline import run_support_detection


def _tiny_ohlcv():
    idx = pd.bdate_range(end="2026-05-21", periods=10)
    close = np.full(10, 100.0)
    return pd.DataFrame(
        {"Open": close, "High": close + 1, "Low": close - 1, "Close": close, "Volume": 1_000_000},
        index=idx,
    )


def _valid_analysis():
    zone = SupportZone(
        center_price=95.0,
        lower_bound=94.0,
        upper_bound=96.0,
        score=4,
        elements=[SupportLevel(price=95.0, element="hvn", points=1)],
        has_dynamic_confirmer=True,
        distance_pct=0.05,
    )
    return SupportAnalysis(valid_zones=[zone], rejected_zones=[], best_zone=zone)


def _invalid_analysis():
    zone = SupportZone(
        center_price=80.0,
        lower_bound=79.0,
        upper_bound=81.0,
        score=2,
        elements=[SupportLevel(price=80.0, element="polarity", points=1)],
        has_dynamic_confirmer=False,
        distance_pct=0.20,
    )
    return SupportAnalysis(valid_zones=[], rejected_zones=[(zone, "score < 3")], best_zone=None)


def _fake_analyze(candidate, data_service):
    if candidate.ticker == "BOOM":
        raise ValueError("synthetic failure")
    if candidate.ticker == "GOOD":
        return _valid_analysis()
    return _invalid_analysis()


def test_pipeline_handles_pass_fail_and_error(monkeypatch, candidate_factory):
    monkeypatch.setattr(support_pipeline, "analyze_supports", _fake_analyze)
    candidates = [
        candidate_factory(_tiny_ohlcv(), ticker="GOOD"),
        candidate_factory(_tiny_ohlcv(), ticker="INVALID"),
        candidate_factory(_tiny_ohlcv(), ticker="BOOM"),
    ]

    run_id, supported = run_support_detection(candidates, data_service=None, persist=False)

    assert run_id is None  # persist=False
    by_ticker = {s.screened.ticker: s for s in supported}
    assert set(by_ticker) == {"GOOD", "INVALID", "BOOM"}
    assert by_ticker["GOOD"].pasa_paso_2 is True
    assert by_ticker["INVALID"].pasa_paso_2 is False
    assert by_ticker["INVALID"].errors == []
    assert by_ticker["BOOM"].pasa_paso_2 is False
    assert by_ticker["BOOM"].errors  # mensaje de error capturado
    assert "synthetic failure" in by_ticker["BOOM"].errors[0]


def test_pipeline_filters_out_failed_step1(monkeypatch, candidate_factory):
    monkeypatch.setattr(support_pipeline, "analyze_supports", _fake_analyze)
    candidates = [
        candidate_factory(_tiny_ohlcv(), ticker="GOOD", pasa_filtros_paso_1=True),
        candidate_factory(_tiny_ohlcv(), ticker="SKIP", pasa_filtros_paso_1=False),
    ]

    _, supported = run_support_detection(candidates, data_service=None, persist=False)

    tickers = {s.screened.ticker for s in supported}
    assert tickers == {"GOOD"}  # SKIP no pasó Paso 1 → filtrado


def test_pipeline_persists_with_given_run_id(monkeypatch, candidate_factory, tmp_path):
    monkeypatch.setattr(support_pipeline, "analyze_supports", _fake_analyze)
    monkeypatch.setenv("PUTS_SCREENER_DB_PATH", str(tmp_path / "supports.db"))
    candidates = [candidate_factory(_tiny_ohlcv(), ticker="GOOD")]

    run_id, _ = run_support_detection(
        candidates, data_service=None, persist=True, run_id="fixed-run"
    )

    assert run_id == "fixed-run"
