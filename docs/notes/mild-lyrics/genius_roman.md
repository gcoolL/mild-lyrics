# `mild-lyrics/genius_roman.py`

Comments lifted out of `mild-lyrics/genius_roman.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).

## 2026-10-13 — by_lyrics, the third way in

Genius files Japanese titles as "Japanese (Romanised)". Spotify's English catalogue often gives a translation instead ("SIGN IS B - AI SOLO VER." for サインはB -アイ Solo Ver.-, "New Genesis" for 新時代), which neither half contains, so both name passes miss. `by_lyrics` searches Genius's lyric index with our three longest lines that need romanising. It takes a song that at least two of them find, then that song's linked romanisation (or the page itself, where it is one). One line alone can be a quote. Three lines may not all agree, because Genius files several pages under one title (アイドル). `believable` in `on_genius` still rejects a wrong song. It runs only after both name passes miss: three web searches, then up to three song records.

Measured over the cached romanisable tracks, against whole-line `SL.reading`: the 8 with a saved Genius map all found the same page and fit (44/44 to 88/91). Of 14 with none, 10 now fit (ダダダダダル 72/72, STAR☆T☆RAIN -Ai Solo Ver.- 66/71, ルル 55/67) and 4 found nothing. One of those, 充Den中, has a Genius page but no romanisation.

## 2026-10-12 — names, NetEase fitting

**name_keys / names_meet.** STAR☆T☆RAIN - NEW ARRANGE VER. (B小町, ルビー(CV:伊駒ゆりえ), 有馬かな(CV:潘めぐみ), MEMちょ(CV:大久保瑠美)) has a Genius romanisation filed as "B小町 (B-Komachi) - …", and the original under "B小町 ルビー (CV:伊駒ゆりえ) (B-Komachi Ruby (CV: Yurie Igoma))". Both `by_us` and `ours` compared each credit as one string, so neither page matched. Each name now also matches by its words outside brackets and by each bracket's contents (a "CV:" prefix dropped). Containment counts only for keys of 3+ characters.

**fit_pairs.** Fits NetEase's (text, romanisation) pairs to another source's lines. Exact text after NFKC/case/punctuation folding first, then `align` by reading (a kakasi reading where the line has no Latin one), kept only if `believable`. Measured on three cached songs: 17/32 → 32/32, 68/68, 11/33 → 33/33.

**_words cuts after commas.** NetEase joins a printed line with 、 ("Miraa、miraa、mirareru、kiraa、parareruwaarudo"), so `unmerge` had nowhere to cut it across the two screen lines.

## 2026-10-13 — backing rows between lead lines

**align(asides=…).** The player and the editor hand `align` their backing-vocal rows as lines of their own, between the lead lines. In YOASOBI's アイドル a "Hey, hey, hey, hey" row sits between every pair, so `rebalance` (adjacent mapped lines only) never paired 「今日も嘘をつくの」 with 「この言葉が…」 and "kono kotoba ga" stayed on the first. And `unmerge` (contiguous rows only) could not cut "Sore demo mada kimi to kimi ni … Dake wa iezu ni ita kedo" across 「それでもまだ」/「君と君にだけは…」: the first got nothing. The callers now name the backing rows. `rebalance` pairs lead lines across them; `unmerge` also tries spans of lead lines, alongside the contiguous ones (which still carve a bracketed ad-lib onto the backing row). With no asides, both behave as before.

**drop_echoed_adlibs and roman_own.** The check "does the line sing this ad-lib itself?" read the line's current reading. Once Genius's reading was on the line, a refetch found the "(Hey! Hey!)" in it and kept it, and that was what got saved. It now reads `roman_own`, the line's reading from before any fix. REVISION 6 re-asks for the readings saved that way.


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

## Lift — 2026-10-25

Docstrings shortened in `mild-lyrics/genius_roman.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### `why`

