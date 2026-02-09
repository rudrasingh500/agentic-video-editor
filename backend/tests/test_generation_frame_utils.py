from __future__ import annotations

import pytest

from operators.generation_operator import (
    _normalize_frame_inputs,
    _normalize_frame_repeat_count,
)
from utils.frame_editing import _expand_replace_indices, resolve_frame_indices


def test_normalize_frame_inputs_image_mode_ignores_frame_selection() -> None:
    frame_range, frame_indices = _normalize_frame_inputs(
        mode="image",
        frame_range={"start_frame": 5, "end_frame": 12},
        frame_indices=[1, 2, 3],
    )
    assert frame_range is None
    assert frame_indices is None


def test_normalize_frame_inputs_requires_selection_for_frame_modes() -> None:
    with pytest.raises(ValueError):
        _normalize_frame_inputs(
            mode="replace_frames",
            frame_range=None,
            frame_indices=None,
        )


def test_resolve_frame_indices_combines_range_and_indices() -> None:
    indices = resolve_frame_indices(
        total_frames=20,
        frame_range={"start_frame": 3, "end_frame": 5},
        frame_indices=[0, 4, -1, 30],
    )
    assert indices == [0, 3, 4, 5]


def test_normalize_frame_repeat_count_defaults_to_one_for_frame_modes() -> None:
    assert _normalize_frame_repeat_count(mode="replace_frames", frame_repeat_count=None) == 1


def test_normalize_frame_repeat_count_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        _normalize_frame_repeat_count(mode="insert_frames", frame_repeat_count=0)


def test_expand_replace_indices_applies_repeat_window() -> None:
    expanded = _expand_replace_indices(
        selected_indices=[3],
        total_frames=10,
        frame_repeat_count=4,
    )
    assert expanded == [3, 4, 5, 6]
