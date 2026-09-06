from provenance_pipeline.records.canonical import build_claim, canonical_json


BASE_VALUES = {
    "platform": "instagram",
    "post_url": "https://instagram.com/p/xxxx",
    "crop_sha256": "a" * 64,
    "embedding_sha256": "b" * 64,
    "detector_model_version": "buffalo_l-2026-09",
    "title_snippet": "Fixture title",
    "thumbnail_url": "https://cdn.example.test/thumbnail.jpg",
    "match_confidence": 0.83,
    "selection_method": "auto",
    "queried_at": "2026-09-03T12:00:00Z",
    "oracle_response_sha256": "c" * 64,
}


def test_canonical_json_ignores_key_insertion_order() -> None:
    body_in_schema_order = {
        "platform": "instagram",
        "normalized_post_url": "https://instagram.com/p/xxxx",
        "crop_sha256": "a" * 64,
        "embedding_sha256": "b" * 64,
        "detector_model_version": "buffalo_l-2026-09",
    }
    body_in_reverse_order = dict(reversed(body_in_schema_order.items()))

    assert canonical_json(body_in_schema_order) == canonical_json(body_in_reverse_order)


def test_build_claim_normalizes_surrounding_whitespace() -> None:
    clean_claim = build_claim(**BASE_VALUES)
    padded_claim = build_claim(
        **{
            **BASE_VALUES,
            "platform": "  instagram\t",
            "post_url": "\nhttps://instagram.com/p/xxxx  ",
            "crop_sha256": f"  {'a' * 64}\n",
            "embedding_sha256": f"\t{'b' * 64} ",
            "detector_model_version": " buffalo_l-2026-09 ",
        }
    )

    assert clean_claim["fingerprint_body"] == padded_claim["fingerprint_body"]
