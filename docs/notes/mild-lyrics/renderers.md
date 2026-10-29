# `mild-lyrics/renderers.py`

Comments lifted out of `mild-lyrics/renderers.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## 2026-10-25 — the rise schedule

Gathered from the RISE_LEAD, EMP_LEAD and FLOAT_MIN notes below and the two `word_lifts` docstrings (lifted further down), which each made part of this case. `Renderer.rise_plan`, `Flow.word_lifts`, `Pinned.line_lifts` and `Amll.word_lifts` point here.

**The stack (Flow, the pinned renderers).** One lift per syllable. `rise_plan` works out the whole line at once: each inked fragment sets off RISE_LEAD (0.06s) before its stamp and climbs over RISE_TIME, and each stamp is held to the one before it, so the rise travels in reading order even where an ad-lib puts a later word's stamp first. `frag_lifts` then holds each height below the fragment in front. The next syllable is already rising before the last has settled, so a word reads as a wave, not as a seam. The distance is measured off the main lyric font, so an ad-lib rises as far as the lead. A passed line fades its lift against the depth blur rather than dropping.

The lead was 0.18s and came down to a frame or two at the rates this draws at. A word standing up before it is sung reads as the line guessing ahead of the voice. A wider window, cut from the local word rate so that rises overlap, was tried. It halved the frames with nothing moving, but put two or three words off the floor at once, and was rejected for the same reason.

**Amll.** AMLL's own schedule, the one the stack rejected, because this renderer is a port of it. A word floats over its own length, ease-out, and stays up, so a held note climbs for as long as it is held. One float per word, not per syllable: over each syllable's own length a word split "sta" + "y" with the hold on the second piece would have its front standing up and its back on the floor for the whole note. A trailing hyphen ends a word (`words_of`), so stutters and spell-outs rise piece by piece. Three numbers differ from AMLL's:

- FLOAT_MIN = RISE_TIME, not AMLL's 1s floor. Against syllable-timed text a 1s floor caught ordinary syllables (median 0.22-0.26s) a quarter of the way up, so the shared `rise` knob read at about a third of the stack's. At RISE_TIME it reads 0.75-0.84 of the stack. Held notes are untouched, since the floor only binds on syllables shorter than it.
- EMP_LEAD = RISE_LEAD, not AMLL's 0.4s. At 0.4s a held word's letters were all moving during the word before it, which is the early lift the stack rejected, at twice the size.
- RISE = 0.055 line-heights, the stack's distance, so the knob means the same movement everywhere. Only the schedule is AMLL's.

## 2026-10-20 — dark seams between a held word's letters (all_glow)

Bug: screenshots of "forever" and "Move" with thin dark vertical lines between letters while the word was held. The ink was fine; the lines were holes in the "Glow every word" light. `glow_lifts` cut the light into one stretch per letter, at the letter's rest columns, each drawn at that letter's own `dx`. When the spread pushes letters apart, the stretches move apart too, and the plain pass is cut out under the word, so each gap had no light at all. Measured on the screenshot: a 3px column at background level (30) between glow of 41-52 on both sides.

Fix: `_glow_bridged` tiles the word on screen. Each letter keeps its own columns, and each gap is filled with the light from the column between those two letters at rest, repeated across the gap (at most 4 passes a gap), its lift eased between the two letters'. A squeeze, if one happens, meets halfway instead. Meeting halfway was tried for gaps too: it put the light off the NEXT letter's edge against the previous letter, a bright band. Clip sides are rounded to whole pixels, so neighbouring passes no longer both light the shared column (Plus).

Measured offscreen (All The Stars, "Haunt" held 4s, real-use settings, GL and raster): gap columns 1-3 before, 26-28 after (continuous with the letter edges). The lifted passes now filter one strip list instead of rebuilding it each pass: wall p50 3.52 -> 3.65ms on GL while the word is held, ~0.3ms more on raster.


## 2026-10-19 — Jelly lines: settling letters hopped a pixel (GL `drawText`)

Bug: a settling word sometimes moved choppily, as if twitching, with Jelly lines on. `emph_plan`'s numbers were smooth: at 240fps no letter's dx, up or scale reversed or kicked. The pixels were not. On the real window (GL FBO, a real-use gui.json, That's What I Like from 30s), single letters jumped exactly 1px up for 1 to 5 frames and came back, near the end of a settle: 6 such hops in 5s.

Cause: `lifted_word` uses plain `drawText` when a letter lands within 0.02px of a row, at `round(y + dy) - dy` under the painter's translate. Qt's GL engine places text 1px high when that translate's fraction is between 0 and 0.5 (raster is right). The line's glide carries such a fraction while its spring settles, and a settling letter's `up` decays through the 0.02 window. So it alternated between the correct picture path and the high glyph. Isolated: `drawText` at a device row of 120 under translate 0.0207, 0.3 or 0.49 inked at 119 on GL and at 120 on raster. 0.51, 0.7 and -0.02 were right on both.

Fix: on that path, a fractional `dy` is taken off the painter (`fromTranslate(dx, 0)`) and the text is drawn at the row itself. Same capture after the fix: 0 hops. Harness: scratch `hook.py` around `memory/bench/bench_column.py` logging every letter `place_word` draws; ink centroid per letter against the plan's y.


## 2026-10-16 — Cards keeps its unlit cards as pictures (`still_card`)

`Cards.paint` drew every visible card a word at a time each frame: about 124 `lifted_word` calls a frame for five or six cards. Median 4.46ms at 1920x1020 raster, against Flow's 1.5. At `act` 0 a card is only its words in the base colour (`swell_of` is 0, so there is no pop, glow or lift, and the fill is drawn at opacity 0). Those cards are now drawn once into a picture, through the same `lifted_word`, by a painter a whole number of device pixels from the screen's, so each word rasterises exactly as it would on screen. The picture is blitted at the card's opacity, and kept while the column rests (keyed by the sub-pixel phase; LRU, 16MB).

A/B on the real window with the clock frozen per frame, 600 frames: drawn live twice is identical (0/255). Kept against live is within 2/255 on antialiased edges (2 only on a few frames, where two words' edges overlap), from applying the opacity once rather than per word. A 600-frame run happened to see only 1/255; the test sees 2 at some scroll positions. Median 4.46 -> 1.77ms, p95 6.71 -> 3.84. `draw_row` also skips the fill pass at `act` 0, which paints nothing. Test: `tests/test_cards_still.py`.

Not done, measured: Spicy Lyrics (2.6ms) spends its time in `_shadow_line`'s `drawPixmap` raster fills, not in `_put`.

## 2026-10-15 — a word with a silence inside it

A word whose timed pieces leave a hole (more than `HOLE_MIN`, 20ms, between one piece's end and the next one's start: "ver|koop", "Cen|traal" in Watskeburt) is split at the hole for the long-word emphasis. Their rule: if every part is held (each passes `emphasised` on its own voiced length) the whole word gets the animation, lit across the hole; if one part is short and another long, only the long one moves; if all are short, none does. `held_parts` does it in `Amll.emph_plan`; with `syll_hold` on, the unit is already the piece and nothing changes. The rise (`word_lifts`) still dates the whole word through `span_of`.

## 2026-10-14 — word pop on spaceless CJK lines

A Japanese line timed a syllable at a time with no spaces (アイドル, STAR☆T☆RAIN: と|び|き|り|の|嘘|…) is one run to `words_of`, so `Amll.emph_plan` asked the gate about the whole line: CJK skips the letter rate, the line had been "held" for seconds, and every character popped at once. `cjk_words` now cuts the run where unspaced CJK meets; a fragment with no letter (！, 、) stays with the one before. `words_of` itself is unchanged, so the rise still moves such a line as before.

A syllable at a time (AMLL's unit) was "very, very bland": a kana is rarely held 0.7s alone. So Japanese (a run with kana) is cut where pykakasi starts a word (とびきりの|嘘|も|愛情|だよずっと), and the gate counts CJK by how it reads (`_letters_of`: kana 2, small kana/ー 1, kanji 3), through the same letter-rate curve as English, where CJK used to skip it. ずっと needs 0.75s at Pop only past 0.7, アイドル 0.99s. Lines with something lit, at 0.7s, over 8 syllable-timed Japanese songs in lyrics/fetched: whole line 98%, per syllable 27%, per word 46%; 40 English songs: 40%. Chinese stays per syllable (no kana; jieba would cost ~1s to load in the paint path). Without pykakasi Japanese falls back to per syllable.

The same report showed the line spreading out of the window: a row's last word had no right limit (`hi = inf`), and a row's first word cannot move left, so a one-word row took the whole spread to the right. The last word now stops at the column's edge (`_lyr_width`), eased like the other limits. Measured on a held "forever" ending a full row: 14.8px past the edge before, 0.5px after.

## 2026-10-13 — words re-rendering as they are sung (GPU, scaled screen)

Their Windows laptop (scaled, GPU drawing on): a "rerender" of the words was visible while the line played. Every line but the sung one is a cached raster picture. The sung line was drawn live, and `lifted_word` drew a word straight to the painter when it sat on a pixel row and through a raster `_word_picture` while it rose, popped or filled. At dpr 1 the two are identical. On Qt's GL engine at a scale they are not. Measured offscreen, Noto Sans Bold, "stopping us right": 2–4k pixels differ, mean 18–88/255, worst up to 235. Below 64 device px the GL glyph cache sets glyphs elsewhere: a whole device row at 1.25× when the baseline falls on a half pixel, up to 0.35px sideways. Above it Qt fills outlines under 4x MSAA. On raster the two paths match to 0 at 1.25× and 1.5×. So each line changed rasteriser when it became current and again when it ended, and each word did as it started and stopped moving.

`_gl_skews` (gradient pens only) became `_gl_scaled`: on GL at dpr ≠ 1 all text goes through `_word_picture`, whatever the pen. The same goes for `lifted_word`, `grad_text`, Spicy's resting rows (`_text_rows`) and the drift/cloud base text that a fill is drawn over. The word cache cap scales with dpr². Bench at 1280x680 ×1.5 on 新時代 46–48s: wall p50 4.37 → 4.54ms. At 1× the output is identical (old vs new differs only where old vs old does, in warm-up frames). Not seen on Windows: Windows uses a different font engine, so its GL glyphs could also differ from raster at 1×. That case is untouched.

## 2026-10-13 — lyric column cost

Their 240Hz panel at 1920x1020, GPU, on Ado (kanji, furigana, romaji under): 120–160fps. Their frame traces showed wall = CPU in every section, so the cost is Python in the lyric column, not GL. Measured offscreen with the real LyricsView and real-use settings, painted through the GL engine into a 4x MSAA FBO, on a fake 240Hz clock (新時代, 45.5–51.5s, 1440 frames). Old and new code rendered the same frames and were diffed.

- **blit** sets and puts back the smooth hint and transform by hand instead of save/restore (~200 calls a frame), and tests the transform type against a frozenset rather than through enum `.value`.
- **adv(fm, txt)** keeps `horizontalAdvance` on the metrics object. CJK widths cost 2–6µs a call, ~130 calls a frame on metrics that live in layout_cache.
- **font_key** keeps `QFont.key()` by font: 1.7µs to build against 0.3µs to hash. Equal fonts have equal keys.
- `lifted_word` skips `_gl_skews` at dpr 1, where it is always false.

Pixel-identical on GL and on raster (every compared frame after warm-up). CPU per frame went from 7.13 to 5.24ms on GL and from 7.75 to 6.22ms on raster.

**_glow_flush (GL only).** all_glow's ~130 clipped strips a frame now go as one `drawPixmapFragments` per pass. Each fragment is cut to the device rect the scissor would have used: every edge rounded, not `QRectF.toRect()`, which was a row short. Opacity then travels per vertex instead of per draw, so the result is within 1/255 of the clipped blits (diffed: worst 1, tens of pixels a frame). Raster, rotation and dpr ≠ 1 keep the clipped blits. Brought GL to 4.61ms. `GLOW_FRAGMENTS = False` turns it off.

A cold layout_plan on the first paint after lyrics arrive (32ms on that song) is now mostly done ahead: see layout_ahead.md.

## 2026-10-12 — margins, late pop, glow colour

**_pad_of.** A line picture's margin is `10 + blur * 6`. When the per-frame budget runs out, `_nearest_blur` hands back the same line at another level, which was placed by the asked-for margin. At a line switch the upcoming lines want less blur and get the more-blurred stand-in, so they sat 6px per level right and down for a frame. Seen on a laptop, where the budget runs out. The margin is now read off the picture.

**LATE_POP.** In `emph_of` a late syllable's letters were squeezed to end with the word, so the y of happ|y grew for 0.45s against h's 0.70s. Every letter now gets at least the first letter's run (LATE_POP × lens[0]), running at most one more emp_tail past the word. Measured: y 0.45s → 0.62s.

**_gl_skews / grad_text (GPU flicker on a scaled screen).** Qt's GL paint engine places a gradient pen at its coordinates divided by the device pixel ratio. Measured: a fill edge at x=150 lands at 150 on raster at every scale, and on GL at 150 (1×), 120 (1.25×) and 100 (1.5×); the painter's translation itself is applied correctly. On their Windows laptop (scaled, iGPU, GPU drawing on) a word was drawn straight to GL only on frames where it sat on a whole pixel row. Other frames went through `_word_picture` (raster, correct). So a word mid-fill showed as fully sung for single frames: frames 234 and 238 of their recording, "us" in "no stopping us right". The next word lit during a pause the same way. Gradient-pen text on GL at a scale ≠ 1 now always goes through a CPU picture. Checked with the real `lifted_word`/`grad_text`: GL and raster edges agree at 1, 1.25 and 1.5. Brush gradients on the main painter (vignette, backgrounds) are probably placed off the same way; not checked.

**_glow_in.** Applies the Glow colour setting to the two glows cut in flat white (held-word halo, long-word glow).

## Lift — 2026-10-25

Docstrings shortened in `mild-lyrics/renderers.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> How the lyric column is drawn.
>
> The window paints every pixel itself, and until now it painted the lyrics
> exactly one way: a scrolling stack of same-size lines, depth carried by opacity
> and distance blur rather than by size, the line being sung filling
> syllable-by-syllable. That is `Flow`, and it is still the default -- everything
> here started as `LyricsView._paint_lines` and its helpers, moved out unchanged
> so that the other ways of showing the same lines are its siblings rather than
> special cases inside it.
>
> A renderer owns the lyric column and nothing else. The background, the cover
> panel, the header, the overlays and every menu are the window's, and it draws
> them around whatever happens here.
>
> Two things every renderer must leave on the view, because the rest of the
> window reads them and there is no default that works:
>
>   view.line_rects   (i, top, h, lo, hi) per line drawn, `top` in content space
>                     -- screen y plus view.scroll. tick() aims the scroll at it
>                     and line_at() turns a click into a seek. A renderer that
>                     pins its lines keeps view.scroll at 0, and then content
>                     space and screen space are the same thing -- line_at()
>                     subtracts the anchor from both sides, so it needs no help.
>   view.content_h    how tall the column came out, for the scroll clamp. Pinned
>                     renderers set 0.0.
>
> One thing a renderer may say about itself: `stacked`, whether its lines are
> laid out by view.layout_line at the window's own lyric size. The stack is; the
> pinned renderers are not, and set their own type. It is not about drawing --
> it is about whether anything OUTSIDE the column can work out where a word
> ended up, which the review marks need. See LyricsView._paint_review_marks.
>
> A stacked renderer may still draw a line under a transform, and says so with
> `line_scale(i)`: what the painter was scaled by about that line's own centre
> when it was drawn, 1.0 for anything untransformed. The layout is still the
> window's, so the outside still knows the boxes -- it just has to put them
> through the same scale to land on the ink. See Amll.SCALE.
>
> A renderer is constructed with the view and keeps it as `self.v` for the life
> of the window; switching renderers builds a new one.

### `blit`

**line 29** — from the docstring, `def blit(p: QPainter, target, pm, src=None) -> None:`

> drawPixmap, put where it is asked to be and not on the nearest pixel.
>
> Under a transform that only shifts -- and a scale of exactly 1 is one --
> Qt's raster engine puts a picture on a whole device pixel whatever the
> smooth-transform hint says. So a word lifting by a fraction of a pixel a
> frame stood still and then jumped a pixel, each word on a frame of its
> own: the line shook while it rose, popped or glowed. Measured by ink
> centroid over tenths of a pixel: plain, 0.0 x5 then 1.0; nudged, 0.1 a
> step. Every picture a renderer draws goes through here so that no new
> call can bring that back.

### `row_rtl`

**line 106** — from the docstring, `def row_rtl(row) -> bool:`

> Whether a wrapped row reads right to left.
>
> wrap_shape has already laid such a row out from the right (see rtl_row):
> its x run the other way, and each word's space leads its last fragment
> instead of trailing it. Everything that fills by the clock asks this so
> the light comes in from the right edge of each word, not the left.

### `Renderer.line_scale`

**line 202** — from the docstring, `def line_scale(self, i: int) -> float:`

> What line `i` was last drawn scaled by, about its own centre.
>
> 1.0 unless a renderer says otherwise, which is every renderer that
> draws its lines at the size the plan gives them. A renderer that
> scales a line has to answer here, because the window puts the review
> marks where the LAYOUT says the words are and nothing else can tell
> it the ink moved. See LyricsView._paint_review_marks.

### `Renderer.scale_about`

**line 209** — from the docstring, `def scale_about(p, s: float, x0: float, width: float,`

> Put the painter under line `i`'s scale. The caller has saved.
>
> Written once and called from both sides -- the renderer drawing the
> line and the window marking it -- because the two have to agree about
> the CENTRE to the pixel or the rules sit off the words by a fraction
> that grows with the distance from it. Two copies of three lines of
> arithmetic is exactly the kind of agreement that stops being one.

### `Renderer.words_of`

**line 218** — from the docstring, `def words_of(row):`

> A wrapped row's fragments, grouped back into the words they spell.
>
> wrap_pieces lays out syllables and drops the flag that said which of
> them belonged together, but it leaves behind the mark that matters:
> the last syllable of a word is the one carrying the trailing space. So
> a word is the run up to and including the next fragment that ends in
> one. A word long enough to have been split across rows comes back as
> one run per row, which is what should happen to it anyway.
>
> A TRAILING HYPHEN ends a run too, and that is the whole difference
> between two shapes that reach here looking identical. Both are
> fragments joined with no space between them, but they are not the same
> thing at all:
>
>   * "wor" + "ry,", "a" + "po" + "lo" + "gize" -- one written word,
>     cut up because the timing needed it. The pieces are not utterances
>     and nothing in the text says where they meet. These must stay one
>     word: what reads them is the rise, and a word whose halves go up
>     at their own speeds tears in two and holds the pose (see
>     Amll.word_lifts).
>   * "fuck-" x5, "F-" "R-" "I-" "E-" "N-" "D-" "S", "d-" + "do",
>     "Off-" + "off-" + ... -- a stutter, a spell-out, a hyphenated
>     compound. Each piece is a whole utterance with a boundary the
>     writer PRINTED, and the voice arrives at each one separately.
>     Grouped into one word they went up as a single slab, so a line
>     that is sung as eight little hits rose once, all together.
>
> The hyphen is the discriminator because it is ink. A syllable split
> inside a word is written with nothing between the pieces; a hyphen is
> a character somebody typed, and a reader sees a boundary where it is.
> Measured across this collection the two never overlap: of 279
> hyphen-joined runs not one is a mid-word split, and of 1356 plain ones
> not one carries a hyphen.
>
> U+002D is the only one the documents actually use; the other two are
> here because they are the same character by another name. The dashes
> are deliberately NOT: an en or em dash between words is punctuation
> and comes with its own spaces.
>
> Returns [[(index in row, fragment), ...], ...].

### `Renderer.voiced_of`

**line 242** — from the docstring, `def voiced_of(run):`

> How long the word was SUNG, which is not how long it lasted.
>
> span_of dates a word from its first start to its last end, which is
> what it is for -- that is where the word sits. But the fragments of a
> split word do not always abut, and where they do not the silence
> between them is inside that span and the word was not being sung
> through it. Anything asking "how long is this note" wants this
> instead: the fragments' own lengths added up, with the holes left out.
>
> Identical to `e - s` for every word whose pieces meet, which is 1335
> of the 1356 split words in this collection. On the 21 that have a hole
> it is the difference between what the singer did and what the document
> spans: "ver|koop" is voiced 0.84s and dated 1.52s, "Andr|e" 0.63s
> against 1.20s, and both are words the EMP_MIN gate is meant to turn
> down and was letting through on the strength of the silence.
>
> Not used for where a word ENDS: a word with a hole is split for the
> emphasis instead, see held_parts.

### `Renderer.rise_plan`

**line 249** — from the docstring, `def rise_plan(self, rows) -> list:`

> When every fragment in the line sets off, in reading order.
>
> The schedule, worked out for the line at once rather than read off
> each fragment as it is drawn. Each entry is (row, index in row, when
> the rise starts), and only for the fragments that have ink and a stamp
> -- a space between two words is not a thing that rises.
>
> What is settled here and cannot be settled a fragment at a time is the
> ORDER. The stamps are not always in it: a line with an ad-lib written
> into it can have its last word starting before its second-to-last,
> because the two really are sung across each other. The eye reads the
> line forwards, so the rise has to travel forwards, and a word yanked
> up out of turn is a picket fence rather than a wave. Each stamp is
> therefore held to the one before it on the way past.

### `Renderer.lifted_word`

**line 264** — from the docstring, `def lifted_word(self, p, at, txt: str, lift: float, fm: QFontMetricsF,`

> drawText, for a word standing between two rows of pixels.
>
> Qt puts a glyph run on a whole device pixel and nothing moves it off:
> not a scale, not a change of hinting, not asking for outlines. So a
> rise five pixels tall is five jumps however smooth the number driving
> it is -- which is what the raising looked like once the glow was made
> to step along WITH the word instead of sliding against it. The stepping
> was always there; making everything agree is what left it on its own
> to be seen.
>
> A picture is not treated that way. So the word is drawn into a small
> one at a whole pixel -- under the painter's own font, pen and opacity,
> so a fill gradient falls exactly where it would have -- and then that
> picture is put at the height the word actually is.
>
> At a whole pixel and unscaled, a blit is the same picture drawText
> would have made, to the last alpha value: measured across a word at
> three sizes, mean difference 0.00 and worst 0. So a word that has
> finished rising drops back to being glyphs with nothing to see at the
> join, and only the one or two words actually in motion ever pay for
> this -- about a twentieth of a millisecond each, against a frame that
> has sixteen.
>
> `grow` and the centre are the pop, taken here for the same reason: it
> is the same word moving in the same direction, and text under a scale
> snaps exactly as hard.

### `Renderer._word_picture`

**line 351** — from the docstring, `def _word_picture(self, p, at, txt: str, ox: float, oy: float,`

> lifted_word's picture of `txt`, kept between frames.
>
> On the GPU canvas (see gpu_canvas) a new picture every frame is a
> raster draw AND an upload into a texture, for one that is usually the
> same as the last: a word's
> picture only changes when the pen does or the glyphs move inside it,
> and a rise only moves where it is put. So it is kept, keyed by exactly
> those -- text, font, pen, and `at` less the picture's corner, the
> float the glyphs are rasterised at -- and the texture with it, which
> Qt keys by the picture. Checked against drawing afresh: 15,585 kept
> pictures, every one identical. A gradient pen, a fill edge moving
> through the word, is never kept.
>
> On the CPU it matters too, since a gliding line (see _paint_line_at)
> puts every word of the sung line through here for as long as it
> moves. Up to 8MB.

