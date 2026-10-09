# Third-party notices

Mild Lyrics is licensed under the GNU Affero General Public License, version 3
or (at your option) any later version, except for the code ported from AMLL,
which is version 3 only (see `LICENSE` and the README). Parts of it are ports
of other people's code, listed here with their licenses. Libraries that are
installed separately and only imported (PyQt6, pykakasi, torch and the rest of
what `mild-setup.py` installs) are not copied into this repository and keep
their own licenses.


## Ported code

### applemusic-like-lyrics (AMLL)

<https://github.com/amll-dev/applemusic-like-lyrics>
Copyright (C) Steve-xmh and the AMLL contributors.
Licensed under the GNU Affero General Public License, version 3 only.

In `mild-lyrics/renderers.py`, the per-letter emphasis and float of the `amll`
renderer (from `packages/core/src/lyric-player/dom/animation/{emphasize,float}/index.ts`)
and the solved spring `Spring` (from `packages/core/src/utils/spring.ts`,
`packages/core/src/lyric-player/base/spring.ts` and `derivative.ts`).

### Spicy Lyrics

<https://github.com/Spikerko/spicy-lyrics>
Copyright (C) Spikerko and the Spicy Lyrics contributors.
Licensed under the GNU Affero General Public License, version 3.

In `mild-lyrics/renderers.py`, the `Spicy` renderer: a port of
`src/utils/Lyrics/Animator/Lyrics/LyricsAnimator.ts`, its DOM applyer,
`Emphasize.ts`, `IsLetterCapable.ts`, `Shared.ts`, `ScrollToActiveLine.ts`,
`LyricsVirtualizer.ts` and the CSS in `src/css/Lyrics/Mixed.css`.

### spr

<https://github.com/Fraktality/spr>
Copyright (c) 2023 Fractality.
Licensed under the MIT License (text below).

In `mild-lyrics/renderers.py`, the stepped spring `_Spr`, as Spicy Lyrics
ships it.

### QQMusicDES

<https://github.com/wangqr/QQMusicDES>
Copyright (c) 2019 wangqr.
Licensed under the MIT License (text below).

In `mild-lyrics/lyric_sources.py`, the DES that decrypts QQ Music's QRC
files.

### crypto-algorithms

<https://github.com/B-Con/crypto-algorithms>
By Brad Conte, released into the public domain.

The textbook DES that QQMusicDES is built on. No license applies; credited
at the author's request.


## Request shapes

The Musixmatch request in `mild-lyrics/lyric_sources.py` follows the one
Spicetify's lyrics-plus makes (`CustomApps/lyrics-plus/ProviderMusixmatch.js`,
<https://github.com/spicetify/cli>, LGPL-2.1).


## MIT License

Applies to spr and QQMusicDES, each under its own copyright line above.

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.
