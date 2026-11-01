"""Plugin overlays: the animated picture a plugin shows over the lyrics
(api.overlay, plugin API 5). The frame is picked from where the song is, so
it pauses, seeks and keeps to the beat with the song without the plugin
sending anything per frame. The picture itself is checked in
plugins.overlay_spec; this only decodes and draws it."""

from __future__ import annotations

import bisect
import collections
import concurrent.futures
import json
import math
import pathlib
import struct
import subprocess
import sys

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QImage, QPainter, QPixmap

from plugin_image_paths import snapshot

MAX_FRAMES = 256
IMAGE_BUDGET = 8 * 1024 * 1024
DECODED_BUDGET = 32 * 1024 * 1024
SCALED_BUDGET = 16 * 1024 * 1024
SCALED_ENTRIES = 256                 # also bound Python/Qt object overhead
MAX_ACTIVE = 8
DECODE_TIMEOUT = 5.0
SHOWN_MAX = 0.9                      # of the window's height, at most
_decoded: dict = {}                  # key -> (frames, delays)
_scaled: collections.OrderedDict = collections.OrderedDict()    # single-frame pixmaps
_failed: set = set()
_pending: dict = {}
_active: dict = {}
_fresh = False                       # a picture landed since the window last asked
_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2,
                                              thread_name_prefix="plugin-image")


def _log(*bits) -> None:
    print("[plugins]", *bits, file=sys.stderr, flush=True)


def image_key(spec):
    return (spec["root"], spec["image"], spec.get("epoch", 0))


