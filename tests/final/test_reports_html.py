"""Tests del HTML report (spec 04 §8)."""

from bs4 import BeautifulSoup

from puts_screener.reports_html import write_html_report

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


def test_html_truncates_elements_over_8(tmp_path, final_candidate_factory):
    elements = [("hvn", 100.0 - i, 1) for i in range(10)]
    fc = final_candidate_factory(ticker="MANY", elements=elements)
    path = write_html_report([fc], _META, output_dir=tmp_path)
    soup = _soup(path)
    card = soup.find("article", class_="card")
    items = card.find("section", class_="elements").find_all("li")
    assert len(items) == 9  # 8 elementos + 1 "+N más"
    assert "+2 más" in card.get_text()


def test_html_latest_copy_created(tmp_path, final_candidate_factory):
    path = write_html_report([final_candidate_factory()], _META, output_dir=tmp_path)
    latest = tmp_path / "screening_latest.html"
    assert latest.exists()
    assert latest.read_text(encoding="utf-8") == path.read_text(encoding="utf-8")
