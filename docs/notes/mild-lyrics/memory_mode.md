# `mild-lyrics/memory_mode.py` — Memory use

## 2026-10-16 — the setting

Storage → **Memory use**: auto / low / normal / more. Auto is low on a machine with 8GB of RAM or less (`total_ram`: sysconf, GlobalMemoryStatusEx on Windows) and normal otherwise; the drawer shows its pick ("auto · normal"). It is machine-specific, so it is in SHARE_SKIP. `LyricsView.apply_memory` puts a profile in force at once, except for the offload worker count, which is read in `main()` before `offload.warm()`. Workers are forked while the process has one thread (see offload.py), so the count cannot change later.

| | low | normal | more |
|---|---|---|---|
| animated cover | `MotionStream`: read off disk ~3 frames ahead | frames held, 192MB budget | frames held, 512MB budget |
| next album's animation | — | — | decoded while the track before plays (`motion_ahead`, up to Fetch ahead) |
| drawn lines / glows | 32 / 8MB | 96 / 16MB | 256 / 48MB |
| word pictures / still cards / thumbnails | 4 / 8 / 12MB | 8 / 16 / 32MB | 32 / 64 / 96MB |
| offload workers | 1 | 2 | 2 |
| Sudachi + kakasi hot entries | let go after 5 min unused | kept | kept |
| malloc_trim | every 30s, plus track changes | track changes | track changes |

Normal is what the player did before the setting existed, apart from the fixes below.

**Measured** (real window offscreen, real-use settings, cap 486 = a 1080p screen; scripts in the session scratchpad `mem/mode_run.py`):

    Linkin Park, The Hunting Party (300 frames on disk)
      low     stream, 300 frames, 30 fps   +8MB    first frame after 50ms
      normal  150 frames, 15 fps           +136MB  520ms
      more    300 frames, 30 fps           +272MB  1021ms (0ms when decoded ahead)
    My Chemical Romance, Three Cheers (105 frames)
      low +8MB, normal +51MB, more +53MB; all 30 fps

Streaming costs no measurable CPU against held frames: the whole offscreen process was at 71% of a core in low and 78% in normal over the same 4s, and `motion_frame()` takes 0.025ms against 0.014ms. Decoding one frame (720px JPEG, smooth scale to 486) takes 1.8ms on the stream's thread. When a frame is not ready in time, the last one stays up.

**Fixes that apply to every mode:**
- `MotionArt._work` kept the last album's decoded frames in its locals while it waited for the next job. After an animated album, its frames (720px, up to ~190MB) stayed alive until the next album with an animation was decoded. The per-album work now runs in `_job`, so the frames die with that frame of the call stack. A test in test_memory_mode.py covers it.
- Frames are decoded no wider than the cap on the worker (`motion_stream.decode`), not at 720px and scaled on the GUI thread. That halves the peak while a cover loads. The look (wall, palette) is still taken from the middle frame at full size.

The "more" decode-ahead runs only while nothing is waiting in MotionArt's queue (`_next`). An album asked for while its decode-ahead is still running is sent once, when that finishes (`_promote`). Only Spotify queues are visible, so only they are decoded ahead.

Releasing Sudachi lets its ~80MB dictionary mapping go; it comes back on the next Japanese line in ~30ms. Released under `_SUDACHI_LOCK`, so a tokenisation in progress keeps its own reference.

## 2026-10-17 — what the floor is made of

