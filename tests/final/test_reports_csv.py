"""Tests del CSV report (spec 04 §7)."""

import csv
from datetime import datetime

from puts_screener.reports_csv import CSV_COLUMNS, write_csv_report


def _read_csv(path):
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        return reader.fieldnames, list(reader)


def test_csv_created_with_expected_name(tmp_path, final_candidate_factory):
    ts = datetime(2026, 5, 21, 16, 30)
    path = write_csv_report(
        [final_candidate_factory(ticker="AAA")], output_dir=tmp_path, timestamp=ts
    )
    assert path.name == "screening_2026-05-21_1630.csv"
    assert path.exists()


def test_csv_has_39_columns_in_exact_order(tmp_path, final_candidate_factory):
    path = write_csv_report([final_candidate_factory()], output_dir=tmp_path)
    fieldnames, _ = _read_csv(path)
    assert fieldnames == list(CSV_COLUMNS)
    assert len(fieldnames) == 39


def test_csv_rows_sorted_by_type_score_distance(tmp_path, final_candidate_factory):
    cands = [
        final_candidate_factory(ticker="T1S5", tipo="T1", score=5),
        final_candidate_factory(ticker="T2S4", tipo="T2", score=4),
        final_candidate_factory(ticker="T1S6", tipo="T1", score=6),
    ]
    path = write_csv_report(cands, output_dir=tmp_path)
    _, rows = _read_csv(path)
    assert [r["ticker"] for r in rows] == ["T1S6", "T1S5", "T2S4"]


def test_csv_none_fields_are_empty_string(tmp_path, final_candidate_factory):
    fc = final_candidate_factory(market_cap=None, price_target_mean=None)
    path = write_csv_report([fc], output_dir=tmp_path)
    _, rows = _read_csv(path)
    assert rows[0]["market_cap"] == ""
    assert rows[0]["price_target_consensus"] == ""


def test_csv_latest_copy_created_with_same_content(tmp_path, final_candidate_factory):
    path = write_csv_report([final_candidate_factory()], output_dir=tmp_path)
    latest = tmp_path / "screening_latest.csv"
    assert latest.exists()
    assert latest.read_text(encoding="utf-8") == path.read_text(encoding="utf-8")


def test_csv_excludes_candidates_not_passing(tmp_path, final_candidate_factory):
    passing = final_candidate_factory(ticker="PASS", passes=True)
    failing = final_candidate_factory(ticker="FAIL", passes=False)
    path = write_csv_report([passing, failing], output_dir=tmp_path)
    _, rows = _read_csv(path)
    assert [r["ticker"] for r in rows] == ["PASS"]


def test_csv_flags_joined_with_pipe(tmp_path, final_candidate_factory):
    fc = final_candidate_factory(
        flags=["Earnings en 10 días (2026-05-31)", "Ex-dividend en 8 días ($0.50)"]
    )
    path = write_csv_report([fc], output_dir=tmp_path)
    _, rows = _read_csv(path)
    assert (
        rows[0]["flags_legibles"]
        == "Earnings en 10 días (2026-05-31) | Ex-dividend en 8 días ($0.50)"
    )
