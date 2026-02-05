from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


def clamp(value: float, min_value: float = 0.0, max_value: float = 1.0) -> float:
    return max(min_value, min(max_value, value))


def linear(t: float) -> float:
    return t


def ease_in(t: float) -> float:
    return t * t


def ease_out(t: float) -> float:
    return 1 - (1 - t) * (1 - t)


def ease_in_out(t: float) -> float:
    if t < 0.5:
        return 2 * t * t
    return 1 - ((-2 * t + 2) ** 2) / 2


def ease_in_out_cubic(t: float) -> float:
    if t < 0.5:
        return 4 * t * t * t
    return 1 - ((-2 * t + 2) ** 3) / 2


def ease_out_bounce(t: float) -> float:
    n1 = 7.5625
    d1 = 2.75
    if t < 1 / d1:
        return n1 * t * t
    if t < 2 / d1:
        t -= 1.5 / d1
        return n1 * t * t + 0.75
    if t < 2.5 / d1:
        t -= 2.25 / d1
        return n1 * t * t + 0.9375
    t -= 2.625 / d1
    return n1 * t * t + 0.984375


def ease_out_elastic(t: float) -> float:
    if t == 0 or t == 1:
        return t
    c4 = (2 * 3.141592653589793) / 3
    return 2 ** (-10 * t) * ((t * 10 - 0.75) * c4) + 1


EASING_FUNCTIONS: dict[str, Callable[[float], float]] = {
    "linear": linear,
    "ease_in": ease_in,
    "ease_out": ease_out,
    "ease_in_out": ease_in_out,
    "ease_in_out_cubic": ease_in_out_cubic,
    "bounce": ease_out_bounce,
    "elastic": ease_out_elastic,
}


def resolve_easing(name: str | None) -> Callable[[float], float]:
    if not name:
        return linear
    return EASING_FUNCTIONS.get(name, linear)


def ease(name: str | None, t: float) -> float:
    return resolve_easing(name)(clamp(t))


def progress_for_time(
    time_s: float,
    start_s: float,
    duration_s: float,
    easing: str | None = None,
) -> float:
    if duration_s <= 0:
        return 1.0 if time_s >= start_s else 0.0
    raw = (time_s - start_s) / duration_s
    return ease(easing, raw)


def interpolate(
    start: float,
    end: float,
    t: float,
    easing: str | None = None,
) -> float:
    return start + (end - start) * ease(easing, t)


@dataclass(frozen=True)
class Keyframe:
    time: float
    value: float
    easing: str | None = None


def interpolate_keyframes(keyframes: list[Keyframe], time_s: float) -> float:
    if not keyframes:
        return 0.0
    if len(keyframes) == 1:
        return keyframes[0].value

    keyframes = sorted(keyframes, key=lambda k: k.time)
    if time_s <= keyframes[0].time:
        return keyframes[0].value
    if time_s >= keyframes[-1].time:
        return keyframes[-1].value

    for idx in range(1, len(keyframes)):
        prev = keyframes[idx - 1]
        curr = keyframes[idx]
        if time_s <= curr.time:
            local_t = (time_s - prev.time) / max(1e-6, curr.time - prev.time)
            return interpolate(prev.value, curr.value, local_t, curr.easing or prev.easing)

    return keyframes[-1].value
