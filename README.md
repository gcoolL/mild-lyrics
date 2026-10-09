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

## Multiplayer

The TTML Editor can time one lyric with other people: **Multiplayer…** on
the start screen, or **File ▸ Multiplayer…**.
It is editor to editor, with no server in between.

1. The host clicks **Host a session** and sends the invite code to the person
   joining, in any chat.
2. They paste it under **Join with a code** and send back the reply code
   their editor makes.
3. The host pastes the reply and the two editors connect, usually within a
   few seconds. Where the two computers can already reach each other (the
   same network, a VPN, open IPv6) they connect before the reply is even
   pasted, and that is all. One invite can bring in several people: **Lets
   in up to** sets how many (1 to 8 at a time in a session). The number is kept
   by the host, not in the code, so nobody holding the code can change it,
   and a place is spent when someone joins and not given back when they
   leave. An invite stops working after half an hour; **New invite** makes
   another.

Everyone needs a name, set at the top of the window and changeable in the
middle of a session.

The song comes along: joiners get the host's copy. If the host fetched it
(Fetch audio…), each joiner's editor downloads that same upload itself.
Only a YouTube video or a SoundCloud track is accepted, rebuilt from its id,
so no peer can point your downloader anywhere else. If the host's audio is a
file of their own, the joiner's editor searches for the song by its title,
artist and the host's exact length. No audio file travels between editors.

A line is held by whoever's cursor or selection is on it, from the first time
they move it, and nobody else can change it until they move off. **Claim selected lines** or **Claim this part**
(a grouped run, from Lines ▸ Group) keeps lines yours after you move away. In
the list, other people's lines are tinted in their colour, with their word
outlined; the names are at the right of the status row. An edit that would
change someone else's line is undone whole, and the status line says whose it
is. Undo only rewinds your own work. Everyone uses their own audio: load the
same cut of the song.

In a session:

- **Where people are.** Click a name at the right of the status row to go to
  their line; **Follow** (in the Multiplayer window) keeps it in view until
  you move your own cursor.
- **Notes.** Right-click a line, **Add a note…**, or use the Notes page: a
  short note on a line for everyone, shown as a ✎ marker with the text on
  hover. Its writer and the host can delete it. Notes belong to the session,
  not the file.
- **Roles.** An invite can bring people in to **watch only**: they see the
  lyric being timed, live, and hold nothing. The host can switch anyone
  between editing and watching, **freeze** the lyric while reviewing (only
  the host edits then), and **give selected lines** to someone, as their
  claim. Your own claims are tinted faintly in your colour, with a doubled
  edge.
- **Splitting the song.** The host's **Split the song between us** groups
  whatever is sung more than once (as **Lines ▸ Group repeats** does), cuts
  the song into sections and gives each section to someone as their claim.
  Every repeat of a part goes to the same person, so they time it once. It
  replaces everyone's claims; watchers get nothing.
- **Who synced what.** Each line shows "● name" for whoever last timed it,
  for the length of the session.
- **Holding words.** By default whoever is on a line holds all of it. The
  host can switch to **single words**: a cursor holds just its word, two
  people can time different words of one line, and their edits are merged;
  an edit that reshapes a line or touches someone's word is turned back.
- **Dropped connections.** A joiner whose connection drops comes back by
  itself, as who it was, for up to ten minutes; edits wait meanwhile. If the
  host's relay is lost, the editor makes a new one and shows a new invite;
  anyone who dropped joins again with that.
- **Lining the copies up.** The host sends its song's loudness outline (no
  audio), and each joiner's editor compares it with its own copy. A copy
  that starts clearly earlier or later is lined up for that session, and
  it says by how much.
- **Credit.** The file's author field (SyncedBy) gains everyone whose edits
  went in.
- **Handing over.** **Make host** passes the session to someone else before
  you leave: everybody moves across to their editor, as who they were, with
  the lyric, notes and claims. It goes through your editor, the only one
  connected to everyone, and is cancelled if they cannot start hosting.

It needs `aioquic`. Setup asks to install it, under Multiplayer (on Arch's
own Python it goes into `pylibs`, beside the other extras; `pacman -S
python-aioquic` works too). A session prints what it does, joins, refusals
and failures, to the terminal as `[multiplayer] ...` lines.

**What is and is not exposed.** The invite is the session's password. It
carries a certificate made for this session alone, which the joiner pins, and
a random token the host checks before letting anyone in. It also carries your
internet address, so send it only to the person you are inviting. The reply
is sealed to the host's editor, so only that editor can read it; posting a
reply where everyone can see it gives nobody else anything. Everything
after that is QUIC (TLS 1.3). What travels is JSON describing lines, checked
field by field against hard limits. No TTML or XML is sent, and no message can
name a file, a setting, the audio or the player. The port is open only while a
session runs and does not answer anyone who lacks a code. Two public STUN
servers (Google's and Cloudflare's, changeable in the dialogue) are asked only
where your connection is on the internet; they never see the session.

**What is not promised.** NAT hole punching gets through most home routers,
but not where both sides' routers hand out a new port for every destination
(symmetric NAT: some mobile networks, carrier-grade NAT, strict school or work
networks). The editor measures this when you host or join and says so before
anyone pastes a code; then the same network, or Tailscale/ZeroTier, works.
Untested so far: a real connection between two homes (it has been tested
over loopback and through simulated routers), and anything on Windows, where
the firewall must let Python receive.

## License

Copyright (C) 2026 gc

Mild Lyrics is free software: you can redistribute it and/or modify it under
the terms of the GNU Affero General Public License as published by the Free
Software Foundation, either version 3 of the License, or (at your option) any
later version. The full text is in `LICENSE`. This applies to every earlier
release as well, including those published before the license was added.

The exception is the code ported from applemusic-like-lyrics (AMLL) -- the
`amll` renderer's per-letter emphasis and float, and the `Spring` it moves
on, in `mild-lyrics/renderers.py`. AMLL is AGPL-3.0-only, so those parts
stay version 3 only, and so does the program as a whole for as long as it
carries them. The `Spicy` renderer is a port of Spicy Lyrics, also AGPL-3.0.
What else it borrows, and from whom, is in `THIRD_PARTY_NOTICES.md`.
