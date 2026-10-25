"""Lucide icons for the home page, drawn through QtSvg and kept as pixmaps.

The shapes are Lucide's (ISC; see THIRD_PARTY_NOTICES.md), as the 1.2.0
home design uses them. Each is rendered once per size, colour and pixel ratio.
"""
from __future__ import annotations

from PyQt6.QtCore import QByteArray, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

_P = "path"
SVG: dict[str, list] = {
    "search": [("circle", 'cx="11" cy="11" r="8"'), (_P, "m21 21-4.3-4.3")],
    "home": [(_P, "M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8"),
             (_P, "M3 10a2 2 0 0 1 .709-1.528l7-5.999a2 2 0 0 1 2.582 0l7 5.999"
                  "A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z")],
    "queue": [(_P, "M21 15V6"), (_P, "M18.5 18a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z"),
              (_P, "M12 12H3"), (_P, "M16 6H3"), (_P, "M12 18H3")],
    "chart": [(_P, "M3 3v16a2 2 0 0 0 2 2h16"), (_P, "M18 17V9"), (_P, "M13 17V5"),
              (_P, "M8 17v-3")],
    "clock": [("circle", 'cx="12" cy="12" r="10"'),
              ("polyline", 'points="12 6 12 12 16 14"')],
    "music": [(_P, "M9 18V5l12-2v13"), ("circle", 'cx="6" cy="18" r="3"'),
              ("circle", 'cx="18" cy="16" r="3"')],
    "user": [("circle", 'cx="12" cy="8" r="5"'), (_P, "M20 21a8 8 0 0 0-16 0")],
    "disc": [("circle", 'cx="12" cy="12" r="10"'), ("circle", 'cx="12" cy="12" r="2"')],
    "list": [(_P, "M3 12h.01"), (_P, "M3 18h.01"), (_P, "M3 6h.01"), (_P, "M8 12h13"),
             (_P, "M8 18h13"), (_P, "M8 6h13")],
    "mic": [(_P, "m11 7.601-5.994 8.19a1 1 0 0 0 .1 1.298l.817.818a1 1 0 0 0 1.314.087L15.09 12"),
            (_P, "M16.5 21.174C15.5 20.5 14.372 20 13 20c-2.058 0-3.928 2.356-6 2"
                 "-2.072-.356-2.775-3.369-1.5-4.5"),
            ("circle", 'cx="16" cy="7" r="5"')],
    "settings": [(_P, "M10 5H3"), (_P, "M12 19H3"), (_P, "M14 3v4"), (_P, "M16 17v4"),
                 (_P, "M21 12h-9"), (_P, "M21 19h-5"), (_P, "M21 5h-7"), (_P, "M8 10v4"),
                 (_P, "M8 12H3")],
    "back": [(_P, "m15 18-6-6 6-6")],
    "pie": [(_P, "M21 12c.552 0 1.005-.449.95-.998a10 10 0 0 0-8.953-8.951c-.55-.055"
                 "-.998.398-.998.95v8a1 1 0 0 0 1 1z"),
            (_P, "M21.21 15.89A10 10 0 1 1 8 2.83")],
    "folder": [(_P, "M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9"
                    "A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z")],
    "mini": [(_P, "M21 9V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v10c0 1.1.9 2 2 2h4"),
             ("rect", 'x="12" y="13" width="10" height="7" rx="2"')],
    "expand": [(_P, "M15 3h6v6"), (_P, "m21 3-7 7"), (_P, "m3 21 7-7"), (_P, "M9 21H3v-6")],
    "repeat": [(_P, "m17 2 4 4-4 4"), (_P, "M3 11v-1a4 4 0 0 1 4-4h14"), (_P, "m7 22-4-4 4-4"),
               (_P, "M21 13v1a4 4 0 0 1-4 4H3")],
    "repeat1": [(_P, "m17 2 4 4-4 4"), (_P, "M3 11v-1a4 4 0 0 1 4-4h14"), (_P, "m7 22-4-4 4-4"),
                (_P, "M21 13v1a4 4 0 0 1-4 4H3"), (_P, "M11 10h1v4")],
    "heart": [(_P, "M2 9.5a5.5 5.5 0 0 1 9.591-3.676.56.56 0 0 0 .818 0A5.5 5.5 0 0 1 22 9.5"
                   "c0 2.29-1.5 4-3 5.5l-5.492 5.313a2 2 0 0 1-3 .019L5 15c-1.5-1.5-3-3.2-3-5.5")],
    "heartF": [(_P, "M2 9.5a5.5 5.5 0 0 1 9.591-3.676.56.56 0 0 0 .818 0A5.5 5.5 0 0 1 22 9.5"
                    "c0 2.29-1.5 4-3 5.5l-5.492 5.313a2 2 0 0 1-3 .019L5 15c-1.5-1.5-3-3.2-3-5.5",
                "fill")],
    "grip": [("circle", f'cx="{x}" cy="{y}" r="1"') for x in (9, 15) for y in (6, 12, 18)],
    "x": [(_P, "M18 6 6 18"), (_P, "m6 6 12 12")],
    "wifi": [(_P, "M12 20h.01"), (_P, "M8.5 16.429a5 5 0 0 1 7 0"),
             (_P, "M5 12.859a10 10 0 0 1 5.17-2.69"), (_P, "M19 12.859a10 10 0 0 0-2.007-1.523"),
             (_P, "M2 8.82a15 15 0 0 1 4.177-2.643"), (_P, "M22 8.82a15 15 0 0 0-11.288-3.764"),
             (_P, "m2 2 20 20")],
    "plug": [(_P, "M12 22v-5"), (_P, "M9 8V2"), (_P, "M15 8V2"),
             (_P, "M18 8v5a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V8Z")],
    "check": [(_P, "M20 6 9 17l-5-5")],
    "up": [(_P, "m18 15-6-6-6 6")],
    "down": [(_P, "m6 9 6 6 6-6")],
    "right": [(_P, "m9 18 6-6-6-6")],
    "pin": [(_P, "M12 17v5"),
            (_P, "M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12"
                 "a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1"
                 " 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z")],
    "plus": [(_P, "M5 12h14"), (_P, "M12 5v14")],
    "pen": [(_P, "M12 20h9"),
            (_P, "M16.376 3.622a1 1 0 0 1 3.002 3.002L7.368 18.635a2 2 0 0 1-.855.506"
                 "l-2.872.838a.5.5 0 0 1-.62-.62l.838-2.872a2 2 0 0 1 .506-.854z")],
    "shuffle": [(_P, "m18 14 4 4-4 4"), (_P, "m18 2 4 4-4 4"),
                (_P, "M2 18h1.973a4 4 0 0 0 3.3-1.7l5.454-7.6a4 4 0 0 1 3.3-1.7H22"),
                (_P, "M2 6h1.972a4 4 0 0 1 3.28 1.7l.288.4"),
                (_P, "M22 18h-6.041a4 4 0 0 1-3.3-1.8l-.359-.45")],
    "play": [("polygon", 'points="6 3 20 12 6 21 6 3"', "fill")],
    "pause": [("rect", 'x="14" y="4" width="4" height="16" rx="1"', "fill"),
              ("rect", 'x="6" y="4" width="4" height="16" rx="1"', "fill")],
    "prev": [("polygon", 'points="19 20 9 12 19 4 19 20"', "fill"),
             ("line", 'x1="5" x2="5" y1="19" y2="5"')],
    "next": [("polygon", 'points="5 4 15 12 5 20 5 4"', "fill"),
             ("line", 'x1="19" x2="19" y1="5" y2="19"')],
    "vol": [(_P, "M11 4.702a.705.705 0 0 0-1.203-.498L6.413 7.587A1.4 1.4 0 0 1 5.416 8H3"
                 "a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2.416a1.4 1.4 0 0 1 .997.413l3.383 3.384"
                 "A.705.705 0 0 0 11 19.298z"),
            (_P, "M16 9a5 5 0 0 1 0 6")],
    "more": [("circle", f'cx="{x}" cy="12" r="1"') for x in (5, 12, 19)],
    "trash": [(_P, "M3 6h18"), (_P, "M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"),
              (_P, "M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2")],
}


