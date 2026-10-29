# `mild-lyrics/lyric_sources.py`

Comments lifted out of `mild-lyrics/lyric_sources.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).

## 2026-10-25 — the card is taken from the plain title

`_apple_song` ranks the rows twice (`_ranked`). The ISRCs and writers come from every row as before. The card comes from `_untagged(reads)`: in each storefront's answer, only the rows titled exactly as asked, when there are any. A tagged version ("Eternity (Orchestral Version)", "Cool Kids (RAC Mix)", "numb [slow + reverb]") passes `_same_song`. When the upload runs long, its length can land within NEAR of that upload while the plain cut falls into `loose`, and so the tagged one became the card and set `card_len`. Replayed offline on the Apple rows of 484 played songs whose stream matches a release within 2s (upload padded +0/+10/+20/+40s): right 484/468/467/476 before, 483/474/474/477 after. The one lost is "Disco Night", whose cut played is itself a tagged version. The ISRCs keep the tagged rows, because a tagged cut that is actually playing still needs its lyrics found by ISRC. closed.md, "The card's length is the earliest pressing's", has the earlier measurement.

## 2026-10-24 — one reader for word-stamped lines; one place for the app's folders

**KRC / QRC / YRC.** `_ne_yrc`, `_krc_items` and `_qrc_items` were three copies of one loop, and lyric_formats had a fourth set of readers for the same formats on disk. They now share `_stamped_rows` (a line's words read *between* the stamps, `_words_between`) and `_stamped_items` (credits, lead/backing split); lyric_formats reads files through `_stamped_rows` too. The between-the-stamps reading had only reached QQ and lyric_formats: NetEase's old token pattern `\((\d+),(\d+),\d+\)([^(]*)` dropped any word starting with "(" -- `(1300,300,0)(hey)` lost the ad-lib, and a run of them left orphans like "hah)" in the lead. Measured on every TTML in lyrics/ written out as YRC and read back: the sources' reader agreed with the file reader on 34 of 115 songs before and 114 after (the one left is "La même", where the credit filter, sources only, drops a "… :" line). KRC and QRC output was identical before and after.

**cache_root / config_root** are now the only copy: `lyrics_gui.app_dir` and doctor's `log_dir` ask them. The rule, as it stood in app_dir: Windows has no XDG, and a config file under ~/.config there is somewhere no installer, backup or uninstaller looks -- Roaming for settings, Local for the cache, Windows' own division and the same one XDG draws. macOS draws it under ~/Library: Application Support is backed up and carried to a new machine, Caches is not. XDG_* is still honoured where set. A Mac that already has ~/.config/mild-lyrics (or ~/.cache) from before Macs were supported keeps using it rather than starting over; moving it is not this code's job, since people copy the folder between machines and run it from a stick. (plugins' `_config_base` is a different question -- the platform's config folder, for permission grants -- and stays.)

## 2026-10-24 — LUV U NEED U's "Okay (oh-ooh)", and the base's line end on QQ

**"Okay (oh-ooh)".** The to-do said this line was lit for a tenth of a second (37.84-37.95) in the NetEase blends. That came from a record built 10-15, before the 10-16 fixes. Rebuilt from today's code with the fixture's Musixmatch base and NetEase, Kuwo, QQ and Kugou fetched again (Apple has no copy; LRCLIB answered 503), no blend did that. Every blend still had a fault, though. The line got no words, and the donor's sung "Okay" was drawn as a background ad-lib under it. Kuwo times "Okay" 37.92-38.64, and QQ/Kugou time it 38.10-39.38. `_relay` refused to cut "Okay (oh-ooh)" along the one syllable "Okay" because 4 of 9 letters is under `RELAY_LIKE`. The donor line stayed unclaimed, and `_lift_strays` filed it as a shout, since "okay" is in `CRIES`. With two or more donor syllables, the same kind of trailing bracket already passes and rides on the last word as a `Guess` ("Hello there (yes)").

`_relay` is now a wrapper around `_cut_along`, which is the old `_relay`. When the whole line fails, it tries the line without a trailing bracket (`TAIL_ASIDE`) and appends the bracket to the last word, and `_unlump` cuts that into a guess. `kwblend`/`kwtriblend` now give `Okay` 37.92-38.16 and `(oh-ooh)` 38.16-38.64, with no background copy. The QQ and Kugou blends are unchanged. Neither `_pair` nor `_restream` ever offers QQ's lone "Okay" to that line, so `_relay` is never asked. tests: test_blends 191, test_one_owner 9.

**The base's line end on a QQ document: refused.** The idea was that where a blend stands down to a QQ, Kuwo or Kugou document (60 cached songs, 21 with a held last word), the base's line end would cut the last syllable by the blend's own rule: `BLEND_TAIL` clear of the next base line, more than `BLEND_HOLD` past, never into the words. It was measured on 50 of the hand-timed files in ./lyrics, with QQ and Apple (lrc.red) asked once each. Late in the run both answered nothing even for "In the End", which looked like a rate limit. 17 songs had both. Of their lines, 29 fired with the reference timing the same last word on QQ's clock:

    lines                          n   |end err| median QQ / cut   mean QQ / cut   cut better / worse
    all that fire                 29         0.239 / 0.159          0.240 / 0.255        15 / 14
    held > 3x the line's median   16         0.181 / 0.282          0.234 / 0.356         6 / 10
    QQ's word ends <0.3s before
      its next line               10         0.215 / 0.453          0.243 / 0.403         2 / 8

The cut helps where QQ was not stretched (Ado's "Fallible", held at the line's own pace) and hurts on exactly the held words it was meant for. Apple's line end there comes before the hand-timed end: BIRDBRAIN's "stop" (-0.64s), Wishes' "chest" (-1.31s). Not built. Scripts: the session's scratchpad (`measure_ends.py`, `ends/docs.json`), not kept.

## 2026-10-22 — Wrong-song lyrics from QQ/Kuwo, and the DJ note

Broken (AK, 216s, US3DF1944903) showed "Don't wanna give you promises that I can't keep" as `kwblend`. The real song opens "You don't know what you did to me" (Spicy, LRCLIB). Kuwo's search has the right title, artist, album and length (MUSIC_68789764), but the lyric filed under it is another song's, and QQ files the same one. No search rule can see that. The blend could: `_pair` found no shared lines, so the blend had nothing to lay on Apple's lines. Then `stand_down` handed over the donor's own word-timed document, because it outranked the line-timed base. The plain `qq`/`kuwo` answers would have won the same way.

`other_song` compares the documents' consecutive word pairs (a CJK character counts as a word). A document is another song when under `STRAY_SHARE` (0.2) of the smaller set is shared. Measured over the cache, with Spicy's document as the reference for 109 answers whose words were a CJK maker's: same-song answers scored ≥ 0.31 (most ≥ 0.7, one odd one at 0.31 with a credits line), and wrong ones ≤ 0.13. Random pairings of different songs (545) topped out at 0.23. `_pair` is too strict for this: it rejected 45 of the 109, many of them the same song split into lines differently.

It is used three times. `stand_down` no longer hands over a donor that is another song than the base. In `_walk`, an answer whose words are QQ's, Kugou's, Kuwo's or NetEase's (the source itself, or a blend that stood down to one) is dropped when it is another song than the reference: Spicy's document, else the first base in hand (Apple, LRCLIB, Musixmatch, Genius). The same test applies to the early on-screen answer and to a cached record, so records that were already wrong are walked again. Fewer than `STRAY_MIN` (8) word pairs on either side means it is not judged. Mostly-CJK against mostly-Latin is judged only when the reference is Spicy's, because a base from LRCLIB or Genius can be romaji of the right song. With no reference at all, nothing changes.

The cache held 12 such answers besides Broken, all now cut: Korean or Chinese songs under English ones (Turn off the lights → a 邓典果DDG song), an English version under the Japanese original, I'm an alien → The End Is Where We Begin, and similar. None of the other 97 was cut.

Kuwo answers a DJ track with one line, 此歌曲为DJ歌曲，请您欣赏. `NO_WORDS` had 请欣赏, which 请您欣赏 does not contain, and nothing for DJ歌曲. It now reads both.

## 2026-10-22 — lrc.red's revamp, and Another Love

Another Love (Tom Odell) had no Apple sync through either door. Apple's search names the album cut GBARL1300522, and lrc.red lacks that code. lrc.red files the song as GBARL1300299 (Long Way Down, line) and GBARL1300107 (the EP, word, 244.36s against 244.09s). `_lrcred_fetch` only searched lrc.red when Apple named no code at all. Now, when the codes in hand give no hand word sync, it asks `search.json` and tries up to three more codes. Hits must match the title, any artist and the length. The nearest length goes first. Where Apple's code has the words, no search is made.

BiniLyrics is now lrc.red's own backend. `lyrics-api.binimum.org` answers 307 to `lrc.red/api/v1` (`"source": "HIT-LRC-RED"`). Its name query also missed, because the album was sent and "Long Way Down (Deluxe)" does not match "Long Way Down" (`MISS-LRC-RED`). The album is no longer sent, and rows are still checked by title and length.

The revamped site documents `/s/{isrc}.json` (metadata only, `sync` is the file's level) and `/s/{isrc}.ttml`. `.song.json` is gone from the docs but still answers, and it is the only place `byModel` appears. bloom's `.json` says `sync: "word"` with no model mark. So the fetch stays on `.song.json`, which is also one request instead of two. If it goes away, the tell left is `/api/v1`'s `timing_type` (Apple's level, "line" for bloom) set against the file's. The API terms ask for a User-Agent with a link and contact email, and a credit linking to lrc.red. Requests to lrc.red and binimum.org (`BINI_HOSTS`) now send `LRCRED_UA`, with the repo link and the address the user gave. Every other source keeps `UA`.

## 2026-10-22 — Syncs: no QQ/Kuwo line entries, and unsynced ("@u") entries

At the user's word, QQ and Kuwo lose their "@l" entries (Kugou never had one), since they do not give line syncs. NetEase keeps its. A line answer from either would no longer match an entry: it cannot be switched off, and in a custom order it sits after the listed entries.

Unsynced answers (`quality` "static") are now entries too, listed last: Spicy, Apple, Unison, NetEase, LRCLIB (`plainLyrics`), Musixmatch (`lyrics_body`) and Genius. Each of these has a code path that builds a Static document. Genius, with only "@u", now loses its plain Sources row in the extended list like everyone else. Saved orders drop the gone entries and append the new ones (`sync_custom`), so a custom order's `syncs_key` changes once and those songs walk again. Test: tests/test_syncs.py.

That append never worked: it read `self.sync_entries()`, which is the saved order itself, so nothing was ever added. With the "@u" entries the drawer had 24 `sync_slot` rows for 17 entries. `menu_value` fell through to `getattr(self, "sync_slot17")`, and the paint died there, taking every Sources row after it. The append now reads `LS.sync_entries(self.src_order)`, and `DRAWER_WHEN` hides any slot with no entry. Checked offscreen with a copy of the user's gui.json: 24 entries, Lookups and People drawn, no faults.

## 2026-10-19 — Syncs: each source's word and line syncs, on or off and in order

Settings ▸ Sources ▸ Syncs lists "source@w" / "source@l" entries (`SRC_SYNCS` says which a source can give). The player hands them over with `set_syncs(off, order)`, like `set_bases`.
- Off: an answer whose `sync_entry` is off is refused everywhere the walk accepts one (lead round, `landed`, the final pick) and in the player's Spicy step. Blends and untimed answers are not in the list.
- Order: only between answers timed alike (`sync_place`; quality still outranks order). Left alone (`SYNC_ORDER` empty) the walk's own order decides, as before. `ahead_of` gives the providers above Spicy for the quality Spicy answered with.
- The stored answer remembers `syncs_key()` ("" while untouched, so older records stay good).
- Replaces Timing ▸ NetEase word sync: the graft runs while "NetEase · word-by-word" is on.
Test: tests/test_syncs.py.

## 2026-10-18 — re-cuts held to the donor's clock (`_on_clock`), and stand-downs for lines with no start

An audit of 36 random cached blends against their donors, which were fetched again, found two blends broken outright. Both still came out the same when rebuilt with the 1.1.91 code.

**I Can Be (Mike Ault, Crysta), kwtriblend.** The outro alternates "I can be, I can be" and "Anything you want and need" eight times in Apple's copy. NetEase and Kuwo each merge every pair into one line, and they repeat it a different number of times. `_timely` correctly dropped every outro pairing. `_restream` then filled the holes from its whole-song letter alignment, which has no idea of time. In a run of identical letters, difflib's longest-block-first matching skipped repeats. The re-cut put NetEase's lines from −12.1 s to +12.8 s away from Apple's (the song is otherwise steady at −0.5 to +0.6), and Kuwo's slipped by +28 s after line 43. The blend came out with lines out of order (177.85, 176.30, 209.78, 181.39…), "Ohhh@205.84 I@213.67" stretched over 12 s, and two lines untimed that both donors time.

`_on_clock` now sits between `_restream` and its two callers in `_blend`, the lead donor's and the filler's. It works in four steps.

- **The clock.** Every paired or re-cut line gives an offset from the base. `_steady_run` finds the longest run of lines, in order, whose offset changes by `CLOCK_STEP` (1.5 s) at most from one kept line to the next. Real jitter between neighbours reached 1.04 s (I Can Be, lines 18 and 19). A slip onto another repeat moves by 2 s or more.
- **No clock, no judging.** If that run covers less than `CLOCK_SHARE` (0.7) of the lines, the re-cut is handed back untouched. The share was 0.17 on Have Fun (Rameses B), where Apple and NetEase lay the song out differently, and 0.33 / 0.68 on Hymn For The Missing / What You Wanted. On every song the gate helped it was 0.75 or more. Without this, Have Fun got 30 moved words and four more lines out of order.
- **Dropped.** A re-cut line off the run is dropped, unless it is said once with both neighbours on the clock. That case is Apple's stamp wobbling, not a slip. A re-cut that fails `_relay` at `RECUT_LIKE`, or `_fits` its room, is replaced only if a local re-cut is found. Dropping it outright changed `_drift`'s neighbours on Opp Stoppa: QQ's "Ayy" relays nothing, yet it was the neighbour keeping line 1's drift at 0.33 rather than 0.54, and without it NetEase's bunched intro won over QQ's.
- **Re-cut locally.** Each hole is aligned only against the donor's free syllables within `BLEND_JUMP` of where the median of the six nearest kept offsets puts the line. The match has to find the line's opening (a lead-in of up to a quarter of the line may go unmatched, as with "Ohhh"), start within `BLEND_JUMP` of that place, fit, and score `RELAY_LIKE` on its letters. Before the opening rule, NetEase's "you" got relayed as "Anything".

**Encore Dance (MIMI, Kasane Teto), triblend.** Apple's copy is unsynced, and NetEase's is line-timed with two of Apple's lines to each of its own. Text pairing found the unsplit lines only, so 16 of 35 lines had no start at all. `_thinner` counted word-timed lines, 0 for both sides, so the blend never stood down. It now also compares the share of lines with a start. The blend has 19/35 against NetEase's 27/27, so it stands down to NetEase.

Measured offline over the same 36 songs, with the bases fetched once and the donors from the audit's jar, HEAD against the change:

    lines with no start   16 -> 0      lines out of order   7 -> 4
    overlapping lines     18 -> 13     word starts no donor has   130 -> 114
    guessed words        128 -> 124    word-timed lines   1374 -> 1374

Songs that changed: I Can Be (in order, two lines untimed where neither donor writes Apple's "I can be, I can be"), Encore Dance, Brand New Numb ("Enemy, enemy" now Kuwo's 77.48/78.28, from times neither donor had), I Should Have Stayed at Home (a line crushed into 0.9 s with five guessed words is untimed now; its ba-da is the line before's), and Come and Get Your Love (a "La…" line now on NetEase's own syllables, 0.46 s before Apple's stamp, where QQ was 0.33 s after it). The other 31 are unchanged.

Still open from the audit, live in 1.1.91:
- Stitches: NetEase's "Needle and the thread" is drawn over Apple's untimed "(Bleed over my…"; Kuwo lines are moved up to 1.9 s by `rhythm`.
- Redbone: "Hail, oh, yeah" is drawn twice.
- Light It Up: "drug, raise a cup" is guessed into 0.12 s where QQ has it.
- Opp Stoppa: QQ's asterisks stop "pussy" matching.
- LUV U NEED U: "I" is crushed to 40 ms where Kuwo has the base's phrasing.

**Hurricane (Panic! At The Disco), the graft.** The pick was NetEase, word-timed. Spicy, ranked above it, held Apple's line sync, so the player grafts NetEase's syllables onto Apple's lines (`graft_syllables`). Five of the 57 stayed line-synced.

- **The extra word.** "When you shoot, I think I'd duck" didn't pair with NetEase's "And when you shoot…". `_near_pairs` refuses a key contained in the other (its `_fragment` guard, which is right for "Caught in the middle" against "Two faced, caught in the middle").
- **The split.** Apple writes "We said, no more war, no more clothes / Give me peace" where NetEase writes "We said, 'No more war! / No more clothes! Give me peace!", twice. That is two lines against two cut at another word, which `_regroup` (one against several only) doesn't cover.

The graft now ends as the blends do. Lines still bare take the donor's stream cut at our breaks (`_on_clock(_restream(...))`), relayed at `RECUT_LIKE`.

- **No whole-song pass needed.** The local re-cut also runs when `_restream` refuses the whole song (`or [None] * len(bit)`). Most graft songs fail its 0.8 letter ratio, at 0.44–0.76, because Apple and NetEase cover different amounts of the song; the local window keeps that safe.
- **Echoes.** A bare line that is wholly a bracket may take a donor backing group whose span holds the clock's place for it. Conro's "(All I want)" is written as a line by Apple and as a backing group of the line before by NetEase.
- **Bracket letters.** In `_on_clock`, a line that `_unaside` empties falls back to its own letters.
- **Trimming.** Syllables already held by a placed line are trimmed from a re-cut before relaying (0.05 s tolerance, since NetEase ends one line exactly where the next starts).
- **Honesty (`sung`).** The first two words must start on donor onsets, fewer than a quarter of the words may be cut from another's syllable, and the line must `_fits` its room. Without this, `_relay` made up onsets by splitting a syllable: "And if it is," crushed into 40 ms steps, "(Gonna give it to you, boy)" squeezed into one syllable, "The" put on NetEase's "Madness", "Three shots, and why should I wait?" relayed over "and watch your weight".

Over the 45 cached songs where the graft applies (a Spicy line sync and a NetEase word sync), line-synced lines went 357 → 282. Overlaps (1) and lines out of order (1) are unchanged, and no line that already had words changed. The 75 newly timed lines start a median 0.12 s from Apple's stamps. 14 of their 412 words start mid-syllable, none of them first in a line. The two furthest were checked by hand and are right: NetEase's 127.47, where Apple's 130.25 breaks its neighbours' clock, and a split of NetEase's 130.16 line at Apple's "So just say after me" (133.10). Of the remaining bare lines, 9 have an unused NetEase line of the same words. Each is either more than 0.75 s from where the clock puts it, or NetEase has fewer repeats there (Good to Be Alive's outro).

The player's own shaping (`_shaped`) was checked over all 2,095 word-timed documents in the cache: it leaves no line untimed that had words. Over the 36 audit blends rebuilt with this code, one untimed line has an unused donor line of its words: Have Fun's "Oo-aah", where `CLOCK_SHARE` keeps `_on_clock` out.

Tests: `test_blends.py`, the three new sections at the end.

## 2026-10-17 — translations filed as lines (`_translations`)

Some uploads to Kuwo and Kugou write a Chinese translation as a line of its own after each sung line. Seen on Kabaaneko's Flower Man (English Version), Project Vela's Don't Feed the Dark and all2me. Kuwo's LRCX for Flower Man carries every translation twice. One copy is all `<0,0>`, which `_kuwo_krc` already drops. The other is word-timed into the gap before the next line ("十尺二寸的花少侠", 8 characters in 0.31s; others in 0.02s). Kugou's Don't Feed the Dark puts its translations in the same gaps. About half are squeezed like that. The other half fill the whole gap ("但一切都是徒劳", 5.5s), so a speed test alone misses them. The blends lifted them in as extra lines, and they were on the screen with pinyin under them.

`_translations` (run from `_furniture`, so QQ, Kuwo, Kugou and NetEase all get it) looks for the pattern, not single lines. A line counts as squeezed when it is in a different script from the line before it and goes by under `SQUEEZED` (60ms) a syllable. A line-timed one also counts when it shares its stamp with the line before it. With 3 or more squeezed lines, their script is taken as the translation's and their predecessors' script as the sung one. If at least a quarter of the sung→translation turns are squeezed, every line in the translation script that comes straight after a sung-script line is dropped. A real bilingual song is safe because nothing in it is squeezed. A lone squeezed ad-lib is safe because it is only one.

Measured over the cache. Per line, the squeeze test hit 5 songs once each on genuine lines ("Yeah, yeah, yeah, yeah, yeah" at 0.14s, a NetEase "(i have to get it all)"), which is why it is gated on the pattern. With the gate it flags 3 of 1232 stored picks: exactly those three songs, exactly half their lines (34/68, 36/72, 43/86). It flags 0 of 2350 Spicy records. At the doors, the three come back as 36, 36 and 43 lines with no Chinese left. `_cached` hands back nothing for a CJK-sourced record that still has the pattern, so the three already stored are walked again the next time they play.

## 2026-10-16 — one owner per donor syllable (`_one_owner`), and strays on their own clock

LUV U NEED U (Slushii) drew 10 overlapping lines in `neblend`, `triblend` and `kutriblend`. Every source alone had none: Kugou, NetEase, QQ and Kuwo all had 0. The base (Musixmatch here, Apple on the desktop) ends a line with "I do". NetEase sings it at the head of the next line ("I do need you, need you"). The base line without a pairing got a `_restream` re-cut, which took that "I do", rightly. The next base line was paired with the same NetEase line and relayed its "I" as its own first word. One syllable timed two lines, and the second line's own "I do" was crushed into its last 60ms.

`_one_owner` now moves a paired line onto its own re-cut when a re-cut line already holds some of its donor syllables. It only does so where the re-cut times at least as many of the line's words and sits no more than `OWNER_SLACK` (0.5s) further from the base line's own span. Both conditions came from the evaluation. On word count alone, Zoutelande lost five words from a line whose re-cut covered half of it. On count plus "nearer", Ice Ice Baby took a re-cut one chorus repetition (4s) late, and LUV kept two overlaps where the re-cut was 0.14 and 0.44s further than the pairing.

The other two overlaps were the intro "Oh, oh, oh-oh…" line. Its re-cut matched none of its words, but its `qby` (+5.38s) still slid a stray NetEase "O-o-oo-o" onto it, and the stray then stretched the line over "Okay". Now `slid` is recorded only for a line whose words were relayed from the donor, and `_lift_strays` no longer extends a host line past the next line's start. The ad-lib itself is still drawn in full as a background.

Measured with `eval_blends.py` over 104 hand-timed songs (Spicy kept out of the donors; `blend`, `kublend`, `neblend`, `triblend`, `kutriblend`), no song worse on any count:

    overlapping lines   484 -> 471      lines out of order   16 -> 14
    drawn twice         blend 25 -> 19, kublend 20 -> 17, neblend 19 -> 16,
                        triblend 20 -> 18, kutriblend 19 -> 17
    onsets >0.5s out    SpongeBob 14.3% -> 3.6%, Toxicity 8.9 -> 8.0 (+3 lines worded),
                        DYSTOPIA 7.8 -> 7.2 (+4), Chasing Clouds 28.9 -> 28.3

`tracks.json`, which `eval_blends.songs` reads, no longer exists, so the run used a scratch cache root with a list rebuilt from the reference filenames and the Apple card's length. See TODO.md. Test: `tests/test_one_owner.py`, with the two real documents in `tests/fixtures/`.

## 2026-10-15 — `_steadiest` stays inside its run of blends

YOASOBI's あの夢をなぞって, with Apple Music switched off, went to `kwblend` (Musixmatch + Kuwo) even though NetEase was ranked above Kuwo. With Apple off (BASE_SHUT), every blend takes Musixmatch's lines. All nine answers were word-timed, so the tie-breakers decided. On those lines, NetEase's blends measured `_steady` 0.14 and Kuwo's 0.12. The 0.02 gap cleared `BLEND_PICK` (0.015), and `_steadiest` moved kwblend to index 0, past the four NetEase blends and past plain `netease` as well.

There were two changes:

- **Each run is reordered on its own.** The reorder now applies within each run of consecutive blends, so a blend never passes a source that is not one. The old test expected `neblend` to jump over `bini`, and it now expects the opposite.
- **The margin scales.** It is now `max(BLEND_PICK, BLEND_PICK_SHARE × the first measured blend's _steady)`, with a share of 0.2. At or below 0.075 the margin is the 0.015 that was calibrated. With Apple's lines this song measured 0.049–0.051, so those calibrated flips should be untouched, but the share itself is not measured against hand-timed files. At 0.14 the margin is 0.028, so 0.02 is left to the order.

Either change alone puts NetEase back on this song: kwblend sits below plain `netease`, and 0.02 at 0.14 no longer clears the margin.

## 2026-10-15 — lrc.red's model syncs

bloom (Fox Haynes, QZZ782503620) was word-synced through BiniLyrics but not lrc.red. lrc.red had it, marked `byModel: true`, and `from_lrcred` passed those over. BiniLyrics had no file of its own for the code (lyrics-storage.binimum.org 404). Its row's `lyricsUrl` is lrc.red's `/s/<ISRC>.ttml`, byte-identical to the song.json `source`. So the BiniLyrics door was reaching the same model sync and labelling it Apple's.

How the two say which is which: lrc.red only in song.json, as `byModel: true`, absent on Apple's own. The TTML is the same either way (`lrc:timing="Word"`, `lyrics.sync`/`timing` both "word", `meta` empty). The one weak tell is that the model's lines have no `part` (Verse/Chorus), which Apple's carry. BiniLyrics' `timing_type` stays at Apple's own level ("line" for bloom) while the linked file is word-timed. Heathens, hand-timed, reads `timing_type: "word"` and has no `byModel`.

Model syncs are now a source of their own, `lrcmodel` ("lrc.red (model)", `src_lrcmodel`, on by default). Its default slot in SOURCES is behind Kuwo, so `carried` puts it there in older saved orders. That is below every hand-timed word source, while it still beats a hand line sync on quality. It shares lrc.red's song.json request with the Apple door (`_lrcred_songs`, memoised).

Apple Music is lrc.red first, then BiniLyrics, never both. Any lrc.red document of Apple's own, line-timed included, ends the source. Where lrc.red has the song only as its model's, BiniLyrics is not asked either, since its row would only link that file. BiniLyrics is asked only where lrc.red has no song at all, and a model file it links (a line row over a word file) is refused there. Adding the provider changes every stored record's `names`, so each song walks again once; the old record still stands in meanwhile.

Blends keep Apple's lines on these songs. Where Apple Music has no sync of its own, `_bases` takes the model sync as the Apple base through `_starts_only`. That keeps Apple's words and each line's start, and drops the word timing and the model's line ends, which run well off. Each line ends at the next start, capped at 10s, and the last at start + 6s, the way `parse_lrc` ends LRC lines. It takes the model sync from `above` where the walk already has it. Otherwise it asks `from_lrcred_model`, which costs no request after the Apple door, since both share `_lrcred_songs`. With Apple Music switched off (BASE_SHUT), only a model sync already in hand is used. On bloom itself no donor (NetEase, QQ, Kugou, Kuwo) has the song, so no blend can be built there and the walk settles on `lrcmodel`.

## 2026-10-14 — a failed source is not a source with nothing

Heathens (Spicy Lyrics off) showed something less than lrc.red's word sync until a reload, and a reload found it at once. A walk stored its pick with `names` (every provider asked), and a provider that timed out or errored had simply left no document. The next load read the record back as settled because the same providers had been asked. Only a forced reload walked again. That was reproduced by failing lrc.red once: LRCLIB's line sync stayed through every later load.

The walk now stores `missed`, the providers it filed a fault against, and `_settled` refuses to reuse a record that one of them could beat. The record is still used as the stand-in (`stored`) while the fresh walk runs. It stays final only when its pick is word-timed and every missed provider ranks below it. A host still backing off after a 429/503 used to answer None without a word, which looked the same as having nothing. `_get`, `_ne_get`, `_amp` and the Musixmatch call now file "asked to wait" for it, so it also gets the hourly "could not reach" toast.

## 2026-10-13 — Kuwo

Kuwo, Kugou and QQ Music all belong to Tencent Music, and Kuwo's word timing is mostly QQ's own. Over 16 correctly matched songs (CJK and English), Kuwo's syllable onsets were identical to QQ's to the millisecond on 12 of the 14 both had. They matched Kugou exactly on 9 of 17. Where Kugou and QQ disagreed (光年之外, 江南, 倔强, bad guy, drivers license), Kuwo sided with QQ every time. On Dynamite it sided with Kugou, because QQ adds ten ad-lib lines of its own.

Against the Spicy Lyrics references held on disk (28 songs, 24 community syncs and 4 Apple), on the 17 that Kuwo, Kugou and QQ all answered, the median scatter after removing each song's offset was Kuwo 0.067s, QQ 0.070s and Kugou 0.093s. NetEase beat all three: 0.052s against QQ's 0.086s on the 19 it shared with QQ, with 86% of words within 150ms against 54%. The Tencent sources mostly run 0.1–0.2s late. So Kuwo is added for coverage, not timing: it answered 夜に駆ける, Lemon and 밤편지, where QQ had nothing. It ranks just below QQ in SOURCES.

**Blends.** Kuwo has the same two blends as QQ and Kugou: `kwblend` (Apple+Kuwo, `blend_kuwo`) and `kwtriblend` (Apple+NetEase+Kuwo, with Kuwo filling NetEase's gaps, `blend_ne_kuwo`). Being QQ's numbers, they are another way in rather than a second opinion. Measured against Spicy references on 10 songs, Apple+Kuwo had the same median scatter as Apple+QQ (0.070s), against Apple+Kugou's 0.085s. On the 5 songs where NetEase answered and the three-ways could run, Apple+NetEase+Kuwo tied with Apple+NetEase+QQ (0.059s); Apple+NetEase+Kugou was 0.062s. Each sits where `blend_rank` puts it, so with Kuwo below QQ both come just behind their QQ counterparts.

**Format.** Search is `search.kuwo.cn/r.s`. Send the full client parameter set: with only `ft/rformat/vermerge/mobi`, the studio 晴天 drops out of the top ten behind its KTV backing track. The lyric is `newlyric.kuwo.cn/newlyric.lrc?<base64(query XOR "yeelion")>` with `lrcx=1`. The answer is a text header, a blank line, then zlib. Inside the zlib is base64 and XOR again, and then gb18030 text; that holds for word-timed answers and plain ones alike. LRCX writes `[mm:ss.mmm]` and then `<a,b>word` pairs. With `k` the `[kuwo:NNN]` value read as octal, a word's offset from the line start is |a+b| / 2(k // 10) ms and its length is |a−b| / 2(k % 10) ms. That is KRC with different arithmetic, so `_kuwo_krc` rewrites it as KRC, and `_krc_items` / `_qq_head` / `_furniture` handle the title card, credits and speaker labels unchanged.

**Translations.** Foreign-language songs have a Chinese translation after every line: every token is `<0,0>`, and the line is stamped where the next line starts. Recent ones open with 以下歌词翻译由文曲大模型提供 ("translation by the Wenqu model"). Both are dropped.

**Line sync.** The format allows plain LRC: the header says `lrcx=0`, and asking without `lrcx=1` returns `[mm:ss.xx]` lines. In practice, none of the roughly 230 recordings probed had line timing without word timing. Every `lrcx=0` answer was either unsynced text with every line on one stamp (wifiskeleton's "famous", stamped 02:42.00 throughout) or an instrumental note (此歌曲为没有填词的纯音乐). `_kuwo_doc` sends anything without `<a,b>` pairs through `parse_lrc`. Real line timing would come out as a Line document, one stamp as Static, and the note is caught by `_instrumental`.

**Matching.** As in `_qq_hits`, title, byline and length must all agree. On top of that, Kuwo's Chinese version markers (伴奏, 片段, 现场, 翻唱, DJ版) count as another cut. An exact title, then a byline with nobody we didn't ask for, outrank a nearer length: Kuwo files the 194s Justin Bieber remix of "bad guy" under the plain title, and the album cut there is 192s. A word-timed copy is preferred over a plain one among the first three hits.

## 2026-10-13 — native names for NetEase, QQ and Kugou

Spotify's English catalogue gives "New Genesis" by Ado for 新時代 and "TK from Ling tosite sigure" for TK from 凛として時雨. The Chinese catalogues file them under the native names, so the three missed both songs and only Musixmatch answered.

**native_names / _or_native.** Where a provider finds nothing, it is asked once more under the names Apple's storefront for the ISRC's country gives (JP→jp, KR→kr, TW→tw, HK→hk; `ISRC_HOME`). The row nearest the length is used. This costs one Apple request, once per track, only after a miss and only for names with no native script already. Measured: New Genesis now comes from NetEase, QQ and Kugou, and the walk ends on triblend instead of mxm.

**_billed_apart (QQ, Kugou).** Where the bylines are written in different scripts, an exact title within KRC_SLACK (2s) stands in for a shared artist. Ado's "unravel" cover, billed in the same script as ours, is still turned away.

**_same_song.** Titles equal once a bracketed tag is removed now match. 新時代 is three characters, below the four that containment needs, so 新時代 (ウタ from ONE PIECE FILM RED) never matched. `_same_cut` still keeps out the live cuts.

**_furniture card.** A " - " card whose title half matches ours exactly is dropped without the byline (Kugou writes "unravel - TK from 凛冽时雨"), and the card test also tries the title without its tag (QQ's "新時代- Ado").

## 2026-10-13 — NetEase: romanised titles, romalrc on its own clock

**_ne_rank, romanised title.** Spotify can show a Japanese title romanised ("Kawaikutegomen (feat. capi)") where NetEase files it in its own script (可愛くてごめん (feat. かぴ)). The two never compared equal, and with the durations 15s apart (204.5 vs 219.9) only the byline agreed. One signal out of three is not enough, so the song was never opened. Where ours is Latin and theirs needs romanising, `SL.reading(theirs)` is compared with our key (exact match only).

**_ne_roman_pairs, row for row.** That copy's romalrc is stamped on its own, between 0.5s early and 0.2s late against lrc, so the 0.05s pairing found 15 of 57 lines. Where the two files have the same number of rows, all within 1s of each other, they pair by position: 57/57.

## 2026-10-12 — NetEase romanisation, furniture

**romalrc is stamped to lrc, not yrc.** `_ne_roman_pairs` pairs it with lrc by its own timestamps, and `_ne_romanise` attaches it to items by text (nearest in time among repeats), falling back to time within 0.35s.

**_ne_borrow_roman.** The word-timed pressing NetEase prefers often ships no romalrc while a sibling pressing does: 怪物 (YOASOBI) 1893590233 has yrc and no romalrc, and 1803908863 has romalrc. The tied pressings already fetched lend theirs by text. Measured: 怪物 0/56 → 56/56. `netease_roman` now returns ordered pairs for `GR.fit_pairs`.

**BG_PAIRS.** 「」 quote a word the lead sings. Read as a backing vocal, 「異常」が胸を埋めつくして lost its head, and its romanisation could not find it (アブノーマリティ・ダンシンガール 48/55 → 55/55).

**_furniture.** Applied to Kugou, NetEase and QQ. It drops a "title - artist" card at the top (either order, matched by shape), credit and copyright runs within EDGE_REACH lines of either end (NE_CREDIT, plus CJK "role：", OP/SP/ISRC and 版权/未经…许可 notices), and section headers anywhere. A bracketed header is any of the listed words. An unbracketed one only counts for words that are never lyrics (Verse, Chorus, Bridge…): "Break" three times running is sung. Cached docs keep what they have until refetched.

**proxy_bypass cache (Windows).** With a system proxy set, urllib's bypass check calls socket.getfqdn on every request, which can take seconds. The answer is cached per host.

## Lift — 2026-10-25

Docstrings shortened in `mild-lyrics/lyric_sources.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> Every lyric provider: Spicy Lyrics, and the eleven for when it has nothing good.
>
> Spicy Lyrics (Community / Apple Music) is the source the app was built around,
> and its data is what every other feature (romanisation, furigana, Genius
> alignment) is tuned against, so it leads the running order by default. But a
> fair slice of any library comes back line-synced, unsynced, or missing
> entirely, and for those there is often better data elsewhere. This module goes
> and gets all of it.
>
> Spicy Lyrics is asked FIRST AND ALONE, and what it answers is what the rest
> have to beat -- see from_spicy and _walk's lead. That is not a courtesy to the
> source it leads with, it is what a track id is worth: Spicy Lyrics is the one
> provider here that can be asked about a song by its Spotify id rather than by
> title, artist and length, so it costs one request and cannot come back with
> the wrong song. It word-syncs most tracks, and on those the other eleven are
> never asked at all.
>
> The chain, in default order:
>
>     amll-ttml-db   word-by-word TTML, community-submitted, indexed by Spotify
>                    id among others. Same data model as Apple Music, so it drops
>                    straight in.
>     the blends     somebody else's within-line timing under Apple Music's
>                    lines. Two lookups rather than one, or three where a second
>                    donor is kept for the lines the first cannot place, so they
>                    are off unless asked for -- and they stand themselves down
>                    without spending anything where a source ranked in front of
>                    their donors already answered word-timed.
>     NetEase        word-level `yrc` where it has it, and -- uniquely here -- a
>                    human-written romanisation on the same clock as the lyrics.
>     Kugou          word-timed KRC, and the Chinese catalogue the English
>                    sources here are worst at.
>     QQ Music       word-timed QRC from QQ itself, its lines as well as its
>                    timings. Worth having beside the blends because it writes
>                    ad-libs Apple has not written at all.
>     Kuwo           word-timed LRCX: on most songs QQ's exact numbers, through
>                    a door that fails apart from QQ's. Unsynced text where it
>                    has no timing.
>     lrc.red model  lrc.red's in-house model word sync of songs Apple only
>                    line-timed. Below every hand-timed word source by default.
>     LRCLIB        huge, open, no key needed -- but line-level LRC only, so
>                    it only ever wins a song nobody word-timed.
>     Musixmatch     its own app endpoint, which is the difference between a
>                    word-timed document and a line-timed one; see _musixmatch.
>                    Below LRCLIB, which costs it nothing where it is word-timed
>                    -- quality outranks order -- and settles the songs where
>                    both of them came back as lines; see SOURCES.
>
> NetEase and Kugou lead QQ Music because that ranking is also what picks the
> blend, and the ones built on NetEase measure better; see SOURCES.
>
> The order is the caller's to set, Spicy Lyrics included; see fallback(). What
> the order cannot do is trade quality away -- a source ranked first still only
> wins against an equal or worse document, never by replacing word timing with
> line timing. The one other thing that overrules it is a document that is
> missing a whole section of the song, which no ranking asked for; see
> _fullest. Being longer than everybody else is not that, and reading it that
> way is how Musixmatch used to win from the bottom of the list.
>
> A source that could not be reached is not a source that had nothing, and the
> difference is the user's: fallback() hands back what went wrong, so the
> window can say which catalogue the order asked for and did not get.
>
> Everything is converted to the shape spicy_lyrics.timeline() already eats, so
> nothing downstream needs to know where a song came from.
>
> The answers are kept on disk, two ways and for two questions. A record under
> `sources` is what a WALK decided, read back only by a walk asking the same
> question of the same providers; a record under `spicy` is one catalogue's
> answer about one track, and is also the only list of songs this program can
> offer, since that API answers about a track and does not enumerate. Both age
> by the same rule and sweep() clears both.

### `quality`

**line 132** — from the docstring, `def quality(body) -> str:`

> What we actually have, judged by the data rather than the Type field.
>
> A document can claim "Syllable" and carry no timed syllables at all, and a
> "Line" one is useless if none of its lines got a StartTime, so this looks.
>
> MOST of the lines, though, not one of them. Apple ships line-synced TTML
> that carries a single timed <span>: the one line with a backing vocal on
> it, whose lead has to be wrapped in a span so the x-bg can hang off it.
> Read as word timing, that is a 38-line document declaring itself
> word-synced on the strength of line 36 -- Three Days Grace's "Never Too
> Late" through BiniLyrics is the case. It said "word-synced" under the
> lyrics, it left the other 37 lines to light in one lump, and it stood
> every blend on the track down (see _outdone), which is the one thing that
> would have given those lines their words.

### `_walking`

**line 160** — from the docstring, `def _walking() -> bool:`

> Whether this thread's walk is still wanted. True where nobody said.
>
> A caller that passes no `alive` gets what it always got: a walk that
> finishes what it started. The predicate is somebody else's and is called
> from every provider thread, so it is never allowed to decide the question
> by raising.

### `_latched`

**line 172** — from the docstring, `def _latched(alive):`

> A walk's cancel token, made final.
>
> Callers spell "does anybody still want this?" as a question about the
> state of this moment, and the state of this moment comes back. The
> fetcher asks whether the slot still holds the track it is walking for;
> the look-ahead asks whether the slot is empty at all. Both can answer no
> and then, a moment later, answer yes again -- the fetcher's own loop
> takes the wanted id OFF the slot before it starts loading it, so a track
> change is a blink of "nobody wants this" between two stretches of
> "carry on".
>
> A blink is all it takes. Every request in flight reads the token (see
> _get) and comes back empty the instant it says no, so the providers that
> were mid-fetch lose their answers; the walk then finds the token saying
> yes again, reaches the end, and STORES what is left as though it were the
> whole truth. That record outlives the blink by a month -- the store is
> keyed by the question, and the question it wrote down is the full one --
> so a song whose first round was cut off keeps a second-best answer for as
> long as it stays in rotation.
>
> Seen as Apple Music's own word-timed document missing from a song Apple
> Music has, with a blend on somebody else's lines stored in its place, and
> the same walk run again by hand picking Apple in four tenths of a second.
>
> So a cancel is final here. Once a walk has been told it is not wanted it
> stays told, it stores nothing, and the caller -- which is still there, or
> it would not have changed the slot -- asks the question again from the
> top. Nobody waits any longer for it: the walk was already being abandoned,
> this only stops it coming back.

### `_under`

**line 193** — from the docstring, `def _under(alive, fn, faults=None, who=None, people=None):`

> `fn`, run as part of the walk `alive` speaks for.
>
> `people` rides along for the one provider that has to choose between
> documents BEFORE the walk ever sees them -- see from_unison, where a
> community database offers several syncs of one song and the roster is the
> user saying which of those people they trust. Everywhere else the roster
> is asked about the answer, which is after the choosing and too late.

### `_blamed`

**line 227** — from the docstring, `def _blamed(why: str, whom: str = "") -> None:`

> File one failure against whoever the walk is asking.
>
> The FIRST one is kept. A provider is several requests -- a search, then a
> download, then the same again for the second shape of the question -- and
> once its host is down they all say the same thing; what the user wants is
> the name of the source and one reason, not five lines of the same reason.
>
> `whom` is who to file it under where the walk has not said -- which is
> the case for a provider that raised on its way out, since it is no longer
> inside the _asks that named it.

### `_door`

**line 284** — from the docstring, `def _door(provider: str, name: str, fn):`

> `fn`, one door of `provider`, told to TRACE under `name` of its own.
>
> Only where the walk is asking `provider` itself for a song it is tracing:
> a blend that wants Apple's lines asks through the same doors, and its time
> is the blend's (see _asks). The fault each door files is kept apart for
> its own line in the overlay, then handed on to the walk's, where it is
> still the provider's -- the Sources row knows Apple Music, not its doors.

### `_apart`

**line 464** — from the docstring, `def _apart(a: str, b: str) -> bool:`

> Whether a space belongs between these two spans whatever the file says.
>
> Two spans written back to back are a file saying they spell ONE word --
> "Couldn't" cut into "Couldn" and "'t" -- and that rule is right and is
> what _syllables is built on. It cannot be true of every pair, though. An
> opening quotation mark never sits against the word in front of it and a
> closing one never sits against the word behind it, in any language that
> uses them: a source that writes
>
>     <span>crie :</span><span>«</span>
>
> has dropped a space, it is not claiming "crie :«" is a word. French
> drops that one often, because the space it wants there is a narrow
> no-break space and does not survive whatever handled the file before this.
>
> ONLY THE UNAMBIGUOUS MARKS, and the two exclusions are the whole of why
> this is a list and not a category test:
>
>   * ’ is left out. It is the apostrophe in "don’t" and
>     "c’est" at least as often as it is a quote, and a rule that put
>     a space inside those would be far worse than the one it fixes.
>   * 「 」 『 』 and the other CJK brackets are left
>     out for the opposite reason: they take no spaces at all, so inserting
>     one would be the same fault in the other direction.

### `_syllables`

**line 482** — from the docstring, `def _syllables(parent, spaced: bool = True) -> list[dict]:`

> Timed <span> children -> Syllables, with word breaks taken from spacing.
>
> TTML has no word flag; a well-formed file puts whitespace between the spans
> that end a word and none between the spans inside one, which is the same
> information IsPartOfWord carries, just written differently.
>
> Some of amll-ttml-db's older hand-made submissions put no whitespace
> anywhere -- every word is its own span, back to back. Reading those by the
> spacing rule spells "Couldn'tbeathersmileitstirredupallthemedia", so when
> the file never spaces anything (`spaced` is False) each span is taken as a
> word instead. Not for CJK, which genuinely runs together and where the
> spans really are sub-word.
>
> A span with no `begin` is still a syllable. A file being written carries
> its words -- and the splits somebody cut them into -- long before it
> carries a timing, and this editor's own working copies and backups are
> exactly that file. Dropping the untimed spans left the line to be read
> back out of its flattened text, where every split, and every word a
> half-timed line had not reached yet, had gone.
>
> Only where the <p> holds no loose text of its own, though, and only once
> nothing in it is timed: a paragraph that mixes plain words with a span or
> two is writing a sentence, not spelling one out, and the words outside
> the spans would be lost if the spans were read as the whole line.

### `_repair`

**line 521** — from the docstring, `def _repair(syls: list[dict], begin: float | None = None,`

> Re-time syllables that are stamped somewhere the line is not.
>
> These are community submissions and some carry a syllable stamped
> 00:00.000 in the middle of an otherwise fine line. Rendered as-is the fill
> jumps back to the start of the song and the whole line reads as sung, so
> any run that lands outside the line gets interpolated across the gap its
> sane neighbours leave.
>
> Outside the LINE, though -- not merely out of turn. Syllables inside a
> line overlap each other on purpose: a word held over the ones after it, a
> rapped line whose breath carries through, an ad-lib sung across the words
> beneath it. Two syllables sounding at once is a thing a singer does, and a
> file that says so is not corrupt. The old test -- every syllable must
> start where the last one ended -- called each of those a mistake and
> flattened the whole rest of the line onto one instant, which is precisely
> the damage this is here to undo.
>
> A line with no stamps of its own has nothing to be outside of, so there
> the reading falls back to the order the syllables are written in.
>
> Syllables with no stamp at all are not out of place, only unwritten yet;
> they sit the repair out and keep their neighbours' company.

### `_unwrap`

**line 579** — from the docstring, `def _unwrap(syls: list[dict]) -> list[dict]:`

> Peel the brackets off a backing vocal.
>
> Apple's TTML -- and amll-ttml-db following it -- writes backing vocals with
> the parentheses baked into the text: "(For" ... "you)". The app draws
> backing vocals as their own indented line and adds brackets itself where it
> wants them, and Spicy Lyrics' own data has none, so leaving these in shows
> one convention's punctuation inside the other's layout.
>
> Only stripped when they actually pair up across the group, so a line that
> genuinely contains a bracket is left alone.

### `_destamp`

**line 614** — from the docstring, `def _destamp(items: list[dict]) -> list[dict]:`

> Drop timings that are not really timings.
>
> A document can arrive with plain, unsynced lyrics in the same timed shape
> as everything else, every line stamped 00:00.000. Taken at face value
> that is a "synced" document where the whole song happens at once: the view
> lights every line at 0:00 and then never moves again, which is worse than
> honestly showing it as unsynced and letting it scroll. Treat a document
> whose stamps never advance as static, and say so.

### `_credits`

**line 630** — from the docstring, `def _credits(root) -> tuple[list[str], str, str, dict]:`

> Who wrote the song, who timed this copy of it, their id, and what song it is.
>
> Three conventions in play, all in the same <head>. Apple writes
> <songwriters><songwriter>. A <lyricsplus:curator> names whoever submitted
> a sync, which no source here fetches any more and a file dropped on the
> window can still carry. amll-ttml-db files the same fact as an <amll:meta
> key="ttmlAuthorGithubLogin">.
>
> Matched by local name: the prefixes differ per file, and amll's <metadata>
> binds xmlns="" so half of it is in no namespace at all.
>
> amll also files the author's numeric GitHub account id as
> ttmlAuthorGithub. That is the one that holds still through a renamed
> login, so it comes back as the maker's id -- see same_person -- prefixed,
> because a GitHub number and a Discord one are different people's numbers.
>
> The title, artist and album come out of the same <amll:meta> tags, and
> they are the only place in a TTML head a song can say what it is. Apple's
> own files never do, which is why a document saved out of the editor used
> to come back not knowing its own name.

### `_agents`

**line 653** — from the docstring, `def _agents(root) -> list[str]:`

> The voices the header declares, in the order it declares them.
>
> A ttm:agent id is an arbitrary name -- v1, v2, singer1, whoever -- but the
> ORDER they are declared in is not arbitrary: the first is the voice the
> document is written from, and it is the one a player draws on the near
> side. Apple's files declare it first, and this project's own renderer
> writes v1 before v2 for exactly that reason.
>
> Taking the primary from whichever LINE came first instead -- which is what
> this used to do -- flips a whole duet the moment the other singer opens
> the song, and plenty of duets open that way. The file said v2, v1, v2 and
> read back as v1, v2, v1: both sides swapped, in the editor on reopening
> and in the player over the live link.

### `_translits`

**line 667** — from the docstring, `def _translits(root) -> dict:`

> Apple's per-syllable readings, by the line key they are filed under.
>
> <iTunesMetadata><transliterations><transliteration xml:lang="ja-Latn">
> <text for="L1"><span begin=.. end=..>yo</span>...</text> -- one span per
> syllable, in the order the line's own spans come, and an x-bg span per
> backing run holding its own. {key: (lead readings, [bg readings, ...])}.

### `_deword`

**line 834** — from the docstring, `def _deword(doc: dict) -> dict:`

> Word-timed document -> line-timed, keeping the line stamps.
>
> Not a loss of information so much as a refusal to claim some: a source that
> times words by dividing a line across its syllables produces a document
> shaped exactly like a real word sync, and the view has no way to tell them
> apart -- it just highlights the wrong syllable very confidently. Dropping to
> the line stamps, which are measured either way, is the honest reading.

### `_song_key`

**line 920** — from the docstring, `def _song_key(name: str) -> str:`

> _norm, with any version marker kept out of the words it swallowed.
>
> For the one lookup that is a dict and not a list of hits to examine.
> Everywhere else a candidate arrives with its title attached and _same_cut
> reads it there; here the question has to be asked of the key itself, or
> "Galaxies (Remix)" and "Galaxies" are the same three-word string and the
> index has no way left to tell them apart. See ALT_CUT.
>
> A title carrying no marker keys exactly as _norm alone did, which is
> almost all of them and is what lets an index cached before this existed
> go on answering for them.

### `SpicyError`

**line 951** — from the docstring, `class SpicyError(Exception):`

> Spicy Lyrics could not be asked, or would not answer.
>
> Not the same thing as it saying a track has no lyrics, which is an answer
> -- None -- and is cached as one. This is everything else: no key, a key
> the service will not take, a rate limit, a timeout, a 500. The difference
> matters to every caller, because a source that had nothing is settled and
> a source that could not be reached is worth saying out loud and asking
> again later; see lyrics_gui.Fetcher._spicy_body.
>
> `code` is the service's own machine-readable error where it gave one
> ("lyrics_not_found", "rate_limited", "key_revoked", ...), `status` the
> HTTP status, and `after` the seconds it asked to be left alone for.

### `set_spicy_key`

**line 1008** — from the docstring, `def set_spicy_key(value: str) -> pathlib.Path:`

> Keep a key for next time, readable only by its owner.
>
> In the config directory rather than this tree: a secret key that lands in
> a working copy is one `git add -A` away from being published, and no
> permission on the file prevents that. A publishable one belongs in
> SPICY_SHIPPED_KEY instead, where it ships.

### `spotify_web_search`

**line 1081** — from the docstring, `def spotify_web_search(meta: dict) -> list[dict] | None:`

> Spotify's catalogue asked over its Web API, in JS_SEARCH's row shape.
>
> None where it could not be asked (no kept token, or it refused). Rows found
> through an ISRC Apple gave for this song carry "isrc": True -- the same
> recording by its registration code, which needs no name to agree. `meta["isrcs"]`,
> where given, are asked instead of Apple's.

### `_spicy_budget`

**line 1198** — from the docstring, `def _spicy_budget(headers) -> None:`

> Note what is left of this application's window, and stop when it is.
>
> Every answer carries it, so this is free, and it is the one reading here
> that is about US rather than about one lookup: a spent window refuses the
> next request whatever it is for, so there is no sense in making it. The
> difference between noticing at zero and noticing at the first refusal is
> a run that pauses and a run that fills a log with 429s.

### `_spicy_fetch`

**line 1213** — from the docstring, `def _spicy_fetch(track: str, timeout: float = TIMEOUT) -> dict | None:`

> Spicy Lyrics' document for one track, or None where it has no lyrics.
>
> Everything that is not an answer raises SpicyError, including a track id
> this never sent: 22 base62 characters is the whole of the API's contract
> for the path, and a URI, a URL or a stray space would otherwise be spent
> on a round trip that can only come back 400.

### `_spicy_docked`

**line 1263** — from the docstring, `def _spicy_docked(doc: dict, tid: str) -> dict:`

> A document as this project keeps them.
>
> Three small things, all of them at this one door so that nothing
> downstream has to know a document was fetched today rather than snapshotted
> two years ago:
>
>   * the zero-width spaces Spicy Lyrics writes into its text come out (see
>     SL.unzwsp_body for why removal and not substitution);
>   * the catalogue is renamed to its three-letter code (see SPICY_CODES);
>   * the credits are filed under TTMLUploadMetadata, which is where every
>     reader of them in this program looks -- the roster that refuses or
>     prefers a person by id, the credit line under the lyrics, and the
>     dataset builder that will only train on a sync somebody's hand made.
>     The API calls the field UploadAttribution and its contents are
>     identical; the name on disk is the older one, and the snapshots still
>     holding it are the ones the benchmarks are measured against.
>
> The track id is filled in where the service left it out, because
> everything downstream reads it off the document.

### `_spicy_record`

**line 1286** — from the docstring, `def _spicy_record(track: str, touch: bool = True) -> dict | None:`

> The stored answer for a track, or None if there is not a usable one.
>
> A miss ages from when it was taken: six hours after the service said no,
> asking again is worth the round trip, because the thing that changes is
> somebody uploading a sync. A hit ages from when it was last USED, so a
> song in rotation keeps its lyrics for as long as it stays in rotation.

### `spicy_lyrics`

**line 1341** — from the docstring, `def spicy_lyrics(track: str, refresh: bool = False, timeout: float = TIMEOUT):`

> Spicy Lyrics' document for a track: off the disk, or asked for.
>
> None means the service has nothing for this track. SpicyError means it was
> not asked or would not say, which is a different thing and is never cached
> as an answer -- an outage must not become a month of "this song has no
> lyrics".

### `from_spicy`

**line 1374** — from the docstring, `def from_spicy(tid: str, meta: dict | None = None, local=None, **_kw):`

> Spicy Lyrics, in the shape every other provider in this file has.
>
> Never raises: trouble is filed through _blamed like anybody else's, so a
> walk carries on without it and the window is told which source it did not
> get. The direct form -- spicy_lyrics() -- is for the callers that want the
> reason in their hands rather than in a report.
>
> `meta` is ignored. This is the one source here asked by Spotify track id
> rather than by title, artist and length, which is also why it cannot
> answer at all for a player that has no Spotify id to give (see
> lyrics_gui.SmtcTransport).
>
> A name key (lyrics_gui.song_key: 22 lowercase hex) passes SPICY_ID's
> shape, and every new song from such a player was spent on a request that
> could only come back empty. It is not asked.

### `spicy_ids`

**line 1415** — from the docstring, `def spicy_ids() -> list[str]:`

> The tracks a Spicy Lyrics document is held for here.
>
> This is the whole of what can be enumerated, and it is worth being plain
> about what it is not: the API answers about one track and does not list
> its catalogue, so this is the songs this machine has fetched, not the
> songs Spicy Lyrics has. Every batch command that used to walk the
> Spicetify cache -- the window's search index, the benchmarks, the dataset
> builders -- is asking that narrower question now, and it grows as songs
> are played.

### `amll_index`

**line 1463** — from the docstring, `def amll_index() -> dict:`

> title+artist -> raw lyric file, built from the db's own index.
>
> Only 2362 of the entries are filed under a Spotify id, but every one of the
> 3157 raw submissions is listed here with its title and artists. On a real
> library the id lookup alone finds almost nothing; this is what makes the
> source worth having.

### `from_qq`

**line 1522** — from the docstring, `def from_qq(tid: str, meta: dict, local=None) -> dict | None:`

> QQ Music's own document, its lines as well as its timings.
>
> The blends take QQ's word timing and lay it under Apple's lines, which is
> usually the better document -- Apple's wording, casing and line splits are
> the ones this player is built around. Usually is not always: QQ writes
> ad-libs the Apple copy simply does not have, on their own lines and in
> their own time, and where reconciling the two loses them the source on its
> own is the honest answer.
>
> Asked of QQ directly, and only of QQ; see _qq. A second door used to be
> kept behind this one -- LyricsPlus', which is gone -- on the grounds that
> the two fail on different songs and its copy was worth one request on the
> handful QQ's own endpoint cannot find. One request there was ten seconds,
> it was spent on every song QQ missed rather than on the handful, and it
> was spent inside the round the blends are waiting on, for a document that,
> where it arrived at all, was QQ's anyway.

### `from_lrclib`

**line 1530** — from the docstring, `def from_lrclib(tid: str, meta: dict, local=None) -> dict | None:`

> LRCLIB, by exact record where it has one and by search where it does not.
>
> /api/get matches the name, the byline and the duration itself, so what
> comes back from it is this recording or nothing. /api/search matches on
> the words, and until the ALT_CUT test below the only thing asked of a hit
> was that it be within four seconds -- which is how the search for
> Protostar's instrumental "Galaxies" came back with "Galaxies (Rogue
> Remix)", four minutes flat against four minutes five, sorted to the top
> for being the only hit anybody had synced.

### `_ne_rank`

**line 1624** — from the docstring, `def _ne_rank(meta: dict) -> list[int]:`

> Plausible NetEase song ids for this track, best first.
>
> Search never fails -- it returns a nearest match for anything, including
> tracks it plainly does not have -- so a hit is only believed when the
> duration lines up, or failing that when the title matches outright. Without
> that check this source would confidently answer for the whole library.
>
> A list rather than a single winner because NetEase routinely carries the
> same recording several times over -- standard, deluxe, compilation -- and
> only some of those releases are stamped word-level. They tie on every
> signal available here (same title, same duration to the millisecond), so
> which one "wins" is decided by result order, and the caller has to open
> more than one to find the timing.

### `_cut`

**line 1757** — from the docstring, `def _cut(y: dict, at: int):`

> One syllable split in two at a character, sharing its time by length.
>
> A bracket does not have to fall on a syllable boundary -- "(hey)" arrives
> as one token, and so does "said (hey) to" -- so the split has to be able
> to happen inside one. The time is divided by character count, which is
> wrong in the way every interpolation is wrong and right in the way that
> matters: the two halves still run end to end over the same span.

### `_ne_bg`

**line 1790** — from the docstring, `def _ne_bg(syls: list[dict], cap: bool = True):`

> A line's syllables split into the lead and its backing vocals.
>
> NetEase writes backing vocals inline and in brackets -- "best （Hahahaha）",
> "（Why） Why was it easy" -- with the brackets timed as words of their own,
> and Kugou's KRC does the same. The view draws a backing vocal as its own
> voice against the line, so they have to leave the lead and become groups in
> their own right. The brackets go with them: they are notation for an inline
> rendering, and _unwrap already strips the same thing off Apple's and amll's
> backing vocals.
>
> Brackets are looked for INSIDE the syllables, not only at their edges. They
> were once only recognised where a token began with one and a later token
> ended with one, which is true of the fullwidth NetEase lines this was
> written for and false of nearly every English one: "(hey) " carries a
> trailing space, so it opened a group it could not close, and the group then
> ran on until some later token happened to end in a bracket --
>
>     Do (hey) anybody make it)   ->  lead "Do", backing "hey) anybody make it"
>
> swallowing the rest of the line into a voice that never sang it. Now the
> close is found wherever it is and the syllable holding it is cut there.
>
> A group that never closes is not a group: its text goes back to the lead
> with its bracket restored, rather than being silently dropped.

### `_unfake`

**line 1883** — from the docstring, `def _unfake(items: list[dict]) -> list[dict]:`

> Divided lines put back to line level, so they light as one.
>
> Left alone where the line carries a backing vocal: the lead's text is only
> recoverable from its syllables, and the pairing of an untimed lead with a
> timed background is a shape nothing downstream expects. Both together are
> rare enough to not be worth the second code path.

### `_ne_writers`

**line 1973** — from the docstring, `def _ne_writers(lrc: str) -> list[str]:`

> Songwriters out of the credit lines the parse above drops.
>
> NetEase stamps them like lyrics -- "[00:00.000]作词 : Ester Dean" -- so they
> have to be recognised anyway to keep them from scrolling past as verse one.
> Having found them, they are worth keeping: this is the only source here
> that names a songwriter for a track Apple has never carried.

### `_netease`

**line 1998** — from the docstring, `def _netease(tid: str, meta: dict) -> dict | None:`

> NetEase Cloud Music.
>
> Worth a slot of its own: it is the only source here that ships a human-written romanisation (`romalrc`) on the same
> timestamps as the lyrics, which is the one thing the Genius path has to
> work hard to reconstruct.
>
> Word-level timing is not a property of the song here but of the particular
> release, so the search's own favourite is not necessarily the copy worth
> having: take the first candidate that is stamped word-level, and settle for
> the best-ranked line-level copy only once the alternates are exhausted.
>
> Falling back costs nothing extra to do well -- reaching the end of the
> candidates is what "no word-level copy exists" means -- so among line-level
> copies prefer one carrying `romalrc`, which is as unevenly distributed
> across releases as the timing is.
>
> An alternate is only an alternate if it ties with the best on every signal
> there is: same title, same length, same byline. Ranking below the winner
> on one of those does not make it a second pressing of this song, it makes
> it a different song -- and walking down to it is how Pipotaku's "SOUR"
> ended up showing somebody else's SOUR of the same length. The word-level
> branch has always demanded that tie; the line-level fallback took whatever
> was left, which is where the wrong lyric got in.

### `_shared`

**line 2052** — from the docstring, `def _shared(a: list[str], b: list[str], pairs: dict, floor: float = BLEND_SAME) -> bool:`

> Whether two line sequences are the same song, given what matched.
>
> Measured against the shorter of the two, not against the base. What is
> being asked here is whether the donor is about this recording, and a donor
> can only answer with the lines it has: one that omits an ad-lib hook, or
> writes as one line what the other splits into two, covers less of the base
> without being any less the same song.
>
> Judged the other way it was the base's length that decided, and a donor was
> turned away for being less complete than the copy on screen. Koven's "Light
> Up" is 46 lines to NetEase's 30 -- NetEase leaves out the "High, high,
> yeah" hook entirely and splits "Who knew that we have the power to be
> whatever we wanted" across two lines. Twenty-two lines matched outright,
> which is 48% of the base and 73% of NetEase, and the base's share is the one
> that was read: the two were declared different recordings and a word-level
> sync was thrown away for a song that had none.
>
> Still a share and not a count, so the donor has to match most of what it
> does carry. A donor about some other recording does not quietly agree with
> two thirds of itself.

### `_coherent`

**line 2064** — from the docstring, `def _coherent(pairs: dict, bit: list, dit: list) -> bool:`

> Whether the matched lines agree about where they are in the song.
>
> A wrong donor does not reach this test. Against a different recording the
> aligner finds a handful of stock lines at most, scattered anywhere -- and
> against a genuinely different song, nothing at all: the control run here
> produced zero exact matches before any timing was even looked at.

### `_pair`

**line 2078** — from the docstring, `def _pair(base: list[dict], other: list[dict]):`

> base line index -> other's, by text, or None if these are not one song.
>
> The two sides split and merge lines differently, so this aligns the text
> sequences and keeps only the stretches that match outright. Too few and the
> donor is answering about some other recording -- a cover, a live version,
> the wrong single entirely -- and every timing it offers is noise.
>
> The near pairs count towards "too few", not just the exact ones. They
> used to be added only after the exact matches alone had cleared the bar,
> and Koven's "All We Needed" never cleared it: NetEase writes "can have"
> for Apple's "could have" ten times over, "speak to us" for "speak of us",
> "its" for "it's" -- 18 exact of 39, against 21 needed, and 27 once the
> near pairs were counted. The song went unblended over a modal verb.
> Counting them is safe for the reason _near_pairs gives: they are found
> only inside the windows the exact matches leave, so they cannot be found
> at all without some exact matches first.
>
> An ad-lib the donor files apart from its line is taken out of ours before
> comparing, as _unaside does for the relay: Apple writes "We see the world
> in a cold light (cold light)" where NetEase writes the line and times the
> echo as a backing group of its own, and the two were never going to match
> as written.

### `_filed_apart`

**line 2097** — from the docstring, `def _filed_apart(doc) -> set:`

> The ad-libs a donor keeps out of its own line stream, by their words.
>
> A source that marks its backing vocals properly puts them in a group of
> their own, beside the line rather than inside it. Their letters are
> therefore not in the stream _restream reads, and a base that writes the
> same ad-lib INSIDE its line has letters with nothing to match against.

### `_unaside`

**line 2106** — from the docstring, `def _unaside(text: str, apart: set) -> str:`

> A line without the ad-libs the donor files apart from its own words.
>
> Only those. A bracket the donor writes into its line like everybody else
> is in the stream and has to stay here too, or the line loses the letters
> that were going to fetch its timing: on Linkin Park's "Runaway", "Mind
> (Gonna run away, gonna run away)" is one line to NetEase as well, and
> taking every bracket out left that line matched to the four letters of
> "Mind" with nothing to relay.

### `_stream_blocks`

**line 2128** — from the docstring, `def _stream_blocks(ours: str, theirs: str, floor: float):`

> The matching blocks of two whole songs' letters, or None if they are
> not alike enough.
>
> Worked out once for a pair. The blends that share a base and a donor --
> Apple with NetEase, with NetEase and QQ, with NetEase and Kugou -- and
> _clock all reach _restream with the same two strings, and this is the one
> difflib pass in the file over thousands of letters: 147ms at 2,500 and
> 389ms at 3,200, each time, with the GIL held. Not the _shorter shortcuts
> that were refused (see TODO.md): difflib is handed exactly what it was.

### `_restream`

**line 2174** — from the docstring, `def _restream(base: list[dict], donor: list[dict], floor: float = 0.80):`

> The donor's syllables re-cut where the BASE breaks its lines.
>
> Two sources can spell a song identically and still pair badly, because
> where a line ends is an editorial decision and they make it differently.
> Apple writes
>
>     I'll give you something to hold all my disasters in
>     Under your skin
>
> where Kugou writes both as one line, and splits "Elbows shouldn't bend
> that way / But it's okay" after "okay" instead of before it. Matched line
> by line that is a song disagreeing with itself: on STOMACH BOOK's "My
> Diorama" only 25 of 48 lines paired, under the floor that decides whether
> the two are even the same recording, and a perfectly good word-timed
> document was thrown away over punctuation.
>
> So the donor is read as what it really is -- one stream of timed
> syllables -- and cut again at the base's own line ends. The alignment is
> over the letters of the whole song, which makes a line break just another
> thing the two sides can disagree about, and one that no longer matters.
>
> Spans are forced apart afterwards so no syllable lands in two lines: a
> letter that matches in both places would otherwise time a word twice.

### `_in_step`

**line 2354** — from the docstring, `def _in_step(out: list, based: list) -> None:`

> Lines that borrowed the wrong repeat of themselves, given back.
>
> A donor cannot tell one repeat of a line from another, and a chorus or an
> outro is the same words several times over. _timely settles that where the
> line-by-line pairing made it -- a pair sitting a bar off its neighbours'
> offset is dropped -- but a start can also arrive by the re-stream or from
> the second donor, and both are added to the map AFTER _timely has run. So
> the wrong repeat still gets through, by the back door.
>
> NF's "Change" is the case: its outro is four lines said twice, and the
> Apple+NetEase+Kugou blend came out running 200.8, 210.8, 212.6, 207.0,
> 208.9, 211.1, 212.7 -- two lines carrying the second repeat's timing while
> sitting in the first repeat's place, and the rest of the outro playing
> catch-up behind them.
>
> Out of sequence is the first half of the test and cannot be all of it: a
> line both donors independently place late is out of sequence too, and
> there it is the donors' reading of the song rather than a mistake -- see
> the "no steadier" case in test_blends. What separates the two is that a
> wrong repeat is a repeat. So a line is only given back when the song says
> the same words somewhere else AND this line has landed on top of that
> other one's timing, which is what borrowing the wrong repeat looks like
> from the outside and what a genuinely late line never looks like.
>
> Which lines are out of sequence is not a question the neighbours can
> answer one pair at a time: read that way the run above accuses 212.6 and
> 207.0 alike, and 207.0 is the one telling the truth. The longest run of
> starts that DO ascend is the answer -- the largest set of lines that can
> all be right together -- and a line outside it is handed back to the
> base's own stamp. Handed back whole: a start that landed on the wrong
> repeat was carrying that repeat's syllables, so the words go with it.
>
> Nothing is done where the base has no stamp of its own to return to, or
> where its stamps are the ones out of order: Pixel Terror's "Enigma" is
> written that way in the Apple document, and there the sequence is not
> evidence about anything.

### `_timely`

**line 2421** — from the docstring, `def _timely(pairs: dict, bit: list, dit: list, tol: float = BLEND_JUMP) -> dict:`

> Drop pairings whose timing disagrees with their neighbours'.
>
> Text cannot place a line in a song that repeats it. "Caught in the middle"
> is ten separate lines of one Linkin Park chorus, "Two faced, caught in the
> middle" six more, and where two sources carry different numbers of repeats
> the aligner is free to pick the wrong one -- it is the same string either
> way, and the result was a chorus landing 2.5s early.
>
> Time tells them apart. Two real transcriptions of one recording drift
> against each other slowly, so every genuine pair in a stretch of song shares
> roughly one offset; a pair matched to the wrong repeat sits a bar or two off
> that. Compared against the median of its neighbours rather than a figure for
> the whole song, so a document that really does drift is not punished for it.
>
> Only a pairing that could be the wrong repeat is judged. A line said once
> on each side has exactly one place to go, and so does the second of two
> on each side paired with the second: where its offset disagrees with its
> neighbours' it is the base's line sync that wobbles, not the pairing. On
> Koven's "All We Needed", Apple's line starts run 0.4s either side of
> NetEase's, and "All we had and all we lost" -- said once in the whole
> song -- was thrown out for it and had NetEase's words slid onto Apple's
> looser start instead. What is still judged is a line the two sides repeat
> a different number of times, or a pairing of the first with the second.

### `_wander`

**line 2470** — from the docstring, `def _wander(bit: list, dit: list, dmap: dict) -> float | None:`

> How much this donor's clock WANDERS against the base's line sync.
>
> Each paired line's offset from the base, then the median distance of
> those from their own median -- so the constant difference between two
> clocks is taken out and only the inconsistency is left. None where too
> little of the song is paired to say anything.
>
> Off the PAIRING, before the re-stream and the filler have added to the
> map. That matters: those add lines this donor could not place on its own,
> and their offsets are the other donor's or a cut of our own making, so
> counting them measures something that is no longer one donor's clock.
> Measured both ways against the hand-timed files here -- the pairing alone
> picks the truly better donor 7 times out of 7, the finished map 6.

### `_clock`

**line 2495** — from the docstring, `def _clock(bit: list, doc) -> tuple:`

> Where this donor's clock sits against the base's line sync.
>
> (shift, wander): how far the whole document is out, and how much it
> wanders about that. `_wander` is the second of those on its own, off the
> pairing alone, which is the right question when what is being weighed is
> two donors' steadiness. This is the other one, and it needs the whole
> song: a donor's copy of a recording can be shifted bodily -- a different
> master, a different cut, an intro the other pressing does not have -- and
> a shift is invisible to every test the blend already runs. Each line
> agrees with its neighbours, `_timely` passes them all, `_astray` finds
> nothing, and the finished document plays a second early from start to
> finish.
>
> Over the songs measured here that failure is not rare and it is not
> small: NetEase hands back Cartoon's "Why We Lose" 21.9 seconds out,
> J. Cole's "MIDDLE CHILD" 1.8 seconds early and Linkin Park's "Faint" 1.7
> late, and QQ Music has all three within a tenth. The base's line sync is
> the only witness to it, because it is the one document known to be timed
> against the recording actually playing.
>
> Read off the pairing AND the donor's own stream re-cut, unlike `_wander`:
> a re-streamed line is still this donor's syllables at this donor's times,
> which is all a shift is asking about, and on a third of the songs here
> the two sides break their lines differently enough that the pairing alone
> says nothing at all.

### `in_order`

**line 2516** — from the docstring, `def in_order(base, first: tuple, second: tuple) -> tuple:`

> The blend's two donors, the one holding THIS recording first.
>
> Each donor is (document, what to call it, which source it is). A
> three-way blend takes its words from the first and asks the second only
> about the lines the first could not place, so which of them leads is the
> single biggest thing about the document that comes out -- and it used to
> be settled once, in the source order, for every song alike. NetEase is
> the steadier of the two in general, which is why it leads by default and
> still does wherever there is nothing to choose between them. It is not
> the steadier one on every song, and on the songs where it is not, a fixed
> order is simply wrong -- an ear on Lil Tecca's "Amigo" said QQ Music
> long before any of this could say why.
>
> What decides is `_clock`'s shift: how far the donor's whole document sits
> from the base's line sync. Not the wander -- the blends already weigh
> that, line by line and blend against blend -- but the constant nothing
> else looks at. Whichever document _blended settled on is the witness,
> because it is the one that was timed against a recording rather than
> matched to one by its text; where that is LRCLIB rather than Apple it is
> a poorer witness, and it is still the only one there is.
>
> Measured through eval_blends over 354 songs with a community word sync to
> score against, the rule off and then on, same jar and same run. It moves
> 32 of the 354 and leaves the rest exactly where they were; of those 32 it
> helps 15, hurts 6 and comes out level on the remaining 11. Words more
> than half a second out of step with their own song go from 1.10% to 0.97%
> of the song at the median and 4.68% to 4.21% on average, and the mean
> scatter across the set falls from 0.258s to 0.163s.
>
> Those are small numbers for what is behind them, because the songs it
> catches are not slightly wrong. Cartoon's "Why We Lose" goes from 81.2%
> of its words out to 0.8%, J. Cole's "MIDDLE CHILD" from 62.0% to 1.2%,
> Linkin Park's "Faint" from 8.5% to none: three songs where NetEase was
> holding another pressing and the blend was a second or twenty out for its
> whole length. The six it hurts are all of the other kind -- BBpanzu's
> "Bang Bang Bang" is the worst at 0% to 12.6% -- and they are the limit of
> what a line sync can witness: it can say which donor's clock is on this
> recording, and nothing at all about whether the words underneath are
> placed well once it is.
>
> The margin cannot be picked off that set, which is worth saying plainly:
> 0.05, 0.065 and 0.08 all land within a thousandth of each other over the
> 354 (4.21%, 4.23%, 4.22% of words out), the tighter one simply moving
> more songs in both directions. So the call is made by the one song
> somebody actually listened to -- "Amigo", NetEase 0.093 against QQ's
> 0.023 -- and 0.05 is the loosest setting that gets it right. Two clocks
> over one recording disagree by a few hundredths for honest reasons, and
> that is about as fine as a real call gets.
>
> The wobble guard does earn its keep: without it the same margin moves 30
> songs instead of 32 and gets 10 of them wrong instead of 6. A donor
> nearer the line sync overall but visibly less steady about sitting there
> has not earned the song.

### `_drift`

**line 2533** — from the docstring, `def _drift(bit: list, dit: list, dmap: dict) -> dict:`

> How far each line sits from where the lines around it put this donor.
>
> Two clocks over one recording differ by an offset that drifts, so "off"
> is never a distance -- it is a distance compared with the lines either
> side. _timely asks exactly this of the pairing and then throws the number
> away, keeping only the verdict; this asks it of the FINISHED map, which
> the re-stream and the filler have both added to since, and hands the
> number back, because the caller wants to know how far off and not only
> whether.

### `_guessed`

**line 2552** — from the docstring, `def _guessed(text: str, group) -> float | None:`

> The share of a line's words that would fill on an onset nobody measured.
>
> A donor that times three words of a nine-word line relays those three and
> hangs everything after them off the last one; _unlump then shares that
> single stamp out among the six words left over, and they go past in a
> rush somewhere the singing has already left. On screen it reads as the
> line coming apart partway through -- the fill tracks the voice, and then
> stops meaning anything -- which is a different failure from a line landing
> in the wrong place, and invisible to any test that only looks at where the
> line begins.
>
> None where the donor has nothing to lay under this line at all: that is a
> hole, and holes are already the second donor's business.

### `_astray`

**line 2562** — from the docstring, `def _astray(bit: list, qit: list, qmap: dict, apart: set = frozenset()) -> dict:`

> The lines the first donor timed, and timed wrong. i -> (drift, guessed).
>
> A donor answers for a song, not for a line, and it can be right about the
> song and wrong about one line of it -- matched to the wrong repeat of a
> chorus, or carrying only half the words the base writes. Until now the
> second donor was only ever asked about the lines the first could not place
> AT ALL, so a line placed badly kept its bad placement while a source
> holding the right one sat unused three lines away.
>
> Two ways of being wrong, because they show up differently and neither test
> sees the other:
>
>   * the line sits somewhere its own neighbours say it does not -- over
>     BLEND_JUMP from where the same donor's surrounding lines put it. The
>     same tolerance _timely uses, and for once that is measured rather than
>     borrowed: 0.75 and 1.0 came back level over the songs here and 1.5 and
>     2.0 came back worse, so there is nothing for a second number to say;
>   * the donor times only part of it, over BLEND_PATCHY of the line filling
>     on an onset it never measured.
>
> Nearly everything the first test catches came in through the re-stream,
> and that is not a coincidence: _timely already throws out a PAIRING that
> disagrees with its neighbours by this much, and the re-stream then fills
> the hole it left from the same donor's syllable stream, unasked and
> unchecked. On the songs here that is where the misplaced lines are --
> Chasing Clouds, Gold and The Mystic pair nothing at all and come through
> the stream whole.
>
> Whether the second donor is any better is _steadier's question, not this
> one's. Lines the first donor cannot place at all are left out: those are
> holes, and the caller asks about them separately -- on the same terms,
> since a hole is only a line nobody has answered for yet.
>
> `apart` is the ad-libs the donors file beside their lines rather than
> inside them, so the second test reads our line the way _peel_bracket is
> about to write it. Without it a line whose bracket the donor keeps
> somewhere else scores as barely timed and is handed over on the strength
> of words nothing was ever going to relay. See _unaside.

### `_steadier`

**line 2583** — from the docstring, `def _steadier(mine: tuple, theirs: tuple) -> bool:`

> Whether the second donor's answer for one line beats the first's.
>
> Conservative on purpose. The second donor has to be placing the line
> itself -- agreeing with its own neighbours to within BLEND_STEADY -- before
> anything it says is worth hearing, which is what stops a bad line being
> swapped for a differently bad one. Past that the failure decides: a line
> the first donor put in the wrong place is simply handed over, since the
> second one demonstrably has it in the right place, while a line the first
> donor only half timed is handed over only where the second really does
> time more of it.

### `_retime`

**line 2617** — from the docstring, `def _retime(a: list[str], b: list[str], bit: list, dit: list,`

> Re-pair lines the aligner put on the wrong repeat of themselves.
>
> Aligning by text alone cannot tell one chorus from the next, and the
> aligner reads the two sides in order, so it can only use each donor line
> once and takes them in the order it meets them. Where the base sings a line
> more times than the donor writes it, that pairs early repeats with late
> ones: on a 40-line track here, two lines were matched to donor lines 45
> seconds away while the donor lines actually beside them went unused.
>
> _timely throws those out, correctly -- but a rejected pair simply became no
> pair, and everything after the last surviving anchor fell back to
> interpolated word timing. The whole back half of that song lost its
> syllables while the donor was holding them.
>
> So: for a line still unpaired, look for a donor line with the SAME text
> whose time agrees with where the surviving anchors say it should be, and
> take the closest one within `tol`. Exact text only, and a donor line only
> once -- this runs after the decision about whether the two documents are
> the same recording has already been made, and must not be able to revisit
> it.

### `_agree`

**line 2664** — from the docstring, `def _agree(starts: dict) -> float:`

> Where a line begins, given up to three opinions about it.
>
> Two rules, both the caller's:
>
>   * the ones that are not too far out are believed, and the earliest of
>     them wins -- a line that lights slightly early reads as anticipation,
>     one that lights late reads as lag;
>   * where all three survive and still disagree by more than a rounding
>     difference, the middle one wins instead. The earliest of three that
>     genuinely disagree is the most likely to be the odd one out, and
>     picking it would let the least reliable vote decide the line.
>
> With everyone an outlier -- three clocks, no two of them close -- there is
> nothing to average, and the line sync gets the line: it is the one that
> came with the words, so it is the one that at least matches what is on
> screen.

### `_last_end`

**line 2677** — from the docstring, `def _last_end(ends: list[float]) -> float | None:`

> The line's end: the soonest anyone measured.
>
> The caller has already carried every end onto the line's agreed start, so
> what is being compared here is how long each source says the line runs.
> That is the whole of what an end means once the line has moved; two sources
> disagreeing about where in the song it sits is the start vote's business,
> and letting that disagreement in here again counted it twice.
>
> The soonest, because all three pad and none of them pad the same lines.
> Apple holds a line open to where it should stop being displayed, QQ pushes
> its last stamp out towards the line after, NetEase invents an end from the
> next line's start when it has none of its own. Taking the latest of two
> opinions therefore did not find the line's end at all -- it found whichever
> source had padded that particular line more. On The Hills it ran a
> seven-word line 4.2s past its last word and held "Yeah", which is sung for
> .6s, on screen for 3.2s. Over the tracks measured that left 27% of blended
> lines still lit more than .4s after the last word had finished filling,
> against 0.7% of the Apple document the blend was built from: a line already
> fully drawn, sitting there into the next one.
>
> Nothing measured is lost by taking the soonest, because the caller then
> pushes the end back out to the last syllable it is actually going to draw.
> A sustain that a source really did measure is in those syllables and stays
> on screen for as long as it was held; what the soonest end drops is only
> the stretch past the last word, which nobody is singing.

### `_blended`

**line 2700** — from the docstring, `def _blended(tid: str, meta: dict, local, timing, whose: str, alone: str,`

> Apple Music's lines with somebody else's word timing under them.
>
> Two documents, not three. NetEase used to vote here on where each line
> begins, and it was a bad third opinion: it is the source least likely to
> be holding the same master, so its vote pulled line starts around on
> songs the other two already agreed about.
>
> Asked one upstream at a time and reconciled here rather than taking
> whichever answered first, and independent of those upstreams' own on/off
> switches: this is a source in its own right, not a mode of the others.
>
> The lines do not have to be Apple's, but they come from Apple Music,
> LRCLIB, Musixmatch or Genius and nowhere else -- see _bases, which reads
> them out of `above` where the round before already fetched them and asks
> for them otherwise. Quality decides between them: nothing here will lay
> word timing under line-level lines while word-level lines are on the table.
>
> `local` is whatever the caller already holds -- in practice Spicy Lyrics'
> own document, which is usually Apple Music too and usually the better copy
> of it. It is offered alongside them: ignoring what was already on the
> machine meant blending against a weaker copy of the same Apple document,
> and, where the round before had found nothing, falling all the way to
> LRCLIB while a perfectly good Apple sync sat unused. It matters more for
> the Chinese catalogue than it looks, where the round before often has
> nothing and the lines can only come from here.
>
> There is no ask of its own left. This used to knock on LyricsPlus' Apple
> endpoint for a base whenever nothing in hand was word-level -- ten seconds
> of the walk, for a scrape of the catalogue BiniLyrics answers for in a
> tenth of one, in the round after BiniLyrics has already been asked and its
> answer handed here in `above`. Everything this blend
> can build on has been fetched by the time it runs, which is what the
> second round is for.

### `unblended`

**line 2720** — from the docstring, `def unblended(doc) -> bool:`

> Whether a blend came back as nothing but its base's own lines.
>
> _blend marks that with `_alone` set to where the lines came from, because
> no donor placed a word on them. It is not a blend, and it is not this
> blend's to hand over: the base is Musixmatch's or LRCLIB's or Genius'
> document, and with that source switched off in Sources it went on the
> screen anyway, credited to it. Where the source is on, the walk asks it
> in its own place and finds the same document there.
>
> A donor's own document, which stand_down hands over where it beat the
> blend, is marked with the donor's name and is not this.

### `set_bases`

**line 2740** — from the docstring, `def set_bases(on, shut=()) -> None:`

> Which of BASE_FROM a blend may take its lines from. The player's
> Blends tab sets this; left alone, every one of them is allowed.
>
> `shut` are the ones of those nobody is to be ASKED for: a copy already in
> hand still counts, but no request goes out for one. The player puts Apple
> Music here when its source is switched off, which is somebody saying they
> want the blends without it -- they used to go with it, all five of them,
> as if Apple's lines were the only ones a blend could have.

### `_bases`

**line 2753** — from the docstring, `def _bases(tid: str, meta: dict, local, above) -> list:`

> The documents a blend may take its lines from, best first.
>
> Apple Music's, LRCLIB's, Musixmatch's and Genius' -- and nobody else's.
> Spicy Lyrics' own document counts only where it is Apple's. Each is taken
> from `above` when the round before already has it, and asked for here
> otherwise, in that order, stopping once something line-timed is in hand:
> nothing further down the list can beat that, since Musixmatch's word sync
> is never used (see _line_only) and Genius has no clock at all.
>
> Quality still decides between them, and the list order breaks a tie.
> Only the ones switched on in BASE_ON are used, and the ones in BASE_SHUT
> only where they are already in hand.

### `stand_down`

**line 2837** — from the docstring, `def stand_down(out, donor, base, alone: str):`

> The blend, or the donor's own document where the blend was not worth it.
>
> Split out of _blended so a measurement can build a blend from documents
> already on disk and still be measuring what the chain would really hand
> over. eval_blends.py rebuilds every blend over a fixed jar of donors, and
> a copy of this rule kept beside it would drift away from this one.

### `_reworded`

**line 2897** — from the docstring, `def _reworded(donor, base):`

> The donor's document, written the way the base writes it.
>
> Standing a blend down to the donor gets the song back whole, and throws
> away the thing the base was chosen for: its wording. Apple writes "You've
> gotten me under your spell" and an apostrophe where QQ Music writes
> "You've got me under your spell"; the reader picked Apple Music, and on
> the two thirds of the song Apple has there is no reason they should stop
> seeing it.
>
> So the donor keeps its lines, its coverage and its clock -- everything
> the stand-down was for -- and every line the base also has is re-lettered
> from the base, cut along the donor's own syllables. That is exactly what
> _relay does inside a blend; this is the same trade, made line by line
> over a document the blend gave up on.
>
> A line the base does not have keeps the donor's words, because there is
> nothing else to write it with. A line whose letters will not re-cut is
> left alone rather than half-done.

### `_short_of`

**line 2934** — from the docstring, `def _short_of(a: str, b: str) -> bool:`

> _shorter, once the two documents are down to their letters.
>
> Split out for one reason: this is the part that costs, and it needs
> nothing but two strings, so it is the part that can be done in another
> process. Measured over a cold walk it was 2046ms across twelve calls, the
> worst of them 389ms on 3216 letters against 3293 -- and every millisecond
> of it held the GIL away from the thread drawing the words. See offload.
>
> Not made cheaper, moved. What difflib matches here is what it matched
> before, to the opcode.

### `_shorter`

**line 2950** — from the docstring, `def _shorter(blend, donor) -> bool:`

> Whether the blend's words are missing a real part of the song.
>
> Two questions, and both have to answer yes. Is this the same lyric --
> nearly all of the blend's letters inside the donor's -- and is there one
> unbroken stretch of the donor the blend has not got, big enough to be a
> section of the song rather than a spelling difference. See BLEND_SHORT.

### `from_kublend`

**line 2979** — from the docstring, `def from_kublend(tid: str, meta: dict, local=None, above=None) -> dict | None:`

> The same, with Kugou underneath instead.
>
> Kugou and QQ are very largely the same word-timed data -- on eight CJK
> tracks measured here, six agreed syllable for syllable to within seventy
> milliseconds -- so this is not a second opinion so much as a second way
> in. It matters because the doors fail separately: Kugou answered for ten
> of those ten tracks where QQ answered for eight.

### `from_neblend`

**line 2985** — from the docstring, `def from_neblend(tid: str, meta: dict, local=None, above=None) -> dict | None:`

> The same, with NetEase's word timings under Apple's lines.
>
> A different pairing from the old three-way blend, which is worth saying
> because that one was bad: there NetEase was a third opinion voting on
> where each LINE begins, against two sources more likely to be holding
> the same master, and it pulled line starts around. Here it is doing the
> thing it is actually good at -- saying where each word lands inside a
> line somebody else has already placed.
>
> Worth its own slot because QQ and NetEase, unlike QQ and Kugou, are not
> the same data: on NF's "If You Want Love" they agree on where a line
> starts to within 0.19s everywhere, and on where the WORDS fall only 30%
> of the time within 50ms, one of them by as much as 0.81s.

### `from_triblend`

**line 2990** — from the docstring, `def from_triblend(tid: str, meta: dict, local=None, above=None) -> dict | None:`

> Apple's lines, NetEase's words, and QQ for the lines NetEase misses.
>
> The three-way blend that was here before asked all three sources about
> every line and let them vote, and it was bad at it -- NetEase is the one
> least likely to be holding the same master, so its vote dragged line
> starts around on songs the other two agreed about. This is the other way
> round: one donor times the words, and the second is asked only about the
> lines the first could not place -- either because it had nothing for them
> or because what it had landed somewhere the line sync says the line is
> not. Nothing is voted on and nothing is averaged; the question put to the
> second donor is the same one, line by line, and its answer is taken whole
> or not at all. See _astray.
>
> NetEase goes first because it is the steadier of the two where both have
> the song -- measured against a hand-timed reference, its words wobble
> 0.079s against QQ's 0.099s -- and QQ covers more songs, which is exactly
> what a filler is for.
>
> Goes first, not always first. Steadier in general is not steadier on this
> song, and where NetEase's whole clock sits further from the base's line
> sync than QQ's does, QQ times the words and NetEase fills the gaps. See
> in_order.

### `from_kutriblend`

**line 2997** — from the docstring, `def from_kutriblend(tid: str, meta: dict, local=None, above=None) -> dict | None:`

> The same three-way again, with Kugou filling the lines NetEase misses.
>
> Kugou and QQ are not a second opinion. They are the same data: over the
> 22 songs in this cache that both answer for, their word onsets agree on
> 100% of words to within 70ms, with a median offset and a median scatter
> of 0.000s each -- they are writing the same numbers. (from_kublend says
> the same from a smaller sample; eval_sources.py --donors is what measured
> this one.)
>
> So this is a second DOOR, and that is the whole of what it is for: the two
> fail separately. Measured against triblend over 30 songs, the two came
> back as the same document wherever both answered -- identical scatter on
> 17 of the 23 they both scored, and never more than 9ms apart on the rest
> -- and the entire difference between them was three songs where QQ's door
> returned nothing at all and Kugou's returned 150 timed lines. Never the
> other way round.
>
> Neither fills BETTER, because there is nothing to choose between the
> numbers they write. This one just answers more often.
>
> Which of the two leads is still decided per song, as in from_triblend:
> being the same document as QQ, Kugou is the same second opinion about
> which pressing NetEase is holding.

### `_peel_aside`

**line 3046** — from the docstring, `def _peel_aside(new: dict, q: dict, qit: list, start, end):`

> Lift a trailing ad-lib out of a line the donor times without it.
>
> Apple writes one line where the donor writes two:
>
>     Chillin' in the back like, "Hey" (Oh, God)
>     No nominations, but it's cool though, oh, God
>
> and QQ times 'Chillin' in the back like "Hey"' then 'Oh God', and
> 'No nominations but it's cool though' then 'Oh God'. Relaying one onto
> the other leaves everything past the donor's last word stuck to a single
> syllable, so the tail fills in one lump while the donor's timing for it
> sits unused in the next line down.
>
> The brackets are not the signal and never were -- the second line has
> none. What says so is that the donor's line for this line is a PREFIX of
> it: the donor split where we did not. Two conditions, both required:
>
>   * everything the donor's paired line says is the start of what ours
>     says, and there is something left over;
>   * some other line of the donor's says exactly the leftover, near
>     enough in time to be this line's.
>
> Returns the backing group with the donor line it came from, and shortens
> the line's own text; or None, which is the answer whenever either
> condition is in doubt.

### `_kin`

**line 3089** — from the docstring, `def _kin(one: str, two: str) -> bool:`

> Whether two shouts are the same shout, however many times it is
> written down: "yes" against "yesyes", "woo" against "woowoo".
>
> Containment alone is not enough for anything but a line already known to
> be an ad-lib -- "you know" is inside "Heard the catalog, you know I got
> some scars on me" -- so what is left of the longer one once the shorter
> is taken out of it has to be next to nothing.

### `_doubled`

**line 3140** — from the docstring, `def _doubled(out: list, key: str, at: float, until: float) -> bool:`

> Whether the document already sings these words across these seconds.
>
> An ad-lib is a SECOND voice. Where the words are on the screen already --
> as a line's own lyric, or as an ad-lib another donor has lent it -- adding
> them again does not add a voice, it draws the one that is there twice.
>
> The hand-timed files here are what settles it. Apple writes "It never goes
> away" over Linkin Park's own "Never goes away" and Dua Lipa's "Ooooh break
> my heart" over "Ooh, break my heart"; the hand-timed Figure.09 and Break
> My Heart write each of those once, as plain consecutive lines. What they
> do keep is a background whose words are NOT the line's -- "Get away from
> me" under "It never goes away" -- which is why this asks about the words
> and the seconds together rather than about either alone.

### `_place_dark`

**line 3151** — from the docstring, `def _place_dark(out: list, qit: list, spoken: set) -> None:`

> A line nobody could match by its letters, given the stamp of the donor
> line left standing where it belongs.
>
> A donor that mishears a line writes a different line. On slayr's
> "Eyesight" Apple has "In your life (In your life)" where NetEase and QQ
> Music both heard "And you'll learn (And you'll learn)" -- the same second
> and a half of the same recording, 0.52 alike by their letters, so the
> pairing, _near_pairs at 0.75 and _restream's cut all walk past it. Apple's
> document for that song is words only, so the line was left with a stamp
> from nobody at all and came out of the blend as bare text: on the screen
> for the whole song, lit up never, twice.
>
> Only for a line with no time at all. One that has its own loses nothing by
> going unpaired, and this leaves those alone.
>
> So it asks the one question the letters cannot: our line has a lit line
> either side of it, and exactly one line of the donor's is still standing
> free in the hole between them -- then they are the same line, whatever
> either side heard. One line and no choice to make is the whole of the
> test; two, and it declines, because picking between them is the guessing
> this is here to avoid. Shouting is not a candidate: an ad-lib in the hole
> is an ad-lib, and _lift_strays is what that is for.
>
> Only the timing is taken, which is what a donor is for in a blend. The
> words stay the base's -- the donor misheard this line, and that is the
> reason it is here at all.

### `_lift_strays`

**line 3186** — from the docstring, `def _lift_strays(out: list, qit: list, spoken: set, slid: dict) -> None:`

> The donor's ad-libs that our lines have no place for, lifted onto them.
>
> QQ Music and Kugou file an ad-lib as a line of its own far more often than
> Apple does, and where Apple has not written it at all there is nothing for
> the line-by-line pairing to attach it to -- so it was dropped, timing and
> all. NF's SUFFICE is the plain case: through the first chorus QQ times
> "Yes", "No", "Woo", "Ayy", "Want a slice" as their own lines and Apple
> writes none of them, while in the LATER chorus Apple writes the same
> ad-libs inline and they come through as backgrounds. The same voice, in
> the same song, appearing only when Apple happened to type it.
>
> Only two kinds are lifted, because the cost of being wrong is a real
> lyric drawn as an afterthought:
>
>   * the shouting -- every word of it in CRIES, the same test fold_cries
>     uses on a document's own lines;
>   * an echo -- words another of the donor's own lines is singing across
>     this stretch of the song, which is what a backing vocal repeating
>     the hook is.
>
> That second test asks the donor rather than the base on purpose. Where
> the base writes one line and the donor writes two, the donor's second
> line is the rest of the lyric, not an ad-lib: on the same song QQ times
> "Stop complainin', man, my head hurts" and then "These catchy records",
> and Apple writes them as one line. Read against the base's text those
> three words look like an echo of words the line already has -- the base
> does have them, further along. Read against the donor's own lines over
> the same seconds, nobody has sung them yet, and they are left where they
> are. The same test keeps "We ain't never spoke", "Uncertain" and "We're
> all hypocrites" out of the margin on this one song, all of them the
> second half of a line Apple wrote whole.
>
> Anything the base already writes in brackets is left alone: that one has
> a home in the lyric and, more often than not, _peel_aside has already
> given it its timing. Matched loosely, because the two rarely write the
> shout the same number of times -- Apple's "(Yes)" against QQ's "Yes yes".

### `_our_words`

**line 3272** — from the docstring, `def _our_words(inner: str, syls: list) -> list:`

> The base's own words for an ad-lib, on the donor's clock.
>
> The two write the same shout differently often enough that the letters
> will not always line up -- "(Ooh)" against "Woo", "(Woo, woo)" against a
> single "Woo", "(Out of sight)" against "I'm out of sight out of sight".
> What is on the screen should still be what the lyric says, so the words
> are the base's in every case and only the timing is borrowed:
>
>   * where the letters do line up, straight through _relay, which is one
>     stamp per word;
>   * where they line up against PART of the donor's line, the same, over
>     the run of syllables that says it;
>   * failing both, one stamp across the whole of it. unlump cuts that into
>     words afterwards, and marks them as the guesses they are.

### `_peel_bracket`

**line 3299** — from the docstring, `def _peel_bracket(new: dict, pool: list, start, end, spoken: set) -> list:`

> Ad-libs the base writes into the line, given the timing a donor has.
>
> Apple marks a backing vocal by writing it in brackets inside the lead's
> own text -- "Yeah, if I did it, then I did it right (Yes)". Read as text
> it is sung by the lead voice, in the lead voice's place on the screen,
> and its words fill in whenever the last word of the line does. Somebody
> else usually knows better: QQ times that "Yes" as a line of its own, and
> with it the bracket can come out of the lyric and be what it is.
>
> _peel_aside does this from the other side -- OUR line runs past where the
> donor's stops -- and only where the donor's text matches the leftover
> exactly. Neither holds here. The line is identical to the donor's own,
> brackets and all, in the three-way where the lines come from NetEase; and
> the two sides rarely write a shout the same number of times, Apple's
> "(Woo, woo)" against QQ's "Woo". So this one takes the bracket as the
> signal, which for a document that uses brackets this way it is, and
> matches the shout loosely.
>
> The words that reach the screen are still the base's: the donor's
> syllables are cut points for what Apple wrote inside the brackets, which
> is what _relay is for. Anything the pool cannot time at about the right
> moment is left in the lyric exactly as it was.

### `_stamped`

**line 3350** — from the docstring, `def _stamped(doc):`

> A document with the syllables nobody has timed yet left out.
>
> parse_ttml keeps those now -- a file being written carries its words long
> before it carries their timings, and this project's own editor saves that
> file every half minute. The blender is not written for them: every
> question it asks of a syllable is where it sits in time, and a syllable
> with no time has no answer to give. They come off here, once, rather than
> being guarded against at each of the thirty places downstream that ask.
>
> Nothing is edited in place -- the caller's document is somebody else's,
> usually a cache entry -- and a document with no untimed syllables in it is
> handed straight back.

### `_blend`

**line 3391** — from the docstring, `def _blend(base: dict, words: str, qq: dict | None, ne: dict | None,`

> The documents reconciled into one. Split out so it can be tested on
> fixed inputs rather than on whatever the servers feel like saying.
>
> `ne` is a third opinion on line starts. Nothing passes one any more; the
> parameter stays because every "who moved this line" branch below is
> written around having more than one opinion to weigh, and collapsing that
> to a single voice would rewrite the reconciling rather than simplify it.

### `_blend.worded`

**line 3403** — from the docstring, `def worded(m, items, i) -> bool:`

> Whether line i would actually come out with words on it.
>
> Having a pairing is not the same as having timings, in two ways. A
> donor with only line stamps pairs with everything and places nothing,
> which is how NetEase's line-level copy of SICK SICK SICK filled every
> slot in the map and left the song bare. And a pairing to the wrong
> line relays nothing: on NF's MOTTO the last "Yeah" was paired to a QQ
> line whose letters are not its letters, so it came out untimed while
> the re-stream had the right syllables for it and was never asked,
> because the map said the line was spoken for.
>
> So this asks the question the loop below will ask, rather than the
> one the map answers.

### `_comparable`

**line 3811** — from the docstring, `def _comparable(a: str, b: str) -> bool:`

> Whether two names are written in the same kind of script.
>
> Two spellings of one artist in one alphabet can be compared, and a
> disagreement between them means something. "YOASOBI" against a
> catalogue's "ヨアソビ" is not a disagreement -- it is the same name
> written the only way that catalogue writes names -- and reading it as one
> would throw away the hits this program exists to find.

### `_same_artist`

**line 3840** — from the docstring, `def _same_artist(theirs: str, ours: str) -> tuple[bool, bool]:`

> (the lead is the same person, anybody is), by name.
>
> Two answers because they are worth different amounts. A shared LEAD is
> what tells S.L.I.D.E by Tory Lanez from Slide by Packy featuring him: the
> titles normalise to the same five letters and the durations are six
> seconds apart, so the lead credit is the only thing left that differs.
> Anybody in common is weaker but still worth having -- sources disagree
> about who leads a collaboration often enough that demanding the lead
> would throw away real hits.
>
> Both true where either side has no credit at all: an unnamed artist is
> not evidence of anything, and Kugou leaves the field empty often enough.

### `_cut_words`

**line 3855** — from the docstring, `def _cut_words(text: str) -> set[str]:`

> The version markers a title carries, spelling flattened.
>
> Run over a title with its camel case pulled apart, because Kugou files
> the one this was written for as "Galaxies (RogueRemix)" -- no space, and
> so no word boundary for `\bremix\b` to find. The capital is the boundary
> there, and it is the only place the missing space can be read from.

### `_same_song`

**line 3889** — from the docstring, `def _same_song(theirs: str, ours: str) -> bool:`

> Whether two titles name the same song, allowing for a longer one.
>
> Deliberately generous in ONE direction only: a source is allowed to have
> "Stronger (Radio Edit)" where we asked for "Stronger", because that is
> the same recording described at more length. It is not allowed to answer
> for something that merely contains our words, and -- see ALT_CUT -- not
> for something whose extra words say it is a different recording.

### `_unison_doc`

**line 3922** — from the docstring, `def _unison_doc(rec: dict) -> dict | None:`

> One Unison record as a document, with the person who timed it on it.
>
> Unison names its submitter in the record and nowhere in the TTML, so a
> document that went through the parser alone arrived anonymous -- and on
> this source, of all of them, that is the credit that matters. Nobody was
> paid to time these: somebody sat down and did it, and the only place they
> are named is a field the lyrics do not carry.

### `_people_of`

**line 3931** — from the docstring, `def _people_of(row: dict):`

> A Unison record's submitter, in the fields a document carries them in.
>
> Unison names its submitter in the record rather than in the TTML, so a
> search row that has not been turned into a document yet and the document
> _unison_doc builds both get this, and the roster answers the same
> question about both.
>
> `keyId` is the account itself and the display name is only what it is
> called today, so the id rides along as `_maker_id` -- prefixed, because
> it is Unison's to hand out and means nothing on any other source.

### `from_unison`

**line 3970** — from the docstring, `def from_unison(tid: str, meta: dict, local=None) -> dict | None:`

> Unison -- the Better Lyrics community's own database.
>
> The only source in this chain whose documents were typed in by the people
> reading them. There is no catalogue behind it and nothing is scraped: a
> song is there because somebody sat down and timed it, which is exactly
> why it is worth asking. It answers for tracks no licensed source carries,
> and it answers in TTML with real word timing.
>
> The same thing makes it the one source here that can be somebody's first
> attempt, so a hit found by searching has to clear a duration check and
> carry its own votes; Unison scores every document low/medium/high and the
> hint is taken. A direct hit is trusted as it stands -- the server already
> matched it -- but its duration is still checked, because the query is
> name-shaped and names repeat.

### `_plain_page`

**line 4103** — from the docstring, `def _plain_page(url: str) -> str:`

> A plain fetch of a web page or its JavaScript, gzip and all.
>
> Not _get: that one is the chain's funnel, with the chain's timeouts and
> its per-host gate, and this is a three-megabyte JavaScript bundle read
> once a day. It also has to say it is a browser to be given the bundle at
> all. Apple Music's catalogue token and SoundCloud's client id are both
> read out of a bundle this way; see _apple_token and _sc_client_id.

### `_apple_token`

**line 4117** — from the docstring, `def _apple_token(force: bool = False) -> str:`

> The music.apple.com web player's catalogue key, cached until it expires.
>
> Apple's catalogue API needs a developer token and the web player carries
> one in its own JavaScript bundle -- the same one handed to every visitor.
> It is read from there, checked against the API once, and kept on disk with
> the expiry Apple stamped into it, because the bundle is megabytes and this
> is a lookup of one field.
>
> The bundle holds more than one JWT and only one of them is the catalogue
> key, so they are tried in turn rather than guessed at by shape. Under a
> lock, because a walk is ten threads wide and the look-ahead is warming
> three more tracks: without it a cold cache is a dozen threads each pulling
> the same bundle.
>
> The same trick editor/sources.py plays for Apple's songwriter credits,
> and deliberately a second copy of it: this module is the one every
> provider lives in and it does not import the editor, or the GUI, or
> anything else that could make a lyric fetch depend on a window existing.

### `_amp`

**line 4159** — from the docstring, `def _amp(token: str, path: str, store: str = ""):`

> One catalogue request, or None.
>
> `store` names a storefront other than the default one. The catalogue is
> the same catalogue either way -- the same recordings under the same ISRCs
> -- but each storefront writes the names in its own language, which is the
> whole reason for asking a second one. See NATIVE_STORE.

### `apple_art`

**line 4195** — from the docstring, `def apple_art(art: dict, size: int = 1000) -> str:`

> One artwork url out of Apple's template.
>
> Apple hands the address over with the size left blank --
> ".../{w}x{h}bb.jpg", and sometimes the crop and the format as well -- so
> it is filled in here and everything downstream gets a plain url to fetch,
> the way every other source gives one.

### `apple_song`

**line 4205** — from the docstring, `def apple_song(meta: dict) -> dict:`

> What Apple Music's catalogue has for this track, asked once.
>
> Three things come back and one request brings all of them: the ISRCs,
> which name the recording BiniLyrics files its TTML under; the
> songwriters, which Apple gives as the publishing credit -- legal names,
> every co-writer, on very nearly everything it has; and the card, which is
> the cover, the album and the rating.
>
> The card is here because of the players that have none. Spotify hands
> over a square cover and the album it belongs to; a browser hands over a
> video's thumbnail, or nothing, and a title where the album should be. The
> catalogue this already asks about the words has the cover too, so it is
> taken while the answer is open rather than asked for again later.
>
> Asked once per track however many callers want it, because they are two
> unrelated errands that happen to share an answer: from_bini wants a key
> to look up, _credited wants a list of names, and neither should cost the
> other a request. The pair are only fetched together because the search
> already returns them both; nothing here asks Apple twice.
>
> More than one ISRC, because a song is issued more than once -- the album
> cut, the single, a remaster, a regional edition -- and they are all the
> same lyric with the same timing. BiniLyrics may hold the TTML under any
> one of them, so the ones that match are all worth trying, in the order of
> how well they match.
>
> Matched on the same three things every other source here is matched on:
> the title allowing for a longer one, somebody in common on the byline,
> and the duration. The duration is the one that separates the album cut
> from the live version -- Apple has "Clocks" at 306.9s and "Clocks (Live)"
> at 285.0s, and only one of them is the recording anybody is playing.

### `_confirmed`

**line 4282** — from the docstring, `def _confirmed(named: dict, billed: dict, want: float) -> list:`

> Recordings both writings of the catalogue agree about, by ISRC.
>
> The last resort, and not a loose one. Spotify hands over a native title
> with a romanised artist -- "感電" by "Kenshi Yonezu" -- and neither
> storefront writes both of those: `us` has "Denki" by "Kenshi Yonezu",
> `jp` has "感電" by "米津玄師". Asked of either alone the song is missed,
> and asked of either alone with one half of the test dropped it is worse
> than missed: every Kenshi Yonezu track of about the right length matches
> on the artist, and the first of them is a different song.
>
> A recording named by one storefront and billed by the other is checked on
> the title, the artist AND the duration, same as anything here -- the three
> answers are simply spread across two writings of the same entry, and the
> ISRC is what staples them back together.

### `_cover_cut`

**line 4300** — from the docstring, `def _cover_cut(rows: list, album: str = "", title: str = ""):`

> Which of several copies of one song the cover should come from.
>
> NOT the closest duration, which is what the ISRCs are ranked by. Asked of
> "Hymn for the Weekend" that picks a Coldplay compilation over A Head Full
> of Dreams, because the compilation's cut is half a second nearer -- the
> right recording and a cover nobody would recognise.
>
> The earliest release is the album the song came out on; anything later
> carrying the same recording is a compilation of it. Where two say the
> same day, Apple's own order of relevance decides, which is what put the
> real album first in that example and every other one tried.
>
> The album the caller names comes first: Apple dates a compilation's copy by the recording.
> Then the title as asked over a tagged one: "Lost (PLZ Tethered Version)" came out 4 days before "Lost".

### `_apple_card`

**line 4313** — from the docstring, `def _apple_card(at: dict | None, meta: dict) -> dict:`

> The catalogue's own description of a track, for a player with none.
>
> Empty where nothing matched, and every field empty where Apple left it
> empty -- the caller fills in around what it already has rather than
> trusting this over it.
>
> `sure` is whether the match had anything real to go on. The search is
> matched on three things and two of them can be vacant: a card with no
> artist matches anybody, and one with no duration matches any length. A
> title alone is not enough to rename somebody's song by, so where that is
> all there was, the answer is offered as a cover and not as a name. See
> LyricsView.on_card.

### `soundcloud_card`

**line 4408** — from the docstring, `def soundcloud_card(meta: dict) -> dict:`

> What SoundCloud has for this track: the cover, and little else.
>
> Matched the same way as everything else here -- the title, somebody on
> the byline, the duration -- with one extra allowance. A SoundCloud title
> is very often "Artist - Title", the artist written twice over, so the far
> side of the dash is tried as the title as well. Without that, the
> uploader's own habit is what loses the match.
>
> The duration is allowed to disagree. An upload is edited, a radio cut, a
> version with the tag on the front; that makes it the wrong recording to
> take an ISRC from and the right one to take a cover from, since it is
> still the same release. A byline that agrees is what carries it instead,
> and nothing without one is taken at all.

### `track_card`

**line 4452** — from the docstring, `def track_card(meta: dict) -> dict:`

> What the catalogues know about a track, for a player that says little.
>
> Apple Music first and for everything, because its catalogue is edited: it
> is where the song's name is spelt the way the label spells it, which is
> what a YouTube upload shouting the artist in capitals is not. SoundCloud
> after it and for the cover alone -- see soundcloud_card -- because the
> songs Apple has never heard of are very often there.
>
> {} where neither knows it, and the player's own card stands.

### `apple_writers`

**line 4472** — from the docstring, `def apple_writers(meta: dict) -> list[str]:`

> Apple Music's songwriter credit, one name each.
>
> The publishing credit rather than an editor's: where Genius has "Ink" and
> "Sounwave", this has "Roshwita Larisha Bacha" and "Mark Anthony Spears".
> It is the credit Apple's own TTML carries, which is what most of the
> documents in this chain are copies of -- so filling a gap from here fills
> it with the same names the file would have had if the copy that reached
> us had kept them.

### `from_bini`

**line 4484** — from the docstring, `def from_bini(tid: str, meta: dict, local=None) -> dict | None:`

> BiniLyrics -- Apple Music's TTML, reached by a different key.
>
> The words are the same ones Apple Music hands over, so this is not a new
> catalogue; it is a door on that one, and the only one left now that
> LyricsPlus' is gone. What makes it the good door is what it is indexed by:
> every other source here is found by a Spotify id or by the words in a
> title, and this one is found by ISRC, which names the recording rather
> than the song.
>
> So the ISRC is worth going and getting. It is asked of Apple Music's own
> search -- the same catalogue, so its answer is the key this door files by
> (see apple_isrcs) -- and both ways of asking go out at once, because the
> name query is one request against a database and there is no sense making
> the answer wait behind a lookup it does not need. Where the ISRC lands a
> document that is the one taken: it cannot be the wrong recording, and the
> name query can. Where it does not, nothing is lost that was ever there.
>
> `meta` may carry an ISRC of its own, and it is believed over Apple's --
> a caller that knows the recording knows better than a search does.
>
> The lyrics live at a URL of their own, one fetch further on. It is
> followed only when it stays on the host that named it -- a document is
> worth having, a redirect somewhere else is not.

### `from_bini.by_isrc`

**line 4502** — from the docstring, `def by_isrc():`

> Every pressing's rows, up to the first that is word-timed.
>
> NOT the first code that answers at all, which is what this did and
> what cost Sweater Weather its word sync. Apple issued that recording
> three times -- the album, the anniversary edition, and the EP it came
> out on first -- and BiniLyrics holds the album's two word-timed and
> the EP's line-timed. The codes are ranked by how near each pressing's
> duration is to the track being played, so the EP sorts first the
> moment the length in hand is the EP's 240.04 rather than the album's
> 240.4 -- which is exactly what happens once Apple's own card has been
> asked for, since the card takes its cover from the earliest release
> and its length from the same row (see _cover_cut, and card_len in
> lyrics_gui). One line-timed pressing then shut out two word-timed
> ones, and the blend built on those lines is what reached the screen.
>
> Merging them is not a looser match. This module's whole reason for
> keeping more than one ISRC is that they are the same lyric with the
> same timing, issued more than once -- so between two copies of it the
> question is which is better TIMED, and that is _bini_pick's to answer
> rather than the duration ranking's. Quality outranks order here as it
> does everywhere else in this walk.
>
> It costs nothing where the best-matching pressing is word-timed,
> which is the common case: the loop stops on the first word row. It
> costs the two extra lookups only where the alternative was handing
> back a line sync, and it already spent them where an earlier code
> answered with nothing.

### `_bini_pick`

**line 4539** — from the docstring, `def _bini_pick(rows: list, title: str, want: float, checked: bool) -> tuple:`

> The best of one lookup's rows, as (the URL its TTML is at, its timing_type).
>
> `checked` says the rows came back from a query that only matched on the
> words in a name, so the title and the duration are looked at again here.
> Rows fetched by ISRC are not checked: the ISRC IS the check, and it is a
> stricter one than any string comparison -- a remaster with a different
> title and a different length is still not the recording that code names.

### `_krc_items`

**line 4668** — from the docstring, `def _krc_items(text: str) -> list[dict]:`

> KRC -> timed items.
>
> A line is `[start,length]` and then one `<offset,length,0>` per syllable,
> the offset measured from the line rather than from the song. Kugou writes
> the credits as lyric lines like NetEase does -- and, unlike NetEase, often
> writes the artist and title as the first sung line too, timed across the
> intro -- so the same credit filter runs here.
>
> Returns the lines and whoever those credits named, since the credit lines
> are the only place Kugou says.

### `_instrumental`

**line 4682** — from the docstring, `def _instrumental(items: list[dict]) -> bool:`

> Whether this document is a note saying the track has no words in it.
>
> Kugou and NetEase both answer for an instrumental with a single line
> reading 纯音乐，请欣赏 -- "instrumental, please enjoy" -- stamped across the
> whole song. Taken at face value that is a word-timed document, and a
> word-timed document beats every real lyric further down the chain: on
> passengerprincess' FINALE it was on the screen as the lyric while NetEase
> was holding the words.
>
> LRCLIB's version is a lone ♪ stamped at 0:00 -- wiv's "i love u." has a
> dozen such records and nothing else -- which says it by having nothing in
> it a voice could sing: no letter or digit anywhere.
>
> Only ever a note: three lines at most, and one of them has to say it.

### `wordless`

**line 4691** — from the docstring, `def wordless(doc) -> bool:`

> Whether a provider's answer is only the note that there are no words.
>
> The providers that serve a catalogue check for it themselves, above. The
> community ones do not: Unison answered Instupendo's "Comfort Chain" with a
> Static document reading "[Instrumental]", and it went on the screen as the
> lyric. So _asks puts every answer through this, whoever it came from.

### `instrumental_cut`

**line 4702** — from the docstring, `def instrumental_cut(title: str) -> bool:`

> Whether a track's own title says it is the instrumental of a song.
>
> "'Bout It (Instrumental)", "Gillette - Instrumental", "(Inst.)", "(Off
> Vocal Ver.)". Such a track has nothing to sing along to, but every source
> that matches by name finds the song it is the instrumental OF: Musixmatch's
> matcher answered JMSN's "'Bout It (Instrumental)" with the vocal cut's word
> timing. So it is not asked for at all.
>
> Only a version marker counts -- bracketed, or after a dash -- never the
> word anywhere in a title. Karaoke cuts are left alone: people sing along
> to those, and the words are what they are for.

### `_krc_head`

**line 4708** — from the docstring, `def _krc_head(items: list[dict], title: str, artist: str) -> list[dict]:`

> The lyrics with Kugou's own title card taken off the front.
>
> Nearly every KRC opens with "artist - title" timed across the intro, as a
> line of the song. It is not one -- nobody sings it -- and left in it takes
> the whole introduction as its own line and lights up while the music is
> still playing.

### `_kugou_hits`

**line 4825** — from the docstring, `def _kugou_hits(title: str, artist: str, want: float) -> list[tuple]:`

> (hash, milliseconds) for the Kugou recordings that look like this one.
>
> Kugou's search answers for anything, so nothing is believed on the name
> alone: a hit needs the duration, and the title has to survive being read
> out of "artist - title", which is the only place the search puts it.
>
> And it needs the ARTIST, which is the check this went without and which
> a short title cannot do without. "S.L.I.D.E" normalises to "slide", and
> _same_song lets a longer title contain a shorter one -- for "Stronger
> (Radio Edit)", which is what that rule is for -- so a search for Tory
> Lanez's S.L.I.D.E came back with Packy's "Slide (feat. Tory Lanez)" at
> 227s, Calvin Harris, Frank Ocean and Migos' "Slide" at 230s, and the
> right song at 233s, all four inside the six seconds _near allows. With
> only the duration to sort them, the winner was whichever recording our
> copy happened to be nearest in length to, and on a track whose Spotify
> duration is a few seconds off Kugou's that is somebody else's song.
>
> The credit is asked for twice over. A row sharing nobody at all with us
> is dropped, and among those that remain a shared LEAD is preferred to a
> shared guest -- which is what separates the song Tory Lanez made from the
> one he appears on. Duration only breaks what is left.

### `_kugou`

**line 4860** — from the docstring, `def _kugou(tid: str, meta: dict) -> dict | None:`

> Kugou, by way of KRC.
>
> Worth a slot of its own: Kugou times its lyrics per syllable, and its
> catalogue is the Chinese one, which is the half of the library the
> English-speaking sources here are worst at. Where amll and Apple have
> nothing for a Mandarin or Cantonese track this frequently has it, word by
> word, and where they do have it this is a second opinion for the blend.
>
> Three requests deep -- find the recording, ask which lyric documents are
> filed against it, download one -- so the walk stops at the first release
> that answers rather than opening every one.

### `_qrc_tables`

**line 4975** — from the docstring, `def _qrc_tables():`

> Every fixed permutation here, precomputed against the bytes it takes.
>
> sp   the S-boxes with the P-box already applied, per box, per 6 bits
> exp  the expansion, per byte of the half-block it expands
> ipl  the initial permutation's left half, per byte of the block
> ipr  ...and its right half, which reads the bit one to the left

### `_qrc_f`

**line 5018** — from the docstring, `def _qrc_f(state: int, key: bytes) -> int:`

> DES's round function: expand to 48 bits, key it, S-box it, permute it.
>
> Textbook from here down -- the expansion, the boxes and the P-box are the
> real DES's, and only the two typo'd entries in QRC_SBOX are QQ's. All of
> it is read out of _qrc_tables; the P-box is already folded into the
> S-box answers.

### `_qrc_items`

**line 5155** — from the docstring, `def _qrc_items(text: str):`

> QRC -> timed items, and whoever its credit lines named.
>
> A line is `[start,length]` and then one `word(start,length)` per syllable,
> with the word BEFORE its stamp and every time measured from the song --
> where Kugou writes the stamp first and measures it from the line. The rest
> is the same shape, credits and backing vocals included, so the same
> filters run over it.

### `_qq_hits`

**line 5164** — from the docstring, `def _qq_hits(title: str, artist: str, want: float) -> list[tuple]:`

> (id, the name and byline QQ files it under) for its likeliest copies.
>
> The desktop search every other client reaches for is behind a login now --
> it answers `code 2001` and a sign-in URL to an anonymous caller, whatever
> headers it is given -- so this asks the older one, which still answers and
> still carries the duration a match has to be checked against.
>
> Believed on the same three signals Kugou's hits are: the title, the
> byline, the length. QQ's search is as willing as anyone's to answer for a
> song it does not have.
>
> QQ's own spelling of the title comes back with the id because the lyric
> needs it: the document opens with a title card written from these strings
> and not from ours, so ours cannot recognise it.

### `_qq_head`

**line 5193** — from the docstring, `def _qq_head(items: list[dict], name: str, artist: str,`

> QQ's own furniture taken out of the lyric.
>
> Two pieces of it. The first line is a title card -- "Clocks - Coldplay" --
> timed across the introduction like Kugou's, but _krc_head cannot be the
> thing that drops it, because it asks for the card to spell the title and
> the byline exactly as we hold them and QQ's card does neither. It writes
> "Time - NF" for a song QQ itself files as "Time (Edit)", and where the
> title carries a bracket -- KiiiKiii's "(나 어떡해)" -- _ne_bg has already
> lifted it out of the line as a backing vocal before anyone can compare.
> So the card is recognised by its SHAPE instead: the title and the byline
> either side of a dash, each matched the way a search hit is.
>
> The second is the speaker label. On a collaboration QQ marks the handover
> with a line reading "Lil Peep：", stamped and timed like a verse, and
> white tee carries four of them. A label is only a label when what it names
> is somebody actually credited on the song, which is what keeps this from
> eating a lyric that happens to end in a colon.
>
> Credited on the song, and not only in the byline: a group is billed under
> the group's name and hands over between its members, none of whom the
> byline mentions. Sexion d'Assaut's "Ma direction" is the case -- four
> lines reading "Maître Gims：", timed and drawn like verses, against a
> byline that says "Sexion D'Assaut" and nothing else. What names him is
> the document itself, in the credit block `_qrc_items` has already read
> two lines above the first of them ("Lyrics by：Maître Gims/Lefa/Barack
> Adama/Maska"), so `wrote` is asked as well as the byline. A name QQ went
> to the trouble of filing as this song's writer is not a lyric that
> happens to be a name and a colon.

### `_mxm_token`

**line 5458** — from the docstring, `def _mxm_token(force: bool = False) -> str:`

> The app token Musixmatch hands out, kept on disk between runs.
>
> Not a secret and not a credential: token.get gives one to anyone who asks
> in the iOS app's clothes. But it cannot be asked for often -- a few in a
> row and the endpoint answers 401 `hint: captcha` for a while -- so one is
> fetched, written down, and used until a call comes back unauthorised.
>
> Spicetify ships a shared token as its default, and copying that is the one
> thing not to do: the value in the repository today is already refused.
> Everybody using it is why.

### `_mxm_ask`

**line 5483** — from the docstring, `def _mxm_ask(tid: str, meta: dict, token: str, common: int = 0):`

> Everything Musixmatch has for one track, in one request.
>
> `optional_calls` is what puts the word timing in the answer at all -- the
> macro leaves track.richsync out unless it is asked for by name, and
> without it finding the richsync costs a second round trip.
>
> `track_spotify_id` is what makes the answer the right recording, and it is
> not a nicety. Asked for "In the End" by name and duration the matcher
> returns track 422430305, which has no richsync; asked with the Spotify id
> it returns 15889056, which does. The name query is sent alongside it as
> what to fall back on, the way BiniLyrics is asked by ISRC first.
>
> `common` (a commontrack_id from _mxm_search) asks for that track alone.

### `_mxm_syllables`

**line 5506** — from the docstring, `def _mxm_syllables(row: dict) -> list[dict]:`

> One richsync line's words, with the ends the gaps between them give.
>
> richsync writes the spaces as entries of their own --
> ("It", 0), (" ", 0.06), ("starts", 0.13) -- so the space says when the
> word before it stopped. That is a measured end, and Musixmatch is the only
> source here that has one: NetEase, QQ and Kugou all tile, running every
> word until the next one starts. 2% of Musixmatch's word pairs are tiled
> against 84-90% of theirs.
>
> Measured is not the same as better, and it was worth checking before
> believing: against the hand-timed files in ./lyrics its word ends land
> 0.213s out where the tiled sources land 0.075s out. A hand-timed lyric is
> itself about three quarters tiled, so the invented end is closer to what
> somebody would write than the real one is. The ends are kept because they
> are this document's own; nothing else is built on them.
>
> A gap also ends a WORD, which is what tells the two apart where richsync
> is letter-by-letter rather than word-by-word: two tokens with no space
> between them are one word, however the line was cut.
>
> Where the gap is stamped at the word's OWN offset the measurement says the
> word stopped the instant it started, which is not a short word but a
> missing reading, and the view draws it as a word that never lights at all.
> They are left standing here and repaired in _mxm_spans, which can see the
> whole document and so can see how long a word of this one runs for.

### `_mxm_spans`

**line 5532** — from the docstring, `def _mxm_spans(out: list) -> None:`

> Musixmatch's word ends, made ends a reader can see.
>
> Two passes, because there are two things wrong with them.
>
> First, a word whose end is its own start never lights at all, and richsync
> writes a good many: 29 across the eight tracks measured here, 27 of them
> the last word of their line, where it ends the line exactly where that word
> begins. Nothing can be read off a reading like that, so the word is given
> the LENGTH of the words beside it -- the median of its own line's timed
> words, which tracks a verse sung faster than its chorus, and the whole
> document's median where a line has none to offer. Clamped to the next
> onset, so the repair is never the longest word on the line.
>
> Then the gaps. Musixmatch stops a word where the singing stops rather than
> running it to the next one -- only 0-4% of its pairs meet end to end -- and
> at the scale a lyric is read at, a tenth of a second of dead air in the
> middle of a phrase reads as the word cutting out, not as phrasing. So a gap
> shorter than MXM_GAP is closed onto the next word's start, and one longer
> than that is left standing, because at that length it is a rest somebody
> actually took. This is what makes the first pass show: without it a
> repaired word ends a fifth of a second before the next begins and still
> looks like it stopped dead.

### `mxm_explicit`

**line 5628** — from the docstring, `def mxm_explicit(tid: str, meta: dict) -> str:`

> Musixmatch's word on whether this RECORDING is explicit.
>
> "explicit", "clean", or "" for no answer -- and "" is the common case, so
> nothing may read silence as either one.
>
> Worth more than a catalogue search because of how the ask is addressed:
> `_mxm_ask` sends `track_spotify_id`, so what comes back is the row for the
> very track the player has open rather than for the song in general, and a
> clean edit and an explicit master are two different tracks with two
> different ids. Where the id misses and the name query answers instead, the
> row is about the song and the flag is worth less -- but a name match that
> lands on the wrong master is already the thing every mask rule here is
> written to survive.
>
> Second to the player's own flag, not first: where Spotify itself has
> answered, nothing was searched for and nothing can have been mismatched.
> This is what the transports that hand over no flag fall back on.
>
> Costs no request of its own: this is the same answer `from_musixmatch`
> fetches, memoised, and Musixmatch is the first donor uncensoring asks
> anyway. See UNMASK_FROM.

### `_musixmatch`

**line 5638** — from the docstring, `def _musixmatch(tid: str, meta: dict) -> dict | None:`

> Musixmatch's own door, and no other.
>
> Ranked where Musixmatch already was, next to last, and that is where it
> belongs rather than where its word timing would put it. Over the 46 songs
> with a hand-timed file here, 32 come back word-timed against none at all
> through the scrape -- but on the 22 that a blend also word-times, the
> blend is the closer document on 20: 4% of its words more than half a
> second out of step with their own song against 20% of these. fallback()
> lets quality outrank order but only between different qualities, so the
> blends keep every one of those.
>
> What it is for is the songs nobody above it has word-timed at all. It
> wins the chain once over those 46 -- they are the songs somebody cared
> enough about to hand-time, so they are the well-covered ones -- and four
> times over 40 tracks taken at random from this library. Two of those four
> turn a line-synced song word-synced (wifiskeleton's "isnt it obvious",
> DAMAG3's "SHOULD i STAY?"), and the one over the 46 is xaviersobased'
> "love hate", whose words land 1% out. The other two take a song off
> `local`, which is what a machine alignment sitting last is for.
>
> The LyricsPlus scrape used to stand behind this one -- it needed no token
> and it answered for tracks the macro cannot match -- and what it brought
> was line-level, from a source that sat next to last precisely because
> its line-level copy was not worth much. Ten seconds of the walk, inside
> the round the blends wait on, for a document ranked below almost
> everything that had already answered. That source is gone altogether now.

### `_mxm_writers`

**line 5740** — from the docstring, `def _mxm_writers(*bodies) -> list[str]:`

> Songwriters, out of whichever copyright line came back with the words.
>
> Musixmatch has a writer_list field and leaves it empty; what it fills in
> is the copyright line -- "Writer(s): Joseph Hahn, Chester Charles
> Bennington, ..." -- so that is where they are read from, the same way
> NetEase's are read out of its credit lines.

### `genius_token`

**line 5762** — from the docstring, `def genius_token() -> str:`

> The Genius token, read out of the player's own settings file.
>
> Read here rather than handed in, because a provider is given a track and
> nothing else, and this is the only one of them that needs a credential
> belonging to the user. The backup is read as well: the player rotates
> gui.json to gui.json.bak on every write, so a token that is only in the
> older of the two is still the token this machine has. caches.credentials
> reads the same two files, and for the same reason.

### `from_genius`

**line 5776** — from the docstring, `def from_genius(tid: str, meta: dict, local=None, above=None) -> dict | None:`

> Genius' words, with nothing timed.
>
> The only source here that can never answer better than "static", which
> settles where it goes and most of what it does. Quality outranks order
> in both directions, so it cannot take a song off anything that came back
> timed however anybody ranks the list, and it loses a tie with another
> untimed document to whoever is above it -- which is everybody. What is
> left is the songs the rest of them have never heard of, and Genius is
> very good at those: it is edited by people who are listening to the
> song, rather than filed from a label's delivery. A lyric on the screen
> with no clock under it is worth having over the notice that says nobody
> has this one.
>
> It is also the text the local aligner has always taken its words from,
> which until now was the only way any of this reached the screen: the
> aligner had to find a copy of the audio and spend minutes on a GPU
> before Genius could say a word. This is the same document, offered
> directly, on the songs where that never happens.
>
> The search needs the user's own token and there is no anonymous door on
> it, so with none typed in this answers nothing rather than spending four
> queries and three retries each on a 401. That is a source switched on
> and silent, which is the honest reading -- Genius is not reachable
> without it.

### `_genius`

**line 5793** — from the docstring, `def _genius(token: str, meta: dict) -> dict | None:`

> One ask.
>
> This one used to file nothing when the network failed, unlike every other
> provider here: local_align.genius_doc catches its own exceptions and
> answers None, so a Genius outage and a song Genius has not got arrived
> looking exactly alike and the only one of the two worth reporting went
> unreported. It says which now -- `genius_doc.last_error` is empty on a
> miss and carries the reason on a shut door -- so the notification can name
> Genius the way it names everybody else.
>
> local_align is imported here rather than at the top of the file because
> it imports this module; by the time anybody reaches a provider both are
> loaded and the lazy import costs a dict lookup.

### `blend_rank`

**line 5908** — from the docstring, `def blend_rank(order: list, name: str) -> tuple:`

> Where a blend sits, read off the user's ranking of its donors.
>
> There is no second list to keep in step. A blend is Apple's lines with
> somebody else's clock under them, and "somebody else" is a source already
> standing in an order the user wrote; so that order decides this one too.
>
> The TIMING donor decides, not the best-ranked of all of them, because the
> timing donor is whose word timing this actually is. Keying on the best
> instead would hand a user who ranked QQ Music first a NetEase-timed
> document, on the strength of the QQ that only fills its gaps.
>
> A blend carrying a filler goes ahead of the same blend without one -- it
> can only cover more of the song -- and the filler breaks what is left of
> the tie. BLEND_OF is deliberately not read: it is in every tuple, so
> counting it would make every blend tie whenever Apple outranks all the
> donors, which is most of the time.

### `provider_order`

**line 5921** — from the docstring, `def provider_order(order: list, on, blend_on=None) -> list:`

> The providers to consult, in the order the SOURCES were ranked.
>
> The chain speaks in providers and there are more of them than there are
> sources: two doors on Apple Music, and seven blends that put Apple's words
> on somebody else's clock. Each source expands to the providers that answer
> for it, in its own place in the order, so moving Apple Music up the list
> moves everything that speaks for Apple Music with it.
>
> A BLEND GOES IMMEDIATELY ABOVE THE HIGHEST-RANKED SOURCE IT BORROWS FROM
> -- Apple+NetEase above NetEase, Apple+Kugou above Kugou, the three-way
> above whichever of NetEase and QQ Music the user put first. Above all of
> its donors, because it is those donors' clock plus something they have
> not got; below everything that is not one of them, because a document
> built out of two sources cannot claim a place in front of a third that
> lent it nothing.
>
> They used to go in at Apple Music's own slot, ahead of Apple's document,
> on the grounds that they are Apple's lines with word timing added. But
> that slot is usually second, so a blend of two sources ranked sixth and
> eighth arrived in front of amll and Unison, and beat both on a tie -- for
> a clock the user had ranked below them. Where the
> blend really is the better document it still wins: quality outranks
> order in fallback(), and a blend exists precisely to be word-timed where
> its base is not.
>
> The move pays for itself twice over in requests. `above` -- what the
> round before found -- now reaches a blend with Apple's own document
> already in it, so _blended takes its base from there instead of going
> back out for a copy of what BiniLyrics has already handed over.
>
> Among themselves they go in donor order -- they used to go in the order
> this file happens to declare them, which put QQ Music first and, since
> fallback() keeps the FIRST of two equally good answers, meant
> Apple+NetEase won once in 1547 cached walks on the machine this was
> written on. Not because it was worse. Because it was asked fourth.
>
> Only the DONORS have to be switched on. Apple Music used to have to be
> as well, so switching it off took every blend with it -- but the lines
> can come from LRCLIB, Musixmatch or Genius just as well (see _bases), and
> the timing, which is the whole of what a blend adds, was never Apple's.

### `carried`

**line 5942** — from the docstring, `def carried(order: list) -> list:`

> A saved running order, with the sources it predates put where they go.
>
> A source this program gained after somebody last wrote their order is not
> one they ranked anywhere -- it is one they have never seen. Appending it
> files it below LRCLIB and the machine's own alignments, which is the slot
> kept for a last resort, so a source added near the top of SOURCES would
> arrive switched on and never win a song.
>
> Each unseen name goes in behind whichever source precedes it in SOURCES
> and the reader actually has, so it lands among the neighbours it was
> ranked with while every source they did order stays exactly where they
> left it. A hand-written --src-order is deliberately not run through this:
> a list typed out means what it says, and its unlisted names keep their
> documented place at the end.

### `lrclib_first`

**line 5958** — from the docstring, `def lrclib_first(order: list) -> list:`

> A saved order with Musixmatch put back behind LRCLIB.
>
> The default used to ship them the other way round, and a stored order is
> a copy of whatever the default was on the day it was written -- so every
> settings file older than this change still ranks Musixmatch first, and
> changing SOURCES alone would give the new order to new installs and to
> nobody else.
>
> ONLY WHERE THEY ARE STILL SIDE BY SIDE in that order, which is the one
> arrangement nobody can have asked for: moving either of them anywhere at
> all breaks the adjacency, and a reader who did move them keeps exactly
> what they moved. What is left is the shipped default, untouched, which is
> the thing being changed.

### `shown_name`

**line 5973** — from the docstring, `def shown_name(name) -> str:`

> A display name with what cannot be drawn taken out.
>
> Discord names are anybody's choice, and some are chosen to be invisible:
> U+20DF on its own, an enclosing diamond with nothing to enclose, or
> U+1CBC, a code point with no character behind it. Drawn as they are, the
> first came out as a stray "◇" whose zero width threw the rest of the
> credit off its measurements -- the link under "TX26" landed half a name
> to the left of the name. Control, format and unassigned characters go,
> and so does a combining mark with no letter in front of it. What is left
> is the name; "" where nothing was.

### `people_of`

**line 5988** — from the docstring, `def people_of(v) -> list[dict]:`

> A credit slot as the people in it: a name each, and an id where there is one.
>
> Spicy Lyrics writes Maker and Uploader as one {id, username, avatar}
> object each, and its own UI reads them that way. But a sync can have more
> than one author, and the day the field grows into a list is not a day this
> should quietly show nothing -- so an object, a list of them, and a bare
> name are all read the same. An empty {} is how "nobody is credited here"
> is spelled, and comes back as nobody rather than as a blank name.
>
> THE ID IS THE POINT OF THIS SHAPE. A Spicy Lyrics display name is the
> person's to change whenever they like, and a roster that knew them only
> by the name they had last month quietly stops refusing -- or preferring --
> the very person it was written about. The id underneath it does not move,
> so it is carried alongside the name from here to the roster and back out
> to the settings file. Spicy Lyrics publishes its own (a Discord id, bare,
> as it always has been stored); Unison's and amll's arrive as `_maker_id`
> beside `_maker`, prefixed with the source -- see maker_slot.
>
> The `url` rides along for the same reason and is put to a different use:
> it is the contributor's own page, and the terms this API is used under ask
> that a community credit LINK to it rather than merely name it. Absent for
> everybody who does not publish one, which is everybody but Spicy Lyrics,
> and an empty one means "do not draw a link" rather than "draw a dead one".

### `maker_slot`

**line 6019** — from the docstring, `def maker_slot(doc: dict):`

> `_maker` with the id and picture filed beside it, as one person.
>
> Unison and amll name their maker in a plain string, which is what the
> editor copies into SyncedBy and so has to stay a string; the account id
> and the avatar travel in `_maker_id` and `_maker_avatar` next to it. This
> puts the three back together, so people_of reads them the way it reads a
> Spicy Lyrics Maker.

### `credits_of`

**line 6032** — from the docstring, `def credits_of(body) -> list[dict]:`

> Everybody a document credits with its TIMING, best claim first.
>
> Four conventions, because four sources carry the fact at all and none of
> them agreed on where to put it: Spicy Lyrics files Maker and Uploader in
> TTMLUploadMetadata, amll and a dropped TTML arrive through _credits as
> `_maker`, Unison names its submitter in the record rather than the TTML
> (see _unison_doc), and a file written by this program's own editor spells
> it SyncedBy.
>
> Not the SONGWRITERS, which is the other credit a document carries and a
> question about the song rather than about this copy of it. Refusing
> somebody's syncs is not refusing to listen to what they wrote.
>
> Maker before Uploader for the same reason lyrics_gui.made_by prints them
> that way: where both are named they are two different people, and the
> first of them is the one whose timing this is.

### `makers_of`

**line 6047** — from the docstring, `def makers_of(body) -> list[dict]:`

> Whoever MADE the timing, and the uploader only where nobody else is named.
>
> The narrower half of credits_of, for refusing. Spicy Lyrics often leaves
> Maker empty and names only the Uploader, and then the uploader is the
> maker -- see lyrics_gui.made_by. But where both are named they are two
> people, and refusing a sync because of who passed it on refuses somebody
> else's work.

### `whose`

**line 6065** — from the docstring, `def whose(name: str) -> str:`

> One credited name, as it is compared.
>
> Case and spacing are noise -- the same person is "Kiri", "kiri" and
> " Kiri " depending on which of the four conventions above carried them --
> and a GitHub login typed the way it is written everywhere else, with an @
> on the front, is the same login without it.

### `same_person`

**line 6086** — from the docstring, `def same_person(a, b) -> bool:`

> Whether two credits, or a credit and a list entry, are one person.
>
> THE ID DECIDES WHEREVER BOTH SIDES HAVE ONE. It is the only thing here
> that holds still: a Spicy Lyrics display name is the person's to change
> whenever they like, so a roster that knew them only by last month's
> spelling stops refusing them at the moment they are hardest to recognise,
> and two different ids under one name are two different people however the
> name reads today.
>
> Where either side has no id the name is all there is. That is right for
> what this is used for -- telling one credit line's people apart, and
> finding an entry to take back off a list -- and wrong for deciding whose
> syncs a list catches, which is answers_to's job: there an entry that has
> an id does not fall back to its name.

### `answers_to`

**line 6097** — from the docstring, `def answers_to(entry, credit) -> bool:`

> Whether a credit is somebody a roster entry means.
>
> One-sided where same_person is symmetric, because the entry is the
> question. AN ENTRY WITH AN ID MEANS THAT ACCOUNT AND NOTHING ELSE: the
> name beside it is there to be read in the settings box, and somebody else
> who takes the name -- or this person's next display name -- is not on the
> list on its account. So a credit with no id, or another one, does not
> answer to it.
>
> An entry with no id is one that was typed, and it matches by name until
> the walk for a playing song meets somebody of that name who has an id --
> see Roster.met. After that it carries their id like any other.

### `person_list`

**line 6108** — from the docstring, `def person_list(raw) -> list[dict]:`

> One of the two lists, however it was stored, typed or passed.
>
> Three shapes reach this. A list of {name, id} is what the app writes now.
> A plain string is what it wrote before, what `--skip-people` hands over,
> and what somebody editing gui.json by hand will type -- commas, because
> these are usernames and a username can contain a space: splitting on
> whitespace would make two people out of "Jane Remover". A list of bare
> strings is the same thing already split.
>
> An entry with an id but no name is kept: it is somebody who was refused
> and has since renamed themselves, and dropping it for having no name to
> show would be undoing the refusal at the moment it starts to matter.

### `with_ids`

**line 6134** — from the docstring, `def with_ids(want, had) -> list[dict]:`

> `want` as it was typed, wearing the ids the list it replaces already knew.
>
> The settings row is a line of text and always will be: names are what a
> person reads under a lyric and what they can sensibly type. So a list
> edited there comes back as names alone, and every id the app had learned
> would be thrown away by the one person who was doing nothing but fixing a
> spelling.
>
> Matched by name, which is all the typed side has. A name that was not on
> the list before is a new person and keeps the nothing it arrived with.

### `Roster`

**line 6145** — from the docstring, `class Roster:`

> Whose syncs to refuse, and whose to take whatever the order says.
>
> Two lists of people, both usually empty, applied to documents rather than
> to sources -- one contributor is not the database they post to -- and,
> because each name is kept beside the id it was read off, going on meaning
> the same account when the person renames themselves. An id is one
> source's own, so an entry that has one follows its person on that source
> alone. See answers_to.
>
> SKIP drops the document outright: it is not shown, not handed to a blend
> as a base, and not counted when the walk decides whether anybody better
> has answered. The source itself is untouched, which is the point -- one
> contributor's syncs on Spicy Lyrics are not Spicy Lyrics.
>
> PICK wins a tie against everybody, however the sources are ranked. That
> is the whole of what it does, and the limit is deliberate: quality still
> outranks order here as it does everywhere else in this walk, so a name on
> this list cannot put a line-timed document on screen over a word-timed
> one. What it settles is the case the user actually described -- two
> documents that are as good as each other, one of them by somebody whose
> work they trust, sitting on a source they ranked below.
>
> SKIP looks at the maker alone (see makers_of): a sync uploaded by
> somebody on the list but made by somebody else is not theirs to refuse.
> The uploader counts only where the document names nobody else. A skip
> beats a pick where both land on one document.
>
> Each entry is matched the way answers_to says: by its id where it has
> one, and by name only while it is still waiting for one. Every match a
> document makes is noted in `met`, so the window can give a waiting entry
> the id of the person it turned out to mean, and an entry that has one the
> display name that person goes by now.

### `Roster.key`

**line 6205** — from the docstring, `def key(self) -> str:`

> The lists as one string, to store beside an answer they shaped.
>
> A cached answer was picked under whichever roster was in force when
> the walk ran, so the roster is part of the question the cache is
> keyed by -- exactly as `names` and `bar` are (see _store). Without
> this, refusing somebody would go on showing their document for the
> month the old answer lives, and taking them off the list again would
> not bring it back.
>
> Built from the MATCH KEYS rather than from the names, so learning
> somebody's id -- from under a lyric, or by a typed entry meeting them
> -- re-asks the question, and a rename, which changes nothing about who
> is refused, does not. See match_key.
>
> Empty on an empty roster, which is what every record written before
> this existed carries -- so nobody's cache is thrown away by adding a
> feature they are not using.
>
> The "m" says skips are judged by the maker alone (see makers_of); an
> answer stored while uploaders were refused too is a different answer.

### `_rejoin`

**line 6229** — from the docstring, `def _rejoin(mora: str, worded: str) -> str:`

> NetEase's readings, cut into words the way a segmenter would cut them.
>
> romalrc is written one mora at a time -- "u sse e wa", "ha n pa na ra" --
> which is accurate and nearly unreadable: under a lyric it looks like the
> song is being spelled out rather than sung. A segmenter knows where the
> words end but gets the readings themselves wrong often enough to matter
> (愛して as "itoshite", 頑張って as "ganbatsute", both wrong here), so the
> two are combined: NetEase says what the sounds are, the segmenter says
> where to break them.
>
> Both sides are compared with their spaces removed, and only the stretches
> that agree outright are re-cut -- where they disagree, NetEase's own
> spacing stands. Guessing a word boundary is not worth a wrong reading.

### `_cached`

**line 6308** — from the docstring, `def _cached(tid: str, touch: bool = True):`

> The stored answer for a track, or None if there is not a usable one.
>
> A miss ages from when it was taken: six hours after a provider said no,
> asking again is worth the round trip. A hit ages from when it was last
> USED, not when it was fetched -- the file's mtime is bumped every time it
> is read back, so a song in rotation keeps its lyrics for as long as it
> stays in rotation, and only a month of not being played lets go.

### `sweep`

**line 6340** — from the docstring, `def sweep(force: bool = False) -> int:`

> Delete the entries nothing has asked for in a month. Returns how many.
>
> Nothing else removes a cached document: the size of this directory is a
> few kilobytes a song and the whole point of it is to still be there the
> next time the song comes round. What ages out is what stopped being
> listened to, plus the six-hour "nobody has this" notes, which are only
> worth keeping until it is worth asking again.
>
> Runs at most once a day -- the stamp file is the clock -- unless forced.
> Both caches go round together: what Spicy Lyrics answered is kept by the
> same rule, in its own directory for its own reasons (see SPICY_DIR), and
> two sweeps on two clocks would be two things to remember.

### `stored`

**line 6419** — from the docstring, `def stored(tid: str):`

> The document last stored for this track, asking nobody.
>
> Not the same question as fallback()'s: that one wants to know whether a
> stored answer settles the walk it is about to do, and refuses a record
> taken under a different set of providers. This one only wants something
> true to put on the screen while that walk happens, and last week's answer
> from a provider since switched off is still this song's words.

### `_store`

**line 6444** — from the docstring, `def _store(tid: str, doc, source: str, names: list, bar: int,`

> Remember the answer, and what was asked to get it.
>
> `names` and `bar` are the question, and without them the answer cannot be
> reused safely: a walk that skipped half the providers because Spicy Lyrics
> already had word timing would otherwise be read back as "nobody has
> anything" by a later ask that really did want to know.
>
> `people` is the rest of the question -- who was being refused and who was
> being preferred while this was decided. Empty for anybody not using
> either list, which is what every record written before them holds, so
> those go on matching.
>
> `missed` names the providers that failed rather than answered; see _settled.

### `refresh`

**line 6475** — from the docstring, `def refresh(tid: str) -> None:`

> Forget a track AND make its sources answer again, not their copies.
>
> For a reload the user asked for. `forget` alone drops only the walk's
> stored pick, and the walk then read the very same documents back: Spicy
> Lyrics' own record off the disk, everybody else's out of the _ONCE memo.
> A source that had since updated its lyric for the song was never asked.
>
> Spicy Lyrics is asked once, on the next walk, rather than having its
> record deleted -- if that one ask cannot get through, the record it had
> is what the walk gets (see spicy_lyrics). The other callers of `forget`
> changed the QUESTION (a better title, a dropped file) and have no reason
> to spend a Spicy request, so they do not come through here.

### `_once`

**line 6510** — from the docstring, `def _once(key: tuple, fn):`

> Ask an upstream once, however many things want the answer.
>
> A walk asks the same servers over and over. With the blends switched on,
> NetEase is fetched three times for one track -- once as itself, once
> under Apple+NetEase, once under the three-way -- and each of those is a
> search and then a lyric fetch, better than a second each. QQ goes the
> same way, three times over between QQ Music itself, Apple+QQ and the
> three-way's filler.
>
> The second caller waits on the first rather than starting again, so the
> duplicates cost nothing at all rather than costing the same again. Kept
> for ONCE_TTL, which is long enough to cover a walk and its retry and
> short enough that a song still gets a fresh answer when it comes round.
>
> A copy goes back to each caller. They mutate what they are given --
> peeling ad-libs off lines, folding, re-stamping -- and one caller's edits
> have no business reaching another's document.

### `_parallel`

**line 6538** — from the docstring, `def _parallel(jobs: dict, each=None) -> dict:`

> Run {key: thunk} at once, and hand back {key: result}.
>
> Everything here is a blocking socket read waiting on somebody else's
> server, so threads are exactly the right tool and the GIL never enters
> into it. A thunk that raises comes back as None: one provider being down
> is not a reason for the others to have been asked in vain.
>
> `each(key, value)` is called as each one lands, on whichever thread it
> landed on, so a caller can do something with the first answer instead of
> waiting for the last. It is never allowed to break the walk.

### `_Fan`

**line 6585** — from the docstring, `class _Fan:`

> Jobs already running, and whatever they have answered so far.
>
> _parallel is this and then waiting for all of it, which is the right
> shape nearly everywhere: an answer sheet with a row for every provider.
> The walk wants the two apart exactly once. Its second round -- the blends
> and Genius -- reads the first round's answers, and it used to wait for
> every one of them before it started; one slow door then decided when the
> blends began, and the blends are what usually wins.
>
> So the round can be read EARLY, with the stragglers still out, and the
> stragglers collected afterwards. What that costs is judgement made on a
> partial sheet: a blend may be built that a late word-timed answer would
> have stood down (see _outdone), or may take its lines from the second-best
> base because the best had not landed. Neither is wrong, only wasted --
> the late answer is still collected, still ranked, and still wins the walk
> if it deserves to. What it buys is a chain whose slowest member costs one
> wait rather than deciding the pace of everything after it.

### `_fan`

**line 6620** — from the docstring, `def _fan(jobs: dict, each=None) -> "_Fan":`

> `jobs` started at once and handed back still running.
>
> The plumbing is _parallel's -- the same cancel token, the same fault
> sheet, the same refusal to let one thunk's exception cost the others --
> and it is written twice rather than shared because the shape of the two
> differs at the one point that matters: this one does not close the pool,
> so the caller has to (see _Fan.all).

### `_outdone`

**line 6650** — from the docstring, `def _outdone(name: str, names: list, ahead, got: dict, local) -> bool:`

> Whether somebody ranked in front of a blend's donors has the song
> word-timed already, which is the whole of what a blend was for.
>
> A blend costs doors of its own -- one for Apple+QQ, two for the three-ways
> -- on top of the ones this walk is already knocking on, and what it buys
> is word timing under lines that had none. Where a source the user put in
> front of its donors came back word-timed, there is nothing left for the
> blend to add that they asked for, so it is not built at all.
>
> In front of the DONORS, which is now the same stretch as in front of the
> blend: provider_order puts each blend immediately above the highest-ranked
> source it borrows from. It was not always -- the blends used to sit up at
> Apple Music's slot, and reading this the other way would have left out
> Apple's own document, amll and Unison, who sit between Apple Music and QQ
> in the default order and are exactly the sources whose word timing makes a
> blend beside the point. Written this way it stays right either way.
>
> Spicy Lyrics counts too, judged by `local`, wherever it is in front of the
> donors. It is not a provider in this walk, so that is read off `ahead`
> instead: the donors being ranked above Spicy Lyrics is what puts Spicy
> behind them. Not where the blend itself outranks Spicy Lyrics -- there the
> user has already said which of those two they want, and it is not Spicy.

### `_beaten_to_it`

**line 6663** — from the docstring, `def _beaten_to_it(name: str, above: dict, ahead, bar: int) -> bool:`

> Whether a costly door has already been answered over the top of.
>
> True when something the user ranked ABOVE it has come back word-timed.
> Word timing is the ceiling of this chain -- the walk stops early on it
> precisely because nothing can beat it -- so a word-timed document from
> higher up the order wins on quality and on order at once, and there is no
> song left for this one to win. Asking anyway buys nothing and costs the
> whole of its wait.
>
> ABOVE it, not merely anywhere, and that is the whole care taken here. A
> word-timed answer from a source the user ranked BELOW this one does not
> stand it down: they said which of those two they would rather have, and
> quietly taking the other because it happened to be quicker is the one
> thing this walk has always refused to do. On a song nobody else has
> word-timed, the door is knocked on exactly as before.
>
> Spicy Lyrics is read off `bar` rather than out of `above`, because it is
> not a provider in this walk -- the player already holds its document. It
> counts as being above unless the caller ranked this source above it,
> which is what `ahead` names. Same reading as `_outdone`.

### `_answered_already`

**line 6672** — from the docstring, `def _answered_already(above: dict, bar: int) -> bool:`

> Whether an untimed source has anything left it could answer for.
>
> Named apart from `_spoken_for`, which is a different question about a
> different thing -- whether a line already writes an ad-lib into its own
> text -- and which this used to be called as well. Two module-level
> functions of one name is one function: the later definition wins, so
> _lift_strays was calling THIS with (text, line) and raising
> AttributeError, and since a provider that raises is passed over in
> silence, the Apple+QQ blend simply never appeared on any song whose
> ad-libs needed lifting. Skillet's "You Ain't Ready" is one of them.
>
> Genius is the only one, and this is why it waits for a second round
> rather than going out with the rest of the walk. Every other provider
> here is a request or two against a database; Genius is four searches and
> a page fetch, on a token that is the user's own and rate-limited to
> their account -- and with the look-ahead warming three tracks in front
> of the one playing, asking it for every song would spend twenty requests
> per track change to answer the handful where anybody needed it.
>
> Nothing is lost by waiting, because there is no song an untimed document
> can win off a source that answered. It ties with another untimed one and
> loses the tie on order, since it sits below them all; against anything
> line-timed or better it is not close. So a single answer from the round
> before -- ANY answer, however poor its timing -- settles it.
>
> `bar` is what the caller already holds, which is usually Spicy Lyrics.
> Read as the walk itself reads it rather than off the `local` document,
> because the two are not always the same question: eval_sources hands a
> provider Spicy's copy to build on while asking it what it has of its
> own, and reading the document there would have this answer nothing on
> every song Spicy has -- which is the opposite of what was asked.
>
> A bar of "static" does not stand it down. That is a tie, and a tie goes
> to whoever the user ranked first; `ahead` is what decides it and the pick
> does that later. Spicy Lyrics is line-timed or better on very nearly
> everything it has, so the case is rare and asking is what makes it right.

### `_gather`

**line 6681** — from the docstring, `def _gather(known: dict, names: list, tid: str, meta: dict, local=None,`

> Every named provider asked at once, in two rounds where one has to be.
>
> The blends are the exception: they lay word timing under somebody else's
> lines, and "somebody else" should be able to be any source the user has
> ranked above them. So they go in a second round, and are handed what the
> first round came back with -- the documents they might build on have then
> already been fetched, by the providers those sources are, and the blend
> costs no request to reach them.
>
> Only the sources ABOVE a blend are offered to it. One ranked below is one
> the user has said they want less, and inheriting its lines through the
> back door is not what putting it there meant.
>
> A blend whose donors are outranked by a word-timed answer is not asked at
> all -- see _outdone. That is decided here rather than inside the blend
> because it is the point of the second round: by now the first round has
> said who has the song, and the blend has not yet spent a request. An
> untimed source -- Genius -- is stood down on the same grounds and by the
> same reasoning, one rung lower down: see _answered_already.
>
> THE SECOND ROUND DOES NOT WAIT FOR THE WHOLE OF THE FIRST. It waits
> ROUND_HOLD and then reads what has landed. The first round is nine or ten
> doors wide and all but one of them answer inside two seconds; the odd one
> out takes ten, and while the round was a barrier it was that one door that
> decided when the blends started -- which is to say when the answer that
> usually wins was ready. The stragglers keep running, are collected below,
> and are ranked in the usual way by whoever called this.
>
> What a partial sheet costs is judgement, not correctness: a blend may be
> built that a late word-timed answer would have stood down, or may take
> its base from the best document that had landed rather than the best there
> was. Both are waste rather than error -- and the blends do not race their
> own donors, because a donor still in flight is one the blend joins inside
> _once rather than fetches again.
>
> Genius is the exception to the exception. It is untimed, so there is no
> song it can win off anybody who answered, and asking it costs the user's
> own rate-limited token -- so it is worth the full wait to find out whether
> it was needed at all. It is decided on the complete first round.

### `_gather.second`

**line 6694** — from the docstring, `def second(who: list, got: dict) -> dict:`

> The ones of `who` still worth asking, given `got`.
>
> A refused document is not in `got` as far as this round is concerned.
> It cannot be handed to a blend as a base -- ignoring somebody's sync
> and then reading their lines under a borrowed clock is not what
> refusing them meant -- and it cannot stand a blend or Genius down
> either, which would be the same document deciding the round without
> appearing in it.

### `fallback`

**line 6730** — from the docstring, `def fallback(tid: str, meta: dict, have: str, enabled=None, force: bool = False,`

> Best document the chain can offer, or None to keep what we already have.
>
> `alive` is asked, from every thread the walk reaches, whether anybody
> still wants the answer. Left off nobody is asked and the walk finishes
> what it started, which is what a caller with somewhere to put the answer
> wants. A player is not one: it asks for whatever is playing, and what is
> playing changes under it. See _walking.
>
> A no there is final, whatever the caller's own predicate answers next:
> see _latched, and the stored second-best answer that was written because
> it was not.
>
> `have` is quality() of the Spicy Lyrics document. A provider is only
> accepted if it beats that, so a line-synced LRCLIB hit can rescue a song
> with no lyrics but can never demote a line-synced Spicy Lyrics one. The walk
> stops early on word timing, since nothing later in the chain could beat it.
>
> `order` overrides the order they are asked in. It matters because the walk
> stops at the first word-synced answer, so whoever comes first decides the
> result on every track where more than one of them has word timing.
>
> `ahead` names the providers the caller has ranked ABOVE Spicy Lyrics. They
> win a tie -- an equally good document from a source the user put first is
> the one they asked for -- and their being there is also why a word-synced
> `have` no longer ends the walk before it starts. Quality still outranks
> order in both directions: nothing here can replace word timing with line
> timing just by sitting higher up the list.
>
> `people` is a Roster: whose syncs to refuse whatever source they turn up
> on, and whose to prefer whatever the order says. It is asked about
> documents rather than providers, and it is part of the cache key, since
> an answer picked under one is not the answer another would have picked.
>
> `note` is told what went wrong, as [(provider, why), ...], once the walk
> is over -- a source that timed out or was refused is one the order asked
> for and did not get, which is not the same thing as it having nothing and
> is worth putting in front of the user. See _blamed. It is called on the
> walk's own thread, once, and only where something did go wrong.

### `made_as`

**line 6752** — from the docstring, `def made_as(name: str, doc) -> str:`

> The blend an answer really is, read off whose timing it ended up using.
>
> A three-way blend whose filler placed nothing is, word for word, the
> two-way blend of its lead: Apple+NetEase+QQ with no line of QQ's in it
> is Apple+NetEase, and _via says so. With Apple+NetEase switched off and
> the three-way left on, that document went on the screen anyway, labelled
> "Apple Music with NetEase" -- so switching the blend off did nothing, and
> the only way to be rid of it was to switch off every blend that could
> turn into it. It is judged as the blend it turned out to be.
>
> Anything that is not a blend, or that does not say who timed it, is what
> its provider's name says.

### `_walk.beats`

**line 6824** — from the docstring, `def beats(rank: int, name: str, doc=None) -> bool:`

> Whether this answer is worth having over what the caller holds.
>
> A tie is won two ways: by a source the caller ranked above what it
> holds, and by a document timed by somebody they asked for by name.
> Neither can win anything else -- rank is read first and read hardest,
> so a preferred name still cannot put line timing over word timing.

### `_walk.landed`

**line 6862** — from the docstring, `def landed(name, doc):`

> The best answer SO FAR, handed over the moment it lands.
>
> The walk is ten providers wide and two rounds deep, and it used to
> hand back nothing at all until the slowest of them had finished --
> so a song nobody had cached sat under "Loading lyrics…" for as long
> as the worst server took, with a perfectly good document from the
> first one already in hand.
>
> Which is worth keeping, but it used to hand over whoever answered
> FIRST and then refuse to look again until the walk was over. The
> clock is not the running order: Musixmatch's endpoint is quick and
> sits last on most lists, so a song where it and a source ranked well
> above it both have word timing put Musixmatch on screen and left it
> there for the rest of the walk. The final answer did replace it, but
> the screen had already backtracked once by then, and the name under
> the lyric was somebody the user had ranked below.
>
> So the early answer can now be overtaken, on the same two rules the
> final pick uses and in the same priority: better timing takes the
> screen from worse, and between two documents timed alike the user's
> order decides. Nothing shown is ever replaced by something the final
> pick would not itself have chosen, so this walks towards that answer
> rather than flickering, and it arrives at the one the order asks for
> instead of the one that happened to be quick.

### `_steadiest`

**line 6917** — from the docstring, `def _steadiest(tied: list):`

> The tied answers with a meaningfully steadier blend moved to the front.
>
> Two blends of one song differ in exactly one thing that matters: whose
> clock is under the words. The running order settles that by whoever the
> user ranked higher, which is right when there is nothing to choose
> between them and wrong when there is -- and on any given song there often
> is. NetEase is the better bet in general and QQ Music is plainly better
> on some songs; a fixed order cannot say which is which.
>
> `_steady` can, and is measured on the way past: see BLEND_PICK for what
> it is and for the six-out-of-six that says it predicts the right answer.
> Only a MEANINGFUL difference moves anything, so a ranking is never
> second-guessed on noise. A blend moves only within its own run of
> consecutive blends, never past a source that is not one (2026-10-15 note).

### `_fullest`

**line 6949** — from the docstring, `def _fullest(tied: list):`

> Of the answers the walk ranked equal, the first that has the whole song.
>
> Order decides between two documents of the same lyric; it does not get to
> decide that a third of the words are not shown. On Bad Computer's "Your
> Spell" every blend answers word-timed, and the NetEase ones are built on
> an Apple copy carrying 359 of the song's 589 letters -- the last section
> is not in it. Ranking NetEase first asks for its clock, not for a shorter
> lyric.
>
> What it does not mean is that the fullest document wins. This used to walk
> the list keeping whichever answer the one in hand was short against, which
> handed the song to whoever wrote the most letters however the user had
> ranked them -- and on 2hollis' "jeans" that was Musixmatch, ranked last of
> fifteen, over a document Apple, QQ Music and Kugou all had whole (see
> BLEND_SHORT for why it read as short at all). A document missing a section
> is passed over; it is the ORDER that then says who gets the song instead,
> which is usually the source ranked next and not the longest one.
>
> Everything is measured against the fullest answer rather than against each
> other, because a document can only be short against a longer one and that
> is the longest there is -- one comparison each, on a list that is up to
> fifteen documents long by the time the blends have answered.

### `_gapped`

**line 6980** — from the docstring, `def _gapped(doc, full) -> bool:`

> Whether `doc` is silent where `full` sings a section's worth of letters.
>
> _shorter reads letters alone, and on a song whose ending is one chorus
> four times over it is fooled: Musixmatch writes Beat It's outro with every
> "(beat it)" echo and "(hee-hee)" in it, difflib lays all of those
> additions into one run across the repeats, and that run is as long as a
> section -- so BiniLyrics, which sings straight through to 256s with no
> hole in it, read as missing one and NetEase was handed the song. A
> section that is really missing leaves the time it took empty: "Your
> Spell"'s Apple copy stops before the last section does. So both have to
> say it. Where either has no clock to ask, letters are all there is.

### `_credited`

**line 6992** — from the docstring, `def _credited(doc: dict, docs: dict, names: list, ahead, local, meta=None) -> dict:`

> The winning document, credited to whoever the top source says wrote it.
>
> Who wrote a song and who timed this copy of it are different questions with
> different best answers. Apple names the publishing writers -- legal names,
> every co-writer -- and a document that beat Apple on timing can easily
> carry one name or none: Kugou gives "Vivian Weeks" where Apple gives four
> people, and LRCLIB gives nobody at all. Taking the words from whoever timed
> them best and the credit from whoever is ranked highest is not a
> contradiction; they were never the same claim.
>
> Ranked highest means the user's own order, Spicy Lyrics in its place in it.
>
> AND WHERE NOBODY ANSWERED AT ALL, Apple Music is asked outright. Half of
> what this chain fetches arrives with no credit on it -- LRCLIB carries
> none by design, NetEase and Kugou carry one name where there were four,
> and a scrape drops the header before anybody sees it -- so a saved file
> ended up with no <songwriters> in it for a song whose writers are not in
> any doubt. It costs no request: Apple's catalogue was already asked about
> this track for the ISRC BiniLyrics is filed by, and the credit came back
> in the same answer (see apple_song). Last, because a document that
> carries its own credit is carrying the one its own source stands behind
> -- the winning document included, which is why it is looked at here as
> well as in the ranking. Nothing already written is replaced by a search.

### `_no_credit_head`

**line 7033** — from the docstring, `def _no_credit_head(doc: dict, wrote: list) -> dict:`

> Drop a leading line that is not a lyric but a credit.
>
> QQ Music opens a good many of its syncs with the songwriters' names as
> the first sung line -- "Noelle Stockwood/Juno Callender" on femtanyl's
> SICK OF IT, "Vivian Weeks" on STOMACH BOOK's -- with no label in front of
> them to say what they are, which is what makes them harder to find than
> Kugou's "Lyrics by：". Two things give them away and both are needed,
> because either alone would eventually throw away somebody's lyric:
>
>   * the line says exactly what some source says the writers are, and
>     nothing else. Whoever wrote the song is known here from every other
>     provider that answered, which is what makes this cheap.
>   * or it cannot be sung AND reads as a list of names: thirty-one
>     characters in a fifth of a second is a marker, not a line. Speed alone
>     is not enough -- "Ayy, woo" goes past at 44 characters a second and is
>     a lyric -- so the words have to be capitalised like names too, which
>     "Whatever you got for me is not enough" is not. Only where the
>     syllables are really timed, since a line-level document's ends are
>     this program's own guesses.

### `duet_flags`

**line 7071** — from the docstring, `def duet_flags(lines: list[dict], tid: str, meta: dict, enabled=None):`

> Recover the second-voice flag from amll-ttml-db.
>
> Spicy Lyrics carries OppositeAligned per line, but a good number of its
> entries are duets with the flag never set -- on the tracks this library
> shares with amll-ttml-db, six of twenty had no flags at all where amll had
> them. Nothing in the cached document can reveal that, since every line is
> just Type "Vocal"; the only way to know is to ask a source that kept the
> TTML agents.
>
> Deliberately only for lines that carry NO flags. Where Spicy Lyrics did
> mark a song up, amll often marks up considerably more of it -- a chorus
> agent read as a second singer -- and overwriting good data with that would
> trade one wrong answer for another. Returns a list of bools, or None.

### `_key`

**line 7108** — from the docstring, `def _key(s: str) -> str:`

> A line reduced to the letters and digits in it, for comparing by text.
>
> Cached because of how it is ASKED. Forty-nine call sites, and the ones
> that matter sit inside the matching loops -- every line of one document
> against every line of another, the same handful of strings coming round
> again and again. Blending five songs calls this 9,668 times over 1,084
> distinct strings, nine reads of each, and the strings are short enough
> (twelve characters on average) that a dict lookup is the cheaper half by
> a wide margin: it was 27% of the blend and is now under 2%.
>
> Bounded rather than unbounded because the walk blends whatever is playing
> for as long as the window is open, and lyrics are a stream of new strings.
> 8192 is several songs' worth of lines and syllables at once.

### `_fragment`

**line 7118** — from the docstring, `def _fragment(one: str, other: str) -> bool:`

> Whether the shorter of two lines is a piece cut out of the longer.
>
> Length alone cannot tell a line rewritten at the head from a line that is
> half of another. "Learned to make it on my own" against a donor's "Had to
> make it on my own" is 82% of the length and 85% similar, and it is plainly
> the same line -- but so, on those numbers, is "Caught in the middle"
> against "Two faced, caught in the middle", which is a different line sung
> a bar later and pairing them put Linkin Park's chorus 1.4s out.
>
> What separates them is not how much shorter one is. It is whether what
> they share is CONTIGUOUS: the chorus fragment is inside the longer line
> whole, every letter of it in one run, while the rewritten head shares only
> its tail -- 15 of 18 letters, and the other three are somewhere else.

### `_ratio_over`

**line 7131** — from the docstring, `def _ratio_over(a: str, b: str, bar: float, tie: bool = False):`

> SequenceMatcher(None, a, b, autojunk=False).ratio() -- or None where
> that could not come out above `bar` (at it, with `tie`).
>
> The ratio is never higher than the two bounds difflib gives for a fraction
> of the cost, so a pair that fails either has failed the bar and nothing
> more is worked out. Measured on lines of similar length, the full ratio
> was 40us and the bounds 15us, and they turned away 98-100% of the pairs
> _near_pairs and _regroup try. What comes back is the same number as
> before wherever it is used, and None only where the caller would have
> thrown it away.

### `_near_pairs`

**line 7144** — from the docstring, `def _near_pairs(a: list[str], b: list[str], mate: dict, floor: float = 0.75) -> dict:`

> Line pairings the exact match missed, taken on similarity instead.
>
> Matching lines by their letters exactly leaves a hole wherever the donor's
> transcription differs by a character, and community transcriptions differ by
> a character constantly. On one 41-line song NetEase wrote "l opened" for "I
> opened" (a capital I typed as a lowercase L, three times), "stelking" for
> "stalking", "****ing" for the word Apple spells out, and dropped the I from
> "And I'm so high" -- six lines that are plainly the same line, left untimed
> because one glyph was wrong.
>
> Safe to be loose here because the exact matches have already pinned the song
> down: an unmatched line can only be paired inside the window its matched
> neighbours leave, so this is choosing between the two or three donor lines
> that could possibly be it, not searching the song. A line still finds no
> mate if nothing in that window resembles it.
>
> Length is checked before similarity, and it is the part that does the real
> work. A chorus gives you "Two faced, caught in the middle" and "Caught in
> the middle" as separate lines, and one contains the other, so they score 0.8
> similar while being different lines sung a bar apart -- pairing them put
> Linkin Park's chorus 1.4s out. A mistyped line is still the same length; a
> shorter line is a shorter line.

### `_regroup`

**line 7178** — from the docstring, `def _regroup(a: list[str], b: list[str], bit: list, dit: list, mate: dict) -> dict:`

> Time the lines the two sides cut in different places.
>
> Everything up to here pairs one line with one line, so a line that the
> donor writes as two -- or two that it writes as one -- has no counterpart
> and gets no words, however plainly it is the same singing. That is not a
> rare shape: Koven's "Gold" is 24 lines against NetEase's 34, and after
> every other pass has run, EVERY line still missing from it is one Apple
> writes whole and NetEase breaks in two.
>
> Both directions are the same problem seen from either end, so both are
> handled here:
>
>   one of ours, several of theirs -- their syllables are concatenated in
>   order and re-cut onto our line, which is exactly what _relay already does
>   for a line whose spelling differs;
>
>   several of ours, one of theirs -- their syllables are shared out between
>   our lines in proportion to how much of the text each carries, and each
>   share is re-cut onto its own line.
>
> Returns {base index: (start, end, syllables)} for the lines it could place.
> Only donor lines nobody else is using, and only inside the window the
> matched lines either side leave -- the same discipline as _near_pairs, for
> the same reason.

### `_letter_ops`

**line 7325** — from the docstring, `def _letter_ops(theirs: str, ours: str, floor: float):`

> The opcodes that line `theirs` up with `ours`, or None if they are not
> alike enough for that to be worth taking.
>
> What _recut needs from difflib depends on the two strings and nothing
> else -- the cuts and the breaks only come in afterwards -- and one blend
> asked for the same pair again and again: _relay is called from a dozen
> places and _blend reaches it three or four times for every line, which is
> most of the 3,280 get_opcodes calls (roughly 1.7 seconds with the GIL
> held) a cold walk made after _shorter was moved to a worker.
>
> The two bounds difflib gives for nothing are checked before the matching
> is done: the ratio can never be higher than either, so a pair that fails
> them fails the floor, and the answer is the one the full ratio gives.

### `_recut`

**line 7339** — from the docstring, `def _recut(theirs: str, ours: str, bounds: list[int], breaks: set[int],`

> Cut positions in the donor's letters, moved onto ours.
>
> Both sides are the same line with the punctuation and casing taken out, so
> they are nearly the same string, and where they are exactly the same string
> the caller never gets here. What is left is a handful of letters one side
> spells differently -- which is a job for the same aligner that paired the
> lines in the first place, one level down.
>
> Letters only one side wrote have no position of their own, and a cut next
> to a run of them can honestly go anywhere in it. `breaks` -- the offsets in
> `ours` that fall between two words -- settles those, because the two live
> cases pull in opposite directions and nothing else tells them apart: a
> donor writing "nothin" for "nothing" leaves a "g" that has to stay with the
> word before it, and one writing "****ing" for a word spelled out leaves
> four letters that have to go with the syllable after. Both are one cut
> against one inserted run; the difference is only which side of it finishes
> a word of ours.

### `_unsplit`

**line 7372** — from the docstring, `def _unsplit(syls: list[dict]) -> list[dict]:`

> Pieces of one word the letters were cut between, put back together.
>
> Two sources spell a contraction differently -- NetEase writes "It is never
> too late" where Apple writes "It's" -- and the letter alignment then puts
> a cut inside OUR word, at the apostrophe. What comes out is "It'" and "s"
> lighting a tenth of a second apart, on a word nobody sings in two pieces.
> Over the songs measured here it is the commonest shape of sub-word cut
> there is: "don'" and "t", "I'" and "m", "walk'" and "s".
>
> Only at the apostrophe, and only where the word runs on. A syllable that
> ENDS a word keeps its own timing however it is spelled, and a sub-word cut
> anywhere else is the donor really having measured two syllables of one
> word, which is the thing this whole file is for.

### `_cut_along`

**line 7409** — from the docstring, `def _cut_along(text: str, syls: list[dict],`

> Re-cut `text` along `syls`' boundaries, keeping our own characters.
>
> The two sides spell the same line but not identically -- one capitalises
> "Internet", the other does not; one writes an em dash with spaces around it.
> Since only the timing is being borrowed, the donor's syllables are used
> purely as cut points and every character that reaches the screen still comes
> from `text`.
>
> Nor do the two always spell it with the same letters, and demanding that
> they did cost far more than it saved. A donor line reading "nothin" for
> "nothing", or "****ing" for the word Apple writes out, is one letter or four
> from ours and unmistakably the same line -- _near_pairs exists precisely to
> keep those pairings -- and refusing to cut along it threw away every word
> timing the donor had for that line anyway. Where the base carries no word
> timings of its own to fall back on that is the difference between a line
> that fills and a line that just sits there: on the cached blends built over
> LRCLIB it left three lines in ten unfilled, scattered through songs that
> were otherwise filling word by word.
>
> So the letters are lined up when they do not match outright, and the cuts
> come across with them.
>
> Matching WORDS to words instead was tried and measured, on the theory that
> a letter alignment cannot know what a word is. It is worse, and for the
> reason this docstring already gives: exact word matching drops every word
> the two sources spell differently, and near-matching words inside a window
> recovers only some of them. Against this, over Stronger, MOTTO and If You
> Want Love -- 91/91 lines timed with nothing invented, against 90/91 with
> twenty-five onsets invented; 77/79 and four, against 75/79. The letters
> already carry the words with them. See eval_sources.py for the instrument.
>
> `floor` is how alike the two have to be before the cuts are taken at all.
> It is looser for a line the re-stream handed over than for one a pairing
> did, because those two arrive with very different amounts of evidence
> behind them; see RECUT_LIKE.

### `_spoken_mark`

**line 7481** — from the docstring, `def _spoken_mark(prev, y, nxt) -> bool:`

> Whether a punctuation syllable is a sound rather than a pause.
>
> Three things have to hold, and dropping any of them was measured to be
> wrong over the documents in lyrics/.
>
> It has to be a mark that CAN be said between two characters --
> SPOKEN_MARKS. Welded-in-a-word alone is not enough: Firework times
> "sky-y-y" as "sky-" "y-" "y" and Odo carries its romanisation in the same
> group, so the closing bracket of 「ひとりじゃない」 has Japanese on one
> side and romaji on the other. Neither mark is uttered.
>
> It has to be joined to real word material on BOTH sides -- a letter or a
> digit touching it, with no space in the flag and none in the text. One
> side is not enough: a full stop ending a sentence is welded to the word
> before it and has a space after. And the neighbour has to be a word, not
> another mark, which is what keeps "you..." timed as "you" + "." + ".."
> from being read as somebody saying "dot".
>
> What is left is a mark inside a token, which is spelling rather than
> punctuation around the words. It was timed because it is said, and
> quiet_marks was taking that away.

### `close_holes`

**line 7498** — from the docstring, `def close_holes(doc):`

> Ends that were not written, made ends a reader can see.
>
> The same repair `_mxm_spans` does for Musixmatch and for the same reason,
> which is that at the scale a lyric is read at a tenth of a second of dead
> air in the middle of a phrase does not read as phrasing -- it reads as the
> word cutting out. A word held to the next word's start is what everybody
> who has hand-timed a line writes.
>
> INSIDE A LINE ONLY, which is where this differs from the Musixmatch one.
> That one closes across lines too, on the grounds that two lines a tenth of
> a second apart are one phrase however they were cut. Here they are not:
> these sources write a line's end deliberately and the player draws a line
> for exactly as long as it lasts, so holding the last word of a line into
> the next one lights both at once.
>
> Backing groups get the same treatment as the lead, separately -- an ad-lib
> is its own phrase and its last word has nothing after it to run to.

### `no_overlap`

**line 7535** — from the docstring, `def no_overlap(doc):`

> No line drawn past the start of the line after it, where the part of
> it past that start is slack rather than singing.
>
> Every other rule here is about what a line SAYS; this one is about the
> screen, where two lines lit at once is two lines the reader has to choose
> between. It happens for honest reasons -- a source holds a line open
> until the next is due, an ad-lib lifted onto a line carries an end from
> further down the song, a fold brings that end up with it -- and on Conro's
> "All I Want" they stacked: "All I want is" ran 25.98 to 34.80 over "All I
> want" at 30.60 and "(All I want)" at 32.88, three lines lit together.
>
> The line's own end is what gives way, and its backing groups with it,
> because the next line's start is a measurement and the end usually is not
> -- it is a held tail, or a stamp somebody put where the next line begins.
>
> But only as far as its own content: an end gives way where it is slack,
> and a sung syllable is not slack. So an end is never pulled below the last
> thing the line is actually singing, and a syllable is clipped only where
> it STRADDLES that start AND is the last of its group, because only then is
> its end slack -- an interior syllable's end is the next one's onset, which
> is a measurement, and pulling it back ends a word before it is sung. One
> that begins after that start is not a tail running over, it is a voice
> singing there,
> and on slayr's "promise" that is most of the song: the echoes that answer
> "Promise-- that you couldn't keep" are each sung a whole line late, and
> pulling their ends back to the next line's start squashed all seven words
> of them to the 50ms floor. The light then stood still for 49 frames out of
> 76 and jumped 20px between them -- a line playing choppily on a renderer
> with nothing wrong with it. A group that begins past that start is left
> alone entirely, which also keeps an end from crossing its own beginning.
>
> Two lines really can sound together -- a trade, an answer, an ad-lib held
> over the line beneath it -- and where the stamps say so, they say so
> because somebody measured it. See Sweep in renderers, which draws a row
> with two voices in it.
>
> So this runs over a blend and nothing else. Every overrun named above is
> one source's end landing on another source's lines: a donor holds a line
> open until the next is due and the base it was laid over disagrees, a
> graft carries an end from further down the song, a fold brings that end up
> with it. Reconciling them is this rule's business. A document from one
> source is not that. Its ends and the starts they run past were written by
> the same hand, in one pass, against one clock, and where they overlap that
> is what was heard -- on Linkin Park's "In the End" the echo answering
> "watch you go" holds its last vowel 46.692 to 54.017, over three lines of
> the verse under it, and clipping it to the next line's start took 6.97s of
> a 7.33s syllable off a note that is plainly still being sung. There is
> nothing to reconcile there and no second opinion to prefer, so the
> measurement stands. See blended().

### `quiet_marks`

**line 7608** — from the docstring, `def quiet_marks(doc):`

> Timing taken off a syllable that is nothing but punctuation.
>
> A source that stamps "..." or an em dash as a syllable of its own gives
> it a turn on screen, and the turn can be enormous: the mark sits between
> two verses and its stamp spans the instrumental break between them, so
> the fill crawls across a dash for twenty seconds while nobody sings.
>
> It is not sung, so it does not get a clock. Its text rides on the word
> before it -- or on the word after, where it opens the line -- and that
> neighbour keeps its OWN times, which is the whole point: the break stops
> being drawn as if something were happening in it.
>
> A masked word is not one of these; see MASKED. Riding it onto its
> neighbour is what took the space out from around it on screen.
>
> A mark INSIDE a word is not one of these either, and that one was a bug:
> the point in "2.3" is sung -- "two point three" -- and its turn on
> screen is the whole reason somebody timed it. See _spoken_mark.
>
> A line that is nothing but marks is left alone. There is no word for it
> to ride on, and a line of dots between verses is a real thing a lyricist
> writes; the interlude setting is what answers that one.

### `unlump`

**line 7655** — from the docstring, `def unlump(doc):`

> Every group in a document, with no syllable holding two words.
>
> _relay does this to what it lays down, but a document has words in it
> that the relay never touched: the base's own syllables where the donor
> had nothing to say about that line, its backing vocals, and every line
> of a document that won outright and was never blended at all. The donors
> carry them -- "or ​am", "I ​am ​a", two words joined with a zero-width
> space and given one timing between them -- and they read exactly like the
> ones the relay used to make.
>
> Not Spicy Lyrics' copy any more, though it used to be the example here.
> Its zero-width spaces are its own -- it writes them over a line that
> already spells its gaps -- so _spicy_docked takes every one of them out at
> the door and a lump of its can only be a lump of real spaces now. See
> SL.unzwsp_body.

### `_unlump`

**line 7691** — from the docstring, `def _unlump(syls: list[dict]) -> list[dict]:`

> One timing covering several words, shared out among them.
>
> The donor does not always cut where we do. Where it holds two of our
> words in one token -- "let me", "that shit", "a fuck," -- and wherever
> the tail of a line ends up on the last syllable, those words fill as a
> single block: they all light at once and none of them lights when it is
> sung. Nearly seven per cent of the syllables in the blends here were
> carrying more than one word.
>
> The share is by character count, which is the same guess `_cut` makes and
> wrong in the same small way. It cannot move a word's onset earlier than
> the donor put the group, and it cannot push one past the group's end, so
> the error it can introduce is bounded by the length of the lump.

### `_cry_lines`

**line 7767** — from the docstring, `def _cry_lines(items: list[dict]) -> set:`

> Lines that are an ad-lib somebody filed as a line of its own.
>
> Sources disagree about this constantly. Apple marks "(What)" inline and
> gives "Oh, God" a line to itself on the same song; QQ and NetEase file
> both as lines. Read as lines they are sung by the lead voice, in the lead
> voice's type, and they take a turn in the scroll that nobody sang.
>
> Nothing here is marked, so it is inferred, and the inference is kept
> narrow because the cost of being wrong is a real lyric drawn as an
> afterthought. All of:
>
>   * the line is nothing but shouting -- every word of it in CRIES;
>   * it is short, and it repeats somewhere else in the song, because an
>     ad-lib is a thing a song does more than once;
>   * both its neighbours are full lines, so a run of "Go, go, go!" against
>     itself is left alone -- that is a refrain, not an ad-lib;
>   * it is neither the first line nor the last.
>
> A looser version of this -- short, repeated, between two long lines, no
> vocabulary -- folded 3.2% of every line in this library and swallowed
> "You big disgrace" and "Suffocation, no breathing". With the vocabulary
> it folds 0.29%, and they are all "Yeah", "Ooh", "Come on".

### `lrc_shaped`

**line 7796** — from the docstring, `def lrc_shaped(doc) -> bool:`

> Whether NetEase, QQ Music or Kugou had a hand in this document.
>
> Three marks are read, because that hand can arrive by three routes:
> `_source` is the provider the walk settled on, `_alone` is the one a
> blend stood down to when its own answer was thinner, and `_via` names the
> upstream a proxy answered from, and a blend writes out its whole makeup,
> "Apple Music + QQ Music + NetEase".
>
> A grafted document is deliberately not one of them. There NetEase lends
> its word timings and nothing else; the lines, the brackets and the
> ad-libs on screen are all Spicy Lyrics' own, and they are not this
> repair's to make.

### `lifted`

**line 7811** — from the docstring, `def lifted(doc) -> bool:`

> Whether these lines were line-synced until somebody lent them words.
>
> Written where it happens rather than worked out here, because by the time
> the document reaches this it no longer remembers: _blend marks a document
> it laid a donor's timings over a base that had none, and graft_syllables
> marks its own output, which is only ever a line-quality base.

### `blended`

**line 7820** — from the docstring, `def blended(doc) -> bool:`

> Whether this document's timings were stitched together from more than
> one source.
>
> `_via` names the makeup a blend wrote out -- "Apple Music + QQ Music" --
> so more than one part in it is the mark of a blend. `_lifted` is the same
> answer arriving another way: _blend sets it where it laid a donor's clock
> over a base that had none, and graft_syllables sets it on a document whose
> words are one source's and whose lines are another's. Both are two sources
> reconciled, which is the whole of what this asks.
>
> `_alone` is read first and answers no. It is written where a blend stood
> down and handed over one donor's own document instead, and that document
> is one source's work however close it came to being a blend.
>
> A document nobody blended carries none of these -- a file off disk, a
> provider's own answer, a lyric somebody timed by hand -- and its ends are
> its author's measurements.

### `needs_adlibs`

**line 7831** — from the docstring, `def needs_adlibs(doc) -> bool:`

> Whether this document's ad-libs are still written into its lyric.
>
> Two ways they can be, and they are different faults with the same shape.
>
> lrc_shaped: NetEase, QQ Music and Kugou hand their lyrics over in an
> LRC-shaped document, and LRC has nowhere to put a second voice at all.
>
> lifted: the lines had only line stamps until a donor lent them word
> timing. A document with no word timing has no per-word groups either, so
> whoever wrote it had exactly two places to put a backing vocal -- in
> brackets inside the lead, or on a line of its own -- and both of those are
> what fold_cries and split_asides put back. The donor's clock is what makes
> it possible to; before the words were timed there was nothing to hang a
> background on.
>
> Still not "repair everything": a document that marks its own backgrounds
> is believed, whoever wrote it, which is the case lrc_shaped's own
> docstring was written around.

### `split_asides`

**line 7837** — from the docstring, `def split_asides(doc):`

> Ad-libs a document writes into the lyric, made backing groups of it.
>
> Apple marks a backing vocal by putting it in brackets inside the line's
> own text -- "Life's got me by the neck with a blade against it (What?)".
> Every other way a document can say "this is a second voice" gets drawn as
> one: NetEase files the same "(What?)" as a proper background and it comes
> out beside the line, in the ad-lib's own place, filling on its own. Left
> in the text it is drawn as part of the lead, in the lead's size, and its
> words light when the last word of the line does.
>
> The blend already peels a bracket off when a donor has separate timing
> for it (see _peel_bracket), which is the better answer because the timing
> is somebody's measurement rather than ours. This is for all the rest, and
> it needs no donor at all: the words are in the line, so the line's own
> syllables already say when they are sung. They are lifted out and the
> lyric keeps everything else.
>
> A line that is nothing but the bracket goes onto the line before it
> instead, timing and all, the way fold_cries moves a shout -- there is no
> lead of its own to hang it on, and a document that marks its ad-libs this
> way has said what that line is. Only where it sits against the line
> before: an ad-lib alone in the middle of a gap is not that line's.
>
> And only where it stands ALONE. Bracketed lines that come one after
> another are not asides at all, they are a passage sung by the second
> voice, and each of them is a lyric in its own right: "(Caught up in the
> storm but we're the survivors)" is answered by "(Lookin' out for love in
> a little bit of darkness)", and "（You're such a fail, what's wrong with
> you?）" by two more like it. Folding those hangs a whole section off one
> line of the verse above it as a whisper. A run of them is left as it
> stands unless every line in the run is a plain shout -- "(Yeah)",
> "(Woo)" -- which is a document listing its ad-libs, not singing a
> passage. See ASIDE_WORDS and CRY_WORDS: the two counts are exactly this
> difference.
>
> Left alone: any bracket whose words the line does not time cleanly, which
> is the answer whenever the two do not line up exactly.

### `_unbracket_edges`

**line 7929** — from the docstring, `def _unbracket_edges(syls: list, run: list, drop: set, edits: dict) -> None:`

> Take the brackets off what an ad-lib leaves behind.
>
> The run is chosen on letters alone, so a source that writes its brackets
> as syllables of their own -- NetEase writes "（", "No", "thoughts", "）"
> -- has them stepped straight over: the words left with the ad-lib and the
> marks stayed standing on the lead, "Hold my hand ( ) tonight". Where the
> same marks are glued to a word instead they ride out on the word before
> and the word after, and have to come off those without taking the word
> with them.
>
> A mark left with nothing on it goes altogether rather than staying as an
> empty syllable: the space between two words is drawn from IsPartOfWord
> when the line is written out, so nothing is holding it apart.
>
> One neighbour each side and no further. Two ad-libs in a row would
> otherwise reach past their own bracket into the one beside it.

### `_reglue`

**line 7943** — from the docstring, `def _reglue(syls: list, kept: list, live: list) -> None:`

> Let a word end where the ad-lib that was finishing it went.
>
> "You (Okay), must find" is two words to the source: "You (" is marked
> part-of-word because "Okay)," is the rest of it. Move the ad-lib into the
> Background and the mark is a lie -- the word ends at "You," now -- but the
> flag still says the next syllable is glued on, and the line came out
> "You,must find".
>
> Whatever stood last before the next surviving syllable is the thing that
> knew whether the word carried on into it, so its flag comes back with it.
> A bracket inside a word, "wo(oo)ah", is marked glued there and stays
> glued here, which is the same rule and the right answer for it.

### `clean_edit`

**line 8101** — from the docstring, `def clean_edit(doc, tid: str, meta: dict, enabled=None) -> str:`

> Why the masks in this document are to be left alone, or "" if they are not.
>
> Five questions, cheapest first, and the string that comes back is the one
> the window puts on screen -- a mask left standing with nothing said about
> it is how a provider that had quietly failed went unnoticed for weeks.
>
> Two of the five are about the RECORDING being the clean cut, where
> filling a mask writes a word over a bar of silence. The other two are
> about whose words these are: a document somebody typed is not a document
> with a defect in it, and its masks are that person's reading of what they
> heard.
>
> Only ever reached for a document that HAS masks: `uncensor` counts them
> before it asks anything, and the great majority of songs have none. So the
> order below is about what the rare song costs, not the common one.
>
> None of the four is allowed to answer from silence. A source that was not
> asked, or was asked and had nothing, says nothing -- it does not say the
> recording is explicit, and it does not say it is clean.

### `_hidden`

**line 8136** — from the docstring, `def _hidden(word: str) -> bool:`

> Whether a word has had letters taken out of it.
>
> Two characters at least: a lone asterisk is a footnote mark or a
> separator, not a word with something hidden inside it.
>
> And a word with stars on BOTH sides of it is not one either. Asterisks
> around a word that is all there are an effect -- *spit*, *Taylored* --
> which is how a lyric writes a stage direction or leans on a word, and
> every one of them is spelled exactly as it is meant to be read. Counting
> those as masks sent the pass to two servers for a song with nothing to
> mend, and left it holding a word it might have talked itself into
> replacing.

### `_blank`

**line 8146** — from the docstring, `def _blank(mask: str) -> bool:`

> Whether a mask says nothing about the word at all.
>
> Two kinds of mask get written, and they are not the same evidence. One is
> written OVER the word -- "n***a", "f**k", "h*es" -- and keeps its length
> and every letter it did not hide. The other stands IN for it: Apple
> writes four stars for a word of any length, and 21 of the 35 masks in the
> track this was measured on hide a five-letter word behind them. The first
> kind can be matched; the second can only be placed.

### `_fill`

**line 8152** — from the docstring, `def _fill(mask: str, word: str) -> str:`

> `mask` with its letters put back from `word`, or "" if that is not it.
>
> Character for character, and the mask wins every character it wrote: the
> case, the apostrophes and the punctuation that come out of this are the
> document's own, and only what was hidden comes from the donor. A donor
> word of a different length is not the word being hidden -- this kind of
> mask is written over the word rather than in place of it -- and one that
> is masked itself has nothing to give.

### `_syl_words`

**line 8172** — from the docstring, `def _syl_words(syls: list) -> list[tuple]:`

> (where the word lives, what it says) for every word in one group.
>
> A word ends at the syllable that is not part of the word after it -- but
> it can also end INSIDE one, and it can be spread across a great many of
> them, and a document that has been through the blends does both:
>
>   "This ****"                 two words under one stamp, which is how
>                               plenty of sources write them
>   "*" "*" "*" "*"             one mask relayed onto somebody else's
>                               timing, which lends a stamp per character
>
> So a word is located by character range rather than by whole syllables --
> a tuple of (syllable, from, to) -- which addresses either. Reading them
> by whole syllables left every mask in a NetEase-timed document unfindable
> and every mask that shared a stamp with its neighbour unmatchable, which
> between them is most of the masks in a blend.

### `_spread`

**line 8199** — from the docstring, `def _spread(word: str, widths: list) -> list:`

> `word` cut into as many pieces as the mask it is replacing was cut into.
>
> The pieces of a mask are STAMPS: a relay lends a document its donor's
> timing by cutting the base's text across the donor's syllables, and a run
> of stars gets cut like any other letters. The word going back in has to
> be cut the same way, because those stamps are the timing this document
> was built on and there is nothing here that could re-time them.
>
> Cut in the mask's own proportions, and cumulatively, so a word that is
> longer or shorter than the mask spreads its difference along the run
> instead of dumping it all in the last piece.

### `_groups_of`

**line 8217** — from the docstring, `def _groups_of(it: dict, i: int) -> list[tuple]:`

> One line's groups, as (where, whatever is holding the words).
>
> A line keeps its words in its lead group's syllables -- or, where the
> source only ever had lines, in the line's own Text and no group at all.
> Reading and writing have to make that choice the same way, and a document
> that has a Lead with no syllables under it is the one that catches a walk
> making it differently: the words are read off the line, and the letters
> put back into a group that never held them. Nothing changes on screen and
> nothing raises.

### `_word_slots`

**line 8229** — from the docstring, `def _word_slots(items: list) -> list[tuple]:`

> Every word in a document, in the order it is sung.
>
> (where, which, text): `where` names the group -- ("lead", line) or
> ("bg", line, k) -- and `which` is the syllables that spell the word, or
> the word's place in a line that has no syllables under it at all. The two
> together are enough to find the word again when it is time to write it
> back, and the walk is in document order, so one document's words can be
> aligned against another's straight through.

### `_slot_key`

**line 8249** — from the docstring, `def _slot_key(at: int, text: str) -> str:`

> One word, as the aligner compares words.
>
> A masked word is given a key of its own so that it can never match: it is
> the thing being looked for, and the whole method is that it falls into
> the gap between two stretches that did match. A word with no letters in
> it gets one too -- two documents agreeing that a line contains a comma is
> not the two of them agreeing about a line.

### `_stand_in`

**line 8256** — from the docstring, `def _stand_in(mask: str, word: str) -> str:`

> The word a blank mask is standing in for, taken on trust from its place.
>
> A mask with no letters left in it cannot be matched against anything, so
> the only evidence there is is where it stands -- and this is only ever
> asked where that evidence is as strong as it gets: the words either side
> of the mask are words the donor sings too, and the donor has exactly one
> word between them. The mask keeps its own punctuation and takes the
> donor's letters, case and all, having none of its own to keep.

### `_spine`

**line 8266** — from the docstring, `def _spine(a: list, b: list) -> list:`

> Anchor pairs (i, j) for two tellings of the same song, in order.
>
> difflib takes the longest block it can find anywhere and fits everything
> else around it, which on a lyric means it is free to match a chorus to
> the same chorus sung two verses later. What comes back is a perfectly
> good alignment; it is just not the one where the song lines up with
> itself, and a word that has been masked out is then looked for beside the
> wrong neighbours -- or falls into a gap that runs backwards, where there
> is nothing to look at at all.
>
> So the spine is built first, out of the words that occur exactly ONCE on
> each side: one copy cannot be matched to the wrong copy of itself. The
> longest run of those that moves forward on both sides is an alignment
> that cannot have jumped, and the stretches between them are short enough
> for difflib to be right about. This is patience diff, for the reason
> patience diff exists.

### `_unglue`

**line 8309** — from the docstring, `def _unglue(mask: str, theirs: list, at: int) -> str:`

> A mask that has lost the space between it and the word beside it.
>
> A relay lends a document somebody else's timing by cutting its words
> across the donor's stamps, and the boundary between two words can go with
> the cut: what is left under one stamp is "the*****", which is a word
> nobody ever sang and which nothing could ever match, because there is
> nothing there to match. It is the commonest way a mask survives a blend
> -- on the three blends measured here it is most of them.
>
> The donor has both words, so the glue is undone against it rather than
> guessed at: the letters have to BE the donor's word at that place --
> exactly, or by filling a mask of their own -- and only then may the run
> of stars beside them take the word next to it. The space comes back with
> them, and unlump gives the two halves a stamp each.

### `_like`

**line 8336** — from the docstring, `def _like(mask: str, word: str) -> bool:`

> Whether a donor word could be what a DAMAGED mask was written over.
>
> A weaker question than the one _fill asks, for the case where the mask can
> no longer answer the strong one. A mask is written over its word and keeps
> its length -- but a blend cuts a document's words across its donor's
> stamps, and a mask cut that way can lose characters to the syllable next
> door: "C**ked," comes back as "c**k," and is four letters where the word
> is six. Matched character for character it fits nothing, and it never
> will.
>
> What its letters still do is appear, in order, in the word it was written
> over. A word the singer did not sing has no reason to spell them in that
> order, and this is only ever asked where the placing is already as good as
> it gets -- one word of ours between two words both documents share, and
> one word of theirs in the same place.

### `_uncapped`

**line 8365** — from the docstring, `def _uncapped(mask: str, got: str, opens: bool, they_open: bool) -> str:`

> `got` with a capital that belonged to the DONOR's line break taken off.
>
> Where a line ends is an editorial decision and two sources make it
> differently -- which is why _unmask_with aligns them as one stream of
> words in the first place. A capital at the start of a donor's line is
> that decision showing, not a fact about the word: Musixmatch breaks
> "...eight in the process, nigga tryna tippy-toe..." after "process" and
> capitalises what follows, and Apple, which writes the whole of it as one
> line with two blank masks in it, was handed that capital back in the
> middle of its line.
>
> So it is taken off again -- but only where every part of the reason is
> present. The mask has to have hidden the first letter, because a mask
> that kept one has already said what the case is (see _recase and _fill).
> The donor's word has to begin the donor's line, because a capital
> anywhere else is the donor spelling a name. And ours must not begin
> ours, or the capital is right where it stands whatever it came from.
> A word in capitals throughout is left alone: that is a spelling too, and
> lowering its first letter alone would make a mess of it rather than a
> sentence.

### `_only_fit`

**line 8388** — from the docstring, `def _only_fit(mask: str, theirs: list, memo: dict) -> str:`

> The word the donor is hiding, when the donor only knows one that fits.
>
> The fallback for a mask the alignment could not put a finger on. Asked of
> the whole donor rather than of a window, so it is only allowed an answer
> the donor is unanimous about: "n***a" has one spelling in any document
> that has the word at all, and a mask like "****" that half the four
> letter words in the song would fit gets no answer from here, which is the
> right answer. The donor is already known to be this recording -- nothing
> reaches here until it has matched half the document.

### `_unmask_with`

**line 8404** — from the docstring, `def _unmask_with(doc, donor):`

> `doc` with every mask this donor can fill filled in, and how many.
>
> The two documents are aligned as one long stream of words rather than
> line by line, because where a line ends is an editorial decision and two
> sources make it differently -- and because a mask cannot match anything,
> so it lands in a gap between matched stretches wherever the lines fall.
> What is in the donor's side of that gap is what the mask is hiding.

### `uncensor`

**line 8539** — from the docstring, `def uncensor(doc, tid: str, meta: dict, enabled=None, on_skip=None):`

> A document with the words its source masked put back into it.
>
> Costs nothing at all on a document that has none: the masks are counted
> before anybody is asked anything, and the great majority of songs have
> none to count. Where there are some, the donors are asked in order and
> each is given whatever the one before it could not fill -- Musixmatch and
> LRCLIB do not mask the same words, and neither of them masks many.
>
> `enabled` is the set of sources the user has switched on, so a donor
> turned off for the chain is not quietly asked here either.
>
> A recording that is ITSELF the clean cut is left exactly as it is, and
> `on_skip` is told why so the window can say so. See clean_edit: filling a
> mask whose word is not in the audio does not restore anything, it writes a
> word over a silence.
>
> Either refusal hands back `doc` -- the very same object, never a copy.
> The window tells a new lyric from the one it is drawing by identity, and a
> document that says what the last one said must not cost a rebuild.

### `graft_syllables`

**line 8573** — from the docstring, `def graft_syllables(base, donor) -> dict | None:`

> Lend a word-timed document's timings to a line-timed one's own lines.
>
> Spicy Lyrics' lyrics are the ones actually chosen for display -- its
> wording, its line splits, its casing -- but where it only has line stamps it
> cannot say when inside a line each word lands. A word-timed source can,
> without having to supply the words as well.
>
> The whole result is put on the donor's clock, including the lines that did
> not match: a line still timed by the base would sit against a different
> reading of the song, and the seam is audible where they meet.

### `_tie_backing`

**line 8740** — from the docstring, `def _tie_backing(lines: list[dict], flags: list[bool]) -> list[bool]:`

> Give every ad-lib the side the line it belongs to hangs off.
>
> An ad-lib is not a voice of its own: it is written inside a line and it is
> drawn against that line, indented from whichever edge the line hangs off.
> Letting it answer this question separately puts a backing vocal on the far
> side of the screen from the words it is backing, which is not a thing the
> layout is supposed to be able to do.

### `_transfer`

**line 8756** — from the docstring, `def _transfer(ours: list[dict], theirs: list[dict]):`

> Copy their per-line flag onto ours, matching the lines by text.
>
> Line counts never agree exactly -- the two sources split and merge
> differently -- so this aligns the two text sequences and only trusts the
> stretches that match outright.
>
> Ad-libs are kept out of the match on both sides and take their own line's
> answer afterwards. Their text is short, repeated, and identical wherever a
> chorus repeats -- "ooh", "yeah", the hook sung behind itself -- which is
> exactly the material a sequence match pairs with the wrong copy; and the
> side an ad-lib hangs off was never its own to have.

### module level (comment)

**line 1585** — before `r"|^\s*[^\W\d_][\w&/'’.\- ]{0,38}?\s[:：]\s*\S"`

> The shape rather than the word: NetEase writes every credit "Role :
> Name", a space either side of the colon, and the roles are as many as
> there are instruments. Beat It's run "Producers", "Rhythm Guitar",
> "Synclavier", "Drum Case Beater"... past the list above as fifteen
> lines of lyric -- 444 letters that made Apple's whole copy read as
> missing a section, so NetEase took the song from BiniLyrics. Measured
> over 1624 cached documents (79653 lines): this matched credits only.

---

## Lift — 2026-09-26

Comments lifted out of `mild-lyrics/lyric_sources.py` on 2026-09-26; the line numbers are that day's.

### module level

**line 91** — before `REVISION = 1`

> What a stored answer was written by. It rides on every record under
> `sources` and a walk will not read one back that does not match, so bumping
> it is how a change to the document shape or to the chain throws the old
> answers away rather than drawing them.
>
> Counted from one again at 1.0.0. It had reached seventeen, which measured
> nothing but how many times the shape changed before there was a version to
> say it in -- and it costs one re-walk per song, spread over listening, which
> is what every one of those seventeen cost.

**line 366** — before `_HOST_PATIENCE: dict[str, float] = {}`

> A host that wants longer than TIMEOUT before it is given up on. Empty since
> LyricsPlus went: twenty seconds was its, and nothing else here has ever
> asked for more than the eight everybody gets.

**line 388** — before `_host_hush: dict[str, float] = {}`

> host -> monotonic time before which it is not asked anything. Set from the
> Retry-After (or RateLimit-Reset) of a 429 or 503: LRCLIB hands out temporary
> bans to clients that keep asking through one, and every provider here
> shares this door, so one refusal quiets the host for everything that would
> have gone to it -- fetch-ahead included -- rather than just the request
> that heard it.

**line 500** — before `OPENS = _OPENS + "\"'\u2018"`

> Every mark that can open a word, the ambiguous " and ' among them.

**line 1008** — before `SPICY_BASE = (os.environ.get("SPICY_LYRICS_API")`

> Spicy Lyrics.
>
> The source this project was built around, and now an ordinary provider in
> this file with the other ten: one HTTP request, a key, the same timeout, the
> same trouble reporting, the same cache rules. It reads by Spotify track id
> rather than by title and artist, which is the one thing that makes it
> different in kind -- and is why it can be asked before the rest and its
> answer handed to them as the document already in hand; see _walk's lead.
>
> It used to be read over the Chrome DevTools protocol out of the Spicetify
> extension's own Cache Storage inside a running Spotify, which is why it
> lived in spicy_lyrics.py and not here. That module keeps what it always
> was -- the document, its timeline, its renderers -- and none of the fetching.

**line 1026** — before `SPICY_CODES = {"spicy_lyrics": "spl", "apple_music": "aml", "spotify": "spt",`

> Spicy Lyrics names the winning catalogue in full; this project has always
> filed it in three letters, and those three letters are what is written into
> the snapshots, the datasets and every "was this a person's work" branch in
> sync/. Translating here, at the one door its documents come in by, is what
> keeps a fetch made today comparable with a snapshot taken last year.
> "unknown" becomes no source at all, which is what an unattributed document
> has always looked like downstream -- and what the terms require it be called.

**line 1036** — before `SPICY_SHIPPED_KEY = "sl_pk_2fyQ-sFN0OnWEjG9WmusHHY9vS8Re7zHj3kSbJncHbM"`

> The key that ships. Public by design: a publishable key travels in the
> program and anyone can read it, which is exactly why a SECRET key must never
> be put here. This one is issued with the "no Origin header" allowance, which
> is what a desktop client needs -- nothing here is a browser, so no Origin is
> ever sent and an allowlist would refuse every request made from here.
> Verified against the live API on 2026-09-20 with no Origin header sent.

**line 1047** — before `SPICY_DIR = _cache_root() / "spicy"`

> Its own directory rather than a corner of `sources`, because the two answer
> different questions. A record under `sources` is what a WALK decided, and is
> read back only by a walk asking the same question of the same providers;
> these are one catalogue's answer about one track, asked for by id, and they
> are the only list of songs this program can offer -- the API answers about a
> track and does not enumerate its catalogue. Same rules either way, and
> sweep() clears both.

**line 1057** — before `_spicy_hushed = 0.0`

> Set when this application's OWN request window is spent. Nothing asks again
> before it passes: the window fetches on every track change and the batch
> tools walk thousands of ids, so the one thing this must not do with a rate
> limit is spend the whole of the next window finding out about it again.
>
> Only ours. A 429 whose code is `upstream_rate_limited` is Spicy Lyrics being
> throttled by the catalogue it asked, for that lookup -- measured with 56 of
> 60 requests still in hand, and the very next track answering 200. Standing
> the whole program down over one of those would turn one unlucky song into a
> minute of silence for every other song.

**line 1070** — before `SPICY_LIMIT: dict = {}`

> What the service last said was left of the window, as
> {"limit", "left", "reset", "at"}. Every answer carries it, happy or not.

**line 1161** — before `SPOTIFY_IDS = _cache_root() / "spotify-ids.json"`

> A Spotify id for a song playing somewhere else, for Spicy Lyrics to be asked
> by. Only ever used with the reader's "Spotify lookup" on (see
> lyrics_gui.Fetcher._spotify_id).


### `_spicy_fetch`

**line 1384** — before `if exc.code == 404 and bad.code in ("lyrics_not_found", "not_found", ""):`

> 404 is the one unhappy status that is an ANSWER: nobody has lyrics
> for this track. It is worth remembering for a while (see MISS_TTL)
> and it is not worth telling anyone about. Read with its code rather
> than on the status alone, so that a 404 from somewhere that is not
> this endpoint -- a base URL pointed wrong, a proxy answering for it
> -- is the failure it is instead of six hours of "this song has no
> lyrics".

**line 1393** — before `if exc.code == 429 and bad.code in ("rate_limited", ""):`

> Our own window, and only ours: `rate_limited` is this application's
> (or this viewer's) budget spent, and nothing else will be answered
> until it resets. `upstream_rate_limited` is the catalogue throttling
> Spicy Lyrics for one lookup, and the next track is unaffected.


### `_spicy_path`

**line 1444** — before `def _spicy_path(track: str) -> pathlib.Path:`

> Its cache. The same rules as the walk's own -- a record per track, a month
> from its last use, six hours for a "nobody has this" -- and the same reasons;
> see _cached.


### `_spicy_record`

**line 1479** — before `return None`

> A community sync is somebody's upload, and uploads get taken down
> and replaced. Kept on use alone, a song in rotation went on crediting
> a sync Spicy Lyrics no longer had. Asked about again every few
> days from when it was FETCHED -- one request, never a retry.


### `spicy_lyrics`

**line 1534** — before `failed = _spicy_failed.get(track)`

> One walk asks this several times over -- the lead, the chain, the
> blends, the fetcher's own retries -- and a failure was not remembered,
> so a service that was already struggling was asked again for the same
> track each time. It is now left alone for that track for a while.

**line 1550** — before `held = spicy_held(track)`

> A reload that could not get through keeps what it had: the
> old document is still this song's, only perhaps not newest.


### module level

**line 4210** — before `BINI_STORE = "https://lyrics-storage.binimum.org"`

> Where its documents live. Its own storage holds Apple's TTML as Apple wrote
> it, filed by ISRC, and is asked first. Its rows' lyricsUrl names lrc.red,
> which serves a copy fetched from that storage and rewritten on the way --
> followed only where the storage has no file under that code.

**line 4496** — before `NATIVE_STORE = ((re.compile(r"[\u3040-\u30ff]"), ("jp",)),`

> Kana, Hangul and Han, and the storefront that writes each one natively.
>
> The US storefront romanises: it answers "Idol" for YOASOBI's アイドル,
> "Usseewa" for Ado's うっせぇわ, "Show" for 唱. A player says what its own
> catalogue says, which for this repertoire is the native title -- so the
> search matched nothing, no ISRC came back, and BiniLyrics (which files by
> ISRC) was never asked. Measured over eight Japanese-titled tracks here, six
> of them got no ISRC at all from `us` alone.
>
> Han on its own does not say which language it is, so it asks both.


### `_apple_song`

**line 4729** — before `if code and _near(secs, want):`

> Each half of the name, remembered against the recording it names,
> so a storefront that writes only one of them the player's way
> still gets a vote. See _confirmed.


### `_krc_items`

**line 5176** — before `toks = [(off, dur, html.unescape(word))`

> Kugou leaves some documents HTML-escaped -- "don&apos;t" on Grant's
> Color -- so each syllable is unescaped after the tags are read.


### `_walk`

**line 7544** — before `mine, lead_name = False, ""`

> THE LEAD. One provider is asked before the rest and alone, and what it
> answers becomes the document the others have to beat: Spicy Lyrics reads
> by track id, costs one request, and word-syncs most songs, so asking it
> first is what keeps the usual song from fanning out to ten servers that
> could not have won anyway. This is the shape the window's own loader had
> -- fetch Spicy, then hand it to the chain as `local` -- moved in here so
> that every caller gets it and not just that one. A caller holding a
> document already (the window still does) passes it as `local` and no
> lead is asked.

**line 7564** — before `if not ahead and order and name in order:`

> What the caller would have worked out for itself: the sources it
> ranked ABOVE the lead still get asked, since a tie goes to the
> one the user put first and a word-timed lead must not end the
> walk before they have answered.

**line 7587** — before `names = [n for n in walk if (enabled is None or n in enabled)`

> The lead is never in the fan-out: it has already answered, and its
> answer is `local`.


### `_relay`

**line 8342** — before `if 0 < at < len(idx):`

> An opening mark before the next letter opens the next word. Cut at
> the letter, the « of `crie : « Akha »` was timed with "crie :". So
> back over spaces and openers -- a mark counting as one only with a
> space before it, so the " closing `you" now` stays where it is.


### module level

**line 8376** — before `WORD_MARKS = re.compile(r"^[&+/@$%#=€£¥]$")`

> "$" is bbno$'s "money" and GEOMETRY DASH GANGSTER RAP's "dollar", and a
> source that times one has timed a word: folded into the syllable before
> it, it lost its turn and took the end of the word with it.


### `_mark_only`

**line 8385** — before `text = SL.canon(str(text or ""))`

> Folded first: Apple writes 風 as ⾵ (KANGXI RADICAL WIND) in God-ish,
> a symbol rather than a letter, and "“⾵”" read as nothing but quotes --
> so it was folded into the syllable before it and "fuu" had no clock.


### module level

**line 8393** — before `SPOKEN_MARKS = set("./:")`

> The marks a reader says out loud when one stands between two characters of
> the same token: "2.3" is two point three, "Twitch.tv" is Twitch dot tv,
> "24/7" is twenty-four seven, "9:15" is nine fifteen. Everything else --
> commas, question marks, quotes, brackets, the hyphens in a melisma -- is
> read as shape or as silence however it is welded in, and stays quiet.


### `_spoken_mark`

**line 8430** — before `return ((bool((prev or {}).get("IsPartOfWord")) or bool(y.get("IsPartOfWord")))`

> Either flag will do. Sources set them inconsistently on a mark -- 2|.|3
> came with the point flagged and the 2 not -- and what actually says
> the three are one token is the text touching on both sides.


### `no_overlap`

**line 8569** — before `out.append(it)`

> Wholly inside the next line's time: nothing here is a tail.


### `no_overlap.clip`

**line 8588** — before `if i == last and st < nxt < en:`

> Only the last syllable's end is slack. An interior one's
> end IS the next one's onset -- a measurement, and moving
> it ends a word before it is sung.


### `no_overlap`

**line 8603** — before `floor = float(start) if isinstance(start, (int, float)) else None`

> The last moment the line is still singing: its own end may give way
> to `nxt`, but never past this.


### `_unlump`

**line 8761** — before `joined: list[str] = []`

> Punctuation alone goes with the word before it -- except an opening
> mark, which opens the word after it: « in `crie : « Akha »`.


### `_fold_onto`

**line 9046** — before `if _key(said) == _key(SL.line_text(host)):`

> An echo of the line is not an ad-lib on it. Apple writes Conro's "All I
> Want" as "All I want" at 30.60 and "(All I want)" at 32.88 -- a call and
> its answer, two lines, sung a bar apart. Folded together they are drawn
> together: one line running 30.60 to 33.99 with the same three words in
> the lead and in the backing group, which reads as the lyric stuttering.
> Nothing is gained by it either; the echo already had a line and a time
> of its own.


---

## Lift — 2026-09-17

### module level

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


### `_get`

**line 434** — before `if not _walking():`

> Asked again on the way in, because the wait for a permit is where a
> dropped walk spends most of what it costs everybody else: the host
> that gates hardest is the slowest one. Handing the permit straight
> back is the whole point.


### module level

**line 510** — before `_OPENS = "\u00ab\u201c\u00bf\u00a1([{"`

> Marks that cannot sit against the text on one side of them, whatever the
> spacing in the file says. See _apart.


### `_syllables`

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


### `_repair`

**line 642** — on `            _repair(timed, begin, end)`

> the same dicts, mended in place

**line 670** — on `        up = max(lo, up)`

> the sane neighbours may themselves overlap


### `parse_ttml`

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


### module level

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


### `_youly`

**line 1305** — before `if answer is not None and _honoured(source, answer[1]):`

> A pin the server could not honour is a different catalogue's
> document, not this one's -- see _honoured. The other shape of the
> question is still read; it sometimes reaches the copy the first one
> missed. In the order they were asked in, so that the shape most
> likely to be the right recording is the one taken where both
> answered.


### module level

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


### `_ne_rank`

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


### `_restream`

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


### `_in_step`

**line 2178** — before `tails, back = [], [len(out)] * len(out)`

> Longest non-decreasing run through the starts, by patience sorting over
> the positions rather than the values, so what it keeps is the lines that
> were already in order.

**line 2186** — on `        while lo < hi:`

> rightmost slot this start fits


### module level

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


### `in_order`

**line 2492** — before `if mine[0] is None or abs(mine[0]) <= BLEND_LEAD:`

> Nothing can beat a shift smaller than the margin, so the second donor
> is not measured at all in the case that is nearly every song. _clock
> re-streams to answer, which is the same work _blend is about to do.


### `_blended`

**line 2846** — before `lead, fill = in_order(base, (got["timed"], whose, alone),`

> Which of the two times the song and which one fills its gaps is settled
> against the base, song by song, rather than by the order they are
> written in here. See in_order.


### `stand_down`

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


### module level

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


### `_reworded`

**line 2950** — before `from difflib import SequenceMatcher`

> Matched here rather than through _pair, whose job is to decide whether
> two documents are the same recording at all -- it measures the share
> that matched against the SHORTER side and refuses below it. That is the
> right question when a donor might be answering about a cover; it is the
> wrong one here, where the caller has already established these are the
> same lyric and one of them is short. Apple's 17 lines against QQ's 31
> failed that share and left every line written QQ's way.


### `from_blend`

**line 3026** — before `return _blended(tid, meta, local, from_qq, "QQ Music", "qq", above)`

> "qq", because that is whose document this stands down to. The name was
> carried over as "apple" when Lyrics+ was renamed after the catalogue it
> usually answers from, which credited QQ Music's own sync to Apple.


### module level

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


### `_lift_strays`

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


### `_peel_bracket.take`

**line 3509** — before `best = None`

> Whoever wrote it most nearly the way we did. The pool holds both
> donors and a song repeats its shouts, so first past the post is not
> good enough: Apple's "(Woo, woo)" should take QQ's "Woo, woo" over
> its "Woo" when the song has both.

**line 3519** — before `if not (_kin(key, k) or (cry and _a_cry(said))):`

> The same shout spelled differently is still the same shout, and
> at this distance from the line there is nothing else it could
> be: Apple writes "(Ooh)" where QQ times "Woo".


### `_peel_bracket`

**line 3542** — on `    if not _key(left):`

> the line was the ad-lib and nothing else


### `_blend`

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


### module level

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


### `_plain_title`

**line 4491** — before `if _cut_words(was) - _cut_words(got):`

> A marker that names a different recording stays: the second search is
> for the same song under a shorter name, not for another cut of it.


### `from_unison`

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


### module level

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


### `_amp`

**line 4762** — before `if e.code not in (401, 403) and e.code not in MISSED:`

> 401 and 403 are the token having turned over, which the caller
> answers by fetching a new one -- not something to report as Apple
> Music being unreachable.


### module level

**line 4773** — before `APPLE_NAMES = re.compile(r"\s*(?:,|&| and )\s*")`

> Apple writes a credit as one string -- "Chris Martin, Guy Berryman, Jonny
> Buckland & Will Champion" -- and TTML wants one <songwriter> each, so it is
> cut back apart here. The same three separators the editor has always used;
> it reads them from this so the two cannot come to disagree about a name.


### `_apple_song`

**line 4862** — before `loose.append(((0 if lead else 1, abs(secs - want)), at, rank))`

> The song, at another length: an album cut against a single, or
> an upload with a few seconds of silence welded on the front.
> Not the recording, so it is no use for an ISRC -- but it is the
> same song, so its cover is the right cover. See _apple_card.


### `_apple_card`

**line 4932** — before `"explicit": True if rating == "explicit" else False if rating else None,`

> None where Apple did not say, which is what every other source
> here means by it.


### module level

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


### `_soundcloud_card`

**line 5079** — before `"art": _sc_art(row.get("artwork_url") or ""),`

> The track's own cover and nothing else. An upload without one is
> drawn on the site with the uploader's avatar, which is a photograph
> of somebody rather than a cover, and the player's own thumbnail
> beats that.


### `from_bini`

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


### module level

**line 5251** — before `KRC_KEY = bytes((64, 71, 97, 119, 94, 50, 116, 71,`

> KRC is Kugou's own lyric format and the only word-timed one it serves. It
> arrives base64'd, with a four-byte "krc1" header, XOR'd against a fixed
> sixteen-byte key and then deflated -- an obfuscation rather than a secret,
> published the same way in every client that reads it.


### `_krc_items`

**line 5301** — before `said = NE_WROTE.match(body) if body else None`

> Dropped from the lyrics, kept as what it says. Kugou stamps the
> credits like verses -- "Lyrics by：Vivian Weeks" timed across the
> intro -- and they are the only place it names a writer.


### module level

**line 5338** — before `NO_WORDS = re.compile(`

> 请欣赏 -- "please enjoy" -- is the tail of the whole family of Kugou's
> placeholder cards, and it is the part worth matching. Listing the fronts one
> at a time got 纯音乐 ("pure music, please enjoy") and missed DJ音乐, which is
> the same card for a DJ edit and went on screen as the lyric. Safe to match
> on its own: _instrumental only ever looks at a document of three lines or
> fewer, and a song whose entire lyric is "please enjoy" has no words either.


### `_kugou`

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


### module level

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


### `_qrc_tables`

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


### `_qrc_des`

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


### module level

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


### `_qrc_items`

**line 5779** — before `said = NE_WROTE.match(body) if body else None`

> Dropped as a lyric, kept as what it says: QQ stamps "作词 : X"
> over the intro the way NetEase and Kugou do, and it is the only
> place either of them names a writer.


### module level

**line 5853** — before `QQ_SAYS = re.compile(r"^\s*(.+?)\s*[:：]\s*$")`

> A line that is a name and a colon and nothing else -- QQ marks who takes
> each verse of a collaboration that way, and times the mark like a lyric.


### `_qq_head`

**line 5900** — before `names = _who(said.group(1)) if said else []`

> Read as a credit line rather than as one name, because QQ writes the
> handover both ways: "Maître Gims：" where one of them takes the
> verse and "Dua Lipa/DaBaby：" where they take it together. Every
> name in it has to be somebody the song credits -- one known name
> beside an unknown one is not a label, it is a lyric with a slash.


### `_qq_doc`

**line 5918** — before `roma, _ = _qrc_items(parts.get("contentroma") or "")`

> The romanisation is word-timed QRC of its own, on the same line clock as
> the lyric, so the lines pair up by where they start. Only its text is
> kept: the view romanises a line, not a syllable.


### module level

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


### `_mxm_token`

**line 6060** — before `return "" if force else held`

> Refused lately. A forced ask is one whose token has just been
> retired, so there is nothing to fall back on there either.

**line 6065** — before `try:`

> A failed ask writes down only the refusal, which drops the dead token
> with it: keeping it would spend a request per track discovering again
> that it is dead.


### `_mxm_spans`

**line 6203** — before `flat = [y for it in out for y in (it["Lead"]["Syllables"] or [])]`

> Across the lines as well as inside them: "the word thereafter" is the
> next line's first where a line has run out, and two lines a tenth of a
> second apart are one phrase however they were cut.


### `_mxm_rich`

**line 6241** — before `cut = sum(1 for i in out if len(i["Lead"]["Syllables"]) > 1)`

> ...unless it is line timing wearing a syllable's clothes. Musixmatch
> richsync for a Japanese lyric is frequently one token per line -- on
> Kenshi Yonezu's "Peace Sign", 43 of the 60 lines are the whole line at a
> single stamp -- and a document like that is shaped exactly like a real
> word sync while carrying none of the information. Left alone it beats a
> line-synced document from a source ranked above it, and the reader gets
> the same timing with a worse lyric. _deword is the honest reading, and
> it is the same trade _youly already makes on a Musixmatch scrape.


### module level

**line 6274** — before `_MXM_EXPLICIT: dict = {}`

> Whether Musixmatch called the matched track explicit, filed under the same
> key as its document. Not carried on the document itself because the document
> is often None -- an instrumental, a restricted track, a song nobody has
> synced -- and the rating is worth having in every one of those cases. Swept
> against _ONCE so it cannot outlive the answer it was read from.


### `_musixmatch`

**line 6348** — before `token = _mxm_token(force=True)`

> The stored token has been retired. Worth exactly one more ask, and
> not worth one at all if the cool-off says the answer will be no.

**line 6355** — before `track = _mxm_body(calls, "matcher.track.get").get("track") or {}`

> Kept whether or not there is a document to go with it. See
> mxm_explicit, which is the only reader.


### `_mxm_doc`

**line 6380** — before `lrc = "" if sub.get("restricted") else str(sub.get("subtitle_body") or "")`

> The subtitle is asked for as LRC so that it arrives as the thing
> parse_lrc already reads, and the plain words behind it are what that
> falls back on for a song nobody has synced at all. It wins a tie
> against a richsync that had to be deworded: both are then line
> stamps, and these are the ones Musixmatch measured for display.

**line 6393** — before `lang = (rich.get("richssync_language") or rich.get("richsync_language")`

> "richssync_language" is Musixmatch's own typo and is the field that
> exists; the spelling it ought to have is read too, in case they fix it.


### module level

**line 6429** — before `GENIUS_CONFIG = "gui.json"`

> Genius: the words themselves, and no clock at all

**line 6492** — before `from_genius.wants_above = True`

> A second-round provider, and one _gather may decide not to ask at all.
> `above` is not read here: like the blends', the decision is taken in
> _gather, where it saves the request rather than only the parsing.


### `_genius`

**line 6523** — before `return {k: v for k, v in doc.items() if k != "_timing"}`

> `_timing` names whose CLOCK a document runs on, and this one has no
> clock. local_align stamps it because it is about to make one; handed
> to the chain as it stands it would have the line under the lyrics
> claim a timing that is not there.


### module level

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


### `provider_order`

**line 6684** — before `home = min(donors, key=order.index) if donors else BLEND_OF`

> The highest-ranked donor. Not the timing donor, which is what
> blend_rank reads: that decides which blend is asked first, a
> question between blends, where this one is about the sources
> around them. A three-way whose filler the user put above its
> clock still borrows from both, and sits above both.


### module level

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


### `stored`

**line 7143** — before `return {**doc, "_source": str(rec.get("source") or "")} if rec.get("source") else doc`

> Carry the name of whoever answered, so the line under the lyrics is
> right from the first frame rather than guessing Spicy Lyrics and
> correcting itself a moment later.


### `_once`

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


### `_parallel`

**line 7298** — before `alive = getattr(_WALK, "alive", None)`

> The one place the walk fans out, and so the one place its cancel token
> has to be handed on: a thread starts with a bare threading.local and
> would otherwise ask nobody's permission for anything. The same goes for
> where a failure is written down, and for whose failure it is -- inherited
> rather than set from the job's key, because a provider fans out again
> inside itself (NetEase asks about several song ids at once) and those
> requests are still that provider's.


### module level

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


### `_outdone`

**line 7452** — before `front = [got.get(n) for n in names[:at]]`

> The other blends are in this stretch too and are not in `got` -- they
> are being decided in this same round -- so they answer None and abstain,
> which is right: no blend stands another one down.


### `_gather`

**line 7611** — before `early = fan.so_far(ROUND_HOLD) if _walking() else {}`

> Opened only once the first round has said something, so this is the one
> point in a walk where giving up saves the whole rest of it rather than
> only what has not gone out yet.


### `_walk`

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


### `_walk.landed`

**line 7809** — before `if was and (rank, liked, -at) <= (was[1], was[2], -was[0]):`

> The same three rules the final pick below uses, in the same
> priority -- better timing, then somebody asked for by name,
> then the running order -- so what goes up early is never
> something the final answer would then have to take back.


### `_walk`

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


### `duet_flags`

**line 8058** — before `return _tie_backing(lines, list(got)) if got else None`

> Tied again on the way out: a file written before ad-libs were
> held to their own line still has one on the wrong side of the
> screen in it, and nothing else would ever correct it.


### module level

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


### `_near_pairs`

**line 8179** — before `if len(key) != len(b[j]) and _fragment(key, b[j]):`

> ...and not a piece cut out of a longer line, which is the case
> the length guard above used to be doing on its own, badly.


### module level

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


### `quiet_marks.fixed`

**line 8734** — before `out[-1]["Text"] = str(out[-1].get("Text") or "") + str(y.get("Text") or "")`

> Onto the word before: its text, and its spacing, since the mark
> is now what ends the word.

**line 8738** — before `while len(out) > 1 and _mark_only(out[0].get("Text")):`

> A mark that opened the line has nothing before it and was kept; give
> it to the word after instead.


### `quiet_marks`

**line 8767** — before `return doc`

> The document back as it came, not a copy of it that says the same
> thing. Almost nothing has a stray mark in it -- 60 of 60 Spicy
> Lyrics documents sampled here needed no repair at all -- and the
> copy was not free: the window decides whether an answer is NEW by
> asking whether it is the same document it already has, so rebuilding
> one that nothing was wrong with made every redraw look like a fresh
> lyric. See LyricsView.on_lyrics, and unlump above, which has always
> worked this way.


### `_unlump`

**line 8852** — before `joined: list[str] = []`

> A piece with no letters in it is not a word -- QQ's token for
> 'like, "' leaves a lone quote mark behind -- so it rides along with
> the one before it rather than being timed on its own.

**line 8876** — before `if k:`

> Only the first of these starts where the source said anything.
> The rest are shared out, and say so: eval_sources.py counts them,
> and a measurement that cannot tell a stamp from a guess is not
> measuring the thing that matters.


### module level

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


### `lrc_shaped`

**line 8995** — before `alone = str(d.get("_alone") or "")`

> `_alone` settles it on its own, in both directions: a blend that
> stood down is not a blend any more, it is exactly the one document
> it stood down to. A triblend holding LRCLIB's copy has nothing of
> NetEase or QQ in it, and one holding NetEase's own has nothing else.


### `_fold_onto`

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


### `_split_aside`

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


### `fold_cries`

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


### module level

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


### `clean_edit`

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


### `_fill`

**line 9570** — before `return ""`

> Whatever is under a mask is a letter. A donor that has
> punctuation there is spelling something else.


### `_spread`

**line 9634** — before `return [word[n:n + 1] for n in range(len(widths))]`

> Fewer letters than stamps. They go at the front, so the word starts
> where the mask started -- which is the one thing about its timing
> that is actually known.


### `_stand_in`

**line 9740** — before `return ""`

> Two letters at least. A single letter standing where a word was
> taken out is a donor that has split something up rather than the
> word itself -- and "a" or "I" in that slot means the mask was never
> hiding a word of this kind at all.


### `_spine`

**line 9778** — before `tails, back, at = [], [None] * len(once), []`

> The longest subsequence of those that also moves forward in b.


### `_unglue`

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


### `_unmask_with`

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


### `_unmask_group`

**line 10104** — before `for lo, hi, bit in sorted(rows, reverse=True):`

> Right to left, so an offset is still the offset it was measured
> at when a syllable holds two words and both of them were masked.


### `_unmask_write`

**line 10136** — before `fresh = dict(got)`

> The line itself was holding the words, so filling them in
> has already rewritten the only copy there is.


### `uncensor`

**line 10194** — before `out = unlump(got)`

> Unlumped again because a mend can put a space back where a blend
> lost one, and two words under one stamp is exactly what unlump
> is for -- see _unglue.


### `graft_syllables`

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

## 2026-10-24 — `_same_song` containment wants a tag

Lost (Linkin Park, Meteora 20th) streamed with the name "Lost IN THE ECHO". The audio was right (`auGo9bUpBf8`, Linkin Park - Topic "Lost"). The name came from `Resolver._apple`. `_same_song` let any title of four or more letters stand for any title containing it once flattened, so Apple's LOST IN THE ECHO (205s, inside `NEAR` of 200s) was a hit for "Lost". `_cover_cut` then took the earliest release, 2012 over 2023, and `recase` wrote it as "Lost IN THE ECHO". This went against `_same_song`'s own docstring, which says a title that merely contains ours does not answer for it.

`_tagged(longer, shorter)`: containment counts only when both titles are equal once bracketed tags and a " - …" / " / …" / "feat. …" tail are taken off both. Stripping one side alone failed on titles with two bracketed parts (Leave a Light On (Talk Away The Dark) [Piano Vocal]). Where the extra holds no Latin letters or digits (kana and hanzi run together), containment alone still counts, as before. `release_of` (YouTube Music) had the same prefix rule (`startswith`) and now uses `TAG_TAIL` the same way.

Saved Apple names in streams.json are used only while `Resolver._named` still passes them against `src_title`. Over their 1,702 entries, two are re-asked: Lost, and an "Asgore Runs Over Dess With Lyrics (Full Version)" upload, whose "With Lyrics" is bare words and not a tag. That one now keeps its upload title. test_cut, test_blends 191, test_isrc_match 30, test_release_pick 6, test_kuwo 29, test_names 95 and test_lrcred_model are green. test_spotify_id fails 3 on its `mb_spotify` stub, which has no `compilations=` (stub drift since 10-22, unrelated).

That alone moved the name to "Lost (PLZ Tethered Version)", another recording: a bracketed tag, released 2023-02-06, four days before Meteora 20th. The album hint missed because Spotify writes "Meteora 20th Anniversary Edition" without brackets. `_cover_cut` now puts a title equal to the one asked ahead of a tagged copy, after the album and before the date. Live (Apple search): Lost → Lost; LOST IN THE ECHO, Stronger and Hymn for the Weekend unchanged. test_cut 41, test_names 95 and test_lrcred_model 23 are green too.

## 2026-10-24 — Musixmatch: an id on an empty row is re-asked by name

Playing from Mild Lyrics, a stream's Spotify id comes from ListenBrainz and the embed page. It can be a reissue's id, not the one Spotify's own client plays. Musixmatch matches `track_spotify_id` before the name, so that id lands on a row with no words. Last Resort (Papa Roach) with `4YLI2hVQu66q23ScZKFg47` → track 462849614: `has_richsync`, `has_subtitles` and `has_lyrics` all 0. By name, or with `5W8YXBz9MTIDyrpYaCg2Ch` → 421591493, which has richsync. Addicted (Saving Abel) did the same.

`_musixmatch` now asks once more without the id when the id's matched row has none of `MXM_HAS`. This costs a request only on those misses. The explicit flag still comes from the id's row, since that is the recording that is playing. A row with no `track_id` is not re-asked: Musixmatch already fell back to the name for those.

The name matcher can land on an empty copy too. worthless (fenix, 110s), played with no Spotify id, matches 453889690 with or without the id: `track_length` 0, no Spotify id, no words. track.search lists that copy and also 456064881 (commontrack 283216666), which has `has_subtitles` and Spotify id `2iVsdOp5hoij4n55roH6pI`. When the matched row is still empty, `_mxm_search` takes the search row that has words, passes `_same_song`, `_same_artist` and `_near`, and ranks lead artist, then richsync, then subtitles, then length. The macro is then asked by `commontrack_id`. On worthless that is three requests and gives a 27-line line-synced document. Last Resort takes two, and a song that matched first time still takes one. Break (Three Days Grace) is still a miss: its only row (467351496) has no words.

Local songs' tids (sha1 of title and artist, 22 lowercase hex characters) are no longer sent as `track_spotify_id` (`_mxm_sid`). test_blends 194, test_uncensor 103 and test_trouble 63 are green.

Kuwo's plain answers (28 in the cache, against 5 line-timed) got a Syncs entry: `SRC_SYNCS["kuwo"]` is now "wu". Kuwo still has no line entry, as test_syncs requires. A saved Syncs order gets `kuwo@u` last. test_syncs is 16 ok.

## 2026-10-27 — TME AI transcriptions are dropped whole

Kugou served Mice on Venus (C418), an instrumental, a syllable-timed document that opened with "本字幕由TME AI技术生成" ("subtitles generated by TME AI"). After that came "The 嗯", "每一天嗯the 去the" and the like, spread over the whole track. Being the only timed answer, it won. The cache held three more of these, all on instrumentals, all noise ("啦啦啦啦啦", "The yeah", "好你对起啦啦"). `_furniture` now returns nothing when one of the first `EDGE_REACH` lines carries `MACHINE_MADE`, so Kugou, QQ, Kuwo and NetEase all turn such a release down. Kugou then tries its next candidate. The four cached picks were deleted. test_translations 6/6, test_credit_block 19/19, test_kuwo 29/29.
