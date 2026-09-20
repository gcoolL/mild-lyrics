# `mild-lyrics/lyric_sources.py`

Comments lifted out of `mild-lyrics/lyric_sources.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

**line 76** — before `REVISION = 16`

> 10: the blends are ordered by their donors' ranking now, and there is a
> fifth of them. Every stored answer was chosen under the old order, which
> asked QQ Music first whatever the user had said, so they are not answers to
> the question this asks any more.
> 11: a blend's second donor is asked about the lines the first one placed
> badly, not only about the ones it could not place at all. A stored blend
> still has those lines where the first donor dropped them -- on the songs
> measured here that is a line 23 seconds out of place, and a dozen more
> between one and five. The cost of saying so is one cold walk, 3.7s against
> 0.001s off the disk, on the songs stored under 10 -- 127 of them on the
> machine this was written on, the rest of that directory having already
> aged out under an earlier bump.
> 12: a blend stands down where a source ranked in front of its donors came
> back word-timed, so a stored answer credited to a blend may be one this
> walk would no longer build.
> 13: four things, and every one of them changes the document rather than
> which document wins. A document is no longer called word-synced on the
> strength of one timed line, which on the songs where Apple wraps a single
> lead in a span is the difference between a blend and no blend at all; a
> line's end may follow the base past the start of the line after it, and may
> not go further than that; a voice the document already sings is not lifted
> beside itself; and the second donor has to place a line steadily before it
> speaks for one nobody has placed. Stored answers were built before all of
> it -- and so is every answer credited to Musixmatch, which is asked at its
> own door now and comes back word-timed where it used to come back as lines.
> 14: the running order is followed between two documents timed alike. The
> walk used to hand the song to whichever of them wrote the most letters,
> reading "longer" as "the other one is missing a section" -- and a source
> that stamps every sung stutter is a quarter longer than the same lyric
> written once, so Musixmatch took songs off sources ranked ten places above
> it, 64 of them on the machine this was written on. A stored answer chosen
> that way is one this walk would no longer choose.
> 15: the LyricsPlus door is asked for LyricsPlus' own submissions and for
> nothing else (see LYRICSPLUS_OWN). Every document it handed over under
> another catalogue's name is one no walk will fetch again -- Apple Music's
> scrape, the QQ copy behind QQ's own endpoint, the line-level Musixmatch --
> and so is every blend that took its base from the first of those. A stored
> answer from any of them is an answer to a question this no longer asks.
> 16: Unison is asked twice and chooses on length. A player hands over the
> title as the shop files it, and the decorations are words a search engine
> has to score: asked for `All The Stars (with SZA) - From "Black Panther:
> The Album"`, Unison does not return the row that IS that recording at all,
> and asked for "All The Stars" it returns it fourteenth. So the plain name
> is now asked for as well and the two sets of results are pooled. Then the
> choice between them stopped being made on matchScore, which compares NAMES:
> the row that runs 232s -- the length of the record -- scored 0.906 for
> carrying the soundtrack suffix, the row that runs 236s scored 0.914, and the
> ranking took the further recording for the sake of a shorter title. Every
> stored answer credited to Unison was picked by the old question and the old
> order, and is one this walk would no longer choose.

**line 217** — before `WORDED_SHARE = 0.5`

> How much of a document has to be word-timed before the document is. Measured
> only in the sense that it separates cleanly: of the 277 documents cached on
> the machine this was written on, 218 of the 219 word-synced ones time every
> line and the last times 90% of them, so anything between a tenth and four
> fifths says the same thing about all of them. Half, because it is the share
> that needs no argument.

**line 264** — before `_WALK = threading.local()`

> Whether anybody still wants the answer to the walk this thread is part of.
>
> A walk cannot be interrupted -- it is a dozen blocking socket reads -- but it
> can be asked, and the places worth asking are the ones where it is about to
> spend something: before a request goes out, and again after it has waited
> its turn at a host gate. The player skips, the walk in hand becomes work for
> a screen that has moved on, and the requests it has not made yet are pure
> cost to the walk somebody IS waiting on -- which is queued behind them at
> the same two permits.
>
> Held per thread rather than passed from provider to provider: every one of
> them takes (tid, meta, local) and none of them has any business knowing
> about this. _parallel carries it onto the threads it starts, which is the
> only place the walk fans out, so the whole chain inherits it from the one
> call that set it.

**line 324** — before `MISSED = {404}`

> What went wrong on the walk, and who it went wrong for.
>
> A provider that answers None is saying two different things at once -- "I
> have not got this song" and "I could not be reached" -- and the second one
> is the user's business, because it is the running order not being followed
> for a reason that is nobody's ranking. The three request funnels write down
> what happened instead of an answer, filed under whichever provider the walk
> is asking at the time, and fallback() hands the list to its caller when the
> walk ends.
>
> A miss is not a fault. 404 is how every one of these doors says it has not
> got the song and half of any library is a 404 somewhere, so it is the one
> status that is passed over in silence. Everything else -- a timeout, a
> refused connection, a 5xx, a rate limit that outlasted its one retry -- is
> worth saying out loud once.

**line 377** — before `_HOST_CAP = {urllib.parse.urlsplit(YOULY_BASE).netloc: 2}`

> How many requests a host is asked to hold at once. Four is what an ordinary
> database will not notice. The LyricsPlus door gets two, because at ten
> seconds a request a permit there is a long thing to be holding and the
> look-ahead is warming three tracks behind whatever is playing; two permits
> is two tracks in flight rather than four, and the track on screen waits one
> request rather than three to get in. It has one caller now (see
> LYRICSPLUS_OWN), so two is also two tracks, not two halves of one.

**line 386** — before `_HOST_PATIENCE = {urllib.parse.urlsplit(YOULY_BASE).netloc: 20.0}`

> HOW LONG A HOST IS GIVEN. TIMEOUT suits a database lookup, which is what
> most of these are: a search and a row, answered in well under a second.
>
> The LyricsPlus door is not that, and it is not that for anything asked of
> it. Measured over ten songs on 2026-09-05, /v1/ttml/get took 8.2s to 17.4s
> to answer AT ALL, hits and misses alike, and /v2 took 3.9s to 10.0s on a
> song it had not seen before (0.06s on the second ask, so it caches). Asked
> again on 2026-09-07 with the pin varied and nothing else, it took 8.7s to
> 12.8s to say 404 or 502 -- so the wait is the door itself and not the
> upstream behind it: pinning its own submissions costs exactly what pinning
> Apple Music cost.
>
> Every one of those is over TIMEOUT. So the door timed out on nearly every
> song -- and its "I have not got it" arrived as a timeout too, which is the
> worse half: a 404 is passed over in silence and a timeout is reported, so
> an ordinary miss was announced as a catalogue being unreachable. That is
> the notification that would not stop, and Apple Music was up throughout.
>
> The wait is honest, then, and the way to stop paying it several times over
> is to knock once. Nothing else waits on it: the walk is run in parallel and
> hands over each answer as it lands (see `landed`), so a door that takes ten
> seconds costs the screen nothing -- whatever else answered is already up,
> and LyricsPlus takes over when it arrives if the order asks for it.


## `_get`

**line 434** — before `if not _walking():`

> Asked again on the way in, because the wait for a permit is where a
> dropped walk spends most of what it costs everybody else: the host
> that gates hardest is the slowest one. Handing the permit straight
> back is the whole point.


## module level

**line 510** — before `_OPENS = "\u00ab\u201c\u00bf\u00a1([{"`

> Marks that cannot sit against the text on one side of them, whatever the
> spacing in the file says. See _apart.


## `_syllables`

**line 581** — before `text += tail.rstrip()`

> rstrip, not strip. The trailing whitespace is what says the word
> ends here and is put back by whoever joins these up, so dropping
> it is right -- but the LEADING whitespace is part of the text.
> French writes a narrow no-break space before its ':' and ';' and
> '!' and '?', and stripping both sides turned "crie\u202f: " into
> ":" and spelled "crie:".

**line 596** — before `if part and _apart(text, nxt):`

> ...and whatever the spacing said, some pairs are not one word. See
> _apart, which is about the marks that cannot sit against their
> neighbour in any language that uses them.


## `_repair`

**line 642** — on `            _repair(timed, begin, end)`

> the same dicts, mended in place

**line 670** — on `        up = max(lo, up)`

> the sane neighbours may themselves overlap


## `parse_ttml`

**line 844** — before `ahead = not (p.text or "").strip()`

> Whether an ad-lib is written BEFORE the words it answers -- the
> "(Promise I like it like—) Promise I like it like that" shape. On a
> timed one the times say so and the player works it out for itself
> (spicy_lyrics.BG_LEAD); on one nobody has timed yet, where it sits
> in the <p> is the only thing that says it, so that is read here.

**line 857** — before `g["Text"] = _unbracket("".join(sp.itertext()).strip())`

> An ad-lib written as plain text inside its wrapper,
> which is how one that has not been timed yet comes out.
> The lead's text is joined from everything that is NOT an
> x-bg, so a backing vocal dropped here is dropped from
> the document.

**line 866** — on `                ahead = False`

> a word of the lead, written as a span

**line 867** — before `if (sp.tail or "").strip():`

> ...and the lead's own words where it is written in no span at
> all: those arrive as the tail of whatever came before them.

**line 882** — before `for g in bg:`

> Nothing for an ad-lib to come in ahead of. A line that is one
> bracket and nothing else has a first voice, not an answering
> one, and calling it a lead-in put a space where no lead was.

**line 911** — before `worded = any(isinstance(y.get("StartTime"), (int, float))`

> By the stamps, not by the shape. A file can spell its words out in spans
> and time none of them -- an unsynced lyric somebody has already cut into
> syllables -- and that is a static document carrying its splits, not a
> word-synced one.


## module level

**line 1019** — before `_NOISE = re.compile(r"\s*[(\[](?:feat|ft|with|remaster|remix|explicit|deluxe)[^)\]]*[)\]]",`

> Bracketed text that is in the way of two catalogues agreeing about which
> SONG this is. Which is a different question from which CUT of it is playing
> -- see ALT_CUT, which answers that one, and answers it off the title as it
> was written, before any of this.
>
> "remix" belongs here for the first question even though it is decisive for
> the second, and the two are not in conflict. Kugou files Rogue's remix of
> "Galaxies" as "Galaxies (remix：Rogue)" and Spotify calls it "Galaxies -
> Rogue Remix": stripped, both are "galaxies" and the two catalogues agree
> they are talking about the same song, which is all _norm is for. Taking
> the word out of here to keep the remix apart from the instrumental looked
> like the same fix and was not -- it left those two spellings as
> "galaxiesremixrogue" and "galaxiesrogueremix", so Kugou stopped answering
> for the remix at all, while the instrumental was still being handed the
> remix's words by every other route. ALT_CUT is where that is decided.
>
> The one caller with no ALT_CUT test to fall back on is the amll index,
> which is a dict lookup with no hit to examine. It keys on _song_key.

**line 1157** — before `LYRICSPLUS_OWN = "lyricsplus"`

> ONE CATALOGUE, ONE KNOCK.
>
> This door used to be four of the chain's providers at once. Apple Music was
> reached through it, so was QQ Music where QQ's own endpoint had nothing, so
> was Musixmatch where the app endpoint came back short of word timing, and so
> were the blends when nothing already in hand had Apple word-timed. Each of
> those is one or two requests, on a host that answers in eight to thirteen
> seconds whatever it is asked (see _HOST_PATIENCE) and holds two requests at
> a time (see _HOST_CAP) -- so a single walk could queue eight ten-second asks
> through a two-wide gate and spend the better part of a minute in here while
> every other source in the chain had long since answered. The blends wait on
> the round before them, so they waited on that too, and the blends are what
> usually wins.
>
> It is asked for one thing now: the syncs LyricsPlus' own readers timed and
> uploaded, which is the one catalogue behind it that is nobody else's and the
> only one it is the only door on. Apple Music comes from BiniLyrics, QQ Music
> from QQ, Musixmatch from Musixmatch -- each of them a door of its own that
> answers in a fraction of a second, and each of them the source's real
> catalogue rather than this server's copy of it. What that costs is the songs
> the scrape had and the real door does not: BiniLyrics indexes by ISRC and
> cannot answer for a recording it has not got, and Musixmatch's line-level
> scrape is gone for the tracks its app endpoint cannot match. What it buys is
> one knock instead of eight, which is the difference between a walk that is
> over in a second or two and one the blends reach a minute late.
>
> from_youly still takes a `source` of anything the server knows, because
> eval_blends builds its jar of donors through it and a measurement wants the
> scrape it is measuring against. Nothing in the CHAIN passes anything but
> this.

**line 1190** — before `_YOULY_WON = {"apple": {"apple"}, "qq": {"qq"}, "deezer": {"deezer"},`

> What the server may answer with when an upstream is asked for BY NAME.
>
> It does not always honour the pin, and there is exactly one door it does
> not: there is no "lyricsplus" filter behind it. Asked for LyricsPlus' own
> submissions it answers with them where it has them, with nothing where it
> has neither -- and, on a good third of the songs tried, with its own
> Apple+QQ reconciliation instead ("qaple"), which is not LyricsPlus' words
> at all. Filed under the slot that asked, that credits a community which
> never wrote them, and it wins the walk from a rank the user gave to
> something else: every cached document this program has ever filed under
> lyricsplus is a qaple.
>
> Every other pin is honoured exactly -- apple, qq, musixmatch and deezer all
> come back as themselves -- so refusing an answer that names a different
> upstream costs nothing anywhere else.


## `_youly`

**line 1305** — before `if answer is not None and _honoured(source, answer[1]):`

> A pin the server could not honour is a different catalogue's
> document, not this one's -- see _honoured. The other shape of the
> question is still read; it sometimes reaches the copy the first one
> missed. In the order they were asked in, so that the shape most
> likely to be the right recording is the one taken where both
> answered.


## module level

**line 1348** — before `from_lyricsplus.wants_above = True`

