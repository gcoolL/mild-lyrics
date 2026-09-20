# mild-lyrics
my goofy lyrics bro

## What is in here

    mild-lyrics/     the player, and everything it is built on
    editor/          the TTML synchroniser
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

Nothing here is heavy any more. Timing a song against its own audio on this
machine -- demucs, a CTC model, gigabytes of wheels and a GPU to run them on
-- was taken out on 2026-09-21, along with the editor's Auto-time and its
vocal map, which sat on the same stack. What is left reads lyrics somebody
else timed, and lets you time them yourself.

## Setting up

To run setup, run in Terminal (Linux) / Command Prompt/Powershell (Windows):

    ./setup.sh          # Linux, macOS
    setup.cmd           # Windows -- double-click works too

It also sets Spotify's debug port for you, through `spicetify config`, keeping
whatever launch flags are already there. Spotify has to be started BY
Spicetify for that to take -- `spicetify auto`, or a shortcut that runs it.