**line 52** — from the docstring, `def why(exc: BaseException, limit: float = 0.0) -> str:`

> One short line for what a request to Genius did instead of answering.
>
> The status codes are spelled out because each of the three says something
> different and only one of them is about the song: 401 is the token, 403 is
> Genius refusing this machine, 429 is this machine having asked too often.
> Every caller here catches and answers empty, and "nothing came back" read
> the same for all three -- which is how a door that was shut looked exactly
> like a song nobody had written down.
>
> Everything else is unwrapped once. A network failure arrives as URLError
> wrapping the thing that actually went wrong, and the wrapper's own str is
> "<urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] ...>" -- the inner reason
> is the sentence somebody can act on, and on Windows it is usually the whole
> answer: a proxy or a TLS interception standing in front of the request.

### `is_song`

**line 128** — from the docstring, `def is_song(hit: dict) -> bool:`

> A song entry, not an album or artist.
>
> The web multi-search top_hit section returns albums too, and an album for
> "<song> (Romanized)" has a romanisation-shaped title and passes every check
> below. Its id then went to /songs/<id>/embed, which is a different id space
> -- so KICK BACK imported the lyrics of whatever song happened to hold that
> number, and put them on the track as its romanisation.

### `_snippet`

**line 151** — from the docstring, `def _snippet(hit: dict) -> str:`

> The one lyric line Genius says it matched, out of the snippet it sends.
>
> A lyric hit carries a few lines of context with the matched characters
> marked by offset, and the line worth showing is the one holding most of
> those marks -- the first and last lines of a snippet are usually cut
> mid-phrase, so the longest or the first would both often be a fragment.

### `_pop`

**line 189** — from the docstring, `def _pop(hit: dict) -> float:`

> Genius's pageview count, flattened to 0..1.
>
> The difference that matters here is between three million and five
> thousand -- the original against somebody's bedroom cover of it -- and on
> a straight count that difference would swamp every other signal, so it is
> read as its order of magnitude.

### `score_song`

**line 201** — from the docstring, `def score_song(query: str, title: str, artist: str, line: str = "",`

> How well a song answers what was typed, and on which of its two halves.
>
> One query gets asked two different questions -- is this the song's NAME,
> or a LINE from inside it -- and the good answer looks different for each,
> so both are scored and the better one is taken. Which one won is worth
> knowing beyond the number: it is the difference between a row that should
> read "In the End -- Linkin Park" and one that should read "But in the end,
> it doesn't even matter".
>
> Popularity settles what the words cannot. "In the End" by Linkin Park and
> "In The End (Linkin Park Cover)" by RADIO TAPOK are near enough identical
> as text, and three million pageviews against five thousand is the whole
> difference between them.

### `search_lyrics`

**line 241** — from the docstring, `def search_lyrics(query: str, token: str = "", limit: int = 6,`

> Songs that answer `query`, whether it is a name or a line, best first.
>
> The web multi-search is the endpoint that reads the lyrics: its `lyric`
> section matches a phrase inside the song rather than in its name, and
> hands back the snippet it matched with the matching characters marked, so
> the line the user half-remembered can be shown back to them.
>
> Section order is NOT taken as ranking. Genius returns each kind of match
> in its own section and the one that answers the question depends on what
> was asked -- "in the end linkin park" put a DJ set's track list and a
> Jay-Z mashup above Linkin Park, because those are what the LYRIC section
> had and the lyric section was read first. Everything is scored against
> what was typed instead; see rank_hit.
>
> The API search is a fallback rather than a supplement, for the same
> reason: it matches names only, has no idea which of them is the record
> everybody means, and on a query the web search already answered it adds
> nothing but other people's covers.
>
> Never raises: this runs behind a keystroke, and a search that cannot reach
> Genius should leave the local hits alone rather than take the screen down.

### `_user_name`

**line 304** — from the docstring, `def _user_name(one) -> str:`

