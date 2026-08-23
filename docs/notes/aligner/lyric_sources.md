# `aligner/lyric_sources.py`

Comments lifted out of `aligner/lyric_sources.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

**line 50** — before `REVISION = 9`

> Bumped when the parsers change, so cached conversions from an older build are
> thrown away instead of quietly outliving the bug they were made with.
> 2: NetEase picks among duplicate releases rather than taking the search's
>    first answer, and Musixmatch word timings are read as line timings.
> 3: NetEase whitespace-only tokens no longer become empty syllables.
> 4: NetEase bracketed asides become real backing vocals.
> 5: Musixmatch really is demoted now -- the winner is spelled "Musixmatch" and
>    the test for it was case-sensitive, so every document cached under 2..4 was
>    stored with its word timings intact and has to be fetched again.
> 6: YouLy+ lines pull their first syllable back to the line's own start, the
>    blend provider joins the chain, and the cache records which providers were
>    walked -- an older record cannot say, so it cannot be trusted either.
> 7: NetEase no longer reaches past a good line-level match for a worse-matched
>    word-level one, lines pair on similarity rather than exact text, and the
>    blend takes its lines from the caller's own document when that is the
>    better copy. Every one of those changes what a stored document contains.
> 8: the blend's line ends are fixed twice over -- compared as durations from
>    the agreed start rather than as three raw clocks, and settled on the
>    soonest of them rather than the latest, since every source pads and taking
>    the latest just picked whichever had padded most. Together those took the
>    blend from holding a quarter of its lines open past the last word to
>    holding about as few as the document it is built from. Also: a donor's word
>    timings are now re-cut onto lines the two sides spell slightly differently,
>    which recovers the donor on a tenth of the lines it paired with. Stored
>    blends have the old ends and the old gaps.
> 9: whether two documents are the same song is decided against the shorter of
>    them rather than against the base, so a donor that writes fewer lines than
>    we do is no longer mistaken for a different recording. Documents stored
>    under 8 were built with donors this would have kept.

**line 111** — before `_cache_root = cache_root`

> The old private name, kept because other modules already import it.

**line 127** — before `MISS_TTL = 6 * 3600`

> A miss is cached too, or every track change re-asks three servers that already
> said no. Short enough that a newly submitted song still shows up the same day.

**line 130** — before `HIT_TTL = 30 * 86400`

> A hit does not last forever either. These are living databases -- a track that
> answered line-level a year ago may well have a word-level submission by now --
> and without this a document only ever refreshed when REVISION happened to move.

**line 135** — before `RANK = {"none": 0, "static": 1, "line": 2, "syllable": 3}`

> How good a document is, so a fallback can only ever be an upgrade.

**line 157** — before `# --------------------------------------------------------------------------`

> quality

**line 184** — before `# --------------------------------------------------------------------------`

> http

**line 186** — before `_HOST_CAP = {urllib.parse.urlsplit(YOULY_BASE).netloc: 2}`

> How many requests may be in flight to one host at a time.
>
> Asking the providers together turned out to need this. LyricsPlus rate-limits
> by concurrency, not by rate: two requests at once are fine and the third comes
> back 429 -- and the blend alone asks it for two upstreams, so the moment the
> plain YouLy+ provider ran alongside it one of the three was refused. The
> result was worse than the serial version it replaced, because a refusal is not
> a slow answer, it is no answer.
>
> Capped per host rather than globally, so the providers still overlap each
> other -- which is where the speed came from. Only requests to the same server
> queue behind one another.


## `_get`

**line 222** — before `if e.code != 429 or attempt == 2:`

> Still held off. The gate is kept across the wait on purpose:
> the point is to stop crowding this host, not to back off and
> immediately let a sibling take the slot.


## module level

**line 238** — before `# --------------------------------------------------------------------------`

> TTML -> Spicy Lyrics document


## `_syllables`

**line 304** — before `if tail.strip():`

> Stray punctuation between spans ("'", ",") belongs to the syllable it
> follows -- left loose it would be dropped, and it is never sung alone.

**line 310** — before `part = not (tail and tail != tail.strip())`

> trailing whitespace in the tail is the word boundary

**line 313** — on `            part = True`

> CJK run: no spaces are expected

**line 315** — before `part = (not any(c.isalnum() for c in text)`

> keep an apostrophe with the word it splits: "Couldn" + "'" + "t"


## `_repair`

**line 356** — before `run = [j for j in range(len(syls)) if j not in ok`

> share the hole evenly between however many broken syllables sit in it


## `_unwrap`

**line 388** — on `        return syls`

> "()" on its own is not a lyric


## `_destamp`

**line 424** — before `if len(set(starts)) > 1 or len(starts) < 2:`

> Not "all zero": a file stamped entirely at 12.0 is equally not a sync.
> One line legitimately starting at 0 is fine, so it takes every line
> agreeing to condemn the document.


