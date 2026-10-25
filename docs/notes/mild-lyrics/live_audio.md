# `mild-lyrics/live_audio.py`, `mild-lyrics/audio_analysis.py`

## 2026-10-20 — our own player analyses the whole song

They asked why our own player listened live when it has the audio. It no longer has to: `own_analysis` (from `steer_live_audio`) sends the player's source, a local file or the resolver's stream URL, to `Live.whole`. That runs on a thread: ffmpeg decodes in its own process to 22050Hz mono float (soundfile is the fallback for local wav/flac), and `audio_analysis.analyse` vectorises the same readings over the whole song. The live tap only covers the second before the result lands. Up to 3 songs' analyses are kept, keyed by source, and are put back after a track change clears `Beat`. Ours is marked `Beat.own`: `on_beat` keeps it over Spotify's for the same song, because ours is of the cut actually playing, and `measure_offset` skips it.

With the whole song in hand:
- **Beats** are flux peaks over a centred 3s mean + 1 sd, rather than only the past.
- **Tempo** is the onset envelope's autocorrelation with a log-Gaussian prior at 120 bpm (σ half an octave). Without the prior, a ~113 bpm song read 76.
- **Sections** are peaks in the distance between the 8s either side (1s blocks of chroma + loudness), at least 12s apart. These drive the palette rotation that live listening could not.

`offload.call` was not used. It gives up after 30s and reruns the job in this process, which a slow stream download could trigger.

Measured:
- Synthetic 3 min (120 bpm, chord and level changes at 60s and 120s): 0.32s; 99% of beats within 50ms of the true grid, first at 0.23s; sections 60.28 / 119.54; tempo 117.8. A 16ms timer on the main thread was at most 2.5ms late while it ran.
- A real YouTube stream through `stream_source._audio`: 0.8s for 213s, length matching the resolver's; tempo 115.8 (true ≈ 113).
- Stub window with a real (never played) QMediaPlayer: loaded 0.32s after asking, kept through Spotify's empty answer, restored after `Beat.clear()`.

## 2026-10-19 — the visualiser for songs Spotify did not analyse

The visualiser (wall modes and the cover halo) reads `Beat`: Spotify's analysis through Spicetify, so any other player, and Mild Lyrics' own, drew nothing. They chose live capture over fetching a copy of the song, and to run it only while the visualiser or halo is on.

**What runs.** `LyricsView.steer_live_audio` (4Hz) wants a tap while the visualiser or halo is on, the battery keeps `viz`, the song is playing, the window is showing, and `Beat` holds nothing from Spotify. Spotify's analysis landing replaces the live rows (`Beat.load` clears), and a failed ask no longer wipes them (`on_beat`). The offset estimator skips live analyses (`measure_offset`).

- Our own player: a `QAudioBufferOutput` on its `QMediaPlayer`, asked for 22050Hz mono float. Rows are stamped with the buffer's `startTime`, which is the player's own position, so they line up exactly. Measured: rows arrive ~47ms ahead of the position they are for.
- Other players, Linux: `parec --monitor-stream=<sink-input>`, only that app's stream, never the whole mix. The stream is found by the bus's app name (aliases for Chromium-family browsers), else the one uncorked stream when there is exactly one (plasma-browser-integration names no app). Our own Qt stream carries no `application.process.id`; it is skipped by `node.name == "Mild Lyrics"`. Rows are stamped with `mono()` and turned into positions with `Clock.position(t)`. They arrive ~89ms after the sound leaves the app.
- Other players, Windows: the default output's loopback through `soundcard` (the whole mix; per-process loopback needs COM). **Untested**: Windows is not available here. Any failure leaves `Live.why` set and the wall as it was.
- macOS: nothing.

**The analysis** (`Analyser`): one row per 1024-sample hop (46ms). Loudness is the RMS in dB of the newest 2048 samples. Chroma is a 4096-sample frame folded into pitch classes from 80Hz to 5kHz and normalised to its peak, as Spotify's is. 2048 could not split semitones near 220Hz: C# read as C. A beat is a spectral-flux peak above mean + 1 sd of the last 3s, at least 0.28s after the previous one. Tempo is the median gap of the last 17 beats, folded into 70–180. There are no sections and no timbre. `Beat.extend` normalises loudness over the last minute, or a fixed -40..-10dB for the first 40 rows, and a row earlier than the last is a seek back that drops what followed.

**Measured** (synthetic: a chord plus a 60Hz kick every 0.5s):
- Analyser alone: beats at every kick after the first 0.7s, tempo 117.5, chroma C/E/G at 0.96–0.98 with the rest at or under 0.19.
- Own-player tap: a silent `QMediaPlayer` with no audio output, a seek at 3s handled.
- Mixer tap: a test stream of my own at 1% volume (−120dB, inaudible), captured by name: a beat every 0.45–0.51s, tempo 117, chroma A/C#/E. The stream monitor is post-volume, so a muted player gives silence.

**Exit crash.** A `QAudioBufferOutput` destructor calls `setAudioBufferOutput` on its player. Parented to `Live`, it outlived the player at exit and segfaulted about 1 run in 4. It is now the player's child and is `deleteLater`'d on stop: 26 runs out of 26 clean.

## 2026-10-22 — Heap corruption on Windows: two threads in soundcard

