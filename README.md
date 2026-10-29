# mild-lyrics
my goofy lyrics bro

Synced lyrics for whatever you're playing, a music player of its own, and an
editor to time lyrics yourself.

## Installing

**Windows**: paste this into PowerShell:

    irm https://github.com/gcoolL/mild-lyrics/releases/latest/download/install.ps1 | iex

**Linux, macOS**: paste this into a terminal:

    curl -fsSL https://github.com/gcoolL/mild-lyrics/releases/latest/download/install.sh | sh

Or download the installer on its own from the
[latest release](https://github.com/gcoolL/mild-lyrics/releases/latest):
double-click `install.cmd` on Windows, or run `sh install.sh` on Linux and
macOS. You don't need the rest of the repository. On Linux you can also open
`install.sh` from the file manager, once it is allowed to run (right-click,
Properties, Permissions, "Allow executing file as program"; browsers download
it without that). It then shows its questions and progress as windows, or
opens itself in a terminal if it can't.

The installer first asks whether you want Mild Lyrics, the TTML Editor or
both, then lists everything it can install, by what it is for, with a
checkbox for each part and each category. Untick anything you don't want.

It also asks where to put Mild Lyrics. Press Enter for the default
(`%LOCALAPPDATA%\Programs\mild-lyrics`, `~/.local/share/mild-lyrics`, or
`~/Library/Application Support/Mild Lyrics`), or type another folder. On
Windows you can also press B to browse. Each install gets its own Python
environment, and if no suitable Python is found, the installer installs one
first. It adds the apps you picked to the Start menu or app menu, and sets
Spotify's debug port through Spicetify when Spicetify is installed.

Mild Lyrics updates itself. Run the same command again to change what is
installed, to repair an install, or to pick up packages a new feature needs.
To remove it, use Settings > Apps on Windows, or on Linux and macOS:

    curl -fsSL https://github.com/gcoolL/mild-lyrics/releases/latest/download/install.sh | sh -s -- --uninstall

The separate vocal for the editor (torch and demucs, several GB) is not
installed by default. To add it, run `setup.sh --heavy` (Windows:
`setup.cmd --heavy`) from the install folder.

### From a git checkout

    ./setup.sh          # Linux, macOS
    setup.cmd           # Windows -- double-click works too

Setup installs what each feature needs, asking first, and sets Spotify's
debug port through Spicetify. `--uninstall` takes things back out, and
`--check` shows what is installed. Updates install themselves, but they never
install packages: run setup again after one to get what new features need.

## The player

- Lyrics from [Spicy Lyrics](https://github.com/Spikerko/spicy-lyrics),
  [Apple Music](https://music.apple.com) (through [lrc.red](https://lrc.red)),
  [AMLL TTML DB](https://github.com/amll-dev/amll-ttml-db),
  [Unison](https://unison.boidu.dev),
  [NetEase Cloud Music](https://music.163.com),
  [Kugou](https://www.kugou.com), [QQ Music](https://y.qq.com),
  [Kuwo](https://www.kuwo.cn), [lrc.red](https://lrc.red)'s model syncs,
  [LRCLIB](https://lrclib.net), [Musixmatch](https://www.musixmatch.com) and
  [Genius](https://genius.com), word by word where they have it
- Follows Spotify, browsers and other media players
- Romanisation for Japanese, Chinese, Korean, Cyrillic and Greek
- Eight lyric styles, album-colour backgrounds and a visualiser
- The song's music video behind the lyrics
- A home page: your library, search, charts, stats and suggestions
- A music player of its own: streams songs, or plays your own music
  files, with a queue and autoplay. No Spotify needed
- Listen along with friends, with voice chat
- Last.fm scrobbling and Discord status
- Mini player and system tray
- Plugins (see [docs/plugins](docs/plugins/README.md))

## The TTML Editor

- Time lyrics syllable by syllable against the song's waveform
- Splits words into syllables automatically, with romanisation kept alongside
- Separates the vocal from the song to time against (demucs, optional)
- Opens and saves TTML, and also opens and exports LRC, Enhanced LRC, ASS,
  KRC, QRC, YRC, LYS and SRT
- Beat lines on the waveform, with snapping
- Multiplayer: time one lyric together, with an invite code and voice chat

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
