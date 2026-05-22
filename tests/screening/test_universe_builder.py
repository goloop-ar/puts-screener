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


@pytest.mark.parametrize(
    ("raw_ticker", "country", "expected"),
    [
        ("ZURN", "Switzerland", "ZURN.SW"),
        ("VOD", "United Kingdom", "VOD.L"),
        ("SAP", "Germany", "SAP.DE"),
        ("ASML", "Netherlands", "ASML.AS"),
        ("VOLV B", "Sweden", "VOLV-B.ST"),  # class share con espacio
        ("NDA SE", "Finland", "NDA-SE.HE"),
        ("FLTR", "Ireland", "FLTR.L"),  # Irlanda cotiza en London
        ("INPST", "Luxembourg", "INPST.AS"),
        ("HSX", "Bermuda", "HSX.L"),
        ("LPP", "Poland", None),  # país no soportado
        ("NAB", "Greece", None),
        ("TEV", "Israel", None),
    ],
)
def test_normalize_stoxx_v2(raw_ticker, country, expected):
    assert universe_builder._normalize_stoxx_ticker_v2(raw_ticker, country) == expected


@responses.activate
def test_fetch_sp500_parses_sample():
    html = (FIXTURES / "wikipedia_sp500_sample.html").read_text(encoding="utf-8")
    responses.add(responses.GET, universe_builder._SP500_URL, body=html, status=200)
    assert universe_builder._fetch_sp500() == ["AAPL", "NVDA", "MSFT", "GOOGL", "JPM"]


@responses.activate
def test_fetch_stoxx600_parses_sample():
    html = (FIXTURES / "wikipedia_stoxx600_sample.html").read_text(encoding="utf-8")
    responses.add(responses.GET, universe_builder._STOXX600_URL, body=html, status=200)
    result = universe_builder._fetch_stoxx600()
    # Poland se skipea → 6 tickers (orden de documento)
    assert sorted(result) == [
        "ASML.AS",
        "FLTR.L",
        "SAP.DE",
        "VOD.L",
        "VOLV-B.ST",
        "ZURN.SW",
    ]


@responses.activate
def test_fetch_nasdaq100_from_fixture():
    html = (FIXTURES / "wikipedia_nasdaq100_sample.html").read_text(encoding="utf-8")
    responses.add(responses.GET, universe_builder._NASDAQ100_URL, body=html, status=200)
    # Tabla "Components" identificada por la columna "Ticker"; la infobox previa se ignora.
    assert universe_builder._fetch_nasdaq100() == ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL"]


def test_build_universe_single(tmp_universe_cache, monkeypatch):
    monkeypatch.setattr(universe_builder, "_fetch_sp500", lambda: ["AAPL", "MSFT"])
    result = universe_builder.build_universe(["sp500"])
    assert result == {"AAPL": {"sp500"}, "MSFT": {"sp500"}}


def test_build_universe_dedup_tagging(tmp_universe_cache, monkeypatch):
    monkeypatch.setattr(universe_builder, "_fetch_sp500", lambda: ["AAPL", "JPM"])
    monkeypatch.setattr(universe_builder, "_fetch_nasdaq100", lambda: ["AAPL", "AMZN"])
    result = universe_builder.build_universe(["sp500", "nasdaq100"])
    assert result["AAPL"] == {"sp500", "nasdaq100"}
    assert result["JPM"] == {"sp500"}
    assert result["AMZN"] == {"nasdaq100"}
    assert list(result) == ["AAPL", "AMZN", "JPM"]  # ordenado alfabéticamente


def test_build_universe_invalid_universe(tmp_universe_cache):
    with pytest.raises(ValueError, match="no soportado"):
        universe_builder.build_universe(["sp500", "foo"])


def test_build_universe_empty_list(tmp_universe_cache):
    with pytest.raises(ValueError, match="al menos un universo"):
        universe_builder.build_universe([])


@responses.activate
def test_build_universe_uses_cache(tmp_universe_cache):
    universe_builder._write_universe_cache("sp500", ["AAPL"], universe_builder._SP500_URL)
    universe_builder._write_universe_cache("stoxx600", ["ASML.AS"], universe_builder._STOXX600_URL)
    result = universe_builder.build_universe(["sp500", "stoxx600"])
    assert result == {"AAPL": {"sp500"}, "ASML.AS": {"stoxx600"}}
    assert len(responses.calls) == 0


def test_build_universe_refresh_ignores_cache(tmp_universe_cache, monkeypatch):
    universe_builder._write_universe_cache("sp500", ["CACHED"], universe_builder._SP500_URL)
    universe_builder._write_universe_cache(
        "stoxx600", ["CACHED.AS"], universe_builder._STOXX600_URL
    )
    monkeypatch.setattr(universe_builder, "_fetch_sp500", lambda: ["AAPL"])
    monkeypatch.setattr(universe_builder, "_fetch_stoxx600", lambda: ["ASML.AS"])
    result = universe_builder.build_universe(["sp500", "stoxx600"], refresh=True)
    assert result == {"AAPL": {"sp500"}, "ASML.AS": {"stoxx600"}}


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
