"""Tests para read_ohlcv_raw sin TTL (spec 09 tanda 0)."""

import os
import time

from puts_screener.providers import cache

_HOURS_STALE = 100
_SECONDS_PER_HOUR = 3600


def test_read_ohlcv_raw_returns_dataframe_when_parquet_exists(tmp_cache_root, sample_ohlcv_df):
    cache.write_ohlcv("AAPL", "1d", sample_ohlcv_df)
    df = cache.read_ohlcv_raw("AAPL", "1d")
    assert df is not None
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert len(df) == len(sample_ohlcv_df)


def test_read_ohlcv_raw_returns_none_when_parquet_missing(tmp_cache_root):
    assert cache.read_ohlcv_raw("NONEXISTENT", "1d") is None


def test_read_ohlcv_raw_ignores_ttl(tmp_cache_root, sample_ohlcv_df):
    cache.write_ohlcv("AAPL", "1d", sample_ohlcv_df)
    path = cache.cache_path("ohlcv", "AAPL_1d.parquet")
    stale = time.time() - _HOURS_STALE * _SECONDS_PER_HOUR
    os.utime(path, (stale, stale))
    # read_ohlcv_slice devolvería None (stale > TTL de 24h); read_ohlcv_raw lo ignora.
    df = cache.read_ohlcv_raw("AAPL", "1d")
    assert df is not None
    assert len(df) == len(sample_ohlcv_df)
