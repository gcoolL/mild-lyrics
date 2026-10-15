"""The shared splitting dictionary: how words are cut, one list per language,
kept on the Worker and readable and writable by anyone (docs/notes/editor/
shared_splits.md). No Qt here: a list is fetched on a thread and kept on disk."""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import threading
import time
import urllib.error
import urllib.request

# The same Worker as collab_net.WORKER and the player's DP.ART_HOST.
BASE = "https://raspy-snowflake-c23c.gcoolltm.workers.dev"
UA = "mild-lyrics-editor/1.0"
TIMEOUT = 8.0
# A language's list is asked for again after this long (an ETag makes it a 304).
STALE = 30 * 60.0
WORD = re.compile(r"^[\w'’-]{1,48}$")

_LOCK = threading.Lock()
_LISTS: dict = {}            # lang -> {"words": {...}, "etag": str, "at": float}
_ASKING: set = set()
_VERSION = [0]               # bumped whenever any list changes


def lang_of(code: str) -> str:
    """The list a pyphen code files under: en_US and en_GB are both "en"."""
    base = str(code or "").split("_")[0].split("-")[0].lower()
    return base if re.fullmatch(r"[a-z]{2,3}", base) else ""


def version() -> int:
    """Changes whenever a list does, so a memo of split answers can tell."""
    return _VERSION[0]


def _cache_path(lang: str) -> pathlib.Path:
    import lyrics_gui as L
    return pathlib.Path(L.app_dir("cache")) / "shared-splits" / f"{lang}.json"


def _enabled() -> bool:
    from . import keys as K
    return bool(K.config().get("split_shared", True))


def _load_disk(lang: str) -> dict:
    try:
        got = json.loads(_cache_path(lang).read_text(encoding="utf-8"))
        if isinstance(got, dict) and isinstance(got.get("words"), dict):
            return got
    except Exception:
        pass
    return {"words": {}, "etag": ""}