> A SECOND-ROUND PROVIDER, and one _gather may decide not to ask at all. Like
> the blends' and Genius', `above` is not read here: the decision is taken in
> _gather, where it saves the request rather than only the parsing.
>
> It is here because this door is the expensive one. Every other source in the
> walk answers in under two seconds; this one takes eight to seventeen and is
> given twenty (see _HOST_PATIENCE), so on the songs where somebody has
> already come back with word timing it was twenty seconds spent finding out
> nothing -- a permit held on a gate two wide, a pass of the player's fetch
> loop held open behind it, and the look-ahead kept off the next track. Asked
> in the second round it is asked only where it could still win; see
> `_beaten_to_it` for when that is.

**line 1440** — before `NE_CREDIT = re.compile(`

> A credit line, stamped and timed like a lyric by every source that writes
> one. Kugou puts "Lyrics by：Vivian Weeks" and "Composed by：Vivian Weeks" at
> the top of a great many songs, in the Latin script and with the fullwidth
> colon, which the Chinese-only pattern walked straight past -- so they were
> sung at the listener over the intro and written into every TTML saved from
> here. The colon is required: it is what separates a credit from a lyric that
> happens to open with the word "Music".
> The Chinese half is not anchored the way the English half is, because the
> roles are QUALIFIED and the qualifier comes first: NetEase's copy of a
> Coldplay track credits 电吉他 (electric guitar), 低音吉他 (bass guitar),
> 音频工程师 (audio engineer), 助理母带工程师 (assistant mastering engineer) and
> 附加制作 (additional production), and a pattern demanding 吉他 or 母带 at the
> start of the line walks past every one of them. They were sung at the reader
> over the outro. So a few characters are allowed either side of the role --
> ahead of it for the qualifier, behind it for 人 or 师 -- while the colon
> still does the work of separating a credit from a lyric.


## `_ne_rank`

**line 1512** — before `if not _same_cut(s.get("name") or "", title):`

> Before anything is weighed: a hit whose title claims a version we
> did not ask for is not a worse copy of this recording, it is a
> different one. It has to be thrown out rather than scored down,
> because the other two signals carry it anyway -- NetEase's copy of
> "Galaxies (Rogue Remix)" is credited to Protostar and is five
> seconds off the instrumental, which is a byline and a duration, and
> two of the three is all this asks for. See ALT_CUT.

**line 1532** — before `if int(same) + int(near) + int(byline) < 2:`

> Two of the three have to agree: the title, the byline, the length.
> One was enough here and one is not evidence -- a duration inside
> five seconds is a coincidence a four-minute song has with half the
> catalogue, and a title alone is every cover and karaoke cut of it.
> On a song NetEase does not have, and search always answers with
> SOMETHING, that single signal is exactly how the wrong lyric got in.

**line 1540** — before `mismatch = bool(akey) and bool(mine) and not byline and any(`

> A BYLINE THAT DISAGREES is not a signal that is merely missing.
>
> Measured, on Conro's "Thrill of It" played from a browser: NetEase
> has it at 200.4s and the upload runs 206, so the duration is 5.6s
> out and only the title and the byline agree. It also has Robert
> Randolph & The Family Band's song of the same name at 207.4s --
> title and duration, no byline, and a full second NEARER. Ranking
> the nearer duration first drew a stranger's lyrics over the song.
>
> So an agreeing name outranks every coincidence of length: a name is
> a statement about whose recording this is, and two songs that share
> a title share a length about as often as any two songs do.
>
> Only where the two are comparable. A catalogue that writes the
> artist in Chinese and a player that writes it in Latin do not
> disagree -- they are not both answering, and `mismatch` stays false
> so nothing is held against a hit nobody can read.

**line 1559** — before `score = (0 if far else 1,`

> In order of what each one is worth. A length wildly out is a
> different recording; a byline that contradicts is somebody else's
> song; the TITLE is what names the song, and it used only to count
> alongside the duration, which is how "Stars" by the same artist --
> right name, wrong song, four seconds nearer -- came out ahead of
> the song actually asked for. The length comes last, as
> corroboration rather than as evidence.

**line 1574** — before `return [(sid, sc[:5]) for sc, sid in scored]`

> Everything but the gap is what the caller weighs a hit by -- two
> pressings of one recording tie here, which is what lets it open both
> and take whichever carries word timing. The gap is left out for exactly
> that reason: it is the one field they never tie on.


## `_restream`

**line 2080** — before `k = _key(_unaside(SL.line_text(it), apart))`

> Our line as this donor would have written it. Where we put an ad-lib
> inside the line and the donor files it beside one, its letters can
> only be matched against the words of some OTHER line -- and then the
> line they were matched into swallows the syllables of the line after
> it. On "Never Too Late" that is Apple's "It's never too late (It's
> never too late)" reaching forward into NetEase's "It's not", which
> left the next line two words it could not relay and no timing at
> all. _peel_bracket takes those brackets out of the lyric a few lines
> further on and gives them the donor's own timing for the ad-lib, so
> this is reading the line the way it is about to be written anyway.

**line 2119** — before `out.append({"Text": SL.syllables_text(take), "_recut": True,`

> Marked as this function's work, because what stands behind a
> re-cut line is the whole song's alignment rather than one line
> matched against one line, and _relay asks a looser question of it
> for that reason. The mark stays on the donor's side of the blend --
> what reaches the screen is built from the base's item.


## `_in_step`

**line 2178** — before `tails, back = [], [len(out)] * len(out)`

> Longest non-decreasing run through the starts, by patience sorting over
> the positions rather than the values, so what it keeps is the lines that
> were already in order.

**line 2186** — on `        while lo < hi:`

> rightmost slot this start fits


## module level

**line 2221** — before `BLEND_LONG = 1.6`

> How much longer than the room it is going into a BORROWED rhythm may be.
>
> Only borrowed ones are asked. A line the pairing placed normally is on the
> donor's own clock and its end is dealt with further down, by believing the
> base about where the singing stops. A rhythm lifted off a donor line and
> anchored somewhere else has no such guarantee: nothing has checked that it
> is even the right LENGTH for the line it is being put in.
>
> LEDGER's "Foreigner" is what says it has to be checked. Kugou writes "Hold
> out your hand of riches and display your royalty" as a line running 83.58
> to 95.70 -- twelve seconds, because it smears the first word across an
> eight-second instrumental: "H" at 83.58, "o" at 86.51, "ut" at 92.22. The
> line sync says that line is 92.18 to 95.62. Anchored on that and left
> unchecked, its words ran eight seconds into the four lines after it.
>
> The test is the LENGTH and not the overrun, because the base's line spacing
> is approximate and a donor line that is a fraction long is ordinary -- a
> singer really does hold a word into the line after. Over the nine lines
> this repairs on that song, the ratio of the donor's span to the room the
> base leaves runs 0.35, 0.75, 0.77, 0.93, 0.95, 1.11, 1.18, 1.18 ... and
> then 3.52, which is the smeared one. There is nothing between 1.18 and
> 3.52 and the cut sits in the middle of that gap.

**line 2291** — before `BLEND_STEADY = 0.5`

> How steady the second donor's own answer has to be before it is taken. It is
> measured the same way as the first donor's -- against its OWN neighbours, not
> against the first donor's line -- because the two are being asked the same
> question about the same line sync, and a donor that agrees with the lines
> around it is placing this one. Measured at 0.35 as well and 0.5 is the better
> of the two, by about as much as the whole change is worth: over the 46 songs
> with a hand-timed file here, 13.36% of Apple+NetEase+Kugou's words land more
> than half a second out at 0.5 against 13.43% at 0.35.

**line 2300** — before `BLEND_PATCHY = 0.34`

> How much of a line may be riding on onsets nobody measured before the second
> donor is asked about it. See _guessed.

**line 2303** — before `BLEND_BETTER = 0.2`

> ...and by how much the second donor has to beat that. Not a tuned number, a
> guard: two donors tokenise differently and the coarser of them guesses a
> little more on every line in the song, which is not a reason to swap a clock.

**line 2309** — before `BLEND_LEAD = 0.05`

> How much nearer the base's line sync the second donor's whole clock has to
> sit before it takes the song off the first. See in_order, which is where the
> measuring and the evidence are.

**line 2313** — before `BLEND_WOBBLE = 0.05`

> ...and how much less steady it is allowed to be about sitting there.

**line 2317** — before `BLEND_PICK = 0.015`

> How much steadier one blend's donor has to be than another's before that
> outranks the order the user put the sources in.
>
> `_steady` is the donor's drift against the base's LINE SYNC, spread rather
> than offset: how far each line sits from where its own neighbours put this
> donor. A donor that agrees with the line sync line by line is placing the
> song; one that wanders is not, and the wandering is what a listener hears
> as a sync being "off in places" even when the song as a whole lines up.
>
> It predicts which donor is actually better. Over the songs here with a
> hand-timed file, every pair of donors that both answered and could both be
> scored against those timings -- nine pairs, the rest being byte-identical
> documents QQ and Kugou both serve -- the one with the lower `_steady` was
> also the one whose words really sat closer to the hand-placed ones. Nine
> out of nine.
>
> The margin is what keeps a ranking from being second-guessed on noise, and
> it is set on the BLENDS rather than on the donors, because the blends are
> what the choice is actually between. Over seven songs where two blends
> could both be scored against a hand-timed file:
>
>     margin   flips that help   flips that hurt   left to the order
>      0.005          2                 0                  3
>      0.015          2                 0                  4
>      0.020          1                 0                  5
>      0.030          1                 0                  6
>
> Nothing hurts at any setting, so the margin is only deciding how much is
> left to the order. 0.015 is the loosest one that still catches both real
> calls -- Bad Computer's "Chasing" by 0.043 and Athena's "Eternal" by 0.019
> -- while leaving Feint's "Do Better", which differs by 0.006 and is a
> genuine tie, to the ranking.


## `in_order`

**line 2492** — before `if mine[0] is None or abs(mine[0]) <= BLEND_LEAD:`

> Nothing can beat a shift smaller than the margin, so the second donor
> is not measured at all in the case that is nearly every song. _clock
> re-streams to answer, which is the same work _blend is about to do.


## `_blended`

**line 2846** — before `lead, fill = in_order(base, (got["timed"], whose, alone),`

> Which of the two times the song and which one fills its gaps is settled
> against the base, song by song, rather than by the order they are
> written in here. See in_order.


## `stand_down`

**line 2868** — before `out = dict(_reworded(donor, base))`

> The donor's document, but written the way the base writes it
> wherever the base has the line at all.
> A blend that times less of the song than the document it borrowed
> from is not a better document, whatever its words are. Laying one
> source's timings under another's lines costs something every time:
> measured against the hand-timed files in ./lyrics over sixteen
> songs, blending NetEase under Apple's lines covers 96% of lines to
> NetEase's own 100% and scatters 0.056s against its 0.047s. Where
> that cost shows up as whole lines going untimed -- Chasing Clouds
> times 29 of Apple's 40 lines where NetEase times all 31 of its own
> -- the donor's document is simply the better one and is handed over
> instead.


## module level

**line 2885** — before `BLEND_SHORT = 0.85`

> How much more of a song the donor must time, on its own lines, before a
> blend gives up and hands over the donor's whole document -- words and all.
>
> 0.15 was too eager. It stood the blend down on Chasing Clouds, where the
> blend times 29 of Apple's 40 lines against NetEase's 31 of 31: a 0.275 gap,
> and the price of closing it is reading NetEase's transcription of an
> English song instead of Apple's. Listened to side by side there is very
> little in it, and the words on screen are the thing the user chose a source
> for. So the bar is now high enough that Chasing Clouds keeps Apple's words,
> and a stand-down means the blend really did fail -- half the song untimed,
> not a verse of it.
> How much of the donor's lyric the blend's own words must cover before the
> blend is worth having at all. _thinner asks how much of what the base HAS
> got timed; this asks whether the base has the song. They are different
> failures: on Bad Computer's "Your Spell" the blend timed 17 of Apple's 17
> lines and looked perfect by every measure _thinner takes, while Apple's
> copy carried 359 letters against QQ Music's 589 -- the last third of the
> song simply was not in it, and no amount of word timing puts it back.
>
> Letters, not lines, because where a line ends is an editorial choice and
> sources make it differently: Apple writes as one line what QQ splits into
> two all the time, and that is not a shorter lyric.
>
> Measured as ONE stretch of the song, not as a total. Counting every letter
> the two documents disagree about made this fire on documents that are
> missing nothing at all: sources differ about whether a sung stutter is
> written out, and Musixmatch -- whose whole richsync is a stamp per sung
> token -- writes "i i see see see" and "y you" where Apple writes them once.
> On 2hollis' "jeans" that is 1071 letters against Apple's 847, a quarter
> more, none of it a part of the song Apple has not got. The largest single
> run Apple is missing there is 64 letters; the last third of "Your Spell"
> is 230. A verse that is not in a document is absent in one piece.

**line 2918** — before `BLEND_SAME_WORDS = 0.85`

> ...and the other direction has to hold too, or a donor padding its document
> with a title card and a credit block would look like the fuller copy. Nearly
> all of the base's own words must be inside the donor's, which is what says
> the two are the same lyric and one of them is short.


## `_reworded`

**line 2950** — before `from difflib import SequenceMatcher`

> Matched here rather than through _pair, whose job is to decide whether
> two documents are the same recording at all -- it measures the share
> that matched against the SHORTER side and refuses below it. That is the
> right question when a donor might be answering about a cover; it is the
> wrong one here, where the caller has already established these are the
> same lyric and one of them is short. Apple's 17 lines against QQ's 31
> failed that share and left every line written QQ's way.


## `from_blend`

**line 3026** — before `return _blended(tid, meta, local, from_qq, "QQ Music", "qq", above)`

> "qq", because that is whose document this stands down to. The name was
> carried over as "apple" when Lyrics+ was renamed after the catalogue it
> usually answers from, which credited QQ Music's own sync to Apple.


## module level

**line 3126** — before `ASIDE_TRIM = " \t,;:.-—–~(（[【"`

