"""Bounded screen-coordinate raster layers for the editor's saved annotations."""
from contextlib import contextmanager
import math
import re
from pathlib import Path
import tempfile
import unicodedata

import cv2
import numpy as np

from .media import probe


def number(value, default=0.0):
    value = float(default if value is None else value)
    if not math.isfinite(value):
        raise ValueError("Annotation contains a non-finite value")
    return value


def rgba(value, opacity=1.0):
    if value in (None, "none"):
        return (0, 0, 0, 0)
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", value):
        raise ValueError("Annotation color must be a hexadecimal RGB/RGBA color")
    alpha = int(value[7:9], 16) if len(value) == 9 else 255
    return (int(value[5:7], 16), int(value[3:5], 16), int(value[1:3], 16),
            round(alpha * min(1, max(0, number(opacity, 1)))))


def raster_shape(shape, width, height):
    if shape.get("mode", "screen") != "screen":
        raise ValueError("Tracked/field annotations cannot yet be exported")
    layer = np.zeros((height, width, 4), dtype=np.uint8)
    def point(x, y):
        return (round(min(1, max(0, number(x))) * (width - 1)),
                round(min(1, max(0, number(y))) * (height - 1)))
    a = point(shape.get("x1", 0), shape.get("y1", 0))
    b = point(shape.get("x2", 0), shape.get("y2", 0))
    stroke = rgba(shape.get("color", "#ffdf36"), shape.get("opacity", 1))
    fill = rgba(shape.get("fill", "none"), shape.get("opacity", 1))
    thickness = max(1, round(min(30, max(1, number(shape.get("lineWidth"), 5))) * width / 1000))
    kind = shape.get("type")
    if kind in {"pen", "freehand", "player-trail", "polygon"}:
        points = shape.get("points") or []
        if len(points) > 4096:
            raise ValueError("Too many annotation points")
        points = np.array([point(*p) for p in points], dtype=np.int32)
        if len(points) > 1:
            if kind == "polygon" and len(points) > 2 and fill[3]:
                cv2.fillPoly(layer, [points], fill, lineType=cv2.LINE_AA)
            cv2.polylines(layer, [points], kind == "polygon", stroke, thickness, cv2.LINE_AA)
    elif kind == "arrow":
        cv2.arrowedLine(layer, a, b, stroke, thickness, cv2.LINE_AA, tipLength=.08)
    elif kind == "line":
        cv2.line(layer, a, b, stroke, thickness, cv2.LINE_AA)
    elif kind == "rectangle":
        if fill[3]: cv2.rectangle(layer, a, b, fill, -1)
        cv2.rectangle(layer, a, b, stroke, thickness, cv2.LINE_AA)
    elif kind in {"text", "player-label"}:
        draw_text(layer, shape, a, width, stroke)
    elif kind in {"circle", "ellipse", "spotlight"}:
        center = ((a[0] + b[0]) // 2, (a[1] + b[1]) // 2)
        axes = (abs(a[0] - b[0]) // 2, abs(a[1] - b[1]) // 2)
        if fill[3]: cv2.ellipse(layer, center, axes, 0, 0, 360, fill, -1, cv2.LINE_AA)
        cv2.ellipse(layer, center, axes, 0, 0, 360, stroke, thickness, cv2.LINE_AA)
    else:
        raise ValueError(f"Unsupported annotation shape: {kind}")
    return layer


# Accent marks drawn by hand: OpenCV's Hershey fonts only contain ASCII glyphs.
_MARKS = {"\u0301": "acute", "\u0300": "grave", "\u030c": "caron", "\u0302": "circumflex", "\u030a": "ring",
          "\u0308": "diaeresis", "\u0303": "tilde", "\u030b": "double_acute", "\u0327": "cedilla", "\u0328": "ogonek"}
_SPECIAL = {"ß": "ss", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D", "ł": "l", "Ł": "L",
            "\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-", "\u2026": "..."}


def _glyphs(text):
    """Split text into (ascii_base, [mark, ...]) pairs; unknown characters become '?'."""
    out = []
    for char in text:
        if char == "\u00b0":  # degree sign: a raised ring
            out.append(("o", ["degree"]))
            continue
        char = _SPECIAL.get(char, char)
        decomposed = unicodedata.normalize("NFD", char)
        base = "".join(c for c in decomposed if not unicodedata.combining(c))
        marks = [_MARKS[c] for c in decomposed if c in _MARKS]
        base = base if base.isascii() and base.isprintable() else "?"
        out.append((base, marks))
    return out


def _advances(glyphs, font, scale):
    """Per-glyph advances from cumulative widths (getTextSize pads every call by the thickness)."""
    text, widths = "", [0]
    for base, _ in glyphs:
        text += base
        widths.append(cv2.getTextSize(text, font, scale, 1)[0][0])
    return [b - a for a, b in zip(widths, widths[1:])]


def _text_width(glyphs, font, scale, thickness):
    return sum(_advances(glyphs, font, scale)) + thickness


def _put_marks(layer, marks, base, left, baseline, advance, scale, font, color, thickness):
    cap = cv2.getTextSize("H", font, scale, 1)[0][1]
    x_height = cv2.getTextSize("x", font, scale, 1)[0][1]
    tall = base.isupper() or base.isdigit() or base in "bdfhklt"
    top = baseline - (cap if tall else x_height)
    cx, gap, w, h = left + advance // 2, max(2, round(cap * .14)), max(2, round(cap * .2)), max(2, round(cap * .22))
    mark_top, mark_bottom = top - gap - h, top - gap
    line = lambda pts: cv2.polylines(layer, [np.array(pts, dtype=np.int32)], False, color, thickness, cv2.LINE_AA)
    for mark in marks:
        if mark == "degree":
            continue
        if mark == "caron" and base in "dtlL":  # Czech ď ť ľ Ľ: apostrophe-like caron beside the letter
            x = left + advance
            line([(x, baseline - cap), (x - w // 2, baseline - cap + h + w // 2)])
        elif mark == "acute": line([(cx - w // 2, mark_bottom), (cx + w // 2, mark_top)])
        elif mark == "grave": line([(cx - w // 2, mark_top), (cx + w // 2, mark_bottom)])
        elif mark == "double_acute":
            for dx in (-w // 2 - 1, w // 2 + 1): line([(cx + dx - w // 3, mark_bottom), (cx + dx + w // 3, mark_top)])
        elif mark == "caron": line([(cx - w, mark_top), (cx, mark_bottom), (cx + w, mark_top)])
        elif mark == "circumflex": line([(cx - w, mark_bottom), (cx, mark_top), (cx + w, mark_bottom)])
        elif mark == "ring": cv2.circle(layer, (cx, (mark_top + mark_bottom) // 2), max(2, h // 2 + 1), color, thickness, cv2.LINE_AA)
        elif mark == "diaeresis":
            for dx in (-w, w): cv2.circle(layer, (cx + dx, (mark_top + mark_bottom) // 2), max(1, thickness // 2 + 1), color, -1, cv2.LINE_AA)
        elif mark == "tilde":
            line([(cx - w - w // 2 + round(k * 3 * w / 6), round((mark_top + mark_bottom) / 2 - math.sin(k * math.pi / 3) * h / 2)) for k in range(7)])
        elif mark in {"cedilla", "ogonek"}:
            line([(cx, baseline), (cx + w // 2, baseline + h // 2), (cx - w // 2, baseline + h)])


def _put_text(layer, glyphs, origin, font, scale, color, thickness):
    x, baseline = origin
    for (base, marks), advance in zip(glyphs, _advances(glyphs, font, scale)):
        if marks == ["degree"]:
            cap = cv2.getTextSize("H", font, scale, 1)[0][1]
            cv2.circle(layer, (x + advance // 2, baseline - cap + cap // 5), max(2, cap // 5), color, thickness, cv2.LINE_AA)
            x += advance
            continue
        cv2.putText(layer, base, (x, baseline), font, scale, color, thickness, cv2.LINE_AA)
        if marks:
            _put_marks(layer, marks, base, x, baseline, advance, scale, font, color, thickness)
        x += advance


def draw_text(layer, shape, origin, width, color):
    """Outlined text with ``origin`` as its top-left corner, sized like the editor.

    The editor measures ``size`` on a 1000-unit-wide canvas. When the editor
    stored a box (``x2``/``y2`` beyond the anchor) the text is shrunk to fit it
    and rotated by ``rotation`` degrees (clockwise) around the box centre, like
    the SVG. Accents are drawn as separate strokes over the ASCII base glyph.
    """
    text = str(shape.get("text") or "")
    if len(text) > 200: raise ValueError("Annotation text is too long")
    glyphs = _glyphs(text.strip())
    if not glyphs: return
    font = cv2.FONT_HERSHEY_DUPLEX
    height = layer.shape[0]
    target = min(400, max(4, number(shape.get("size"), 36))) * width / 1000
    base_height = cv2.getTextSize("H", font, 1, 1)[0][1]
    scale = target * .72 / base_height
    thickness = max(1, round(scale * 2))
    x2 = round(min(1, max(0, number(shape.get("x2"), 0))) * (width - 1))
    y2 = round(min(1, max(0, number(shape.get("y2"), 0))) * (height - 1))
    has_box = x2 > origin[0] + 1 and y2 > origin[1] + 1
    if has_box:  # Hershey glyphs are wider than the editor font: never overflow the box
        measured = _text_width(glyphs, font, scale, thickness)
        if measured > x2 - origin[0]:
            scale *= (x2 - origin[0]) / measured
            thickness = max(1, round(scale * 2))
    x, y = origin[0], origin[1] + round(target * .8)
    outline = thickness + max(2, round(target / 9))
    rotation = number(shape.get("rotation"), 0) % 360
    target_layer = np.zeros_like(layer) if rotation else layer
    _put_text(target_layer, glyphs, (x, y), font, scale, (0, 0, 0, color[3]), outline)
    _put_text(target_layer, glyphs, (x, y), font, scale, color, thickness)
    if rotation:
        if has_box:
            centre = ((origin[0] + x2) / 2, (origin[1] + y2) / 2)
        else:
            centre = (origin[0] + _text_width(glyphs, font, scale, thickness) / 2, origin[1] + target / 2)
        matrix = cv2.getRotationMatrix2D(centre, -rotation, 1)
        rotated = cv2.warpAffine(target_layer, matrix, (layer.shape[1], layer.shape[0]), flags=cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
        np.copyto(layer, rotated, where=rotated[:, :, 3:4] > 0)


def blend(base, layer):
    # PNG needs straight alpha: drawing an opaque mask onto transparent pixels
    # without this conversion creates dark fringes after FFmpeg composition.
    src = layer[:, :, 3:4].astype(np.float32) / 255
    dst = base[:, :, 3:4].astype(np.float32) / 255
    alpha = src + dst * (1 - src)
    colors = layer[:, :, :3] * src + base[:, :, :3] * dst * (1 - src)
    base[:, :, :3] = np.round(colors / np.maximum(alpha, 1e-6)).astype(np.uint8)
    base[:, :, 3:4] = np.round(alpha * 255).astype(np.uint8)


def annotation_freeze(annotation, source, start, end, seconds, time_offset: float = 0, event=None):
    """The pause to insert, as (clip-relative instant, seconds, has_audio).

    The hold anchors to the event timestamp -- the instant the coach tagged --
    so a requested pause appears even when no drawing was saved on the event.
    Without an event the saved drawing frame is the fallback. Either anchor is
    clamped inside the clip: a requested pause must never be dropped silently.
    """
    seconds = number(seconds)
    if not 0 <= seconds <= 10: raise ValueError("Freeze duration must be between 0 and 10 seconds")
    if not seconds: return None
    anchor = number(getattr(event, "timestamp")) if event is not None and getattr(event, "timestamp", None) is not None \
        else number(annotation.timestamp) if annotation is not None and getattr(annotation, "timestamp", None) is not None else None
    if anchor is None: return None
    duration = end - start
    if duration <= 0: raise ValueError("Invalid clip range")
    at = min(max(0.0, anchor - time_offset - start), max(0.0, duration - 0.04))
    has_audio = any(s.get("codec_type") == "audio" for s in probe(Path(source))["streams"])
    return at, seconds, has_audio


@contextmanager
def annotation_layers(annotation, event, source, start, end, output, *, time_offset=0, freeze=None):
    """Yield PNG/time layers; delete only this job's temporary PNGs on all exits."""
    if not annotation or not annotation.shapes:
        yield []
        return
    if annotation.coordinate_mode != "screen":
        raise ValueError("Tracked/field annotations cannot yet be exported")
    if len(annotation.shapes) > 200:
        raise ValueError("Too many annotation shapes")
    info = next(s for s in probe(Path(source))["streams"] if s.get("codec_type") == "video")
    width, height = int(info["width"]), int(info["height"])
    rotation = next((number(s.get("rotation")) for s in info.get("side_data_list", []) if "rotation" in s), 0)
    if abs(rotation) % 180 == 90: width, height = height, width
    if width * height > 4096 * 2304:
        raise ValueError("Annotation export supports video frames up to 4096 x 2304 pixels")
    groups = {}
    for shape in annotation.shapes:
        if shape.get("visible") is False: continue
        first = number(shape.get("start"), annotation.start if annotation.start is not None else event.start if event.start is not None else event.timestamp - 5)
        last = number(shape.get("end"), annotation.end if annotation.end is not None else event.end if event.end is not None else event.timestamp + 5)
        first, last = max(start, first - time_offset), min(end, last - time_offset)
        if last <= first: continue
        if freeze:
            at, duration, _ = freeze
            if not first <= start + at < last: continue
            window = (at, at + duration)
        else:
            window = (first - start, last - start)
        groups.setdefault(window, []).append(shape)
    if len(groups) > 32:
        raise ValueError("Too many distinct annotation time windows")
    with tempfile.TemporaryDirectory(prefix=f"{output.stem}-ink-", dir=output.parent) as directory:
        layers = []
        for i, ((first, last), shapes) in enumerate(groups.items()):
            canvas = np.zeros((height, width, 4), dtype=np.uint8)
            for shape in shapes: blend(canvas, raster_shape(shape, width, height))
            path = Path(directory) / f"layer-{i}.png"
            if not cv2.imwrite(str(path), canvas): raise RuntimeError("Cannot write annotation layer")
            layers.append((path, first, last))
        yield layers