## `_credits`

**line 455** — before `seen.add(text.lower())`

> the same name is sometimes listed by two <songwriters> blocks


## `parse_ttml`

**line 477** — before `agents = [_attr(p, "agent") for p in paras]`

> Two-voice songs alternate agents; the one that opens the song is the lead
> side and the other gets mirrored to the right, which is what Apple does.

**line 482** — before `spaced = any((sp.tail or "") != (sp.tail or "").strip()`

> Decided for the whole file, not per line: a properly spaced document still
> has lines whose words all happen to be one span, and judging those alone
> would flip the rule mid-song.

**line 501** — before `lead = None`

> line-level: no timed spans, just the words. Roles carry the
> translation and romanisation, which are not part of the line.

**line 537** — before `"HasTransliterations": cjk,`

> No per-syllable TransliteratedText comes back from these sources -- the
> x-roman role is one flat string per line, romanised per mora rather
> than per sung syllable, so it cannot be hung on the timings. Flagging
> the document instead lets the existing deriver produce a romanisation
> that actually follows the voice.

**line 549** — before `doc["SongWriters"] = writers`

> Same field Spicy Lyrics' own documents use, so the info panel reads
> one key whatever answered.


## `_deword`

**line 573** — before `for a in ("StartTime", "EndTime"):`

> A line whose <p> carried no begin/end kept its timing on the group
> alone, so take it back before the group goes -- otherwise demoting the
> word timings would strip the line of any timing at all.

**line 580** — before `bg = [g for g in (new.get("Background") or []) if isinstance(g, dict)]`

> Backing vocals are their own voice with their own line timing, so they
> survive the demotion; only the syllables inside them go.


## module level

**line 604** — before `# --------------------------------------------------------------------------`

> LRC -> Spicy Lyrics document


## `parse_lrc`

**line 620** — before `if len({t for t, _ in rows}) < 2:`

> Same trap as the TTML one: stamps that never advance are not a sync. Keep
> the words -- they are still the lyrics -- and fall through to Static
> below, using them if the record carried no plain text of its own.

**line 630** — on `                continue`

> an empty stamp is an instrumental gap

**line 631** — before `nxt = next((rows[j][0] for j in range(i + 1, len(rows))), None)`

> LRC gives starts only; a line runs until the next one begins,
> bounded so a long instrumental break does not leave one line lit.


## module level

**line 647** — before `# --------------------------------------------------------------------------`

> the providers


## `amll_index`

**line 693** — before `out.setdefault(f"{_norm(name)}\x00{_norm(art)}", f)`

> first submission wins; later ones are usually re-uploads


## `from_amll`

**line 717** — before `for art in re.split(r"\s*[,;/&]\s*|\s+feat\.?\s+|\s+x\s+", artist):`

> the credit line may hold several artists; any one of them matching is
> enough, since the db files a song under each separately


## `from_youly`

**line 789** — before `won = str((rec.get("processingTime") or {}).get("winnerSource") or "")`

> It says which of its own upstreams actually answered -- "apple",
> "musixmatch", "qq", "deezer", "lyricsplus" (its own user submissions).
> Worth keeping: "YouLy+" alone says nothing about how good the data
> is, whereas Apple means word-timed and Musixmatch usually does not.

**line 802** — before `if "musixmatch" in won.lower() and doc.get("Type") == "Syllable":`

> Musixmatch is the one upstream here whose word timings are not measured.
> Where it has them at all they are a line's duration cut up between its
> words, so they drift against the voice while looking exactly as
> authoritative as Apple's -- read them as the line sync they really are.
> Covers "musixmatch-word" too, which is the same data under another name,
> and any capitalisation of either: this is a label from someone else's API
> and matching it exactly is a bet there is no reason to take.


## `from_lrclib`

**line 828** — before `q = _qs(track_name=title, artist_name=artist)`

> /api/get insists on an exact duration match; search is fuzzy, so fall
> back to it and pick the closest-length hit ourselves.

**line 839** — before `hits.sort(key=lambda h: (not h.get("syncedLyrics"),`

> a synced hit beats a longer unsynced one, then closest duration


## module level

**line 856** — before `# --------------------------------------------------------------------------`

> NetEase Cloud Music

**line 860** — before `NE_TRIES = 3`

> How many search hits to open looking for word-level timing. Every one costs a
> request, and past the first few the candidates are no longer the same song.

**line 863** — before `NE_SPREAD = 20.0`

> Beyond this much difference in length, two tracks sharing a title are two
> different songs rather than two pressings of one. Masters vary by a second or
> two; nothing legitimate varies by twenty.

**line 867** — before `NE_CREDIT = re.compile(`

> Credits are stamped like lyrics and would otherwise scroll past as verse one.

**line 871** — before `NE_WROTE = re.compile(r"^\s*(作词|作曲|词|曲)\s*[:：]\s*(.+)$")`

