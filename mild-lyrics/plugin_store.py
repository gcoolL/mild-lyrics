"""The plugin marketplace: the listing on Mild Lyrics' Worker, installs, and
submissions for review. The guide for authors is docs/plugins/README.md.

The listing and zips are written by docs/discord-cover-worker/publish.py. A
zip is installed only if its size and sha256 are the listing's.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import sys
import tempfile
import threading
import pathlib
import urllib.error
import urllib.request

import plugins as PL
from discord_presence import ART_HOST

HOST = ART_HOST
TIMEOUT = 15
MAX_INDEX = 1_000_000
MAX_ZIP = 25 * 1024 * 1024          # a KV value's own limit
UA = {"User-Agent": "Mild Lyrics"}
SUBMIT_MAX = 5 * 1024 * 1024         # the Worker's own limit
GUIDE = "https://github.com/gcoolL/mild-lyrics/blob/main/docs/plugins/README.md"
# Names that usually hold somebody's keys or settings, asked about first.
PRIVATE = (".env", "*.key", "*.pem", "*secret*", "*token*", "*credential*",
           "settings.json", "config.json", "*.sqlite", "*.db")

_index: dict | None = None          # id -> listing entry, once fetched
_error = ""                         # why the last look failed
_busy = threading.Lock()
_fresh: set = set()                 # ids installed this run, not yet loaded
_dialog = None                      # the open Browse window, held
_sending = None                     # the submit relay while one is sent
_window = None                      # the drawer's Plugins tab (market_tab)


def _log(*bits) -> None:
    print("[plugin store]", *bits, file=sys.stderr, flush=True)


# ------------------------------------------------------------------ listing
def version_key(v: str) -> tuple:
    """Dotted numbers first; a release sorts after its own pre-releases."""
    m = re.match(r"(\d+(?:\.\d+)*)(.*)", v)
    if not m:
        return ((), 0, v)
    return (tuple(int(x) for x in m.group(1).split(".")), m.group(2) == "",
            m.group(2))


def _entry_ok(e) -> bool:
    if not isinstance(e, dict):
        return False
    pid, ver = str(e.get("id") or ""), str(e.get("version") or "")
    return bool(PL.ID_RE.fullmatch(pid) and PL.VERSION_RE.fullmatch(ver)
                and e.get("zip") == f"plugins/{pid}/{ver}.zip"
                and isinstance(e.get("size"), int) and 0 < e["size"] <= MAX_ZIP
                and re.fullmatch(r"[0-9a-f]{64}", str(e.get("sha256") or "")))


def fetch_index() -> dict:
    """The listing, {id: entry}; {} when nothing is published. Blocking."""
    req = urllib.request.Request(f"{HOST}/plugins/index.json", headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            got = json.loads(r.read(MAX_INDEX))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {}
        raise
    out = {}
    for e in (got.get("plugins") if isinstance(got, dict) else None) or []:
        if _entry_ok(e):
            out[e["id"]] = e
        else:
            _log("skipped a malformed listing entry:", str(e)[:120])
    return out


def refresh(done=None) -> bool:
    """Look at the listing on a thread; done() after, on that thread. One
    look at a time, never retried. False when one is already going."""
    if not HOST or not _busy.acquire(blocking=False):
        return False

    def run():
        global _index, _error
        try:
            _index, _error = fetch_index(), ""
        except (OSError, ValueError) as e:
            _error = str(getattr(e, "reason", None) or e)[:160]
            _log("could not read the listing:", _error)
        finally:
            _busy.release()
        if done:
            done()
    threading.Thread(target=run, daemon=True, name="plugin-store").start()
    return True


def update_for(pid: str, version: str) -> dict | None:
    """The listing's entry for `pid` when it is newer than `version`."""
    e = (_index or {}).get(pid)
    if e and version_key(e["version"]) > version_key(version or "0"):
        return e
    return None


def said() -> str:
    """What the Browse plugins row reads."""
    if _index is None:
        return "can't reach it" if _error else "marketplace"
    ups = sum(1 for p in PL.plugins() if update_for(p.id, p.version))
    if ups:
        return f"{ups} update{'s' * (ups > 1)}"
    return f"{len(_index)} listed"