> What may be shaved off the end of the line once the tail is taken away:
> the punctuation that was joining the two, and the bracket that opened the
> one being lifted. Never a quote -- 'like, "Hey"' ends in one that belongs
> to the line.

**line 3208** — before `STRAY_REACH = 0.6`

> How far past a line's own end a donor's stray ad-lib may start and still
> belong to it. Wider than that and it is sitting in a gap the base does not
> describe, which is not something to guess about.

**line 3258** — before `DOUBLE_SLACK = 0.15`

> How far two voices may overlap and still be called one voice written twice.


## `_lift_strays`

**line 3362** — before `host = None`

> The donor's clock, against lines the blend has largely put on that
> same clock -- whoever timed this line timed the stray beside it.

**line 3376** — before `if _kin(key, _key(ln.get("Text") or "")):`

> Loosely: the two sides rarely write a shout the same number of
> times, and "Ooh, break my heart" is the line QQ Music writes as
> "Ooooh break my heart".

**line 3394** — before `if _doubled(out, key, group["StartTime"], group["EndTime"]):`

> Asked of the finished document rather than of the donor. _echoes
> above asks whether the DONOR sings these words over this stretch,
> which is what says a stray is a backing vocal at all; this asks
> whether WE are already singing them, which is what says it has
> nowhere left to go. The two come apart in a three-way, where the
> filler's whole document is read for strays and the first donor has
> already spoken for most of it: on "Never Too Late" the last "It's
> never too late" is QQ's line 58, our line 37, and was drawn as both.


## `_peel_bracket.take`

**line 3509** — before `best = None`

> Whoever wrote it most nearly the way we did. The pool holds both
> donors and a song repeats its shouts, so first past the post is not
> good enough: Apple's "(Woo, woo)" should take QQ's "Woo, woo" over
> its "Woo" when the song has both.

**line 3519** — before `if not (_kin(key, k) or (cry and _a_cry(said))):`

> The same shout spelled differently is still the same shout, and
> at this distance from the line there is nothing else it could
> be: Apple writes "(Ooh)" where QQ times "Woo".


## `_peel_bracket`

**line 3542** — on `    if not _key(left):`

> the line was the ad-lib and nothing else


## `_blend`

**line 3614** — before `base_had = quality(SL.payload(base))`

> Whether these lines had word timing of their own before this. It decides
> nothing here; it is written onto the result, because a document that was
> line-synced until now had nowhere to mark a backing vocal and its
> ad-libs are therefore still sitting in its lyric. See needs_adlibs.

**line 3620** — on `    qorig = len(qit)`

> before the re-stream and the filler append to it

**line 3621** — before `apart = _filed_apart(qq) | _filed_apart(spare)`

> The ad-libs the donors keep out of their own line streams. Every test
> below that asks "can this line be relayed" reads the line through it,
> because _peel_bracket is going to take those brackets out of the lyric
> and hand them a donor's own timing -- so the question the tests answer
> and the line that finally gets drawn are the same line. See _unaside.
>
> Both donors together, because _peel_bracket draws on both: a bracket
> comes out of the lyric if EITHER of them has it filed as a group. The
> re-stream reads a narrower set of its own -- only what the donor whose
> stream it is keeps apart -- since that is a fact about that one stream.

**line 3655** — before `astray_q = {i: j for i, j in qpairs.items() if i not in (qmap or {})}`

> What the pairing found and the timing check then rejected. See `loose`
> below: the two disagree about WHERE the line is, and about nothing else.

**line 3659** — before `recut = _restream(bit, qit)`

> Whatever the line-by-line pairing could not place, taken from the
> donor read as what it is -- one stream of timed syllables, cut where
> we cut ours. It used to be all or nothing, and only when the pairing
> had failed outright (under three lines in five), which left the
> middle case unserved: femtanyl's P3T paired 36 of 55 lines, cleared
> that bar, and the other 19 stayed untimed while the words for them
> sat in the donor.
>
> The holes are filled and the pairings are kept. A line the pairing
> placed was placed on better evidence than the stream can offer, and
> where the pairing placed nothing at all every line is a hole, which
> is the old behaviour arrived at from the other side.

**line 3681** — before `steady = _wander(bit, qit, qmap or {})`

> Taken HERE: after the re-stream, before the filler. Both of those add
> to the map and only one of them is still this donor speaking -- a
> re-streamed line is this donor's own syllables re-cut to our line
> breaks, where a filled one is somebody else's line entirely. See
> _wander.

**line 3688** — before `borrowed: set = set()`

> A second donor, for the lines the first one could not place. Not a third
> opinion -- nothing votes here -- just somebody else asked about the lines
> nobody has answered for yet, and about the handful the first donor
> answered for and got wrong. The old three-way blend put all three sources
> against every line and was the worse for it; this one speaks where the
> others are silent, and where what they said is not about this line.

**line 3695** — before `rhythm: set = set()`

> Lines taken from a donor for their WORDS while the base keeps the say
> over where the line begins. See the drift test below and, for what it
> means at the point of use, `start` in the main loop.

**line 3699** — before `dropped: set = set()`

> Whose timing was handed over that way, so a line the first donor still
> writes does not come back as an ad-lib beside itself. See below.

**line 3702** — before `spare_lines = _items(SL.payload(spare)) if spare else []`

> Parsed whether or not there are holes to fill: the second donor is
> fetched either way, and even where it is needed for nothing else it can
> still be the one holding the timing for an ad-lib (in the three-way the
> lines and the words come from NetEase, and QQ is the one that times the
> shouts).

**line 3730** — before `dropped.add(id(qit[qmap[i]]))`

> The line the first donor timed is still this document's
> line -- only its clock has been handed over -- so it stays
> spoken for. Left unspoken it would come back through
> _lift_strays as an ad-lib in the margin: the same words,
> twice, once beside themselves.

**line 3737** — before `rhythm.add(i)`

> A hole is not a free hit either. The line has no words yet,
> but it does have the line sync's own opinion about where it
> begins, and handing it to a donor that disagrees with its
> OWN neighbours trades a start that was right for one that is
> word-timed and wrong. On "Never Too Late" that is the last
> "It's not too late", which the base places at 3:08.8 and QQ
> Music six tenths of a second later.
>
> The same bar _steadier holds the filler to when it wants a
> line the first donor already timed: the question is the same
> one, and the answer should not turn on whether somebody else
> got there first. No drift at all -- a base with no stamp on
> the line, or none on its neighbours -- is no objection, and
> the filler is taken as it always was.
>
> It used to `continue` here, and that is the trade read the
> wrong way round. The objection is to the donor's PLACEMENT,
> and the placement is not the only thing on offer: the words,
> their order and the rhythm between them are all still this
> line's, and the base -- being line-synced, which is the
> whole reason a blend is being built -- has none of them. So
> the line is taken for its rhythm and anchored on the base's
> own stamp. Nothing is traded: the start stays the one that
> was right, and the line stops being the only one on screen
> that lights all at once. On LEDGER's "Foreigner" that is ten
> of the twelve lines the blend left unworded, every one of
> them a repeat of a chorus line that the donor places about a
> second off where the line sync does.

**line 3775** — before `spoken = {id(qit[k]) for k in (qmap or {}).values()`

> Which donor lines this document speaks for. By identity, because the
> re-stream and the filler both append to qit and the second donor's
> lines end up living in it too.

**line 3780** — on `    slid: dict[int, float] = {}`

> how far each line moved the donor

**line 3781** — on `    over: dict[int, float] = {}`

> ...and how far the BASE overlaps

**line 3782** — before `pool = []`

> Every donor line AND every ad-lib hanging off one, because a source
> that marks its backing vocals properly -- NetEase does, on LOST -- has
> the timing for a bracket our base only wrote into the lyric.

**line 3814** — before `lent = ((q or {}).get("Lead") or {}).get("Syllables") or []`

> ...unless the donor is about to lend this line its words, in which
> case the donor's own clock IS the line's clock.
>
> _agree weighs opinions about where a line begins, and on a
> line-level base the base's opinion is not about that at all: Apple
> stamps when a line should APPEAR, which is a beat before anybody
> sings it, while the donor stamped when the word is sung. Believing
> the earlier of the two and then sliding the donor's whole line back
> onto it moved measured timings off the voice -- on Contra every one
> of the eight worst lines was early, 0.36s median and 1.54s at worst.
>
> Worse, each line was pulled by a DIFFERENT amount, which is a
> distortion and not an offset: lines that were spaced correctly in
> the donor's clock ended up shuffled against each other until they
> overlapped. NetEase's own document of Contra has no line running
> into the next one anywhere; the blend built from it had four.
>
> So where the donor's syllables are going to be laid down, they are
> laid down where the donor put them. The base's stamp still decides
> a line the donor cannot time, and _agree still weighs the rest.

**line 3836** — before `if isinstance(b_s, (int, float)):`

> Borrowed for its rhythm alone -- the base says where this one
> begins. `qby` below then slides the donor's syllables onto it.

**line 3849** — before `asides = _peel_bracket(new, pool, start, _line_end(it), spoken)`

> An ad-lib written inside our line that the donor times as a line of
> its own. Apple writes 'Chillin\' in the back like, "Hey" (Oh, God)'
> and QQ times 'Chillin\' in the back like "Hey"' then 'Oh God'
> separately, so relaying one onto the other leaves everything after
> the last timed word -- '"Hey" (Oh, God)' -- stuck to a single
> syllable, filling in one lump. Peeled off, the lead takes the words
> it has and the bracket takes the timing the donor already had for it.

**line 3884** — before `loose = qit[astray_q[i]]`

> A PAIRING _timely THREW OUT. It threw it out for being out of
> step with its neighbours, which is how a repeated line gets
> matched to the wrong repeat -- and rightly, because a chorus
> landing a bar early is worse than a chorus landing whole.
>
> But the line then got nothing at all, and that is throwing
> away the half of the answer that was never in doubt. What
> _timely rejects is a PLACEMENT: it compares where the donor
> puts the line against where the base puts it. The WORDS are
> the same words in the same order with the same rhythm
> between them, and the base has no rhythm to offer -- it is
> line-synced, that is why a blend is being built at all.
>
> So the donor's syllables are relayed and then anchored on
> the BASE's stamp rather than the donor's. The line is word
> timed, and it begins where the source _timely believed put
> it. LEDGER's "Foreigner" is twelve lines of one 56-line
> document, every one of them a repeat of a chorus line.

**line 3932** — before `own = ends.get("base")`

> Where the base says the singing stops, believe it. QQ's and Kugou's
> words tile their line -- every word runs until the next one starts,
> and the last one runs to wherever the line was cut -- so a line whose
> voice stops early is held lit through the gap after it. Apple times
> the end of the singing instead. On NF's "If You Want Love", "Ask me,
> how I'm doing" ends at 24.32 by Apple and at 24.87 by Kugou, which is
> exactly where the next line begins.
>
> Only where the base's own end stands clear of the next line: an end
> that IS the next line's start is a tile too, and swapping one for the
> other gains nothing.
>
> Nothing is done about the ends INSIDE a line, because there is
> nothing to do it with. Every source tiles them: NetEase 99% of word
> pairs across this cache, QQ 98%, and on the songs both have, QQ ends
> LATER than NetEase four times as often as it ends earlier -- it has
> no mid-line ends to lend, only longer ones. A hand-timed lyric is
> 74% tiled itself, so a quarter of the pairs really do want an end
> nobody is carrying. Capping a word's fill at a multiple of its
> line's own pace was measured against 4005 words of hand timing here
> and made it worse at every setting tried: |median| end error 0.091s
> as it stands, 0.093s at four times the pace, 0.102s at one and a
> half. The ends we have are not biased, only scattered, and a blunt
> rule shortens the right words as often as the wrong ones.

**line 3961** — before `and (not syls or own >= max(sung, syls[-1]["StartTime"] + 0.05))):`

> Never into the words. Only the last one's tail is stretched
> by the tiling; if the base wants to end before the word
> before it has finished, the two do not agree about this line
> and the base's end is not describing it.

**line 3972** — before `end = own`

> ...and where the base's line runs INTO the line after it,
> believe that too. A voice still sounding under the next line is
> a thing only the base can say: NetEase never writes two lines
> overlapping, and QQ and Kugou tile theirs, so the end they hand
> over is the next line's start whatever was actually sung. Nor is
> it the padding _last_end guards against -- padding fills a gap,
> and an end past the next line's start has no gap to fill.
>
> On "Never Too Late", "It's never too late" is held to 1:55.85
> under "The world we knew", which begins at 1:55.18. Taking the
> soonest end anybody measured cut it at NetEase's 1:55.23 and the
> sustain stopped filling while it was still being sung.

**line 3990** — before `over[len(out)] = (max(0.0, b_e - b_nxt)`

> How far the BASE runs into the line after it, which is how far this
> line is allowed to. See the cap below the loop.

**line 4011** — before `for i in range(len(out) - 1):`

> A line may run into the one after it only as far as the base says it
> does. The branch above puts the base's overlap back where it had one,
> and this is the same fact read the other way: a donor that overruns is
> not describing a held note, it wrote several of our lines as one. On Dua
> Lipa's "New Rules" NetEase files three repeats of "I got new rules, I
> count 'em" as a single eighteen-second line, and relaying that span left
> the hook lit over the top of its own next two repeats.

**line 4024** — before `if at <= mine or done <= room:`

> Not where the base's own stamps run backwards -- Pixel Terror's
> "Enigma" has lines out of order in the Apple document -- since there
> the line after is no evidence about where this one stops.

**line 4041** — before `for lines in (qit[:qorig], spare_lines):`

> Both donors, because either can be the one holding the ad-libs.
> The three-way asks NetEase first and keeps QQ for the gaps, and QQ
> is the one that files a shout as a line of its own.

**line 4050** — before `worded = sum(1 for i in out`

> By the same share quality() reads, so the document does not claim word
> timing on the strength of the one line a donor could place.

**line 4066** — before `if steady is not None and ("qq" in used or "spare" in used):`

> How steadily the donor that actually timed this document tracks the
> base's line sync. Recorded rather than acted on here -- the pick that
> reads it is fallback()'s, which is the only place that can see the
> other blends this one is being weighed against. See BLEND_PICK.


