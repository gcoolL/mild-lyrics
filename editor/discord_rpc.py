"""The editor's Discord status: which song is being synced, how far along
it is, where in the song you are, and whether it is a multiplayer session.

The same pipe and the same pacing as the player's card (discord_presence):
Discord takes five changes in twenty seconds, a new song or a pause goes
ahead of the rest, and a card that differs only in its times is not sent
again. "Playing Mild Lyrics", where the player's says "Listening to": the
application is the same one, and it is syncing that is being done.

    Syncing The Mystic — Adam Jensen
    62% synced · at 1:23 · hosting a session with 2 others

While the song plays at its own speed the time is Discord's own bar, which
counts on by itself; paused, or slowed down, it is said in words, kept up
with as far as the pacing lets it.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.parse
import urllib.request

from PyQt6.QtCore import QObject, QTimer

import discord_presence as DP

from . import keys as K

TICK_MS = 1000

SETTINGS = [
    ("Discord status", "discord", "bool", None, False,
     "Show what you are syncing on your Discord profile, through the "
     "Discord app on this machine: the song, how much of it is timed and "
     "where you are in it. Discord's own Settings ▸ Activity Privacy has "
     "to let it show."),
    ("Show the song", "discord_song", "bool", None, True,
     "Its title, artist and cover. Off, it says only that you are syncing lyrics "
     "— for a song that is not out yet."),
    ("Show where you are", "discord_time", "bool", None, True,
     "The time in the song: a running bar while it plays, the time itself "
     "while it is paused."),
    ("Show multiplayer", "discord_session", "bool", None, True,
     "Say when you are in a session, and how many are in it. Never who."),
]
DEFAULTS = {key: default for _l, key, _k, _s, default, _n in SETTINGS}


def setting(key: str):
    return K.config().get(key, DEFAULTS[key])


def progress(doc) -> tuple[int, int]:
    """(syllables timed, syllables) over every voice: how far the sync is."""
    timed = total = 0
    for ln in getattr(doc, "lines", []) or []:
        for g in [ln.lead, *ln.bg]:
            for s in g.syls:
                if not str(s.text or "").strip():
                    continue
                total += 1
                if s.start is not None:
                    timed += 1
    return timed, total


def _key(s: str) -> str:
    return "".join(c for c in (s or "").casefold() if c.isalnum())


def _first(artist: str) -> str:
    """The first of several credited artists: "A, B & C feat. D" is A."""
    return re.split(r"\s*(?:,|&|\band\b|\bfeat\.?|\bft\.?|\bx\b|;)\s*",
                    artist or "", maxsplit=1, flags=re.I)[0]


def _like(a: str, b: str) -> bool:
    ka, kb = _key(a), _key(b)
    return bool(ka and kb) and (ka == kb or (len(ka) >= 4 and ka in kb)
                                or (len(kb) >= 4 and kb in ka))


def _ask(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mild Lyrics"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8", "replace")


def find_cover(title: str, artist: str, ask=_ask) -> str:
    """The song's cover as a public address Discord can fetch, or "".

    From the iTunes Search API by title and artist, the way the player finds
    records. Both must match -- a title alone is nowhere near unique -- and
    the picture is asked for at 512px, Discord's own size for a large image.
    """
    if not title.strip() or not artist.strip():
        return ""
    q = urllib.parse.urlencode({"term": f"{_first(artist)} {title}",
                                "entity": "song", "limit": 15})
    try:
        hits = (json.loads(ask(f"https://itunes.apple.com/search?{q}"))
                or {}).get("results") or []
    except Exception:                                    # noqa: BLE001
        return ""
    for h in hits:
        art = str(h.get("artworkUrl100") or "")
        if (art.startswith("https://") and _like(h.get("trackName", ""), title)
                and _like(h.get("artistName", ""), _first(artist))):
            return re.sub(r"/\d+x\d+(bb)?\.(jpg|png|webp)$", r"/512x512bb.\2", art)
    return ""


def clock(secs: float) -> str:
    secs = max(0, int(secs))
    return f"{secs // 3600}:{secs // 60 % 60:02d}:{secs % 60:02d}" \
        if secs >= 3600 else f"{secs // 60}:{secs % 60:02d}"


def activity(st: dict, cfg: dict) -> dict | None:
    """What Discord is told, or None to show nothing.

    `st`: title, artist, timed, total (syllables), pos, length (seconds),
    playing, rate, people (in the session, you included; 0 when there is
    none) and role ("host" or "member"). `cfg`: the discord_* settings.
    """
    if not st or not st.get("total"):
        return None
    title, artist = str(st.get("title") or "").strip(), str(st.get("artist") or "").strip()
    if cfg["discord_song"] and title:
        top = f"Syncing {title}" + (f" — {artist}" if artist else "")
    else:
        top = "Syncing lyrics"
    timed, total = int(st.get("timed") or 0), int(st["total"])
    pct = 100 if timed >= total else min(99, int(timed * 100 / total))
    bits = [f"{pct}% synced"]
    playing = bool(st.get("playing"))
    pos, length = float(st.get("pos") or 0.0), float(st.get("length") or 0.0)
    bar = (cfg["discord_time"] and playing and length > 0
           and abs(float(st.get("rate") or 1.0) - 1.0) < 0.01)
    if cfg["discord_time"] and not bar:
        bits.append(("at " if playing else "paused at ") + clock(pos))
    people = int(st.get("people") or 0)
    if cfg["discord_session"] and people > 1:
        others = people - 1
        bits.append(("hosting a session" if st.get("role") == "host"
                     else "in a session")
                    + f" with {others} other{'s' * (others != 1)}")
    # Listening, as the player's card is: Discord draws its times as the
    # song's own bar (where it is, how long it is). As Playing they read as
    # a countdown, and a paused card ran a "playing for" clock from 0:00.
    act: dict = {"type": DP.KIND_TYPE["listening"], "details": DP._field(top),
                 "state": DP._field(" · ".join(bits))}
    art = str(st.get("art") or "")
    if cfg["discord_song"] and art.startswith("https://"):
        act["assets"] = {"large_image": art}
        if title:
            act["assets"]["large_text"] = DP._field(
                title + (f" — {artist}" if artist else ""))
    if bar:
        start = time.time() - max(0.0, pos)
        act["timestamps"] = {"start": int(start * 1000),
                             "end": int((start + length) * 1000)}
    return act


class Status(QObject):
    """The card, kept up with the editor once a second while it is on."""

    def __init__(self, ed) -> None:
        super().__init__(ed)
        self.ed = ed
        self.presence = DP.Presence()
        self.covers: dict = {}          # (title, artist) -> address, "" for none
        self.timer = QTimer(self)
        self.timer.setInterval(TICK_MS)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    def state(self) -> dict:
        ed = self.ed
        doc, pl = getattr(ed, "doc", None), ed.player
        timed, total = progress(doc)
        meta = getattr(doc, "meta", None) or {}
        st = {"title": str(meta.get("Title") or pl.title() or ""),
              "artist": str(meta.get("Artist") or pl.artist() or ""),
              "timed": timed, "total": total,
              "pos": float(pl.position() or 0.0),
              "length": float(pl.duration() or 0.0),
              "playing": bool(pl.playing()), "rate": float(pl.rate() or 1.0),
              "people": 0, "role": ""}
        st["art"] = self.cover(st["title"], st["artist"])
        co = getattr(ed, "collab", None)
        if co is not None and co.active() and co.session is not None:
            st["people"] = len(co.session.peers)
            st["role"] = co.session.role
        return st

    def cover(self, title: str, artist: str) -> str:
        """The song's cover: Spotify's own while Spotify is what is being
        timed against, else looked up once per song, off the GUI thread --
        "" until it comes back, and the card is sent again when it does."""
        pl = self.ed.player
        if getattr(pl, "kind", "") == "spotify":
            art = str((getattr(getattr(pl, "clock", None), "meta", None)
                       or {}).get("art") or "")
            if art.startswith("https://"):
                return art
        if not bool(setting("discord_song")):
            return ""
        key = (_key(title), _key(artist))
        if not all(key):
            return ""
        if key not in self.covers:
            self.covers[key] = ""
            threading.Thread(target=lambda: self.covers.__setitem__(
                key, find_cover(title, artist)), daemon=True,
                name="discord-cover").start()
        return self.covers[key]

    def tick(self) -> None:
        on = bool(setting("discord"))
        if not on and self.presence.said() == "off":
            return
        cfg = {k: setting(k) for k in DEFAULTS}
        st = self.state() if on else {}
        act = activity(st, cfg) if on else None
        # Ahead of the pacing: another song, a start or a stop, somebody
        # joining or leaving, a setting just changed -- each of those looks
        # like nothing happened if it waits its turn behind the percentage.
        key = "|".join(str(x) for x in (
            st.get("title"), st.get("artist"), st.get("art"), st.get("playing"),
            st.get("people"), sorted(cfg.items())))
        self.presence.want(act, on, "", key)

    def stop(self) -> None:
        self.timer.stop()
        self.presence.stop()
