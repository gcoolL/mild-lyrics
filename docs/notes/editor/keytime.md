# keytime.py

## Why — 2026-11-03

A timing key is read by `fire()` when the event loop gets to it, and the
stamp is the player's position then. While the editor is busy (a garbage
collection, a long relayout) the key waits and its stamp lands late by
that wait. Every key event carries the platform's press time in ms.

## How

- Shortcuts are decided on the ShortcutOverride sent to the focused widget,
  before any window sees the press, so `KeyClock` filters the focused
  widget (moved on `focusChanged`) and the window handle; never the whole
  application, and no native-message hook.
- The press clock is not perf_counter: each press gives `gap = read -
  pressed` in perf ms; the smallest gap in the last 120 s (256 presses) is
  the clocks' offset, and a press's wait is its gap less that. Nothing is
  corrected before 5 presses.
- Waits up to 20 ms are left alone (event clocks tick in whole ms, 15.6 ms
  on Windows); on Windows 8 ms (half a tick) is kept back. Over 1 s is a
  clock fault and ignored; an event clock more than 1 s behind the last
  starts the calibration over.
- `fire()` takes `waited()` (consumed, only within 50 ms of the press being
  read), scaled by the playback rate, only while playing. `tap-waited` rows
  in follow.log record each correction.

## Checked

Offscreen: real shortcut presses (QTest) reach the filter, on-time presses
are not moved; presses fed as read 45/120/600 ms late are stamped back to
within ~1 ms; 15 ms and 5000 ms are left alone. Not yet checked: real
Windows and Wayland press clocks.
