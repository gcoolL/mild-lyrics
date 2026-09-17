#!/usr/bin/env python3
"""Watch the live link while the editor is syncing, from outside both windows.

    python3 tools_link_watch.py                    # until ctrl-c
    python3 tools_link_watch.py --seconds 300
    python3 tools_link_watch.py --log /tmp/link.jsonl

Leave it running in a terminal, sync a song with "Show in Mild Lyrics" on,
and it prints a line the moment the link misbehaves -- with the wall clock
beside it, so it can be lined up against what was on screen.

WHY IT CAN SEE ANYTHING AT ALL. The player announces its state on a 50ms
timer, and _maybe_announce guarantees a row every SAY_EVERY (0.5s) even when
nothing has moved. That timer is on the player's GUI THREAD -- the thread
that draws the words and the thread that reads the editor's socket. So a gap
in the row stream is not this program missing something: it is the only
outside measurement of the player's event loop stalling, which is the one
fault that stops the sweep, stops new lines arriving and leaves the clock
mis-anchored all at once.

The four things it calls out:

  stall    no row for longer than --stall. The window was not drawing and was
           not reading the socket. The editor sees nothing wrong: its pushes
           sit in the kernel's receive buffer and land late, all at once.
  dropped  `live` went false -- the player let the editor's document go and
           put the song's own back. New lines stop appearing until the editor
           notices and re-pushes.
  track    `tid` changed under the sync. With any_player on this is another
           program on the bus taking the window over.
  offset   `base` or the per-track part moved. The words are now drawn at a
           different time from the one they were stamped at.

READ-ONLY. It sends `state` and nothing else. `state`, `doc` and `source_doc`
are the three messages that only ask; `ttml`, `clear`, `seek` and `follow`
are the ones that do something, and none of them is sent from here. It
connects as a second client, which the player already supports -- the editor
keeps its own connection and is not disturbed.

One thing it CANNOT do is tell a stall from the player having been closed.
Both look like rows stopping. It says which when the socket also drops.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time

PORT = int(os.environ.get("MILD_LYRICS_LINK_PORT", "8778") or 8778)


def rows(sock: socket.socket, ask_every: float):
    """Every state row the player sends, as it arrives.

    Asked for as well as listened for. The announcements alone would do, but
    a `state` on a timer of our own means a stall shows up as this program's
    question going unanswered too, rather than only as the player having
    gone quiet -- the same fact, said by both halves.
    """
    buf = b""
    asked = 0.0
    sock.settimeout(0.2)
    while True:
        now = time.monotonic()
        if now - asked >= ask_every:
            asked = now
            try:
                sock.sendall(b'{"cmd":"state"}\n')
            except OSError:
                return
        try:
            got = sock.recv(65536)
        except socket.timeout:
            yield None
            continue
        except OSError:
            return
        if not got:
            return
        buf += got
        while b"\n" in buf:
            row, buf = buf.split(b"\n", 1)
            text = row.decode("utf-8", "replace").strip()
            if not text:
                continue
            try:
                msg = json.loads(text)
            except ValueError:
                continue
            if isinstance(msg, dict) and "pos" in msg:
                yield msg


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--seconds", type=float, default=0.0,
                    help="stop after this long (default: until ctrl-c)")
    ap.add_argument("--stall", type=float, default=0.75,
                    help="a gap this long between rows is called a stall. The "
                         "player promises one every 0.5s, so the default "
                         "leaves half a beat of slack (default: 0.75)")
    ap.add_argument("--log", default="",
                    help="write every row here as JSON lines, for reading "
                         "afterwards")
    args = ap.parse_args()

    try:
        sock = socket.create_connection(("127.0.0.1", args.port), 3)
    except OSError as exc:
        print(f"no player on 127.0.0.1:{args.port} — is Mild Lyrics running? "
              f"({exc})", file=sys.stderr)
        return 1

    out = open(args.log, "w", encoding="utf-8") if args.log else None
    began = time.monotonic()
    print(f"watching the link on :{args.port} — read-only. ctrl-c to stop.")

    last = time.monotonic()
    was: dict = {}
    seen = 0
    worst = 0.0
    counts = {"stall": 0, "dropped": 0, "track": 0, "offset": 0}

    def say(kind: str, text: str) -> None:
        counts[kind] = counts.get(kind, 0) + 1
        print(f"{time.strftime('%H:%M:%S')}  +{time.monotonic()-began:7.1f}s  "
              f"{kind:<8}{text}", flush=True)

    try:
        for msg in rows(sock, ask_every=0.2):
            now = time.monotonic()
            gap = now - last
            if gap > args.stall:
                worst = max(worst, gap)
                say("stall", f"no word from the player for {gap:.2f}s — it was "
                             f"neither drawing nor reading the editor's socket")
            if msg is None:
                continue
            last = now
            seen += 1
            if out is not None:
                out.write(json.dumps({"at": round(now - began, 3), **msg}) + "\n")
                out.flush()
            if was:
                if was.get("live") and not msg.get("live"):
                    say("dropped", f"the player let the editor's document go "
                                   f"(track {msg.get('tid') or '—'}, "
                                   f"{msg.get('status')})")
                if was.get("tid") != msg.get("tid"):
                    say("track", f"{was.get('title') or '—'} → "
                                 f"{msg.get('title') or '—'}")
                for field in ("base", "track"):
                    a, b = float(was.get(field, 0.0)), float(msg.get(field, 0.0))
                    if abs(a - b) > 0.002:
                        say("offset", f"{field} {a:+.3f}s → {b:+.3f}s — the "
                                      f"words are drawn {b - a:+.3f}s from "
                                      f"where they were")
            was = msg
            if args.seconds and now - began >= args.seconds:
                break
    except KeyboardInterrupt:
        print()
    finally:
        sock.close()
        if out is not None:
            out.close()

    ran = time.monotonic() - began
    print(f"\n{seen} rows in {ran:.0f}s "
          f"({seen / ran if ran else 0:.1f}/s; the player promises 2/s)")
    for kind, n in counts.items():
        print(f"  {kind:<9}{n}")
    if counts["stall"]:
        print(f"  worst gap {worst:.2f}s")
    if out is not None:
        print(f"  rows written to {args.log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
