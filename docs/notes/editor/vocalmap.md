# `editor/vocalmap.py`

Comments lifted out of `editor/vocalmap.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

**line 66** — before `FLOOR = 0.45`

> How strong a flux peak has to be to count as a place a word could start.
> `vocal.PEAK` is 0.25, which is right for its own job -- measuring a whole
> song's standing bias, where more attacks is more votes and a wrong one costs
> nothing. Here a wrong one moves a word. At 0.25 the spread against the hand
> timings is 0.023 s and chance is 0.026: no signal at all. This is where the
> measurement in the docstring holds up.

**line 74** — before `ALIVE = 0.90`

> Where the vocal is loud enough to be singing rather than a reverb tail.
> `vocal.activity` is a soft 0..1 and its own -38 dB floor is generous by
> design; this reads the top of that curve, so an edge is a real entrance.

**line 78** — on `JOIN = 0.06`

> gaps in the activity shorter than this are not gaps

**line 79** — before `ALONE = 0.15`

> How far from a mark of a better kind a note has to be to be worth offering
> as a start of its own. The reach `ops.from_first` searches in, because that
> is the distance at which one mark can stand in for another.

**line 83** — on `LEAST = 0.08`

> and runs shorter than this are not entrances

**line 119** — before `BLENDS_KEPT = 4`

> How many rendered blends one song keeps. The slider settles somewhere and
> stays there, so the only ones worth holding are the last few positions --
> and the two that matter most, the mixture and the stem alone, are never
> rendered at all. Both ends of the slider are files that already exist.


## `blend`

**line 162** — before `if mix.shape[0] != voc.shape[0]:`

> Demucs works in stereo and plenty of songs here are not, so the two
> can disagree about how many channels they have even though they agree
> about every sample in them.

**line 175** — before `peak = float(got.abs().max())`

> The sum can clip where the vocal was loud to begin with. Scaling the
> whole file by one number keeps the balance that was asked for; limiting
> would not, and a limiter's pumping is exactly the kind of thing a
> person listens THROUGH when they are trying to hear a consonant.


## `_keep_stem`

**line 211** — before `_prune_blends(path, keep=None)`

> Whatever was mixed from an older separation is not this one.


## `VocalMap.__init__`

**line 242** — on `        self.mel = mel`

> (fine frames, 80) float32, for drawing

**line 243** — on `        self.pitch = pitch`

> (fine frames,) Hz or NaN, for notes

**line 244** — on `        self.present = present`

> (frames,) 0..1

**line 245** — on `        self.onset = onset`

> (frames,) 0..1


## `VocalMap.build`

**line 282** — before `_keep_stem(path, sep, srate, tell)`

> Kept as audio as well as as a picture. Everything below throws
> the stem away and keeps what can be drawn from it, which was
> right while the vocal was only ever looked at -- and it is the
> separation, the expensive half, that would have to be done
> again to hear it. See `stem_path`.

**line 293** — before `pitch = vocal.pitch(mono).numpy()`

> Cheap next to everything above it -- a third of a second for a
> three-minute song, against half a minute for the separation -- and
> it is what a chopped vocal has instead of attacks. See `notes`.

**line 302** — before `np.savez_compressed(store, mel=mel.astype("float16"),`

> float16 for the picture: it is displayed, never measured, and
> half the bytes of a four-minute song is worth more than a
> precision nothing here can see.


## `VocalMap.marks`

**line 430** — before `held = sorted(starts)`

> ...and the notes, last, and only where there is nothing else. Not
> `JOIN` this time but `ALONE`, which is the radius anything reading
> these searches in: a note a tenth of a second from an attack is not
> a second event worth offering, it is a worse answer to a question
> already answered, and offering it costs three points of words in
> `ops.from_first` for nothing. Where the flux is silent -- a chopped
> vocal, a held note re-struck -- every note survives this, which is
> the case they were added for.


## `VocalMap`

**line 452** — before `AGREE = 25.0`

> How many points of separation between "the document says somebody is
> singing here" and "the document says nobody is" before the audio is
> believed to be this document's song. Measured: the right recording of
> `MaKE ME FAMOUSS >_<` scores +69, and a 212-second recording opened
> against the same 103-second document scores -7. There is no sensible
> threshold between those two that is hard to choose.


## `VocalMap.agrees`

**line 504** — before `lead = abs((got["heard"] if got["heard"] is not None else 0.0)`

> A document with no rests in it cannot be checked this way. The
> lead-in is the fallback: a lyric that starts singing thirteen
> seconds in, over audio that starts singing at half a second, is
> not that audio's lyric.


## `VocalMap.image`

**line 559** — on `        v = v ** gamma`

> hold the quiet detail down

**line 562** — before `pic = np.ascontiguousarray(lut[idx.T[::-1]])`

> (frames, bands) -> (bands, frames), then flipped so band 0 is the
> bottom row, which is what everybody expects a spectrogram to do.

**line 567** — on `        return img.copy()`

> own the bytes; `pic` is local


## `VocalMap`

**line 580** — before `FLUX_FLOOR = 25`

> How wide the neighbourhood is that a flux peak has to stand out FROM,
> in mel columns of 10 ms. A quarter of a second either way: long enough
> to cover a syllable and its neighbours, short enough that a loud bar
> does not raise the floor under a quiet one.


## `VocalMap.flux`

**line 629** — before `win = np.lib.stride_tricks.sliding_window_view(pad, 2 * k + 1)`

> A sliding median, done as a stride trick rather than a loop: a
> four-minute song is 24,000 columns and the loop was the slowest
> thing in the strip.

**line 634** — before `floor = float(np.median(got))`

> Floored at its own median and topped at its 99th, so the trace sits
> on the baseline where nothing is happening instead of drawing the
> noise. The measurement in the docstring is what says this is the
> right floor: a hand-placed word start is 3.4 times the MEDIAN of
> this signal, so the median is the height below which it has nothing
> to say. Without it every column had something on it and the peaks
> were lost in the fur.

**line 645** — before `self._flux = np.concatenate([out[:1], out])`

> One column shorter than the picture, being a difference. Pad the
> front so column i of the trace is column i of the image.
