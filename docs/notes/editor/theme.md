# `editor/theme.py`

Comments lifted out of `editor/theme.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

**line 20** — on `INK_0 = "#0d0e12"`

> the window behind everything

**line 21** — on `INK_1 = "#14161c"`

> the lyric list, the waveform bed

**line 22** — on `INK_2 = "#1b1e26"`

> chrome: ribbon, transport, dialogs

**line 23** — on `INK_3 = "#232733"`

> a control at rest

**line 24** — on `INK_4 = "#2c313f"`

> ...under the pointer

**line 25** — on `LINE = "#2a2e3a"`

> hairlines, 1px, never heavier

**line 28** — before `FAINT = "#7b8194"`

> Lifted to 4.6:1 on INK_1 -- line numbers are set in it, and a
> number nobody can read is not a quieter number, it is a missing one.

**line 33** — before `LEAD = "#5b8cff"         # the lead voice, the playhead, the primary action`

> Two carry meaning. Nothing else is allowed to be colourful, so that these
> always mean what they say.

**line 35** — on `LEAD = "#5b8cff"`

> the lead voice, the playhead, the primary action

**line 37** — on `BACK = "#e8a05c"`

> backing vocals, wherever they are drawn

**line 38** — on `DUET = "#61c98a"`

> the answering voice

**line 39** — on `WARN = "#e2585f"`

> only for losing work

**line 41** — on `CHIP = "#262a35"`

> a syllable at rest

**line 43** — on `SUNG = "#39415a"`

> sung through, in preview

**line 55** — before `SCALE = 1.0`

> Everything is sized through font(), so one number moves the whole window.
> Lyrics are the thing being read here, not chrome, and they are set larger
> than a settings panel would be -- this is a tool for looking at words.


## `font`

**line 107** — before `f.setStyleHint(QFont.StyleHint.Monospace)`

> Times and line numbers have to line up vertically down a column or
> they cannot be compared at a glance, which is the only reason
> anybody reads a column of times.
