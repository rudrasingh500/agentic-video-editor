from __future__ import annotations

import logging
import os
import tempfile
from contextlib import nullcontext
from typing import Any


cv2: Any = None
mp: Any = None
np: Any = None

try:
    import cv2 as _cv2
    import mediapipe as _mp
    import numpy as _np

    cv2 = _cv2
    mp = _mp
    np = _np
except Exception:  # pragma: no cover - runtime dependency gate
    pass


logger = logging.getLogger(__name__)


FACE_DETECTION_MIN_CONFIDENCE = 0.6
VIDEO_SAMPLE_SECONDS = 1.5
MIN_VIDEO_SAMPLE_STRIDE = 12
HAAR_SCALE_FACTOR = 1.1
HAAR_MIN_NEIGHBORS = 6
HAAR_MIN_SIZE_PX = 40


_HAAR_FACE_CASCADE: Any = None


VIDEO_TYPES = {
    "video/mp4",
    "video/webm",
    "video/quicktime",
    "video/x-msvideo",
    "video/mpeg",
}

IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/heic",
    "image/heif",
}


def extract_snippets_from_asset(content: bytes, content_type: str) -> list[dict[str, Any]]:
    if cv2 is None or mp is None or np is None:
        logger.warning("Snippet extraction skipped: cv dependencies unavailable")
        return []

    if content_type in IMAGE_TYPES:
        image = cv2.imdecode(np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            return []

        detector_backend, detector_context = _open_face_detector()
        if detector_context is None:
            logger.warning("Snippet extraction skipped: no face detector backend")
            return []

        with detector_context as detector:
            return _extract_from_frame(
                image,
                frame_index=0,
                timestamp_ms=0,
                detector=detector,
                detector_backend=detector_backend,
            )

    if content_type in VIDEO_TYPES:
        return _extract_from_video_bytes(content)

    return []


def _extract_from_video_bytes(content: bytes) -> list[dict[str, Any]]:
    snippets: list[dict[str, Any]] = []
    fd, tmp_path = tempfile.mkstemp(suffix=".mp4")
    capture = None
    try:
        with os.fdopen(fd, "wb") as tmp:
            tmp.write(content)

        capture = cv2.VideoCapture(tmp_path)
        if not capture.isOpened():
            return []

        fps = capture.get(cv2.CAP_PROP_FPS) or 24.0
        sample_stride = max(int(fps * VIDEO_SAMPLE_SECONDS), MIN_VIDEO_SAMPLE_STRIDE)

        detector_backend, detector_context = _open_face_detector()
        if detector_context is None:
            logger.warning("Snippet extraction skipped: no face detector backend")
            return []

        with detector_context as detector:
            frame_index = 0
            while True:
                ok, frame = capture.read()
                if not ok:
                    break

                if frame_index % sample_stride == 0:
                    timestamp_ms = int((frame_index / fps) * 1000.0)
                    snippets.extend(
                        _extract_from_frame(
                            frame,
                            frame_index=frame_index,
                            timestamp_ms=timestamp_ms,
                            detector=detector,
                            detector_backend=detector_backend,
                        )
                    )

                frame_index += 1

    finally:
        if capture is not None:
            capture.release()
        try:
            os.remove(tmp_path)
        except OSError:
            logger.debug("Failed to cleanup temporary video file: %s", tmp_path)

    return snippets


def _extract_from_frame(
    frame_bgr: Any,
    frame_index: int,
    timestamp_ms: int,
    detector: Any,
    detector_backend: str,
) -> list[dict[str, Any]]:
    snippets: list[dict[str, Any]] = []
    detections = _detect_faces(
        frame_bgr=frame_bgr,
        detector=detector,
        detector_backend=detector_backend,
    )

    height, width = frame_bgr.shape[:2]
    for face_bbox, face_quality in detections:
        face_crop = _crop(frame_bgr, face_bbox)
        if face_crop.size == 0:
            continue

        face_embedding = _compute_visual_embedding(face_crop)

        face_bytes = _encode_jpeg(face_crop)
        if not face_bytes:
            continue

        snippets.append(
            {
                "snippet_type": "face",
                "frame_index": frame_index,
                "timestamp_ms": timestamp_ms,
                "bbox": _bbox_json(face_bbox, width, height),
                "crop_bytes": face_bytes,
                "preview_bytes": face_bytes,
                "descriptor": "Detected face snippet",
                "embedding": face_embedding,
                "quality_score": face_quality,
                "tags": ["face", "auto-detected"],
            }
        )

        person_bbox = _expand_bbox(face_bbox, width, height)
        person_crop = _crop(frame_bgr, person_bbox)
        if person_crop.size == 0:
            continue

        person_bytes = _encode_jpeg(person_crop)
        if person_bytes:
            snippets.append(
                {
                    "snippet_type": "person",
                    "frame_index": frame_index,
                    "timestamp_ms": timestamp_ms,
                    "bbox": _bbox_json(person_bbox, width, height),
                    "crop_bytes": person_bytes,
                    "preview_bytes": person_bytes,
                    "descriptor": "Face-anchored person region",
                    "embedding": None,
                    "quality_score": face_quality,
                    "tags": ["person", "auto-detected", "context-only"],
                }
            )

    return snippets


def _open_face_detector() -> tuple[str, Any | None]:
    if mp is not None and hasattr(mp, "solutions") and hasattr(mp.solutions, "face_detection"):
        detector = mp.solutions.face_detection.FaceDetection(
            model_selection=0,
            min_detection_confidence=FACE_DETECTION_MIN_CONFIDENCE,
        )
        return "mediapipe", detector

    cascade = _get_haar_face_cascade()
    if cascade is not None:
        return "opencv_haar", nullcontext(cascade)

    return "none", None


def _get_haar_face_cascade() -> Any | None:
    global _HAAR_FACE_CASCADE

    if _HAAR_FACE_CASCADE is not None:
        return _HAAR_FACE_CASCADE

    data_root = getattr(getattr(cv2, "data", None), "haarcascades", None)
    if not data_root:
        return None

    cascade_path = os.path.join(data_root, "haarcascade_frontalface_default.xml")
    if not os.path.exists(cascade_path):
        return None

    cascade = cv2.CascadeClassifier(cascade_path)
    if cascade.empty():
        logger.warning("Failed to load OpenCV Haar cascade: %s", cascade_path)
        return None

    _HAAR_FACE_CASCADE = cascade
    return _HAAR_FACE_CASCADE


def _detect_faces(
    frame_bgr: Any,
    detector: Any,
    detector_backend: str,
) -> list[tuple[tuple[int, int, int, int], float]]:
    if detector_backend == "mediapipe":
        return _detect_faces_mediapipe(frame_bgr, detector)

    if detector_backend == "opencv_haar":
        return _detect_faces_haar(frame_bgr, detector)

    return []


def _detect_faces_mediapipe(
    frame_bgr: Any,
    detector: Any,
) -> list[tuple[tuple[int, int, int, int], float]]:
    height, width = frame_bgr.shape[:2]
    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    result = detector.process(rgb)
    detections = result.detections or []

    found: list[tuple[tuple[int, int, int, int], float]] = []
    for det in detections:
        rel = det.location_data.relative_bounding_box
        bbox = _to_abs_bbox(rel.xmin, rel.ymin, rel.width, rel.height, width, height)
        score = float(det.score[0]) if det.score else 0.0
        found.append((bbox, score))

    return found


def _detect_faces_haar(
    frame_bgr: Any,
    detector: Any,
) -> list[tuple[tuple[int, int, int, int], float]]:
    height, width = frame_bgr.shape[:2]
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)

    min_size = max(HAAR_MIN_SIZE_PX, int(min(width, height) * 0.08))
    boxes = detector.detectMultiScale(
        gray,
        scaleFactor=HAAR_SCALE_FACTOR,
        minNeighbors=HAAR_MIN_NEIGHBORS,
        minSize=(min_size, min_size),
    )

    found: list[tuple[tuple[int, int, int, int], float]] = []
    for x, y, w, h in sorted(boxes, key=lambda item: item[2] * item[3], reverse=True):
        left = int(max(0, x))
        top = int(max(0, y))
        right = int(min(width, x + w))
        bottom = int(min(height, y + h))
        if right <= left or bottom <= top:
            continue

        area_ratio = ((right - left) * (bottom - top)) / float(max(width * height, 1))
        score = float(min(0.95, max(0.55, area_ratio * 8.0)))
        found.append(((left, top, right, bottom), score))

    return found


