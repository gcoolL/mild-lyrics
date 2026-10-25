# `editor/sources.py`

Comments lifted out of `editor/sources.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

**line 129** — before `_apple_token = LS._apple_token`

> Apple's catalogue API, borrowed whole from the chain: it needs a developer
> token scraped out of the web player's own JavaScript, and lyric_sources
> already gets one there to look up the ISRC BiniLyrics files by. Two copies
> of that meant two token files, two scrapes of a three-megabyte bundle, and
> two chances to drift apart on how the token is checked.

**line 169** — before `WROTE_IT = ("composition", "lyrics", "writing")`

> What Apple calls the part of the credits that is the SONG rather than the
> recording. Everything under it wrote the thing; everything else played it,
> produced it or engineered it.


## `apple_credits`

**line 221** — before `writer = (any(any(w in r for w in WROTE) for r in roles)`

> By the ROLE, not by the heading it is filed under: the
> composition section also holds arrangers and the band name,
> and neither wrote the song. The heading is only consulted
> when Apple lists no role at all.


## module level

**line 239** — before `_split_names = LS.apple_names`

> One credit line as the people in it. The chain cuts Apple's credits apart
> for the same reason and on the same three separators, so it is read from
> there rather than written twice -- two spellings of "who counts as a name"
> would put different <songwriter> tags in a file depending on which button
> filled them in.


## `chain_doc`

**line 355** — before `try:`

> Not where one source was asked for BY NAME. The roster is about what
> gets played, and this window is where a sync gets fixed: naming the
> source is asking to see what it has, and a refusal that answered
> "nothing found" to a question that specific would read as the door
> being down.

**line 365** — before `raise RuntimeError(f"{', '.join(want) or 'the chain'}: "`

> Not swallowed. A chain that threw and a chain that found nothing
> both came back as "nothing found", so the one fault worth knowing
> about -- a provider erroring, a missing key, no network -- was
> indistinguishable from a song simply not being in any database.
> The window runs this on a worker that turns a raising job into a
> message, which is where this belongs.


## `detect_roles`

**line 455** — before `counts = [len(M.words_in(text)) for text, _ in want]`

> words_in, not split(). The document's words are cut with words_in,
> which keeps French's spaced punctuation on its word -- "Pourquoi ?"
> is ONE word there and two to split(). The counts then disagreed,
> the line was skipped, and "Find ad-libs" silently did nothing on
> every line with a ? ! : ; or « » in it.


## `fetch_audio`

**line 559** — before `kept = LA._kept(key)`

> Kept before the `with` closes, because that is what deletes it.


---

## Lift — 2026-10-25

Docstrings shortened in `editor/sources.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> Where the words and the credits come from.
>
> Three suppliers, each asked for the thing it is actually good at:
>
>   * Genius for the TEXT. It is edited by people who are listening to the
>     song, it marks who sings what in its section headers and its typography,
>     and it is the only one of the three that knows an ad-lib is an ad-lib.
>   * the Mild Lyrics chain for a document somebody has already timed --
>     amll-ttml-db, LRCLIB, NetEase, QQ and the rest, exactly as the player
>     ranks them. That is the right starting point when the job is to fix a
>     sync rather than to make one.
>   * Genius and Apple Music for the SONGWRITERS, which neither the words nor
>     the timings carry.
>
> Nothing here touches the GUI, and every call returns something ordinary --
> a Doc, a list of names, or None -- so the window can run all of it on a
> worker thread.

### `genius_hits`

**line 33** — from the docstring, `def genius_hits(token: str, title: str, artist: str, timeout: float = 8.0) -> list[dict]:`

> Songs Genius thinks this might be, best first, translations dropped.
>
> Raises where Genius could not be ASKED, and answers an empty list where it
> was asked and knows no such song. Those are two different things to be
> told and they used to arrive as the same empty list -- which is how "no
> Genius token", "a proxy in front of the request" and "Genius has never
> heard of this song" all came out on the status line as `Genius has nothing
> for that`, on Windows in particular, where a TLS interception sits in front
> of the request often enough to be the first thing to suspect.

### `genius_doc`

**line 54** — from the docstring, `def genius_doc(token: str, song_id: int, timeout: float = 8.0) -> M.Doc | None:`

> One Genius song as an untimed document, voices and ad-libs and all.
>
> Genius' own markup is read rather than thrown away: its section headers
> name who sings each part, its typography marks which of them is singing
> each line, and a trailing parenthesis is an ad-lib. That is precisely the
> three things a TTML needs and nothing else here can infer -- so a document
> fetched this way arrives with its duet sides and its backing vocals
> already set, and the editor's job is to check them rather than to make
> them.
>
> Raises where the page could not be read, for the same reason genius_hits
> does: a song whose lyrics nobody has written down yet and a request that
> never left the machine are not the same news.

### `apple_songwriters`

**line 126** — from the docstring, `def apple_songwriters(title: str, artist: str) -> list[str]:`

> Apple's composer credit for this song, as a list of names.
>
> Apple writes them as one string -- "Chris Martin, Guy Berryman, Jonny
> Buckland & Will Champion" -- so it is split back apart here, which is the
> shape TTML wants (one <songwriter> each) and the shape Genius already
> hands over.

### `apple_credits`

**line 155** — from the docstring, `def apple_credits(title: str, artist: str) -> dict:`

> Apple's credits for this song, by the role each person is under.
>
> Richer than `composerName`, which is one flat string with everybody in
> it: this keeps the roles Apple files them under, so the people who WROTE
> the song can be told from the people who produced or engineered it.
>
> Not legal names, though. Apple's credits carry the same performing names
> Genius does -- Love Blur's writers come back "slayr" and "waera .", not
> the names on the publishing. Nothing reachable from here carries those:
> MusicBrainz models a legal name as a relationship and does not have one
> for most artists, and the PRO repertories (ASCAP, BMI) refuse machine
> access outright. So this is offered for what it is.

### `apple_writers`

**line 206** — from the docstring, `def apple_writers(meta: dict) -> tuple[list, str]:`

> Apple's writer credits for this song, and where they came from.
>
> Kept apart from songwriters() because it answers a different question.
> Genius lists who its editors credit; Apple lists what the publishing
> says, which is where a legal name appears when there is one -- luther
> comes back with "Roshwita Larisha Bacha" and "Mark Anthony Spears" where
> Genius has "Ink" and "Sounwave". On a self-released track the publishing
> is the artist's own name and both say the same thing.

### `songwriters`

**line 219** — from the docstring, `def songwriters(meta: dict, token: str = "", song_id: int | None = None) -> tuple[list, str]:`

> Who wrote this song, and who says so.
>
> Genius first because it separates writers from producers and Apple does
> not, and Apple second because it carries songs Genius has never had a
> page for. Whichever answers is the answer; they are not merged, since two
> databases spelling the same four people differently would put eight names
> in the file.

### `player_sources`

**line 236** — from the docstring, `def player_sources() -> tuple[list, set]:`

> Which providers the player asks, and in what order.
>
> Read from its settings rather than assumed. Asking the chain with no
> preferences at all walks lyric_sources.PROVIDERS with everything switched
> on -- which is not what the player does, and on one machine meant the
> editor answering with a blend (which had been switched OFF, and which merges
> Apple's TTML in) where the player would have answered with the community
> db.
>
> The player's settings are a list of SOURCES and the chain wants providers,
> so the same expansion the player does is done here -- otherwise the two
> disagree about who is even being asked.

### `player_people`

**line 290** — from the docstring, `def player_people() -> LS.Roster:`

> Whose syncs the player refuses, and whose it prefers.
>
> Read from its settings for the same reason player_sources is: the editor
> fetching a starting point wants the document the player would have put on
> screen, and a contributor the user has said no to is no more wanted here
> -- fixing somebody's sync is not a way to be handed it.

### `chain_doc`

**line 297** — from the docstring, `def chain_doc(tid: str, meta: dict, order=None, only: str = "",`

> The best document Mild Lyrics can find for this track, and its source.
>
> `force` because the editor is asking on purpose: the chain caches its
> answer for the player's benefit, and a user pressing "fetch" wants the
> lookup done, not the last one repeated.
>
> `only` asks one named provider and nothing else -- for when the chain's
> ranking is not the question and a particular source is.
>
> `note` is handed the sources that could not be reached, the same way the
> player's walk hands them over. A door being down and a song not being
> behind it read identically here -- "had nothing for it" -- and asking one
> named source is exactly where the difference matters.

### `_borrow_duet`

**line 338** — from the docstring, `def _borrow_duet(doc: M.Doc, body, tid: str, meta: dict) -> bool:`

> Fill in the second voice from amll-ttml-db, where the source had none.
>
> Most providers do not carry the flag at all -- LRCLIB and QQ have nowhere
> to put it, and a good share of Spicy Lyrics' own entries are duets with it
> never set. amll keeps the TTML agents, so it is the one place to ask. The
> player already does this and caches the answer; this is the same call, so
> a document fetched here comes out marked up the same way the player would
> have marked it.
>
> Only where nothing is flagged already: overwriting a source that DID say
> who sings what with somebody else's reading trades one answer for another.

### `detect_roles`

**line 371** — from the docstring, `def detect_roles(doc: M.Doc, alternate: bool = False) -> str:`

> Find the ad-libs from the text alone.
>
> Only the shapes that are conventions rather than guesses:
>
>   * a whole line inside brackets is a backing line;
>   * a trailing bracketed run is an ad-lib answering the line it follows;
>   * a line ALREADY carrying a backing group is left alone.
>
> `alternate` used to stripe every other line onto the second voice. It is
> gone: striping is a convention applied to a song nobody has read, it says
> nothing true about who sings what, and on a lyric that already had its
> sides marked it threw that reading away. What the button does now is
> ops.swap_agents, which mirrors the reading instead of replacing it. The
> argument is still accepted so old callers do not break, and ignored.

### `audio_key`

**line 412** — from the docstring, `def audio_key(artist: str, title: str) -> str:`

> A stable filename for a song that has no track id of its own.
>
> The player keys its kept copies by Spotify id, which is the right key
> when there is one and no key at all when the words came from Genius or a
> file. A slug of the two names is the next best thing: it is stable across
> sessions, so the second time somebody asks for a song they get the copy
> instead of the download, and the hash on the end keeps two songs whose
> names slugify the same from overwriting each other.

### `fetch_audio`

**line 424** — from the docstring, `def fetch_audio(title: str, artist: str = "", length: float = 0.0,`

> A copy of this song on disk to time against. Returns (path, warning).
>
> The editor has always been able to fetch the WORDS and never the song
> they belong to, which left one job -- find a recording -- as the only
> thing somebody had to leave the program to do. Worse, it left them doing
> it by hand, and a hand-found file is how a 212-second recording came to
> be open behind a 103-second lyric with nothing saying so.
>
> `local_align.fetched` is the player's own fetcher and it does the part
> that matters: it searches by name AND length, and then plays the
> candidate to a speech model to check the words it hears are this song's
> words, against a handful of other songs as decoys. A recording of the
> wrong song at the right length is the failure this catches and a length
> check alone cannot. Pass `words` -- from the document that is open -- and
> that check runs; leave it out and it cannot.
>
> The copy is KEPT, unlike the player's use of the same call, where it is
> deleted the moment the alignment finishes. An editor holds a song open
> for an afternoon, and re-downloading it every time the window opens would
> be both slow and rude to whoever is hosting it. It lands in the same
> store the player fills, under the same 8 GB cap, so `caches.py` can see
> it and the Storage dialogue can clear it.
>
> Raises RuntimeError with `fetched`'s own words when there is no copy to
> be had -- those explain three quite different failures and are worth
> passing through unedited.

### `audio_hits`

**line 466** — from the docstring, `def audio_hits(title: str, artist: str = "", length: float = 0.0) -> list[dict]:`

> Every recording the search turned up, for somebody to choose from.
>
> The same search fetch_audio makes, stopped before anything is picked:
> what it would have tried first comes first, then the rest of what fits
> the length, then the ones that do not, closest first. Each row carries
> the upload's title, who put it up, where, and its length.
>
> SoundCloud Go+ copies are not rows at all, since picking one could only
> fail; `audio_hits.gated` says how many were left out. Raises RuntimeError
> with the reason when there is nothing to offer.

---

## Earlier lift — 2026-08-23

Comments lifted out of `editor/sources.py` on 2026-08-23, before the work that followed. They are not in the code any more, so they are kept here as they were; the line numbers are the ones that code had then.

### module level

**line 46** — before `# --------------------------------------------------------------------------`

> Genius: the words, and who sings them


### `genius_doc`

**line 94** — before `ln.lead, ln.bg = ln.bg[0], ln.bg[1:]`

> A line that is nothing but an ad-lib is a backing LINE. Left as
> a lead with no words it would render as an empty <p>.


### module level

**line 131** — before `# --------------------------------------------------------------------------`

> Apple Music: songwriters, through the web player's own key


### `apple_songwriters`

**line 221** — before `if want_t and want_t not in L._akey(at.get("name") or ""):`

> Apple's search is generous in the same way Genius' is; a cover or a
> karaoke version credits different people, so the hit has to look
> like the song that was asked for.


### module level

**line 262** — before `# --------------------------------------------------------------------------`

> the player's own chain

**line 367** — before `# --------------------------------------------------------------------------`

> roles, for documents that arrive without them


### `detect_roles`

**line 390** — before `want = ([(b, True) for b in head] + [(lead, None)]`

> One group per bracketed run, not one group per END. "(ooh) (aah)"
> is two answering voices and a player draws them as two rows; run
> together they came out as a single group spelling "ooh) (aah".

**line 397** — on `            continue`

> the words do not add up; leave it be