### `Renderer.shaped_units`

**line 386** — from the docstring, `def shaped_units(cls, txt: str, font: QFont, fm: QFontMetricsF) -> tuple:`

> `txt` cut where the FONT lets it be cut: ((piece, x), ...).
>
> A word drawn a letter at a time is reshaped a letter at a time, and a
> ligature does not survive that: this face draws "fl" as one glyph, and
> "fly-y-y" came apart into an f and an l of the wrong shapes in the wrong
> places. So the pieces are the glyph clusters of the word as laid out
> whole -- a ligature is one piece and moves as one -- cut only where a
> cluster also starts a grapheme, and `x` is where the layout put it.

### `Renderer.shaped_offsets`

**line 443** — from the docstring, `def shaped_offsets(cls, txt: str, font: QFont, fm: QFontMetricsF) -> tuple:`

> Where a drawText of `txt` actually puts each character.
>
> Not the same as adding up the characters' own advances, and not the
> same as the width of the text before each one either. Both of those
> miss KERNING, which the font applies to a PAIR: the width of "ev" does
> not include the tuck between the "v" and whatever follows it, so a
> character placed at that width sits a pixel to the right of where the
> font would have put it.
>
> A pixel matters here because this is only used when a word is drawn
> character by character -- which is only while it is being emphasised.
> A letter that is a pixel out for the length of a held note, and right
> again the moment the note ends, is exactly as visible as it sounds.
> Measured over five documents before this: 19 of 104 emphasised words
> moved a letter when the glow started, by up to 3.7px.
>
> So the real positions are asked for, by laying the text out the way
> the painter will. Cached per text and face; a line has a handful of
> distinct words and a song a few hundred.
>
> Falls back to the prefix widths where the layout does not hand back
> one glyph per character -- a ligature, a combining mark -- which is
> the old behaviour and no worse than it was.

### `Renderer.place_word`

**line 470** — from the docstring, `def place_word(self, p, at, txt: str, lift: float, fm: QFontMetricsF,`

> A fragment, drawn as one word or as its separate characters.
>
> Every path that puts lyric text on the screen goes through here, so
> that a renderer which moves the characters of a word independently --
> see Amll.emph_of -- moves them in the un-sung layer and the sung layer
> alike. They are the same letters: if only the lit half is displaced,
> the word tears in two along the fill boundary.

### `Renderer.swell_of`

**line 504** — from the docstring, `def swell_of(self, s, e, pos: float, act: float) -> float:`

> How far into its swell a syllable is, 0..1, or 0 if it has none.
>
> Per syllable and on the syllable's own clock: up and back down over
> exactly the time the file gives it. Only a syllable held at least
> `pop_min` swells -- the long ones, not the rapid ones -- eased in over
> the 0.2s past the bar so a syllable just over it barely moves. Both
> the pop and the long-word glow ride this one number, so they agree
> about which syllables are long.

### `Renderer.emph_glow`

**line 573** — from the docstring, `def emph_glow(self, p, emph, at, font: QFont, fm: QFontMetricsF,`

> The light behind each character of a held word.
>
> Per character rather than one halo for the whole word, because
> glow_of sizes its blur from the drawn WIDTH: ask it for a six letter
> word and it gives about eleven pixels of spread, against four for a
> single letter. One halo for the word is therefore not the same light
> only wider -- it is a much bigger one, and it reads as a haze around
> the word rather than as the letters being lit.
>
> The halos of two neighbours do meet in the gap between them, where
> they add. That was survivable once the word stopped GROWING: measured
> over every held word in a chorus, the dimmest point between two
> letters still sits 54% below the letters at full strength. It was not
> survivable before, which is what sent this looking for a culprit in
> the light when the culprit was the size. See Amll.SWELL.
>
> `edge` is where the fill has got to, None for all of it. The light is
> masked by it the way AMLL's mask takes the text-shadow with the text:
> a letter glows only as far as it has been sung, fading across the
> fill's own `soft`. Lit whole, a halfway "o" glowed on its unsung half
> too and the edge of the fill stood out hard against it.

### `Renderer.on_grid`

**line 706** — from the docstring, `def on_grid(self, dy: float) -> float:`

> A vertical distance rounded onto the screen's own pixel grid.
>
> Used for where a rise ENDS, not for where it is along the way. A word
> that has finished rising sits at a whole pixel and can be drawn as
> plain glyphs, which is both sharper and very much cheaper than the
> picture lifted_word has to make for one still moving -- and since only
> the moving ones need that treatment, there are one or two of them in a
> frame rather than a line's worth.
>
> Rounding every step of the way instead is what made the raising
> choppy: it is the same five jumps Qt would have imposed anyway, with
> the glow stepping along in time with them so that nothing was left to
> disguise it.

### `Renderer.frag_lifts`

**line 712** — from the docstring, `def frag_lifts(self, rows, full: float, pos: float) -> list:`

> How far each fragment has lifted in pixels, one dict per row.
>
> The plan says when each one sets off; this says how far along it the
> clock has got. Held down to whatever the fragment in front of it
> reached, which is the other half of keeping the line in reading order:
> the plan puts the stamps in order, and this keeps the heights in it.
>
> The DESTINATION is put on the pixel grid, and the travel to it is
> left alone. So a word at rest sits exactly on a row of pixels and is
> drawn as glyphs, and a word in motion is somewhere between two of
> them and is drawn as a picture -- see lifted_word. Every layer reads
> this one number, so the base text, the fill over it, the glow behind
> it and any reading above it cannot disagree about where the word is.

### `Renderer._paint_dots`

**line 727** — from the docstring, `def _paint_dots(self, p, ln, fm, ox, y, pos, act, alpha, width,`

> Instrumental break, the way Apple Music shows it: three dots that
> fill across the gap so a 40-second solo is not just dead air.
>
> `align` is for the renderers that set their own: the stack follows the
> window's alignment setting, but one that centres every line it draws
> would otherwise leave the dots hanging off to the left of it.
>
> `flights` is one (lift, opacity left, how much bigger) per dot, or
> None per dot for one still sitting in its place -- the float troll,
> handed in rather than asked for here, because it belongs to the stack
> and this is drawn by every renderer there is. See Flow.dot_flights.

### `Renderer.wheel`

**line 768** — from the docstring, `def wheel(self, dy: float) -> bool:`

> One notch of the wheel, offered here before the window takes it.
>
> The window's own answer is to move view.scroll, which is the right
> answer for a renderer whose lines are laid out against it and no
> answer at all for one that pins them -- so a pinned renderer that
> wants to be scrollable has had no way to say so, and the wheel simply
> did nothing to it.
>
> True means taken, and the window leaves its own scroll alone. The
> default is to decline, which is what every renderer but the amll
> column does: their lines are where they are for reasons the wheel has
> nothing to say about.

### `Renderer.credits_index`

**line 774** — from the docstring, `def credits_index(self):`

> Which line is the credit block, or None.
>
> The last one where there is one, or the first with credits_top on --
> see LyricsView.build_lines, which puts it there -- but found rather than assumed, because a renderer
> that drew the wrong row here would be printing a lyric where the
> attribution belongs.

### `Renderer.credits_block`

**line 783** — from the docstring, `def credits_block(self, p, x0: float, width: float, top: float,`

> The credit block, drawn with its top at `top`. Returns its height.
>
> For the renderers that do not lay the whole document out and so never
> reach the row it rides on. They put it under whatever they drew last,
> once the song has finished -- see credits_due, and the renderers that
> call this, which each decide where "last" is for them.
>
> Held inside the window where `H` says how tall that is: these
> renderers place their lines by the height of the window rather than by
> a scroll, so a long credit under a line that wrapped three ways would
> otherwise run off the bottom and be absent again.
>
> Centred by default rather than following the window's own alignment,
> because the renderers that come here centre their lines whatever that
> setting says, and a credit hanging off the left under a line in the
> middle reads as something else on the screen rather than as the foot
> of what is above it.

### `Renderer._paint_credits`

**line 800** — from the docstring, `def _paint_credits(self, p, rows, fm, x0: float, y: float, width: float,`

> The footer under the last line. Dim and unanimated -- it is not part
> of the song and should never look like the next thing to be sung.
>
> `rows` are (which credit, one wrapped line of it). The songwriters are
> the song's own credit and are drawn brighter than the rest, however
> many lines of them there are.
>
> `links` is that same block's clickable stretches, one list per credit:
> a Spicy Lyrics contributor's own page, Unison's address. They are drawn
> over the row that already holds them rather than instead of it -- same
> font, same place, brighter and underlined -- so the line reads the same
> whether or not anything in it is a link, and a name that wrapped onto
> the next row simply does not match there and is left alone.
>
> Where they land is written down for the window to hit-test; see
> LyricsView.credit_at. The rect is the ink plus a little, because a
> credit is small type and a link nobody can hit is not a link.
>
> A block moving between two rows of pixels is drawn as one picture,
> put where it is -- see _credits_picture.

### `Renderer._credits_picture`

**line 908** — from the docstring, `def _credits_picture(self, p, rows, fm, font, x0: float, y: float,`

> The credit block as one picture, put at the height it really is.
>
> Text is put on a whole row of pixels whatever it is asked -- see
> lifted_word -- so a block scrolling into place stepped a pixel at a
> time, its words against the faces beside them (pictures, which
> glide) and against every lyric line above it, which since the glide
> (Flow._paint_line_at) moves by fractions. That is the shiver the
> lines had, left on the credits: drawn here at a whole pixel, the
> picture carries the fraction. At rest a block sits on a row and is
> text again, which is the same pixels -- see lifted_word.
>
> One picture, kept while nothing in it changes; a fade remakes it
> each frame, which is a few rows of small text.

### `Flow.emph_plan`

**line 973** — from the docstring, `def emph_plan(self, rows, pos: float, fm: QFontMetricsF,`

> Which words of this line are being held, and how they are moving.
>
> Empty for the stack, whose swell is the pop and the glow and belongs
> to the word as a whole. See Amll.emph_plan for the other answer, and
> for why it is worked out once for the line rather than per fragment:
> both the un-sung layer and the fill over it have to read the same one.

### `Flow.layout_plan`

**line 1043** — from the docstring, `def layout_plan(self, width: float):`

> Every line's place down the column, worked out once for the document.
>
> Nothing in here answers to the clock or to the scroll. How tall a line
> is, the air under it, and the ink it covers left to right are decided
> by the words and the size they are set at -- so the whole column is
> one list, and a frame reads it instead of building it.
>
> It used to be built on every frame, and the whole document's worth:
> the loop needs each line's height to know where the next one goes, so
> there was no way to ask about the nine lines the window can show
> without laying out all hundred and thirty first. That is the cost the
> layout cache never covered, because a cache hit per line per frame is
> still a hundred and thirty lookups per frame.
>
> Kept in the WINDOW's cache rather than one of this renderer's own, so
> that everything which already empties that -- a new lyric, a new font,
> a new size, a resize -- empties this too. `line_spacing` is in the key
> as well because it moves the lines without changing one of them.
>
> The two offsets are RELATIVE for the same reason. `off` is measured
> from the top of the column and `lo`/`hi` from x0, and neither the
> anchor nor the art panel changes a thing about how the words are laid
> out -- so the panel can slide and the window can be dragged taller
> without throwing the column away and wrapping it all again.

### `Flow.rects`

**line 1077** — from the docstring, `def rects(self, plan, top: float, x0: float):`

> line_rects for the column, which moves only when the window does.
>
> The list is in CONTENT space -- the scroll is added back the moment it
> is taken off -- so the one thing that changes every frame is the one
> thing it does not depend on. It is rebuilt when the anchor or x0 move,
> and otherwise handed back as it stands. Held by identity rather than
> by a key so that a plan thrown away takes its rectangles with it.

### `Flow._warm_next`

**line 1117** — from the docstring, `def _warm_next(self, plan, live, width: float, H: int = 0) -> None:`

> On a frame with ration to spare, build what the NEXT switch wants.
>
> A line's blur is how far it is from the line being sung, so a switch
> moves every line in the column to a new level and each level is its
> own picture -- six to eleven of them on the frame it lands, against a
> ration of two. PIX_PER_FRAME exists to spread that over the frames
> after, which works and is invisible, but it is paying for the burst
> once it has already happened.
>
> The burst is predictable a whole line ahead. `blur` is base(dist)
> scaled by (1 - act), and act is zero on every line but the one going
> out and the one coming in -- so for all the rest, next line's picture
> is this line's arithmetic with dist measured from one further down.
> The two that are easing are left to the ration exactly as now: they
> sweep through levels gradually and there is nothing to precompute.
>
> This costs nothing where there is nothing to do. The ration goes
> unspent on the great majority of frames -- 2374 of 2400 over a warm
> sweep of "NF - Time" -- and a pass that builds nothing sets _warm_done
> and is not run again until the line changes.
>
> REACH IS A NUMBER OF LINES; THE WINDOW IS A NUMBER OF PIXELS. Five
> either way is the right guess for ordinary type in an ordinary window
> and badly wrong at the edges: at 46px in a 500px window the stack holds
> about three lines, and warming five each way built 55 pictures nobody
> could see out of 63 -- 87% of the work, and 87% of the cache it
> evicted. So each candidate is placed where it will BE after the switch
> (the line coming in sits at the anchor, so everything else moves by the
> difference between their offsets) and the ones that land outside the
> window are left alone. The reach stays five: it is now a ceiling
> rather than the whole rule, and on a tall window with small type
> nothing changes at all.

### `Flow.float_of`

**line 1188** — from the docstring, `def float_of(self, at, pos: float):`

> Where a word that set off at `at` has got to, and what is left of it.
>
> Returns (lift in pixels, the opacity it has left, how much bigger it is
> being drawn), or None for a note the clock has not reached -- which is
> everything still to be sung, so the ordinary path pays one comparison
> for this.
>
> Driven by the CLOCK and not by the wall, which is what makes it agree
> with itself: a syllable dragged back under the playhead comes back with
> everything else, a pause holds a half-gone word exactly where it had
> got to, and the same second of the song looks the same twice. The
> cloud drift is entitled to the wall because it is weather -- it says
> nothing about where the song is -- and this says exactly that.

### `Flow.dot_flights`

**line 1199** — from the docstring, `def dot_flights(self, ln, pos: float):`

> Where each of the three dots of an interlude has got to, or None.
>
> The dots are a countdown rather than a lyric, so they do not leave one
> at a time across the whole of a break the way syllables leave across a
> line: a dot let go at the third of a forty-second solo would be gone
> for half a minute of nothing, and what is left behind is a countdown
> with no numerals in it. They leave at the END, one after another, the
> last of them landing exactly as the words come back -- so the break
> finishes on an empty window and the line arrives into it.
>
> Handed to _paint_dots, which is on the base class and is drawn by the
> pinned renderers too. Like every other troll this one belongs to the
> stack, and a renderer that never asks for this never gets it.

### `Flow.float_lifts`

**line 1213** — from the docstring, `def float_lifts(self, rows, rrows, ln, pos: float) -> dict:`

> Every fragment already on its way out, keyed (romaji?, row, index).
>
> One flight per SYLLABLE, and each one sets off the moment that syllable
> is SUNG rather than when its note is over, so the word leaves while the
> voice is still on it -- the fill sweeps across it on the way up and the
> halo goes with it. That is the whole of the effect: the line comes
> apart in the order it is being sung, the front of it already up the
> window while the last word is still being held.
>
> A line-timed document has one fragment to a line and so the line goes
> up as a slab, which is the only thing it can be given -- there is
> nothing in it that says when one word started and the next one did.
>
> Keyed the way `lifted` is, because it lands in the same places: the
> base text, the fill drawn over it, the halo, and the reading sitting
> above a kanji, all of which have to agree to the pixel about where the
> word IS.

### `Flow.glow_of`

**line 1229** — from the docstring, `def glow_of(core: str, fm: QFontMetricsF, held: float):`

> How wide and how bright the halo on one word is.
>
> Returns (blur radius in pixels, strength 0..1), and both of them
> answer to the word's LENGTH -- which is measured the way the eye
> measures it, as the width the word was drawn at, in line-heights.
> Counting characters is a poor stand-in for that in a proportional font
> ("ill" and "WOW" are both three of them) and a worse one for a script
> that spells a whole word in a single glyph.
>
> Length goes mostly into how far the light CARRIES. Lit from behind, a
> long word throws a broad soft halo and a short one a tight bright
> spark; blurring both by the same few pixels made the short one a blob
> with a letter somewhere in it and left the long one wearing a thin
> outline. The radius ran 2..10 pixels across the whole range of words
> before, which is barely a range at all, and it ran in PIXELS -- so the
> halo shrank back into the letters every time the type was made bigger.
> It is a fraction of the line height now, and the type takes it along.
>
> It goes only a little into how BRIGHT the word is. A long word is
> already putting out more light by having more ink in it, and paying it
> for its length a second time blows the line out.
>
> `held` is how long the note is, which is the other half of both: a
> word gone by in a sixteenth has no time to light up.

### `Flow.word_lifts`

**line 1291** — from the docstring, `def word_lifts(self, rows, fm: QFontMetricsF, pos: float, act: float,`

> How far each fragment has been lifted, keyed by (row, index in row).
>
> One lift per SYLLABLE, on a schedule cut for the whole line at once --
> see rise_plan. This used to be one lift per word shared by every
> syllable in it, on the grounds that a word rising a syllable at a time
> tears in half. It does not stay torn: the next syllable is already on
> its way up before the last has settled, so what the eye gets is not a
> seam but a wave travelling through the word at the speed it is sung.
>
> The distance is measured off the MAIN lyric font, not off the line's
> own. An ad-lib is set at two thirds the size, and scaling its rise with
> its type made it go up by two thirds of the amount -- which is not what
> an amount is. Every word in the window now travels the same distance.
>
> Faded out against the depth blur rather than stopped dead, so a line
> that has just been passed settles back onto its baseline instead of
> dropping the moment the clock leaves it.

### `Flow.sung_edge`

**line 1302** — from the docstring, `def sung_edge(self, row, pos: float) -> float | None:`

> How far along a row the voice has got, in line-local pixels.
>
> None where it has not reached the row at all. The answer is the right
> edge of the longest run of fragments from the START of the row that
> the clock is level with or past -- so it stops at the first word the
> voice has not reached, and the word it stops inside contributes its
> own fraction of itself.
>
> Walking a run rather than taking the furthest lit fragment is what
> keeps this honest where a source stamps a line out of order, which
> they do. Furthest-lit would run the light out to a word the voice is
> nowhere near because its stamps happen to sit early; a run stops
> where the singing stops. See the fill, which asks each word its own
> clock and has the same rule for the same reason.

### `Flow.glow_lifts`

**line 1320** — from the docstring, `def glow_lifts(self, rows, ox: float, lifted: dict, emphs: dict,`

> (row, x0, x1, dy, dx) for all_glow: how far each stretch of the
> line stands off where the picture has it -- a word's float, and each
> letter of a held word at its own height and spread (an average for
> the word left a blurred copy showing under the letters above it:
> "grets" behind "regrets") -- with neighbours that stand alike (to a
> quarter of a pixel) run together, so it is a few passes, not one a
> letter. The gaps a held word's spread opens are bridged (see
> _glow_bridged): left dark, they were seams between its letters.

### `Flow.all_glow`

**line 1394** — from the docstring, `def all_glow(self, p, idx: int, ln: dict, rows, fm: QFontMetricsF,`

> A halo behind every word the voice has already been through.
>
> The halo the fill draws below is one word's: it comes up under the
> syllable being sung and goes out behind it, so at any moment exactly
> one word in the window is lit. This is the other thing a glow can be
> -- the light stays. Every word the voice has passed goes on glowing,
> the word being sung glows as far into itself as the fill has got, and
> a word the voice has not reached has no light at all. What travels
> along the line is the EDGE of it. Off unless `word_glow` is turned up,
> and the two stack: the word being sung still gets its own on top.
>
> Three things make it light rather than fog, and the first two were
> what was wrong with it before:
>
> It is drawn in the line's own colour taken to full brightness --
> see glow_colour -- and not in the base ink. A blurred copy of the same
> grey the text is already drawn in, added back over itself, is not a
> glow; it is the line out of focus, which is the one effect this window
> already has and calls the depth blur. Light is brighter than the thing
> it comes off.
>
> It stops where the voice has. A line lit end to end has nothing moving
> in it, and a soft wash under un-sung words is a smear behind text that
> is not doing anything yet. Lit to the voice and no further, the glow
> is the fill's own shadow and moves with it.
>
> And it is ADDED -- `CompositionMode_Plus` -- because that is what
> light does. Laid over normally it would be a grey film on the
> background between the words; added, the gaps take nothing.
>
> Nothing is drawn twice to get it. The obvious way to light every word
> is to take each one, blur a copy and lay it behind -- a second
> rasterisation of every word on screen, a per-word cache where there
> was one entry per SUNG word, and, at a tight radius, a legible second
> copy of the word sitting behind the first. The picture wanted here
> already exists: `line_pixmap` keeps one drawing of the line per blur
> level, and it takes a pen, so the light is that same drawing in the
> sung colour at a wider level. One picture per line, cached beside the
> ones the depth blur is already keeping, and the glyphs are rasterised
> exactly as often as they were.
>
> The level is the line's own blur plus the spread, never less: a halo
> sharper than the text it belongs to is exactly the ghost copy this
> avoids, and a distant line is already soft.
>
> Skipped where the words are not where the picture says they are --
> every word in a pixmap is on the baseline, so a line coming apart
> under the float troll, or a word turning under the spin, would be lit
> where it used to be. The rise is not in that class: 5.5% of a line
> height, well inside the blur, and a wash does not notice.

### `Flow._glow_ramp`

**line 1540** — from the docstring, `def _glow_ramp(self, p, at: QPointF, pm: QPixmap, x0: float, x1: float,`

> The glow across `x0`..`x1`, stepping from opacity `a0` to `a1`.
>
> Each step is its own clipped blit, and the clips do not overlap, so
> what this costs over a single blit of the same span is the calls and
> not the pixels. See all_glow for why the alternative -- a real
> gradient, through an off-screen copy of the picture -- is not worth
> its allocation on every frame.

### `Flow._glow_strip`

**line 1629** — from the docstring, `def _glow_strip(p, at: QPointF, pm: QPixmap, x0: float, x1: float,`

> One horizontal slice of the glow, clipped out of the whole picture.
>
> `x0`..`x1` and `top`..`bot` are in the PICTURE's own pixels; `at` is
> where its top-left corner goes. Clipping rather than cropping because
> a crop is a copy: the clip costs the pixels it lets through and the
> source pixmap is the one in the cache, untouched.

### `Flow.draw_base`

**line 1647** — from the docstring, `def draw_base(self, p, ln, rows, fm: QFontMetricsF, ox: float, y: float,`

