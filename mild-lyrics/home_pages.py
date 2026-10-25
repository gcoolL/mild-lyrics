"""The pages of the home view: Home, Search, the library lists, Song, Album,
Artist, Playlist, the local files and Your stats. Mixed into home_page.Home.
"""
from __future__ import annotations

import os
import pathlib
import random
import re
import time

from PyQt6.QtCore import QPointF, QRectF, Qt, QUrl
from PyQt6.QtGui import QColor, QDesktopServices, QFont, QPainter, QPainterPath, QPen

import autoplay as AP
import noconsole
import library as LIB
import play_log as PLG
import stream_source as SS
import genius_roman as GR
import saves

W_ = QFont.Weight
INK = QColor(234, 234, 234)
DARK = QColor(20, 20, 25)
KIND_LABEL = {"w": "Word-by-word", "l": "Line", "r": "Romanised", "n": "No lyrics"}
MIX_PATIENCE = 8.0        # seconds a mix waits for the rest of its data before showing what it has
FILTERS = ["All", "Word-by-word", "Line", "No lyrics"]
LINE_LIFT = 0.5        # GR.score_song a lyric hit needs, on its line, to lead a search with its song
SEARCH_TABS = ["Top results", "Songs", "Artists", "Albums", "Lyrics", "YouTube"]
TITLES = {"queue": "Queue", "charts": "Charts", "recent": "Recently played", "songs": "Songs",
          "artists": "Artists", "albums": "Albums", "playlists": "Playlists", "lyrics": "Saved lyrics",
          "local": "On this computer", "stats": "Your stats", "liked": "Liked songs", "words": "Lyrics",
          "artist_top": "Top songs"}


