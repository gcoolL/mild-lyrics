"""The player's keys as a rebindable table: named actions, slots, keys; changes
kept in gui.json as {slot: key}. Notes: docs/notes/mild-lyrics/keymap.md."""
from __future__ import annotations

import sys

# (section, [(what it does, [(slot, default key), ...] or a fixed label)])
# A row's slots are the chips it shows. A row whose second element is a str
# is fixed: it is listed, and it cannot be changed.
TABLE = [
    ("Playback", [
        ("play / pause", [("play_pause", "Space")]),
        ("seek -/+ 5s", [("seek_back", "<"), ("seek_fwd", ">")]),
        ("previous / next line", [("prev_line", "Up"), ("next_line", "Down")]),
        ("next / previous track", [("next_track", "N"), ("prev_track", "P")]),
        ("seek to a line", "click"),
        ("scrub", "drag bar"),
        ("volume, on its bar", "wheel"),
    ]),
    ("Timing", [
        ("offset -/+ 50ms", [("offset_back", "["), ("offset_fwd", "]")]),
        ("offset -/+ 10ms", [("offset_back_fine", "Shift+["),
                             ("offset_fwd_fine", "Shift+]")]),
        ("clear track / global offset", [("clear_track_offset", "0"),
                                         ("clear_offset", "Shift+0")]),
        ("resync to audio", [("resync", "X")]),
    ]),
    ("Lyrics", [
        ("reload lyrics", [("reload", "R")]),
        ("fix this line's romaji", [("fix_romaji", "Shift+R")]),
        ("romaji from Genius", [("genius", "Shift+G")]),
        ("copy line / all", [("copy_line", "C"), ("copy_all", "Shift+C")]),
        ("save .ttml / card", [("save_ttml", "S"), ("save_card", "Shift+S")]),
        ("search all lyrics + Genius", [("search", "/")]),
        ("song info", [("info", "I")]),
        ("review this document", [("review", "Y")]),
        ("mark any lyric's faults as it plays", [("review_marks", "Shift+Y")]),
    ]),
    ("Look", [
        ("background style", [("bg", "D")]),
        ("visualiser", [("viz", "V")]),
        ("visualiser mode", [("viz_mode", "Shift+V")]),
        ("line alignment", [("align", "L")]),
        ("word pop", [("pop", "E")]),
        ("focus mode", [("focus", "O")]),
        ("sung colour", [("sung", "U")]),
        ("glow / depth blur", [("glow", "G"), ("blur", "Shift+B")]),
        ("regular / compact view", [("view", "A")]),
        ("text size", [("bigger", "+"), ("smaller", "-")]),
    ]),
    ("Window", [
        ("settings menu", [("menu", "M")]),
        ("home page", [("browse", "B")]),
        ("queue", [("queue", "Q")]),
        ("fullscreen", [("fullscreen", "F")]),
        ("fullscreen", "F11"),
        ("always on top", [("on_top", "T")]),
        ("hide to the tray", [("tray", "Ctrl+W")]),
        ("debug overlay", [("debug", "F12")]),
        ("these sections", "Tab / ← →"),
        ("keys", [("help", "H"), ("help_2", "?")]),
        ("play a pasted song", [("paste", "Ctrl+V")]),
        ("quit", [("quit", "Ctrl+Q")]),
        ("close, or leave fullscreen", "Esc"),
    ]),
]

# slot -> the action it fires, where the two are not spelt the same
ACTION_OF = {"help_2": "help"}

# keys an action answers to without a chip of its own
ALIASES = {
    ",": "seek_back", "Left": "seek_back",
    ".": "seek_fwd", "Right": "seek_fwd",
    "F1": "help", "F3": "search", "Shift+F3": "search_lines",
    "=": "bigger", "_": "smaller",
    # the home page's key before 1.2.0
    "Home": "browse",
    # Shift+[ and Shift+] by character, for layouts that type them with AltGr
    "{": "offset_back_fine", "}": "offset_fwd_fine",
}

FIXED = {"F11", "Esc", "Tab", "Shift+Tab", "Ctrl+Y"}

DEFAULTS = {slot: key for _s, rows in TABLE for _d, slots in rows
            if not isinstance(slots, str) for slot, key in slots}
DESC = {slot: desc for _s, rows in TABLE for desc, slots in rows
        if not isinstance(slots, str) for slot, _k in slots}
ORDER = list(DEFAULTS)


