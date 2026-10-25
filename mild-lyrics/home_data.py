"""Spotify's library, feed, charts and pages for the home page, through
Spicetify; reads and writes each on a worker of their own. Notes:
docs/notes/mild-lyrics/home_page.md."""
from __future__ import annotations

import json
import queue
import threading
import time

from PyQt6.QtCore import QObject, pyqtSignal

# Shared helpers the scripts below start with. T() is one track in the shape
# the page draws: uri, name, sub (the artists), artists, album, art, ms.
_PRE = r"""
const P = Spicetify.Platform;
const img = (o) => { if (!o) return ""; if (typeof o === "string") return o;
  const s = o.sources || o.items || o; if (Array.isArray(s) && s.length) {
    const x = s.find(i => (i.width || 0) >= 250) || s[0]; return x.url || (x.sources ? img(x) : ""); }
  return o.url || ""; };
const pick = (imgs) => { if (!Array.isArray(imgs) || !imgs.length) return "";
  const x = imgs.find(i => i.label === "large") || imgs.find(i => (i.width || 0) >= 250) || imgs[0];
  return x.url || ""; };
const names = (a) => (a || []).map(x => x.name || (x.profile || {}).name).filter(Boolean);
const T = (t) => { if (!t || !t.uri) return null; const al = t.album || t.albumOfTrack || {};
  const ar = Array.isArray(t.artists) ? t.artists : ((t.artists || {}).items || []);
  return {uri: t.uri, uid: t.uid || "", name: t.name || "", sub: names(ar).join(", "),
    artists: ar.map(x => ({name: x.name || (x.profile || {}).name || "", uri: x.uri || ""})),
    album: al.name || "", album_uri: al.uri || "",
    art: pick(al.images) || img(al.coverArt) || pick(t.images) || "",
    ms: ((t.duration || {}).milliseconds) || ((t.duration || {}).totalMilliseconds) || 0,
    added: (typeof t.addedAt === "string") ? t.addedAt : "",
    plays: Number(t.playcount || 0) || 0}; };
"""

JS_FEED = "(async () => { try {" + _PRE + r"""
  const r = await Spicetify.GraphQL.Request(Spicetify.GraphQL.Definitions.home,
    {timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone, sp_t: "", facet: null,
     sectionItemsLimit: 10, homeEndUserIntegration: "INTEGRATION_WEB_PLAYER"});
  const secs = ((((r.data || {}).home || {}).sectionContainer || {}).sections || {}).items || [];
  const out = [];
  for (const s of secs) {
    const title = (((s.data || {}).title) || {}).transformedLabel || "";
    const items = [];
    for (const i of (((s.sectionItems || {}).items) || [])) {
      const d = ((i.content || {}).data) || {};
      const k = d.__typename;
      if (!d.uri || !["Playlist", "Album", "Artist"].includes(k)) continue;
      items.push({uri: d.uri, kind: k.toLowerCase(),
        name: d.name || (d.profile || {}).name || "",
        sub: (d.description || "").replace(/<[^>]+>/g, "") ||
             names(((d.artists || {}).items) || []).join(", ") || k,
        art: img(d.images && (d.images.items || [])[0]) || img(d.coverArt) ||
             img((d.visuals || {}).avatarImage),
        colour: (((((d.images || {}).items || [])[0] || {}).extractedColors || {}).colorDark || {}).hex || ""});
    }
    if (items.length) out.push({title, uri: s.uri || "", kind: (s.data || {}).__typename || "", items});
  }
  return out;
} catch (e) { return null; } })()"""

JS_LIKED = "(async () => { try {" + _PRE + r"""
  const out = []; let off = 0;
  while (off < %d) {
    const r = await P.LibraryAPI.getTracks({limit: 200, offset: off});
    const it = (r || {}).items || [];
    for (const t of it) { const x = T(t); if (x) out.push(x); }
    if (it.length < 200) break; off += 200;
  }
  return out;
} catch (e) { return null; } })()"""

