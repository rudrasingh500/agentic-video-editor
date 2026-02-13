from __future__ import annotations

import base64
import json
import logging
import os
import tempfile
from contextlib import nullcontext
from typing import Any

from openai import OpenAI

from . import config
from .prompts import FACE_VERIFICATION_PROMPT


cv2: Any = None
mp: Any = None
np: Any = None
_CV_IMPORT_ERROR: str | None = None
_MEDIAPIPE_IMPORT_ERROR: str | None = None
_NUMPY_IMPORT_ERROR: str | None = None

try:
    import cv2 as _cv2
    cv2 = _cv2
except Exception as exc:  # pragma: no cover - runtime dependency gate
    _CV_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"

try:
    import mediapipe as _mp

    mp = _mp
except Exception as exc:  # pragma: no cover - runtime dependency gate
    _MEDIAPIPE_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"

try:
    import numpy as _np

    np = _np
except Exception as exc:  # pragma: no cover - runtime dependency gate
    _NUMPY_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"


logger = logging.getLogger(__name__)


class _DetectorGroup:
    def __init__(self, detectors: list[Any]) -> None:
        self._detectors = detectors

    def __enter__(self) -> list[Any]:
        return self._detectors

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        for detector in reversed(self._detectors):
            close = getattr(detector, "close", None)
            if callable(close):
                close()
        return False


VIDEO_SAMPLE_SECONDS = config.VIDEO_SAMPLE_SECONDS
MIN_VIDEO_SAMPLE_STRIDE = config.MIN_VIDEO_SAMPLE_STRIDE
HAAR_SCALE_FACTOR = 1.1
HAAR_MIN_NEIGHBORS = 6
HAAR_MIN_SIZE_PX = 40
MEDIAPIPE_FACE_DETECTION_MIN_CONFIDENCE = config.MEDIAPIPE_FACE_DETECTION_MIN_CONFIDENCE
MEDIAPIPE_MODEL_SELECTION = config.MEDIAPIPE_MODEL_SELECTION
MEDIAPIPE_ENABLE_DUAL_MODEL = config.MEDIAPIPE_ENABLE_DUAL_MODEL
HAAR_FACE_DETECTION_MIN_CONFIDENCE = config.HAAR_FACE_DETECTION_MIN_CONFIDENCE
SNIPPET_FACE_MODE = config.SNIPPET_FACE_MODE
SNIPPET_REQUIRE_MEDIAPIPE = config.SNIPPET_REQUIRE_MEDIAPIPE
SNIPPET_ENABLE_HAAR_FALLBACK = config.SNIPPET_ENABLE_HAAR_FALLBACK
SNIPPET_ENABLE_HAAR_ASSIST = config.SNIPPET_ENABLE_HAAR_ASSIST
SNIPPET_ENABLE_LLM_FACE_VERIFY = config.SNIPPET_ENABLE_LLM_FACE_VERIFY
SNIPPET_SKIP_WHEN_METADATA_NO_PEOPLE = config.SNIPPET_SKIP_WHEN_METADATA_NO_PEOPLE
SNIPPET_CREATE_PERSON_CONTEXT = config.SNIPPET_CREATE_PERSON_CONTEXT
MEDIAPIPE_FACE_MIN_SHARPNESS = config.MEDIAPIPE_FACE_MIN_SHARPNESS
HAAR_FACE_MIN_SHARPNESS = config.HAAR_FACE_MIN_SHARPNESS
SNIPPET_FACE_MIN_AREA_RATIO = config.SNIPPET_FACE_MIN_AREA_RATIO
SNIPPET_FACE_MAX_AREA_RATIO = config.SNIPPET_FACE_MAX_AREA_RATIO
SNIPPET_FACE_MIN_SIDE_PX = config.SNIPPET_FACE_MIN_SIDE_PX
SNIPPET_FACE_MIN_ASPECT_RATIO = config.SNIPPET_FACE_MIN_ASPECT_RATIO
SNIPPET_FACE_MAX_ASPECT_RATIO = config.SNIPPET_FACE_MAX_ASPECT_RATIO
SNIPPET_LLM_FACE_MIN_CONF = config.SNIPPET_LLM_FACE_MIN_CONF
SNIPPET_FACE_VERIFY_MIN_SIDE_PX = config.SNIPPET_FACE_VERIFY_MIN_SIDE_PX
VIDEO_USE_METADATA_FACE_WINDOWS = config.VIDEO_USE_METADATA_FACE_WINDOWS
VIDEO_FACE_WINDOW_PADDING_MS = config.VIDEO_FACE_WINDOW_PADDING_MS
VIDEO_FACE_SAMPLES_PER_WINDOW = config.VIDEO_FACE_SAMPLES_PER_WINDOW
VIDEO_BASELINE_SAMPLES = config.VIDEO_BASELINE_SAMPLES
SNIPPET_MAX_CANDIDATES_PER_FRAME = config.SNIPPET_MAX_CANDIDATES_PER_FRAME
SNIPPET_MAX_LLM_VERIFICATIONS_PER_ASSET = config.SNIPPET_MAX_LLM_VERIFICATIONS_PER_ASSET
SNIPPET_MAX_ACCEPTED_FACES_PER_ASSET = config.SNIPPET_MAX_ACCEPTED_FACES_PER_ASSET
SNIPPET_ALLOW_CONTEXT_RECOVERY = config.SNIPPET_ALLOW_CONTEXT_RECOVERY
SNIPPET_CONTEXT_RECOVERY_MIN_DETECTOR_SCORE = config.SNIPPET_CONTEXT_RECOVERY_MIN_DETECTOR_SCORE
SNIPPET_CONTEXT_RECOVERY_MIN_CONTEXT_CONF = config.SNIPPET_CONTEXT_RECOVERY_MIN_CONTEXT_CONF
SNIPPET_CONTEXT_RECOVERY_MAX_NOT_PERSON_CONF = config.SNIPPET_CONTEXT_RECOVERY_MAX_NOT_PERSON_CONF
SNIPPET_FACE_VERIFY_MODEL = os.getenv(
    "SNIPPET_FACE_VERIFY_MODEL", "google/gemini-3-flash-preview"
)
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
FACE_VERIFICATION_REASONING_CONFIG = {
    "reasoning": {
        "effort": "medium",
    }
}

