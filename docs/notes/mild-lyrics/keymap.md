# keymap.py and kblayout.py

## 2026-10-16 — keys by position, named as the layout prints them

**Asked for:** somebody on AZERTY found the Keys tab's QWERTY names "very
confusing", and `[` `]` needed AltGr there. The naming bugs were fixed the
day before (by character, scan-code checked); this is the labels and
defaults half.

**What it does.** Six defaults sit by position rather than by character:
`[` `]`, `Shift+[` `Shift+]`, `0` `Shift+0` (`keymap.POSITIONAL`). Each takes
the name the active layout gives the key where US has that character, so on
Belgian AZERTY the offsets are `^ $` / `¨ *` and the clears `À` / `0`, and
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
