# `editor/theme.py`

Comments lifted out of `editor/theme.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

**line 31** — before `ACCENTS = {"blue": "#5b8cff", "violet": "#9a7bff", "teal": "#2fb8b0",`

> The one bright ink: the lead voice, the playhead, a filled slider, the
> selected chip. It is a setting because it is the single colour somebody
> looks at all day and the only one in here that carries no meaning of its
> own -- BACK has to read as "not the lead" and WARN has to read as wrong,
> where this one just has to be the colour you want to work in.


---

## Lift — 2026-10-25

Docstrings shortened in `editor/theme.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> One palette, one type scale, one set of metrics -- for every window here.
>
> The colours were written twice before this file existed, once in the strip
> and once in the list, and they had already drifted: the same syllable was a
> different blue depending on which half of the window it was drawn in. A
> lyric is one material and has to look like one, so there is one place to
> change it.
>
> The scheme is Mild Lyrics' own, brought inland: near-black, one bright ink
> for the lead voice and everything that means "here", a warm one for backing
> vocals, a green for the answering voice. Surfaces step UP towards the viewer
> -- the window is the darkest thing on screen and a control at rest is two
> steps lighter -- so depth reads without a single shadow.

### `_set_accent`

**line 120** — from the docstring, `def _set_accent(name: str) -> str:`

> Make `name` the bright ink, and derive the dim one from it.
>
> LEAD_DIM is not a second setting: it is what the accent looks like with
> the window behind it, and a person picking a colour is not also picking
> how far to sink it. Mixed rather than darkened, because darkening a blue
> gives a navy and mixing it with the near-black surface gives the same
> colour at a distance -- which is what "dim" has to mean for a chip that
> has already been sung.

### `family`

**line 172** — from the docstring, `def family() -> str:`

> The first face on this machine from the project's own stack.
>
> Looked up once. Every font() asks for it, and the painted widgets ask
> for fonts per chip and per block, per frame -- two dozen times a frame,
> each one a full list of the machine's families built and searched. That
> was the largest single cost of a frame while the song played. The editor
> installs no faces of its own, so the answer cannot change under it.

### `font`

**line 183** — from the docstring, `def font(px: float = 12, weight: int = 500, mono: bool = False,`

> The house face at `px`, scaled with the window.
>
> `mono` is what the clock and the times ask for, so their digits line up
> down a column. The classic look answers with the system's monospace; the
> new one keeps the house face and turns its tabular figures on instead,
> so every number in the window is in the same type as everything else.

### `card`

**line 334** — from the docstring, `def card(widget, level: str = INK_2) -> None:`

> Put a widget on a raised surface with a hairline round it.
>
> Scoped to this widget by object name. An unscoped stylesheet on a parent
> is inherited by every descendant, which put a border and a 6px radius
> around every label and text box inside the card and flattened the buttons
> with it -- Qt's selectors match children unless told otherwise.

---

## Earlier lift — 2026-08-23

Comments lifted out of `editor/theme.py` on 2026-08-23, before the work that followed. They are not in the code any more, so they are kept here as they were; the line numbers are the ones that code had then.

### module level

**line 20** — on `INK_0 = "#0d0e12"`

> the window behind everything

**line 21** — on `INK_1 = "#14161c"`

> the lyric list, the waveform bed

**line 22** — on `INK_2 = "#1b1e26"`

> chrome: ribbon, transport, dialogues

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


### `font`

**line 107** — before `f.setStyleHint(QFont.StyleHint.Monospace)`

> Times and line numbers have to line up vertically down a column or
> they cannot be compared at a glance, which is the only reason
> anybody reads a column of times.
