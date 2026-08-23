# `aligner/build_dataset.py`

Comments lifted out of `aligner/build_dataset.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

**line 50** — before `MIN_CLIP = 0.6`

> A clip shorter than this is not worth a training step, and one longer than
> this is a line the reference has mistimed -- either way it is dropped rather
> than taught.

**line 55** — before `CLIP_PAD = 0.15`

> Room around the line, because a reference marks where a word STARTS and the
> last one has to finish somewhere.

**line 86** — before `OFFSETS = LS.cache_root() / "offsets.json"`

> Displacements MEASURED against each song's reference, written by the
> benchmark. Below this there is nothing worth moving.

**line 89** — before `COMMUNITY = "spl"`

> The source tag on a cached document that means somebody uploaded it.


## `right_song`

**line 167** — before `return True, f"could not listen ({LA.heard.why})"`

> Could not listen is not evidence of anything. Keep the song.

**line 180** — before `return True, f"nothing to compare against (songs it is not scored {n*100:.0f}%)"`

> Nothing in common with the decoys means a different language, not a
> different recording: two Japanese songs scored nulls of exactly 0%
> and would have been thrown out of the dataset for it.


## `main`

**line 217** — before `import random`

> Four songs to compare every transcript against. Any four will do -- they
> only have to be songs the audio is NOT -- so they are taken from the front
> of the cache and reused for every check.

**line 253** — before `if str(doc.get("source") or "") != COMMUNITY:`

> Community uploads only.
>
> The cache holds three kinds: `spl`, contributed to Spicy Lyrics
> by people; `aml`, Apple Music's own word-synced lyrics; and
> `spt`. Of the 376 word-synced documents here, 227 are spl and
> 149 are aml, and nothing used to tell them apart -- 40% of the
> clips this cut were audio paired with Apple's timings.
>
> TTMLUploadMetadata agrees exactly, 227 to 227, so `source` is
> not being trusted on its own.

**line 292** — before `mono = LA._resample(LA._channels(stem, 1), srate, LA.RATE)[0]`

> Mono at the model's own rate, which is what the clips are
> stored as: nothing downstream wants anything else, and a
> stereo 44.1k copy of every song is forty times the disk.

**line 302** — before `lag = float(offsets.get(f"{meta['artist']} - {meta['title']}", 0.0))`

> Where this copy sits against the timings the clips are cut
> on. See measured_offsets: a song with no measurement is left
> exactly where it was, which is what every song used to get.
