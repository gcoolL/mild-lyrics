# `editor/vocalmap.py`

Comments lifted out of `editor/vocalmap.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).



## 2026-10-26 — The mixture picture's settings, measured

Score: the AUC of the drawn picture's rise (40ms after against 40ms before, half-wave, mean over the bands shown, best within ±20ms) at hand-placed lead syllable starts, against every third frame of the lyric span (0.5 is chance). Seven songs with local audio and a word-timed TTML, each shifted by its own best fit first. Three more pairs were dropped as different cuts (best AUC ≤ 0.55, one at the edge of the ±1.5s shift range).

| | 1-Step | Inside | Run | FlyNG | scriber | doggirl | 115 | mean |
|---|---|---|---|---|---|---|---|---|
| as built and drawn now | .790 | .833 | .694 | .652 | .747 | .631 | .752 | .728 |

Generation variants changed it by 0.02 at most and lost on most songs: f_max 11 kHz, a 16ms window, per-band median whitening, and the combinations of these. The drawing defaults are at the best point as well. Floor p20/p60/p70 gave .731/.721/.715, gamma 0.8/2.5 gave .727/.720, and cutting below 150/300 Hz gave .721/.719 (300-4000 Hz .715, 1000-7600 Hz .702). The settings are not what limits the picture; the mix is. On doggirl the cached vocal stem scored .654 against the mixture's .631, through the same picture. Part of any mixture score is the drums: in rhythmic songs syllables land on hits. Scripts: `evalspec.py`, `evaldisp.py`, `evalstem.py` (bench).

## 2026-10-17 — Spectrogram without a separated vocal

Vocal ▸ Spectrogram draws the MIXTURE's mel behind the words, for people
without torch/demucs or who do not want to wait for a separation.
`VocalMap.mixture` builds it with numpy and soundfile only (ffmpeg fallback
for other formats), cached as `<key>-spec.npz` beside the stem map, so
"Separate again" (`forget`) drops it too.

No resampler: the file is read at its own rate with the 25 ms window and
10 ms hop scaled to that rate, so the FFT bins land 40 Hz apart as they do at
16 kHz, and the per-song normalisation takes out the scale that changes.
Against `audio.mel(audio.mono16k(...))` on a 2-minute FLAC at 44.1 kHz: same
12289 frames, correlation 0.998, ±1 frame shift drops it to 0.94 (aligned);
0.6 s and a 45 MB peak.

It lives in `wave.spec`, not `wave.vocal`: everything that reads
`wave.vocal` (marks, claims, "What it says…", From the first word, the mix
slider) means the separated stem. The strip draws the picture and nothing on
it — no flux trace and no marks, because on the mixture the attacks sit near
chance (see the module docstring). Spectrogram and Vocal view switch each
other off.

## 2026-10-16 — your own separated vocal

`VocalMap.build(path, own=...)` takes a vocal somebody already has (a stem
pack, UVR, the artist's) in place of `separate.vocal`; everything after it
starts from a wave, so the mel, activity, onsets, pitch, the kept stem and the
mix slider are unchanged. It has to be the same cut: lengths within
`OWN_SLACK` (0.5s) or it is refused, since every mark would be out by the
gap. It is resampled to the song's rate when kept, so `blend` can stream it.
The `.npz` carries `own=1`; a kept map is read back and never replaced by a
demucs run unasked ("Separate again" in the Vocal group asks for one, via
`forget`). `find_own` picks up "<song> (Vocals).flac", "<song>_vocals.wav"
and the like beside the song or in a `stems` folder there, when no map is
kept yet. `stem.available(separate=False)` does not ask for demucs.
Test: `test_own_vocal.py`.

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

## Lift — 2026-10-25

Docstrings shortened in `editor/vocalmap.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> The separated vocal: a picture, a list of places a word could start, and
> the stem itself to listen to.
>
> The third of those is the newest and the plainest. Everything below measures
> the vocal and draws what it measured; `stem_path` and `blend` just hand it
> back as audio, so a person timing by hand can take the band out of their ears
> instead of reading it off a spectrogram. Half speed is called the single most
> useful thing there is for placing syllables by hand -- it gives the ear more
> of the consonant to aim at -- and turning the drums down does the same job
> from the other side. The two compose. See Editor._vocal_mix for the control.
>
> WHY A SPECTROGRAM HERE AND NOT IN `waveform`. That module says, correctly,
> that a picture of the MIXTURE invites snapping to the wrong thing: the loudest
> attack in a bar is a snare, and hand-placed word starts do not sit on snares. Measured
> on `ToxiPlays, Hypertoxicated - MaKE ME FAMOUSS >_<`, 251 hand-placed word
> starts against the spectral flux of the same audio:
>
>     mixture   median -0.018 s,  spread 0.070 s   (chance spread 0.098 s)
>     stem      median -0.028 s,  spread 0.040 s   (chance spread 0.060 s)
>
> The `chance spread` column is the same statistic with the document slid half a
> second to a second and a half either way, which is what "the attacks are so
> dense that everything hits one" looks like. On the mixture the true figure is
> most of the way to chance and the picture really is not worth tracing. On the
> demucs vocal it is two thirds of it, and consistently -- so the stem's attacks
> DO know something about where this file's words are, and the mixture's very
> nearly do not. That difference is the whole reason this module separates
> first.
>
> WHAT IT IS STILL NOT. A spread of 0.040 s is not a placement. It is enough to
> say that a word sitting 0.2 s from every attack in earshot is in the wrong
> place, and nowhere near enough to justify moving a word that is already within
> about 0.05 s of one. Snapping to these was built and then removed on the
> evidence; `ops.consistency` measures what is left and `ops.claims` decides
> which marks are readable at all. Nothing here ever returns a time on its own.
>
> THE THREE KINDS OF LANDMARK, in the order they are trusted:
>
>   * an ACTIVITY edge -- the vocal starting after real silence, or stopping.
>     Unambiguous when it happens, and on a dense rapped song it hardly ever
>     happens: this one is 81% sung and yields nine of them.
>   * a FLUX attack -- energy arriving in the mel spectrum. Always available,
>     which is the problem: at the floor `vocal.attacks` uses for calibration
>     there are 7.6 a second and a nearest-attack match means nothing. `FLOOR`
>     below is set where the measurement above still shows signal.
>   * a NOTE onset -- the pitch stepping, or voicing resuming. The one that
>     reads a chopped vocal, which has no edges and no attacks and is most of
>     what a drop is made of; see `VocalMap.notes` for what it is worth where
>     the other two fail and where they do not.
>
> Everything is on `audio.FRAME`, the 20 ms grid the rest of the project reports
> times on.

