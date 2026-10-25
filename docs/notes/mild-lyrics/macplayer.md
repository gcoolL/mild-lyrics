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

## Lift — 2026-10-25

Docstrings shortened in `mild-lyrics/macplayer.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> What is playing on a Mac, by whichever of the three doors is open.
>
> macOS has no session bus and no media transport that a program may simply
> ask. What it has is:
>
>   * MEDIAREMOTE, a private framework behind the now-playing card in Control
>     Centre. It is the true equivalent of MPRIS -- one answer covering every
>     player on the machine, browsers included, with an elapsed time, the
>     moment that elapsed time was true, the rate it is running at, and the
>     artwork as bytes. It is also the door Apple closed: since macOS 15.4 the
>     functions answer nothing unless the caller carries an entitlement no
>     third-party program can have. So it is TRIED, and where it answers it is
>     used for everything, and where it does not the other two carry it.
>
>   * APPLE EVENTS to the music players. Spotify and Music both publish a
>     scripting dictionary with an exact player position in it -- better than
>     anything MPRIS gives, since it is the player's own clock rather than a
>     property sampled off a bus. The first ask raises the Automation consent
>     prompt; a refusal is not a crash, it is this door reporting itself shut.
>
>   * APPLE EVENTS INTO A BROWSER'S PAGE, which is how a song playing on
>     YouTube reaches the window on a Mac with MediaRemote closed. Safari and
>     the Chromium browsers will run a line of JavaScript in a tab for us,
>     which reads the page's own MediaSession card and -- the part no other
>     door on any platform gives -- the media element's currentTime, which is
>     the exact position rather than a figure rounded to the second. Both
>     browsers ship with that switched OFF; see NEEDS_JS, which is the message
>     the window and the doctor both show.
>
> Nothing here knows about lyrics, the window, or the transport that wraps it.
> It answers one question -- who is playing what, and where have they got to --
> and answers it as plain dictionaries, so it can be tested without a Mac by
> handing the two readers something else to run.
>
> One thing here is not about players at all: default_output, which names the
> speaker the sound is coming out of. It lives here because it is the same kind
> of thing -- a fact about this Mac that takes a framework to ask for -- and
> because putting it anywhere else would mean a second ctypes preamble.

### `MediaRemote`

**line 73** — from the docstring, `class MediaRemote:`

> The private framework, resolved once, or a closed door that says why.
>
> `ok` answers whether the framework is HERE -- loaded, with the symbols
> this calls exported. It does not answer whether it will tell you anything,
> because that is not a question it can be asked: since macOS 15.4 an
> unentitled caller gets a framework that loads, symbols that resolve, calls
> that succeed and an empty card, which is byte for byte what a Mac with
> nothing playing looks like. `read` returns {} for both, and telling them
> apart means asking somebody else whether they have a song -- which is
> MacTransport's job, not this one's.

### `MediaRemote._block`

**line 141** — from the docstring, `def _block(self, name: str, fn, *argtypes):`

> A C function wrapped as an Objective-C block, made once and kept.
>
> MediaRemote answers by calling a block, and a block is a struct whose
> fourth word is a function pointer -- so one can be built out of ctypes
> without an Objective-C runtime in sight. It has to be kept alive for
> as long as the framework might call it, which here is for the life of
> this object: `fn` reads what the caller left in `_landed`, and the
> lock above means there is never more than one caller.

### `MediaRemote.who`

**line 217** — from the docstring, `def who(self) -> str:`

> The short name of whoever the card belongs to, or "".
>
> Asked separately from the card because the framework keeps it
> separately, and cached for a moment because the answer only changes
> when somebody else starts playing. "" is a real answer and the caller
> must cope with it: the two symbols behind this are the first thing an
> older MediaRemote is missing.

### `MediaRemote.read`

**line 251** — from the docstring, `def read(self) -> dict | None:`

> The now-playing card, or None if this door is shut.
>
> None and an EMPTY card are two different answers and both happen: shut
> is shut, and an empty card is a Mac with nothing playing. The
> difference is what stops the transport falling back to Apple Events
> every time somebody pauses.

### `run_script`

**line 321** — from the docstring, `def run_script(source: str, timeout: float = ASK_TIMEOUT) -> str:`

> One AppleScript, its output, and "" for every way it can fail.
>
> Never raises. A player that is not installed, a consent prompt that was
> refused, a browser with JavaScript from Apple Events switched off and
> osascript itself missing all arrive here as the same empty string, and
> the caller's next move is the same for all of them: ask somebody else.

### `browser`

**line 437** — from the docstring, `def browser(which: str) -> dict | None:`

> A browser's playing tab, read through the page itself. None if shut.
>
> None covers every reason there is nothing here: the browser is not
> running, no tab is playing, the user never switched on Apple Events for
> JavaScript, or they refused the Automation prompt. Which of those it was
> is not knowable from the outside -- `checked` below is what tells the
> difference, and it is asked once by the doctor rather than four times a
> second by the window.

### `checked`

**line 475** — from the docstring, `def checked(which: str) -> tuple[bool, str]:`

> Whether this browser will run JavaScript for us, and why not.
>
> For the doctor and for the one toast the window shows. Told apart by
> asking for something every page can answer: a browser that is merely
> playing nothing returns an empty document title, and one that has Apple
> Events switched off for JavaScript returns an error instead.

### `default_output`

**line 503** — from the docstring, `def default_output() -> tuple[str, str]:`

> The Mac's current output device: (a stable id, a name to show).
>
> ("", "") for every way there is nothing to say, which on a Mac is only
> ever "this is not a Mac" or "CoreAudio would not answer" -- there is no
> optional piece to install and no permission to grant.
>
> It is the DEFAULT device rather than the player's own stream, and unlike
> PipeWire there is no per-application route to ask about: macOS has no user
> -facing way to send one app to a different output, so the default is the
> output, for every application on the machine.