> A Genius user's display name.
>
> `login` and `name` differ on an artist account -- eminem against Eminem --
> and the second is the one anybody reading a credit line wants. Both are
> present on every user object this asks about, so this is a preference and
> not a fallback chain with a hole in it.

### `credit_of`

**line 354** — from the docstring, `def credit_of(song: dict) -> str:`

> Who vouched for this Genius lyric, as one line -- or "".
>
> NOT the transcribers, which is what this was originally asked for and
> what Genius does not hand over: the embed carries a contributor COUNT and
> no names, and nothing reachable turns that into people. What it does name
> is everyone who put their word behind the lyric being right, which is a
> smaller set and a stronger claim:
>
>   * `lyrics_marked_complete_by` -- somebody said it is finished;
>   * `lyrics_marked_staff_approved_by` -- a member of Genius staff agreed;
>   * `verified_lyrics_by` -- the artist themselves, or whoever the role
>     says, confirmed it. A list, and `human_readable_role_for_display`
>     is how Genius words the role.
>
> All three can be set at once and any of them can be absent.
>
> `lyrics_state` == "complete" and `pending_lyrics_edits_count` are NOT
> printed, though they are free -- they ride in the search result. They say
> what STATE the lyric is in, and a state is not a credit: it names nobody,
> it puts nobody's word behind the words, and it reads under the last line
> of a song as though Genius were a person who had signed off on it. The
> line is a list of who vouched, or it is absent.
>
> Deliberately not `_maker`. Marking a lyric complete is a statement about
> the WORDS, and `_maker` is wired to judge_sync, whose two lists are about
> whose TIMING to trust. A Genius lyric is timed here, off the audio, by
> from_genius -- so putting these names in `_maker` would enrol somebody in
> a roster about work they had no part in. See docs/notes/TODO.md.

### `song_of`

**line 380** — from the docstring, `def song_of(token: str, song_id: int, timeout: float = 6.0) -> dict:`

> One song's full record from the API, or {}.
>
> The search hit is a summary: it carries the lyric's state and sometimes
> the counts, and not the people. Everybody credit_of names lives here and
> nowhere else, which is why this is a second request and is asked for once
> per document rather than per line.

### `lyrics_for`

**line 394** — from the docstring, `def lyrics_for(song_id: int, timeout: float = 6.0, markup: bool = False) -> str:`

> Plain text for a song id, via the embed endpoint.
>
> With `markup`, the italic and bold tags survive. They are how Genius says
> who is singing, and the section headers say what each style means -- see
> legend(). Everything else is still stripped.
>
> Why it came back empty is left on `lyrics_for.last_error`. A page that
> could not be reached and a page with no words on it both answer "" here,
> and the caller has to be able to tell them apart -- see why().

### `_styled`

**line 432** — from the docstring, `def _styled(line: str, open_now: list[str] | None = None) -> tuple[str, str]:`

> (the words, which style carries most of them).
>
> "" for unstyled, "i", "b", "bi" or "star". A line is usually wrapped whole,
> but a part of one can be styled on its own; the style that covers the most
> characters is the line's, because that is the voice the line belongs to.
>
> `open_now` is the styling still open where this line begins, and it is
> left holding the styling still open where it ends -- so a caller reading a
> whole lyric threads one list through every line of it. Genius wraps a RUN
> of lines in one tag, opening it on the first and closing it on the last:
>
>     <i>Si je vous gêne, bah c'est la même
>
>     Si je vous gêne, bah c'est la même</i>
>
> Read a line at a time and the second of those comes back unstyled, so the
> two halves of one couplet went to two different singers -- which is
> exactly what somebody watching the screen sees, one line answered and the
> next one not.

### `_who`

**line 523** — from the docstring, `def _who(mapping: dict, style: str) -> str:`