# ------------------------------------------------------------------ installs
def download(e: dict) -> bytes:
    """The entry's zip, checked against its size and sha256. Blocking."""
    req = urllib.request.Request(f"{HOST}/{e['zip']}", headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT * 4) as r:
        data = r.read(e["size"] + 1)
    if len(data) != e["size"] or hashlib.sha256(data).hexdigest() != e["sha256"]:
        raise ValueError("the download is not the file the listing names")
    return data


def install_bytes(e: dict, data: bytes) -> str:
    """Install a checked zip; what happened, for the Browse row."""
    with tempfile.TemporaryDirectory() as tmp:
        z = pathlib.Path(tmp) / f"{e['id']}.zip"
        z.write_bytes(data)
        m = PL.peek(z)
        if m["id"] != e["id"] or str(m.get("version") or "") != e["version"]:
            raise ValueError("the zip's plugin.json is not the listing's")
        if PL.permissions(m) != PL.permissions(e):
            raise ValueError("the zip asks for other permissions than the listing shows")
        PL.install(z, grant=True)       # its permissions were just shown
    p = PL._PLUGINS.get(e["id"])
    if p is None:
        _fresh.add(e["id"])
        return "installed · restart Mild Lyrics to see it"
    return "updated · restart Mild Lyrics" if p.stale else "updated"


# ---------------------------------------------------------------- asking
def _here():
    """The drawer's Plugins tab, when the window draws its own questions."""
    return _window if _window is not None and _window.in_window() else None


def ask(dlg: dict) -> None:
    """A question in LyricsView.ask's shape: asked inside the window in the
    new interface, in a system box in the classic one."""
    w = _here()
    if w is not None:
        w.view.ask(dlg)
        return
    from PyQt6.QtWidgets import QMessageBox
    box = QMessageBox(QMessageBox.Icon.Question, dlg["title"],
                      "\n\n".join(dlg.get("body") or []))
    box.setStandardButtons(QMessageBox.StandardButton.Yes
                           | QMessageBox.StandardButton.Cancel)
    box.button(QMessageBox.StandardButton.Yes).setText(dlg.get("yes") or "OK")
    box.setDefaultButton(QMessageBox.StandardButton.Cancel)
    if box.exec() == QMessageBox.StandardButton.Yes and dlg.get("ok"):
        dlg["ok"](dlg)


def tell(title: str, text: str) -> None:
    """Something went wrong: a toast in the window, else a system box."""
    w = _here()
    if w is not None:
        w.view.toast(f"{title}: {text}")
        return
    from PyQt6.QtWidgets import QMessageBox
    QMessageBox.warning(None, title, text)


# --------------------------------------------------------------- submitting
def private_files(folder: pathlib.Path) -> list[str]:
    return [f.relative_to(folder).as_posix() for f in PL.pack_files(folder)
            if any(fnmatch.fnmatch(f.name.lower(), g) for g in PRIVATE)]


