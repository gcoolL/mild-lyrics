"""The player's keys, as a table that can be rebound.

Every key the window answers to used to be a branch of keyPressEvent, which
was fine for as long as nobody wanted a different one. Here each thing a key
does is an ACTION with a name, each action has one or two SLOTS -- the chips
the Keys tab shows, "N" and "P" for next and previous track -- and each slot
holds the key that fires it. What somebody has changed is kept in gui.json as
{slot: key}; a slot not in there has its default.

Some keys are not the user's to move and are listed as fixed: the mouse, Tab
and the arrows that walk the panels, Esc, and F11. A few actions also answer
to a second key nobody sees in the list -- the arrow keys seek as well as
< and >, F1 opens the help as well as H -- and those aliases go on working
until a slot is given the same key, at which point the slot wins.

A key is on one action at most. Binding one that is already in use takes it
off the action that had it, which is then left with no key and says so --
the other way round, both keys dead or the old one silently winning, reads
as the window being broken.
"""
from __future__ import annotations

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
        ("visualizer", [("viz", "V")]),
        ("visualizer mode", [("viz_mode", "Shift+V")]),
        ("line alignment", [("align", "L")]),
        ("word pop", [("pop", "E")]),
        ("focus mode", [("focus", "O")]),
        ("sung colour", [("sung", "U")]),
        ("glow / depth blur", [("glow", "G"), ("blur", "B")]),
        ("regular / compact view", [("view", "A")]),
        ("text size", [("bigger", "+"), ("smaller", "-")]),
    ]),
    ("Window", [
        ("settings menu", [("menu", "M")]),
        ("browse, search & queue", [("browse", "Home")]),
        ("fullscreen", [("fullscreen", "F")]),
        ("fullscreen", "F11"),
        ("always on top", [("on_top", "T")]),
        ("these sections", "Tab / ← →"),
        ("keys", [("help", "H"), ("help_2", "?")]),
        ("play a pasted song", [("paste", "Ctrl+V")]),
        ("quit", [("quit", "Q")]),
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
}

FIXED = {"F11", "Esc", "Tab", "Shift+Tab", "Ctrl+Y"}

DEFAULTS = {slot: key for _s, rows in TABLE for _d, slots in rows
            if not isinstance(slots, str) for slot, key in slots}
DESC = {slot: desc for _s, rows in TABLE for desc, slots in rows
        if not isinstance(slots, str) for slot, _k in slots}
ORDER = list(DEFAULTS)


def action(slot: str) -> str:
    return ACTION_OF.get(slot, slot)


def current(keymap: dict | None) -> dict:
    """Every slot's key: the default, unless it has been changed."""
    got = dict(DEFAULTS)
    for slot, key in (keymap or {}).items():
        if slot in got and isinstance(key, str):
            got[slot] = key
    return got


def resolve(keymap: dict | None) -> dict:
    """{key: action} for the window to look a press up in."""
    out = {}
    bound = current(keymap)
    for slot in ORDER:
        key = bound[slot]
        if key and key not in out and key not in FIXED:
            out[key] = action(slot)
    for key, act in ALIASES.items():
        out.setdefault(key, act)
    return out


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
    kept = {s: k for s, k in bound.items() if k != DEFAULTS[s]}
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
            # Shift with these is what the table calls them: the key under
            # the hand, not the character a layout happens to print.
            K.Key_BraceLeft: "Shift+[", K.Key_BraceRight: "Shift+]",
            K.Key_ParenRight: "Shift+0",
        }
        for i in range(1, 25):
            _NAMED[getattr(K, f"Key_F{i}")] = f"F{i}"
    return _NAMED


# keys whose name already says Shift was held, or whose character is one
MARKS = set("<>?+_:\"|~!@#$%^&*(")


def key_name(ev) -> str | None:
    """A key press as the table spells keys, or None for a bare modifier."""
    from PyQt6.QtCore import Qt
    K, M = Qt.Key, Qt.KeyboardModifier
    k, mods = ev.key(), ev.modifiers()
    if k in (K.Key_Shift, K.Key_Control, K.Key_Alt, K.Key_Meta,
             K.Key_AltGr, K.Key_CapsLock, K.Key_unknown):
        return None
    named = _named()
    if k in named:
        base = named[k]
    elif K.Key_A <= k <= K.Key_Z:
        base = chr(int(k))
    elif K.Key_0 <= k <= K.Key_9:
        base = chr(int(k))
    else:
        text = ev.text() or ""
        base = text.upper() if text and text.isprintable() else ""
        if not base:
            return None
    out = []
    if mods & M.ControlModifier:
        out.append("Ctrl")
    if mods & M.AltModifier:
        out.append("Alt")
    if (mods & M.ShiftModifier and not base.startswith("Shift+")
            and base not in MARKS and base != "Tab"):
        out.append("Shift")
    if k == K.Key_Backtab:
        out.append("Shift")
    return "+".join(out + [base])