# Defaults that sit by POSITION: the key US has that character on, named as
# the active layout types it (AZERTY's ^ $ where US has [ ]). A group moves
# together, or not at all if it would land on another default's key.
POSITIONAL = [
    {"offset_back": ("[", False), "offset_fwd": ("]", False),
     "offset_back_fine": ("[", True), "offset_fwd_fine": ("]", True)},
    {"clear_track_offset": ("0", False), "clear_offset": ("0", True)},
]


def action(slot: str) -> str:
    return ACTION_OF.get(slot, slot)


def defaults(keymap: dict | None = None) -> dict:
    """Every slot's default on the layout in use; DEFAULTS where unread."""
    out = dict(DEFAULTS)
    lay = layout()
    if lay is None:
        return out
    user = {s: k for s, k in (keymap or {}).items()
            if s in DEFAULTS and isinstance(k, str)}
    for group in POSITIONAL:
        names = {s: typed_name(lay, us, shifted)
                 for s, (us, shifted) in group.items()}
        got = set(names.values())
        if None in got or len(got) < len(names) or got & FIXED:
            continue
        if got & {out[s] for s in DEFAULTS if s not in group}:
            continue
        mine = {k for s, k in user.items() if s not in group}
        for slot, name in names.items():
            if name not in mine:
                out[slot] = name
    return out


def current(keymap: dict | None) -> dict:
    """Every slot's key: the default, unless it has been changed."""
    got = defaults(keymap)
    for slot, key in (keymap or {}).items():
        if slot in got and isinstance(key, str):
            got[slot] = key
    return got


def _resolve(keymap: dict | None) -> dict:
    out = {}
    bound = current(keymap)
    for slot in ORDER:
        key = bound[slot]
        if key and key not in out and key not in FIXED:
            out[key] = action(slot)
    for key, act in ALIASES.items():
        out.setdefault(key, act)
    # the US characters keep working where the layout moved a default off them
    for group in POSITIONAL:
        for slot in group:
            if slot not in (keymap or {}):
                out.setdefault(DEFAULTS[slot], action(slot))
    return out


class Actions(dict):
    """{key: action}, re-made when what the layout is known to be changes."""

    def __init__(self, keymap: dict | None):
        super().__init__()
        self.keymap = dict(keymap or {})
        self._seen = -1
        self._fill()

    def _fill(self) -> None:
        self.clear()
        self.update(_resolve(self.keymap))
        self._seen = _LAY["version"]

    def get(self, key, default=None):
        if self._seen != _LAY["version"]:
            self._fill()
        return super().get(key, default)


def resolve(keymap: dict | None) -> Actions:
    """{key: action} for the window to look a press up in."""
    return Actions(keymap)


def bind(keymap: dict | None, slot: str, key: str) -> tuple[dict, str, dict]:
    """Put `key` on `slot`. Returns (the keymap to keep, what to say, notes).

    `notes` is {slot: line} for the slots that lost a key to this one, so
    the list can say under each where its key went. Only what differs from
    the defaults is kept.
    """
    if key in FIXED:
        return dict(keymap or {}), f"{key} is kept by the window", {}
    bound = current(keymap)
    notes, said = {}, ""
    if key:
        for other in ORDER:
            if other != slot and bound[other] == key:
                bound[other] = ""
                notes[other] = f"{key} went to “{DESC[slot]}”"
                said = f"{key} taken off “{DESC[other]}”, which has no key now"
    bound[slot] = key
    if not key:
        said = f"“{DESC[slot]}” has no key now"
    base = defaults()
    kept = {s: k for s, k in bound.items() if k != base[s]}
    base = defaults(kept)
    kept = {s: k for s, k in bound.items() if k != base[s]}
    return kept, said, notes


def help_rows(keymap: dict | None) -> list:
    """The table as the classic Keys panel lists it: [(section, [(keys,
    what)])], with whatever the keys are now."""
    bound = current(keymap)
    out = []
    for section, rows in TABLE:
        got = []
        for desc, slots in rows:
            if isinstance(slots, str):
                keys = slots
            else:
                keys = " / ".join(bound[s] or "—" for s, _k in slots)
            if got and got[-1][1] == desc:
                got[-1] = (f"{got[-1][0]} / {keys}", desc)
            else:
                got.append((keys, desc))
        out.append((section, got))
    return out


_NAMED = None


