# `mild-lyrics/genius_roman.py`

Comments lifted out of `mild-lyrics/genius_roman.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

**line 167** — before `NOT_A_SONG = re.compile(r"\b(track ?list|tracklist|album art|booklet|credits|"`

> Titles that are not a song anybody wants to hear: a DJ set's contents, a
> booklet, the credits page. They are posted as songs on Genius and they match
> a lyric query beautifully, because they contain every line of thirty songs.

**line 172** — before `A_VERSION = re.compile(r"\b(cover|remix|demo|live|acapp?ella|a cappella|"`

> ...and titles that ARE the song, but not the recording being looked for.
> Only a penalty, and only when the query did not ask for one: somebody
> searching "in the end demo" should still be given the demo.

**line 181** — before `GENIUS_ACCOUNT = re.compile(r"genius\s*(users|translations?|romani[sz]ations?|"`

> The accounts Genius keeps a song's paperwork under: the translation, the
> romanisation, the annotated copy. Real pages about a real song, and the
> right one to import a romanisation FROM -- but never the thing to play, so
> they sit under the record itself rather than above it.

**line 188** — before `MIN_HIT = 0.55`

> Below this a hit is not an answer to the question, it is a song with the
> words in it somewhere -- a DJ set's track list, a poem that shares a noun.
> Showing nothing is the better answer there.


## `score_song`

**line 232** — before `if kq and kq == key(title):`

> The query IS the name. Worth stating outright rather than leaving to a
> ratio, which reads "Poker Face" against "Poker Face Lady Gaga" as 0.67
> and lets any song with the words somewhere in it past.

**line 240** — before `said = (min(1.0, 0.55 + 0.03 * len(kq)) if kq and kq in kl`

> A LINE CONTAINED IS ONLY AS GOOD AS THE LINE IS LONG. Twenty-five
> letters found inside a lyric is the song; nine ("poker face") is a
> coincidence, and scoring it 1.0 put Kendrick Lamar above Lady Gaga
> for her own single. Full marks arrive at about fifteen letters.


## `rank_hit`

**line 259** — before `return 0.0, "name"`

> Not a penalty but a floor: a DJ set's track list holds every line of
> thirty songs, so it answers a long lyric query perfectly and is
> never the thing anybody was looking for.


## `search_lyrics.take`

**line 310** — before `score = max(score, was[0])`

> The same song out of two sections: keep the better score, and
> the snippet, which only the lyric section carries.

**line 315** — before `line = ""`

> It is the NAME that was searched for, and this song has it. The
> lyric section will still have handed over a line, and showing
> that line as the headline made the answer to "in the end" read
> "But in the end, it doesn't even matter" -- a quotation where a
> song title was asked for.


## `credit_of`

**line 430** — before `verified.append(f"{name} ({role})"`

> "Verified by Eminem (Verified Artist)" says the same thing twice.


---

## Earlier lift — 2026-08-23

Comments lifted out of `mild-lyrics/genius_roman.py` on 2026-08-23, before the work that followed. They are not in the code any more, so they are kept here as they were; the line numbers are the ones that code had then.

### module level

**line 39** — before `ROMAN_HINT = re.compile(r"romani[sz]ed|romani[sz]ation|\bromaji\b", re.I)`

> what marks a Genius entry as a romanisation rather than the original


### `search`

**line 54** — before `clean_title = re.sub(r"[\(\[\{].*?[\)\]\}]", "", title).strip()`

> Clean queries to prevent search index errors

**line 71** — before `if token:`

> Strategy 1: Official API (requires Bearer Token)

**line 88** — before `try:`

> Strategy 2: Genius Web Multi-Search (Same endpoint used by genius.com frontend)

**line 96** — before `if sec.get("type") in ("top_hit", "song"):`

> Target song hits and top hits

**line 106** — before `if any(is_romanization(h) for h in hits):`

> Stop only once something claiming to BE a romanisation has turned up.
> Stopping on any hit at all meant the plain "<title> <artist>" query --
> which nearly always returns the original song and nothing else -- ate
> the whole budget, and the Romanized/Genius Romanizations queries that
> actually find these entries never ran. That alone was most of the
> "no romanised version found" results.

**line 115** — before `hits.sort(key=lambda h: not is_romanization(h))`

> romanisations first, so find_romanization does not spend a fetch on the
> original before reaching them


### `lyrics_for`

**line 162** — before `chunk = js`

> The embed is JavaScript writing a JSON-encoded HTML blob, so the markup is
> escaped twice. Unescaping the two levels by hand left the backslashes half
> eaten, the rg_embed_body match then failed, and clean_lines() was handed
> the whole script -- "document.write(JSON.parse(...", "Powered by Genius"
> and a stray backslash per blank line all entered the song as lyrics and
> went into the alignment. Undo the JS string escapes, then let json do the
> inner layer.


### module level

**line 190** — before `STYLE_TAGS = {"i": "i", "em": "i", "b": "b", "strong": "b"}`

> Genius marks who is singing with type styling, and declares what the styling
> means in the section header: "[Verse 1: RM, <i>RM & Jung Kook</i>, <b>j-hope</b>]"
> says plain is RM, italic is the two of them together, bold is j-hope. The
> legend is re-declared at every header, which is the only place the mapping
> ever changes -- so nothing here has to guess a convention, and a song that
> swaps its styling halfway is read correctly.
>
> Asterisks are the fifth style, used on songs with more artists than the four
> type styles can carry.


### `_styled`

**line 233** — before `if not style and re.fullmatch(r"\s*\*[^*]+\*\s*", words):`

> Asterisks only count when they wrap the line rather than sit inside a
> word, so "*ay*" is a voice and "5*7" is arithmetic.


### `legend`

**line 280** — on `    for n, ch in enumerate(body):`

> split on commas outside any tag

**line 290** — before `who = re.sub(r"\s*\([^)]*\)\s*$", "", who).strip()`

> "Lil' Kleine (Boef)" is Lil' Kleine with Boef behind him, not a
> third person. Left alone it splits one singer into two and the
> line counts that decide the voices come out wrong.

**line 294** — before `if who.startswith("*") and who.endswith("*"):`

> An asterisked name in a header is the fifth voice, same as in a
> line -- songs with more artists than the type styles can carry.


### `voiced_lines`

**line 317** — before `if _annotation(bare):`

> The same filter clean_lines applies, deliberately: this changes who a
> line is credited to and must never change which lines there are, or
> the aligner would be timing a different set of words than before.

**line 323** — before `got = legend(line)`

> A new section re-declares the mapping. One without a legend --
> "[Instrumental Intro]" -- says nothing about voices, so the
> previous section's mapping is kept rather than cleared.


### `sides`

**line 368** — on `            side = last`

> unattributed: stay where we are

**line 374** — on `            side = False`

> both sing it and one of them is v1

**line 385** — before `out, last, prev = [], False, None`

> Alternate on every change of singer instead, ignoring who they are.


### module level

**line 404** — before `BOILER_FIRST = re.compile(r"^\s*songtekst\s+van\b", re.I)`

> Some Genius pages still carry a title line from an older style guide -- the
> Dutch ones say 'Songtekst van Boef – "Wejoow" ft. Lil\' Kleine'. It is not
> sung, and left in it becomes the song's first line and gets timed as though
> it were. Only ever the first line, so a lyric that happens to say the words
> later keeps them.

**line 496** — on `MAX_JOIN = 4`

> most Genius lines one sung line is allowed to swallow

**line 498** — before `REVISION = 3`

> Bump whenever the matching below changes shape. A stored alignment is only
> as good as the code that produced it, and results are cached per track --
> without a stamp, a track aligned by an older, worse version kept its old
> answer forever and the improvement never reached the song you were playing.


### `align`

**line 526** — before `score = [[0.0] * (m + 1) for _ in range(n + 1)]`

> score[i][j] = best total over the first i of ours and j of theirs

**line 528** — before `back = [[(2, 0)] * (m + 1) for _ in range(n + 1)]`

> back[i][j] = (move, run); 1 take a run of `run` theirs, 2 skip ours, 3 skip theirs

**line 531** — before `ko = key(ours[i - 1])`

> one matcher per row: it caches the analysis of seq2, and rebuilding
> that for every cell dominated the runtime

**line 544** — before `la = len(joined)`

> length alone caps the ratio at 2*min/(la+lb); once the run has
> outgrown our line, every longer run caps lower still, so stop
> rather than scoring the rest of them

**line 551** — before `if sm.real_quick_ratio() < min_score or sm.quick_ratio() < min_score:`

> cheap upper bounds first -- most cells never need the real one


### `rebalance`

**line 591** — before `if any(ours[x].strip() and x not in mapping for x in range(a + 1, b)):`

> only adjacent lines, allowing for unmatched blanks between them


### `unmerge`

**line 633** — before `spans = []`

> The merged text can land on either of the lines it covers, so look up
> as well as down: 「何度だって生きる」/「お前や君の中」 came back with
> the whole "Nando datte ikiru omae ya kimi no naka" on the SECOND line
> and nothing on the first.

**line 652** — before `total = sum(scores) / len(scores)`

> splitting has to explain the line better than leaving it whole