> Who a line in this style belongs to, or "" where the song never said.
>
> A header that names ONE artist names them for the whole of their section,
> whatever the styling does inside it. "[Pont : Maître Gims]" with the
> stanza in italics is emphasis, not a second singer -- and reading that
> italic as somebody the header did not name left four lines to whoever
> happened to sing last, which was the other man.
>
> Where the header names two, an unlisted style is still nobody: telling
> them apart is the whole of what the mapping is for, and guessing between
> them would undo it.

### `voiced_lines`

**line 532** — from the docstring, `def voiced_lines(text: str) -> list[dict]:`

> Lyric lines with who sings each, read from the styling and the headers.
>
> [{"text", "who", "style"}] -- `who` is "" where the song never said.
> Headers are consumed rather than returned: they are the legend, not lyrics.
>
> The styling is threaded through the lines rather than read afresh on each
> one, because Genius spells a run of lines as one tag around all of them;
> see _styled. A section header starts it over, since Genius closes its tags
> before one and a tag left open across a header is a slip in the markup --
> bounded to its own section, it costs a stanza rather than the rest of the
> song.

### `sides`

**line 562** — from the docstring, `def sides(lines: list[dict], main: str = "") -> list[bool]:`

> True where a line belongs to the second voice, by the project's rules.
>
> The most-sung artist takes the first voice and the second-most takes the
> other. Anyone else alternates: each line by somebody else takes the side
> the line before it did not. A line two artists share goes to the first
> voice if the first voice is one of them, and otherwise alternates too.
>
> If that cannot be held -- if an artist would have to appear on both sides
> -- the whole song falls back to alternating on every change of singer,
> which at least stays legible: the contrast is then between consecutive
> voices rather than between named people.

### `_wrapped`

**line 619** — from the docstring, `def _wrapped(line: str) -> bool:`

> Is the whole line one bracketed run -- "(Ooh, ooh)" and nothing else?
>
> The test used to be "starts with ( and ends with )", which is not the same
> question. Jane Remover's "Dancing with your eyes closed" is 21 lines of
> "(Promise I like it like—) Promise I like it like that": they open with an
> ad-lib and go on with the words the singer sings, and every one of them
> was thrown away before it reached the aligner or the editor -- 68 rows in,
> 34 lines out.

### `align`

**line 740** — from the docstring, `def align(ours: list[str], theirs: list[str], min_score: float = 0.55,`

> Map our line indexes onto Genius lines, in order.
>
> A plain nearest-match would happily pair line 3 with line 40 and scramble a
> whole song, so this is a monotonic alignment: matches must advance through
> both sequences. Weak pairings are dropped rather than forced, since leaving a
> line alone beats replacing it with someone else's words.
>
> One of ours may take a RUN of consecutive Genius lines. Genius breaks for
> the page, not for the vocal, so a single sung line is often printed as two:
> 「くわばら くわばら くわばら目にも止まらん速さ」 is "Kuwabara, kuwabara,
> kuwabara" + "Me ni mo tomaran hayasa, hey". Pairing one-to-one kept the
> first half and silently dropped the rest, which is why romanised lines came
> out shorter than the original underneath them -- six of the first thirteen
> lines of Otonoke lost a piece that way.
>
> `asides` are our backing-vocal rows: the words are slid and split between
> the lead lines either side of them as if they were not there.

### `believable`

**line 852** — from the docstring, `def believable(pairs) -> bool:`

> Whether a whole song's mapping reads like the song it is put on.
>
> `pairs` is (our reading, Genius line) for every line the mapping covers.
> One line can disagree for good reasons -- 運命 sung "sadame", a dictionary
> reading Genius spells another way -- so this asks about the MEDIAN line.
> Measured over the 105 songs cached on 2026-10-04: every healthy map sat at
> 0.73 or above, and the broken ones at 0.58 or below -- another song by the
> same artist (5 chance matches at 0.49-0.60), the Japanese version of a
> Korean song, and two maps put on the wrong lines wholesale (0.24, 0.28).

