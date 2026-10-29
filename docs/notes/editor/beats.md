# editor/beats.py — notes

## The beat grid — 2026-10-28

A line on the strip for every beat, with fainter ones on the half beats, and
drags that land on them within `SNAP` pixels, the playhead first and Shift for
none (Settings ▸ Timing: "Beats behind the words", "Snap to beats").

**How it is found.** numpy only, so it runs wherever the editor does. The
song at 22 050 Hz mono; a half-wave log-mel flux (64 bands, 30 Hz–8 kHz, a
512-sample window every 256) less its half-second running mean; the beat's
length from the flux's autocorrelation leaning towards 120 bpm (Ellis 2007),
with the peak's fraction found; then the beats by dynamic programming against
that length (librosa's `beat_track` does the same, tightness 100). 0.2 s for
a 3-minute song, kept beside the vocal view's files as `<key>-beats1.npz`.

Three corrections came out of measuring it:

- **The window was hearing hits early.** With a 2048-sample (93 ms) window
  centred on the frame, beats on a click track came out 21 ms early: the
  window starts hearing a hit half its length before it lands. At 512 (23 ms)
  it is 1.4 ms. Against hand-placed syllable starts, the starts' median lean
  after their nearest beat went from 12.9 ms to 4.6 ms.
- **That made the tempo halve on sharp hits.** At 150 bpm a beat is 34.45
  frames; a flux peak a frame wide misses itself at a lag of 34, and the
  double (69 frames, 75 bpm) won. The flux is softened (σ 2 frames) before
  the autocorrelation only; the beats are still placed on the sharp one.
- **Off-beat hats.** A hat fills more mel bands than a kick, so on a kick and
  hat pattern the grid locked onto the hats, half a beat out. After tracking,
  the flux under 160 Hz is compared on the beats and between them; a kick
  landing between moves the grid half a beat.

**Measured** on the 7 hand-timed songs of `memory/bench/spec/evalbeats.py`
(tempo within 1.5 bpm of librosa on all of them; beats agreeing within 70 ms
on six, F 0.78–0.99). On Run they disagree by most of a half beat, and the
hand timing sides with this one: 31% of its starts sit within 30 ms of these
beats, 15% of librosa's.

Hand-placed syllable starts within 30 ms of the grid, against the same starts
slid at random (chance):

    beats          29%   (chance 11%)
    half beats     48%   (chance 22%)
    quarter beats  66%   (chance 46%)

So a start is on the beat or the half beat about twice as often as chance,
and quarter beats are close to chance -- too dense to mean anything, which is
why snapping stops at half beats. Half the starts are on neither, so a snap
is a suggestion; Shift is there for the rest.

**Drawing.** Into the strip's cached picture, teal (violet when the accent
is teal), skipped once the beats would come closer than 5 px; the half-beat
lines only while drags snap to them and they are 12 px apart. A drag that has
landed on a beat lights that line.
