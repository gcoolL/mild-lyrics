# `mild-lyrics/layout_ahead.py`

## 2026-10-13 — laying the next song out before it starts

**Why.** The first paint of a new song lays out every line at once. Their frame trace showed 28–50ms spikes at song starts. Offscreen, on Ado's 新時代 at 1920px with furigana and romaji under: 32ms. Of that, 25ms was 1043 cold CJK `horizontalAdvance` calls (~24µs each) and 9ms was pykakasi readings.

**How.** The measurements are already kept on objects that outlive a song: `advance()`'s and `wrap_shape`'s memos on the QFontMetricsF, and `spicy_lyrics._segments`' lru_cache. So laying a song out once, anywhere, leaves its real first layout mostly hits. The fetch-ahead thread (`Fetcher._warm`) already has each upcoming track's document. It now emits `ahead_ready(tid, timeline)`, once per track. `LayoutAhead` runs on the main thread, every 30ms, for about 0.6ms a turn. Each turn calls the window's own `build_lines(raw)` and `layout_line(i)`, with the job's lines, `japanese` flag and a scratch `layout_cache` swapped in, then swapped back. It is the same code as the real layout, so nothing is approximated, and nothing it makes is shown.

Needed alongside:
- `face_metrics(font)`: one QFontMetricsF per face for the ruby and romaji rows (and the panel's title rows). They made a new one every layout, so their memos died with it.
- `split_to_fit`, `build_lines`, `ruby_rows`, `_spread`, `wrap_rows` and `_scroll_text` measure through `advance()`.
- `renderers.adv` shares `advance`'s memo (`fm._adv`).

**Measured** (offscreen, GL, real-use settings; switching 新時代 → 踊 mid-run, 3 runs each): first frame after the switch 14–17ms cold, 6–8ms warmed. The rest is line pictures and the plan itself. Laying 新時代 out ahead took 28ms in all, over 12 turns. A line cannot be split, so a few turns run long: the first line 12.5ms (one-time pykakasi and font setup in a fresh process), and lines with furigana plus romaji ~5ms. These land during the previous song, a few times a song.

Not warmed: romaji corrections (`apply_romaji_fixes`) and the fetcher's shaping, so a corrected or reshaped line is laid out cold. Instrumental songs are skipped, since the column is a different width there.
