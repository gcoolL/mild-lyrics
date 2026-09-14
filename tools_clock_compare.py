#!/usr/bin/env python3
"""What Spicy Lyrics' clock says, beside this program's.

    python3 tools_clock_compare.py                 # ten seconds of samples
    python3 tools_clock_compare.py --seconds 30

Both programs are drawing the same song from the same player at the same
moment, so the only honest way to compare them is to read both at once.
Three numbers come back per sample:

  engine  where the playback engine says the audio is. The referee: it is
          what CdpTransport anchors on and what Spicy Lyrics reads too, so
          neither program's answer is the standard here.
  mild    this program's clock -- the interpolated, slewed, hold-corrected
          number the words are actually drawn from. Read from a real Clock
          driven by a real CdpTransport at the sampler's own rate.
  spicy   Spicy Lyrics' clock, recovered from what it DREW. It writes a CSS
          variable on every word saying how far the sweep has got through it
          (`--gradient-position`), so the word being swept plus that word's
          own timings give the position its clock was at when the frame was
          painted -- to within a syllable, which on a word-timed lyric is
          tens of milliseconds.

Read-only. Nothing is seeked, nothing is paused, and the pause-pin is
switched off so this cannot nudge a paused player the way the window would.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / "aligner"), str(ROOT)]

import lyrics_gui as L          # noqa: E402
import spicy_lyrics as SL       # noqa: E402
import spotify_dom as SD        # noqa: E402

# One eval per sample: the two clocks the page can answer for, and the state
# of the line Spicy Lyrics has on screen. Together, because a round trip is
# where the disagreement would hide -- asked separately they are readings of
# two different moments.
JS_BOTH = """
(async () => {
  const P = Spicetify && Spicetify.Player;
  const ctl = (P && P.getProgress) ? P.getProgress() / 1000 : null;
  let engine = null;
  try {
    const PA = Spicetify.Platform;
    if (PA && PA.PlaybackAPI && PA.PlaybackAPI._isLocal
        && PA.PlayerAPI && PA.PlayerAPI._contextPlayer
        && PA.PlayerAPI._contextPlayer.getPositionState) {
      const got = await Promise.race([
        PA.PlayerAPI._contextPlayer.getPositionState({}),
        new Promise(r => setTimeout(() => r(null), 400))]);
      if (got && got.position != null) engine = Number(got.position) / 1000;
    }
  } catch (e) {}
  const el = document.querySelector('#SpicyLyricsPage .line.Active');
  let line = null;
  if (el) {
    const words = [...el.querySelectorAll('span.word')].map(s => {
      const g = (s.style.getPropertyValue('--gradient-position') || '').trim();
      return { text: (s.innerText || '').replace(/\\s+/g, ''),
               fill: g.endsWith('%') ? parseFloat(g) : null };
    });
    line = { text: (el.innerText || '').trim().replace(/\\s+/g, ' '), words };
  }
  return { ctl, engine, line, id: (((P || {}).data || {}).item || {}).uri || '' };
})()
"""


def flat(text: str) -> str:
    """A line or a word, as it is compared across the two renderings."""
    return re.sub(r"[^0-9a-z぀-ヿ一-鿿]", "", (text or "").lower())


def spicy_seconds(line: dict, timeline: list,
                  near: float | None = None) -> tuple[float | None, float | None]:
    """Where Spicy's clock was, by both readings of its sweep.

    The variable rests at -20% before a word and reaches 100% at the end of
    it, so the sweep is either 0..100 across the syllable or -20..100 across
    it -- the first if the negative value is just a resting place, the second
    if the gradient really is drawn a fifth of a word early. Both are
    returned and the run decides; see the summary.
    """
    want = flat(line.get("text", ""))
    if not want:
        return None, None
    words = line.get("words") or []
    # WHICH occurrence of the line. A chorus is the same words four times
    # over, and matching on the words alone picked whichever came first --
    # which is how a reading came back a minute and a quarter out. The one
    # meant is the one nearest where the song is; `near` is the engine, which
    # is nobody's opinion.
    same = [ln for ln in timeline
            if flat(ln.get("text") or "") == want
            and len(ln.get("syls") or []) == len(words)]
    if not same:
        return None, None
    if near is not None and len(same) > 1:
        same.sort(key=lambda ln: abs(float(ln.get("start") or 0.0) - near))
    for ln in same[:1]:
        syls = ln.get("syls") or []
        for i, w in enumerate(words):
            fill = w.get("fill")
            # A syllable is (start, end, text, part-of-word) -- see
            # SL.split_syllables, which is what shapes these.
            syl = syls[i]
            s, e = (syl[0], syl[1]) if isinstance(syl, (tuple, list)) else (None, None)
            if fill is None or s is None or e is None or e <= s:
                continue
            if 0.0 < fill < 100.0:
                return s + (e - s) * fill / 100.0, s + (e - s) * (fill + 20) / 120.0
        return None, None
    return None, None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--drive", action="store_true",
                    help="work the player as well as watch it: play, pause, "
                         "play, skip, previous -- the four moments where two "
                         "clocks are allowed to disagree. Puts the track back "
                         "where it found it. ONLY with the listener's say-so: "
                         "it is their music that starts and stops.")
    ap.add_argument("--every", type=float, default=0.15, help="seconds between samples")
    ap.add_argument("--port", type=int, default=9222)
    args = ap.parse_args()

    cdp = SD.connect(args.port)
    io = L.CdpTransport(args.port)
    clock = L.Clock(io)

    going = True

    def sample() -> None:
        # The window's own sampler, at the window's own rate, with the one
        # thing that writes to the player switched off.
        while going:
            try:
                clock.apply(io.read(False), False, False)
            except Exception:                                # noqa: BLE001
                pass
            time.sleep(L.SAMPLE_MS / 1000.0)

    pump = threading.Thread(target=sample, daemon=True)
    pump.start()
    time.sleep(0.5)

    tid = clock.tid
    timeline = []
    if tid:
        try:
            body = cdp.evaluate(SL.JS_GET % SL._j(SL.CACHE_PREFIX, SL.IDB_NAME,
                                                  SL.IDB_STORE, tid))
            body = (body or {}).get("body")
            timeline = SL.timeline(body, split="none") if body else []
        except Exception as e:                               # noqa: BLE001
            print(f"(no cached Spicy document for {tid}: {e})")

    def document_for(track: str) -> list:
        """Spicy's own cached document for a track, as timed lines."""
        if not track:
            return []
        try:
            got = cdp.evaluate(SL.JS_GET % SL._j(SL.CACHE_PREFIX, SL.IDB_NAME,
                                                 SL.IDB_STORE, track))
            body = (got or {}).get("body")
            return SL.timeline(body, split="none") if body else []
        except Exception:                                    # noqa: BLE001
            return []

    print(f"track {tid or '—'} · {len(timeline)} lines from Spicy's own cache")
    # WHAT IS DONE TO THE PLAYER AND WHEN, in seconds from the start of the
    # run. Each one is a moment the two clocks are allowed to disagree: an
    # unpause is a leap this program measures and takes back off (see
    # Clock._apply) and Spicy Lyrics does not correct at all; a skip is a
    # hand-over; a previous inside the first seconds of a track restarts the
    # same track at nothing, which is a seek with no audio to hide it.
    SCRIPT = ([(0.0, "PlayPause", "play"), (12.0, "PlayPause", "pause"),
               (17.0, "PlayPause", "play"), (27.0, "Next", "skip"),
               (37.0, "Previous", "previous")] if args.drive else [])
    ends = (SCRIPT[-1][0] + 12.0) if SCRIPT else args.seconds
    was_pos, was_playing, was_tid = clock.position(), clock.status == "Playing", tid

    rows, mild_gap, spicy_gap, spicy20_gap = [], [], [], []
    began = time.monotonic()
    phase, since = ("watching" if not SCRIPT else "before"), began
    todo = list(SCRIPT)
    print(f"{'t':>6} {'engine':>9} {'mild':>9} {'spicy':>9}   "
          f"{'mild-eng':>9} {'spicy-eng':>9}  what")
    while time.monotonic() - began < ends:
        now = time.monotonic()
        if todo and now - began >= todo[0][0]:
            _at, what, name = todo.pop(0)
            try:
                io.command(what)
            except Exception as e:                           # noqa: BLE001
                print(f"  ({name} refused: {e})")
            phase, since = name, time.monotonic()
        got = cdp.evaluate(JS_BOTH)
        mild = clock.position()
        if not isinstance(got, dict):
            time.sleep(args.every)
            continue
        if clock.tid and clock.tid != tid:
            tid, timeline = clock.tid, document_for(clock.tid)
        eng = got.get("engine")
        line = got.get("line") or {}
        a, b = spicy_seconds(line, timeline, eng) if line else (None, None)
        if eng is not None:
            mild_gap.append((phase, now - since, mild - eng))
            if a is not None:
                spicy_gap.append((phase, now - since, a - eng))
                spicy20_gap.append((phase, now - since, b - eng))
        fmt = lambda v: f"{v:9.3f}" if isinstance(v, (int, float)) else f"{'—':>9}"
        print(f"{now - began:6.1f} {fmt(eng)} {fmt(mild)} {fmt(a)}   "
              f"{fmt(None if eng is None else mild - eng)} "
              f"{fmt(None if (eng is None or a is None) else a - eng)}  "
              f"{phase}+{now - since:.1f}s {(line.get('text') or '')[:22]}")
        rows.append((phase, now - since, eng, mild, a))
        time.sleep(args.every)
    going = False

    if args.drive:
        # Back where it was found. The skip and the previous moved the queue,
        # so the way back is the way in reverse, and the position and the
        # pause are put back by hand.
        try:
            for _ in range(2):
                if clock.tid != was_tid:
                    io.command("Previous")
                    time.sleep(1.2)
                    clock.apply(io.read(False), False, False)
            if clock.tid == was_tid:
                io.seek(max(0.0, was_pos))
            time.sleep(0.4)
            clock.apply(io.read(False), False, False)
            if (clock.status == "Playing") != was_playing:
                io.command("PlayPause")
            print(f"\nput back: {clock.tid} at {was_pos:.1f}s, "
                  f"{'playing' if was_playing else 'paused'}")
        except Exception as e:                               # noqa: BLE001
            print(f"\n(could not put it back: {e})")

    def said(name: str, xs: list) -> None:
        vals = [v for _p, _t, v in xs]
        if not vals:
            print(f"  {name:<24} no samples")
            return
        sd = statistics.pstdev(vals) if len(vals) > 1 else 0.0
        print(f"  {name:<24} {statistics.mean(vals):+.3f}s mean, "
              f"{sd:.3f}s sd, worst {max(vals, key=abs):+.3f}s, over {len(vals)}")

    print("\nagainst the engine, which neither of them is:")
    said("mild - engine", mild_gap)
    said("spicy - engine (0-100)", spicy_gap)
    said("spicy - engine (-20-100)", spicy20_gap)

    for name in dict.fromkeys(p for p, _t, _v in mild_gap):
        print(f"\n{name}:")
        said("  mild - engine", [r for r in mild_gap if r[0] == name])
        said("  spicy - engine", [r for r in spicy_gap if r[0] == name])
        settle = [r for r in mild_gap if r[0] == name and r[1] <= 2.0]
        if settle and name != "before":
            said("  mild, first 2s", settle)
            said("  spicy, first 2s",
                 [r for r in spicy_gap if r[0] == name and r[1] <= 2.0])


if __name__ == "__main__":
    main()