def submit(data: bytes, pid: str, version: str) -> str:
    """Send a packed plugin for review; the Worker's answer. Blocking."""
    req = urllib.request.Request(
        f"{HOST}/plugins/submit", data=data, method="POST",
        headers={**UA, "Content-Type": "application/zip",
                 "X-Plugin": f"{pid} {version}"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT * 4) as r:
            return r.read(500).decode("utf-8", "replace").strip()
    except urllib.error.HTTPError as e:
        raise ValueError(e.read(500).decode("utf-8", "replace").strip()
                         or f"HTTP {e.code}") from None


def pick_and_submit() -> None:
    from PyQt6.QtCore import QObject, pyqtSignal
    from PyQt6.QtWidgets import QFileDialog
    global _sending
    if _sending is not None:
        if PL._toast:
            PL._toast("a plugin is already being sent")
        return
    path, _f = QFileDialog.getOpenFileName(
        None, "Submit a plugin: the plugin.json in its folder",
        str(pathlib.Path.home()), "Plugin (plugin.json)")
    if not path:
        return
    folder = pathlib.Path(path).parent
    try:
        m = PL._read_manifest(folder)
    except ValueError as e:
        tell("Not a plugin", str(e))
        return
    version = str(m.get("version") or "")
    if not PL.VERSION_RE.fullmatch(version):
        tell("Not a plugin", "plugin.json needs a version: digits, letters, . + -")
        return
    data = PL.pack(folder, m["id"])
    if len(data) > SUBMIT_MAX:
        tell("Too big", f"{len(data) // 1024} KB zipped; 5 MB at most")
        return
    files = PL.pack_files(folder)
    risky = private_files(folder)
    body = [f"{m.get('name') or m['id']} {version}: {len(files)} files, "
            f"{len(data) // 1024 + 1} KB zipped.",
            "Everything in the folder is sent, apart from __pycache__, .git "
            "and tests. Once it has been reviewed it is listed for everyone, "
            "so it must hold no keys or settings of yours."]
    if risky:
        body.append("These look private; check them first: " + ", ".join(risky))
    ask({"title": "Submit for review?", "body": body, "yes": "Submit",
         "default_no": True,
         "ok": lambda _d: _send(m["id"], version, data)})


def _send(pid: str, version: str, data: bytes) -> None:
    from PyQt6.QtCore import QObject, pyqtSignal
    global _sending

    class Relay(QObject):
        said = pyqtSignal(str)

    relay = _sending = Relay()

    def done(text: str) -> None:
        global _sending
        _sending = None
        if PL._toast:
            PL._toast(text)
    relay.said.connect(done)

    def run():
        try:
            relay.said.emit(f"{pid} {version} sent · {submit(data, pid, version)}")
        except (OSError, ValueError) as e:
            relay.said.emit(f"{pid} not sent: {getattr(e, 'reason', None) or e}")
    threading.Thread(target=run, daemon=True, name="plugin-submit").start()


# ------------------------------------------------------------------- window
SORTS = ("Most downloaded", "Recently updated", "Name")
SHOWS = ("All", "Installed", "Updates")


def short_count(n: int) -> str:
    if n < 1000:
        return str(n)
    if n < 10_000:
        return f"{n / 1000:.1f}".rstrip("0").rstrip(".") + "k"
    if n < 1_000_000:
        return f"{n // 1000}k"
    return f"{n / 1e6:.1f}".rstrip("0").rstrip(".") + "M"


def asks_for(e: dict) -> str:
    """A listing's permissions in a few words, for its card."""
    p = PL.permissions(e)
    bits = []
    if p["network"]:
        bits.append("internet (" + ", ".join(p["network"]) + ")")
    if p["player"]:
        bits.append("player controls")
    if p["spotify"]:
        bits.append("scripts in Spotify")
    if p["listen"]:
        bits.append("local connections")
    if p["folders"]:
        bits.append("a folder outside its own")
    return ", ".join(bits) or "nothing beyond its own folder"


def size_text(b: int) -> str:
    return f"{b / 1024:.0f} KB" if b < 1024 * 1024 else f"{b / 1048576:.1f} MB"


def day_text(iso: str) -> str:
    import datetime
    try:
        d = datetime.date.fromisoformat(iso[:10])
    except ValueError:
        return ""
    return f"{d.day} {d:%b %Y}"                 # %-d is not on Windows


def state_of(e: dict) -> str:
    """new, fresh (installed this run), installed, update, stale, removed,
    local (installed, not listed) or too-new (needs a newer Mild Lyrics)."""
    p = PL._PLUGINS.get(e["id"])
    if p is not None and p.removed:
        return "removed"
    if e.get("local"):
        return "local"
    if p is None:
        if e.get("api", 1) > PL.API_VERSION:
            return "too-new"
        return "fresh" if e["id"] in _fresh else "new"
    if p.stale:
        return "stale"
    if update_for(p.id, p.version):
        return "too-new" if e.get("api", 1) > PL.API_VERSION else "update"
    return "installed"


def entries() -> list[dict]:
    """The listing, and installed plugins it does not list."""
    out = list((_index or {}).values())
    for p in PL.plugins():
        if p.id not in (_index or {}):
            out.append({"id": p.id, "name": p.name, "version": p.version,
                        "description": p.about, "local": True})
    return out


def shown(items: list[dict], query: str, show: str, sort: str) -> list[dict]:
    q = query.strip().lower()

    def hit(e):
        text = " ".join(str(e.get(k) or "") for k in
                        ("name", "id", "description", "author")).lower()
        return all(w in text for w in q.split())
    st = {e["id"]: state_of(e) for e in items}
    keep = {"All": lambda e: not e.get("local") or st[e["id"]] == "local",
            "Installed": lambda e: st[e["id"]] in ("installed", "update",
                                                   "stale", "local", "fresh"),
            "Updates": lambda e: st[e["id"]] == "update"}[show]
    got = [e for e in items if keep(e) and hit(e)]
    name = lambda e: e["name"].lower()                       # noqa: E731
    if sort == "Name":
        return sorted(got, key=name)
    if sort == "Recently updated":
        return sorted(sorted(got, key=name), key=lambda e: e.get("published", ""),
                      reverse=True)
    return sorted(sorted(got, key=name), key=lambda e: e.get("downloads", 0),
                  reverse=True)


def browse() -> None:
    """The drawer's Plugins tab in the new interface; a window in the classic."""
    global _dialog
    w = _here()
    if w is not None:
        w.open()
        return
    if _dialog is None:
        _dialog = _make_dialog()
    _dialog.show()
    _dialog.raise_()
    _dialog.activateWindow()
    _dialog.load()


def _make_dialog():
    import zlib
    from PyQt6.QtCore import QObject, QRectF, Qt, pyqtSignal
    from PyQt6.QtGui import (QColor, QFont, QKeySequence, QPainter, QPalette,
                             QPixmap, QShortcut)
    from PyQt6.QtWidgets import (QApplication, QButtonGroup, QComboBox,
                                 QDialog, QFrame, QHBoxLayout, QLabel,
                                 QLineEdit, QMessageBox, QPushButton,
                                 QScrollArea, QSizePolicy, QToolButton,
                                 QVBoxLayout, QWidget)

    def rgba(c: QColor, a: float) -> str:
        return f"rgba({c.red()},{c.green()},{c.blue()},{a:.2f})"

    def avatar(e: dict, size: int, dpr: float) -> QPixmap:
        """A rounded tile in the plugin's own colour, with its initials."""
        pm = QPixmap(int(size * dpr), int(size * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor.fromHsv(zlib.crc32(e["id"].encode()) % 360, 110, 200))
        p.drawRoundedRect(QRectF(0, 0, size, size), size * 0.24, size * 0.24)
        words = [w for w in e["name"].replace("-", " ").split() if w[:1].isalnum()]
        initials = "".join(w[0] for w in words[:2]).upper() or "?"
        f = QFont(p.font())
        f.setBold(True)
        f.setPixelSize(int(size * (0.42 if len(initials) < 2 else 0.36)))
        p.setFont(f)
        p.setPen(QColor(255, 255, 255))
        p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, initials)
        p.end()
        return pm

    class Relay(QObject):
        listed = pyqtSignal()
        fetched = pyqtSignal(str, object, str)      # id, bytes, error

    class Browser(QDialog):
        def __init__(self) -> None:
            super().__init__(None)
            self.setWindowTitle("Plugins")
            self.resize(680, 640)
            self.relay = Relay()                    # held: see its signals
            self.relay.listed.connect(self.listed)
            self.relay.fetched.connect(self.fetched)
            self.notes: dict = {}                   # id -> (text, ok)
            self.working: set = set()
            pal = QApplication.palette()
            self.text = pal.color(QPalette.ColorRole.Text)
            self.hi = pal.color(QPalette.ColorRole.Highlight)
            self.muted = rgba(self.text, 0.62)
            self.grey = QColor(self.text)
            self.grey.setAlphaF(0.62)
            dark = pal.color(QPalette.ColorRole.Window).lightness() < 128
            self.good = QColor("#5fbf7a" if dark else "#2e8b4e")
            self.bad = QColor("#e0726b" if dark else "#c0392b")
            self.setStyleSheet(f"""
                QFrame#card {{ background: {rgba(pal.color(QPalette.ColorRole.Base), 1)};
                    border: 1px solid {rgba(self.text, 0.12)}; border-radius: 10px; }}
                QFrame#card:hover {{ border-color: {rgba(self.hi, 0.7)}; }}
                QLabel#muted {{ color: {self.muted}; }}
                QPushButton#seg {{ padding: 4px 12px; border-radius: 12px;
                    border: 1px solid {rgba(self.text, 0.18)}; background: transparent; }}
                QPushButton#seg:checked {{ background: {rgba(self.hi, 0.9)};
                    color: {pal.color(QPalette.ColorRole.HighlightedText).name()};
                    border-color: transparent; }}
                QPushButton#quiet {{ border: none; background: transparent;
                    color: {self.muted}; padding: 2px 6px; }}
                QPushButton#quiet:hover {{ color: {self.bad.name()}; }}
            """)
            top = QVBoxLayout(self)
            top.setContentsMargins(16, 16, 16, 12)
            top.setSpacing(10)

            bar = QHBoxLayout()
            self.search = QLineEdit()
            self.search.setPlaceholderText("Search plugins")
            self.search.setClearButtonEnabled(True)
            self.search.textChanged.connect(self.fill)
            bar.addWidget(self.search, 1)
            self.sort = QComboBox()
            self.sort.addItems(SORTS)
            self.sort.currentTextChanged.connect(self.fill)
            bar.addWidget(self.sort)
            self.again = QToolButton()
            self.again.setText("↻")
            self.again.setToolTip("Look at the marketplace again")
            self.again.clicked.connect(lambda: self.load(force=True))
            bar.addWidget(self.again)
            top.addLayout(bar)

            segs = QHBoxLayout()
            segs.setSpacing(6)
            self.shows = QButtonGroup(self)
            self.seg_buttons = {}
            for i, name in enumerate(SHOWS):
                b = QPushButton(name)
                b.setObjectName("seg")
                b.setCheckable(True)
                b.setChecked(i == 0)
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                self.shows.addButton(b, i)
                self.seg_buttons[name] = b
                segs.addWidget(b)
            self.shows.idClicked.connect(lambda _i: self.fill())
            segs.addStretch(1)
            self.count = QLabel("")
            self.count.setObjectName("muted")
            segs.addWidget(self.count)
            top.addLayout(segs)

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.inner = QWidget()
            self.rows = QVBoxLayout(self.inner)
            self.rows.setContentsMargins(0, 0, 4, 0)
            self.rows.setSpacing(8)
            self.rows.setAlignment(Qt.AlignmentFlag.AlignTop)
            scroll.setWidget(self.inner)
            top.addWidget(scroll, 1)

            warn = QLabel("Each plugin runs walled in: its own folder, plus what it "
                          "asks for, shown before it is installed. Each one listed "
                          "here was read before it was listed.")
            warn.setObjectName("muted")
            warn.setWordWrap(True)
            top.addWidget(warn)
            foot = QHBoxLayout()
            guide = QLabel(f'<a href="{GUIDE}">Write your own</a>')
            guide.setOpenExternalLinks(True)
            foot.addWidget(guide)
            send = QPushButton("Submit a plugin…")
            send.clicked.connect(pick_and_submit)
            foot.addWidget(send)
            foot.addStretch(1)
            close = QPushButton("Close")
            close.clicked.connect(self.close)
            foot.addWidget(close)
            top.addLayout(foot)
            QShortcut(QKeySequence.StandardKey.Find, self, self.search.setFocus)

        # -- the listing
        def load(self, force: bool = False) -> None:
            self.search.setFocus()
            if _index is not None and not force:
                self.fill()
                return
            if refresh(self.relay.listed.emit):
                self.again.setEnabled(False)
                self.message("Looking at the marketplace…")

        def listed(self) -> None:
            self.again.setEnabled(True)
            self.fill()

        def message(self, text: str) -> None:
            self.clear()
            self.count.setText("")
            m = QLabel(text)
            m.setObjectName("muted")
            m.setWordWrap(True)
            m.setAlignment(Qt.AlignmentFlag.AlignCenter)
            m.setMinimumHeight(160)
            self.rows.addWidget(m)

        def clear(self) -> None:
            while self.rows.count():
                w = self.rows.takeAt(0).widget()
                if w is not None:
                    w.setParent(None)           # gone now, not at the next loop
                    w.deleteLater()

        def fill(self) -> None:
            if _index is None:
                self.message(f"Couldn't reach the marketplace.\n{_error}\n\n"
                             "↻ looks again." if _error else
                             "Looking at the marketplace…")
                return
            items = entries()
            ups = sum(1 for e in items if state_of(e) == "update")
            self.seg_buttons["Updates"].setText(f"Updates ({ups})" if ups else "Updates")
            show = SHOWS[max(0, self.shows.checkedId())]
            got = shown(items, self.search.text(), show, self.sort.currentText())
            listed = len(_index)
            counted = f"{listed} plugin{'s' * (listed != 1)} listed"
            self.clear()
            if not got:
                self.message({"Updates": "Everything is up to date.",
                              "Installed": "Nothing installed yet."}.get(show, "")
                             if not self.search.text().strip() else
                             "No plugin matches that.")
                self.count.setText(counted)
                return
            self.count.setText(counted)
            for e in got:
                self.rows.addWidget(self.card(e))
            self.rows.addStretch(1)

        # -- one plugin
        def badge(self, text: str, colour: QColor) -> QLabel:
            b = QLabel(text)
            b.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            b.setStyleSheet(f"color: {rgba(colour, colour.alphaF())}; background: {rgba(colour, 0.14)};"
                            "border-radius: 8px; padding: 1px 7px; font-size: 11px;")
            return b

        def card(self, e: dict) -> QFrame:
            st = state_of(e)
            box = QFrame()
            box.setObjectName("card")
            h = QHBoxLayout(box)
            h.setContentsMargins(12, 12, 12, 12)
            h.setSpacing(12)
            pic = QLabel()
            pic.setPixmap(avatar(e, 44, self.devicePixelRatioF()))
            pic.setAlignment(Qt.AlignmentFlag.AlignTop)
            h.addWidget(pic, 0, Qt.AlignmentFlag.AlignTop)

            text = QVBoxLayout()
            text.setSpacing(3)
            head = QHBoxLayout()
            head.setSpacing(6)
            name = QLabel(_esc(e["name"]))
            f = QFont(name.font())
            f.setBold(True)
            f.setPointSizeF(f.pointSizeF() * 1.15)
            name.setFont(f)
            head.addWidget(name)
            p = PL._PLUGINS.get(e["id"])
            ver = QLabel(_esc(f"{p.version} → {e['version']}" if st == "update"
                              else e.get("version") or ""))
            ver.setObjectName("muted")
            head.addWidget(ver)
            for label, colour in self.badges(e, st):
                head.addWidget(self.badge(label, colour))
            head.addStretch(1)
            text.addLayout(head)
            if e.get("description"):
                about = QLabel(_esc(e["description"]))
                about.setWordWrap(True)
                about.setSizePolicy(QSizePolicy.Policy.Ignored,
                                    QSizePolicy.Policy.Preferred)
                text.addWidget(about)
            meta = self.meta(e)
            if not e.get("local"):
                meta = (meta + "<br>" if meta else "") + "asks for: " + _esc(asks_for(e))
            if meta:
                m = QLabel(meta)
                m.setObjectName("muted")
                m.setOpenExternalLinks(True)
                m.setWordWrap(True)
                text.addWidget(m)
            note = self.notes.get(e["id"])
            if note:
                n = QLabel(_esc(note[0]))
                n.setWordWrap(True)
                n.setStyleSheet(f"color: {(self.good if note[1] else self.bad).name()};")
                text.addWidget(n)
            h.addLayout(text, 1)

            side = QVBoxLayout()
            side.setSpacing(2)
            verb, live = self.verb(e, st)
            if verb:
                b = QPushButton(verb)
                b.setEnabled(live)
                b.setMinimumWidth(110)
                if live:
                    b.setDefault(st == "update")
                    b.clicked.connect(lambda _c=False, e=e: self.want(e))
                side.addWidget(b)
            if st in ("installed", "update", "stale", "local", "fresh"):
                rm = QPushButton("Uninstall")
                rm.setObjectName("quiet")
                rm.setCursor(Qt.CursorShape.PointingHandCursor)
                rm.clicked.connect(lambda _c=False, e=e: self.remove(e))
                side.addWidget(rm, 0, Qt.AlignmentFlag.AlignRight)
            side.addStretch(1)
            h.addLayout(side)
            return box

        def badges(self, e: dict, st: str) -> list:
            return {"installed": [("Installed", self.good)],
                    "fresh": [("Installed · restart to use", self.good)],
                    "update": [("Update available", self.hi)],
                    "stale": [("Restart to use", self.hi)],
                    "removed": [("Removed · restart to drop its tab", self.grey)],
                    "local": [("Not in the marketplace", self.grey)],
                    "too-new": [("Needs a newer Mild Lyrics", self.bad)]}.get(st, [])

        def meta(self, e: dict) -> str:
            if e.get("local"):
                return ""
            n = e.get("downloads")
            bits = []
            if isinstance(n, int):
                bits.append(f"⬇ {short_count(n)} download{'s' * (n != 1)}")
            if e.get("author"):
                bits.append(f"by {_esc(e['author'])}")
            if e.get("size"):
                bits.append(size_text(e["size"]))
            day = day_text(e.get("published") or "")
            if day:
                bits.append(f"updated {day}")
            home = e.get("homepage") or ""
            if home.startswith("https://"):
                bits.append(f'<a href="{_esc(home)}">homepage ↗</a>')
            return " · ".join(bits)

        def verb(self, e: dict, st: str) -> tuple[str, bool]:
            if e["id"] in self.working:
                return "Installing…", False
            if st == "removed":
                return ("", False) if e.get("local") else ("Install", True)
            return {"new": ("Install", True), "update": ("Update", True),
                    "installed": ("", False), "fresh": ("", False),
                    "stale": ("", False), "local": ("", False),
                    "too-new": ("Install", False)}[st]

        # -- doing
        def want(self, e: dict) -> None:
            PL.confirm(e, lambda: self.go(e))

        def go(self, e: dict) -> None:
            self.working.add(e["id"])
            self.notes.pop(e["id"], None)
            self.fill()

            def run():
                try:
                    self.relay.fetched.emit(e["id"], download(e), "")
                except (OSError, ValueError) as err:
                    self.relay.fetched.emit(
                        e["id"], None, str(getattr(err, "reason", None) or err))
            threading.Thread(target=run, daemon=True,
                             name="plugin-download").start()

        def fetched(self, pid: str, data, err: str) -> None:
            self.working.discard(pid)
            e = (_index or {}).get(pid)
            if e is not None and data is not None:
                try:
                    install_bytes(e, data)          # its badge says how it went
                except (OSError, ValueError) as x:
                    err = str(x)
            if err:
                self.notes[pid] = (f"Not installed: {err}", False)
                _log(pid, "not installed:", err)
            self.fill()

        def remove(self, e: dict) -> None:
            ask({"title": f"Uninstall {e['name']}?",
                 "body": [f"{e['name']} is stopped and its files deleted. Its "
                          "settings are kept, so installing it again keeps them."],
                 "yes": "Uninstall", "ok": lambda _d: self.drop(e)})

        def drop(self, e: dict) -> None:
            try:
                PL.uninstall(e["id"])
                self.notes.pop(e["id"], None)
            except OSError as x:
                self.notes[e["id"]] = (str(x), False)
            _fresh.discard(e["id"])
            self.fill()

    return Browser()


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))
