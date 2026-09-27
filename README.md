# mild-lyrics
my goofy lyrics bro

## What is in here

    mild-lyrics/     the player, and everything it is built on
    editor/          the TTML Editor
    docs/            the prose that was lifted out of the code
    lyrics/          what the two of them save, in two rooms:
                       fetched/   copies the player kept of what it fetched
                       made/      work timed by hand, in the editor

Plus the launchers, the setup scripts and `noconsole.py`, which is what keeps
a console window from appearing behind either of them on Windows.

That is the whole repository. The rest of what this project has produced --
the forced aligner and its training code, the test suite, the Android port,
the benchmarks and the audio they were measured on -- sits beside it rather
than in it, because none of it is the program and together it is a gigabyte
and a half. A few comments still point at `sync/`, `tests/` or `local_align`
by name; that is where they are.

Nothing here is heavy by default. Timing a song against its own audio on
this machine -- a CTC model, gigabytes of wheels and a GPU to run them on --
was taken out on 2026-09-21, along with the editor's Auto-time, which sat on
the same stack. What is left reads lyrics somebody else timed, and lets you
time them yourself.

Setup still offers demucs, for separating a vocal out of the mix so it can be
timed against the stem rather than the band. It is the one group that is never
installed on a yes: it is gigabytes, it wants the word "yes" typed out, and
`--heavy` is how you mean it from a script.

## Setting up

To run setup, run in Terminal (Linux) / Command Prompt/Powershell (Windows):

    ./setup.sh          # Linux, macOS
    setup.cmd           # Windows -- double-click works too

It also sets Spotify's debug port for you, through `spicetify config`, keeping
whatever launch flags are already there. Spotify has to be started BY
Spicetify for that to take -- `spicetify auto`, or a shortcut that runs it.

## Two interfaces

The player and the TTML Editor share one switch, **Interface: new / classic**,
kept in `interface.json` beside their settings; flipping it in one redraws
the other.

- **New** -- the settings open in a drawer on the right, with a switch,
  side-by-side buttons, a ▾ list or a slider for each kind of setting, and a
  Keys tab where every key can be rebound. Questions the settings ask are
  asked inside the window. The editor takes on the player's look: glass over
  the album colours, white ink, a slim toolbar with ▾ menus, and the
  transport split into playback and status. Switch back at the foot of the
  drawer.
- **Classic** -- the centred menu, the ribbon and the dialogues, as they were.
  Switch back in Settings ▸ Text ▸ Interface (player) or Settings… ▸ Look ▸
  Interface (editor).

Settings ▸ Background ▸ **Now playing** lays the song out four ways in either
interface: `panel` (the cover in its own panel), `card`, `bar` along the
bottom, or `backdrop` (the cover only as the wall).

The editor keeps **romanisation** with the lyric -- a reading per syllable, or
one per line -- and writes it into the TTML the way Apple Music
(`<transliterations>`) and amll-ttml-db (`x-roman`) do, so the player shows
it too. Japanese, Chinese, Korean, Cyrillic and Greek are cut into syllables
by the automatic split.
