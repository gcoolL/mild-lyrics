"""Timing one lyric together: what travels, who holds what, and who decides.

Nothing here knows about Qt or the network. The window hands it documents and
messages; it hands back messages to send and changes to apply. That is what
lets two and three people be tested in one process with a list for a wire.

THE SHAPE. One person hosts and is the authority. Everybody else's edits go
to the host, which checks them against who holds what, applies them to the
one true document and tells everyone -- the sender too -- what happened.

WHAT AN EDIT IS. The editor changes its document in place, in some three
thousand lines of operations, and nothing about that is going to grow a patch
format. So an edit here is a DIFF: the document now against the document as
last agreed (`shared`), line by line, by each line's uid. A line that changed
is sent whole. A song is a few hundred lines at most, and comparing them is
dataclass equality, which costs less than one repaint.

    set    {o:"set", u:uid, l:line}   a line, new or changed, whole
    del    {o:"del", u:uid}
    order  {o:"order", u:[uid...]}    every line, in order -- only on a move
    meta   {o:"meta", m:{...}}        the header: title, artist, writers
    parts  {o:"parts", p:[...]}       the grouped runs (Doc.parts)

WHO HOLDS WHAT. A line is held by whoever's cursor or selection is on it, and
by whoever has claimed it (a chorus, say) until they let it go. A held line
can only be changed by its holder. An edit that would change anyone else's
line is not partly applied: it is undone whole, here and at the host, so
nobody is ever left with half of a merge.

WHY NOTHING BUT JSON. A peer is somebody else's program. What arrives is
checked field by field against hard limits before it becomes a single
syllable; there is no TTML on the wire, so no XML parser ever sees a peer's
bytes, and there is no message that names a file, a setting, the audio or the
player. The worst a peer can do is change the lines nobody else holds.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time

from . import model as M

PROTO = 1

# Hard limits on what a peer may send. Generous for any real song -- the
# longest in the test corpus is 240 lines -- and small enough that a hostile
# message cannot make the editor do real work.
MAX_LINES = 3000
MAX_SYLS = 400
MAX_BG = 8
MAX_TEXT = 200
MAX_ROMAN = 400
MAX_TIME = 86400.0
MAX_META_KEYS = 32
MAX_META_STR = 300
MAX_META_LIST = 40
MAX_PARTS = 200
MAX_PART_LINES = 64
MAX_PART_WORDS = 64
MAX_OPS = 4 * MAX_LINES + 8
MAX_NAME = 32
MAX_PEERS = 8
STRIKES = 3
MAX_NOTE = 300
MAX_NOTES_LINE = 20
MAX_NOTES = 500

UID = re.compile(r"[0-9a-f]{12}\Z")
# A hold on one word, in "hold single words" mode: line uid / voice / word.
WORD_KEY = re.compile(r"([0-9a-f]{12})/(\d{1,2})/(\d{1,4})\Z")
AGENT = re.compile(r"v\d{1,2}\Z")
META_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,31}\Z")
# Taken out of anything a peer names or says before it is shown. The status
# line and the toasts are QLabels, which take a string that looks like markup
# AS markup -- so a name cannot carry < > or &, and can never be a tag.
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u200b-\u200f\u2028-\u202e\u2066-\u2069<>&]")

COLOURS = ["#5ec8ff", "#ff8a5e", "#9be36c", "#e58cff", "#ffd45e",
           "#5effc8", "#ff5e9a", "#a0a8ff"]


class Bad(ValueError):
    """What a peer sent is not something this protocol would ever send."""


# --------------------------------------------------------------- the wire
def _num(x, what: str) -> float | None:
    if x is None:
        return None
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise Bad(f"{what}: not a number")
    x = float(x)
    if not math.isfinite(x) or not 0.0 <= x <= MAX_TIME:
        raise Bad(f"{what}: out of range")
    return x


def _str(x, cap: int, what: str) -> str:
    if not isinstance(x, str):
        raise Bad(f"{what}: not text")
    if len(x) > cap:
        raise Bad(f"{what}: too long")
    return x


def _list(x, cap: int, what: str) -> list:
    if not isinstance(x, list):
        raise Bad(f"{what}: not a list")
    if len(x) > cap:
        raise Bad(f"{what}: too many")
    return x


def _uid(x) -> str:
    if not isinstance(x, str) or not UID.match(x):
        raise Bad("uid")
    return x


def group_out(g: M.Group) -> dict:
    return {"r": g.roman, "i": g.lead_in,
            "y": [[s.text, s.start, s.end, s.part, s.roman] for s in g.syls]}


def group_in(obj) -> M.Group:
    if not isinstance(obj, dict):
        raise Bad("group")
    syls = []
    for row in _list(obj.get("y"), MAX_SYLS, "syllables"):
        if not isinstance(row, list) or len(row) != 5:
            raise Bad("syllable")
        text, start, end, part, roman = row
        if not isinstance(part, bool):
            raise Bad("syllable join")
        syls.append(M.Syl(_str(text, MAX_TEXT, "text"), _num(start, "start"),
                          _num(end, "end"), part,
                          _str(roman, MAX_ROMAN, "reading")))
    lead_in = obj.get("i")
    if not isinstance(lead_in, bool):
        raise Bad("lead_in")
    return M.Group(syls, lead_in, _str(obj.get("r"), MAX_ROMAN, "reading"))


def line_out(ln: M.Line) -> dict:
    return {"a": ln.agent, "s": ln.start, "e": ln.end,
            "l": group_out(ln.lead), "b": [group_out(g) for g in ln.bg]}


def line_in(obj, uid: str) -> M.Line:
    if not isinstance(obj, dict):
        raise Bad("line")
    agent = obj.get("a")
    if not isinstance(agent, str) or not AGENT.match(agent):
        raise Bad("agent")
    bg = [group_in(g) for g in _list(obj.get("b"), MAX_BG, "backing")]
    return M.Line(group_in(obj.get("l")), bg, agent, _num(obj.get("s"), "start"),
                  _num(obj.get("e"), "end"), _uid(uid))


def meta_in(obj) -> dict:
    if not isinstance(obj, dict) or len(obj) > MAX_META_KEYS:
        raise Bad("meta")
    out = {}
    for k, v in obj.items():
        if not isinstance(k, str) or not META_KEY.match(k):
            raise Bad("meta key")
        if v is None or isinstance(v, bool):
            out[k] = v
        elif isinstance(v, (int, float)):
            if not math.isfinite(float(v)):
                raise Bad("meta number")
            out[k] = v
        elif isinstance(v, str):
            out[k] = _str(v, MAX_META_STR, "meta")
        elif isinstance(v, list):
            out[k] = [_str(x, MAX_META_STR, "meta")
                      for x in _list(v, MAX_META_LIST, "meta")]
        else:
            raise Bad("meta value")
    return out


def meta_out(meta: dict) -> dict:
    """The header as it can travel. A value the protocol would refuse from a
    peer is not sent either -- it stays in this editor's own copy."""
    out = {}
    for k, v in meta.items():
        try:
            out.update(meta_in({k: list(v) if isinstance(v, tuple) else v}))
        except Bad:
            continue
    return out


