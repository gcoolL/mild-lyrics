# `mild-lyrics/spicy_lyrics.py`

Comments lifted out of `mild-lyrics/spicy_lyrics.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

**line 88** — before `CACHE_PREFIX = "SpicyLyrics_LyricsStore"`

> WHERE SPICY LYRICS KEEPS WHAT IT HAS FETCHED, as a prefix rather than a
> name. The bucket carries a generation in its own name and the extension
> bumps it: the Marketplace build today opens "SpicyLyrics_LyricsStore_g1",
> and the builds before it opened "SpicyLyrics_LyricsStore" plainly. Pinned
> to one generation this read an empty store on every other build -- and an
> empty store is indistinguishable from Spicy Lyrics having nothing for any
> song, which is what it looked like. Every store whose name starts with this
> is read, newest generation first.
>
> It is a PREFIX everywhere it is passed, and it has to be: caches.open()
> CREATES a store that is not there, so a name guessed wrong does not fail,
> it quietly makes an empty one and reads that.

**line 101** — before `IDB_NAME, IDB_STORE = "spicylyrics", "lyricsStore"`

> ...and the IndexedDB the builds before those used, matched by prefix for
> the same reason. Only databases the page actually lists are opened, so a
> miss here cannot conjure one either.

**line 106** — before `_JS_STORES = """`

> Resolving both, in front of every snippet below that reads them.

**line 123** — before `JS_WHERE = """(() => {`

> What the page says about itself. The same two facts MPRIS publishes, asked
> of Spotify's own renderer instead -- which is the only route that exists on
> Windows and on a Mac, and is the more accurate of the two everywhere: the
> position here is the player's own rather than a property sampled off a bus.

**line 203** — before `JS_IDS = """`

> The same question with nothing but the ids wanted, which is what every tool
> here that walks the whole cache asks. It was six copies of one snippet that
> opened the store by name -- and so six more places that read an empty cache
> on a build whose generation had moved on, and made one each while they were
> at it.

**line 322** — before `# --------------------------------------------------------------------------`

> READING SPICY LYRICS' CACHE. Every route in this project that opens that
> cache comes through here, and the reason is the zero-width spaces: Spicy
> Lyrics puts them in itself, so not one of them is the lyric's own and not
> one of them should survive being read. Taking them out at the door is the
> only way that stays true -- `unzwsp` can only clean the string in front of
> it, and it was being asked in some places and not others, which is how six
> of the .ttml files here came to be written with a zero-width space sitting
> after every word.

**line 603** — before `SCRIPTED = re.compile(r"[぀-ヿ⺀-⿟㐀-䶿一-鿿ᄀ-ᇿㄱ-ㆎ가-힣ힰ-ퟻ]")`

> Every script here that a romanisation is FOR. CJK on its own leaves Hangul
> out, and Hangul is the case where a source hands us a perfectly good reading
> and nothing ever draws it: QQ Music files "na eo ddeo kae" against KiiiKiii's
> 나 어떡해 and the gate below threw it away for not being Chinese or Japanese.

**line 686** — before `_PARTICLE_SAID = {"は": ("ha", "wa"), "へ": ("he", "e"), "を": ("wo", "o")}`

> The same three, as (what pykakasi spells them, what they are read) for a
> particle sitting at the END of a segment rather than alone in one.


## `line_readings`

**line 806** — before `rom = particle_rom(src, rom, at_start=(a == 0))`

> Before the cut, not after it. See particle_rom: a segment is where
> the segmenter has already said what the words are, and a syllable is
> not -- correcting per syllable reached 46 of this collection's 143
> particles and this reaches 120.


## module level

**line 836** — before `KANA = re.compile(r"[぀-ゟ゠-ヿ]")`

> Han characters are shared; kana are not. This is what tells a Japanese
> lyric from a Chinese one, and pykakasi will read Chinese as Japanese all day
> without ever saying it cannot -- 电吉他 came back furigana'd ていおん・きち.

**line 917** — before `# --------------------------------------------------------------------------`

> Hangul and Han, which pykakasi cannot read and used to be given up on.

**line 922** — before `KO_LEAD = ("g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss", "",`

> Revised Romanization, by the arithmetic the code points are laid out with: a
> syllable block is (lead * 21 + vowel) * 28 + tail counted from U+AC00, so the
> jamo come back out with two divisions and no table of 11,172 syllables.

**line 929** — before `KO_TAIL = ("", "k", "k", "k", "n", "n", "n", "t", "l", "k", "m", "l", "l", "l",`

> A final consonant is not pronounced the way the same jamo is pronounced at
> the front of a block -- it is unreleased, so ㄱ ㄲ ㅋ all come out k and ㅅ ㅆ
> ㅈ ㅊ ㅌ ㅎ all come out t.

**line 935** — before `KO_MOVE = ("", "g", "kk", "ks", "n", "nj", "n", "d", "r", "lg", "lm", "lb",`

> ...except in front of a silent ㅇ, where it slides into the next block as an
> onset instead and is released after all: 한국어 is han-gu-geo, not han-guk-eo.
> The pair finals split, one letter to each side.

**line 941** — before `KO_BLEND = {("k", "n"): ("ng", "n"), ("k", "m"): ("ng", "m"),`

> Where a final and the consonant after it change each other. Each value spells
> BOTH sounds, because that is what assimilation means -- 신라 is silla, not
> sil-ra -- so the onset it swallows is not written again.
> Written as (what the block keeps, what the next block starts with), so a
> reading can still be cut up a block at a time for ruby.


## `hangul_pieces`

**line 1005** — on `            head = KO_ASPIRATE[head]`

> ㅎ before g/d/j/b: 좋고 joko

**line 1013** — on `        if nlead == 11:`

> ㅇ, silent: the final moves over

**line 1015** — before `if len(move) > 1 and KO_TAIL[tail] == move[:1]:`

> A pair final splits, one letter staying and one going across.

**line 1022** — on `        if nlead == 18:`

> ㅎ: aspirated by the final

**line 1025** — on `        if tail == 27:`

> ㅎ final: taken by the onset

**line 1034** — on `            carried = blend[1]`

> the onset the blend swallowed


## `pinyin_reading`

**line 1084** — before `if len(out) < len(text) and HAN.match(text[len(out)]):`

> A Han character yields one reading; a run of anything else comes
> back whole and is spread over the characters it came from.


## `readings`

**line 1141** — before `joined = "".join(canon(texts[i]) for i in run)`

> Both of the others are read a run at a time for the same reason the
> Japanese one is: 银行 is a bank and 一行 is a line, and a syllable
> timed on its own has lost the word that says which. Then the reading
> is cut back up by the characters each piece brought to it.


## `timeline`

**line 1283** — before `japanese = any(KANA.search(line_text(i) or "") for i in items)`

> Asked of the whole document rather than of a line: a Japanese lyric has
> lines that are all kanji, and one of those is not a Chinese song.


## `timeline.roman_of`

**line 1314** — before `if not any(y.get("TransliteratedText") for y in syls):`

> A source that carries no romanisation at all used to end the matter,
> because there was nothing to fall back on but pykakasi and pykakasi
> is only right about one of these scripts. Now there is: a reading
> can be DERIVED for any run `can_read` says this machine can read, so
> a Korean lyric nobody has ever romanised, or a Chinese one on a
> machine with pypinyin installed, gets one here rather than being
> drawn twice in its own script.

**line 1324** — before `derived, owner = readings(texts, japanese)`

> pykakasi answers for any Han character put in front of it and never
> says it could not -- it reads Chinese as Japanese, and Korean not at
> all. `readings` is what decides which script each run of the line is
> actually in and reads it with the right thing: kana and the kanji of
> a document that HAS kana through pykakasi, Hangul by the Revised
> Romanization rules, and the rest of the Han through pypinyin where
> it is installed. The source's own romanisation still wins wherever
> it gave one.

**line 1358** — before `if all(SCRIPTED.search(r[2] or "") or not (r[2] or "").strip()`

> A "romanisation" still written in the script it was meant to leave is
> not one -- it is the line again, drawn a second time in the smaller
> type. That is what a Chinese lyric produced here before `readings`
> could read one, and it is still what a script nothing here handles
> produces, so the refusal stays: showing the line twice is worse than
> showing it once.


## `timeline`

**line 1424** — before `"group": group,`

> The line this one belongs to. An ad-lib is written as part of
> its line and is drawn hanging off it, so the two have to stay
> findable from each other after the list is flattened and a
> backing group that starts early is moved ahead of its lead.

**line 1429** — before `"sung": last_sung(lead),`

> When the singing stops, as opposed to when the line ends.


## `_finished`

**line 1535** — before `return True`

> An interlude marker: breathing dots over an instrumental gap, with
> nothing in it to sing. It is never mid-word, so it never has a claim
> on the view -- without this the marker's end IS the next line's
> start, and a scroll-ahead into a line that follows a gap could not
> begin until the moment it was too late to be ahead of anything.


## `focus_index`

**line 1581** — before `started = [i for i, ln in enumerate(lines)`

> A document of nothing but ad-libs: there is no line to read on to,
> so the newest thing that has started is as good as it gets.

**line 1586** — before `opened: dict = {}`

> When each line's ad-libs first open their mouths. Taken as "has begun"
> rather than "is sounding now": a two-word ad-lib can be over before the
> line it announces starts, and a view that followed it there and came
> back would have scrolled twice to arrive where it already was.


## module level

**line 1901** — before `LABELS = (("Title", "musicName"), ("Artist", "artists"), ("Album", "album"),`

> What a song is, as amll-ttml-db files it -- the only convention here that has
> anywhere to put a title. Apple's <head> names the writers and nothing else,
> so a document saved out of the editor with a title and an artist typed into
> its Song info box came back from disk anonymous, and the "that file holds a
> different song" guard had nothing left to compare.


## `_covering`

**line 1934** — before `if not isinstance(b, (int, float)):`

> The lead's stamps where it has them, the line's where it has not: a
> group whose syllables are still untimed carries no stamps of its own,
> and reading the pair off it alone unstamped every line-timed <p> in a
> document that had any word timing at all.


## `render_ttml`

**line 2044** — before `inner = _spans(lead) if _worth_spans(lead) else escape(line_text(item))`

> A Lead holding no syllables is not a lead -- it is a line-timed line
> wearing the word-timed shape, which every mixed document has some of.
> Written out of its own (empty) spans the words went with them: 13 of
> the 62 lines of NF's "Time" came back out of a save as empty <p>s.

**line 2053** — before `if g.get("LeadIn") and not isinstance(g.get("StartTime"), (int, float)):`

> An untimed ad-lib that opens its line is written where it
> sounds, because nothing else in the file can say so: a timed one
> is placed by its stamps whichever end it is written at, and one
> with no stamps has only its position left. Written after the
> lead like the rest, "(Promise I like it like—) Promise I like it
> like that" came back as an answer instead of a call.

**line 2066** — before `if lang:`

> Checked against the words before it is written. Providers guess this
> from a few hundred words and the guess goes wrong the same way every
> time -- an English lyric filed under a small Latin-script language.
> Music Baby ships as `pcm`, Creep as `sco`. It picks the hyphenation a
> word is cut with and it is what a reader is told the song is, so a
> wrong one is not cosmetic.

**line 2093** — before `writers = "".join(`

> A credit is a name, not a lyric, and one of them arrived with a
> zero-width space in front of it -- which is invisible in the tag and
> not invisible at all to anything matching the name.


---

## Earlier lift — 2026-08-23

Comments lifted out of `mild-lyrics/spicy_lyrics.py` on 2026-08-23, before the work that followed. They are not in the code any more, so they are kept here as they were; the line numbers are the ones that code had then.

### module level

**line 78** — before `sys.path[:0] = [str(p) for p in (_HERE, _HERE.parent) if str(p) not in sys.path]`

> spotify_dom.py may sit next to this file or one level up -- offer both, or the
> import below fails depending on where the scripts were dropped.

**line 88** — before `# --------------------------------------------------------------------------`

> current track id, straight off D-Bus (no CDP needed)

**line 109** — before `# --------------------------------------------------------------------------`

> JS payloads

**line 228** — before `# --------------------------------------------------------------------------`

> player clock (D-Bus, no CDP round-trips)

**line 257** — before `HYPHENS = "-\u2011\u2013"`

> Written boundaries: a hyphen, a non-breaking hyphen, an en dash.

**line 259** — before `DIGRAPHS = ("th", "ch", "sh", "ph", "wh", "gh", "ck", "qu")`

> Only true digraphs -- one sound, never split. Ordinary onset clusters (st, tr,
> bl...) must stay splittable or VCCV words break: ques-tion, not que-stion.


### `syllabify`

**line 273** — before `if len(word) > 1 and any(h in word[:-1] for h in HYPHENS):`

> A hyphen already IS a syllable boundary -- somebody wrote it there --
> and it belongs to the piece before it: "Ten-time" is sung "Ten-" then
> "time", never "Ten" then "-time". Split on it first and syllabify each
> part on its own, so the rule below never has to reason about a word with
> two halves in it.

**line 293** — before `if pieces:`

> the chunk was a bare hyphen; it rides on whatever is there

**line 301** — before `while len(pieces) > 1 and all(c in HYPHENS for c in pieces[0]):`

> ...and a leading bare hyphen has nothing before it to ride on

**line 334** — before `final_le = (`

> word-final consonant + "le" is a syllable of its own (lit-tle, im-pos-si-ble)

**line 338** — before `silent = -1`

> otherwise a trailing silent 'e' is not its own syllable -- and it stays
> silent with an inflection stuck on it: saved, named, missed, Tides.
> Those came back "sa-ved", "na-med", "mis-sed", "Ti-des", which is a
> second syllable nobody sings.
>
> It is only silent where English actually swallows it. After t or d the
> -ed IS a syllable (wan-ted, nee-ded), and after a sibilant so is the -es
> (wish-es, ra-ces, pa-ges) -- hence the two exception sets.

**line 362** — before `units, at = [], end_v + 1`

> Count the consonants between two vowels in UNITS, where a digraph
> is one unit -- "ch" is a single sound and cannot be cut through.
>
> Doing it this way, rather than counting letters and then shoving the
> cut off a digraph, is what tells "tea-cher" from "wach-ten". Both
> contain "ch"; in the first it is the entire cluster, so it opens the
> next syllable, and in the second a "t" follows it, so the "ch" closes
> this one. The old code moved the cut LEFT whenever it landed inside a
> digraph, which gave "wa-chten" -- an onset no language has.

**line 379** — on `            cut = units[0]`

> one consonant: it opens the next syllable

**line 385** — before `cuts = [c for c in cuts if c < n - 3] + [n - 3]`

> the last syllable is consonant + "le", so cut before that consonant

**line 393** — before `out: list[str] = []`

> a piece with no vowel is not a syllable -- fold it into its neighbour


### module level

**line 447** — before `CJK = re.compile(r"[぀-ヿ⺀-⿟㐀-䶿一-鿿]")`

> kana, radicals/compat forms, ext-A, unified

**line 464** — on `SOKUON = re.compile(r"[っッ]\s*$")`

> small tsu, っ / ッ

**line 491** — before `PARTICLES = {"は": "wa", "へ": "e", "を": "o"}`

> Standalone particles are written one way and read another. Romanising them
> per-character gives "watashi ha" / "kimi wo", which is simply wrong.

**line 512** — before `TRAILING_KANA = "っゃゅょぁぃぅぇぉゎーッャュョァィゥェォヮ"`

> kana that never begin a mora: they lean on the character before them


### `line_readings`

**line 542** — on `    owner = [-1] * len(texts)`

> which romanizer word each syllable fell in

**line 583** — before `if stripped in PARTICLES and (i or stripped != "は"):`

> a syllable that is nothing but は/へ/を is the particle, not the kana


### `furigana`

**line 645** — before `touched = [i for i, (x, y) in enumerate(spans) if x < hi and y > lo]`

> A reading can straddle two timed pieces, since the syllable split and
> the word split are different things. Divide it by character share
> rather than dropping it or hanging it off one side.


### `geminate`

**line 686** — on `        return None`

> gemination before a vowel is not a thing

**line 689** — on `        head = head[1:]`

> already doubled on the far side


### module level

**line 695** — before `BG_LEAD = 0.4`

> How far ahead of its line a backing vocal must start before it is read as
> leading the line rather than opening with it.
>
> Not any amount: a backing vocal sung WITH the line is routinely stamped a
> hair early. On "No More Sorrow" the ad-libs lead by 0.01-0.02s, which is
> jitter, and lifting those above the line they answer just scattered it. The
> same track's genuine early entries lead by ~3.3s, so there is a lot of room
> between the two. Of the 416 early backing vocals in a 2323-song library, 288
> clear this and 128 are the near-simultaneous kind.


### `timeline.syls_of`

**line 721** — before `_trim(y.get(key) or y.get("Text", "")),`

> some syllables carry an empty romanisation; showing the
> original there beats rendering a hole in the line
>
> Trimmed at the edges: the layout puts its own gap
> between two pieces that are not part of one word, so
> a piece carrying a trailing space of its own is drawn
> with two. See syllables_text.

**line 733** — before `return s`

> A romanisation is already one token per sung syllable; re-splitting
> it would interpolate boundaries inside "sayonara" for no gain.


### `timeline.roman_of`

**line 741** — before `syls = [y for y in (group or {}).get("Syllables") or []`

> must use the SAME filter syls_of does, or the zip below pairs each
> romanisation with the wrong original

**line 745** — before `if not any(CJK.search(y.get("Text", "") or "") for y in syls):`

> A line with no CJK in it is already readable, so it gets no second
> row -- some sources hand back a "transliteration" for the English
> lines of a mixed song that is just the English again.

**line 750** — before `if not any(y.get("TransliteratedText") for y in syls):`

> Some tracks flag transliterations at the top but leave whole lines
> without one. Derive those rather than showing a blank under every
> other romanised line.

**line 757** — before `texts = [y.get("Text", "") or "" for y in syls]`

> derived readings come from the whole line at once, for the context

**line 766** — before `broken = {owner[i] for i, y in enumerate(syls) if failed(y) and owner[i] >= 0}`

> If any syllable of a word needs deriving, derive the whole word. Mixing
> a derived "shi" for 沈 with the source's "mu" for む spells "shi mu";
> taking both halves of the derived reading spells "shizumu".

**line 773** — before `if failed(y) or owner[i] in broken:`

> The source is kept wherever it holds up -- it is community-curated
> and handles the invented readings lyrics are full of, which nothing
> can infer from the text.

**line 779** — before `for i in range(len(rows) - 1):`

> Syllables that fall inside one romanizer word are one word on screen:
> "shizu" + "mu" reads as "shizumu", and 諦めの悪い輩 reads "taime no
> warui tomogara" rather than "tai me no waru i tomogara".
>
> It takes BOTH signals to agree. The romanizer alone lumps a whole kana
> run into one segment, which glued "sayonara dake datta" into a blob;
> IsPartOfWord alone is Japanese orthography, which happily runs a
> entire phrase together because the script has no spaces. Where the
> word segmentation and the source's own word flag say the same thing,
> the join is safe.

**line 793** — before `for i in range(len(rows) - 1):`

> っ geminates onto the next syllable, so those two do join

**line 800** — before `return [tuple(r) for r in rows]`

> Note every token is spaced (part=False) except those joins: IsPartOfWord
> encodes Japanese orthography, which is right for かな but would glue the
> romanisation into "sayonaradakedatsuta".


### `timeline`

**line 819** — on `        here = len(out)`

> where this line's own row begins

**line 827** — before `"text_roman": roman_text(lead, item),`

> line-level lyrics carry the romanisation on the item, not on a
> Lead group -- passing `lead` twice never looked there

**line 834** — before `bg = item.get("Background")`

> Backing vocals are a concurrent voice with their own timings, not part
> of the lead line -- emit them as separate entries so they overlap it.

**line 837** — before `lead_syls = [y.get("StartTime") for y in (lead or {}).get("Syllables") or []`

> When the lead is actually SUNG, not when its group nominally opens.
> Lead.StartTime is padded ahead of the first syllable, and comparing
> against it found no early ad-libs at all in the whole cache -- while
> 416 backing vocals do come in before the lead's first syllable, which
> is the moment a listener hears the line begin.

**line 854** — before `at = len(out)`

> An ad-lib that comes in BEFORE the line it belongs to should be
> read before it, not under it. Anything starting at or after the
> lead stays below, which is the common case (an answering vocal).

**line 861** — on `                here += 1`

> the lead has moved down a row

**line 878** — before `return synced`

> Deliberately NOT sorted by start. The source lists lines in reading order,
> and sorting broke that wherever two voices overlap: a backing vocal whose
> own StartTime falls after the NEXT lead line's got lifted away from the
> line it answers and dropped a row lower ("critics I turn to" / "Crickets"
> landing under the following line), and an ad-lib that comes in a beat
> before the lead it sits under jumped above it. Across the whole local
> cache that hit 64 of 1988 songs; only one had source order genuinely
> wrong, and that one has stale timestamps no ordering can rescue.


### `focus_index`

**line 935** — on `    while moved:`

> walk out to the outermost container


### `active_index`

**line 957** — on `                return idx`

> still in the gap after this line


### module level

**line 975** — before `# --------------------------------------------------------------------------`

> formatting


### `syllables_text`

**line 1019** — before `out += text if s.get("IsPartOfWord") else _trim(text) + " "`

> Both edges: a leading space doubles the gap just as a trailing one
> does, and the piece before it has already ended its word.


### `line_text`

**line 1042** — before `text = (text + " " + " ".join(f"({p})" for p in parts)).strip()`

> One pair of brackets per GROUP, not one pair around all of them.
> Two answering voices written apart -- "(Baow) (What the fuck are
> you doing, Toxi?)" -- came back as "(Baow What the fuck are you
> doing, Toxi?)", which is every word in the wrong shape and reads
> as one long ad-lib rather than two short ones.


### `syllable_group`

**line 1073** — before `out.append(tag + s.get("Text", "") + ("" if s.get("IsPartOfWord") else " "))`

> IsPartOfWord means "joins the next syllable with no space"


### `elrc_line`

**line 1088** — on `        body = line_text(item)`

> Line/Static types carry no syllable data


### `_covering`

**line 1155** — before `own = e`

> What the line sings on its own, before any ad-lib widens it. The clamp
> below may not cut into this.

**line 1170** — before `floor = own if isinstance(own, (int, float)) else None`

> ...but not so far that two lines are lit at once.
>
> Widening a line to hold its ad-libs and stopping there traded one visible
> fault for another: containment went perfect and a quarter of the lines
> began overlapping the next, which is the fault a reader actually notices.
> So the line reaches as far as it must and no further than the next line's
> start. What is being cut is an ad-lib's END, which was mostly the hold
> rather than a measurement -- and a line that has to be truncated here is
> really telling you its ad-lib is mistimed, which is a different bug.
>
> ONLY the ad-lib's end. That is what this always said it did, and not
> what it did: `e` is the widened end, and where nothing had widened it,
> the line's own singing was cut instead. A duet answering before the
> other singer has finished -- two voices overlapping on purpose, which
> is the whole point of two agents -- came out of a save with its <p>
> ending where the answer began, and the rest of the line outside the
> element that carries it. Hence `own`: the clamp may take back the hold
> an ad-lib added and no more.


### `render_ttml`

**line 1239** — on `        nxt = items[n] if n < len(items) else None`

> n is 1-based


### `render`

**line 1300** — before `return render_ttml(body, True)`

> x-bg is how TTML natively carries backing vocals -- always emit them,
> unlike the text/lrc formats where they are an opt-in inline annotation.

**line 1304** — before `items = next(`

> synced types (Syllable/Line) use "Content"; unsynced "Static" uses "Lines"


### `main`

**line 1448** — on `                pos -= a.offset`

> positive offset shows lines later

**line 1457** — before `head += "(not cached yet -- waiting)"`

> Spicy Lyrics writes the cache only after it fetches a
> song, so a just-started track is often not there yet.
> Keep re-checking instead of going silent for the song.

**line 1506** — before `while region and region[0] not in cur:`

> live region = every currently-sounding line, redrawn in place.
> Lines that stop sounding drop out of the region and stay on
> screen above it as history.
