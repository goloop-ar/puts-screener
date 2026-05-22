"""Tests de integración del pipeline final (spec 04 §9)."""

from puts_screener import final_pipeline
from puts_screener.binary_events import BinaryEventsReport


def _report(flags=None):
    return BinaryEventsReport(
        earnings_date=None,
        dias_a_earnings=None,
        earnings_en_45d=False,
        ex_div_date=None,
        dias_a_ex_div=None,
        ex_div_en_45d=False,
        ex_div_amount=None,
        eventos_macro=[],
        eventos_macro_en_45d=False,
        tiene_eventos_binarios=bool(flags),
        flags_legibles=flags or [],
    )


def _wire_pipeline(monkeypatch, supported, *, persist_run_id="rid", boom_ticker=None, calls=None):
    """Monkeypatchea los 3 pasos del pipeline con stubs controlados."""
    screened = [s.screened for s in supported]
    calls = calls if calls is not None else []

    def fake_screening(universe, data_service, max_workers=8, persist=True, db_path=None):
        calls.append("screening")
        return (persist_run_id if persist else None, screened)

    def fake_support(screened_candidates, data_service, max_workers=8, persist=True, run_id=None):
        calls.append("support")
        return (run_id, supported)

    def fake_check(ticker, today, data_service, macro_calendar):
        calls.append(f"check:{ticker}")
        if ticker == boom_ticker:
            raise RuntimeError("synthetic boom")
        return _report()

    monkeypatch.setattr(final_pipeline, "run_screening", fake_screening)
    monkeypatch.setattr(final_pipeline, "run_support_detection", fake_support)
    monkeypatch.setattr(final_pipeline, "check_binary_events", fake_check)
    monkeypatch.setattr(final_pipeline, "load_macro_calendar", lambda path: [])
    return calls


def test_pipeline_runs_three_steps_in_order(monkeypatch, final_candidate_factory):
    supported = [
        final_candidate_factory(ticker="AAA", tipo="T1", score=5, passes=True).supported,
        final_candidate_factory(ticker="BBB", tipo="T2", score=4, passes=True).supported,
        final_candidate_factory(ticker="CCC", passes=False).supported,
    ]
    saved = []
    monkeypatch.setattr(
        final_pipeline, "save_binary_events", lambda rid, fcs: saved.append((rid, len(fcs)))
    )
    calls = _wire_pipeline(monkeypatch, supported)

    run_id, finals = final_pipeline.run_final_pipeline(
        ["AAA", "BBB", "CCC"], data_service=None, persist=True, generate_reports=False
    )

    assert run_id == "rid"
    assert len(finals) == 3
    assert calls.index("screening") < calls.index("support")
    first_check = min(i for i, c in enumerate(calls) if c.startswith("check:"))
    assert calls.index("support") < first_check
    assert {c for c in calls if c.startswith("check:")} == {"check:AAA", "check:BBB", "check:CCC"}
    assert saved == [("rid", 3)]


def test_pipeline_isolates_step3_failure(monkeypatch, final_candidate_factory):
    supported = [
        final_candidate_factory(ticker="OK", passes=True).supported,
        final_candidate_factory(ticker="BOOM", passes=True).supported,
    ]
    monkeypatch.setattr(final_pipeline, "save_binary_events", lambda rid, fcs: None)
    _wire_pipeline(monkeypatch, supported, boom_ticker="BOOM")

    _, finals = final_pipeline.run_final_pipeline(
        ["OK", "BOOM"], data_service=None, persist=False, generate_reports=False
    )

    by_ticker = {fc.ticker: fc for fc in finals}
    assert by_ticker["OK"].errors == []
    assert by_ticker["BOOM"].errors  # error capturado, no propagado
    assert "synthetic boom" in by_ticker["BOOM"].errors[0]
    assert by_ticker["BOOM"].binary_events.flags_legibles == []


def test_generate_reports_false_skips_writers(monkeypatch, final_candidate_factory):
    supported = [final_candidate_factory(ticker="AAA", passes=True).supported]
    _wire_pipeline(monkeypatch, supported)
    csv_calls, html_calls = [], []
    monkeypatch.setattr(final_pipeline, "write_csv_report", lambda *a, **k: csv_calls.append(1))
    monkeypatch.setattr(final_pipeline, "write_html_report", lambda *a, **k: html_calls.append(1))
    monkeypatch.setattr(final_pipeline, "save_binary_events", lambda rid, fcs: None)

    final_pipeline.run_final_pipeline(
        ["AAA"], data_service=None, persist=False, generate_reports=False
    )
    assert csv_calls == []
    assert html_calls == []


def test_persist_false_skips_save(monkeypatch, final_candidate_factory):
    supported = [final_candidate_factory(ticker="AAA", passes=True).supported]
    _wire_pipeline(monkeypatch, supported)
    saved = []
    monkeypatch.setattr(final_pipeline, "save_binary_events", lambda rid, fcs: saved.append(1))

    run_id, _ = final_pipeline.run_final_pipeline(
        ["AAA"], data_service=None, persist=False, generate_reports=False
    )
    assert run_id is None
    assert saved == []
