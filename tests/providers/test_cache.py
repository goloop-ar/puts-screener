import os
import time
from datetime import date

from puts_screener.providers import cache

_HOURS_STALE = 100
_SECONDS_PER_HOUR = 3600


def test_json_round_trip(tmp_cache_root):
    data = {"ticker": "AAPL", "sector": "Technology", "market_cap_usd": 3.0e12}
    cache.write_cache("profile", "AAPL.json", data)
    assert cache.get_cached("profile", "AAPL.json") == data


def test_parquet_round_trip(tmp_cache_root, sample_ohlcv_df):
    cache.write_cache("ohlcv", "AAPL_1d.parquet", sample_ohlcv_df)
    loaded = cache.get_cached("ohlcv", "AAPL_1d.parquet")
    assert loaded is not None
    assert list(loaded.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert len(loaded) == len(sample_ohlcv_df)


def test_is_fresh_recent_file(tmp_cache_root):
    path = cache.cache_path("profile", "AAPL.json")
    cache.write_json(path, {"x": 1})
    assert cache.is_fresh(path, ttl_hours=24) is True


def test_is_fresh_stale_file(tmp_cache_root):
    path = cache.cache_path("profile", "AAPL.json")
    cache.write_json(path, {"x": 1})
    stale = time.time() - _HOURS_STALE * _SECONDS_PER_HOUR
    os.utime(path, (stale, stale))
    assert cache.is_fresh(path, ttl_hours=24) is False


def test_read_ohlcv_slice_within_range(tmp_cache_root, sample_ohlcv_df):
    cache.write_ohlcv("AAPL", "1d", sample_ohlcv_df)
    start = sample_ohlcv_df.index[5].date()
    end = sample_ohlcv_df.index[15].date()
    sliced = cache.read_ohlcv_slice("AAPL", "1d", start, end)
    assert sliced is not None
    assert sliced.index.min().date() == start
    assert sliced.index.max().date() == end


def test_read_ohlcv_slice_start_before_cache(tmp_cache_root, sample_ohlcv_df):
    cache.write_ohlcv("AAPL", "1d", sample_ohlcv_df)
    early = date(2000, 1, 1)
    end = sample_ohlcv_df.index[10].date()
    assert cache.read_ohlcv_slice("AAPL", "1d", early, end) is None


def test_cache_disabled(tmp_cache_root, disable_cache):
    # low-level write ignora CACHE_DISABLED: deja el archivo en disco
    path = cache.cache_path("profile", "AAPL.json")
    cache.write_json(path, {"x": 1})
    # get_cached devuelve None aunque el archivo exista
    assert cache.get_cached("profile", "AAPL.json") is None
    # write_cache es no-op
    cache.write_cache("profile", "OTHER.json", {"y": 2})
    assert not cache.cache_path("profile", "OTHER.json").exists()