> The two of those that are songwriter credits rather than production ones:
> 作词/词 is the lyricist, 作曲/曲 the composer. Everyone else on that list
> played on the record or released it, which is not the same claim.

**line 875** — before `NE_YRC_LINE = re.compile(r"^\[(\d+),(\d+)\]")`

> [start,dur](start,dur,0)word(start,dur,0)word...


## `_ne_get`

**line 882** — on `    with _gate(url):`

> same courtesy as everyone else's server


## `_ne_rank`

**line 917** — before `theirs = _norm(s.get("name") or "")`

> containment, not equality: NetEase files Japanese singles under both
> scripts at once ("オトノケ - Otonoke"), which never equals either half

**line 926** — before `far = want > 0 and dur > 0 and abs(dur - want) > NE_SPREAD`

> Sharing a title is not being the same song. "BROKEN MIRROR" by BOOM
> BOOM SATELLITES runs 380s against Architects' 190s, and -- being the
> one release here with word timing -- it won outright and put a
> Japanese rock song's lyrics on screen.
>
> Demoted rather than dropped. Dropping it needs the duration we were
> handed to be right, and when it is not the veto falls on the correct
> song instead: given a wrong length for "The Drug In Me Is Reimagined"
> this threw away all four real matches and kept the one track on the
> album that happened to be that long. Demotion costs nothing when the
> duration is right -- the tier below never wins a word-timing contest --
> and still leaves the right answer reachable when it is wrong.

**line 939** — before `mine = {_norm(a.get("name") or "") for a in (s.get("artists") or [])`

> Ranking only, never a veto: credited-artist strings disagree across
> services often enough that requiring a match would cost real hits.
> It earns its place by keeping covers -- which pass both guards above,
> a faithful one being the same song at the same length -- below the
> real thing now that the caller walks past the first candidate.

**line 949** — before `score = (0 if far else 1,`

> a duration match is the stronger signal; prefer one that is both

**line 956** — before `return [(sid, sc[:3]) for sc, sid in scored]`

> Everything but the last component. Those are the categorical ones -- is it
> plausibly this song at all, did the duration match, did the byline -- and
> every pressing of one recording scores the same on all three, which is
> exactly the group the caller may shop around inside for word timing. The
> last is the raw duration delta, which differs by milliseconds between
> pressings and would split that group for no reason.


## `_ne_yrc`

**line 982** — before `if syls:`

> Some releases spend a whole token on the space between two
> words. It has nothing to draw, but it is still what marks the
> token before it as ending a word -- carry that back before
> dropping it, or the two words either side run together.
> Left in, it renders as a timed syllable with no text: 15% of
> the syllables in a bad case, each one a highlight step that
> lands on nothing.

**line 994** — before `"IsPartOfWord": word == text})`

> NetEase puts the space inside the token it follows

**line 999** — before `if not lead:`

> A line that is nothing but a bracketed aside ("（*Laughs*）") has no
> lead left to sing against. Rather than emit a blank line with a
> backing vocal hanging off it, keep it as the line it plainly is.


## `_ne_bg`

**line 1060** — before `lead.extend(cur)`

> A bracket that never closes is not a backing vocal, just a stray mark


## module level

**line 1094** — before `FAKE_EVEN = 0.006          # how close to identical the durations have to be`

> A line whose syllables all run for exactly the same length was never measured:
> nobody sings five words in five equal breaths. It is what a source hands back
> when it holds a line stamp and no word timing and divides one by the other.
> Rogue's "Let's Talk" opens with such a line -- two words, 7.37s each, against
> a real vocal of well under a second -- and on screen that is one word filling
> for seven seconds while the singer has long since moved on.
>
> Only stripped where the division actually shows. A short line split evenly is
> just as invented, but every word in it lands within a breath of where it
> belongs, and dropping the timing there would trade a harmless inaccuracy for
> a visibly untimed line.

**line 1105** — on `FAKE_EVEN = 0.006`

> how close to identical the durations have to be

**line 1106** — on `FAKE_SHOW = 1.2`

> seconds per syllable, past which the crawl is plain


## `_ne_doc`

**line 1152** — before `roma = _ne_lrc_rows(get("romalrc"))`

> romalrc is line-level and keyed to the same clock, so it can be matched by
> start time -- no fuzzy alignment needed, unlike a Genius page.

**line 1168** — before `"HasTransliterations": False,`

> false on purpose: where romalrc exists the lines already carry a real
> romanisation, and where it does not, deriving one is the GUI's own
> decision to make rather than something this source should assert


## `_ne_writers`

**line 1194** — before `for name in re.split(r"\s*[/、,，&]\s*", m.group(2)):`

> one credit line can list several people, and the two lines usually
> name the same person twice over


## `from_netease`

