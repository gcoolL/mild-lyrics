# `mild-lyrics/deadkeys.py`

## Lift — 2026-10-25

Docstrings shortened in `mild-lyrics/deadkeys.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> Windows: one press of a dead key reaches the window, as it does on Linux.
>
> Qt's Windows key mapper drops a key-down when Windows has queued WM_DEADCHAR for it
> ("consume dead chars"), and drops the key-up for a press it never recorded. So AZERTY's
> `^` took two presses, and the second fired twice: Windows types "^^" for a dead key
> pressed twice, as two characters. A WH_KEYBOARD hook on the GUI thread sees the press
> first. Where the window takes it as a key (`taker`), the hook posts Key_Dead_* and
> swallows the press, so no accent is started; anywhere else (a text field) it lets the
> press through and Windows composes "ê" as before. The hook runs only for keyboard
> messages, never under every message (what hung 1.1.9), and is installed only while the
> layout has dead keys. Notes: docs/notes/mild-lyrics/keymap.md.