### `stem_path`

**line 101** — from the docstring, `def stem_path(path: str) -> pathlib.Path:`

> Where this song's separated vocal is kept as AUDIO, not as a picture.
>
> The map beside it is a spectrogram and three curves -- enough to draw the
> vocal and to say where it starts things, and not a thing you can listen
> to. Timing by hand wants the other one: the mixture's drums land on the
> beat and the singer does not, so a word start that is inaudible under a
> full mix is obvious on the stem alone. See `blend`, and Editor._vocal_mix
> for the control.
>
> FLAC rather than WAV. It is exact, every path this editor already opens
> accepts it (see app.AUDIO), and it is about half the bytes -- which is
> the difference between a cache somebody notices and one they do not.

### `blend`

**line 114** — from the docstring, `def blend(path: str, level: float, say=None) -> str:`

> The song with its vocal at `level`, as a file to play. 0..1.
>
> 0 is the mixture untouched and 1 is the stem by itself. In between, the
> backing is what is left when the vocal is taken out of the mixture --
> `mix - stem`, which is exact by construction and needs no second
> separation -- and it is turned down by `level`:
>
>     out = stem + (mix - stem) * (1 - level)
>
> so 0 really is the file that was opened, sample for sample, and not a
> re-encode of it that drifts a frame. Neither end is rendered: both are
> already on disk.

### `_blend_streamed`

**line 198** — from the docstring, `def _blend_streamed(path, stem, level: float, tmp) -> bool:`

> Write the blend without holding the song: True if that was possible.
>
> The whole-song way holds the vocal, the mixture, their difference, a
> scaled copy, its absolute value and a transposed copy at once -- about
> 400MB for four minutes. This reads the two files twice instead, once for
> the loudest sample (the mix is scaled down if it would clip, and that
> needs the whole of it) and once to write, and holds one block. It does
> not attempt what needs the whole song at once, which is a mixture at a
> different sample rate, or one soundfile cannot open at all; those return
> False and are done the long way.

### `_keep_stem`

**line 224** — from the docstring, `def _keep_stem(path: str, sep, srate: int, tell=None) -> None:`

> Write the separated vocal out beside its map.
>
> Quietly. A song whose picture came out fine but whose stem could not be
> written -- a full disk, a cache directory somebody has made read-only --
> still has a vocal view, and the mix control is simply not offered for it;
> that is a better answer than refusing the view over the half of the job
> that was not asked for.

### `VocalMap._read`

**line 451** — from the docstring, `def _read(cls, store: pathlib.Path, stems: bool,`

