# tray.py — the system tray icon

## 2026-10-24 — resting in the tray, and a quicker second launch

Goal: less use while in the tray at Memory use low or lower, and a faster
start from the tray. `Tray.hide_window` / `_back` call `LyricsView.tray_rest`.

- **Every mode:** player reads every 250ms (`TRAY_SAMPLE_MS`, was 16), frame
  steps at 2Hz (`FRAME_TRAY_HZ`, was 10), the output-device check at its idle
  10s, the music video paused once by `MusicVideo.hold()` and seeked back by
  `sync()` on return. Syncing it paused was worse than playing it: a paused
  `sync()` seeks to the clock whenever it drifts past DRIFT, so each poll
  decoded from a keyframe (normal hidden: 10.6% CPU with the pause, 8.2%
  playing, 0.3% held). The mini player's refresh-rate timer stops on hide.
- **low and minimal** also let go of the line pictures, glows, tints, word
  pictures, card thumbnails, the animated cover's frames (`park_motion`), the
  readers, and the video decoder (`MusicVideo.rest()`; `wake()` opens the
  same source, a `show`/`swap` while resting is kept for it), then trim the heap.
  Normal and more keep all of it.
- **Second launch:** `mild-lyrics.pyw` knocks before the venv hop and the
  lyrics_gui import, 230 → 50ms to reach the hidden window here (Windows
  imports are slower, so more there). No answer costs ~1ms: the Qt modules it
  loaded are imported next anyway. Flags that make their own run skip it.

Measured in a headless KWin (60Hz, 1280×820, GL except minimal), Firework
fixture with NF's FEAR animated cover and a cached song-clock video, 10s
windows; bench in memory/bench/traylean (`OLD=1` skips the rest):

| mode | hidden CPU before → after | own MB hidden before → after |
|---|---|---|
| normal | 8.2% → 0.3% | 271 → 277 (kept) |
| low | 7.6% → 0.3% | 200 → 155 |
| minimal | 24.4% → 0.4% | 102 → 73 |

Coming back: the first frame ~9ms as before; low/minimal redraw the lines on
it, the animation is back in 55–77ms and the video's frames in 45–130ms (its
last picture and the still cover show until then). The player's reads were
not in the bench (the fixture stops the sampler); 60 reads a second → 4.

## 2026-10-24 — menu items did nothing on Plasma

Bug: Hide to tray did nothing. The menu was cleared and refilled
on aboutToShow. Plasma's host reads the dbusmenu layout ahead of time and sends
`Event(id, "clicked")` for the ids it read, so every click landed on an item
the rebuild had deleted (Qt's `byId` finds nothing and does nothing). Every
item was affected, not only Hide. Now the menu is built once and `_sync` only
changes texts and visibility (ids stay); it runs on open, every 2 s with the
tooltip, and on hide/show. Checked with bench/tray/click.py (dbus-python,
cached layout → AboutToShow(0) → Event): Hide, Show, Lyrics, Home and Quit all
act; before the fix none did. `QAction.trigger()` in a test does not show this.

## 2026-10-24 — built

Built 2026-10-24: minimise into the tray so the music keeps playing, the icon
just "ML" (the home rail's narrow logo), a click opens the window on the view
and page it left, right-click has a few options.

- **Setting:** Settings ▸ Player ▸ "Hide to tray on": `close`,
  `minimise`, `off` (default since 2026-10-27); `--tray` on the command line. `close` sends the close
  button there too; `minimise` only a minimise; `off` has no icon at all.
- **Minimise is not heard on Wayland.** KWin sends xdg_toplevel `suspended`
  and Qt only stops exposing the surface — measured in a headless KWin, a
  minimise and a switch to another virtual desktop look exactly alike
  (activation lost, `isExposed()` false, no WindowStateChange). So on Wayland
  the ways in are the close button (in `close` mode), Ctrl+W ("hide to the
  tray" in the Keys tab) and the tray menu. On Windows and X11 a minimise
  arrives as a WindowStateChange and goes to the tray.
- **Only a spontaneous close goes to the tray** (`QCloseEvent.spontaneous()`:
  the title bar's button, Alt+F4). Quit (Ctrl+Q), Esc, the updater's and
  memory-mode restarts all call `close()` and still quit. Logging out sets
  `quitting` from `commitDataRequest` so a hidden window cannot hold it up.
- **Same place on return:** the window is hidden, not rebuilt, so view and
  home page stay. Fullscreen/maximised is put back, the mini player is hidden
  and shown again in place of the big window, and KWin keep-above is
  re-applied as `exit_mini` does. `quitOnLastWindowClosed` is off while
  hidden.
- **Started again while hidden:** a QLocalServer (`mild-lyrics-tray-<user>`)
  listens only while the window is in the tray; `main()` knocks before making
  the QApplication and exits if answered. Visible windows don't listen, so
  running two on purpose still works; `--no-persist`, `--snapshot`,
  `--fixture`, `--track` and offscreen runs never knock.
- **Menu:** the song, Play/Pause, Next, Previous, Show/Hide, Lyrics, Home,
  Quit. Middle-click is play/pause. Tooltip is the song, checked every 2 s.
- **Ink:** light on a dark colour scheme, dark on a light one
  (`styleHints().colorScheme()`), redrawn when it changes; the user's Font
  setting, Black weight, as wide as the icon.
- The first close-to-tray says so once in a notification (`tray_told` in
  gui.json).

Checked in a headless KWin (Wayland and Xwayland) on a private bus with a
stand-in StatusNotifierWatcher: close hides, SNI `Activate` and a second
launch's knock both restore on Home ▸ Stats, fullscreen comes back, Ctrl+W and
the menu work, `minimise` mode's close button quits and saves; on X11 a
minimise hides to the tray, and with `off` it stays a minimise. Not seen on
their Plasma panel or on Windows yet.
