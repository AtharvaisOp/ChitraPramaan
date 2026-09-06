"""Reverse-image search and explicit social-domain filtering."""

from .domain_filter import ALLOWED_SOCIAL_DOMAINS, filter_to_social, normalize_url
from .rerank import (
    DEFAULT_AUTO_THRESHOLD,
    RankedResult,
    cosine_similarity,
    embed_candidate,
    select_match,
)
from .reverse_search import (
    RawResult,
    ReverseSearchError,
    SearchAuthError,
    SearchNotConfigured,
    SearchProviderUnavailable,
    SearchRateLimited,
    SearchResponseInvalid,
    reverse_image_search,
)

__all__ = [
    "ALLOWED_SOCIAL_DOMAINS",
    "DEFAULT_AUTO_THRESHOLD",
    "RawResult",
    "RankedResult",
    "ReverseSearchError",
    "SearchAuthError",
    "SearchNotConfigured",
    "SearchProviderUnavailable",
    "SearchRateLimited",
    "SearchResponseInvalid",
    "cosine_similarity",
    "embed_candidate",
    "filter_to_social",
    "normalize_url",
    "reverse_image_search",
    "select_match",
]
