# mild-lyrics
my goofy lyrics bro

Synced lyrics for whatever you're playing, a music player of its own, and an
editor to time lyrics yourself.

## Setting up

    ./setup.sh          # Linux, macOS
    setup.cmd           # Windows -- double-click works too

Setup installs what each feature needs, asking first, and sets Spotify's
debug port through Spicetify. `--uninstall` takes things back out, and
`--check` shows what is installed. Updates install themselves, but they never
install packages: run setup again after one to get what new features need.

## The player

- Word-by-word lyrics from Spicy Lyrics, Apple Music, AMLL, NetEase, Kugou,
  QQ Music, Kuwo, LRCLIB, Musixmatch and more
- Follows Spotify, browsers and other media players
- Romanisation for Japanese, Chinese, Korean, Cyrillic and Greek
- Eight lyric styles, album-colour backgrounds and a visualiser
- The song's music video behind the lyrics
- A home page: your library, search, charts, stats and suggestions
- A music player of its own: streams songs, or plays your own music
  files, with a queue and autoplay. No Spotify needed
- Listen along with friends
- Last.fm scrobbling and Discord status
- Mini player and system tray
- Plugins (see [docs/plugins](docs/plugins/README.md))

## The TTML Editor

- Time lyrics syllable by syllable against the song's waveform
- Splits words into syllables automatically, with romanisation kept alongside
- Separates the vocal from the song to time against (demucs, optional)
- Opens and exports LRC, Enhanced LRC, ASS, KRC, QRC, YRC, LYS and SRT
- Multiplayer: time one lyric together, with an invite code

## Keys

B opens the home page, Q the queue, and Ctrl+Q quits. Every key can be
rebound in the settings drawer's Keys tab.

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