> Read a kept map back, or refuse it if it is missing a part.
>
> A map written before there was a pitch track cannot have one added,
> and one written before the stem was kept cannot be listened to:
> either way what is missing was measured from audio this file does not
> hold. Raising here puts the song through `build` again, which costs a
> separation once and then never again -- which is better than a song
> quietly having half the marks, or half the modes, that every other
> song has.

### `VocalMap.notes`

**line 491** — from the docstring, `def notes(self) -> list[float]:`

> Where the singing changes note: the times a chop or a word starts.
>
> THE THIRD KIND OF LANDMARK, and the one that answers for the material
> the other two cannot read. An activity edge needs the vocal to stop; a
> flux attack needs energy to arrive. A chopped vocal lead -- the
> singer's own voice cut into sixteenths and pitched up, which is how
> half the drops in this folder are built -- does neither: it runs
> continuously, so there is no edge, and each chop is spliced onto the
> last at the same level, so there is no attack.
>
> What it does do is change PITCH, every chop. Measured on `Conro -
> Therapy`, whose first chorus had been timed by hand and whose drop is
> the same material:
>
>                          nearest mark   within 50ms   chance
>     chopped chorus
>       flux attacks           0.060s         43%       0.088s
>       note onsets            0.042s         58%       0.056s
>       both                   0.024s         77%       0.038s
>     sung verses
>       flux attacks           0.010s         71%       0.075s
>       both                   0.005s         84%       0.052s
>
> So on the material that was failing it roughly doubles the syllables
> that land where they belong, and on ordinary singing -- where the flux
> was already good -- it still helps rather than getting in the way.
>
> Those figures are for every note this finds. `marks` passes on fewer:
> one only where no better mark is within `ALONE`, which on that song
> leaves 172 of 425 and takes the chorus from 68% to 57%. That is the
> price of not moving `ops.from_first`, which the full set costs three
> points of words -- and the strip draws what `marks` passes on rather
> than everything found here, so a tick on screen is a tick the walk
> can also use.

### `VocalMap.marks`

**line 501** — from the docstring, `def marks(self, floor: float = FLOOR) -> dict:`

> `{"starts": [...], "ends": [...]}` -- every landmark, in seconds.
>
> A start is an activity entrance, a flux attack or a note onset, in
> that order of trust, and each one that lands within `JOIN` of a mark
> already found is dropped as the same event heard a second way.
> `notes` is also handed back on its own, because the strip draws it
> differently: it is the weakest of the three and the one most worth
> being able to tell apart by eye.
>
> Ends are activity exits only. Nothing in the flux says a word STOPPED
> -- half-wave rectification threw that away on purpose, back in
> `vocal.onsets` -- and a note ending is where the next one begins, so
> an end has no second-best source and simply is not offered where the
> singing does not stop.

### `VocalMap.agrees`

**line 529** — from the docstring, `def agrees(self, spans: list[tuple[float, float]]) -> dict:`

> Whether this audio is plausibly the song `spans` was timed against.
>
> WHY THIS EXISTS. The view will happily separate whatever audio the
> window has open and draw it behind whatever document is loaded, and
> the two have no reason to be the same song. That is not a hypothetical
> -- it is how this was first used: a 212-second recording behind a
> 103-second lyric, every mark landing somewhere arbitrary, and nothing
> anywhere saying so. A picture that is confidently wrong is worse than
> no picture, because the whole point of it is to be believed.
>
> The test is the one thing a lyric knows about audio without knowing
> the words: WHEN NOBODY IS SINGING. Take the frames the document says
> are inside a rest and the frames it says are inside a word, and ask
> how much likelier the vocal is to be sounding in the second than the
> first. On the right recording that gap is enormous. On the wrong one
> it is nothing, and it stays nothing however the two are slid about,
> which is why this beats correlating the two masks -- both are on most
> of the time, so their overlap is high whatever you do to it.
>
> Only the document's own span is looked at, so a song with a long
> outro nobody has timed is not held against it.

### `VocalMap.image`

**line 576** — from the docstring, `def image(self, ramp=((20, 22, 28), (91, 140, 255), (233, 234, 238)),`

> The mel as a coloured QImage, one column per 10 ms, low band at the
> bottom.
>
> `audio.mel` is already normalised per song -- its own mean and spread
> taken out -- but that is not the same as being FRAMED. The values it
> produces are lopsided: this song's bottom fifth of pixels sit in the
> 1e-6 log floor and its top thousandth reach 2.0, so a symmetric window
> spends most of its brightness on the quiet half and the picture comes
> out a flat wash. The window is taken from the song's own percentiles
> instead, which puts the median down near the background and leaves the
> top of the ramp for the formants -- the part somebody is looking at.
>
> The ramp is applied here, in numpy, rather than by compositing a tint
> over a grey image in the widget. Painting the picture inside
> `paintEvent` meant a third QPainter open on top of the two the strip
> already has, which Qt ends the process over; and a lookup table over
> 256 values is the cheaper of the two anyway.

