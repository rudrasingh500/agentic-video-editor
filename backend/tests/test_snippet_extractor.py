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
    monkeypatch.setattr(snippet_extractor, "_get_haar_face_cascade", lambda: sentinel)

    backend, detector_context = snippet_extractor._open_face_detector()

    assert backend == "opencv_haar"
    assert detector_context is not None
    with detector_context as detector:
        assert detector is sentinel


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
    monkeypatch.setattr(snippet_extractor, "_get_haar_face_cascade", lambda: object())

    backend, detector_context = snippet_extractor._open_face_detector()

    assert backend == "mediapipe"
    assert detector_context is not None
    with detector_context as detector:
        assert detector == "mediapipe_detector"