FACE_METADATA_HINT_KEYWORDS = {
    "person",
    "people",
    "face",
    "portrait",
    "selfie",
    "man",
    "woman",
    "child",
    "adult",
    "group",
}


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


def extract_snippets_from_asset(
    content: bytes,
    content_type: str,
    metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    logger.debug(
        "snippet_extract_start content_type=%s bytes=%d face_mode=%s require_mediapipe=%s llm_verify=%s mp_min_conf=%.3f mp_min_sharpness=%.1f",
        content_type,
        len(content),
        SNIPPET_FACE_MODE,
        SNIPPET_REQUIRE_MEDIAPIPE,
        SNIPPET_ENABLE_LLM_FACE_VERIFY,
        MEDIAPIPE_FACE_DETECTION_MIN_CONFIDENCE,
        MEDIAPIPE_FACE_MIN_SHARPNESS,
    )

    if cv2 is None or np is None:
        logger.warning("Snippet extraction skipped: cv dependencies unavailable")
        return []

    if _should_skip_from_metadata(metadata):
        logger.info(
            "Snippet extraction skipped: metadata indicates no people/faces tags=%s faces=%s",
            metadata.get("tags") if isinstance(metadata, dict) else None,
            metadata.get("faces") if isinstance(metadata, dict) else None,
        )
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
            snippets = _extract_from_frame(
                image,
                frame_index=0,
                timestamp_ms=0,
                detector=detector,
                detector_backend=detector_backend,
            )
            logger.info(
                "snippet_extract_complete mode=image detector=%s snippets=%d",
                detector_backend,
                len(snippets),
            )
            return snippets

    if content_type in VIDEO_TYPES:
        snippets = _extract_from_video_bytes(content, metadata=metadata)
        logger.info("snippet_extract_complete mode=video snippets=%d", len(snippets))
        return snippets

    return []


def _extract_from_video_bytes(
    content: bytes,
    metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
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
        total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        sample_stride = max(int(fps * VIDEO_SAMPLE_SECONDS), MIN_VIDEO_SAMPLE_STRIDE)
        expected_faces = _expected_face_count(metadata)
        face_windows_ms = _collect_face_windows_ms(metadata)
        target_frames = _build_target_sample_frames(
            total_frames=total_frames,
            fps=fps,
            sample_stride=sample_stride,
            face_windows_ms=face_windows_ms,
            expected_faces=expected_faces,
        )

        budgets = {
            "llm_checks": 0,
            "accepted_faces": 0,
        }

        logger.debug(
            "video_sampling fps=%.3f sample_stride=%d seconds=%.2f total_frames=%d target_frames=%d windows=%d expected_faces=%d llm_budget=%d face_budget=%d",
            fps,
            sample_stride,
            VIDEO_SAMPLE_SECONDS,
            total_frames,
            len(target_frames),
            len(face_windows_ms),
            expected_faces,
            SNIPPET_MAX_LLM_VERIFICATIONS_PER_ASSET,
            SNIPPET_MAX_ACCEPTED_FACES_PER_ASSET,
        )

        detector_backend, detector_context = _open_face_detector()
        if detector_context is None:
            logger.warning("Snippet extraction skipped: no face detector backend")
            return []

        with detector_context as detector:
            frame_index = 0
            sampled_frames = 0
            while True:
                ok, frame = capture.read()
                if not ok:
                    break

                if frame_index in target_frames:
                    sampled_frames += 1
                    timestamp_ms = int((frame_index / fps) * 1000.0)
                    snippets.extend(
                        _extract_from_frame(
                            frame,
                            frame_index=frame_index,
                            timestamp_ms=timestamp_ms,
                            detector=detector,
                            detector_backend=detector_backend,
                            budgets=budgets,
                            expected_faces=expected_faces,
                        )
                    )

                if (
                    budgets["llm_checks"] >= SNIPPET_MAX_LLM_VERIFICATIONS_PER_ASSET
                    or budgets["accepted_faces"] >= SNIPPET_MAX_ACCEPTED_FACES_PER_ASSET
                ):
                    logger.debug(
                        "video_snippet_budget_stop frame=%d llm_checks=%d accepted_faces=%d",
                        frame_index,
                        budgets["llm_checks"],
                        budgets["accepted_faces"],
                    )
                    break

                frame_index += 1

            logger.info(
                "video_snippet_pass_complete total_frames=%d sampled_frames=%d snippets=%d detector=%s",
                frame_index,
                sampled_frames,
                len(snippets),
                detector_backend,
            )

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
    budgets: dict[str, int] | None = None,
    expected_faces: int = 0,
) -> list[dict[str, Any]]:
    snippets: list[dict[str, Any]] = []
    detections = _detect_faces(
        frame_bgr=frame_bgr,
        detector=detector,
        detector_backend=detector_backend,
    )
    detections = sorted(detections, key=lambda item: item[1], reverse=True)
    per_frame_cap = SNIPPET_MAX_CANDIDATES_PER_FRAME
    if expected_faces > 0:
        per_frame_cap = max(per_frame_cap, min(expected_faces, 4))
    if per_frame_cap > 0:
        detections = detections[:per_frame_cap]

    height, width = frame_bgr.shape[:2]
    frame_bytes = _encode_jpeg(frame_bgr)
    quality_reject_counts: dict[str, int] = {}
    verification_reject_counts: dict[str, int] = {}
    accepted_faces = 0
    for face_bbox, face_quality in detections:
        if expected_faces > 0 and accepted_faces >= expected_faces:
            break

        quality_ok, quality_reason = _passes_detection_quality(
            face_bbox,
            frame_bgr,
            face_quality,
            detector_backend,
        )
        if not quality_ok:
            quality_reject_counts[quality_reason] = quality_reject_counts.get(quality_reason, 0) + 1
            continue

        face_crop = _crop(frame_bgr, face_bbox)
        if face_crop.size == 0:
            continue

        face_bytes = _encode_jpeg(face_crop)
        if not face_bytes:
            continue

        verification_crop = _prepare_verification_crop(face_crop)
        verification_bytes = _encode_jpeg(verification_crop)
        if not verification_bytes:
            verification_bytes = face_bytes

        verification = _verify_face_candidate_llm(
            face_bytes=verification_bytes,
            frame_bytes=frame_bytes,
            bbox=_bbox_json(face_bbox, width, height),
        )
        if budgets is not None:
            budgets["llm_checks"] = budgets.get("llm_checks", 0) + 1
        accepted, verification_reason = _verification_accepts_face(verification)
        if (
            not accepted
            and _should_recover_context_face(
                verification=verification,
                detector_score=face_quality,
                expected_faces=expected_faces,
                accepted_faces=accepted_faces,
            )
        ):
            accepted = True
            verification_reason = "context_recovery"

        if not accepted:
            verification_reject_counts[verification_reason] = (
                verification_reject_counts.get(verification_reason, 0) + 1
            )
            continue

        face_embedding = _compute_visual_embedding(face_crop)
        accepted_faces += 1
        if budgets is not None:
            budgets["accepted_faces"] = budgets.get("accepted_faces", 0) + 1

        snippets.append(
            {
                "snippet_type": "face",
                "frame_index": frame_index,
                "timestamp_ms": timestamp_ms,
                "bbox": _bbox_json(face_bbox, width, height),
                "crop_bytes": face_bytes,
                "preview_bytes": face_bytes,
                "descriptor": "Verified face snippet",
                "embedding": face_embedding,
                "quality_score": face_quality,
                "tags": (
                    ["face", "auto-detected", "verified-face"]
                    if verification_reason != "context_recovery"
                    else ["face", "auto-detected", "verified-face", "context-recovery"]
                ),
                "verification": verification,
            }
        )

        if SNIPPET_CREATE_PERSON_CONTEXT:
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
                        "verification": verification,
                    }
                )

    if detections:
        logger.debug(
            "frame_snippet_trace frame=%d ts_ms=%d detections=%d accepted_faces=%d quality_rejects=%s verification_rejects=%s",
            frame_index,
            timestamp_ms,
            len(detections),
            accepted_faces,
            quality_reject_counts,
            verification_reject_counts,
        )

    return snippets


