from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cairo
from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageFont

from animation_engine import clamp, ease, progress_for_time


@dataclass(frozen=True)
class OverlayAsset:
    path: str
    fps: float
    frame_count: int
    duration: float
    is_sequence: bool
    start_number: int = 1


@dataclass
class Layer:
    image: Image.Image
    x: float
    y: float
    opacity: float = 1.0
    scale: float = 1.0


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_alpha(value: str) -> tuple[str, float | None]:
    if "@" not in value:
        return value, None
    base, alpha_raw = value.rsplit("@", 1)
    try:
        alpha = float(alpha_raw)
    except ValueError:
        return value, None
    return base, clamp(alpha)


def parse_color(value: Any, default: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    if value is None:
        return default
    if isinstance(value, (list, tuple)):
        if len(value) == 4:
            return tuple(int(v) for v in value)  # type: ignore[return-value]
        if len(value) == 3:
            return (int(value[0]), int(value[1]), int(value[2]), default[3])
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return default
        if raw.lower() in {"transparent", "none", "clear"}:
            return (0, 0, 0, 0)
        base, alpha = _parse_alpha(raw)
        if base.startswith("#") and len(base) == 9:
            rgb = ImageColor.getrgb(base[:7])
            alpha = int(base[7:9], 16) / 255.0
            return (rgb[0], rgb[1], rgb[2], int(alpha * 255))
        rgb = ImageColor.getrgb(base)
        if alpha is None:
            return (rgb[0], rgb[1], rgb[2], default[3])
        return (rgb[0], rgb[1], rgb[2], int(alpha * 255))
    return default


def apply_opacity(image: Image.Image, opacity: float) -> Image.Image:
    opacity = clamp(opacity)
    if opacity >= 0.999:
        return image
    alpha = image.getchannel("A")
    alpha = alpha.point(lambda value: int(value * opacity))
    image.putalpha(alpha)
    return image


def resolve_length(value: Any, max_value: int) -> float | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        try:
            numeric = float(stripped)
        except ValueError:
            return None
    else:
        numeric = _safe_float(value, 0.0)
    if 0.0 <= numeric <= 1.0:
        return numeric * max_value
    return numeric


def render_linear_gradient(
    size: tuple[int, int],
    start_color: tuple[int, int, int, int],
    end_color: tuple[int, int, int, int],
    angle_deg: float,
) -> Image.Image:
    width, height = size
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    ctx = cairo.Context(surface)
    angle = math.radians(angle_deg)
    half_w = width / 2
    half_h = height / 2
    x0 = half_w - math.cos(angle) * half_w
    y0 = half_h - math.sin(angle) * half_h
    x1 = half_w + math.cos(angle) * half_w
    y1 = half_h + math.sin(angle) * half_h
    grad = cairo.LinearGradient(x0, y0, x1, y1)
    sr, sg, sb, sa = (c / 255.0 for c in start_color)
    er, eg, eb, ea = (c / 255.0 for c in end_color)
    grad.add_color_stop_rgba(0, sr, sg, sb, sa)
    grad.add_color_stop_rgba(1, er, eg, eb, ea)
    ctx.rectangle(0, 0, width, height)
    ctx.set_source(grad)
    ctx.fill()
    buf = surface.get_data()
    image = Image.frombuffer("RGBA", (width, height), buf, "raw", "BGRA", 0, 1)
    return image.copy()


def _load_font(font: Any, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if isinstance(font, str) and font:
        try:
            return ImageFont.truetype(font, size)
        except OSError:
            pass
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _text_bbox(
    text: str,
    font: ImageFont.ImageFont,
    spacing: int,
    align: str,
    stroke_width: int,
) -> tuple[int, int]:
    dummy = Image.new("RGBA", (2, 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(dummy)
    bbox = draw.multiline_textbbox(
        (0, 0),
        text,
        font=font,
        spacing=spacing,
        align=align,
        stroke_width=stroke_width,
    )
    return (bbox[2] - bbox[0], bbox[3] - bbox[1])


def _wrap_text(text: str, font: ImageFont.ImageFont, max_width: int, spacing: int) -> str:
    if not text:
        return ""
    if max_width <= 0:
        return text
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        words = paragraph.split(" ")
        if not words:
            lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            test_line = f"{current} {word}".strip()
            width, _ = _text_bbox(test_line, font, spacing, "left", 0)
            if width <= max_width:
                current = test_line
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return "\n".join(lines)


def _build_text_layer(
    text: str,
    font: ImageFont.ImageFont,
    color: tuple[int, int, int, int],
    align: str,
    spacing: int,
    outline_width: int,
    outline_color: tuple[int, int, int, int],
    shadow_color: tuple[int, int, int, int] | None,
    shadow_offset: tuple[int, int],
    shadow_blur: int,
    gradient: dict[str, Any] | None,
) -> Image.Image:
    text_width, text_height = _text_bbox(text, font, spacing, align, outline_width)
    pad = max(outline_width, shadow_blur) + max(abs(shadow_offset[0]), abs(shadow_offset[1]))
    width = max(1, text_width + pad * 2)
    height = max(1, text_height + pad * 2)
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    if shadow_color is not None and shadow_color[3] > 0:
        shadow_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow_layer)
        shadow_draw.multiline_text(
            (pad + shadow_offset[0], pad + shadow_offset[1]),
            text,
            font=font,
            fill=shadow_color,
            spacing=spacing,
            align=align,
        )
        if shadow_blur > 0:
            shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(shadow_blur))
        layer.alpha_composite(shadow_layer)

    if gradient:
        mask = Image.new("L", (text_width, text_height), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.multiline_text(
            (0, 0),
            text,
            font=font,
            fill=255,
            spacing=spacing,
            align=align,
        )
        start_color = parse_color(
            gradient.get("start_color") or gradient.get("start"),
            color,
        )
        end_color = parse_color(
            gradient.get("end_color") or gradient.get("end"),
            color,
        )
        angle = _safe_float(gradient.get("angle"), 0.0)
        gradient_img = render_linear_gradient((text_width, text_height), start_color, end_color, angle)
        layer.paste(gradient_img, (pad, pad), mask)
        if outline_width > 0:
            draw.multiline_text(
                (pad, pad),
                text,
                font=font,
                fill=(0, 0, 0, 0),
                spacing=spacing,
                align=align,
                stroke_width=outline_width,
                stroke_fill=outline_color,
            )
    else:
        draw.multiline_text(
            (pad, pad),
            text,
            font=font,
            fill=color,
            spacing=spacing,
            align=align,
            stroke_width=outline_width,
            stroke_fill=outline_color,
        )

    return layer


def _draw_rounded_rect(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    radius: int,
    fill: tuple[int, int, int, int] | int | None,
    outline: tuple[int, int, int, int] | int | None,
    width: int,
) -> None:
    if radius > 0 and hasattr(draw, "rounded_rectangle"):
        draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)
    else:
        draw.rectangle(box, fill=fill, outline=outline, width=width)


def _sanitize_label(label: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", label)


class OverlayGenerator:
    def __init__(self, width: int, height: int, fps: float, output_dir: Path):
        self.width = width
        self.height = height
        self.fps = fps
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate(
        self, kind: str, params: dict[str, Any], duration: float, label: str
    ) -> OverlayAsset:
        safe_label = _sanitize_label(label)
        animation = self._parse_animation(params)
        animated = self._is_animated(kind, params, animation)
        frame_count = max(1, int(math.ceil(duration * self.fps)))

        if not animated:
            frame = self._render_frame(kind, params, 0.0, duration, animation)
            output_path = self.output_dir / f"{safe_label}.png"
            frame.save(output_path, "PNG")
            return OverlayAsset(
                path=str(output_path),
                fps=self.fps,
                frame_count=1,
                duration=duration,
                is_sequence=False,
            )

        sequence_dir = self.output_dir / safe_label
        sequence_dir.mkdir(parents=True, exist_ok=True)
        pattern = sequence_dir / "frame_%06d.png"
        for idx in range(frame_count):
            time_s = idx / self.fps
            frame = self._render_frame(kind, params, time_s, duration, animation)
            frame_path = sequence_dir / f"frame_{idx + 1:06d}.png"
            frame.save(frame_path, "PNG")

        return OverlayAsset(
            path=str(pattern),
            fps=self.fps,
            frame_count=frame_count,
            duration=duration,
            is_sequence=True,
            start_number=1,
        )

    def _parse_animation(self, params: dict[str, Any]) -> dict[str, Any]:
        animation = params.get("animation")
        if isinstance(animation, str):
            animation = {"type": animation}
        if not isinstance(animation, dict):
            animation = {}
        animation_type = animation.get("type") or params.get("animation_type") or "none"
        animation["type"] = str(animation_type).lower()
        return animation

    def _is_animated(
        self, kind: str, params: dict[str, Any], animation: dict[str, Any]
    ) -> bool:
        if animation.get("type") not in {"", "none"}:
            return True
        if kind.lower() in {"animated_text"}:
            return True
        if kind.lower() == "progress_bar":
            start = params.get("progress_start")
            end = params.get("progress_end")
            if start is not None or end is not None:
                return True
        return False

    def _render_frame(
        self,
        kind: str,
        params: dict[str, Any],
        time_s: float,
        duration: float,
        animation: dict[str, Any],
    ) -> Image.Image:
        canvas = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        kind_lower = kind.lower()

        if kind_lower in {"caption", "title", "animated_text"}:
            layer = self._render_text_layer(kind_lower, params, time_s, duration, animation)
            if layer:
                self._composite_layer(canvas, layer, time_s, duration, animation)
            return canvas

        if kind_lower == "lower_third":
            layer = self._render_lower_third(params)
            if layer:
                self._composite_layer(canvas, layer, time_s, duration, animation)
            return canvas

        if kind_lower == "watermark":
            layer = self._render_watermark(params)
            if layer:
                self._composite_layer(canvas, layer, time_s, duration, animation)
            return canvas

        if kind_lower == "call_out":
            layer = self._render_call_out(params)
            if layer:
                self._composite_layer(canvas, layer, time_s, duration, animation)
            return canvas

        if kind_lower == "progress_bar":
            layer = self._render_progress_bar(params, time_s, duration, animation)
            if layer:
                self._composite_layer(canvas, layer, time_s, duration, animation)
            return canvas

        if kind_lower == "shape":
            layer = self._render_shape(params)
            if layer:
                self._composite_layer(canvas, layer, time_s, duration, animation)
            return canvas

        return canvas

    def _composite_layer(
        self,
        canvas: Image.Image,
        layer: Layer,
        time_s: float,
        duration: float,
        animation: dict[str, Any],
    ) -> None:
        animated_layer = self._apply_animation(layer, time_s, duration, animation)
        image = animated_layer.image
        if animated_layer.scale != 1.0:
            width = max(1, int(image.width * animated_layer.scale))
            height = max(1, int(image.height * animated_layer.scale))
            image = image.resize((width, height), resample=Image.LANCZOS)
        image = apply_opacity(image, animated_layer.opacity)
        canvas.paste(image, (int(animated_layer.x), int(animated_layer.y)), image)

    def _apply_animation(
        self, layer: Layer, time_s: float, duration: float, animation: dict[str, Any]
    ) -> Layer:
        anim_type = animation.get("type", "none")
        if anim_type in {"", "none"}:
            return layer

        start_ms = _safe_float(animation.get("start_ms"), 0.0)
        duration_ms = _safe_float(animation.get("duration_ms"), 600.0)
        easing = animation.get("easing") or "ease_in_out"
        start_s = start_ms / 1000.0
        anim_duration_s = max(0.0, min(duration, duration_ms / 1000.0))
        progress = progress_for_time(time_s, start_s, anim_duration_s, easing)

        opacity = layer.opacity
        scale = layer.scale
        x = layer.x
        y = layer.y
        distance = _safe_float(animation.get("distance"), 40.0)
        direction = str(animation.get("direction") or "up").lower()

        if anim_type in {"fade_in", "fade"}:
            opacity *= progress
        elif anim_type == "fade_out":
            opacity *= 1.0 - progress
        elif anim_type in {"slide_in", "slide"}:
            if direction == "left":
                x -= distance * (1.0 - progress)
            elif direction == "right":
                x += distance * (1.0 - progress)
            elif direction == "down":
                y += distance * (1.0 - progress)
            else:
                y -= distance * (1.0 - progress)
        elif anim_type == "slide_out":
            if direction == "left":
                x -= distance * progress
            elif direction == "right":
                x += distance * progress
            elif direction == "down":
                y += distance * progress
            else:
                y -= distance * progress
        elif anim_type in {"scale_in", "pop", "morph"}:
            scale *= 0.8 + 0.2 * progress
            opacity *= progress
        elif anim_type == "bounce":
            scale *= 0.8 + 0.2 * ease("bounce", progress)

        return Layer(image=layer.image, x=x, y=y, opacity=opacity, scale=scale)

    def _render_text_layer(
        self,
        kind: str,
        params: dict[str, Any],
        time_s: float,
        duration: float,
        animation: dict[str, Any],
    ) -> Layer | None:
        text = str(params.get("text", ""))
        if not text:
            return None

        base_size = int(max(8, _safe_float(params.get("size"), 48.0)))
        font = _load_font(params.get("font"), base_size)
        align = str(params.get("align") or "center").lower()
        spacing_value = params.get("line_spacing")
        if spacing_value is None:
            spacing = int(round(base_size * 0.2))
        else:
            spacing = int(round(base_size * max(0.0, float(spacing_value) - 1.0)))
        max_width = resolve_length(params.get("max_width"), self.width)
        if max_width:
            text = _wrap_text(text, font, int(max_width), spacing)

        anim_type = animation.get("type")
        if kind == "animated_text" and anim_type in {"", "none"}:
            anim_type = "typewriter"

        if anim_type == "typewriter":
            start_s = _safe_float(animation.get("start_ms"), 0.0) / 1000.0
            duration_ms = _safe_float(animation.get("duration_ms"), 800.0)
            anim_duration = max(0.1, min(duration, duration_ms / 1000.0))
            progress = progress_for_time(time_s, start_s, anim_duration, animation.get("easing"))
            visible_count = max(0, int(round(len(text) * progress)))
            text = text[:visible_count]
        elif anim_type == "fade_words":
            words = text.split()
            if words:
                start_s = _safe_float(animation.get("start_ms"), 0.0) / 1000.0
                duration_ms = _safe_float(animation.get("duration_ms"), 800.0)
                anim_duration = max(0.1, min(duration, duration_ms / 1000.0))
                progress = progress_for_time(time_s, start_s, anim_duration, animation.get("easing"))
                visible_words = max(0, int(round(len(words) * progress)))
                text = " ".join(words[:visible_words])

        if not text:
            return None

        color = parse_color(params.get("color"), (255, 255, 255, 255))
        outline_color = parse_color(params.get("outline_color"), (0, 0, 0, 255))
        outline_width = int(max(0, _safe_float(params.get("outline_width"), 0.0)))
        shadow_color = params.get("shadow_color")
        shadow = (
            parse_color(shadow_color, (0, 0, 0, 0)) if shadow_color is not None else None
        )
        shadow_offset = (
            int(_safe_float(params.get("shadow_offset_x"), 2.0)),
            int(_safe_float(params.get("shadow_offset_y"), 2.0)),
        )
        shadow_blur = int(max(0, _safe_float(params.get("shadow_blur"), 4.0)))
        gradient = params.get("text_gradient") or params.get("gradient")
        if not isinstance(gradient, dict):
            gradient = None

        text_layer = _build_text_layer(
            text=text,
            font=font,
            color=color,
            align=align,
            spacing=spacing,
            outline_width=outline_width,
            outline_color=outline_color,
            shadow_color=shadow,
            shadow_offset=shadow_offset,
            shadow_blur=shadow_blur,
            gradient=gradient,
        )

        padding = int(max(0, _safe_float(params.get("bg_padding"), 0.0)))
        bg_color = params.get("bg_color")
        bg_radius = int(max(0, _safe_float(params.get("bg_radius"), 12.0)))
        if bg_color:
            bg_layer = Image.new("RGBA", (text_layer.width + padding * 2, text_layer.height + padding * 2), (0, 0, 0, 0))
            draw = ImageDraw.Draw(bg_layer)
            _draw_rounded_rect(
                draw,
                (0, 0, bg_layer.width, bg_layer.height),
                bg_radius,
                parse_color(bg_color, (0, 0, 0, 160)),
                None,
                0,
            )
            bg_layer.paste(text_layer, (padding, padding), text_layer)
            text_layer = bg_layer

        opacity = _safe_float(params.get("opacity"), 1.0)
        x_raw = params.get("x")
        y_raw = params.get("y")
        x = resolve_length(x_raw, self.width)
        y = resolve_length(y_raw, self.height)
        margin = int(max(0, _safe_float(params.get("margin"), 40.0)))
        if isinstance(x_raw, str):
            x_key = x_raw.strip().lower()
            if x_key == "left":
                x = float(margin)
            elif x_key == "right":
                x = float(self.width - text_layer.width - margin)
            elif x_key in {"center", "middle"}:
                x = float((self.width - text_layer.width) / 2)
        if isinstance(y_raw, str):
            y_key = y_raw.strip().lower()
            if y_key == "top":
                y = float(margin)
            elif y_key == "bottom":
                y = float(self.height - text_layer.height - margin)
            elif y_key in {"center", "middle"}:
                y = float((self.height - text_layer.height) / 2)
        if x is None:
            x = (self.width - text_layer.width) / 2
        if y is None:
            if kind == "caption":
                y = self.height - text_layer.height - margin
            else:
                y = (self.height - text_layer.height) / 2
        return Layer(image=text_layer, x=x, y=y, opacity=opacity)

    def _render_lower_third(self, params: dict[str, Any]) -> Layer | None:
        name = str(params.get("name", "")).strip()
        title = str(params.get("title", "")).strip()
        if not name and not title:
            return None
        name_size = int(max(8, _safe_float(params.get("name_size"), 42.0)))
        title_size = int(max(8, _safe_float(params.get("title_size"), 28.0)))
        name_font = _load_font(params.get("font"), name_size)
        title_font = _load_font(params.get("font"), title_size)
        padding = int(max(0, _safe_float(params.get("padding"), 24.0)))
        spacing = int(max(0, _safe_float(params.get("line_spacing"), 8.0)))
        name_color = parse_color(params.get("name_color"), (255, 255, 255, 255))
        title_color = parse_color(params.get("title_color"), (220, 220, 220, 255))
        bg_color = parse_color(params.get("bg_color"), (0, 0, 0, 180))
        accent_color = parse_color(params.get("accent_color"), (0, 173, 239, 255))

        name_w, name_h = _text_bbox(name, name_font, spacing, "left", 0)
        title_w, title_h = _text_bbox(title, title_font, spacing, "left", 0)
        text_w = max(name_w, title_w)
        text_h = name_h + (spacing if title else 0) + title_h
        bar_height = int(max(text_h + padding * 2, _safe_float(params.get("bar_height"), text_h + padding * 2)))
        bar_width = int(max(text_w + padding * 2 + 8, _safe_float(params.get("bar_width"), text_w + padding * 2)))
        radius = int(max(0, _safe_float(params.get("radius"), 12.0)))

        bar = Image.new("RGBA", (bar_width, bar_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(bar)
        _draw_rounded_rect(draw, (0, 0, bar_width, bar_height), radius, bg_color, None, 0)
        accent_width = int(max(4, _safe_float(params.get("accent_width"), 6.0)))
        draw.rectangle((0, 0, accent_width, bar_height), fill=accent_color)
        text_x = padding + accent_width
        text_y = (bar_height - text_h) / 2
        if name:
            draw.text((text_x, text_y), name, font=name_font, fill=name_color)
            text_y += name_h + spacing
        if title:
            draw.text((text_x, text_y), title, font=title_font, fill=title_color)

        x = resolve_length(params.get("x"), self.width)
        y = resolve_length(params.get("y"), self.height)
        margin = int(max(0, _safe_float(params.get("margin"), 40.0)))
        if x is None:
            x = margin
        if y is None:
            y = self.height - bar_height - margin
        opacity = _safe_float(params.get("opacity"), 1.0)
        return Layer(image=bar, x=x, y=y, opacity=opacity)

    def _render_watermark(self, params: dict[str, Any]) -> Layer | None:
        image_path = params.get("image_path") or params.get("path")
        if not image_path:
            return None
        try:
            overlay = Image.open(image_path).convert("RGBA")
        except OSError:
            return None
        scale = _safe_float(params.get("scale"), 0.2)
        width = params.get("width")
        height = params.get("height")
        if width or height:
            target_w = int(resolve_length(width, self.width) or overlay.width)
            target_h = int(resolve_length(height, self.height) or overlay.height)
            overlay = overlay.resize((target_w, target_h), resample=Image.LANCZOS)
        else:
            if scale <= 0:
                scale = 0.2
            overlay = overlay.resize(
                (
                    max(1, int(overlay.width * scale)),
                    max(1, int(overlay.height * scale)),
                ),
                resample=Image.LANCZOS,
            )
        opacity = _safe_float(params.get("opacity"), 0.6)
        overlay = apply_opacity(overlay, opacity)

        position = str(params.get("position") or "bottom_right").lower()
        margin = int(max(0, _safe_float(params.get("margin"), 32.0)))
        x = resolve_length(params.get("x"), self.width)
        y = resolve_length(params.get("y"), self.height)
        if x is None or y is None:
            if position == "top_left":
                x = margin
                y = margin
            elif position == "top_right":
                x = self.width - overlay.width - margin
                y = margin
            elif position == "bottom_left":
                x = margin
                y = self.height - overlay.height - margin
            elif position == "center":
                x = (self.width - overlay.width) / 2
                y = (self.height - overlay.height) / 2
            else:
                x = self.width - overlay.width - margin
                y = self.height - overlay.height - margin
        return Layer(image=overlay, x=float(x), y=float(y), opacity=1.0)

    def _render_call_out(self, params: dict[str, Any]) -> Layer | None:
        text = str(params.get("text", "")).strip()
        if not text:
            return None
        box_w = int(max(80, _safe_float(params.get("box_width"), 360.0)))
        box_h = int(max(60, _safe_float(params.get("box_height"), 120.0)))
        box_x = resolve_length(params.get("box_x"), self.width)
        box_y = resolve_length(params.get("box_y"), self.height)
        if box_x is None:
            box_x = 80.0
        if box_y is None:
            box_y = 80.0
        box_color = parse_color(params.get("box_color"), (0, 0, 0, 200))
        text_color = parse_color(params.get("color"), (255, 255, 255, 255))
        font = _load_font(params.get("font"), int(max(8, _safe_float(params.get("size"), 32.0))))
        radius = int(max(0, _safe_float(params.get("radius"), 12.0)))
        line_color = parse_color(params.get("line_color"), (255, 255, 255, 255))
        line_width = int(max(1, _safe_float(params.get("line_width"), 3.0)))
        target_x = resolve_length(params.get("target_x"), self.width)
        target_y = resolve_length(params.get("target_y"), self.height)
        if target_x is None:
            target_x = box_x + box_w + 40
        if target_y is None:
            target_y = box_y + box_h / 2

        layer = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        _draw_rounded_rect(
            draw,
            (int(box_x), int(box_y), int(box_x + box_w), int(box_y + box_h)),
            radius,
            box_color,
            None,
            0,
        )
        draw.line(
            (box_x + box_w / 2, box_y + box_h / 2, target_x, target_y),
            fill=line_color,
            width=line_width,
        )
        arrow_size = int(max(0, _safe_float(params.get("arrow_size"), 10.0)))
        if arrow_size > 0:
            angle = math.atan2(target_y - (box_y + box_h / 2), target_x - (box_x + box_w / 2))
            arrow_angle = math.pi / 8
            p1 = (
                target_x - arrow_size * math.cos(angle - arrow_angle),
                target_y - arrow_size * math.sin(angle - arrow_angle),
            )
            p2 = (
                target_x - arrow_size * math.cos(angle + arrow_angle),
                target_y - arrow_size * math.sin(angle + arrow_angle),
            )
            draw.polygon([p1, p2, (target_x, target_y)], fill=line_color)

        padding = int(max(0, _safe_float(params.get("padding"), 16.0)))
        text_area_w = box_w - padding * 2
        text_area_h = box_h - padding * 2
        spacing = int(max(0, _safe_float(params.get("line_spacing"), 6.0)))
        text = _wrap_text(text, font, text_area_w, spacing)
        draw.multiline_text(
            (box_x + padding, box_y + padding),
            text,
            font=font,
            fill=text_color,
            spacing=spacing,
        )
        opacity = _safe_float(params.get("opacity"), 1.0)
        return Layer(image=layer, x=0, y=0, opacity=opacity)

    def _render_progress_bar(
        self,
        params: dict[str, Any],
        time_s: float,
        duration: float,
        animation: dict[str, Any],
    ) -> Layer | None:
        width = int(max(10, _safe_float(params.get("width"), 600.0)))
        height = int(max(4, _safe_float(params.get("height"), 16.0)))
        x = resolve_length(params.get("x"), self.width)
        y = resolve_length(params.get("y"), self.height)
        if x is None:
            x = (self.width - width) / 2
        if y is None:
            y = self.height - height - 40
        bg_color = parse_color(params.get("bg_color"), (255, 255, 255, 64))
        fg_color = parse_color(params.get("fg_color"), (255, 255, 255, 220))
        border_color = params.get("border_color")
        border = parse_color(border_color, (255, 255, 255, 255)) if border_color else None
        border_width = int(max(0, _safe_float(params.get("border_width"), 0.0)))
        radius = int(max(0, _safe_float(params.get("radius"), height / 2)))
        progress_value = _safe_float(params.get("progress"), 1.0)
        progress_start = params.get("progress_start")
        progress_end = params.get("progress_end")
        if progress_start is not None or progress_end is not None:
            start_value = _safe_float(progress_start, 0.0)
            end_value = _safe_float(progress_end, 1.0)
            anim_progress = progress_for_time(
                time_s,
                _safe_float(animation.get("start_ms"), 0.0) / 1000.0,
                max(0.1, _safe_float(animation.get("duration_ms"), duration * 1000.0) / 1000.0),
                animation.get("easing"),
            )
            progress_value = start_value + (end_value - start_value) * anim_progress
        progress_value = clamp(progress_value)

        bar = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(bar)
        _draw_rounded_rect(draw, (0, 0, width, height), radius, bg_color, None, 0)
        fill_width = int(round(width * progress_value))
        if fill_width > 0:
            _draw_rounded_rect(
                draw,
                (0, 0, fill_width, height),
                radius,
                fg_color,
                None,
                0,
            )
        if border and border_width > 0:
            _draw_rounded_rect(
                draw,
                (0, 0, width, height),
                radius,
                None,
                border,
                border_width,
            )
        opacity = _safe_float(params.get("opacity"), 1.0)
        return Layer(image=bar, x=float(x), y=float(y), opacity=opacity)

    def _render_shape(self, params: dict[str, Any]) -> Layer | None:
        shape = str(params.get("shape") or "rect").lower()
        width = int(max(1, _safe_float(params.get("width"), 200.0)))
        height = int(max(1, _safe_float(params.get("height"), 100.0)))
        x = resolve_length(params.get("x"), self.width) or 0.0
        y = resolve_length(params.get("y"), self.height) or 0.0
        color = parse_color(params.get("color"), (255, 255, 255, 180))
        stroke_color = params.get("stroke_color")
        stroke = parse_color(stroke_color, (255, 255, 255, 255)) if stroke_color else None
        stroke_width = int(max(0, _safe_float(params.get("stroke_width"), 0.0)))
        radius = int(max(0, _safe_float(params.get("radius"), 12.0)))
        gradient = params.get("gradient")
        layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)

        if isinstance(gradient, dict):
            start_color = parse_color(gradient.get("start"), color)
            end_color = parse_color(gradient.get("end"), color)
            angle = _safe_float(gradient.get("angle"), 0.0)
            gradient_img = render_linear_gradient((width, height), start_color, end_color, angle)
            mask = Image.new("L", (width, height), 0)
            mask_draw = ImageDraw.Draw(mask)
            if shape in {"circle", "ellipse"}:
                mask_draw.ellipse((0, 0, width, height), fill=255)
            elif shape in {"rounded_rect", "roundrect"}:
                _draw_rounded_rect(mask_draw, (0, 0, width, height), radius, 255, None, 0)
            else:
                mask_draw.rectangle((0, 0, width, height), fill=255)
            layer.paste(gradient_img, (0, 0), mask)
            if stroke and stroke_width > 0:
                if shape in {"circle", "ellipse"}:
                    draw.ellipse((0, 0, width, height), outline=stroke, width=stroke_width)
                elif shape in {"rounded_rect", "roundrect"}:
                    _draw_rounded_rect(
                        draw, (0, 0, width, height), radius, None, stroke, stroke_width
                    )
                else:
                    draw.rectangle((0, 0, width, height), outline=stroke, width=stroke_width)
        else:
            if shape in {"circle", "ellipse"}:
                draw.ellipse((0, 0, width, height), fill=color, outline=stroke, width=stroke_width)
            elif shape in {"rounded_rect", "roundrect"}:
                _draw_rounded_rect(draw, (0, 0, width, height), radius, color, stroke, stroke_width)
            elif shape == "line":
                draw.line((0, height / 2, width, height / 2), fill=color, width=max(1, stroke_width or 4))
            elif shape == "arrow":
                draw.line((0, height / 2, width, height / 2), fill=color, width=max(1, stroke_width or 4))
                arrow_size = int(max(6, _safe_float(params.get("arrow_size"), 12.0)))
                draw.polygon(
                    [
                        (width, height / 2),
                        (width - arrow_size, height / 2 - arrow_size / 2),
                        (width - arrow_size, height / 2 + arrow_size / 2),
                    ],
                    fill=color,
                )
            else:
                draw.rectangle((0, 0, width, height), fill=color, outline=stroke, width=stroke_width)

        opacity = _safe_float(params.get("opacity"), 1.0)
        return Layer(image=layer, x=float(x), y=float(y), opacity=opacity)
