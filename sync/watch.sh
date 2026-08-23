#!/bin/bash
# What the overnight run is doing, and whether it is still alive.
#
#   ./sync/watch.sh
#
# Written because "is it still going?" and "did it break?" look identical from
# outside: a run whose log has not moved in an hour is either fetching a slow
# song or dead, and the difference is the mtime of the log plus whether the
# process is still there.
S=/tmp/claude-1000/-home-gc-mild-lyrics/06b4cb69-57af-4caa-80a9-c08ef5cf8fde/scratchpad
LOG=$S/overnight.log
now=$(date +%s)

# Anchored to the interpreter, because `pgrep -f` searches whole command lines
# and this script's own name appears in the command line of whatever shell is
# running it -- the first version of this reported "benching" while the data
# pass was running, having matched the very command that wrote the file.
running() { pgrep -f "^[^ ]*python3(\.[0-9]+)? -m sync\.sync $1" >/dev/null; }
phase="idle"
running dataset && phase="cutting clips"
running train   && phase="training"
running bench   && phase="benching"
pgrep -f "bash .*overnight\.sh" >/dev/null || phase="$phase (chain has exited)"
echo "phase:    $phase"

if [ -f "$LOG" ]; then
    age=$(( now - $(stat -c %Y "$LOG") ))
    printf 'log:      %s, last written %dm %ds ago' "$LOG" $((age/60)) $((age%60))
    [ "$age" -gt 1800 ] && printf '   <-- STALLED?'
    echo
fi

echo "sleep:    $(systemd-inhibit --list 2>/dev/null | grep -c 'mild-lyrics') inhibitor(s) held"
echo "gpu:      $(nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader)"
echo "disk:     $(df -h /home | awk 'NR==2{print $4" free"}')"

python3 - <<'PY'
import json, pathlib
H = pathlib.Path.home() / ".cache/mild-lyrics/sync"
try:
    rows = [json.loads(l) for l in (H/"dataset/manifest.jsonl").read_text().splitlines()]
    seen = {r["tid"]: r for r in rows}
    clips = sum(len(r["lines"]) for r in seen.values())
    secs = sum(c["secs"] for r in seen.values() for c in r["lines"])
    print(f"dataset:  {len(seen)} songs, {clips} clips, {secs/3600:.1f} hours "
          f"({sum(1 for r in seen.values() if r.get('recut'))} re-cut)")
except Exception as exc:
    print(f"dataset:  unreadable ({type(exc).__name__})")
for name in ("syncnet-v2.pt", "syncnet-boundary.pt"):
    p = H / name
    if not p.exists():
        print(f"{name:20} not written yet")
        continue
    try:
        import torch
        got = torch.load(p, map_location="cpu", weights_only=False)
        last = (got.get("history") or [{}])[-1]
        print(f"{name:20} step {got.get('step')}, loss {last.get('loss')}, "
              f"held {last.get('held')}, heard {last.get('heard')}")
    except Exception as exc:
        print(f"{name:20} unreadable ({type(exc).__name__})")
PY

echo "--- last lines"
grep -vE "^\s*$|Warning" "$LOG" 2>/dev/null | tail -6
bad=$(grep -cE "Traceback|CUDA out of memory|Killed|SystemExit|No such file" "$LOG" 2>/dev/null)
[ "${bad:-0}" -gt 0 ] && { echo "--- $bad error line(s):"; grep -E "Traceback|CUDA out of memory|Killed|SystemExit|No such file" "$LOG" | tail -3; }
exit 0