**line 1225** — before `top = ranked[0][1]`

> Only the candidates that are as plausible as the best one may be preferred
> for their word timing. That walk exists because word timing belongs to a
> pressing rather than to a song, so the copy worth having is not always the
> search's favourite -- but it assumed every candidate WAS the song, and a
> lower-scoring candidate is precisely the one that might not be. Reaching
> past a good line-level match to a worse-matched word-level one is how a
> different band's song ends up on screen.

**line 1234** — before `got = _parallel({sid: (lambda s=sid: _ne_get(`

> Opened all at once. Which release carries the word timing cannot be known
> without looking, so this always ended up making two or three round trips
> to the same server one after the other; made together they cost one.

**line 1240** — on `    for sid, score in ranked:`

> still decided in rank order


## module level

**line 1255** — before `# --------------------------------------------------------------------------`

> the blend: QQ's word timings, Apple's (or LRCLIB's) lines, NetEase's opinion

**line 1257** — before `BLEND_NEAR = 0.35     # two clocks this close are reading the same performance`

> Each of the three knows something the others do not. QQ Music times inside a
> line better than anyone here and writes the lyrics worse -- no punctuation, no
> casing, credits stamped as verse one. Apple has the wording, the line splits
> and the casing that should reach the screen, and line stamps that are usually
> right but sometimes sit early. NetEase is a third opinion on where a line
> begins, from a catalogue that is not derived from either of the others -- and
> the least trustworthy of the three, because the release it found may not be
> the recording being played.
>
> So: Apple says what the words are, QQ says when each of them lands, and the
> three clocks vote on where the line as a whole sits.

**line 1268** — on `BLEND_NEAR = 0.35`

> two clocks this close are reading the same performance

**line 1269** — on `BLEND_FAR = 1.5`

> this far from everyone else is a different reading

**line 1270** — on `BLEND_SAME = 0.55`

> matched lines below this share (of the shorter side) = not this song

**line 1271** — on `BLEND_JUMP = 0.75`

> a pair drifting this far from its neighbours is mis-paired

**line 1300** — before `COHERE_MIN = 8`

> A share of matched lines is not the only way to know two documents are about
> one recording, and on a donor that cuts its lines differently it is a poor
> one. What cannot happen by accident is agreement about the CLOCK: a dozen
> lines that match by text and also place themselves within half a second of one
> another are the same performance, whatever fraction of the document they are.
>
> Koven's "Gold" is the case. NetEase writes 34 lines where Apple writes 24, so
> only half of Apple's lines have a single exact counterpart and the share gate
> refused the whole donor -- while the twelve that did match agreed on one
> offset to within 0.18s across the entire song. _shared already knows about
> donors that split lines differently and defends by measuring against the
> shorter side, but that does nothing here, where the base IS the shorter side.
>
> Enough lines to be sure the agreement is not a coincidence...

**line 1315** — before `COHERE_TOL = 0.5`

> ...how close they have to sit to their own median to count as agreeing...

**line 1317** — before `COHERE_SHARE = 0.9`

> ...and how many of them must. Not all: one line of a repeated hook matched to
> the wrong repeat is normal and _timely will deal with it later.


## `_pair`

**line 1357** — before `if not _shared(a, b, pairs):`

> Decided on the exact matches alone: whether these two are the same song is
> exactly the question the loose pass must not be allowed to answer, since
> it would happily pair anything with anything inside a wide enough window.


## `_timely`

**line 1382** — on `        return pairs`

> nothing paired, or the donor was rejected whole

**line 1390** — on `        return pairs`

> too few to have a trend to disagree with


## `from_blend`

**line 1568** — before `got = _parallel({`

> All three at once -- this provider is three lookups deep and serially it
> was three times the wait of any other. LRCLIB stays out of the race: it
> is only wanted when nothing better has lines, and asking it every time
> would spend a request per track to save one on the few that need it.

**line 1578** — before `picks = [(local, _words_from(local), "spicy"),`

> Best wording available, richest first. `local` wins ties: it is the copy
> the app is already showing, so blending onto it keeps the line splits and
> casing on screen the same before and after.

**line 1584** — before `picks.sort(key=lambda p: RANK.get(quality(p[0]), 0), reverse=True)`

> stable, so `local` keeps its place on a tie

**line 1594** — before `rank = lambda d: RANK.get(quality(d), 0) if d else 0        # noqa: E731`

> Never hand back less than what went in. With an unsynced base -- Spicy
> Lyrics has words but no timing for the track -- and donors whose line
> splits will not align to it, there is nothing to reconcile and the result
> is the unsynced base back again. Meanwhile one of those donors was a
> perfectly good line sync on its own. Turning the blend on must not be how
> you lose the sync, so where the reconciliation ends up worse than a source
> it was built from, that source is handed back instead.


## `_blend`

**line 1625** — before `ne_ends = bool(ne) and quality(ne) == "syllable"`

> Whether this donor's line ends are measured or invented. A word-level
> NetEase document ends a line where its last syllable ends; a line-level
> one has no end at all, so _ne_doc fills one in from the next line's start
> or, failing that, ten seconds. Those are placeholders, and letting them
> into the vote had them win it: on a track where NetEase only had line
> timing, 29 of 84 lines were stretched -- one by 8.1 seconds -- to a
> boundary nobody had measured. The same fabrication is in parse_lrc, so
> LRCLIB is read the same way.

**line 1650** — on `            out.append(new)`

> unsynced line, and nobody could time it

**line 1653** — before `for who in ("qq", "ne"):`

> Credit is for changing the answer, not for being asked. A donor whose
> clock agrees with the base moves nothing, and naming it implies a
> reconciliation that never took place -- so each is judged by whether
> the line would have landed elsewhere without it.

**line 1661** — before `if not rest or abs(_agree(rest) - start) > 1e-6:`

> No `rest` at all means this donor is the only reason the line has
> a time -- the base is unsynced. That is the largest contribution
> there is, and testing it by "would the answer change without it"
> scored it as nothing, so a document NetEase had timed end to end
> went out credited to Spicy Lyrics.

**line 1669** — before `qby = (start - q_s) if isinstance(q_s, (int, float)) else 0.0`

> QQ's syllables carry the shape of the line -- which word is held, which
> is clipped -- and that shape is worth keeping even where its clock is
> the one that lost the vote. So it is moved onto the agreed start rather
> than thrown away: the line lands where the vote says, and inside it the
> words fall where QQ heard them.

**line 1678** — on `            used.add("qq")`

> its word timings really are on screen

**line 1680** — before `own = (it.get("Lead") or {}).get("Syllables") or []`

> QQ has nothing to say about this line -- it does not carry the
> track at all, or it words the line differently enough that the
> syllables cannot be re-cut onto ours. Apple's own word timings
> then stand: they are what this document would have had without
> the blend, and dropping them to a single untimed blob would make
> asking for the blend a downgrade on every track QQ has never
> heard of.

**line 1691** — before `lent = _relay(new["Text"],`

> Neither QQ nor the base can word this line, and NetEase can.
> It is already paired and already voted on the start, so its
> syllables move onto that start exactly as QQ's would.
>
> Without this the blend answered line-level for any track QQ
> and Apple have never heard of, was outranked by NetEase alone
> at the bottom of from_blend, and handed the whole document
> back on NetEase's clock -- losing the very line starts it had
> just reconciled. Rogue's "Let's Talk" opened 5.6s early that
> way, against an LRCLIB start the blend had already agreed on.

**line 1707** — before `n_e = (_line_end(n) if n else None) if ne_ends else None`

> NetEase gets a say in the end too, where it measured one at all.
>
> Each end arrives on its own source's clock, and the line has just been
> moved off all of them onto the agreed start -- so each is carried over
> by the same distance its own start sat from that agreement. What is
> then compared is how long each source says the line lasts, which is
> the only part of an end that survives being moved.
>
> Comparing them raw counted the same disagreement twice. A donor whose
> release runs a second behind the base was handing over an end a second
> too late as well as a start a second too late, and the start vote had
> already dealt with the second one.

**line 1731** — before `if syls:`

> Never before the last word we are actually going to draw. The words
> are measured; the line end is a display boundary, and a boundary that
> falls inside its own syllables freezes the fill mid-word. This is also
> what makes taking the soonest end safe: a sustain one source measured
> and another clipped is in the syllables, and comes back here.

**line 1741** — on `        end = max(end, start + 0.05)`

> a line of no duration never lights up

**line 1745** — before `new["Lead"] = {"StartTime": start, "EndTime": end, "Syllables": syls}`

> On the group, not just the item: timeline() reads a word-synced
> line's end off its Lead and never looks at the item, so an end
> left only up there is an end nothing downstream ever sees.

**line 1750** — before `bg = [g for g in (it.get("Background") or []) if isinstance(g, dict)]`

> Backing vocals came with the base's words on the base's clock, so they
> move with the line rather than staying where the base left them.

**line 1767** — before `if not doc.get("SongWriters"):`

> LRCLIB names nobody and QQ rarely does, but NetEase stamps the writers
> into the lyrics themselves -- so where the base came up empty, ask it.

**line 1774** — before `parts = [n for n, key in (("QQ Music", "qq"), ("NetEase", "ne")) if key in used]`

> Name only what actually got a say. A donor that failed to align was not
> merely unhelpful, it was about a different recording, and saying it
> contributed would misreport where these timings came from.

**line 1781** — before `doc["_alone"] = origin`

> Neither donor had anything for this track, or nothing that matched it.
> What comes out is then one source's document with its own timings
> untouched -- so it should say so, and be called what that source is
> called anywhere else. "Blend · Apple Music" for a document nothing was
> blended into claims work that did not happen, and hides which source
> the lyrics on screen actually are.

**line 1789** — on `            doc["_via"] = "apple"`

> what from_youly would have reported


## module level

**line 1796** — before `# --------------------------------------------------------------------------`

> alignments made on this machine
>
> Kept in their own directory, apart from the lookup cache further down, and
> the difference is not filing. Everything in CACHE_DIR is an answer somebody
> else's server gave and can be asked for again, so it carries a TTL and
> forget() throws it away. An alignment is minutes of this machine's own GPU
> spent on a copy of the audio that has since been deleted: losing it is not a
> re-fetch, it is doing the work again. So it has no TTL, and forget() -- which
> exists to make the next ask really ask -- does not touch it.

**line 1807** — before `SOURCE_FILE = _cache_root() / "sources.json"`

> Which copy of a track was aligned against, kept so the next run uses the same
> one.
>
> Two uploads of one song can share a length to the tenth of a second and be
> different recordings -- a live take runs the same three minutes as the studio
> cut and starts singing nine seconds later. The search does not return the same
> candidates twice running, so a song could be aligned against the album on
> Monday and a live performance on Tuesday, and the second alignment would be
> nine seconds out with nothing in this program having changed. Remembering the
> choice is what makes an alignment reproducible at all.

**line 1854** — before `ALIGN_REV = 4`

> Bumped when the aligner changes enough that its old answers are worth
> re-measuring rather than trusting. Same bargain as the Genius revision: these
> are derived, so a track measured once by an older version would otherwise
> keep that version's mistakes forever.
> 2: the words now come from Genius rather than from whichever source happened
> to be best-timed, and every word in a line is given a timing and run on to
> meet the next one. Both change the answer enough that older alignments are
> worth re-measuring rather than keeping.
> 3: two changes, and the second is the reason for the bump. English words are
> divided into syllables by their pronunciation, which an old alignment simply
> does not carry. And the song is no longer walked in one pass where a
> line-synced copy of the same recording exists to anchor between -- which is
> what stops a line being stretched across an instrumental break, and is the
> difference between a line held for twenty-four seconds and one held for two.
> Alignments made before this kept whichever the single pass happened to give.
> 4: the anchoring in 3 had stopped working and nobody could tell. A log line
> referred to two names that a refactor had removed, so every call raised, the
> caller caught it and quietly fell back to the single pass -- for months of
> alignments that say "rev 3" and were made without any of it. Ninety-six of
> them were sitting in the cache, being served in preference to re-measuring.
>
> What else changed with it, any one of which would have earned a bump:
> English words are read by wav2vec2 rather than MMS_FA; a line no longer
> loses its words when the line above it overruns; ad-libs are timed as their
> own voice instead of taking the lead's time, and no longer held for four
> seconds by an envelope that cannot hear which voice it is listening to;
> syllables are divided by dictionary rather than by rules; a line the walk
> could not place falls back to where the speech model heard it, and failing
> that to a share of the gap, so a song no longer has dark lines in it.


## `_rejoin`

**line 1961** — before `stops, at = set(), 0`

> where each word ends, counted in the despaced string

**line 1970** — before `same = {}`

> flat index -> worded index, for the stretches that matched exactly

**line 1980** — before `nxt = flat[i + 1] if i + 1 < len(flat) else "a"`

> Never break onto or away from punctuation: the segmenter counts "K.O."
> as three tokens and splitting there spells it "K . O .", which is
> worse than the per-mora line this is meant to improve on.


## `netease_roman`

**line 2018** — before `for i, c in enumerate(roman):`

> Genius opens a line with a capital and these two get read together --
> a Genius line, then a NetEase line filling a gap in it, then Genius
> again. Left lowercase the borrowed ones announce themselves as coming
> from somewhere else, which is not information anybody wanted.


## module level

**line 2031** — before `# --------------------------------------------------------------------------`

> disk cache


## `_cached`

**line 2047** — on `        return None`

> a stale "nothing here", or a hit old enough to re-ask


## module level

**line 2084** — before `# --------------------------------------------------------------------------`

> the chain


## `fallback`

**line 2151** — before `names = [n for n in names if n in ahead]`

> Only the ones ranked above Spicy Lyrics are still in the running, and
> asking the rest would be three network requests spent on answers that
> cannot be accepted.

**line 2166** — before `if doc and list(rec.get("names") or []) == names:`

> A hit is only reusable if it came out of this same running order:
> move a provider up the list and the old winner may no longer be
> the one that would win now, which is the whole point of the move.

**line 2172** — before `elif not doc and set(names) <= set(rec.get("names") or []) \`

> A miss carries over to any ask that is no harder than the one that
> produced it -- fewer providers, or a higher bar to clear.

**line 2178** — before `docs = _gather(known, names, tid, meta or {}, local)`

> Asked all at once rather than one after another. Serially this was the
> slowest thing the app did: four providers that each take a second or two
> and are each allowed eight, so a track none of them had could sit there
> for half a minute with nothing on screen. They do not depend on each
> other, so the walk costs what the slowest one costs.
>
> The cost is that the short-circuit is gone -- every enabled provider is
> now asked even when the first would have settled it. That is a handful of
> requests once per track per month, against a wait the user actually sits
> through.

**line 2191** — on `    for name in names:`

> priority order, so ties keep the earlier


## module level

**line 2205** — before `# --------------------------------------------------------------------------`

> duet flags

**line 2207** — before `DUET_TTL = 30 * 86400`

> A duet miss is remembered far longer than a lyrics miss: this asks about
> tracks that already HAVE good lyrics, so it would otherwise fire on most of
> the library at every track change, forever.

**line 2266** — before `LIKE_LEN = 0.8`

> How near in length two lines must be before their similarity is even worth
> scoring. A typo keeps a line's length; a line that is a fragment of another
> does not, and containment is what scores misleadingly high.

**line 2321** — before `REGROUP_LIKE = 0.88`

> How alike a run of lines and the single line facing it have to read before
> they are treated as the same words cut in two places. Looser than a
> line-for-line pair is allowed to be, because the run has already had to agree
> about its own length, which is the check that does the real work in
> _near_pairs -- and the window it may look in is bounded by matched lines
> either side, so this is choosing between a couple of candidates rather than
> searching a song.

**line 2329** — before `REGROUP_SPAN = 4`

> The most lines one side may spend saying what the other says in one. Past
> this it is not a split, it is two different readings of the section.

**line 2332** — before `REGROUP_SURE = 0.97`

> Word for word, allowing for the odd letter. A run this close to ours, with
> nothing else in the window anywhere near as close, is not a guess about WHICH
> line it is -- so the only thing left for the clock to say is where that line
> falls, and it is entitled to disagree with its neighbours about that.

**line 2337** — before `REGROUP_FAR = 2.5`

> How far such a run may still sit from where the clock expects it. Wide enough
> for a transcription that stamps the pickup rather than the downbeat -- one
> line on "Gold" is written a second and a half early and is plainly the right
> line -- and far short of the distance to the next repeat of a chorus, which
> is what the ordinary tolerance is there to refuse.


## `_regroup`

**line 2375** — before `clock = sorted(`

> The same clock the rest of the graft is read against. A window bounded by
> matched lines is not on its own enough to place a run: where the matches
> are sparse that window is wide, and a line the song repeats will happily
> find its own words several seconds from where it is being sung. On one
> track here four lines were placed 5.4s early that way, all by the same
> amount, which is a repeat matched to the wrong repeat and nothing else.

**line 2386** — on `    spoken = set()`

> base lines this pass has already placed

**line 2428** — on `                    continue`

> a run is two or more

**line 2432** — before `span = None`

> Prefer a run that agrees with the clock. Failing that, a run that is
> word for word ours and the only one of its kind left in the window is
> still the right line -- there is no other repeat for it to be -- so it
> is allowed to disagree about the timing, within reason.

**line 2442** — before `s = SL.line_start(bit[i])`

> Nothing sits where the clock expects. A run that is word for word
> ours can still be right -- the donor may stamp the pickup rather
> than the downbeat -- but only while there is no question WHICH run
> it is. So take the near-exact ones close enough to be candidates
> at all, and act only if that leaves exactly one. A second repeat
> of a chorus is bars away, not inside this bound, so it does not
> make its neighbour ambiguous; another reading of the same moment
> would, and should.

**line 2497** — before `shares, at = [], 0`

> share them out by how much of the joined text each line carries


## module level

**line 2530** — before `RELAY_LIKE = 0.75`

> How alike two spellings of one line must be before the donor's syllable
> boundaries are trusted as cut points for ours. The line pairing has already
> decided these are the same line; this is the narrower question of whether the
> two write it closely enough to cut along, so it matches _near_pairs' floor.


## `_recut`

**line 2562** — before `at = [0] * (len(theirs) + 1)`

> at[i] is where donor letter i lands in ours; lo[i]..hi[i] the range that
> placing it is really free to choose from, which is empty where the two
> sides spell the letter the same and the aligner matched it outright.

**line 2567** — on `    loose = None`

> the run before here, if it was one

**line 2573** — on `                lo[i1] = loose`

> the run before could go either way

**line 2575** — before `for k in range(i2 - i1):`

> A run the two sides spell differently has no letter-for-letter
> answer, so it is divided in proportion. Crude, and near enough:
> these runs are a word or two long, and a cut inside one only
> decides which of two neighbouring words a letter fills with.

**line 2589** — before `out.append(min(free, key=lambda p: (abs(p - at[b]), -p)) if free else at[b])`

> nearest word boundary it is allowed to reach, the later one on a tie


## `_relay`

**line 2618** — before `spans = [(s, _key(s.get("Text") or "")) for s in syls or []]`

> Punctuation-only syllables ("!", ",") carry no letters to line up on.
> Dropping them costs a highlight step on something nobody sings, and the
> mark itself still arrives as part of the slice around it.

**line 2624** — before `if not spans or not idx or len(ours) != len(idx):`

> Lowercasing changed the letter count -- a Turkish dotted I, a final sigma.
> The cuts are counted in letters, so there is nothing to count them off.

**line 2635** — before `breaks = {0, len(ours)} | {p for p in range(1, len(ours))`

> Where our own words end: a gap in the line between two letters is
> the space, hyphen or comma between them.

**line 2648** — before `stop = idx[at] if at < len(idx) else len(text)`

> up to the next syllable's first letter, so the punctuation and spacing
> between two words stay attached to the word they follow

**line 2653** — before `if out:`

> The donor sings a word our line does not carry. Nothing of ours
> can be drawn for it and a syllable with no text fills as a blank
> step, so its time goes to the syllable beside it -- the one whose
> letters those moments were spent on as far as this line is
> concerned -- and `cut` stays put, leaving whatever punctuation it
> did claim for the slice that follows.

**line 2672** — before `out[-1]["Text"] += text[cut:].rstrip()`

> A tail the last syllable never claimed -- a "?" the donor did not
> write -- belongs to the last word on screen rather than to nowhere.


## `graft_syllables`

**line 2705** — before `if not (_shared(a, b, dict(pairs), floor=0.6)`

> Same reasoning as _transfer: a weak alignment means these are not the same
> rendition, and timings hung on the wrong lines are worse than none. Held
> to a higher share than the blend is, because this moves the whole document
> onto the donor's clock rather than reconciling line by line -- but against
> the shorter side for the same reason _shared explains, or a donor that
> simply writes fewer lines than we do never gets to lend anything.
> Either kind of evidence will do: most of the shorter document matching, or
> fewer matches that agree about the clock. Both are still decided on the
> exact matches alone, which is the point _pair makes -- the loose pass must
> not get to answer whether these two are the same recording.

**line 2719** — before `mate = dict(pairs)`

> Which lines can actually take the donor's syllables, decided before any
> timing is moved -- the ones that can are the anchors the rest hang off.

**line 2723** — before `mate = _timely(mate, bit, dit)`

> Same trap as the blend's: a repeated chorus line matches its own text
> wherever it lands, so a pair that disagrees with its neighbours about the
> clock is matched to the wrong repeat and must not lend its timings.

**line 2727** — before `mate.update(_retime(a, b, bit, dit, mate))`

> ...and give the lines it just rejected somewhere right to go. Without
> this a mis-anchored repeat costs its own line AND everything after the
> last surviving anchor, which is how a song ends up word-timed for its
> first half and interpolated for its second.

**line 2732** — before `take = {}`

> (start, end, syllables) per line, whatever shape it came from -- one
> donor line, a run of them, or a share of one. Normalised here so the
> rewrite below does not care which.

**line 2746** — before `for i, got in _regroup(a, b, bit, dit, mate).items():`

> Last of all, the lines the two sides cut in different places -- they need
> every 1:1 pairing already settled, because those are the walls of the
> window they are allowed to look in.

**line 2754** — before `anchors = sorted(`

> The two clocks do not differ by a constant. Where the documents disagree
> about how the song is cut into lines the gap drifts -- one pairing here
> ran from +0.6s to +9.8s across a single track -- so an unmatched line is
> placed by the matched lines either side of it rather than by an average
> that is wrong at both ends.
> Every line that got words is an anchor, including the regrouped ones --
> they know where they landed as exactly as any 1:1 pair does, and past the
> last of them there is nothing left to interpolate from.

**line 2789** — before `by = there - here`

> Found, but its words could not be re-cut onto ours: the two
> sides do not spell the line with the same letters, which is
> what a censored "****ing" against the word written out comes
> to. The words inside it are lost either way, but where the
> line falls is known exactly -- so use that rather than
> interpolating a position we were told.

**line 2800** — before `if isinstance(new.get("Background"), list):`

> Backing vocals came with the base's words, so they keep the base's
> timing -- but the line around them has just moved to the donor's
> clock, and a backing vocal left behind sings against the wrong line.

**line 2813** — before `doc["_timing"] = "netease"`

> Provenance splits in two here, and the text is the half a reader would
> mean by "where are these lyrics from".


## `_transfer`

**line 2839** — before `if matched < 0.6 * len(ours) or not any(out):`

> A weak alignment means the two are not really the same rendition of the
> song, and guessing which side a line belongs to is worse than not saying.
