"""Publish a plugin to the marketplace: zip its folder into ART, list it.

    python publish.py <plugin folder> [--local] [--dry-run]
    python publish.py --remove <id> [--local]

Submissions from other people (POST /plugins/submit) wait unlisted:

    python publish.py --pending              what is waiting
    python publish.py --fetch <submission>   unpack it for review, never run
    python publish.py --approve <submission> publish what --fetch unpacked
    python publish.py --reject <submission>

Needs `npx wrangler login` once. A version, once published, is never
replaced: bump plugin.json's version to publish again. --local writes into
`npx wrangler dev`'s own store instead of the live one.
"""

from __future__ import annotations

import argparse
import datetime
import difflib
import hashlib
import io
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "mild-lyrics"))
import plugins as PL  # noqa: E402

INDEX = "plugins/index.json"
SUBMISSIONS = "submissions/"
SUB_RE = re.compile(r"[0-9a-z]{1,12}-[0-9a-f]{8}")
# Submissions are unpacked here, outside the checkout, and only ever read.
REVIEW = pathlib.Path.home() / ".cache" / "mild-lyrics-review"
UNPACKED_MAX = 50 * 1024 * 1024
NATIVE = (".so", ".pyd", ".dll", ".dylib", ".exe", ".bin")
URL_RE = re.compile(r"""https?://[^\s'"<>)\]]+""")
# Optional plugin.json fields carried into the listing as they are.
EXTRA = ("author", "homepage")


def wrangler(*args: str, where: str) -> subprocess.CompletedProcess:
    cmd = ["npx", "--no-install", "wrangler", "kv", "key", *args,
           "--binding", "ART", f"--{where}"]
    return subprocess.run(cmd, cwd=HERE, capture_output=True, text=True)


def get(key: str, where: str) -> bytes | None:
    """A key's value, or None when it is not there."""
    with tempfile.TemporaryDirectory() as tmp:
        out = pathlib.Path(tmp) / "v"
        cmd = ["npx", "--no-install", "wrangler", "kv", "key", "get", key,
               "--binding", "ART", f"--{where}"]
        with out.open("wb") as f:
            r = subprocess.run(cmd, cwd=HERE, stdout=f, stderr=subprocess.PIPE,
                               text=False)
        body = out.read_bytes()
    if r.returncode != 0 or body.strip() == b"Value not found":
        return None
    return body