### `_left_over`

**line 862** — from the docstring, `def _left_over(mapping: dict[int, str], ours: list[str], theirs: list[str],`

> Put a Genius line nothing took onto the line of ours that sings it.
>
> Genius printed Ado's 「夢の中に居させて I wanna be free」 as two lines, and
> the one before it took the whole run through "isasete" -- so "I wanna
> be free" was matched to nothing and never shown, though it is sung on
> that very line. Only between lines that were used, only onto a line near
> where it sat, and only where it makes that line read clearly better.

### `rebalance`

**line 884** — from the docstring, `def rebalance(mapping: dict[int, str], ours: list[str],`

> Slide the boundary between two neighbouring lines to where it belongs.
>
> Genius does not break where the vocal does, in either direction, so a run
> taken for one line can end with words that belong to the next -- 「今日も嘘
> をつくの」 came out as "Kyou mo uso wo tsuku no kono kotoba ga", carrying off
> the opening of the line below -- and the mirror leaves 「なんてないわけがない」
> without its "Wake ga nai", which turns up on the following line instead.
>
> Neither is a matching failure as such: the words are present, just on the
> wrong side of one boundary. So for each adjacent pair, try every cut of
> their combined text and keep the one that reads best against both lines.
> A backing row between the two is stepped over (see align).

### `unmerge`

**line 918** — from the docstring, `def unmerge(mapping: dict[int, str], ours: list[str],`

> Undo the opposite mistake: one Genius line covering several of ours.
>
> Genius prints 「今日何食べた？」「好きな本は？」 as one line, "Kyou nani
> tabeta? Suki na hon wa?". The alignment can only give that to one of the
> two, so the first line showed a romanisation with a whole extra question in
> it and the second showed none. Cut it back apart on a word boundary, and
> only where both halves stand on their own -- a bad cut would put half a
> sentence under each line, which is worse than the merge. A lead line is
> also tried cut across the lead lines either side, over backing rows.

### `misses_script`

**line 964** — from the docstring, `def misses_script(text: str, reading: str, theirs: str) -> bool:`

> Whether a Genius line says nothing for the part of ours that needed it.
>
> A line that is half English matches on its English alone. 「キタ、 drift,
> drift, drift」 reads "kita drift, drift, drift", and Genius' "(Drift,
> Drift, Drift)" -- which has no "kita" in it anywhere -- scored 0.88
> against that, so it was drawn as the line's romanisation and キタ lost the
> only reading it had. Take away the words the line already wrote in Latin
> letters, from both sides, and see what Genius has left for the rest: if
> nothing at all, the match was only ever with the English.
>
> Nothing, and not merely something unlike our reading: Genius decodes a
> stylised line into words ours cannot, and '"get 1⚪︎st iπ 31"' as "Get
> lost in me" is a romanisation worth keeping that shares no letters with
> "1stip".

### `_words`

**line 988** — from the docstring, `def _words(text: str) -> list[str]:`

> Where a Genius line may be cut back apart: at spaces, and after hyphens
> and commas (NetEase joins with 、).
>
> God-ish's 「とぅ とぅる」「とぅ とぅ とぅる "風"」 are two sung lines that
> Genius prints as one word, "Tu-turu-tu-tu-turu, "fuu"" -- cutting at spaces
> alone could not separate them, so the first line got nothing and the second
> got both. A piece that ended a word keeps its space as a trailing " ".

### `_carried`

**line 1003** — from the docstring, `def _carried(scores: list[float], min_score: float) -> bool:`

> Whether a cut is good enough overall though one piece reads badly.
>
> A piece Genius wrote in English, not in romaji, looks nothing like our
> reading of the katakana it stands for: 「アイウォンチュー ウォンチュー」 reads
> "aiwonchuu wonchuu" and Genius has "I Want You, Want You", 0.45 apart. When
> the rest of the cut matches all but exactly, the leftover still belongs to
> the one line left for it -- so let one piece through on a much lower bar.