# LibraryAPI filter ids: "0" albums, "1" artists, "2" playlists.
JS_SHELF = "(async () => { try {" + _PRE + r"""
  const r = await P.LibraryAPI.getContents({filters: [%s], limit: 200, offset: 0});
  return ((r || {}).items || []).filter(x => x && x.uri).map(x => ({uri: x.uri,
    kind: x.type || "", name: x.name || "",
    sub: x.type === "album" ? names(x.artists).join(", ") :
         x.type === "playlist" ? ((x.owner || {}).displayName || "Playlist") : "Artist",
    art: pick(x.images), mine: !!x.isOwnedBySelf, can_add: !!x.canAdd,
    count: x.totalLength || 0, played: x.lastPlayedAt || ""}));
} catch (e) { return null; } })()"""

JS_PLAYLIST = "(async () => { try {" + _PRE + r"""
  const u = %s;
  const m = await P.PlaylistAPI.getMetadata(u);
  const c = await P.PlaylistAPI.getContents(u, {limit: 500});
  return {uri: u, name: (m || {}).name || "", sub: ((m || {}).description || "").replace(/<[^>]+>/g, ""),
    owner: (((m || {}).owner) || {}).displayName || "", mine: !!(m || {}).isOwnedBySelf,
    can_add: !!((m || {}).permissions || {}).canEditItems || !!(m || {}).canAdd || !!(m || {}).isOwnedBySelf,
    art: pick((m || {}).images), total: ((c || {}).totalLength) || 0,
    tracks: (((c || {}).items) || []).map(T).filter(Boolean)};
} catch (e) { return null; } })()"""

JS_ALBUM = "(async () => { try {" + _PRE + r"""
  const r = await Spicetify.GraphQL.Request(Spicetify.GraphQL.Definitions.getAlbum,
    {uri: %s, locale: "", offset: 0, limit: 100});
  const a = ((r.data || {}).albumUnion) || {};
  if (!a.uri) return null;
  const ar = ((a.artists || {}).items || []).map(y => ({name: (y.profile || {}).name || "", uri: y.uri || ""}));
  const tracks = [];
  for (const x of (((a.tracksV2 || a.tracks || {}).items) || [])) {
    const t = x.track || ((x.trackV2 || {}).data) || x || {};
    if (!t.uri) continue;
    const ta = ((t.artists || {}).items || []).map(y => ({name: (y.profile || {}).name || "", uri: y.uri || ""}));
    tracks.push({uri: t.uri, name: t.name || "", artists: ta, sub: ta.map(y => y.name).join(", "),
      ms: ((t.duration || {}).totalMilliseconds) || 0, plays: Number(t.playcount || 0) || 0,
      album: a.name || "", album_uri: a.uri, art: img(a.coverArt)});
  }
  return {uri: a.uri, name: a.name || "", year: (((a.date || {}).isoString) || "").slice(0, 4),
    type: (a.type || "album").toLowerCase(), label: a.label || "", art: img(a.coverArt),
    artists: ar, tracks};
} catch (e) { return null; } })()"""

JS_ARTIST = "(async () => { try {" + _PRE + r"""
  const r = await Spicetify.GraphQL.Request(Spicetify.GraphQL.Definitions.queryArtistOverview,
    {uri: %s, locale: ""});
  const a = ((r.data || {}).artistUnion) || {};
  if (!a.uri) return null;
  const d = a.discography || {};
  const top = (((d.topTracks || {}).items) || []).map(x => T(x.track)).filter(Boolean);
  const rel = (x) => ({uri: x.uri, name: x.name || "", kind: "album",
    sub: ((x.date || {}).year || "") + "", art: img(x.coverArt), year: (x.date || {}).year || "",
    type: (x.type || "").toLowerCase()});
  const albums = (((d.popularReleasesAlbums || {}).items) || []).map(rel);
  for (const g of (((d.albums || {}).items) || []))
    for (const x of (((g.releases || {}).items) || []))
      if (!albums.find(y => y.uri === x.uri)) albums.push(rel(x));
  const related = ((((a.relatedContent || {}).relatedArtists) || {}).items || []).map(x => ({
    uri: x.uri, name: (x.profile || {}).name || "", kind: "artist", sub: "Artist",
    art: img((x.visuals || {}).avatarImage)}));
  return {uri: a.uri, name: (a.profile || {}).name || "", art: img((a.visuals || {}).avatarImage),
    header: img((a.headerImage || {}).data) || img(a.headerImage),
    listeners: (a.stats || {}).monthlyListeners || 0, saved: !!a.saved,
    tracks: top, albums: albums.slice(0, 24), related: related.slice(0, 12)};
} catch (e) { return null; } })()"""