def _svg(name: str, colour: QColor) -> bytes:
    rgb = colour.name()
    parts = []
    for item in SVG[name]:
        tag, body = item[0], item[1]
        filled = len(item) > 2
        if tag == _P:
            body = f'd="{body}"'
        fill = f' fill="{rgb}"' if filled else ""
        parts.append(f"<{tag} {body}{fill}/>")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
            f'viewBox="0 0 24 24" fill="none" stroke="{rgb}" stroke-width="2" '
            f'stroke-linecap="round" stroke-linejoin="round">{"".join(parts)}</svg>'
            ).encode()


_cache: dict[tuple, QPixmap] = {}


def pixmap(name: str, px: float, colour: QColor, dpr: float = 1.0) -> QPixmap:
    """The icon at `px` logical pixels, as an opaque-colour pixmap."""
    side = max(1, int(round(px * dpr)))
    key = (name, side, colour.rgb(), round(dpr, 3))
    pm = _cache.get(key)
    if pm is not None:
        return pm
    pm = QPixmap(side, side)
    pm.fill(Qt.GlobalColor.transparent)
    solid = QColor(colour)
    solid.setAlpha(255)
    r = QSvgRenderer(QByteArray(_svg(name, solid)))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r.render(p, QRectF(0, 0, side, side))
    p.end()
    pm.setDevicePixelRatio(dpr)
    if len(_cache) > 600:
        _cache.clear()
    _cache[key] = pm
    return pm


def draw(p: QPainter, name: str, rect: QRectF, colour: QColor) -> None:
    """Draw an icon centred in `rect`, sized to its shorter side."""
    if name not in SVG:
        return
    side = min(rect.width(), rect.height())
    dpr = p.device().devicePixelRatioF() if p.device() is not None else 1.0
    pm = pixmap(name, side, colour, dpr)
    box = QRectF(rect.center().x() - side / 2, rect.center().y() - side / 2, side, side)
    was = p.opacity()
    if colour.alpha() < 255:
        p.setOpacity(was * colour.alphaF())
    p.drawPixmap(box, pm, QRectF(pm.rect()))
    p.setOpacity(was)
