import json

import cv2
import numpy as np

from provenance_pipeline.face.detector import FaceDetection, sha256_bytes
from provenance_pipeline.search.rerank import RankedResult
from provenance_pipeline.search.reverse_search import RawResult


def _write_fixture_photo(path) -> bytes:
    y, x = np.indices((96, 112), dtype=np.uint16)
    image = np.stack(
        (
            (x * 3 + y * 5) % 256,
            (x * x + y * 7) % 256,
            (x * 11 + y * y) % 256,
        ),
        axis=2,
    ).astype(np.uint8)
    success, encoded = cv2.imencode(".jpg", image)
    assert success
    uploaded_bytes = encoded.tobytes()
    path.write_bytes(uploaded_bytes)
    return uploaded_bytes


def _prepare_search(tmp_path, monkeypatch):
    from cli import run

    photo_path = tmp_path / "no-result.jpg"
    _write_fixture_photo(photo_path)
    subject = FaceDetection(
        bbox=(20, 15, 75, 75),
        det_score=0.98,
        embedding=np.linspace(0.1, 1.0, 512, dtype=np.float32),
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: "y")
    monkeypatch.setattr(run, "detect_faces", lambda _image: [subject])
    return run, photo_path


def _forbidden(message: str):
    def fail(*_args, **_kwargs):
        raise AssertionError(message)

    return fail


