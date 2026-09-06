from backend import rate_limit


def test_retry_after_uses_the_limit_that_is_actually_blocking(monkeypatch) -> None:
    monkeypatch.setitem(
        rate_limit.LIMITS,
        "fixture",
        rate_limit.Limit(per_client=2, global_limit=10),
    )
    limiter = rate_limit.SlidingWindowLimiter(window_seconds=10)

    assert limiter.check("fixture", "older-client", now=0) is None
    assert limiter.check("fixture", "blocked-client", now=5) is None
    assert limiter.check("fixture", "blocked-client", now=6) is None

    assert limiter.check("fixture", "blocked-client", now=7) == 8


def test_retry_after_does_not_add_a_second_at_an_exact_boundary(monkeypatch) -> None:
    monkeypatch.setitem(
        rate_limit.LIMITS,
        "fixture",
        rate_limit.Limit(per_client=1, global_limit=10),
    )
    limiter = rate_limit.SlidingWindowLimiter(window_seconds=10)

    assert limiter.check("fixture", "client", now=2) is None
    assert limiter.check("fixture", "client", now=5) == 7