def parts_in(obj) -> list:
    out = []
    for part in _list(obj, MAX_PARTS, "parts"):
        lines = []
        for words in _list(part, MAX_PART_LINES, "part"):
            lines.append(tuple(_str(w, MAX_TEXT, "part word")
                               for w in _list(words, MAX_PART_WORDS, "part line")))
        out.append(tuple(lines))
    return out


def parts_out(parts: list) -> list:
    return [[list(words) for words in part] for part in parts]


def doc_out(doc: M.Doc) -> dict:
    return {"lines": [[ln.uid, line_out(ln)] for ln in doc.lines],
            "meta": meta_out(doc.meta), "parts": parts_out(doc.parts)}


def doc_in(obj) -> M.Doc:
    if not isinstance(obj, dict):
        raise Bad("document")
    lines, seen = [], set()
    for row in _list(obj.get("lines"), MAX_LINES, "lines"):
        if not isinstance(row, list) or len(row) != 2:
            raise Bad("line row")
        ln = line_in(row[1], row[0])
        if ln.uid in seen:
            raise Bad("uid twice")
        seen.add(ln.uid)
        lines.append(ln)
    return M.Doc(lines, meta_in(obj.get("meta")), parts_in(obj.get("parts")))


def ops_in(raw) -> list[dict]:
    """A peer's list of operations, checked and rebuilt -- never passed on as
    it came, so a field the protocol does not have cannot ride along."""
    out = []
    for op in _list(raw, MAX_OPS, "ops"):
        if not isinstance(op, dict):
            raise Bad("op")
        kind = op.get("o")
        if kind == "set":
            uid = _uid(op.get("u"))
            line_in(op.get("l"), uid)
            got = {"o": "set", "u": uid, "l": op["l"]}
            if op.get("b") is not None:
                line_in(op["b"], uid)
                got["b"] = op["b"]
            if op.get("m") is True:
                got["m"] = True
            out.append(got)
        elif kind == "del":
            out.append({"o": "del", "u": _uid(op.get("u"))})
        elif kind == "order":
            uids = [_uid(u) for u in _list(op.get("u"), MAX_LINES, "order")]
            if len(set(uids)) != len(uids):
                raise Bad("order: uid twice")
            out.append({"o": "order", "u": uids})
        elif kind == "meta":
            out.append({"o": "meta", "m": meta_in(op.get("m"))})
        elif kind == "parts":
            out.append({"o": "parts", "p": parts_out(parts_in(op.get("p")))})
        else:
            raise Bad("op kind")
    return out


YT_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")
SC_PART = re.compile(r"[A-Za-z0-9_-]{1,100}\Z")
SPOTIFY_ID = re.compile(r"[A-Za-z0-9]{22}\Z")


def song_url(url) -> str:
    """A link a joiner's editor may download the song from, rebuilt from its
    bare id -- or '' for anything else.

    Only a YouTube video or a SoundCloud track, and never the string the
    host sent: a host is somebody else's program, and what the joiner's
    downloader is pointed at must not be theirs to choose. Everything that
    is not one of these two shapes is dropped, and the joiner searches for
    the song by name and length instead.
    """
    if not isinstance(url, str) or len(url) > 300:
        return ""
    try:
        from urllib.parse import parse_qs, urlsplit
        u = urlsplit(url.strip())
    except ValueError:
        return ""
    host = (u.hostname or "").lower()
    if u.scheme not in ("https", "http"):
        return ""
    if host in ("youtube.com", "www.youtube.com", "m.youtube.com",
                "music.youtube.com") and u.path == "/watch":
        vid = (parse_qs(u.query).get("v") or [""])[0]
        return f"https://www.youtube.com/watch?v={vid}" if YT_ID.match(vid) else ""
    if host == "youtu.be":
        vid = u.path.strip("/")
        return f"https://www.youtube.com/watch?v={vid}" if YT_ID.match(vid) else ""
    if host in ("soundcloud.com", "www.soundcloud.com", "m.soundcloud.com"):
        parts = [x for x in u.path.split("/") if x]
        if len(parts) == 2 and all(SC_PART.match(x) for x in parts) \
                and parts[0] not in ("search", "discover", "you", "stream"):
            return f"https://soundcloud.com/{parts[0]}/{parts[1]}"
    return ""


def song_in(msg) -> dict:
    """What the host is timing against, checked: which upload (if it came
    from one), the names to search by otherwise, and how long it is."""
    if not isinstance(msg, dict):
        raise Bad("song")
    dur = _num(msg.get("dur") or 0.0, "song length") or 0.0
    tid = msg.get("tid") if isinstance(msg.get("tid"), str) and \
        SPOTIFY_ID.match(msg.get("tid")) else ""
    return {"url": song_url(msg.get("url")),
            "title": _plain(msg.get("title"), MAX_META_STR),
            "artist": _plain(msg.get("artist"), MAX_META_STR),
            "dur": dur, "tid": tid}


def note_text(x) -> str:
    """A note as it may be kept and shown: plain, one paragraph, short."""
    if not isinstance(x, str):
        raise Bad("note")
    x = " ".join(CONTROL.sub(" ", x.replace("<", "‹").replace(">", "›")
                             .replace("&", "+")).split())
    if not x:
        raise Bad("empty note")
    return x[:MAX_NOTE]


def notes_in(raw) -> list[dict]:
    out = []
    for n in _list(raw, MAX_NOTES_LINE, "notes"):
        if not isinstance(n, dict):
            raise Bad("note")
        i, by = n.get("i"), n.get("by")
        if not isinstance(i, int) or isinstance(i, bool) or \
                not isinstance(by, int) or isinstance(by, bool):
            raise Bad("note id")
        out.append({"i": i, "by": by, "n": clean_name(n.get("n")),
                    "x": note_text(n.get("x"))})
    return out


def clean_name(x) -> str:
    """A name as it may be shown: plain text, one line, short."""
    if not isinstance(x, str):
        return "someone"
    x = CONTROL.sub("", x).strip()[:MAX_NAME].strip()
    return x or "someone"