def _store(lang: str, got: dict) -> None:
    with _LOCK:
        _LISTS[lang] = {"words": got.get("words") or {},
                        "etag": got.get("etag") or "", "at": time.time()}
        _VERSION[0] += 1
    try:
        p = _cache_path(lang)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"words": got.get("words") or {},
                                 "etag": got.get("etag") or ""},
                                ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _request(path: str, body=None, headers=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    req = urllib.request.Request(
        BASE + path, data=data, method="GET" if body is None else "POST",
        headers={"User-Agent": UA, "Content-Type": "application/json",
                 **(headers or {})})
    return urllib.request.urlopen(req, timeout=TIMEOUT)


def fetch(lang: str) -> str:
    """Ask the Worker for this language's list, now. "" or why it failed."""
    if not lang:
        return "no language"
    with _LOCK:
        etag = (_LISTS.get(lang) or {}).get("etag", "")
    try:
        with _request(f"/splits/{lang}",
                      headers={"If-None-Match": etag} if etag else None) as r:
            got = json.loads(r.read().decode("utf-8"))
            _store(lang, {"words": got.get("words") or {},
                          "etag": r.headers.get("ETag") or ""})
    except urllib.error.HTTPError as e:
        if e.code == 304:
            with _LOCK:
                if lang in _LISTS:
                    _LISTS[lang]["at"] = time.time()
            return ""
        return f"HTTP {e.code}"
    except Exception as e:                                  # noqa: BLE001
        return str(getattr(e, "reason", e)) or type(e).__name__
    return ""


def _refresh_soon(lang: str) -> None:
    with _LOCK:
        if lang in _ASKING:
            return
        _ASKING.add(lang)

    def run():
        try:
            fetch(lang)
        finally:
            with _LOCK:
                _ASKING.discard(lang)

    threading.Thread(target=run, name="shared-splits", daemon=True).start()


def words(lang: str, refresh: bool = True) -> dict:
    """This language's list as it stands here: {word: {"ways", "locked"}}.

    Read from disk the first time, and asked of the Worker in the background
    when older than STALE. Empty with the setting off."""
    if not lang or not _enabled():
        return {}
    with _LOCK:
        have = _LISTS.get(lang)
    if have is None:
        got = _load_disk(lang)
        with _LOCK:
            have = _LISTS.setdefault(lang, {"words": got["words"],
                                            "etag": got.get("etag", ""), "at": 0.0})
            _VERSION[0] += 1
    if refresh and time.time() - have["at"] > STALE:
        _refresh_soon(lang)
    return have["words"]


def ways_for(word_key: str, lang: str) -> list[list[str]]:
    """The shared ways for a bare lowercased word, the usual one first."""
    got = words(lang).get(word_key) or {}
    out = []
    for way in got.get("ways") or []:
        if (isinstance(way, list) and way and all(isinstance(b, str) and b for b in way)
                and "".join(way) == word_key and way not in out):
            out.append(list(way))
    return out


# Answers that are not failures: the list already said so, nothing was sent.
UNCHANGED = "unchanged"
ALREADY = "already"
BATCH = 500                  # words in one request (the Worker's SPLIT_BATCH)


def _have(lang: str) -> dict:
    with _LOCK:
        return dict((_LISTS.get(lang) or {}).get("words") or {})


def _send(path: str, key: str, items: list, extra: dict, headers=None,
          codes: dict | None = None) -> tuple[list, list, dict]:
    """POST `items` under `key` in batches: (done, same, {word: why not})."""
    done, same, bad = [], [], {}
    for at in range(0, len(items), BATCH):
        chunk = items[at:at + BATCH]
        words = [x["word"] if isinstance(x, dict) else x for x in chunk]
        try:
            with _request(path, {key: chunk, **extra}, headers) as r:
                got = json.loads(r.read().decode("utf-8"))
            done += list(got.get("done") or [])
            same += list(got.get("same") or [])
            bad.update(got.get("refused") or {})
        except urllib.error.HTTPError as e:
            why = (codes or {}).get(e.code, f"HTTP {e.code}")
            bad.update({w: why for w in words})
        except Exception as e:                              # noqa: BLE001
            why = str(getattr(e, "reason", e)) or type(e).__name__
            bad.update({w: why for w in words})
    return done, same, bad


def submit_many(lang: str, plan: dict) -> tuple[list, list, dict]:
    """Put several words' ways in the list ([] removes one), in as few
    requests as there are batches: (done, unchanged, {word: why not}).
    A word already so, or locked, is answered from the list here, unsent."""
    have = _have(lang)
    done, same, bad, send = [], [], {}, []
    for word, ways in plan.items():
        word = str(word or "").lower()
        if not lang or not WORD.match(word):
            bad[word] = "not a word"
            continue
        keep = []
        for w in ways:
            w = [b.lower() for b in w]
            if w not in keep:
                keep.append(w)
        if any("".join(w) != word or not all(w) for w in keep):
            bad[word] = "a way does not spell the word"
            continue
        now = have.get(word)
        if (now is None and not keep) or (now is not None and now.get("ways") == keep):
            same.append(word)
            continue
        if now is not None and now.get("locked"):
            bad[word] = "locked"
            continue
        send.append({"word": word, "ways": keep})
    if send:
        d, s2, b = _send(f"/splits/{lang}", "entries", send, {},
                         codes={429: "enough sent for today", 413: "too many at once"})
        done, same, bad = done + d, same + s2, {**bad, **b}
        fetch(lang)
    return done, same, bad


def submit(lang: str, word: str, ways: list[list[str]]) -> str:
    """One word's ways: "" when shared, UNCHANGED when it already was, or why not."""
    done, same, bad = submit_many(lang, {word: ways})
    return "" if done else UNCHANGED if same else next(iter(bad.values()), "not sent")


def lock_many(lang: str, words: list, locked: bool, secret: str) -> tuple[list, list, dict]:
    """Lock or unlock several entries in one request, with the owner's secret:
    (done, already so, {word: why not}). Ones already so are not sent."""
    if not secret:
        return [], [], {str(w): "no owner secret set" for w in words}
    have = _have(lang)
    done, same, bad, send = [], [], {}, []
    for word in words:
        word = str(word or "").lower()
        now = have.get(word)
        if now is None:
            bad[word] = "no such entry"
        elif bool(now.get("locked")) == bool(locked):
            same.append(word)
        else:
            send.append(word)
    if send:
        owner = hashlib.sha256(secret.encode("utf-8")).hexdigest()
        d, s2, b = _send(f"/splits/{lang}/lock", "words", send, {"lock": bool(locked)},
                         {"X-Owner-Hash": owner},
                         {403: "not the owner secret", 503: "no owner is set on the Worker"})
        done, same, bad = done + d, same + s2, {**bad, **b}
        fetch(lang)
    return done, same, bad


def lock(lang: str, word: str, locked: bool, secret: str) -> str:
    """One entry: "" when done, ALREADY when it already was, or why not."""
    done, same, bad = lock_many(lang, [word], locked, secret)
    return "" if done else ALREADY if same else next(iter(bad.values()), "not sent")
