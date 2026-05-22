"""Tests del loader del calendario macro (spec 04 §4)."""

from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from puts_screener.macro_calendar import MacroEvent, load_macro_calendar

# Path al calendario real del repo, robusto al cwd (tests/final/ → repo root).
_REAL_CALENDAR = Path(__file__).resolve().parents[2] / "data" / "macro_calendar.yaml"


def test_load_real_calendar_counts():
    events = load_macro_calendar(_REAL_CALENDAR)
    assert len(events) == 20
    assert all(isinstance(e, MacroEvent) for e in events)
    by_kind = Counter(e.kind for e in events)
    assert by_kind["fomc"] == 8
    assert by_kind["cpi"] == 12
    # las fechas quedan como `date`, no strings
    assert all(isinstance(e.date, date) for e in events)


def test_missing_file_returns_empty(tmp_path):
    assert load_macro_calendar(tmp_path / "nope.yaml") == []


def test_empty_file_returns_empty(tmp_path):
    f = tmp_path / "empty.yaml"
    f.write_text("", encoding="utf-8")
    assert load_macro_calendar(f) == []


def test_events_empty_list_returns_empty(tmp_path):
    f = tmp_path / "no_events.yaml"
    f.write_text("events: []\n", encoding="utf-8")
    assert load_macro_calendar(f) == []


def test_malformed_yaml_raises_value_error(tmp_path):
    f = tmp_path / "broken.yaml"
    f.write_text("events: [unclosed\n  - oops", encoding="utf-8")
    with pytest.raises(ValueError, match="malformed"):
        load_macro_calendar(f)


def test_invalid_kind_raises_value_error(tmp_path):
    f = tmp_path / "bad_kind.yaml"
    f.write_text(
        'events:\n  - date: 2026-01-01\n    kind: bananas\n    description: "x"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="invalid kind"):
        load_macro_calendar(f)


def test_malformed_date_raises(tmp_path):
    f = tmp_path / "bad_date.yaml"
    f.write_text(
        'events:\n  - date: "2026-99-99"\n    kind: fomc\n    description: "x"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_macro_calendar(f)
