import pytest

from puts_screener.providers import rate_limit
from puts_screener.providers.rate_limit import RateLimiter


class _FakeTime:
    """Reloj falso: monotonic devuelve `now`, sleep avanza `now` y registra."""

    def __init__(self):
        self.now = 1000.0
        self.sleeps: list[float] = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def test_constructor_rejects_zero():
    with pytest.raises(ValueError):
        RateLimiter(max_per_minute=0)


def test_third_call_blocks(monkeypatch):
    fake = _FakeTime()
    monkeypatch.setattr(rate_limit, "time", fake)

    limiter = RateLimiter(max_per_minute=2)
    limiter.wait_for_slot()
    limiter.wait_for_slot()
    assert fake.sleeps == []  # los dos primeros slots son inmediatos

    limiter.wait_for_slot()  # el tercero debe esperar a que la ventana avance
    assert len(fake.sleeps) == 1
    assert fake.sleeps[0] > 0