A real-use player at 42s, low mode: 414MB resident, 240MB proportional (Pss); 153MB of the resident figure is library pages shared with other processes. A malloc tracker (LD_PRELOAD, live bytes by first caller outside libc; session scratchpad `mem/mtrack`), run on the real window in a headless KWin with the GL canvas:

    Qt images (the player's pictures)        12-29MB
    NVIDIA EGL driver                        25MB, plus a CPU copy of each uploaded texture
    Python (large objects)                   11MB; small objects and code sit in its own arenas, ~30MB in all

GPU drawing against CPU drawing, headless Wayland at 1080p: about 330MB against 190MB resident. The NVIDIA and Mesa GL stacks plus driver buffers are ~140MB. They chose to keep GPU drawing in low mode (2026-10-17).

Cut:
- **Image plugins.** `loadFromData` with no format makes Qt load every image plugin to ask (AVIF, HEIF, JXL, EXR, RAW and their codecs): +11MB, measured with one JPEG. `image_format()` names JPG/PNG/GIF/WEBP from the first bytes; anything else still asks.
- **Vignette.** `fade_layer` is one column on the GPU, stretched across by `_paint_fade`: it only changes downwards. 8MB less at 1080p, plus the driver's copy.
- **Scene.** `scene_div` builds the wall at half size on the GPU, and `_paint_scene` filters it up. Through Qt's GL paint engine at 1920x1080, full size against half: veil (their style) identical, blobs ≤2/255, wash ≤1/255, art wall ≤4/255 at bg_dim 0 (p99.9 ≤2). 6MB less at 1080p, plus the driver's copy, and a quarter of the pixels per rebuild.

Not cut, after measuring:
- Restricting EGL to NVIDIA's vendor file (`__EGL_VENDOR_LIBRARY_FILENAMES`) keeps Mesa's LLVM and gallium out: 10-17MB of shared pages, no private memory. Not worth breaking other machines.
- KDE's platform theme (28 KF6 libraries) is ~16MB of shared pages and a few MB of its own; replacing it changes how dialogs look.
- `-OO` (no docstrings) saves 2MB on import, and several entry points print `__doc__`.

## 2026-10-17 — minimal: a ceiling of own memory

Goal: never above 150MB, aiming at 100MB or under. **Own memory** is what only the player holds: Private_Clean + Private_Dirty from `smaps_rollup`, summed over the player and its child processes (`MM.own_memory`; PrivateUsage on Windows, phys_footprint on macOS, resident where neither can be read). A bare PyQt6 window at 1080p on Wayland is already 103MB resident, ~70MB of it shared Qt and Python libraries, so a resident target was never reachable. The overlay shows both figures: `memory 96 MB own · 184 resident (minimal)`.

What minimal does, and what it costs:
- **CPU drawing** whatever GPU drawing says (`gpu_wanted`; the drawer reads "auto · CPU (memory minimal)"). The GL stack is ~140MB. Paint at 1080p on the CPU: median 10.4ms, p95 12.8ms.
- **No waiting workers.** `offload` starts a fresh `python -I` (the zygote, 4.5MB own, flat after 21 jobs). Each job gets a forked child that imports what it needs (40-85ms), answers over a socketpair handed across with `send_fds`, and exits. Fresh rather than forked from the player: a fork would come to own every page the player later changes. A job from `lyrics_gui` itself (`estimate_from`, 15-41ms) runs in the window, since importing it in a job would load Qt. The zygote starts live; leaving minimal live runs jobs in the window until the next launch ("workers after restart").
- **No Sudachi.** It is ~80MB resident the moment it loads, so even inside a job it would put the total at ~185MB. Japanese is read by pykakasi's packed table, let go with `release_readers(deep=True)` (the packed dict too, read back from its cache file on the next line).
- **Animated cover streamed, and only while drawn.** `MS.AHEAD` is 1. A stream not read by `motion_frame` for 2s is parked (`park_motion`; the look stays) and asked for again when it is drawn. The full-size middle frame is dropped once the look is made (all modes).
- **Pictures.** Flat walls (veil, solid, clear) are one pixel, laid as a fill. Other walls are half size, filtered up (+0.65ms a frame on the CPU). The art wall's glow is a quarter size, the vignette one column. Raster, normal vs minimal at 1920x1080: flat walls identical, blobs ≤2/255, art ≤4/255 (5/255 on 0.02% of pixels at bg_dim 0). Caches: pix 6, glow 1, words 1, still 2, thumbs 4MB.
- **Slack.** `M_ARENA_MAX` 2 before threads start; a trim every 2s; `linecache` cleared; `MotionArt._known` read per job.
- **The watchdog** (`hold_ceiling`, every 2s): over 100MB trim; over 120 drop the pixmap, glow, word and thumbnail caches; over 135 park the cover, release the readers, drop the outgoing wall; over 150 all of it, and say so once. Each new stage goes to follow.log once.

All modes: `caches._audio_dir` no longer imports `local_align` to ask for a path (3.6MB at startup). The drawer's dropdown shows what auto came to, as the segments do.

**Measured** (headless KWin, real window 1920x1052, real-use settings: art wall, veil; a scripted session — English, Japanese, a 105-frame cover, window hidden 15s, a 300-frame cover; own memory every 0.5s for 112s):

    minimal   own max 111MB, median 96, p90 108, min 77; resident max 214
    low       own max 284MB, median 237 (GPU canvas, Sudachi kept 5 min)

In minimal, the Japanese song cost +25MB at its peak, which settled to +13. An animated cover cost +14 at its peak, and hiding the window let it go (91MB). The watchdog reached stage 1 only (trim).

Not done: the Plugins tab (`market_tab` + `plugin_store`, ~5MB) is still built at startup. Without it, a plugin install's questions would fall back to system dialogs.

## 2026-10-17 — minimal: lines flickering in a big window, and switching in live

**Flicker.** They saw lines flicker in minimal "when the resolution is high enough". The 6MB line-picture budget holds 13 pictures at 1920x1080 (37 at 1000x700), fewer than the column draws in one frame. So each new picture evicted one about to be drawn, and with two to four builds allowed per frame, `_nearest_blur` filled in from other blur levels. Counted offscreen over 12s: 172 of 349 frames drew a line at the wrong blur level (low: 1 of 514).

`shed_pixmaps` now never evicts a picture drawn in this frame or the last one (`_pix_now`, `_pix_last`, swapped where the per-frame budgets are reset), so the budget is a floor under what is on screen, not a cap through it. After: 1 frame out of 417 at 1920x1080 and 1 of 243 at 3840x1080, that one being the resize. The cache holds 8MB at 1080p and 12MB at 3840x1080. The watchdog's second stage sheds the same way. It used to clear the whole cache every 2s, and over 120MB that would have flickered on its own.

**Switching into minimal live.** From normal with GPU drawing, own memory stayed at ~220MB after the switch against 115 for a fresh start. The difference is all the GL driver. With the canvas gone, Qt's Wayland EGL display stays initialised until the process exits, and with it NVIDIA's `nvidiactl` mapping (30MB), +52MB of driver heap and an extra thread. The same switch with GPU drawing off lands at 112. So `apply_memory` restarts the player into minimal (`restart_lean`, the updater's `UP.restart`, settings saved first, `--memory minimal` passed explicitly so a launch flag cannot undo it). This happens only when this process ever made the canvas (`_gl_loaded`); otherwise the switch stays live.

## 2026-10-17 — minimal: the ceiling hit over and over in a long session

Reported after about an hour in minimal: the 150MB toast again and again. follow.log showed own memory under 100MB while the editor was linked. Once the player went back to fetching for Spotify it sat at 135-148, and every quick run through the queue pushed it to 150-160. An in-process report (`memory/bench/inspect_live.py`, run through `sys.remote_exec`) gave: C heap 93MB with 56 in use, and anonymous memory 57MB (a fresh start has 36 and 34).

Reproduced offscreen by cycling 100 cached tracks with covers through the real fetch path, with the network blocked (`scratchpad mem/cycle.py`): own 74 → 170MB. Python's own allocations grew only 27 → 40MB (tracemalloc), so the rest was native. Releasing each cache in turn at the end: line pictures 20MB, tints 2.4MB, everything else under 1MB. Even with all of them gone, own stayed at 146MB with the heap in use back at its startup size and 52MB of heap free but not returned.

- **Line pictures.** The flicker fix (never shed what was drawn in the last two frames) made the column's real working set the floor: at their blur 0.1, every line is drawn sharp and again at blur 1 for the cross-fade, about 17 pictures and 19MB at 1080p. In minimal a blurred picture is now kept at `soft_scale`'s last stage, but only when that stage is an exact half; drawing it at its logical size does the same 2x smooth enlarge. `_pad_of` reads the logical width. Glow pictures stay whole, since `_glow_strip` cuts them by pixel. Measured: 9.3 → 5.9MB in a frame. The pixel difference sits within the frame-to-frame noise of the springs (0.035% of pixels >3/255 more than an identical control).
- **Tints.** `Renderer._TINTS` was capped at 256 pictures, keyed by the glow picture's cacheKey. Minimal's 1MB glow cache churns, so it filled with tints of glows that no longer exist (6.2MB). It is now held to `TINT_BYTES` (the glow budget), and the watchdog's second stage drops it.
- **Fragmentation.** glibc's mmap threshold climbs to the largest block freed, so picture buffers of a few MB landed in the heap among small long-lived blocks. Minimal pins `M_MMAP_THRESHOLD` at 256KB (`MM.mmap_threshold`, at launch and on switching in): every picture gets its own mapping, given back when freed. Paint cost was within noise in the final run (median 10.69ms both ways; an earlier run alone measured +0.7ms).
- **The watchdog.** A dip from stage 4 to 3 and back counted as a new stage and toasted again. Stages now count down only under 120MB, and the ceiling is said once a session.
- **pypinyin.** It loads ~45MB of dicts (600k objects) on the first Chinese song and kept them. Minimal's deep release now drops its modules and `editor.syllables._zh_phrases`. The load still spikes own to ~200MB during a Chinese song, and leaves ~20MB of Python allocator fragmentation after. Not solved here; see TODO.

After all of it, the same 100 tracks: 116MB at song 20 and 131 at 40 (including the harness's own 7.9MB render target). Before: 138 and 147.

## 2026-10-17 — minimal: readings in a job

Decided after the above: read a song in one pass and let the readers go with it. In minimal (`SL.READ_IN_JOB`), `SL.timeline` sends any song whose lines have kana or Han to `offload.call(_timeline_job, …)`. It passes `SUDACHI_OFF` along, since a fresh process would otherwise load Sudachi (one did: 159MB). The job builds the whole timeline and exits. Every player caller (fetch, ahead, dropped files, rebuilds) goes through `timeline`, so pypinyin and pykakasi's table never load in the window for it. Furigana in the layout (`SL.ruby(…, ("ja",))`) still uses pykakasi here and releases it as before.

Measured, against the same songs read in-process (equal results on all four): 182-204ms per song in the job, while in-process cold is 138ms and warm 2-4ms. While the job runs, own memory is +57MB for Chinese and +33MB for Japanese, gone when it exits. `hold_ceiling` skips a check that lands while a job runs (`offload.busy()`), so that brief rise is not shed against.

The 100-track cycle, which includes the Chinese song that took own memory to 199MB: 135MB at song 40, 132 at 60, 136 at 100, flat (the harness's 7.9MB render target included). pypinyin was never in the player's modules.