The Windows laptop crashed four times in a row (21:43–21:59). Each was `pythonw3.13.exe`, `ntdll`, `0xc0000374` (heap corruption), 1–2 s after a song change while following Spotify or Windows media. Song changes from the own player (the "mine" tap) never crashed. With the visualiser on and no Spotify analysis yet, `steer_live_audio` starts the mixer loopback. It stops it when the analysis lands about a second later, and starts it again at the next song. `stop()` only sets an Event, so the old `_loopback` thread is still inside soundcard when the new one starts. The last stall dump before the 21:59 crash has two threads at `get_microphone` (`live_audio.py:266`) at once. soundcard drives WASAPI as raw COM through cffi and is not thread-safe.

Fix: `SC_LOCK`, held by `_loopback` for the whole recording. A new loopback waits for the old one to close, and gives up if it is stopped while waiting. The soundcard objects are locals of `_loopback_held`, so they die before the lock is released. Checked with a fake soundcard (scratchpad sc_lock_check.py) and twelve start/stop changes 30 ms apart: 1 thread inside at most, and 3 at once without the lock. All threads end. Untested on Windows. A loopback stuck in a silent `record()` would hold the lock, and the visualiser would go quiet rather than crash.

Also found: each crash leaves its `multiprocessing` offload worker running (parent gone, ~20–55 MB each; five on the Windows laptop). Not fixed.

To catch the next one, WER LocalDumps is on for pythonw3.13.exe (minidumps in %LOCALAPPDATA%\mild-lyrics\crash-dumps beside stalls.log, at most 5). Remove the key `HKLM\SOFTWARE\Microsoft\Windows\Windows Error Reporting\LocalDumps\pythonw3.13.exe` when done.

## 2026-10-25 — The heap corruption was soundcard's PROPVARIANT, not two threads

Bug: the window crashed when music played from other sources. On the Windows laptop at 00:24:22 Firefox started playing, the window switched to "Windows media: firefox", and at 00:24:23 `pythonw3.13.exe` died with `0xc0000374` in ntdll. The visualiser was on (`viz` 1.5), so the switch started the mixer loopback. That was the first tap of a process 20 s old, and `SC_LOCK` was in the build, so two threads in soundcard (the 10-22 entry above) cannot have been the cause. The minidump's faulting thread was freeing memory inside an OpenSSL handshake. That thread found the damage; it did not cause it.

**Found with page heap.** soundcard 0.4.6 was installed in a python.org 3.11 venv on the laptop (`%LOCALAPPDATA%\mild-lyrics\probe\scvenv`), with full page heap set for `python.exe` (IFEO `GlobalFlag` 0x02000000, `PageHeapFlags` 3; removed afterwards). The first tap faulted at `mediafoundation.py:375`, `IPropertyStore::GetValue(..., propvariant.ptr)`, whether taps ran on one thread or on many. soundcard's cffi header declares `PROPVARIANT` as `{VARTYPE vt; WORD r1, r2, r3; void *data}`, which is 16 bytes. Windows' PROPVARIANT is 24 bytes on x64. `_PropVariant` allocates `CoTaskMemAlloc(sizeof)` = 16, and GetValue writes 24 into it: 8 bytes past the end on every `.name` and `.channels`. `get_microphone(name)` reads the name of every device, so each tap start wrote past several blocks. Without page heap the damage turns up later, in whichever thread frees nearby memory. Its `__del__` also never freed the block.

**Second fault, same session.** soundcard calls `CoInitializeEx(MTA)` once, on the thread that imports it. Each tap ran on a new thread, so once the first tap's thread had ended, later taps had no apartment: 39 of 40 failed `0x800401f0` (CO_E_NOTINITIALIZED). In the app that is "the output could not be recorded" from the second song on. Calling CoInitializeEx before the import does not help: soundcard treats S_FALSE as an error (`Error 0x100000001`) and the import fails.

Fix: `live_audio.soundcard()` replaces `_PropVariant`'s `__init__`/`__del__` with 24 zeroed bytes that are cleared and then freed. `SC_HOME` runs every soundcard call on one long-lived thread, which does the import first. That replaces `SC_LOCK`, since jobs run one at a time. The loopback is picked by the default speaker's id, not its name. Measured: home thread 40/40 taps recorded, a thread per tap 1/40. Offline: `tests/test_live_audio_home.py` (fake soundcard). On Windows with the fix, under full page heap: 30 starts, no fault, none failed. 13 recorded; the other 17 were stopped before their turn. The unpatched module faulted on its first tap under the same settings. The laptop's app has the fix (backup `live_audio.py.before-propvariant`).

## Lift — 2026-10-25

Docstrings shortened in `mild-lyrics/live_audio.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> The visualiser's analysis, heard live, for songs Spotify has not analysed.
>
> Mild Lyrics' own player has the song, so `whole` analyses all of it
> (audio_analysis.song); until that lands, its decoded audio (QAudioBufferOutput)
> is read as it plays. Another player's sound is recorded off the mixer while it plays: its own
> stream through parec on Linux, the output loopback through soundcard on
> Windows. Nothing is kept; each hop becomes one row of what Beat reads.
> Notes: docs/notes/mild-lyrics/live_audio.md.
