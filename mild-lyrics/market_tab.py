"""The drawer's Plugins tab: the marketplace, drawn the way the drawer is.

LyricsView holds one (view.market) and hands it the tab's paint, presses,
wheel and keys; everything is drawn with the view's own drawer helpers, and
questions go through view.ask, so nothing here opens a window of its own.
"""

from __future__ import annotations

import collections
import threading
import zlib

from PyQt6.QtCore import QObject, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetricsF

import keymap as KM
import plugins as PL
import plugin_store as ST

SHOWS = ("All", "Installed", "Updates")
SORTS = {"Popular": "Most downloaded", "New": "Recently updated", "A–Z": "Name"}
GREEN = QColor(130, 214, 160)
BLUE = QColor(140, 186, 255)
RED = QColor(240, 150, 140)


class _Relay(QObject):
    listed = pyqtSignal()
    fetched = pyqtSignal(str, object, str)          # id, bytes, error


class MarketTab:
    def __init__(self, view, field_cls, wrap_rows) -> None:
        self.view = view
        self.wrap = wrap_rows
        self.query = field_cls(limit=60)
        self.searching = False
        self.show = "All"
        self.sort = "Popular"
        self.notes: dict = {}                       # id -> error text
        self.working: set = set()
        self.relay = _Relay()                       # held: see its signals
        self.relay.listed.connect(self._changed)
        self.relay.fetched.connect(self._fetched)
        self._asks: collections.deque = collections.deque()
        ST._window = self

    # -- reached from plugin_store
    def in_window(self) -> bool:
        return not self.view.classic()

    def open(self) -> None:
        v = self.view
        v.show_menu, v.dr_tab, v.dr_sel = True, "plugins", None
        v.dr_kscroll = 0.0
        self.load()
        v.update()

    def load(self, force: bool = False) -> None:
        if ST._index is None or force:
            ST.refresh(self.relay.listed.emit)

    def _changed(self) -> None:
        self.view._dr_rev += 1
        self.view.update()

    # -- what the drawer's cache watches (see LyricsView._dr_said)
    def said(self) -> tuple:
        from time import monotonic
        return (id(ST._index), ST._error, ST._busy.locked(), self.show, self.sort,
                self.query.text, self.searching and int(monotonic() * 2) % 2,
                tuple(sorted(self.working)), tuple(sorted(self.notes.items())),
                tuple((p.id, p.version, p.removed, p.stale) for p in PL.plugins()),
                tuple(sorted(ST._fresh)))

    # ------------------------------------------------------------- painting
    def paint(self, p, g: dict) -> None:
        v, u, body = self.view, g["u"], g["body"]
        if ST._index is None and not ST._busy.locked() and not ST._error:
            self.load()
        x0, w = body.x() + 28 * u, body.width() - 56 * u
        y = body.y() + 14 * u

        # The search box and the look-again button.
        box = QRectF(x0, y, w - 46 * u, 36 * u)
        v._dr_pill(p, box, QColor(0, 0, 0, 70),
                   QColor(234, 234, 234, 150) if self.searching else v.W(0.16),
                   radius=9 * u)
        v._dr_text(p, QRectF(box.x() + 10 * u, box.y(), 16 * u, box.height()),
                   "⌕", v.dr_font(16 * u, 600), v.W(0.55),
                   Qt.AlignmentFlag.AlignCenter, elide=False)
        fs = v.dr_font(14.5 * u, 600)
        inner = box.adjusted(30 * u, 0, -8 * u, 0)
        if self.searching:
            p.setFont(fs)
            p.setPen(QColor(234, 234, 234))
            v._paint_field(p, self.query, inner, QFontMetricsF(fs), "Search plugins")
        else:
            v._dr_text(p, inner, self.query.text or "Search plugins", fs,
                       v.W(0.92 if self.query.text else 0.42))
        v.dr_hit(box, ("mk", "search"))
        again = QRectF(box.right() + 10 * u, y, 36 * u, 36 * u)
        busy = ST._busy.locked()
        hot = again.contains(v.mouse_pos) and not busy
        v._dr_pill(p, again, v.W(0.14 if hot else 0.06), v.W(0.2), radius=9 * u)
        v._dr_text(p, again, "…" if busy else "↻", v.dr_font(17 * u, 700),
                   v.W(0.45 if busy else 0.9), Qt.AlignmentFlag.AlignCenter,
                   elide=False)
        if not busy:
            v.dr_hit(again, ("mk", "again"))

        # What is shown, and in what order.
        y += 36 * u + 26 * u
        items = ST.entries() if ST._index is not None else []
        ups = sum(1 for e in items if ST.state_of(e) == "update")
        f = v.dr_font(14 * u, 600)
        shows = [f"Updates ({ups})" if s == "Updates" and ups else s for s in SHOWS]
        cur = next(s for s in shows if s.split(" (")[0] == self.show)
        v._dr_segmented(p, x0, y, shows, cur, u, f, ("mk", "show"))
        sw = v._dr_seg_w(list(SORTS), f, u)
        v._dr_segmented(p, x0 + w - sw, y, list(SORTS), self.sort, u, f,
                        ("mk", "sort"))

        # The list.
        top = y + 26 * u
        area = QRectF(body.x(), top, body.width(), body.bottom() - top)
        p.fillRect(QRectF(body.x(), top - 1, body.width(), 1), v.W(0.06))
        got = (ST.shown(items, self.query.text, self.show, SORTS[self.sort])
               if ST._index is not None else [])
        cards = [self._lay(e, w, u) for e in got]
        empty = self._empty_text(items, got)
        foot_h = self._foot(p, None, x0, w, u)
        total = 14 * u + sum(c["h"] + 10 * u for c in cards) + \
            (150 * u if empty else 0) + foot_h + 16 * u
        span = max(0.0, total - area.height())
        v.dr_scroll_max = span
        v.dr_kscroll = max(0.0, min(span, v.dr_kscroll))
        p.save()
        p.setClipRect(area)
        cy = top + 14 * u - v.dr_kscroll
        if empty:
            v._dr_text(p, QRectF(x0, cy, w, 120 * u), empty, v.dr_font(15.5 * u, 500),
                       v.W(0.55), Qt.AlignmentFlag.AlignCenter, elide=False)
            cy += 150 * u
        for c in cards:
            r = QRectF(x0, cy, w, c["h"])
            if r.bottom() >= area.y() and r.y() <= area.bottom():
                self._card(p, c, r, u, area)
            cy += c["h"] + 10 * u
        self._foot(p, QRectF(x0, cy, w, foot_h), x0, w, u)
        p.restore()
        if span > 1:
            track = QRectF(body.right() - 8 * u, area.y() + 6 * u, 3 * u,
                           area.height() - 12 * u)
            frac = area.height() / (area.height() + span)
            knob = QRectF(track.x(), track.y() + track.height() * (1 - frac)
                          * (v.dr_kscroll / span), track.width(),
                          track.height() * frac)
            v._dr_pill(p, knob, v.W(0.18))

    def _empty_text(self, items, got) -> str:
        if ST._index is None:
            if ST._error:
                return f"Couldn't reach the marketplace.\n{ST._error}\n↻ looks again."
            return "Looking at the marketplace…"
        if got:
            return ""
        if self.query.text.strip():
            return f"No plugin matches “{self.query.text.strip()}”."
        return {"Updates": "Everything is up to date.",
                "Installed": "Nothing installed yet."}.get(
            self.show, "Nothing is listed yet.")

    # -- one card
    def _lay(self, e: dict, w: float, u: float) -> dict:
        v = self.view
        st = ST.state_of(e)
        verb = self._verb(e, st)
        fb = v.dr_font(14.5 * u, 500)
        fmb = QFontMetricsF(fb)
        btn_w = 128 * u if verb or st in self._removable() else 0.0
        tw = w - 28 * u - 44 * u - 14 * u - (btn_w + 14 * u if btn_w else 0)
        about = self.wrap(fmb, e.get("description") or "", tw, 3) \
            if e.get("description") else []
        meta = self._meta(e)
        note = self.notes.get(e["id"], "")
        fa = v.dr_font(13 * u, 600)
        asks = [] if e.get("local") else self.wrap(
            QFontMetricsF(fa), "Asks for: " + ST.asks_for(e), tw, 2)
        h = (24 * u + len(about) * fmb.height() * 1.25 + (22 * u if meta else 0)
             + 20 * u * len(asks) + (4 * u if asks else 0) + (22 * u if note else 0))
        return {"e": e, "st": st, "verb": verb, "about": about, "meta": meta,
                "note": note, "asks": asks, "tw": tw, "btn_w": btn_w,
                "h": max(44 * u, h) + 28 * u}

    @staticmethod
    def _removable() -> tuple:
        return ("installed", "update", "stale", "local", "fresh")

    def _verb(self, e: dict, st: str) -> str:
        if e["id"] in self.working:
            return "Installing…"
        return {"new": "Install", "update": "Update",
                "removed": "" if e.get("local") else "Install"}.get(st, "")

    def _badge(self, e: dict, st: str):
        return {"installed": ("Installed", GREEN),
                "fresh": ("Installed · restart to use", GREEN),
                "update": ("Update available", BLUE),
                "stale": ("Restart to use", BLUE),
                "removed": ("Removed · restart to drop its tab", None),
                "local": ("Not in the marketplace", None),
                "too-new": ("Needs a newer Mild Lyrics", RED)}.get(st)

    def _meta(self, e: dict) -> list:
        """[(text, url or None)], drawn with · between."""
        if e.get("local"):
            return []
        out = []
        n = e.get("downloads")
        if isinstance(n, int):
            out.append((f"⬇ {ST.short_count(n)} download{'s' * (n != 1)}", None))
        if e.get("author"):
            out.append((f"by {e['author']}", None))
        if e.get("size"):
            out.append((ST.size_text(e["size"]), None))
        day = ST.day_text(e.get("published") or "")
        if day:
            out.append((f"updated {day}", None))
        home = str(e.get("homepage") or "")
        if home.startswith("https://"):
            out.append(("homepage ↗", home))
        return out

    def _card(self, p, c: dict, r: QRectF, u: float, area: QRectF) -> None:
        v, e, st = self.view, c["e"], c["st"]
        hot = r.contains(v.mouse_pos) and area.contains(v.mouse_pos)
        v._dr_pill(p, r, v.W(0.075 if hot else 0.045), v.W(0.08), radius=12 * u)
        v.dr_hit(r.intersected(area), ("mk", "card", e["id"]))
        pad = 14 * u
        tile = QRectF(r.x() + pad, r.y() + pad, 44 * u, 44 * u)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor.fromHsv(zlib.crc32(e["id"].encode()) % 360, 120, 205))
        p.drawRoundedRect(tile, 11 * u, 11 * u)
        p.setBrush(Qt.BrushStyle.NoBrush)
        words = [w for w in e["name"].replace("-", " ").split() if w[:1].isalnum()]
        initials = "".join(w[0] for w in words[:2]).upper() or "?"
        v._dr_text(p, tile, initials, v.dr_font((18 if len(initials) < 2 else 16) * u, 800),
                   QColor(255, 255, 255), Qt.AlignmentFlag.AlignCenter, elide=False)

        tx = tile.right() + 14 * u
        ty = r.y() + pad
        fn = v.dr_font(17 * u, 700)
        fv = v.dr_font(14 * u, 500)
        name_w = min(QFontMetricsF(fn).horizontalAdvance(e["name"]) + 2, c["tw"])
        v._dr_text(p, QRectF(tx, ty, name_w, 24 * u), e["name"], fn, v.W(0.96))
        x = tx + name_w + 8 * u
        plug = PL._PLUGINS.get(e["id"])
        ver = (f"{plug.version} → {e['version']}" if st == "update" and plug
               else str(e.get("version") or ""))
        vw = QFontMetricsF(fv).horizontalAdvance(ver) + 2
        if x + vw < tx + c["tw"]:
            v._dr_text(p, QRectF(x, ty, vw, 24 * u), ver, fv, v.W(0.5), elide=False)
            x += vw + 8 * u
        badge = self._badge(e, st)
        if badge:
            fbd = v.dr_font(12.5 * u, 700)
            bw = QFontMetricsF(fbd).horizontalAdvance(badge[0]) + 16 * u
            if x + bw <= tx + c["tw"]:
                col = badge[1] or v.W(0.6)
                fill = QColor(col)
                fill.setAlpha(36 if badge[1] else 20)
                b = QRectF(x, ty + 2 * u, bw, 20 * u)
                v._dr_pill(p, b, fill)
                v._dr_text(p, b, badge[0], fbd, col, Qt.AlignmentFlag.AlignCenter,
                           elide=False)
        ty += 24 * u
        fb = v.dr_font(14.5 * u, 500)
        lh = QFontMetricsF(fb).height() * 1.25
        for line in c["about"]:
            v._dr_text(p, QRectF(tx, ty, c["tw"], lh), line, fb, v.W(0.74))
            ty += lh
        if c["meta"]:
            fm_ = v.dr_font(13 * u, 500)
            fmm = QFontMetricsF(fm_)
            x = tx
            for i, (text, url) in enumerate(c["meta"]):
                if i:
                    dot = " · "
                    dw = fmm.horizontalAdvance(dot)
                    v._dr_text(p, QRectF(x, ty + 2 * u, dw, 20 * u), dot, fm_,
                               v.W(0.35), elide=False)
                    x += dw
                tw_ = fmm.horizontalAdvance(text) + 1
                if x + tw_ > tx + c["tw"]:
                    break
                rr = QRectF(x, ty + 2 * u, tw_, 20 * u)
                link_hot = url and rr.contains(v.mouse_pos)
                v._dr_text(p, rr, text, fm_,
                           v.W(0.95) if link_hot else BLUE if url else v.W(0.48),
                           elide=False)
                if url:
                    v.dr_hit(rr, ("mk", "open", url))
                x += tw_
            ty += 22 * u
        for line in c["asks"]:
            v._dr_text(p, QRectF(tx, ty + 2 * u, c["tw"], 20 * u), line,
                       v.dr_font(13 * u, 600), v.W(0.62))
            ty += 20 * u
        if c["asks"]:
            ty += 4 * u
        if c["note"]:
            v._dr_text(p, QRectF(tx, ty + 2 * u, c["tw"], 20 * u), c["note"],
                       v.dr_font(13.5 * u, 600), RED)

        right = r.right() - pad
        by = r.y() + pad
        if c["verb"]:
            busy = e["id"] in self.working
            f = v.dr_font(15 * u, 700)
            h = QFontMetricsF(f).height() + 16 * u
            btn = QRectF(right - c["btn_w"], by, c["btn_w"], h)
            bhot = btn.contains(v.mouse_pos) and not busy
            strong = st == "update"
            if busy:
                p.setOpacity(0.5)
            v._dr_pill(p, btn, v.W(0.92 if strong else 0.14 if bhot else 0.06),
                       None if strong else v.W(0.2), radius=9 * u)
            v._dr_text(p, btn, c["verb"], f,
                       QColor(20, 20, 25) if strong else QColor(234, 234, 234),
                       Qt.AlignmentFlag.AlignCenter, elide=False)
            p.setOpacity(1.0)
            if not busy:
                v.dr_hit(btn, ("mk", "act", e["id"]))
            by = btn.bottom() + 6 * u
        if st in self._removable():
            f = v.dr_font(13.5 * u, 600)
            tw_ = QFontMetricsF(f).horizontalAdvance("Uninstall") + 16 * u
            rm = QRectF(right - tw_, by, tw_, 26 * u)
            rhot = rm.contains(v.mouse_pos)
            v._dr_text(p, rm, "Uninstall", f, RED if rhot else v.W(0.5),
                       Qt.AlignmentFlag.AlignCenter, elide=False)
            v.dr_hit(rm, ("mk", "rm", e["id"]))

    def _foot(self, p, r, x0: float, w: float, u: float) -> float:
        """The note and the two ways to make one. Measured when r is None."""
        v = self.view
        fn = v.dr_font(13.5 * u, 500)
        fmn = QFontMetricsF(fn)
        note = ("Each plugin runs walled in: its own folder, plus what it asks for, "
                "shown before it is installed. Each one here was read before it "
                "was listed.")
        lines = self.wrap(fmn, note, w, 3)
        lh = fmn.height() * 1.3
        f = v.dr_font(14.5 * u, 700)
        bh = QFontMetricsF(f).height() + 16 * u
        h = 10 * u + len(lines) * lh + 12 * u + bh
        if r is None:
            return h
        y = r.y() + 10 * u
        for line in lines:
            v._dr_text(p, QRectF(x0, y, w, lh), line, fn, v.W(0.42))
            y += lh
        y += 12 * u
        x = x0
        for label, what in (("Submit a plugin…", ("mk", "submit")),
                            ("Write your own ↗", ("mk", "open", ST.GUIDE))):
            bw = QFontMetricsF(f).horizontalAdvance(label) + 32 * u
            b = QRectF(x, y, bw, bh)
            hot = b.contains(v.mouse_pos)
            v._dr_pill(p, b, v.W(0.14 if hot else 0.06), v.W(0.2), radius=9 * u)
            v._dr_text(p, b, label, f, QColor(234, 234, 234),
                       Qt.AlignmentFlag.AlignCenter, elide=False)
            v.dr_hit(b, what)
            x += bw + 10 * u
        return h

    # ---------------------------------------------------------------- input
    def press(self, what: tuple, pos) -> None:
        sub = what[1]
        self.searching = sub == "search"
        if sub == "search":
            self.query.press(pos)
        elif sub == "again":
            self.load(force=True)
        elif sub == "show":
            self.show = str(what[2]).split(" (")[0]
            self.view.dr_kscroll = 0.0
        elif sub == "sort":
            self.sort = what[2]
            self.view.dr_kscroll = 0.0
        elif sub == "act":
            self.want(what[2])
        elif sub == "rm":
            self.remove(what[2])
        elif sub == "open":
            self.view.open_url(what[2])
        elif sub == "submit":
            ST.pick_and_submit()

    def key(self, ev) -> bool:
        """The tab's keys; False hands one back to the drawer (Esc with
        nothing to clear, and the keys bound to menu, help, info, quit)."""
        v = self.view
        k = ev.key()
        ctrl = bool(ev.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if k == Qt.Key.Key_Escape:
            if self.searching or self.query.text:
                self.query.set_text("")
                self.searching = False
                return True
            return False
        if (k == Qt.Key.Key_Slash and not self.searching) or (k == Qt.Key.Key_F and ctrl):
            self.searching = True
            return True
        typed = bool(ev.text()) and ev.text().isprintable() and not ctrl
        if self.searching and (typed or k in (
                Qt.Key.Key_Backspace, Qt.Key.Key_Delete, Qt.Key.Key_Home,
                Qt.Key.Key_End, Qt.Key.Key_Left, Qt.Key.Key_Right) or (
                ctrl and k in (Qt.Key.Key_A, Qt.Key.Key_V, Qt.Key.Key_C, Qt.Key.Key_X))):
            v.field_key(self.query, ev)
            v.dr_kscroll = 0.0
            return True
        name = KM.key_name(ev)
        act = v.key_actions.get(name) if name else None
        if act in ("menu", "help", "info", "quit"):
            return False
        if typed and ev.text().isalnum():
            self.searching = True
            v.field_key(self.query, ev)
            v.dr_kscroll = 0.0
            return True
        if k in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown):
            step = 60 if k in (Qt.Key.Key_Up, Qt.Key.Key_Down) else 400
            up = k in (Qt.Key.Key_Up, Qt.Key.Key_PageUp)
            v.dr_kscroll = max(0.0, min(v.dr_scroll_max,
                                        v.dr_kscroll + (-step if up else step)))
            return True
        if k in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            i = SHOWS.index(self.show) + (-1 if k == Qt.Key.Key_Backtab else 1)
            self.show = SHOWS[i % len(SHOWS)]
            v.dr_kscroll = 0.0
            return True
        return True

    # ---------------------------------------------------------------- doing
    def want(self, pid: str) -> None:
        e = (ST._index or {}).get(pid)
        if e is None:
            return
        PL.confirm(e, lambda: self._download(e))

    def _download(self, e: dict) -> None:
        self.working.add(e["id"])
        self.notes.pop(e["id"], None)

        def run():
            try:
                self.relay.fetched.emit(e["id"], ST.download(e), "")
            except (OSError, ValueError) as err:
                self.relay.fetched.emit(e["id"], None,
                                        str(getattr(err, "reason", None) or err))
        threading.Thread(target=run, daemon=True, name="plugin-download").start()

    def _fetched(self, pid: str, data, err: str) -> None:
        self.working.discard(pid)
        e = (ST._index or {}).get(pid)
        if e is not None and data is not None:
            try:
                said = ST.install_bytes(e, data)
                self.view.toast(f"{e['name']} {said}")
            except (OSError, ValueError) as x:
                err = str(x)
        if err:
            self.notes[pid] = f"Not installed: {err}"
            ST._log(pid, "not installed:", err)
        self._changed()

    def remove(self, pid: str) -> None:
        p = PL._PLUGINS.get(pid)
        e = (ST._index or {}).get(pid) or {}
        name = e.get("name") or (p.name if p else pid)

        def go(_d=None):
            try:
                PL.uninstall(pid)
                self.notes.pop(pid, None)
                self.view.toast(f"{name} removed · restart Mild Lyrics to drop its tab")
            except OSError as x:
                self.notes[pid] = str(x)
            ST._fresh.discard(pid)
            self._changed()
        self.view.ask({"title": f"Uninstall {name}?",
                       "body": [f"{name} is stopped and its files are deleted. Its "
                                "settings are kept, so installing it again keeps "
                                "them."],
                       "yes": "Uninstall", "danger": True, "ok": go})