def _to_abs_bbox(x: float, y: float, w: float, h: float, width: int, height: int) -> tuple[int, int, int, int]:
    left = int(max(0, x * width))
    top = int(max(0, y * height))
    right = int(min(width, (x + w) * width))
    bottom = int(min(height, (y + h) * height))
    return left, top, right, bottom


def _expand_bbox(bbox: tuple[int, int, int, int], width: int, height: int) -> tuple[int, int, int, int]:
    left, top, right, bottom = bbox
    bw = right - left
    bh = bottom - top

    cx = left + bw / 2.0
    cy = top + bh / 2.0

    exp_w = bw * 2.6
    exp_h = bh * 4.2

    x1 = int(max(0, cx - exp_w / 2.0))
    y1 = int(max(0, cy - exp_h * 0.35))
    x2 = int(min(width, cx + exp_w / 2.0))
    y2 = int(min(height, cy + exp_h * 0.65))
    return x1, y1, x2, y2


def _bbox_json(bbox: tuple[int, int, int, int], width: int, height: int) -> dict[str, Any]:
    left, top, right, bottom = bbox
    return {
        "x": left,
        "y": top,
        "width": max(0, right - left),
        "height": max(0, bottom - top),
        "normalized": {
            "x": left / float(width or 1),
            "y": top / float(height or 1),
            "width": (right - left) / float(width or 1),
            "height": (bottom - top) / float(height or 1),
        },
    }


def _crop(frame_bgr: Any, bbox: tuple[int, int, int, int]) -> Any:
    left, top, right, bottom = bbox
    return frame_bgr[top:bottom, left:right]


def _encode_jpeg(image_bgr: Any) -> bytes | None:
    ok, encoded = cv2.imencode(".jpg", image_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    if not ok:
        return None
    return bytes(encoded.tobytes())


def _compute_visual_embedding(image_bgr: Any) -> list[float]:
    resized = cv2.resize(image_bgr, (32, 32), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    gray_vec = gray.astype(np.float32).reshape(-1) / 255.0  # 1024

    hist = cv2.calcHist([resized], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256])
    hist_vec = hist.astype(np.float32).reshape(-1)  # 512
    hist_sum = float(hist_vec.sum())
    if hist_sum > 0:
        hist_vec = hist_vec / hist_sum

    embedding = np.concatenate([gray_vec, hist_vec], axis=0)
    norm = float(np.linalg.norm(embedding))
    if norm > 0:
        embedding = embedding / norm

    if embedding.shape[0] != 1536:
        logger.warning("Unexpected visual embedding shape: %s", embedding.shape)

    return embedding.astype(np.float32).tolist()
