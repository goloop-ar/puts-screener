"""Tests de detección de eventos binarios (spec 04 §5)."""

from datetime import date, timedelta
from pathlib import Path

from puts_screener.binary_events import check_binary_events, check_macro_events
from puts_screener.macro_calendar import MacroEvent, load_macro_calendar
from puts_screener.providers.models import EarningsEvent

_REAL_CALENDAR = Path(__file__).resolve().parents[2] / "data" / "macro_calendar.yaml"
_TODAY = date(2026, 5, 21)


class _FakeDataService:
    """Stub mínimo con la única firma que usa check_binary_events (duck typing)."""

    def __init__(self, earnings=None, raises=False):
        self._earnings = earnings
        self._raises = raises

    def get_upcoming_earnings(self, ticker, lookforward_days=60):
        if self._raises:
            raise RuntimeError("provider boom")
        return self._earnings


def _earnings(days_ahead: int) -> EarningsEvent:
    return EarningsEvent(
        ticker="X",
        date=_TODAY + timedelta(days=days_ahead),
        eps_estimate=None,
        eps_actual=None,
        when=None,
    )


# --- check_macro_events ---


def test_check_macro_events_window_filter():
    calendar = [
        MacroEvent(date=_TODAY - timedelta(days=1), kind="cpi", description="pasado"),
        MacroEvent(date=_TODAY + timedelta(days=10), kind="fomc", description="en ventana 1"),
        MacroEvent(date=_TODAY + timedelta(days=44), kind="cpi", description="en ventana 2"),
        MacroEvent(date=_TODAY + timedelta(days=46), kind="fomc", description="fuera"),
    ]
    result = check_macro_events(_TODAY, calendar)
    descriptions = [e.description for e in result]
    assert descriptions == ["en ventana 1", "en ventana 2"]


def test_check_macro_events_real_calendar_today():
    calendar = load_macro_calendar(_REAL_CALENDAR)
    result = check_macro_events(date.today(), calendar)
    # con today dentro del rango del calendario 2026 hay al menos un FOMC/CPI próximo
    assert len(result) >= 1
    assert all(e in calendar for e in result)


# --- check_binary_events ---


def test_earnings_in_window_sets_flag_and_days():
    ds = _FakeDataService(earnings=_earnings(12))
    report = check_binary_events("X", _TODAY, ds, macro_calendar=[])
    assert report.earnings_en_45d is True
    assert report.dias_a_earnings == 12
    assert report.earnings_date == date(2026, 6, 2)
    assert "Earnings en 12 días (2026-06-02)" in report.flags_legibles
    assert report.tiene_eventos_binarios is True


def test_earnings_out_of_window_flag_false_days_computed():
    ds = _FakeDataService(earnings=_earnings(60))
    report = check_binary_events("X", _TODAY, ds, macro_calendar=[])
    assert report.earnings_en_45d is False
    assert report.dias_a_earnings == 60
    assert report.flags_legibles == []


def test_earnings_provider_exception_isolated():
    ds = _FakeDataService(raises=True)
    report = check_binary_events("X", _TODAY, ds, macro_calendar=[])
    assert report.earnings_date is None
    assert report.dias_a_earnings is None
    assert report.earnings_en_45d is False
    assert report.tiene_eventos_binarios is False


def test_no_events_means_no_binary_events():
    ds = _FakeDataService(earnings=None)
    report = check_binary_events("X", _TODAY, ds, macro_calendar=[])
    assert report.tiene_eventos_binarios is False
    assert report.flags_legibles == []
    assert report.eventos_macro == []


def test_ex_dividend_is_stubbed_none():
    """El stub de ex-dividend deja todos los campos en None/False (tanda siguiente)."""
    ds = _FakeDataService(earnings=None)
    report = check_binary_events("X", _TODAY, ds, macro_calendar=[])
    assert report.ex_div_date is None
    assert report.dias_a_ex_div is None
    assert report.ex_div_en_45d is False
    assert report.ex_div_amount is None


def test_macro_in_window_adds_flag():
    calendar = [MacroEvent(date=_TODAY + timedelta(days=5), kind="fomc", description="FOMC")]
    ds = _FakeDataService(earnings=None)
    report = check_binary_events("X", _TODAY, ds, macro_calendar=calendar)
    assert report.eventos_macro_en_45d is True
    assert len(report.eventos_macro) == 1
    assert "Evento macro: fomc en 5 días (FOMC)" in report.flags_legibles


def test_flags_order_earnings_before_macro():
    """Orden de severidad: earnings primero, macro al final (ex_div stubeado → ausente)."""
    ds = _FakeDataService(earnings=_earnings(10))
    calendar = [MacroEvent(date=_TODAY + timedelta(days=5), kind="cpi", description="CPI")]
    report = check_binary_events("X", _TODAY, ds, macro_calendar=calendar)

    assert report.flags_legibles[0].startswith("Earnings en")
    macro_idx = next(i for i, f in enumerate(report.flags_legibles) if f.startswith("Evento macro"))
    assert macro_idx > 0
    assert not any("Ex-dividend" in f for f in report.flags_legibles)
