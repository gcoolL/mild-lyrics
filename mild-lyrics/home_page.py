"""The 1.2.0 home page: library, search, pages, the local player, stats and
setup, painted by hand (pages in home_pages.py). Notes:
docs/notes/mild-lyrics/home_page.md."""
from __future__ import annotations

import colorsys
import hashlib
import pathlib
import re
import threading
import time

from PyQt6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QLinearGradient, QPainter,
                         QPainterPath, QPen, QPixmap, QRadialGradient)
from PyQt6.QtWidgets import QApplication, QWidget

import home_data as HD
import home_icons as IC
import autoplay as AP
import library as LIB
import local_player as LP
import noconsole
import pasted_links as PLK
import play_log as PLG
import stream_source as SS
from home_pages import NO_DIRS, Pages, credit_names

W_ = QFont.Weight
NET_POLL = 10.0       # s between connection checks while offline
NET_RETRY = 35.0      # s: connected but the sources failed; asked again after their FAIL_WAIT...
NET_RETRIES = 3       # ...this many times, then given up on
INK = QColor(234, 234, 234)
DARK = QColor(20, 20, 25)
PINK = QColor(246, 179, 174)
RED = QColor(180, 50, 45)
BASE = QColor(27, 20, 32)

# Settings this page owns: kept in gui.json beside the window's own.
DEFAULTS = {
    "home_np": "toolbar", "home_wash": True, "home_shelf_picks": True,
    "home_shelf_made": True, "home_shelf_soon": True, "home_shelf_recent": True, "home_shelf_charts": True,
    "home_shelf_wbw": True, "home_prefer_wbw": True, "home_drop_skips": True,
    "home_unplayed": True, "home_look": 30, "home_mode": "history",
    "home_local_dirs": "", "home_onboarded": False, "home_key_told": False,
    "home_hidden": "", "home_recent_q": "", "home_mini_top": True,
    "home_shuffle": False, "home_repeat": "off", "home_play_in": "auto", "home_autoplay": True,
    "home_mini_adlibs": True, "home_main": "Spotify", "home_chart": "Global",
}
PLAY_IN = ["auto", "Spotify", "Mild Lyrics"]
MAIN_PLAYERS = ["Spotify", "Mild Lyrics", "Another player"]   # which banner the home page may show
CHARTS = ["Global", "Viral 50", "Your country"]
NP_MODES = ["toolbar", "card", "bar"]
MODES = [("history", "Your listening"), ("song", "This song"), ("fresh", "Something new")]
TOP_NAV = [("home", "Home", "home"), ("queue", "Queue", "queue"), ("charts", "Charts", "chart")]
LIB_NAV = [("recent", "Recently played", "clock"), ("songs", "Songs", "music"),
           ("artists", "Artists", "user"), ("albums", "Albums", "disc"),
           ("playlists", "Playlists", "list"), ("lyrics", "Saved lyrics", "mic"),
           ("local", "On this computer", "folder"), ("stats", "Your stats", "pie")]
KIND_LABEL = {"w": "Word-by-word", "l": "Line", "r": "Romanised", "n": "No lyrics"}


def clean(values: dict) -> dict:
    """Saved settings, each the type its default is."""
    out = {}
    for k, d in DEFAULTS.items():
        v = values.get(k, d)
        try:
            if isinstance(d, bool):
                v = bool(v)
            elif isinstance(d, int):
                v = max(7, min(90, int(v))) if k == "home_look" else int(v)
            else:
                v = str(v if v is not None else d)
        except (TypeError, ValueError):
            v = d
        out[k] = v
    if out["home_np"] not in NP_MODES:
        out["home_np"] = "toolbar"
    if out["home_mode"] not in dict(MODES):
        out["home_mode"] = "history"
    if out["home_repeat"] not in ("off", "all", "one"):
        out["home_repeat"] = "off"
    if out["home_play_in"] not in PLAY_IN:
        out["home_play_in"] = "auto"
    if out["home_main"] not in MAIN_PLAYERS:
        out["home_main"] = "Spotify"
    if out["home_chart"] not in CHARTS:
        out["home_chart"] = "Global"
    return out


def tid_of(uri: str) -> str:
    return (uri or "").split(":")[-1] if (uri or "").startswith("spotify:track:") else ""


def shade(c: QColor, light: float, sat: float | None = None) -> QColor:
    h, l_, s = colorsys.rgb_to_hls(c.redF(), c.greenF(), c.blueF())
    s = s if sat is None else max(s, sat)
    r, g, b = colorsys.hls_to_rgb(h, light, min(1.0, s))
    return QColor(int(r * 255), int(g * 255), int(b * 255))


def fmt_ms(ms: float) -> str:
    s = int(round((ms or 0) / 1000))
    return f"{s // 60}:{s % 60:02d}" if s else ""