> The line's un-sung text, drawn here instead of blitted from cache.
>
> Every word in the cached pixmap is on the baseline, so a line with a
> word lifted out of it cannot use one. Cutting the lifted word out of
> the pixmap was the first way this was done and it is not sound: a cut
> is a rectangle, and a neighbouring glyph is entitled to put ink inside
> it. The left arm of a "t" reaches back under the space in front of it,
> and lost that arm every time the word before it finished.
>
> Only the line being sung ever comes through here -- everything else in
> the column still gets its pixmap -- so this is one line's worth of text
> a frame, on top of the fill that line is already drawing live.
>
> A word in `gone` is on its way out of the window: it is drawn at the
> height it has got to and at what is left of its opacity, exactly as
> the fill draws its sung half over the top. A word left down here on
> the baseline while its lit self climbs away is the same ghost the spin
> clip used to leave behind.

### `Flow.cloud_of`

**line 1751** — from the docstring, `def cloud_of(self, key, W: int, H: int):`

> Drift state for one whole LINE.
>
> Per word it scrambled the reading order -- each word arrived from its own
> direction and the line landed as a jumble. The cloud is the line: the
> words keep their layout inside it, so it stays readable however far it
> has floated.
>
> Entry and exit directions come from a hash of the key, so a line keeps
> the same path instead of teleporting when it leaves and comes back.

### `Flow._paint_cloud`

**line 1771** — from the docstring, `def _paint_cloud(self, p, idx, ln, rows, fm, ox, y, pos, act, alpha, dist,`

> Every word adrift in its own cloud.
>
> It floats in from off-screen as the line arrives, bobs while the line is
> being sung, and floats away again once the line has passed. Like the
> zero-g mode this gives up depth blur and furigana -- there is nowhere for
> a reading to sit above a word that is halfway across the window.

### `Flow._paint_loose`

**line 1892** — from the docstring, `def _paint_loose(self, p, idx, ln, rows, fm, ox, y, pos, act, alpha,`

> One line with every word cut loose from it.
>
> Each word is drawn on its own, at its resting position plus whatever
> offset the physics has accumulated, turned about its own centre. Two
> things are deliberately given up while this is on: depth blur, because
> blurring per word instead of per line would mean a pixmap per word per
> frame, and the ruby/furigana row, because a reading has nowhere to sit
> once the kanji it belongs to has floated off. Everything else -- the
> sung fill, the activation fade, the viewport falloff -- still applies,
> so the line reads normally apart from being scattered.
>
> Layout is untouched: `rows` is the same list the normal path uses, so
> wrapping, hit-testing and scrolling all still see the line where it was.

### `Flow.focus_trim`

**line 1955** — from the docstring, `def focus_trim(self, dist: int):`

> What focus mode does to a line `dist` lines from the one being sung.
>
> Returns (hush, mute) -- a multiplier on the un-sung opacity, and
> whether the line gives up its sung overlay as well -- or None for a
> line focus takes off the screen altogether.
>
> The band has a hard edge: focus N keeps N lines either side, the ring
> at N+1 is the hint of one more, and everything past that is not drawn.
> That is what the knob says it does, and in a column that SCROLLS it is
> never seen doing it. By the time a line is far enough out for the cut
> to reach it, the viewport gradient has all but finished it off -- so
> what focus deletes is something already invisible, and what the reader
> sees is the periphery blurring away rather than lines being taken.
>
> Which is a property of the column, not of the knob, and Amll has a
> different column. See Amll.focus_trim.

### `_bezier`

**line 2302** — from the docstring, `def _bezier(x1: float, y1: float, x2: float, y2: float):`

> CSS's cubic-bezier(x1, y1, x2, y2), as a function of x.
>
> The curve is given as a parametric pair and wanted as y for a given x, so
> the parameter is found by Newton-Raphson and bisection is kept as the
> fallback for the flat stretches Newton cannot climb. Cached per curve
> because there are only ever three of them.

### `Sweep`

**line 2406** — from the docstring, `class Sweep:`

> Where the light is along one row, this frame.
>
> Usually one place. Not always: a document can have two words of the same
> row sung ACROSS each other -- a trade, a second voice answering before the
> first has finished, an ad-lib written inline -- and then there are two
> voices in the row and two places the light has to be at once. A single
> edge cannot express that. It has to pick one of them, and whichever it
> picks, the other word is the one being sung with no light on it.

### `Sweep.near`

**line 2416** — from the docstring, `def near(self, px: float, w: float) -> float | None:`

> The light this fragment belongs to: the nearest one BEHIND it, or
> None where every light in the row has already gone past it.
>
> With a single light -- which is almost every row of almost every
> document -- this hands the same one to every fragment, and the whole
> row is drawn through one gradient exactly as before. Two lights, and
> each word takes the one that is actually sweeping through it.
>
> Only ever asked about a fragment the voice has NOT REACHED: one part
> way through is filled from its own clock and a finished one is filled
> solid, and neither comes here (see Amll.fill_pen). So the only light
> that belongs to a fragment here is one arriving at it, and a light
> already past it belongs to some other word.
>
> Which is why the ones past it are dropped rather than measured. The
> gradient a light draws is sung on its left and clear on its right,
> and a gradient PADS: hand a fragment a light past its own right edge
> and every letter of it is left of the sung end, so it is painted
> solid -- a word the voice is nowhere near, lit end to end. That is
> what a row with two lights in it did to the word between them. It
> took the far one whenever that was the nearer of the two, and the
> fragment lit for the two or three frames until the light moved on:
> "Boop-boop-boop; yeah", with the "yeah" of an ad-lib stamped before
> the "boop;" in front of it, lights that "boop;" whole for 40ms as the
> "yeah" opens, and 40ms is long enough to see and short enough to look
> like a fault in the window rather than in the document.
>
> A light that has reached the fragment but not crossed it is kept, and
> that is the case this is here for: two voices in one row, each word
> filling from the one sweeping through it.

### `Emph`

**line 2431** — from the docstring, `class Emph:`

> A held word's characters, and where each of them is this frame.
>
> `(character, sideways, up, scale, how lit)` per grapheme, in pixels, plus
> the one blur radius they share -- AMLL animates the shadow's alpha and
> leaves its spread alone for the whole of a word's life.
>
> `sideways` is a finished offset from the fragment's own laid-out x, not a
> nudge: it already carries the word's opening out. It has to, because a
> word can be written as several fragments and each fragment is laid out
> against the UNSCALED widths of the ones before it. Widening a fragment on
> its own therefore walks it into the fragment after it -- measured at 12.6
> pixels of overlap on a six-letter word in two fragments, which is two
> letters drawn through each other. The whole word is laid out at once in
> emph_plan instead, and each fragment is handed its own slice of it.

### `_solve_spring`

**line 2457** — from the docstring, `def _solve_spring(frm: float, vel: float, to: float, mass: float,`

> Position at t, for a spring let go at `frm` moving at `vel`.
>
> The two branches are the two ways a spring can be: damped hard enough
> that it crawls in to the target, and damped less than that, so it arrives
> early and rings. Both are the standard solution; what matters here is that
> the velocity is an argument, because a spring re-aimed halfway through has
> to leave at the speed it was already going or the line visibly stops dead
> and sets off again.

### `Spring._speed`

**line 2500** — from the docstring, `def _speed(self, t: float) -> float:`

> How fast it is travelling at t, off the solved curve.
>
> The window either side is CLAMPED to the moment the spring was let
> go, and that is not a rounding detail. _solve_spring answers the
> TARGET for any t below zero -- it is a curve from 0 forwards and a
> flat line before it -- so a centred difference that reaches back past
> zero reads the whole remaining distance as though it had been covered
> in a millisecond. On a frame shorter than H, which is the first frame
> after every re-aim if the caller is stepping fast enough, that is a
> velocity a thousand times too big, handed straight back to _reaim by
> the next set_target. Measured, with a target that moves every frame:
> at a 1ms step the value tracks the target 50 behind, and at 0.9ms it
> is -inf inside 3000 frames.
>
> Clamping here rather than putting a floor under `step` in update():
> a floor makes the clock run fast, which is a spring that settles
> sooner than the caller asked for, and it would leave _accel -- which
> reads this function at t +/- H, one whole H further back -- reaching
> past zero anyway.

### `Amll`

**line 2598** — from the docstring, `class Amll(Flow):`

> The stack again, moved the way Apple Music-like Lyrics moves it.
>
> Everything about the WORDS is the stack's: the same plan, the same blurred
> pictures for distant lines, the same fill sweeping through the line being
> sung, the same rise and pop and glow and dots. What is different is how
> the column gets from one line to the next.
>
> The stack scrolls. There is one number -- view.scroll -- the window eases
> towards the line being sung, and every line in the column is a fixed
> distance from every other, so the whole thing arrives together like a page
> being slid.
>
> This does not scroll at all. Every line is given its own place in the
> window and its own spring to get there, and the springs are let go in
> order down the column, each a little after the one above it. A line change
> therefore moves the top of the column first and the bottom of it last, and
> for the fifth of a second in between, the column is not straight: it is a
> wave passing down it. That is the whole effect, and it cannot be had by
> easing a scroll, because a scroll has one number and a wave needs one per
> line.
>
> Because the lines carry themselves, view.scroll is left at 0 and the wheel
> does nothing -- the same bargain the pinned renderers make, for the same
> reason. AMLL's own touch-and-wheel engine, which lets a reader drag the
> column and hands it back five seconds later, is not ported.

### `Amll.focus_trim`

**line 2662** — from the docstring, `def focus_trim(self, dist: int):`

> The same band, taken away gradually, because here it is watched.
>
> Flow.focus_trim cuts at N+1 and is right to: a scrolling column has
> already carried a line that far out into the viewport gradient, so
> the line the cut takes was a ghost before it was taken.
>
> This column does not scroll. Every line springs to a place of its
> own around the window's Line height, the gradient's centre, and it
> is packed the way AMLL packs it -- so the line sitting at N+1 here
> is still perfectly legible when the focal line moves on and the cut
> reaches it. Cutting there does not read as
> focus. It reads as a line being DELETED in mid-air, one row below
> something the reader is in the middle of, on the beat of every line
> change.
>
> So the band keeps going past the edge instead, at a share of the ring
> that falls away over FOCUS_FADE more lines and is squared so it goes
> quickly, which the depth blur is riding up to MAX_BLUR through at the
> same time. By the last of them the line is carrying about two parts
> in a thousand of the ink, which is nothing to look at and nothing to
> draw -- and THAT is where it is dropped, on a line nobody can see
> rather than on one they can.
>
> Focus still means what the knob says: N lines either side is what is
> readable, and the rest is periphery. What it no longer does is take
> the periphery away while someone is looking at it.
>
> Not under zero-g or the clouds, which cut a line into its words and
> draw them one at a time -- there is no cached picture to lean on, so
> a line carrying two parts in a thousand of the ink costs exactly what
> the line being sung costs. _warm_next stands down in those two modes
> for the same reason. The hard cut comes back, and it is the right
> trade: a mode that is already throwing the words about is not one
> where a line leaving quietly is what anybody is looking at.

### `Amll.wheel`

**line 2698** — from the docstring, `def wheel(self, dy: float) -> bool:`

> Taken, while the column is this renderer's to move.
>
> It is not always. An unsynced document has no clock to spring to, so
> paint hands the frame to the stack, and the stack moves the column
> with view.scroll -- nothing on that path ever reads the offset this
> would move. Taking the wheel there was taking it nowhere: a page of
> static lyrics could not be scrolled at all under this renderer, which
> is the one kind of document a reader has to scroll BY HAND, because
> there is no clock to carry them down it.
>
> Declined, and the window falls through to its own scroll, which is
> what is actually drawing the column at that moment.
>
> The step lands on the offset whole rather than being eased into it,
> because the easing is already there: every line springs to its new
> place, so a notch of the wheel is carried by the same movement a line
> change is, with the same stagger running down the column. That is what
> AMLL does with a wheel step too -- its DiscreteScroll relayout moves
> the targets and lets the springs do the rest.

### `Amll._rebase`

**line 2710** — from the docstring, `def _rebase(self, plan, H: int) -> bool:`

> A new SONG under the renderer means new springs.
>
> Everything remembered here is remembered by LINE NUMBER, and a line
> number means nothing once the next song is on -- the same trap the
> pinned renderers document at Pinned.forget.
>
> The new springs start two windows below the bottom, which is where
> AMLL starts a rebuilt view, so a song arrives by flying up into place
> with the stagger running down it rather than by being switched on.
>
> Keyed on the TRACK, which is the only thing that actually answers the
> question. A document is replaced far more often than the song
> changes: a better source arriving mid-song hands over a new one, and
> the reader is told about it by the whole column scrolling in from
> below to announce lyrics that were already on screen.
>
> Keying on the list it came in was wrong -- every replacement is a new
> list. Keying on the WORDS was wrong too, and less obviously: a better
> source is a different transcription, so the punctuation and the
> capitals move, and prepare() puts interlude markers in where the gaps
> are, so a corrected clock can add or drop a line and change the count.
> Either is enough to make the same song look like a different one.
>
> The track id changes when the song does and at no other time, so that
> is what this asks. Where there is no clock to ask -- a fixture, a
> test -- it falls back to the words, which is at least stable across a
> re-timing.
>
> Being handed a different NUMBER of lines for the same song is a
> separate question from being handed a different song: the springs
> have to be resized either way, but only a new song arrives from
> below. See below the key.

### `Amll._step`

**line 2741** — from the docstring, `def _step(self) -> float:`

> Seconds since the last frame, clamped. See MAX_STEP.
>
> The unclamped figure is kept as `self._wall`, because the clamp is for
> the springs and the seek detector needs the truth: a frame that really
> did take a second is a frame the song really did advance a second in,
> and comparing it against a tenth would call that a seek.

### `Amll._focal`

**line 2762** — from the docstring, `def _focal(self, pos: float, n: int, seeking: bool = False) -> int:`

> The line the column is built around.
>
> The window's own answer, so this renderer and every other one agree
> about where the song is -- and, more to the point, so that a line
> whose end has been stretched over an ad-lib written into it does not
> hold the column while the next line sings. See view.focus_line.
>
> With one exception, for the case that answer is not written for.
> focus_index never scrolls away from a line that is still sounding,
> which is right while the song is playing and wrong the instant someone
> CLICKS a line: a line beginning under the tail of the one before it
> then lands on the line before it, and the column travels there, waits
> for that line to finish, and only then goes on to the line that was
> actually asked for. Two moves, and the first of them to the wrong
> place.
>
> So a seek that lands exactly on a line's own start -- which is what a
> click is, and what nothing else produces -- pins the column to that
> line, and holds it there until the song's own answer catches up with
> it. Nothing about playback changes: this can only ever move the focus
> FORWARD, to a line that has already begun.

### `Amll.sweep_of`

**line 2965** — from the docstring, `def sweep_of(self, row, ox: float, pos: float, fm: QFontMetricsF):`

> Every light burning along this row, or None before any of them.
>
> A fragment part way through its own span puts a light where the voice
> has got to inside it. Normally exactly one fragment is in that state
> and the row has one light; where two words are sung across each other
> it has two, and both words fill at once. See Sweep.
>
> The whole row is read, never broken out of early. Breaking at the
> first fragment that has not started was the bug: stamps are not always
> in reading order -- a line with an ad-lib written into it can have its
> last word start before its second-to-last -- and stopping there left
> a word that really was being sung with no light on it until whatever
> preceded it in the ROW caught up.
>
> With nothing mid-flight the light waits at the end of the furthest
> word finished, which is AMLL's pause segment: through a gap in the
> timing the sweep holds rather than running on to meet the next word.

### `Amll.syll_bar`

**line 3036** — from the docstring, `def syll_bar(self) -> float:`

> How long a SYLLABLE must be held to be one, or 0 for the word.
>
> The window's knob, read through a default because the renderers are
> also driven by the stub views in the tests, which borrow the real
> methods off LyricsView rather than inheriting its state. A knob added
> here should not be a thing each of those has to learn about before
> anything will paint.

### `Amll.graphemes`

**line 3081** — from the docstring, `def graphemes(cls, txt: str) -> tuple:`

> A word split the way it is READ, not the way it is stored.
>
> AMLL reaches for Intl.Segmenter here. There is no such thing to hand,
> so this is the part of it that matters for lyrics: a base character
> keeps whatever hangs off it -- accents, a variation selector, the
> joiner in a compound emoji -- instead of being torn off it and given
> a scale and a float of its own.

### `Amll.emphasised`

**line 3104** — from the docstring, `def emphasised(cls, core: str, dur: float, bar: float = 0.0,`

> Whether this word is being HELD, as against merely being long.
>
> With `bar` above zero the question is asked about a SYLLABLE instead,
> and the whole of it is "was this piece held that long" -- see
> emph_plan, which is where the unit is chosen. Both of AMLL's guards
> are dropped with the unit, deliberately: the letter rate below is a
> measure of how much text there is to get through and a syllable is
> one mouthful by construction, and the single-letter rule is about a
> one-letter WORD, where the whole of the note is one character. The
> "o" of a held "o-oh" is neither, and it is exactly what this is for.
>
> AMLL's shouldEmphasize, and the length cap is the interesting half of
> it: a second of "understanding" is a word being pronounced and a
> second of "stay" is a note. Only the second is a performance, so only
> the second lights up. The stack lights both, because it decides on
> duration alone -- which is why a slow line there can have four or five
> words glowing at once and a line here has one.
>
> The bar is per LETTER, which is where this parts from AMLL. AMLL caps
> a word at seven letters a second, a ceiling that left "Titanium"
> (eight letters, four seconds) unlit, and is flat below it, so a
> held "go" and a spoken "forever" were asked the same. Here the bar
> is Pop only past times (letters / EMP_LETTERS) ** EMP_POW, never
> under EMP_SHORT of it: a two-to-four-letter word earns it a little
> sooner, "forever" needs 1.3 times as long, and the curve flattens so
> "understanding" still lights at 2s. Letters are letters and digits;
> punctuation used to count, so "it," was a longer word than "it".
>
> Measured over the 36672 words in lyrics/fetched: at 0.7s the share
> lit barely moves (9.3% -> 9.7%) but shifts from long words to short
> ones -- "forever" at 0.87s and "darkness" at 0.82s go dark, "go" at
> 0.69s and "ooh" at 0.61s light. At 1.0s, 4.8% -> 5.0%.
>
> CJK is counted by how it reads (`_letters_of`): a kana as two
> letters, a kanji as three, so ずっと is as long as "zutto".
>
> Right-to-left words never are: the emphasis moves each letter on its
> own, which pulls joined Arabic apart into its isolated forms, and the
> letter positions it reads are laid out left to right. Spicy turns its
> letter groups off for them for the same reason.

### `Amll.left_hold`

**line 3128** — from the docstring, `def left_hold(self, idx: int, ln: dict, rows, fm: QFontMetricsF,`

> (hold, sink) for a line the voice has just left.
>
> AMLL's disable() reverses a line's floats and leaves its emphasis
> playing to the end. Here the emphasis was scaled by the line's
> activation, which falls to nothing in about 60ms, so the last word
> of a line -- whose note ends with the line, and so whose tail and
> Pop linger always run past it -- snapped back to rest at once, and
> Pop linger did nothing there at all.
>
> So a line whose held word is still moving when the voice leaves it
> is held: `hold` 1 keeps it sharp (a blurred line is a still picture,
> nothing in it can bend) and its emphasis unfaded until the word is
> at rest, then eases back to 0 over HOLD_EASE so the blur returns
> gradually. `sink` is what the line's float is scaled by meanwhile:
> down from 1 to 0 across the hold, landing as the word does, rather
> than with the activation.

### `Amll.emph_plan`

**line 3183** — from the docstring, `def emph_plan(self, rows, pos: float, fm: QFontMetricsF,`

> Held WORDS, not held syllables.
>
> This is the thing that stopped it firing at all. AMLL asks
> shouldEmphasize about a word, and a word there is the whole word --
> the merged chunk, with the whole note's length on it. The rows here
> are cut into SYLLABLES, and a note held two seconds over three of them
> has not one syllable lasting a second, so the gate turned every one of
> them down and nothing in the document ever lit up.
>
> So the syllables are grouped back into the words they spell -- which
> Renderer.words_of already does, and span_of already dates -- the gate
> is asked about the word, and the characters of the word are then dealt
> back out to the syllables that own them. The stagger and the push are
> therefore cut across the whole word, which is also what AMLL does:
> both count from the word's first character, not from each syllable's.
>
> `syll_hold` puts the unit back to the syllable, on purpose and with
> its own bar. The reason the word is the unit above is that a syllable
> cannot clear a bar of EMP_MIN -- the median one in these documents is
> a quarter of a second -- so the gate is no use at the smaller unit
> until it is told a smaller number, and that number is the setting.
> Given one, every piece the document was timed into is judged on its
> own length: the run is split here, before the tail is picked, and
> everything downstream is unchanged because a one-piece run is a shape
> it already handles. What changes on screen is that a word stops
> moving as one thing. "Ti|ta|ni|um" with the hold on its last piece
> lights that piece and leaves the other three alone, where the word
> unit lights all eight letters off the whole four seconds.
>
> The bar is what decides how much of a song glows, and it is steep.
> Over the 71922 timed pieces in this folder: 1.0s lights 3.5% of them
> and leaves something lit in 22% of the 8892 lines, which is roughly
> what the word unit does at 25%; 0.75s is 33% of lines, 0.5s is 56%,
> and 0.4s is 70%. So the number is not a threshold to be tuned around
> a word -- it is the density knob, and the word unit sits at the top
> of its range.

### `Amll.emph_of`

**line 3378** — from the docstring, `def emph_of(self, txt: str, s, e, pos: float, fm: QFontMetricsF,`

> Where every character of a held word is, this frame.
>
> Three movements at once, each on its own clock, which is what makes
> this a different thing from the stack's pop rather than a tuning of
> it:
>
>   * the characters grow, and the word opens out by exactly as much
>     as they grow, so the letters keep the gaps they were set with.
>     AMLL does that with a separate sideways push of a fixed share of
>     the em; this does it by giving each character a slot as wide as
>     its own scaled advance. See emph_plan for why the push could not
>     do the job on this face;
>   * each one floats up and back down on a sine, setting off EMP_LEAD
>     before its own glow and running 1.4 times as long, so the movement
>     is already under way when the light arrives;
>   * the light swells and dies on a two-piece bezier that is not
>     symmetric -- see _emp_easing, which comes up on one curve and
>     leaves on another.
>
> and each character is started a little after the one before it, by a
> fifth of the word's length divided between them. That stagger is the
> reason any of this is per character: without it the letters all do the
> same thing at the same moment, which is a word scaling, which is the
> pop the stack already has.
>
> How MUCH of all that is a curve on the word's length -- cubed while it
> is under two seconds and square-rooted past it, so a note held briefly
> barely moves and a long one does not run away with the line. The last
> word of a line is given half again, which is AMLL putting a button on
> the end of the phrase.
>
> The window's own knobs still mean what they mean: `pop` scales the
> movement, `glow_scale` the light and `rise` the float.

### `Amll.word_lifts`

**line 3537** — from the docstring, `def word_lifts(self, rows, fm: QFontMetricsF, pos: float, act: float,`