def _open_face_detector() -> tuple[str, Any | None]:
    _refresh_mediapipe_module()

    if mp is not None and hasattr(mp, "solutions") and hasattr(mp.solutions, "face_detection"):
        detector = mp.solutions.face_detection.FaceDetection(
            model_selection=MEDIAPIPE_MODEL_SELECTION,
            min_detection_confidence=MEDIAPIPE_FACE_DETECTION_MIN_CONFIDENCE,
        )
        if MEDIAPIPE_ENABLE_DUAL_MODEL:
            secondary_model = 1 if MEDIAPIPE_MODEL_SELECTION == 0 else 0
            secondary_detector = mp.solutions.face_detection.FaceDetection(
                model_selection=secondary_model,
                min_detection_confidence=MEDIAPIPE_FACE_DETECTION_MIN_CONFIDENCE,
            )

            logger.debug(
                "face_detector_opened backend=mediapipe_dual model_selection=%d secondary_model=%d min_conf=%.3f",
                MEDIAPIPE_MODEL_SELECTION,
                secondary_model,
                MEDIAPIPE_FACE_DETECTION_MIN_CONFIDENCE,
            )
            return "mediapipe", _DetectorGroup([detector, secondary_detector])

        logger.debug(
            "face_detector_opened backend=mediapipe model_selection=%d min_conf=%.3f",
            MEDIAPIPE_MODEL_SELECTION,
            MEDIAPIPE_FACE_DETECTION_MIN_CONFIDENCE,
        )
        return "mediapipe", detector

    if SNIPPET_REQUIRE_MEDIAPIPE:
        logger.warning(
            "Snippet extraction skipped: mediapipe required but unavailable import_error=%s module=%s has_solutions=%s has_face_detection=%s",
            _MEDIAPIPE_IMPORT_ERROR,
            getattr(mp, "__name__", None) if mp is not None else None,
            bool(mp is not None and hasattr(mp, "solutions")),
            bool(mp is not None and hasattr(getattr(mp, "solutions", None), "face_detection")),
        )
        return "none", None

    if not SNIPPET_ENABLE_HAAR_FALLBACK:
        logger.warning("Snippet extraction skipped: haar fallback disabled")
        return "none", None

    cascade = _get_haar_face_cascade()
    if cascade is not None:
        logger.debug("face_detector_opened backend=opencv_haar")
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