## module level

**line 4238** — before `UNISON_CREDIT = f"Lyrics from Unison ({UNISON_BASE})"`

> How Unison is to be named wherever its words are on screen: it asks
> for its address alongside its name, and that is the whole of what it
> asks for. Only the footer under the lyrics prints this -- see
> lyrics_gui.credit_rows. The menus, the header and the toasts go on
> saying "Unison", where a URL is noise rather than credit.

**line 4249** — before `KRC_SLACK = 2.0`

> How far a lyric candidate's duration may sit from the recording it is
> offered for. Much tighter than NEAR, which is there to let two CATALOGUES
> disagree about one track's length; these two numbers come from Kugou, about
> a recording Kugou has already identified by hash, and they agree to within
> about 40ms when the candidate really is filed against it. NEAR's six
> seconds are wide enough to accept the remix's lyric for the instrumental --
> 240.0 offered against 245.0 -- which is what it did.

**line 4280** — before `def _who(text: str) -> list[str]:`

> Kugou writes a credit list with an ideographic comma, everyone else with a
> slash or an ampersand. NAMES_APART already knows all of them; it is defined
> further down for _no_credit_head, and the pattern is the same question.

**line 4331** — before `ALT_CUT = re.compile(`

> Words in a title that name a DIFFERENT RECORDING rather than describing this
> one at more length.
>
> _same_song is generous about a longer title on purpose -- "Stronger (Radio
> Edit)" is the recording we asked for, written out -- and these are the
> words that make the extra text mean the opposite. A remix is a different
> performance with different words, and frequently with words where the song
> it was made from has none: Protostar's "Galaxies" is an instrumental, Rogue
> remixed it with a vocal, and QQ Music, Kugou, NetEase and Genius all file
> that vocal under a title the instrumental's title is a prefix of. Every one
> of them handed it over for the instrumental.
>
> A VETO rather than a demotion, and this is the part that was missing. Each
> of those sources already ranked its hits, and each already preferred the
> exact title -- and each then walked PAST it to the next candidate, because
> the exact title had no lyrics filed against it. Which is the correct answer
> for an instrumental and was being read as "nothing here, try the next one".
>
> One-directional, so asking for the remix still finds it: a marker is only
> held against a hit when WE did not ask for it. The direction is load-
> bearing elsewhere too -- _qq_head reads _same_song this way round, matching
> a lyric's own title card, which carries the plain name, against the longer
> name the catalogue files the track under.
>
> The vocabulary is local_align.ALT_VERSION's, which asks the same question
> about an AUDIO search hit, plus the four this library's corner of dance
> music actually uses. Kept as two lists rather than one import because they
> are two different decisions: there a marker ranks a hit last, since the
> right recording may not be on SoundCloud at all and a live take of the same
> length is better than silence, and here it drops the hit outright, since
> the wrong words on the screen are worse than no words.

**line 4459** — before `FEAT_BRACKET = re.compile(r"\s*[(\[](?:with|feat|ft|featuring|from)\b[^)\]]*[)\]]",`

> WHAT TO PUT IN A SEARCH BOX, as opposed to what to match against.
>
> A player hands over the title as the shop files it, decorations and all:
> Spotify calls Kendrick Lamar and SZA's single `All The Stars (with SZA) -
> From "Black Panther: The Album"`. Sent to a search engine whole, those extra
> words are eleven more things to score against, and they push the record
> down or off the end of the results -- measured here, the row that IS that
> recording is returned fourteenth for the plain name and not at all for the
> decorated one.
>
> So the plain name is asked for as well. It is only ever a QUERY: everything
> that comes back still goes through _same_song, _same_cut, _near and
> _same_artist before it can be believed, so a broader question can surface
> more candidates and cannot accept a worse one. That is what makes it safe
> to be blunt here -- and why a marker that names a different recording is
> left alone anyway, since dropping "(Live)" would spend the second search
> looking for the wrong thing.


## `_plain_title`

**line 4491** — before `if _cut_words(was) - _cut_words(got):`

> A marker that names a different recording stays: the second search is
> for the same song under a shorter name, not for another cut of it.


## `from_unison`

**line 4518** — before `rule = getattr(_WALK, "people", None) or Roster()`

> No duration in the question, and no album either. Unison matches both
> exactly rather than nearly, and its records often carry neither at all,
> so sending one 404s a song it has: "uncomfy" answers on song and artist
> and does not answer for the same pair with its own length attached, and
> JMSN's "Love Me" -- filed with no album whatsoever -- stops answering
> the moment any album is sent. The album is the worse of the two,
> because ours is nearly never theirs: a submitter types the single a
> song was released as ("La même") where the player is playing the record
> it ended up on ("Ceinture noire"), and both are correct. Asking on song
> and artist is what the endpoint is actually for; the checks below, on
> whatever comes back, are what keep the answer honest.

**line 4542** — before `rows = []`

> Asked for as it was written, and again under the plain name where those
> are two different questions. The results are pooled rather than taken in
> turn: which of the two queries happens to surface the right row is the
> search engine's business, and the ranking below is this program's.

**line 4565** — before `lead, any_of = _same_artist(str(row.get("artist") or ""), artist)`

> The credit, as well as the name. Unison's records often carry no
> duration at all, and _near passes anything when one side is
> missing, so on a title as ordinary as "My Mind" the duration check
> was doing nothing and the name check was matching everybody's song
> of that name. Somebody else's careful sync is still somebody
> else's song.

**line 4575** — before `who = _people_of(row)`

> WHOSE SYNC, before anything else about it.
>
> This is the one place in the chain where the roster has to be
> consulted on the way IN. Everywhere else a source has one document
> for a song and the roster is asked about the answer; here a
> community database has several, and the provider picks one of them
> -- so a refused submitter's sync does not get refused, it gets
> RETURNED, and hides the perfectly good one behind it. The same
> arithmetic the other way is what makes "prefer" mean anything at
> all: measured on "All The Stars", Unison carries a sync by Seme
> scoring 0.914 and one by gcc scoring 0.906, and a user who has
> named gcc has said which of those two they want.

**line 4590** — before `try:`

> HOW NEAR THE LENGTH IS, above anything Unison says about the name.
>
> matchScore is the provider's similarity between two NAMES, and a
> name carries decorations that say nothing about which recording it
> is. Measured on "All The Stars", which Unison carries twice: the row
> called 'All The Stars (From "Black Panther: The Album")' runs 232s,
> which is the length of the record, and scores 0.906; the row called
> 'All the Stars' runs 236s and scores 0.914. Both clear _near, so the
> tie went to the score -- and the ranking took the further recording
> for the sake of a shorter title.
>
> The duration is the one field here that says WHICH recording a row
> describes, so it is evidence and matchScore is corroboration, in
> that order. It is the same thing _ne_rank was taught about NetEase,
> arriving at the other end: there a name that AGREES had to outrank a
> coincidence of length, and here a length that agrees has to outrank
> a coincidence of spelling.
>
> Only where there is something to compare. Unison's records often
> carry no duration at all, and a row that states nothing is neither
> corroborated nor contradicted -- it must not be read as a row that
> is infinitely far away, or every song filed without a length would
> fall behind every song filed with one.
> Coerced the way _near coerces it, and not with _secs: Unison sends
> the duration as a number and _secs only reads the TTML clock
> spellings, so asking it here would call every record lengthless and
> leave the ranking exactly as it was.


## module level

**line 4637** — before `APPLE_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "`

> APPLE MUSIC'S OWN SEARCH, for the one field BiniLyrics is filed by.
>
> BiniLyrics indexes by ISRC -- its documents literally live at
> <ISRC>.ttml -- and from_bini has always known how to ask that way. Nothing
> ever had an ISRC to give it. The player's metadata comes off MPRIS or out
> of the Spotify page, and neither carries one, so every ask fell through to
> the name query: title, artist, album, duration, matched by string.
>
> A name query answers for a recording that shares a name. An ISRC names the
> recording. Between "Clocks" and "Clocks (Live)", between the 2002 master
> and the 2016 remaster, between a single edit and the album cut, the words
> are usually the same and the timings are not -- and a lyric on the wrong
> master is a lyric that drifts.
>
> Apple's catalogue is where the ISRC comes from, which is fitting: it is the
> same catalogue BiniLyrics holds the lyrics for, so an ISRC Apple gives for
> a recording is the key BiniLyrics filed that recording's TTML under. Asked
> with `extend=isrc`, which is not returned by default and is the whole
> reason the iTunes Search API cannot be used for this -- it has no ISRC in
> it at all.

**line 4660** — before `APPLE_TOKEN_FILE = _cache_root() / "apple-token.json"`

> Beside the caches rather than inside the sources cache, because it is not
> a source's answer and because the editor asks Apple for its songwriter
> credits through this same door: one token, one file, one lock, whichever
> of them warms it. See editor/sources.py.


## `_amp`

**line 4762** — before `if e.code not in (401, 403) and e.code not in MISSED:`

> 401 and 403 are the token having turned over, which the caller
> answers by fetching a new one -- not something to report as Apple
> Music being unreachable.


## module level

**line 4773** — before `APPLE_NAMES = re.compile(r"\s*(?:,|&| and )\s*")`

> Apple writes a credit as one string -- "Chris Martin, Guy Berryman, Jonny
> Buckland & Will Champion" -- and TTML wants one <songwriter> each, so it is
> cut back apart here. The same three separators the editor has always used;
> it reads them from this so the two cannot come to disagree about a name.


## `_apple_song`

**line 4862** — before `loose.append(((0 if lead else 1, abs(secs - want)), at, rank))`

> The song, at another length: an album cut against a single, or
> an upload with a few seconds of silence welded on the front.
> Not the recording, so it is no use for an ISRC -- but it is the
> same song, so its cover is the right cover. See _apple_card.


## `_apple_card`

**line 4932** — before `"explicit": True if rating == "explicit" else False if rating else None,`

> None where Apple did not say, which is what every other source
> here means by it.


## module level

**line 4944** — before `SC_API = "https://api-v2.soundcloud.com"`

> SoundCloud, for the covers Apple Music does not have
>
> Not a lyric source: SoundCloud has no lyrics and never has. It is here
> because a great many songs -- the remix, the flip, the bedroom release, the
> thing a label put on YouTube and nowhere else -- are on SoundCloud and are
> not in Apple's catalogue, and a track picked up off a browser needs
> SOMEBODY to say what it looks like.
>
> What is taken from it: the cover, the album where the uploader filled one
> in, and the explicit flag. What is NOT taken from it: the name. SoundCloud
> is a place people upload their own files -- the artist is whatever the
> account is called ("ALLURE" for Allure, all capitals) and the title is
> whatever was typed into the box, decorations and all, which is the thing
> this program is trying to get away from. Apple's catalogue is edited; a
> SoundCloud page is not.

**line 4961** — before `SC_ID_LIFE = 24 * 3600.0`

> The web player hands its own key out in its JavaScript, which is where
> every SoundCloud client gets one. Kept for a day: it turns over on their
> side now and then, and a stale one answers 401, which is what force= is
> for.


## `_soundcloud_card`

**line 5079** — before `"art": _sc_art(row.get("artwork_url") or ""),`

> The track's own cover and nothing else. An upload without one is
> drawn on the site with the uploader's avatar, which is a photograph
> of somebody rather than a cover, and the player's own thumbnail
> beats that.


## `from_bini`

**line 5165** — before `if not isrc and not (title and (artist or want > 0)):`

> WHAT IS ENOUGH TO ASK WITH, and it is not the same for the two doors.
>
> This used to be `title and artist` -- the NAME query's precondition,
> applied to the whole function. by_name already tests exactly that for
> itself, so all the top guard ever did was shut the ISRC door as well,
> for a caller that had no artist to give. And the ISRC door does not
> need one: apple_isrcs finds the recording by title and duration, which
> is a stricter test than a name query is.
>
> Whose callers have no artist: Firefox's. Its own MPRIS publishes the
> WINDOW title and no xesam:artist at all -- see BRIDGE_PLAYERS in
> lyrics_gui -- and song_from_video only recovers one where the upload is
> named "Artist - Title". A window title like "The Taste | YouTube Music"
> has no dash in it and the artist stays empty. Measured over seven songs
> asked both ways: six of seven answered with an artist and NONE of seven
> without, while apple_isrcs had found the codes every time. The door
> that would have worked was never opened.
>
> Checked for the thing that matters before it was widened -- whether the
> answer is the same RECORDING. Nine songs, the full query against the
> ISRC door with the artist blanked: eight came back the same document
> word for word (the ninth had no answer to compare), S.L.I.D.E. among
> them, which is _same_artist's own hard case.
>
> THE DURATION IS WHAT MAKES IT SAFE, and it is not optional here. With a
> length, five songs of five named the right record. With neither an
> artist nor a length, the title is the only test left and it is not
> enough: "Time" comes back as Pink Floyd's 425.9s, not NF's 240.4s. So a
> bare title is still refused, exactly as it was.


## module level

**line 5251** — before `KRC_KEY = bytes((64, 71, 97, 119, 94, 50, 116, 71,`

> KRC is Kugou's own lyric format and the only word-timed one it serves. It
> arrives base64'd, with a four-byte "krc1" header, XOR'd against a fixed
> sixteen-byte key and then deflated -- an obfuscation rather than a secret,
> published the same way in every client that reads it.


## `_krc_items`

**line 5301** — before `said = NE_WROTE.match(body) if body else None`

> Dropped from the lyrics, kept as what it says. Kugou stamps the
> credits like verses -- "Lyrics by：Vivian Weeks" timed across the
> intro -- and they are the only place it names a writer.


## module level

**line 5338** — before `NO_WORDS = re.compile(`

> 请欣赏 -- "please enjoy" -- is the tail of the whole family of Kugou's
> placeholder cards, and it is the part worth matching. Listing the fronts one
> at a time got 纯音乐 ("pure music, please enjoy") and missed DJ音乐, which is
> the same card for a DJ edit and went on screen as the lyric. Safe to match
> on its own: _instrumental only ever looks at a document of three lines or
> fewer, and a song whose entire lyric is "please enjoy" has no words either.


