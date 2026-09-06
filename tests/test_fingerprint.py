from copy import deepcopy

import pytest

from provenance_pipeline.records.canonical import build_claim
from provenance_pipeline.records.fingerprint import compute_fingerprint
from tests.test_canonical import BASE_VALUES


def test_fingerprint_is_stable_across_key_order_and_normalized_whitespace() -> None:
    clean_body = build_claim(**BASE_VALUES)["fingerprint_body"]
    padded_body = build_claim(
        **{
            **BASE_VALUES,
            "platform": " Instagram ",
            "post_url": " https://instagram.com/p/xxxx ",
            "crop_sha256": f" {'A' * 64} ",
            "embedding_sha256": f" {'B' * 64} ",
            "detector_model_version": " buffalo_l-2026-09 ",
        }
    )["fingerprint_body"]
    reversed_body = dict(reversed(padded_body.items()))

    assert compute_fingerprint(clean_body) == compute_fingerprint(reversed_body)


@pytest.mark.parametrize(
    ("field", "changed_value"),
    [
        ("title_snippet", "A different title"),
        ("thumbnail_url", "https://cdn.example.test/different.jpg"),
        ("match_confidence", 0.12),
    ],
)
def test_envelope_changes_do_not_change_fingerprint(
    field: str, changed_value: object
) -> None:
    original_claim = build_claim(**BASE_VALUES)
    changed_claim = deepcopy(original_claim)
    changed_claim["envelope"][field] = changed_value

    assert compute_fingerprint(original_claim["fingerprint_body"]) == compute_fingerprint(
        changed_claim["fingerprint_body"]
    )


@pytest.mark.parametrize("field", ["crop_sha256", "embedding_sha256"])
def test_photo_binding_hash_changes_fingerprint(field: str) -> None:
    original_claim = build_claim(**BASE_VALUES)
    changed_claim = deepcopy(original_claim)
    changed_claim["fingerprint_body"][field] = "d" * 64

    assert compute_fingerprint(original_claim["fingerprint_body"]) != compute_fingerprint(
        changed_claim["fingerprint_body"]
    )
