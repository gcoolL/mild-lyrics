# `editor/stem/separate.py`

## Lift — 2026-10-25

Docstrings shortened in `editor/stem/separate.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> The vocal out of a mixture, with demucs.
>
> What is left of the aligner's separation stage: the model loaded, used and let
> go of inside one call, on the card where there is one and room on it, and on
> the CPU otherwise -- which is several times slower and finishes, and beats
> taking a card out from under a game.

### `_vocals_only`

**line 21** — from the docstring, `def _vocals_only(model, mix, dev: str, seg: float, overlap: float = 0.25):`

> The vocal row of `apply_model(model, mix[None], split=True, shifts=0)[0]`,
> or None if demucs does not offer what this needs.
>
> `apply_model` overlaps its segments into an output for EVERY source over
> the whole song -- four sources, two channels, 340MB for four minutes -- and
> this program keeps one of them. The sum is per source, so a row of it is
> the same numbers whether or not the other three are added up beside it:
> each segment is still run through the model by demucs' own non-split
> path, and only the vocal row of what comes back is weighted into the
> output. The arithmetic is apply_model's, operation for operation, so the
> result is the same to the bit; see there for the weights. A bag of models
> is combined the way apply_model combines it, again for the one row.
