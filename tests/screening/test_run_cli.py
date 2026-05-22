"""Tests del parser de CLI de run.py (flag --universe)."""

import pytest

from puts_screener.run import build_arg_parser


def test_universe_single():
    args = build_arg_parser().parse_args(["--universe", "sp500"])
    assert args.universe == ["sp500"]


def test_universe_csv_multi():
    args = build_arg_parser().parse_args(["--universe", "sp500,nasdaq100"])
    assert args.universe == ["sp500", "nasdaq100"]


def test_universe_default_is_sp500():
    args = build_arg_parser().parse_args([])
    assert args.universe == ["sp500"]


def test_universe_invalid_rejected():
    with pytest.raises(SystemExit):
        build_arg_parser().parse_args(["--universe", "foo"])


def test_universe_normalizes_case_and_whitespace():
    args = build_arg_parser().parse_args(["--universe", " SP500 , Nasdaq100 "])
    assert args.universe == ["sp500", "nasdaq100"]