CHARTS = {"Global": "spotify:playlist:37i9dQZEVXbMDoHDwVN2tF",
          "Viral 50": "spotify:playlist:37i9dQZEVXbLiRSasKsNU9"}

# Spotify's own Top 50 per country; the ids are stable (checked 2026-10-18).
# Search does not return these, so a country missing here falls back to Global.
COUNTRY_TOP = {
    "US": "37i9dQZEVXbLRQDuF5jeBp", "GB": "37i9dQZEVXbLnolsZ8PSNw", "BE": "37i9dQZEVXbJNSeeHswcKB",
    "NL": "37i9dQZEVXbKCF6dqVpDkS", "FR": "37i9dQZEVXbIPWwFssbupI", "DE": "37i9dQZEVXbJiZcmkrIHGU",
    "IT": "37i9dQZEVXbIQnj7RRhdSX", "ES": "37i9dQZEVXbNFJfN1Vw8d9", "BR": "37i9dQZEVXbMXbN3EUUhlg",
    "MX": "37i9dQZEVXbO3qyFxbkOE1", "CA": "37i9dQZEVXbKj23U1GF4IR", "AU": "37i9dQZEVXbJPcfkRz0wJ0",
    "JP": "37i9dQZEVXbKXQ4mDTEBXq", "KR": "37i9dQZEVXbNxXF4SkHj9F", "SE": "37i9dQZEVXbLoATJ81JYXz",
    "NO": "37i9dQZEVXbJvfa0Yxg7E7", "DK": "37i9dQZEVXbL3J0k32lWnN", "FI": "37i9dQZEVXbMxcczTSoGwZ",
    "PL": "37i9dQZEVXbN6itCcaL3Tt", "PT": "37i9dQZEVXbKyJS56d1pgi", "IE": "37i9dQZEVXbKM896FDX8L1",
    "AT": "37i9dQZEVXbKNHh6NIXu36", "CH": "37i9dQZEVXbJiyhoAPEfMK", "IN": "37i9dQZEVXbLZ52XmnySJg",
    "ID": "37i9dQZEVXbObFQZ3JLcXt", "PH": "37i9dQZEVXbNBz9cRCSFkY", "AR": "37i9dQZEVXbMMy2roB9myp",
    "CL": "37i9dQZEVXbL0GavIqMTeb", "CO": "37i9dQZEVXbOa2lmxNORXQ", "TR": "37i9dQZEVXbIVYVBNw9D5K",
    "NZ": "37i9dQZEVXbM8SIrkERIYl", "ZA": "37i9dQZEVXbMH2jvi6jvjk",
}
JS_COUNTRY = ("(async () => { try { return ((await Spicetify.Platform.ProductStateAPI.getValues())"
              " || {}).country || \"\"; } catch (e) { return null; } })()")

JS_SEARCH = "(async () => { try {" + _PRE + r"""
  const r = await Spicetify.GraphQL.Request(Spicetify.GraphQL.Definitions.searchDesktop,
    {searchTerm: %s, offset: 0, limit: 20, numberOfTopResults: 5, includeAudiobooks: false,
     includeArtistHasConcertsField: false, includePreReleases: false,
     includeLocalConcertsField: false, includeAuthors: false});
  const s = (r.data || {}).searchV2 || {};
  const tracks = (((s.tracksV2 || {}).items) || []).map(x => T(((x.item || {}).data) || x.data)).filter(Boolean);
  const artists = (((s.artists || {}).items) || []).map(x => x.data || {}).filter(d => d.uri)
    .map(d => ({uri: d.uri, kind: "artist", name: (d.profile || {}).name || "", sub: "Artist",
      art: img((d.visuals || {}).avatarImage)}));
  const albums = ((((s.albumsV2 || s.albums) || {}).items) || []).map(x => x.data || {}).filter(d => d.uri)
    .map(d => ({uri: d.uri, kind: "album", name: d.name || "",
      sub: names(((d.artists || {}).items) || []).join(", ") + (((d.date || {}).year) ? " · " + d.date.year : ""),
      art: img(d.coverArt)}));
  const playlists = (((s.playlists || {}).items) || []).map(x => x.data || {}).filter(d => d.uri)
    .map(d => ({uri: d.uri, kind: "playlist", name: d.name || "",
      sub: ((d.ownerV2 || {}).data || {}).name || "Playlist", art: img(((d.images || {}).items || [])[0])}));
  const top = ((((s.topResultsV2 || {}).itemsV2) || []).map(x => ((x.item || {}).data) || {})[0]) || {};
  return {tracks, artists, albums, playlists, top: top.uri || ""};
} catch (e) { return null; } })()"""

