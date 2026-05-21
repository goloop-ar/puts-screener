from pathlib import Path

import pytest
import responses

from puts_screener import universe_builder

FIXTURES = Path(__file__).resolve().parent / "fixtures"

_BLOOMBERG_CASES = [
    ("SAP GR", "SAP.DE"),
    ("MC FP", "MC.PA"),
    ("VOD LN", "VOD.L"),
    ("ENEL IM", "ENEL.MI"),
    ("SAN SM", "SAN.MC"),
    ("ASML NA", "ASML.AS"),
    ("NESN SW", "NESN.SW"),
    ("DSV DC", "DSV.CO"),
    ("VOLV SS", "VOLV.ST"),
    ("NOKIA FH", "NOKIA.HE"),
    ("EQNR NO", "EQNR.OL"),
    ("KBC BB", "KBC.BR"),
    ("EDP PL", "EDP.LS"),
    ("OMV AV", "OMV.VI"),
]


@pytest.mark.parametrize(("raw", "expected"), _BLOOMBERG_CASES)
def test_normalize_stoxx_ticker_bloomberg_suffix(raw, expected):
    assert universe_builder._normalize_stoxx_ticker(raw) == expected


@pytest.mark.parametrize("raw", ["ASML.AS", "NESN.SW", "VOD.L"])
def test_normalize_stoxx_ticker_dot_suffix(raw):
    assert universe_builder._normalize_stoxx_ticker(raw) == raw


@pytest.mark.parametrize("raw", ["XYZ HK", "ABC.TO", "FOO JP", ""])
def test_normalize_stoxx_ticker_unsupported(raw):
    assert universe_builder._normalize_stoxx_ticker(raw) is None


@responses.activate
def test_fetch_sp500_parses_sample():
    html = (FIXTURES / "wikipedia_sp500_sample.html").read_text(encoding="utf-8")
    responses.add(responses.GET, universe_builder._SP500_URL, body=html, status=200)
    assert universe_builder._fetch_sp500() == ["AAPL", "NVDA", "MSFT", "GOOGL", "JPM"]


@responses.activate
def test_fetch_stoxx600_parses_sample():
    html = (FIXTURES / "wikipedia_stoxx600_sample.html").read_text(encoding="utf-8")
    responses.add(responses.GET, universe_builder._STOXX600_URL, body=html, status=200)
    assert universe_builder._fetch_stoxx600() == [
        "SAP.DE",
        "MC.PA",
        "ASML.AS",
        "NESN.SW",
        "AIR.PA",
        "SIE.DE",
        "VOD.L",
        "ENEL.MI",
        "SAN.MC",
        "RIO.L",
    ]


def test_build_universe_combines_and_deduplicates(tmp_universe_cache, monkeypatch):
    monkeypatch.setattr(universe_builder, "_fetch_sp500", lambda: ["AAPL", "MSFT"])
    monkeypatch.setattr(universe_builder, "_fetch_stoxx600", lambda: ["ASML.AS", "MSFT"])
    assert universe_builder.build_universe() == ["AAPL", "ASML.AS", "MSFT"]


@responses.activate
def test_build_universe_uses_cache(tmp_universe_cache):
    universe_builder._write_universe_cache("sp500", ["AAPL"], universe_builder._SP500_URL)
    universe_builder._write_universe_cache("stoxx600", ["ASML.AS"], universe_builder._STOXX600_URL)
    result = universe_builder.build_universe()
    assert result == ["AAPL", "ASML.AS"]
    assert len(responses.calls) == 0


def test_build_universe_refresh_ignores_cache(tmp_universe_cache, monkeypatch):
    universe_builder._write_universe_cache("sp500", ["CACHED"], universe_builder._SP500_URL)
    universe_builder._write_universe_cache(
        "stoxx600", ["CACHED.AS"], universe_builder._STOXX600_URL
    )
    monkeypatch.setattr(universe_builder, "_fetch_sp500", lambda: ["AAPL"])
    monkeypatch.setattr(universe_builder, "_fetch_stoxx600", lambda: ["ASML.AS"])
    assert universe_builder.build_universe(refresh=True) == ["AAPL", "ASML.AS"]


def test_cache_disabled_env(tmp_universe_cache, monkeypatch):
    monkeypatch.setenv("CACHE_DISABLED", "1")
    # un write con cache deshabilitado es no-op
    universe_builder._write_universe_cache("sp500", ["AAPL"], universe_builder._SP500_URL)
    assert not universe_builder._cache_path("sp500").exists()
    # y un read devuelve None aunque exista un archivo
    monkeypatch.delenv("CACHE_DISABLED")
    universe_builder._write_universe_cache("sp500", ["AAPL"], universe_builder._SP500_URL)
    monkeypatch.setenv("CACHE_DISABLED", "1")
    assert universe_builder._read_universe_cache("sp500") is None