def _refresh_mediapipe_module() -> None:
    global mp, _MEDIAPIPE_IMPORT_ERROR

    if mp is not None and hasattr(mp, "solutions") and hasattr(mp.solutions, "face_detection"):
        return

    try:
        import mediapipe as _mp_runtime

        mp = _mp_runtime
        _MEDIAPIPE_IMPORT_ERROR = None
    except Exception as exc:  # pragma: no cover - runtime dependency gate
        _MEDIAPIPE_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"


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

    if isinstance(detector, (list, tuple)):
        detector_objs = list(detector)
    else:
        detector_objs = [detector]

    found: list[tuple[tuple[int, int, int, int], float]] = []
    for detector_obj in detector_objs:
        result = detector_obj.process(rgb)
        detections = result.detections or []
        for det in detections:
            rel = det.location_data.relative_bounding_box
            bbox = _to_abs_bbox(rel.xmin, rel.ymin, rel.width, rel.height, width, height)
            score = float(det.score[0]) if det.score else 0.0
            found.append((bbox, score))

    if SNIPPET_ENABLE_HAAR_ASSIST:
        haar_detector = _get_haar_face_cascade()
        if haar_detector is not None:
            assisted = _detect_faces_haar(frame_bgr, haar_detector)
            if assisted:
                logger.debug(
                    "mediapipe_haar_assist mp=%d haar=%d",
                    len(found),
                    len(assisted),
                )
                found.extend(assisted)

    deduped = _dedupe_detections(found)
    if len(found) != len(deduped):
        logger.debug("mediapipe_dedupe raw=%d deduped=%d", len(found), len(deduped))
    return deduped


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