# ----------------------------------------------------------- diff & apply
def diff(old: M.Doc, new: M.Doc) -> list[dict]:
    """What turns `old` into `new`, as operations."""
    ops = []
    before = {ln.uid: ln for ln in old.lines}
    now = {ln.uid for ln in new.lines}
    for ln in new.lines:
        was = before.get(ln.uid)
        if was is None or was != ln:
            ops.append({"o": "set", "u": ln.uid, "l": line_out(ln)})
    for uid in before:
        if uid not in now:
            ops.append({"o": "del", "u": uid})
    order = [ln.uid for ln in new.lines]
    if order != [ln.uid for ln in old.lines]:
        ops.append({"o": "order", "u": order})
    if meta_out(new.meta) != meta_out(old.meta):
        ops.append({"o": "meta", "m": meta_out(new.meta)})
    if list(new.parts) != list(old.parts):
        ops.append({"o": "parts", "p": parts_out(new.parts)})
    return ops


def adopt(shared: M.Doc, doc: M.Doc) -> None:
    """Give a line rebuilt as a new object its old uid back, if it is word
    for word and time for time the line it replaced.

    Some operations build every line afresh rather than change the ones
    there. Without this, each of those reads as every line deleted and made
    again -- which touches every line anyone holds, and is refused.
    """
    have = {ln.uid for ln in doc.lines}
    gone: dict[str, list[str]] = {}
    for ln in shared.lines:
        if ln.uid not in have:
            gone.setdefault(_key(ln), []).append(ln.uid)
    if not gone:
        return
    known = {ln.uid for ln in shared.lines}
    for ln in doc.lines:
        if ln.uid not in known:
            got = gone.get(_key(ln))
            if got:
                ln.uid = got.pop(0)


def _key(ln: M.Line) -> str:
    return json.dumps(line_out(ln), sort_keys=True)


def _shape(ln: M.Line):
    """What has to be the same for two versions of a line to be merged word
    by word: its voices, their syllable counts, where the words break."""
    return (ln.agent, len(ln.bg),
            tuple((len(g.syls), tuple(s.part for s in g.syls), g.lead_in)
                  for g in ln.groups()))


def changed_words(old: M.Line, new: M.Line):
    """{(voice, word)} that differ between two versions of a line, or None
    when the line itself was reshaped -- words split, joined, added."""
    if _shape(old) != _shape(new):
        return None
    out = set()
    for v, (a, b) in enumerate(zip(old.groups(), new.groups())):
        if a.roman != b.roman:
            out.update((v, w) for w in range(len(b.words())))
            continue
        for w, run in enumerate(b.words()):
            if any(a.syls[k] != b.syls[k] for k in run):
                out.add((v, w))
    if (old.start, old.end) != (new.start, new.end) and not out:
        # Only the line's own frame moved: it belongs to no one word.
        out.add((0, 0))
    return out


def merge_line(base: M.Line, theirs: M.Line, now: M.Line) -> M.Line | None:
    """`now` with the words `theirs` changed from `base` taken from theirs.
    None when the three are not the same shape, or both sides changed the
    same word -- then it is refused, never guessed at."""
    mine = changed_words(base, theirs)
    other = changed_words(base, now)
    if mine is None or other is None or mine & other:
        return None
    out = M._line(now)
    for v, (tg, og) in enumerate(zip(theirs.groups(), out.groups())):
        for w, run in enumerate(tg.words()):
            if (v, w) in mine:
                for k in run:
                    og.syls[k] = M._syl(tg.syls[k])
    if (base.start, base.end) != (theirs.start, theirs.end):
        out.start, out.end = theirs.start, theirs.end
    return out


def blocking(owner: dict, me, ops: list[dict], shared: M.Doc) -> dict:
    """The holds of other people these ops would break: a held line touched
    at all, or a held word whose syllables change -- or any held word on a
    line that is reshaped or deleted."""
    lines = {ln.uid: ln for ln in shared.lines}
    words: dict[str, dict] = {}
    for k, pid in owner.items():
        m = WORD_KEY.match(k)
        if m and pid != me:
            words.setdefault(m.group(1), {})[k] = pid
    out = {}
    for op in ops:
        if op["o"] not in ("set", "del"):
            continue
        u = op["u"]
        if u in owner and owner[u] != me:
            out[u] = owner[u]
            continue
        held = words.get(u)
        if not held:
            continue
        old = lines.get(u)
        if op["o"] == "del" or old is None:
            out.update(held)
            continue
        base = line_in(op["b"], u) if op.get("b") is not None else old
        changed = changed_words(base, line_in(op["l"], u))
        if changed is None:
            out.update(held)
            continue
        for k, pid in held.items():
            m = WORD_KEY.match(k)
            if (int(m.group(2)), int(m.group(3))) in changed:
                out[k] = pid
    return out


def word_key(doc: M.Doc, uid: str, voice: int, syl: int) -> str | None:
    """The hold key for the word a cursor is on."""
    for ln in doc.lines:
        if ln.uid == uid:
            gs = ln.groups()
            if not 0 <= voice < len(gs):
                return None
            for w, run in enumerate(gs[voice].words()):
                if syl in run:
                    return f"{uid}/{voice}/{w}"
            return None
    return None


def touched(ops: list[dict]) -> set[str]:
    """The lines an edit changes or removes. Moving a line is not changing
    it: somebody inserting a verse above your chorus does not touch it."""
    return {op["u"] for op in ops if op["o"] in ("set", "del")}


def structural(ops: list[dict]) -> bool:
    """Whether lines came, went or moved -- which is when anything that
    remembers a line by its NUMBER has to be told where it went."""
    return any(op["o"] in ("del", "order") for op in ops)


def reorder(lines: list, order: list[str]) -> list:
    """`lines` in `order`, keeping any line the order does not name just
    after the line it followed before -- an undo snapshot can hold a line of
    yours that the rest of the session has not heard of yet."""
    by = {ln.uid: ln for ln in lines}
    out = [by[u] for u in order if u in by]
    placed = {ln.uid for ln in out}
    for i, ln in enumerate(lines):
        if ln.uid in placed:
            continue
        prev = next((lines[j].uid for j in range(i - 1, -1, -1)
                     if lines[j].uid in placed), None)
        at = 0 if prev is None else next(
            k for k, x in enumerate(out) if x.uid == prev) + 1
        out.insert(at, ln)
        placed.add(ln.uid)
    return out


def apply(doc: M.Doc, ops: list[dict]) -> None:
    """Make `ops` true of `doc`, in place. Safe on any document: the shared
    one, the one on screen, and every undo snapshot."""
    for op in ops:
        kind = op["o"]
        if kind == "set":
            ln = line_in(op["l"], op["u"])
            for i, have in enumerate(doc.lines):
                if have.uid == ln.uid:
                    doc.lines[i] = ln
                    break
            else:
                doc.lines.append(ln)
        elif kind == "del":
            doc.lines[:] = [ln for ln in doc.lines if ln.uid != op["u"]]
        elif kind == "order":
            doc.lines[:] = reorder(doc.lines, op["u"])
        elif kind == "meta":
            keep = {k: v for k, v in doc.meta.items()
                    if k not in meta_out({k: v})}
            doc.meta.clear()
            doc.meta.update(keep)
            doc.meta.update(op["m"])
        elif kind == "parts":
            doc.parts[:] = parts_in(op["p"])