def put(key: str, data: bytes, where: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        f = pathlib.Path(tmp) / "v"
        f.write_bytes(data)
        r = wrangler("put", key, "--path", str(f), where=where)
    if r.returncode != 0:
        sys.exit(f"wrangler could not write {key}:\n{r.stderr.strip()}")


def load_index(where: str) -> dict:
    raw = get(INDEX, where)
    if raw is None:
        return {"format": 1, "plugins": []}
    try:
        index = json.loads(raw)
    except ValueError:
        sys.exit(f"{INDEX} in ART is not JSON; fix it by hand first")
    if not isinstance(index.get("plugins"), list):
        sys.exit(f"{INDEX} in ART has no plugins list")
    return index


def save_index(index: dict, where: str) -> None:
    index["plugins"].sort(key=lambda e: e["name"].lower())
    put(INDEX, json.dumps(index, indent=1).encode(), where)


def publish(folder: pathlib.Path, where: str, dry: bool) -> None:
    try:
        m = PL._read_manifest(folder)
    except ValueError as e:
        sys.exit(f"{folder}: {e}")
    pid, version = m["id"], str(m.get("version") or "")
    if not PL.VERSION_RE.fullmatch(version):
        sys.exit(f"{pid}: version {version!r} -- digits, letters, . + - only")
    data = PL.pack(folder, pid)
    sha = hashlib.sha256(data).hexdigest()
    key = f"plugins/{pid}/{version}.zip"
    entry = {"id": pid, "name": str(m.get("name") or pid), "version": version,
             "api": int(m.get("api", 1)),
             "description": str(m.get("description") or ""),
             "permissions": PL.permissions(m),
             "zip": key, "size": len(data), "sha256": sha,
             "published": datetime.date.today().isoformat()}
    entry.update({k: str(m[k]) for k in EXTRA if m.get(k)})
    if dry:
        out = HERE / f"{pid}-{version}.zip"
        out.write_bytes(data)
        print(json.dumps(entry, indent=1))
        print("zip written to", out, "-- nothing published")
        return
    there = get(key, where)
    if there is not None and hashlib.sha256(there).hexdigest() != sha:
        sys.exit(f"{pid} {version} is already published with other files; "
                 "bump the version in plugin.json")
    if there is None:
        put(key, data, where)
    index = load_index(where)
    index["plugins"] = [e for e in index["plugins"] if e.get("id") != pid]
    index["plugins"].append(entry)
    save_index(index, where)
    print(f"published {pid} {version} ({len(data)} bytes, sha256 {sha[:12]}…)")


def remove(pid: str, where: str) -> None:
    index = load_index(where)
    left = [e for e in index["plugins"] if e.get("id") != pid]
    if len(left) == len(index["plugins"]):
        sys.exit(f"{pid} is not listed")
    index["plugins"] = left
    save_index(index, where)
    print(f"{pid} delisted; its zips stay, so installs keep their files")


def sub_id(s: str) -> str:
    if not SUB_RE.fullmatch(s):
        sys.exit(f"{s!r} is not a submission id (see --pending)")
    return s


def pending(where: str) -> None:
    r = subprocess.run(["npx", "--no-install", "wrangler", "kv", "key", "list",
                        "--prefix", SUBMISSIONS, "--binding", "ART", f"--{where}"],
                       cwd=HERE, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"wrangler could not list submissions:\n{r.stderr.strip()}")
    keys = json.loads(r.stdout or "[]")
    if not keys:
        print("nothing waiting")
    listed = {e["id"]: e for e in load_index(where)["plugins"]} if keys else {}
    for k in keys:
        m = k.get("metadata") or {}
        sid = k["name"][len(SUBMISSIONS):].removesuffix(".zip")
        was = listed.get(m.get("id"))
        note = f"  UPDATE to listed {was['version']}" if was else "  new"
        print(f"{sid}  {m.get('id')} {m.get('version')}  {m.get('size')} bytes  "
              f"{m.get('at', '')[:16]}{note}")


def _unpack(data: bytes, into: pathlib.Path) -> pathlib.Path:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        if sum(i.file_size for i in z.infolist()) > UNPACKED_MAX:
            sys.exit("unpacks to more than 50 MB; reject it")
    tmp = into.with_suffix(".zip")
    tmp.write_bytes(data)
    try:
        return PL._unpacked(tmp, into)
    finally:
        tmp.unlink()


def _report(folder: pathlib.Path, old: pathlib.Path | None) -> str:
    """What a reviewer should look at first."""
    lines, urls = [], set()
    for f in PL.pack_files(folder):
        rel = f.relative_to(folder).as_posix()
        flag = "  NATIVE CODE" if f.name.endswith(NATIVE) else ""
        lines.append(f"  {rel}  {f.stat().st_size} bytes{flag}")
        try:
            urls.update(URL_RE.findall(f.read_text(encoding="utf-8")))
        except (UnicodeDecodeError, OSError):
            pass
    m = PL._read_manifest(folder)
    out = ["asks to:", *(f"  {x}" for x in PL.describe(m)),
           "files:", *lines, "addresses it names:", *(f"  {u}" for u in sorted(urls))]
    if old is None:
        return "\n".join(out)
    a = {f.relative_to(old).as_posix(): f for f in PL.pack_files(old)}
    b = {f.relative_to(folder).as_posix(): f for f in PL.pack_files(folder)}
    diff = []
    for rel in sorted(a.keys() | b.keys()):
        try:
            x = a[rel].read_text(encoding="utf-8").splitlines() if rel in a else []
            y = b[rel].read_text(encoding="utf-8").splitlines() if rel in b else []
        except UnicodeDecodeError:
            if rel not in a or rel not in b or a[rel].read_bytes() != b[rel].read_bytes():
                diff.append(f"binary {rel} differs")
            continue
        diff.extend(difflib.unified_diff(x, y, f"listed/{rel}", f"submitted/{rel}",
                                         lineterm=""))
    return "\n".join(out + ["changes from the listed version:", *diff])


def fetch(sid: str, where: str) -> None:
    data = get(f"{SUBMISSIONS}{sid}.zip", where)
    if data is None:
        sys.exit(f"no submission {sid}")
    root = REVIEW / sid
    shutil.rmtree(root, ignore_errors=True)
    (root / "submitted").mkdir(parents=True)
    try:
        folder = _unpack(data, root / "submitted")
        m = PL._read_manifest(folder)
    except (ValueError, zipfile.BadZipFile) as e:
        sys.exit(f"{sid} is not a plugin: {e}; reject it")
    old = None
    was = {e["id"]: e for e in load_index(where)["plugins"]}.get(m["id"])
    if was:
        listed = get(was["zip"], where)
        if listed is not None:
            (root / "listed").mkdir()
            old = _unpack(listed, root / "listed")
    report = _report(folder, old)
    (root / "report.txt").write_text(report + "\n", encoding="utf-8")
    print(f"{m['id']} {m.get('version')} -- {m.get('name')}"
          f"{' by ' + m['author'] if m.get('author') else ''}")
    if was:
        print(f"UPDATES the listed {was['id']} {was['version']}: is it the same author?")
    print(report if len(report) < 6000 else report[:6000] + "\n…")
    print(f"\nunpacked in {folder}\nreport in {root / 'report.txt'}")
    print("Read it; do not run it outside a sandbox. Then --approve or --reject.")


def approve(sid: str, where: str) -> None:
    got = [d for d in (REVIEW / sid / "submitted").glob("**/plugin.json")]
    if len(got) != 1:
        sys.exit(f"fetch and read {sid} first (--fetch {sid})")
    data = get(f"{SUBMISSIONS}{sid}.zip", where)
    if data is None:
        sys.exit(f"no submission {sid} any more")
    publish(got[0].parent, where, False)
    reject(sid, where, said="approved and removed from the queue")


def reject(sid: str, where: str, said: str = "rejected") -> None:
    r = wrangler("delete", f"{SUBMISSIONS}{sid}.zip", where=where)
    if r.returncode != 0:
        sys.exit(f"wrangler could not delete {sid}:\n{r.stderr.strip()}")
    print(f"{sid} {said}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("folder", nargs="?", type=pathlib.Path)
    ap.add_argument("--remove", metavar="ID")
    ap.add_argument("--pending", action="store_true")
    ap.add_argument("--fetch", metavar="SUBMISSION")
    ap.add_argument("--approve", metavar="SUBMISSION")
    ap.add_argument("--reject", metavar="SUBMISSION")
    ap.add_argument("--local", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    where = "local" if a.local else "remote"
    if a.remove:
        remove(a.remove, where)
    elif a.pending:
        pending(where)
    elif a.fetch:
        fetch(sub_id(a.fetch), where)
    elif a.approve:
        approve(sub_id(a.approve), where)
    elif a.reject:
        reject(sub_id(a.reject), where)
    elif a.folder:
        publish(a.folder.resolve(), where, a.dry_run)
    else:
        ap.error("a plugin folder, --remove, --pending, --fetch, --approve "
                 "or --reject")


if __name__ == "__main__":
    main()