def _named() -> dict:
    global _NAMED
    if _NAMED is None:
        from PyQt6.QtCore import Qt
        K = Qt.Key
        _NAMED = {
            K.Key_Space: "Space", K.Key_Up: "Up", K.Key_Down: "Down",
            K.Key_Left: "Left", K.Key_Right: "Right", K.Key_Home: "Home",
            K.Key_End: "End", K.Key_PageUp: "PgUp", K.Key_PageDown: "PgDown",
            K.Key_Escape: "Esc", K.Key_Tab: "Tab", K.Key_Backtab: "Tab",
            K.Key_Return: "Enter", K.Key_Enter: "Enter",
            K.Key_Backspace: "Backspace", K.Key_Delete: "Delete",
            K.Key_Insert: "Insert",
            K.Key_Less: "<", K.Key_Greater: ">", K.Key_Comma: ",",
            K.Key_Period: ".", K.Key_Slash: "/", K.Key_Question: "?",
            K.Key_BracketLeft: "[", K.Key_BracketRight: "]",
            K.Key_Plus: "+", K.Key_Equal: "=", K.Key_Minus: "-",
            K.Key_Underscore: "_", K.Key_Semicolon: ";", K.Key_Colon: ":",
            K.Key_Apostrophe: "'", K.Key_QuoteDbl: '"', K.Key_Backslash: "\\",
            K.Key_Bar: "|", K.Key_QuoteLeft: "`", K.Key_AsciiTilde: "~",
            K.Key_Exclam: "!", K.Key_At: "@", K.Key_NumberSign: "#",
            K.Key_Dollar: "$", K.Key_Percent: "%", K.Key_AsciiCircum: "^",
            K.Key_Ampersand: "&", K.Key_Asterisk: "*", K.Key_ParenLeft: "(",
            K.Key_BraceLeft: "{", K.Key_BraceRight: "}",
            K.Key_ParenRight: ")",
        }
        for i in range(1, 25):
            _NAMED[getattr(K, f"Key_F{i}")] = f"F{i}"
        # Dead keys (AZERTY's ^, QWERTZ's ^ and ´) arrive with no text: name
        # them by the mark they print, so one press binds and fires.
        for dead, mark in DEAD.items():
            if hasattr(K, dead):
                _NAMED[getattr(K, dead)] = mark
    return _NAMED


DEAD = {"Key_Dead_Circumflex": "^", "Key_Dead_Grave": "`",
        "Key_Dead_Acute": "´", "Key_Dead_Tilde": "~",
        "Key_Dead_Diaeresis": "¨", "Key_Dead_Abovering": "°",
        "Key_Dead_Cedilla": "¸", "Key_Dead_Caron": "ˇ",
        "Key_Dead_Macron": "¯", "Key_Dead_Breve": "˘",
        "Key_Dead_Abovedot": "˙", "Key_Dead_Doubleacute": "˝",
        "Key_Dead_Ogonek": "˛"}


# With Shift held, these characters are named as the US key under the hand,
# which is how the table spells them. Without Shift (AZERTY's ")", AltGr's
# "{") they are only themselves.
SHIFTED_AS = {"{": "Shift+[", "}": "Shift+]", ")": "Shift+0"}
# Where those keys sit: xkb keycodes, Windows scan codes, macOS virtual keys.
US_KEY = {"linux": {")": 19, "{": 34, "}": 35},
          "win32": {")": 0x0B, "{": 0x1A, "}": 0x1B},
          "darwin": {")": 0x1D, "{": 0x21, "}": 0x1E}}


def _plat() -> str:
    return "linux" if sys.platform.startswith("linux") else sys.platform


def _native_code(ev) -> int:
    return ev.nativeVirtualKey() if _plat() == "darwin" else ev.nativeScanCode()


def _on_us_key(ev, ch: str) -> bool:
    """Whether `ch` came off the key US Shift puts it on (QWERTZ types ")"
    with Shift+9). Unknown -- no code, another platform -- counts as yes."""
    want = US_KEY.get(_plat(), {}).get(ch)
    code = _native_code(ev)
    return not want or code in (0, 1) or code == want


def _named_as(base: str, shift: bool, ctrl: bool, alt: bool, on_us) -> str:
    """The table's spelling of a press, once its base is known."""
    if shift and base in SHIFTED_AS and on_us(base):
        base, shift = SHIFTED_AS[base], False
    # Qt reports the character Shift made, so Shift on a digit or a mark was
    # spent making it (AZERTY's digits, its "/" and "."): not part of the name.
    if len(base) == 1 and not base.isalpha():
        shift = False
    out = []
    if ctrl:
        out.append("Ctrl")
    if alt:
        out.append("Alt")
    if shift and base != "Tab":
        out.append("Shift")
    return "+".join(out + [base])


# The layout in use (kblayout.Layout), read once a window exists to ask.
# "version" moves whenever what it says changes, so Actions re-make.
_LAY = {"read": False, "layout": None, "version": 0, "misses": 0,
        "reread_at": 0.0}
