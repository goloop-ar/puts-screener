"""Tests del parsing de la watchlist personal (spec 08 §8.1). Archivos temporales."""

import logging
from pathlib import Path

from puts_screener.universe_builder import load_watchlist


def _write(tmp_path, content: str) -> Path:
    p = tmp_path / "watchlist.txt"
    p.write_text(content, encoding="utf-8")
    return p


def test_load_watchlist_typical(tmp_path):
    p = _write(tmp_path, "# Comentario inicial\nCRWV\nARM\n\nBARC.L\n# otro comentario\ncrwv\n")
    assert load_watchlist(p) == {"CRWV", "ARM", "BARC.L"}


def test_load_watchlist_missing_file(tmp_path, caplog):
    p = tmp_path / "no_existe.txt"
    with caplog.at_level(logging.WARNING):
        result = load_watchlist(p)
    assert result == set()
    assert any(
        "no encontrado" in r.getMessage() and "no_existe.txt" in r.getMessage()
        for r in caplog.records
    )


def test_load_watchlist_lowercase_normalized(tmp_path):
    p = _write(tmp_path, "crwv\nbarc.l\n")
    assert load_watchlist(p) == {"CRWV", "BARC.L"}


def test_load_watchlist_dedup_within_file(tmp_path):
    p = _write(tmp_path, "CRWV\ncrwv\nCRWV\n  crwv  \n")
    assert load_watchlist(p) == {"CRWV"}


def test_load_watchlist_comments_ignored(tmp_path):
    p = _write(tmp_path, "# comentario\nCRWV\n# otro\n")
    assert load_watchlist(p) == {"CRWV"}


def test_load_watchlist_empty_lines_ignored(tmp_path):
    p = _write(tmp_path, "\nCRWV\n\n  \nARM\n\n")
    assert load_watchlist(p) == {"CRWV", "ARM"}


def test_load_watchlist_invalid_ticker_skipped(tmp_path, caplog):
    p = _write(tmp_path, "CRWV\nA B\nA@B\nARM\n")
    with caplog.at_level(logging.WARNING):
        result = load_watchlist(p)
    assert result == {"CRWV", "ARM"}
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2


def test_load_watchlist_european_tickers(tmp_path):
    p = _write(tmp_path, "BARC.L\nABI.BR\nASML.AS\n")
    assert load_watchlist(p) == {"BARC.L", "ABI.BR", "ASML.AS"}


def test_load_watchlist_empty_file(tmp_path, caplog):
    p = _write(tmp_path, "")
    with caplog.at_level(logging.WARNING):
        result = load_watchlist(p)
    assert result == set()
    assert [r for r in caplog.records if r.levelno == logging.WARNING] == []


def test_load_watchlist_only_comments(tmp_path, caplog):
    p = _write(tmp_path, "# foo\n# bar\n")
    with caplog.at_level(logging.WARNING):
        result = load_watchlist(p)
    assert result == set()
    assert [r for r in caplog.records if r.levelno == logging.WARNING] == []