# The quick one (about a third of a second): Spotify's own search box's
# mixed top results. JS_SEARCH, the full one, follows it.
JS_SEARCH_FAST = "(async () => { try {" + _PRE + r"""
  const r = await Spicetify.GraphQL.Request(Spicetify.GraphQL.Definitions.searchModalResults,
    {searchTerm: %s, offset: 0, limit: 12, numberOfTopResults: 12, includeAudiobooks: false,
     includePreReleases: false, includeLocalConcertsField: false, includeAuthors: false});
  const items = ((((r || {}).data || {}).searchV2 || {}).topResultsV2 || {}).itemsV2 || [];
  const out = {tracks: [], artists: [], albums: [], playlists: [], top: ""};
  for (const w of items) {
    const d = (((w || {}).item || w || {}).data) || {};
    if (!d.uri) continue;
    if (!out.top) out.top = d.uri;
    if (d.__typename === "Track") { const x = T(d); if (x) out.tracks.push(x); }
    else if (d.__typename === "Artist") out.artists.push({uri: d.uri, kind: "artist",
      name: (d.profile || {}).name || "", sub: "Artist", art: img((d.visuals || {}).avatarImage)});
    else if (d.__typename === "Album") out.albums.push({uri: d.uri, kind: "album", name: d.name || "",
      sub: names(((d.artists || {}).items) || []).join(", "), art: img(d.coverArt)});
    else if (d.__typename === "Playlist") out.playlists.push({uri: d.uri, kind: "playlist", name: d.name || "",
      sub: ((d.ownerV2 || {}).data || {}).name || "Playlist", art: img(((d.images || {}).items || [])[0])});
  }
  return out;
} catch (e) { return null; } })()"""

# Spotify's own song radio (what its autoplay plays): a seed track to a mix of about 50.
JS_RADIO = "(async () => { try {" + _PRE + r"""
  const r = await Spicetify.CosmosAsync.get("https://spclient.wg.spotify.com/inspiredby-mix/v2/seed_to_playlist/"
    + %s + "?response-format=json");
  const uri = (((r || {}).mediaItems || [])[0] || {}).uri;
  if (!uri) return null;
  const c = await P.PlaylistAPI.getContents(uri, {limit: 60});
  return {uri, tracks: (((c || {}).items) || []).map(T).filter(Boolean)};
} catch (e) { return null; } })()"""

JS_CONTAINS = "(async () => { try { return await Spicetify.Platform.LibraryAPI.contains(...%s); }" \
              " catch (e) { return null; } })()"

JS_LIKE = "(async () => { try { await Spicetify.Platform.LibraryAPI.%s({uris: [%s]}); return true; }" \
          " catch (e) { return String(e); } })()"
JS_QUEUE_ADD = "(async () => { try { await Spicetify.Platform.PlayerAPI.addToQueue(%s); return true; }" \
               " catch (e) { return String(e); } })()"
# Play next: in front of whatever comes next, queued or not.
JS_QUEUE_NEXT = r"""(async () => { try {
  const P = Spicetify.Platform, items = %s;
  const q = await P.PlayerAPI.getQueue();
  const first = (((q || {}).queued) || [])[0] || (((q || {}).nextUp) || [])[0];
  if (first && first.uri) await P.PlayerAPI.insertIntoQueue(items, {before: {uri: first.uri, uid: first.uid}});
  else await P.PlayerAPI.addToQueue(items);
  return true; } catch (e) { return String(e); } })()"""
JS_QUEUE_CLEAR = "(async () => { try { await Spicetify.Platform.PlayerAPI.clearQueue(); return true; }" \
                 " catch (e) { return String(e); } })()"