def _dedupe_detections(
    detections: list[tuple[tuple[int, int, int, int], float]],
    iou_threshold: float = 0.45,
) -> list[tuple[tuple[int, int, int, int], float]]:
    if len(detections) < 2:
        return detections

    ordered = sorted(detections, key=lambda item: item[1], reverse=True)
    selected: list[tuple[tuple[int, int, int, int], float]] = []
    for bbox, score in ordered:
        if all(_bbox_iou(bbox, kept_bbox) < iou_threshold for kept_bbox, _ in selected):
            selected.append((bbox, score))
    return selected


def _bbox_iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b

    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)

    inter_w = max(0, ix2 - ix1)
    inter_h = max(0, iy2 - iy1)
    inter_area = inter_w * inter_h
    if inter_area <= 0:
        return 0.0

    a_area = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    b_area = max(0, bx2 - bx1) * max(0, by2 - by1)
    union = max(a_area + b_area - inter_area, 1)
    return inter_area / float(union)


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


def _collect_face_windows_ms(metadata: dict[str, Any] | None) -> list[tuple[int, int]]:
    if not VIDEO_USE_METADATA_FACE_WINDOWS:
        return []
    if not isinstance(metadata, dict):
        return []

    faces = metadata.get("faces")
    if not isinstance(faces, list):
        return []

    windows: list[tuple[int, int]] = []
    for item in faces:
        if not isinstance(item, dict):
            continue

        start_ms = _safe_int_ms(item.get("start_ms"))
        end_ms = _safe_int_ms(item.get("end_ms"))
        if start_ms is None:
            start_ms = _safe_int_ms(item.get("start_time_ms"))
        if end_ms is None:
            end_ms = _safe_int_ms(item.get("end_time_ms"))

        if start_ms is None or end_ms is None:
            anchor_ms = _safe_int_ms(item.get("appears_at_ms"))
            if anchor_ms is None:
                anchor_ms = _safe_int_ms(item.get("timestamp_ms"))
            if anchor_ms is None:
                anchor_ms = _safe_int_ms(item.get("time_ms"))
            if anchor_ms is not None:
                start_ms = anchor_ms - VIDEO_FACE_WINDOW_PADDING_MS
                end_ms = anchor_ms + VIDEO_FACE_WINDOW_PADDING_MS

        if start_ms is None or end_ms is None:
            continue

        s = max(0, min(start_ms, end_ms))
        e = max(0, max(start_ms, end_ms))
        windows.append((s, e))

    return windows


