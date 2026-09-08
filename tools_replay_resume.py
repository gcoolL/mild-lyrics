#!/usr/bin/env python3
"""Replay one real pause/unpause through several Clocks at once.

READ-ONLY -- the only transport call is read(); nothing is sent to the player.
You drive it: start it, then pause and play in Spotify once.

Every clock gets the SAME readings and differs only in `unpause_delay`. If the
setting does anything, the columns diverge. If they don't, `_bias` is not what
is moving the words and the answer is somewhere else entirely.

`bias` is what each clock decided the player's unpause leap was. `err` is
clock.position() minus the position the player just reported -- negative means
the words sit behind what the player says.

    python3 tools_replay_resume.py [seconds]
"""
import os, sys, time
os.environ["MILD_LYRICS_LINK_PORT"] = "0"
sys.path[:0] = ["/home/gc/mild-lyrics/aligner", "/home/gc/mild-lyrics"]
import lyrics_gui as L

CAPS = [0.00, 0.05, 0.15, 0.25, 0.50]
wait = float(sys.argv[1]) if len(sys.argv) > 1 else 120.0

io = L.make_transport(9222, "auto")
clocks = []
for cap in CAPS:
    c = L.Clock(transport=io)
    c.unpause_delay = cap
    clocks.append(c)

print(f"transport: {io.name}   unpause_delay columns: "
      + "  ".join(f"{c:.2f}" for c in CAPS))
print("pause, then play. ctrl-c when done.\n")

resumed_at = None
shown = 0
try:
    START = time.monotonic()
    while time.monotonic() - START < wait:
        got = io.read(False)
        was = clocks[0].status
        for c in clocks:
            c._apply(got, False, False)
        pos, at, status = got["pos"], got["at"], got["status"]
        if status == "Playing" and was != "Playing":
            resumed_at = at
            shown = 0
            print(f"  RESUME at reported pos {pos:.3f}")
            print("     t      " + "".join(f"{c:>16.2f}" for c in CAPS))
        if resumed_at is not None and status == "Playing":
            dt = at - resumed_at
            if dt >= shown * 0.25 and shown <= 10:
                shown += 1
                cells = "".join(
                    f"  {c._bias*1000:5.0f}/{(c.position()-pos)*1000:+6.0f}"
                    for c in clocks)
                print(f"   +{dt:5.2f}s" + cells)
            if dt > 2.6:
                resumed_at = None
        time.sleep(L.SAMPLE_MS / 1000.0)
        if time.monotonic() - START > wait:
            break
except KeyboardInterrupt:
    pass
print("\n  cells are  bias_ms / (clock - player)_ms")
print("  (read-only; nothing was sent to the player)")