> How far each word has floated, on AMLL's schedule rather than the
> stack's.
>
> The two disagree about what a float is FOR. The stack gives every
> syllable a fixed window of a third of a second, set off a frame or two
> early and held down to whatever the syllable in front of it reached,
> so that what crosses the line is a wave in reading order and never a
> word standing up out of turn -- and the docstring at RISE_LEAD records
> that a wider schedule was tried there and rejected, because two or
> three words off the floor at once reads as the line guessing ahead of
> the voice.
>
> AMLL's is the wider schedule. A word floats over its own LENGTH, so a
> held note climbs for as long as it is held and several words really
> are in the air together. That is the thing the stack decided against,
> and it is here because it is what this renderer is a port of: on a
> line of short words the whole line drifts up, and on a held one the
> note rises with it. It is ease-out and it does not come back down --
> the word stays where it got to.
>
> One float per WORD, though, not per syllable, and this is the other
> half of why the two schedules cannot be mixed. The stack can afford a
> lift per syllable because each one is over in a third of a second and
> the next is already climbing before the last has settled -- a wave
> through the word, not a seam. Run over each syllable's OWN length
> instead and the seam stops being momentary: a word split "sta" + "y"
> with the hold on the second syllable has the first floating over a
> third of a second and the second over a second and a half, so the
> front half of the word stands up while the back half is still on the
> floor, and stays there. The word tears in two and holds the pose.
>
> So every syllable of a word is given the word's own span and the same
> lift, and the word goes up in one piece. That is also what AMLL means
> by a word: the thing it emphasises is the merged chunk, not the pieces
> the timing happens to be written in.
>
> What a word is, though, is settled by Renderer.words_of, and a piece
> that ends in a HYPHEN ends one. That is not a syllable split -- it is
> a stutter, a spell-out or a hyphenated compound, and each piece of it
> is an utterance the voice arrives at separately. Read as one word they
> went up as a slab: "fuck-fuck-fuck-fuck-fuck" rose once over the whole
> of itself instead of five times, and so did every "F-R-I-E-N-D-S" in
> the chorus of one. The tearing this schedule has to avoid is a word
> coming apart at a seam nobody wrote; a hyphen is a seam somebody did.
>
> The one other departure is the floor under that length, and it is
> there so that the `rise` knob means the same amount of movement here
> as it does everywhere else in the window. See FLOAT_MIN.

### `Amll._scaled`

**line 3702** — from the docstring, `def _scaled(self, p, args, s: float, x0: float, width: float,`

> One line, under its own scale if it has one.
>
> The transform is skipped entirely at full size rather than applied as
> an identity, because a painter under ANY transform resamples the
> pictures the stack blurs its distant lines into. The line being sung
> is the one at full size, so the line that has to be sharp is the one
> that never sees a transform.

### `Pinned`

**line 3714** — from the docstring, `class Pinned(Renderer):`

> Shared ground for the renderers that do not scroll.
>
> The stack is a column taller than the window that slides past a focus
> band. These are not: they show one or two lines, in a place they choose,
> and the line being sung changes what is drawn rather than where the window
> is looking. So view.scroll stays at 0 and the wheel does nothing to them.
> (Cards outgrew that and scrolls again -- what it kept is everything below.)
>
> They also draw every word live. The stack caches an un-sung line as a
> pre-blurred pixmap because it has thirty of them on screen; two lines at a
> size of their own would miss that cache on every frame it mattered.

### `Pinned.song_end`

**line 3731** — from the docstring, `def song_end(self) -> float | None:`

> The last moment this document has anything to say, or None.
>
> Worked out once per document, the way _index is: a new lyric is a new
> list rather than an edited one, so its identity and length are enough
> to notice one. The credits row has no clock and the interludes are not
> words, so neither counts -- what is wanted is when the singing stops.

### `Pinned.stacked`

**line 3759** — from the docstring, `def stacked(self) -> bool:`

> Only on the static page, which is the stack's own layout.
>
> These renderers set their own type and lay their own rows out, so the
> window cannot work out where a word of theirs ended up -- which is
> what `stacked` asks, and why the review marks go to the margin under
> them. A document with no clock is drawn by the stack instead (see
> static_page), and on that path the layout IS the window's, so the
> rules can go back under the words.

### `Pinned.static_page`

**line 3764** — from the docstring, `def static_page(self, p, x0: float, width: float, H: int) -> bool:`

> A document with no clock, printed as a page. True if it was.
>
> These renderers are about WHERE THE VOICE IS: one line held in the
> middle of the window, the next one waiting, the last one fading out.
> Take the clock away and there is no voice to be anywhere, and what
> they did with that was draw nothing at all -- `live` is empty, so
> `current` has no line to build a frame around and the paint fell
> straight through to the end. A reader who had chosen one of these and
> opened a page of untimed lyrics got an empty window.
> (Cards is the exception and does not come here: it lays the whole
> document out already, so it has a page to draw without a clock. What
> it had instead was every card dimmed as un-sung -- see its paint.)
>
> The stack knows how to print a page of text, and it moves that page
> with view.scroll, which is the thing the window scrolls when a
> renderer declines the wheel -- so this hands over whole rather than
> reimplementing a static column here. It is the same answer Amll
> reaches for on the same path, and for the same reason.
>
> The stack is built on first use and kept: a renderer is made once per
> window and a document arrives unsynced far more often than never,
> but there is no reason for every one of these to carry a second
> renderer around for a document that may never come.

### `Pinned.face_pair`

**line 3778** — from the docstring, `def face_pair(self, px: float):`

> (font, its metrics) at this size, built once and handed to every
> frame that asks.
>
> Both were built afresh on every frame, and the metrics carry the
> advance and shape memos (see advance, wrap_shape) -- so every frame laid
> out the current, previous and next lines from nothing, the words and
> the wrapping alike. What the font is made from is in the key: the
> family, the size it is truncated to and the pinned weight.

### `Pinned.singable`

**line 3795** — from the docstring, `def singable(self, i: int) -> bool:`

> A line these renderers have anything to say about.
>
> The trailing credits block is a paragraph about the document, not a
> line of the song, so it is never one of the lines these pick between,
> never takes a band or a card of its own, and is never the line the
> clock is on. It is still DRAWN -- attribution has to be wherever the
> lyrics are -- by credits_block, under whatever the renderer put last
> on the screen, or at the foot of the column where there is one.

### `Pinned._index`

**line 3801** — from the docstring, `def _index(self):`

> The document sorted into lines that own a place and lines that do not.
>
> `group` is the item a line was written in, so a backing vocal and the
> line it belongs to still point at each other after the flattening has
> moved an ad-lib that opens early ahead of its own lead. What comes out
> of that is a HEAD -- a line one of these renderers gives a place of its
> own: every lead line, plus an ad-lib whose lead is missing, which is
> the whole document in a source that is nothing but backing vocals.
>
> Worked out once per document. A new lyric is a new list rather than an
> edited one, so its identity and length are enough to notice one.

### `Pinned._same_doc`

**line 3827** — from the docstring, `def _same_doc(had, key) -> bool:`

> Whether (lines, count) is the document `had` was worked out for.
>
> The list itself is held and compared by `is`, not remembered by id():
> a song's list is freed when the next one replaces it, and the next can
> be born at the same address -- with the same number of lines, that was
> the old song's index handed to the new one.

### `Pinned.forget`

**line 3832** — from the docstring, `def forget(self) -> None:`

> The document under the renderer has been replaced.
>
> Anything one of these remembers between frames is remembered as a LINE
> NUMBER, and a line number means nothing once the next song is on: at
> best it is a different line, at worst it is past the end of a shorter
> document. Nothing to do by default; Spotlight has a fade to drop.

### `Pinned.current`

**line 3868** — from the docstring, `def current(self, pos: float):`

> The line to build the frame around, and the head after it.
>
> The window's own answer to where the song is (see view.focus_line),
> not the first thing sounding. The two differ exactly where a line has
> an ad-lib written into it: the document stretches such a line's end
> over its backing vocal, so it is still "sounding" through the whole
> of the line after it -- and a renderer that drew the first live line
> sat on the finished one and would not move on until the ad-lib let
> go. It also puts a lead line in front of anything backing it, which
> is what these want anyway: an ad-lib is drawn hanging off its line,
> so the line is what the frame is about even when the ad-lib is the
> only part of it sounding yet.

### `Pinned.mark`

**line 3903** — from the docstring, `def mark(self, i: int, top: float, h: float, x0: float, width: float) -> None:`

> Publish a line's box so a click on it seeks there.
>
> In the space the stack publishes in: screen y plus view.scroll, which
> is 0 for everything here that pins its lines. line_at subtracts the
> anchor from the click and from the box alike, so it cancels and must
> not be added in.

### `Pinned.line_lifts`

**line 3909** — from the docstring, `def line_lifts(self, rows, fm: QFontMetricsF, pos: float,`

> How far each fragment has lifted, one dict per row, keyed by index.
>
> The same schedule the stack uses and for the same reason: the rise is
> cut for the whole LINE rather than run off each syllable's own clock,
> so what crosses it is an incline and not a step. Asked for the line
> and not for a row at a time because the incline does not stop at a row
> break -- the head of row two is the next thing after the tail of row
> one, and it should be on its way up before the voice gets there. See
> Renderer.rise_plan.

### `Pinned.draw_row`

**line 3919** — from the docstring, `def draw_row(self, p, row, ox: float, ry: float, fm: QFontMetricsF,`

> One wrapped row of a line, filled to the clock.
>
> Un-sung text first and the fill over it, both under whatever transform
> the pop and the rise have put on the painter -- so a word that lifts
> takes all of itself with it. Nothing is cached and nothing is clipped,
> which is why these renderers never had the stack's trouble of a cut
> rectangle biting a neighbouring glyph.
>
> `lifts` is this row's share of the whole line's rise, worked out once
> by the caller. A row left to work out its own would be a line the wave
> has to restart at every row break.

### `Pinned.draw_adlibs`

**line 3987** — from the docstring, `def draw_adlibs(self, p, of: int, live, font: QFont, fm: QFontMetricsF,`

> The backing vocals of one line, small, under it. Returns the drop.
>
> They are drawn INSIDE the block of the line they belong to rather than
> given a place of their own, because that is what they are: a second
> voice on this line, sung across it. A renderer that handed them a slot
> of their own had them taking the place of the line coming next, which
> is the one thing the reader needs to be able to see.

### `Spotlight`

**line 4005** — from the docstring, `class Spotlight(Pinned):`

> The line being sung, alone and large, between the two either side of it.
>
> Nothing moves up the window: a line arrives where the last one was and the
> two cross-fade.
>
> That fade is on a clock of this renderer's own, and not on the activations
> the window eases, because those say what is SOUNDING. A line whose last
> word is held under the start of the next one goes on sounding through it,
> and every line written that way -- a trade, a chorus with a tail, anything
> with an ad-lib in it -- was drawn at full strength straight through its
> replacement for as long as the document said it lasted. Lines here are
> stacked in one place, so what that reads as is not a line leaving: it is
> two lyrics printed over each other. The line being sung is now the only
> big one, and whatever it took over from has FADE seconds to get out.
>
> The neighbours are set small and dim, and hung off the top and bottom of
> whatever the middle line actually came out to be rather than off a guess at
> how tall one line is -- a couplet that wraps to three rows would otherwise
> have them printed through it. All three take a click.
>
> The credit goes under the lowest of them once the song has finished, for
> the same reason it is hung off the real height rather than a guess: where
> the lines end is not known until they are drawn.

### `Spotlight.leaving`

**line 4020** — from the docstring, `def leaving(self, cur):`

> {line: how much of it is left}, for the line on its way out.
>
> One at a time, and always the last one there was. A drag along the
> progress bar changes the line under the clock on every frame, and a
> fade that kept all of them had a second of song dissolving on top of
> itself -- twenty big lines drawn over each other, for as long as the
> reader held the bar.

### `Karaoke`

**line 4093** — from the docstring, `class Karaoke(Pinned):`

> Two lines in the middle of the window: what is being sung, and what is
> coming.
>
> Which of the two bands a line lands in is decided by where it is in the
> document and not by which band is free, so a line never changes row
> halfway through being sung -- that is the whole reason the pair alternates
> rather than scrolling. It counts LINES THAT TAKE A BAND, though, rather
> than raw indices: a verse with an ad-lib written into every line has its
> lines two apart, and alternating on the index alone put every one of them
> in the same band, each printed through the last.
>
> Ad-libs do not take a band at all. They are drawn small underneath the
> line they hang off, inside its block, which is where they are sung from --
> handing them a band of their own is handing them the place where the
> reader looks for what is coming next.
>
> Where two lead lines overlap -- a trade, a second voice answering before
> the first has finished -- both are sounding and both are drawn filling,
> one per band, which is what the alternation was for in the first place.
>
> The line that has not started yet is dim, and comes up out of that dimness
> over the couple of seconds before its turn. Being dim says "not this one";
> getting brighter says when -- and it says it in the one thing every
> renderer here already uses to mean now, which drawing a bar under it did
> not.
>
> The credit sits under the lower band once the song has finished,
> whichever of the two that turned out to be.

### `Word`

**line 4157** — from the docstring, `class Word(Pinned):`

> One word at a time, very large, in the middle of the window.
>
> A word, not a syllable. Word-timed documents are timed per syllable and the
> layout keeps them that way -- which is what lets the fill sweep through a
> held note -- so the syllables are put back together here and the word takes
> the span of the ones that spell it. Otherwise a line of Apple Music TTML
> reads out as "you", "'", "re" rather than as the words being sung.
>
> An ad-lib sung across the line gets a word of its own underneath, small.
> Two voices cannot share one slot in the middle of the window: it used to
> take whichever of them came first in the document and drop the other, so a
> chorus answered by its own backing vocals came out as either the chorus or
> the answer, never as the two of them at once -- and which one it was came
> down to how the source happened to have written them down.
>
> A line with no word timing under it has nothing to take apart, so it is
> drawn whole instead -- which is also what happens to every line of a
> line-synced source, and is why this degrades rather than going blank.
>
> The credit follows the last word on screen -- the ad-lib under it where
> there is one, the word itself where there is not -- a beat after the last
> word of the song has been sung.

### `Cards`

**line 4268** — from the docstring, `class Cards(Pinned):`

> A card per line, the whole song's worth, scrolling past the window.
>
> Every card takes a click, over the whole of its rounded rectangle rather
> than over the text alone -- the card is what the reader is aiming at.
>
> This drew three cards and pinned them: the line being sung and one either
> side, moving past a window that never scrolled. Three cards is all the song
> a reader can have, and the wheel did nothing to them, so there was no way
> to look ahead or back. It lays the whole document out now and lets the
> column scroll like the stack does -- the window follows the song on its
> own, and a reader who takes the wheel gets the rest of the song and is
> given it back four seconds later, which is the behaviour the stack has had
> all along.
>
> An ad-lib is set smaller on a card inset from its line's, so the two read
> as one thing written together rather than as two lines of the song.
>
> The credit takes no card. It is not a line of the song, and it rides at
> the foot of the column exactly as it does at the foot of the stack -- this
> is the one of these four that lays the document out, so it is the one that
> has a foot to put it at.

### `Cards.rows`

**line 4279** — from the docstring, `def rows(self, i: int, fm: QFontMetricsF, width: float):`

> This renderer's wrapped rows for a line, kept between frames.
>
> Cards lays out the whole document rather than the two lines around the
> clock, and wrapping every line of it on every frame is not free. It is
> kept in the WINDOW's cache rather than one of this renderer's own so
> that everything which already empties that -- a new lyric, a new font,
> a new size -- empties this too.

### `Cards.still_card`

**line 4346** — from the docstring, `def still_card(self, p, i, ln, rows, fm, x0: float, width: float,`

> An unlit card's words as one kept picture. False where it cannot.
>
> At act 0 a card is its words in the base colour and nothing else, so
> they are drawn once, through the same lifted_word, by a painter a
> whole number of device pixels from the screen's: every word lands on
> exactly the pixels it would have. Kept while the column rests; a
> scroll changes the phase and remakes it. Measured: docs/notes.

### `_Spr`

**line 4403** — from the docstring, `class _Spr:`

> Spicy Lyrics' spring: a port of Fraktality's spr, as Spicy ships it.
>
> Not the Spring above. That one is AMLL's, and is solved for a position
> at t from a moment it was let go; this one is stepped, frame by frame,
> from where it is and how fast it is going -- which is what the words of a
> Spicy line are driven by, and what gives them their particular settle.
> `f` is in hertz and `d` is the damping ratio, as spr takes them.

### `_Curve`

**line 4465** — from the docstring, `class _Curve:`

> The `cubic-spline` package Spicy draws its keyframes through.
>
> A natural cubic spline, solved once for the knots and read at x. Spicy
> hands it three or four (time, value) points per effect and asks it where
> the effect should be at a word's progress -- so the curve between the
> knots, overshoot and all, is part of the look and is reproduced exactly
> rather than eased some other way.

### `_gauss`

**line 4582** — from the docstring, `def _gauss(img: QImage, radius: float) -> QImage:`

> A Gaussian blur, as a CSS text-shadow draws one.
>
> Qt's own blur effect, which is a true Gaussian: measured on a hard edge,
> its 10-90% ramp is 1.25-1.3 times the radius it is given, and a CSS
> shadow of blur b -- a Gaussian of sigma b/2 -- has a ramp of 1.28 b. So a
> CSS radius goes in as it is. soft_scale, which the stack blurs with, was
> tried first and cannot be fitted: its ramp moves in steps of whole
> halvings and even goes backwards between them (5px at 3x, 4px at 3.5x).

### `Spicy`

**line 4609** — from the docstring, `class Spicy(Renderer):`

> Spicy Lyrics' renderer, as the Spicetify extension draws it.
>
> A port of src/utils/Lyrics/Animator/Lyrics/LyricsAnimator.ts, the
> Applyer that builds its DOM, the CSS in src/css/Lyrics/Mixed.css that
> turns the animator's variables into pixels, and ScrollToActiveLine. The
> default look -- Spicy's "simple lyrics mode" is off by default there and
> is not ported.
>
> What it does, all of it Spicy's own numbers:
>
>   * Every syllable is its own element with three springs -- scale, a lift
>     measured in font sizes, and a glow -- aimed each frame at a natural
>     cubic spline read at the syllable's progress. Idle at 95% and a
>     hundredth of an em low, it swells to 105% as it is sung and settles.
>   * A syllable held a second or more is split into letters, each letter
>     timed over the syllable less its last quarter second, and each with
>     springs of its own pulled towards the letter being sung by distance.
>   * The fill is a gradient per syllable, 85% white to 50% across a fifth
>     of its width, carried from -20% to 100% as it is sung.
>   * A line not being sung is drawn the way the CSS draws it: the glyphs
>     themselves are transparent and what shows is their text-shadow, white
>     at half strength for a line to come and 85% for one gone by, under a
>     line opacity of about a half and a blur of 1.25px per line of
>     distance from the one being sung.
>   * A gap long enough for dots opens a line of three that swell and
>     light in turn, and the group springs shut half a second before the
>     words come back.
>   * Hovering a line lights it, clears its blur, and puts Spicy's rounded
>     highlight behind it.
>
> The column moves the way Spicy moves it -- its smooth scroll, and the
> wheel taking the blur off until
> three quarters of a second after the last notch -- but WHEN it moves
> and to which line, and to what height, is the stack's: the window's own
> focus line, with Scroll ahead and Off by one, at its Line height (Spicy
> puts it thirty pixels above the middle). Spicy's rule for that holds the earlier of
> two sounding lines while a long one lasts, which sent the column back
> up a line mid-song.
>
> Every knob in the window's menu reaches it; see `knob`.

### `Spicy._by_place`

**line 4766** — from the docstring, `def _by_place(self, states, frags, pos: float) -> set:`

> Where a line sits, not its own clock, says how it is drawn: every
> line above the one being sung is finished and every line below it
> untouched, even one already sung. The lines being sung stay as they
> are. The current line is the last one started, so an ad-lib that ends
> under a lead still being sung stays sung rather than going back.
>
> A line above the current one whose every syllable is sung is
> finished then and there, though its own end is still to come; the
> lines it returns went that way this frame and are drawn so at once.

### `Spicy.face_pair`

**line 5088** — from the docstring, `def face_pair(self, px: float, bg: bool = False):`

> (font, its metrics), one pair for every line set at this size.
>
> A font and a QFontMetricsF were built for every line, at every layout
> -- which is every step of a window resize -- and the advance and shape
> memos the metrics carry (see advance, wrap_shape) went with the object,
> so a line never found a word another line had already measured. Held
> by face, rounded size and background instead, the way the window keeps
> the stack's face; the face is in the key, so a change of type is a new
> pair. Nothing changes a font it is given.

### `Spicy.lay`

**line 5100** — from the docstring, `def lay(self, i: int, width: float):`

> A line set at Spicy's size: background vocals at three quarters,
> rows 1.18 ems apart, and 5cqw kept clear on the far side as the
> line's padding does. The face is the window's; see font().
>
> (rows, fm, h, rrows, rfm, font, rfont, pitch, ox-shift,
>  ruby, rufont, rufm, row-tops)
>
> Readings above sit in a band of their own over the rows that have
> any, set at the same share of the line's size as in the window. A
> row with none gets no band: a line that wraps into a Latin tail kept
> its tail a whole band away from the rest of it. row-tops is where
> each row starts, and one more entry for where the last one ends.

### `Spicy.lays_all`

**line 5166** — from the docstring, `def lays_all(self, width: float, n: int) -> list:`

> `lay` for every line, with what its cache key holds in common made
> once instead of once a line.
>
> The key is looked up for every line of the song on every frame, and
> most of it -- the face, the alignment, the reading modes, the size --
> is the same for all of them; building it per line was two hundred
> calls into the window for the same answer. It is the same key, so a
> hit is the entry `lay` stored, and a miss is left to `lay`.

### `Spicy._put`

**line 5484** — from the docstring, `def _put(self, p, at: QPointF, txt: str, fm, scale: float, lift: float,`

> Text under a CSS `scale` about (ox, cy) after a translateY.
>
> With a `fill`, the word is drawn once in solid white as a mask and
> the fill -- a translucent gradient -- laid into it. Drawing the
> glyphs straight in a translucent pen lays the colour on twice
> wherever two glyphs overlap, which heavy faces do at every join
> ("fl", "ck", "It"): a light seam at each one. A browser shapes the
> whole run first and fills that, so Spicy never shows one.

### `Spicy._glow`

**line 5547** — from the docstring, `def _glow(self, p, txt: str, font, fm, at: QPointF, radius: float,`

> A text-shadow: 0 0 radius, white at alpha.
>
> The radius moves every frame with the glow spring, so it is drawn as
> the two nearest half-pixel steps laid over each other in proportion
> -- a halo that grows smoothly rather than one that jumps between
> cached sizes a few frames apart.

### `Spicy._keep_pix`

**line 5739** — from the docstring, `def _keep_pix(self, sig, lvl, pm: QPixmap, pad: int) -> None:`

> Keep a drawn line, within a count of them and a number of bytes.
>
> Held to sixty lines however big each was, which is a hundred megabytes
> or so of the column's width at ordinary scale and four times that on a
> display drawn at twice the size. The budget is the stack's own, and at
> ordinary scale the count is still what bites. What goes is the one
> drawn longest ago: a line that is on screen is looked up every frame
> and moved to the end (see _shadow_line), so it is never the one.

### `Renderer.lifted_word` (comment)

**line 269** — before `t = p.transform()`

