# Still to do

Reported and not yet fixed. Everything here is blocked on evidence rather
than on work: the fault is either on a machine this was not written on, or
on a song nobody has named yet. Each entry says what is known, what would
settle it, and where to start.

Fixed items are not listed. They are in the commit log, which says what the
measurement was.


## QQ Music shows nothing on Windows

**Reported:** with QQ Music as the only source enabled, no lyrics appear.
Two Windows machines. Unknown whether it is the fetch or the drawing.

**Known:** the whole path works from Linux. Asked directly for Clocks, the
search answers, the download returns 5033 bytes, the QRC decrypts, and 29
syllable-timed lines come out. Poker Face, Creep and After Hours the same.
So there is nothing wrong with the endpoints, the DES port or the parser as
such, and nothing in that path is platform-dependent -- it is pure-Python
integers, `zlib`, and `urllib`.

With QQ alone enabled, `provider_order` reduces to `["qq"]`: no blend is
built, because a blend is only asked for when every source it draws on is
switched on and Apple Music would be off. So the walk really is one door.

**Needed:** on the Windows machine,

    python aligner/doctor.py --source qq

That was added for this. It names each step -- search, download, decrypt,
parse, document -- and says which one dies. The four fail differently and
want different answers:

- **search** returns nothing believable: either the endpoint refused the
  request, which on Windows is usually a proxy or a TLS interception in
  front of it, or it answered and no row matched on title, byline and
  length at once (`_qq_hits` wants two of the three).
- **download** returns no bytes: `_get` swallowed an HTTP error. Reachability.
- **decrypt** fails: the payload arrived encrypted and is not the shape
  `_qrc_des` reads. Would be the surprising one.
- **document** is empty: every line was dropped as furniture by `_qq_head`
  or as an instrumental card. That is a parsing question, not a network one.

If every step says OK on Windows too, the fault is downstream of the fetch
and the next place to look is `Fetcher._shaped` and `needs_adlibs`.


## NetEase is passed over for a worse source

**Reported:** NetEase has the better lyrics for a song and something else
gets used.

**Known:** nothing yet, because no song has been named. The pick is
`_walk`'s: `beats()` takes better timing over worse, and between two
documents of equal timing the user's own source order decides, with
`_fullest` stepping in where the better-ranked one is missing a section of
the song. Any of those three could be the one that is wrong here, and they
want different fixes -- an order that is being honoured correctly and simply
is not what was wanted is not a bug at all.

Worth ruling out first: this is not `_ne_rank` picking the wrong RELEASE.
That was checked -- ten songs, every candidate list, and the word-timed copy
came back each time -- and the report is about a different source winning,
not about NetEase answering badly.

**Needed:** one song where it happens. Both documents will already be on
disk under `~/.cache/mild-lyrics/sources/<track id>.json`, so a title is
enough to compare what NetEase said with what won and to see which of the
three rules made the choice.


## Lag in the lyrics on Windows

**Reported:** the lyrics lag on Windows.

**Known:** no obvious culprit. The frame timer already runs at an integer
divisor of the panel's real refresh rate and carries its deadline in float
seconds (`retune_frames`, `_frame`), the background scene is composited at
15fps and blitted at the frame rate (`scene_layer`), the visualizer paints
at a third size for three of its four modes, and a window that is not being
shown drops to `FRAME_IDLE_HZ`.

One thing that is known to be expensive and known to be on: with `rise`
above zero, the line being sung stops using its cached pixmap and draws its
own text every frame (`Flow.draw_base`, `own_text`). That is one line's
worth of glyphs per frame and it is deliberate -- a cached pixmap has every
word on the baseline, and cutting the lifted word out of it bit the
neighbouring glyphs -- but it is the first thing to measure.

**Needed:** two readings.

1. Does it still lag with `--viz 0 --bg none --glow 0 --rise 0`? That
   separates paint cost from everything the background does.
2. Does it lag in a window as well as fullscreen? That separates paint cost
   from compositing.

If it is the paint, the next step is a frame-time readout rather than a
guess: mean and 95th percentile of `paintEvent`, drawn in a corner behind a
flag.


## A better picture in the vocal view

**Reported:** the spectrogram itself is not readable enough to time against.

**Known:** the picture is `vocalmap.VocalMap.image` -- a mel spectrogram of
the demucs vocal, one column per 10ms, windowed on the song's own 40th and
99.5th percentiles and gamma'd at 1.35 so the quiet detail stays down. The
strip zooms on the wheel (`Wave.zoom`) and that zoom is horizontal only.
There is no control over the contrast, no way to look at part of the
frequency range, and the picture is drawn from one fixed ramp.

**Needed:** which of these is actually in the way -- zoom, frequency range,
contrast, or scrubbing the playhead against it. They are four different
pieces of work and the fourth is the only one that is not just drawing.


## Loose ends

- `aligner/&1` is a stray file from a mistyped shell redirect. It is not
  in the repo and nothing reads it; it can go.
- Four test files fail to import when run from the repository root --
  `test_aligner.py`, `test_anchor.py`, `test_syllables.py`, `test_voice.py`
  -- because they put `aligner/` on `sys.path` in a way that does not
  survive the working directory. `test_offset.py` fails on a fixture path
  under a scratch directory that no longer exists. None of these are
  regressions; they were failing the same way before this batch of work.
