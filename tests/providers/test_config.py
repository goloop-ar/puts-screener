from puts_screener.providers import config


def test_finnhub_key_absent(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    assert config.get_finnhub_api_key() is None


def test_finnhub_key_present(monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "abc123")
    assert config.get_finnhub_api_key() == "abc123"


def test_finnhub_key_empty_is_none(monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "")
    assert config.get_finnhub_api_key() is None


def test_cache_disabled_truthy(monkeypatch):
    for value in ("1", "true", "True", "yes"):
        monkeypatch.setenv("CACHE_DISABLED", value)
        assert config.is_cache_disabled() is True


def test_cache_disabled_falsy(monkeypatch):
    for value in ("0", "", "false"):
        monkeypatch.setenv("CACHE_DISABLED", value)
        assert config.is_cache_disabled() is False


def test_cache_disabled_unset(monkeypatch):
    monkeypatch.delenv("CACHE_DISABLED", raising=False)
    assert config.is_cache_disabled() is False
