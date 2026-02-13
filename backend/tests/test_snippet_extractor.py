import pytest
from types import SimpleNamespace

from agent.asset_processing import snippet_extractor


def _require_cv_deps():
    if snippet_extractor.cv2 is None or snippet_extractor.np is None:
        pytest.skip("opencv/numpy dependencies are not available in this environment")


def test_compute_visual_embedding_has_expected_shape_and_norm():
    _require_cv_deps()
    np = snippet_extractor.np

    image = np.full((64, 64, 3), 127, dtype=np.uint8)
    embedding = snippet_extractor._compute_visual_embedding(image)

    assert len(embedding) == 1536

    vector = np.array(embedding, dtype=np.float32)
    norm = float(np.linalg.norm(vector))
    assert 0.99 <= norm <= 1.01


def test_compute_visual_embedding_changes_for_different_inputs():
    _require_cv_deps()
    np = snippet_extractor.np

    black = np.zeros((64, 64, 3), dtype=np.uint8)
    white = np.full((64, 64, 3), 255, dtype=np.uint8)

    emb_black = snippet_extractor._compute_visual_embedding(black)
    emb_white = snippet_extractor._compute_visual_embedding(white)

    assert emb_black != emb_white


def test_open_face_detector_falls_back_to_haar(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(snippet_extractor, "mp", SimpleNamespace())
    monkeypatch.setattr(snippet_extractor, "_refresh_mediapipe_module", lambda: None)
    monkeypatch.setattr(snippet_extractor, "_get_haar_face_cascade", lambda: sentinel)
    monkeypatch.setattr(snippet_extractor, "SNIPPET_REQUIRE_MEDIAPIPE", False)
    monkeypatch.setattr(snippet_extractor, "SNIPPET_ENABLE_HAAR_FALLBACK", True)

    backend, detector_context = snippet_extractor._open_face_detector()

    assert backend == "opencv_haar"
    assert detector_context is not None
    with detector_context as detector:
        assert detector is sentinel


def test_open_face_detector_skips_when_mediapipe_required(monkeypatch):
    monkeypatch.setattr(snippet_extractor, "mp", SimpleNamespace())
    monkeypatch.setattr(snippet_extractor, "_refresh_mediapipe_module", lambda: None)
    monkeypatch.setattr(snippet_extractor, "SNIPPET_REQUIRE_MEDIAPIPE", True)
    monkeypatch.setattr(snippet_extractor, "SNIPPET_ENABLE_HAAR_FALLBACK", True)

    backend, detector_context = snippet_extractor._open_face_detector()

    assert backend == "none"
    assert detector_context is None


def test_open_face_detector_prefers_mediapipe(monkeypatch):
    class _FakeFaceDetection:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return "mediapipe_detector"

        def __exit__(self, exc_type, exc, tb):
            return False

    mp_stub = SimpleNamespace(
        solutions=SimpleNamespace(
            face_detection=SimpleNamespace(FaceDetection=_FakeFaceDetection)
        )
    )

    monkeypatch.setattr(snippet_extractor, "mp", mp_stub)
    monkeypatch.setattr(snippet_extractor, "MEDIAPIPE_ENABLE_DUAL_MODEL", False)
    monkeypatch.setattr(snippet_extractor, "_get_haar_face_cascade", lambda: object())

    backend, detector_context = snippet_extractor._open_face_detector()

    assert backend == "mediapipe"
    assert detector_context is not None
    with detector_context as detector:
        assert detector == "mediapipe_detector"


def test_should_skip_from_metadata_when_faces_empty_and_no_hints(monkeypatch):
    monkeypatch.setattr(snippet_extractor, "SNIPPET_SKIP_WHEN_METADATA_NO_PEOPLE", True)
    metadata = {
        "faces": [],
        "tags": ["nature", "landscape"],
        "summary": "A sandy trail through dry brush.",
    }

    assert snippet_extractor._should_skip_from_metadata(metadata) is True


def test_should_not_skip_from_metadata_when_people_hints(monkeypatch):
    monkeypatch.setattr(snippet_extractor, "SNIPPET_SKIP_WHEN_METADATA_NO_PEOPLE", True)
    metadata = {
        "faces": [],
        "tags": ["portrait", "outdoor"],
        "summary": "Close-up portrait in bright light.",
    }

    assert snippet_extractor._should_skip_from_metadata(metadata) is False


def test_verification_accepts_face_by_threshold(monkeypatch):
    monkeypatch.setattr(snippet_extractor, "SNIPPET_LLM_FACE_MIN_CONF", 0.9)

    accepted_ok, _ = snippet_extractor._verification_accepts_face(
        {"label": "face", "confidence": 0.95}
    )
    accepted_not_person, _ = snippet_extractor._verification_accepts_face(
        {"label": "not_person", "confidence": 0.99}
    )

    assert accepted_ok is True
    assert accepted_not_person is False
