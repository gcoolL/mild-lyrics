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
the synchroniser's training code, the test suite, the Android port, the
benchmarks and the audio they were measured on -- sits beside it rather than
in it, because none of it is the program and together it is a gigabyte and a
half. A few comments still point at `sync/` or `tests/` by name; that is where
they are.

## Setting up

To run setup, run in Terminal (Linux) / Command Prompt/Powershell (Windows):

    ./setup.sh          # Linux, macOS
    setup.cmd           # Windows -- double-click works too

## The Spicy Lyrics key

Spicy Lyrics — the community's hand-timed syncs, and the source everything
else here is ranked against — is an API like the other ten sources, and it
wants a key. One ships with the program, so there is nothing to set up.

To use your own instead, make one at
[the dashboard](https://spicylyrics.org/dashboard/applications) and:

    mild-lyrics/spicy_lyrics.py key sl_sk_...

It goes in the settings directory, not in this tree, and `SPICY_LYRICS_KEY`
in the environment beats that. A *publishable* key (`sl_pk_`) for a program
like this one has to be issued with the **no Origin header** allowance:
nothing here is a browser, so no `Origin` is ever sent and an origin allowlist
would refuse every request. A *secret* key (`sl_sk_`) is your application's
whole budget and belongs only on a machine you control — never in the source.

Wherever the lyrics are shown, so is the credit: the catalogue that answered,
and — where it is the community's — whoever timed it and whoever uploaded it,
each one linked to their own page. That is a condition of the API, and it is
the reason the API is worth having.
