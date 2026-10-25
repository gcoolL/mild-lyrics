# `editor/collab_audio.py`

## Lift — 2026-10-25

Docstrings shortened in `editor/collab_audio.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> Does everybody's copy of the song start at the same moment?
>
> Each person in a session times against their own copy, and two copies of one
> recording can differ at the start: a little more silence, a trimmed fade-in,
> a different encoder's padding. Then everybody's taps are true to their own
> copy and a fraction of a second out from everybody else's.
>
> So the host sends its copy's loudness outline -- the same readings the
> waveform is drawn from, a hundred a second, a byte each: about 24KB for a
> four-minute song and nothing anyone could listen to -- and each joiner lines
> its own outline up against it. What is compared is where the sound STARTS
> (the rise in loudness, on a log scale), not how loud it is, so two masters
> at different levels still agree.
>
> Only a clear answer is acted on. The best match has to stand well above
> every other shift tried, and above the second best by a margin; anything
> less is reported as "could not tell", never guessed at.
