# `mild-lyrics/macplayer.py`

Comments lifted out of `mild-lyrics/macplayer.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

**line 60** — before `NEEDS_JS = ("the browser will not run JavaScript for Apple Events yet — "`

> What to tell somebody whose browser will not answer. Both browsers ship with
> Apple Events switched off for JavaScript, and the setting is in a menu that
> is itself switched off by default, so "it does not work" here is nearly
> always this and nothing else.

**line 67** — before `ASK_TIMEOUT = 4.0`

> How long a scripting call is given before it is taken to have hung. An
> osascript that is waiting on a consent prompt waits forever, and a player
> poll that waits forever is a window that never draws again.

**line 74** — before `# --------------------------------------------------------------------------`

> MediaRemote, through ctypes

**line 76** — before `MR_KEYS = {`

> The keys the now-playing dictionary is filled in under. They are the names
> of the framework's exported CFString constants, and the constants hold their
> own names, so the strings can be written here rather than dlsym'd one by one.

**line 93** — before `CF_EPOCH = 978307200.0`

> Seconds between the Unix epoch and the one CoreFoundation counts from.

**line 95** — before `BUNDLE_NAMES = {`

> What a bundle identifier is really called. MediaRemote names the player by
> its bundle id, and that is the only place on a Mac where the name arrives in
> a form nothing else here uses. Anything not on the list falls back to its
> last dotted word, which is right for nearly every application ever shipped.


## `MediaRemote.__init__`

**line 143** — before `self._blocks: dict = {}`

> One block per question, made the first time it is asked and kept.
> A block is a struct the framework calls back into, so it has to
> outlive the call -- and making a fresh one per reading meant a list
> of them growing four times a second, with nothing able to say when
> one was safe to free. There is only ever one request in flight (see
> the lock below), so one block each is all there is to keep.


## `MediaRemote._open`

**line 198** — before `try:`

> Who the card belongs to. Its own pair of symbols, and older builds
> of the framework do not export them -- which costs the player's name
> and nothing else, so it is not allowed to shut the door.


## `MediaRemote`

**line 211** — before `def _block(self, name: str, fn, *argtypes):`

> -- the block, which is the awkward part ------------------------------


## `MediaRemote._block`

**line 240** — on `        blk.flags = 1 << 29`

> BLOCK_IS_GLOBAL


## `MediaRemote`

**line 250** — before `def _text(self, ref) -> str:`

> -- reading CoreFoundation values -------------------------------------


## `MediaRemote._text`

**line 258** — on `        if not self._cf.CFStringGetCString(ref, buf, n, 0x08000100):`

> kCFStringEncodingUTF8


## `MediaRemote._number`

**line 268** — on `        self._cf.CFNumberGetValue(ref, 13, ctypes.byref(out))`

> kCFNumberDoubleType


## `MediaRemote.read`

**line 386** — before `return {}`

> Answered, with nothing in it. On a Mac where the framework
> still talks that means silence; on one where Apple has shut
> it, it means every time. The caller tells the two apart by
> asking somebody else once and seeing whether THEY have a
> song -- see Mac.read.

**line 392** — before `said = got.get("rate")`

> The rate is how fast the elapsed time is running, and it is
> what carries the reading forward from the moment it was true.
> Not every player sets it, and one that does not is not playing
> at zero speed -- it is playing at 1x and has not said so, which
> is why the fallback is the transport's own answer and not the
> missing number.


## module level

**line 421** — before `# --------------------------------------------------------------------------`

> Apple Events

**line 443** — before `MUSIC_APPS = {"spotify": "Spotify", "music": "Music"}`

> The two music players. Both answer in the same tab-separated order so one
> parser does for both, and both are asked whether they are running first --
> of the APPLICATION rather than of System Events, because that is the form
> which does not launch what it is asking about. A lyrics window that started
> Music every time it polled would be a remarkable bug.
>
> The one field they disagree about is the duration: Spotify's scripting
> dictionary gives it in milliseconds and Music's in seconds. It is settled
> here, by which application answered, rather than by how big the number is --
> a track that is four seconds long and a track that is four thousand
> milliseconds long are the same track, and no threshold can tell them apart.


## `music_app`

**line 495** — before `"kind": "music",`

> A music player is playing music. It is the same exemption Spotify
> gets on every other platform, said in the one field that carries it.


## module level

**line 501** — before `PAGE_JS = (`

> What to ask a page. One expression, because that is all `do JavaScript` and
> `execute javascript` will take, and it has to answer for a tab that is
> playing nothing as readily as for one that is.
>
> The element's currentTime is the point of the whole thing. Every other way
> into a browser on any platform -- MPRIS, the Windows transport, MediaRemote
> -- reads a position the browser last wrote down, rounded to the second.
> This is the clock the audio is actually coming out of, to the millisecond,
> which makes a Mac with this switched on the most accurate browser reading
> this program has anywhere.

**line 522** — before `CHROMIUM = {`

> The browsers, and how each is told to run it. Chromium's dictionary counts
> tabs, Safari's counts documents, and that is the whole difference.


## `browser`

**line 602** — before `"kind": "",`

> A page plays its music through a <video> as readily as its films,
> so there is nothing here that says which this is. Left empty on
> purpose: looks_like_a_song has the address, which is the better
> signal, and the lyrics lookup has the last word.


## module level

**line 638** — before `# --------------------------------------------------------------------------`

> CoreAudio: which speaker

**line 641** — before `def _fourcc(code: str) -> int:`

> CoreAudio names its properties with four-character codes, which are just
> big-endian integers wearing a disguise. Spelled out rather than written as
> numbers so they can be read against Apple's headers.

**line 648** — on `CA_SYSTEM = 1`

> kAudioObjectSystemObject

**line 649** — on `CA_DEFAULT_OUT = _fourcc("dOut")`

> kAudioHardwarePropertyDefaultOutputDevice

**line 650** — on `CA_GLOBAL = _fourcc("glob")`

> kAudioObjectPropertyScopeGlobal

**line 651** — on `CA_NAME = _fourcc("lnam")`

> kAudioObjectPropertyName

**line 652** — on `CA_UID = _fourcc("uid ")`

> kAudioDevicePropertyDeviceUID