def _ago(t: float) -> str:
    d = time.time() - t
    if d < 86400 and time.strftime("%d") == time.strftime("%d", time.localtime(t)):
        return "today"
    days = int(d // 86400) + 1
    if days <= 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    if days < 14:
        return "last week"
    if days < 60:
        return f"{days // 7} weeks ago"
    return time.strftime("%d %b %Y", time.localtime(t))


def join_names(names: list) -> str:
    """Artists as shown: "A", "A & B", "A, B & C"."""
    names = [n for n in names if n]
    return "" if not names else names[0] if len(names) == 1 else ", ".join(names[:-1]) + " & " + names[-1]


CREDIT = re.compile(r"\s*(?:,|&|\+|\bfeat\.?(?=\s)|\bft\.?(?=\s)|\bfeaturing\b|\bwith\b|\s[xX]\s)\s*")


def edition_words(title: str) -> set[str]:
    """What a title's brackets say about its edition: "(Deluxe Version)" -> {"deluxe"}."""
    said = " ".join(re.findall(r"[\(\[]([^)\]]*)[\)\]]", title or "")).lower()
    return set(re.findall(r"\w+", said)) - {"version", "edition", "the"}


def credit_names(text: str) -> list[str]:
    """A credit line cut at every joiner, for lookups only (it cuts "Simon & Garfunkel" too)."""
    return [n.strip() for n in CREDIT.split(text or "") if n and n.strip()]


def _row_of(r: dict) -> dict:
    """A play-log row as an item."""
    uri = r.get("uri") or ""
    return {"kind": "track" if uri else "song", "uri": uri, "name": r.get("title", ""),
            "sub": r.get("artist", ""), "art": r.get("art", ""), "ms": (r.get("len") or 0) * 1000,
            "t": r.get("t", 0), "player": r.get("player", ""), "album": r.get("album", ""),
            "artists": [{"name": a, "uri": ""} for a in PLG.artists_of(r.get("artist", ""))]}


class Pages:
    """Mixed into Home: every page, and the clicks that belong to them."""

    # ============================================================ dispatch
    def paint_page(self, p: QPainter, x: float, y: float, w: float, L: dict) -> float:
        fn = getattr(self, "page_" + self.page, None)
        if fn is None:
            fn = self.page_home
        return fn(p, x, y, w, L) - y

    def vis(self, r: QRectF) -> bool:
        return r.bottom() >= self.content.top() and r.top() <= self.content.bottom()

    # ========================================================== components
    def title(self, p, x, y, w, s: str, sub: str = "") -> float:
        S = self.S
        px = {"L": 34, "M": 30, "S": 26, "XS": 22}[self.bp]
        self.text(p, QRectF(x, y, w, S(px * 1.3)), s, px, W_.Black)
        y += S(px * 1.3)
        if sub:
            self.text(p, QRectF(x, y + S(4), w, S(22)), sub, 14.5, W_.Medium, self.a(0.55))
            y += S(28)
        return y

    def head(self, p, x, y, w, s: str, sub: str = "", link: str = "", link_kind: str = "",
             link_arg=None, px: float = 22) -> float:
        S = self.S
        lw = 0.0
        if link:
            fm = self.fm(14.5, W_.DemiBold)
            lw = fm.horizontalAdvance(link)
            lr = QRectF(x + w - lw, y + S(4), lw, S(24))
            self.text(p, lr, link, 14.5, W_.DemiBold, self.a(0.95 if self.hot(link_kind, link_arg) else 0.62),
                      elide=False)
            self.hit(link_kind, link_arg, lr)
        self.text(p, QRectF(x, y, w - lw - S(12), S(px * 1.35)), s, px, W_.Black)
        y += S(px * 1.35)
        if sub:
            self.text(p, QRectF(x, y, w - lw - S(12), S(20)), sub, 13.5, W_.Medium, self.a(0.55))
            y += S(22)
        return y + S(10)

    def tiles(self, p, x, y, w, items: list, cols: int, round_: bool = False, dismiss: bool = False,
              why: bool = False, lines: int = 2, px: float = 15.5, max_rows: int = 1000) -> float:
        S = self.S
        if not items:
            return y
        gap = S(16)
        cw = (w - gap * (cols - 1)) / cols
        th = cw + S(8) + S(22) + (S(20) if lines > 1 else 0) + (S(36) if why else 0)
        for i, it in enumerate(items[:cols * max_rows]):
            r, c = divmod(i, cols)
            tx, ty = x + c * (cw + gap), y + r * (th + S(14))
            card = QRectF(tx, ty, cw, th)
            if not self.vis(card):
                continue
            art = QRectF(tx, ty, cw, cw)
            hot = self.hot("item", it)
            if hot:
                self.rr(p, card.adjusted(-S(8), -S(8), S(8), S(4)), S(10), self.a(0.06))
            if it.get("uri") == "liked":
                self.liked_art(p, art, S(8))
            else:
                self.cover(p, art, it.get("art", ""), S(8), it.get("name", ""), round_=round_)
            self.hit("item", it, card)
            if hot and it.get("kind") in ("track", "local", "song"):
                pb = QRectF(art.right() - S(50), art.bottom() - S(50), S(40), S(40))
                self.rr(p, pb, S(20), INK)
                self.icon(p, "play", pb.adjusted(S(12), S(11), -S(10), -S(11)), DARK)
            if dismiss and (hot or self.hot("dismiss", it)):
                xb = QRectF(art.right() - S(34), art.y() + S(8), S(26), S(26))
                self.rr(p, xb, S(13), QColor(16, 16, 21, 190))
                self.icon(p, "x", xb.adjusted(S(7), S(7), -S(7), -S(7)))
                self.hit("dismiss", it, xb)
            cov = it.get("_cov")
            if cov is not None:
                self.cov_badge(p, art, cov, round_)
            ty2 = art.bottom() + S(8)
            self.text(p, QRectF(tx, ty2, cw, S(22)), it.get("name", ""), px, W_.Bold,
                      align=Qt.AlignmentFlag.AlignHCenter if round_ else Qt.AlignmentFlag.AlignLeft)
            if lines > 1:
                self.text(p, QRectF(tx, ty2 + S(22), cw, S(20)), self.who(it), 13.5, W_.Medium,
                          self.a(0.55),
                          align=Qt.AlignmentFlag.AlignHCenter if round_ else Qt.AlignmentFlag.AlignLeft)
            if why and it.get("why"):
                self.wrap(p, tx, ty2 + S(44), cw, it["why"], 12, W_.Medium, self.a(0.5), rows=2, lh=1.3)
        rows = (min(len(items), cols * max_rows) + cols - 1) // cols
        return y + rows * (th + S(14))

    def liked_art(self, p, r: QRectF, rad: float) -> None:
        from PyQt6.QtGui import QLinearGradient
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        g.setColorAt(0, QColor(106, 74, 176))
        g.setColorAt(1, QColor(150, 170, 220))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(r, rad, rad)
        p.setBrush(Qt.BrushStyle.NoBrush)
        side = r.width() * 0.3
        self.icon(p, "heartF", QRectF(r.center().x() - side / 2, r.center().y() - side / 2, side, side), INK)

    def cov_badge(self, p, art: QRectF, cov: float, round_: bool) -> None:
        S = self.S
        s = f"{int(round(cov * 100))}%"
        fm = self.fm(11.5, W_.Bold)
        w = fm.horizontalAdvance(s) + S(26)
        r = (QRectF(art.center().x() - w / 2, art.bottom() - S(28), w, S(20)) if round_
             else QRectF(art.x() + S(8), art.y() + S(8), w, S(20)))
        self.rr(p, r, S(6), QColor(16, 16, 21, 190))
        self.icon(p, "mic", QRectF(r.x() + S(6), r.center().y() - S(6), S(12), S(12)))
        self.text(p, QRectF(r.x() + S(20), r.y(), w - S(22), r.height()), s, 11.5, W_.Bold, elide=False)

    def table(self, p, x, y, w, rows: list, extra: list[str] = (), end: str = "TIME",
              ctx_uri: str = "", numbers: bool = True, art: bool = True, panel: bool = True,
              context: list | None = None) -> float:
        """The design's list: #, cover, title and artist, extra columns, lyrics, time, heart."""
        S = self.S
        rail = self.bp in ("S", "XS")
        num_w = S(32) if numbers else 0.0
        art_w = S(52) if art else 0.0
        ex = [] if rail else list(extra)
        lyr_w, end_w, heart_w = (0.0 if self.bp == "XS" else S(110)), S(64), S(36)
        rest = w - S(24) - num_w - art_w - lyr_w - end_w - heart_w
        title_w = rest * (1.6 / (1.6 + len(ex))) if ex else rest
        ex_w = (rest - title_w) / max(1, len(ex))
        top = y
        self.row_rects = []
        y += S(12)
        if context is None:
            context = [r for r in rows if "head" not in r]
        from home_page import Ctx
        context = Ctx(context)
        if panel:
            hx = x + S(12)
            cols_ = [("#" if numbers else "", num_w), ("", art_w), ("TITLE", title_w)]
            cols_ += [(e, ex_w) for e in ex] + [("LYRICS" if lyr_w else "", lyr_w), (end, end_w)]
            for label, cw in cols_:
                al = Qt.AlignmentFlag.AlignRight if label == end else Qt.AlignmentFlag.AlignLeft
                self.text(p, QRectF(hx, y, cw, S(24)), label, 13, W_.Bold, self.a(0.55), al)
                hx += cw
            y += S(32)
            p.fillRect(QRectF(x + S(12), y, w - S(24), 1), self.a(0.08))
            y += S(8)
        for i, r in enumerate(rows):
            if "head" in r:
                self.text(p, QRectF(x + S(12), y + S(8), w, S(24)), r["head"], 13, W_.Bold, self.a(0.62))
                y += S(36)
                continue
            rh = S(60) if art else S(44)
            rr = QRectF(x + S(8), y, w - S(16), rh)
            self.row_rects.append((r, rr))
            if self.vis(rr):
                hot = self.hot("item", r) or self.hot("heart", r)
                sel = r.get("_on") or (self.page == "search" and self.sel == r.get("_i", -9))
                if hot or sel:
                    self.rr(p, rr, S(8), self.a(0.08 if sel else 0.06))
                cx = rr.x() + S(4)
                if numbers:
                    n = r.get("_n", i + 1)
                    self.text(p, QRectF(cx, rr.y(), num_w, rh), str(n) if n != "" else "", 14.5, W_.DemiBold,
                              self.a(0.55))
                    cx += num_w
                if art:
                    self.cover(p, QRectF(cx, rr.y() + (rh - S(44)) / 2, S(44), S(44)), r.get("art", ""), S(6),
                               r.get("name", ""), label=False)
                    cx += art_w
                name = r.get("name", "")
                sub = self.who(r)
                if art and sub:
                    self.text(p, QRectF(cx, rr.y() + S(8), title_w - S(12), S(24)), name, 15.5, W_.Bold,
                              INK if not r.get("_on") else self.accent()[1])
                    self.text(p, QRectF(cx, rr.y() + S(31), title_w - S(12), S(20)), sub, 13.5, W_.Medium,
                              self.a(0.55))
                elif art:
                    self.text(p, QRectF(cx, rr.y(), title_w - S(12), rh), name, 15.5, W_.Bold,
                              INK if not r.get("_on") else self.accent()[1])
                else:
                    tw = self.text(p, QRectF(cx, rr.y(), title_w - S(12), rh), name, 15.5, W_.Bold)
                    if r.get("feat"):
                        self.text(p, QRectF(cx + tw + S(6), rr.y(), title_w - tw - S(18), rh), r["feat"], 14.5,
                                  W_.Medium, self.a(0.55))
                cx += title_w
                for k, e in enumerate(ex):
                    val = (r.get("_x") or [""] * len(ex))[k] if k < len(r.get("_x") or []) else ""
                    self.text(p, QRectF(cx, rr.y(), ex_w - S(12), rh), val, 14.5, W_.Medium, self.a(0.62))
                    cx += ex_w
                if lyr_w:
                    kl = KIND_LABEL.get(self.kind_of(r) or "", "")
                    if kl:
                        self.badge(p, cx, rr.center().y(), kl)
                    cx += lyr_w
                endv = r.get("_end")
                if endv is None:
                    endv = self.fmt(r.get("ms", 0))
                self.text(p, QRectF(cx, rr.y(), end_w, rh), endv, 14, W_.DemiBold, self.a(0.55),
                          Qt.AlignmentFlag.AlignRight)
                cx += end_w
                self.heart(p, QRectF(cx + S(12), rr.center().y() - S(8), S(16), S(16)), r)
                if ctx_uri and "_ctx" not in r:
                    r["_ctx"] = ctx_uri
                if context is not None:
                    r["_list"] = context
                self.hit("item", r, QRectF(rr.x(), rr.y(), rr.width() - heart_w, rr.height()))
            y += rh + S(2)
        y += S(12)
        if panel:
            self.rr(p, QRectF(x, top, w, y - top), S(12), self.a(0.04), self.a(0.10))
        return y

    def fmt(self, ms: float) -> str:
        s = int(round((ms or 0) / 1000))
        return f"{s // 60}:{s % 60:02d}" if s else ""

    def empty(self, p, x, y, w, s: str) -> float:
        S = self.S
        r = QRectF(x, y, w, S(90))
        self.rr(p, r, S(12), self.a(0.04), self.a(0.10))
        self.wrap(p, x + S(24), y + S(24), w - S(48), s, 15, W_.Medium, self.a(0.62), rows=2)
        return y + S(110)

    def filters_bar(self, p, x, y, w, page: str, opts: list[str], action: str = "",
                    action_kind: str = "") -> None:
        S = self.S
        right = x + w
        if action:
            b = self.button(p, right, y, action, "act", action_kind, right=True)
            right = b.x() - S(10)
        if opts and self.bp not in ("XS",):
            cur = self.filters.get(page, opts[0])
            self.seg(p, right, y, [(o, o) for o in opts], cur, "filter:" + page, right=True)

    def matches(self, r: dict, f: str) -> bool:
        if f in ("All", "", None):
            return True
        k = self.kind_of(r)
        if f == "Word-by-word":
            return k == "w"
        if f == "Line":
            return k in ("l", "r")
        if f == "No lyrics":
            return k == "n" or (k is None and r.get("kind") == "local")
        return True

    # ============================================================== Home
    def page_home(self, p, x, y, w, L) -> float:
        S, v = self.S, self.v
        y = self.title(p, x, y, w, "Home") + S(20)
        y = self.banner(p, x, y, w)
        if v.home_np == "card":
            y = self.np_card(p, x, y, w) + S(34)
        feed = self.spot.get("feed") or [] if self.online else []
        if v.home_shelf_picks:
            picks = self.top_picks(feed) if self.online else self.my_mixes()
            if picks:
                y = self.head(p, x, y, w, "Top picks for you")
                y = self.pick_cards(p, x, y, w, picks) + S(34)
        if v.home_shelf_made:
            mode = v.home_mode
            recs = self._recs.get(mode) or []
            title = {"history": "Made from your listening", "song": "Like this song",
                     "fresh": "Something new"}[mode]
            fm = self.fm(15, W_.DemiBold)
            segw = sum(fm.horizontalAdvance(lbl) + S(28) for _k, lbl in self.MODES()) + S(8)
            wide = w > segw + S(360)
            yh = y
            y = self.head(p, x, y, w - (segw if wide else 0), title, self._recs_note.get(mode, ""))
            self.seg(p, x + w, yh + S(4) if wide else y, self.MODES(), mode, "mode", right=True)
            if not wide:
                y += S(48)
            cols = {"L": 6, "M": 4, "S": 3, "XS": 2}[self.bp]
            if recs:
                y = self.tiles(p, x, y, w, recs, cols, dismiss=True, why=True, max_rows=1) + S(20)
            else:
                y = self.empty(p, x, y, w, self.recs_empty(mode)) + S(10)
        if v.home_shelf_recent:
            rec = self.recents(8)
            if rec:
                y = self.head(p, x, y, w, "Recently played", link="See all", link_kind="nav",
                              link_arg="recent")
                cols = {"L": 8, "M": 6, "S": 4, "XS": 3}[self.bp]
                y = self.tiles(p, x, y, w, rec, cols, px=14.5, max_rows=1) + S(20)
        both = [k for k in ("charts", "wbw") if getattr(v, "home_shelf_" + k)]
        if both:
            two = len(both) == 2 and self.bp in ("L", "M")
            cw = (w - S(24)) / 2 if two else w
            ys = []
            cx = x
            for k in both:
                if k == "charts":
                    which = self.shelf_chart()
                    rows = (self.chart_rows(which) or [])[:6]
                    ys.append(self.mini_list(p, cx, y, cw, "Top songs",
                                             f"{'Spotify' if self.online else 'Shazam' if which == 'Viral 50' else 'Deezer'} · {which}",
                                             rows,
                                             numbers=True, see="charts"))
                else:
                    rows = self.wbw_rows()[:6]
                    ys.append(self.mini_list(p, cx, y, cw, "Word-by-word in your library", "Saved TTMLs",
                                             rows, numbers=False, see="lyrics"))
                if two:
                    cx += cw + S(24)
                else:
                    y = ys[-1] + S(24)
            if two:
                y = max(ys) + S(24)
        return y

    def MODES(self):
        return [("history", "Your listening"), ("song", "This song"), ("fresh", "Something new")]

    def banner(self, p, x, y, w) -> float:
        """Says why the page is thin when the player or Spotify is not there -- as far as the
        main player (Settings ▸ Home) makes it worth saying: no Spotify banner without Spotify."""
        S, v = self.S, self.v
        main = v.home_main
        if getattr(self, "_banner_off", False):
            return y
        if main == "Spotify" and not self.online:
            t, n, ic = ("Playing in Mild Lyrics", "Spotify isn’t connected, so songs stream here and the "
                        "catalogue is Deezer’s. Your Spotify library and mixes come back when it is.", "plug")
            btns = [("How to connect", "port_help", False), ("I don’t use Spotify", "main_mild", False),
                    ("Got it", "banner_off", True)]
        elif main == "Another player" and not v.clock.tid and not self.player.active:
            t, n, ic = ("No player found", "Mild Lyrics follows browsers and other players through the "
                        "system’s media controls. Start one, or play your own files here.", "music")
            btns = [("Play your own files", "go_local", False), ("Choose players", "players", False),
                    ("Got it", "banner_off", True)]
        else:
            return y
        if w < S(900):                                      # narrow: the first and the last only
            btns = [btns[0], btns[-1]]
        r = QRectF(x, y, w, S(84))
        self.rr(p, r, S(12), self.a(0.08), self.a(0.16))
        c = QRectF(r.x() + S(18), r.center().y() - S(21), S(42), S(42))
        self.rr(p, c, S(21), self.a(0.10))
        self.icon(p, ic, c.adjusted(S(11), S(11), -S(11), -S(11)))
        bx = r.right() - S(18)
        for label, k, prim in reversed(btns):
            b = self.button(p, bx, r.center().y() - S(18), label, "act", k, style="primary" if prim else "soft",
                            h=36, px=15, right=True)
            bx = b.x() - S(8)
        tw = bx - c.right() - S(28)
        self.text(p, QRectF(c.right() + S(16), r.y() + S(14), tw, S(24)), t, 17, W_.Bold)
        self.wrap(p, c.right() + S(16), r.y() + S(40), tw, n, 13.5, W_.Medium, self.a(0.62), rows=2, lh=1.25)
        return r.bottom() + S(30)

    def top_picks(self, feed: list) -> list[dict]:
        out = []
        for sec in feed:
            t = (sec.get("title") or "")
            if not sec.get("picks") and not re.search(r"made for|top mixes|mix", t, re.I):
                continue
            for it in sec.get("items") or []:
                if it.get("kind") == "playlist":
                    lab = "Made for you" if "made for" in t.lower() else t
                    out.append(dict(it, label=lab))
                if len(out) >= 4:
                    return out
        return out

    # ------------------------------------------------------- your own mixes
    def taste(self) -> list[str]:
        """Your artists, most played first: the play log, then liked songs where it is thin."""
        look = int(self.v.home_look or 30)
        out = [a for a, _n in self.log.top_artists(max(look, 90), 8)]
        if len(out) < 4:
            from collections import Counter
            c = Counter((r.get("sub") or "").split(",")[0].strip() for r in self.liked_rows[:300])
            out += [a for a, _n in c.most_common(8) if a and a not in out]
        return out[:8]

    def artist_found(self, name: str) -> dict | None:
        got = self.dz.found(name)
        if got is None:
            self.dz.lookup(name)
            return None
        return SS.best_artist(got.get("artists") or [], name) or {}

    def my_mixes(self) -> list[dict]:
        """Top picks made here, from what you listen to: On Repeat, a mix per artist you
        play most, and Something New. Nothing from a catalogue that does not know you."""
        out = []
        reps = self.log.top_songs(30, 40)
        if len(reps) >= 5:
            first = reps[0][0]
            out.append({"uri": "mild:mix:repeat", "kind": "playlist", "name": "On Repeat",
                        "sub": "The songs you have played most this month", "art": first.get("art", ""),
                        "label": "From your plays", "colour": self.placeholder("On Repeat").darker(160).name()})
        tops = self.taste()
        for name in tops[:2 if out else 3]:
            a = self.artist_found(name) or {}
            rel = (self.dz.get("artist:" + a["uri"]) or {}).get("related", []) if a.get("uri") else []
            with_ = [name] + [r["name"] for r in rel[:2]]
            out.append({"uri": "mild:mix:artist:" + name, "kind": "playlist", "name": f"{name} Mix",
                        "sub": ", ".join(with_) + " and more", "art": a.get("art", ""),
                        "label": "Because you play " + name, "colour": self.placeholder(name).darker(170).name()})
            if a.get("uri") and not rel:
                self.dz.artist(a["uri"])
        if tops:
            out.append({"uri": "mild:mix:new", "kind": "playlist", "name": "Something New",
                        "sub": "Artists near " + ", ".join(tops[:2]) + " you have not played", "art": "",
                        "label": "New to you", "colour": self.placeholder("new").darker(170).name()})
        return out[:4]

    def mix_data(self, uri: str) -> dict | None:
        """A mix's songs, put together from the play log and the catalogue; None while it is."""
        key = uri.split("mild:mix:", 1)[-1]
        held = self._mixes.get(key)
        if held is not None:
            return held
        heard = {AP.norm(r.get("title", "")) for r in self.log.recent(30)}
        # The same order every time the page is drawn (and all day): an unseeded pick
        # reshuffled the list on every frame while it was being put together.
        rnd = lambda: random.Random(f"{key}|{time.strftime('%Y-%m-%d')}")
        liked = {AP.title_of(x) + "|" + AP.artist_of(x) for x in self.liked_rows}
        tops = self.log.top_artists(int(self.v.home_look or 30), 20)
        most = max([n for _a, n in tops] or [1])
        fav = {AP.norm(a): n / most for a, n in tops}
        banned = self.banned_keys()
        mine = lambda r: dict(_row_of(r), kind="track")
        if key == "repeat":
            tracks = [mine(r) for r, _n in self.log.top_songs(30, 50)]
            got = {"name": "On Repeat", "sub": "The songs you have played most this month", "tracks": tracks}
        elif key.startswith("artist:"):
            name = key[7:]
            a = self.artist_found(name)
            if a is None:
                return None
            radio = self.dz.get("radio:" + a["uri"]) if a.get("uri") else {"tracks": []}
            if radio is None:
                self.dz.radio(a["uri"])
                return None
            own = [mine(r) for r, _n in self.log.top_songs(365, 200)
                   if AP.norm((r.get("artist") or "").split(",")[0]) == AP.norm(name)][:12]
            fresh = AP.pick([dict(t, kind="track") for t in radio.get("tracks") or []], 30, name,
                            {AP.title_of(t) for t in own}, set(), banned, liked, fav, wbw=self.kind_of,
                            prefer_wbw=bool(self.v.home_prefer_wbw), rnd=rnd())
            tracks, i, j = [], 0, 0
            while i < len(own) or j < len(fresh):          # one of yours, then two like them
                if i < len(own):
                    tracks.append(own[i]); i += 1
                tracks += fresh[j:j + 2]; j += 2
            got = {"name": f"{name} Mix", "sub": f"Your songs by {name}, and ones like them", "tracks": tracks}
        elif key == "new":
            heard_a = self.log.heard_artists() | {AP.artist_of(x) for x in self.liked_rows}
            cands, waiting = [], False
            for name in self.taste()[:4]:
                a = self.artist_found(name)
                if a is None:
                    waiting = True
                    continue
                if not a.get("uri"):
                    continue
                ag = self.dz.get("artist:" + a["uri"])
                if ag is None:
                    self.dz.artist(a["uri"]); waiting = True
                    continue
                for ra in ag.get("related") or []:
                    if AP.norm(ra["name"]) in heard_a:
                        continue
                    rg = self.dz.get("artist:" + ra["uri"])
                    if rg is None:
                        self.dz.artist(ra["uri"]); waiting = True
                        continue
                    cands += [dict(t, kind="track", why=f"Near {name}") for t in (rg.get("tracks") or [])[:3]]
            # Shown once it is all in (or after MIX_PATIENCE with what there is), never
            # half-built: a list that grew while you looked at it moved under the mouse.
            if key not in self._mix_asked:
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(int(MIX_PATIENCE * 1000) + 100, self.v.update)
            first = self._mix_asked.setdefault(key, time.monotonic())
            if waiting and time.monotonic() - first < MIX_PATIENCE:
                return None
            tracks = AP.pick(cands, 30, "", heard, set(), banned, liked, fav, wbw=self.kind_of,
                             prefer_wbw=bool(self.v.home_prefer_wbw), rnd=rnd())
            got = {"name": "Something New", "sub": "Artists near yours that you have not played yet", "tracks": tracks}
        else:
            return None
        got = dict(got, uri=uri, mine=False, owner="Mild Lyrics", total=len(got["tracks"]),
                   art=(got["tracks"][0].get("art", "") if got["tracks"] else ""), mix=True)
        self._mixes[key] = got
        return got

    def pick_cards(self, p, x, y, w, picks: list) -> float:
        S = self.S
        cols = {"L": 4, "M": 3, "S": 2, "XS": 1}[self.bp]
        gap = S(20)
        cw = (w - gap * (cols - 1)) / cols
        bot = S(72)
        for i, it in enumerate(picks[:cols]):
            cx = x + i * (cw + gap)
            self.text(p, QRectF(cx, y, cw, S(20)), it.get("label", ""), 13.5, W_.Medium, self.a(0.62))
            r = QRectF(cx, y + S(26), cw, cw + bot)
            col = QColor(it.get("colour") or "#3a2a3a")
            path = QPainterPath()
            path.addRoundedRect(r, S(10), S(10))
            p.save()
            p.setClipPath(path, Qt.ClipOperation.IntersectClip)
            self.cover(p, QRectF(r.x(), r.y(), cw, cw), it.get("art", ""), 0, it.get("name", ""))
            band = QRectF(r.x(), r.y() + cw, r.width(), bot)
            p.fillRect(band, QColor(col.red(), col.green(), col.blue(), 240))
            self.wrap(p, band.x() + S(16), band.y() + S(12), band.width() - S(32), it.get("sub", ""), 13.5,
                      W_.Medium, self.a(0.92), rows=2, lh=1.3)
            p.restore()
            p.setPen(QPen(self.a(0.16 if self.hot("item", it) else 0.08), 1))
            p.drawRoundedRect(r, S(10), S(10))
            self.hit("item", it, r)
        return y + S(26) + cw + bot

    def np_card(self, p, x, y, w) -> float:
        """The now-playing card with three lines of the lyric and what is up next."""
        S, v = self.S, self.v
        it = self.np_item()
        two = self.bp in ("L", "M")
        h = S(316 if self.bp == "L" else 290)
        r = QRectF(x, y, w, h)
        self.rr(p, r, S(14), self.a(0.06), self.a(0.10))
        lw = w * 0.56 if two else w
        side = h - S(56)
        art = QRectF(r.x() + S(28), r.y() + S(28), side, side)
        if v.art_full is not None and not self.player.active:
            path = QPainterPath()
            path.addRoundedRect(art, S(10), S(10))
            p.save()
            p.setClipPath(path, Qt.ClipOperation.IntersectClip)
            p.drawPixmap(art, v.art_full, QRectF(v.art_full.rect()))
            p.restore()
        else:
            self.cover(p, art, it["art"], S(10), it["name"])
        tx = art.right() + S(28)
        tw = r.x() + lw - tx - S(24)
        ty = art.y()
        who = self.follow_label().replace("Following ", "").replace("Pinned to ", "").upper()
        self.text(p, QRectF(tx, ty, tw, S(20)), f"NOW PLAYING · {who}", 13, W_.Bold, self.a(0.62))
        ty += S(22)
        big = 40 if self.bp == "L" else 32
        name = it["name"] or "Nothing playing"
        while big > 22 and self.fm(big, W_.Black).horizontalAdvance(name) > tw:
            big -= 2
        self.text(p, QRectF(tx, ty, tw, S(big * 1.25)), name, big, W_.Black)
        ty += S(big * 1.25)
        self.text(p, QRectF(tx, ty, tw, S(22)), self.who(it), 15, W_.Medium, self.a(0.62))
        ty += S(34)
        cur, nxt, _f = self.mini_lines()
        prev = ""
        lines = v.lines or []
        if lines and cur:
            for i, ln in enumerate(lines):
                if ln.get("text") == cur and i:
                    prev = lines[i - 1].get("text", "")
                    break
        _acc, light = self.accent()
        self.text(p, QRectF(tx, ty, tw, S(24)), prev, 15, W_.Bold, self.a(0.3))
        self.text(p, QRectF(tx, ty + S(24), tw, S(32)), cur, 22, W_.Black, light)
        self.text(p, QRectF(tx, ty + S(58), tw, S(24)), nxt, 15, W_.Bold, self.a(0.3))
        by = art.bottom() - S(40)
        b = self.button(p, tx, by, "Open lyrics", "lyrics", icon="mic", style="accent")
        if it.get("uri"):
            self.button(p, b.right() + S(8), by, "This song", "act", "this_song")
        if two:
            ux = r.x() + lw
            p.fillRect(QRectF(ux, r.y() + S(16), 1, h - S(32)), self.a(0.08))
            lx, rx = ux + S(24), r.right() - S(24)
            uw = rx - lx
            self.text(p, QRectF(lx, r.y() + S(24), uw, S(28)), "Up next", 19, W_.Black)
            fq = self.fm(14, W_.DemiBold)
            qr = QRectF(rx - fq.horizontalAdvance("Queue"), r.y() + S(24), fq.horizontalAdvance("Queue"), S(28))
            self.text(p, qr, "Queue", 14, W_.DemiBold, self.a(0.95 if self.hot("nav", "queue") else 0.62), elide=False)
            self.hit("nav", "queue", qr)
            rows = self.upnext()
            fit = max(1, int((r.bottom() - S(16) - (r.y() + S(62))) // S(54)))
            yy = r.y() + S(62)
            for q in rows[:fit]:
                rr = QRectF(lx - S(8), yy, uw + S(16), S(52))
                if self.hot("item", q):
                    self.rr(p, rr, S(8), self.a(0.06))
                self.cover(p, QRectF(lx, rr.y() + S(6), S(40), S(40)), q.get("art", ""), S(6),
                           q.get("name", ""), label=False)
                kl = KIND_LABEL.get(self.kind_of(q) or "", "")
                bw = (self.fm(12.5, W_.DemiBold).horizontalAdvance(kl) + S(26)) if kl else 0
                tw_ = uw - S(52) - bw
                self.text(p, QRectF(lx + S(52), rr.y() + S(5), tw_, S(22)), q.get("name", ""), 15, W_.Bold)
                self.text(p, QRectF(lx + S(52), rr.y() + S(27), tw_, S(20)), self.who(q), 13, W_.Medium,
                          self.a(0.55))
                if kl:
                    self.badge(p, rx, rr.center().y(), kl, right=True)
                self.hit("item", q, rr)
                yy += S(54)
            if len(rows) > fit:
                more = f"+{len(rows) - fit} more"
                mr = QRectF(lx, yy, uw, S(22))
                self.text(p, mr, more, 13.5, W_.DemiBold, self.a(0.55))
                self.hit("nav", "queue", mr)
            if not rows:
                self.text(p, QRectF(lx, yy, uw, S(24)), "Nothing queued", 14, W_.Medium, self.a(0.55))
        return r.bottom()

    def upnext(self) -> list[dict]:
        if self.player.active:
            q = self.player.queue[self.player.idx + 1:]
            return [self.local_item(t) for t in q]
        if time.monotonic() - getattr(self.v, "queue_at", 0) > 20:
            self.v.fetcher.request_queue()
            self.v.queue_at = time.monotonic()
        return [dict(r, kind="track", name=r.get("name", "")) for r in (self.v.queue_items or [])]

    def mini_list(self, p, x, y, w, title: str, note: str, rows: list, numbers: bool, see: str) -> float:
        S = self.S
        top = y
        y += S(18)
        self.text(p, QRectF(x + S(20), y, w - S(40), S(28)), title, 19, W_.Black)
        self.text(p, QRectF(x + S(20), y, w - S(40), S(28)), note, 13.5, W_.Medium, self.a(0.55),
                  Qt.AlignmentFlag.AlignRight)
        y += S(40)
        if not rows:
            y += self.wrap(p, x + S(20), y, w - S(40), "Nothing here yet." if see != "lyrics" else
                           "Word-by-word TTMLs you save or make land here.", 14, W_.Medium, self.a(0.55))
        for i, r in enumerate(rows):
            rr = QRectF(x + S(10), y, w - S(20), S(52))
            if not self.vis(rr):
                y += S(54)
                continue
            if self.hot("item", r):
                self.rr(p, rr, S(8), self.a(0.06))
            cx = rr.x() + S(8)
            if numbers:
                self.text(p, QRectF(cx, rr.y(), S(24), rr.height()), str(i + 1), 14.5, W_.DemiBold, self.a(0.55))
                cx += S(28)
            self.cover(p, QRectF(cx, rr.y() + S(6), S(40), S(40)), r.get("art", ""), S(6), r.get("name", ""),
                       label=False)
            cx += S(52)
            chip = r.get("_chip") or KIND_LABEL.get(self.kind_of(r) or "", "")
            cw_ = self.fm(12.5, W_.DemiBold).horizontalAdvance(chip) + S(30) if chip else 0
            self.text(p, QRectF(cx, rr.y() + S(5), rr.right() - cx - cw_, S(22)), r.get("name", ""), 15, W_.Bold)
            self.text(p, QRectF(cx, rr.y() + S(27), rr.right() - cx - cw_, S(20)), self.who(r), 13,
                      W_.Medium, self.a(0.55))
            if chip:
                self.badge(p, rr.right() - S(8), rr.center().y(), chip, right=True)
            self.hit("item", r, rr)
            y += S(54)
        y += S(14)
        self.rr(p, QRectF(x, top, w, y - top), S(14), self.a(0.04), self.a(0.10))
        return y

    # ------------------------------------------------------- suggestions
    def recs_empty(self, mode: str) -> str:
        if mode == "history" and not self.log.load():
            if self.online and not (self.v.discover or {}).get("songs") and not self.v.discover_at:
                return "Looking for songs…"
            return "Nothing logged yet. Play a few songs and this fills in from what you listen to."
        return "Looking for songs…"

    def build_recs(self) -> None:
        """Suggestions for the current mode, from the play log and the catalogue's artist pages
        (Spotify's, else Deezer's)."""
        mode = self.v.home_mode
        now = time.monotonic()
        if now - self._recs_at.get(mode, -1e9) < 30 and self._recs.get(mode):
            return
        self._recs_at[mode] = now
        v, spot = self.v, self.spot
        look = int(v.home_look or 30)
        hidden = self.hidden()
        hidden_a = self.hidden_artists()
        skips = self.log.skipped() if v.home_drop_skips else set()
        heard = self.log.heard()
        heard_a = self.log.heard_artists()
        recent = {(r.get("title", "").lower() + "|" + r.get("artist", "").lower())
                  for r in self.log.since(3)}
        meta = v.clock.meta or {}
        playing = (AP.norm(meta.get("title", "")), AP.norm((meta.get("artist") or "").split(",")[0]))
        out: list[dict] = []
        seen = set()

        def add(t: dict, why: str) -> None:
            key = (t.get("name", "").lower() + "|" + t.get("sub", "").lower())
            if (key in seen or key in hidden or key in skips or not t.get("uri") or AP.artist_of(t) in hidden_a
                    or t.get("uri") == f"spotify:track:{v.clock.tid}"
                    or (AP.norm(t.get("name", "")), AP.artist_of(t)) == playing):
                return
            if not v.home_unplayed and key not in heard:
                return
            seen.add(key)
            out.append(dict(t, kind="track", why=why))

        def artist_rows(uri: str) -> dict | None:
            src = self.src(uri)
            got = src.get("artist:" + uri)
            if got is None:
                src.artist(uri)
            return got

        note = ""
        if mode == "history":
            tops = self.log.top_artists(look, 5)
            if tops:
                note = (f"From {look} days of plays and skips. Most played: "
                        + ", ".join(a for a, _n in tops[:3]))
                uris = self.artist_uris()
                for name, n in tops:
                    uri = self.artist_uri(name, uris)
                    got = artist_rows(uri) if uri else None
                    days = self.log.days_played(name, 14)
                    for t in (got or {}).get("tracks", [])[:6]:
                        k = t["name"].lower() + "|" + t["sub"].lower()
                        if k in recent:
                            continue
                        pl = self.log.plays_of(t["name"], name, look)
                        why = (f"{name} · {n} plays in {look} days" if not pl else
                               f"{name} · played on {days} of the last 14 days" if days > 2 else
                               f"{name} · {pl} plays, no skips")
                        if k not in heard:
                            why = f"{name} · not played yet"
                        add(t, why)
                        if sum(1 for o in out if o["sub"].startswith(name)) >= 2:
                            break
                for name, _n in tops[:3]:
                    uri = self.artist_uri(name, uris)
                    got = self.src(uri).get("artist:" + uri) if uri else None
                    for rel in (got or {}).get("related", [])[:2]:
                        rg = artist_rows(rel["uri"])
                        for t in (rg or {}).get("tracks", [])[:1]:
                            add(t, f"Spotify’s pick near {name}" if self.online else f"Near {name}")
            else:
                d = v.discover or {}
                seed = d.get("seed") or ""
                note = (f"From Spotify’s play history, while this computer’s own log fills up"
                        + (f" · because you played {seed}" if seed else ""))
                for t in d.get("songs") or []:
                    add(dict(t, artists=[]), f"Because you played {seed}" if seed else "From your history")
        elif mode == "song":
            title = meta.get("title", "this song")
            note = f"Like {title} — from the playing song only"
            sugg = v.suggest if self.online else None
            if not sugg:
                # without Spotify: the credited artists' own pages in the catalogue in use
                names = [a for a in meta.get("artists") or [] if a] or credit_names(meta.get("artist") or "")
                uris = self.artist_uris()
                pages = [artist_rows(u) for u in (self.artist_uri(n, uris) for n in names[:3]) if u]
                sugg = {"top": [t for g in pages for t in (g or {}).get("tracks", [])[:5]],
                        "related": [r for g in pages for r in (g or {}).get("related", [])[:4]][:4]}
            for t in sugg.get("top") or []:
                add(dict(t, artists=[]) if sugg is v.suggest else t, "Same artist")
            for rel in (sugg.get("related") or [])[:4]:
                rg = artist_rows(rel["uri"])
                for t in (rg or {}).get("tracks", [])[:2]:
                    add(t, f"Similar to {title}")
        else:
            note = "Artists you have not played, near your taste"
            tops = self.log.top_artists(look, 4) or []
            uris = self.artist_uris()
            for name, _n in tops:
                uri = self.artist_uri(name, uris)
                got = artist_rows(uri) if uri else None
                for rel in (got or {}).get("related", [])[:4]:
                    if rel["name"].lower() in heard_a:
                        continue
                    rg = artist_rows(rel["uri"])
                    for t in (rg or {}).get("tracks", [])[:1]:
                        add(t, f"New to you · near {name}")
            if not tops:
                for t in (v.discover or {}).get("songs") or []:
                    if t.get("sub", "").lower() not in heard_a:
                        add(dict(t, artists=[]), "New to you")
        if v.home_prefer_wbw:
            out.sort(key=lambda t: 0 if self.kind_of(t) in ("w", None) else 1)
        self._recs[mode] = out[:12]
        self._recs_note[mode] = note
        if not out:
            self._recs_at[mode] = now - 25

    def artist_uris(self) -> dict[str, str]:
        """Artist name -> Spotify uri, from what is known: liked songs, the feed, Spotify's history."""
        out = {}
        for r in self.liked_rows:
            for a in r.get("artists") or []:
                if a.get("uri"):
                    out.setdefault(a["name"].lower(), a["uri"])
        for a in self.spot.get("artists") or []:
            out.setdefault(a.get("name", "").lower(), a.get("uri", ""))
        return out

    def artist_face(self, name: str, known: dict) -> tuple[str, str]:
        """(uri, picture) for an artist known only by name: Deezer's picture (see SS.Faces);
        with Spotify up, its page where the uri is `known`, else found by name on a click."""
        f = self.faces.get(name) or {}
        uri = (known.get(name.lower(), "") if self.online else f.get("uri", ""))
        return uri, f.get("art", "")

    def artist_uri(self, name: str, known: dict) -> str:
        """An artist's uri by name: from what is known, else the catalogue's search (asked once)."""
        uri = known.get(name.lower())
        if uri and (self.online or not uri.startswith("spotify:")):     # Spotify's pages need Spotify
            return uri
        got = self.cat.found(name)
        if got is None:
            self.cat.lookup(name)
            return ""
        a = next((a for a in got.get("artists") or [] if a.get("name", "").lower() == name.lower()), None)
        return a["uri"] if a else ""

    def recents(self, n: int) -> list[dict]:
        rows, seen = [], set()
        for r in self.log.recent(80):
            k = (r.get("title", "") + "|" + r.get("artist", "")).lower()
            if k in seen:
                continue
            seen.add(k)
            rows.append(_row_of(r))
            if len(rows) >= n:
                return rows
        for t in self.v.recents_tracks or []:
            k = (t.get("name", "") + "|" + t.get("sub", "")).lower()
            if k in seen:
                continue
            seen.add(k)
            rows.append(dict(t, kind="track", artists=[]))
            if len(rows) >= n:
                break
        return rows

    def chart_rows(self, which: str) -> list[dict] | None:
        cat = self.cat
        got = cat.get("pl:" + cat.chart_uri(which))
        if got is None:
            cat.chart(which)
            return None
        uri = got.get("uri", "")
        return [dict(t, kind="track", _ctx=uri) for t in got.get("tracks") or []]

    def wbw_rows(self) -> list[dict]:
        return [dict(r, _chip=r["_x"][0]) for r in self.lyric_files() if r.get("_k") == "w"]

    # =============================================================== Search
    def search_changed(self) -> None:
        self.sel = -1
        self._q_timer.start()
        self.v.wind_genius(self.v.bq_field.text)

    def run_search(self) -> None:
        q = self.v.bq_field.text.strip()
        if len(q) >= 2:
            self.search_src(q).search(q)

    def search_key(self, ev) -> bool:
        v = self.v
        k = ev.key()
        songs = self._s_songs if hasattr(self, "_s_songs") else []
        if k == Qt.Key.Key_Down:
            self.sel = min(len(songs) - 1, self.sel + 1)
            return True
        if k == Qt.Key.Key_Up:
            self.sel = max(-1, self.sel - 1)
            return True
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            q = v.bq_field.text.strip()
            if q:
                self.remember_q(q)
            if 0 <= self.sel < len(songs):
                self.play(songs[self.sel])
            elif getattr(self, "_s_top", None):
                self.open_item(self._s_top)
            return True
        used, changed = v.field_key(v.bq_field, ev)
        if used:
            if changed:
                self.search_changed()
            return True
        return False

    def remember_q(self, q: str) -> None:
        was = [x for x in str(self.v.home_recent_q or "").split("\n") if x and x.lower() != q.lower()]
        self.v.home_recent_q = "\n".join([q] + was[:7])

    def page_search(self, p, x, y, w, L) -> float:
        S, v = self.S, self.v
        fld = v.bq_field
        box = QRectF(x, y, w, S(52))
        self.rr(p, box, S(12), self.a(0.08), self.a(0.14))
        self.icon(p, "search", QRectF(box.x() + S(16), box.center().y() - S(10), S(20), S(20)), self.a(0.62))
        f = self.font(19, W_.DemiBold)
        p.setFont(f)
        p.setPen(INK)
        from PyQt6.QtGui import QFontMetricsF
        v._paint_field(p, fld, QRectF(box.x() + S(48), box.y() + S(8), box.width() - S(100), box.height() - S(16)),
                       QFontMetricsF(f), "Songs, artists, albums or a line you remember")
        q = fld.text.strip()
        if q:
            xb = QRectF(box.right() - S(42), box.center().y() - S(14), S(28), S(28))
            self.rr(p, xb, S(14), self.a(0.18 if self.hot("act", "clear_q") else 0.10))
            self.icon(p, "x", xb.adjusted(S(8), S(8), -S(8), -S(8)))
            self.hit("act", "clear_q", xb)
        y = box.bottom() + S(16)
        if not q:
            return self.search_empty(p, x, y, w)
        src = self.search_src(q)
        got = src.found(q) or {}
        if not got and len(q) >= 2 and src.age("search:" + q) > 600 and not self._q_timer.isActive():
            self._q_timer.start()
        songs = [dict(t, kind="track") for t in got.get("tracks") or []]
        if not songs and src is not self.links:
            songs = self.own_matches(q)
        artists = got.get("artists") or []
        albums = got.get("albums") or []
        lyr = self.lyric_hits(q)
        lifted = self.line_song(q, songs, lyr, src)
        if lifted is not None:
            songs = [lifted] + [s_ for s_ in songs if s_ is not lifted and s_.get("uri") != lifted.get("uri")]
        self._s_songs = songs
        tab = self.search_tab
        self.seg(p, x, y, [(t, t) for t in SEARCH_TABS], tab, "stab", px=14.5)
        y += S(56)
        if not (songs or artists or albums or lyr):
            busy = len(q) >= 2 and ("search:" + q) not in src.data
            say = ("Reading the link…" if busy and src is self.links else "Searching…" if busy else
                   f"Couldn’t read that link: {got['error']}" if got.get("error") else f"Nothing found for “{q}”")
            self.text(p, QRectF(x, y, w, S(30)), say, 17, W_.Bold, self.a(0.62))
            return y + S(40)
        top = lifted or got.get("top_item")
        if top is None and got.get("top"):
            top = next((a for a in artists + albums + songs if a.get("uri") == got["top"]), None)
        top = top or (artists[0] if artists and artists[0]["name"].lower().startswith(q.lower()) else
                      songs[0] if songs else None)
        if top and top.get("kind") == "artist" and songs and not self.sings(top, songs[:10]):
            top = songs[0]                  # an artist merely named like the song, singing none of these
        self._s_top = top
        for i, s_ in enumerate(songs):
            s_["_i"] = i
        if tab == "Top results":
            two = self.bp in ("L", "M")
            if top is not None:
                lw = w * 0.56 if two else w
                yh = self.head(p, x, y, lw, "Top result")
                card = QRectF(x, yh, lw, S(276))             # 16 between the kind line and Play
                self.rr(p, card, S(14), self.a(0.10 if self.hot("item", top) else 0.06), self.a(0.10))
                rnd = top.get("kind") == "artist"
                self.cover(p, QRectF(card.x() + S(22), card.y() + S(22), S(112), S(112)), top.get("art", ""),
                           S(8), top.get("name", ""), round_=rnd)
                self.text(p, QRectF(card.x() + S(22), card.y() + S(146), lw - S(44), S(40)), top.get("name", ""),
                          30, W_.Black)
                kind = {"artist": "Artist", "album": "Album", "track": "Song", "playlist": "Playlist"}.get(
                    top.get("kind"), "")
                self.text(p, QRectF(card.x() + S(22), card.y() + S(186), lw - S(44), S(22)),
                          kind + (f" · {top['sub']}" if top.get("sub") and kind != "Artist" else ""), 14.5,
                          W_.Medium, self.a(0.62))
                self.hit("item", top, card)
                self.button(p, card.x() + S(22), card.bottom() - S(52), "Play", "play_item", top, icon="play",
                            style="primary")
                if two:
                    sx = x + lw + S(24)
                    sw = w - lw - S(24)
                    yy = self.head(p, sx, y, sw, "Songs", link="See all", link_kind="stab", link_arg="Songs")
                    self.table(p, sx, yy - S(12), sw, songs[:4], numbers=False, panel=False, context=[])
                    y = max(card.bottom(), yy + S(4 * 62)) + S(30)
                else:
                    y = card.bottom() + S(30)
                    y = self.head(p, x, y, w, "Songs", link="See all", link_kind="stab", link_arg="Songs")
                    y = self.table(p, x, y, w, songs[:4], numbers=False, panel=False, context=[]) + S(20)
            cols = {"L": 6, "M": 4, "S": 3, "XS": 2}[self.bp]
            if artists:
                y = self.head(p, x, y, w, "Artists", link="See all", link_kind="stab", link_arg="Artists")
                y = self.tiles(p, x, y, w, artists, cols, round_=True, lines=1, max_rows=1) + S(20)
            if albums:
                y = self.head(p, x, y, w, "Albums", link="See all", link_kind="stab", link_arg="Albums")
                y = self.tiles(p, x, y, w, albums, cols, max_rows=1) + S(20)
            if lyr:
                y = self.head(p, x, y, w, "In lyrics", link="See all", link_kind="stab", link_arg="Lyrics")
                y = self.lyric_list(p, x, y, w, lyr[:3])
            return y
        if tab == "Songs":
            return self.table(p, x, y, w, songs, extra=["ALBUM"] if songs else [],
                              numbers=True, context=[]) if songs else self.empty(p, x, y, w, "No songs.")
        if tab == "YouTube":
            yt = self.yt.found(q)
            if yt is None:
                if not self.yt.age("search:" + q) < 1e8:
                    self.yt.search(q)
                return self.empty(p, x, y, w, "Asking YouTube…")
            rows = [dict(t, _x=[f"{t['plays']:,} views" if t.get("plays") else ""]) for t in yt.get("tracks") or []]
            if not rows:
                return self.empty(p, x, y, w, "Nothing on YouTube for that.")
            self.text(p, QRectF(x, y - S(8), w, S(20)), "Anything uploaded, played here in Mild Lyrics: covers, "
                      "remixes, live takes", 13, W_.Medium, self.a(0.55))
            return self.table(p, x, y + S(16), w, rows, extra=["VIEWS"], numbers=True, context=[])
        cols = {"L": 6, "M": 4, "S": 3, "XS": 2}[self.bp]
        if tab == "Artists":
            return self.tiles(p, x, y, w, artists, cols, round_=True, lines=1)
        if tab == "Albums":
            return self.tiles(p, x, y, w, albums, cols)
        return self.lyric_list(p, x, y, w, lyr) if lyr else self.empty(
            p, x, y, w, "No saved lyric has that line. Genius is asked once you stop typing.")

    @staticmethod
    def sings(artist: dict, songs: list[dict]) -> bool:
        """Whether any of `songs` credits `artist`, by uri or by name."""
        uri, name = artist.get("uri", ""), SS.norm(artist.get("name", ""))
        for s in songs:
            cred = s.get("artists") or [{"name": n} for n in str(s.get("sub", "")).split(", ")]
            if any((uri and a.get("uri") == uri) or SS.norm(a.get("name", "")) == name for a in cred):
                return True
        return False

    def own_matches(self, q: str) -> list[dict]:
        """Songs already here that answer `q`, shown while the catalogue is asked."""
        n = q.lower()
        out, seen = [], set()
        pool = list(self.liked_rows) + [_row_of(r) for r in self.log.recent(300)] + \
            [self.local_item(t) for t in self.lib.tracks]
        for r in pool:
            name, sub = r.get("name", ""), r.get("sub", "")
            k = (name + "|" + sub).lower()
            if k in seen or (n not in name.lower() and n not in sub.lower()):
                continue
            seen.add(k)
            out.append(r)
            if len(out) >= 8:
                break
        return out

    def search_empty(self, p, x, y, w) -> float:
        S = self.S
        qs = [x_ for x_ in str(self.v.home_recent_q or "").split("\n") if x_]
        if qs:
            y = self.head(p, x, y, w, "Recent searches")
            cx = x
            for q in qs[:8]:
                fm = self.fm(15, W_.DemiBold)
                bw = fm.horizontalAdvance(q) + S(32)
                if cx + bw > x + w:
                    break
                r = QRectF(cx, y, bw, S(36))
                self.rr(p, r, S(18), self.a(0.14 if self.hot("recent_q", q) else 0.08))
                self.text(p, r, q, 15, W_.DemiBold, INK, Qt.AlignmentFlag.AlignHCenter, elide=False)
                self.hit("recent_q", q, r)
                cx += bw + S(8)
            y += S(60)
        y = self.head(p, x, y, w, "Ways to search")
        tips = [("Search a line", "Type words you remember; saved lyrics and Genius are searched too", "lovely"),
                ("Only word-by-word", "The Songs tab marks which have line timing only", ""),
                ("Artists and albums", "Mixed into Top results, or a tab each", "")]
        cols = 3 if self.bp in ("L", "M") else 1
        cw = (w - S(16) * (cols - 1)) / cols
        fm = self.fm(13.5, W_.Medium)
        lines = max(1, max(int(fm.horizontalAdvance(s_) // max(1.0, cw - S(40))) + 1 for _t, s_, _q in tips))
        ch = S(62) + lines * fm.height() * 1.35
        for i, (t, s_, q) in enumerate(tips):
            r, c = divmod(i, cols)
            card = QRectF(x + c * (cw + S(16)), y + r * (ch + S(14)), cw, ch)
            self.rr(p, card, S(12), self.a(0.10 if self.hot("recent_q", q or t) else 0.06), self.a(0.10))
            self.text(p, QRectF(card.x() + S(18), card.y() + S(16), cw - S(36), S(24)), t, 16, W_.Bold)
            self.wrap(p, card.x() + S(18), card.y() + S(44), cw - S(36), s_, 13.5, W_.Medium, self.a(0.62), rows=4)
            if q:
                self.hit("recent_q", q, card)
        return y + ((len(tips) + cols - 1) // cols) * (ch + S(14))

    def lyric_hits(self, q: str) -> list[dict]:
        if len(q) < 3:
            return []
        out = []
        for h in self.v.index.search(q, self.v.clock.tid, limit=12):
            if h.get("why") == "name":
                continue
            out.append({"kind": "track", "uri": f"spotify:track:{h.get('id', '')}", "name": h.get("title") or "",
                        "sub": h.get("artist", ""), "line": h.get("line", ""), "art": ""})
        known = {(o["name"].lower(), o["sub"].lower()) for o in out}
        for g in self.v.genius_rows(q, known) or []:
            out.append({"kind": "genius", "name": g.get("title", ""), "sub": g.get("artist", ""),
                        "line": g.get("line", ""), "art": g.get("art", ""), "genius": g})
        return out

    def line_song(self, q: str, songs: list[dict], lyr: list[dict], src) -> dict | None:
        """A search that is a line from a song: that song, found by its name, to lead the results.
        The catalogue matches the words alone ("…a sign of the times..." got Everything Suxxx)."""
        if src is self.links or len(q.split()) < 4:
            return None
        if any(SS.norm(s_.get("name", "")) == SS.norm(q) for s_ in songs[:5]):
            return None                                     # it is a song's name too
        for hit in lyr[:4]:
            if hit.get("line") and hit.get("name"):
                score, why = GR.score_song(q, hit["name"], hit.get("sub", ""), hit["line"])
                if why == "line" and score >= LINE_LIFT:
                    break
        else:
            return None
        title, by = SS.norm(hit["name"]), SS.norm(str(hit.get("sub", "")).split(",")[0])

        def same(t: dict) -> bool:
            return SS.norm(t.get("name", "")) == title and by in SS.norm(t.get("sub", ""))
        lead = next((t for t in songs if same(t)), None)
        if lead is not None:
            return lead
        ask = f"{hit['name']} {hit.get('sub', '')}".strip()
        got = src.found(ask)
        if got is None:
            src.lookup(ask)
            return None
        return next((dict(t, kind="track") for t in got.get("tracks") or [] if same(t)), None)

    def lyric_list(self, p, x, y, w, rows: list) -> float:
        S = self.S
        for r in rows:
            rr = QRectF(x, y, w, S(74))
            self.rr(p, rr, S(10), self.a(0.09 if self.hot("item", r) else 0.05))
            self.cover(p, QRectF(rr.x() + S(14), rr.y() + S(13), S(48), S(48)), r.get("art", ""), S(6),
                       r.get("name", ""), label=False)
            line = (r.get("line") or "").strip()
            self.text(p, QRectF(rr.x() + S(76), rr.y() + S(10), w - S(100), S(24)),
                      f"“{line}”" if line else r.get("name", ""), 16, W_.Bold)
            bits = [r.get("name")] if line else []
            bits.append(r.get("sub"))
            self.text(p, QRectF(rr.x() + S(76), rr.y() + S(38), w - S(100), S(22)),
                      " · ".join(x_ for x_ in bits if x_)
                      + ((" · on Genius" if line else " · on Genius, by its name") if r.get("kind") == "genius" else ""),
                      13.5, W_.Medium, self.a(0.55))
            self.hit("item", r, rr)
            y += S(82)
        return y

    # ========================================================== list pages
    def list_head(self, p, x, y, w, page: str, sub: str, opts: list[str] = (), action: str = "",
                  action_kind: str = "") -> float:
        S = self.S
        title = TITLES.get(page, page)
        right_w = 0.0
        if opts or action:
            fm = self.fm(15, W_.DemiBold)
            right_w = sum(fm.horizontalAdvance(o) + S(28) for o in opts) + S(8)
            right_w += (self.fm(16, W_.Bold).horizontalAdvance(action) + S(42)) if action else 0
        wide = w - right_w > S(360)
        y1 = self.title(p, x, y, w - (right_w if wide else 0), title, sub)
        self.filters_bar(p, x, (y + S(20)) if wide else y1 + S(6), w, page, list(opts), action, action_kind)
        return (y1 if wide else y1 + S(52)) + S(20)

    def page_queue(self, p, x, y, w, L) -> float:
        v, S = self.v, self.S
        if self.player.active:
            pl = self.player
            q = pl.queue
            mine = [i for i in range(pl.idx + 1, len(q)) if not q[i].get("_auto")]
            auto = [i for i in range(pl.idx + 1, len(q)) if q[i].get("_auto")]
            note = "Playing in Mild Lyrics" + (" · autoplay on" if self.v.home_autoplay else "")
            y = self.list_head(p, x, y, w, "queue", note, action="Clear queue", action_kind="clear_queue")
            rows = [{"head": "NOW PLAYING"}]
            cur = pl.current
            if cur:
                rows.append(dict(self.local_item(cur), _on=True, _n="", _qi=pl.idx))
            n = 1
            for head, idxs in (("UP NEXT", mine), ("AUTOPLAY · SONGS LIKE THESE", auto)):
                if idxs:
                    rows.append({"head": head})
                    for i in idxs:
                        rows.append(dict(self.local_item(q[i]), _n=n, _qi=i))
                        n += 1
            if self.v.home_autoplay and not auto and self.net_down:
                rows.append({"head": "AUTOPLAY · OFFLINE, WAITING FOR A CONNECTION…"})
            elif self.v.home_autoplay and not auto and self.auto_want:
                rows.append({"head": "AUTOPLAY · FINDING SONGS LIKE THESE…"})
            return self.table(p, x, y, w, rows)
        src = "Spotify"
        y = self.list_head(p, x, y, w, "queue", f"Playing from {src} · drag any song onto Queue to add it",
                           action="Clear queue", action_kind="clear_queue")
        rows = []
        if v.queue_cur:
            rows += [{"head": "NOW PLAYING"}, dict(v.queue_cur, kind="track", _on=True, _n="")]
        queued = [r for r in v.queue_items or [] if r.get("src") == "queued"]
        nextup = [r for r in v.queue_items or [] if r.get("src") != "queued"]
        n = 1
        if queued:
            rows.append({"head": "NEXT IN QUEUE"})
            for r in queued:
                rows.append(dict(r, kind="track", _n=n, _q=True))
                n += 1
        if nextup:
            rows.append({"head": "UP NEXT"})
            for r in nextup[:40]:
                rows.append(dict(r, kind="track", _n=n, _q=True))
                n += 1
        recs = (self._recs.get(v.home_mode) or [])[:4]
        if recs:
            rows.append({"head": "THEN, FROM YOUR SUGGESTIONS"})
            for r in recs:
                rows.append(dict(r, _n=n, _shown=r.get("why") or ""))    # the reason shows; `sub` stays the artist
                n += 1
        if len(rows) <= 2 and not v.queue_at:
            return self.empty(p, x, y, w, "Reading the queue…")
        return self.table(p, x, y, w, rows)

    def page_charts(self, p, x, y, w, L) -> float:
        S = self.S
        which = self.filters.get("charts", self.shelf_chart())
        uri = self.cat.chart_uri(which)
        sub = "Spotify charts, with the lyric timing each song has here" if self.online else \
            (self.cat.get("pl:" + uri) or {}).get("sub") or "Playing here in Mild Lyrics"
        y = self.list_head(p, x, y, w, "charts", sub, ["Global", "Viral 50", "Your country"])
        rows = self.chart_rows(which)
        if rows is None:
            return self.empty(p, x, y, w, "This chart could not be loaded; it is asked again shortly."
                              if self.cat.failed("pl:" + uri) else "Loading the chart…")
        f = rows
        for i, r in enumerate(f):
            r["_n"] = i + 1
            r["_x"] = [r.get("album", "")]
        return self.table(p, x, y, w, f, extra=["ALBUM"] if self.bp == "L" else [], context=None)

    def page_recent(self, p, x, y, w, L) -> float:
        y = self.list_head(p, x, y, w, "recent", "From every player Mild Lyrics follows, on this computer")
        rows = []
        for day, rs in PLG.by_day(self.log.recent(200)).items():
            rows.append({"head": day})
            for r in rs:
                it = _row_of(r)
                it["_x"] = [r.get("player", "")]
                it["_end"] = time.strftime("%H:%M", time.localtime(r.get("t", 0)))
                it["_n"] = ""
                rows.append(it)
        if not rows:
            return self.empty(p, x, y, w, "Nothing logged yet. Every song you play while Mild Lyrics is open, "
                                          "from any player it follows, lands here.")
        return self.table(p, x, y, w, rows, extra=["PLAYER"], end="AT", context=[])

    def page_songs(self, p, x, y, w, L) -> float:
        y = self.list_head(p, x, y, w, "songs", "Liked songs and everything you have played", FILTERS)
        f = self.filters.get("songs", "All")
        seen, rows = set(), []
        for r in self.liked_rows:
            k = (r.get("name", "") + "|" + r.get("sub", "")).lower()
            if k not in seen:
                seen.add(k)
                rows.append(dict(r, _x=[r.get("album", "")]))
        for r in self.log.recent(400):
            k = (r.get("title", "") + "|" + r.get("artist", "")).lower()
            if k not in seen:
                seen.add(k)
                it = _row_of(r)
                it["_x"] = [r.get("album", "")]
                rows.append(it)
        rows = [r for r in rows if self.matches(r, f)]
        for i, r in enumerate(rows):
            r["_n"] = i + 1
        if not rows:
            return self.empty(p, x, y, w, "No songs match." if f != "All" else "Nothing here yet.")
        return self.table(p, x, y, w, rows[:500], extra=["ALBUM"])

    def page_liked(self, p, x, y, w, L) -> float:
        n = len(self.liked_rows)
        y = self.list_head(p, x, y, w, "liked", f"{n} songs · newest first · drop songs on Liked songs in the "
                                                "sidebar to add them", FILTERS)
        f = self.filters.get("liked", "All")
        rows = [dict(r, _x=[r.get("album", "")]) for r in self.liked_rows if self.matches(r, f)]
        for i, r in enumerate(rows):
            r["_n"] = i + 1
        if not rows:
            return self.empty(p, x, y, w, "Nothing liked yet. Use the heart on any song, or right-click it."
                              if not self.liked_rows else "No liked songs match.")
        return self.table(p, x, y, w, rows[:2000], extra=["ALBUM"], ctx_uri="", context=None)

    def page_artists(self, p, x, y, w, L) -> float:
        y = self.list_head(p, x, y, w, "artists", "Followed, then your most played")
        items = [dict(a, kind="artist") for a in self.library.artists()]
        have = {a["name"].lower() for a in items}
        for a in self.spot.get("artists") or []:
            if a.get("name", "").lower() not in have:
                items.append(dict(a, kind="artist"))
                have.add(a.get("name", "").lower())
        known = self.artist_uris()
        for name, n in self.log.top_artists(365, 24):
            if name.lower() not in have:
                uri, art = self.artist_face(name, known)
                items.append({"kind": "artist", "name": name, "sub": f"{n} play{'s' if n != 1 else ''}", "uri": uri, "art": art})
        cols = {"L": 6, "M": 4, "S": 3, "XS": 2}[self.bp]
        if not items:
            return self.empty(p, x, y, w, "Follow artists from their page, or play some, and they show here.")
        return self.tiles(p, x, y, w, items, cols, round_=True)

    def page_albums(self, p, x, y, w, L) -> float:
        y = self.list_head(p, x, y, w, "albums", "Saved in your library")
        items = [dict(a, kind="album") for a in self.library.albums()]
        have = {LIB.entity_key(a) for a in items}
        items += [dict(a, kind="album") for a in self.spot.get("albums") or []
                  if LIB.entity_key(dict(a, kind="album")) not in have]
        cols = {"L": 6, "M": 4, "S": 3, "XS": 2}[self.bp]
        if not items:
            return self.empty(p, x, y, w, "Albums you save from their page show here.")
        return self.tiles(p, x, y, w, items, cols)

    def page_playlists(self, p, x, y, w, L) -> float:
        S = self.S
        y = self.list_head(p, x, y, w, "playlists", "Yours and ones you follow", action="New playlist",
                           action_kind="new_pl")
        items = [{"kind": "playlist", "uri": "liked", "name": "Liked songs", "sub": f"{len(self.liked_rows)} songs",
                  "art": ""}]
        items += [dict(a, kind="playlist") for a in self.all_playlists()]
        for it in (self.top_picks(self.spot.get("feed") or []) if self.online else self.my_mixes()):
            if it["uri"] not in {i["uri"] for i in items}:
                items.append(dict(it, sub="Made for you"))
        cols = {"L": 6, "M": 4, "S": 3, "XS": 2}[self.bp]
        return self.tiles(p, x, y, w, items, cols)

    def lyric_files(self) -> list[dict]:
        if self.lyr_files is not None:
            return self.lyr_files
        out = []
        rooms = [(saves.chosen(self.v.save_fetched_dir), "Fetched"), (saves.EDITOR, "Made by you")]
        for room, what in rooms:
            try:
                files = list(pathlib.Path(room).glob("*.ttml"))
            except OSError:
                files = []
            for f in files:
                stem = f.stem
                artist, _, title = stem.partition(" - ")
                if not title:
                    artist, title = "", stem
                try:
                    st = f.stat().st_mtime
                    head = f.open("rb").read(1500).decode("utf-8", "replace")
                except OSError:
                    continue
                timing = re.search(r'itunes:timing="(\w+)"', head)
                k = "w" if timing and timing.group(1).lower() == "word" else "l"
                out.append({"kind": "file", "name": title, "sub": artist, "path": str(f), "_k": k,
                            "_x": [what, _ago(st)], "t": st, "art": ""})
        out.sort(key=lambda r: -r["t"])
        self.lyr_files = out
        return out

    def page_lyrics(self, p, x, y, w, L) -> float:
        y = self.list_head(p, x, y, w, "lyrics", "The TTMLs kept here · lyrics/fetched and lyrics/made",
                           ["All", "Fetched", "Made by you"], action="Open folder", action_kind="open_folder")
        f = self.filters.get("lyrics", "All")
        rows = [r for r in self.lyric_files() if f == "All" or r["_x"][0] == f]
        for i, r in enumerate(rows):
            r["_n"] = i + 1
            r["_end"] = ""
        if not rows:
            return self.empty(p, x, y, w, "No TTMLs saved yet. Save one from the lyrics (S), or time one in "
                                          "the TTML Editor.")
        return self.table(p, x, y, w, rows, extra=["SOURCE", "SAVED"], end="", art=False)

    def local_item(self, t: dict) -> dict:
        """A track of the local player (a file or a stream) as a row."""
        out = {"kind": "local" if t.get("path") else "track", "name": t.get("title", ""),
               "sub": t.get("artist", ""), "art": t.get("art", ""),
               "ms": t.get("ms", 0), "path": t.get("path", ""), "title": t.get("title", ""),
               "artist": t.get("artist", ""), "album": t.get("album", ""), "tid": t.get("tid", ""),
               "uri": t.get("uri", ""), "spotify": t.get("spotify", ""), "_track": t}
        if t.get("path"):
            out["_k"] = self.local_kind(t)
        return out

    def local_kind(self, t: dict) -> str | None:
        return self.kinds.get(t.get("tid", "")) or None

    def page_local(self, p, x, y, w, L) -> float:
        S = self.S
        dirs = self.local_dirs()
        n = len(self.lib.tracks)
        sub = ("Played by Mild Lyrics itself, no other player needed · "
               + ", ".join(d.replace(str(pathlib.Path.home()), "~") for d in dirs) + f" · {n} songs")
        if self.lib.scanning:
            sub += " · scanning…"
        y = self.list_head(p, x, y, w, "local", sub, FILTERS, action="Add folder", action_kind="add_folder")
        f = self.filters.get("local", "All")
        rows = []
        for t in self.lib.tracks:
            it = self.local_item(t)
            if not self.matches(it, f):
                continue
            it["_x"] = [t.get("album", ""), t.get("fmt", "")] if self.bp == "L" else [t.get("fmt", "")]
            it["_on"] = self.player.current is t
            rows.append(it)
        for i, r in enumerate(rows):
            r["_n"] = i + 1
        if not rows:
            return self.empty(p, x, y, w, "Scanning your folders…" if self.lib.scanning else
                              "No music files found. Add a folder with your own songs: MP3, FLAC, Ogg, M4A, WAV.")
        return self.table(p, x, y, w, rows, extra=["ALBUM", "FORMAT"] if self.bp == "L" else ["FORMAT"],
                          context=rows)

    # ============================================================ Stats
    def page_stats(self, p, x, y, w, L) -> float:
        S = self.S
        yh = y
        y = self.title(p, x, y, w, "Your stats", "From every player Mild Lyrics follows, on this computer")
        self.seg(p, x + w, yh + S(14), [(k, k) for k in ("Week", "Month", "Year")], self.stat_per, "stat_per",
                 right=True)
        st = self.log.stats(self.stat_per)
        y += S(20)
        hrs = st["secs"] / 3600
        nums = [(f"{int(hrs)} h {int((hrs % 1) * 60)} m" if hrs < 10 else f"{int(hrs)} h", "listened"),
                (f"{st['plays']:,}", "songs"), (f"{st['artists']:,}", "artists"),
                (f"{st['lines']:,}", "lyric lines followed")]
        cols = 4 if self.bp in ("L", "M") else 2
        cw = (w - S(18) * (cols - 1)) / cols
        for i, (val, lab) in enumerate(nums):
            r, c = divmod(i, cols)
            card = QRectF(x + c * (cw + S(18)), y + r * S(112), cw, S(96))
            self.rr(p, card, S(12), self.a(0.06), self.a(0.10))
            self.text(p, QRectF(card.x() + S(20), card.y() + S(14), cw - S(40), S(44)), val, 32, W_.Black)
            self.text(p, QRectF(card.x() + S(20), card.y() + S(58), cw - S(40), S(22)), lab, 14, W_.Medium,
                      self.a(0.62))
        y += ((len(nums) + cols - 1) // cols) * S(112) + S(12)
        if not st["plays"] and not st["secs"]:
            return self.empty(p, x, y, w, "Nothing logged for this period yet. Mild Lyrics keeps this on this "
                                          "computer only, from the songs you play while it is open.")
        two = self.bp in ("L", "M")
        lw = w * 0.56 if two else w
        rw = w - lw - S(24) if two else w
        top_a = st["top_artists"]
        y1 = y
        card_h = S(70) + max(1, len(top_a)) * S(53)
        self.rr(p, QRectF(x, y, lw, card_h), S(14), self.a(0.05), self.a(0.10))
        self.text(p, QRectF(x + S(24), y + S(20), lw, S(28)), "Top artists", 19, W_.Black)
        yy = y + S(64)
        mx = max([n for _a, n in top_a] or [1])
        for a, n in top_a:
            self.text(p, QRectF(x + S(24), yy, lw - S(140), S(22)), a, 15.5, W_.DemiBold)
            self.text(p, QRectF(x, yy, lw - S(24), S(22)), f"{n} play{'s' if n != 1 else ''}", 13.5, W_.Medium, self.a(0.55),
                      Qt.AlignmentFlag.AlignRight)
            bar = QRectF(x + S(24), yy + S(28), lw - S(140), S(5))
            self.rr(p, bar, S(2.5), self.a(0.10))
            self.rr(p, QRectF(bar.x(), bar.y(), bar.width() * n / mx, bar.height()), S(2.5), INK)
            yy += S(53)
        ry = y if two else y + card_h + S(24)
        rx = x + lw + S(24) if two else x
        songs = st["top_songs"]
        ch = S(70) + max(1, len(songs)) * S(58)
        self.rr(p, QRectF(rx, ry, rw, ch), S(14), self.a(0.05), self.a(0.10))
        self.text(p, QRectF(rx + S(24), ry + S(20), rw, S(28)), "Top songs", 19, W_.Black)
        yy = ry + S(62)
        for i, (r, n) in enumerate(songs):
            it = _row_of(r)
            rr = QRectF(rx + S(12), yy, rw - S(24), S(54))
            if self.hot("item", it):
                self.rr(p, rr, S(8), self.a(0.06))
            self.text(p, QRectF(rr.x() + S(8), rr.y(), S(20), rr.height()), str(i + 1), 14.5, W_.DemiBold,
                      self.a(0.55))
            self.cover(p, QRectF(rr.x() + S(34), rr.y() + S(5), S(44), S(44)), it["art"], S(6), it["name"],
                       label=False)
            self.text(p, QRectF(rr.x() + S(90), rr.y() + S(6), rr.width() - S(180), S(22)), it["name"], 15, W_.Bold)
            self.text(p, QRectF(rr.x() + S(90), rr.y() + S(28), rr.width() - S(180), S(20)), it["sub"], 13,
                      W_.Medium, self.a(0.55))
            self.text(p, QRectF(rr.x(), rr.y(), rr.width() - S(8), rr.height()), f"{n} play{'s' if n != 1 else ''}", 13.5, W_.Medium,
                      self.a(0.55), Qt.AlignmentFlag.AlignRight)
            self.hit("item", it, rr)
            yy += S(58)
        y = max(y1 + card_h, ry + ch) + S(24)
        # when you listen
        hrs_ = st["hours"]
        hh = S(220)
        self.rr(p, QRectF(x, y, lw, hh), S(14), self.a(0.05), self.a(0.10))
        self.text(p, QRectF(x + S(24), y + S(20), lw, S(28)), "When you listen", 19, W_.Black)
        peak = max(range(24), key=lambda i: hrs_[i]) if any(hrs_) else 0
        self.text(p, QRectF(x + S(24), y + S(48), lw - S(48), S(20)),
                  f"Most of it around {peak:02d}:00" if any(hrs_) else "", 13.5, W_.Medium, self.a(0.55))
        mx = max(hrs_) or 1
        bw = (lw - S(48)) / 24
        _acc, light = self.accent()
        for i, s in enumerate(hrs_):
            bh = max(S(3), (hh - S(110)) * s / mx)
            r = QRectF(x + S(24) + i * bw + S(2), y + hh - S(30) - bh, bw - S(4), bh)
            self.rr(p, r, S(3), light if abs(i - peak) <= 1 else self.a(0.35))
        for i in (0, 6, 12, 18):
            self.text(p, QRectF(x + S(24) + i * bw, y + hh - S(26), S(40), S(18)), f"{i}:00", 11.5, W_.Medium,
                      self.a(0.45))
        ry = y if two else y + hh + S(24)
        ph = S(220)
        self.rr(p, QRectF(rx, ry, rw, ph), S(14), self.a(0.05), self.a(0.10))
        self.text(p, QRectF(rx + S(24), ry + S(20), rw, S(28)), "Lyrics you followed", 19, W_.Black)
        kinds = st["kinds"]
        tot = sum(kinds.values()) or 1
        share = [("Word-by-word", kinds.get("w", 0) / tot, light), ("Line", kinds.get("l", 0) / tot, self.a(0.6)),
                 ("No lyrics", kinds.get("n", 0) / tot, self.a(0.2))]
        yy = self.share_bar(p, rx + S(24), ry + S(58), rw - S(48), share)
        self.text(p, QRectF(rx + S(24), yy + S(10), rw, S(28)), "Players", 19, W_.Black)
        pl = st["players"]
        tot = sum(pl.values()) or 1
        cols_ = [INK, light, self.a(0.45), self.accent()[0]]
        share = [(k, n / tot, cols_[i % 4]) for i, (k, n) in enumerate(pl.most_common(4))]
        self.share_bar(p, rx + S(24), yy + S(46), rw - S(48), share)
        return max(y + hh, ry + ph) + S(10)

    def share_bar(self, p, x, y, w, share: list) -> float:
        S = self.S
        bar = QRectF(x, y, w, S(10))
        path = QPainterPath()
        path.addRoundedRect(bar, S(5), S(5))
        p.save()
        p.setClipPath(path, Qt.ClipOperation.IntersectClip)
        p.fillRect(bar, self.a(0.08))
        cx = x
        for _n, f, c in share:
            p.fillRect(QRectF(cx, y, w * f, bar.height()), c)
            cx += w * f
        p.restore()
        cx = x
        yy = y + S(20)
        for n, f, c in share:
            label = f"{n}  {int(round(f * 100))}%"
            fm = self.fm(13.5, W_.DemiBold)
            lw = fm.horizontalAdvance(label) + S(28)
            if cx + lw > x + w:
                cx, yy = x, yy + S(24)
            self.rr(p, QRectF(cx, yy + S(6), S(9), S(9)), S(2), c)
            self.text(p, QRectF(cx + S(15), yy, lw, S(22)), label, 13.5, W_.DemiBold, self.a(0.8), elide=False)
            cx += lw
        return yy + S(30)

    # ======================================================= item pages
    def hero(self, p, x, y, w, art: str, label: str, name: str, meta_bits: list, round_: bool = False,
             mosaic: list | None = None) -> tuple[float, float]:
        """Cover, kicker, big title and the line under it; returns (y for buttons, x of text)."""
        S = self.S
        side = S({"L": 236, "M": 190, "S": 140, "XS": 96}[self.bp])
        art_r = QRectF(x, y, side, side)
        if mosaic:
            q = side / 2
            for i, m in enumerate(mosaic[:4]):
                self.cover(p, QRectF(x + (i % 2) * q, y + (i // 2) * q, q, q), m.get("art", ""), 0,
                           m.get("name", ""), label=False)
        else:
            self.cover(p, art_r, art, S(10), name, round_=round_)
        tx = art_r.right() + S({"L": 32, "M": 24, "S": 18, "XS": 14}[self.bp])
        tw = x + w - tx
        ty = y + max(0.0, side - S(170))
        self.text(p, QRectF(tx, ty, tw, S(20)), label, 13.5, W_.Bold, self.a(0.62))
        big = {"L": 60, "M": 48, "S": 38, "XS": 28}[self.bp]
        fm = self.fm(big, W_.Black)
        while big > 26 and fm.horizontalAdvance(name) > tw:
            big -= 4
            fm = self.fm(big, W_.Black)
        self.text(p, QRectF(tx, ty + S(20), tw, S(big * 1.25)), name, big, W_.Black)
        my = ty + S(20 + big * 1.25)
        cx = tx
        for bit in meta_bits:
            if isinstance(bit, dict):
                s = bit.get("name", "")
                fmb = self.fm(15, W_.Bold)
                bw = min(fmb.horizontalAdvance(s), tx + tw - cx)
                r = QRectF(cx, my, bw, S(24))
                hot = self.hot("link", bit)
                self.text(p, r, s, 15, W_.Bold, INK if hot else self.a(0.92))
                p.fillRect(QRectF(cx, r.bottom() - S(3), bw, 1), self.a(0.6 if hot else 0.3))
                self.hit("link", bit, r)
                cx += bw
            else:
                fmb = self.fm(15, W_.Medium)
                s = bit
                bw = min(fmb.horizontalAdvance(s), max(0.0, tx + tw - cx))
                self.text(p, QRectF(cx, my, bw, S(24)), s, 15, W_.Medium, self.a(0.62))
                cx += bw
        return max(my + S(36), y), tx, art_r.bottom()

    def page_album(self, p, x, y, w, L) -> float:
        S = self.S
        self.by_name("album")
        arg = self.arg or {}
        y = self.backlink(p, x, y)
        uri = arg.get("uri", "")
        missing = False
        if not uri or uri.startswith("spotify:") and not self.online:
            # A song from the play log has no album uri, and Spotify's cannot be read while it is
            # away: found by name and artist in the catalogue in use, as page_artist does.
            name, by = arg.get("name", ""), arg.get("sub", "").split(" · ")[0]   # "Linkin Park · 2012"
            # Asked without its edition: Deezer matches every word, and calls Spotify's
            # "Oxymoron (Deluxe Version)" "Oxymoron (Deluxe)".
            plain = re.sub(r"\s*[\(\[][^)\]]*[\)\]]", "", name).strip() or name
            q = f"{plain} {by}".strip()
            sr = self.cat.found(q) if q else None
            if sr is None and q:
                self.cat.lookup(q)
            same = [a for a in (sr or {}).get("albums") or [] if SS.norm(a.get("name", "")) == SS.norm(name)]
            a0 = max(same, key=lambda a: (bool(by) and SS.norm(by) in SS.norm(a.get("sub", "")),
                                          edition_words(a.get("name", "")) == edition_words(name),
                                          len(edition_words(a.get("name", "")) & edition_words(name))), default=None)
            if a0:
                self.arg = arg = dict(arg, uri=a0["uri"], art=arg.get("art") or a0.get("art", ""))
                self.src(a0["uri"]).album(a0["uri"])
            missing = sr is not None and a0 is None or not q
        got = self.src(arg.get("uri", "")).get("album:" + arg.get("uri", ""))
        tracks = [dict(t, kind="track", _ctx=arg.get("uri", "")) for t in (got or {}).get("tracks") or []]
        known = [self.kind_of(t) for t in tracks]
        wbw = sum(1 for k in known if k == "w")
        mins = sum(t.get("ms", 0) for t in tracks) / 60000
        bits = []
        arts = (got or {}).get("artists") or ([{"name": arg["sub"].split(" · ")[0], "uri": ""}] if arg.get("sub") else [])
        for i, a in enumerate(arts):
            if i:
                bits.append(" & " if i == len(arts) - 1 else ", ")
            bits.append(dict(a, kind="artist"))
        info = [b for b in ((got or {}).get("year", ""), f"{len(tracks)} songs, {int(mins)} min" if tracks else "",
                            f"{wbw} word-by-word here" if wbw else "") if b]
        bits += [" · " + " · ".join(info)] if info else []
        by, tx, bottom = self.hero(p, x, y, w, (got or arg).get("art", ""),
                                   ((got or {}).get("type") or "album").upper(), (got or arg).get("name", ""), bits)
        item = dict(got or arg, kind="album", tracks=tracks)
        b = self.button(p, tx, by, "Play", "play_item", item, icon="play", style="primary")
        b = self.button(p, b.right() + S(8), by, "Shuffle", "shuffle_item", item, icon="shuffle")
        b = self.button(p, b.right() + S(8), by, "Add to queue", "queue_item", item, icon="queue")
        lead_ = ((got or {}).get("artists") or [{}])[0].get("name", "")
        alb = {"kind": "album", "uri": (got or arg).get("uri", ""), "name": (got or arg).get("name", ""),
               "sub": lead_ or arg.get("sub", ""), "art": (got or arg).get("art", ""), "year": (got or {}).get("year", "")}
        on = self.follows(alb)
        self.button(p, b.right() + S(8), by, "Saved" if on else "Save", "act", ("follow", alb),
                    icon="check" if on else "plus")
        y = max(bottom, by + S(40)) + S(30)
        if got is None:
            return self.empty(p, x, y, w, f"No album called {arg.get('name', '')} in the catalogue."
                              if missing else "Loading…")
        for i, t in enumerate(tracks):
            t["_n"] = i + 1
            t["_on"] = t.get("uri") == f"spotify:track:{self.v.clock.tid}"
            names = [a["name"] for a in t.get("artists") or []]
            leads = [a["name"] for a in (got or {}).get("artists") or []]
            feat = [n for n in names if n not in leads]
            t["feat"] = ("feat. " + ", ".join(feat)) if feat else ""
        y = self.table(p, x, y, w, tracks, art=False) + S(30)
        lead = ((got or {}).get("artists") or [{}])[0]
        if lead.get("uri"):
            ag = self.src(lead["uri"]).get("artist:" + lead["uri"])
            if ag is None:
                self.src(lead["uri"]).artist(lead["uri"])
            more = [dict(a, sub=str(a.get("year", ""))) for a in (ag or {}).get("albums", [])
                    if a.get("uri") != arg.get("uri") and a.get("type") != "single"][:6]
            if more:
                y = self.head(p, x, y, w, f"More by {lead.get('name', '')}", link="See all", link_kind="link",
                              link_arg=dict(lead, kind="artist"))
                cols = {"L": 6, "M": 4, "S": 3, "XS": 2}[self.bp]
                y = self.tiles(p, x, y, w, more, cols, max_rows=1)
        return y

    def page_playlist(self, p, x, y, w, L) -> float:
        S = self.S
        arg = self.arg or {}
        y = self.backlink(p, x, y)
        uri = arg.get("uri", "")
        held = self.pl_data(uri)
        got = held if held is not None else (arg if arg.get("tracks") else None)   # a pasted link's
        local = uri.startswith("mild:playlist:")
        tracks = [dict(t, kind=t.get("kind") or "track", _ctx=("" if local else uri))
                  for t in (got or {}).get("tracks") or []]
        mine = bool((got or {}).get("mine"))
        editable = local or (mine and self.online)
        wbw = sum(1 for t in tracks if self.kind_of(t) == "w")
        owner = (got or {}).get("owner", "")
        n = (got or {}).get("total") or len(tracks)
        sub = [f"{n} song{'s' if n != 1 else ''}",
               (got or {}).get("sub", "") if (got or {}).get("mix") else
               "in Mild Lyrics" if local else "made by you" if mine else (f"by {owner}" if owner else "")]
        if wbw:
            sub.append(f"{wbw} with word-by-word lyrics here")
        if not local and not self.online and held is not None and not uri.startswith("mild:"):
            sub.append("as Spotify last showed it")
        mosaic = tracks[:4] if local and len(tracks) >= 4 else None
        art = arg.get("art") if uri.startswith("mild:mix:") and arg.get("art") else (got or arg).get("art", "")
        kicker = "MADE FROM YOUR LISTENING" if uri.startswith("mild:mix:") else "PLAYLIST"
        by, tx, bottom = self.hero(p, x, y, w, art, kicker, (got or arg).get("name", ""),
                                   [" · ".join(s_ for s_ in sub if s_)], mosaic=mosaic)
        item = dict(got or arg, kind="playlist", tracks=tracks)
        b = self.button(p, tx, by, "Play", "play_item", item, icon="play", style="primary")
        b = self.button(p, b.right() + S(8), by, "Shuffle", "shuffle_item", item, icon="shuffle")
        if editable:
            b = self.button(p, b.right() + S(8), by, "Done" if self.pl_edit else "Edit", "act", "pl_edit", icon="pen",
                            style="primary" if self.pl_edit else "soft")
        if local and self.pl_edit:
            b = self.button(p, b.right() + S(8), by, "Rename", "act", "pl_rename")
            self.button(p, b.right() + S(8), by, "Delete", "act", "pl_delete", icon="trash")
        y = max(bottom, by + S(40)) + S(30)
        if got is None:
            return self.empty(p, x, y, w, "Putting it together from what you play…" if uri.startswith("mild:mix:")
                              else "Loading…" if self.online or uri.startswith("deezer:") else
                              "This playlist opens when Spotify is connected.")
        if not tracks:
            return self.empty(p, x, y, w, "Nothing in it yet. Right-click any song ▸ Add to playlist, or drag "
                                          "songs onto it in the sidebar.")
        if self.pl_edit:
            self.text(p, QRectF(x, y - S(18), w, S(18)), "Drag a song to move it, or remove it with ×."
                      + ("" if local else " Changes go straight to Spotify."), 13, W_.Medium, self.a(0.55))
            y += S(10)
        for i, t in enumerate(tracks):
            t["_n"] = i + 1
            t["_on"] = self.is_playing(t)
        y = self.table(p, x, y, w, tracks, extra=["ALBUM"] if self.bp == "L" else [])
        if self.pl_edit:
            for t, rr in self.row_rects:
                xr = QRectF(rr.right() - S(36), rr.center().y() - S(14), S(28), S(28))
                self.rr(p, xr, S(14), QColor(16, 16, 21, 220))
                self.icon(p, "x", xr.adjusted(S(8), S(8), -S(8), -S(8)))
                self.hit("pl_rm", t, xr)
                if local and t.get("_pi") is not None:
                    self.drops.append(({"to": "row", "i": t["_pi"]}, QRectF(rr)))
        return y

    def by_name(self, kind: str) -> None:
        """A Spotify artist or album while Spotify is away: the catalogue's own, found by name."""
        arg = self.arg or {}
        uri = arg.get("uri", "")
        if uri and (self.online or not uri.startswith("spotify:") or self.spot.get(f"{kind}:{uri}") is not None):
            return
        if kind == "artist":
            self.arg = dict(arg, uri="", spotify_uri=uri)
            return
        name, who = arg.get("name", ""), (arg.get("sub") or "").split("·")[0].strip()
        if not name:
            return
        found = self.cat.found(f"{who} {name}".strip())
        if found is None:
            self.cat.lookup(f"{who} {name}".strip())
            return
        hit = next((a for a in found.get("albums") or []
                    if SS.norm(a.get("name", "")) == SS.norm(name)), None)
        if hit:
            self.arg = dict(arg, uri=hit["uri"], art=arg.get("art") or hit.get("art", ""), spotify_uri=uri)

    def page_artist(self, p, x, y, w, L) -> float:
        S = self.S
        self.by_name("artist")
        arg = self.arg or {}
        uri = arg.get("uri", "")
        missing = False
        if not uri:
            got = None
            q = arg.get("name", "")
            sr = self.cat.found(q) if q else None
            if sr is None and q:
                self.cat.lookup(q)
            a0 = next((a for a in (sr or {}).get("artists") or [] if a["name"].lower() == q.lower()), None)
            if a0:
                self.arg = dict(arg, uri=a0["uri"], art=a0.get("art", ""))
                self.src(a0["uri"]).artist(a0["uri"])
            missing = sr is not None and a0 is None or not q
        else:
            got = self.src(uri).get("artist:" + uri)
        name = self.spelt((got or arg).get("name", ""))
        band = QRectF(self.content.x(), y - (self.content.y() + self.S(28) - self.content.y()) - S(0),
                      self.content.width(), S({"L": 330, "M": 280, "S": 220, "XS": 170}[self.bp]))
        band.moveTop(y - S(28))
        hdr = (got or {}).get("header") or (got or arg).get("art", "")
        if hdr:
            # On whole device pixels: at a fractional edge the clip let one more row of the
            # picture through than the fade covered, a bright seam under the header.
            dt = p.deviceTransform()
            d = dt.mapRect(band)
            band = dt.inverted()[0].mapRect(QRectF(QPointF(round(d.left()), round(d.top())),
                                                   QPointF(round(d.right()), round(d.bottom()))))
            p.save()
            p.setClipRect(band, Qt.ClipOperation.IntersectClip)
            p.setOpacity(0.55)
            self.cover(p, QRectF(band.x(), band.y() - band.width() * 0.25, band.width(), band.width()), hdr, 0, name,
                       label=False)
            p.setOpacity(1.0)
            from PyQt6.QtGui import QLinearGradient
            g = QLinearGradient(band.topLeft(), band.bottomLeft())
            g.setColorAt(0, QColor(16, 16, 21, 60))
            g.setColorAt(1, QColor(16, 16, 21, 225))
            p.fillRect(band, g)
            p.restore()
        y = self.backlink(p, x, y)
        y = band.bottom() - S(170)
        self.text(p, QRectF(x, y, w, S(20)), "ARTIST", 13.5, W_.Bold, self.a(0.75))
        big = {"L": 80, "M": 60, "S": 44, "XS": 32}[self.bp]
        self.text(p, QRectF(x, y + S(18), w, S(big * 1.2)), name, big, W_.Black)
        y += S(18 + big * 1.15)
        mine = self.log.plays_of(artist=name, days=30)
        tops = [a for a, _n in self.log.top_artists(30, 1)]
        note = ("Your most played artist this month" if tops and tops[0].lower() == name.lower() else
                f"{mine} play{'s' if mine != 1 else ''} this month" if mine else
                f"{int(got.get('listeners') or 0):,} monthly listeners"
                if got and not uri.startswith("deezer:") else "")
        self.text(p, QRectF(x, y, w, S(22)), note, 15, W_.Medium, self.a(0.8))
        y += S(34)
        tracks = self.artist_tops((got or arg).get("name", ""),
                                  [dict(t, kind="track", _ctx=uri) for t in (got or {}).get("tracks") or []], uri)
        item = dict(got or arg, kind="artist", tracks=tracks)
        b = self.button(p, x, y, "Play", "play_item", item, icon="play", style="primary")
        b = self.button(p, b.right() + S(8), y, "Shuffle", "shuffle_item", item, icon="shuffle")
        b = self.button(p, b.right() + S(8), y, f"Mix from {name}" if len(name) < 24 else "Mix", "act",
                        ("mix", dict(got or arg, kind="artist", name=name)), icon="shuffle")
        fol = dict(got or arg, kind="artist")
        saved = self.follows(fol)
        self.button(p, b.right() + S(8), y, "Following" if saved else "Follow", "act", ("follow", fol),
                    icon="check" if saved else "plus")
        y = max(band.bottom(), y + S(40)) + S(28)
        if got is None:
            return self.empty(p, x, y, w, f"No artist called {name} in the catalogue." if missing else "Loading…")
        two = self.bp in ("L", "M")
        lw = w * 0.58 if two else w
        rw = w - lw - S(24) if two else w
        for i, t in enumerate(tracks):
            pl = self.log.plays_of(t["name"], name)
            t["_n"] = i + 1
            t["_end"] = f"{pl} play{'s' if pl != 1 else ''}" if pl else self.fmt(t.get("ms", 0))
            said = ", ".join(self.spelt(a) for a in PLG.artists_of(t.get("sub", "")))
            if said != t.get("sub", ""):
                t["_shown"] = said                   # shown only; `sub` stays the catalogue's
        top_y = y
        hot = self.hot("top_songs", item)
        tw = self.text(p, QRectF(x + S(24), y + S(18), lw, S(28)), "Top songs", 19, W_.Black)
        self.icon(p, "right", QRectF(x + S(28) + tw, y + S(24), S(16), S(16)), INK if hot else self.a(0.55))
        if hot:
            p.fillRect(QRectF(x + S(24), y + S(44), tw, S(1.5)), INK)
        self.hit("top_songs", item, QRectF(x + S(16), y + S(12), tw + S(36), S(40)))
        self.text(p, QRectF(x, y + S(18), lw - S(24), S(28)), "Your plays", 13.5, W_.Medium, self.a(0.55),
                  Qt.AlignmentFlag.AlignRight)
        plays = any(t.get("plays_text") for t in tracks[:6])
        ty = self.table(p, x, y + S(40), lw, [dict(t, _x=[t.get("plays_text", "")]) for t in tracks[:6]] if plays
                        else tracks[:6], extra=["PLAYS"] if plays else (), panel=False)
        self.rr(p, QRectF(x, top_y, lw, ty - top_y), S(14), self.a(0.04), self.a(0.10))
        ry = top_y if two else ty + S(24)
        rx = x + lw + S(24) if two else x
        rh = self.artist_lyrics(p, rx, ry, rw, name, tracks)
        y = max(ty, rh) + S(30)
        albums = [a for a in (got or {}).get("albums") or [] if a.get("type") != "single"]   # a single is no album
        cols = {"L": 6, "M": 4, "S": 3, "XS": 2}[self.bp]
        if albums:
            y = self.head(p, x, y, w, "Albums")
            y = self.tiles(p, x, y, w, [dict(a, sub=str(a.get("year", ""))) for a in albums], cols, max_rows=2) + S(10)
        rel = (got or {}).get("related") or []
        if rel:
            heard = self.log.heard_artists()
            rel = [dict(a, sub="In your rotation" if a["name"].lower() in heard else "New to you") for a in rel]
            y = self.head(p, x, y, w, "Fans also play", "Ones you already play are marked")
            y = self.tiles(p, x, y, w, rel, cols, round_=True, max_rows=1)
        return y

    def artist_tops(self, name: str, cat: list, uri: str = "") -> list:
        """An artist's top songs: YouTube Music's order and plays (SS.yt_artist_top), each as the
        catalogue's copy when it has one, then the catalogue's own top songs. Deezer's put a new
        single first and left out Second & Sebring (2026-10-25)."""
        if not name:
            return cat
        self.yt.artist_top(name)
        yt = (self.yt.get("top:youtube:" + name) or {}).get("tracks") or []
        if not yt:
            return cat
        mine = {SS.norm(t.get("name", "")): t for t in cat}
        out, used = [], set()
        for t in yt:
            key = SS.norm(t["name"])
            if key in used:
                continue
            used.add(key)
            c = mine.get(key)
            out.append(dict(c, plays_text=t["plays_text"]) if c else dict(t, _ctx=uri) if uri else dict(t))
        return out + [t for t in cat if SS.norm(t.get("name", "")) not in used]

    def page_artist_top(self, p, x, y, w, L) -> float:
        """An artist's top songs in full, from the artist page's Top songs heading."""
        S = self.S
        arg = self.arg or {}
        uri = arg.get("uri", "")
        got = self.src(uri).get("artist:" + uri) if uri else None
        cat_name = (got or arg).get("name", "")
        y = self.backlink(p, x, y) + S(24)
        y = self.title(p, x, y, w, "Top songs", self.spelt(cat_name)) + S(16)
        tracks = self.artist_tops(cat_name, [dict(t, kind="track", _ctx=uri) for t in (got or {}).get("tracks") or []],
                                  uri)
        # most played first (2026-10-25); YouTube's order breaks ties ("29M" and "29M"), songs without a count last
        tracks.sort(key=lambda t: -SS.plays_of(t.get("plays_text", "")))
        item = dict(got or arg, kind="artist", tracks=tracks)
        b = self.button(p, x, y, "Play", "play_item", item, icon="play", style="primary")
        self.button(p, b.right() + S(8), y, "Shuffle", "shuffle_item", item, icon="shuffle")
        y += S(64)
        if not tracks:
            return self.empty(p, x, y, w, "Loading…" if got is None else f"No top songs for {cat_name}.")
        plays = any(t.get("plays_text") for t in tracks)
        rows = [dict(t, _n=i + 1, _x=([t.get("plays_text", "")] if plays else []) + [t.get("album", "")])
                for i, t in enumerate(tracks)]
        return self.table(p, x, y, w, rows, extra=(["PLAYS"] if plays else []) + ["ALBUM"], ctx_uri=uri)

    def spelt(self, name: str) -> str:
        """An artist's name as the player writes it ("shambles") where the catalogue
        capitalises it ("Shambles"): the playing song's credits, else the play log's."""
        low = name.lower()
        for a in self.v.credits() or []:
            if a.get("name", "").lower() == low:
                return a["name"]
        if getattr(self, "_spell_rev", None) != self.log.rev:
            self._spell = {a.lower(): a for r in self.log.load() for a in PLG.artists_of(r.get("artist", ""))}
            self._spell_rev = self.log.rev
        return self._spell.get(low, name)

    def artist_lyrics(self, p, x, y, w, name: str, tracks: list) -> float:
        S = self.S
        known = [(t, self.kind_of(t)) for t in tracks]
        played = [(t, k) for t, k in known if k is not None]
        wbw = sum(1 for _t, k in played if k == "w")
        line_only = [t for t, k in played if k in ("l",)]
        h = S(140) + min(3, len(line_only)) * S(38) + S(20)
        self.rr(p, QRectF(x, y, w, h), S(14), self.a(0.06), self.a(0.10))
        self.text(p, QRectF(x + S(24), y + S(20), w - S(48), S(28)), f"Lyrics for {name}", 19, W_.Black)
        if played:
            note = (f"Word-by-word for {wbw} of the {len(played)} top songs with lyrics here."
                    + (f" {len(line_only)} have line timing only." if line_only else ""))
        else:
            note = "None of the top songs has lyrics on this computer yet; they are fetched as they play."
        nh = self.wrap(p, x + S(24), y + S(52), w - S(48), note, 14, W_.Medium, self.a(0.75), rows=3)
        bar = QRectF(x + S(24), y + S(60) + nh, w - S(48), S(6))
        self.rr(p, bar, S(3), self.a(0.10))
        if played:
            self.rr(p, QRectF(bar.x(), bar.y(), bar.width() * wbw / len(played), bar.height()), S(3),
                    self.accent()[1])
        yy = bar.bottom() + S(18)
        for t in line_only[:3]:
            self.text(p, QRectF(x + S(24), yy, w - S(110), S(30)), t["name"], 15, W_.DemiBold)
            self.badge(p, x + w - S(24), yy + S(15), "Line", right=True)
            p.fillRect(QRectF(x + S(24), yy + S(34), w - S(48), 1), self.a(0.08))
            yy += S(38)
        return y + h

    def who(self, it: dict) -> str:
        """Its artists as shown, "A, B & C"; the data keeps "A, B" (song_key reads it)."""
        if it.get("_shown"):
            return it["_shown"]
        sub = it.get("sub") or it.get("artist") or ""
        names = [a.get("name", "") if isinstance(a, dict) else str(a) for a in it.get("artists") or []]
        names = [n for n in names if n]
        if len(names) > 1 and it.get("kind") in (None, "track", "local", "song") and sub == ", ".join(names):
            return join_names(names)
        return sub

    def is_current(self, arg: dict) -> bool:
        """This song is the one playing, by its uri or its track id (a Deezer row's, by name)."""
        tid = tid_of_uri(arg.get("uri", "")) or self.tid_by_name(arg)
        return self.is_playing(arg) or bool(tid) and tid == (self.v.clock.tid or "")

    def fetch_source(self, arg: dict, tid: str, name: str, cur: bool) -> None:
        """One source's lyrics for this song, to compare with the ones in use."""
        import threading
        key = f"src|{tid}|{name}"
        self.words[key] = None
        v = self.v
        meta = dict(v.clock.meta or {}) if cur else {
            "title": arg.get("name", ""), "artist": arg.get("sub", ""), "album": arg.get("album", ""),
            "length": (arg.get("ms") or 0) / 1000.0}
        split, threshold = v.lyric_split()

        def work():
            got = {"lines": [], "source": name, "tid": tid, "kind": ""}
            try:
                import lyric_sources as LS
                import spicy_lyrics as SL
                fn = dict(LS.PROVIDERS).get(name)
                doc = LS._asks(name, lambda: fn(tid, meta), tid) if fn else None
                if isinstance(doc, dict):
                    shaped = v.fetcher.shaped_copy(doc)       # as the lyrics view would draw it
                    got.update(lines=SL.timeline(shaped, split=split, threshold=threshold), kind=LS.quality(doc))
            except Exception as e:                          # noqa: BLE001
                got["error"] = str(e)[:120]
            self.words_ready.emit(key, got)
        threading.Thread(target=work, daemon=True, name="lyrics-compare").start()

    def song_lines(self, arg: dict, cur: bool) -> tuple[list[dict], str, str]:
        """(lines, source label, track id) for a song's page: the playing song's own,
        else its lyrics fetched as the page opened (the same walk as playing would)."""
        v = self.v
        if cur and v.lines:
            return [ln for ln in v.lines if (ln.get("text") or "").strip()], v.lyric_source_label(), v.clock.tid or ""
        key = arg.get("uri") or (arg.get("name", "") + "|" + arg.get("sub", ""))
        got = self.words.get(key)
        if key not in self.words:
            self.fetch_words(arg)
            return [], "", ""
        if got is None:
            return [], "", ""
        src = got.get("source", "")
        label = {"spicy": "Spicy Lyrics", "apple": "Apple Music"}.get(src, src)
        return [ln for ln in got.get("lines") or [] if (ln.get("text") or "").strip()], label, got.get("tid", "")

    @staticmethod
    def is_single(arg: dict) -> bool:
        """A release that is the song on its own: "LV Sandals - Single" for "LV Sandals"."""
        album, title = arg.get("album") or "", arg.get("name") or arg.get("title") or ""
        if re.search(r"\s-\s(single|ep)$", album, re.I):
            return bool(re.search(r"\s-\ssingle$", album, re.I)) or SS.norm(album[:album.rfind(" - ")]) == SS.norm(title)
        return bool(album) and SS.norm(album) == SS.norm(title)

    def page_song(self, p, x, y, w, L) -> float:
        S, v = self.S, self.v
        arg = self.arg or {}
        y = self.backlink(p, x, y)
        cur = self.is_current(arg)
        bits = []
        artists = arg.get("artists") or [{"name": n.strip(), "uri": ""}
                                           for n in (arg.get("sub") or "").split(",") if n.strip()]
        for i, a in enumerate(artists):
            if i:
                bits.append(" & " if i == len(artists) - 1 else ", ")
            bits.append({"kind": "artist", "uri": a.get("uri", ""), "name": a.get("name", "")})
        if arg.get("album"):
            if self.is_single(arg):
                bits.append(" · Single")
            else:
                bits += [" · ", {"kind": "album", "uri": arg.get("album_uri", ""), "name": arg["album"],
                                 "sub": artists[0]["name"] if artists else "", "art": arg.get("art", "")}]
        pl = self.log.plays_of(arg.get("name", ""), (arg.get("sub") or "").split(",")[0])
        extra = [b for b in (self.fmt(arg.get("ms", 0)),
                             (f"you’ve played it {pl} time{'s' if pl != 1 else ''}" if pl else "")) if b]
        if extra:
            bits.append(" · " + " · ".join(extra))
        by, tx, bottom = self.hero(p, x, y, w, arg.get("art", ""), "SONG", arg.get("name", ""), bits)
        b = self.button(p, tx, by, "Play", "play_item", arg, icon="play", style="primary")
        b = self.button(p, b.right() + S(8), by, "Open lyrics", "act", ("lyrics", arg), icon="mic", style="accent")
        b = self.button(p, b.right() + S(8), by, "Make a queue from this song", "act", ("radio", arg), icon="shuffle")
        b = self.button(p, b.right() + S(8), by, "Add to queue", "queue_item", arg, icon="plus")
        if self.likeable(dict(arg, kind=arg.get("kind") or "track")):
            on = self.is_liked(arg)
            b = self.button(p, b.right() + S(8), by, "Liked" if on else "Like", "heart", arg,
                            icon="heartF" if on else "heart")
        if b.right() + S(210) < x + w:
            self.button(p, b.right() + S(8), by, "Time in the editor", "act", ("editor", arg), icon="pen")
        else:                                               # no room left: a row of its own
            by += S(48)
            self.button(p, tx, by, "Time in the editor", "act", ("editor", arg), icon="pen")
        y = max(bottom, by + S(40)) + S(30)
        two = self.bp in ("L", "M")
        lw = w * 0.58 if two else w
        rw = w - lw - S(24) if two else w
        top = y
        lines, src, tid = self.song_lines(arg, cur)
        kind = self.kind_of(arg)
        skey = arg.get("uri") or (arg.get("name", "") + "|" + arg.get("sub", ""))
        shown = self.src_show.get(skey)
        asking = False
        if shown and tid:
            k = f"src|{tid}|{shown[0]}"
            if k not in self.words:
                self.fetch_source(arg, tid, shown[0], cur)
            got = self.words.get(k)
            asking = got is None
            lines = [ln for ln in (got or {}).get("lines") or [] if (ln.get("text") or "").strip()]
            src = shown[1]                    # "Showing" in Sources says it is a comparison
            kind = {"syllable": "w", "line": "l"}.get((got or {}).get("kind", ""), "")
        self._song_shown = lines
        fm = self.fm(15.5, W_.Bold)
        rows_h = sum(S(32) if not ln.get("background") else S(24) for ln in lines)
        lh = S(80) + (rows_h if lines else S(32)) + S(20)
        self.rr(p, QRectF(x, y, lw, lh), S(14), self.a(0.05), self.a(0.10))
        self.text(p, QRectF(x + S(24), y + S(20), S(90), S(28)), "Lyrics", 19, W_.Black)
        if lines:
            cb = self.button(p, x + lw - S(20), y + S(16), "Copy lyrics", "act", ("copy_all", lines), icon="list",
                             h=32, px=14, right=True)
            note_w = cb.x() - (x + S(100)) - S(10)
        else:
            note_w = lw - S(124)
        self.text(p, QRectF(x + S(100), y + S(22), note_w, S(26)),
                  " · ".join(b for b in (src, {"w": "word-by-word", "l": "line timing", "r": "romanised"}.get(
                      kind or "", ""), "right-click a line to copy it" if lines else "") if b),
                  13.5, W_.Medium, self.a(0.55))
        yy = y + S(64)
        if lines:
            mid = -1
            st = self.mini_state() if cur else None
            if st:
                # By time, not by text: a repeated chorus lit its first copy and dimmed all before it.
                pos = st[3]
                for i, ln in enumerate(lines):
                    if not ln.get("background") and ln.get("start") is not None and ln["start"] <= pos:
                        mid = i
            _acc, light = self.accent()
            for i, ln in enumerate(lines):
                t = ln.get("text", "")
                bg = bool(ln.get("background"))
                rh = S(24) if bg else S(32)
                r = QRectF(x + S(14), yy, lw - S(28), rh)
                if self.vis(r):
                    if self.hot("lyr_line", (i, t)):
                        self.rr(p, r, S(6), self.a(0.06))
                    on = i == mid
                    duet = bool(ln.get("opposite"))     # the second voice on the other side, as the lyrics view has it
                    ind = S(16) if bg else 0
                    self.text(p, QRectF(r.x() + S(10) + (0 if duet else ind), r.y(), r.width() - S(20) - ind, rh), t,
                              13.5 if bg else (17 if on else 15.5), W_.Bold if bg else (W_.Black if on else W_.Bold),
                              light if on else self.a(0.4 if bg else (0.5 if cur and i < mid else 0.75)),
                              Qt.AlignmentFlag.AlignRight if duet else Qt.AlignmentFlag.AlignLeft)
                    self.hit("lyr_line", (i, t), r)
                yy += rh
        else:
            fetching = not cur and skey in self.words and self.words.get(skey) is None
            if shown and tid:
                say = f"Asking {shown[1]}…" if asking else f"{shown[1]} has no lyrics for this song."
            else:
                say = "Looking for its lyrics…" if fetching else "No lyrics were found for this song."
            self.wrap(p, x + S(24), yy, lw - S(48), say, 14.5, W_.Medium, self.a(0.55))
        ry = top if two else top + lh + S(24)
        rx = x + lw + S(24) if two else x
        rh = self.song_sources(p, rx, ry, rw, tid if not cur else None, shown[0] if shown and tid else None, tid)
        y = max(top + lh, ry + rh) + S(30)
        a0 = (arg.get("artists") or [{}])[0]
        if a0.get("uri"):
            ag = self.src(a0["uri"]).get("artist:" + a0["uri"])
            sim = []
            for rel in (ag or {}).get("related", [])[:6]:
                rg = self.src(rel["uri"]).get("artist:" + rel["uri"])
                if rg is None:
                    self.src(rel["uri"]).artist(rel["uri"])
                    continue
                if rg.get("tracks"):
                    sim.append(dict(rg["tracks"][0], kind="track", why=f"Near {a0.get('name', '')}"))
            if sim:
                y = self.head(p, x, y, w, f"If you like {arg.get('name', '')}", "From artists near this one")
                cols = {"L": 6, "M": 4, "S": 3, "XS": 2}[self.bp]
                y = self.tiles(p, x, y, w, sim, cols, max_rows=1)
        return y

    def song_sources(self, p, x, y, w, tid, shown=None, real: str = "") -> float:
        """Where the lyrics came from, what every other source asked had (its sync), and the
        sources not asked yet. A click on one fetches and shows its lyrics in the Lyrics card,
        to compare (`shown`); Use makes the one shown this song's source (`real`: its track id)."""
        S, v = self.S, self.v
        real = real or tid or ""
        try:
            rows = v.source_rows_for_home(tid) if tid != "" else []
        except Exception:                                   # noqa: BLE001
            rows = []

        def tall(r) -> float:
            return S(56) if r.get("on") or r.get("kind") else S(40)
        h = S(72) + (sum(tall(r) for r in rows) if rows else S(56)) + S(10)
        self.rr(p, QRectF(x, y, w, h), S(14), self.a(0.05), self.a(0.10))
        self.text(p, QRectF(x + S(24), y + S(20), S(120), S(28)), "Sources", 19, W_.Black)
        if rows and real and any(r.get("picked") for r in rows):
            fm = self.fm(13, W_.Bold)
            say = "your pick · back to auto"
            ar = QRectF(x + w - S(24) - fm.horizontalAdvance(say), y + S(24), fm.horizontalAdvance(say), S(22))
            self.text(p, ar, say, 13, W_.Bold, self.a(0.8 if self.hot("src_auto", real) else 0.5),
                      Qt.AlignmentFlag.AlignRight, elide=False)
            self.hit("src_auto", real, ar.adjusted(-S(6), -S(4), S(6), S(4)))
        elif rows:
            self.text(p, QRectF(x + S(120), y + S(24), w - S(144), S(22)), "click one to compare", 13,
                      W_.Medium, self.a(0.45), Qt.AlignmentFlag.AlignRight)
        yy = y + S(62)
        if not rows:
            self.wrap(p, x + S(24), yy, w - S(48), "Shows once this song's lyrics have been looked for.",
                      14, W_.Medium, self.a(0.55))
        good = {"syllable": INK, "line": self.a(0.8)}
        for r in rows:
            rh = tall(r)
            row = QRectF(x + S(10), yy - S(6), w - S(20), rh - S(2))
            if not self.vis(row):
                yy += rh
                continue
            on_show = r["key"] == shown if shown else bool(r.get("on"))
            if on_show or self.hot("src_pick", (r["key"], r["name"], bool(r.get("on")))):
                self.rr(p, row, S(9), self.a(0.08 if on_show else 0.05))
            self.hit("src_pick", (r["key"], r["name"], bool(r.get("on"))), row)
            badge = ("Showing" if shown and r["key"] == shown and not r.get("on") else
                     "In use" if r.get("on") else "")
            got = self.words.get(f"src|{real}|{r['key']}") if real and badge == "Showing" else None
            # it had a sync when asked, or what it has is on screen: it can be the one
            usable = bool(real) and not r.get("on") and (bool(got and got.get("lines"))
                                                        or r.get("kind") in ("syllable", "line"))
            room = S(72) if usable and badge else 0
            if rh < S(56):                                  # not asked yet: one line
                self.text(p, QRectF(x + S(24), yy, w - S(160) - room, S(28)), r["name"], 14.5, W_.Bold,
                          self.a(0.6))
                if not badge:
                    self.text(p, QRectF(x + S(24), yy, w - S(48), S(28)), "Fetch", 13, W_.Bold,
                              self.a(0.75 if self.hot("src_pick", (r["key"], r["name"], False)) else 0.4),
                              Qt.AlignmentFlag.AlignRight)
            else:
                self.text(p, QRectF(x + S(24), yy, w - S(140) - room, S(24)), r["name"], 15.5, W_.Bold,
                          INK if r.get("on") or r.get("kind") in ("syllable", "line") else self.a(0.6))
                self.text(p, QRectF(x + S(24), yy + S(23), w - S(140) - room, S(20)), r["note"], 13, W_.Medium,
                          good.get(r.get("kind"), self.a(0.45)) if not r.get("on") else self.a(0.62))
            if badge == "In use":
                b_ = QRectF(x + w - S(20) - S(76), yy + S(6), S(76), S(30))
                self.rr(p, b_, S(8), INK)
                self.text(p, b_, "In use", 14, W_.Bold, DARK, Qt.AlignmentFlag.AlignHCenter)
            elif badge:
                b_ = QRectF(x + w - S(20) - S(92), yy + (S(6) if rh >= S(56) else S(-1)), S(92), S(30))
                self.rr(p, b_, S(8), None, self.a(0.5))
                self.text(p, b_, "Showing", 14, W_.Bold, INK, Qt.AlignmentFlag.AlignHCenter)
            if usable:
                use = (real, r["key"], r["name"])
                u_ = QRectF((b_.x() - S(8) if badge else x + w - S(20)) - S(64), b_.y() if badge else yy + S(6), S(64), S(30))
                self.rr(p, u_, S(8), QColor(255, 255, 255) if self.hot("src_use", use) else INK)
                self.text(p, u_, "Use", 14, W_.Bold, DARK, Qt.AlignmentFlag.AlignHCenter)
                self.hit("src_use", use, u_)
            yy += rh
        return h

    def page_words(self, p, x, y, w, L) -> float:
        """A song's lyrics read through, for a song that is not playing."""
        S = self.S
        arg = self.arg or {}
        y = self.backlink(p, x, y)
        key = arg.get("uri") or (arg.get("name", "") + "|" + arg.get("sub", ""))
        got = self.words.get(key)
        side = S(96)
        self.cover(p, QRectF(x, y, side, side), arg.get("art", ""), S(8), arg.get("name", ""))
        tx = x + side + S(20)
        self.text(p, QRectF(tx, y + S(4), w - side, S(20)), "LYRICS", 13, W_.Bold, self.a(0.62))
        self.text(p, QRectF(tx, y + S(22), w - side - S(20), S(40)), arg.get("name", ""), 30, W_.Black)
        src = (got or {}).get("source", "")
        label = {"spicy": "Spicy Lyrics", "apple": "Apple Music"}.get(src, src)
        self.text(p, QRectF(tx, y + S(62), w - side - S(20), S(22)),
                  " · ".join(b for b in (arg.get("sub", ""), label) if b), 15, W_.Medium, self.a(0.62))
        by = y + side + S(18)
        b = self.button(p, x, by, "Play", "play_item", arg, icon="play", style="primary")
        if self.other_player(arg):
            lbl, ic, act = self.other_player(arg)
            self.button(p, b.right() + S(8), by, lbl, "ctxdo", (act, arg), icon=ic)
        y = by + S(64)
        if got is None:
            return self.empty(p, x, y, w, "Looking for its lyrics…")
        tid = got.get("tid", "")
        two = self.bp in ("L", "M")
        rw = min(S(380), w * 0.38) if two else w
        lw = w - rw - S(32) if two else w
        side = y
        if tid:                                       # every source, to compare with the one picked
            if two:
                side = y + self.song_sources(p, x + lw + S(32), y, rw, tid, (self.src_show.get(key) or (None,))[0])
            else:
                y += self.song_sources(p, x, y, w, tid, (self.src_show.get(key) or (None,))[0]) + S(24)
        lines = got.get("lines") or []
        shown = self.src_show.get(key)
        if shown and tid:
            k = f"src|{tid}|{shown[0]}"
            if k not in self.words:
                self.fetch_source(arg, tid, shown[0], False)
            alt = self.words.get(k)
            if alt is None:
                return max(side, self.empty(p, x, y, lw, f"Asking {shown[1]}…"))
            lines = alt.get("lines") or []
            if not lines:
                return max(side, self.empty(p, x, y, lw, f"{shown[1]} has no lyrics for this song."))
        if not lines:
            return max(side, self.empty(p, x, y, lw, "No lyrics were found for this song." if not got.get("error")
                                        else f"Could not look: {got['error']}"))
        _acc, light = self.accent()
        for ln in lines:
            t = (ln.get("text") or "").strip()
            if not t or ln.get("credits"):
                continue
            bg = bool(ln.get("background"))
            px = 17 if bg else 26
            duet = bool(ln.get("opposite"))         # the second voice on the other side, as the lyrics view has it
            h = self.wrap(p, x + (S(18) if bg != duet else 0), y, lw - S(18), t, px, W_.Bold if bg else W_.Black,
                          self.a(0.55) if bg else self.a(0.88), rows=4, lh=1.25,
                          align=Qt.AlignmentFlag.AlignRight if duet else Qt.AlignmentFlag.AlignLeft)
            y += h + (S(4) if bg else S(14))
        return max(side, y + S(20))

    def backlink(self, p, x, y) -> float:
        S = self.S
        prev = self.stack[-1][0] if self.stack else "home"
        label = TITLES.get(prev, prev.title()) if prev != "home" else "Home"
        if not self.stack and getattr(self, "from_lyrics", False):
            label = "Lyrics"
        fm = self.fm(14.5, W_.DemiBold)
        r = QRectF(x, y, fm.horizontalAdvance(label) + S(44), S(32))
        self.rr(p, r, S(8), self.a(0.16 if self.hot("back") else 0.10))
        self.icon(p, "back", QRectF(r.x() + S(10), r.center().y() - S(8), S(16), S(16)))
        self.text(p, QRectF(r.x() + S(30), r.y(), r.width() - S(34), r.height()), label, 14.5, W_.DemiBold,
                  elide=False)
        self.hit("back", None, r)
        return r.bottom() + S(26)

    # =========================================================== clicks
    def click_page(self, kind: str, payload, pos=None) -> None:
        v = self.v
        if kind == "item" and payload.get("_qi") is not None and self.player.active:
            pl = self.player
            if 0 <= payload["_qi"] < len(pl.queue) and payload["_qi"] != pl.idx:
                pl.idx = payload["_qi"]
                pl.ended = False
                pl._load()
            return
        if kind == "item":
            it = payload
            k = it.get("kind")
            if k == "file":
                self.play_by_name(it.get("name", ""), it.get("sub", ""))
            elif k == "song":
                self.play_by_name(it.get("name", ""), it.get("sub", ""))
            elif k == "genius":
                v.gq_matching = it["genius"]
                v.fetcher.request_gmatch(it["genius"])
                self.say("Finding it on Spotify…")
            elif k == "local" and any(r.get("kind") != "local" for r in it.get("_list") or []):
                self.play_here(it, it.get("_list"))
            elif k == "local":
                ctx = it.get("_list") or [it]
                self.play_local(it, ctx)
            elif k == "track" and it.get("_q"):
                v.fetcher.request_skip(it.get("uri", ""), it.get("uid", ""))
            elif k == "track":
                self.play(it, context=it.get("_list"), ctx_uri=it.get("_ctx", ""))
            else:
                self.open_item(it)
        elif kind == "lyr_line":
            i, _t = payload
            arg = self.arg or {}
            lines = getattr(self, "_song_shown", [])
            if 0 <= i < len(lines) and lines[i].get("start") is not None:
                at = float(lines[i]["start"])
                if self.is_current(arg):
                    v.seek_song(at + v.track_offset())
                else:
                    self.play_from(arg, at)
        elif kind == "src_pick":
            name, label, on = payload
            arg = self.arg or {}
            skey = arg.get("uri") or (arg.get("name", "") + "|" + arg.get("sub", ""))
            if on or (self.src_show.get(skey) or ("",))[0] == name:
                self.src_show.pop(skey, None)          # back to the lyrics in use
            else:
                self.src_show[skey] = (name, label)
            v.update()
        elif kind in ("src_use", "src_auto"):
            import lyric_sources as LS
            tid, name, label = payload if kind == "src_use" else (payload, "", "")
            LS.pick_for_song(tid, name)
            arg = self.arg or {}
            skey = arg.get("uri") or (arg.get("name", "") + "|" + arg.get("sub", ""))
            self.src_show.pop(skey, None)
            if tid == (v.clock.tid or ""):
                v.reset_track("Switching lyrics…", keep=True)
            else:
                self.words.pop(skey, None)              # the page's copy, asked again with the pick
            v.toast(f"{label} for this song from now on" if name else "this song's lyrics picked as usual again")
            v.update()
        elif kind == "dismiss":
            self.hide(payload)
        elif kind == "link":
            self.open_item(payload)
        elif kind == "top_songs":
            self.go("artist_top", payload)
        elif kind == "back":
            if not self.back():
                self.go("home", push=False)
        elif kind == "mode":
            v.home_mode = payload
            self.build_recs()
        elif kind == "stab":
            self.search_tab = payload
            self.sel = -1
        elif kind == "stat_per":
            self.stat_per = payload
        elif kind == "recent_q":
            v.bq_field.set_text(payload)
            self.search_changed()
            self.run_search()
        elif kind.startswith("filter:"):
            self.filters[kind[7:]] = payload
            if kind == "filter:charts":
                self.cat.chart(payload)
        elif kind == "play_item":
            it = payload
            if it.get("kind") == "local":
                self.play_local(it, [it])
            elif it.get("uri") == "liked":
                self.play_here(it, shuffle=False)
            elif it.get("kind") in ("artist",) and not it.get("uri"):
                rows = it.get("tracks") or []
                if rows:
                    self.play(rows[0], context=rows)
            else:
                self.play(it)
        elif kind == "shuffle_item":
            if self.play_in() == "mild" or (payload.get("uri") or "").startswith("deezer:"):
                self.play_here(payload, shuffle=True)
            else:
                self.spot.shuffle(True)
                self.play(payload)
        elif kind == "queue_item":
            self.queue(payload)
        elif kind == "pl_rm":
            self.pl_remove(payload)
        elif kind == "act":
            self.page_act(payload)
        elif kind == "ctxdo":
            act, it = payload
            self.ctx = {"item": it, "x": 0, "y": 0}
            self.ctx_do(act)

    def page_act(self, what) -> None:
        v = self.v
        if isinstance(what, tuple):
            k, arg = what
            if k == "follow":
                self.follow({k2: arg.get(k2) for k2 in ("uri", "name", "art", "kind", "sub", "year")})
            elif k == "lyrics":
                self.open_words(arg)
            elif k == "copy_all":
                self.copy_lyrics(arg)
            elif k == "radio":
                self.song_radio(arg)
            elif k == "editor":
                self.time_in_editor(arg)
            elif k == "mix":
                self.artist_mix(arg)
            return
        if what == "clear_q":
            v.bq_field.set_text("")
            self.search_changed()
        elif what == "clear_queue":
            if self.player.active:
                self.player.queue = self.player.queue[:self.player.idx + 1]
            else:
                self.spot.queue_clear()
            self.say("Queue cleared")
        elif what == "open_folder":
            QDesktopServices.openUrl(QUrl.fromLocalFile(noconsole.real_path(saves.chosen(v.save_fetched_dir).parent)))
        elif what == "add_folder":
            self.add_folder()
        elif what == "new_pl":
            self.new_playlist()
        elif what == "pl_edit":
            self.pl_edit = not self.pl_edit
        elif what == "pl_rename":
            pid = (self.arg or {}).get("uri", "").rsplit(":", 1)[-1]
            name = v.ask_text("Rename playlist", "Name")
            if name:
                self.library.rename(pid, name)
                self.arg = self.pl_item(self.library.playlist(pid))
        elif what == "pl_delete":
            pid = (self.arg or {}).get("uri", "").rsplit(":", 1)[-1]
            at = next((i for i, x in enumerate(self.library.playlists()) if x["id"] == pid), 0)
            gone = self.library.delete(pid)
            if gone:
                self.pl_edit = False
                self.go("playlists", push=False)
                self.say(f"Deleted “{gone['name']}”", lambda: self.library.restore(gone, at))
        elif what == "go_local":
            self.go("local")
        elif what == "go_follow":
            self.popover = True
        elif what == "port_help":
            v.show_port_help()
        elif what == "banner_off":
            self._banner_off = True
        elif what == "main_mild":
            was = v.home_main
            v.home_main = "Mild Lyrics"
            v.autosave()

            def undo():
                v.home_main = was
                v.autosave()
            self.say("Main player: Mild Lyrics · Settings ▸ Home changes it", undo)
        elif what == "go_local":
            self.go("local")
        elif what == "players":
            self.popover = True
        elif what == "this_song":
            self.go("song", self.np_item_full())

    def np_item_full(self) -> dict:
        it = self.np_item()
        album = (self.v.albums or {}).get(self.v.clock.tid or "") or {}
        if album.get("uri"):
            it["album_uri"] = album["uri"]
        return it

    def add_folder(self) -> None:
        from PyQt6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(self.v, "A folder with your music", str(pathlib.Path.home() / "Music"))
        if not d:
            return
        dirs = self.local_dirs()
        if d not in dirs:
            dirs.append(d)
        self.v.home_local_dirs = "\n".join(dirs)
        self.lib.set_dirs(dirs)
        self.lib.scan()
        self.v.autosave()
        self.say(f"Looking for songs in {os.path.basename(d) or d}…")

    def play_local(self, it: dict, ctx: list) -> None:
        tracks = [r.get("_track") or r for r in ctx if r.get("kind") == "local"]
        i = next((n for n, r in enumerate(ctx) if r is it), 0)
        if self.player.play(tracks, i):
            self.pause_spotify()
        else:
            self.say("Qt Multimedia is not available, so files cannot play here")

    def play_by_name(self, title: str, artist: str) -> None:
        """A song known only by name: one of the local files, else where songs play (Spotify's
        first match, or streamed here when Spotify is away or finds nothing)."""
        key = (title.lower(), artist.lower())
        for t in self.lib.tracks:
            if (t.get("title", "").lower(), t.get("artist", "").lower()) == key:
                self.play_local({"kind": "local", "_track": t}, [{"kind": "local", "_track": t}])
                return
        if not self.can_play():
            return
        item = {"kind": "track", "name": title, "sub": artist}
        if self.play_in() == "mild" or not self.online:
            self.play_here(item)
            return
        q = f"{title} {(credit_names(artist) or [''])[0]}".strip()
        self.v.home_q = (q, item)
        self.v.fetcher.request_catsearch(q)
        self.say(f"Looking for “{title}” on Spotify…")

    def found_by_name(self, item: dict, results) -> None:
        """Spotify's answer to play_by_name: its first song, else the song streamed here."""
        song = next((r for r in results or [] if r.get("kind") == "Track" and r.get("uri")), None)
        if song is None:
            self.say(f"“{item.get('name', '')}” is not on Spotify: playing it in Mild Lyrics")
            self.play_here(item)
            return
        if self.player.active:
            self.player.stand_down()
        self.v.fetcher.request_play(song["uri"])
        self.say(f"Playing {song.get('name') or 'it'}")

    def play_from(self, item: dict, at: float) -> None:
        """Play a song that is not playing, from `at` (a line clicked on its page)."""
        self.play(dict(item, kind=item.get("kind") or "track"))
        self._seek_when = (item, at, time.monotonic() + 30.0)


def tid_of_uri(uri: str) -> str:
    return (uri or "").split(":")[-1] if (uri or "").startswith("spotify:track:") else ""