### `page_artist`

**line 1024** — from the docstring, `def page_artist(title: str) -> str:`

> Who a Genius romanisation page says the song is by.
>
> These are filed under a Genius account -- "Genius Romanizations" -- so the
> primary_artist field never names the musician. The title does, in front of
> a dash: "Ado - 踊 (Odo) (Romanized)", "星野源 (Gen Hoshino) - 恋 (Koi)
> (Romanized)". That is the only place the page says whose song it is.
>
> "" where the title does not say, which is not evidence of anything.

### `by_us`

**line 1031** — from the docstring, `def by_us(hit: dict, artist: str) -> bool:`

> Whether a romanisation page is for the artist that was asked about.
>
> Ado's 踊 searched for under its ROMANISED name, "Odo", returns as its first
> result a page titled "しゃりんジョースター (Sharin Joestar) - DIO sings ODO/Ado
> (Romanized)" -- a JoJo parody, filed as a romanisation, and the genuine
> "Ado - 踊 (Odo) (Romanized)" is not in those results at all. Taken on the
> first is_romanisation hit, that parody became the romanisation of the song:
> the screen showed 半端 reading as "Joestar" and ふわふわしたい as "Muda muda".
> Searched under its Japanese name the right page comes back first, which is
> why this only ever went wrong on one half of the same song.
>
> Matched with `_norm`, not `key`: key() keeps only ASCII letters, so it
> reads 星野源 as the empty string and would throw away every page whose
> artist is written in the script the song is in -- which is most of them.

### `linked_romanisation`

**line 1093** — from the docstring, `def linked_romanisation(token: str, song_id, timeout: float = 6.0) -> dict | None:`

> The romanisation Genius itself files against a song, if there is one.
>
> A song's own record lists its translations, romanisation among them, and a
> page reached that way cannot be the wrong song -- Genius is saying these
> two belong together. That is worth more than any comparison of titles.
>
> Costs one request, so it is asked only where searching for the
> romanisation directly has already come up empty.

### `ours`

**line 1105** — from the docstring, `def ours(hit: dict, title: str, artist: str) -> bool:`

> Whether a search hit is the song that was asked for.
>
> The byline does most of the work here, so the title test is looser than
> `_same_song` -- that one will not let a name shorter than four letters be
> contained in a longer one, which is right when the title is all there is
> and wrong here: "Odo" is three letters, Genius files the song as "踊 (Odo)",
> and the artist has already had to match.
>
> `_same_cut` still stands, so a remix or a live cut cannot answer for the
> recording that was asked about.

### `find_romanisation`

**line 1158** — from the docstring, `def find_romanisation(token: str, title: str, artist: str,`

> (lines, chosen hit) for the best romanised match, or None.
>
> Three ways in, in this order; the last, by_lyrics, needs `texts`.
>
> A page that calls itself a romanisation is taken where it is also for the
> right artist -- it used to be taken on the first half alone, and see by_us
> for what that let through.
>
> Where none is, the SONG is looked for instead and its own record asked what
> it has been translated into. That is the case a romanised title creates:
> Ado's 踊 searched as "Odo" does not return its romanisation page at all, so
> there is nothing for the first pass to find, and the song itself is the
> only thing in the results that knows where the romanisation lives.

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

**line 106** — before `if any(is_romanisation(h) for h in hits):`

> Stop only once something claiming to BE a romanisation has turned up.
> Stopping on any hit at all meant the plain "<title> <artist>" query --
> which nearly always returns the original song and nothing else -- ate
> the whole budget, and the Romanized/Genius Romanizations queries that
> actually find these entries never ran. That alone was most of the
> "no romanised version found" results.

**line 115** — before `hits.sort(key=lambda h: not is_romanisation(h))`

> romanisations first, so find_romanisation does not spend a fetch on the
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
