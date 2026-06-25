"""Tests del HTML report (spec 04 §8 + spec 06: banner macro, tier, currency)."""

from datetime import date, datetime

import pandas as pd
from bs4 import BeautifulSoup

from puts_screener.macro_calendar import MacroEvent
from puts_screener.reports_html import (
    _format_candidate,
    _format_macro_events_for_banner,
    write_html_report,
)

_META = {
    "run_id": "test-run",
    "universe_size": 100,
    "n_paso_1": 30,
    "n_paso_2": 12,
    "generated_at": "2026-05-21T16:30:00",
    "version": "0.1",
}


def _soup(path):
    return BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")


def _ticker(article):
    return article.find("strong", class_="ticker").get_text(strip=True)


def test_html_is_valid_and_contains_tickers(tmp_path, final_candidate_factory):
    cands = [final_candidate_factory(ticker="AAA"), final_candidate_factory(ticker="BBB")]
    path = write_html_report(cands, _META, output_dir=tmp_path)
    soup = _soup(path)
    assert soup.find("html") is not None
    assert soup.find("title") is not None
    text = soup.get_text()
    assert "AAA" in text
    assert "BBB" in text


def test_html_flags_section_only_when_flags(tmp_path, final_candidate_factory):
    with_flags = final_candidate_factory(ticker="WFLAG", flags=["Earnings en 10 días (2026-05-31)"])
    no_flags = final_candidate_factory(ticker="NOFLAG", flags=[])
    path = write_html_report([with_flags, no_flags], _META, output_dir=tmp_path)
    soup = _soup(path)
    cards = {_ticker(a): a for a in soup.find_all("article", class_="card")}
    assert cards["WFLAG"].find("section", class_="flags") is not None
    assert cards["NOFLAG"].find("section", class_="flags") is None


def test_html_cards_sorted_by_type_score(tmp_path, final_candidate_factory):
    cands = [
        final_candidate_factory(ticker="T1S5", tipo="T1", score=5),
        final_candidate_factory(ticker="T2S4", tipo="T2", score=4),
        final_candidate_factory(ticker="T1S6", tipo="T1", score=6),
    ]
    path = write_html_report(cands, _META, output_dir=tmp_path)
    soup = _soup(path)
    tickers = [_ticker(a) for a in soup.find_all("article", class_="card")]
    assert tickers == ["T1S6", "T1S5", "T2S4"]


def test_html_renders_all_elements_no_truncation(tmp_path, final_candidate_factory):
    """Spec 07: cards full-width muestran todos los elementos, sin truncado ni '+N más'."""
    elements = [("hvn", 100.0 - i, 1) for i in range(10)]
    fc = final_candidate_factory(ticker="MANY", elements=elements)
    path = write_html_report([fc], _META, output_dir=tmp_path)
    soup = _soup(path)
    card = soup.find("article", class_="card")
    items = card.find("section", class_="elements").find_all("li")
    assert len(items) == 10  # todos los elementos
    assert card.find("li", class_="more") is None  # sin "+N más"


def test_html_universe_badges_single(tmp_path, final_candidate_factory):
    fc = final_candidate_factory(ticker="ONE", universes=("sp500",))
    path = write_html_report([fc], _META, output_dir=tmp_path)
    soup = _soup(path)
    card = soup.find("article", class_="card")
    badges = card.find_all("span", class_="universe-badge")
    assert len(badges) == 1
    assert badges[0].get_text(strip=True) == "sp500"


def test_html_universe_badges_multiple(tmp_path, final_candidate_factory):
    fc = final_candidate_factory(ticker="TWO", universes=("nasdaq100", "sp500"))
    path = write_html_report([fc], _META, output_dir=tmp_path)
    soup = _soup(path)
    card = soup.find("article", class_="card")
    badges = card.find_all("span", class_="universe-badge")
    assert len(badges) == 2
    assert {b.get_text(strip=True) for b in badges} == {"nasdaq100", "sp500"}


def test_html_momentum_section_absent_when_no_signals(tmp_path, final_candidate_factory):
    fc = final_candidate_factory(ticker="NOSIG", momentum_signals=())
    path = write_html_report([fc], _META, output_dir=tmp_path)
    card = _soup(path).find("article", class_="card")
    assert card.find("section", class_="momentum") is None


def test_html_momentum_section_shown_with_signals(tmp_path, final_candidate_factory):
    fc = final_candidate_factory(ticker="SIG", momentum_signals=("rsi",))
    path = write_html_report([fc], _META, output_dir=tmp_path)
    card = _soup(path).find("article", class_="card")
    section = card.find("section", class_="momentum")
    assert section is not None
    assert "Divergencia (rsi)" in section.get_text()


def test_html_latest_copy_created(tmp_path, final_candidate_factory):
    path = write_html_report([final_candidate_factory()], _META, output_dir=tmp_path)
    latest = tmp_path / "screening_latest.html"
    assert latest.exists()
    assert latest.read_text(encoding="utf-8") == path.read_text(encoding="utf-8")


# --- spec 06: macro banner ---

_BANNER_TODAY = date(2026, 5, 21)


def test_format_macro_events_for_banner_sorts_by_date():
    events = [
        MacroEvent(date=date(2026, 6, 10), kind="cpi", description="CPI"),
        MacroEvent(date=date(2026, 5, 30), kind="fomc", description="FOMC"),
    ]
    result = _format_macro_events_for_banner(events, _BANNER_TODAY)
    assert [e["date"] for e in result] == ["2026-05-30", "2026-06-10"]