## `_kugou`

**line 5461** — before `if not (_near(float(cand.get("duration") or 0) / 1000.0,`

> The recording is already settled -- it is `hashed` -- and this
> endpoint is only being asked which lyric documents are filed
> against it. It does not answer that question. `keyword` is in
> the query and it weighs, so the candidates come back sorted by
> a title match rather than by what the hash is: asked for
> Protostar's "Galaxies" at 245s, the one candidate offered is
> Tchaikovsky's "The Seasons Op. 37b: June - Barcarole" at 320s,
> and asked for the hash next to it, the second candidate is
> "Galaxies (RogueRemix)".
>
> So each is checked against the recording it claims to be for.
> Its own DURATION does that and does it whatever script the two
> catalogues write in -- a lyric filed against this hash carries
> this hash's length, to the millisecond -- where a title test
> would be asking Kugou's spelling to agree with Spotify's. The
> title is read for one thing only: whether it names a different
> cut. See ALT_CUT.


## module level

**line 5500** — before `QQ_SEARCH = "https://c.y.qq.com/soso/fcgi-bin/client_search_cp"`

> QRC is QQ Music's word-timed format, and unlike Kugou's KRC it is properly
> encrypted rather than merely obfuscated: triple DES over a fixed key, then
> a deflate. The catch is that the DES is a BROKEN one. QQ's build reads and
> writes each four-byte half back to front, carries two typos in its S-boxes
> (sbox2[23] and sbox4[53]), and takes the second half of every subkey off by
> one -- so a stock 3DES answers noise whichever way the three keys are
> ordered, which is the first thing anyone tries. It has to be reproduced bug
> for bug. What follows is a port of wangqr/QQMusicDES, itself B-Con's
> textbook implementation bent back into the shape QQ's client expects.
>
> Worth the code rather than leaving QQ to Lyrics+, which is the door this
> source used to go through. Over the 26 songs in this library the Lyrics+
> door answered word-level 17 times and QQ's own answered 24, and where both
> answered the timings were identical to the millisecond -- Lyrics+ is
> relaying this very document. The six it adds are songs it had all along and
> could not be asked for.

**line 5519** — before `QRC_KEYS = (b"!@#)(NHL", b"123ZXC!@", b"!@#)(*$%")`

> Decrypt, encrypt, decrypt, in that order. Published in every client that
> reads a QRC; the same three keys appear in Lyricify's decrypter spelled as
> one 24-byte string, which is the same thing said differently.

**line 5573** — before `QRC_IP = (57, 49, 41, 33, 25, 17, 9, 1, 59, 51, 43, 35, 27, 19, 11, 3,`

> The three permutations DES is built out of, written as tables rather than as
> the unrolled bit expressions the C uses. QRC_IP is the initial permutation's
> left half; the right half is every one of those bits less one.

**line 5592** — before `QRC_ORDER = (3, 2, 1, 0, 7, 6, 5, 4)`

> Byte i of a block, as QQ's build addresses it: the two four-byte halves are
> each read back to front. This one macro is most of what makes the cipher
> incompatible with everybody else's DES.


## `_qrc_tables`

**line 4671** — before `def _qrc_tables():`

> Every permutation in this cipher is fixed, so none of them has to be walked
> a bit at a time while a song is waiting. Each is worked out once here
> against every byte that can be fed to it, and the round loop becomes a
> handful of lookups.
>
> That is worth doing because of WHERE the cost fell. A QRC payload is
> decrypted three times over and there are two of them per track, the lyric
> and its romanisation, so the bit loops were 1.6 seconds of pure Python on
> every cold track -- on a walk thread, holding the GIL rather than waiting
> on a socket, while the window was trying to draw the words of the song that
> had just started. Measured over 12000 bytes: 273ms a pass down to 33ms, and
> a track's whole envelope from 1.64s to 0.20s.
>
> Built FROM the tables above rather than written out beside them, which is
> the only reason this is safe to have done at all. QQ's two typo'd S-box
> entries and the byte reordering in QRC_ORDER survive by construction --
> change a constant and these change with it -- and tests/test_qrc.py keeps
> the bit-by-bit original beside the new one and asks them both the same
> questions.

**line 4683** — before `row = (six & 0x20) | ((six & 0x1F) >> 1) | ((six & 1) << 4)`

> The row is spelled by the outer two bits of the six and the column by
> the inner four; the tables are written the other way round.

**line 4698** — before `lcol, rcol = ipl[QRC_ORDER[b // 8]], ipr[QRC_ORDER[b // 8]]`

> QRC_ORDER is where _qrc_bit actually read the byte from, so it has to be
> what indexes the table too. The right half takes the bit one to the left of
> the left half's, which is never across a byte boundary: no entry of QRC_IP
> is a multiple of eight.


## `_qrc_des`

**line 4776** — before `rounds = [int.from_bytes(bytes(r), "big")`

> _qrc_schedule still hands its subkeys back as six-byte strings, which is
> what they are. They are turned into ints once per call here rather than
> once per round, which is sixteen times a block.

**line 4791** — before `left, right = right, (`

> The round function is written out rather than called. It is the same
> expression as _qrc_f, and the point of keeping _qrc_f is that
> tests/test_qrc.py holds the two of them together -- but a payload is
> thousands of blocks at sixteen rounds each, and at that count the call
> itself is a fifth of the work.


## module level

**line 5709** — before `QRC_CDATA = re.compile(r"<(contentroma|content)\b[^>]*>\s*<!\[CDATA\[(.*?)\]\]>", re.S)`

> The download hands back an XML document inside an HTML comment, with each
> payload in a CDATA block: `content` is the lyric, `contentroma` the
> romanisation, and `contentts` a translation this module has no use for. The
> word boundary matters -- without it `content` swallows `contentts` too.

**line 5714** — before `QRC_BODY = re.compile(r'LyricContent="(.*)"\s*/>', re.S)`

> Greedy, and deliberately so: QQ does not escape the quotes inside this
> attribute, so The Weeknd's "After Hours" carries a dozen raw ones and a
> lazy match stops at the first. Nothing is unescaped on the way out either,
> because nothing is escaped on the way in -- not even an apostrophe.

**line 5721** — before `QRC_TAIL = re.compile(r"^~+\s*end\s*~+$", re.I)`

> QQ closes a good many of its documents with a sentinel line, timed like a
> lyric and sung by nobody.

**line 5724** — before `QQ_CREDIT = re.compile(`

> QQ files a fuller credit block than NetEase or Kugou do, and it qualifies
> the roles: KiiiKiii's carries "Original Lyrics by：", "Vocal Directed by：",
> "Background Vocals by：" and "Programming by：". NE_CREDIT wants its keyword
> at the START of the line and walks past every one of them. What gives them
> away is the shape instead -- a short role, and then the colon that separates
> it from the names. Two shapes, because QQ writes the block both ways: a role
> ending in "by", and a bare field name.


## `_qrc_items`

**line 5779** — before `said = NE_WROTE.match(body) if body else None`

> Dropped as a lyric, kept as what it says: QQ stamps "作词 : X"
> over the intro the way NetEase and Kugou do, and it is the only
> place either of them names a writer.


## module level

**line 5853** — before `QQ_SAYS = re.compile(r"^\s*(.+?)\s*[:：]\s*$")`

> A line that is a name and a colon and nothing else -- QQ marks who takes
> each verse of a collaboration that way, and times the mark like a lyric.


## `_qq_head`

**line 5900** — before `names = _who(said.group(1)) if said else []`

> Read as a credit line rather than as one name, because QQ writes the
> handover both ways: "Maître Gims：" where one of them takes the
> verse and "Dua Lipa/DaBaby：" where they take it together. Every
> name in it has to be somebody the song credits -- one known name
> beside an unknown one is not a label, it is a lyric with a slash.


## `_qq_doc`

**line 5918** — before `roma, _ = _qrc_items(parts.get("contentroma") or "")`

> The romanisation is word-timed QRC of its own, on the same line clock as
> the lyric, so the lines pair up by where they start. Only its text is
> kept: the view romanises a line, not a syllable.


## module level

**line 5956** — before `MXM_BASE = "https://apic-appmobile.musixmatch.com/ws/1.1/"`

> Musixmatch answers three ways for one song -- the plain words, a line-level
> subtitle, and `richsync`, which times every word -- and one request can ask
> for all three. What this module got instead was whatever Lyrics+ scraped,
> which is the subtitle and never anything better: asked for `musixmatch` by
> name it comes back Line-typed with not a syllable on it, on every track
> tried. So Musixmatch has been in the running order contributing nothing that
> LRCLIB could not.
>
> The shape of the request is neither documented nor guessable. It is the one
> Spicetify's lyrics-plus makes (CustomApps/lyrics-plus/ProviderMusixmatch.js),
> down to the headers, which the iOS endpoint reads.

**line 5969** — before `MXM_HEAD = {`

> Not decoration. The endpoint answers the iOS app and checks that it is being
> spoken to like one; the desktop host with the desktop app_id is a different
> door with a much shorter temper.

**line 5980** — before `MXM_COLD = 1800.0`

> How long to leave token.get alone once it has refused. It answers 401 with
> `hint: captcha` after a handful of asks from one machine, and asking again
> inside the cool-off only holds it open.

**line 5984** — before `MXM_WROTE = re.compile(r"writer\(s\)\s*:\s*(.+)", re.I)`

> Musixmatch files the songwriters in the copyright line rather than in a field
> of their own: "Writer(s): Joseph Hahn, Chester Charles Bennington, ...", with
> a "Copyright:" line of publishers under it. One line, so the publishers are
> not read as five more writers.

**line 5989** — before `MXM_STOP = 0.005`

> How close a word's measured end has to be to its own start before that end
> is read as no measurement at all; see _mxm_spans. Taken off the
> distribution rather than picked: over 2247 words from eight tracks, 27 land
> within 2ms of their own start and 8 more within 10ms, and then there is a
> trough before the real spread of word lengths begins and climbs to its peak
> around a quarter of a second. The cut sits in that trough.

**line 5996** — before `MXM_GAP = 0.4`

> A gap shorter than this is not a rest, it is the end of the word that has
> not been written down; see _mxm_spans. Musixmatch's own median gap is 33 to
> 71ms across the tracks measured here, so the great majority close.
>
> Measured at 0.2 first and that was too tight. NEFFEX's "Are You Ok?" is the
> track that says so: 69 gaps survived it INSIDE a line, and they run 0.200,
> 0.201, 0.202 ... 0.352 in one unbroken stretch, which is not a song pausing
> 69 times in the middle of its own phrases -- it is the same missing word end
> as the shorter ones, a little larger. Past 0.4 what is left is a rest that
> was really taken: the same song's remaining mid-line gap is 0.84s, and Creep
> and "Never Too Late" hold 1.2 and 1.49 inside a line. So the cut goes where
> the continuum ends rather than where it started.


## `_mxm_token`

**line 6060** — before `return "" if force else held`

> Refused lately. A forced ask is one whose token has just been
> retired, so there is nothing to fall back on there either.

**line 6065** — before `try:`

> A failed ask writes down only the refusal, which drops the dead token
> with it: keeping it would spend a request per track discovering again
> that it is dead.


## `_mxm_spans`

**line 6203** — before `flat = [y for it in out for y in (it["Lead"]["Syllables"] or [])]`

> Across the lines as well as inside them: "the word thereafter" is the
> next line's first where a line has run out, and two lines a tenth of a
> second apart are one phrase however they were cut.


## `_mxm_rich`

**line 6241** — before `cut = sum(1 for i in out if len(i["Lead"]["Syllables"]) > 1)`

> ...unless it is line timing wearing a syllable's clothes. Musixmatch
> richsync for a Japanese lyric is frequently one token per line -- on
> Kenshi Yonezu's "Peace Sign", 43 of the 60 lines are the whole line at a
> single stamp -- and a document like that is shaped exactly like a real
> word sync while carrying none of the information. Left alone it beats a
> line-synced document from a source ranked above it, and the reader gets
> the same timing with a worse lyric. _deword is the honest reading, and
> it is the same trade _youly already makes on a Musixmatch scrape.


## module level

**line 6274** — before `_MXM_EXPLICIT: dict = {}`

> Whether Musixmatch called the matched track explicit, filed under the same
> key as its document. Not carried on the document itself because the document
> is often None -- an instrumental, a restricted track, a song nobody has
> synced -- and the rating is worth having in every one of those cases. Swept
> against _ONCE so it cannot outlive the answer it was read from.


## `_musixmatch`

**line 6348** — before `token = _mxm_token(force=True)`

> The stored token has been retired. Worth exactly one more ask, and
> not worth one at all if the cool-off says the answer will be no.

**line 6355** — before `track = _mxm_body(calls, "matcher.track.get").get("track") or {}`

> Kept whether or not there is a document to go with it. See
> mxm_explicit, which is the only reader.


## `_mxm_doc`

**line 6380** — before `lrc = "" if sub.get("restricted") else str(sub.get("subtitle_body") or "")`

> The subtitle is asked for as LRC so that it arrives as the thing
> parse_lrc already reads, and the plain words behind it are what that
> falls back on for a song nobody has synced at all. It wins a tie
> against a richsync that had to be deworded: both are then line
> stamps, and these are the ones Musixmatch measured for display.

**line 6393** — before `lang = (rich.get("richssync_language") or rich.get("richsync_language")`

> "richssync_language" is Musixmatch's own typo and is the field that
> exists; the spelling it ought to have is read too, in case they fix it.


## module level

**line 6429** — before `GENIUS_CONFIG = "gui.json"`

> Genius: the words themselves, and no clock at all

**line 6492** — before `from_genius.wants_above = True`

> A second-round provider, and one _gather may decide not to ask at all.
> `above` is not read here: like the blends', the decision is taken in
> _gather, where it saves the request rather than only the parsing.


## `_genius`

**line 6523** — before `return {k: v for k, v in doc.items() if k != "_timing"}`