JS_PL_ADD = "(async () => { try { await Spicetify.Platform.PlaylistAPI.add(%s, %s, {after: \"end\"});" \
            " return true; } catch (e) { return String(e); } })()"
JS_PL_REMOVE = "(async () => { try { await Spicetify.Platform.PlaylistAPI.remove(%s, %s); return true; }" \
               " catch (e) { return String(e); } })()"
JS_PL_MOVE = "(async () => { try { await Spicetify.Platform.PlaylistAPI.move(%s, %s, %s); return true; }" \
             " catch (e) { return String(e); } })()"
JS_PL_CREATE = "(async () => { try { return await Spicetify.Platform.RootlistAPI.createPlaylist(%s," \
               " {before: \"start\"}); } catch (e) { return null; } })()"
JS_SHUFFLE = "(async () => { try { await Spicetify.Platform.PlayerAPI.setShuffle(%s); return true; }" \
             " catch (e) { return String(e); } })()"
JS_FOLLOW = "(async () => { try { await Spicetify.Platform.LibraryAPI.%s({uris: [%s]}); return true; }" \
            " catch (e) { return String(e); } })()"


def mosaic(u: str) -> str:
    """A playlist's four-cover collage as Spotify's own mosaic image."""
    parts = [p for p in u.split(":")[2:] if p]
    return "https://mosaic.scdn.co/300/" + "".join(parts) if len(parts) == 4 else ""


def _arturl(v, fix):
    """Every "art" in a result through the window's art_url."""
    if isinstance(v, list):
        for x in v:
            _arturl(x, fix)
    elif isinstance(v, dict):
        for k, x in v.items():
            if k in ("art", "header") and isinstance(x, str):
                v[k] = fix(x)
            else:
                _arturl(x, fix)
    return v