def _safe_int_ms(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(round(float(value)))
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            return int(round(float(raw)))
        except ValueError:
            return None
    return None


def _build_target_sample_frames(
    total_frames: int,
    fps: float,
    sample_stride: int,
    face_windows_ms: list[tuple[int, int]],
    expected_faces: int = 0,
) -> set[int]:
    if total_frames <= 0:
        return set()

    targets: set[int] = set()
    if face_windows_ms:
        per_window = max(1, VIDEO_FACE_SAMPLES_PER_WINDOW)
        for start_ms, end_ms in face_windows_ms:
            start_frame = max(0, int((start_ms / 1000.0) * fps))
            end_frame = min(total_frames - 1, int((end_ms / 1000.0) * fps))
            if end_frame < start_frame:
                continue
            if per_window == 1:
                targets.add((start_frame + end_frame) // 2)
                continue

            span = max(end_frame - start_frame, 1)
            for idx in range(per_window):
                ratio = idx / float(per_window - 1)
                frame_idx = start_frame + int(round(span * ratio))
                targets.add(max(0, min(total_frames - 1, frame_idx)))

    baseline = max(1, VIDEO_BASELINE_SAMPLES, expected_faces * 3 if expected_faces > 0 else 1)
    if baseline == 1:
        targets.add(0)
    else:
        span = max(total_frames - 1, 1)
        for idx in range(baseline):
            ratio = idx / float(baseline - 1)
            frame_idx = int(round(span * ratio))
            targets.add(max(0, min(total_frames - 1, frame_idx)))

    if not targets:
        for frame_idx in range(0, total_frames, max(1, sample_stride)):
            targets.add(frame_idx)

    return targets


def _expected_face_count(metadata: dict[str, Any] | None) -> int:
    if not isinstance(metadata, dict):
        return 0
    faces = metadata.get("faces")
    if isinstance(faces, list):
        return max(0, len(faces))
    if isinstance(faces, dict) and faces:
        return 1
    return 0


def _prepare_verification_crop(image_bgr: Any) -> Any:
    height, width = image_bgr.shape[:2]
    shortest_side = min(height, width)
    if shortest_side >= SNIPPET_FACE_VERIFY_MIN_SIDE_PX:
        return image_bgr

    scale = SNIPPET_FACE_VERIFY_MIN_SIDE_PX / float(max(shortest_side, 1))
    target_w = max(1, int(round(width * scale)))
    target_h = max(1, int(round(height * scale)))
    return cv2.resize(image_bgr, (target_w, target_h), interpolation=cv2.INTER_CUBIC)


def _should_skip_from_metadata(metadata: dict[str, Any] | None) -> bool:
    if not SNIPPET_SKIP_WHEN_METADATA_NO_PEOPLE:
        return False
    if not isinstance(metadata, dict) or not metadata:
        return False

    technical = metadata.get("technical")
    if isinstance(technical, dict) and technical.get("analysis_fallback"):
        return False

    faces = metadata.get("faces")
    if isinstance(faces, list) and len(faces) > 0:
        return False
    if isinstance(faces, dict) and faces:
        return False

    if _metadata_has_person_hints(metadata):
        return False

    return isinstance(faces, list) and len(faces) == 0


def _metadata_has_person_hints(metadata: dict[str, Any]) -> bool:
    tags = metadata.get("tags")
    if isinstance(tags, list):
        for tag in tags:
            if not isinstance(tag, str):
                continue
            lower_tag = tag.lower()
            if any(keyword in lower_tag for keyword in FACE_METADATA_HINT_KEYWORDS):
                return True

    summary = metadata.get("summary")
    if isinstance(summary, str):
        summary_lower = summary.lower()
        if any(keyword in summary_lower for keyword in FACE_METADATA_HINT_KEYWORDS):
            return True

    return False


def _passes_detection_quality(
    bbox: tuple[int, int, int, int],
    frame_bgr: Any,
    detector_score: float,
    detector_backend: str,
) -> tuple[bool, str]:
    min_detector_confidence = (
        MEDIAPIPE_FACE_DETECTION_MIN_CONFIDENCE
        if detector_backend == "mediapipe"
        else HAAR_FACE_DETECTION_MIN_CONFIDENCE
    )
    if detector_score < min_detector_confidence:
        return False, "detector_conf_too_low"

    height, width = frame_bgr.shape[:2]
    left, top, right, bottom = bbox
    bw = max(0, right - left)
    bh = max(0, bottom - top)
    if bw < SNIPPET_FACE_MIN_SIDE_PX or bh < SNIPPET_FACE_MIN_SIDE_PX:
        return False, "bbox_too_small"

    frame_area = max(width * height, 1)
    area_ratio = (bw * bh) / float(frame_area)
    if area_ratio < SNIPPET_FACE_MIN_AREA_RATIO or area_ratio > SNIPPET_FACE_MAX_AREA_RATIO:
        return False, "bbox_area_ratio_out_of_range"

    aspect_ratio = bw / float(max(bh, 1))
    if (
        aspect_ratio < SNIPPET_FACE_MIN_ASPECT_RATIO
        or aspect_ratio > SNIPPET_FACE_MAX_ASPECT_RATIO
    ):
        return False, "bbox_aspect_out_of_range"

    crop = _crop(frame_bgr, bbox)
    if crop.size == 0:
        return False, "empty_crop"

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    min_sharpness = (
        MEDIAPIPE_FACE_MIN_SHARPNESS
        if detector_backend == "mediapipe"
        else HAAR_FACE_MIN_SHARPNESS
    )
    if sharpness < min_sharpness:
        return False, "sharpness_too_low"

    return True, "ok"


def _get_openrouter_client() -> OpenAI | None:
    if not OPENROUTER_API_KEY:
        return None
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=OPENROUTER_API_KEY,
    )


def _verify_face_candidate_llm(
    face_bytes: bytes,
    frame_bytes: bytes | None,
    bbox: dict[str, Any] | None,
) -> dict[str, Any]:
    default_reject = {
        "label": "not_person",
        "confidence": 0.0,
        "reason": "verification_unavailable",
        "occlusion": "unknown",
        "frontalness": "unknown",
    }

    if not SNIPPET_ENABLE_LLM_FACE_VERIFY:
        if SNIPPET_FACE_MODE == "precision":
            logger.debug("face_verification_rejected reason=verification_disabled_precision_mode")
            return default_reject
        return {
            "label": "face",
            "confidence": 1.0,
            "reason": "llm_verification_disabled",
            "occlusion": "unknown",
            "frontalness": "unknown",
        }

    client = _get_openrouter_client()
    if client is None:
        logger.warning("Face verification skipped: OPENROUTER_API_KEY not configured")
        return default_reject

    crop_b64 = base64.b64encode(face_bytes).decode("utf-8")
    crop_image_part = {
        "type": "image_url",
        "image_url": {"url": f"data:image/jpeg;base64,{crop_b64}"},
    }

    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": "Candidate crop image (primary evidence).",
        },
        crop_image_part,
    ]

    if frame_bytes:
        frame_b64 = base64.b64encode(frame_bytes).decode("utf-8")
        content.extend(
            [
                {
                    "type": "text",
                    "text": "Full-frame context image (secondary evidence).",
                },
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{frame_b64}"},
                },
            ]
        )

    if bbox:
        content.append(
            {
                "type": "text",
                "text": f"Detector bbox metadata: {json.dumps(bbox)}",
            }
        )

    content.append({"type": "text", "text": FACE_VERIFICATION_PROMPT})

    try:
        response = client.chat.completions.create(
            model=SNIPPET_FACE_VERIFY_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": content,
                }
            ],
            response_format={"type": "json_object"},
            extra_body=FACE_VERIFICATION_REASONING_CONFIG,
        )
        parsed = _extract_response_json(response)
        if not isinstance(parsed, dict):
            return {
                **default_reject,
                "reason": "invalid_verification_response",
            }
        return {
            "label": str(parsed.get("label", "not_person")),
            "confidence": float(parsed.get("confidence", 0.0) or 0.0),
            "reason": str(parsed.get("reason", ""))[:300],
            "occlusion": str(parsed.get("occlusion", "unknown")),
            "frontalness": str(parsed.get("frontalness", "unknown")),
            "model": SNIPPET_FACE_VERIFY_MODEL,
        }
    except Exception as exc:
        logger.warning("Face verification request failed: %s", str(exc))
        return {
            **default_reject,
            "reason": "verification_failed",
        }