> `_timing` names whose CLOCK a document runs on, and this one has no
> clock. local_align stamps it because it is about to make one; handed
> to the chain as it stands it would have the line under the lyrics
> claim a timing that is not there.


## module level

**line 6530** — before `SRC_PARTS = {"spicy": ["spicy"], "apple": ["bini"], "amll": ["amll"],`

> Which providers answer for a source. Mostly one each. Spicy Lyrics is not
> in this table because it is not fetched by the chain at all: it is read out
> of the Spotify page (see Fetcher).
>
> Apple Music used to have two, BiniLyrics and the LyricsPlus door asked for
> Apple by name, and they were two doors on one catalogue at wildly different
> prices: BiniLyrics indexes by ISRC, cannot answer for the wrong recording,
> and answers in about a tenth of a second; the other fetched from Apple and
> converted the TTML on the way and took eight to seventeen (see
> _HOST_PATIENCE). The cheap one is the only one now -- see LYRICSPLUS_OWN --
> so Apple Music is a recording matched by ISRC or it is nothing, which is
> also the stricter of the two answers.

**line 6547** — before `BLENDS = {"blend": ("apple", "qq"), "kublend": ("apple", "kugou"),`

> A blend is one source's WORDS under another's word timing, so it belongs to
> the source whose words you read -- Apple Music -- and it is only asked for
> when every source it draws on is switched on. Ranking Apple Music above QQ
> Music and leaving both on is what asks for "Apple's lines, QQ's timing";
> switching QQ off is what says you would rather not have it at all.
> The tuple is (whose words, whose clock, who fills the gaps) -- the same
> order _blended takes its arguments in, and blend_rank reads it that way.

**line 6559** — before `BLEND_KEY = {"blend": "blend_qq", "kublend": "blend_kugou",`

> The settings key, argparse dest and attribute for each blend's switch, named
> for the donors rather than for the internal name: blend_ne_qq says what it
> is, where blend_triblend says only what it is called.

**line 6565** — before `PROVIDER_SRC = {p: n for n, parts in SRC_PARTS.items() for p in parts}`

> Every provider back to the source it answers for, for the line under the
> lyrics and for anything else that holds a provider name and owes the user
> the name of a catalogue.

**line 6570** — before `WAS_SRC = {"youly": "apple", "bini": "apple", "blend": "apple",`

> What the old menu called things, for reading a settings file written by it.

**line 6575** — before `SOURCES = ["spicy", "apple", "amll", "unison", "lyricsplus", "netease",`

> The order they are consulted in unless the user says otherwise.
>
> NetEase and Kugou ahead of QQ Music, because this order decides which blend
> is asked first and fallback() keeps the first of two equally good answers --
> so whoever leads here usually wins. Measured against the hand-timed files in
> ./lyrics, Apple+QQ leaves 10.7% of a song's words more than half a second
> out of step with the rest of it, against 5.8% for Apple+NetEase+Kugou, and
> it cuts a third of its lines short where the three-way cuts a quarter.
> Shipping QQ first was handing every fresh install the worst of the five.
> LyricsPlus' submissions sit with the other databases people hand-time and
> upload, which is what they are, rather than on a measurement of the kind
> above: asked by name for 40 of the songs in ./lyrics it answered for none
> of them, so there is nothing yet to rank it by. That is a reason to place
> it by kind, not to place it last -- rank only settles ties here, the whole
> enabled chain is asked in parallel either way.
>
> LRCLIB above Musixmatch, which is the one pair here ordered against the
> better clock rather than with it. Musixmatch is word-timed where LRCLIB is
> line-timed and never anything else, and on those songs it wins anyway:
> quality outranks order in both directions, so nothing about this ranking
> can hand a line-level document a song that somebody has word-timed. What it
> decides is the songs where Musixmatch came back line-level TOO -- its
> subtitle rather than its richsync -- and there the two are answering the
> same question with the same kind of answer, and LRCLIB is the open database
> with no token, no cool-off and no rate limit behind it.
>
> Genius last, and it is the one entry here placed by what it CANNOT do.
> Its documents are untimed, so it is barred by quality from taking a song
> off anything above it however anybody ranks the list, and the only songs
> it can speak for are the ones every other source was silent on. That is
> the definition of the slot at the end -- and it is the slot carried()
> hands a source nobody has ever ranked, so the placement needs no
> migration to go on being right.


## `provider_order`

**line 6684** — before `home = min(donors, key=order.index) if donors else BLEND_OF`

> The highest-ranked donor. Not the timing donor, which is what
> blend_rank reads: that decides which blend is asked first, a
> question between blends, where this one is about the sources
> around them. A three-way whose filler the user put above its
> clock still borrows from both, and sits above both.


## module level

**line 6753** — before `def people(v) -> list[str]:`

> WHO TIMED IT, rather than which database it is sitting in.
>
> Four of these sources are people: Spicy Lyrics' community entries, amll,
> LyricsPlus' curators and Unison are all somebody sitting down with a song
> and timing it by hand. The running order cannot say anything about that --
> it ranks the databases, and a database is not a person. So a user who
> knows one contributor's syncs drift and another's are better than the
> licensed copy has no way to say either, short of switching a whole source
> off and losing everybody else on it with them.
>
> That is what the two lists here are for, and they are deliberately the
> smallest thing that answers it: names to refuse, and names to take. See
> Roster.

**line 6912** — before `PROVIDERS = [("amll", from_amll), ("blend", from_blend),`

> Named for the source each one answers from, not for the door it knocks on:
> Apple Music and Musixmatch and QQ Music all come through Lyrics+, and the
> running order the user writes is a list of sources, so the chain has to be
> able to ask for one of them without the other two.

**line 6925** — before `from_amll.credits_people = True`

> The providers worth ASKING to find out whether somebody named on the prefer
> list has this song. A name can only be found by fetching the document that
> carries it, so a walk that already holds word timing has to go and look --
> and this is what keeps going and looking from meaning all ten doors on
> every song. See _walk.
>
> Which is not quite the same list as "can say who timed it". Apple,
> Musixmatch, LRCLIB and the three Chinese catalogues have nowhere to put the
> fact and never carry it, so they are out for the obvious reason. Two are
> out for reasons of their own:
>
>   * SPICY LYRICS carries it and is the biggest source of it here -- but it
>     is not in this table because it is not in PROVIDERS at all. It is read
>     out of the Spotify page rather than fetched by the chain, so there is
>     nothing to ask: the player already has its document in hand and asks
>     the roster about it directly. See Fetcher._load.
>   * LYRICSPLUS carries a curator and is deliberately left out. Its door is
>     given twenty seconds (see _HOST_PATIENCE) and times out on nearly every
>     song, and a timeout is reported where a miss is passed over in silence
>     -- so hunting it would put a wait and a "could not reach LyricsPlus" on
>     every word-timed track, for a credit that is a submitter's name on a
>     handful of songs. It is still honoured wherever the chain is walking
>     anyway: what this list decides is only whether a door is worth opening
>     on a song that was otherwise settled.


## `stored`

**line 7143** — before `return {**doc, "_source": str(rec.get("source") or "")} if rec.get("source") else doc`

> Carry the name of whoever answered, so the line under the lyrics is
> right from the first frame rather than guessing Spicy Lyrics and
> correcting itself a moment later.


## `_once`

**line 7247** — before `if rec["value"] is None and not _walking():`

> A walk that was given up on answers None for a reason that has
> nothing to do with the upstream. Left in the memo that reads as
> "this track has nothing", for ONCE_TTL, to every walk that comes
> after it -- including the one the user is actually waiting on,
> which is usually the very next thing to ask.

**line 7257** — before `return fn() if _walking() else None`

> Either the first caller is taking longer than any honest ask can, or
> this walk has been dropped. Only the first is worth asking again for:
> the wait itself was the thing worth having.


## `_parallel`

**line 7298** — before `alive = getattr(_WALK, "alive", None)`

> The one place the walk fans out, and so the one place its cancel token
> has to be handed on: a thread starts with a bare threading.local and
> would otherwise ask nobody's permission for anything. The same goes for
> where a failure is written down, and for whose failure it is -- inherited
> rather than set from the job's key, because a provider fans out again
> inside itself (NetEase asks about several song ids at once) and those
> requests are still that provider's.


## module level

**line 7325** — before `ROUND_HOLD = 2.0`

> How long the round after the first will wait for it before getting on with
> what it can already answer. See _Fan and _gather.
>
> Two seconds, because that is where the chain divides. Measured over this
> library, every door but one answers inside it -- BiniLyrics and LRCLIB in a
> tenth of a second, NetEase and Kugou in about two, QQ in three or four --
> and the LyricsPlus door takes eight to thirteen whatever it is asked (see
> _HOST_PATIENCE). Waiting for the slowest of them to decide when the rest of
> the chain may start is the whole of what this is for.


## `_outdone`

**line 7452** — before `front = [got.get(n) for n in names[:at]]`

> The other blends are in this stretch too and are not in `got` -- they
> are being decided in this same round -- so they answer None and abstain,
> which is right: no blend stands another one down.


## `_gather`

**line 7611** — before `early = fan.so_far(ROUND_HOLD) if _walking() else {}`

> Opened only once the first round has said something, so this is the one
> point in a walk where giving up saves the whole rest of it rather than
> only what has not gone out yet.


## `_walk`

**line 7683** — before `local = None`

> What the caller already holds is a document like any other, and a
> refused one is no more usable as a blend's base here than it was on
> screen. `have` is the caller's to put right -- it is a quality, not
> a document, and a walk cannot tell "line-timed" refused from
> line-timed -- which is why the player drops the body itself.

**line 7691** — before `hunt = (bool(rule.pick) and not rule.likes(local)`

> WHO ELSE IS WORTH ASKING with word timing already in hand. `ahead` is
> the standing answer -- a source ranked above whatever the caller holds
> wins a tie -- and a name on the prefer list is the other one: their
> sync wins that tie from wherever it is sitting, which is the whole
> point of naming them, and the only way to find out whether they have
> this song is to ask. Narrowed to the sources where a name can be found
> for what asking them costs, so preferring somebody does not turn every
> song with word timing into a ten-door walk. See credits_people.

**line 7740** — before `rec = None`

> Not this question. The record holds the answer a walk arrived at
> under whichever roster was in force when it ran -- both what it
> settled on and, for a stored miss, what it found nobody worth
> having. Refusing somebody would otherwise leave their document
> on screen until the entry aged out, and taking them off the list
> again would not bring it back. See Roster.key.

**line 7753** — before `_told(report, doc, was)`

> Handed over the same way a fresh answer is. This is the
> look-ahead's whole payoff -- the track was warmed, the
> answer is on the disk, and the caller can draw it now --
> and it used to be the one path that did not report: the
> walk returned before _gather, so nothing landed, and a
> warmed song reached the screen no sooner than a cold one.

**line 7762** — before `return None`

> The best the same walk could find, and it does not beat
> what we already hold. Asking again cannot change that:
> anything it passed over was ranked no higher than a bar
> this one has already cleared. Without this the whole
> chain went back to the network on every play of a song
> whose lyrics were cached and simply not an improvement.


## `_walk.landed`

**line 7809** — before `if was and (rank, liked, -at) <= (was[1], was[2], -was[0]):`

> The same three rules the final pick below uses, in the same
> priority -- better timing, then somebody asked for by name,
> then the running order -- so what goes up early is never
> something the final answer would then have to take back.


## `_walk`

**line 7833** — before `liked = [row for row in tied if rule.likes(row[0])]`

> Somebody asked for by name takes the tie off everybody else in it,
> whatever source they are sitting on -- which is the whole of what
> naming them does. The tie is what the running order would have settled
> and the only place an order can still be overruled without overruling
> the timing: `tied` is already down to the documents of equal quality,
> so nothing here can put a worse-timed one on screen.

**line 7842** — before `return None`

> Dropped part way. Nothing is stored: a walk that stopped asking did
> not find out that nobody has the song, and _store would file that
> silence under the whole provider list -- which _cached reads back as
> a settled "no" for the next six hours, on a track that was only ever
> skipped past.


## `duet_flags`

**line 8058** — before `return _tie_backing(lines, list(got)) if got else None`

> Tied again on the way out: a file written before ad-libs were
> held to their own line still has one on the wrong side of the
> screen in it, and nothing else would ever correct it.


## module level

**line 8102** — before `LIKE_LEN = 0.65`

> How much shorter one line may be than the other and still be it. Loose,
> because length is a bad test for the thing it was standing in for: see
> _fragment, which asks the question length was being asked to answer.

**line 8106** — before `FRAGMENT = 0.95`

> A line is a FRAGMENT of another when nearly all of it appears inside the
> other in one piece. That is the chorus case the length guard was really
> aimed at, and it is what makes "Caught in the middle" different from "Two
> faced, caught in the middle" -- every letter of the shorter is in the
> longer, in order, unbroken.


## `_near_pairs`

**line 8179** — before `if len(key) != len(b[j]) and _fragment(key, b[j]):`

> ...and not a piece cut out of a longer line, which is the case
> the length guard above used to be doing on its own, badly.


## module level

**line 8364** — before `RELAY_LIKE = 0.75`

> How alike our line and the syllables offered for it have to be before the
> donor's cut points are trusted on it. The question it answers is not "did
> they hear the same words" -- they often did not -- but "are these syllables
> THIS line's at all", because a pairing can hand over a line that is not
> ours and then the cuts land anywhere. See _recut.

**line 8370** — before `#     ------   (none at all, at 0.75)`

