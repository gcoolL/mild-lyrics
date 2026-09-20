# `mild-lyrics/eval_blends.py`

Comments lifted out of `mild-lyrics/eval_blends.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

**line 63** — before `DONORS = ("apple", "qq", "netease", "kugou", "spicy")`

> Every source a blend can be built from, plus Spicy Lyrics' own copy -- which
> is the base on the tracks it has one for, and the reference under
> `--against spicy`.

**line 67** — before `WHOSE = {"qq": "QQ Music", "kugou": "Kugou", "netease": "NetEase"}`

> What each donor is called where a blend names its makeup. The same strings
> from_blend and its neighbours pass to _blended.

**line 70** — before `CUT_SHORT = 0.30`

> How far apart two hand-timed line ends may be before the shorter one counts
> as cut short. Below this is the ordinary disagreement between two people
> timing the same sustain.

**line 74** — before `SAME_VOICE = 0.15`

> ...and how far two voices may overlap and still be two voices. _blend has a
> constant of its own for the same idea; this one is deliberately separate,
> because a measurement written in terms of the thing it is measuring cannot
> tell you the thing is wrong.

**line 99** — before `# --------------------------------------------------------------------------`

> the jar

**line 202** — before `# --------------------------------------------------------------------------`

> building a blend over the jar


## `build`

**line 229** — before `lead, fill = LS.in_order(`

> Through in_order, because which donor leads is part of what the chain
> hands over and a copy of that rule kept here would drift away from it,
> exactly as stand_down would.


## module level

**line 246** — before `# --------------------------------------------------------------------------`

> the four questions


## `measure`

**line 399** — before `"loose": sum(1 for e in errs`

> Against the SONG's own median, so a document timed against
> another master is judged on how much it disagrees with
> itself rather than on which pressing it came from.