# US key positions, by the character on them unshifted
US_POS = {plat: {"[": codes["{"], "]": codes["}"], "0": codes[")"]}
          for plat, codes in US_KEY.items()}


def layout():
    """The active layout, or None: unread, unreadable, or found wrong."""
    if not _LAY["read"]:
        from PyQt6.QtGui import QGuiApplication
        if QGuiApplication.instance() is None:
            return None
        _LAY.update(read=True, layout=_read(), misses=0)
        _LAY["version"] += 1
    return _LAY["layout"]


def _read():
    try:
        from PyQt6.QtGui import QGuiApplication
        import kblayout
        return kblayout.read(QGuiApplication.platformName())
    except Exception:                                       # noqa: BLE001
        return None


def use_layout(lay) -> None:
    """Put a layout in (tests), or None for the US names."""
    _LAY.update(read=True, layout=lay, misses=0)
    _LAY["version"] += 1


def forget_layout() -> None:
    """The system says the layout changed: read it again when next asked."""
    _LAY.update(read=False, layout=None, misses=0)
    _LAY["version"] += 1


def typed_name(lay, us: str, shifted: bool, group: int | None = None):
    """The name a press of the US `us` key gets on `lay`, or None."""
    code = US_POS.get(_plat(), {}).get(us)
    return None if code is None else code_name(lay, code, shifted, group)


def code_name(lay, code: int, shifted: bool, group: int | None = None):
    got = lay.typed(code, shifted, group)
    if not got:
        return None
    ch, dead = got
    base = ch if dead or not ch.isalpha() else ch.upper()
    us = {v: k for k, v in US_KEY.get(_plat(), {}).items()}
    return _named_as(base, shifted, False, False, lambda c: us.get(code) == c)


def _check(ev, name: str, shifted: bool) -> None:
    """Hold the layout to what Qt says a press typed: switch to the group
    that fits, re-read it, and on Windows stop trusting it after three
    unexplained misses in a row."""
    lay = _LAY["layout"]
    if lay is None:
        return
    code = _native_code(ev)
    if code not in lay.groups[lay.group]:
        return
    if code_name(lay, code, shifted) == name:
        _LAY["misses"] = 0
        return
    for g in range(len(lay.groups)):
        if g != lay.group and code_name(lay, code, shifted, g) == name:
            lay.group = g
            _LAY["misses"] = 0
            _LAY["version"] += 1
            return
    # Unexplained: AltGr on Linux (no Ctrl+Alt there), or the layout changed
    # under us. A fresh read replaces it only if it reads and differs.
    import time
    now = time.monotonic()
    if now - _LAY["reread_at"] > 30.0:
        _LAY["reread_at"] = now
        fresh = _read()
        if fresh is not None and fresh.groups != lay.groups:
            _LAY.update(layout=fresh, misses=0)
            _LAY["version"] += 1
            if code_name(fresh, code, shifted) == name:
                return
    if sys.platform == "win32":
        _LAY["misses"] += 1
        if _LAY["misses"] >= 3:
            use_layout(None)


def key_name(ev) -> str | None:
    """A key press as the table spells keys, or None for a bare modifier."""
    from PyQt6.QtCore import Qt
    K, M = Qt.Key, Qt.KeyboardModifier
    k, mods = ev.key(), ev.modifiers()
    if k in (K.Key_Shift, K.Key_Control, K.Key_Alt, K.Key_Meta,
             K.Key_AltGr, K.Key_CapsLock, K.Key_unknown):
        return None
    ctrl, alt = bool(mods & M.ControlModifier), bool(mods & M.AltModifier)
    text = ev.text() or ""
    # Windows reports AltGr as Ctrl+Alt; a printable character means it was.
    altgr = (sys.platform == "win32" and ctrl and alt and len(text) == 1
             and text.isprintable())
    named = _named()
    if altgr:
        base = text.upper() if text.isalpha() else text
        ctrl = alt = False
    elif k in named:
        base = named[k]
    elif K.Key_A <= k <= K.Key_Z:
        base = chr(int(k))
    elif K.Key_0 <= k <= K.Key_9:
        base = chr(int(k))
    else:
        base = text.upper() if text and text.isprintable() else ""
        if not base:
            return None
    shift = bool(mods & M.ShiftModifier)
    name = _named_as(base, shift, ctrl, alt, lambda c: _on_us_key(ev, c))
    if k == K.Key_Backtab:
        name = name[:-len("Tab")] + "Shift+Tab"
    if not (ctrl or alt or altgr or mods & M.MetaModifier) and _LAY["read"]:
        _check(ev, name, shift)
    return name
