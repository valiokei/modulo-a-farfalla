"""Bounded screen-coordinate raster layers for the editor's saved annotations."""
from contextlib import contextmanager
import math
import re
from pathlib import Path
import tempfile

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
    elif kind in {"circle", "ellipse", "spotlight"}:
        center = ((a[0] + b[0]) // 2, (a[1] + b[1]) // 2)
        axes = (abs(a[0] - b[0]) // 2, abs(a[1] - b[1]) // 2)
        if fill[3]: cv2.ellipse(layer, center, axes, 0, 0, 360, fill, -1, cv2.LINE_AA)
        cv2.ellipse(layer, center, axes, 0, 0, 360, stroke, thickness, cv2.LINE_AA)
    else:
        raise ValueError(f"Unsupported annotation shape: {kind}")
    return layer


def blend(base, layer):
    # PNG needs straight alpha: drawing an opaque mask onto transparent pixels
    # without this conversion creates dark fringes after FFmpeg composition.
    src = layer[:, :, 3:4].astype(np.float32) / 255
    dst = base[:, :, 3:4].astype(np.float32) / 255
    alpha = src + dst * (1 - src)
    colors = layer[:, :, :3] * src + base[:, :, :3] * dst * (1 - src)
    base[:, :, :3] = np.round(colors / np.maximum(alpha, 1e-6)).astype(np.uint8)
    base[:, :, 3:4] = np.round(alpha * 255).astype(np.uint8)


def annotation_freeze(annotation, source, start, end, seconds, time_offset=0):
    seconds = number(seconds)
    if not 0 <= seconds <= 10: raise ValueError("Freeze duration must be between 0 and 10 seconds")
    if not seconds or not annotation or not annotation.shapes: return None
    at = number(annotation.timestamp) - time_offset - start
    if not 0 <= at < end - start:
        raise ValueError("The saved drawing frame is outside the exported clip")
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
    if freeze and not groups:
        raise ValueError("No visible drawings at the saved frame; save drawings on a frame inside the event")
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