def digest(doc: M.Doc) -> str:
    """One short string that two documents share only if they are the same.
    Sent with the host's changes now and then, so a joiner that has drifted
    -- however it did -- finds out and asks for the whole thing again."""
    raw = json.dumps(doc_out(doc), sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False)
    return hashlib.blake2b(raw.encode("utf-8"), digest_size=8).hexdigest()


def same_lines(a: M.Doc, b: M.Doc) -> bool:
    return ([ln.uid for ln in a.lines] == [ln.uid for ln in b.lines]
            and a.lines == b.lines)


# ------------------------------------------------------------------ locks
def timing(ln: M.Line) -> tuple:
    """Every time a line holds: what timing it changes."""
    return (ln.start, ln.end,
            tuple((x.start, x.end) for g in ln.groups() for x in g.syls))


def _any_time(t: tuple) -> bool:
    return t[0] is not None or t[1] is not None or any(
        a is not None or b is not None for a, b in t[2])


HEX = re.compile(r"#[0-9a-fA-F]{6}\Z")


def synced_in(raw) -> dict[str, dict]:
    """Who last timed each line, as the host says: uid -> {n, c}."""
    if raw is None:
        return {}
    if not isinstance(raw, dict) or len(raw) > MAX_LINES:
        raise Bad("synced")
    out = {}
    for u, v in raw.items():
        if not isinstance(v, dict):
            raise Bad("synced")
        c = v.get("c")
        out[_uid(u)] = {"n": clean_name(v.get("n")),
                        "c": c if isinstance(c, str) and HEX.match(c) else "#a0a8ff"}
    return out


class Locks:
    """Who holds which line, first come first served.

    `presence` is where each person IS -- cursor and selection -- and moves
    with them. `claims` are lines somebody asked to keep, and stay theirs
    until they let go or leave. A line held either way by one person is not
    given to another until it is free.
    """

    def __init__(self) -> None:
        self.owner: dict[str, int] = {}
        self.presence: dict[int, set[str]] = {}
        self.claims: dict[int, set[str]] = {}

    def holder(self, uid: str) -> int | None:
        return self.owner.get(uid)

    def held_by_others(self, pid: int, uids) -> dict[str, int]:
        return {u: self.owner[u] for u in uids
                if u in self.owner and self.owner[u] != pid}

    def _settle(self, pid: int) -> None:
        want = self.presence.get(pid, set()) | self.claims.get(pid, set())
        for u, who in list(self.owner.items()):
            if who == pid and u not in want:
                del self.owner[u]
        for u in want:
            self.owner.setdefault(u, pid)

    def set_presence(self, pid: int, uids) -> None:
        self.presence[pid] = set(uids)
        self._settle(pid)
        self._regrant()

    def claim(self, pid: int, uids) -> list[str]:
        """Claim what is free; return what somebody else already holds."""
        uids = set(uids)
        taken = [u for u in uids if self.owner.get(u, pid) != pid]
        self.claims.setdefault(pid, set()).update(u for u in uids
                                                 if u not in taken)
        self._settle(pid)
        return taken

    def release(self, pid: int, uids=None) -> None:
        mine = self.claims.setdefault(pid, set())
        if uids is None:
            mine.clear()
        else:
            mine.difference_update(uids)
        self._settle(pid)
        self._regrant()

    def drop(self, pid: int) -> None:
        self.presence.pop(pid, None)
        self.claims.pop(pid, None)
        self._settle(pid)
        self._regrant()

    def forget(self, uids) -> None:
        """Lines that no longer exist are nobody's."""
        uids = set(uids)
        dead = {k for k in self.owner if k.split("/")[0] in uids} | uids
        for k in dead:
            self.owner.pop(k, None)
        for s in (*self.presence.values(), *self.claims.values()):
            s.difference_update({k for k in s if k.split("/")[0] in uids})

    def _regrant(self) -> None:
        """Somebody let go: whoever else is on those lines gets them."""
        for pid in list(self.presence):
            self._settle(pid)
        for pid in list(self.claims):
            self._settle(pid)

    def share(self, plan: dict[int, set]) -> None:
        """Every claim replaced by `plan` (pid -> line uids): the host
        sharing the song out. A line given this way is theirs even where
        somebody else's cursor merely is; that cursor holds what it is on
        again once the line is let go."""
        self.claims = {pid: set(us) for pid, us in plan.items()}
        self.owner = {u: pid for pid, us in self.claims.items() for u in us}
        self._regrant()

    def table(self) -> dict[str, int]:
        return dict(self.owner)

    def claimed(self) -> dict[str, int]:
        return {u: pid for pid, us in self.claims.items() for u in us
                if self.owner.get(u) == pid}


def _who(held: dict[str, int], doc: M.Doc, names: dict[int, str]) -> str:
    """'line 12 is Sam's' -- the first of them, for the status bar."""
    at = {ln.uid: i for i, ln in enumerate(doc.lines)}
    key, pid = min(held.items(),
                   key=lambda kv: at.get(kv[0].split("/")[0], 1 << 30))
    row = at.get(key.split("/")[0])
    name = names.get(pid, "someone")
    more = f" (and {len(held) - 1} more)" if len(held) > 1 else ""
    if row is None:
        return f"a line {name} holds{more}"
    if "/" in key:
        return f"a word on line {row + 1} is {name}'s{more}"
    return f"line {row + 1} is {name}'s{more}"