> ...and the same question asked of a line the RE-STREAM handed over, which
> is a different question with a much better answer behind it already.
>
> A pairing is one line matched against one line and nothing else; the floor
> above is all that stands behind it. A re-streamed line is not matched at
> all -- _restream aligns the whole song's letters at once, holds its own
> floor over that alignment, and hands each of our lines the span of the
> donor's stream that fell inside it, in order, without overlap. Every line
> around it is evidence about where it begins and ends, and _in_step then
> checks the placement again. Asking a 37-letter line to prove itself over
> again on its own, with all of that thrown away, is a weaker test overruling
> a stronger one.
>
> What it costs when it does: Slushii's "LUV U NEED U" through Kugou, where
> Apple sings "And watch these moments fall back into place" and Kugou heard
> "And though she's moving slow back into place". Eight words against eight,
> "And" on the front and "back into place" on the back, and the middle a
> straight mishearing -- 0.712 on the letters, and the line came out as the
> only bare one in a verse the donor had timed word for word.
>
> Not zero, though, because a re-stream can still hand a line words that are
> not its words: the same song gives Apple's "Oh, oh, oh-oh, oh" the four
> letters of Kugou's "Okay", which is the one place in that document where
> the stream really has nothing to say. That is 0.29.
>
> So the number is off the curve rather than off the example. Every donor
> fetched for the 109 hand-timed documents in ./lyrics, blended under the
> same document stripped to its line stamps, scored against its own words --
> and read over the 90 song/donor pairs where the blend is already sound
> (nine words in ten inside half a second), because a donor holding a
> different recording is wrong everywhere and swamps both sides of the
> question. What each floor ADDS, with the song's own constant taken out:
>
>     floor    lines added    median    p90     over 1s

**line 8405** — before `RECUT_LIKE = 0.65`

>     0.70          53         0.180    0.550     5.3%
>     0.65          66         0.184    0.583     5.9%
>     0.60          79         0.196    0.884     9.7%
>     0.55          82         0.198    1.236    11.4%
>     0.50          93         0.209    1.236    11.2%
>
> (What it already draws there, for scale: median 0.058, p90 0.238, 1.8%.)
>
> 0.70 and 0.65 add the same kind of line and 0.65 adds thirteen more of
> them. Below that the p90 doubles and then doubles again, which is the
> stream running out of anything to say and the letters agreeing by accident
> instead -- a line more than a second out is worse on screen than a line
> that never filled. So the floor goes at the knee, not at 0.712.

**line 8470** — before `CONTRACTED = "'\u2019"`

> The marks a word can be cut at without the cut being a syllable.

**line 8586** — before `MASKED = re.compile(r"\*\*+")`

> A word the source will not print. "f***" still has letters in it and was
> never in question; "****" has none, so it reached _key as empty and went
> through the door marked punctuation -- which glued it to its neighbour and
> ate the space between them: "Damn,****, every time", "You got that**** long
> arms". It is a word. Somebody sings it, it takes a turn on screen, and the
> spaces on either side of it are its own.
>
> Two asterisks or more, because one is an ellipsis' cousin -- a footnote
> mark, a lone star between verses -- and those really are marks. Nothing
> else is read as a mask: a run of dashes or hashes is as likely to be the
> punctuation this function exists for.

**line 8599** — before `WORD_MARKS = re.compile(r"^[&+/@]$")`

> SYMBOLS THAT ARE WORDS, which go through the door marked punctuation for
> exactly the reason a mask used to and want the same exemption.
>
> An ampersand between two names is read out -- "Osaze and Marcus" -- and the
> spaces on either side of it are its own. Ridden onto the word before it, its
> text is welded there and the word boundary moves to the far side of it, so
> the name comes out "Osaze& Marcus": the space is not narrowed, it is gone,
> and a new one appears where there was none. The slash that separates two
> credited singers is the same shape ("Brendon Urie / Juice WRLD"), and it is
> in this library as well.
>
> Only where the symbol stands ALONE as the syllable. Nothing here adds a
> space that was not there: the spacing comes off IsPartOfWord, so a source
> that writes "rock/pop" as one word cut into three keeps its pieces flagged
> as one word and draws exactly as it did. All this does is stop a symbol
> somebody sings being welded to the word in front of it.
>
> It costs what the mask costs: a lone "&" keeps its own stamp, and a source
> that gave it an enormous one gives it a turn on screen to match. That is
> the same bargain MASKED already struck -- it is a word, somebody sings it,
> and a word with a strange clock is the source's business rather than a
> reason to stop drawing it as a word.

**line 8632** — before `HOLE_GAP = 0.35`

> A hole between two syllables of one line shorter than this is not a rest
> somebody took, it is the end of a word that was not written down; see
> close_holes.
>
> The number is the one the editor already uses for the same judgement
> (ops.MAX_GAP), and QQ Music's own documents are what say it is right here.
> Over 19 songs, 6,882 syllable-to-syllable pairs inside a line: every
> document meets end to end between 73% and 100% of the time, and 13 of the
> 19 are above 90%. Contiguous is the house style, so a document that is not
> contiguous is not phrasing differently -- it is one whose ends were left
> out. Koven's "Light Up" meets end to end 35% of the time and its holes run
> 0.15s to 0.25s in the middle of phrases: "How do you switch up your
> mindset" is written with a fifth of a second of silence after "How".
>
> What is left standing above the cut really is a rest: across the same 19
> songs only 9% of the non-zero gaps are longer than 0.7s, and those are bars
> nobody sings in.


## `quiet_marks.fixed`

**line 8734** — before `out[-1]["Text"] = str(out[-1].get("Text") or "") + str(y.get("Text") or "")`

> Onto the word before: its text, and its spacing, since the mark
> is now what ends the word.

**line 8738** — before `while len(out) > 1 and _mark_only(out[0].get("Text")):`

> A mark that opened the line has nothing before it and was kept; give
> it to the word after instead.


## `quiet_marks`

**line 8767** — before `return doc`

> The document back as it came, not a copy of it that says the same
> thing. Almost nothing has a stray mark in it -- 60 of 60 Spicy
> Lyrics documents sampled here needed no repair at all -- and the
> copy was not free: the window decides whether an answer is NEW by
> asking whether it is the same document it already has, so rebuilding
> one that nothing was wrong with made every redraw look like a fresh
> lyric. See LyricsView.on_lyrics, and unlump above, which has always
> worked this way.


## `_unlump`

**line 8852** — before `joined: list[str] = []`

> A piece with no letters in it is not a word -- QQ's token for
> 'like, "' leaves a lone quote mark behind -- so it rides along with
> the one before it rather than being timed on its own.

**line 8876** — before `if k:`

> Only the first of these starts where the source said anything.
> The rest are shared out, and say so: eval_sources.py counts them,
> and a measurement that cannot tell a stamp from a guess is not
> measuring the thing that matters.


## module level

**line 8895** — before `ASIDE_WORDS = 6`

> How long a LONE bracketed line may be and still be read as an ad-lib on the
> line before it; see _fold_onto. Larger than CRY_WORDS, which counts the
> words of a shout, because a bracketed line and a bracketed run of words
> inside a lyric are two different claims. A shout is "(Yeah)" or "(Oh, God)"
> and four words is generous for one. A line the document put in brackets by
> itself is that document saying "second voice", and what a second voice
> sings is a phrase: Skillet's "Rise" answers "In a world gone mad" with
> "（In a place so sad）" -- five words, unmistakably the echo, and it was
> being drawn as a lyric with its brackets showing.

**line 8958** — before `CJK_MAKERS = ("qq", "kugou", "netease")`

> NetEase, QQ Music and Kugou hand their lyrics over in an LRC-shaped
> document, and LRC has nowhere to put a second voice: a backing vocal is
> either a line of its own -- "Yeah", "Uh", "Straight up" -- or a bracket
> sitting inside the lead. fold_cries and split_asides put both back where
> they belong, which is a repair of THOSE sources' shape and of nothing else.
> Spicy Lyrics and amll-ttml-db write real TTML and mark their own
> backgrounds, so running the repair over one of them rewrites a document
> that was already right: an amll copy reading "made chains for the crew
> (Ice)" came apart into a line and an ad-lib nobody asked for, and the
> screen stopped matching Spicy Lyrics' own. So the repair is only offered a
> document one of the three had a hand in.

**line 8970** — before `CJK_SOURCES = set(CJK_MAKERS) | set(BLENDS)`

> The blends are somebody else's lines under one of those three's word
> timing, and the donor's own ad-lib lines are lifted into them as they are
> built, so they carry the shape in with the timings. Read off BLENDS rather
> than written out, so a sixth blend cannot be added and forgotten here.


## `lrc_shaped`

**line 8995** — before `alone = str(d.get("_alone") or "")`

> `_alone` settles it on its own, in both directions: a blend that
> stood down is not a blend any more, it is exactly the one document
> it stood down to. A triblend holding LRCLIB's copy has nothing of
> NetEase or QQ in it, and one holding NetEase's own has nothing else.


## `_fold_onto`

**line 9131** — before `said = SL.line_text({"Lead": {"Syllables": syls}}) or ""`

> Brackets round a whole line do not always mean an ad-lib. Round a shout
> -- "(Yeah)", "(Oh, God)" -- they do, and that is what this is for. Round
> a whole sung sentence they mean the other thing entirely: a second voice
> singing a line of its own, or a call answering the verse. "(Caught up in
> the storm but we're the survivors)" is nine words and a complete lyric,
> and folding it into the line above turned a line somebody sings into a
> whisper hanging off the end of another one.
>
> A line standing on its own may be a phrase -- see ASIDE_WORDS. One with
> another bracketed line beside it has to be a shout to come along, which
> is the count fold_cries uses for the same judgement.

**line 9151** — before `said = [y for y in said if y["Text"]]`

> A bracket the source wrote as a syllable of its own is nothing at all
> once the bracket comes off, and an empty syllable still takes a word's
> turn to light on the screen.


## `_split_aside`

**line 9241** — on `            continue`

> the line IS the ad-lib

**line 9242** — before `said, spill = [], ""`

> The bracket does not have to be alone on its syllable, and where it
> is not, everything outside it belongs to the LEAD. QQ times
> "Yeah (Now she missin' me), yo" with the close and the comma glued
> into one syllable, "me),": strip only the edges of that and the
> ad-lib keeps "me)," while the lead's words run together as "Yeahyo",
> having lost the comma and the space it was holding. So the syllable
> is cut at the bracket instead, and what was outside is handed back.

**line 9267** — before `if spill.strip():`

> After the edges, so the mark this puts back is not stripped off
> again as one of theirs. It goes on the word before the ad-lib where
> there is one -- punctuation trailing a bracket is the lead's
> sentence carrying on -- and on the word after it where there is not.


## `fold_cries`

**line 9335** — before `for g in (it.get("Background") or []):`

> Whatever was hanging off the folded line comes with it. An
> ad-lib can have an ad-lib -- "Oh, yeah" with a "Uh" against it --
> and taking only the line's own words dropped the second one out
> of the song entirely.

**line 9348** — before `fresh = dict(it)`

> A copy deep enough to own its own Background list. Appending to the
> one that came in reaches back into the caller's document -- and the
> caller here is the cache, so the next reader of that document would
> have found ad-libs on it that nobody put there.


## module level

**line 9362** — before `MASK = "*"`

> A masked word, filled back in from a source that wrote it out.
>
> Apple Music carries the clean edit of a great many songs, and it marks what
> was taken out rather than dropping it: "n***a", "f**k", "****". Nothing is
> missing there but the letters -- the syllable is in the document, it is
> timed, and it is being sung -- so it can be filled in from a source that
> writes the word down. Two are asked, and both are already in the chain:
> Musixmatch, which is matched by Spotify id and answers explicit, and LRCLIB
> behind it, which needs no key and has almost everything.
>
> The letters go back one at a time. A mask is believed about every character
> it really wrote and only the `*` are filled in, so "F**k" comes back "Fuck"
> and never "fuck", and "n***a," keeps its comma. A donor word may only fill
> a mask it is exactly the shape of, in a document that agrees with the donor
> about the words either side of it -- so a cover, a remix or the wrong
> single cannot write a word of its own into the middle of a line.

**line 9379** — before ``UNMASK_EDGE = "\"'`“”‘’(){}[]<>,.!?;:…-–—"``

> Punctuation to look past at either end of a word. The mask is matched
> against somebody else's spelling of the same word, and two sources disagree
> about commas far more often than they disagree about letters.

**line 9383** — before `UNMASK_SHARE = 0.5`

> What share of a document's plain words a donor has to spell the same way
> before it is allowed to fill anything in. Half is the same bar _shared
> holds a blend donor to, and for the same reason: a donor about some other
> recording does not quietly agree with half of this one.

**line 9388** — before `UNMASK_REACH = 4`

> How far either side of where the alignment leaves it a donor word may be
> picked up. A mask sits in the gap between two stretches that matched, and
> the gap is usually the mask alone; anything further out than a few words is
> not this word being spelled differently, it is a line nobody matched.

**line 9393** — before `UNMASK_FROM = ("mxm", "lrclib")`

> Who is asked for the words, in order.

**line 9396** — before `CLEAN_MARK = re.compile(`

> A title that says the recording itself is the clean one.
>
> The whole premise above is that the DOCUMENT was censored and the RECORDING
> was not -- Apple files the clean lyric against a song whose audio says the
> word, and the letters are all that is missing. Where the recording is the
> clean edit too, putting them back is the feature running backwards: the
> screen says "fuck" over a bar of silence.
>
> Written narrowly on purpose. It matches a MARKER -- parenthesised, bracketed,
> or hung off a dash at the end -- and never a bare word, because "clean" is a
> word songs are allowed to be called: "Mr. Clean" is a title and Clean Bandit
> is a band. And "Radio Edit" is deliberately not in here. A radio edit is a
> LENGTH edit far more often than a censored one -- there are two in ./lyrics
> that say the words perfectly plainly -- and turning uncensoring off for all
> of them to catch the few would be trading a rare wrong word for a common
> missing one.
>
> EDITION in lyrics_gui and _NOISE above both know these suffixes already and
> both STRIP them, which is the opposite job: they are making two catalogues
> agree about which song this is, and this is asking which CUT of it is playing.

**line 9422** — before `COMMUNITY_SYNC = "a community sync"`

> The one answer clean_edit gives that the window keeps to itself. A
> person's own transcription is not a provider that failed quietly --
> it is the case where nothing went wrong at all -- and the names in it
> are printed on the next line of the footer anyway, by made_by. Named
> here rather than matched as a string over in the window, so the two
> cannot drift apart. See lyrics_gui.credit_rows.