def test_format_macro_events_for_banner_excludes_past():
    events = [
        MacroEvent(date=date(2026, 5, 10), kind="cpi", description="pasado"),
        MacroEvent(date=date(2026, 5, 30), kind="fomc", description="futuro"),
    ]
    result = _format_macro_events_for_banner(events, _BANNER_TODAY)
    assert [e["description"] for e in result] == ["futuro"]


def test_format_macro_events_for_banner_includes_jurisdiction():
    events = [MacroEvent(date=date(2026, 5, 30), kind="fomc", description="FOMC meeting")]
    result = _format_macro_events_for_banner(events, _BANNER_TODAY)
    assert result[0]["jurisdiction"] == "US"
    assert result[0]["kind_display"] == "FOMC"
    assert result[0]["days_until"] == 9


def test_html_macro_banner_shown_once_not_per_card(tmp_path, final_candidate_factory):
    """El banner macro aparece una sola vez (a nivel run), no en cada card."""
    macro = [MacroEvent(date=date(2026, 6, 1), kind="fomc", description="FOMC")]
    cands = [final_candidate_factory(ticker="AAA"), final_candidate_factory(ticker="BBB")]
    # timestamp fijo anterior al evento: el banner filtra eventos pasados (e.date < today),
    # así que sin pinnearlo el test se rompe al correrse después del 2026-06-01 (date-rot).
    path = write_html_report(
        cands,
        _META,
        output_dir=tmp_path,
        macro_events=macro,
        timestamp=datetime(2026, 5, 21, 16, 30),
    )
    soup = _soup(path)
    assert len(soup.find_all("section", class_="macro-banner")) == 1
    # ninguna card tiene el evento macro en sus flags
    for card in soup.find_all("article", class_="card"):
        flags_sec = card.find("section", class_="flags")
        assert flags_sec is None or "FOMC" not in flags_sec.get_text()


# --- spec 06: currency + tier en _format_candidate ---


def test_format_candidate_includes_currency_formatted_fields(final_candidate_factory):
    fc = final_candidate_factory(
        ticker="BARC", currency="GBp", spot=453.55, price_target_mean=500.0
    )
    d = _format_candidate(fc)
    assert d["currency"] == "GBp"
    assert d["spot_formatted"] == "453.55p"
    assert d["price_target_formatted"] == "500.00p"
    assert d["zona_min_formatted"].endswith("p")
    assert d["zona_max_formatted"].endswith("p")
    assert all("price_formatted" in el for el in d["elements"])
    usd = _format_candidate(final_candidate_factory(ticker="AAA", currency="USD", spot=100.0))
    assert usd["spot_formatted"] == "$100.00"
    assert "score_tier" in usd and "score_tier_stars" in usd and "score_tier_label" in usd


def test_format_candidate_excludes_macro_from_flags_legibles(final_candidate_factory):
    fc = final_candidate_factory(ticker="AAA", flags=["Earnings en 10 días (2026-05-31)"])
    d = _format_candidate(fc)
    assert d["flags_legibles"] == ["Earnings en 10 días (2026-05-31)"]
    assert not any("macro" in f.lower() for f in d["flags_legibles"])


# --- spec 07: strikes + mini-chart en _format_candidate ---


def _ohlcv(n_days: int, base: float = 100.0) -> pd.DataFrame:
    idx = pd.bdate_range(end="2026-05-26", periods=n_days)
    closes = [base + i * 0.05 for i in range(n_days)]
    return pd.DataFrame(
        {"Open": closes, "High": closes, "Low": closes, "Close": closes, "Volume": [1] * n_days},
        index=idx,
    )


def test_format_candidate_includes_strikes(final_candidate_factory):
    d = _format_candidate(final_candidate_factory(ticker="AAA"))
    for key in ("strike_aggressive", "strike_natural", "strike_conservative"):
        assert isinstance(d[key], float)
    for key in (
        "strike_aggressive_formatted",
        "strike_natural_formatted",
        "strike_conservative_formatted",
    ):
        assert isinstance(d[key], str)
        assert d[key] != ""


def test_format_candidate_includes_chart_svg(final_candidate_factory):
    fc = final_candidate_factory(ticker="AAA")
    fc.supported.screened.ohlcv_daily = _ohlcv(180)
    d = _format_candidate(fc)
    assert d["chart_svg"] != ""
    assert "<svg" in d["chart_svg"]
    assert d["chart_placeholder"] == ""


def test_format_candidate_chart_placeholder_when_short_history(final_candidate_factory):
    fc = final_candidate_factory(ticker="AAA")
    fc.supported.screened.ohlcv_daily = _ohlcv(20)
    d = _format_candidate(fc)
    assert d["chart_svg"] == ""
    assert d["chart_placeholder"] == "Histórico insuficiente para chart"


def test_html_renders_watchlist_badge(tmp_path, final_candidate_factory):
    fc = final_candidate_factory(ticker="WL", universes=("sp500", "watchlist"))
    path = write_html_report([fc], _META, output_dir=tmp_path)
    html = path.read_text(encoding="utf-8")
    assert '<span class="universe-badge">watchlist</span>' in html
    assert '<span class="universe-badge">sp500</span>' in html