class Spot(QObject):
    """The page's Spotify. `got(key, value)` lands on the GUI thread."""

    got = pyqtSignal(str, object)
    did = pyqtSignal(str, object)          # a write: its tag, True or the error

    KEEP = 300.0
    FAIL_WAIT = 30.0          # s a read that failed is not asked again (each failure re-ran autoplay, which re-asked)

    def __init__(self, ask, art_url) -> None:
        super().__init__()
        self.ask = ask
        self.art_url = lambda u: (mosaic(u) if u.startswith("spotify:mosaic:") else "") or art_url(u)
        self.data: dict[str, tuple[float, object]] = {}
        self.fails: dict[str, float] = {}       # key -> when its last read failed
        self._want: dict[str, str] = {}
        self._order: list[str] = []
        self._busy: set[str] = set()
        self._lock = threading.Lock()
        self._kick = threading.Event()
        self._acts: queue.Queue = queue.Queue()
        self.stop = False
        threading.Thread(target=self._reads, daemon=True).start()
        threading.Thread(target=self._writes, daemon=True).start()

    # ------------------------------------------------------------ reads
    def get(self, key: str):
        hit = self.data.get(key)
        return None if hit is None else hit[1]

    def age(self, key: str) -> float:
        hit = self.data.get(key)
        return 1e9 if hit is None else time.monotonic() - hit[0]

    def failed(self, key: str) -> bool:
        """The last read of `key` failed (no answer, an error) less than FAIL_WAIT ago."""
        at = self.fails.get(key)
        return at is not None and time.monotonic() - at < self.FAIL_WAIT

    def want(self, key: str, js: str, keep: float | None = None, first: bool = False) -> None:
        """Ask for `key` unless a fresh answer is held, one is on its way, or it just failed."""
        if self.age(key) < (self.KEEP if keep is None else keep) or self.failed(key):
            return
        with self._lock:
            if key in self._busy or key in self._want:
                return
            self._want[key] = js
            if first:
                self._order.insert(0, key)
            else:
                self._order.append(key)
        self._kick.set()

    def want_only(self, key: str, js: str, keep: float | None = None) -> None:
        """Like want, but the newest ask replaces any not yet started: a search box."""
        with self._lock:
            for k in [k for k in self._order if k.startswith(("search:", "searchfull:"))]:
                self._order.remove(k)
                self._want.pop(k, None)
        self.fails.pop(key, None)              # typed again: asked again
        self.want(key, js, keep=keep, first=True)

    def drop(self, key: str) -> None:
        self.data.pop(key, None)
        self.fails.pop(key, None)

    def _reads(self) -> None:
        while not self.stop:
            self._kick.wait(1.0)
            while not self.stop:
                with self._lock:
                    if not self._order:
                        self._kick.clear()
                        break
                    key = self._order.pop(0)
                    js = self._want.pop(key)
                    self._busy.add(key)
                try:
                    val = self.ask(js)
                except Exception:                            # noqa: BLE001
                    val = None
                if val is not None:
                    val = _arturl(val, self.art_url)
                    self.data[key] = (time.monotonic(), val)
                    self.fails.pop(key, None)
                else:
                    self.fails[key] = time.monotonic()
                with self._lock:
                    self._busy.discard(key)
                if not self.stop:
                    self.got.emit(key, val)

    # ------------------------------------------------------------ writes
    def act(self, tag: str, js: str) -> None:
        self._acts.put((tag, js))

    def _writes(self) -> None:
        while not self.stop:
            tag, js = self._acts.get()
            if self.stop:
                return
            try:
                val = self.ask(js)
            except Exception as e:                           # noqa: BLE001
                val = str(e)
            if not self.stop:
                self.did.emit(tag, val)

    def close(self) -> None:
        self.stop = True
        self._kick.set()
        self._acts.put(("", ""))

    # ------------------------------------------------------------ named asks
    def feed(self):
        self.want("feed", JS_FEED, keep=900)

    def liked(self, n: int = 2000, keep: float | None = None):
        self.want("liked", JS_LIKED % n, keep=keep)

    def shelf(self, which: str):
        fid = {"albums": '"0"', "artists": '"1"', "playlists": '"2"'}[which]
        self.want(which, JS_SHELF % fid, keep=120)

    def playlist(self, uri: str, keep: float = 60):
        self.want("pl:" + uri, JS_PLAYLIST % json.dumps(uri), keep=keep, first=True)

    def album(self, uri: str):
        self.want("album:" + uri, JS_ALBUM % json.dumps(uri), keep=1800, first=True)

    def artist(self, uri: str):
        self.want("artist:" + uri, JS_ARTIST % json.dumps(uri), keep=1800, first=True)

    def chart(self, which: str):
        self.playlist(self.chart_uri(which), keep=3600)

    def chart_uri(self, which: str) -> str:
        if which == "Your country":
            self.want("country", JS_COUNTRY, keep=86400)
            cc = self.get("country") or ""
            if cc in COUNTRY_TOP:
                return "spotify:playlist:" + COUNTRY_TOP[cc]
            return CHARTS["Global"]
        return CHARTS.get(which, CHARTS["Global"])

    def radio(self, track_uri: str):
        self.want("radio:" + track_uri, JS_RADIO % json.dumps(track_uri), keep=3600)

    def search(self, q: str):
        self.want_only("search:" + q, JS_SEARCH_FAST % json.dumps(q), keep=600)
        self.want("searchfull:" + q, JS_SEARCH % json.dumps(q), keep=600)

    def lookup(self, q: str):
        """A search that is not a search box: kept a day, and never cancelled by the next one."""
        self.want("search:" + q, JS_SEARCH_FAST % json.dumps(q), keep=86400)

    def found(self, q: str) -> dict | None:
        """The fullest answer held for `q`."""
        return self.get("searchfull:" + q) or self.get("search:" + q)

    # ------------------------------------------------------------ named writes
    def like(self, uri: str, on: bool):
        self.act(("like:" if on else "unlike:") + uri,
                 JS_LIKE % ("add" if on else "remove", json.dumps(uri)))

    def follow(self, uri: str, on: bool):
        self.act(("follow:" if on else "unfollow:") + uri,
                 JS_FOLLOW % ("add" if on else "remove", json.dumps(uri)))

    def queue_add(self, uris: list[str], next_: bool = False):
        items = json.dumps([{"uri": u} for u in uris])
        self.act("queue_next" if next_ else "queue_add",
                 (JS_QUEUE_NEXT if next_ else JS_QUEUE_ADD) % items)

    def queue_clear(self):
        self.act("queue_clear", JS_QUEUE_CLEAR)

    def pl_add(self, pl: str, uris: list[str]):
        self.act("pl_add:" + pl, JS_PL_ADD % (json.dumps(pl), json.dumps(uris)))

    def pl_remove(self, pl: str, rows: list[dict]):
        self.act("pl_remove:" + pl, JS_PL_REMOVE % (json.dumps(pl), json.dumps(
            [{"uri": r.get("uri", ""), "uid": r.get("uid", "")} for r in rows])))

    def pl_move(self, pl: str, row: dict, before: dict | None):
        where = ({"before": {"uri": before.get("uri", ""), "uid": before.get("uid", "")}}
                 if before else {"after": "end"})
        self.act("pl_move:" + pl, JS_PL_MOVE % (json.dumps(pl), json.dumps(
            [{"uri": row.get("uri", ""), "uid": row.get("uid", "")}]), json.dumps(where)))

    def pl_create(self, name: str):
        self.act("pl_create", JS_PL_CREATE % json.dumps(name))

    def shuffle(self, on: bool):
        self.act("shuffle", JS_SHUFFLE % ("true" if on else "false"))