# ------------------------------------------------------------------- host
class Host:
    """The authority. The host's own edits go through `local` like anybody's.

    Everything to be sent is put in `outbox` as (pid, message), pid None for
    everyone; the window drains it after every call.
    """

    role = "host"

    def __init__(self, doc: M.Doc, name: str) -> None:
        M.ensure_unique(doc)
        self.shared = doc.clone()
        self.me = 0
        self.rev = 0
        self.peers: dict[int, dict] = {0: {"n": clean_name(name),
                                           "c": COLOURS[0], "at": None}}
        self.locks = Locks()
        self.outbox: list[tuple[int | None, dict]] = []
        self.strikes: dict[int, int] = {}
        self._hashed_at = 0.0
        self.contributors: list[str] = []     # names, in order of first edit
        self.notes: dict[str, list[dict]] = {}  # line uid -> notes on it
        # Who last timed each line: uid -> {n: name, c: colour}. Kept by
        # name and colour, not id, so it outlives them leaving. The
        # session's, never the file's, as notes are.
        self.synced: dict[str, dict] = {}
        self._note_id = 0
        self.frozen = False       # only the host may edit while it is
        self.away: dict[int, dict] = {}       # dropped, and may come back
        self.hold_words = False   # True: a cursor holds its word, not its line
        self._sel: dict[int, list] = {}

    # -- people
    def names(self) -> dict[int, str]:
        return {pid: p["n"] for pid, p in self.peers.items()}

    def join(self, pid: int, hello: dict, watch: bool = False,
             back: int | None = None) -> bool:
        """`watch` comes from the invite they used, never from the hello.
        `back` is who they were before a dropped connection, said by the
        resume invite they came in on -- also never by the hello."""
        if len(self.peers) >= MAX_PEERS + 1 or pid in self.peers:
            return False
        was = self.away.pop(back, None) if back is not None else None
        used = {p["c"] for p in self.peers.values()}
        colour = next((c for c in COLOURS if c not in used), COLOURS[pid % 8])
        if was is not None and was["c"] not in used:
            colour = was["c"]
        self.peers[pid] = {"n": clean_name(hello.get("name")), "c": colour,
                           "at": None,
                           "ro": was["ro"] if was is not None else bool(watch)}
        if was is not None and was["claims"]:
            self.locks.claim(pid, [u for u in was["claims"]
                                   if u in {ln.uid for ln in self.shared.lines}])
        self.outbox.append((pid, {"t": "welcome", "you": pid, "rev": self.rev,
                                  "doc": doc_out(self.shared),
                                  "h": digest(self.shared),
                                  "notes": self.notes, "synced": self.synced}))
        self._tell_who()
        return True

    def step_away(self, pid: int) -> None:
        """Their connection dropped: they are gone for now, but who they
        were -- colour, role, the lines they claimed -- is kept for when
        they come back on their resume invite."""
        p = self.peers.get(pid)
        if p is None:
            return
        self.away[pid] = {"n": p["n"], "c": p["c"], "ro": p.get("ro", False),
                          "claims": set(self.locks.claims.get(pid, set()))}
        self.leave(pid)

    def leave(self, pid: int) -> None:
        if self.peers.pop(pid, None) is not None:
            self.locks.drop(pid)
            self.strikes.pop(pid, None)
            self._tell_who()

    def _tell_who(self) -> None:
        self.outbox.append((None, {"t": "who", "peers": {
            str(pid): p for pid, p in self.peers.items()},
            "locks": self.locks.table(), "claims": self.locks.claimed(),
            "frozen": self.frozen, "words": self.hold_words}))

    # -- what arrives
    def on_message(self, pid: int, msg) -> str | None:
        """Handle one message from a joiner. Returns a reason to disconnect
        them, or None."""
        if pid not in self.peers:
            return "not joined"
        try:
            if not isinstance(msg, dict):
                raise Bad("message")
            kind = msg.get("t")
            if kind == "ops":
                self._their_ops(pid, ops_in(msg.get("ops")), msg.get("n"))
            elif kind == "here":
                self.here(pid, msg.get("c"), msg.get("s"))
            elif kind == "claim":
                self.claim(pid, [_uid(u) for u in
                                 _list(msg.get("u"), MAX_LINES, "claim")])
            elif kind == "release":
                raw = msg.get("u")
                self.release(pid, None if raw is None else
                             [_uid(u) for u in _list(raw, MAX_LINES, "release")])
            elif kind == "name":
                self.rename(pid, msg.get("n"))
            elif kind == "note":
                self.note(pid, _uid(msg.get("u")), msg.get("x"))
            elif kind == "unnote":
                i = msg.get("i")
                if not isinstance(i, int) or isinstance(i, bool):
                    raise Bad("note id")
                self.unnote(pid, _uid(msg.get("u")), i)
            elif kind == "resync":
                self.outbox.append((pid, {"t": "state", "rev": self.rev,
                                          "doc": doc_out(self.shared),
                                          "h": digest(self.shared),
                                          "synced": self.synced}))
            elif kind == "bye":
                return "left"
            else:
                raise Bad("message kind")
        except Bad as e:
            self.strikes[pid] = self.strikes.get(pid, 0) + 1
            if self.strikes[pid] >= STRIKES:
                return f"sent nonsense ({e})"
        return None

    def may_edit(self, pid: int) -> str:
        """'' if this person may change the lyric now, else why not."""
        if pid != 0 and self.peers.get(pid, {}).get("ro"):
            return "you can watch this session but not edit it"
        if pid != 0 and self.frozen:
            return "the host has frozen the lyric for now"
        return ""

    def _their_ops(self, pid: int, ops: list[dict], seq) -> None:
        seq = seq if isinstance(seq, int) and not isinstance(seq, bool) else 0
        no = self.may_edit(pid)
        if no:
            self.outbox.append((pid, {"t": "fix", "ack": seq, "why": no,
                                      "ops": diff(_after(self.shared, ops),
                                                  self.shared)}))
            return
        # Holds are judged on what THIS edit changed (each line against the
        # version it started from), before any merging: merged, a line also
        # carries other people's words, and those are not this edit's.
        held = blocking(self.locks.owner, pid, ops, self.shared)
        if not held:
            merged = self._merge(ops)
            if merged is None:
                self.outbox.append((pid, {"t": "fix", "ack": seq,
                                          "why": "somebody changed the same "
                                                 "words at the same time",
                                          "ops": []}))
                self.outbox.append((pid, {"t": "state", "rev": self.rev,
                                          "doc": doc_out(self.shared),
                                          "h": digest(self.shared)}))
                return
            ops = merged
        if held:
            # All of it or none of it: the joiner's whole edit goes back.
            self.outbox.append((pid, {"t": "fix", "ack": seq,
                                      "why": _who(held, self.shared, self.names()),
                                      "ops": diff(_after(self.shared, ops),
                                                  self.shared)}))
            return
        if len(self.shared.lines) - sum(o["o"] == "del" for o in ops) \
                + sum(o["o"] == "set" for o in ops) > MAX_LINES:
            self.outbox.append((pid, {"t": "fix", "ack": seq,
                                      "why": "the lyric is at its size limit",
                                      "ops": diff(_after(self.shared, ops),
                                                  self.shared)}))
            return
        self._commit(pid, ops, seq)

    def _merge(self, ops: list[dict]) -> list[dict] | None:
        """A line somebody else changed while this edit was on its way:
        merged word by word where the two touched different words, None
        where they cannot be told apart."""
        lines = {ln.uid: ln for ln in self.shared.lines}
        out = []
        for op in ops:
            base = op.get("b")
            if op["o"] != "set" or base is None or op["u"] not in lines:
                # Never a joiner's own word for "merged": only the host says so.
                out.append({k: v for k, v in op.items()
                            if not (op["o"] == "set" and k in ("b", "m"))})
                continue
            now = lines[op["u"]]
            b = line_in(base, op["u"])
            if b == now:                       # nothing happened meanwhile
                out.append({"o": "set", "u": op["u"], "l": op["l"], "b": base})
                continue
            got = merge_line(b, line_in(op["l"], op["u"]), now)
            if got is None:
                return None
            out.append({"o": "set", "u": op["u"], "l": line_out(got),
                        "b": base, "m": True})
        return out

    def _commit(self, pid: int, ops: list[dict], seq: int = 0) -> None:
        ops = [{k: v for k, v in op.items() if k != "b"} for op in ops]
        if touched(ops) and pid in self.peers:
            name = self.peers[pid]["n"]
            if name != "someone" and name not in self.contributors:
                self.contributors.append(name)
        before = {ln.uid for ln in self.shared.lines}
        was = {ln.uid: timing(ln) for ln in self.shared.lines}
        apply(self.shared, ops)
        now = {ln.uid: ln for ln in self.shared.lines}
        sy, unsy = [], []
        for o in ops:
            if o["o"] != "set" or o["u"] not in now:
                continue
            t = timing(now[o["u"]])
            if t == was.get(o["u"]) or (o["u"] not in was and not _any_time(t)):
                continue
            if _any_time(t) and pid in self.peers:
                self.synced[o["u"]] = {"n": self.peers[pid]["n"],
                                       "c": self.peers[pid]["c"]}
                sy.append(o["u"])
            elif self.synced.pop(o["u"], None) is not None:
                unsy.append(o["u"])
        if any(o["o"] == "order" for o in ops) or any(
                o["o"] == "del" for o in ops) or any(
                o["o"] == "set" and o["u"] not in before for o in ops):
            # Whatever order the sender proposed, everyone is told the order
            # the host ended up with -- so they all end up with it too.
            ops = [o for o in ops if o["o"] != "order"] + [
                {"o": "order", "u": [ln.uid for ln in self.shared.lines]}]
        gone = {o["u"] for o in ops if o["o"] == "del"}
        if gone:
            self.locks.forget(gone)
            for u in gone:
                self.synced.pop(u, None)
            for u in gone & set(self.notes):
                del self.notes[u]
                self.outbox.append((None, {"t": "notes", "u": u, "n": []}))
        self.rev += 1
        msg = {"t": "applied", "rev": self.rev, "by": pid, "ack": seq,
               "ops": ops}
        if sy:
            msg["sy"] = sy
        if unsy:
            msg["usy"] = unsy
        now = time.monotonic()
        if now - self._hashed_at > 0.5:
            self._hashed_at = now
            msg["h"] = digest(self.shared)
        self.outbox.append((None, msg))
        if gone:
            self._tell_who()

    # -- the host's own hands
    def local(self, doc: M.Doc, force: bool = False) -> tuple[list, str]:
        """The host edited `doc`. Returns (ops sent, why refused or '').
        Refused, the edit is undone in `doc` before this returns."""
        M.ensure_unique(doc)
        adopt(self.shared, doc)
        ops = diff(self.shared, doc)
        if not ops:
            return [], ""
        held = {} if force else blocking(self.locks.owner, 0, ops, self.shared)
        if held:
            apply(doc, diff(doc, self.shared))
            return [], _who(held, self.shared, self.names())
        self._commit(0, ops)
        return ops, ""

    def here(self, pid: int, cursor, selection) -> None:
        at = None
        if cursor is not None:
            c = _list(cursor, 3, "cursor")
            if len(c) != 3 or not all(isinstance(x, int) and not isinstance(x, bool)
                                      and 0 <= x < 100000 for x in c[1:]):
                raise Bad("cursor")
            at = [_uid(c[0]), c[1], c[2]]
        sel = [_uid(u) for u in _list(selection or [], MAX_LINES, "selection")]
        self.peers[pid]["at"] = at
        self._sel[pid] = sel
        self.locks.set_presence(pid, self._wants(pid))
        self._tell_who()

    def _wants(self, pid: int) -> set[str]:
        """What somebody's cursor and selection hold, in the mode the host
        chose: their lines, or -- holding single words -- the word their
        cursor is on and any OTHER lines they have selected."""
        p = self.peers.get(pid) or {}
        if p.get("ro"):
            return set()        # watching holds nothing
        at, sel = p.get("at"), set(self._sel.get(pid, []))
        if not self.hold_words:
            return sel | ({at[0]} if at else set())
        want = sel - ({at[0]} if at else set())
        if at:
            key = word_key(self.shared, at[0], at[1], at[2])
            want.add(key or at[0])
        return want

    # -------------------------------------------------- handing it over
    def handover_state(self, to: int) -> dict:
        """Everything a new host needs that is not already on its screen:
        who everybody is, what they hold, the notes, the session's rules."""
        people = {}
        for pid, p in self.peers.items():
            if pid in (0, to):
                continue
            people[str(pid)] = {"n": p["n"], "c": p["c"],
                                "ro": bool(p.get("ro")),
                                "claims": sorted(self.locks.claims.get(pid, ()))}
        return {"doc": doc_out(self.shared), "notes": self.notes,
                "synced": self.synced,
                "contributors": list(self.contributors),
                "frozen": False, "words": self.hold_words, "people": people,
                "mine": sorted(self.locks.claims.get(to, ()))}

    def take_over(self, state: dict) -> list[int]:
        """Become the host of a session handed over: everybody else is
        'away' until they come across on the invite made for them, then
        returns as who they were. Returns their old ids."""
        self.notes = {u: v for u, v in state["notes"].items()}
        self.synced = dict(state.get("synced") or {})
        self.contributors = list(state["contributors"])
        self.hold_words = bool(state["words"])
        self.frozen = bool(state["frozen"])
        uids = {ln.uid for ln in self.shared.lines}
        for pid, p in state["people"].items():
            self.away[pid] = {"n": p["n"], "c": p["c"], "ro": p["ro"],
                              "claims": {u for u in p["claims"] if u in uids}}
        mine = [u for u in state["mine"] if u in uids]
        if mine:
            self.locks.claim(0, mine)
        return list(state["people"])

    def set_hold(self, words: bool) -> None:
        """Whole lines (the default) or single words."""
        self.hold_words = bool(words)
        for pid in list(self.peers):
            self.locks.set_presence(pid, self._wants(pid))
        self._tell_who()

    def claim(self, pid: int, uids) -> list[str]:
        if self.peers.get(pid, {}).get("ro"):
            return list(uids)
        taken = self.locks.claim(pid, uids)
        self._tell_who()
        return taken

    def assign(self, pid: int, uids) -> list[str]:
        """The host hands lines to somebody: theirs, as if they had claimed
        them -- and theirs to let go of. Returns what somebody else holds."""
        if pid not in self.peers or self.peers[pid].get("ro"):
            return list(uids)
        return self.claim(pid, uids)

    def share(self, plan: dict[int, list]) -> None:
        """The host shares the song out (ops.share_out): every claim is
        replaced. Watchers and people not here get nothing."""
        uids = {ln.uid for ln in self.shared.lines}
        self.locks.share({pid: {u for u in us if u in uids}
                          for pid, us in plan.items()
                          if pid in self.peers and not self.peers[pid].get("ro")})
        self._tell_who()

    def set_role(self, pid: int, watch: bool) -> None:
        if pid == 0 or pid not in self.peers:
            return
        self.peers[pid]["ro"] = bool(watch)
        if watch:
            self.locks.drop(pid)     # a watcher holds nothing, claims included
        self._tell_who()

    def freeze(self, on: bool) -> None:
        self.frozen = bool(on)
        self._tell_who()

    def release(self, pid: int, uids=None) -> None:
        self.locks.release(pid, uids)
        self._tell_who()

    def note(self, pid: int, uid: str, text) -> bool:
        """A note on a line, from anybody in the session."""
        if uid not in {ln.uid for ln in self.shared.lines}:
            return False
        line = self.notes.setdefault(uid, [])
        if len(line) >= MAX_NOTES_LINE or \
                sum(len(v) for v in self.notes.values()) >= MAX_NOTES:
            raise Bad("too many notes")
        self._note_id += 1
        line.append({"i": self._note_id, "by": pid,
                     "n": self.peers.get(pid, {}).get("n", "someone"),
                     "x": note_text(text)})
        self.outbox.append((None, {"t": "notes", "u": uid, "n": line}))
        return True

    def unnote(self, pid: int, uid: str, i: int) -> bool:
        """Take a note away: its writer may, and so may the host."""
        line = self.notes.get(uid) or []
        keep = [n for n in line if not (n["i"] == i and pid in (n["by"], 0))]
        if len(keep) == len(line):
            return False
        if keep:
            self.notes[uid] = keep
        else:
            self.notes.pop(uid, None)
        self.outbox.append((None, {"t": "notes", "u": uid, "n": keep}))
        return True

    def rename(self, pid: int, name) -> None:
        if pid in self.peers:
            self.peers[pid]["n"] = clean_name(name)
            self._tell_who()

    def kick(self, pid: int) -> None:
        self.outbox.append((pid, {"t": "end", "why": "the host removed you"}))
        self.leave(pid)