### `VocalMap.flux`

**line 620** — from the docstring, `def flux(self, bands: tuple[int, int] | None = None):`

> Energy ARRIVING, as a 0..1 trace on the picture's own 10ms grid.
>
> Why this and not the picture. The mel says how loud each band is, and
> a word start is not loudness -- it is a change in it. Measured on
> `MaKE ME FAMOUSS >_<` against 226 hand-placed word starts, and on
> `Scared of the Dark` against 419, taking how much the signal rises at
> a word start against how much it rises anywhere:
>
>                                 rapped    sung
>     the mel as drawn             1.40x    1.34x
>     half-wave flux of it         1.61x    1.37x
>     flux over its running floor  3.41x    2.58x
>
> So the picture really does not say where words start -- 1.4 times the
> background is nothing to read -- and the same audio, differenced and
> then read against its own neighbourhood, says it three times over.
> That is not a placement either (see this module's docstring, which is
> emphatic about it, and it still stands) but it is a trace somebody
> can look at and see where the singer started something.
>
> The running floor is what does the work. Raw flux is loud where the
> song is loud, so a peak in a quiet bar is invisible beside an ordinary
> one in a loud chorus; taking each peak against the median of its own
> neighbourhood puts the two on the same footing. It is what an onset
> detector does before it thresholds, and `vocal.attacks` is already
> thresholding something like it to make the ticks -- this is the same
> evidence drawn continuously, so the marks below the threshold can be
> seen rather than only counted.

## The picture and the trace — 2026-10-28

Compared against Spicy Lyrics' sync tool (tool.spicylyrics.org, a fork of the
AMLL TTML tool; both run the `apoint123/wasm-spectrogram` crate: left channel,
no window, FFT 1024, hop 64 samples, `log10(1 + |X|·9/√(2N))·gain` at a fixed
gain of 3, linear 0–20 kHz, frames drawn from where they start). Side by side
on the same songs, three things in ours read worse, each with a measured cause:

- **Quiet tones above ~2 kHz missing.** One floor and ceiling for the whole
  song (p40/p99.5) puts the upper bands under the floor: on Brain Rot,
  2–4 kHz was lit 34% of the time and 4–7.6 kHz 27%, against ~95% in theirs.
  With each band framed by its own percentiles every range sits near 50–60%.
- **Blur.** 80 triangle bands stretched to the strip; above ~1.5 kHz a band is
  wider than the gap between a voice's harmonics, so they merge.
- **Consonants missing.** The mel stops at 7.6 kHz, the stem model's range.
  Sibilants live at 4–12 kHz and reach 20 kHz on loud parts.

So the picture is now its own array (`_picture`, `VocalMap.pic`), apart from
the 80-band mel that marks, flux and the model read: 128 rows spaced like mel
from 40 Hz to 20 kHz (or Nyquist), each the loudest FFT bin in its slice (the
nearest bin when a slice holds none), a 25 ms Hann window every 5 ms, log
power kept as float16. For the vocal view it is drawn from the kept stem at
its own rate, so the stem's consonants show; the mixture's comes from the
song. A 2-minute song draws in 0.8 s and reads back in 0.02 s; the image
colours in 0.12 s. Settings ▸ Levels picks per-band (the default) or the old
whole-song framing. A band that never changes has no range and draws dark,
which hides a steady hum; a band holding only noise is stretched up to full
brightness, the price of seeing quiet consonants.

The attack trace was heavy on held notes: vibrato moves each harmonic between
neighbouring bands, and plain half-wave flux counts every move as an arrival.
It now compares each band with the loudest of the five around it two frames
back (SuperFlux, Böck & Widmer 2013). Scored against hand-placed syllable
starts (bench `evaltrace.py`, the 7 songs `evalspec.py` uses, AUC of the trace
at the starts against every frame in the lyric):

                                  mean AUC   above 0.3 away from a start
    flux as it was                  0.673        4.9%
    SuperFlux, 5 bands, lag 2       0.700        4.1%

Higher on every song (115: 0.666 → 0.743). On the one song with a kept stem
and a hand timing (doggirl), the stem's own mel goes 0.635 → 0.642. The
`2026-10-26` finding still holds for the picture: no drawing setting moved the
picture's own rise at starts, so the new picture is for reading, not a better
detector.