> Whether it lands on a row of the SCREEN: a gliding line carries its
> fraction of a pixel in the painter's translation, not in `y`.
>
> Under a scale it does not, whatever `y` says. Amll scales the line
> being sung from 0.97 up to 1 as it arrives, for most of a second,
> and every word of it was glyphs at a fractional device row: measured
> through a switch, the first word at 457.07, 449.47, 442.92... Qt put
> each on a whole pixel while its glow and the words already pictures
> slid -- unseen at the start, where the line moves 15px a frame, and
> a one-pixel hop every few frames in the second half, where it moves
> a third of one. As pictures they scale and slide with the rest.
> Confirmed on screen 2026-10-02: the shiver went.

### `Renderer.lifted_word` (comment)

**line 300** — before `if exact:`

> `exact`: a letter of a held word, which the push eases sideways.
> Then the picture carries the fraction of a pixel and the glyphs sit
> on a whole one inside it, and it is a picture every frame. Qt sets
> a glyph down only in quarter pixels, so the letters moved outward in
> little jumps, each on a frame of its own: measured on "walls", a
> thin "l" lost 46 of its 999 lit pixels for three frames and got them
> back. Not for anything else: a word standing still keeps the glyphs
> Qt would have drawn, sharp, and the plain drawText on a whole row
> matches its picture exactly -- with the fraction carried instead,
> the two differed, and a letter passing a row blinked for a frame.

### `Renderer.emph_glow` (comment)

**line 575** — before `p.save()`

>
> And the light SPILLS past the edge across that same `soft`, at the
> word's own level: the fill already fades on into the next letter
> while it waits at a syllable's end, and a glow stopping dead at the
> letter before it was the hard line between "no" and "thin'".
>
> It is light AROUND the letters, the way AMLL's text-shadow is: added
> (Plus) and drawn BEFORE them, so their own ink covers it. Drawn
> after them it was added onto the ink too, and a sung fill is
> already at full value -- there is nothing left to brighten but
> towards white. Measured on a peach (255,180,140) fill: the lit
> letters went to (255,239,231) beside unlit ones still peach.
> How wide and how strong is the renderer's HALO_SIZE / HALO_SCALE.
> In the line's own glow colour (`tint`), so what spills round the
> letters is their colour.

### `Flow.all_glow` (comment)

**line 1477** — before `if not lifts:`

> `lifts` -- (row, x0, x1, dy, dx) -- are the stretches of a row whose
> words are standing up off it: the float, and a held word's bend on
> top. The picture has every word on the baseline, so their light was
> left where they used to be and showed under the risen letters (red
> dashes under "tomorr" in the album's tint). Each stretch is drawn
> again lifted by its own dy, and cut out of the plain pass. A held
> word stays in the same light all the way, rising and settling with
> it -- an earlier fix cut held words out and lit them another way,
> and the swap at either end of the bend was a visible pop.

### `Flow._paint_line_at` (comment)

**line 2023** — before `if self.GLIDE:`

> A line in motion is at a fraction of a pixel nearly every frame.
> Everything below puts its rows on the pixel grid -- on_grid -- so
> its words would step a pixel at a time while the glow behind them
> and every other line glided: measured at 240fps on the sung line,
> the text sat 59.9 to 60.9px below the line's top from one frame to
> the next, a shiver against its own glow for as long as the line
> moved. So the line is drawn at the pixel and the painter carries
> the fraction: every part of it moves together, and lifted_word,
> seeing a row that is not on the screen's grid, draws its words as
> pictures that can sit between rows. At rest the springs aim at a
> whole pixel (see Amll.paint), there is no fraction, and the words
> are plain glyphs again.

### `Flow._paint_line_at` (comment)

**line 2068** — before `stays = max(act, hold)`

> Faded out with the line rather than dropped: the plan used to stop
> the moment the line lost the stage, and a held word still bending
> snapped back to rest in a frame. act * (1 - blur) is what the
> word float (word_lifts) already eases out on. A line held for its
> word is not faded at all: the word runs its own course to rest,
> as AMLL's emphasis does on a line it has disabled.

### `Flow._paint_line_at` (comment)

**line 2177** — before `ed = self.fill_edge(sweep, px, w, frac, rtl)`

> The fill edge travels WITH the letters. Fixed where they
> sit at rest, it fell in the gap the spread opens between
> two of them -- the "o" of "no" moved clear of it and lit
> whole, the "t" stayed grey, and the soft edge faded out
> across empty space: a hard line at every syllable split.
> Carried by each letter's own shift, every letter is filled
> exactly as far as it would be standing still.

### `Amll` (comment)

**line 2617** — before `SWELL = 1.0`

> AMLL's emphasis, letter by letter: each letter of a held word grows by
> up to a tenth of `amount` (SWELL) and lifts on its own (BOB). Both were
> 0 while a held word was drawn as ONE picture -- scaled whole, its 1-2px
> gaps welded. place_word now draws such a word a letter at a time, each
> in a slot as wide as its own grown advance (emph_plan), so the gaps
> are the font's own however far the letters grow.

### `Amll.emph_plan` (comment)

**line 3213** — before `arrive = []`

> A letter sets off when the FILL reaches it: its syllable's
> start plus the share of the syllable the fill takes to get
> to it. Within a syllable AMLL's own stagger (two fifths of
> it) put the letters up nearly together, so the word climbed
> in steps, one per syllable -- op|por|tu|ni|ties as a
> staircase. Paced by the fill, the bend is one slope moving
> exactly where the colour is.

### `Amll.emph_plan` (comment)

**line 3243** — before `push = fm.height() * _EM * 0.1`

> A third of AMLL's sideways push on top of the slot: a letter
> at the height of its swell stands 0.01 * amount em further
> from its neighbours. Without it the gaps were only ever the
> font's own, and where the font left one under a pixel ("r"
> before "e") the anti-aliasing of two growing letters met
> across it. AMLL's whole push on top of the slot was too much:
> "compares" spread some 40px, its "c" off the line's edge.

### `Amll.emph_plan` (comment)

**line 3260** — before `centre = left + plain * 0.5`

> Outward from the word's middle, never across it. The letters
> swell one after another, so re-centring the whole word on
> each frame slid a letter that had not started yet TOWARD
> the middle whenever one beside it grew. Instead each letter
> keeps its rest place and moves out by what the letters
> between it and the middle have grown, plus half its own:
> every gap stays what the font made it, plus the push.

### `Amll.emph_plan` (comment)

**line 3286** — before `runs = runs_by_row[r_i]`

> Kept off its neighbours. A word may spread into half the
> space either side of it -- so two swelling at once still
> cannot meet -- and none past the start of its row; whatever
> it cannot have on one side it takes on the other. "compares"
> grew into "else" until the space between them was gone, and
> off the left of the line when it started the row. Only where
> both sides are short is the spread itself squeezed.

### `Amll.emph_of` (comment)

**line 3420** — before `linger = max(0.0, min(1.0, float(getattr(self.v, "pop_linger", 0.0)`

> The BEND. AMLL starts letter i du/2.5/n after the first, so the
> swell takes four tenths of the word to cross it and every letter
> runs the whole du: at any instant the letters stand at different
> points of the same curve, and the word bends. Measured on a two-second "forever",
> the old 0.06s steps, each cut short to end with the word, left the
> letters within 0.2px of each other -- the word went up flat, a
> third higher than AMLL, where AMLL's slope is 1-2.5px.
>
> AMLL's proportions, fitted inside the note. Run at AMLL's own
> lengths the last letter is still floating at 1.8 du -- a held two
> seconds kept moving for two more, into the next line, where the
> line's fade cut it off mid-bend. So the schedule is squeezed to end
> emp_tail after the note: the stagger, the swell and the 1.4x float
> keep their ratios, and a letter whose syllable starts late is given
> what is left rather than running past.
>
> Pop linger runs from that (0) to AMLL's own lengths (1), for anyone
> who likes the word still moving into the next line.

### `Amll.emph_of` (comment)

**line 3442** — before `if arrive is None:`

> A letter sets off when the voice reaches it: at its own syllable,
> and inside that by AMLL's stagger, two fifths of the syllable
> divided between its letters -- so a word timed in one piece is
> AMLL's exactly. Staggering evenly across the whole word instead
> bent the next syllable before it was sung, and with the glow on it
> lit up early, like the snap renderer.
>
> And every letter runs on to the word's end rather than for a fixed
> length. With fixed lengths a long first syllable had settled before
> the next began -- "no" of no|thin' rose and fell alone, then "thin'"
> did it again, two bumps. Running on, "no" is still up as "thin'"
> rises: one wave, moving with the voice. Capped at AMLL's own du.

### `Amll.emph_of` (comment)

**line 3457** — before `leans = [0.0] + [min(self.LEAN_MAX, max(0.0, b - a))`

> A letter's float sets off when the one before it arrives, so a
> waiting letter leans up after the sung one -- on its own curve.
> Held up to a share of its neighbour instead (a rope), it rode that
> neighbour and then took off on its own: two pushes, and the word
> looked like it was correcting itself. Only the float leans; the
> grow and the light still wait for the fill.

### `Amll.emph_of` (comment)

**line 3498** — before `up = (math.sin(math.pi * x) ** 2`

> sin squared, not AMLL's sin: the same peak, but it lifts off and
> LANDS at rest. A sine arrives at the floor at full speed, which
> over AMLL's seconds-long float went unseen; fitted inside the
> note it read as each letter dropping and stopping dead. The
> grow's own lift rides the same curve, so a letter's height is
> one movement rather than two on different clocks.

---

## Lift — 2026-09-26

Comments lifted out of `mild-lyrics/renderers.py` on 2026-09-26; the line numbers are that day's.

### module level

**line 65** — before `NUDGE = 1.0 + 1e-7`

> Off by a ten-millionth: nothing to see, but enough that Qt stops treating
> the transform as a plain shift.

**line 104** — before `WARM_EDGE = 40`

> How far outside the window a line still counts as worth warming. The same
> margin paint() culls on, and for the same reason: a line a few pixels off
> the edge is one scroll frame from being drawn.

**line 131** — before `FACE_GAP = "\u2002\u2003"`

> The room left after a community sync maker's name for their picture: an en
> and an em space, so it sits a little clear of the name at the credit's size.


### `Renderer.credits_block`

**line 617** — before `top = H * 0.08`

> Above the lyrics, before they start: the head of the window
> rather than the foot of whatever line is waiting.


### `Flow.all_glow`

**line 1267** — before `split = bool(rrows) and any(row_rtl(row) for row in rows)`

> Bands of the picture, each swept by its own row's edge. The
> romanisation normally rides in the last row's band; under a
> right-to-left line it is Latin and runs the other way, so it gets
> bands of its own, lit by its own clock.


### `Flow._paint_line`

**line 1830** — before `rw = rufm.horizontalAdvance(read)`

> Filled the way the text under it is, not stepped in two
> flat shades: a reading sits over its own characters, so
> the same sweep crosses both at the same place.

**line 1839** — before `fx, fw = row[f_i][0], row[f_i][1]`

> Where the wipe is on the text underneath, not how far
> through the syllable's time: a syllable of 批判 with
> ひはん over 批判 and かい over 戒 lit every reading in
> it at once, wherever it sat along the characters.


### `Sweep.near`

**line 2084** — before `got = [ed for ed in self.edges if ed >= px]`

> Mirrored: the light comes from the right, so the ones behind a
> fragment are the ones at or right of its left edge.


### `Amll`

**line 2332** — before `ALIGN = 0.40`

> Where the focal line's middle sits when the window has no Line height.


### `Amll._focal`

**line 2565** — before `if self._sought is not None and self._sought >= n:`

> Both of these are line numbers kept from an earlier frame, and the
> earlier frame may have been a longer song: taken back unchecked
> they indexed past the new one's plan on every frame, and a window
> that cannot paint stays on the song it last drew.


### `Pinned`

**line 3198** — before `CREDIT_AFTER = 0.0`

> How long after the song's last word the credit appears. These renderers
> show where the voice IS, and a credit standing under the line being sung
> is a second thing to read for the length of the song -- so it waits for
> the end, which is where the stack puts it too: at the foot of the
> document, reached when the document is.


### `Spotlight.paint`

**line 3675** — before `if self.credits_due(pos):`

> Under the lowest line drawn, wherever that came out -- three lines
> of a couplet reach further down the window than three of a refrain --
> and only once the song is done with.


### `Word.paint`

**line 3901** — before `if self.credits_due(pos):`

> After the last word on screen -- the ad-lib under the word where
> there is one, the word itself where there is not -- and a beat after
> the last word of the song has finished; see CREDIT_AFTER.


### `Cards.paint`

**line 3968** — before `if -fm.height() * 8 < y < H + gap:`

> No card of its own: it is a paragraph about the document
> rather than a line of the song, and the stack puts it at the
> foot of the column exactly this way.


### `Spicy`

**line 4269** — before `stacked = False`

> Its own type and its own wrap, so the review marks cannot find the
> words where the window's layout says they are.

**line 4273** — before `SCALE = _Curve([(0, 0.95), (0.7, 1.0505), (1, 1)])`

> LyricsAnimator.ts

**line 4283** — before `Y_SPR = (1.45, 0.4)`

> Spicy's own springs while a syllable is sung. Once it is sung they are
> critically damped (see _Spr.settle): its ratios overshoot on the way
> back to finished, and a word wobbled as it settled.

**line 4296** — before `LETTER_MIN = 1.0`

> Emphasize.ts, IsLetterCapable.ts, lyrics.ts

**line 4298** — before `LETTER_TRIM = 0.25`

> Emphasize.ts ends a letter group, and its letters, a quarter second
> before the syllable.

**line 4304** — before `BLUR_STEP = 1.25`

> Shared.ts, Mixed.css

**line 4324** — before `LINE_GAP = 0.3`

> Between one line and the next, measured off Spicy: 0.3 of the type
> over and above the rows' own line-height.

**line 4330** — before `COOLDOWN = 0.75`

> ScrollToActiveLine.ts, LyricsVirtualizer.ts

**line 4334** — before `SCROLL_EASE = staticmethod(_bezier(0.42, 0.0, 0.58, 1.0))`

