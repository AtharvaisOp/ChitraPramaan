from threading import Lock
import time

import pytest
import requests

from provenance_pipeline.search.domain_filter import (
    MAX_REDIRECT_WORKERS,
    filter_to_social,
    normalize_url,
)
from provenance_pipeline.search.reverse_search import RawResult


def _result(url: str, title: str) -> RawResult:
    return RawResult(
        url=url,
        title=title,
        thumbnail_url=f"https://images.example.test/{title}.jpg",
        source="fixture",
    )


def test_normalize_url_resolves_redirects_and_strips_tracking(monkeypatch) -> None:
    requested_urls: list[str] = []

    def fake_head(url: str, **kwargs):
        requested_urls.append(url)
        assert kwargs["method"] == "HEAD"
        return (
                "https://www.instagram.com/p/abc123/"
                "?utm_medium=social&keep=value&fbclid=secret#comments"
            )

    monkeypatch.setattr(
        "provenance_pipeline.search.domain_filter.public_request", fake_head
    )

    normalized = normalize_url(
        " HTTPS://redirect.example/path?utm_source=oracle&token=kept#fragment "
    )

    assert requested_urls == ["https://redirect.example/path?token=kept"]
    assert normalized == "https://www.instagram.com/p/abc123/?keep=value"


def test_filter_to_social_uses_explicit_domains_and_preserves_order(
    monkeypatch,
) -> None:
    redirect_targets = {
        "https://short.example/x-post": "https://mobile.x.com/user/status/1?utm_source=lens",
        "https://instagram.com/p/2": "https://instagram.com/p/2?igshid=tracking",
        "https://notinstagram.com/lookalike": "https://notinstagram.com/lookalike",
        "https://news.example/article": "https://news.example/article",
        "https://old.example/reddit": "https://www.reddit.com/r/pics/comments/3?fbclid=x",
    }

    def fake_head(url: str, **_kwargs):
        return redirect_targets[url]

    monkeypatch.setattr(
        "provenance_pipeline.search.domain_filter.public_request", fake_head
    )
    results = [
        _result("https://short.example/x-post", "x"),
        _result("https://instagram.com/p/2?igshid=tracking", "instagram"),
        _result("https://notinstagram.com/lookalike", "lookalike"),
        _result("https://news.example/article", "news"),
        _result("https://old.example/reddit", "reddit"),
    ]

    filtered = filter_to_social(results)

    assert [result.title for result in filtered] == ["x", "instagram", "reddit"]
    assert [result.url for result in filtered] == [
        "https://mobile.x.com/user/status/1",
        "https://instagram.com/p/2",
        "https://www.reddit.com/r/pics/comments/3",
    ]


def test_normalize_url_keeps_original_when_head_fails(monkeypatch) -> None:
    def fail_head(*_args, **_kwargs):
        raise requests.Timeout("fixture timeout")

    monkeypatch.setattr(
        "provenance_pipeline.search.domain_filter.public_request", fail_head
    )

    assert normalize_url("https://x.com/a?utm_campaign=test&id=7#reply") == (
        "https://x.com/a?id=7"
    )


@pytest.mark.parametrize(
    "hostname",
    [
        "x.com",
        "twitter.com",
        "instagram.com",
        "facebook.com",
        "linkedin.com",
        "reddit.com",
        "tiktok.com",
    ],
)
def test_every_documented_domain_is_allowed(monkeypatch, hostname: str) -> None:
    url = f"https://www.{hostname}/fixture"
    monkeypatch.setattr(
        "provenance_pipeline.search.domain_filter.public_request",
        lambda *_args, **_kwargs: url,
    )

    assert filter_to_social([_result(url, hostname)])[0].url == url


def test_redirect_resolution_concurrency_is_bounded(monkeypatch) -> None:
    lock = Lock()
    active = 0
    peak = 0

    def fake_head(url: str, **_kwargs) -> str:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return url

    monkeypatch.setattr(
        "provenance_pipeline.search.domain_filter.public_request", fake_head
    )
    results = [
        _result(f"https://instagram.com/p/{index}", str(index))
        for index in range(18)
    ]

    filtered = filter_to_social(results)

    assert [result.title for result in filtered] == [str(index) for index in range(18)]
    assert 1 < peak <= MAX_REDIRECT_WORKERS