def _verification_accepts_face(verification: dict[str, Any]) -> tuple[bool, str]:
    label = str(verification.get("label", "")).strip().lower()
    confidence = float(verification.get("confidence") or 0.0)
    if label != "face":
        return False, f"label_{label or 'missing'}"
    if confidence < SNIPPET_LLM_FACE_MIN_CONF:
        return False, "verification_conf_too_low"
    return True, "ok"


def _should_recover_context_face(
    verification: dict[str, Any],
    detector_score: float,
    expected_faces: int,
    accepted_faces: int,
) -> bool:
    if not SNIPPET_ALLOW_CONTEXT_RECOVERY:
        return False
    if expected_faces < 3:
        return False
    if accepted_faces >= expected_faces:
        return False
    if detector_score < SNIPPET_CONTEXT_RECOVERY_MIN_DETECTOR_SCORE:
        return False

    label = str(verification.get("label", "")).strip().lower()
    confidence = float(verification.get("confidence") or 0.0)
    if label == "person_context":
        return confidence >= SNIPPET_CONTEXT_RECOVERY_MIN_CONTEXT_CONF

    if label == "not_person":
        # If the classifier is uncertain this is "not_person" but detector score
        # is strong and we're below expected count, recover it as a face candidate.
        return confidence <= SNIPPET_CONTEXT_RECOVERY_MAX_NOT_PERSON_CONF

    return False


