# keymap.py and kblayout.py

## 2026-10-16 — keys by position, named as the layout prints them

**Why:** on AZERTY the Keys tab's QWERTY names were misleading,
and `[` `]` needed AltGr there. The naming bugs were fixed the
day before (by character, scan-code checked); this is the labels and
defaults half.

**What it does.** Six defaults sit by position rather than by character:
`[` `]`, `Shift+[` `Shift+]`, `0` `Shift+0` (`keymap.POSITIONAL`). Each takes
the name the active layout gives the key where US has that character, so on
AZERTY the offsets are `^ $` / `¨ *` and the clears `À` / `0`, and
the Keys tab prints exactly that. Letters and the mnemonic keys (`+ - / < >`)
stay by character: Q is quit wherever Q is.

  * A group (the four offsets, the two clears) moves together, or not at
    all if any of its names lands on another default's key. German's and
    Spanish's `]` key types `+`, which is `bigger`, so their offsets stay on
    the US characters (AltGr, as before); their clears move to `0` / `=`.
  * A key the user chose is never taken by a default: that slot keeps its
    US character instead.
  * The US characters stay as aliases for positional slots the user has not
    touched, so AltGr+5 on AZERTY still fires `[`.
  * `bind` stores only what differs from the layout's defaults (two passes,
    since the defaults depend on what the user chose).

**Reading the layout** (`kblayout.read`, once a window exists):

    Wayland  own wl_display connection, wl_seat -> wl_keyboard; the
             compositor sends its xkb keymap at once. libxkbcommon then
             gives each key's plain and Shift character per group.   12ms
    X11      xkbcommon-x11 from the core keyboard; active group exact. 44ms
    Windows  ToUnicodeEx per scan code on GetKeyboardLayout(0); dead keys
             flushed with a second call. NOT RUN HERE.
    macOS    not read: US names, as before.

Inside a real Wayland Qt app the first `resolve` costs 23ms, once.

**Held to what Qt says.** Every press with no Ctrl/Alt/Meta is checked
against the layout (`keymap._check`): another group that fits becomes the
active one (multi-layout setups: Wayland gives no group without focus, so
the first group is assumed until a press says otherwise); an unexplained
miss re-reads at most every 30s and adopts the result only if it read and
differs (Linux AltGr presses miss, since level 3 is not in the map). On
Windows only, three unexplained misses in a row drop the layout and the US
names come back -- the safe degradation for a path nobody here can run.
`Actions` (what `resolve` returns) re-makes itself when the layout changes,
and `KeyboardLayoutChange` makes the window forget it.

**Windows AltGr.** Windows reports AltGr as Ctrl+Alt. A Ctrl+Alt press that
carries one printable character is taken as AltGr and named by that
character; a real Ctrl+Alt+A carries a control character and stays
`Ctrl+Alt+A`.

Tests: `tests/test_kblayout.py` (layouts compiled with `xkbcli
compile-keymap`; set `MILD_LIVE_LAYOUT=1` to also read this session's
compositor), `tests/test_keymap.py`.

## 2026-10-25 — Windows: a dead key took two presses

Seen on the Windows laptop in AZERTY: `^` (the offset key) had to be pressed twice. Read from Qt 6.11's `qwindowskeymapper.cpp`: `translateKeyEvent` returns early when `PeekMessage` finds a `WM_DEADCHAR` queued ("consume dead chars"), so the dead key's key-down never becomes a QKeyEvent. The key-up is dropped as well, because a release with no recorded press is ignored (only the Surface Pen F18-F20 case is let through). The second press makes Windows type a real `^` (`WM_CHAR`), and Qt delivers that one. Nothing of the first press reaches Qt, so this cannot be fixed at the QKeyEvent level.

`deadkeys.py` installs a `WH_KEYBOARD` hook on the GUI thread. It runs only when a keyboard message is taken off the queue, not under every message (see lyrics_gui.md, 2026-10-18, for why that matters), and only while the layout read has a dead key (`DK.sync`, at start and on KeyboardLayoutChange).

**First version, same day: one press, then two.** It posted Key_Dead_* and let Windows compose, staying quiet on the press after. On the Windows laptop the first `^` now moved the offset once, and the second moved it twice. Windows' AZERTY tables have no `^`+`^` entry, so the second press types both marks, `^^`: two WM_CHARs, and Qt turns each into a key press.

**Now: take it or leave it.** The window answers `dead_key_taken(name)` the way keyPressEvent would route the press. It returns True when a key is being bound, or when the key is bound in the lyrics view with no dialog, editing, search, drawer or review open. Then the hook posts Key_Dead_* with the key's scan code (what Linux delivers, so key_name, `_check` and binding need no change) and swallows the key-down. Windows starts no accent, so each press is one action, with no `^^` and no stray accent on the next letter. Anywhere else the press passes untouched and Windows composes as before: `ê` in the search box, and a literal `^` from `^` then space.

Tests: `tests/test_deadkeys.py` (the hook's decisions on a fake layout, and the posted event through offscreen Qt); `dead_key_taken` was checked on the real window offscreen (each state, and a posted `^` reaching do_action once). Confirmed on the Windows laptop the same day: every `^` moves the offset once, and `ê` still types.

## Lift — 2026-10-25

Docstrings shortened in `mild-lyrics/keymap.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> The player's keys, as a table that can be rebound.
>
> Every key the window answers to used to be a branch of keyPressEvent, which
> was fine for as long as nobody wanted a different one. Here each thing a key
> does is an ACTION with a name, each action has one or two SLOTS -- the chips
> the Keys tab shows, "N" and "P" for next and previous track -- and each slot
> holds the key that fires it. What somebody has changed is kept in gui.json as
> {slot: key}; a slot not in there has its default.
>
> Some keys are not the user's to move and are listed as fixed: the mouse, Tab
> and the arrows that walk the panels, Esc, and F11. A few actions also answer
> to a second key nobody sees in the list -- the arrow keys seek as well as
> < and >, F1 opens the help as well as H -- and those aliases go on working
> until a slot is given the same key, at which point the slot wins.
>
> A key is on one action at most. Binding one that is already in use takes it
> off the action that had it, which is then left with no key and says so --
> the other way round, both keys dead or the old one silently winning, reads
> as the window being broken.
>
> The [ ] and 0 defaults follow the key, not the character, and are named as
> the active layout prints them: docs/notes/mild-lyrics/keymap.md.
