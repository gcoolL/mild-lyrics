# `aligner/spicy_lyrics.py`

Comments lifted out of `aligner/spicy_lyrics.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

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


## `syllabify`

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


## module level

**line 447** — before `CJK = re.compile(r"[぀-ヿ⺀-⿟㐀-䶿一-鿿]")`

> kana, radicals/compat forms, ext-A, unified

**line 464** — on `SOKUON = re.compile(r"[っッ]\s*$")`

> small tsu, っ / ッ

**line 491** — before `PARTICLES = {"は": "wa", "へ": "e", "を": "o"}`

> Standalone particles are written one way and read another. Romanising them
> per-character gives "watashi ha" / "kimi wo", which is simply wrong.

**line 512** — before `TRAILING_KANA = "っゃゅょぁぃぅぇぉゎーッャュョァィゥェォヮ"`

> kana that never begin a mora: they lean on the character before them


## `line_readings`

**line 542** — on `    owner = [-1] * len(texts)`

> which romanizer word each syllable fell in

**line 583** — before `if stripped in PARTICLES and (i or stripped != "は"):`

> a syllable that is nothing but は/へ/を is the particle, not the kana


## `furigana`

**line 645** — before `touched = [i for i, (x, y) in enumerate(spans) if x < hi and y > lo]`

> A reading can straddle two timed pieces, since the syllable split and
> the word split are different things. Divide it by character share
> rather than dropping it or hanging it off one side.


## `geminate`

**line 686** — on `        return None`

> gemination before a vowel is not a thing

**line 689** — on `        head = head[1:]`

> already doubled on the far side


## module level

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


## `timeline.syls_of`

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


## `timeline.roman_of`

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


## `timeline`

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


## `focus_index`

**line 935** — on `    while moved:`

> walk out to the outermost container


## `active_index`

**line 957** — on `                return idx`

> still in the gap after this line


## module level

**line 975** — before `# --------------------------------------------------------------------------`

> formatting


## `syllables_text`

**line 1019** — before `out += text if s.get("IsPartOfWord") else _trim(text) + " "`

> Both edges: a leading space doubles the gap just as a trailing one
> does, and the piece before it has already ended its word.


## `line_text`

**line 1042** — before `text = (text + " " + " ".join(f"({p})" for p in parts)).strip()`

> One pair of brackets per GROUP, not one pair around all of them.
> Two answering voices written apart -- "(Baow) (What the fuck are
> you doing, Toxi?)" -- came back as "(Baow What the fuck are you
> doing, Toxi?)", which is every word in the wrong shape and reads
> as one long ad-lib rather than two short ones.


## `syllable_group`

**line 1073** — before `out.append(tag + s.get("Text", "") + ("" if s.get("IsPartOfWord") else " "))`

> IsPartOfWord means "joins the next syllable with no space"


## `elrc_line`

**line 1088** — on `        body = line_text(item)`

> Line/Static types carry no syllable data


## `_covering`

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


## `render_ttml`

**line 1239** — on `        nxt = items[n] if n < len(items) else None`

> n is 1-based


## `render`

**line 1300** — before `return render_ttml(body, True)`

> x-bg is how TTML natively carries backing vocals -- always emit them,
> unlike the text/lrc formats where they are an opt-in inline annotation.

**line 1304** — before `items = next(`

> synced types (Syllable/Line) use "Content"; unsynced "Static" uses "Lines"


## `main`

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
