# `editor/stem/vocal.py`

## Lift — 2026-10-25

Docstrings shortened in `editor/stem/vocal.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> What the audio itself says about where the singing is.
>
> WHY THIS EXISTS. Separation changes what a frame of silence MEANS. On a
> mixture, a quiet vocal sits under a loud guitar and frame energy says nothing
> about whether anybody is singing; on a separated vocal it very nearly says
> exactly that. The aligner has never looked. `audio.loudness` has been in this
> package the whole time and only `offset.lead_silence` ever called it.
>
> WHAT IT IS FOR. The CTC lattice has no way to say "no lyric happens here". A
> path crossing an instrumental can only idle in blank, and idling is cheap --
> which is the peakiness that `ctcalign.levelled` exists to fight and only partly
> wins. The measured failure is not scattered error: it is a handful of spans a
> song, seconds out, where the singing stops and the path wanders. Frame energy
> from a separated vocal is close to a ground-truth answer for exactly those
> frames, so it is worth more than another 6,000 training steps.
>
> ONSETS. The other half is where a word STARTS. The model already emits a
> word-start channel that nothing reads (model.py:84, channel 0). Spectral flux
> -- how much the spectrum jumped since the last frame -- is the classic
> complement to it, and note onsets improving lyrics-to-audio alignment is a
> result old enough to be uncontroversial. On a separated vocal a flux peak is a
> sung attack rather than a snare.
>
> EVERYTHING IS ON THE 20 MS GRID, audio.FRAME, the same grid as the model's
> emissions and every time in every file this package writes. The two things
> this reads -- audio.loudness and audio.mel -- are both on the 10 ms hop, so
> both are reduced by audio.STRIDE here and nowhere else.

### `gate`

**line 68** — from the docstring, `def gate(logp, present, weight: float = 1.0, blank: int | None = None):`

> The emissions, with silence made expensive to spell through.
>
> `present` is `activity()`. Where it is 0 the frame gets a blank bonus of
> `weight` nats, and where it is 1 nothing changes -- so a path crossing an
> instrumental is not merely allowed to idle in blank, it is paid to. What
> this cannot do is move a word: it only makes the gaps between words honest.
>
> Nothing is subtracted from the letters. Penalising letters in quiet frames
> sounds equivalent and is not: it drives the path to spell the whole lyric
> inside whatever is loud, which on a song with one loud chorus is a way to
> lose the verses.

### `track`

**line 95** — from the docstring, `def track(wave, frames: int | None = None):`

> (frames, 2): how high the note is, and how much it just changed.
>
> NOT voicing. A voicing channel was tried and is degenerate on this data:
> the clips are cut around words, so nearly every frame of nearly every clip
> is voiced, and a head learns nothing from a target that is almost always 1.
> (detect_pitch_frequency has no voicing decision of its own either -- it
> returns a confident frequency for silence.)
>
> What is left is the part the idea rests on: a singer changes note where a
> syllable begins far more often than in the middle of one, so the SECOND
> channel -- the size of the pitch change -- is a note-onset signal, and
> predicting it is what should push onset structure into the encoder.
>
> The height is log-scaled, because a semitone is a ratio and a linear target
> would spend all its resolution on the top octave.

### `pitch`

**line 183** — from the docstring, `def pitch(wave, hop: int = audio.HOP) -> torch.Tensor:`

> f0 per 10 ms frame in Hz, NaN where the frame is not periodic.
>
> YIN: the difference between the frame and itself shifted by every lag in
> range, normalised so that a long lag is not automatically cheaper, then
> the first lag that dips under `PITCH_APERIODIC` -- the first, not the
> best, which is what keeps it from answering an octave down.

### `notes`

**line 272** — from the docstring, `def notes(f0, floor: float = NOTE_STEP, window: int = NOTE_WINDOW,`

> The times a new note starts, in seconds.
>
> Two kinds, and they are the same event seen from either side: the pitch
> STEPS -- the median of the frames before differs from the median of the
> frames after by more than `floor` cents -- or voicing RESUMES after a gap,
> which is a chop with silence in front of it or a consonant.
>
> Medians either side rather than a difference between neighbours, because
> an f0 track is noisy frame to frame and vibrato swings further than some
> intervals. Over 80 ms the wobble averages out and a step does not.

### module level (comment)

**line 118** — before `LOW, HIGH = 65.0, 1000.0      # Hz: below a bass voice, above a whistle register`

> ------------------------------------------------------- pitch, for training
> Note onsets and phoneme starts are temporally correlated -- a singer changes
> note where a syllable begins far more often than in the middle of one -- so a
> head made to predict F0 alongside the letters pushes that correlation into
> the encoder, where the CTC head can use it. See "Improving Lyrics Alignment
> through Joint Pitch Detection" (arXiv 2202.01646). The head is thrown away at
> inference; only what it did to the body is kept.

### module level (comment)

**line 170** — before `PITCH_MIN = 70.0      # Hz. Below a bass voice; a bass line is not in the stem.`

> ------------------------------------------------- a song's own standing bias
> One calibration constant for every song is a compromise. The model's lateness
> is not the same on a whispered ballad and a rapped verse, and the measured
> figures say so: three Dutch songs read 0.118-0.176s AHEAD of their reference
> and a fourth 0.192s BEHIND it, which no single number can absorb.
>
> The fix is to stop needing a reference. A sung attack is a fact about the
> recording, so the gap between where a word was placed and the attack it was
> placed on can be measured on the song itself -- no lyric, no donor, no
> language. What that gap agrees on is this song's bias, and it can simply be
> taken off.
> ---------------------------------------------------------------- the notes
> What a chopped vocal does instead of an attack.
>
> A flux peak is energy ARRIVING, and that is what a sung word does: a
> consonant, a breath, a new note struck. It is not what a CHOPPED vocal does.
> In the drop of a track built the way `Conro - Therapy` is, the lead IS the
> singer -- their own voice, cut into sixteenths and pitched up a fifth -- and
> it runs continuously: there is no gap for energy to arrive into, so the flux
> has nothing to fire on. Measured against the hand-made timings of that song's
> chopped chorus, where the flux marks land 0.060 s from a syllable and only
> 43% of them within 50 ms, against 0.010 s and 71% on the sung verses of the
> same file.
>
> Every chop is a new NOTE, though, and that is readable: the pitch steps. On
> the same 74 syllables, note onsets land 0.039 s away with 61% inside 50 ms,
> and the two kinds of mark together 0.023 s with 72%.
>
> HOW THE PITCH IS FOUND. YIN (de Cheveigne & Kawahara 2002), in torch,
> because this package has torch and torchaudio and nothing else -- librosa's
> `pyin` scores a little better per mark but is a dependency the project does
> not have. The difference function is computed through the autocorrelation
> so a song is a couple of FFTs rather than a loop over lags.

### `_yin` (comment)

**line 258** — before `size = 1 << (2 * win - 1).bit_length()`

> r(tau) for every lag at once, through the FFT. The correlation is
> between the ANALYSIS window -- the first half of the frame -- and the
> whole frame, so that r(tau) sums the same samples the energy terms
> below count. Correlating the frame with itself instead makes r(tau)
> shorter as tau grows and the difference function comes out tilted,
> which reads as a pitch a whole tone off.