def credit(existing, names: list[str]) -> str:
    """SyncedBy with everyone who timed lines in it: who the file already
    named first, then each newcomer once, in the order they joined in."""
    have = [x.strip() for x in str(existing or "").split(",") if x.strip()]
    for n in names:
        if n not in have:
            have.append(n)
    return ", ".join(have)[:MAX_META_STR]


def _after(doc: M.Doc, ops: list[dict]) -> M.Doc:
    out = doc.clone()
    apply(out, ops)
    return out


# ----------------------------------------------------------------- joiner
class Member:
    """A joiner's side. `shared` is the host's document as last heard, plus
    this joiner's own edits on their way there -- each of which the host
    either echoes back as applied or answers with a fix."""

    role = "member"

    def __init__(self, name: str) -> None:
        self.name = clean_name(name)
        self.me: int | None = None
        self.shared: M.Doc | None = None
        self.rev = 0
        self.peers: dict[int, dict] = {}
        self.owner: dict[str, int] = {}
        self.claims: dict[str, int] = {}
        self.frozen = False
        self.hold_words = False
        self.offline = False      # dropped, and on the way back in
        self.outbox: list[tuple[int | None, dict]] = []
        self.sent = 0
        self.acked = 0
        self.notes: dict[str, list[dict]] = {}
        self.synced: dict[str, dict] = {}

    def may_edit(self) -> str:
        if self.offline:
            return ("reconnecting to the host — edits wait until this "
                    "editor is back in")
        if self.peers.get(self.me, {}).get("ro"):
            return "you can watch this session but not edit it"
        if self.frozen:
            return "the host has frozen the lyric for now"
        return ""

    def hello(self, token: str, app: str = "") -> dict:
        return {"t": "hello", "proto": PROTO, "token": token,
                "name": self.name, "app": app}

    def names(self) -> dict[int, str]:
        return {pid: p["n"] for pid, p in self.peers.items()}

    def held_by_others(self, uids) -> dict[str, int]:
        return {u: self.owner[u] for u in uids
                if u in self.owner and self.owner[u] != self.me}

    def local(self, doc: M.Doc, force: bool = False) -> tuple[list, str]:
        if self.shared is None:
            return [], ""
        M.ensure_unique(doc)
        adopt(self.shared, doc)
        ops = diff(self.shared, doc)
        if not ops:
            return [], ""
        no = self.may_edit()
        if no:
            apply(doc, diff(doc, self.shared))
            return [], no
        held = blocking(self.owner, self.me, ops, self.shared)
        if held:
            apply(doc, diff(doc, self.shared))
            return [], _who(held, self.shared, self.names())
        before = {ln.uid: ln for ln in self.shared.lines}
        for op in ops:
            if op["o"] == "set" and op["u"] in before:
                op["b"] = line_out(before[op["u"]])   # what this edit started from
        apply(self.shared, ops)
        self.sent += 1
        self.outbox.append((None, {"t": "ops", "n": self.sent, "ops": ops}))
        return ops, ""

    def here(self, cursor, selection) -> None:
        self.outbox.append((None, {"t": "here", "c": cursor, "s": selection}))

    def claim(self, uids) -> None:
        self.outbox.append((None, {"t": "claim", "u": list(uids)}))

    def note(self, uid: str, text: str) -> None:
        self.outbox.append((None, {"t": "note", "u": uid,
                                   "x": note_text(text)}))

    def unnote(self, uid: str, i: int) -> None:
        self.outbox.append((None, {"t": "unnote", "u": uid, "i": int(i)}))

    def rename(self, name: str) -> None:
        self.name = clean_name(name)
        self.outbox.append((None, {"t": "name", "n": self.name}))

    def release(self, uids=None) -> None:
        self.outbox.append((None, {"t": "release",
                                   "u": None if uids is None else list(uids)}))

    def on_message(self, msg) -> dict:
        """Handle one message from the host. Returns what the window must do:

            {"doc": Doc}            take this document whole (joining)
            {"ops": [...]}          apply these to the screen and the undo
            {"fix": [...], "why"}   my edit was refused: put these back
            {"who": True}           people or locks changed
            {"end": why}            the session is over
            {}                      nothing to do

        Raises Bad if the host sent something no host would.
        """
        if not isinstance(msg, dict):
            raise Bad("message")
        kind = msg.get("t")
        if kind in ("welcome", "state"):
            doc = doc_in(msg.get("doc"))
            if kind == "welcome":
                you = msg.get("you")
                if not isinstance(you, int) or isinstance(you, bool):
                    raise Bad("you")
                self.me = you
            self.rev = _int(msg.get("rev"))
            self.acked = self.sent
            if "synced" in msg:
                self.synced = synced_in(msg.get("synced"))
            if kind == "welcome":
                raw = msg.get("notes") or {}
                if not isinstance(raw, dict) or len(raw) > MAX_NOTES:
                    raise Bad("notes")
                self.notes = {_uid(u): notes_in(v) for u, v in raw.items()}
                self.notes = {u: v for u, v in self.notes.items() if v}
            if self.shared is None:
                self.shared = doc.clone()
                return {"doc": doc}
            ops = diff(self.shared, doc)
            self.shared = doc
            back = self.offline
            self.offline = False
            return {"ops": ops, "resync": True, "back": back}
        if self.shared is None:
            raise Bad("before welcome")
        if kind == "applied":
            ops = ops_in(msg.get("ops"))
            self.rev = _int(msg.get("rev"))
            by = msg.get("by")
            who = self.peers.get(by) if isinstance(by, int) else None
            for u in _list(msg.get("sy") or [], MAX_LINES, "synced"):
                if who is not None:
                    self.synced[_uid(u)] = {"n": who["n"], "c": who["c"]}
            for u in _list(msg.get("usy") or [], MAX_LINES, "synced"):
                self.synced.pop(_uid(u), None)
            for o in ops:
                if o["o"] == "del":
                    self.synced.pop(o["u"], None)
            if by == self.me:
                self.acked = max(self.acked, _int(msg.get("ack")))
                # Ours, echoed: already on screen and in `shared`. Only the
                # order is worth taking -- it is the one the host settled on.
                ops = [o for o in ops if o["o"] == "order" or o.get("m")]
            # Somebody else's, while ours may be in flight: our lines are ours
            # (held), so the only overlap is a lock race -- and the host's
            # answer to that comes as a fix for our edit, right after this.
            apply(self.shared, ops)
            out = {"ops": ops}
            h = msg.get("h")
            if isinstance(h, str) and self.acked >= self.sent \
                    and h != digest(self.shared):
                self.outbox.append((None, {"t": "resync"}))
            return out
        if kind == "fix":
            ops = ops_in(msg.get("ops"))
            self.acked = max(self.acked, _int(msg.get("ack")))
            apply(self.shared, ops)
            return {"fix": ops, "why": _plain(msg.get("why"))}
        if kind == "who":
            peers = msg.get("peers")
            if not isinstance(peers, dict) or len(peers) > MAX_PEERS + 1:
                raise Bad("peers")
            got = {}
            for k, p in peers.items():
                if not isinstance(p, dict) or not str(k).isdigit():
                    raise Bad("peer")
                colour = p.get("c") if isinstance(p.get("c"), str) and \
                    re.fullmatch(r"#[0-9a-fA-F]{6}", p["c"]) else "#a0a8ff"
                at = p.get("at")
                if at is not None:
                    if not (isinstance(at, list) and len(at) == 3
                            and isinstance(at[0], str) and UID.match(at[0])
                            and all(isinstance(x, int) and not isinstance(x, bool)
                                    for x in at[1:])):
                        at = None
                got[int(k)] = {"n": clean_name(p.get("n")), "c": colour, "at": at,
                               "ro": p.get("ro") is True}
            self.peers = got
            self.frozen = msg.get("frozen") is True
            self.hold_words = msg.get("words") is True
            self.owner = _table(msg.get("locks"))
            self.claims = _table(msg.get("claims"))
            return {"who": True}
        if kind == "end":
            return {"end": _plain(msg.get("why")) or "the session ended"}
        if kind == "song":
            return {"song": song_in(msg)}
        if kind == "env":
            # The host copy's loudness outline (collab_audio): only its
            # shape is checked here -- this module has no numpy -- and the
            # rest where it is unpacked.
            hz, d = msg.get("hz"), msg.get("d")
            if hz != 100 or not isinstance(d, str) or not 0 < len(d) <= 480008:
                raise Bad("outline")
            return {"env": (hz, d, song_url(msg.get("u")))}
        if kind == "become":
            st = msg.get("state")
            if not isinstance(st, dict):
                raise Bad("handover")
            people = {}
            raw = st.get("people")
            if not isinstance(raw, dict) or len(raw) > MAX_PEERS:
                raise Bad("handover people")
            for k, p in raw.items():
                if not str(k).isdigit() or not isinstance(p, dict):
                    raise Bad("handover person")
                colour = p.get("c") if isinstance(p.get("c"), str) and \
                    re.fullmatch(r"#[0-9a-fA-F]{6}", p["c"]) else "#a0a8ff"
                people[int(k)] = {
                    "n": clean_name(p.get("n")), "c": colour,
                    "ro": p.get("ro") is True,
                    "claims": [_uid(u) for u in _list(p.get("claims") or [],
                                                      MAX_LINES, "claims")]}
            notes = st.get("notes") or {}
            if not isinstance(notes, dict) or len(notes) > MAX_NOTES:
                raise Bad("handover notes")
            return {"become": {
                "doc": doc_in(st.get("doc")),
                "notes": {_uid(u): notes_in(v) for u, v in notes.items()},
                "synced": synced_in(st.get("synced")),
                "contributors": [clean_name(x) for x in
                                 _list(st.get("contributors") or [], 64,
                                       "contributors")],
                "frozen": st.get("frozen") is True,
                "words": st.get("words") is True, "people": people,
                "mine": [_uid(u) for u in _list(st.get("mine") or [],
                                                MAX_LINES, "claims")]}}
        if kind in ("move", "reply"):
            code = msg.get("code")
            if not isinstance(code, str) or not 0 < len(code) <= 8192:
                raise Bad("code")
            return {kind: code, "host": clean_name(msg.get("host"))}
        if kind == "handover_off":
            return {"handover_off": _plain(msg.get("why")) or "cancelled"}
        if kind == "resume":
            iid, tok = msg.get("i"), msg.get("k")
            if not (isinstance(iid, str) and re.fullmatch(r"[0-9a-f]{16}", iid)
                    and isinstance(tok, str)
                    and re.fullmatch(r"[0-9a-f]{32}", tok)):
                raise Bad("resume")
            return {"resume": (iid, tok)}
        if kind == "notes":
            uid = _uid(msg.get("u"))
            got = notes_in(msg.get("n"))
            if got:
                self.notes[uid] = got
            else:
                self.notes.pop(uid, None)
            return {"notes": uid}
        raise Bad("message kind")


def _plain(x, cap: int = 120) -> str:
    """Text from the host, as it may be shown: plain, one line, short."""
    return CONTROL.sub("", x).strip()[:cap] if isinstance(x, str) else ""


def _int(x) -> int:
    return x if isinstance(x, int) and not isinstance(x, bool) else 0


def _table(raw) -> dict[str, int]:
    if not isinstance(raw, dict) or len(raw) > MAX_LINES:
        raise Bad("lock table")
    out = {}
    for u, pid in raw.items():
        if isinstance(u, str) and (UID.match(u) or WORD_KEY.match(u)) \
                and isinstance(pid, int):
            out[u] = pid
    return out