def _decode(spec):
    """Off the GUI: snapshot a link-free local file, then let a memory-limited
    child decode those bytes. No plugin path reaches a Qt decoder in the host.
    The trusted worker emits at most 8 MiB plus a bounded header."""
    data = snapshot(spec["image"], spec["root"])
    worker = pathlib.Path(__file__).with_name("plugin_image_worker.py")
    flags = 0x08000000 if sys.platform == "win32" else 0
    with subprocess.Popen([sys.executable, "-I", "-B", str(worker)],
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, creationflags=flags) as proc:
        try:
            out, err = proc.communicate(data, timeout=DECODE_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise ValueError("overlay decoding timed out") from None
    if proc.returncode:
        raise ValueError(err.decode("utf-8", "replace")[:300] or "overlay decoder failed")
    if len(out) < 4 or len(out) > IMAGE_BUDGET + 16384:
        raise ValueError("invalid decoder output length")
    n = struct.unpack("!I", out[:4])[0]
    if not 0 < n < 16380:
        raise ValueError("invalid decoder header")
    meta = json.loads(out[4:4 + n])
    w, h, delays = meta["width"], meta["height"], meta["delays"]
    if (not 0 < w <= 1024 or not 0 < h <= 1024
            or not 0 < len(delays) <= MAX_FRAMES
            or not all(math.isfinite(d) and d > 0 for d in delays)):
        raise ValueError("invalid decoder dimensions or timings")
    stride = w * h * 4
    if stride * len(delays) > IMAGE_BUDGET or len(out) != 4 + n + stride * len(delays):
        raise ValueError("invalid decoder frame bytes")
    pixels = memoryview(out)[4 + n:]
    images = [QImage(bytes(pixels[i * stride:(i + 1) * stride]), w, h,
                     w * 4, QImage.Format.Format_RGBA8888).copy()
              for i in range(len(delays))]
    return images, delays if len(images) > 1 else [1.0]


def _decoded_bytes():
    return sum(im.sizeInBytes() for images, _ in _decoded.values() for im in images)


def _scaled_bytes():
    return sum(pm.width() * pm.height() * 4 for pm in _scaled.values())


def sync(specs):
    """On the GUI plugin tick, including when not painting: keep only active
    resources, reap bounded decode jobs and schedule at most two. Too many
    overlays are omitted, not endlessly evicted/reloaded on every paint."""
    global _active, _fresh
    _active = dict(list({image_key(s): s for s in specs}.items())[:MAX_ACTIVE])
    for key in list(_decoded):
        if key not in _active:
            del _decoded[key]
    _failed.intersection_update(_active)
    for key in list(_scaled):
        if key[0] not in _active:
            del _scaled[key]
    for key, future in list(_pending.items()):
        if not future.done():
            if key not in _active:
                future.cancel()
            continue
        del _pending[key]
        if key not in _active:
            continue
        try:
            result = future.result()
            size = sum(im.sizeInBytes() for im in result[0])
            if size + _decoded_bytes() > DECODED_BUDGET:
                raise ValueError("active overlay decoded-byte budget exhausted")
            _decoded[key] = result
            _fresh = True
        except Exception as exc:
            _failed.add(key)
            _log("overlay", key[1], "could not be read:", exc)
    # Memory use lowered the budgets: let the latest pictures go, said once.
    while _decoded and _decoded_bytes() > DECODED_BUDGET:
        key = next(reversed(_decoded))
        del _decoded[key]
        _failed.add(key)
        _log("overlay", key[1], "left out: over the Memory use budget")
    if _scaled_bytes() > SCALED_BUDGET:
        _scaled.clear()
    for key, spec in _active.items():
        if len(_pending) >= 2:
            break
        if key not in _decoded and key not in _failed and key not in _pending:
            _pending[key] = _pool.submit(_decode, dict(spec))


def budgets(decoded: int, scaled: int) -> None:
    """Memory use's limits for decoded and scaled frames; sync applies them."""
    global DECODED_BUDGET, SCALED_BUDGET
    DECODED_BUDGET, SCALED_BUDGET = decoded, scaled


def take_fresh() -> bool:
    """Whether a picture was decoded since the last ask: the window repaints
    then, paused or not."""
    global _fresh
    got, _fresh = _fresh, False
    return got


BEAT_WINDOW = 8                      # beats either side a steady tempo is fitted over


def _steady(k: int, starts: list[float]) -> tuple[float, float]:
    """A steady grid fitted around beat k: (where beat k falls, beat length),
    a least-squares line through the nearby beats. A median would be steadier
    against one wild beat, but it jumps as the window moves on, and the jumps
    show as the dance lurching."""
    lo, hi = max(0, k - BEAT_WINDOW), min(len(starts), k + BEAT_WINDOW + 1)
    xs, ys = range(lo - k, hi - k), starts[lo:hi]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    g = (sum((x - mx) * (y - my) for x, y in zip(xs, ys))
         / sum((x - mx) ** 2 for x in xs))
    g = max(1e-3, g)
    return my - mx * g, g


def beat_at(pos: float, starts: list[float]) -> float | None:
    """Beats since the song's first, at a steady pace: each beat's gap is not
    stretched to a beat of its own (uneven or live-detected beats would make
    the dance speed up and slow down); a grid fitted around the beat before
    is blended into the one around the beat after, so it never jumps. None
    without two beats."""
    if len(starts) < 2:
        return None
    k = min(len(starts) - 1, max(0, bisect.bisect_right(starts, pos) - 1))
    at, g = _steady(k, starts)
    b = k + (pos - at) / g
    if k + 1 < len(starts) and pos > starts[k]:
        w = min(1.0, (pos - starts[k]) / max(1e-3, starts[k + 1] - starts[k]))
        at2, g2 = _steady(k + 1, starts)
        b += w * (k + 1 + (pos - at2) / g2 - b)
    return b


def phase(pos: float, spec: dict, total: float, starts: list[float],
          tempo: float) -> float:
    """How far through its loop the picture is, 0..1. With beats per loop:
    a fixed bpm if the plugin gave one, else the song's beats, else the
    song's tempo, else its fallback_bpm. Without, its own speed, from the
    song's position all the same."""
    beats = spec.get("beats")
    if beats:
        b = None
        if spec.get("bpm"):
            b = pos * spec["bpm"] / 60.0
        else:
            b = beat_at(pos, starts)
            bpm = tempo or spec.get("fallback_bpm")
            if b is None and bpm:
                b = pos * bpm / 60.0
        if b is not None:
            return ((b + spec.get("offset", 0.0)) / beats) % 1.0
    return (max(0.0, pos) / total) % 1.0 if total > 0 else 0.0


def frame_at(ph: float, ends: list[float]) -> int:
    t = min(max(ph, 0.0), 1.0 - 1e-9) * ends[-1]
    return min(len(ends) - 1, bisect.bisect_right(ends, t))


def _pixmap(spec: dict, image: QImage, index: int, w: int, h: int,
            dpr: float) -> QPixmap:
    # Each admitted overlay owns a share, including room for its current
    # frame. A large static overlay must not evict another one's current
    # frame and cause every following paint to rescale the same images.
    owner = image_key(spec)
    budget = SCALED_BUDGET // MAX_ACTIVE
    entries = max(1, SCALED_ENTRIES // MAX_ACTIVE)
    factor = min(1.0, 2048 / max(w, h), (budget / 4 / max(1, w * h)) ** 0.5)
    w, h = max(1, int(w * factor)), max(1, int(h * factor))
    key = (owner, index, w, h, dpr, spec.get("pixelated", False))
    got = _scaled.get(key)
    if got is None:
        smooth = (Qt.TransformationMode.FastTransformation if spec.get("pixelated")
                  else Qt.TransformationMode.SmoothTransformation)
        mine = [k for k in _scaled if k[0] == owner]
        used = sum(_scaled[k].width() * _scaled[k].height() * 4 for k in mine)
        while mine and (used + w * h * 4 > budget or len(mine) >= entries):
            old = _scaled.pop(mine.pop(0))
            used -= old.width() * old.height() * 4
        got = QPixmap.fromImage(image.scaled(
            w, h, Qt.AspectRatioMode.IgnoreAspectRatio, smooth))
        got.setDevicePixelRatio(dpr)
        _scaled[key] = got
    else:
        _scaled.move_to_end(key)
    return got


def reflected(distance: float, span: float) -> float:
    """Triangle wave: travel to an edge and reflect, even across many hits.
    No integration state, so pauses, seeks and frame drops cannot drift."""
    if span <= 0:
        return 0.0
    return span - abs(distance % (2.0 * span) - span)


def place(spec: dict, fw: int, fh: int, W: int, H: int, pos: float = 0.0) -> QRectF:
    """Where the picture goes: `size` px tall at most (and no wider than half
    the window), `margin` px in from its corner."""
    h = min(float(spec.get("size", 96.0)), H * SHOWN_MAX)
    w = h * fw / max(1, fh)
    if w > W * 0.5:
        w, h = W * 0.5, W * 0.5 * fh / max(1, fw)
    m = float(spec.get("margin", 16.0))
    corner = spec.get("corner", "bottom-right")
    x = m if corner.endswith("left") else W - m - w
    y = m if corner.startswith("top") else H - m - h
    if spec.get("motion") == "dvd":
        # Keep the entire canvas inside the viewport, including on resize
        # and when the requested margin exceeds the available room.
        room_x, room_y = max(0.0, W - w), max(0.0, H - h)
        mx, my = min(m, room_x / 2), min(m, room_y / 2)
        span_x, span_y = room_x - 2 * mx, room_y - 2 * my
        speed = spec.get("speed", 90.0)
        seconds = max(0.0, pos) if math.isfinite(pos) else 0.0
        dx = reflected(seconds * speed * 0.8, span_x)
        dy = reflected(seconds * speed * 0.6, span_y)
        x = mx + (dx if corner.endswith("left") else span_x - dx)
        y = my + (dy if corner.startswith("top") else span_y - dy)
    return QRectF(x, y, w, h)


def paint(p: QPainter, W: int, H: int, specs: list[dict], pos: float,
          starts: list[float], tempo: float) -> None:
    """Every running plugin's overlay, over the lyrics. Never raises: a bad
    picture is logged once and left out."""
    for spec in specs:
        try:
            got = _decoded.get(image_key(spec))
            if got is None:
                continue
            images, delays = got
            order = [i for i in (spec.get("frames") or range(len(images)))
                     if 0 <= i < len(images)] or list(range(len(images)))
            ends, t = [], 0.0
            for i in order:
                t += delays[i]
                ends.append(t)
            idx = order[frame_at(phase(pos, spec, t, starts, tempo), ends)]
            first = images[order[0]]
            r = place(spec, first.width(), first.height(), W, H, pos)
            dpr = p.device().devicePixelRatioF() if p.device() else 1.0
            pm = _pixmap(spec, images[idx], idx, max(1, round(r.width() * dpr)),
                         max(1, round(r.height() * dpr)), dpr)
            p.save()
            p.setOpacity(float(spec.get("opacity", 1.0)))
            if spec.get("mirror"):
                p.translate(r.x() * 2 + r.width(), 0)
                p.scale(-1, 1)
            p.drawPixmap(r, pm, QRectF(pm.rect()))
            p.restore()
        except Exception as e:                           # noqa: BLE001
            key = image_key(spec)
            if key not in _failed:
                _failed.add(key)
                _log("overlay", spec.get("image"), "could not be drawn:", e)