def _extract_response_json(response: Any) -> dict[str, Any] | None:
    if response is None:
        return None

    choices = getattr(response, "choices", None)
    if isinstance(choices, list) and choices:
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None)
        parsed = _parse_json_content(content)
        if parsed is not None:
            return parsed

    if hasattr(response, "model_dump"):
        maybe = response.model_dump()
    else:
        maybe = response

    if not isinstance(maybe, dict):
        return None

    raw_choices = maybe.get("choices")
    if not isinstance(raw_choices, list) or not raw_choices:
        return None

    raw_message = raw_choices[0].get("message") if isinstance(raw_choices[0], dict) else None
    if not isinstance(raw_message, dict):
        return None

    return _parse_json_content(raw_message.get("content"))


def _parse_json_content(content: Any) -> dict[str, Any] | None:
    if isinstance(content, str):
        text = content.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return None

    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text" and isinstance(item.get("text"), str):
                    text_parts.append(item["text"])
                continue

            item_type = getattr(item, "type", None)
            item_text = getattr(item, "text", None)
            if item_type == "text" and isinstance(item_text, str):
                text_parts.append(item_text)

        if text_parts:
            joined = "\n".join(part for part in text_parts if part).strip()
            if not joined:
                return None
            try:
                parsed = json.loads(joined)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                return None

    return None