# Languages the window romanises; a lyric in one of them is "Romanised".
NON_LATIN = {"ja", "ko", "zh", "ru", "uk", "be", "bg", "sr", "mk", "el", "th", "ar", "he", "fa",
             "hi", "ta", "te", "bn", "ka", "hy", "yue", "cmn"}


class Kinds(QObject):
    """Track id -> 'w' word-by-word, 'l' line, 'r' romanised, 'n' none, from the source cache.

    Scanned on a thread once, then only the records that changed; kept in kinds.json.
    """

    done = pyqtSignal()

    def __init__(self, sources_dir, keep, quality) -> None:
        super().__init__()
        self.dir, self.keep, self.quality = sources_dir, keep, quality
        self.map: dict[str, str] = {}
        self._seen: dict[str, float] = {}
        self.busy = False
        self.again = False
        try:
            got = json.loads(self.keep.read_text(encoding="utf-8"))
            self._seen = {k: v[0] for k, v in got.items()}
            self.map = {k: v[1] for k, v in got.items() if v[1]}
        except Exception:                                    # noqa: BLE001
            pass

    def get(self, tid: str) -> str | None:
        return self.map.get(tid) if tid else None

    def note(self, tid: str, body) -> None:
        """The playing song's own lyric, as soon as it is on screen."""
        if tid and body is not None:
            k = self.kind_of(body)
            if k:
                self.map[tid] = k

    def kind_of(self, doc) -> str:
        try:
            q = self.quality(doc)
        except Exception:                                    # noqa: BLE001
            return ""
        if q == "none":
            return "n"
        lang = str((doc.get("Language") if isinstance(doc, dict) else "") or "").split("-")[0].lower()
        if lang in NON_LATIN:
            return "r"
        return "w" if q == "syllable" else "l"

    def scan(self) -> None:
        if self.busy:
            self.again = True        # a record landed mid-scan: look once more after it
            return
        self.busy = True
        threading.Thread(target=self._scan, daemon=True).start()

    def _scan(self) -> None:
        import os
        changed = False
        try:
            names = os.listdir(self.dir)
        except OSError:
            names = []
        for n in names:
            if not n.endswith(".json"):
                continue
            tid = n[:-5]
            p = self.dir / n
            try:
                mt = p.stat().st_mtime
            except OSError:
                continue
            if self._seen.get(tid) == mt:
                continue
            self._seen[tid] = mt
            changed = True
            try:
                rec = json.loads(p.read_text(encoding="utf-8"))
            except Exception:                                # noqa: BLE001
                continue
            doc = rec.get("doc") if isinstance(rec, dict) else None
            if isinstance(doc, dict):
                k = self.kind_of(doc)
                if k:
                    self.map[tid] = k
        if changed:
            try:
                self.keep.parent.mkdir(parents=True, exist_ok=True)
                self.keep.write_text(json.dumps({t: [m, self.map.get(t, "")]
                                                 for t, m in self._seen.items()}), encoding="utf-8")
            except OSError:
                pass
        self.busy = False
        self.done.emit()
        if self.again:
            self.again = False
            self.scan()