class Home(Pages):
    """State, chrome and input for the home page; pages come from Pages."""

    def __init__(self, v) -> None:
        self.v = v
        self.spot = HD.Spot(v.fetcher._ask, v.art_url_of)
        self.spot_q = HD.Spot(v.fetcher._ask, v.art_url_of)     # search only: never waits behind a page
        self.dz = SS.Deezer()
        self.dz_q = SS.Deezer()
        self.ups = SS.Deezer()          # upcoming releases: 2-6s first asks, kept off the pages' readers
        self.yt = SS.YouTube(v.clean_video)
        self.links = PLK.Links(v.clean_video, self.spotify_search,
                               lambda: self.online and self.play_in() == "spotify")
        self.pending_link: str | None = None
        for src in (self.spot, self.spot_q, self.dz, self.dz_q, self.ups, self.yt, self.links):
            src.got.connect(self.on_got)
        self.spot.got.connect(self.on_spot)
        self.spot.did.connect(self.on_did)
        self.library = LIB.Library(v.config_dir() / "library.json",
                                   write=not getattr(v.args, "no_persist", False))
        self.resolver = SS.Resolver(v.cache_dir() / "streams.json")
        self.resolver.page = self.spotify_search
        self.log = PLG.PlayLog(v.config_dir() / "plays.jsonl",
                               write=not getattr(v.args, "no_persist", False))
        self.tracker = PLG.Tracker(self.log)
        self.tracker.on_row = self.auto_heard
        self._names: dict = {}
        self._names_rev = -1
        self.faces = SS.Faces(v.cache_dir() / "home" / "artist-faces.json")
        SS.UPCOMING_FILE = v.cache_dir() / "home" / "upcoming.json"
        self.faces.done.connect(v.update)
        self.kinds = HD.Kinds(v.sources_dir(), v.cache_dir() / "kinds.json", v.quality_of)
        self.kinds.done.connect(v.update)
        QTimer.singleShot(8000, self.kinds.scan)
        v.fetcher.ahead_ready.connect(lambda *_: self.kinds.scan())    # fetch-ahead wrote a record
        self.lib = LP.LocalLibrary(v.cache_dir())
        self.lib.changed.connect(self.on_local)
        self.player = v.local_player
        self.player.changed.connect(v.update)
        self.player.changed.connect(v.ahead_soon)
        self.player.resolver = self.resolver
        self.resolver.ready.connect(self.player.on_resolved)
        self.resolver.ready.connect(lambda *_a: v.update())
        self.resolver.found_spotify.connect(lambda _k: v.update())
        self.resolver.found_spotify.connect(lambda _k: v.ahead_soon())
        self.player.failed.connect(lambda why: self.say(f"Could not play it: {why}"))
        self.player.near_end.connect(self.autoplay_fill)
        self.player.near_end.connect(self.auto_smooth)
        self.loud = SS.Loudness(v.cache_dir() / "loudness.json")
        self._smooth_soon = QTimer(singleShot=True, interval=400)
        self._smooth_soon.timeout.connect(self.auto_smooth)
        self.loud.done.connect(self._smooth_soon.start)
        self.player.ran_out.connect(self.autoplay_ran_out)
        self.player.can_grow = lambda: bool(self.v.home_autoplay) and self.v.listen.role != "hear"
        self.auto_want = False
        self.auto_resume = False
        self.auto_rebuild = False               # two skips: autoplay's run is replaced once new picks land
        self.auto_anchor = ""                   # the song autoplay follows: skips below count while it leads
        self.skipped_artists: dict[str, int] = {}
        self.auto_skips = 0                     # autoplay's songs skipped in a row
        self._auto_ord = 0                      # autoplay songs numbered as they come, for auto_smooth
        self.net = SS.NetCheck()
        self.net.done.connect(self.on_net)
        self.net_down = False           # nothing online answered and no connection: waiting for one
        self._net_then = None           # what runs again once something can answer
        self._net_say = ("", "")        # (offline, given up) messages for it
        self._net_tries = 0
        self.src_show: dict = {}        # song -> (source, label) its page shows, to compare
        self._song_shown: list = []     # the lines the Song page shows (a click's index is into these)
        self._seek_when = None          # (song, seconds, give up at): seek once it plays
        self.player.shuffle = bool(v.home_shuffle)
        self.player.repeat = v.home_repeat
        self.lib.set_dirs(self.local_dirs())
        self.page, self.arg = "home", None
        self.stack: list[tuple] = []
        self.hits: list[tuple] = []
        self.hover = None
        self.press_at: QPointF | None = None
        self.pressed = None
        self.drag = None                    # an item being dragged to a target
        self.ctx = None                     # {"x", "y", "item", "sub"}
        self.popover = False
        self.note = None                    # (text, undo, until)
        self.filters: dict[str, str] = {}
        self.chart = "Global"
        self.stat_per = "Month"
        self.search_tab = "Top results"
        self.sel = -1
        self.pl_edit = False
        self.pl_order: dict[str, list] = {}
        self.liked: set[str] = set()                # Spotify's liked uris
        self.sp_liked: list[dict] = []
        self.ob_step = 0 if (not v.home_onboarded and v.first_run) else None
        self.ob_pct = 0.0
        self.mini = False
        self.mini_win = None
        self.mhits: list[tuple] = []
        self._mini_was = None
        self.drops: list[tuple] = []
        self.u = 1.0
        self.bp = "L"
        self.content = QRectF()
        self._wash_key = None
        self._wash_pm: QPixmap | None = None
        self._fonts: dict = {}
        self._fms: dict = {}
        self._recs: dict[str, list] = {}
        self._recs_note: dict[str, str] = {}
        self._recs_at: dict[str, float] = {}
        self._q_timer = QTimer()
        self._q_timer.setSingleShot(True)
        self._q_timer.setInterval(150)
        self._q_timer.timeout.connect(self.run_search)
        self._q_asked = ""
        self.lyr_files: list[dict] | None = None
        self.pending: tuple | None = None       # (data key, shuffle) to play here once it lands
        self.words: dict[str, dict | None] = {}
        self._mixes: dict[str, dict] = {}       # your own mixes, as put together this session
        self._mix_asked: dict[str, float] = {}  # when each mix was first asked for
        self._wb = _WordsBridge()
        self.words_ready = self._wb.done
        self.words_ready.connect(self.on_words)

    # ================================================================ data
        self.load_mirror()                      # Spotify's library as last seen, until it answers
    def local_dirs(self) -> list[str]:
        """The chosen folders; ~/Music until any are chosen, none once all are removed."""
        got = [d for d in str(self.v.home_local_dirs or "").split("\n") if d.strip()]
        if not got and self.v.home_local_dirs != NO_DIRS:
            music = pathlib.Path.home() / "Music"
            got = [str(music)] if music.is_dir() else []
        return got

    @property
    def online(self) -> bool:
        """Spotify's page answers: its catalogue and the library are there."""
        return self.v.fetcher.cdp is not None

    @property
    def cat(self):
        """The catalogue pages and charts come from: Spotify's, else Deezer's."""
        return self.spot if self.online else self.dz

    @property
    def cat_q(self):
        """Search: Deezer's (Apple-ordered), Spotify or not, unless songs are set to play in Spotify.
        Deliberately independent of Spotify (2026-10-22)."""
        return self.spot_q if self.online and self.v.home_play_in == "Spotify" else self.dz_q

    def src(self, uri: str):
        return self.dz if (uri or "").startswith("deezer:") else self.spot

    def search_src(self, q: str):
        """What the search box asks: a pasted link is read as that link, anything else searched."""
        return self.links if PLK.find(q) else self.cat_q

    def play_link(self, text: str) -> None:
        """Play what a pasted link is (see pasted_links); the answer lands in on_got."""
        self.pending_link = text
        got = self.links.found(text)
        if got is not None:
            self.on_got("search:" + text, got)
        else:
            self.links.lookup(text)

    def played_link(self, got) -> None:
        text = self.pending_link or ""
        link = PLK.find(text)
        self.pending_link = None
        name = PLK.NAMES.get((got or {}).get("service") or (link.service if link else ""), "")
        what = f"{name} link" if link and link.kind != "id" else "id"
        if got and got.get("choices"):          # a bare number more than one service has: let them pick
            self.v.open_browse("home")
            self.go("search")
            self.v.bq_field.set_text(text)
            self.search_changed()
            self.v.toast("that id is a song on more than one service — pick which")
            return
        top = (got or {}).get("top_item")
        if not got or got.get("error") or not top:
            self.v.toast(f"couldn’t read that {what}" + (f": {got['error']}" if got and got.get("error") else ""))
            return
        if top.get("kind") != "track" and not top.get("tracks") and not top.get("uri"):
            self.v.toast(f"nothing playable behind that {what}")
            return
        self.play(top, got.get("tracks") if top.get("kind") == "track" else None)
        self.v.toast(f"playing {top.get('name') or 'it'}" + (f" — {top['sub']}" if top.get("sub") else "")
                     + (f" (from {name})" if name else ""))

    def play_in(self) -> str:
        """Which player a song picked here goes to: "spotify" or "mild"."""
        want = self.v.home_play_in
        if want == "Mild Lyrics":
            return "mild"
        if want == "Spotify":
            return "spotify"
        if self.v.home_main == "Mild Lyrics" or self.player.active:
            return "mild"                   # (or something is playing here now)
        return "spotify" if self.online else "mild"

    def shelf_chart(self) -> str:
        """The chart the Top songs shelf shows (Settings ▸ Home); without Spotify, Deezer's and Shazam's."""
        return self.v.home_chart if self.v.home_chart in CHARTS else "Global"

    def spotify_search(self, q: str) -> list[dict]:
        """Spotify's in-app search, from a resolver thread; [] while Spotify is away."""
        if not self.online:
            return []
        import json as _json
        got = self.v.fetcher._ask(HD.JS_SEARCH_FAST % _json.dumps(q)) or {}
        return got.get("tracks") or []

    def opened(self) -> None:
        """The page came up: ask for what it shows, if it has gone stale."""
        s = self.spot
        self._mixes.clear()
        self._mix_asked.clear()
        if self.online:
            s.liked()
            s.shelf("playlists")
        self.cat.feed()
        self.log.load()
        if self.v.home_shelf_charts:
            self.cat.chart(self.shelf_chart())
        self.want_page()
        self.build_recs()

    def want_page(self) -> None:
        pg, arg = self.page, self.arg
        s = self.src((arg or {}).get("uri", "")) if pg in ("playlist", "album", "artist", "artist_top") else self.cat
        if pg == "queue":
            self.v.fetcher.request_queue()
        elif pg == "charts":
            s.chart(self.filters.get("charts", self.shelf_chart()))
        elif pg in ("artists", "albums"):
            self.spot.shelf(pg)
        elif pg == "playlists":
            self.spot.shelf("playlists")
        elif pg == "playlist" and arg:
            s.playlist(arg.get("uri", ""))
        elif pg == "album" and arg:
            s.album(arg.get("uri", ""))
        elif pg in ("artist", "artist_top") and arg:
            s.artist(arg.get("uri", ""))
        elif pg == "song" and arg:
            for a in (arg.get("artists") or [])[:1]:
                if a.get("uri"):
                    self.src(a["uri"]).artist(a["uri"])
        elif pg == "local" and not self.lib.scanned_at and not self.lib.scanning:
            self.lib.scan()
        elif pg == "lyrics":
            self.lyr_files = None

    MIRRORED = ("liked", "playlists", "albums", "artists")

    def on_spot(self, key: str, val) -> None:
        """Spotify's library answers are kept, so it stays browsable while Spotify is away."""
        if val is None:
            return
        if key in self.MIRRORED:
            self.library.mirror(key, val)
        elif key.startswith("pl:") and any(x.get("uri") == key[3:] for x in self.spot.get("playlists") or []):
            self.library.mirror(key, val)
        if key == "liked" and isinstance(val, list):
            self.sp_liked = [dict(r, kind="track") for r in val]
            self.liked = {r["uri"] for r in val if r.get("uri")}
            self.flush_pending()

    def load_mirror(self) -> None:
        """Spotify's library as it was last seen, shown until Spotify answers again."""
        for key, val in (self.library.d.get("mirror") or {}).items():
            if key not in self.spot.data:
                self.spot.data[key] = (-1e9, val)
        if self.spot.get("liked"):
            self.on_spot("liked", self.spot.get("liked"))

    @property
    def liked_rows(self) -> list[dict]:
        """Liked songs: Mild Lyrics' own, then Spotify's that are not among them."""
        mine = self.library.liked()
        have = {LIB.song_key(x) for x in mine}
        gone = {u for u, on in self.library.pending().items() if not on}
        return list(mine) + [r for r in self.sp_liked if LIB.song_key(r) not in have
                             and r.get("uri") not in gone]

    def is_liked(self, item: dict) -> bool:
        uri = item.get("uri") or ""
        if self.library.is_liked(item):
            return True
        return uri in self.liked and self.library.pending().get(uri) is not False

    def flush_pending(self) -> None:
        """Likes and unlikes made while Spotify was away, told to it now it answers."""
        if not self.online:
            return
        for uri, on in list(self.library.pending().items()):
            self.spot.like(uri, on)
            (self.liked.add if on else self.liked.discard)(uri)
            if not on:
                self.sp_liked = [r for r in self.sp_liked if r.get("uri") != uri]
            self.library.told(uri)

    def on_got(self, key: str, val) -> None:
        if self.pending_link is not None and key == "search:" + self.pending_link:
            self.played_link(val)
        if key.startswith(("radio:", "search:", "artist:", "top:", "related:")) and self.auto_want:
            QTimer.singleShot(0, self.autoplay_fill)
        if key.startswith(("radio:", "search:", "artist:", "top:", "related:")) \
                and getattr(self, "_radio_want", None):
            want, self._radio_want = self._radio_want, None
            QTimer.singleShot(0, lambda: self.song_radio(want))
        if key.startswith(("artist:", "search:")) or key in ("feed", "liked"):
            self._recs_at.clear()
        if key == "country" and self.page == "charts":
            self.spot.chart(self.filters.get("charts", "Global"))
        if self.pending and self.pending[0].startswith("mix:"):
            data = self.pl_data(self.pending[0][4:])
            if data and data.get("tracks"):
                shuffle = self.pending[1]
                self.pending = None
                self.play_stream(data["tracks"][0], data["tracks"], shuffle)
        if self.pending and key == self.pending[0] and isinstance(val, dict):
            _key, shuffle = self.pending
            self.pending = None
            rows = [dict(t, kind="track") for t in val.get("tracks") or []]
            if rows:
                self.play_stream(rows[0], rows, shuffle)
        if self.v.view == "browse":
            self.build_recs()
            self.v.update()

    def on_did(self, tag: str, val) -> None:
        if val is True or (tag == "pl_create" and val):
            if tag.startswith(("pl_add:", "pl_remove:", "pl_move:")):
                self.spot.drop("pl:" + tag.split(":", 1)[1])
                self.want_page()
            if tag == "pl_create":
                self.spot.drop("playlists")
                self.spot.shelf("playlists")
            if tag in ("queue_add", "queue_next", "queue_clear"):
                self.v.fetcher.request_queue()
            return
        self.say("Spotify would not do that" + (f": {str(val)[:80]}" if val else ""))
        if tag.startswith(("like:", "unlike:")):
            self.say("Saved in Mild Lyrics; Spotify would not take it" + (f": {str(val)[:60]}" if val else ""))
            self.spot.drop("liked")
            self.spot.liked(keep=0)

    def on_words(self, key: str, got) -> None:
        if key.startswith("editor|"):
            self.launch_editor(got)
            return
        self.words[key] = got
        self.v.update()

    def on_local(self) -> None:
        self.v.update()

    def kind_of(self, item: dict) -> str | None:
        """'w' word-by-word, 'l' line, 'r' romanised, 'n' none -- or None if not known here."""
        if "_k" in item:
            return item["_k"]
        if item.get("_track") is not None:
            got = self.track_kind(item["_track"])
            if got:
                return got
        tid = tid_of(item.get("uri", "")) or item.get("tid") or self.tid_by_name(item)
        if not tid:
            return None
        got = self.kinds.get(tid)
        if got:
            return got
        s = self.v.index.by_id.get(tid)
        if s is None:
            return None
        return "r" if s.get("roman") else "w" if s.get("synced") else "l"

    def track_kind(self, t: dict) -> str | None:
        """A local-player song's kind, under either id fetch-ahead and the load keep it by (local_ahead)."""
        import lyric_sources as LS
        key = LP._key(t.get("title", ""), t.get("artist", ""))
        sid = self.resolver.spotify_of(t) or LS.spotify_id_known(key) or ""
        return self.kinds.get(sid) or self.kinds.get(t.get("tid") or key)

    def tid_by_name(self, item: dict) -> str:
        """A catalogue row's track id (a Deezer row has none) by its name: the playing
        song's, else the one the play log heard it as."""
        key = (AP.title_of(item), AP.artist_of(item))
        if not key[0]:
            return ""
        meta = self.v.clock.meta or {}
        if self.v.clock.tid and key == (AP.title_of(meta), AP.artist_of(meta)):
            return self.v.clock.tid
        if self._names_rev != self.log.rev:
            self._names = {(AP.title_of(r), AP.artist_of(r)): r["tid"] for r in self.log.load() if r.get("tid")}
            self._names_rev = self.log.rev
        return self._names.get(key, "")

    # ============================================================ actions
    def go(self, page: str, arg=None, push: bool = True) -> None:
        if push and page in ("home", "search") or page in [k for k, _l, _i in TOP_NAV + LIB_NAV]:
            self.from_lyrics = False
        if push and (page, arg) != (self.page, self.arg):
            self.stack.append((self.page, self.arg, self.v.browse_scroll_target))
            del self.stack[:-40]
        self.page, self.arg = page, arg
        self.ctx, self.popover, self.sel, self.pl_edit = None, False, -1, False
        self.v.browse_tab = "search" if page == "search" else "home"
        self.v.browse_scroll = self.v.browse_scroll_target = 0.0
        self.want_page()
        self.v.update()

    def back(self) -> bool:
        if not self.stack:
            if getattr(self, "from_lyrics", False):
                self.from_lyrics = False
                self.v.close_browse()
                return True
            return False
        page, arg, scroll = self.stack.pop()
        self.go(page, arg, push=False)
        self.v.browse_scroll = self.v.browse_scroll_target = scroll
        return True

    def toggle_queue(self) -> None:
        """The queue button: the queue, or from the queue back to where it was opened from."""
        if self.page != "queue" or not self.back():
            self.go("queue")

    def say(self, text: str, undo=None) -> None:
        self.note = (text, undo, time.monotonic() + 5.0)
        self.v.update()

    def can_play(self) -> bool:
        return not self.v.listen.holds("play")

    def play(self, item: dict, context: list | None = None, ctx_uri: str = "") -> None:
        """Play a card or a row, in whichever player it belongs to."""
        if not self.can_play():
            self.say("Listening along: the host picks the songs")
            return
        k = item.get("kind")
        if k == "local":
            self.play_here(item, context or [item])
            return
        uri = item.get("uri") or ""
        if not uri:
            if self.likeable(item) or item.get("tracks"):    # known only by name, or a pasted link's: stream it
                self.play_here(item, context)
            return
        if self.play_in() == "mild" or uri.startswith(("deezer:", "mild:", "youtube:")) or uri == "liked":
            self.play_here(item, context)
            return
        self.release_pin_for("spotify")
        if self.player.active:
            self.player.stand_down()
        if ctx_uri and k == "track":
            self.v.fetcher.request_play_in(ctx_uri, uri)
        else:
            self.v.fetcher.request_play(uri)
        self.v.skip_at = time.monotonic()

    @staticmethod
    def stream_of(item: dict) -> dict:
        """A song as the local player's track: a file stays a file, anything else streams."""
        if item.get("_track"):
            return item["_track"]
        if item.get("path"):
            return {"path": item["path"], "title": item.get("title") or item.get("name", ""),
                    "artist": item.get("artist") or item.get("sub", ""), "album": item.get("album", ""),
                    "art": item.get("art", ""), "ms": item.get("ms") or 0, "tid": item.get("tid", "")}
        uri = item.get("uri") or ""
        return {"stream": True, "title": item.get("song") or item.get("name", ""),
                "artist": item.get("song_by") or item.get("sub", ""),
                "album": item.get("album", ""), "art": item.get("art", ""), "ms": item.get("ms") or 0,
                "spotify": uri.rsplit(":", 1)[-1] if uri.startswith("spotify:track:") else "", "uri": uri,
                "yt": item.get("yt", ""), "isrc": item.get("isrc", "")}

    def play_here(self, item: dict, context: list | None = None, shuffle: bool = False) -> None:
        """Play a song, an album, a playlist or an artist in Mild Lyrics' own player."""
        k = item.get("kind")
        if k in ("track", "local", "song"):
            rows = [r for r in (context or []) if r.get("kind") in ("track", "local", "song")] or [item]
            self.play_stream(item, rows, shuffle)
            return
        if item.get("tracks"):
            rows = list(item["tracks"])
            self.play_stream(rows[0], rows, shuffle)
            return
        uri = item.get("uri") or ""
        if uri.startswith("mild:") or uri == "liked":
            data = self.pl_data(uri) if uri != "liked" else {"tracks": self.liked_rows}
            rows = (data or {}).get("tracks")
            if rows:
                self.play_stream(rows[0], rows, shuffle)
            elif data is None and uri.startswith("mild:mix:"):
                self.pending = ("mix:" + uri, shuffle)
                self.say(f"Putting {item.get('name', 'it')} together…")
            else:
                self.say("Nothing in it to play yet")
            return
        src = self.src(uri)
        key = {"album": "album:", "artist": "artist:", "playlist": "pl:"}.get(k, "") + uri
        got = src.get(key)
        if got and got.get("tracks"):
            rows = [dict(t, kind="track") for t in got["tracks"]]
            self.play_stream(rows[0], rows, shuffle)
            return
        self.pending = (key, shuffle)
        getattr(src, {"album": "album", "artist": "artist", "playlist": "playlist"}.get(k, "album"))(uri)
        self.say(f"Getting {item.get('name', 'it')} ready…")

    def play_stream(self, item: dict, rows: list, shuffle: bool = False) -> None:
        self.release_pin_for("mild")
        tracks = [self.stream_of(r) for r in rows]
        i = next((n for n, r in enumerate(rows) if r is item), None)
        if i is None:
            i = next((n for n, r in enumerate(rows) if LIB.song_key(r) == LIB.song_key(item)), 0)
        was = self.player.shuffle
        if shuffle:
            self.player.shuffle = True
        ok = self.player.play(tracks, i)
        self.player.shuffle = was
        if not ok:
            self.say("Qt Multimedia is not available, so songs cannot play here")
            return
        QTimer.singleShot(0, self.autoplay_fill)          # autoplay's songs queued now, not near the end
        if self.online:
            self.pause_spotify()
        self.say(f"Playing {item.get('name', '')} in Mild Lyrics")

    # ------------------------------------------------------------ autoplay
    def autoplay_fill(self) -> None:
        """Keep about AP.AHEAD songs like the one you chose queued after Mild Lyrics' own queue.

        Follows the anchor (the last song chosen by hand) and autoplay's songs heard since it,
        never skipped ones; candidates from auto_candidates, ranked by autoplay.pick. Waits while
        an ask is on its way so the sources fuse; when_online waits for a connection. On a rebuild
        (auto_rebuild) the old run stays until new picks replace it, and stays if none come."""
        pl = self.player
        if not self.v.home_autoplay or not pl.queue or self.v.listen.role == "hear":
            self.auto_want = False              # (listening along: the sharer picks every song)
            return
        urgent = pl.ended or pl.wants_next
        queued = len(pl.queue) - pl.idx - 1
        hand = [t for t in pl.queue[pl.idx + 1:] if not t.get("_auto")]
        ahead = len(hand) if self.auto_rebuild else queued
        if ahead >= AP.TOP_UP_BELOW and not urgent:
            self.auto_want = False
            return
        if hand and len(hand) >= AP.TOP_UP_BELOW:
            self.auto_want = False
            return
        anchor, _ok = self.auto_seeds()
        akey = LIB.song_key(anchor) if anchor else ""
        if akey != self.auto_anchor:                # a new song chosen: its skips start over
            self.auto_anchor, self.skipped_artists, self.auto_skips = akey, {}, 0
        liked = {AP.title_of(x) + "|" + AP.artist_of(x) for x in self.liked_rows}
        song = lambda r: AP.norm(r.get("title", "")) + "|" + AP.norm((r.get("artist") or "").split(",")[0])
        # Liked songs are what you want to hear again: only this queue and the last few plays keep them out
        heard_titles = {AP.norm(t.get("title", "")) for t in pl.queue[max(0, pl.idx - 50):]}
        heard_titles |= {AP.norm(r.get("title", "")) for i, r in enumerate(self.log.recent(80))
                         if i < AP.LIKED_REST or song(r) not in liked}
        heard_songs = {song(r) for r in self.log.recent(300)} - liked
        used = lambda t: AP.title_of(t) in heard_titles or f"{AP.title_of(t)}|{AP.artist_of(t)}" in heard_songs
        cands, waiting, failed = self.auto_candidates(drop=used)
        if waiting and not urgent:
            self.auto_want = True                   # the rest lands within seconds: fuse them all
            return
        if not cands:
            self.auto_want = waiting
            if self.auto_rebuild and queued > ahead:
                self.auto_rebuild = waiting         # nothing new: the old run plays on
            elif failed and not waiting:
                self.when_online(self.autoplay_fill, "You're offline: autoplay carries on once you're back online",
                                 "Autoplay found no songs: the song sources are not answering")
            elif not waiting and queued == 0:
                self.say("Autoplay found no songs like this one")
            return
        self.auto_want = False
        self._net_tries = 0
        banned = self.banned_keys()
        tops = self.log.top_artists(int(self.v.home_look or 30), 20)
        most = max([n for _a, n in tops] or [1])
        fav = {AP.norm(a): n / most for a, n in tops}
        want = max(0, AP.AHEAD - ahead)
        got = AP.pick(cands, want, (anchor or {}).get("artist", ""), heard_titles, heard_songs, banned, liked, fav,
                      wbw=self.kind_of, prefer_wbw=bool(self.v.home_prefer_wbw),
                      skipped_artists=self.skipped_artists)
        if not got:
            self.auto_rebuild = False
            return
        new = [dict(self.stream_of(t), _auto=True, _hop=t.get("_hop", 1)) for t in got]
        if self.auto_rebuild:
            self.auto_rebuild = False
            pl.replace_after(hand + new)
        else:
            pl.enqueue(new)
        self.auto_smooth()
        if self.auto_resume or pl.ended:
            self.auto_resume = False
            pl.resume_after_end()

    def auto_smooth(self) -> None:
        """Autoplay's songs still to come, reordered so none comes in much quieter than the song
        before it (AP.smooth, loudness from self.loud); songs queued by hand never move."""
        pl = self.player
        if not pl.queue or self.v.listen.role == "hear":
            return
        q, out, prev, i = pl.queue, [], pl.current, pl.idx + 1
        for t in q[i:]:
            if t.get("_auto") and "_ord" not in t:      # pick's order, so each pass starts from it
                self._auto_ord += 1
                t["_ord"] = self._auto_ord
        while i < len(q):
            j = i
            while j < len(q) and q[j].get("_auto"):
                j += 1
            if j == i:
                prev = q[i]
                out.append(prev)
                i += 1
                continue
            out += AP.smooth(prev, sorted(q[i:j], key=lambda t: t["_ord"]), self.loud.get)
            prev, i = out[-1], j
        if any(a is not b for a, b in zip(out, q[pl.idx + 1:])):
            pl.replace_after(out)

    def auto_seeds(self) -> tuple[dict | None, list[dict]]:
        """(anchor, heard): the last song chosen by hand at or before the one playing, and up to two
        of autoplay's songs after it that were listened to and came from the anchor's own lists
        (AP.SEED_HOPS), so the run never wanders off it. A skipped song never seeds."""
        pl = self.player
        q = pl.queue[:pl.idx + 1] or pl.queue[-1:]
        at = next((i for i in range(len(q) - 1, -1, -1) if not q[i].get("_auto")), 0)
        if not q:
            return None, []
        near = [t for t in q[at + 1:] if t.get("_heard") and t.get("_hop", AP.SEED_HOPS + 1) <= AP.SEED_HOPS]
        return q[at], near[::-1][:2]

    def auto_heard(self, row: dict) -> None:
        """An autoplay song ended (the tracker's row). A skip counts against its artist and drops
        the artist's other queued picks; two skips in a row make the rest again from the anchor."""
        pl = self.player
        if not row.get("auto") or not pl.active or not self.v.home_autoplay:
            return
        if not row.get("skip"):
            self.auto_skips = 0
            return
        who = AP.artist_of(row)
        self.skipped_artists[who] = self.skipped_artists.get(who, 0) + 1
        self.auto_skips += 1
        after = pl.queue[pl.idx + 1:]
        if self.auto_skips >= 2:
            self.auto_skips = 0
            keep = [t for t in after if not t.get("_auto")]          # songs queued by hand never move
            if len(keep) < AP.TOP_UP_BELOW:
                # the run is made again, but held until its replacement lands: emptied first, a
                # refill that found nothing left the queue empty (2026-10-28)
                self.auto_rebuild = True
                QTimer.singleShot(0, self.autoplay_fill)
                return
        else:
            keep = [t for t in after if not (t.get("_auto") and AP.artist_of(t) == who)]
        if len(keep) != len(after):
            pl.replace_after(keep)
            QTimer.singleShot(0, self.autoplay_fill)

    def auto_candidates(self, seeds: list | None = None, drop=None) -> tuple[list, bool, bool]:
        """(candidate songs, best first; whether more are on their way; whether an ask failed).
        Seeded by `seeds` (player tracks), else auto_seeds. YouTube Music's song radio for each seed,
        Spotify's when it answers, Deezer's artist radio for the first, fused by rank (AP.fuse, which
        leaves out what `drop` says); related artists' top songs only when those are too few.
        Each song carries `_hop`: 1 from the first seed's lists, 2 from a later seed's."""
        if seeds is None:
            anchor, heard = self.auto_seeds()
            seeds = [anchor] + heard if anchor else []
        lists, weights, state = [], [], {"waiting": False, "failed": False}

        def need(src, key: str, ask):
            got = src.get(key)
            if got is None:
                if src.failed(key):
                    state["failed"] = True
                else:
                    ask()
                    state["waiting"] = True
            return got

        def add(tracks: list, w: float, leave: str = "", hop: int = 1) -> int | None:
            tracks = [dict(x, kind="track", _hop=hop) for x in tracks if not leave or x.get("uri") != leave]
            if tracks:
                lists.append(tracks)
                weights.append(w)
                return len(lists) - 1
            return None

        own = None                                      # where the anchor's YouTube Music radio is in lists
        for n, t in enumerate(seeds[:3]):
            w = 1.0 if n == 0 else 0.5                  # the anchor leads; songs heard since widen it
            vid = self.resolver.yt_of(t)
            if vid:
                got = need(self.yt, "radio:youtube:" + vid, lambda: self.yt.radio(vid))
                if got is not None:
                    at = add(got.get("tracks") or [], w, hop=1 + (n > 0))
                    own = at if n == 0 else own
            sid = self.resolver.spotify_of(t) if t.get("stream") else t.get("spotify", "")
            if self.online and sid and n < 2:
                got = need(self.spot, "radio:spotify:track:" + sid,
                           lambda: self.spot.radio("spotify:track:" + sid))
                if got is not None:
                    add(got.get("tracks") or [], w, "spotify:track:" + sid, 1 + (n > 0))
        if seeds:
            a, wait, fail = self.dz_artist_of(seeds[0])
            state["waiting"] |= wait
            state["failed"] |= fail
            if a is not None:
                uri = a["uri"]
                r = need(self.dz, "radio:" + uri, lambda: self.dz.radio(uri))
                if r is not None:
                    add(r.get("tracks") or [], 0.5)
                    if own is not None and AP.stray(lists[own], r.get("tracks") or []):
                        weights[own] = AP.STRAY_W           # its music video's radio stands in
                        a0 = seeds[0]
                        title, who = a0.get("title") or a0.get("name") or "", a0.get("artist") or a0.get("sub") or ""
                        mv = need(self.yt, f"mv:{title}|{who}", lambda: self.yt.video_of(title, who))
                        mvid = (mv or {}).get("vid") or ""
                        if mvid and mvid != self.resolver.yt_of(a0):
                            got = need(self.yt, "radio:youtube:" + mvid, lambda: self.yt.radio(mvid))
                            if got is not None:
                                add(got.get("tracks") or [], 1.0)
                if len(AP.fuse(lists)) < AP.AHEAD and not state["waiting"]:
                    # one ask each for the related list and their top songs, not a whole artist page
                    ag = self.dz.get("artist:" + uri) or need(self.dz, "related:" + uri, lambda: self.dz.related(uri))
                    for ra in ((ag or {}).get("related") or [])[:6]:
                        ru = ra["uri"]
                        rg = self.dz.get("artist:" + ru) or need(self.dz, "top:" + ru, lambda: self.dz.top(ru))
                        if rg is not None:
                            add((rg.get("tracks") or [])[:4], 0.25)
        return AP.fuse(lists, weights, drop=drop), state["waiting"], state["failed"]

    def dz_artist_of(self, t: dict) -> tuple[dict | None, bool, bool]:
        """(Deezer artist, still asking, an ask failed) for a song: the first of its credited
        artists Deezer knows by that name, else the artist of Deezer's own copy of the song.
        Names are taken in order, waiting on each: "Men" answering first took Of Mice & Men."""
        names = [a.get("name", "") for a in t.get("artists") or [] if isinstance(a, dict)]
        names = [n for n in names + credit_names(t.get("artist") or t.get("sub") or "") if n]
        failed = False
        for who in dict.fromkeys(names):
            found = self.dz.found(who)
            if found is None:
                if self.dz.failed("search:" + who):
                    failed = True
                    continue
                self.dz.lookup(who)
                return None, True, failed
            a = SS.best_artist(found.get("artists") or [], who)     # not "NF!" for NF
            if a is not None:
                return a, False, False
        title = t.get("title") or t.get("name") or ""
        if title and names:
            q = f"{title} {names[0]}"
            found = self.dz.found(q)
            if found is None:
                if self.dz.failed("search:" + q):
                    return None, False, True
                self.dz.lookup(q)
                return None, True, failed
            for x in found.get("tracks") or []:
                if SS.norm(x.get("name", "")) == SS.norm(title) and (x.get("artists") or [{}])[0].get("uri"):
                    a = x["artists"][0]
                    return {"name": a.get("name", ""), "uri": a["uri"]}, False, False
        return None, False, failed

    def autoplay_ran_out(self) -> None:
        if self.v.home_autoplay:
            self.auto_resume = True
            self.autoplay_fill()

    # ------------------------------------------------------------ nothing online answered
    def when_online(self, then, offline: str, gave_up: str) -> None:
        """Nothing online answered: see whether there is a connection at all. Offline, say
        so and run `then` once it is back; connected, the sources failed, so try again a
        few times. Never a queue made out of nothing."""
        self._net_then, self._net_say = then, (offline, gave_up)
        self.net.ask()

    def on_net(self, up: bool) -> None:
        then = self._net_then
        if then is None:
            self.net_down = False
            return
        if not up:
            if not self.net_down:
                self.net_down = True
                self.say(self._net_say[0])
                self.v.update()
            QTimer.singleShot(int(NET_POLL * 1000), self.net.ask)
            return
        self._net_then = None
        if self.net_down:                                    # back online: ask everything again
            self.net_down = False
            self._net_tries = 0
            self.spot.fails.clear()
            self.dz.fails.clear()
            self.yt.fails.clear()
            self.v.update()
            then()
            return
        self._net_tries += 1
        if self._net_tries > NET_RETRIES:
            self._net_tries = 0
            self.say(self._net_say[1])
            return
        if self._net_tries == 1:
            self.say("The song sources are not answering: trying again shortly")
        QTimer.singleShot(int(NET_RETRY * 1000), then)

    # ------------------------------------------------------------ lyrics, copied
    def copy_menu(self, line: str, gpos) -> None:
        from PyQt6.QtWidgets import QApplication, QMenu
        menu = QMenu(self.v)
        one = menu.addAction("Copy line")
        every = menu.addAction("Copy all lyrics")
        chosen = menu.exec(gpos)
        if chosen is one:
            QApplication.clipboard().setText(line)
            self.say("Line copied")
        elif chosen is every:
            self.copy_lyrics(self._song_shown)

    def copy_lyrics(self, lines: list) -> None:
        from PyQt6.QtWidgets import QApplication
        text = "\n".join((("  " if ln.get("background") else "") + (ln.get("text") or "").strip())
                          for ln in lines if (ln.get("text") or "").strip())
        QApplication.clipboard().setText(text)
        self.say("Lyrics copied")

    # ------------------------------------------------------------ song radio
    def song_radio(self, item: dict) -> None:
        """Make a queue from this song: it, then songs like it, in place of the queue there was.

        In Spotify, Spotify's own song radio (the mix its "Go to song radio" plays), from
        the song. In Mild Lyrics' player, the song and autoplay's picks seeded by it."""
        if not self.can_play():
            self.say("Listening along: the host picks the songs")
            return
        seed = self.stream_of(item)
        sid = seed.get("spotify") or ""
        here = self.player.active and self.is_playing(item)     # playing in Mild Lyrics: it stays here
        name = item.get("name", "it")
        again = (lambda: self.song_radio(item), f"You're offline: the queue from {name} is made once you're back online",
                 f"No queue from {name}: the song sources are not answering")
        if self.play_in() == "spotify" and self.online and sid and not here:
            got = self.spot.get("radio:spotify:track:" + sid)
            if got is None and self.spot.failed("radio:spotify:track:" + sid):
                self._radio_want = None
                self.when_online(*again)
                return
            if got is None:
                self.spot.radio("spotify:track:" + sid)
                self._radio_want = item
                self.say(f"Making a queue from {item.get('name', 'it')}…")
                return
            self._radio_want = None
            self.release_pin_for("spotify")
            was_here = self.player.active
            if was_here:
                self.player.stand_down()
            if self.is_playing(item) and not was_here:
                # already playing in Spotify: the radio carries on from where it is, not from 0:00
                self.v.fetcher.request_play_in(got["uri"], "spotify:track:" + sid,
                                               int((self.v.song_position() + 0.25) * 1000))
            else:
                self.v.fetcher.request_play_in(got["uri"], "spotify:track:" + sid)
            self.say(f"Playing a queue made from {item.get('name', 'it')}")
            return
        cands, waiting, failed = self.auto_candidates([seed])
        if waiting:                                      # every source in before the queue is made
            self._radio_want = item
            self.say(f"Making a queue from {item.get('name', 'it')}…")
            return
        self._radio_want = None
        if not cands:
            if failed:
                self.when_online(*again)
            else:
                self.say("No songs like this one were found")
            return
        self._net_tries = 0
        banned = self.banned_keys()
        picks = AP.pick(cands, AP.AHEAD, seed.get("artist", ""), {AP.norm(seed.get("title", ""))}, set(),
                        banned, {AP.title_of(x) + "|" + AP.artist_of(x) for x in self.liked_rows}, {},
                        wbw=self.kind_of, prefer_wbw=bool(self.v.home_prefer_wbw))
        pl = self.player
        if here:
            # the song is playing here: it plays on, and what follows it is the new queue
            (pl.current or {}).pop("_auto", None)       # chosen now: autoplay follows it
            pl.replace_after([dict(self.stream_of(t), _auto=True, _hop=t.get("_hop", 1)) for t in picks])
            self.auto_smooth()
            self.say(f"Queue made from {item.get('name', 'it')}")
            return
        rows = [dict(item, kind=item.get("kind") or "track")] + [dict(t, kind="track") for t in picks]
        self.play_stream(rows[0], rows)
        for t in pl.queue[1:]:
            t["_auto"] = True
        self.auto_smooth()
        self.say(f"Playing a queue made from {item.get('name', 'it')}")

    def pause_spotify(self) -> None:
        self.spot.act("pause", "(() => { try { if (Spicetify.Player.isPlaying())"
                               " Spicetify.Player.pause(); return true; } catch (e) { return true; } })()")

    def queue(self, item: dict, next_: bool = False) -> None:
        if item.get("kind") == "local":
            self.player.enqueue([item.get("_track") or item], next_)
            self.say(f"“{item.get('name', '')}” " + ("plays next" if next_ else "added to the queue"))
            return
        if self.player.active or self.play_in() == "mild" or (item.get("uri") or "").startswith("deezer:"):
            rows = item.get("tracks") or [item]
            if self.likeable(item) or item.get("tracks"):
                self.player.enqueue([self.stream_of(r) for r in rows], next_)
            self.say(f"“{item.get('name', '')}” " + ("plays next" if next_ else "added to the queue"))
            return
        uris = [item["uri"]] if item.get("uri") else []
        if item.get("kind") in ("album", "playlist") and item.get("tracks"):
            uris = [t["uri"] for t in item["tracks"] if t.get("uri")]
        if not uris:
            return
        self.spot.queue_add(uris, next_)
        self.say(f"“{item.get('name', '')}” " + ("plays next" if next_ else "added to the queue"))

    def likeable(self, item: dict) -> bool:
        return item.get("kind") in ("track", "local", "song", None) and bool(item.get("name") or item.get("title"))

    def like(self, item: dict) -> None:
        """Liked in Mild Lyrics, and in Spotify too when it is a Spotify song and Spotify is there."""
        if not self.likeable(item):
            return
        uri = item.get("uri") or ""
        on = not self.is_liked(item)
        was_lib = self.library.is_liked(item)
        self.library.like(item, on)
        sp = uri.startswith("spotify:track:") and self.online and (on or uri in self.liked)
        pend = uri.startswith("spotify:track:") and not self.online and (on or uri in self.liked)
        was_pending = self.library.pending().get(uri)
        if sp:
            (self.liked.add if on else self.liked.discard)(uri)
            if not on:
                self.sp_liked = [r for r in self.sp_liked if r.get("uri") != uri]
            self.spot.like(uri, on)
        elif pend:
            self.library.pend(uri, on)          # told to Spotify when it answers again

        def undo():
            self.library.like(item, was_lib)
            if pend:
                if was_pending is None:
                    self.library.told(uri)
                else:
                    self.library.pend(uri, was_pending)
            if sp:
                (self.liked.discard if on else self.liked.add)(uri)
                if not on:
                    self.sp_liked.insert(0, dict(item, kind="track"))
                self.spot.like(uri, not on)
        self.say("Added to Liked songs" if on else "Removed from Liked songs", undo)

    def hide(self, item: dict) -> None:
        key = (item.get("name", "") + "|" + item.get("sub", "")).lower()
        was = self.v.home_hidden
        self.v.home_hidden = (was + "\n" + key).strip()
        self._recs_at.clear()
        self.build_recs()

        def undo():
            self.v.home_hidden = was
            self._recs_at.clear()
            self.build_recs()
        self.say(f"Won’t suggest “{item.get('name', '')}” again", undo)

    def hidden(self) -> set[str]:
        return {x for x in str(self.v.home_hidden or "").split("\n") if x}

    def hide_artist(self, item: dict) -> None:
        """Never suggest this artist: kept with the hidden songs as "*|artist"."""
        name = item.get("name", "")
        was = self.v.home_hidden
        self.v.home_hidden = (was + "\n*|" + AP.norm(name)).strip()
        self._recs_at.clear()
        self._mixes.clear()
        self.build_recs()

        def undo():
            self.v.home_hidden = was
            self._recs_at.clear()
            self.build_recs()
        self.say(f"Won’t suggest {name} again", undo)

    def artist_mix(self, item: dict) -> None:
        """A mix from this artist -- your songs by them, two like them after each -- played here."""
        name = item.get("name", "")
        if name:
            self.play({"uri": "mild:mix:artist:" + name, "kind": "playlist", "name": f"{name} Mix"})

    def hidden_artists(self) -> set[str]:
        return {x[2:] for x in self.hidden() if x.startswith("*|")}

    def banned_keys(self) -> set[str]:
        """Hidden and twice-skipped songs as autoplay.pick keys, and hidden artists as "*|artist"."""
        out = set()
        for x in self.hidden() | (self.log.skipped() if self.v.home_drop_skips else set()):
            out.add(x if x.startswith("*|") else
                    AP.norm(x.split("|")[0]) + "|" + AP.norm(x.split("|")[-1].split(",")[0]))
        return out

    def clear_hidden(self) -> None:
        """Forget every song and artist dismissed from suggestions (Settings ▸ Home)."""
        was = self.v.home_hidden
        n = len(self.hidden())
        if not n:
            self.say("Nothing dismissed")
            return
        self.v.home_hidden = ""
        self._recs_at.clear()
        self._mixes.clear()
        self.build_recs()

        def undo():
            self.v.home_hidden = was
            self._recs_at.clear()
            self.build_recs()
        self.say(f"Suggestions start over · {n} dismissed {'one is' if n == 1 else 'ones are'} back", undo)

    def add_to_playlist(self, pl: dict, item: dict) -> None:
        rows = item.get("tracks") if item.get("kind") in ("album", "playlist") else [item]
        rows = [r for r in rows or [] if self.likeable(dict(r, kind=r.get("kind") or "track"))]
        if (pl.get("uri") or "").startswith("mild:playlist:"):
            pid = pl["uri"].rsplit(":", 1)[-1]
            n = self.library.add(pid, rows)
            self.say(f"Added to {pl.get('name', 'the playlist')}" if n else f"Already in {pl.get('name', 'it')}")
            return
        uris = [r["uri"] for r in rows if (r.get("uri") or "").startswith("spotify:track:")]
        if not uris:
            self.say("Spotify playlists only take Spotify songs")
            return
        self.spot.pl_add(pl["uri"], uris)
        self.say(f"Added to {pl.get('name', 'the playlist')}")

    def new_playlist(self, with_item: dict | None = None) -> None:
        name, ok = self.v.ask_text("New playlist", "Name")
        name = name.strip() if ok else ""
        if not name:
            return
        pl = self.library.create(name, [with_item] if with_item and self.likeable(with_item) else None)
        self.say(f"Made “{pl['name']}”")
        self.go("playlist", self.pl_item(pl))

    def pl_item(self, pl: dict) -> dict:
        """A Mild Lyrics playlist as a tile, sidebar row or page subject."""
        items = pl.get("items") or []
        n = len(items)
        return {"uri": f"mild:playlist:{pl['id']}", "kind": "playlist", "name": pl.get("name", ""),
                "sub": f"{n} song{'s' if n != 1 else ''} · Mild Lyrics", "art": (items[0].get("art", "") if items else ""),
                "mine": True, "can_add": True, "local_pl": pl["id"]}

    def all_playlists(self) -> list[dict]:
        """Mild Lyrics' playlists, then Spotify's (as last seen, while it is away)."""
        return [self.pl_item(p) for p in self.library.playlists()] + \
            [x for x in (self.spot.get("playlists") or []) if x.get("kind") == "playlist"]

    def pl_data(self, uri: str) -> dict | None:
        """A playlist's page data, wherever the playlist lives."""
        if uri.startswith("mild:mix:"):
            return self.mix_data(uri)
        if uri.startswith("mild:playlist:"):
            pl = self.library.playlist(uri.rsplit(":", 1)[-1])
            if pl is None:
                return None
            items = [dict(x, kind=x.get("kind") or "track", _pi=i) for i, x in enumerate(pl["items"])]
            return {"uri": uri, "name": pl["name"], "mine": True, "owner": "you", "local": True,
                    "total": len(items), "art": items[0].get("art", "") if items else "", "tracks": items}
        return self.src(uri).get("pl:" + uri)

    def follow(self, item: dict) -> None:
        """Follow an artist or save an album, in Mild Lyrics (and Spotify, for its own, when it is there)."""
        on = not self.follows(item)
        self.library.follow(item, on)
        uri = item.get("uri") or ""
        if uri.startswith("spotify:") and self.online:
            self.spot.follow(uri, on)
            got = self.spot.get(("artist:" if item.get("kind") == "artist" else "album:") + uri)
            if got is not None:
                got["saved"] = on
        verb = ("Following" if on else "Stopped following") if item.get("kind") == "artist" else \
            ("Saved" if on else "Removed")
        self.say(f"{verb} {item.get('name', '')}", lambda: (self.library.follow(item, not on),
                                                             self.online and uri.startswith("spotify:")
                                                             and self.spot.follow(uri, not on)))

    def pl_remove(self, item: dict) -> None:
        uri = (self.arg or {}).get("uri", "")
        if uri.startswith("mild:playlist:"):
            pid = uri.rsplit(":", 1)[-1]
            i = item.get("_pi")
            gone = self.library.remove(pid, i) if i is not None else None
            if gone is not None:
                self.say(f"Removed “{gone.get('name', '')}”", lambda: self.library.insert(pid, i, gone))
            return
        self.spot.pl_remove(uri, [item])
        self.say(f"Removed “{item.get('name', '')}”")

    def pl_drop(self, item: dict, to: int) -> None:
        """A song dragged onto a row of the Mild Lyrics playlist being edited: moved there."""
        uri = (self.arg or {}).get("uri", "")
        if not uri.startswith("mild:playlist:"):
            return
        pid = uri.rsplit(":", 1)[-1]
        src = item.get("_pi")
        if src is None:
            self.library.add(pid, [item])
            n = len(self.library.playlist(pid)["items"]) - 1
            self.library.move(pid, n, to)
        elif src != to:
            self.library.move(pid, src, to)

    def follows(self, item: dict) -> bool:
        if self.library.follows(item):
            return True
        uri = item.get("uri") or ""
        mine = self.spot.get("artists" if item.get("kind") == "artist" else "albums") or []
        return any(x.get("uri") == uri for x in mine)

    def open_item(self, item: dict) -> None:
        k = item.get("kind")
        if k in ("album", "artist", "playlist"):
            if item.get("uri") == "liked":
                self.go("liked")
            else:
                self.go(k, item)
        elif k == "song":
            self.go("song", item)
        else:
            self.play(item)

    def open_lyrics(self) -> None:
        self.v.close_browse()

    def open_from_lyrics(self, kind: str, payload=None) -> None:
        """A click on the song, an artist or the album in the lyrics view: its page here,
        with the way back going to the lyrics."""
        v = self.v
        song = self.np_item_full()
        if kind == "song":
            arg = song
        elif kind == "album":
            uri = payload or song.get("album_uri") or \
                ((v.albums or {}).get(v.clock.tid or "") or {}).get("uri", "")
            arg = {"kind": "album", "uri": uri or "", "name": song.get("album", ""),
                   "sub": (song.get("sub") or "").split(",")[0].strip(), "art": song.get("art", "")}
        elif str(payload or "").startswith("name:"):     # a credit with no uri: the page finds it by name
            arg = {"kind": "artist", "uri": "", "name": payload[5:]}
        else:
            name = next((a.get("name", "") for a in song.get("artists") or [] if a.get("uri") == payload), "")
            arg = {"kind": "artist", "uri": payload or "", "name": name or (song.get("sub") or "").split(",")[0]}
        v.open_browse("home")
        self.stack.clear()
        self.go(kind, arg, push=False)
        self.from_lyrics = True

    def is_playing(self, it: dict) -> bool:
        tid = self.v.clock.tid or ""
        if not tid:
            return False
        uri = it.get("uri") or ""
        if uri.endswith(":" + tid):
            return True
        cur = self.player.current if self.player.active else None
        return bool(cur and cur.get("uri") and cur.get("uri") == uri)

    def open_words(self, it: dict) -> None:
        """Open lyrics: the lyrics view for the song playing, a read-through page for any other."""
        if self.is_playing(it):
            self.open_lyrics()
            return
        self.go("words", dict(it))
        self.fetch_words(it)

    def fetch_words(self, it: dict) -> None:
        """Its lyrics, through the same sources and cache as a playing song's, on a thread."""
        key = it.get("uri") or (it.get("name", "") + "|" + it.get("sub", ""))
        if key in self.words and self.words[key] is not None:
            return
        self.words[key] = None
        meta = {"title": it.get("name", ""), "artist": it.get("sub", ""), "album": it.get("album", ""),
                "length": (it.get("ms") or 0) / 1000.0}
        tid = tid_of(it.get("uri", ""))
        v = self.v
        split, threshold = v.lyric_split()

        def work():
            got = {"lines": [], "source": ""}
            try:
                t = tid or SS.spotify_id(meta["title"], meta["artist"], meta["album"], it.get("ms") or 0) \
                    or LP._key(meta["title"], meta["artist"])
                got["tid"] = t
                # Playback's own pick and shaping: the bare walk skipped Spicy, your own
                # files and the unlumping, so lines read differently from the song playing.
                ans = v.fetcher.preview_body(t, meta)
                if ans:
                    doc, name = ans
                    got.update(lines=TL(doc, split, threshold), source=name, doc=doc)
            except Exception as e:                          # noqa: BLE001
                got["error"] = str(e)[:120]
            self.words_ready.emit(key, got)
        threading.Thread(target=work, daemon=True, name="lyrics-preview").start()

    def time_in_editor(self, it: dict) -> None:
        """The TTML Editor on this song: its lyrics as a file (never a Spicy Lyrics sync: Apple's
        instead, or none), its audio from this computer, the very stream Mild Lyrics is playing
        (saved beside the lyrics), Spotify, or fetched by the editor."""
        v = self.v
        cur = self.is_current(it)
        key = it.get("uri") or (it.get("name", "") + "|" + it.get("sub", ""))
        got = self.words.get(key) or {}
        body = v.body if cur else got.get("doc")
        tid = (v.clock.tid or "") if cur else got.get("tid", "") or tid_of(it.get("uri", ""))
        title, artist = it.get("name", ""), (it.get("sub") or "").split(",")[0].strip()
        meta = {"title": title, "artist": it.get("sub", ""), "album": it.get("album", ""),
                "length": (it.get("ms") or 0) / 1000.0}
        audio = it.get("path", "") if it.get("kind") == "local" else ""
        pc = self.player.current if self.player.active else None
        if cur and not audio and pc and pc.get("path"):
            audio = pc["path"]
        stream = self.player.loaded_url() if cur and not audio and pc else ""
        spotify = cur and not audio and not self.player.active and self.online
        self.say(f"Opening “{title}” in the TTML Editor…")

        def work():
            out = {"editor": True, "title": title, "artist": artist, "audio": audio,
                   "spotify": spotify, "path": "", "note": ""}
            doc = body
            try:
                if doc is not None and LS_spicy_made(doc):
                    doc = LS_apple_instead(tid, meta)
                    out["note"] = ("Apple Music's sync, in place of Spicy Lyrics'" if doc
                                   else "no lyrics: Spicy Lyrics syncs are not handed to the editor")
                if doc:
                    where = v.cache_dir() / "editor"
                    where.mkdir(parents=True, exist_ok=True)
                    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", f"{artist} - {title}".strip(" -"))[:120]
                    path = where / f"{name or 'lyrics'}.ttml"
                    path.write_text(TTML_of(doc) + "\n", encoding="utf-8")
                    out["path"] = str(path)
            except Exception as e:                          # noqa: BLE001
                out["note"] = f"could not write its lyrics: {str(e)[:80]}"
            if stream:
                try:
                    out["audio"] = SS.save_stream(stream, v.cache_dir() / "editor", f"{artist} - {title}")
                except Exception as e:                      # noqa: BLE001
                    out["note"] = (out["note"] + " · " if out["note"] else "") + \
                        f"the editor finds its own copy (Mild Lyrics' could not be saved: {str(e)[:60]})"
            self.words_ready.emit("editor|" + key, out)
        threading.Thread(target=work, daemon=True, name="to-editor").start()

    def launch_editor(self, out: dict) -> None:
        import subprocess
        import sys
        exe = pathlib.Path(__file__).resolve().parent.parent / "ttml-editor.pyw"
        cmd = [sys.executable, str(exe)]
        if out.get("path"):
            cmd.append(noconsole.real_path(out["path"]))
        cmd += ["--title", out["title"], "--artist", out["artist"]]
        if out.get("audio"):
            cmd += ["--source", "local", "--audio", noconsole.real_path(out["audio"])]
        elif out.get("spotify"):
            cmd += ["--source", "spotify"]
        else:
            cmd += ["--source", "local", "--fetch"]
        try:
            subprocess.Popen(cmd, start_new_session=True, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:                              # noqa: BLE001
            self.say(f"Could not start the TTML Editor: {str(e)[:80]}")
            return
        self.say("TTML Editor opening" + (f" · {out['note']}" if out.get("note") else ""))

    # ============================================================== layout
    def S(self, x: float) -> float:
        return x * self.u

    def font(self, px: float, weight=W_.DemiBold) -> QFont:
        key = (round(px * self.u, 1), int(weight.value if hasattr(weight, "value") else weight),
               self.v.ui_family, self.v.ui_weight)    # the Font setting, changed while the app runs
        f = self._fonts.get(key)
        if f is None:
            f = self.v.ui_font(px * self.u, weight)
            f.setPixelSize(max(8, int(round(px * self.u))))
            if len(self._fonts) > 200:
                self._fonts.clear()
                self._fms.clear()
            self._fonts[key] = f
        return f

    def fm(self, px: float, weight=W_.DemiBold) -> QFontMetricsF:
        f = self.font(px, weight)
        key = id(f)
        got = self._fms.get(key)
        if got is None or got[0] is not f:
            got = (f, QFontMetricsF(f))
            self._fms[key] = got
        return got[1]

    def lay(self, W: int, H: int) -> dict:
        self.u = max(0.82, min(1.45, min(W / 1440.0, H / 900.0) * 1.05))
        dw = W / self.u
        self.bp = "L" if dw >= 1200 else "M" if dw >= 900 else "S" if dw >= 600 else "XS"
        rail = self.bp in ("S", "XS")
        side = self.S({"L": 260, "M": 220, "S": 64, "XS": 56}[self.bp])
        np = self.v.home_np
        top = self.S(72 if H / self.u >= 520 else 56) if np == "toolbar" else 0.0
        bar = self.S(84 if H / self.u >= 520 else 64) if np in ("card", "bar") else 0.0
        pad = {"L": (28, 36), "M": (24, 28), "S": (20, 20), "XS": (14, 14)}[self.bp]
        self.content = QRectF(side, top, W - side, H - top - bar)
        return {"W": W, "H": H, "side": side, "top": top, "bar": bar, "rail": rail,
                "px": self.S(pad[1]), "py": self.S(pad[0])}

    def cols(self, w: float, want: dict) -> int:
        return want[self.bp]

    # =========================================================== painting
    def hit(self, kind: str, payload, r: QRectF) -> QRectF:
        self.hits.append((kind, payload, QRectF(r)))
        return r

    def hot(self, kind: str, payload=None) -> bool:
        h = self.hover
        if not h or h[0] != kind:
            return False
        return payload is None or h[1] is payload or hit_key(h) == hit_key((kind, payload))

    def text(self, p: QPainter, r: QRectF, s: str, px: float, weight=W_.DemiBold,
             colour: QColor = INK, align=Qt.AlignmentFlag.AlignLeft, elide: bool = True,
             valign=Qt.AlignmentFlag.AlignVCenter) -> float:
        f = self.font(px, weight)
        p.setFont(f)
        p.setPen(colour)
        fm = self.fm(px, weight)
        s = s or ""
        if elide:
            s = fm.elidedText(s, Qt.TextElideMode.ElideRight, max(0.0, r.width()))
        p.drawText(r, int(align | valign), s)
        return fm.horizontalAdvance(s)

    def wrap(self, p: QPainter, x: float, y: float, w: float, s: str, px: float,
             weight=W_.Medium, colour: QColor = INK, rows: int = 3, lh: float = 1.35,
             align=Qt.AlignmentFlag.AlignLeft) -> float:
        """Word-wrapped text from (x, y); returns the height used."""
        fm = self.fm(px, weight)
        words, lines, cur = (s or "").split(), [], ""
        for wd in words:
            t = (cur + " " + wd).strip()
            if fm.horizontalAdvance(t) <= w or not cur:
                cur = t
            else:
                lines.append(cur)
                cur = wd
        if cur:
            lines.append(cur)
        if len(lines) > rows:
            lines = lines[:rows]
            lines[-1] = fm.elidedText(lines[-1] + " …", Qt.TextElideMode.ElideRight, w)
        h = fm.height() * lh
        for i, ln in enumerate(lines):
            self.text(p, QRectF(x, y + i * h, w, h), ln, px, weight, colour, align)
        return h * len(lines)

    @staticmethod
    def a(alpha: float, c: QColor = INK) -> QColor:
        out = QColor(c)
        out.setAlphaF(max(0.0, min(1.0, alpha)))
        return out

    def rr(self, p: QPainter, r: QRectF, rad: float, fill: QColor | None,
           line: QColor | None = None) -> None:
        p.setPen(QPen(line, 1) if line is not None else Qt.PenStyle.NoPen)
        p.setBrush(fill if fill is not None else Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, rad, rad)
        p.setBrush(Qt.BrushStyle.NoBrush)

    def icon(self, p: QPainter, name: str, r: QRectF, colour: QColor = INK) -> None:
        IC.draw(p, name, r, colour)

    def accent(self) -> tuple[QColor, QColor]:
        """(button fill, light tint) from the cover, or the design's red."""
        pal = getattr(self.v, "palette", None)
        if pal:
            c = pal[0]
            return shade(c, 0.42, 0.45), shade(c, 0.83, 0.55)
        return QColor(RED), QColor(PINK)

    def placeholder(self, name: str) -> QColor:
        h = int(hashlib.sha1((name or "?").encode()).hexdigest()[:6], 16)
        return QColor.fromHsl(h % 360, 70, 70)

    def cover(self, p: QPainter, r: QRectF, url: str, rad: float, name: str = "",
              round_: bool = False, label: bool = True) -> None:
        pm = self.v.thumb(url, max(r.width(), r.height()) * self.v.devicePixelRatioF()) if url else None
        path = QPainterPath()
        if round_:
            path.addEllipse(r)
        else:
            path.addRoundedRect(r, rad, rad)
        p.save()
        p.setClipPath(path, Qt.ClipOperation.IntersectClip)
        if pm is not None and not pm.isNull():
            sw, sh = pm.width(), pm.height()
            k = min(sw / max(1.0, r.width()), sh / max(1.0, r.height()))
            src = QRectF((sw - r.width() * k) / 2, (sh - r.height() * k) / 2,
                         r.width() * k, r.height() * k)
            p.drawPixmap(r, pm, src)
        else:
            c = self.placeholder(name)
            p.fillRect(r, c)
            if label and name and r.width() > self.S(40):
                ink = QColor(42, 18, 20) if c.lightnessF() > 0.55 else INK
                px = max(10.0, min(30.0, r.width() / self.u * 0.13))
                pad = r.width() * 0.07
                self.wrap(p, r.x() + pad, r.bottom() - pad - self.fm(px, W_.Black).height() * 2.1,
                          r.width() - 2 * pad, name, px, W_.Black, ink, rows=2, lh=1.05)
        p.restore()

    def badge(self, p: QPainter, x: float, cy: float, s: str, right: bool = False) -> float:
        fm = self.fm(12.5, W_.DemiBold)
        w = fm.horizontalAdvance(s) + self.S(16)
        h = self.S(22)
        r = QRectF(x - w if right else x, cy - h / 2, w, h)
        self.rr(p, r, self.S(6), self.a(0.10))
        self.text(p, r, s, 12.5, W_.DemiBold, self.a(0.75), Qt.AlignmentFlag.AlignHCenter)
        return w

    def button(self, p: QPainter, x: float, y: float, label: str, kind: str, payload=None,
               icon: str = "", style: str = "soft", h: float = 40, px: float = 16,
               right: bool = False) -> QRectF:
        """A button the design's way: flush-left label, icon first."""
        fm = self.fm(px, W_.Bold)
        ih = self.S(18) if icon else 0.0
        gap = self.S(8) if icon and label else 0.0
        w = self.S(32 if label else 16) + ih + gap + (fm.horizontalAdvance(label) if label else 0.0)
        if not label:
            w = self.S(h)
        r = QRectF(x - w if right else x, y, w, self.S(h))
        hot = self.hot(kind, payload)
        acc, _light = self.accent()
        if style == "primary":
            fill, ink = (QColor(255, 255, 255) if hot else INK), DARK
        elif style == "accent":
            fill, ink = (shade(acc, 0.5) if hot else acc), QColor(255, 255, 255)
        elif style == "ghost":
            fill, ink = (self.a(0.09) if hot else None), INK
        else:
            fill, ink = self.a(0.16 if hot else 0.10), INK
        self.rr(p, r, self.S(9) if label else r.height() / 2, fill)
        cx = r.x() + (self.S(16) if label else (r.width() - ih) / 2)
        if icon:
            self.icon(p, icon, QRectF(cx, r.center().y() - ih / 2, ih, ih), ink)
            cx += ih + gap
        if label:
            self.text(p, QRectF(cx, r.y(), r.right() - cx, r.height()), label, px, W_.Bold, ink,
                      elide=False)
        return self.hit(kind, payload, r)

    def seg(self, p: QPainter, x: float, y: float, opts: list[tuple[str, str]], cur: str,
            kind: str, right: bool = False, px: float = 15, h: float = 36) -> QRectF:
        fm = self.fm(px, W_.DemiBold)
        ws = [fm.horizontalAdvance(lbl) + self.S(28) for _k, lbl in opts]
        total = sum(ws) + self.S(8)
        x0 = x - total if right else x
        box = QRectF(x0, y, total, self.S(h))
        self.rr(p, box, self.S(10), self.a(0.08))
        cx = x0 + self.S(4)
        for (k, lbl), w in zip(opts, ws):
            r = QRectF(cx, y + self.S(4), w, self.S(h - 8))
            on = k == cur
            if on:
                self.rr(p, r, self.S(7), INK)
            elif self.hot(kind, k):
                self.rr(p, r, self.S(7), self.a(0.08))
            self.text(p, r, lbl, px, W_.DemiBold, DARK if on else self.a(0.75),
                      Qt.AlignmentFlag.AlignHCenter, elide=False)
            self.hit(kind, k, r)
            cx += w
        return box

    def switch(self, p: QPainter, r: QRectF, on: bool) -> None:
        self.rr(p, r, r.height() / 2, INK if on else self.a(0.18))
        d = r.height() - self.S(4)
        x = r.right() - d - self.S(2) if on else r.x() + self.S(2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(22, 22, 27) if on else self.a(0.75))
        p.drawEllipse(QRectF(x, r.y() + self.S(2), d, d))
        p.setBrush(Qt.BrushStyle.NoBrush)

    def heart(self, p: QPainter, r: QRectF, item: dict) -> None:
        if not self.likeable(item):
            return
        on = self.is_liked(item)
        hot = self.hot("heart", item)
        self.icon(p, "heartF" if on else "heart", r,
                  self.accent()[1] if on else self.a(0.85 if hot else 0.45))
        self.hit("heart", item, r.adjusted(-4, -4, 4, 4))

    # -------------------------------------------------------------- frame
    def paint(self, p: QPainter, W: int, H: int) -> None:
        L = self.lay(W, H)
        self.hits = []
        self.drops = []
        self.paint_ground(p, W, H)
        c = self.content
        p.save()
        p.setClipRect(c)
        y0 = c.y() + L["py"] - self.v.browse_scroll
        h = self.paint_page(p, c.x() + L["px"], y0, c.width() - 2 * L["px"], L)
        p.restore()
        # clicked where it shows: a tile scrolled under the toolbar's empty space is not hit through it
        self.hits = [(k, pl, r.intersected(c)) for k, pl, r in self.hits if r.intersects(c)]
        self.drops = [(d, r.intersected(c)) for d, r in self.drops if r.intersects(c)]
        self.v.content_h_browse = max(0.0, h + L["py"] * 2 - c.height())
        self.paint_side(p, L)
        if L["top"]:
            self.paint_toolbar(p, L)
        if L["bar"]:
            self.paint_bar(p, L)
        if self.popover:
            self.paint_popover(p, L)
        if self.ctx:
            self.paint_ctx(p, L)
        if self.drag and self.drag.get("live"):
            self.paint_drag(p)
        self.paint_note(p, L)
        if self.ob_step is not None:
            self.paint_onboarding(p, L)

    def paint_ground(self, p: QPainter, W: int, H: int) -> None:
        """The base colour and, when on, a wash of the cover's colours."""
        pal = list(getattr(self.v, "palette", None) or [])
        key = (W, H, bool(self.v.home_wash), tuple(c.rgb() for c in pal[:4]))
        if key != self._wash_key or self._wash_pm is None:
            pm = QPixmap(max(1, W), max(1, H))
            pm.fill(BASE)
            if self.v.home_wash and pal:
                q = QPainter(pm)
                spots = ((0.18, 0.28, 0.55), (0.78, 0.72, 0.60), (0.62, 0.14, 0.45), (0.30, 0.88, 0.55))
                for i, (fx, fy, fr) in enumerate(spots):
                    c = shade(pal[i % len(pal)], 0.36 if i % 2 == 0 else 0.26, 0.4)
                    g = QRadialGradient(QPointF(W * fx, H * fy), max(W, H) * fr)
                    g.setColorAt(0.0, c)
                    g.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), 0))
                    q.fillRect(pm.rect(), g)
                q.fillRect(pm.rect(), QColor(8, 8, 11, 158))
                q.end()
            self._wash_pm, self._wash_key = pm, key
        p.drawPixmap(0, 0, self._wash_pm)

    def paint_side(self, p: QPainter, L: dict) -> None:
        S, rail = self.S, L["rail"]
        H = L["H"] - L["bar"]
        r = QRectF(0, 0, L["side"], H)
        p.fillRect(r, QColor(16, 16, 21, 204))
        p.fillRect(QRectF(r.right() - 1, 0, 1, r.height()), self.a(0.10))
        x0, w = S(8 if rail else 10), r.width() - S(16 if rail else 20)
        y = S(16)
        if rail:
            self.text(p, QRectF(0, y, r.width(), S(30)), "ML", 19, W_.Black, INK,
                      Qt.AlignmentFlag.AlignHCenter)
        else:
            self.text(p, QRectF(x0 + S(14), y, w, S(30)), "Mild Lyrics", 19, W_.Black)
        y += S(44)
        sb = QRectF(x0, y, w, S(36))
        on = self.page == "search"
        self.rr(p, sb, S(9), self.a(0.16 if on or self.hot("nav", "search") else 0.08))
        self.icon(p, "search", QRectF(sb.x() + (sb.width() - S(18)) / 2 if rail else sb.x() + S(10),
                                      sb.center().y() - S(9), S(18), S(18)), self.a(0.55))
        if not rail:
            self.text(p, QRectF(sb.x() + S(36), sb.y(), sb.width(), sb.height()), "Search", 15,
                      W_.Medium, self.a(0.55))
            k = QRectF(sb.right() - S(28), sb.center().y() - S(10), S(20), S(20))
            self.rr(p, k, S(6), self.a(0.10))
            self.text(p, k, "/", 12.5, W_.DemiBold, self.a(0.55), Qt.AlignmentFlag.AlignHCenter)
        self.hit("nav", "search", sb)
        y += S(44)
        dragging = bool(self.drag and self.drag.get("live"))

        def nav(key, label, ic, yy, drop=None):
            rr = QRectF(x0, yy, w, S(40))
            cur = self.page == key or (key == "playlists" and self.page == "playlist"
                                       and False)
            if cur or self.hot("nav", key):
                self.rr(p, rr, S(9), self.a(0.13 if cur else 0.07))
            if dragging and drop:
                p.setPen(QPen(self.accent()[1], 2, Qt.PenStyle.DashLine))
                p.drawRoundedRect(rr.adjusted(1, 1, -1, -1), S(9), S(9))
            col = QColor(255, 255, 255) if cur else self.a(0.62)
            ix = rr.x() + (rr.width() - S(18)) / 2 if rail else rr.x() + S(14)
            self.icon(p, ic, QRectF(ix, rr.center().y() - S(9), S(18), S(18)), col)
            if not rail:
                self.text(p, QRectF(rr.x() + S(44), rr.y(), rr.width() - S(50), rr.height()),
                          label, 16, W_.DemiBold, col)
            self.hit("nav", key, rr)
            if drop:
                self.drops.append((drop, QRectF(rr)))
            return yy + S(42)

        for key, label, ic in TOP_NAV:
            y = nav(key, label, ic, y, drop={"to": "queue"} if key == "queue" else None)
        if rail:
            p.fillRect(QRectF(x0 + S(6), y + S(6), w - S(12), 1), self.a(0.10))
            y += S(14)
        else:
            self.text(p, QRectF(x0 + S(14), y + S(10), w, S(24)), "LIBRARY", 13, W_.Bold, self.a(0.55))
            y += S(38)
        foot = S(96) + (S(44) if self.v.listen.role and self.v.listen_badge else 0)
        for key, label, ic in LIB_NAV:
            if y + S(42) > H - foot:
                break
            y = nav(key, label, ic, y)
        if not rail and y + S(82) < H - foot:
            self.text(p, QRectF(x0 + S(14), y + S(10), w, S(24)), "PLAYLISTS", 13, W_.Bold, self.a(0.55))
            y += S(38)
            lists = [{"uri": "liked", "name": "Liked songs", "kind": "playlist", "can_add": True}]
            lists += self.all_playlists()
            for pl in lists:
                if y + S(42) > H - foot:
                    break
                rr = QRectF(x0, y, w, S(42))
                cur = (self.page == "liked" and pl["uri"] == "liked") or (
                    self.page == "playlist" and (self.arg or {}).get("uri") == pl["uri"])
                if cur or self.hot("side_pl", pl):
                    self.rr(p, rr, S(9), self.a(0.13 if cur else 0.07))
                if dragging and (pl.get("can_add") or pl.get("mine")) and (
                        pl["uri"].startswith(("mild:", "liked")) or self.online):
                    p.setPen(QPen(self.accent()[1], 2, Qt.PenStyle.DashLine))
                    p.drawRoundedRect(rr.adjusted(1, 1, -1, -1), S(9), S(9))
                art = QRectF(rr.x() + S(14), rr.y() + S(6), S(30), S(30))
                if pl["uri"] == "liked":
                    g = QLinearGradient(art.topLeft(), art.bottomRight())
                    g.setColorAt(0, QColor(106, 74, 176))
                    g.setColorAt(1, QColor(150, 170, 220))
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(g)
                    p.drawRoundedRect(art, S(5), S(5))
                    self.icon(p, "heartF", art.adjusted(S(8), S(8), -S(8), -S(8)), INK)
                else:
                    self.cover(p, art, pl.get("art", ""), S(5), pl.get("name", ""), label=False)
                self.text(p, QRectF(art.right() + S(10), rr.y(), rr.right() - art.right() - S(14),
                                    rr.height()), pl.get("name", ""), 15, W_.DemiBold, self.a(0.80))
                self.hit("side_pl", pl, rr)
                if pl.get("can_add") or pl.get("mine"):
                    self.drops.append(({"to": "playlist", "pl": pl}, QRectF(rr)))
                y += S(44)
        ln = self.v.listen
        if ln.role and self.v.listen_badge:
            # Listen along, sharing or listening: its line, and its menu on click (Show on screen).
            up = ln.link is not None and ln.link.up
            text = (("Locked · " if ln.locked else "") + (f"{ln.heard} listening along" if ln.heard
                    else "Sharing · nobody yet")) if ln.role == "host" else (
                "Listening along" if up and not ln._host_gone_at else "Listening along · waiting")
            lr = QRectF(x0, H - S(96) - S(40), w, S(36))
            if self.hot("listen"):
                self.rr(p, lr, S(9), self.a(0.07))
            live = up and (ln.role == "hear" or ln.heard)
            dx = lr.x() + (lr.width() - S(8)) / 2 if rail else lr.x() + S(19)    # on Settings' icon
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(30, 215, 96) if live else self.a(0.35))
            p.drawEllipse(QRectF(dx, lr.center().y() - S(4), S(8), S(8)))
            if not rail:
                self.text(p, QRectF(lr.x() + S(44), lr.y(), lr.width() - S(54), lr.height()), text, 13.5,
                          W_.DemiBold, self.a(0.75))
            self.hit("listen", None, lr)
        fy = H - S(96) + S(6)
        p.fillRect(QRectF(x0, fy, w, 1), self.a(0.08))
        rr = QRectF(x0, fy + S(10), w, S(40))
        if self.hot("settings"):
            self.rr(p, rr, S(9), self.a(0.07))
        ix = rr.x() + (rr.width() - S(18)) / 2 if rail else rr.x() + S(14)
        self.icon(p, "settings", QRectF(ix, rr.center().y() - S(9), S(18), S(18)), self.a(0.62))
        if not rail:
            self.text(p, QRectF(rr.x() + S(44), rr.y(), rr.width(), rr.height()), "Settings", 16,
                      W_.DemiBold, self.a(0.62))
            self.text(p, QRectF(rr.x(), rr.y(), rr.width() - S(12), rr.height()),
                      self.v.key_name("menu"), 12.5, W_.DemiBold, self.a(0.45), Qt.AlignmentFlag.AlignRight)
        self.hit("settings", None, rr)
        fr = QRectF(x0, rr.bottom() + S(2), w, S(36))
        if self.popover or self.hot("follow"):
            self.rr(p, fr, S(9), self.a(0.13 if self.popover else 0.07))
        dot_on = self.v.clock.status == "Playing"
        dx = fr.x() + (fr.width() - S(8)) / 2 if rail else fr.x() + S(19)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(126, 211, 154) if dot_on else self.a(0.35))
        p.drawEllipse(QRectF(dx, fr.center().y() - S(4), S(8), S(8)))
        if not rail:
            self.text(p, QRectF(fr.x() + S(44), fr.y(), fr.width() - S(74), fr.height()),
                      self.follow_label(), 13.5, W_.DemiBold, self.a(0.75))
            self.icon(p, "pin" if self.pinned() else "up",
                      QRectF(fr.right() - S(28), fr.center().y() - S(7.5), S(15), S(15)), self.a(0.75))
        self.hit("follow", None, fr)

    def np_item(self) -> dict:
        v = self.v
        meta = v.clock.meta or {}
        tid = v.clock.tid or ""
        uri = f"spotify:track:{tid}" if tid and len(tid) == 22 and not LP_hex(tid) else ""
        names = [n for n in meta.get("artists") or [] if n]
        try:
            cr = list(v.credits() or [])
        except Exception:                                   # noqa: BLE001
            cr = []
        if not names:
            cn = [a.get("name", "") for a in cr]
            names = cn if cn and ", ".join(cn) == meta.get("artist", "") else PLG.artists_of(meta.get("artist", ""))
        uris = {SS.norm(a.get("name", "")): a.get("uri", "") for a in cr}
        return {"kind": "track", "uri": uri, "name": meta.get("title", ""),
                "sub": meta.get("artist", ""), "album": meta.get("album", ""),
                "art": meta.get("art", ""), "ms": float(meta.get("length", 0) or 0) * 1000, "tid": tid,
                "artists": [{"name": n, "uri": uris.get(SS.norm(n), "")} for n in names]}

    def artist_links(self, p: QPainter, r: QRectF, it: dict, px: float, center: bool) -> None:
        """A song's artists, "A, B & C", each a link to its page."""
        arts = [a for a in it.get("artists") or [] if a.get("name")]
        fm = self.fm(px, W_.Medium)
        parts = []
        for i, a in enumerate(arts):
            if i:
                parts.append((" & " if i == len(arts) - 1 else ", ", None))
            parts.append((a["name"], a))
        if not parts:
            self.text(p, r, it.get("sub", ""), px, W_.Medium, self.a(0.62),
                      Qt.AlignmentFlag.AlignHCenter if center else Qt.AlignmentFlag.AlignLeft)
            return
        total = sum(fm.horizontalAdvance(t) for t, _a in parts)
        x = r.x() + max(0.0, (r.width() - total) / 2) if center else r.x()
        for t, a in parts:
            w = min(fm.horizontalAdvance(t), r.right() - x)
            if w <= 0:
                break
            rr = QRectF(x, r.y(), w, r.height())
            hot = a is not None and self.hot("np_artist", dict(a, kind="artist"))
            self.text(p, rr, t, px, W_.Medium, INK if hot else self.a(0.62))
            if a is not None:
                ink = QRectF(x, rr.center().y() - fm.height() / 2, w, fm.height())   # the name, not the title above
                if hot:
                    p.fillRect(QRectF(x, ink.bottom() - self.S(1), w, 1), self.a(0.6))
                self.hit("np_artist", dict(a, kind="artist"), ink)
            x += w

    def progress(self) -> float:
        ln = float((self.v.clock.meta or {}).get("length", 0) or 0)
        return max(0.0, min(1.0, self.v.song_position() / ln)) if ln > 0 else 0.0

    def paint_toolbar(self, p: QPainter, L: dict) -> None:
        S = self.S
        r = QRectF(L["side"], 0, L["W"] - L["side"], L["top"])
        p.fillRect(r, QColor(16, 16, 21, 140))
        p.fillRect(QRectF(r.x(), r.bottom() - 1, r.width(), 1), self.a(0.08))
        pad = S(24) if self.bp in ("L", "M") else S(12)
        cy = r.center().y()
        x = r.x() + pad
        playing = self.v.song_playing()
        if not L["rail"]:
            self.button(p, x, cy - S(20), "", "t_prev", icon="prev", style="ghost", h=40)
            x += S(44)
        self.button(p, x, cy - S(22), "", "t_play", icon="pause" if playing else "play",
                    style="ghost", h=44)
        x += S(48)
        if not L["rail"]:
            self.button(p, x, cy - S(20), "", "t_next", icon="next", style="ghost", h=40)
            x += S(44)
        right = r.right() - pad
        acc, _ = self.accent()
        lb = self.button(p, right, cy - S(20), "Lyrics" if self.bp != "XS" else "", "lyrics",
                         icon="mic", style="accent", right=True)
        right = lb.x() - S(8)
        if not L["rail"]:
            for k, ic in (("t_queue", "queue"), ("t_mini", "mini")):
                b = self.button(p, right, cy - S(20), "", k, icon=ic, style="ghost", right=True)
                right = b.x() - S(4)
            if self.player.active and self.bp == "L":
                right = self.paint_local_ctl(p, right, cy) - S(8)
        lcd_w = min(S(560), right - x - S(24))
        lh = S(52 if L["top"] > S(60) else 42)
        lcd = QRectF(x + (right - x - lcd_w) / 2, cy - lh / 2, lcd_w, lh)
        self.paint_lcd(p, lcd)

    def paint_lcd(self, p: QPainter, r: QRectF) -> None:
        S = self.S
        it = self.np_item()
        hot = self.hot("lcd")
        path = QPainterPath()
        path.addRoundedRect(r, S(10), S(10))
        p.save()
        p.setClipPath(path)
        p.fillRect(r, self.a(0.12 if hot else 0.08))
        art = QRectF(r.x(), r.y(), r.height(), r.height())
        if self.v.art_full is not None and not self.player.active:
            p.drawPixmap(art, self.v.art_full, QRectF(self.v.art_full.rect()))
        else:
            self.cover(p, art, it["art"], 0, it["name"], label=False)
        tx = art.right() + S(12)
        heart = bool(it["uri"])
        tw = r.right() - tx - S(12) - (S(40) if heart else 0)
        name = it["name"] or ("Nothing playing" if not self.v.clock.tid else "…")
        self.text(p, QRectF(tx, r.y() + r.height() * 0.12, tw, r.height() * 0.42), name, 14.5,
                  W_.Bold, INK, Qt.AlignmentFlag.AlignHCenter)
        sub_r = QRectF(tx, r.y() + r.height() * 0.48, tw, r.height() * 0.36)
        bar = QRectF(art.right(), r.bottom() - S(3), r.right() - art.right() - (S(40) if heart else 0), S(3))
        p.fillRect(bar, self.a(0.10))
        p.fillRect(QRectF(bar.x(), bar.y(), bar.width() * self.progress(), bar.height()), INK)
        p.restore()
        p.setPen(QPen(self.a(0.10), 1))
        p.drawRoundedRect(r, S(10), S(10))
        self.hit("lcd", None, r)
        self.hit("seek", bar, bar.adjusted(0, -S(2), 0, 0))     # the bar and 2px: the card above opens the song
        self.artist_links(p, sub_r, it, 12.5, True)
        if heart:
            self.heart(p, QRectF(r.right() - S(30), r.center().y() - S(8), S(16), S(16)), it)

    def paint_local_ctl(self, p: QPainter, right: float, cy: float) -> float:
        S = self.S
        _acc, light = self.accent()
        vol = QRectF(right - S(64), cy - S(2), S(64), S(4))
        self.rr(p, vol, S(2), self.a(0.18))
        self.rr(p, QRectF(vol.x(), vol.y(), vol.width() * self.player.volume, vol.height()), S(2), INK)
        self.hit("vol", None, vol.adjusted(0, -S(8), 0, S(8)))
        self.icon(p, "vol", QRectF(vol.x() - S(26), cy - S(9), S(18), S(18)), self.a(0.7))
        x = vol.x() - S(32)
        rep = self.player.repeat
        b = self.button(p, x, cy - S(18), "", "t_repeat", icon="repeat1" if rep == "one" else "repeat",
                        style="ghost", h=36, right=True)
        IC.draw(p, "repeat1" if rep == "one" else "repeat", b.adjusted(S(9), S(9), -S(9), -S(9)),
                light if rep != "off" else self.a(0.7))
        b2 = self.button(p, b.x() - S(2), cy - S(18), "", "t_shuffle", icon="shuffle", style="ghost",
                         h=36, right=True)
        if self.player.shuffle:
            IC.draw(p, "shuffle", b2.adjusted(S(9), S(9), -S(9), -S(9)), light)
        return b2.x()

    def paint_bar(self, p: QPainter, L: dict) -> None:
        """The bottom bar, for the card and bar layouts."""
        S = self.S
        r = QRectF(0, L["H"] - L["bar"], L["W"], L["bar"])
        p.fillRect(r, QColor(16, 16, 21, 235))
        p.fillRect(QRectF(0, r.y(), r.width(), 1), self.a(0.08))
        it = self.np_item()
        pad = S(20)
        art = QRectF(pad, r.y() + (r.height() - S(52)) / 2, S(52), S(52))
        if self.v.art_full is not None and not self.player.active:
            path = QPainterPath()
            path.addRoundedRect(art, S(6), S(6))
            p.save()
            p.setClipPath(path)
            p.drawPixmap(art, self.v.art_full, QRectF(self.v.art_full.rect()))
            p.restore()
        else:
            self.cover(p, art, it["art"], S(6), it["name"], label=False)
        self.hit("lcd", None, art)
        tw = S(240) if self.bp in ("L", "M") else r.width() - S(260)
        self.text(p, QRectF(art.right() + S(12), art.y() + S(4), tw, S(24)), it["name"] or "Nothing playing",
                  16, W_.Bold)
        self.artist_links(p, QRectF(art.right() + S(12), art.y() + S(28), tw, S(20)), it, 13.5, False)
        cx = r.center().x()
        cy = r.y() + S(30)
        playing = self.v.song_playing()
        self.button(p, cx - S(64), cy - S(18), "", "t_prev", icon="prev", style="ghost", h=36)
        self.button(p, cx - S(20), cy - S(20), "", "t_play", icon="pause" if playing else "play",
                    style="primary", h=40)
        self.button(p, cx + S(28), cy - S(18), "", "t_next", icon="next", style="ghost", h=36)
        if self.bp in ("L", "M"):
            ln = float((self.v.clock.meta or {}).get("length", 0) or 0)
            pos = self.v.song_position()
            bw = S(480) if self.bp == "L" else S(300)
            bar = QRectF(cx - bw / 2, r.bottom() - S(18), bw, S(4))
            self.rr(p, bar, S(2), self.a(0.16))
            self.rr(p, QRectF(bar.x(), bar.y(), bar.width() * self.progress(), bar.height()), S(2), INK)
            self.text(p, QRectF(bar.x() - S(52), bar.y() - S(8), S(44), S(20)), fmt_ms(pos * 1000), 12.5,
                      W_.DemiBold, self.a(0.55), Qt.AlignmentFlag.AlignRight)
            self.text(p, QRectF(bar.right() + S(8), bar.y() - S(8), S(52), S(20)),
                      "-" + fmt_ms(max(0.0, ln - pos) * 1000) if ln else "", 12.5, W_.DemiBold, self.a(0.55))
            self.hit("seek", bar, bar.adjusted(0, -S(6), 0, S(6)))
        right = r.right() - pad
        b = self.button(p, right, cy - S(20), "Lyrics" if self.bp != "XS" else "", "lyrics", icon="mic",
                        style="accent", right=True)
        b = self.button(p, b.x() - S(8), cy - S(20), "", "t_queue", icon="queue", style="ghost", right=True)
        if self.bp == "L":
            self.button(p, b.x() - S(4), cy - S(20), "", "t_mini", icon="mini", style="ghost", right=True)

    # ------------------------------------------------------------ overlays
    def follow_label(self) -> str:
        if self.player.active:
            return "Pinned to Mild Lyrics" if self.pinned() == "mild" else "Playing here"
        if not self.online and not self.v.clock.tid:
            return "Mild Lyrics player"
        name = getattr(self.v.clock.io, "name", "") or "Spotify"
        app = name.split(":")[-1].strip() or "Spotify"
        app = app[:1].upper() + app[1:]
        ov = self.overlay()
        if ov is not None and ov.pinned and ov.pinned != "mild":
            return f"Pinned to {ov.pin_name or app}"
        return f"Following {app}"

    def overlay(self):
        io = self.v.clock.io
        return io if hasattr(io, "pin") else None

    def players(self) -> list[dict]:
        """Spotify, every other player the bus or media service names, and Mild Lyrics."""
        ov = self.overlay()
        io = getattr(self.v.clock.io, "inner", self.v.clock.io)
        sess = ov._session() if ov is not None else None
        home = getattr(sess, "HOME", "") if sess is not None else ""
        port = hasattr(io, "pin_side") or type(io).__name__ == "CdpTransport"
        cur_app = (getattr(self.v.clock.io, "app", "") or "").lower()
        out = []
        if port or home:
            sp_on = not self.player.active and cur_app in ("", "spotify")
            meta = self.v.clock.meta or {} if sp_on else {}
            out.append({"who": "spotify", "name": "Spotify", "sess": None,
                        "what": " — ".join(x for x in (meta.get("title"), meta.get("artist")) if x) or
                        ("the desktop app" if not sp_on else "nothing"),
                        "playing": sp_on and self.v.clock.status == "Playing", "on": sp_on})
        if sess is not None and (self.v.any_player or (ov and ov.pinned not in (None, "mild", "spotify"))):
            try:
                names = sess._sessions()
            except Exception:                               # noqa: BLE001
                names = []
            for who in names[:8]:
                if who == home:
                    continue
                try:
                    got = sess._read_one(False, who)
                except Exception:                           # noqa: BLE001
                    continue
                app = sess._app_of(who) or str(who)
                meta = got.get("meta") or {}
                what = " — ".join(x for x in (meta.get("title"), meta.get("artist")) if x)
                out.append({"who": who, "name": app[:1].upper() + app[1:], "what": what or "nothing",
                            "playing": got.get("status") == "Playing", "sess": sess,
                            "on": app.lower() == cur_app and not self.player.active})
        cur = self.player.current
        out.append({"who": "mild", "name": "Mild Lyrics", "sess": None,
                    "what": (f"{cur.get('title')} — {cur.get('artist')}" if cur else
                             f"Your own files · {len(self.lib.tracks)} songs"),
                    "playing": self.player.playing(), "on": self.player.active})
        return out

    def paint_popover(self, p: QPainter, L: dict) -> None:
        S = self.S
        rows = self._pop_rows = self.players()
        w = min(S(380), L["W"] - S(24))
        h = S(64) + len(rows) * S(56) + S(60)
        r = QRectF(S(10), L["H"] - S(58) - h, w, h)
        self.shadow(p, r)
        self.rr(p, r, S(12), QColor(24, 24, 29, 247), self.a(0.14))
        self.hit("pop_bg", None, r)
        self.text(p, QRectF(r.x() + S(16), r.y() + S(12), w, S(24)), "Follow", 16, W_.Black)
        auto = not self.pinned() and not self.player.active
        a = QRectF(r.right() - S(140), r.y() + S(10), S(126), S(28))
        self.rr(p, a, S(8), INK if auto else self.a(0.08))
        self.text(p, a, "Whoever plays", 13, W_.DemiBold, DARK if auto else self.a(0.8),
                  Qt.AlignmentFlag.AlignHCenter)
        self.hit("pop_auto", None, a)
        y = r.y() + S(48)
        for row in rows:
            rr = QRectF(r.x() + S(6), y, w - S(12), S(52))
            if row["on"] or self.hot("pop_pick", row["who"]):
                self.rr(p, rr, S(8), self.a(0.06 if row["on"] else 0.05))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(126, 211, 154) if row["playing"] else self.a(0.35))
            p.drawEllipse(QRectF(rr.x() + S(12), rr.y() + S(14), S(8), S(8)))
            self.text(p, QRectF(rr.x() + S(30), rr.y() + S(6), rr.width() - S(80), S(22)), row["name"],
                      15, W_.Bold)
            self.text(p, QRectF(rr.x() + S(30), rr.y() + S(27), rr.width() - S(80), S(20)),
                      row["what"] + (" · following" if row["on"] else ""), 12.5, W_.Medium, self.a(0.55))
            self.hit("pop_pick", row["who"], rr)
            if row["who"]:
                pin = QRectF(rr.right() - S(40), rr.center().y() - S(15), S(30), S(30))
                on = self.pinned() == str(row["who"])
                self.rr(p, pin, S(15), INK if on else self.a(0.08))
                self.icon(p, "pin", pin.adjusted(S(8), S(8), -S(8), -S(8)), DARK if on else self.a(0.6))
                self.hit("pop_pin", row["who"], pin)
            y += S(56)
        p.fillRect(QRectF(r.x() + S(12), y + S(4), w - S(24), 1), self.a(0.08))
        sw = QRectF(r.right() - S(56), y + S(18), S(42), S(24))
        self.text(p, QRectF(r.x() + S(16), y + S(10), w - S(90), S(22)), "Any media player", 14.5, W_.Bold)
        self.text(p, QRectF(r.x() + S(16), y + S(30), w - S(90), S(20)),
                  "Spotify, browsers and other players" if self.v.any_player else "Off: only Spotify is looked at",
                  12.5, W_.Medium, self.a(0.55))
        self.switch(p, sw, bool(self.v.any_player))
        self.hit("pop_any", None, QRectF(r.x(), y + S(6), w, S(50)))

    def shadow(self, p: QPainter, r: QRectF) -> None:
        for i, al in ((14, 0.10), (8, 0.14), (3, 0.18)):
            self.rr(p, r.adjusted(-self.S(i) / 2, -self.S(i) / 4, self.S(i) / 2, self.S(i)),
                    self.S(14 + i), QColor(0, 0, 0, int(al * 255)))

    def ctx_items(self) -> list[tuple]:
        """(label, icon, action) rows for the open menu; label "" is a rule."""
        it = self.ctx["item"]
        k = it.get("kind")
        out = []
        other = self.other_player(it)
        if k in ("track", "local"):
            out += [("Play next", "play", "next"), ("Add to queue", "queue", "queue")]
            if other:
                out.append(other)
            if self.likeable(it):
                on = self.is_liked(it)
                out += [("", "", ""), ("Remove from Liked songs" if on else "Like",
                                      "heartF" if on else "heart", "like"),
                        ("Add to playlist", "plus", "sub")]
                if self.ctx.get("sub"):
                    for pl in self.my_playlists(it):
                        out.append(("    " + pl.get("name", ""), "list", ("pl", pl)))
                    out.append(("    New playlist…", "plus", "newpl"))
            pi = it.get("_pi")
            if pi is not None and (self.arg or {}).get("uri", "").startswith("mild:playlist:"):
                out.append(("Remove from this playlist", "x", "pl_rm"))
            out.append(("", "", ""))
            if it.get("artists") and it["artists"][0].get("uri"):
                out.append(("Go to artist", "user", "artist"))
            if it.get("album_uri"):
                out.append(("Go to album", "disc", "album"))
            out += [("About this song", "music", "song"), ("Open lyrics", "mic", "lyrics"),
                    ("Make a queue from this song", "shuffle", "radio"),
                    ("Time in the editor", "pen", "editor")]
            if k == "track":
                out += [("", "", ""), ("Not interested" if it.get("why") else "Never suggest this song",
                                       "x", "hide")]
        elif k == "artist":
            out = [("Play", "play", "play")] + ([other] if other else []) + [
                   ("Mix from this artist", "shuffle", "mix"), ("Go to artist", "user", "open"),
                   ("Unfollow" if self.follows(it) else "Follow", "check" if self.follows(it) else "plus", "follow"),
                   ("", "", ""), ("Don’t suggest this artist", "x", "hide_artist")]
        else:
            out = [("Play", "play", "play")] + ([other] if other else []) + [("Open", "list", "open"),
                                                                            ("Add to queue", "queue", "queue")]
            if k == "album":
                if it.get("artist_uri") or (it.get("artists") or [{}])[0].get("uri") or it.get("sub"):
                    out.append(("Go to artist", "user", "album_artist"))
                out.append(("Remove from your albums" if self.follows(it) else "Save to your albums",
                            "check" if self.follows(it) else "plus", "follow"))
        return out

    def other_player(self, it: dict):
        """The menu row that plays this in the player it would not go to by default."""
        uri = it.get("uri") or ""
        if it.get("kind") == "local" or not uri:
            return None
        if self.play_in() == "spotify":
            return ("Play in Mild Lyrics", "music", "here")
        if self.online and uri.startswith("spotify:"):
            return ("Play in Spotify", "play", "spotify")
        return None

    def my_playlists(self, item: dict | None = None) -> list[dict]:
        """Playlists a song can be added to: Mild Lyrics' always, Spotify's own for its songs while it is there."""
        sp = self.online and (item is None or (item.get("uri") or "").startswith("spotify:track:"))
        return [x for x in self.all_playlists() if x["uri"].startswith("mild:")
                or (sp and (x.get("mine") or x.get("can_add")))]

    def paint_ctx(self, p: QPainter, L: dict) -> None:
        S = self.S
        rows = self.ctx_items()
        it = self.ctx["item"]
        fm = self.fm(14.5, W_.DemiBold)
        hint = {"sub": S(26), "queue": S(70)}       # room for "▸" / "or drag" on the right
        w = min(S(360), max([S(250)] + [S(4 + 34 + 14 + 4) + (S(20) if lbl.startswith("    ") else 0)
                                        + fm.horizontalAdvance(lbl.strip()) + hint.get(a, 0)
                                        for lbl, _i, a in rows if lbl and isinstance(a, str)]))
        h = S(62) + sum(S(9) if not lbl else S(35) for lbl, _i, _a in rows)
        x = max(S(8), min(self.ctx["x"], L["W"] - w - S(8)))
        y = max(S(8), min(self.ctx["y"], L["H"] - h - S(8)))
        r = QRectF(x, y, w, h)
        self.shadow(p, r)
        self.rr(p, r, S(10), QColor(24, 24, 29, 247), self.a(0.14))
        self.hit("ctx_bg", None, r)
        self.text(p, QRectF(x + S(14), y + S(10), w - S(28), S(22)), it.get("name", ""), 15, W_.Bold)
        sub = {"track": "Song", "local": "On this computer", "artist": "Artist", "album": "Album",
               "playlist": "Playlist"}.get(it.get("kind"), "")
        if it.get("sub") and it.get("kind") != "artist":
            sub += " · " + it["sub"]
        self.text(p, QRectF(x + S(14), y + S(30), w - S(28), S(20)), sub, 12.5, W_.Medium, self.a(0.55))
        yy = y + S(56)
        for lbl, ic, act in rows:
            if not lbl:
                p.fillRect(QRectF(x + S(10), yy + S(4), w - S(20), 1), self.a(0.10))
                yy += S(9)
                continue
            rr = QRectF(x + S(4), yy, w - S(8), S(33))
            if self.hot("ctx", act):
                self.rr(p, rr, S(7), self.a(0.09))
            ind = S(20) if lbl.startswith("    ") else 0
            self.icon(p, ic, QRectF(rr.x() + S(10) + ind, rr.center().y() - S(7.5), S(15), S(15)),
                      self.a(0.75 if act == "hide" else 0.92))
            right = hint.get(act, S(14)) if isinstance(act, str) else S(14)
            self.text(p, QRectF(rr.x() + S(34) + ind, rr.y(), rr.width() - S(34) - ind - right, rr.height()),
                      lbl.strip(),
                      14.5, W_.DemiBold, self.a(0.75 if act == "hide" else 0.95))
            if act == "sub":
                self.text(p, QRectF(rr.x(), rr.y(), rr.width() - S(10), rr.height()),
                          "▾" if self.ctx.get("sub") else "▸", 13, W_.DemiBold, self.a(0.55),
                          Qt.AlignmentFlag.AlignRight)
            elif act == "queue":
                self.text(p, QRectF(rr.x(), rr.y(), rr.width() - S(10), rr.height()), "or drag", 12,
                          W_.Medium, self.a(0.45), Qt.AlignmentFlag.AlignRight)
            self.hit("ctx", act, rr)
            yy += S(35)

    def ctx_do(self, act) -> None:
        it = self.ctx["item"]
        if act == "sub":
            self.ctx["sub"] = not self.ctx.get("sub")
            return
        self.ctx = None
        if isinstance(act, tuple) and act[0] == "pl":
            self.add_to_playlist(act[1], it)
        elif act == "newpl":
            self.new_playlist(it)
        elif act == "pl_rm":
            self.pl_remove(it)
        elif act == "follow":
            self.follow(it)
        elif act == "next":
            self.queue(it, True)
        elif act == "queue":
            self.queue(it)
        elif act == "like":
            self.like(it)
        elif act == "artist":
            a = it["artists"][0]
            self.go("artist", {"kind": "artist", "uri": a["uri"], "name": a.get("name", "")})
        elif act == "album":
            self.go("album", {"kind": "album", "uri": it["album_uri"], "name": it.get("album", "")})
        elif act == "song":
            self.go("song", dict(it))
        elif act == "lyrics":
            self.open_words(it)
        elif act == "here":
            self.play_here(it, it.get("_list"))
        elif act == "radio":
            self.song_radio(it)
        elif act == "editor":
            self.time_in_editor(it)
        elif act == "mix":
            self.artist_mix(it)
        elif act == "hide_artist":
            self.hide_artist(it)
        elif act == "album_artist":
            a = (it.get("artists") or [{}])[0]
            uri = it.get("artist_uri") or a.get("uri", "")
            name = a.get("name") or it.get("sub", "").split("·")[0].split(",")[0].strip()
            self.go("artist", {"kind": "artist", "uri": uri, "name": name})
        elif act == "spotify":
            if self.player.active:
                self.player.stand_down()
            if it.get("_ctx") and it.get("kind") == "track":
                self.v.fetcher.request_play_in(it["_ctx"], it["uri"])
            else:
                self.v.fetcher.request_play(it["uri"])
        elif act == "hide":
            self.hide(it)
        elif act == "play":
            self.play(it)
        elif act == "open":
            self.open_item(it)

    def paint_drag(self, p: QPainter) -> None:
        S = self.S
        pos = self.v.mouse_pos
        name = self.drag["item"].get("name", "")
        fm = self.fm(14, W_.Bold)
        r = QRectF(pos.x() + S(12), pos.y() + S(8), min(S(260), fm.horizontalAdvance(name) + S(54)), S(36))
        self.rr(p, r, S(8), QColor(40, 40, 46, 230), self.a(0.18))
        self.icon(p, "music", QRectF(r.x() + S(10), r.center().y() - S(8), S(16), S(16)), self.accent()[1])
        self.text(p, QRectF(r.x() + S(34), r.y(), r.width() - S(42), r.height()), name, 14, W_.Bold)

    def paint_note(self, p: QPainter, L: dict) -> None:
        """The toast with Undo, or the one-time note about the B key."""
        S = self.S
        now = time.monotonic()
        if self.note and self.note[2] > now:
            text, undo, _ = self.note
            fm = self.fm(15, W_.DemiBold)
            w = min(L["W"] - S(40), fm.horizontalAdvance(text) + S(56) + (S(80) if undo else 0))
            r = QRectF(self.content.center().x() - w / 2, L["H"] - L["bar"] - S(80), w, S(50))
            self.shadow(p, r)
            self.rr(p, r, S(10), QColor(40, 40, 46, 235), self.a(0.14))
            self.hit("note_bg", None, r)
            self.text(p, QRectF(r.x() + S(20), r.y(), r.width() - S(110 if undo else 40), r.height()), text,
                      15, W_.DemiBold)
            if undo:
                self.button(p, r.right() - S(10), r.y() + S(9), "Undo", "undo", style="primary", h=32,
                            px=14, right=True)
            return
        self.note = None
        if self.v.home_key_told or self.ob_step is not None or self.v.first_run:
            return
        key = self.v.key_name("browse")
        w = min(L["W"] - S(40), S(530))
        r = QRectF(self.content.center().x() - w / 2, L["H"] - L["bar"] - S(102), w, S(74))
        self.shadow(p, r)
        self.rr(p, r, S(12), QColor(24, 24, 29, 245), self.a(0.16))
        self.hit("note_bg", None, r)
        self.text(p, QRectF(r.x() + S(20), r.y() + S(12), w - S(220), S(24)),
                  f"Home now opens with {key}", 15.5, W_.Bold)
        self.text(p, QRectF(r.x() + S(20), r.y() + S(38), w - S(220), S(22)),
                  "The Home key still works until you pick one in Keys", 13, W_.Medium, self.a(0.62))
        b = self.button(p, r.right() - S(16), r.y() + S(19), "Got it", "key_ok", style="primary", h=36,
                        px=14.5, right=True)
        self.button(p, b.x() - S(8), r.y() + S(19), "Keep Home", "key_keep", h=36, px=14.5, right=True)

    # ---------------------------------------------------------- onboarding
    def ob_rows(self) -> tuple[str, str, list]:
        v = self.v
        ok = v.fetcher.cdp is not None
        steps = [
            ("Welcome to Mild Lyrics",
             "Word-by-word lyrics for whatever you play. With Spotify's debug port open, your library, "
             "charts and suggestions come in too. Everything else works without it.",
             [("Spotify", "Connected" if ok else "Library, charts and suggestions", None,
               "Connected" if ok else "How to connect", "ob_spotify", not ok)]),
            ("Where do you listen?", "Mild Lyrics follows these. You can change it any time from the bottom "
             "of the sidebar.",
             [("Spotify", "The desktop app", None, "", "", False),
              ("Mild Lyrics player", "Plays files from your own folders, no other player needed", None,
               "Choose folder", "ob_folder", False),
              ("Browsers and other players", "YouTube Music, SoundCloud, VLC and the rest, through the "
               "system's media controls", "any_player", "", "", False)]),
            ("How lyrics should look", "All of these are in Settings later too.",
             [("Your sources", "Which sources and syncs to use, in order: Spicy Lyrics · word-by-word, "
               "Unison · word-by-word, Spicy Lyrics · line-by-line…", None, "Choose…", "ob_sources", False),
              ("Romanise non-Latin lyrics", "Japanese, Korean, Chinese and Cyrillic get a Latin line under them",
               "roman", "", "", False),
              ("Key for the home page", f"{v.key_name('browse')}, easier to reach than Home"
               if v.key_name("browse") != "Home" else "Home, as in older versions", None,
               v.key_name("browse"), "ob_key", False)]),
            ("Building your lyric index", "Matching your history to saved and fetched lyrics. You can start "
             "listening while this runs.", []),
        ]
        return steps[self.ob_step]

    def paint_onboarding(self, p: QPainter, L: dict) -> None:
        S = self.S
        p.fillRect(QRectF(0, 0, L["W"], L["H"]), QColor(8, 8, 11, 184))
        self.hits = [h for h in self.hits if h[0] == "never"]
        title, note, rows = self.ob_rows()
        w = min(S(620), L["W"] - S(32))
        fmn = self.fm(15, W_.Medium)
        n_rows = max(1, int(fmn.horizontalAdvance(note) // max(1.0, w - S(56) - S(30))) + 1)
        h = (S(92) + min(3, n_rows) * fmn.height() * 1.35 + S(12) + len(rows) * S(68)
             + (S(70) if self.ob_step == 3 else 0) + S(84))
        r = QRectF((L["W"] - w) / 2, (L["H"] - h) / 2, w, h)
        self.shadow(p, r)
        self.rr(p, r, S(14), QColor(22, 22, 27, 252), self.a(0.14))
        self.hit("ob_bg", None, r)
        x, y = r.x() + S(28), r.y() + S(26)
        self.text(p, QRectF(x, y, w, S(20)), f"STEP {self.ob_step + 1} OF 4", 13, W_.Bold, self.a(0.62))
        self.text(p, QRectF(x, y + S(20), w - S(56), S(40)), title, 28, W_.Black)
        y += S(66)
        y += self.wrap(p, x, y, w - S(56), note, 15, W_.Medium, self.a(0.75), rows=3) + S(12)
        for label, sub, key, act, actk, primary in rows:
            rr = QRectF(r.x() + S(16), y, w - S(32), S(60))
            self.text(p, QRectF(rr.x() + S(12), rr.y() + S(8), rr.width() - S(180), S(24)), label, 16, W_.Bold)
            self.text(p, QRectF(rr.x() + S(12), rr.y() + S(32), rr.width() - S(180), S(20)), sub, 13.5,
                      W_.Medium, self.a(0.62))
            right = rr.right() - S(12)
            if key:
                on = bool(getattr(self.v, key)) if key != "roman" else self.v.roman != "off"
                sw = QRectF(right - S(42), rr.center().y() - S(12), S(42), S(24))
                self.switch(p, sw, on)
                self.hit("ob_toggle", key, rr)
                right = sw.x() - S(10)
            if act:
                self.button(p, right, rr.center().y() - S(17), act, actk, style="primary" if primary else "soft",
                            h=34, px=14, right=True)
            y += S(68)
        if self.ob_step == 3:
            bar = QRectF(x, y + S(8), w - S(56), S(6))
            self.rr(p, bar, S(3), self.a(0.12))
            done = self.ob_pct
            self.rr(p, QRectF(bar.x(), bar.y(), bar.width() * done, bar.height()), S(3), self.accent()[1])
            n = len(self.v.index.songs or [])
            self.text(p, QRectF(x, bar.bottom() + S(8), w, S(22)),
                      f"Done · {n} songs indexed" if done >= 1.0 else
                      f"{int(done * 100)}% · reading the lyrics already on this computer", 13.5, W_.Medium,
                      self.a(0.62))
        fy = r.bottom() - S(64)
        p.fillRect(QRectF(r.x(), fy, w, 1), self.a(0.08))
        dx = r.x() + S(22)
        for i in range(4):
            dw = S(20) if i == self.ob_step else S(8)
            self.rr(p, QRectF(dx, fy + S(29), dw, S(8)), S(4), INK if i == self.ob_step else self.a(0.25))
            dx += dw + S(6)
        b = self.button(p, r.right() - S(20), fy + S(13), "Start listening" if self.ob_step == 3 else "Continue",
                        "ob_next", style="primary", right=True)
        if self.ob_step < 3:
            b = self.button(p, b.x() - S(8), fy + S(13), "Skip setup", "ob_skip", style="ghost", right=True)
        if self.ob_step > 0:
            self.button(p, b.x() - S(8), fy + S(13), "Back", "ob_back", style="ghost", right=True)

    def ob_do(self, kind: str, payload) -> None:
        v = self.v
        if kind == "ob_next":
            if self.ob_step >= 3:
                self.ob_finish()
                return
            self.ob_step += 1
            if self.ob_step == 3:
                self.ob_pct = 0.0 if not v.index.songs else 1.0
                if not v.index.songs and not v.indexing:
                    v.indexing = True
                    v.fetcher.request_index()
        elif kind == "ob_back":
            self.ob_step = max(0, self.ob_step - 1)
        elif kind == "ob_skip":
            self.ob_finish()
        elif kind == "ob_spotify":
            v.show_port_help()
        elif kind == "ob_folder":
            self.add_folder()
        elif kind == "ob_toggle":
            if payload == "roman":
                v.menu_set("roman", "off" if v.roman != "off" else "under")
            elif payload == "any_player":
                v.menu_set("any_player", not v.any_player)
                v.follow_players(say=False)
        elif kind == "ob_key":
            self.set_home_key(keep_home=v.key_name("browse") != "Home")
        elif kind == "ob_sources":                    # setup goes on after; the drawer is over it
            v.show_menu, v.show_help = True, False
            v.dr_tab = "settings"
            v.dr_section_to("Sources")
            v.menu_idx = v.dr_menu_index().get("sync_slot0", v.menu_idx)      # the Syncs, in view

    def ob_finish(self) -> None:
        self.ob_step = None
        self.v.home_onboarded = True
        self.v.home_key_told = True
        self.v.autosave()

    def set_home_key(self, keep_home: bool) -> None:
        km = dict(self.v.keymap or {})
        if keep_home:
            km["browse"], km["blur"] = "Home", "B"
        else:
            km.pop("browse", None)
            km.pop("blur", None)
        self.v.set_keymap(km)

    def paint_entry(self, p: QPainter, W: int, H: int) -> list:
        """The Home and Search pills over the lyrics, while the mouse moves."""
        self.u = max(0.82, min(1.45, min(W / 1440.0, H / 900.0) * 1.05))
        S = self.S
        out = []
        pos = self.v.mouse_pos
        key = self.v.key_name("browse")
        fm = self.fm(14.5, W_.Bold)
        fk = self.fm(12, W_.DemiBold)
        w = S(46) + fm.horizontalAdvance("Home") + (fk.horizontalAdvance(key) + S(18) if key else 0)
        r = QRectF(S(20), S(20), w, S(40))
        hot = r.contains(pos)
        self.rr(p, r, r.height() / 2, QColor(16, 16, 21, 200 if hot else 150), self.a(0.18))
        self.icon(p, "home", QRectF(r.x() + S(14), r.center().y() - S(8), S(16), S(16)))
        self.text(p, QRectF(r.x() + S(38), r.y(), fm.horizontalAdvance("Home") + S(4), r.height()), "Home",
                  14.5, W_.Bold, elide=False)
        if key:
            k = QRectF(r.right() - S(12) - fk.horizontalAdvance(key) - S(10), r.center().y() - S(10),
                       fk.horizontalAdvance(key) + S(10), S(20))
            self.rr(p, k, S(5), self.a(0.12))
            self.text(p, k, key, 12, W_.DemiBold, self.a(0.8), Qt.AlignmentFlag.AlignHCenter, elide=False)
        out.append(("home", r))
        s_ = QRectF(r.right() + S(8), r.y(), S(40), S(40))
        hot = s_.contains(pos)
        self.rr(p, s_, S(20), QColor(16, 16, 21, 200 if hot else 150), self.a(0.18))
        self.icon(p, "search", s_.adjusted(S(12), S(12), -S(12), -S(12)))
        out.append(("search", s_))
        return out

    # ------------------------------------------------------------ mini
    def enter_mini(self) -> None:
        """The mini player: a window of its own, the big one hidden until it closes."""
        v = self.v
        if self.mini:
            return
        self.mini = True
        self._mini_was = v.isFullScreen()
        self.mini_win = MiniWindow(self)
        self.mini_win.show()
        if v.home_mini_top:
            QTimer.singleShot(400, lambda: self.mini_win is not None
                              and v.keep_window_above(self.mini_win, True))
        # Hidden, not minimised: KWin left a minimise request on screen.
        v.hide()

    def exit_mini(self) -> None:
        v = self.v
        if not self.mini:
            return
        self.mini = False
        win, self.mini_win = self.mini_win, None
        if win is not None:
            win.hide()
            win.deleteLater()
        if self._mini_was:
            v.showFullScreen()
        else:
            v.showNormal()
        # KWin's keepAbove went with the surface the hide threw away.
        if getattr(v, "on_top", False) and QApplication.platformName().startswith("wayland"):
            v.keep_window_above(v, True)
        v.raise_()
        v.activateWindow()

    def mini_pos(self) -> float:
        """The lyric's own time, off the clock: the big window's frames stop while it is hidden."""
        v = self.v
        ed = v.editor_position()
        clock = ed - v.track_offset() if ed is not None else v.clock.position()   # as LyricsView.position
        return clock - v.track_offset()

    def mini_lines(self) -> tuple[str, str, float]:
        """The sung line, the next one, and how far through the first it is."""
        st = self.mini_state()
        if st is None:
            return (self.v.status_text or "…", "", 0.0)
        lead, _bg, nxt, pos = st
        start = lead.get("start")
        span = max(0.01, float(lead.get("end") or (start or 0) + 1) - float(start or 0))
        f = max(0.0, min(1.0, (pos - float(start)) / span)) if start is not None else 0.0
        return lead.get("text", ""), (nxt or {}).get("text", ""), f

    def mini_state(self):
        """(lead line, its ad-libs, next lead line, lyric time) -- or None with no lyric."""
        lines = self.v.lines or []
        leads = [i for i, ln in enumerate(lines) if not ln.get("background") and not ln.get("credits")
                 and (ln.get("text") or "").strip()]
        if not leads:
            return None
        pos = self.mini_pos()
        cur = leads[0]
        for i in leads:
            if (lines[i].get("start") or 0) <= pos:
                cur = i
            else:
                break
        k = leads.index(cur)
        stop = leads[k + 1] if k + 1 < len(leads) else len(lines)
        bg = [ln for ln in lines[cur + 1:stop] if ln.get("background") and (ln.get("text") or "").strip()]
        nxt = lines[leads[k + 1]] if k + 1 < len(leads) else None
        return lines[cur], bg, nxt, pos

    def mini_leads(self) -> list:
        """The lyric's lead lines, in order: what mini_state steps through."""
        return [ln for ln in self.v.lines or [] if not ln.get("background") and not ln.get("credits")
                and (ln.get("text") or "").strip()]

    def mini_credit_due(self, pos: float, leads: list):
        """"start" before the first line with Credits on top, "end" once the singing is over, else None."""
        if not any(ln.get("credits") for ln in self.v.lines or []):
            return None
        starts = [ln["start"] for ln in leads if isinstance(ln.get("start"), (int, float))]
        if getattr(self.v, "credits_top", False):
            return "start" if starts and pos < min(starts) else None
        ends = [t for ln in leads for t in [ln.get("end", ln.get("start"))] if isinstance(t, (int, float))]
        return "end" if ends and pos >= max(ends) else None

    def mini_credit(self, p: QPainter, x: float, y: float, w: float, bottom: float, alpha: float) -> float:
        """The credit block's rows, wrapped, as far as `bottom`; returns the y under them."""
        block = next((ln for ln in self.v.lines or [] if ln.get("credits")), None)
        lh = self.fm(12.5, W_.Medium).height() * 1.3
        for row in (block or {}).get("credits") or ():
            fit = int((bottom - y) // lh)
            if fit < 1:
                break
            y += self.wrap(p, x, y, w, " ".join(str(row).split()), 12.5, W_.Medium,
                           self.a(alpha), min(3, fit), 1.3) + self.S(2)
        return y

    def sweep(self, p: QPainter, x: float, y: float, w: float, ln: dict, pos: float, px: float,
              weight, lit: QColor, dim: QColor, rows: int = 2) -> float:
        """A line laid out word by word and filled syllable by syllable; returns its height.
        A duet's second voice (`opposite`) hangs off the right, as in the lyrics view."""
        try:
            pieces = [pc for pc in self.v.pieces_of(ln) if pc[2]]
        except Exception:                                   # noqa: BLE001
            pieces = [(ln.get("start"), ln.get("end"), ln.get("text", ""), False)]
        # Wrapped a word at a time: syllables joined to the next one ("toge|ther") stay on one row.
        words, cur = [], []
        for pc in pieces:
            cur.append(pc)
            if not pc[3]:
                words.append(cur)
                cur = []
        if cur:
            words.append(cur)
        for _ in range(4):
            fm = self.fm(px, weight)
            space = fm.horizontalAdvance(" ")
            lay, cx, row = [], 0.0, 0
            for word in words:
                tws = [fm.horizontalAdvance(pc[2]) for pc in word]
                if cx > 0 and cx + sum(tws) > w:
                    row, cx = row + 1, 0.0
                for (s_, e_, t, joined), tw in zip(word, tws):
                    if cx > 0 and cx + tw > w:          # a word wider than the row
                        row, cx = row + 1, 0.0
                    lay.append((row, cx, tw, s_, e_, t))
                    cx += tw + (0.0 if joined else space)
            if row < rows or px <= 11:
                break
            px *= 0.86
        f = self.font(px, weight)
        fm = self.fm(px, weight)
        lh = fm.height() * 1.12
        p.setFont(f)
        ends: dict = {}
        for row, cx, tw, *_ in lay:
            ends[row] = max(ends.get(row, 0.0), cx + tw)
        right = bool(ln.get("opposite"))
        for row, cx, tw, s_, e_, t in lay:
            if row >= rows:
                break
            r = QRectF(x + (w - ends[row] if right else 0.0) + cx, y + row * lh, tw + 2, lh)
            if s_ is None or e_ is None:
                frac = 1.0 if (ln.get("start") or 0) <= pos else 0.0
            else:
                frac = max(0.0, min(1.0, (pos - s_) / max(0.01, e_ - s_)))
            al = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            if frac <= 0.0 or frac >= 1.0:
                p.setPen(lit if frac >= 1.0 else dim)
            else:
                # One pass with a soft edge: drawing the word twice (dim, then lit clipped)
                # left a grey fringe round every lit glyph and cut letters in half.
                soft = min(0.35, max(0.08, fm.horizontalAdvance("n") / max(1.0, tw)))
                g = QLinearGradient(QPointF(r.x(), 0), QPointF(r.x() + tw, 0))
                g.setColorAt(max(0.0, frac - soft / 2), lit)
                g.setColorAt(min(1.0, frac + soft / 2), dim)
                p.setPen(QPen(QBrush(g), 1))
            p.drawText(r, al, t)
        used = min(rows, (lay[-1][0] + 1) if lay else 1)
        return used * lh

    def paint_mini(self, p: QPainter, W: int, H: int) -> None:
        keep, self.hits = self.hits, []
        self.u = max(0.75, min(2.0, W / 400.0))
        S = self.S
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.paint_ground(p, W, H)
        p.fillRect(QRectF(0, 0, W, H), QColor(16, 16, 21, 110))
        pad = S(14)
        it = self.np_item()
        art = QRectF(pad, pad, S(64), S(64))
        if self.v.art_full is not None and not self.player.active:
            path = QPainterPath()
            path.addRoundedRect(art, S(8), S(8))
            p.save()
            p.setClipPath(path)
            p.drawPixmap(art, self.v.art_full, QRectF(self.v.art_full.rect()))
            p.restore()
        else:
            self.cover(p, art, it["art"], S(8), it["name"])
        self.hit("mini_exit", None, art)
        tx = art.right() + S(12)
        tw = W - tx - S(84)
        self.text(p, QRectF(tx, art.y() + S(8), tw, S(24)), it["name"] or "Nothing playing", 16, W_.Bold)
        self.text(p, QRectF(tx, art.y() + S(34), tw, S(20)), self.who(it), 13, W_.Medium, self.a(0.6))
        top = bool(self.v.home_mini_top)
        b = QRectF(W - pad - S(30), pad, S(30), S(30))
        self.rr(p, b, S(15), self.a(0.18 if self.hot("mini_exit2") else 0.10))
        self.icon(p, "expand", b.adjusted(S(8), S(8), -S(8), -S(8)))
        self.hit("mini_exit2", None, b)
        b2 = QRectF(b.x() - S(34), pad, S(30), S(30))
        self.rr(p, b2, S(15), INK if top else self.a(0.10))
        self.icon(p, "pin", b2.adjusted(S(8), S(8), -S(8), -S(8)), DARK if top else INK)
        self.hit("mini_pin", None, b2)
        ctl_y = H - pad - S(38)
        y = art.bottom() + S(12)
        room = ctl_y - S(6) - y
        _acc, light = self.accent()
        st = self.mini_state()
        if st is None:
            self.text(p, QRectF(pad, y, W - 2 * pad, S(26)), self.v.status_text or "…", 16, W_.Bold, self.a(0.5))
        else:
            lead, bg, nxt, pos = st
            bottom = ctl_y - S(4)
            leads = self.mini_leads()
            due = self.mini_credit_due(pos, leads)
            if due:
                y = self.mini_credit(p, pad, y, W - 2 * pad, bottom, 0.5)
                queue = leads if due == "start" else []
            else:
                rows = 1 if room <= S(84) else 2 if room <= S(150) else 3
                if getattr(self.v, "_sung", None) is not None:
                    light = QColor(255, 255, 255)    # Text ▸ Sung colour: white, as in the lyrics view
                y += self.sweep(p, pad, y, W - 2 * pad, lead, pos, 19, W_.Black, light, self.a(0.38), rows)
                if bg and self.v.home_mini_adlibs and y + S(20) <= bottom:
                    for ln in bg[:1]:
                        y += S(2) + self.sweep(p, pad, y + S(2), W - 2 * pad, ln, pos, 13.5, W_.Bold,
                                               self.a(0.85, light), self.a(0.25), 1)
                queue = leads[next((k + 1 for k, ln in enumerate(leads) if ln is lead), len(leads)):]
            # What follows, as far down as the window has room for.
            lh = self.fm(14, W_.Bold).height() * 1.25
            for ln in queue:
                fit = int((bottom - y - S(4)) // lh)
                if fit < 1:
                    break
                y += S(4) + self.wrap(p, pad, y + S(4), W - 2 * pad, ln.get("text", ""), 14, W_.Bold,
                                      self.a(0.32), min(2, fit), 1.25,
                                      Qt.AlignmentFlag.AlignRight if ln.get("opposite") else Qt.AlignmentFlag.AlignLeft)
            else:
                if due is None and not getattr(self.v, "credits_top", False):
                    self.mini_credit(p, pad, y + S(10), W - 2 * pad, bottom, 0.3)
        cy = ctl_y + S(19)
        playing = self.v.song_playing()
        self.button(p, pad - S(2), cy - S(17), "", "t_prev", icon="prev", style="ghost", h=34)
        bp_ = QRectF(pad + S(38), cy - S(19), S(38), S(38))
        self.rr(p, bp_, S(19), INK)
        self.icon(p, "pause" if playing else "play", bp_.adjusted(S(10), S(10), -S(10), -S(10)), DARK)
        self.hit("t_play", None, bp_)
        self.button(p, pad + S(80), cy - S(17), "", "t_next", icon="next", style="ghost", h=34)
        bar = QRectF(pad + S(124), cy - S(2), W - pad * 2 - S(124) - S(52), S(4))
        self.rr(p, bar, S(2), self.a(0.16))
        self.rr(p, QRectF(bar.x(), bar.y(), bar.width() * self.progress(), bar.height()), S(2), INK)
        self.hit("seek", bar, bar.adjusted(0, -S(8), 0, S(8)))
        ln_ = float((self.v.clock.meta or {}).get("length", 0) or 0)
        left = max(0.0, ln_ - self.v.song_position())
        self.text(p, QRectF(bar.right() + S(6), cy - S(10), S(48), S(20)), "-" + fmt_ms(left * 1000) if ln_ else "",
                  12.5, W_.DemiBold, self.a(0.55), Qt.AlignmentFlag.AlignRight)
        grip = QRectF(W - S(14), H - S(14), S(14), S(14))
        p.setPen(QPen(self.a(0.3), 1))
        for k in (4, 8, 12):
            p.drawLine(QPointF(W - S(k), H - 1), QPointF(W - 1, H - S(k)))
        self.hit("mini_grip", None, grip)
        self.mhits, self.hits = self.hits, keep

    # =============================================================== input
    def at(self, pos):
        for kind, payload, r in reversed(self.hits):
            if r.contains(pos):
                return (kind, payload)
        return None

    def move(self, pos) -> None:
        h = self.at(pos)
        if self.press_at is not None and self.pressed and self.pressed[0] == "vol":
            r = next((r for k, _p, r in reversed(self.hits) if k == "vol"), None)     # dragged along the bar
            if r is not None:
                self.player.set_volume(max(0.0, min(1.0, (pos.x() - r.x()) / max(1.0, r.width()))))
                self.v.update()
        if self.press_at is not None and self.pressed and not (self.drag and self.drag.get("live")):
            item = self.pressed[1] if isinstance(self.pressed[1], dict) else None
            if (item and item.get("kind") in ("track", "local", "album", "playlist")
                    and (pos - self.press_at).manhattanLength() > 8):
                self.drag = {"item": item, "live": True}
        if hit_key(h) != hit_key(self.hover):
            self.hover = h
            self.v.update()
        if self.drag and self.drag.get("live"):
            self.v.update()
        field = self.page == "search" and self.v.bq_field.under(pos)
        self.v.set_cursor(Qt.CursorShape.IBeamCursor if field else
                          Qt.CursorShape.PointingHandCursor if h and not h[0].endswith("_bg")
                          else Qt.CursorShape.ArrowCursor)

    def press(self, ev) -> None:
        pos = ev.position()
        right = ev.button() == Qt.MouseButton.RightButton
        if self.ob_step is not None:
            h = self.at(pos)
            if h and h[0].startswith("ob_") and h[0] != "ob_bg":
                self.ob_do(*h)
            self.v.update()
            return
        h = self.at(pos)
        if self.ctx and (not h or not h[0].startswith("ctx")):
            self.ctx = None
            self.v.update()
            if not right:
                return
        if self.popover and (not h or not h[0].startswith("pop")) and (not h or h[0] != "follow"):
            self.popover = False
            self.v.update()
            return
        if self.page == "search" and self.v.bq_field.press(
                pos, bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)):
            self.v.field_drag = self.v.bq_field
            return
        if right:
            if h and h[0] == "lyr_line":
                self.copy_menu(h[1][1], ev.globalPosition().toPoint())
                return
            if h and isinstance(h[1], dict) and h[1].get("kind") in ("track", "local", "album", "artist",
                                                                       "playlist"):
                self.ctx = {"x": pos.x(), "y": pos.y(), "item": h[1], "sub": False}
                self.v.update()
            return
        self.press_at, self.pressed = pos, h

    def release(self, ev) -> None:
        pos = ev.position()
        h, self.pressed, self.press_at = self.pressed, None, None
        if self.drag and self.drag.get("live"):
            item = self.drag["item"]
            self.drag = None
            target = next((pl for pl, r in reversed(self.drops) if r.contains(pos)), None)
            if target:
                if target["to"] == "queue":
                    self.queue(item)
                elif target.get("to") == "row":
                    self.pl_drop(item, target["i"])
                elif target["pl"]["uri"] == "liked":
                    if self.is_liked(item):
                        self.say("Already in Liked songs")
                    else:
                        self.like(item)
                else:
                    self.add_to_playlist(target["pl"], item)
            self.v.update()
            return
        if h is None or hit_key(self.at(pos)) != hit_key(h):
            return
        self.click(*h, pos=pos)
        self.v.update()

    def double(self, ev) -> None:
        h = self.at(ev.position())
        if h and h[0] == "row" and isinstance(h[1], dict):
            pass

    def click(self, kind: str, payload, pos=None) -> None:
        v = self.v
        if kind.startswith("ctx"):
            if kind == "ctx":
                self.ctx_do(payload)
            return
        if kind.startswith("pop"):
            self.pop_do(kind, payload)
            return
        if kind == "nav":
            self.go(payload)
            if payload == "search":
                self.v.bq_field.select_all()
        elif kind == "side_pl":
            self.go("liked" if payload["uri"] == "liked" else "playlist",
                    None if payload["uri"] == "liked" else payload)
        elif kind == "settings":
            v.show_menu, v.show_help = True, False
            v.dr_tab = "settings"
            v.dr_section_to("Home")
        elif kind == "follow":
            self.popover = not self.popover
        elif kind == "listen":
            from PyQt6.QtGui import QCursor
            v.listen_menu(QCursor.pos())
        elif kind == "lyrics":
            self.open_lyrics()
        elif kind == "lcd":
            if v.clock.tid or self.player.active:
                self.go("song", self.np_item_full())      # the song's page, not the lyrics
        elif kind == "np_artist":
            self.open_item(payload)
        elif kind == "t_play":
            v.player_do("PlayPause")
        elif kind == "t_prev":
            v.skip_at = time.monotonic()
            v.player_do("Previous")
        elif kind == "t_next":
            v.skip_at = time.monotonic()
            v.player_do("Next")
        elif kind == "t_queue":
            self.toggle_queue()
        elif kind == "t_mini":
            self.enter_mini()
        elif kind == "t_shuffle":
            self.player.shuffle = v.home_shuffle = not self.player.shuffle
        elif kind == "t_repeat":
            self.player.repeat = v.home_repeat = {"off": "all", "all": "one", "one": "off"}[self.player.repeat]
        elif kind == "vol" and pos is not None:
            r = next(r for k, _p, r in reversed(self.hits) if k == "vol")
            self.player.set_volume((pos.x() - r.x()) / max(1.0, r.width()))
        elif kind == "seek" and pos is not None:
            f = max(0.0, min(1.0, (pos.x() - payload.x()) / max(1.0, payload.width())))
            ln = float((v.clock.meta or {}).get("length", 0) or 0)
            if ln:
                v.seek_song(f * ln)
        elif kind == "heart":
            self.like(payload)
        elif kind == "undo":
            if self.note and self.note[1]:
                self.note[1]()
            self.note = None
        elif kind == "key_ok":
            v.home_key_told = True
            v.autosave()
        elif kind == "key_keep":
            self.set_home_key(keep_home=True)
            v.home_key_told = True
            v.autosave()
            self.say("Home stays on the Home key; B is the depth blur again")
        else:
            self.click_page(kind, payload, pos)

    def pop_do(self, kind: str, payload) -> None:
        v = self.v
        rows = getattr(self, "_pop_rows", [])
        if kind == "pop_any":
            v.menu_set("any_player", not v.any_player)
            v.follow_players(say=False)
        elif kind == "pop_auto":
            self.set_pin(None)
            self.say("Following whoever plays")
        elif kind == "pop_pick":
            row = next((r for r in rows if r["who"] == payload), None)
            if self.pinned() and self.pinned() != payload:
                self.set_pin(None)
            if payload == "mild":
                if self.player.current is not None:
                    self.player.active = True
                else:
                    self.go("local")
            elif row is not None:
                if self.player.active:
                    self.player.stand_down()
                if row.get("sess") is not None:
                    row["sess"].who = row["who"]
        elif kind == "pop_pin":
            row = next((r for r in rows if r["who"] == payload), None)
            if row is None:
                return
            if self.pinned() == payload:
                self.set_pin(None)
                self.say(f"Unpinned {row['name']}: following whoever plays")
            else:
                self.set_pin(row)
                self.say(f"Pinned to {row['name']}: other players are not followed")

    def pinned(self) -> str:
        ov = self.overlay()
        return (ov.pinned or "") if ov is not None else ""

    def set_pin(self, row) -> None:
        ov = self.overlay()
        if ov is None:
            return
        if row is None:
            ov.pin(None)
        else:
            ov.pin(row["who"], row["name"])

    def release_pin_for(self, target: str) -> None:
        """Playing something picked here is choosing a player: a pin on another one gives way."""
        pin = self.pinned()
        if pin and pin != target:
            self.set_pin(None)

    def wheel(self, ev) -> None:
        if self.ob_step is not None or self.ctx:
            return
        self.v.browse_scroll_target -= ev.angleDelta().y() * 0.7

    def key(self, ev) -> None:
        v = self.v
        k = ev.key()
        text = ev.text()
        mods = ev.modifiers()
        if self.ob_step is not None:
            if k == Qt.Key.Key_Escape:
                self.ob_finish()
            elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.ob_do("ob_next", None)
            v.update()
            return
        if k == Qt.Key.Key_Escape:
            if self.ctx or self.popover:
                self.ctx, self.popover = None, False
            elif self.page == "search" and v.bq_field.text:
                v.bq_field.set_text("")
                self.search_changed()
            elif not self.back():
                v.close_browse()
            v.update()
            return
        if self.page == "search":
            if self.search_key(ev):
                v.update()
                return
        if text == "/" or k == Qt.Key.Key_F3:
            self.go("search")
            v.bq_field.select_all()
            return
        if v.key_matches(ev, "paste"):        # a link pasted anywhere here: what it is, on the search page
            self.go("search")
            v.bq_field.set_text("")
            if v.bq_field.paste():
                self.search_changed()
            return
        if v.key_matches(ev, "browse") and self.page != "search":
            self.go("home")
            return
        if v.key_matches(ev, "queue") and self.page != "search":
            self.toggle_queue()
            return
        if v.key_matches(ev, "quit"):
            v.close()
            return
        if k in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            v.browse_scroll_target += 150 * (1 if k == Qt.Key.Key_Down else -1)
            return
        if k in (Qt.Key.Key_PageDown, Qt.Key.Key_PageUp):
            v.browse_scroll_target += self.content.height() * 0.85 * (1 if k == Qt.Key.Key_PageDown else -1)
            return
        if text and text.isprintable() and text != " " and not (mods & Qt.KeyboardModifier.ControlModifier):
            self.go("search")
            v.bq_field.set_text(text)
            self.search_changed()
            return
        v.transport_key(k, bool(mods & Qt.KeyboardModifier.ShiftModifier))

    def tick(self) -> bool:
        """Per-frame upkeep; True while something on the page is moving."""
        now = time.monotonic()
        if self.ob_step == 3 and self.ob_pct < 1.0:
            got = len(self.v.index.songs or [])
            self.ob_pct = 1.0 if (got and not self.v.indexing) else min(0.95, self.ob_pct + 0.004)
            return True
        if self.page == "album" and self.cd_at and int(time.time()) != self.cd_sec:
            return True                     # the release countdown's next second: one frame
        return bool(self.note and self.note[2] > now) or bool(self.drag)

    def observe(self) -> None:
        """Feed the play log; called from the window's poll."""
        v = self.v
        ov = self.overlay()
        if ov is not None and ov.pin_lost:
            self.say(f"{ov.pin_lost} closed: following whoever plays again")
            ov.pin_lost = ""
        if self._seek_when is not None:
            song, at, until = self._seek_when
            if time.monotonic() > until:
                self._seek_when = None
            elif v.clock.status == "Playing" and v.clock.tid and self.is_current(song):
                self._seek_when = None
                v.seek_song(at + v.track_offset())
        meta = v.clock.meta or {}
        kind = ""
        if v.body is not None:
            try:
                kind = v.lyric_quality()
            except Exception:                               # noqa: BLE001
                kind = ""
        line = None
        if v.lines:
            pos = v.position() - v.track_offset()
            line = sum(1 for ln in v.lines if (ln.get("start") or 0) <= pos) - 1
        player = "Mild Lyrics" if self.player.active else (
            (getattr(v.clock.io, "app", "") or "spotify").replace("-", " ").title())
        uri = f"spotify:track:{v.clock.tid}" if v.clock.tid and not LP_hex(v.clock.tid) else ""
        if v.body is not None and v.clock.tid and v.clock.tid not in self.kinds.map:
            self.kinds.note(v.clock.tid, v.body)
        cur = self.player.current if self.player.active else None
        auto = bool(cur and cur.get("_auto"))
        self.tracker.observe(v.clock.tid, meta, v.clock.status == "Playing", v.clock.position(),
                             player, kind, line, uri, auto)
        v.lastfm.observe(self.tracker.cur, meta, v.clock.status == "Playing",
                         v.lastfm_scrobble, v.lastfm_spotify)
        now = self.tracker.cur or {}
        if auto and not cur.get("_heard") and now.get("s", 0) >= PLG.SKIP_BEFORE \
                and AP.norm(now.get("title", "")) == AP.title_of(cur):
            cur["_heard"] = True                # listened to, not skipped: it seeds autoplay too

    def close(self) -> None:
        self.tracker.flush()
        for src in (self.spot, self.spot_q, self.dz, self.dz_q, self.ups, self.yt, self.links):
            src.close()
        self.resolver.close()


def LP_hex(tid: str) -> bool:
    """A song_key (hex) rather than a Spotify id."""
    return bool(tid) and all(c in "0123456789abcdef" for c in tid)


class MiniWindow(QWidget):
    """The mini player's own window: drag anywhere to move it, the corner to size it."""

    TITLE = "Mild Lyrics mini player"

    def __init__(self, home: Home) -> None:
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.home = home
        self.setWindowTitle(self.TITLE)
        self.setMouseTracking(True)
        self.setMinimumSize(300, 150)
        self.resize(int(400 * home.u), int(250 * home.u))
        self.pressed = None
        self.timer = QTimer(self)
        hz = self.screen().refreshRate() if self.screen() is not None else 60.0
        self.timer.setInterval(max(4, int(1000 / max(30.0, hz))))
        self.timer.timeout.connect(self.update)
        self.timer.start()

    def showEvent(self, ev) -> None:                         # noqa: N802
        self.timer.start()
        super().showEvent(ev)

    def hideEvent(self, ev) -> None:                         # noqa: N802
        self.timer.stop()                   # hidden in the tray: no refresh-rate wakeups
        super().hideEvent(ev)

    def paintEvent(self, _ev) -> None:                       # noqa: N802
        p = QPainter(self)
        try:
            self.home.paint_mini(p, self.width(), self.height())
        finally:
            p.end()

    def at(self, pos):
        for kind, payload, r in reversed(getattr(self.home, "mhits", [])):
            if r.contains(pos):
                return (kind, payload)
        return None

    def mousePressEvent(self, ev) -> None:                   # noqa: N802
        h = self.at(ev.position())
        if h is None or h[0] == "mini_grip":
            handle = self.windowHandle()
            if handle is not None:
                if h is None:
                    handle.startSystemMove()
                else:
                    handle.startSystemResize(Qt.Edge.RightEdge | Qt.Edge.BottomEdge)
            return
        self.pressed = h

    def mouseReleaseEvent(self, ev) -> None:                 # noqa: N802
        h, self.pressed = self.pressed, None
        if h is None or hit_key(self.at(ev.position())) != hit_key(h):
            return
        home, v = self.home, self.home.v
        kind, payload = h
        if kind in ("mini_exit", "mini_exit2"):
            home.exit_mini()
        elif kind == "mini_pin":
            v.home_mini_top = not v.home_mini_top
            v.keep_window_above(self, v.home_mini_top)
        elif kind == "seek":
            f = max(0.0, min(1.0, (ev.position().x() - payload.x()) / max(1.0, payload.width())))
            ln = float((v.clock.meta or {}).get("length", 0) or 0)
            if ln:
                v.seek_song(f * ln)
        else:
            home.click(kind, payload, ev.position())
        self.update()

    def mouseMoveEvent(self, ev) -> None:                    # noqa: N802
        h = self.at(ev.position())
        self.home.hover = h
        self.setCursor(Qt.CursorShape.SizeFDiagCursor if h and h[0] == "mini_grip" else
                       Qt.CursorShape.PointingHandCursor if h else Qt.CursorShape.ArrowCursor)

    def keyPressEvent(self, ev) -> None:                     # noqa: N802
        if ev.key() == Qt.Key.Key_Escape:
            self.home.exit_mini()
            return
        self.home.v.transport_key(ev.key(), bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier))

    def closeEvent(self, ev) -> None:                        # noqa: N802
        ev.accept()
        # At once, not later: with the big window hidden, this is the last window and Qt would quit.
        if self.home.mini:
            self.home.exit_mini()


class _WordsBridge(QObject):
    """Carries a fetched preview back to the GUI thread."""
    done = pyqtSignal(str, object)


def LS_spicy_made(doc) -> bool:
    import lyric_sources as LS
    return LS.spicy_made(doc)


def LS_apple_instead(tid: str, meta: dict):
    import lyric_sources as LS
    return LS.apple_instead(tid, meta)


def TTML_of(doc) -> str:
    import spicy_lyrics as SL
    return SL.render(doc, "ttml")


def TL(doc, split: str, threshold: float) -> list[dict]:
    import spicy_lyrics as SL
    return SL.timeline(doc, split=split, threshold=threshold)


ITEM_KEYS = ("uri", "name", "sub", "path", "_qi", "_pi", "_n", "_i", "head")


def hit_key(h):
    """What a hit is, for "is it the same one": kind and the item's identity, never the
    item by value. A row holds the list it is in (`_list`), the list holds the row, and
    comparing two paints' copies of that by value never ends (RecursionError: the click
    was dropped)."""
    if h is None:
        return None
    kind, payload = h
    if isinstance(payload, dict):
        return (kind,) + tuple(str(payload.get(k, "")) for k in ITEM_KEYS)
    if isinstance(payload, (str, int, float, bool, type(None))):
        return (kind, payload)
    if isinstance(payload, tuple):
        return (kind,) + tuple(hit_key(("", x)) if isinstance(x, dict) else x for x in payload)
    return (kind, type(payload).__name__)


class Ctx(list):
    """The list a row belongs to: compared and hashed by identity, so a row that holds it
    can be compared, and printed, without walking back into itself."""
    __eq__ = object.__eq__
    __ne__ = object.__ne__
    __hash__ = object.__hash__

    def __repr__(self) -> str:
        return f"<{len(self)} rows>"