## `clean_edit`

**line 9452** — before `hand = str((doc or {}).get("_hand") or "")`

> 1. Somebody's own file. The masks in it were put there by the person
>    whose screen this is, timed against the copy they were listening to,
>    and a document that was made by hand is not a document with a defect
>    in it. This one is not evidence about the recording at all; it is
>    about whose words these are.

**line 9460** — before `who = credited(doc)`

> 2. Somebody else's, for the same reason. A community sync is a person's
>    transcription of what they heard -- Spicy Lyrics' uploads, Unison's
>    submissions, the AMLL database -- and where they wrote a mask, a mask
>    is what they meant. It may be the clean cut they were listening to;
>    it may be their own choice about their own file. Either way it is not
>    a catalogue filing the clean lyric against explicit audio, which is
>    the one thing this feature exists to put right.
>
>    Apple's own TTML carries no such credit, and neither do QQ, Kugou,
>    NetEase, Musixmatch or LRCLIB, so the common case is untouched.

**line 9473** — before `for field in ("title", "album"):`

> 3. The title, which costs nothing and is right whenever it speaks. It is
>    also the only one of the four that works away from Spotify: MPRIS and
>    the Windows session hand over a title and an album and no flags at all.

**line 9480** — before `said = (meta or {}).get("explicit")`

> 4. Spotify's own flag for the track the player has open. The best
>    evidence there is and the cheapest: it came down with the title in
>    the same reading, it names the RECORDING rather than the song -- a
>    clean edit and the master it was cut from are two different tracks
>    with two different ids -- and nothing had to be searched for to get
>    it, so nothing can have been mismatched on the way. None where the
>    player did not say, which is every transport but Spicetify.

**line 9490** — before `if enabled is None or "mxm" in enabled:`

> 5. Musixmatch, which is asked the same way -- `_mxm_ask` sends
>    track_spotify_id -- and is the fallback for the transports that hand
>    over no flag of their own. Skipped when the user has switched
>    Musixmatch off: it is not asked as a donor then either.


## `_fill`

**line 9570** — before `return ""`

> Whatever is under a mask is a letter. A donor that has
> punctuation there is spelling something else.


## `_spread`

**line 9634** — before `return [word[n:n + 1] for n in range(len(widths))]`

> Fewer letters than stamps. They go at the front, so the word starts
> where the mask started -- which is the one thing about its timing
> that is actually known.


## `_stand_in`

**line 9740** — before `return ""`

> Two letters at least. A single letter standing where a word was
> taken out is a donor that has split something up rather than the
> word itself -- and "a" or "I" in that slot means the mask was never
> hiding a word of this kind at all.


## `_spine`

**line 9778** — before `tails, back, at = [], [None] * len(once), []`

> The longest subsequence of those that also moves forward in b.


## `_unglue`

**line 9827** — before `return ""`

> Stars at both ends, or at neither: this is a mask written over one
> word, and the word it was written over is the whole of it.

**line 9832** — before `return ""`

> No letters to check the glue against. "a" is enough -- it still has
> to BE the donor's word at that place, and one letter agreeing where
> the alignment says it should is the same evidence as five.

**line 9836** — on `    j = at if tail else at + 1`

> where the letters should be

**line 9837** — on `    k = at + 1 if tail else at`

> and the word that was taken out


## `_unmask_with`

**line 9974** — before `yours = _word_slots(_items(SL.payload(donor or {})))`

> The donor's slots rather than only its words: which of them begin a
> line is what says whether a capital it hands over is about the word or
> about where that source decided to break. See _uncapped.

**line 9987** — before `return doc, 0`

> Not this recording. Every word it could offer would be a guess.

**line 9997** — before `lo = hi = 0`

> The gap between the two stretches that did match, if the two of
> them left one where this word is. They do not always: the aligner
> is free to match a chorus to the same chorus sung later, and where
> it has, the stretch after the mask begins BEFORE the stretch in
> front of it ends. Nothing is lost by it -- a chorus matched to
> itself spells the same words -- but there is no window to read.

**line 10007** — before `got, src = "", None`

> The rules in order of how much they know, and every one of them
> asked before the one under it. The order is not housekeeping: a mask
> glued to the word in front of it -- "We****" -- is the exact shape
> of a mask written over a longer word, so a rule that goes looking
> for one anywhere in the donor will find a word that fits and be
> wrong. It only gets to look once the rules that know WHERE they are
> have had their turn.

**line 10016** — before `if i0 < k < i1 and j0 < want < j1 and i1 - i0 == j1 - j0:`

> Nothing to match, so nothing but the place: the mask stands in a
> stretch between two words both documents share, and the two of
> them put the SAME NUMBER of words in that stretch. Then its
> place in the stretch names one word of the donor's and no other.
>
> Asking instead that both its neighbours anchor -- which is the
> same rule with a stretch of one -- turned down every mask whose
> neighbours the two sources merely spell differently, and that is
> not rare: two transcriptions of the same line disagree about
> where a word ends far more often than they disagree about what
> is sung. A stretch that has grown or shrunk between the two IS
> turned down, because then nothing says which word of it went.

**line 10031** — before `for j in sorted(range(lo, hi), key=lambda x: (abs(x - want), x)):`

> Nearest the alignment's guess first, so a line with two masks in
> it takes them in the order they are sung rather than the order
> the window happens to be scanned in.

**line 10040** — before `got = _unglue(mask, theirs, want)`

> Two of the donor's words where the document has one: the mask
> may have been glued to its neighbour on the way through a blend.

**line 10047** — before `got, src = _recase(mask, _stand_in(mask, theirs[want])), want`

> The mask has been cut about on its way through a blend and no
> longer has the shape of anything. Its letters are still in the
> donor's word, in order, and both documents put exactly one word
> in this place -- so it is that word, whatever length the mask
> was left with.

**line 10054** — before `if src is not None:`

> Only where one of the rules above named a word of the donor's.
> _unglue builds its answer out of two of them and _only_fit finds
> its word by searching the whole document, so neither has a line
> of the donor's to hold responsible for a capital.


## `_unmask_group`

**line 10104** — before `for lo, hi, bit in sorted(rows, reverse=True):`

> Right to left, so an offset is still the offset it was measured
> at when a syllable holds two words and both of them were masked.


## `_unmask_write`

**line 10136** — before `fresh = dict(got)`

> The line itself was holding the words, so filling them in
> has already rewritten the only copy there is.


## `uncensor`

**line 10194** — before `out = unlump(got)`

> Unlumped again because a mend can put a space back where a blend
> lost one, and two words under one stamp is exactly what unlump
> is for -- see _unglue.


## `graft_syllables`

**line 10266** — before `own, b_e = new.get("EndTime"), _line_end(it)`

> The base's own end, where it has one that stands clear of the
> next line. NetEase stamps a line to where the next one begins,
> so grafting its end onto a document that knows when the singing
> actually stopped holds the line lit through the silence after
> it -- the same trade the blends were making with QQ and Kugou.
> Never into the words: if the base wants to end before a word
> that has already finished, it is not describing this line.

**line 10316** — before `doc["_lifted"] = True`

> A graft only ever runs on a line-quality base -- it is refused above
> otherwise -- so these lines are lifted by definition.


---

## Earlier lift — 2026-08-23

Comments lifted out of `mild-lyrics/lyric_sources.py` on 2026-08-23, before the work that followed. They are not in the code any more, so they are kept here as they were; the line numbers are the ones that code had then.

### module level

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


### `_get`

**line 222** — before `if e.code != 429 or attempt == 2:`

> Still held off. The gate is kept across the wait on purpose:
> the point is to stop crowding this host, not to back off and
> immediately let a sibling take the slot.


### module level

**line 238** — before `# --------------------------------------------------------------------------`

> TTML -> Spicy Lyrics document


### `_syllables`

**line 304** — before `if tail.strip():`

> Stray punctuation between spans ("'", ",") belongs to the syllable it
> follows -- left loose it would be dropped, and it is never sung alone.

**line 310** — before `part = not (tail and tail != tail.strip())`

> trailing whitespace in the tail is the word boundary

**line 313** — on `            part = True`

> CJK run: no spaces are expected

**line 315** — before `part = (not any(c.isalnum() for c in text)`

> keep an apostrophe with the word it splits: "Couldn" + "'" + "t"


### `_repair`

**line 356** — before `run = [j for j in range(len(syls)) if j not in ok`

> share the hole evenly between however many broken syllables sit in it


### `_unwrap`

**line 388** — on `        return syls`

> "()" on its own is not a lyric


### `_destamp`

**line 424** — before `if len(set(starts)) > 1 or len(starts) < 2:`

> Not "all zero": a file stamped entirely at 12.0 is equally not a sync.
> One line legitimately starting at 0 is fine, so it takes every line
> agreeing to condemn the document.


### `_credits`

**line 455** — before `seen.add(text.lower())`

> the same name is sometimes listed by two <songwriters> blocks


### `parse_ttml`

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


### `_deword`

**line 573** — before `for a in ("StartTime", "EndTime"):`

> A line whose <p> carried no begin/end kept its timing on the group
> alone, so take it back before the group goes -- otherwise demoting the
> word timings would strip the line of any timing at all.

**line 580** — before `bg = [g for g in (new.get("Background") or []) if isinstance(g, dict)]`

> Backing vocals are their own voice with their own line timing, so they
> survive the demotion; only the syllables inside them go.


### module level

**line 604** — before `# --------------------------------------------------------------------------`

> LRC -> Spicy Lyrics document


### `parse_lrc`

**line 620** — before `if len({t for t, _ in rows}) < 2:`

> Same trap as the TTML one: stamps that never advance are not a sync. Keep
> the words -- they are still the lyrics -- and fall through to Static
> below, using them if the record carried no plain text of its own.

**line 630** — on `                continue`

> an empty stamp is an instrumental gap

**line 631** — before `nxt = next((rows[j][0] for j in range(i + 1, len(rows))), None)`

> LRC gives starts only; a line runs until the next one begins,
> bounded so a long instrumental break does not leave one line lit.


### module level

**line 647** — before `# --------------------------------------------------------------------------`

> the providers


### `amll_index`

**line 693** — before `out.setdefault(f"{_norm(name)}\x00{_norm(art)}", f)`

> first submission wins; later ones are usually re-uploads


### `from_amll`

**line 717** — before `for art in re.split(r"\s*[,;/&]\s*|\s+feat\.?\s+|\s+x\s+", artist):`

> the credit line may hold several artists; any one of them matching is
> enough, since the db files a song under each separately


### `from_youly`

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


### `from_lrclib`

**line 828** — before `q = _qs(track_name=title, artist_name=artist)`

> /api/get insists on an exact duration match; search is fuzzy, so fall
> back to it and pick the closest-length hit ourselves.

**line 839** — before `hits.sort(key=lambda h: (not h.get("syncedLyrics"),`

> a synced hit beats a longer unsynced one, then closest duration


### module level

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


### `_ne_get`

**line 882** — on `    with _gate(url):`

> same courtesy as everyone else's server


### `_ne_rank`

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


### `_ne_yrc`

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


### `_ne_bg`

**line 1060** — before `lead.extend(cur)`

> A bracket that never closes is not a backing vocal, just a stray mark


### module level

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


### `_ne_doc`

**line 1152** — before `roma = _ne_lrc_rows(get("romalrc"))`

> romalrc is line-level and keyed to the same clock, so it can be matched by
> start time -- no fuzzy alignment needed, unlike a Genius page.

**line 1168** — before `"HasTransliterations": False,`

> false on purpose: where romalrc exists the lines already carry a real
> romanisation, and where it does not, deriving one is the GUI's own
> decision to make rather than something this source should assert


### `_ne_writers`

**line 1194** — before `for name in re.split(r"\s*[/、,，&]\s*", m.group(2)):`

> one credit line can list several people, and the two lines usually
> name the same person twice over


### `from_netease`

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


### module level

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


### `_pair`

**line 1357** — before `if not _shared(a, b, pairs):`

> Decided on the exact matches alone: whether these two are the same song is
> exactly the question the loose pass must not be allowed to answer, since
> it would happily pair anything with anything inside a wide enough window.


### `_timely`

**line 1382** — on `        return pairs`

> nothing paired, or the donor was rejected whole

**line 1390** — on `        return pairs`

> too few to have a trend to disagree with


### `from_blend`

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


### `_blend`

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


### module level

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


### `_rejoin`

**line 1961** — before `stops, at = set(), 0`

> where each word ends, counted in the despaced string

**line 1970** — before `same = {}`

> flat index -> worded index, for the stretches that matched exactly

**line 1980** — before `nxt = flat[i + 1] if i + 1 < len(flat) else "a"`

> Never break onto or away from punctuation: the segmenter counts "K.O."
> as three tokens and splitting there spells it "K . O .", which is
> worse than the per-mora line this is meant to improve on.


### `netease_roman`

**line 2018** — before `for i, c in enumerate(roman):`

> Genius opens a line with a capital and these two get read together --
> a Genius line, then a NetEase line filling a gap in it, then Genius
> again. Left lowercase the borrowed ones announce themselves as coming
> from somewhere else, which is not information anybody wanted.


### module level

**line 2031** — before `# --------------------------------------------------------------------------`

> disk cache


### `_cached`

**line 2047** — on `        return None`

> a stale "nothing here", or a hit old enough to re-ask


### module level

**line 2084** — before `# --------------------------------------------------------------------------`

> the chain


### `fallback`

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


### module level

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


### `_regroup`

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


### module level

**line 2530** — before `RELAY_LIKE = 0.75`

> How alike two spellings of one line must be before the donor's syllable
> boundaries are trusted as cut points for ours. The line pairing has already
> decided these are the same line; this is the narrower question of whether the
> two write it closely enough to cut along, so it matches _near_pairs' floor.


### `_recut`

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


### `_relay`

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


### `graft_syllables`

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


### `_transfer`

**line 2839** — before `if matched < 0.6 * len(ours) or not any(out):`

> A weak alignment means the two are not really the same rendition of the
> song, and guessing which side a line belongs to is worse than not saying.