def test_dry_run_executes_end_to_end_and_saves_claim(
    tmp_path, monkeypatch, capsys
) -> None:
    from cli import run

    photo_path = tmp_path / "sample.jpg"
    uploaded_bytes = _write_fixture_photo(photo_path)
    subject = FaceDetection(
        bbox=(20, 15, 75, 75),
        det_score=0.98,
        embedding=np.linspace(0.1, 1.0, 512, dtype=np.float32),
    )
    candidate = RawResult(
        url="https://instagram.com/p/fixture",
        title="Fixture post",
        thumbnail_url="https://images.example.test/fixture.jpg",
        source="Instagram",
    )
    events: list[str] = []

    def confirm(_prompt: str) -> str:
        events.append("consent")
        return "y"

    def fake_detect(_image: np.ndarray) -> list[FaceDetection]:
        events.append("detect")
        return [subject]

    def fake_search(crop_bytes: bytes) -> list[RawResult]:
        events.append("search")
        assert crop_bytes.startswith(b"\xff\xd8\xff")
        assert crop_bytes != uploaded_bytes
        return [candidate]

    def fake_rerank(candidates, query_embedding) -> list[RankedResult]:
        events.append("rerank")
        assert candidates == [candidate]
        assert np.array_equal(query_embedding, subject.embedding)
        return [RankedResult(candidate=candidate, score=0.91)]

    def forbidden_external_write(*_args, **_kwargs):
        raise AssertionError("dry-run must not pin or call the chain")

    monkeypatch.setattr("builtins.input", confirm)
    monkeypatch.setattr(run, "detect_faces", fake_detect)
    monkeypatch.setattr(run, "reverse_image_search", fake_search)
    monkeypatch.setattr(run, "filter_to_social", lambda results: results)
    monkeypatch.setattr(run, "rerank", fake_rerank)
    monkeypatch.setattr(run, "pin_json", forbidden_external_write)
    monkeypatch.setattr(run, "anchor_claim", forbidden_external_write)

    exit_code = run.main(
        [
            "--photo",
            str(photo_path),
            "--auto-threshold",
            "0.90",
            "--network",
            "sepolia",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    assert events == ["consent", "detect", "search", "rerank"]
    claim_path = tmp_path / "sample.claim.json"
    claim = json.loads(claim_path.read_text(encoding="utf-8"))
    assert set(claim) == {"fingerprint_body", "envelope"}
    assert claim["fingerprint_body"]["normalized_post_url"] == candidate.url
    assert claim["envelope"]["selection_method"] == "auto"
    assert claim["envelope"]["match_confidence"] == 0.91
    assert claim["envelope"]["image_sha256"] == sha256_bytes(uploaded_bytes)

    output = capsys.readouterr().out
    assert "Claim summary" in output
    assert "IPFS CID: not pinned (--dry-run)" in output
    assert "Transaction hash: not sent (--dry-run)" in output


def test_consent_rejection_aborts_before_detection_or_search(
    tmp_path, monkeypatch, capsys
) -> None:
    from cli import run

    photo_path = tmp_path / "declined.jpg"
    _write_fixture_photo(photo_path)

    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    monkeypatch.setattr(
        run,
        "detect_faces",
        lambda _image: (_ for _ in ()).throw(
            AssertionError("detection must not run without consent")
        ),
    )
    monkeypatch.setattr(
        run,
        "reverse_image_search",
        lambda _bytes: (_ for _ in ()).throw(
            AssertionError("search must not run without consent")
        ),
    )

    assert run.main(["--photo", str(photo_path), "--dry-run"]) == 2
    assert not (tmp_path / "declined.claim.json").exists()
    assert "No search was performed" in capsys.readouterr().out


def test_zero_raw_results_exits_cleanly(tmp_path, monkeypatch, capsys) -> None:
    run, photo_path = _prepare_search(tmp_path, monkeypatch)
    monkeypatch.setattr(run, "reverse_image_search", lambda _crop: [])
    monkeypatch.setattr(
        run,
        "filter_to_social",
        _forbidden("filtering must not run without provider results"),
    )
    monkeypatch.setattr(
        run,
        "rerank",
        _forbidden("rerank must not run without provider results"),
    )
    monkeypatch.setattr(
        run,
        "_choose_match",
        _forbidden("selection must not run without provider results"),
    )

    exit_code = run.main(["--photo", str(photo_path), "--dry-run"])

    captured = capsys.readouterr()
    assert exit_code != 0
    assert (
        "No matching images were found for this photo. Try another photo."
        in captured.err
    )
    assert "Traceback" not in captured.out + captured.err
    assert not photo_path.with_suffix(".claim.json").exists()


def test_zero_supported_results_exits_cleanly(
    tmp_path, monkeypatch, capsys
) -> None:
    run, photo_path = _prepare_search(tmp_path, monkeypatch)
    raw_result = RawResult(
        url="https://news.example.test/photo",
        title="Unsupported source",
        thumbnail_url="https://images.example.test/photo.jpg",
        source="News",
    )
    monkeypatch.setattr(run, "reverse_image_search", lambda _crop: [raw_result])
    monkeypatch.setattr(run, "filter_to_social", lambda _results: [])
    monkeypatch.setattr(
        run,
        "rerank",
        _forbidden("rerank must not run without supported candidates"),
    )
    monkeypatch.setattr(
        run,
        "_choose_match",
        _forbidden("selection must not run without supported candidates"),
    )

    exit_code = run.main(["--photo", str(photo_path), "--dry-run"])

    captured = capsys.readouterr()
    assert exit_code != 0
    assert (
        "No supported source results were found. Try another photo."
        in captured.err
    )
    assert "Traceback" not in captured.out + captured.err
    assert not photo_path.with_suffix(".claim.json").exists()


def test_zero_ranked_results_exits_cleanly(tmp_path, monkeypatch, capsys) -> None:
    run, photo_path = _prepare_search(tmp_path, monkeypatch)
    social_result = RawResult(
        url="https://instagram.com/p/no-face",
        title="Supported source",
        thumbnail_url="https://images.example.test/no-face.jpg",
        source="Instagram",
    )
    monkeypatch.setattr(run, "reverse_image_search", lambda _crop: [social_result])
    monkeypatch.setattr(run, "filter_to_social", lambda results: results)
    monkeypatch.setattr(run, "rerank", lambda _candidates, _embedding: [])
    monkeypatch.setattr(
        run,
        "_choose_match",
        _forbidden("selection must not run without ranked candidates"),
    )

    exit_code = run.main(["--photo", str(photo_path), "--dry-run"])

    captured = capsys.readouterr()
    assert exit_code != 0
    assert (
        "No candidate thumbnails had a usable face. Try another photo."
        in captured.err
    )
    assert "Traceback" not in captured.out + captured.err
    assert not photo_path.with_suffix(".claim.json").exists()


def test_cli_collects_multi_face_subject_choice(monkeypatch) -> None:
    from cli import run

    faces = [
        FaceDetection(
            bbox=(0, 0, 40, 40),
            det_score=0.9,
            embedding=np.zeros(512, dtype=np.float32),
        ),
        FaceDetection(
            bbox=(50, 10, 70, 30),
            det_score=0.99,
            embedding=np.ones(512, dtype=np.float32),
        ),
    ]
    monkeypatch.setattr("builtins.input", lambda _prompt: "2")

    assert run._choose_subject(faces) is faces[1]


def test_cli_collects_below_threshold_match_choice(monkeypatch) -> None:
    from cli import run

    ranked = [
        RankedResult(
            candidate=RawResult(
                url="https://instagram.com/p/first",
                title="First",
                thumbnail_url="https://example.test/first.jpg",
                source="fixture",
            ),
            score=0.79,
        ),
        RankedResult(
            candidate=RawResult(
                url="https://instagram.com/p/second",
                title="Second",
                thumbnail_url="https://example.test/second.jpg",
                source="fixture",
            ),
            score=0.72,
        ),
    ]
    monkeypatch.setattr("builtins.input", lambda _prompt: "2")

    selected, method = run._choose_match(ranked, auto_threshold=0.8)

    assert selected is ranked[1]
    assert method == "human"