> Chromium's programmatic smooth scroll: ease-in-out, sqrt(delta)/60 s
> capped at a fifth of a second. Spicy's scroller is `scroll-behavior:
> smooth`, so this is the curve it is actually moved on.


### `Spicy._by_place`

**line 4451** — before `begun = lines[i].get("start") is None or lines[i]["start"] <= pos`

> A lead whose ad-lib comes in first sits above a line already
> started, but has not been sung: it waits, untouched.


### `Spicy.animate`

**line 4589** — before `for fr in frags[i]:`

> Not the one just sung: at rest, finished, from the
> first frame it is drawn, even if it was never sung or
> was left mid-swell by a seek.

**line 4598** — before `self._rest(fr, bool(lines[i].get("dots")))`

> Jumped over, never sung: finished as it stands.

**line 4608** — before `for fr in frags[i]:`

> Back to how it started, sung already or not.


### `Spicy.wheel`

**line 4701** — before `self.scroll_tw = None`

> A notch is 96px. Added straight to the column it jumped that far
> in one frame; it goes to a target the paint eases towards instead,
> and notches that land mid-glide add to where it is headed.


### `Spicy.font`

**line 4744** — before `try:`

> No ligatures: a held word is drawn a letter at a time, and an "fl"
> joined in one word and apart in the next set them differently.


### `Spicy.lay`

**line 4774** — before `own = (ln.get("pieces"), ln.get("pieces_roman"))`

> The pieces as well as the line: a romanisation arrives, or is
> retimed, by a new list on the same line, and keyed by the line
> alone the layout made before it stayed until the renderer was
> built again. The lists are kept with the entry so neither id can
> be handed to another list while it is cached.


### `Spicy.paint`

**line 4875** — before `a_, gs = self._dot_state(i, ln, states[i], pos, now)`

> Its full height, as the stack keeps it, unless Hide idle
> gaps is on: Spicy collapses a musical line it is not on,
> which moves every line under it as one opens or shuts, so
> it is the window's choice, eased as the stack eases it.
> The dots come and go either way.

**line 4894** — before `geom = (int(width), int(H))`

> The column is kept in pixels, so a new width or height leaves it
> wherever the old layout had the line: re-centre it at once, and
> hand the scroll back from the wheel, as the window's scroll does.

**line 4911** — before `self.sy += (self.wheel_to - self.sy) * (1.0 - math.exp(-dt * 24.0))`

> About 90% of the way in a tenth of a second, whatever the rate.

**line 4921** — before `rank, r_ = [], -1`

> Blur by how many LYRIC lines away, from the line the column is on.
> Background vocals sit with their lead and interlude lines are not
> counted: in the document they are entries of their own, and
> counting them put a whole step of blur between two lines that are
> next to each other on the screen.

**line 4947** — before `if i in self.op and states[i] is not None:`

> Unseen: no fade to watch, so it comes into view as it is.

**line 4973** — before `if dist > band + 1:`

> Focus lines: that many either side, one more as a hint.


### `Spicy.knob`

**line 5101** — before `def knob(self, name: str, default):`

> The window's own settings, each read so that the value the "Spicy
> Lyrics defaults" preset gives it is Spicy exactly: a multiplier of 1
> on Spicy's own number, or 0 for something Spicy does not do. Read
> through defaults because the stub views in the tests do not carry
> every knob the window does.


### `Spicy._glow`

**line 5233** — before `for step, share in ((lo, 1.0 - w), (lo + 1, w)):`

> The colour's alpha is clamped to 1 as CSS clamps rgba(), so a
> letter's 1.85 is full strength; only the Glow knob above 1 lays the
> halo down again. (Until 2026-10-28 the 1.85 was laid down twice.)


### `Spicy._active_line`

**line 5288** — before `self._glow(p, fr.core, font, fm, QPointF(bx, base), 6.0,`

> Glow every word: the voice's own light, left behind on
> every word it has reached.

**line 5305** — before `fill = lambda x, w, gp, d=rtl: self._fill(x, w, gp, a1, a2, d, sung)`

> The line's direction by default, but the romanisation under an
> Arabic line is Latin and passes its own: it fills left to right.


### `Spicy._shadow_line`

**line 5356** — before `pen = self._sung(ln) if st == "S" else QColor(255, 255, 255)`

> Opaque in the picture, the shadow's alpha on the blit: see _put
> for why translucent ink cannot be laid glyph by glyph.

**line 5361** — before `lvl = round(blur * 4) / 4`

> The text-shadow's own blur radius, to a quarter pixel so the
> pictures can be kept; see _gauss for why it goes in unchanged.

**line 5380** — before `hit = have[min(have, key=lambda k: abs(k - lvl))]`

> Out of pictures for this frame: every line in the window
> changes level on the same frame when the line being sung
> does, and building them all at once is a visible stall.
> The nearest level already made stands in until a later
> frame has room, which is a frame or two.

**line 5402** — before `pp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)`

> Words mid-settle are pictures under a scale: without this they
> land on whole pixels and a word easing to rest steps and shakes.


---

## Lift — 2026-09-17

### module level

**line 52** — before `TEXT = None`

> The two things these painters need from the window's own module. lyrics_gui
> fills them in where it imports this one. A plain `import lyrics_gui` here
> would load a SECOND copy of that module every time the window is started as a
> script -- which is how the .desktop file starts it -- so the dependency is
> handed over instead of reached for.

**line 60** — before `RISE_LEAD = 0.06`

> The rise sets off a little before the syllable does and is over shortly
> after it starts, so a syllable is already moving when it arrives rather
> than setting out once it is being sung. Held notes would otherwise climb
> for as long as they are held -- the rise took the whole of a word's length,
> so a note held four seconds rose for four seconds, which reads as drifting
> rather than as a lift.
>
> The lead was 0.18s, which is a fifth of a second of a word standing up
> before anything is sung: on a line of short words the whole line was in the
> air ahead of the voice. It is a HINT that the word is coming, not an
> announcement, so it is down to the width of one frame or two at the rates
> this draws at -- the movement still starts first, which is all it was for.
>
> It was worth finding out what a wider schedule looks like, and the answer is
> that it looks wrong. Cutting the window from the local word rate so that
> consecutive rises overlap does make the line move more continuously -- about
> half as many frames with nothing moving at all, measured over three
> documents at three tempos -- but what you get for that is two or three words
> off the floor at once, and a word standing up before it is sung reads as the
> line guessing ahead rather than as the voice lifting it. The rise belongs to
> the word being sung. It stays there.

**line 84** — before `STAYING = (0.0, None, 1.0)`

> What float_lifts hands back for a word that has not set off yet: on its
> baseline, at the size it was set in, and at whatever opacity the rest of
> the line is being drawn at -- which is what the None says, since only the
> caller knows whether that is the un-sung falloff or the activation.

**line 90** — before `MAX_BLUR = 9`

> The blurriest a distant line is allowed to get, and so the number of
> pictures one line can ever need. lyrics_gui reads it to know the range to
> look through when it is rationing builds -- see its _nearest_blur.


### `Renderer`

**line 100** — before `scrolls = True`

> False pins the lines: tick() then leaves view.scroll where it is instead
> of chasing the line being sung down the column.

**line 103** — before `stacked = False`

> Whether the column is laid out by view.layout_line at the window's own
> lyric font -- so the window can work out where any fragment of any line
> ended up without asking. Only the stack is: the pinned renderers choose
> their own sizes and lay their rows out themselves. What reads it is
> LyricsView._paint_review_marks, which draws under the words and cannot
> guess at their boxes; a renderer that answers False gets the marks in
> the margin and none in the text.

**line 111** — before `snap = False`

> Each word takes the sung colour whole at the moment it starts, rather
> than the fill sweeping through it. Only the stack has a use for this so
> far, but the fill is written once, in draw_row, and reads it from here.

**line 115** — before `SCALE_EPS = 5e-4`

> Nearer to full size than this is full size: a transform that moves the
> ink by less than half a thousandth costs a resample and shows nothing.
> Read by everything that has to decide whether a line_scale is worth
> applying, on both sides of the window. See scale_about.

**line 266** — before `NUDGE = 1.0 + 1e-7`

> Qt blits a pixmap onto whole device pixels while the transform is a
> plain translation, and resamples it the moment the transform is anything
> else. This is the smallest thing that is not a translation. It is not a
> trick to be tidied away: without it the picture lands on a whole pixel
> and the word steps instead of moving. See lifted_word.


### `Renderer.lifted_word`

**line 308** — before `m = max(3.0, fm.height() * 0.22)`

> Room for what hangs outside the advance -- a "j" reaches left of its
> origin, an "f" past the end of it -- and for the resample to have
> something to reach into rather than a hard edge.


### `Renderer.place_word`

**line 403** — before `parts = emph.parts`

> Each character goes where the WHOLE fragment would have put it, not
> where adding up the characters one at a time puts it.
>
> The two are not the same, and the difference is kerning. Drawing
> "even" in one go, the font pulls the pair after the "v" in by a
> pixel; drawing four separate characters and stepping by each one's
> own advance, it does not. So the moment a word starts being
> emphasised -- which is the moment it stops being drawn in one piece
> -- its later letters jump sideways, and they jump back when the
> emphasis ends. Measured over five documents: 19 of 104 emphasised
> words move a letter this way, by up to 3.7px.
>
> Asking the metrics for the width of the text BEFORE each character
> is asking for the shaped position, kerning and all, so the letters
> sit exactly where they sat a frame earlier and the only thing that
> moves them is the swell.
> Drawn in ONE piece, not character by character.
>
> Character by character is how AMLL does it, and it cannot be made
> safe at this type size. Measured on the real window at the settings
> this is used at, the ink gaps INSIDE a word are one to two pixels.
> Every per-character path then closes them: each character is floored
> onto the pixel grid on its own, scaled about its own centre on its
> own, and haloed on its own. A word with six letters came out as two
> runs of ink while it was held -- letters welded into blocks -- and
> every arrangement of slots, kerning and halo strength that was tried
> moved the problem around without fixing it, because a one pixel gap
> has nothing to give.
>
> So the swell is applied to the fragment as a whole: one scale about
> its own centre, one float, one string handed to lifted_word exactly
> as an un-emphasised word is. The gaps are then whatever the font
> laid out, scaled -- they cannot close, because nothing is positioned
> independently any more.
>
> What that costs is the per-character wave, which is the part of
> AMLL's emphasis that needs room this face does not have between its
> letters. What survives is the swell and the light, on the word.


### `Renderer.emph_glow`

**line 469** — before `radius = max(1, round(self.glow_of(ch, fm, emph.held)[0]`

> Sized for THIS character, not for the word it is part of,
> and then taken in by HALO_SIZE.


### `Renderer._paint_dots`

**line 551** — before `p.save()`

> Saved, not put back by hand at the end. This used to set NoPen and
> restore only the BRUSH, so the pen leaked into the rest of the
> frame: measured, a drawText straight after a line of dots put zero
> ink on the screen. The art panel survived it by luck -- it sets its
> own pen before every draw -- and a paint fault here is silent, so
> what it would have looked like is the window losing everything
> drawn after the dots.

**line 564** — on `                continue`

> this one has gone


### `Flow.__init__`

**line 616** — before `self._rk = self._rects = None`

> What `rects` last handed back, and what it was built for.

**line 619** — before `self._warm_at: int | None = None`

> Which line _warm_next is building ahead for, and whether it has
> finished. See _warm_next.


### `Flow`

**line 624** — before `HALO = True`

> Whether an ordinary word gets a halo behind it while it is being sung.
> The stack lights every word held longer than a moment. AMLL lights only
> the ones it has decided are being PERFORMED -- see Amll.emphasised --
> and gives the rest no shadow at all, which is most of what makes its
> held notes stand out: there is nothing else lit to compete with them.

**line 630** — before `HALO_SCALE = 1.0`

> How strongly a held word's own light is laid on, and how far it spreads.
> 1.0 is what glow_of asks for.

**line 635** — before `ALL_GLOW_SPREAD = 2`

> The light behind the words the voice has been through -- see all_glow,
> and `word_glow` for whether it is on at all. How many blur levels wider
> than the line's own picture the light is cut, and how brightly it is
> added at the line's full activation.
>
> Two levels, not three. `line_pixmap` blurs by shrinking the picture
> through a mip chain by (1 + level), so the spread is about how far the
> light carries from the letters: three levels is a quarter-size wash that
> pools in the gaps between words and reads as fog over the line, and one
> is so tight it barely leaves the ink. Two hugs the letters and falls off
> inside half their height, which is the bloom a glow actually looks like.
> It is also well inside MAX_BLUR from a focused line, so the level asked
> for is one the cache already keeps a family member at and the ration
> already knows how to stand in for -- see _warm_next, which builds it
> ahead with the rest.

**line 653** — before `ALL_GLOW_PAST = 0.4`

> What a word the voice has left behind keeps, against the word in the
> mouth, and how far back the one comes down to the other -- in line
> heights, so the type takes it along the way everything else here does.
>
> Under half. The point of this is that sung words go on glowing, but if
> they glow as hard as the word being sung then the brightest thing in the
> window is whichever part of the line has the most ink in it, and there
> is nothing for the eye to follow. Kept as a trail rather than a step at
> the word boundary: a step is a seam standing still in the middle of a
> line, and this is meant to read as a light being carried.

**line 665** — before `TRAIL_STEPS = 7`

> How many blits the trail is stepped across. It is a slow gradient over a
> couple of line heights, so it takes far fewer than the edge does.

**line 669** — before `def emph_plan(self, rows, pos: float, fm: QFontMetricsF,`

> -- the fill, as three decisions a subclass can take differently ----
>
> Pulled out of _paint_line rather than left inline because the amll
> column fills a line by a different rule and the rest of that method --
> the rise, the pop, the glow, the ruby, the readings -- is the same
> either way. What is a per-word question here is a per-row one there.


### `Flow.paint`

**line 797** — before `m = H if (v.zero_g > 0 or v.clouds > 0) else 40`

> One margin and one cloud test for the frame, not one of each per line.


### `Flow`

**line 818** — before `WARM_REACH = 5`

> How far from the line being sung a picture is still worth building
> ahead. Beyond this the blur has saturated -- 1.4 * 4**1.35 is already
> over MAX_BLUR -- so every line out here shares one level and has had it
> since the last switch. Nothing to warm.


### `Flow._warm_next`

**line 865** — on `                return`

> more to do; come back next frame

**line 866** — before `ln = v.lines[i]`

> Only the rows _paint_line actually BLITS. It hands a credits
> block to _paint_credits and an interlude to _paint_dots, both
> before the pixmap path, and neither of them has a picture --
> layout_line gives a credits row (n, text) pairs rather than the
> (x, advance, text, start, end) line_pixmap unpacks, and gives an
> interlude no rows at all. Asking for one raised straight out of
> paintEvent, which loses the whole frame AFTER the lyrics: the
> art panel, the toast and any overlay simply never got drawn.

**line 878** — before `if v.focus and self.focus_trim(dist) is None:`

> The same window _paint_line draws, so nothing is built for a
> line that will not be on screen to want it.

**line 888** — before `if v.word_glow > 0 and v._pix_left > 0:`

> The glow is another member of the same family -- the same line
> at a wider level, in the sung colour instead of the base ink --
> wanted on the same frames and missing from the cache for the
> same reason. Warmed here so turning it on does not double the
> burst a switch pays. See all_glow.

**line 896** — before `self._warm_done = v._pix_left > 0 or v._pix_left == had`

> The loop ran to the end, so every line in range was asked for and
> there is nothing to come back for. The one thing that can still be
> outstanding is the second level on the very last line, skipped
> because the ration ran out exactly there -- which reads as no ration
> left and something built, and is the one case that runs again.


### `Flow.float_of`

**line 943** — before `t = min(1.0, (pos - at) / self.float_span())`

> Clamped rather than short-circuited at the far end, so what comes
> back never goes backwards: a word long gone reads as all the way up
> with nothing left, and not as back on its baseline. Nothing draws it
> either way -- the caller is gone at zero -- but a lift that falls to
> zero at the end of the flight is a trap for the next thing that asks.

**line 949** — before `unit = self.v.lyric_fm(False).height()`

> It goes faster the higher it gets, and it is transparent long before
> it is far: at half gone it has travelled a third of the distance,
> which is what letting go of something looks like from underneath --
> a thing that is thrown starts fast and slows, and this does not.
>
> The distance is measured off the MAIN lyric font rather than the
> line's own, the way word_lifts measures the rise, so an ad-lib set
> at two thirds the size does not float two thirds as far.
>
> And it grows on the way, on the same curve as the climb, so that the
> word reads as coming AT the reader rather than receding: a thing
> going away gets smaller, and a word that shrank as it faded would be
> leaving through the back of the window instead of over your head.
> Half faded it is half again as big, which is as far as this can go
> before a word passing the line above it is wearing it.


### `Flow`

**line 967** — before `DOT_STAGGER = 0.34`

> How far apart the three dots let go, as a share of one flight. A third
> of a flight: enough that they leave in a countable order rather than as
> one object coming apart, and not so much that the first one is halfway
> up the window before the last has moved.


### `Flow.dot_flights`

**line 991** — before `start = ln.get("start")`

> The last dot's flight ends on the line's first word; the ones before
> it set off a stagger earlier each, and none of them before the break
> itself has started -- a gap shorter than the whole departure lets
> them all go at once rather than going back in time to do it.


### `Flow.float_lifts`

**line 1029** — before `flight = self.float_of(s if s is not None else start, pos)`

> A fragment with no clock of its own leaves with the line
> it is part of, rather than sitting there for ever after
> everything round it has gone.


### `Flow.all_glow`

**line 1205** — before `lit = [self.sung_edge(row, pos) for row in rows]`

> Where the light reaches on each row, and the band of the picture
> that row owns.
>
> The bands meet at the row BOXES and not midway between the
> baselines. Midway looks like the fair answer and is not: a row's box
> is its ascent and its reading above it, which reaches a good deal
> further up than half the gap, so the seam fell inside the next row's
> capitals and lit the tops of words the voice had not got to. See
> sung_edge -- the whole point of this is that nothing ahead of the
> voice is lit, and a seam is no excuse.
>
> So a band starts where its row's box starts and ends where the next
> one's does. The first runs up to the top of the picture, which is
> the padding the first row's own light spills into. The last runs to
> the bottom for the same reason -- unless there are romaji under it,
> which are their own words at their own widths and have no business
> being lit by the row above.

**line 1243** — before `self._glow_strip(p, at, pm, 0.0, float(pm.width()), top, bot, past)`

> A row the voice has finished with. All of it is behind, so
> all of it is at the settled level -- the trail below is
> measured from where the voice IS, and it is not on this row.

**line 1248** — before `self._glow_strip(p, at, pm, 0.0, pad + edge - trail, top, bot, past)`

> The row the light is on. Three pieces, left to right: everything
> well behind the voice at the settled level, a trail coming up to
> full across the last line-height and a half, and the soft edge
> the voice itself is standing on.
>
> The trail is what makes it a light being CARRIED rather than a
> line that has been switched on. Words already sung keep a glow,
> because that is the point of this, but they keep less of one
> than the word in the mouth -- otherwise the brightest thing in
> the window is wherever the line happens to be longest, and the
> eye has nothing to follow.
>
> All of it drawn as narrow blits with the opacity stepping across
> them rather than by masking the picture through a gradient. A
> gradient cannot be applied to a pixmap without an off-screen
> copy, which is a full-size allocation and three more passes over
> every pixel of the line, every frame. The strips are clipped, so
> they share out the row's pixels rather than each paying for them
> -- twenty of them cost about what one blit of the row does.


### `Flow.draw_base`

**line 1347** — before `flew, left, big = gone.get(`

> A reading goes wherever the kanji under it goes, grows
> with it and fades with it. See ruby_lift: the same
> argument, and the same answer.

**line 1363** — before `if spin is not None and (r_i, x) == (spin[0], spin[1]):`

> The word being spun draws its own base, turned; a second
> copy sitting still underneath it is the thing the old clip
> was cutting away.

**line 1374** — before `self.place_word(p, QPointF(ox + x, gy), txt, lift, fm, big,`

> The centre a growing word turns about is where the word
> actually IS, which is the lift's business: scaling about the
> baseline it left behind would throw it further up the window
> the bigger it got. Nothing noticed while the only thing that
> scaled was the pop, two pixels off its own line.


### `Flow._paint_line`

**line 1676** — before `peek = self.v.focus_idx`

> The line the column has SCROLLED TO counts as near, as well as the
> line being sung. With `scroll_lead` set -- and it is set by default
> -- the two are different for the third of a second before a line
> starts: the column has already moved down to it, so it is sitting at
> the anchor being read, and it was still being drawn blurred because
> nobody was singing it yet. Whatever the reader is looking at is
> what should be sharp.

**line 1702** — before `y = y + (1.0 - act) * 7.0 * self.v.line_drop * (1 if idx in live else 0)`

> The line's own entrance: it lands seven pixels low the frame its
> first word starts and rides the activation back up to where the plan
> put it. The drop is a STEP -- a line not yet sounding is drawn at its
> place, and joining `live` moves it -- so what the eye gets is the
> line being knocked down and recovering, not sliding in from below.
> That is the effect, and `line_drop` scales it; at 0 the line simply
> lights up where it already was.

**line 1727** — before `gone = {}`

> Troll: every syllable lifts off and fades from the moment the voice
> reaches it, so a line comes apart in the order it is being sung
> rather than going up as a slab. What is settled here is only which
> words have left and how far; draw_base and the fill below put them
> where that says, between them drawing the un-sung half of a word and
> the sung half at the same height.
>
> Below the clouds and zero-g on purpose. Both of those already have
> the words off the line and moving on their own account, and two sets
> of arithmetic arguing over where one word is is not a third effect.

**line 1739** — before `last = self.float_of(ln.get("end") or ln.get("start"), pos)`

> Nothing in the line sets off later than the line's own end, so
> once THAT flight is over every word in it has gone and there is
> nothing here to draw at all. One comparison to find that out,
> before the scan below walks the fragments: it is the answer for
> every line the song has already passed, which by the end of a
> play is most of the document.

**line 1751** — before `emphs = (self.emph_plan(rows, pos, fm, ln["background"])`

> Once for the line: the un-sung layer below and the fill over it must
> agree to the pixel about where every character of a held word is.

**line 1755** — before `own_text = ((self.v.rise > 0 and act > 0.01 and blur < 1.0)`

> Whether the line draws its own text is decided by whether the rise
> can reach it at all, not by whether anything has lifted YET: live
> text and a blitted pixmap do not rasterise quite alike, and switching
> between them at the moment the first word sets off puts a visible
> change of weight in the middle of a line. Switching when the line
> activates hides it under the fade that is happening anyway.
>
> A line with a word in the air cannot use a picture either, and for
> the same reason the rise cannot: every word in a pixmap is on the
> baseline. That half is not gated on the activation, unlike the rise
> -- a line whose last word left as the next line started is still in
> the air well after its activation has eased away to nothing.
> A line with a word coming apart into its characters cannot use its
> cached picture either, and for the same reason the rise cannot:
> every word in that picture is one piece, on the baseline.

**line 1806** — before `gy = self.on_grid(ry)`

> The same rounding draw_base does, because the fill goes over the
> text draw_base drew and the two cannot disagree about where the
> row is. See lifted_word: a baseline on the grid is what lets a
> word that is not moving be glyphs instead of a picture.

**line 1836** — before `flew, left, big = gone.get((False, r_i, f_i), STAYING)`

> How far this word has floated off, and what it is being
> drawn at: its own remaining opacity if it has left, and the
> line's activation if it is still in place. A word on its way
> out is lit at the brightness it was sung at and fades from
> there -- it does not drop to the un-sung falloff the instant
> it leaves, which is a flicker in the middle of the line.

**line 1850** — before `rise = lifted.get((r_i, f_i), 0.0) + flew`

> Both of the vertical moves this fragment is about to make,
> worked out before anything is drawn: the glow is painted
> first and has to be put where the word is GOING to be, not
> where its baseline is. A halo drawn at the baseline sat in
> the hole a lifted word had just climbed out of -- the word
> up in the air with its own light left on the floor beneath
> it, which is the one thing a halo must never do.

**line 1860** — before `self.emph_glow(p, emph, QPointF(px, gy), font, fm,`

> The word is being held, and its swell replaces the pop
> and the one halo cut for the whole word outright rather
> than layering under them.

**line 1876** — before `poplift = popk * self.v.pop * fm.height() * 0.055`

> Left fractional, like the rise: lifted_word places the
> word where this actually says rather than on the nearest row
> of pixels, and the glow below is given the very same number,
> so the halo cannot cross a boundary half a frame before the
> letters it belongs to.

**line 1889** — before `grow = (1.0 + 0.38 * swell * strength) * big`

> `big` as well: a word being sung is also a word on its
> way out under the float troll, and a halo that stayed
> its own size while the word grew through it would be a
> light sitting inside the letters instead of behind them.

**line 1907** — before `wcx, wcy = px + w * 0.5, gy - fm.ascent() * 0.35`

> draw_base has already put this word's un-sung self at the
> same height; the fill goes over it. Neither of them puts the
> lift on the painter any more -- lifted_word places the word
> itself, because a translation is exactly what Qt rounds away.

**line 1915** — before `if rise or poplift:`

> The spun word turns about its own centre, and a rotation
> is a transform on the painter whatever else is going on,
> so its lift rides along on that rather than through
> lifted_word. It is already being resampled.

**line 1936** — before `self.lifted_word(p, QPointF(px, gy), txt, rise + poplift,`

> The centre follows the word up. See draw_base, which
> draws the un-sung half of this same word at the same
> place and has to agree with it to the pixel.


### module level

**line 2001** — before `def _bezier(x1: float, y1: float, x2: float, y2: float):`

> -- AMLL's emphasis, and the easings it is cut with ----------------------
>
> Ported from applemusic-like-lyrics,
> packages/core/src/lyric-player/dom/animation/{emphasize,float}/index.ts.
>
> The stack's own swell -- the pop and the glow -- is one movement per WORD:
> the whole word grows and lights on a sine through its own span. AMLL's is
> per CHARACTER, and it is three movements at once, each on its own clock:
>
>   * the letters grow, and push APART from the middle of the word, so a held
>     word opens out rather than simply getting bigger;
>   * each letter floats up and back down on a sine, starting 400ms before its
>     own glow and running 1.4 times as long;
>   * the glow swells and dies on a two-piece bezier that is not symmetric --
>     it comes up faster than it goes away.
>
> and each letter is started a little after the one before it, so the movement
> travels through the word instead of happening to all of it at once. That
> stagger is the reason it is worth having per character at all.

**line 2067** — before `_BEZ_IN = _bezier(0.2, 0.4, 0.58, 1.0)`

> The two halves of the emphasis envelope. It is deliberately lopsided: the
> light arrives on one curve and leaves on another, so the word does not
> simply breathe in and out symmetrically.

**line 2072** — before `_EASE_OUT = _bezier(0.0, 0.0, 0.58, 1.0)`

> CSS `ease-out`, which is what a word's ordinary float is cut with.

**line 2085** — before `_CJK = re.compile(r"[぀-ヿ⺀-⿟㐀-䶿一-鿿]")`

> The ranges spicy_lyrics.CJK covers, kept here rather than imported so that
> this module goes on depending on nothing but Qt. If that one moves, this is
> the other place to look.

**line 2090** — before `_EM = 0.83`

> A line's height is not its em. 0.05em is AMLL's float distance and this is
> what that comes to as a fraction of QFontMetricsF.height(), which carries
> the leading as well.


### `Emph.__init__`

**line 2145** — before `self.parts, self.radius, self.held = parts, radius, held`

> `radius` is the halo the WORD would take; `held` is how long the
> note is, which is what a halo for one CHARACTER has to be worked out
> from. See emph_glow: a blur cut for a six letter word is two and a
> half times what a single letter wants, and drawing that on each
> letter is how a held word ended up wearing a haze.


### module level

**line 2156** — before `def _solve_spring(frm: float, vel: float, to: float, mass: float,`

> -- springs, for the renderer below ---------------------------------------
>
> Ported from applemusic-like-lyrics, packages/core/src/utils/spring.ts and
> packages/core/src/lyric-player/base/spring.ts.
>
> The thing worth taking is that the spring is SOLVED rather than stepped. A
> stepped spring integrates a velocity once per frame, so its path depends on
> how the frames fell -- a dropped frame is a different curve, and a window
> that was hidden for a second comes back somewhere else entirely. This one
> has a closed form for position at time t, so the frames only decide where it
> is SAMPLED. Two machines drawing at 60 and at 144 draw the same movement.


### `Spring`

**line 2210** — before `H = 1e-3`

> The step either side used to read a speed off the solved curve. AMLL's
> derivative.ts, which does the same thing for the same reason: the closed
> form gives a position and re-aiming needs a velocity.


### `Spring.__init__`

**line 2219** — on `        self._f = None`

> None: sitting on the target

**line 2220** — on `        self._queued = None`

> (seconds to wait, where to go)


### `Spring.arrived`

**line 2268** — on `            return True`

> the cheap answer, and the common one


### `Spring.set_target`

**line 2292** — before `if self._queued is not None:`

> Saying again what has already been said does not restart the
> wait. The renderer re-states every line's aim on every frame --
> it has no cheap way to know the aim did not move -- and a wait
> re-armed each frame is a wait that never comes round, which is a
> line that never sets off at all. What the caller means by a
> delay is "be there after this long", not "start counting again".


### module level

**line 2329** — before `_SLOW = (90.0, 15.0)`

> How the column is carried, by the gap between the line being sung and the one
> before it. AMLL's getPosYSpringPolicy, numbers and all.
>
> What this buys is a column that moves at the song's rate without being told
> what that is: a patter verse whose lines are a fifth of a second apart is
> carried stiffly enough to keep up, and a ballad with four seconds between
> lines is carried gently, because a stiff spring over a long gap arrives and
> then sits waiting, which reads as the column twitching between lines.

**line 2337** — on `_SLOW = (90.0, 15.0)`

> seeks and interludes


### `_spring_policy`

**line 2347** — before `ratio = (1.0 - (g - _MIN_GAP) / (_MAX_GAP - _MIN_GAP)) ** _GAP_EXP`

> Fifth root, so the mapping leans towards the fast end rather than
> sitting in the middle of the range for most of it.


### `Amll`

**line 2384** — before `HALO = False`

> Only a word this renderer has decided is being held lights up, and it
> lights per character. See Flow.HALO and Amll.emph_of.

**line 2387** — before `HALO_SCALE = 1.0`

> How strongly a held word's own light is laid on.
>
> This was turned down to a quarter for a while, to stop the light from
> bridging the gap between two letters and welding them. That was the
> wrong culprit, found with a measurement that could not tell a letter the
> fill had not lit yet from a letter that had merged with its neighbour.
> What was actually welding them was the word GROWING -- see SWELL.
>
> With the growing gone the letters no longer move, so the gaps can be
> measured where they actually are. At full strength the dimmest point
> between two letters still sits 54% below the letters themselves, over
> every emphasised word in a chorus. There is nothing here to turn down.

**line 2400** — before `HALO_SIZE = 1.0`

> How much a held word grows. 0 keeps the letters exactly as the font laid
> them out, which is the only thing that holds at a one pixel gap; see the
> note by `word_scale` in emph_of.
> How far a held word's light spreads, against what glow_of asks for.
>
> 1.0, because the shrinking that was wanted had already happened. The
> halo used to be sized from the whole WORD's width and then drawn on each
> letter -- eleven pixels of blur on a single character instead of four --
> which is what read as a huge glow. Sizing it per character fixed that;
> taking it in by half on top left about two pixels, which is barely a
> glow at all. This is the knob if it wants adjusting, but the fault was
> the wrong unit, not the amount.

**line 2414** — before `BOB = 0.0`

> How much each character bobs on its own while the word is held. Off for
> the same reason SWELL is; see the note by the parts built in emph_of.

**line 2418** — before `ALIGN = 0.35`

> Where the line being sung is held down the window: AMLL's alignPosition,
> against its centre anchor, so it is the line's MIDDLE that lands here and
> a couplet that wraps to three rows does not sit lower than a short one.

**line 2422** — before `SCALE = 0.97`

> What a line that is NOT being sung is drawn at -- AMLL's SCALE_ASPECT.
> The way round is worth noticing: the sung line stays its own size and
> everything else shrinks a little, so the line being sung is never bigger
> than the type the document was set in. Against its neighbours it still
> reads as growing, and `scales` springs each line between the two, so it
> grows over about the length of a word rather than snapping.
>
> This was 1.0 for a while, which turned the whole cue off, over two
> objections that are both answered now:
>
>   * The review marks. `stacked` used to answer False for anything
>     scaled, which sent the marks to the margin for as long as this
>     renderer was in use. But the layout never stopped being the
>     window's -- only the painter was transformed -- so the answer is to
>     publish the transform, not to disown the layout. See `line_scale`,
>     which _paint_review_marks now puts the boxes through.
>   * Resampling. A painter under any transform resamples, so a scaled
>     line is a slightly soft line. That is true and it is the price;
>     what makes it payable is that it is never charged on a line
>     anybody is reading sharp. The line being sung and its neighbours
>     are lit, and lit lines are held at 1.0 and never see a transform;
>     a hand on the wheel takes the column to full size for as long as it
>     is there (see `browse` below); and a stopped song is all 1.0. What
>     is left is the un-sung depth of a playing column, which the stack
>     has already blurred and faded.

**line 2448** — before `STAGGER = 0.05`

> The stagger. Each line down the column sets off this much later than the
> one above it, and below the line being sung the spacing tightens by
> DECAY per line, so the wave gathers as it goes rather than spreading.

**line 2453** — before `MAX_STEP = 0.10`

> A step longer than this is a window that was hidden, not a slow frame.
> Handing it to the springs whole runs most of a second of travel between
> two drawn frames, which is a column that teleports on being shown again.

**line 2457** — before `FADE = 0.25`

> Half the width of the light that travels along a row, as a fraction of
> the line's height -- so the band itself is 0.5 of it, which is AMLL's
> wordFadeWidth default. Scaled by the window's own `edge` knob, which
> goes on meaning the same thing it means everywhere else.

**line 2462** — before `JITTER = 0.15`

> Telling a seek from playback, which is AMLL's SeekDetector and its
> numbers. The idea is to stop guessing at a threshold and compare the
> MEDIA clock's advance against what the wall clock says it should have
> been: playing, it should have moved by the frame time; paused, not at
> all. Anything else is a jump.
>
> A fixed threshold could not do this. At 1.5 seconds it missed a click on
> a line a beat away -- which reads as ordinary playback by size alone,
> and is nothing of the kind -- and any threshold small enough to catch
> that would have fired on the clock's own slew.
>
> Springs go to the slow parameters across a seek and the stagger is
> dropped: a drag along the progress bar moves the focal line every frame,
> and a wave started on each of them is a column that never settles.

**line 2476** — on `    JITTER = 0.15`

> what the clock may be out by regardless

**line 2477** — on `    DRIFT = 0.5`

> ...plus this share of the expected advance

**line 2478** — on `    UNTRUSTED = 0.8`

> a frame longer than this proves nothing


### `Amll.__init__`

**line 2488** — before `self.offset = 0.0`

> How far the reader has pushed the column away from where the song
> would have put it, and the range that is allowed to be. AMLL's
> scrollOffset, and the bounds its beginFrame works out every frame.

**line 2493** — before `self._sought = None`

> The line a click asked for, held until the song's own answer reaches
> it. See _focal.

**line 2496** — before `self._focal_was = None`

> The last focus worth believing, and how many frames running the
> clock has claimed to be before the song started. See _focal.

**line 2500** — before `self._jolt = False`

> Set whenever the column is moved by the reader rather than by the
> song, which is one of the cases the stagger must not be used for.
> See the note above `spacing` in paint.

**line 2504** — before `self._last_top = None`

> Where the column was aimed last frame, so this one can tell which
> way it is about to move and how far.

**line 2507** — before `self._held = None`

> The line the column was built around when the reader took the
> wheel. AMLL's FocusController freezes it for as long as they are
> reading, so the song does not slide the column out from under them.

**line 2511** — before `self.now = mono`

> The wall clock the springs are stepped by, held rather than reached
> for so that a test can drive a frame at a time. Nothing else moves
> them: the song's own clock says WHERE the column should be, and this
> says how long it has had to get there.


### `Amll`

**line 2517** — before `def line_scale(self, i: int) -> float:`

> Inherited from Flow, and true: the column is laid out by
> view.layout_line at the window's own lyric size, which is the question
> `stacked` asks. It used to answer False here on the grounds that SCALE
> moves the ink, but that is a fact about the PAINTER, and the answer to
> it is `line_scale` rather than giving up the layout. See SCALE.


### `Amll._rebase`

**line 2610** — before `hold = self.ys[-1].value`

> Same song, different number of lines -- a marker inserted, a
> split changed. Make the lists fit and leave the column alone:
> anything new starts where the line above it already is, so
> nothing flies in and nothing jumps.


### `Amll._seeking`

**line 2651** — before `return False`

> The window was away. Nothing can be told from this frame, so
> nothing is claimed -- the baseline above is all it is good for.


### `Amll._focal`

**line 2686** — before `if seeking:`

> A click is authoritative and immediate: the reader pointed at a
> line, and that is where the column goes.

**line 2692** — on `                self._sought = None`

> the song has caught up

**line 2698** — before `if self._focal_was is not None and i < self._focal_was - 1:`

> Otherwise, a clock that has momentarily lost its place must not move
> the column. A seek is a round trip to the player, and until it
> answers, the position can read as something from before it. Taken at
> face value that is the song being somewhere else entirely, so
> clicking a line could send the whole column up the document and then
> bring it back down -- two moves, the first one to nowhere.
>
> What tells the two apart is not WHERE the answer is but whether it
> lasts: a reading that was never true is replaced a frame or two
> later, and a real one keeps saying the same thing. So a jump
> backwards that nothing asked for is held for three frames before it
> is believed. A genuine one still arrives, fifty milliseconds late,
> which is nothing; a phantom is gone before it can move anything.


### `Amll`

**line 2720** — before `CLICK_SNAP = 0.05`

> How near a seek has to land to a line's start to count as a click on it.

**line 2745** — before `def _fade(self, fm: QFontMetricsF) -> float:`

> -- one light, travelling along the row -----------------------------
>
> The stack fills a word from the word's own clock: the boundary is at
> `frac` of the way through THIS word, and the soft edge either side of it
> is drawn only on this word, because this is the only word being drawn
> with a gradient. Everything to its left is solid and everything to its
> right has not been drawn at all.
>
> That is not what AMLL does, and the difference is the soft edge. There
> the mask is one gradient per row in the ROW's own coordinates, so the
> band is a light of real width -- half a line height -- travelling along
> the row, and when it straddles a syllable boundary it lights the tail of
> one word and the head of the next at the same time. Cut at every
> boundary, as the stack cuts it, a band that wide is a band that is
> almost never drawn whole: on syllable-timed text it is truncated several
> times a word.
>
> So the position is worked out once for the row and every fragment near
> it is drawn with the same gradient, in the same coordinates. Where the
> light is between two words -- a gap in the timing, a held breath -- it
> sits still at the end of the last word sung, which is AMLL's pause
> segment and the reason the sweep does not run ahead of the voice.


### `Amll.fill_shows`

**line 2811** — before `if frac > 0:`

> Its own clock says it is lit, whatever the rest of the row is doing.
> This is what keeps a word being sung across another one drawn: the
> nearest light may well be the other voice's.

**line 2816** — before `soft = self._fade(fm)`

> A word the voice has not reached has ink only where a light BEHIND
> it spills onto it, and `Sweep.near` is what decides that a light is
> behind it.
>
> Asking only whether it lies left of the light was the first bug.
> With one voice nothing unstarted ever does, so it never showed; with
> two, a word waiting for the second voice sits well to the left of the
> first voice's light, passed that test, and was then drawn solid for
> being "behind" a light that was never coming for it. Measured over
> four lines that have words sung across each other, a word that had
> not started was drawn fully sung in 679 frames out of 680.
>
> Asking whether the band reached it from EITHER side was the second,
> and it is the same fault a hair's breadth narrower. The band is a
> TRAILING fill -- sung behind the light, clear in front of it -- so a
> light two pixels past a word's last letter leaves every letter of it
> behind the light, and a gradient PADS: the word is painted as solidly
> as one being performed. What it looks like is a word lighting up for
> the two or three frames it takes the other voice to move on.
>
> With the light in front of a word dropped where it is chosen, all
> this has left to ask is the other end: whether the band reaches
> FORWARD far enough to touch a word the light has yet to arrive at.


### `Amll.fill_pen`

**line 2834** — before `if frac >= 1.0:`

> Sung is sung. Nothing else in the row may un-sing it.
>
> This used to ask the nearest light instead, and where two voices
> share a row the nearest light moves: a word finished by the first
> voice would find the second voice's light closer, get that light's
> gradient, and go back to being half unlit. On screen the line looks
> like it re-ran its own sync from the middle.

**line 2843** — before `if frac > 0.0:`

> Part way through: its OWN light, not the row's nearest. With one
> voice these are the same thing -- the row's light IS this word's --
> so the only case they differ is the one that was going wrong.

**line 2849** — before `ed = sweep.near(px, w)`

> Not started: the only light that can reach it is a neighbour's,
> which is what lets the soft edge cross a word boundary. It is
> never solid -- nothing the voice has not reached is fully sung,
> whatever is lit elsewhere in the row. Which is why the clear
> colour is an answer this has to be able to give: `Sweep.near`
> hands back nothing at all when every light in the row is in
> front of this word, and a pen of the sung colour at no alpha
> draws exactly the nothing that deserves.


### `Amll`

**line 2860** — before `EMP_MIN = 1.0`

> -- the swell, AMLL's way -------------------------------------------

**line 2862** — on `    EMP_MIN = 1.0`

> a word held this long is worth emphasising

**line 2863** — on `    EMP_CHARS = 7`

> ...and that second buys this many letters. A longer word is not shut
> out, it is asked to be held for proportionally longer -- see
> `Amll.emphasised`, where the ceiling this used to be is argued into a
> rate. Unless it is CJK, which is exempt from both readings.

**line 2864** — before `FLOAT_MIN = RISE_TIME`

> The shortest a float is allowed to take, which is the one number here
> that is deliberately NOT AMLL's.
>
> AMLL floats a word over max(1s, its length). The 1s floor is written for
> word-timed lyrics, where a word often lasts about that. Against
> syllable-timed text it is the wrong floor by a factor of four -- the
> median syllable across three documents here is 0.22 to 0.26s -- so every
> ordinary syllable was caught a quarter of the way up its climb and the
> `rise` knob read at about a THIRD of what the same number gives in the
> stack: measured 0.35, 0.36 and 0.46 of it on Poker Face, Time and
> Clocks. A setting shared with every other renderer cannot mean a
> different amount here.
>
> Lowered to the stack's own RISE_TIME, which is its answer to the same
> question. That brings the three documents to 0.84, 0.82 and 0.75 of the
> stack, and it costs nothing that makes AMLL's float what it is: the
> floor only ever binds on syllables SHORTER than it, so a held note is
> untouched -- a three second note still climbs for the whole three
> seconds, reaching the same 1.6, 4.1 and 6.0 pixels at 0.5s, 1.5s and 3s
> whatever this is set to. Put it back to 1.0 for AMLL's own number.

**line 2885** — before `EMP_LEAD = RISE_LEAD`

> How early a character's float sets off ahead of its own glow. AMLL says
> 400ms; this says RISE_LEAD, and the argument is already written down at
> the top of this file.
>
> At 0.4s the swell does not start early within a word, it starts during
> the WORD BEFORE. Measured on a held word following a short one: every
> one of its six characters was already moving 0.30 to 0.38s before the
> word began, which is to say the whole of it was in the air while the
> previous word was still being sung -- and the letter that shows it worst
> is whichever one opens the held syllable, because that is the part of
> the word the voice has not reached at all.
>
> RISE_LEAD's note records this same finding for the stack's own rise and
> settles it: a lead of 0.18s was already judged too much, because "a word
> standing up before it is sung reads as the line guessing ahead rather
> than as the voice lifting it", and it came down to one or two frames --
> enough that the movement still starts first, which is all a lead is for.
> That answer applies here unchanged; 0.4s is more than twice the value it
> rejected. AMLL can afford it because a word there is one timed unit and
> its neighbours are words, not syllables of the same word.

**line 2906** — before `SETTLE = 0.25`

> How long after the note the last character is still settling. See span.

**line 2908** — before `CHAR_STEP = RISE_LEAD`

> How far apart the characters of one SYLLABLE set off. A couple of
> frames -- enough to read as a wave, never enough to pretend the voice
> has moved through a held note. See the note by `arrive` in emph_plan.

**line 2912** — before `RISE = 0.055`

> How far a word floats, as a fraction of the line height.
>
> AMLL says 0.05em and the stack says 0.055 line-heights, which are the
> same intent in different units -- but the window's `rise` knob is
> calibrated against the STACK's, and converting the em honestly came out
> at three quarters of it. The knob then meant something quieter here than
> everywhere else in the window, which is the one thing a shared setting
> must not do. So the distance is the stack's and the SCHEDULE is AMLL's,
> which is the half that actually differs. See word_lifts.


### `Amll.emph_plan`

**line 3008** — before `arrive = []`

> When the voice actually reaches each character, read off
> the syllable it belongs to rather than assumed even across
> the word. See emph_of.
> When the voice reaches each character.
>
> A SYLLABLE is the smallest thing the voice actually moves
> between, so its start is when all of its characters arrive.
> Spreading them across the syllable's length instead -- which
> is what this did first -- claims the voice walks through the
> letters of a held note, and it does not: two characters held
> for two seconds had the second one arriving a full second
> after the first, so it swelled on its own, a second late,
> with the rest of the word already flat. One letter bulging
> by itself for the length of a held note, and right again the
> moment the note ends.
>
> Within a syllable the characters are given a couple of
> frames between them and no more: enough for the swell to
> read as travelling rather than as the whole syllable
> snapping at once, never enough to claim the voice has moved.
> Capped by the syllable's own length so a quick one cannot
> stagger past its own end.

**line 3042** — before `spans, at = [], 0`

> Lay the whole word out at its current size, across its
> fragments, and hand each fragment the slice that is its own.

**line 3063** — before `cur = left + (plain - grown) * 0.5`

> Re-centred, so opening out does not walk the word sideways
> into whatever is beside it.

**line 3069** — before `placed[sp[3]] = (cur + (wide - sp[1]) * 0.5) - sp[2]`

> The glyph is drawn unscaled then scaled about its own
> centre, so its centre goes to the middle of the slot.


### `Amll.emph_of`

**line 3122** — before `held_for = (e - s) if voiced is None else voiced`

> How long the NOTE is, which is what the gate and the two curves
> below are all asking about, and not the same as how wide the word's
> span is -- see voiced_of. The default is the span, so a caller with
> only a start and an end (a word asked about on its own) gets exactly
> what it always did.

**line 3141** — before `held = min(1.0, max(0.0, (held_for - 0.18) / 1.1))`

> How BRIGHT, and how far the light carries, from the window's own
> glow_of rather than from AMLL's curve -- the same trade as the rise,
> and for the same reason.
>
> AMLL cubes its glow below three seconds, so a word of 1.0s is lit at
> 0.018 and one of 1.5s at 0.063. Its own gate lets a word in at 1.0s,
> which means AMLL admits words to the emphasis and then gives them
> nothing to see: measured over five documents here, the peak alpha
> came out at 0.02 on Poker Face and 0.05 on Time. The effect was
> firing and was invisible.
>
> glow_of answers the same question -- how wide and how bright is the
> halo on a word held this long -- and it is already calibrated
> against these documents and against the window's type. It also
> measures the word's length as a WIDTH rather than a character count,
> which is the better measure and the one this file argues for at
> length. AMLL's own curve is two lines above, if it is wanted back.

**line 3166** — before `if arrive is None:`

> When each character starts, and the one place this cannot simply
> copy AMLL.
>
> AMLL sets character i going at `de + (du / 2.5 / n) * i` -- evenly
> spread across the word, then compressed towards its start so the
> swell travels through quickly rather than taking the whole note.
> Evenly spread is right THERE, because a word is one timed unit with
> nothing inside it.
>
> Here a word has syllables inside it, each with its own stamps, and
> they are regularly nothing like even. Spread evenly anyway, the
> characters of a late syllable set off long before the voice reaches
> them: a word split "mat" + "ter" with a long first syllable had the
> second "t" moving most of a second before it was sung, which reads
> as one letter of the word jumping the queue.
>
> So what is spread evenly is replaced by when the voice ACTUALLY
> arrives at each character, and the same compression is applied to
> that. It is the same formula: AMLL's `(du/n) * i` is simply the
> arrival time of character i in a word with no internal timing, so
> this reduces to exactly AMLL's stagger for such a word and follows
> the syllables for one that has them.

**line 3189** — before `arrive = [s + ((e - s) / n) * i for i in range(n)]`

> From the word's own length, not from `du` -- `du` carries the
> one second floor and the 1.2 the last word of a line is given,
> neither of which has anything to say about when the voice
> reaches a character. emph_plan always passes the real arrival
> times; this is the fallback for a word asked about on its own.

**line 3195** — before `offs = [max(0.0, a - s) for a in arrive]`

> A character starts when the voice reaches IT, not before.
>
> AMLL divides this by 2.5, pulling every character back towards the
> start of the word so the swell travels through quickly instead of
> taking the whole note. That is harmless there, because an AMLL word
> is one timed unit -- there is no such thing as "when the voice
> reaches character three", so nothing can be early relative to it.
>
> Here there is. Measured on a held word timed 4 + 2 characters: the
> voice reaches the fourth character at 71.904 and the compression
> started it moving at 71.620, nearly three tenths of a second before
> it was sung -- and the last two, which belong to the held syllable,
> set off 0.36s and 0.95s before their turn. One letter of a word
> stirring while the voice is still somewhere to the left of it is the
> whole complaint, and no lead small enough to fix it would leave a
> lead at all.
>
> So the arrival times are used as they stand. The swell then follows
> the voice across the word rather than anticipating it, which is what
> the fill beside it already does, and each character still leads its
> own moment by EMP_LEAD -- a frame or two, the same everywhere else.

**line 3218** — before `ends = (e - s) + self.SETTLE`

> How long each character's own swell lasts, chosen so that the LAST
> of them finishes as the word does.
>
> AMLL runs every character for the word's full length and staggers
> the starts on top of that, so the last character finishes a stagger
> AFTER the word -- four tenths of the note, which on a three second
> hold is well over a second of a finished word still shining while
> the next ones are being sung. Its float is worse: 1.4 times the
> length again.
>
> The swell belongs to the word being sung, the same rule the lead
> obeys at EMP_LEAD. So the stagger is taken OUT of the window rather
> than added to it, and the last character lands SETTLE after the end
> of the note rather than a whole stagger after it.
>
> SETTLE is not slack, it is what keeps the word looking shiny rather
> than rippling. With the characters no longer allowed to anticipate
> the voice their starts are spread across the whole note, so if each
> one also had to FINISH by the end of it, each envelope would be a
> fraction of the note and only one or two letters would ever be up at
> a time -- a wave running along the word instead of the word itself
> lighting. Letting the last one run a quarter second past the end
> gives every envelope enough room to overlap its neighbours.
> Each character is lit until the NOTE is over, not for a length
> shared with every other character.
>
> One shared length has to be short enough that the last character to
> start still finishes by the end, and where a syllable split puts
> that character late, it is very short -- so the characters that
> started first went dark long before the word was done being sung. On
> a word split four letters then two, the first letter's light ended a
> third of a second early; on a word whose last syllable opens at four
> fifths of the note, before the halfway mark.
>
> Measured from each character's own start to the same finish instead,
> so an early character simply glows for longer. They still peak in
> order, which is what makes the light travel.

**line 3257** — before `swell = fm.height() * self.RISE * min(1.0, self.v.rise)`

> The per-character swell is AMLL's own fixed amplitude, and `rise`
> may switch it off but not amplify it.
>
> This one does not belong to the knob. The knob moves a WORD, and a
> word moving further is just a word moving further -- it stays one
> shape. This moves the characters of a word against EACH OTHER, so
> turning it up does not make the effect bigger, it makes the word
> come apart: measured on a six-character word at 46px, the spread
> between its first and last character runs 3.7px at rise 1, 6.8px at
> rise 2 and 9.9px at rise 3, against AMLL's own 0.05em, which is
> 3.4px here. Past about four the letters stop reading as one word.
>
> So the knob is a gate rather than a multiplier here: 0 turns it off,
> anything above 1 is AMLL's amplitude and no more. The word's own
> float above goes on scaling with it in full, because that one moves
> every character of the word by the same amount and cannot tear it.
> Not doubled for a background line. AMLL floats an ad-lib twice as
> far; this file's own rule is that every word in the window travels
> the SAME distance, whatever type it is set in -- see the note in
> Flow.word_lifts, which measures off the main lyric font for exactly
> this reason. An ad-lib going up twice as far as the line it hangs
> off does not read as emphasis, it reads as a different renderer
> drawing it.

**line 3281** — before `word_k = max((_emp_easing(max(0.0, min(1.0, (pos - (s + o)) / sp)))`

> One scale for the whole word, not one per character.
>
> A character scaled about its own centre grows into its neighbours,
> and the neighbours are close: measured on the lyric face, the INK
> gaps inside a word are 3 to 6 pixels, against the two and a half a
> tenth of extra size adds. Giving each character a slot as wide as
> its own grown advance keeps the ADVANCES right and still merges the
> ink, because the characters are not all growing by the same amount
> at the same moment -- the wave is passing through them. Rendered and
> counted, 41 frames of 73 across one held note had two letters fused
> into one shape.
>
> With a single scale every gap grows by that same factor instead of
> closing, which no arrangement of per-character sizes can promise.
> What is lost is the size wave; what keeps the swell travelling is
> the glow and the float, which are still per character and neither of
> which can push a letter sideways. Taken at the leading edge of the
> wave so the word swells with the first character the voice reaches.

**line 3301** — before `word_scale = 1.0 + word_k * 0.1 * amount * self.SWELL`

> The swell does not change the SIZE of the text, only its light and
> its height.
>
> Growing it is what AMLL does and there is no room for it here.
> Measured on the real window at the settings this runs at, the ink
> gaps inside a word are one to two pixels. Growing the word by a
> tenth moves every letter's edge outward by more than that, and the
> glyphs are re-rasterised onto the pixel grid at the new size, so a
> gap of one pixel does not become a gap of one and a bit -- it
> rounds away. A six-letter word came out as two runs of ink instead
> of six while it was held, and it kept doing it after the spacing was
> made to follow the size, after the kerning was fixed, and with the
> halo turned off entirely, because none of those put a pixel back
> that the grid had taken.
>
> A face with air between its letters would carry it. This one does
> not, and the letters are worth more than the swell: what is left --
> the word lifting and lighting as it is held -- is the part that
> still reads at this size. SWELL is the amount, for a face that can
> afford it.

**line 3332** — before `0.0,`

> No sideways push: emph_plan places the letters, and
> nothing is allowed to move them off that.

**line 3335** — before `up * self.BOB + k * 0.025 * amount * em * self.BOB,`

> ...and no vertical bob either. AMLL floats each
> character as the companion to growing it, so the
> letters ride the swell they are part of. With the
> growing gone -- see SWELL -- a letter rising on its
> own is movement with nothing to explain it: the
> syllables just go up. What the word does instead is
> the float every word gets, from word_lifts, which
> moves all of it together. BOB puts this back for a
> face that can carry the growing too.


### `Amll.word_lifts`

**line 3405** — before `full = self.on_grid(unit * self.RISE * self.v.rise * act * (1.0 - blur))`

> On the pixel grid, for the reason Renderer.on_grid gives: a word
> that has finished floating then sits exactly on a row of pixels and
> draws as glyphs instead of as the little picture lifted_word has to
> make for one still moving. Without this every word in the column was
> parked a fraction of a pixel off the grid for the whole song, so the
> whole column was permanently resampled -- softer, and paying the
> picture cost on every word of every frame.
> `bg` is deliberately not in this. AMLL floats a background line
> twice as far as a lead one; the stack's own rule, at the top of
> Flow.word_lifts, is that the distance comes off the MAIN lyric font
> so that every word in the window travels the same amount. An ad-lib
> is set at two thirds the size and rising twice as far made it the
> most mobile thing on screen.

**line 3419** — before `out = {}`

> In READING order, whatever order the stamps are in.
>
> They are not always in it. A line with an ad-lib written into it can
> have a word stamped before the word in front of it, because the two
> really are sung across each other -- one such line in this
> collection has its third word starting sixty-five milliseconds
> before its second. Run off the stamps as they stand, the third word
> goes up before the second and the line comes apart: measured over
> that line, a word stood higher than the word before it in 36 frames
> of 111, where the stack managed none.
>
> So the same two rules Renderer.rise_plan and frag_lifts use between
> them: each word's start is held to the one before it on the way
> past, and each word's lift is held down to whatever the word before
> it reached. The eye reads the line forwards, so the rise has to
> travel forwards; what crosses the line is a wave and never a word
> yanked up out of turn. Held across the whole LINE rather than per
> row, because the head of row two is the next thing after the tail of
> row one.


### `Amll.paint`

**line 3462** — before `if not v.synced:`

> An unsynced document has no clock to follow and nothing to spring
> to. The stack already knows how to print a page of text.
>
> And it moves that page with view.scroll, which makes the whole of
> this renderer's own way of moving the column dead on this path: the
> offset is not read, the springs are not stepped, and `_last_top` is
> about a column that is not being drawn. Dropped rather than left to
> sit, so that a clock arriving later starts from where the words are
> instead of applying a push the reader gave a static page. See wheel.

**line 3480** — before `v.content_h = 0.0`

> Nothing for the window to scroll: the wheel comes here instead, and
> what it moves is this renderer's own offset. See Amll.wheel, and
> Renderer.wheel for why the window has to be asked at all.

**line 3494** — before `reading = mono() < getattr(v, "user_scroll_until", 0.0)`

> While the reader is reading ahead, the column stops following the
> song. Letting it follow puts the line they are looking at somewhere
> else every few seconds, which is the column being taken back off
> them one line at a time rather than all at once when the four
> seconds are up. AMLL freezes the same thing for the same reason --
> see its FocusController, which holds the target for the whole of a
> scroll rather than re-deriving it per frame.

**line 3510** — before `self.offset = 0.0`

> Four seconds after the last notch the column is the song's
> again. The offset is dropped whole and the springs carry every
> line home with the stagger running down them, which is AMLL's
> resetScroll: the return is an animation nobody has to write,
> because it is the same one a line change already uses.

**line 3517** — before `v.focus_idx = focal`

> tick() only works this out for a renderer that scrolls, and this one
> does not -- so the renderer that owns the column owes it the answer.
> _paint_line reads it to keep the line being read sharp, and so do
> the review marks.

**line 3525** — before `base = H * self.ALIGN - plan[focal][1] / 2 - plan[focal][0]`

> Where every line would sit if the springs were already there. The
> focal line's MIDDLE lands on the align position; everything else
> follows from the plan, which is the same prefix sum down the column
> that the stack uses.

**line 3530** — before `self._bounds = (min(0.0, -plan[focal][0]),`

> How far the wheel is allowed to push it, which is AMLL's beginFrame:
> back as far as the top of the document, forward until the last line
> sits in the middle of the window. Worked out every frame because
> both ends move as the song does.

**line 3539** — before `stride = plan[focal][1] * 2.0`

> The stagger is safe in ONE direction, and only over a short move.
>
> It works by letting the top of the column set off before the bottom
> of it. Which way the column is going therefore decides whether that
> is a wave or a collision:
>
>   * moving UP -- the song advancing to the next line, which is
>     almost every move there is -- the line that sets off first moves
>     AWAY from the one under it. The gaps stretch and close again.
>     Nothing can touch anything.
>   * moving DOWN -- seeking back, clicking a line above, scrolling
>     back, coming home from a scroll -- the line that sets off first
>     moves straight at the one under it, which is still waiting its
>     turn. It arrives on top of it, and stays there until the wave
>     reaches the bottom of the window.
>
> Enumerating the causes was the wrong way round and kept missing
> them: a click that seeks forward by less than a second read as
> ordinary playback and got the stagger anyway. The direction is the
> property that actually matters, and it does not need to know why the
> column is moving.
>
> The distance is the other half. A move of about one line is what the
> wave is for; a click ten lines up covers ten times that, and with a
> stagger under it the top of the column is most of a window away from
> the bottom before the bottom has moved at all. So: up, and no
> further than the step a line change actually takes -- one line, or
> two where the step carries over an ad-lib.
>
> AMLL arrives at the same place from the other end, by naming the
> scenarios: DiscreteScroll, ContinuousScroll, InteractionStart and
> Seek all set disableStagger.

**line 3579** — before `small = 1.0 + (self.SCALE - 1.0) * (1.0 - v.browse)`

> What an un-sung line is aimed at, which is not always SCALE. A hand
> on the wheel takes the whole column back to full size, and it is the
> same reason the blur lets go of it (see `browse` in tick, and the
> note by the review marks' distance fade): somebody scrolling is
> READING the column rather than listening to it, and every line they
> are reading wants to be the size the document was set in and drawn
> without a transform over it. The depth cue is for a column being
> sung past, and it comes back as soon as the hand does.

**line 3594** — before `sp.set_target(y)`

> The line being sung when a document lands is already the one
> being read -- it flies in with the rest, but it is not given
> the wait, so the words are legible while the column settles.

**line 3608** — before `if y + entry[1] >= 0:`

> Only the lines from the top of the window down are given a wait:
> a line that is already above the viewport has nothing to show for
> having set off late, and counting it would spend the whole
> stagger before the wave reached anything visible.

**line 3617** — before `m = H if (v.zero_g > 0 or v.clouds > 0) else 40`

> From here down this is the stack's own frame loop, against spring
> positions instead of a scrolled plan. See Flow.paint.

**line 3624** — before `rects.append((i, y + v.scroll, h, x0 + lo, x0 + hi))`

> In content space, which for a renderer that pins its scroll is
> the same space -- added back the moment it is taken off, so the
> contract holds if that ever stops being true.


### `Pinned`

**line 3677** — before `ADLIB_GAP = 0.22`

> The air between a line and the first of the ad-libs under it, in lines
> of the type they are set in.


### `Pinned.__init__`

**line 3685** — before `self._page = None`

> The stack, built only if a document with no clock turns up. See
> static_page.


### `Pinned`

**line 3752** — before `def _index(self):`

> -- ad-libs, and the lines they hang off ----------------------------


### `Pinned.current`

**line 3848** — before `cur = next((i for i in live if not self.v.lines[i].get("background")),`

> No line to read on to -- a document of nothing but ad-libs, or
> one whose only singable lines are backing vocals.


### `Pinned.draw_row`

**line 3924** — before `lift = lifts.get(f_i, 0.0)`

> Neither the lift nor the pop goes on the painter: lifted_word
> places the word, because a translation is the one thing Qt
> rounds to a whole pixel. See Renderer.lifted_word.


### `Spotlight`

**line 4036** — before `FADE = 0.22`

> Long enough to read as a dissolve rather than a cut, short enough that
> the two lines are never both legible at once.


### `Spotlight.animating`

**line 4071** — before `return bool(self.gone)`

> The window eases activations and repaints while they move; this fade
> is quicker than they are and has to ask for its own frames.


### `Spotlight.paint`

**line 4077** — before `if self.static_page(p, x0, width, H):`

> No clock, no voice to follow: the page is printed instead, by the
> stack, which also leaves it somewhere the wheel can move. See
> Pinned.static_page.

**line 4094** — before `for i in sorted(out, key=lambda k: out[k]) + ([] if cur is None else [cur]):`

> Faintest first, and the line being sung last of all, so it is drawn
> over whatever it is replacing rather than under it.

**line 4115** — before `foot += self.draw_adlibs(p, cur, live, small, fm_sm, x0, width, foot,`

> The backing vocals of the line being sung, hung off the bottom of it
> at the size the neighbours are set in. They are part of this line, so
> the line coming next is pushed below them.


### `Karaoke`

**line 4161** — on `    LEAD = 2.0`

> seconds of run-up the bar shows


### `Karaoke.paint`

**line 4165** — before `if self.static_page(p, x0, width, H):`

> No clock, no voice to follow: the page is printed instead, by the
> stack, which also leaves it somewhere the wheel can move. See
> Pinned.static_page.

**line 4180** — before `slots: dict[int, int] = {}`

> Who is in which band. Every line SOUNDING that takes a band takes
> the one its own place in the document gives it, and the line coming
> takes whichever band is left over -- if two voices are already using
> both, the line coming next IS one of them and nothing is being held
> back. Sounding, and not "the line an ad-lib belongs to": reaching
> back from a live ad-lib would put a line whose own words finished a
> bar ago into the pair, and put it there dressed as the line coming
> next, which is the last thing it is.

**line 4194** — before `band = fm.height() * 2.6`

> Two bands of a fixed height, so the pair can never reach each other
> however many rows either line wraps to -- a slot whose position came
> out of its own line's height is a slot that moves, and the point of
> the alternation is that neither of them does.
>
> A block too tall for its band grows AWAY from the divider between
> them rather than out of the middle in both directions. Growing both
> ways was survivable while a band held one line of two or three rows;
> a line with its ad-libs under it is regularly taller than that, and
> what came of two of those was the second voice of one band printed
> through the first row of the other.

**line 4206** — on `        low = H * 0.5`

> top of the lower of the two

**line 4207** — on `        divide = fm.height() * 0.35`

> the closest either comes to it

**line 4222** — before `alpha = (0.18 + 0.14 * self.run_up(ln, pos)) if coming else 0.34`

> The line coming brightens as it approaches, which is the whole
> of what tells the pair apart: two lines set the same size, one
> of them lit and one of them coming up.

**line 4228** — before `self.mark(i, top, own, x0, width)`

> Its own rows, not the whole block: what is under it belongs to
> the ad-libs, and each of them publishes a box of its own to be
> clicked on.


### `Word.paint`

**line 4311** — before `if self.static_page(p, x0, width, H):`

> No clock, no voice to follow: the page is printed instead, by the
> stack, which also leaves it somewhere the wheel can move. See
> Pinned.static_page.

**line 4333** — before `p.setFont(self.font(v.lyric_px() * 1.1))`

> Nothing to pick from: the whole line, centred.

**line 4342** — before `subs = []`

> The ad-libs of this line that are sounding, and what each of them is
> saying. Whichever of them opened first stands in for the line itself
> while the line has not been sung into yet: an ad-lib that comes in
> ahead of its lead is what the song is doing, and the middle of the
> window is for what the song is doing.

**line 4352** — before `got = self.pick(said, pos) or (said[0] if said else None)`

> Its first word until it has sung one, the same fallback the line
> itself gets: a voice that is sounding has something to show even
> in the breath before its first word.

**line 4360** — before `of, big = subs.pop(0)`

> The line has not been sung into yet and something backing it
> has: that is what the song is doing, so it takes the middle
> rather than being printed under a word nobody has sung.

**line 4367** — before `mid = H * 0.46 if not subs else H * 0.42`

> The big word sits a little high when something is written under it,
> so the pair is centred on the window rather than the lead alone.


### `Cards`

**line 4404** — on `    INSET = 0.10`

> of the column, per side, for an ad-lib card


### `Cards.paint`

**line 4435** — before `still = not v.synced`

> A document with no clock. Nothing on it is being sung and nothing is
> waiting its turn, which is the whole of what `act` separates -- so
> every card is drawn as the present one rather than as the un-sung
> one. It was the un-sung one: a card nobody is on keeps its words at
> a third of a fade that is itself down at 0.38, which on a timed song
> is a depth cue and on a page of untimed lyrics is a sheet of frosted
> glass over the whole document.
>
> `act` itself is left alone and stays 0. It is also what the rise and
> the fill read, and there is no time on this document for either of
> them to happen at -- what is wanted is a page that can be read, not
> a page pretending to be sung. Compare base_colour, which refuses the
> duet tint on a static document for the same reason.

**line 4461** — before `dist = v.vfade(y + h / 2)`

> Faded by distance from the focus band as well as by whether
> it is being sung, the way the stack fades its own column: a
> scrolling renderer that did not would slice the card at the
> top of the window off at full strength. The card itself goes
> with its words -- a panel left behind by the text that was on
> it is a blank card floating at the edge of the window.

**line 4474** — before `p.save()`

> Saved around the panel for the reason _paint_dots is:
> the window hands one painter to everything it draws, and
> this used to hand it back with NoPen and NoBrush on it
> after EVERY frame, not only over an interlude.

**line 4484** — before `self.draw_block(p, ln, rows, f, cx + pad, cw - pad * 2,`

> 0.34 is what an un-sung card's words are worth under
> the sung fill that is coming for them. With no clock
> nothing is coming, so there is no layer to leave room
> for and the words go on at the strength the stack gives
> a static page.

## 2026-10-17 — Glow every word: a held word's light per letter

Reported on BBpanzu, "Bang Bang Bang" ("Word pop" 3, "Glow every word" 0.3): a faded "grets" behind "regrets". The ghost was `all_glow`'s picture of the line (blur level +2, in the glow colour). `glow_lifts` lifted a held word's stretch of it by the AVERAGE of its letters' heights, so under a bent word the light of the letters above the average was left below them, and the letters under it had light above. `glow_lifts` now gives each letter of a held word its own stretch: its rest columns (`shaped_units`), lifted by its own `up` and moved by its own spread (`dx`). Neighbours that stand alike still run together. `all_glow` draws each stretch translated by (dx, -dy), cut out of the plain pass at both its rest place and where it lands.

Measured on "humanity" (FLAVOR FOLEY, held 4.6s): old against new differs on 200-2,000 pixels as the bend grows (two runs of the same code are identical to the pixel). The band of light under the risen letters is gone. Motion at 240fps through "satisfactory": top-edge reversals 5 either way, halo frame-to-frame change identical. The strips do not shimmer.

Tried and reverted the same day: rasterising a grown letter at its grown size (picture density × grow in 1/32 steps), for "satisfactory" looking soft at pop 3. Against vector text it came closer (mean 0.62 → 0.27 at 1.2x), but nothing showed at normal size, and "satisfactory" still vibrated once it ran. Each 1/32 step re-snaps the picture's position and re-rasterises the glyphs. 240fps: 7 reversals against 5. The softness seen was the ghost glow above, not the scale.

## 2026-10-19 — Ad-libs only with their line (amll)

Text ▸ Ad-libs and credits ▸ "Ad-libs only with their line", `adlibs_with_line`,
default on, `--[no-]adlibs-with-line`. The amll column only; the stack, Spicy
Lyrics and the pinned renderers are untouched (the pinned ones already draw an
ad-lib only while it is on).

- **Which line is an ad-lib's lead** (`Amll.adlib_leads`): the lead line of
  its `group`, which can come AFTER it -- an ad-lib that opens early is
  flattened ahead of its lead (Cheap Thrills, line 63 before 64). A line with
  no group hangs off the nearest lead line above it. An ad-lib whose group
  has no lead never folds, so a document of nothing but backing vocals is
  still all there.
- **When it is out** (`shut_adlibs`): while its lead or itself is sounding,
  or its lead is the focal line. `sounding()` holds the last line through a
  gap, so an ad-lib stays out until the next line takes over, then folds.
  2026-10-22: also every ad-lib while the user has scrolled away
  (`user_scroll_until`); back in sync they fold again the usual way.
  2026-10-22: also from `ADLIB_EARLY` (0.4s) before its own start. Opening
  takes 0.32-0.50s from its trigger (Cheap Thrills, 60fps). An ad-lib sung
  before its lead (63 before 64) used to be half out only 0.17s into its
  first word and fully out at 0.32s. They want it to still open as it is
  sung, a little earlier. At 0.4 (0.35 once the lift below went in) it is half out at +0.02s and full at
  +0.08s. 0.6 (full at -0.12s) was too early: they could see it 0.2-0.3s
  before the word.
  2026-10-24: not with its lead when an interlude marker (`dots`) sits
  between them; it then opens only on its own clock. Self Aware (Spicy): the
  lead "Oh" is sung 8.32-9.16, and the line is padded to 15.6 over an ad-lib
  "Oh" at 14.14. The lead stayed focal through the gap, so the ad-lib was out
  5s before it was sung. They said it "depends on the interlude time set", so
  the test is the marker that `prepare` inserts at the Interlude gap setting,
  not a fixed time. With interludes off, or set longer than the gap, the
  ad-lib opens with its lead as before. Across 3505 docs, 55 of 7452 ad-libs
  start more than 2s after their lead's last word.
- **Where its room comes from** (`adlib_lift`, 2026-10-22): an ad-lib open
  below the focal line, but ahead of its lead (its lead is not focal), lifts
  the whole column by `ADLIB_LIFT` (0.65) of the room it takes. They wanted
  the lines above to go up more than the lines below go down. For 63, as it
  is sung, the line above is now -23px and the line below +7px (it was -4 /
  +20). When its lead becomes focal the lift drops out, and the column
  centres on the lead as usual. The lift
  is the difference between `shut_offs` totals with and without those
  ad-libs, so `shut_offs` keeps two results. The column moves up sooner, so
  the room opens sooner and the fade comes sooner. `ADLIB_EARLY` went 0.4 ->
  0.35 to keep half out at +0.02s.
- **Moving and popping together** (2026-10-22): the lines should move
  at the same time as the ad-lib popping up. At 0.35 the trigger came at
  -0.35s, but the lines only started at -0.18s, because the stagger delays
  each line by its place on screen. The ad-lib showed at -0.02s, once the
  room reached 0.45h. Three changes:
  - a rising lift sets `_jolt`, so that move is not staggered;
  - `ADLIB_IN` 0.35 -> 0.15;
  - the room gate is 0.3h over 0.6h (`ROOM_FROM`, `ROOM_OVER`; was 0.45 over
    0.5).

  `ADLIB_EARLY` went to 0.12. Line 63 now: the lines move from -0.12s, the
  ad-lib shows at -0.05s, it is half out at 0.00 and full at +0.07s, and the
  room is 90% open at +0.08s. The bigger move to the lead (64) starts after
  that, staggered as before. Lead-first ad-libs fade in over 4 frames at 60fps
  (line 14 was 7; 28 and 40 were already 3-4).
- **How it folds** (`shut_offs`): a shut ad-lib takes no room. It sits where
  the line after it sits, under it, and the lead gets the ordinary 0.42 gap
  back instead of the 0.16 it keeps next to an ad-lib. Cached by plan and
  shut set.
- **How it opens** (`show_adlibs`, `adlib_fade`, `faded`): it fades, and the
  fade is held back by how far the line below has moved off it. It is
  `smooth(o) * smooth((room - 0.45h) / 0.5h)`, where `o` eases in over 0.35s
  and out over 0.6s, and `room` is `ys[i+1] - ys[i]`. (Now 0.3h / 0.6h and 0.15s in;
  see "Moving and popping together".)
  - A shut ad-lib (o = 0) is never drawn.
  - A folding one fades as the gap closes rather than on a clock. Fading on a
    0.18s clock left an empty hole for about 0.3s, because the stagger
    reaches the lines above late. The 0.6s is only a backstop.
  - `QPainter.setOpacity` is absolute, and the fill, the glow and the base
    each set their own. `faded` therefore shadows `p.setOpacity` on the
    painter instance for the call, scaling every value by the fade, then
    deletes the shadow.
  - First version (same day), replaced: the ad-lib was drawn clipped at the
    top of the line below. They found it looked bad. The stagger also opened
    that clip on every line switch, so every folded ad-lib showed cut off
    while the column moved. The test's whole-song check fails on that
    version.

Test: `~/mild-lyrics-archive/tests/test_adlib_open.py` (30 checks). It uses
the real Amll on a fake clock and a real painter, with `_paint_line`
recorded. Its View stub is test_renderers' own, plus a `__getattr__` that
borrows LyricsView's methods and DEFAULTS, because that stub had gone stale
(`sung_color` → `sung_colour`, `line_spacing`).

## 2026-10-28 — Spicy renderer checked against Spicy Lyrics 34ad8c6

Compared with Spikerko/spicy-lyrics at 34ad8c6 (2026-10-24):
LyricsAnimator.ts, Emphasize.ts, IsLetterCapable.ts, Syllable.ts, Mixed.css,
ScrollToActiveLine.ts and LyricsVirtualizer.ts. Simple lyrics mode was left out.
The springs, splines, glow radii and opacities, letter split (≥1s, ending
250ms early), dot timings (-550ms), fill gradient, line opacities, blur steps
and hover wash all still match. What changed:

- **Glow over the fill.** A `text-shadow` paints in the foreground phase,
  after a `background-clip: text` background, so in Spicy the halo lies on
  top of the gradient. It was drawn underneath. Words, letters and dots now
  draw `_put` first and then `_glow`.
- **Alpha clamp.** `rgba(255,255,255,1.85)` is opaque white, not twice
  white. `_glow` now clamps before the Glow knob.
- **Mild's extra glows follow the fill.** Glow every word and Glow long
  words lit the whole syllable from its first frame, ahead of the fill.
  Measured on NF - Time with word_glow 1, pop_glow 0.9: on "tonight" and
  "everything", letters not yet sung carried a halo. They are now faded
  out across the fill's own soft edge (`_lit_span`, `_lit_part`). On a
  letter group that edge is the edge of the letter being sung. Spicy's own
  word glow (≤35%, 4-6px) still covers the whole element, as the CSS does.
- **`_gauss` at a scale other than 1×.** A QGraphicsPixmapItem lays out a
  pixmap that carries a ratio in points, so the blur shrank its picture
  toward the top left by the ratio: every Spicy halo and blurred idle line
  landed up-left of its word. Measured: a box at x=80 came back at x=53
  at 1.5×. It is now blurred in device pixels.
- **Letter group lift.** CSS applies `transform` inside `scale`, so the
  group's lift is now scaled with it (a twentieth of a pixel).
- **Interlude dots.** The group opens over 0.3s (`.dotGroup` transition,
  ease), not 0.1s, and closes over 0.4s, not 0.35s. The gap is Spicy's
  clamp(0.005rem, 1.7cqw, 0.18rem), not 0.08em.
- **Preset.** Spicy's virtualizer centres the line with 30px padding,
  so it sits 30px above the middle: focus_height 0.46 (exact at ~800px tall).
  The glow is white, so glow_tint is white, and pop_glow and pop_linger are
  0, so the preset no longer inherits them from whatever was set.

Harness: scratchpad shot.py/lead.py pattern. Two Spicy renderers on one fake
clock, one with the glow knobs off, and their difference is the glow.

