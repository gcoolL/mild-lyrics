"""Multiplayer in the window: the Multiplayer dialogue, the people strip, and
the glue between the editor's document and a session.

The editor knows almost nothing about any of this. It calls four things:

    after_refresh()      the document may have changed: share it
    moved()              the cursor or the selection moved: tell people
    may_replace(what)    a whole new lyric is about to replace this one
    leave()              the window is closing

and everything else -- what to send, what came in, which lines are whose --
is here and in collab.py.

WHAT A REMOTE CHANGE TOUCHES. The document on screen, and every undo and redo
snapshot: so that undoing rewinds YOUR work and never puts back a line
somebody else has since changed. While a hand is mid-gesture -- a drag, a
sweep, a word being typed -- changes that arrive wait until it lets go, so
nothing moves under it.
"""
from __future__ import annotations

import html
import sys
import time
import traceback

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QTextOption
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QMessageBox,
    QPlainTextEdit, QScrollArea,
    QPushButton, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from . import collab as C, keys as K, model as M, ops

DOC_MSGS_HOST = {"ops", "resync"}
DOC_MSGS_MEMBER = {"welcome", "state", "applied", "fix"}
# How long a change that moves lines about may wait for a hand to let go.
# Never longer: a gesture flag that is never cleared -- a press whose release
# went to a menu -- must not freeze everybody else's work on this screen.
HOLD_FOR = 0.8
# How long a session may take to move to a new host before it is finished
# anyway -- whoever has not come across by then is told to ask for an invite.
HANDOVER_WAIT = 60.0


class _Quiet:
    """Where an endpoint's chatter goes when no Multiplayer window is open."""

    def say(self, *_a) -> None:
        pass

    show_nat = show_code = failed = say


def _unwire(net) -> None:
    """Take every handler off an endpoint's signals: it is being retired, and
    must not be heard saying `left` as it closes."""
    for sig in (net.status, net.nat, net.code, net.joined, net.connected,
                net.message, net.left, net.failed):
        try:
            sig.disconnect()
        except TypeError:
            pass


def log(text: str) -> None:
    """One line to the terminal, for the next time a session misbehaves."""
    print(f"[multiplayer] {text}", file=sys.stderr, flush=True)


def _moves_lines(msg) -> bool:
    if msg.get("t") in ("welcome", "state"):
        return True
    ops_ = msg.get("ops")
    return isinstance(ops_, list) and any(
        isinstance(o, dict) and o.get("o") in ("del", "order") for o in ops_)


def _plain(label: QLabel) -> QLabel:
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label


class Strip(QWidget):
    """Who is here, in their colours, in the status row. A name is a button:
    it goes to where that person is."""

    picked = pyqtSignal(int)

    def __init__(self) -> None:
        super().__init__()
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(10)
        self.hide()

    def show_people(self, people: list[tuple]) -> None:
        """[(pid, colour, name, where)] -- plain text, every one of them (a
        button's text is never read as markup)."""
        if people == getattr(self, "_shown", None):
            return
        self._shown = people
        while self.lay.count():
            w = self.lay.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        for pid, colour, name, where in people:
            dot = _plain(QLabel("●"))
            dot.setStyleSheet(f"color:{colour};")
            self.lay.addWidget(dot)
            who = QPushButton(f"{name}{'  ' + where if where else ''}")
            who.setFlat(True)
            who.setCursor(Qt.CursorShape.PointingHandCursor)
            who.setToolTip("Go to where they are")
            who.setStyleSheet("QPushButton { color: rgba(234,234,234,170);"
                              " border: none; background: transparent;"
                              " padding: 0px; }"
                              " QPushButton:hover { color: white; }")
            who.clicked.connect(lambda _c=False, p=pid: self.picked.emit(p))
            self.lay.addWidget(who)
        self.setVisible(bool(people))


def _guarded(fn):
    """A slot the network calls. A slot that raises takes the whole editor
    down with it (and the lyric being worked on); a bug in multiplayer must
    cost the session, never the work."""
    def run(self, *args):
        try:
            return fn(self, *args)
        except Exception:                        # noqa: BLE001
            traceback.print_exc()
            try:
                self._end("left the session — something went wrong in "
                          "multiplayer (details in the terminal)")
            except Exception:                    # noqa: BLE001
                traceback.print_exc()
    run.__name__ = fn.__name__
    return run


class Controller(QObject):
    def __init__(self, ed) -> None:
        super().__init__(ed)
        self.ed = ed
        self.session = None
        self.net = None
        self.dialog: Dialog | None = None
        self.strip = Strip()
        self.strip.picked.connect(self.go_to)
        self.following: int | None = None
        self.queue: list = []
        self._applying = False
        self._force = False
        self.drain = QTimer(self)
        self.drain.setInterval(60)
        self.drain.timeout.connect(self._drain)
        self.here_timer = QTimer(self)
        self.here_timer.setSingleShot(True)
        self.here_timer.timeout.connect(self._send_here)

    # ------------------------------------------------------------- state
    def active(self) -> bool:
        return self.session is not None and (
            self.session.role == "host" or self.session.shared is not None)

    def joined(self) -> bool:
        return self.active() and self.session.role == "member"

    def me(self):
        return self.session.me if self.session else None

    def name(self) -> str:
        return C.clean_name(K.config().get("collab_name") or "")

    def owner(self) -> dict:
        if not self.session:
            return {}
        if self.session.role == "host":
            return self.session.locks.table()
        return self.session.owner

    def claimed(self) -> dict:
        if not self.session:
            return {}
        if self.session.role == "host":
            return self.session.locks.claimed()
        return self.session.claims

    # ------------------------------------------------------ editor hooks
    def after_refresh(self) -> None:
        """The editor redrew -- maybe after an edit. Share what changed."""
        if self._applying or not self.active():
            return
        if getattr(self, "_handover", None):
            if C.diff(self.session.shared, self.ed.doc):
                C.apply(self.ed.doc, C.diff(self.ed.doc, self.session.shared))
                self._redraw(True)
                self.ed.notify("not changed — the session is moving to a new "
                               "host; edits wait until it has")
            return
        ops_, why = self.session.local(self.ed.doc, force=self._force)
        self._force = False
        if ops_:
            self._credit()
        if why:
            undo = self.ed._undo
            if undo and C.same_lines(undo[-1], self.ed.doc):
                undo.pop()      # the edit never happened: nothing to undo
            self._redraw(True)
            log(f"refused here: {why}")
            self.ed.notify(f"not changed — {why}")
        self._flush()
        if ops_ and C.structural(ops_):
            self._here_soon()
        self._paint()

    def stamp(self) -> str:
        """For the autosave: in a session, whether the lyric changed at all.
        Its usual test -- how many lines, how many timed, how long -- does
        not move when somebody re-times the syllables inside a line, which
        is most of what a session does."""
        return C.digest(self.ed.doc) if self.active() else ""

    def _credit(self) -> None:
        """Host only: SyncedBy names everyone whose edits went in. Written as
        an ordinary edit of the header, so it travels like one."""
        s = self.session
        if s is None or s.role != "host" or not s.contributors:
            return
        want = C.credit(self.ed.doc.meta.get("SyncedBy"), s.contributors)
        if want == str(self.ed.doc.meta.get("SyncedBy") or ""):
            return
        self.ed.doc.meta["SyncedBy"] = want
        s.local(self.ed.doc)
        self._flush()

    def go_to(self, pid: int) -> None:
        """Show where somebody is -- the list scrolled to their line, the
        cursor left alone: going to look at somebody's line must not take it
        from them, and the cursor is what holds a line."""
        if not self.active():
            return
        if pid == self.me():
            self.ed.list.reveal_cursor()
            return
        p = self.session.peers.get(pid)
        if not p or not p.get("at"):
            self.ed.notify(f"{p['n'] if p else 'they'} have not picked a "
                           "line yet")
            return
        self._reveal(p["at"])

    def follow(self, pid: int | None) -> None:
        """Keep somebody's line in view as they move, until this hand moves."""
        self.following = None if pid == self.following else pid
        self._followed_at = None
        if self.following is not None:
            self.go_to(self.following)
        self._paint()

    def _reveal(self, at) -> None:
        doc, L = self.ed.doc, self.ed.list
        line = next((i for i, ln in enumerate(doc.lines) if ln.uid == at[0]), None)
        if line is None:
            return
        for r in L.rows:
            if (r.line, r.voice) == (line, at[1]) or (r.line == line and r.voice == 0):
                L.reveal_row(r)
                L.viewport().update()
                return

    def moved(self) -> None:
        """The cursor or selection moved by hand: from now on, where it is
        holds the line. Until then it holds nothing -- everybody's cursor
        starts on line 1, and the first line would otherwise belong to
        whoever happened to be there first, without either of them knowing."""
        if self.active():
            self._placed = True
            self._here_soon()
            if self.following is not None and not self._applying:
                self.following = None       # the hand took over
                self._paint()

    def _here_soon(self) -> None:
        if self.active():
            self.here_timer.start(60)

    def may_replace(self, what: str = "this lyric") -> bool:
        """A whole new lyric is about to replace the shared one."""
        if not self.active():
            return True
        if self.session.role == "member":
            self.ed.notify("in a session, only the host can replace the lyric "
                           "— leave the session first")
            return False
        if len(self.session.peers) <= 1:
            # Nobody has joined yet: there is nobody to ask on behalf of.
            self._force = True
            QTimer.singleShot(0, lambda: setattr(self, "_force", False))
            return True
        got = QMessageBox.question(
            self.ed, "Replace the lyric for everyone?",
            f"Everyone in this session will get {what} in place of the "
            "lyric they are working on, including lines they are holding.")
        if got != QMessageBox.StandardButton.Yes:
            return False
        # For the replacement only, which redraws before control comes back
        # here. If it never happens, the next ordinary edit must not inherit
        # the right to walk over other people's lines.
        self._force = True
        QTimer.singleShot(0, lambda: setattr(self, "_force", False))
        return True

    def leave(self, closing: bool = False) -> None:
        if self.session is not None and self.session.role == "member" \
                and self.net is not None:
            self.net.send(None, {"t": "bye"})
        if self.session is not None and self.session.role == "host" \
                and self.net is not None:
            self.net.send(None, {"t": "end", "why": "the host left"})
        self._end("", redraw=not closing)

    # ------------------------------------------------------------ the song
    @staticmethod
    def seats() -> int:
        try:
            n = int(K.config().get("collab_seats", 4))
        except (TypeError, ValueError):
            n = 4
        return max(1, min(C.MAX_PEERS, n))

    def set_seats(self, n: int) -> None:
        K.remember(collab_seats=int(n))
        if self.net is not None and self.session is not None \
                and self.session.role == "host":
            self.net.set_seats(int(n))
        if self.dialog:
            self.dialog.show_seats()

    def song_info(self) -> dict:
        """What this editor is timing against, as the others can fetch it."""
        ed = self.ed
        meta = ed._audio_meta()
        spotify = ed.player.kind == "spotify"
        return {"t": "song",
                "url": "" if spotify else C.song_url(getattr(ed, "audio_url", "")),
                "title": meta["title"], "artist": meta["artist"],
                "dur": round(float(ed.player.duration() or 0.0), 2),
                "tid": (ed.player.track_id() or "") if spotify else ""}

    def song_changed(self) -> None:
        """The host's audio changed: tell everybody which song it is now."""
        if self.session is None or self.session.role != "host" or self.net is None:
            return
        info = self.song_info()
        if info == getattr(self, "_sent_song", None) or not info["dur"]:
            return
        self._sent_song = info
        log(f"song: {info['title'] or '?'} ({info['dur']:.0f}s) "
            f"{info['url'] or 'no link — joiners search'}")
        self.net.send(None, info)

    def _song(self, info: dict) -> None:
        """A joiner told which song the host is timing against: get a copy
        of the same one, unless it is already open here."""
        from . import sources
        self.host_song = info
        ed = self.ed
        mine = float(ed.player.duration() or 0.0) if ed.player.kind == "local" else 0.0
        if info["url"] and C.song_url(getattr(ed, "audio_url", "")) == info["url"]:
            return
        if not info["url"] and mine and info["dur"] and abs(mine - info["dur"]) < 0.5:
            return                      # a copy of the right length is open
        if not info["url"] and not info["title"]:
            ed.notify("the host has not said which song this is — "
                      "Fetch audio… to find one")
            return
        what = info["title"] or "the song"
        if info["url"]:
            def job(say):
                say(f"getting the host's copy of “{what}”…")
                return sources.fetch_audio_url(info["url"], info["title"],
                                               info["artist"], info["tid"])
        else:
            words = [w for ln in ed.doc.lines for g in ln.groups()
                     for w in g.text().split()]

            def job(say):
                say(f"finding “{what}” at the host's length…")
                return sources.fetch_audio(info["title"], info["artist"],
                                           info["dur"], info["tid"], words,
                                           say=say)[0]

        def done(path, err):
            if err or not path:
                from .start import _reason
                why = _reason(err) or "nothing came back"
                log(f"could not get the host's song: {why}")
                ed.notify(f"could not get the host's song — {why}. "
                          "Fetch audio… to look for it yourself")
                self.song_state = f"not here — {why}"
            else:
                ed.open_audio(path)
                ed.audio_url = info["url"]
                ed.notify(f"opened the host's song, “{what}”")
                self.song_state = "here"
                if info["dur"] and abs(float(ed.player.duration() or 0)
                                       - info["dur"]) > 1.0:
                    ed.notify(f"this copy is {ed.player.duration():.0f}s and "
                              f"the host's is {info['dur']:.0f}s — the times "
                              "may not line up")
            if self.dialog:
                self.dialog.show_song()

        self.song_state = "fetching…"
        if self.dialog:
            self.dialog.show_song()
        if not ed.run(job, done, lane="audio"):
            self.song_state = "waiting — another download is running"
            QTimer.singleShot(3000, lambda i=info: self.active()
                              and self._song(i))

    # ---------------------------------------------- lining the copies up
    def envelope_ready(self) -> None:
        """This editor has its song's outline: the host sends it on, a
        joiner compares it with the host's."""
        if not self.active():
            return
        if self.session.role == "host":
            self._send_env(None)
        else:
            self._line_up()

    def _send_env(self, cid) -> None:
        env = getattr(self.ed.wave, "env", None)
        if env is None or self.net is None:
            return
        from . import collab_audio as CA
        if cid is None and getattr(self, "_sent_env", None) is env:
            return
        self._sent_env = env
        self.net.send(cid, {"t": "env", "hz": CA.HZ, "d": CA.pack(env),
                            "u": self.song_info().get("url", "")})

    def _line_up(self) -> None:
        """Compare this copy with the host's, and line it up if it is
        clearly early or late. Once per pair of outlines."""
        theirs = getattr(self, "host_env", None)
        mine = getattr(self.ed.wave, "env", None)
        path = getattr(self.ed.wave, "_from", "")
        if theirs is None or mine is None:
            return
        key = (hash(theirs[1]), id(mine))
        if key == getattr(self, "_lined_up", None):
            return
        self._lined_up = key
        from . import collab_audio as CA
        ed = self.ed
        # A copy already lined up is not moved again: a second measurement a
        # reading off would otherwise shift it back and forth for ever.
        local = (ed.player.kind == "local" and bool(path)
                 and "mild-lyrics-aligned" not in str(path))

        def job(say):
            say("comparing your copy of the song with the host's…")
            host = CA.unpack(theirs[1], theirs[0])
            late, why = CA.measure(host, mine)
            out = ""
            if late is not None and abs(late) >= CA.NEGLIGIBLE and local:
                out = CA.shifted(path, late)
            return late, why, out

        def done(res, err):
            if err or not res:
                log(f"could not compare with the host's copy: {err}")
                return
            late, why, out = res
            if late is None:
                log(f"copies not compared: {why}")
                ed.notify("could not tell whether your copy of the song lines "
                          f"up with the host's ({why}) — check it by ear")
                return
            if abs(late) < CA.NEGLIGIBLE:
                log(f"your copy matches the host's ({late * 1000:+.0f}ms)")
                return
            said = (f"your copy started {abs(late):.2f}s "
                    f"{'later' if late > 0 else 'earlier'} than the host's")
            if out:
                url = getattr(ed, "audio_url", "")
                ed.open_audio(out)
                ed.audio_url = url          # still the host's song
                log(f"{said}; lined it up ({out})")
                ed.notify(f"{said} — lined it up, so your times match theirs")
            else:
                log(f"{said}; not shifted (timing against Spotify)")
                ed.notify(f"{said} — times you tap will be that far out from "
                          "theirs; use a local copy to have it lined up")

        ed.run(job, done, lane="align")

    def fetch_song_again(self) -> None:
        info = getattr(self, "host_song", None)
        if info and self.joined():
            self.ed.audio_url = ""
            self._song(info)

    def rename(self, name: str) -> str:
        """A new name, kept, and told to the session if there is one."""
        name = " ".join(str(name or "").split())
        K.remember(collab_name=name)
        clean = C.clean_name(name)
        if self.session is not None:
            if self.session.role == "host":
                self.session.rename(0, clean)
            else:
                self.session.rename(clean)
            self._flush()
            self._paint()
        if self.net is not None:
            self.net.name = clean
        return clean

    def place(self, lay) -> None:
        """Put the people strip into the status row (re-made on every
        change of interface, which takes everything out of it)."""
        lay.addWidget(self.strip)

    # ----------------------------------------------------- the session
    def start_host(self, dialog) -> str:
        from . import collab_net as NET
        if NET.available():
            return f"multiplayer needs {NET.available()} — run setup"
        if self.route() == "relay" and self._turn() is None:
            return ("Relay is chosen, and no relay is set up yet: fill in "
                    "Relay on the first page (a free ExpressTURN account "
                    "gives one) — or choose Direct, only with people you "
                    "trust")
        self.leave()
        try:
            self.net = NET.Endpoint("host", self.name(), stun=self._stun(),
                                    parent=self, turn=self._turn(),
                                    relay_only=self.relay_only())
        except OSError as e:
            return f"could not open a network port: {e}"
        self.session = C.Host(self.ed.doc, self.name())
        self._placed = False
        self._sent_song = None
        self.net.seats = self.seats()
        self.net.watch = False
        self._wire(dialog)
        self.net.joined.connect(self._joined)
        self.net.host()
        self._after_start()
        return ""

    def start_join(self, dialog, code: str) -> str:
        from . import collab_net as NET
        if NET.available():
            return f"multiplayer needs {NET.available()} — run setup"
        self.leave()
        try:
            self.net = NET.Endpoint("member", self.name(), stun=self._stun(),
                                    parent=self, turn=self._turn(),
                                    relay_only=self.relay_only())
        except OSError as e:
            return f"could not open a network port: {e}"
        try:
            self.net.join(code)
        except NET.BadCode as e:
            self.net.close()
            self.net = None
            return str(e)
        self.session = C.Member(self.name())
        self._resume = None
        self.host_env = None
        self._placed = False
        self.host_song = None
        self.song_state = ""
        self._wire(dialog)
        self.net.connected.connect(lambda: dialog.say("connected — getting "
                                                      "the lyric…"))
        self.net.connected.connect(
            lambda: log(f"connected to the host — {self.path_of(0) or '?'}"))
        return ""

    def path_of(self, pid: int) -> str:
        """"direct" or "via relay" for one person, "" where this editor has
        no connection of its own to them: a joiner is connected to the host
        alone, the host to every joiner (whose id is its connection's)."""
        net, s = self.net, self.session
        if net is None or s is None or pid == s.me:
            return ""
        if s.role == "host":
            got = net.path(pid)
        elif pid == 0 and net.conns:
            got = net.path(next(iter(net.conns)))
        else:
            return ""
        return {"relay": "via relay", "direct": "direct"}.get(got, "")

    @_guarded
    def _failed(self, why: str) -> None:
        """A joiner who never got in has no session left to be in."""
        log(f"could not connect: {why}")
        if self.session is not None and self.session.role == "member" \
                and not self.active():
            self._end("")

    # ------------------------------------------------------------ notes
    def notes(self) -> dict:
        return self.session.notes if self.session is not None else {}

    def add_note(self, line: int, text: str) -> str:
        if not self.active():
            return "not in a session"
        doc = self.ed.doc
        if not 0 <= line < len(doc.lines):
            return "no such line"
        try:
            if self.session.role == "host":
                self.session.note(0, doc.lines[line].uid, text)
            else:
                self.session.note(doc.lines[line].uid, text)
        except C.Bad as e:
            return str(e)
        self._flush()
        self._paint()
        return ""

    def remove_note(self, uid: str, i: int) -> None:
        if not self.active():
            return
        if self.session.role == "host":
            self.session.unnote(0, uid, i)
        else:
            self.session.unnote(uid, i)
        self._flush()
        self._paint()

    def _note_menu(self, menu, rows) -> None:
        """The line menu's own item, while in a session."""
        if not self.active() or not rows:
            return
        line = rows[0]
        menu.addSeparator()
        menu.addAction(f"Add a note to line {line + 1}…").triggered.connect(
            lambda _c=False, i=line: self.ask_note(i))

    def ask_note(self, line: int) -> None:
        text, ok = QInputDialog.getText(
            self.ed, "Note", f"A note on line {line + 1}, for everyone in "
            "the session:")
        if ok and text.strip():
            why = self.add_note(line, text)
            if why:
                self.ed.notify(f"no note — {why}")

    def _new_notes(self, uid: str) -> None:
        """Say so when somebody else leaves a note."""
        seen = getattr(self, "_seen_notes", None)
        if seen is None:
            seen = self._seen_notes = set()
        at = {ln.uid: i for i, ln in enumerate(self.ed.doc.lines)}
        for n in self.notes().get(uid, []):
            key = (uid, n["i"])
            if key in seen:
                continue
            seen.add(key)
            if n["by"] != self.me() and uid in at:
                self.ed.notify(f"{n['n']} left a note on line {at[uid] + 1}: "
                               f"{n['x'][:80]}")

    def _wire(self, dialog) -> None:
        dialog = dialog or self.dialog or _Quiet()
        self.ed.list.menu_extra = self._note_menu
        self._seen_notes = set()
        n = self.net
        n.status.connect(dialog.say)
        n.nat.connect(dialog.show_nat)
        n.code.connect(dialog.show_code)
        n.failed.connect(dialog.failed)
        n.failed.connect(self._failed)
        n.message.connect(self._message)
        n.left.connect(self._left)
        self.drain.start()

    def _after_start(self) -> None:
        self._paint()

    def _stun(self) -> list:
        raw = str(K.config().get("collab_stun") or "").split()
        return raw or None

    @staticmethod
    def route() -> str:
        """How this editor connects: "relay" (the default, and what the
        window recommends) or "direct" -- see Dialog's first page."""
        got = str(K.config().get("collab_route") or "relay")
        return got if got in ("relay", "direct") else "relay"

    def relay_only(self) -> bool:
        """Relay chosen and a relay set up: this side's addresses stay out
        of every code and everything goes through the relay. Without one,
        a JOINER still connects -- its reply goes to the host alone."""
        return self.route() == "relay" and self._turn() is not None

    @staticmethod
    def _turn():
        """(server, username, password) of a TURN server, or None: the relay
        a session falls back on when no direct path connects. See
        collab_turn -- only the side hosting needs one."""
        cfg = K.config()
        server = str(cfg.get("collab_turn_server") or "").strip()
        user = str(cfg.get("collab_turn_user") or "").strip()
        password = str(cfg.get("collab_turn_pass") or "")
        return (server, user, password) if server and user else None

    @_guarded
    def _joined(self, cid: int, hello: dict) -> None:
        back = hello.get("_resume")
        back = back if isinstance(back, int) and not isinstance(back, bool) else None
        if not self.session.join(cid, hello, watch=hello.get("_watch") is True,
                                 back=back):
            self.net.drop(cid, "the session is full")
            return
        self._flush()
        # Their own way back in, should this connection drop.
        iid, tok = self.net.make_resume(cid)
        self.net.send(cid, {"t": "resume", "i": iid, "k": tok})
        name = self.session.peers[cid]["n"]
        log(f"{name} joined — {self.path_of(cid) or '?'}")
        info = self.song_info()
        if info["dur"]:
            self.net.send(cid, info)
            self._send_env(cid)
        self.ed.notify(f"{name} joined")
        if self.dialog:
            self.dialog.say(f"{name} joined")
            self.dialog.show_seats()
        if self.dialog:
            self.dialog.refresh_people()
        self._paint()

    @_guarded
    def _left(self, cid: int, why: str) -> None:
        if self.session is None:
            return
        if self.session.role == "host":
            peer = self.session.peers.get(cid)
            if peer is None:
                return
            h = getattr(self, "_handover", None)
            if h and cid == h["to"] and not h["moved"]:
                self._cancel_handover(f"{peer['n']} left before taking over")
            gone = self.net.gone_resume.pop(cid, None) if self.net else None
            if why not in ("left", "removed") and gone is not None:
                # Dropped rather than gone: keep their place for them.
                self.session.step_away(cid)
                self.net.reopen(*gone)
                self._flush()
                log(f"{peer['n']} dropped ({why}); their way back is open")
                self.ed.notify(f"{peer['n']} dropped — they can come back by "
                               "themselves")
                if self.dialog:
                    self.dialog.refresh_people()
                self._paint()
                return
            self.session.leave(cid)
            self._flush()
            log(f"{peer['n']} left: {why}")
            self.ed.notify(f"{peer['n']} left" + (f" ({why})" if why not in
                                                  ("left", "") else ""))
            if self.dialog:
                self.dialog.refresh_people()
            self._paint()
        else:
            way = getattr(self, "_resume", None)
            if way and why not in ("left", "removed") and self.active():
                self._resume = None              # one use
                self.session.offline = True
                log(f"lost the host ({why}); reconnecting")
                self.ed.notify("lost the connection to the host — reconnecting "
                               "(edits wait until it is back)")
                self.net.resume(*way)
                return
            self._end("the connection to the host was lost"
                      if why not in ("left",) else "the session ended")

    def _end(self, why: str, redraw: bool = True) -> None:
        # Both let go of BEFORE the port closes: closing says `left`, which
        # comes straight back in here.
        net, self.net = self.net, None
        was, self.session = self.session, None
        self._handover = None
        for spare in (getattr(self, "_moving", None), getattr(self, "_old_net", None)):
            if spare is not None and spare is not net:
                _unwire(spare)
                spare.close()
        self._moving = self._old_net = None
        if net is not None:
            net.close()
            net.deleteLater()
        self.queue.clear()
        self.drain.stop()
        self.ed.list.held, self.ed.list.held_at = {}, {}
        self.ed.list.noted = {}
        self.ed.list._note_at.clear()
        self.ed.list.viewport().update()
        self.strip.show_people([])
        if why:
            self.ed.notify(why)
        if was is not None and was.role == "member" and redraw:
            self.ed.dirty = True        # what they were working on is theirs now
            self.ed.refresh(relayout=False)
        if self.dialog:
            self.dialog.refresh_people()

    # ---------------------------------------------------------- traffic
    def _flush(self) -> None:
        if self.session is None:
            return
        out, self.session.outbox = self.session.outbox, []
        if self.net is None:
            return
        for pid, msg in out:
            if self.session.role == "host":
                if pid == 0:
                    continue
                self.net.send(pid, msg)
            else:
                self.net.send(None, msg)
        if self.session.role == "host" and any(
                m.get("t") == "who" for _p, m in out):
            self._paint()

    def _busy(self) -> bool:
        return bool(self._why_busy())

    def _why_busy(self) -> str:
        L = self.ed.list
        for name, on in (("typing", L.editor is not None),
                         ("typing a reading",
                          getattr(L, "reditor", None) is not None),
                         ("dragging in the list", bool(getattr(L, "_drag", None))),
                         ("drag sync", self.ed.bar.dragging()),
                         ("dragging on the waveform",
                          getattr(self.ed.wave, "_grab", None) is not None),
                         ("sweeping", bool(getattr(self.ed, "_sweeping", None)))):
            if on:
                return name
        return ""

    @_guarded
    def _message(self, cid: int, msg) -> None:
        if self.session is None:
            return
        kind = msg.get("t") if isinstance(msg, dict) else None
        doc_msg = kind in (DOC_MSGS_HOST if self.session.role == "host"
                           else DOC_MSGS_MEMBER)
        if doc_msg and (self.queue or (self._busy() and _moves_lines(msg))):
            # Behind a gesture, or behind something already waiting -- order
            # matters. A change to other people's lines alone never waits:
            # it cannot move anything under this hand.
            if not self.queue:
                self._held_since = time.monotonic()
            self.queue.append((cid, msg))
            return
        self._handle(cid, msg)

    @_guarded
    def _drain(self) -> None:
        if not self.queue:
            return
        late = time.monotonic() - getattr(self, "_held_since", 0.0) > HOLD_FOR
        if self._busy() and not late:
            return
        if late and self._busy():
            log(f"applied {len(self.queue)} waiting change(s) mid-gesture "
                f"after {HOLD_FOR}s (busy: {self._why_busy()})")
        while self.queue and self.session is not None:
            cid, msg = self.queue.pop(0)
            self._handle(cid, msg)

    def _handle(self, cid: int, msg) -> None:
        if self.session.role == "host":
            if isinstance(msg, dict) and msg.get("t") in ("moved", "moving",
                                                          "done"):
                self._handover_msg(cid, msg)
                return
            n = len(self.session.outbox)
            why = self.session.on_message(cid, msg)
            for _pid, out in self.session.outbox[n:]:
                if out.get("t") == "applied" and out.get("by") != 0:
                    self._remote(out["ops"])
                    self._credit()
                elif out.get("t") == "notes":
                    self._new_notes(out["u"])
            self._flush()
            if why:
                log(f"dropped a joiner: {why}")
                self.session.leave(cid)
                if self.net is not None:
                    self.net.drop(cid, why)
                self._flush()
            if msg.get("t") in ("here", "claim", "release", "note", "unnote",
                                "name") if isinstance(msg, dict) else False:
                self._paint()
            return
        try:
            got = self.session.on_message(msg)
        except C.Bad as e:
            log(f"the host sent something wrong: {e}")
            self.leave()
            self.ed.notify("left the session — the host sent something "
                           "this editor does not understand")
            return
        if "doc" in got:
            self._take(got["doc"])
        if "ops" in got:
            self._remote(got["ops"], resync=got.get("resync", False))
        if got.get("back"):
            log("back in the session")
            self.ed.notify("back in the session")
            self._here_soon()
        if "resume" in got:
            self._resume = got["resume"]
        if "fix" in got:
            log(f"refused by the host: {got['why'] or '(no reason)'}")
            self._remote(got["fix"], snapshots=False)
            self.ed.notify(f"not changed — {got['why']}" if got["why"]
                           else "not changed")
        if "end" in got:
            self._end(got["end"])
            return
        if "who" in got:
            role = (self.session.peers.get(self.session.me, {}).get("ro"),
                    self.session.frozen)
            if role != getattr(self, "_role_seen", (None, None)):
                was = getattr(self, "_role_seen", (None, None))
                self._role_seen = role
                if role[0] and not was[0]:
                    self.ed.notify("you are watching this session — the host "
                                   "lets you see it, not edit it")
                elif was[0] and not role[0]:
                    self.ed.notify("the host lets you edit now")
                if role[1] and not was[1]:
                    self.ed.notify("the host has frozen the lyric for now")
                elif was[1] and not role[1]:
                    self.ed.notify("the lyric is open for editing again")
        if "become" in got:
            self._become(got["become"])
            return
        if "move" in got:
            self._move(got["move"], got.get("host", ""))
        if "handover_off" in got:
            self._move_off(got["handover_off"])
        if "song" in got:
            self._song(got["song"])
        if "env" in got:
            self.host_env = got["env"]
            self._line_up()
        if "notes" in got:
            self._new_notes(got["notes"])
        self._flush()
        self._paint()

    def _take(self, doc: M.Doc) -> None:
        """Joining: the host's lyric replaces this one, kept safe first."""
        from . import backups
        ed = self.ed
        if ed.doc.lines:
            backups.stash(ed.doc, ed._song_name(), "before joining a session")
        ed.doc = doc
        ed.path = None
        ed.song_id = None
        ed._undo.clear()
        ed._redo.clear()
        ed.dirty = True
        self._redraw(True)
        ed.show_editor()
        host = self.net.host_name() if self.net else ""
        ed.notify(f"joined {host}'s session" if host else "joined")
        if self.dialog:
            self.dialog.joined()
        self._placed = False
        self._here_soon()

    def _remote(self, ops_: list, snapshots: bool = True,
                resync: bool = False) -> None:
        """Somebody else's change: on screen, and in every snapshot."""
        if not ops_:
            return
        ed = self.ed
        moved = C.structural(ops_)
        kept = self._places() if moved else None
        C.apply(ed.doc, ops_)
        if snapshots:
            for snap in (*ed._undo, *ed._redo):
                C.apply(snap, ops_)
        if kept is not None:
            self._put(kept)
        self._check_places()
        ed.dirty = True
        self._redraw(moved or resync)

    def _redraw(self, relayout: bool) -> None:
        self._applying = True
        try:
            self.ed.refresh(relayout=relayout)
        finally:
            self._applying = False

    # ---------------------------------------------------- where people are
    @_guarded
    def _send_here(self) -> None:
        if not self.active():
            return
        L, doc = self.ed.list, self.ed.doc
        i, v, k = L.cursor
        cur = [doc.lines[i].uid, int(v), int(k)] if 0 <= i < len(doc.lines) \
            else None
        sel = sorted({doc.lines[line].uid for line, _v in L.selection
                      if 0 <= line < len(doc.lines)})
        if not getattr(self, "_placed", False):
            cur, sel = None, []
        if self.session.role == "host":
            self.session.here(0, cur, sel)
        else:
            self.session.here(cur, sel)
        self._flush()
        self._paint()

    def _places(self) -> dict:
        L, doc = self.ed.list, self.ed.doc

        def u(i):
            return doc.lines[i].uid if 0 <= i < len(doc.lines) else None
        return {"cursor": (u(L.cursor[0]), L.cursor[0], *L.cursor[1:]),
                "sel": [(u(a), b) for a, b in L.selection],
                "anchor": (u(L._anchor[0]), L._anchor[1]),
                "words": [(u(a), b, c) for a, b, c in L.word_sel],
                "next": (u(L.next_row[0]), L.next_row[1]) if L.next_row else None}

    def _put(self, kept: dict) -> None:
        L, doc = self.ed.list, self.ed.doc
        at = {ln.uid: i for i, ln in enumerate(doc.lines)}
        uid, was, v, k = kept["cursor"]
        line = at.get(uid, min(was, max(0, len(doc.lines) - 1)))
        L.cursor = (line, v if uid in at else 0, k if uid in at else 0)
        L.selection = {(at[a], b) for a, b in kept["sel"] if a in at}
        a, b = kept["anchor"]
        L._anchor = (at[a], b) if a in at else (line, 0)
        L.word_sel = {(at[a], b, c) for a, b, c in kept["words"] if a in at}
        nxt = kept["next"]
        L.next_row = (at[nxt[0]], nxt[1]) if nxt and nxt[0] in at else None

    def _check_places(self) -> None:
        """Whatever the list remembers by number must still point at
        something: a remote change can shorten a line it does not hold."""
        L, doc = self.ed.list, self.ed.doc
        i, v, k = L.cursor
        g = doc.group(i, v)
        if g is None:
            i = min(max(0, i), max(0, len(doc.lines) - 1))
            v, k = 0, 0
            g = doc.group(i, 0)
        if g is not None and g.syls:
            k = min(max(0, k), len(g.syls) - 1)
        L.cursor = (i, v, k)
        L.selection = {(a, b) for a, b in L.selection if doc.group(a, b)}
        L.word_sel = {(a, b, c) for a, b, c in L.word_sel
                      if doc.group(a, b) and 0 <= c < len(doc.group(a, b).words())}

    def _paint(self) -> None:
        """Other people's lines and cursors onto the list, names onto the
        strip."""
        if not self.active():
            return
        doc, me = self.ed.doc, self.me()
        at = {ln.uid: i for i, ln in enumerate(doc.lines)}
        peers = self.session.peers
        claimed = self.claimed()
        held = {}
        for uid, pid in self.owner().items():
            if pid == me or uid not in at or pid not in peers:
                continue
            held[at[uid]] = (peers[pid]["c"], uid in claimed)
        held_at = {}
        people = []
        for pid, p in sorted(peers.items()):
            where = ""
            if p.get("at") and p["at"][0] in at:
                line = at[p["at"][0]]
                where = f"line {line + 1}"
                if pid != me:
                    held_at[(line, p["at"][1])] = (p["at"][2], p["c"])
            how = self.path_of(pid)
            people.append((pid, p["c"], "you" if pid == me else p["n"],
                           where + (f" ({how})" if how else "")
                           + (" (watching)" if p.get("ro") else "")
                           + (" (following)" if pid == self.following
                              else "")))
        noted = {}
        for uid, ns in self.notes().items():
            if uid in at and ns:
                tip = "<qt>" + "<br>".join(
                    f"<b>{html.escape(n['n'])}</b>: {html.escape(n['x'])}"
                    for n in ns) + "</qt>"
                noted[at[uid]] = (len(ns), tip)
        L = self.ed.list
        L.on_note = self.open_notes
        if noted != L.noted:
            L.noted = noted
            L._note_at.clear()
            L.viewport().update()
        if held != L.held or held_at != L.held_at:
            L.held, L.held_at = held, held_at
            L.viewport().update()
        self.strip.show_people(people)
        if self.dialog:
            self.dialog.show_notes()
        if self.following is not None:
            p = peers.get(self.following)
            if p is None:
                self.following = None
            elif p.get("at") and p["at"] != getattr(self, "_followed_at", None):
                self._followed_at = p["at"]
                self._reveal(p["at"])
        if self.dialog:
            self.dialog.refresh_people()

    # ------------------------------------------------------------ claims
    def claim_selection(self) -> str:
        if not self.active():
            return ""
        doc, L = self.ed.doc, self.ed.list
        rows = sorted({line for line, _v in L.selection} | {L.cursor[0]})
        return self._claim([doc.lines[i].uid for i in rows
                            if 0 <= i < len(doc.lines)])

    def claim_part(self) -> str:
        """The whole of the grouped run the cursor is in -- every place it
        is sung, since a chorus timed once is timed everywhere."""
        if not self.active():
            return ""
        doc, i = self.ed.doc, self.ed.list.cursor[0]
        runs = ops.part_runs(doc)
        mine = next((r for r in runs if r[1] <= i < r[1] + r[2]), None)
        if mine is None:
            return "the cursor is not in a grouped part (Lines → Group)"
        rows = [line for r in runs if r[0] == mine[0]
                for line in range(r[1], r[1] + r[2])]
        return self._claim([doc.lines[k].uid for k in rows])

    def _claim(self, uids: list) -> str:
        owner = self.owner()
        taken = [u for u in uids if owner.get(u, self.me()) != self.me()]
        if self.session.role == "host":
            self.session.claim(0, uids)
        else:
            self.session.claim(uids)
        self._flush()
        self._paint()
        n = len(uids) - len(taken)
        return (f"claimed {n} line{'s' * (n != 1)}"
                + (f" — {len(taken)} already someone else's" if taken else ""))

    def release(self) -> None:
        if not self.active():
            return
        if self.session.role == "host":
            self.session.release(0)
        else:
            self.session.release()
        self._flush()
        self._paint()

    def set_role(self, pid: int, watch: bool) -> None:
        if self.session is None or self.session.role != "host":
            return
        self.session.set_role(pid, watch)
        self._flush()
        self._paint()

    def freeze(self, on: bool) -> None:
        if self.session is None or self.session.role != "host":
            return
        self.session.freeze(on)
        self._flush()
        self._paint()
        self.ed.notify("the lyric is frozen — only you can edit it" if on
                       else "everyone can edit again")

    # ------------------------------------------ handing the session over
    def hand_over(self, pid: int) -> str:
        """Host: make somebody else the host, so the session outlives this
        editor leaving. Everybody else moves across to them -- through here,
        since this is the only editor already talking to all of them."""
        s = self.session
        if s is None or s.role != "host" or self.net is None:
            return ""
        p = s.peers.get(pid)
        if not p:
            return ""
        if p.get("ro"):
            return f"{p['n']} can only watch — let them edit first"
        if getattr(self, "_handover", None):
            return "already handing the session over"
        self._handover = {"to": pid, "name": p["n"],
                          "others": [q for q in s.peers if q not in (0, pid)],
                          "moved": False}
        s.freeze(True)                  # nobody edits while it moves
        self._flush()
        self.net.send(pid, {"t": "become", "state": s.handover_state(pid)})
        log(f"handing the session to {p['n']}")
        self.ed.notify(f"handing the session to {p['n']} — edits wait until "
                       "everyone has moved across")
        QTimer.singleShot(int(HANDOVER_WAIT * 1000),
                          lambda h=self._handover: self._handover_late(h))
        return f"handing the session to {p['n']}…"

    def _handover_msg(self, cid: int, msg: dict) -> None:
        h = getattr(self, "_handover", None)
        if not h:
            return
        kind = msg["t"]
        if kind == "moved" and cid == h["to"]:
            codes = msg.get("codes")
            if not isinstance(codes, dict) or msg.get("fail"):
                self._cancel_handover(str(msg.get("fail") or "they could not "
                                          "start hosting")[:120])
                return
            h["moved"] = True
            for q in h["others"]:
                code = codes.get(str(q))
                if isinstance(code, str) and 0 < len(code) <= 8192:
                    self.net.send(q, {"t": "move", "code": code,
                                      "host": h["name"]})
            if not h["others"]:
                self._finish_handover()
        elif kind == "moving" and cid in h["others"]:
            code = msg.get("code")
            if isinstance(code, str) and 0 < len(code) <= 8192:
                self.net.send(h["to"], {"t": "reply", "code": code})
        elif kind == "done" and cid == h["to"]:
            self._finish_handover()

    def _cancel_handover(self, why: str) -> None:
        h, self._handover = getattr(self, "_handover", None), None
        if not h or self.session is None:
            return
        self.session.freeze(False)
        self._flush()
        self.net.send(None, {"t": "handover_off", "why": why})
        log(f"handover cancelled: {why}")
        self.ed.notify(f"the session stays here — {why}")

    def _handover_late(self, h) -> None:
        if getattr(self, "_handover", None) is not h:
            return
        if h["moved"]:
            self._finish_handover()     # whoever did not come across is told
        else:
            self._cancel_handover(f"{h['name']} did not start hosting in time")

    def _finish_handover(self) -> None:
        h = getattr(self, "_handover", None)
        if not h or self.net is None:
            return
        self.net.send(None, {"t": "end", "why": f"the session moved to "
                             f"{h['name']} — if you were not moved across, "
                             "ask them for an invite"})
        log(f"the session is now hosted by {h['name']}")
        self._end(f"handed the session to {h['name']}")

    # -- the new host's side
    def _become(self, state: dict) -> None:
        from . import collab_net as NET
        ed, old = self.ed, self.net
        ops_ = C.diff(ed.doc, state["doc"])
        if ops_:
            self._remote(ops_)          # exactly the old host's lyric
        try:
            net2 = NET.Endpoint("host", self.name(), stun=self._stun(), parent=self,
                                turn=self._turn(), relay_only=self.relay_only())
        except OSError as e:
            old.send(None, {"t": "moved", "codes": {}, "fail": f"no port: {e}"})
            return
        host = C.Host(ed.doc, self.name())
        host.notes = {u: v for u, v in state["notes"].items()}
        expect = host.take_over({**state, "notes": state["notes"]})
        _unwire(old)
        old.message.connect(self._old_message)
        self._old_net = old
        self.session, self.net = host, net2
        self._sent_song = None
        self._placed = False
        self._expect = set(expect)
        self._wire(None)
        net2.joined.connect(self._joined)
        net2.joined.connect(lambda _c, h: self._arrived(h))
        net2.nat.connect(lambda _v, e=list(expect), o=old: o.send(None, {
            "t": "moved", "codes": {str(q): self.net.invite_for(q) for q in e}}))
        net2.host(invite=False)
        log(f"taking over as host for {len(expect)} other(s)")
        self.ed.notify("you are the host now — the others are moving across")
        QTimer.singleShot(int((HANDOVER_WAIT - 5) * 1000), self._took_over)
        if self.dialog:
            self.dialog.refresh_people()
        self._paint()

    def _arrived(self, hello: dict) -> None:
        back = hello.get("_resume")
        self._expect = getattr(self, "_expect", set()) - {back}
        if not self._expect:
            self._took_over()

    def _took_over(self) -> None:
        old, self._old_net = getattr(self, "_old_net", None), None
        if old is None:
            return
        old.send(None, {"t": "done"})
        QTimer.singleShot(1000, lambda: (_unwire(old), old.close()))

    @_guarded
    def _old_message(self, _cid: int, msg) -> None:
        """The old session, while it lasts: only its replies matter now."""
        if isinstance(msg, dict) and msg.get("t") == "reply" and self.net:
            from . import collab_net as NET
            try:
                self.net.take_reply(str(msg.get("code") or ""))
            except NET.BadCode as e:
                log(f"a reply relayed by the old host did not take: {e}")

    # -- everybody else's side
    def _move(self, code: str, host: str) -> None:
        from . import collab_net as NET
        if getattr(self, "_moving", None) is not None:
            return
        try:
            net2 = NET.Endpoint("member", self.name(), stun=self._stun(),
                                parent=self, turn=self._turn(),
                                    relay_only=self.relay_only())
            net2.join(code)
        except (OSError, NET.BadCode) as e:
            log(f"could not move to the new host: {e}")
            return
        self.session.offline = True
        self._moving = net2
        old = self.net
        net2.code.connect(lambda kind, r, o=old: kind == "reply" and o.send(
            None, {"t": "moving", "code": r}))
        net2.connected.connect(lambda n=net2: self._moved(n))
        log(f"moving to {host or 'the new host'}")
        self.ed.notify(f"the session is moving to {host or 'a new host'} — "
                       "edits wait until you are across")

    def _moved(self, net2) -> None:
        """Across: the new host is who we talk to now."""
        old = self.net
        self._moving = None
        self.net = net2
        _unwire(net2)
        self._wire(None)
        if old is not None:
            _unwire(old)
            QTimer.singleShot(500, old.close)

    def _move_off(self, why: str) -> None:
        net2, self._moving = getattr(self, "_moving", None), None
        if net2 is not None:
            _unwire(net2)
            net2.close()
        if self.session is not None:
            self.session.offline = False
        self.ed.notify(f"the session stays with its host — {why}")

    def set_hold(self, words: bool) -> None:
        """Host: a cursor holds its whole line (the default), or only the
        word it is on -- so two people can time different words of one
        line, and their edits are merged."""
        if self.session is None or self.session.role != "host":
            return
        self.session.set_hold(words)
        self._flush()
        self._paint()
        self.ed.notify("a cursor now holds only its word" if words
                       else "a cursor holds its whole line again")

    def give_selection(self, pid: int) -> str:
        """Host: the selected lines become theirs, as a claim of theirs."""
        if self.session is None or self.session.role != "host":
            return ""
        doc, L = self.ed.doc, self.ed.list
        rows = sorted({line for line, _v in L.selection} | {L.cursor[0]})
        uids = [doc.lines[i].uid for i in rows if 0 <= i < len(doc.lines)]
        taken = self.session.assign(pid, uids)
        self._flush()
        self._paint()
        name = self.session.peers.get(pid, {}).get("n", "them")
        n = len(uids) - len(taken)
        return (f"gave {name} {n} line{'s' * (n != 1)}"
                + (f" — {len(taken)} held by someone else" if taken else ""))

    def kick(self, pid: int) -> None:
        if self.session is None or self.session.role != "host":
            return
        self.session.kick(pid)
        self._flush()
        if self.net is not None:
            QTimer.singleShot(300, lambda: self.net and self.net.drop(pid, "removed"))
        self._paint()

    def open(self) -> None:
        if self.dialog is None:
            self.dialog = Dialog(self)
        self.dialog.refresh_people()
        self.dialog.show()
        self.dialog.raise_()

    def open_notes(self, line: int) -> None:
        """A line's ✎ pill, clicked: its notes, in the session window.

        The line is only scrolled to, as Go does: moving the cursor there is
        presence, and would take the line (and stop a Follow) just for
        reading what was said about it. A note added from here goes on the
        clicked line instead -- see Dialog._add_note."""
        self.open()
        self.dialog._go_line(line)
        self.dialog._to(4)
        self.dialog.show_notes(True, focus=line)
        self.dialog.note_in.setFocus()


# ---------------------------------------------------------------- dialogue
class Dialog(QDialog):
    """Host, join, and who is here. Not modal: the lyric stays workable."""

    def __init__(self, ctl: Controller) -> None:
        super().__init__(ctl.ed)
        self.ctl = ctl
        self.setWindowTitle("Multiplayer")
        self.setModal(False)
        box = QVBoxLayout(self)
        # Above every page, so it can be set -- or changed -- at any point,
        # in a session as well: a joiner who skipped it is not "someone" for
        # the rest of the evening.
        row = QHBoxLayout()
        row.addWidget(QLabel("Your name"))
        self.name = QLineEdit(str(K.config().get("collab_name") or ""))
        self.name.setMaxLength(C.MAX_NAME)
        self.name.setPlaceholderText("what the others see — needed to host or join")
        self.name.editingFinished.connect(self._renamed)
        row.addWidget(self.name, 1)
        box.addLayout(row)
        self.pages = QStackedWidget()
        box.addWidget(self.pages)
        self.pages.addWidget(self._start_page())
        self.pages.addWidget(self._host_page())
        self.pages.addWidget(self._join_page())
        self.pages.addWidget(self._room_page())
        self.pages.addWidget(self._notes_page())
        self.status = _plain(QLabel(""))
        self.status.setWordWrap(True)
        box.addWidget(self.status)
        self.resize(560, 460)

    # -- pages
    def _start_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        intro = QLabel(
            "Time one lyric together. The host sends an invite code; the "
            "joiner sends a reply code back. Swap them in any chat — an "
            "invite is the password to this session.\n\n"
            "Through a relay, the codes carry only the relay's address, and "
            "the session is encrypted end to end on its way through it. "
            "Directly, they carry your IP addresses: only with people you "
            "trust, never posted publicly.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        go = QHBoxLayout()
        host = QPushButton("Host a session")
        host.setProperty("primary", "1")
        host.clicked.connect(self._host)
        join = QPushButton("Join with a code")
        join.clicked.connect(lambda: self._named() and self._to(2))
        go.addWidget(host)
        go.addWidget(join)
        lay.addLayout(go)
        how = QHBoxLayout()
        how.addWidget(QLabel("Connect"))
        self.route = QComboBox()
        self.route.addItem("Through a relay — recommended", "relay")
        self.route.addItem("Directly — only with people you trust", "direct")
        self.route.setCurrentIndex(0 if self.ctl.route() == "relay" else 1)
        self.route.setToolTip(
            "Through a relay, the codes carry only the relay's address: an "
            "invite can be posted anywhere, and nobody who joins learns your "
            "IP address. Directly, the codes carry your IP addresses (public, "
            "home network and IPv6) and so does the connection: send codes "
            "only to people you trust, and never post one publicly.")
        self.route.currentIndexChanged.connect(lambda _i: self._remember())
        how.addWidget(self.route, 1)
        lay.addLayout(how)
        relay = QHBoxLayout()
        relay.addWidget(QLabel("Relay (TURN)"))
        cfg = K.config()
        self.turn_server = QLineEdit(str(cfg.get("collab_turn_server") or ""))
        self.turn_server.setPlaceholderText("relay1.expressturn.com:3478")
        self.turn_user = QLineEdit(str(cfg.get("collab_turn_user") or ""))
        self.turn_user.setPlaceholderText("username")
        self.turn_pass = QLineEdit(str(cfg.get("collab_turn_pass") or ""))
        self.turn_pass.setPlaceholderText("password")
        self.turn_pass.setEchoMode(QLineEdit.EchoMode.Password)
        tip = ("Used only when two editors cannot reach each other directly — "
               "a phone hotspot, a campus or mobile network. Only the side "
               "hosting needs one: then anyone can join. Any TURN server "
               "over UDP works — a free account at expressturn.com or "
               "Metered's Open Relay gives a server, a username and a "
               "password. The session stays encrypted end to end; the relay "
               "carries it without being able to read it.")
        for w_ in (self.turn_server, self.turn_user, self.turn_pass):
            w_.setToolTip(tip)
            w_.editingFinished.connect(self._remember)
        relay.addWidget(self.turn_server, 2)
        relay.addWidget(self.turn_user, 1)
        relay.addWidget(self.turn_pass, 1)
        lay.addLayout(relay)
        get = QLabel('No relay yet? <a href="https://www.expressturn.com/">'
                     'ExpressTURN</a> gives one free (1 TB a month): its '
                     'server, username and password go above.')
        get.setOpenExternalLinks(True)
        get.setWordWrap(True)
        get.setProperty("hint", "1")
        lay.addWidget(get)
        adv = QHBoxLayout()
        adv.addWidget(QLabel("STUN servers"))
        self.stun = QLineEdit(str(K.config().get("collab_stun") or ""))
        self.stun.setPlaceholderText("stun.l.google.com:19302 "
                                     "stun.cloudflare.com:3478")
        self.stun.setToolTip("Asked only where this connection is on the "
                             "internet. They never see the session.")
        adv.addWidget(self.stun, 1)
        lay.addLayout(adv)
        # STUN only finds this computer's address for a direct connection;
        # through a relay it is not asked at all.
        self._stun_row = [self.stun]
        self._route_rows()
        self.route.currentIndexChanged.connect(lambda _i: self._route_rows())
        lay.addStretch(1)
        return w

    def _code_box(self, readonly: bool) -> QPlainTextEdit:
        t = QPlainTextEdit()
        t.setReadOnly(readonly)
        t.setFixedHeight(84)
        t.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        t.setWordWrapMode(QTextOption.WrapMode.WrapAnywhere)
        return t

    def _host_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.nat_h = _plain(QLabel(""))
        self.nat_h.setWordWrap(True)
        lay.addWidget(self.nat_h)
        lay.addWidget(QLabel("1.  Send this invite to whoever is joining"))
        self.invite = self._code_box(True)
        lay.addWidget(self.invite)
        row = QHBoxLayout()
        cp = QPushButton("Copy invite")
        cp.clicked.connect(lambda: self._copy(self.invite))
        row.addWidget(cp)
        again = QPushButton("New invite")
        again.setToolTip("A fresh code: the old one stops letting anyone in "
                         "once its places are used or it is half an hour old")
        again.clicked.connect(self._new_invite)
        row.addWidget(again)
        row.addSpacing(12)
        row.addWidget(QLabel("Lets in up to"))
        self.seats = QSpinBox()
        self.seats.setRange(1, C.MAX_PEERS)
        self.seats.setValue(self.ctl.seats())
        self.seats.setSuffix(" people")
        self.seats.setToolTip(
            "How many people this one code can bring in. Kept here, not in "
            "the code, so nobody holding it can change it; a place is used "
            "up when someone joins and is not given back when they leave. "
            "Changing it applies to the invite already sent.")
        self.seats.valueChanged.connect(self.ctl.set_seats)
        row.addWidget(self.seats)
        row.addWidget(QLabel("to"))
        self.kind = QComboBox()
        self.kind.addItems(["edit", "watch only"])
        self.kind.setToolTip("Watching: they see the lyric being timed, live, "
                             "but cannot change it and hold no lines. Kept "
                             "here, not in the code, like the number of "
                             "places; changing it applies to the invite "
                             "already sent.")
        self.kind.currentTextChanged.connect(
            lambda t: self.ctl.net and self.ctl.net.set_watch(t == "watch only"))
        row.addWidget(self.kind)
        row.addStretch(1)
        lay.addLayout(row)
        self.seats_lbl = _plain(QLabel(""))
        lay.addWidget(self.seats_lbl)
        two = QLabel("2.  Paste the reply they send back — unless they are "
                     "already in, which happens when the two computers can "
                     "reach each other directly")
        two.setWordWrap(True)
        lay.addWidget(two)
        self.reply_in = self._code_box(False)
        lay.addWidget(self.reply_in)
        row = QHBoxLayout()
        con = QPushButton("Connect")
        con.setProperty("primary", "1")
        con.clicked.connect(self._take_reply)
        row.addWidget(con)
        room = QPushButton("Who is here…")
        room.clicked.connect(lambda: self._to(3))
        row.addWidget(room)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)
        return w

    def _join_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("1.  Paste the invite you were sent"))
        self.invite_in = self._code_box(False)
        lay.addWidget(self.invite_in)
        row = QHBoxLayout()
        mk = QPushButton("Make my reply")
        mk.setProperty("primary", "1")
        mk.clicked.connect(self._join)
        row.addWidget(mk)
        back = QPushButton("Back")
        back.clicked.connect(lambda: self._to(0))
        row.addWidget(back)
        row.addStretch(1)
        lay.addLayout(row)
        self.nat_j = _plain(QLabel(""))
        self.nat_j.setWordWrap(True)
        lay.addWidget(self.nat_j)
        two = QLabel("2.  Send this reply back to the host. If you are "
                     "connected before they paste it, that is all.")
        two.setWordWrap(True)
        lay.addWidget(two)
        self.reply = self._code_box(True)
        lay.addWidget(self.reply)
        cp = QPushButton("Copy reply")
        cp.clicked.connect(lambda: self._copy(self.reply))
        lay.addWidget(cp, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addStretch(1)
        return w

    def _room_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.people = QVBoxLayout()
        lay.addLayout(self.people)
        song = QHBoxLayout()
        self.song_lbl = _plain(QLabel(""))
        self.song_lbl.setWordWrap(True)
        song.addWidget(self.song_lbl, 1)
        self.song_btn = QPushButton("Get the host's song again")
        self.song_btn.clicked.connect(self.ctl.fetch_song_again)
        self.song_btn.hide()                # a joiner's, once there is a song
        song.addWidget(self.song_btn)
        lay.addLayout(song)
        note = QLabel("A line is held by whoever is on it, and nobody else "
                      "can change it until they move off. Claiming keeps "
                      "lines yours after you move — for a chorus you are "
                      "taking, say.")
        note.setWordWrap(True)
        lay.addWidget(note)
        row = QHBoxLayout()
        for label, fn in (("Claim selected lines", self.ctl.claim_selection),
                          ("Claim this part", self.ctl.claim_part)):
            b = QPushButton(label)
            b.clicked.connect(lambda _c=False, f=fn: self.say(f()))
            row.addWidget(b)
        rel = QPushButton("Let go of my claims")
        rel.clicked.connect(lambda: (self.ctl.release(), self.say("let go")))
        row.addWidget(rel)
        lay.addLayout(row)
        row = QHBoxLayout()
        self.hold_box = QComboBox()
        self.hold_box.addItems(["Hold whole lines", "Hold single words"])
        self.hold_box.setToolTip(
            "Whole lines: whoever is on a line has it to themselves. Single "
            "words: only the word under their cursor is theirs, so two people "
            "can time different words of one line -- their edits are merged, "
            "and one that would reshape the line or touch someone's word is "
            "turned back.")
        self.hold_box.currentIndexChanged.connect(
            lambda i: self.ctl.set_hold(i == 1))
        row.addWidget(self.hold_box)
        self.freeze_btn = QPushButton("Freeze the lyric")
        self.freeze_btn.setCheckable(True)
        self.freeze_btn.setToolTip("Nobody but you can change it until you "
                                   "unfreeze it — for reviewing")
        self.freeze_btn.toggled.connect(self.ctl.freeze)
        row.addWidget(self.freeze_btn)
        notes = QPushButton("Notes…")
        notes.setToolTip("Notes people pinned to lines in this session")
        notes.clicked.connect(lambda: (self._to(4), self.show_notes(True, focus=-1)))
        row.addWidget(notes)
        self.invite_more = QPushButton("Invite another…")
        self.invite_more.clicked.connect(self._invite_more)
        row.addWidget(self.invite_more)
        leave = QPushButton("Leave the session")
        leave.clicked.connect(self._leave)
        row.addWidget(leave)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)
        return w

    def _notes_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("Notes on lines, for everyone in the session. "
                             "They are kept with the session, not in the "
                             "file."))
        scroll = self.notes_scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        self.notes_lay = QVBoxLayout(inner)
        self.notes_lay.addStretch(1)
        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)
        row = QHBoxLayout()
        self.note_in = QLineEdit()
        self.note_in.setMaxLength(C.MAX_NOTE)
        self.note_in.setPlaceholderText("a note on the line your cursor is on")
        self.note_in.returnPressed.connect(self._add_note)
        row.addWidget(self.note_in, 1)
        add = QPushButton("Add")
        add.clicked.connect(self._add_note)
        row.addWidget(add)
        back = QPushButton("Back")
        back.clicked.connect(lambda: self._to(3))
        row.addWidget(back)
        lay.addLayout(row)
        return w

    def _add_note(self) -> None:
        text = self.note_in.text().strip()
        if not text:
            return
        line = getattr(self, "_notes_focus", None)
        if line is None or not 0 <= line < len(self.ctl.ed.doc.lines):
            line = self.ctl.ed.list.cursor[0]
        why = self.ctl.add_note(line, text)
        self.say(why or "noted")
        if not why:
            self.note_in.clear()
        self.show_notes(True)

    def show_notes(self, force: bool = False, focus: int | None = None) -> None:
        """The notes, a row each; `focus`, a line whose notes are scrolled
        to and set in bold -- the line whose pill was clicked."""
        if self.pages.currentIndex() != 4 and not force:
            return
        doc = self.ctl.ed.doc
        at = {ln.uid: i for i, ln in enumerate(doc.lines)}
        rows = sorted(((at[u], u, n) for u, ns in self.ctl.notes().items()
                       if u in at for n in ns), key=lambda r: (r[0], r[2]["i"]))
        sig = [(i, u, n["i"], n["x"], n["n"]) for i, u, n in rows]
        if focus is not None:
            # -1: opened from the Notes button, about no line in particular.
            self._notes_focus = focus if focus >= 0 else None
            self.note_in.setPlaceholderText(
                f"a note on line {focus + 1}" if focus >= 0
                else "a note on the line your cursor is on")
        focus = getattr(self, "_notes_focus", None)
        if sig == getattr(self, "_notes_sig", None) and not force:
            return
        self._notes_sig = sig
        while self.notes_lay.count() > 1:
            it = self.notes_lay.takeAt(0)
            if it.widget() is not None:
                it.widget().deleteLater()
        me, host = self.ctl.me(), self.ctl.session and self.ctl.session.role == "host"
        first = None
        for line, uid, n in rows:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            lab = _plain(QLabel(f"line {line + 1} · {n['n']}: {n['x']}"))
            lab.setWordWrap(True)
            if line == focus:
                lab.setStyleSheet("font-weight: 700;")
                first = first or row
            h.addWidget(lab, 1)
            go = QPushButton("Go")
            go.clicked.connect(lambda _c=False, i=line: self._go_line(i))
            h.addWidget(go)
            if host or n["by"] == me:
                rm = QPushButton("Delete")
                rm.clicked.connect(lambda _c=False, u=uid, i=n["i"]:
                                   self.ctl.remove_note(u, i))
                h.addWidget(rm)
            self.notes_lay.insertWidget(self.notes_lay.count() - 1, row)
        if not rows:
            empty = _plain(QLabel("No notes yet."))
            self.notes_lay.insertWidget(0, empty)
        if first is not None:
            # Once the rows are laid out, or there is nowhere yet to scroll to.
            QTimer.singleShot(0, lambda w=first: self.notes_scroll.ensureWidgetVisible(w))

    def _go_line(self, line: int) -> None:
        L = self.ctl.ed.list
        for r in L.rows:
            if r.line == line and r.voice == 0:
                L.reveal_row(r)
                L.viewport().update()
                return

    # -- doing
    def _to(self, n: int) -> None:
        self.pages.setCurrentIndex(n)

    def _named(self) -> bool:
        if C.clean_name(self.name.text()) == "someone":
            self.say("Pick a name first — it is what the others see.")
            self.name.setFocus()
            return False
        return True

    def _renamed(self) -> None:
        if self.name.text().strip():
            got = self.ctl.rename(self.name.text())
            if self.ctl.session is not None:
                self.say(f"you are {got} now")

    def _route_rows(self) -> None:
        direct = self.route.currentData() == "direct"
        for w_ in getattr(self, "_stun_row", []):
            w_.setEnabled(direct)
            w_.setToolTip("" if direct else "Only used to connect directly; "
                          "through a relay it is not asked.")

    def _remember(self) -> None:
        self.ctl.rename(self.name.text())
        K.remember(collab_route=self.route.currentData() or "relay",
                   collab_stun=" ".join(self.stun.text().split()),
                   collab_turn_server=self.turn_server.text().strip(),
                   collab_turn_user=self.turn_user.text().strip(),
                   collab_turn_pass=self.turn_pass.text())

    def _host(self) -> None:
        if not self._named():
            return
        self._remember()
        self.invite.clear()
        self.reply_in.clear()
        self.nat_h.setText("")
        why = self.ctl.start_host(self)
        if why:
            self.say(why)
            return
        self._to(1)

    def _join(self) -> None:
        if not self._named():
            return
        self._remember()
        self.reply.clear()
        why = self.ctl.start_join(self, self.invite_in.toPlainText())
        self.say(why)

    def _take_reply(self) -> None:
        from . import collab_net as NET
        if self.ctl.net is None:
            return
        try:
            name = self.ctl.net.take_reply(self.reply_in.toPlainText())
        except NET.BadCode as e:
            self.say(str(e))
            return
        self.reply_in.clear()
        self.say(f"reaching {name}… (up to twenty seconds)")

    def _new_invite(self) -> None:
        if self.ctl.net is not None:
            self.ctl.net.new_invite()
            self.show_seats()

    def show_seats(self) -> None:
        net = self.ctl.net
        if net is None or not hasattr(net, "invite_state") or \
                self.ctl.session is None or self.ctl.session.role != "host":
            self.seats_lbl.setText("")
            return
        joined, seats, shut = net.invite_state()
        self.seats_lbl.setText(
            f"This invite: {joined} of {seats} "
            f"{'place' if seats == 1 else 'places'} used"
            + (f" — {shut}" if shut and joined < seats else ""))

    def _invite_more(self) -> None:
        if self.ctl.session is not None and self.ctl.session.role == "host" \
                and self.ctl.net is not None:
            self.ctl.net.new_invite()
            self._to(1)

    def _leave(self) -> None:
        self.ctl.leave()
        self._to(0)
        self.say("left the session")

    def _copy(self, box: QPlainTextEdit) -> None:
        text = box.toPlainText().strip()
        if text:
            QGuiApplication.clipboard().setText(text)
            self.say("copied")

    # -- told
    def say(self, text: str) -> None:
        self.status.setText(text or "")

    def show_code(self, kind: str, code: str) -> None:
        (self.invite if kind == "invite" else self.reply).setPlainText(code)
        if kind == "invite":
            self.show_seats()

    def show_nat(self, v: dict) -> None:
        host = bool(self.ctl.session and self.ctl.session.role == "host")
        if v.get("relay_only"):
            text = ("Through the relay only: the "
                    + ("invite" if host else "reply")
                    + " carries the relay's address and nothing of yours, "
                    "and everything goes through it, still encrypted end to "
                    "end. " + ("The invite is safe to post anywhere; whoever "
                               "joins never learns your IP address.\n\n"
                               "Nothing connects until you paste their reply "
                               "below: a relay lets in only the addresses the "
                               "reply names."
                               if host else "The host never learns your IP "
                               "address.\n\nNothing connects until the host "
                               "pastes this reply: send it back to them."))
            if not v.get("relay"):
                text = f"⚠ The relay did not start: {v.get('relay_why')}."
            (self.nat_h if host else self.nat_j).setText(text)
            return
        if v.get("relay"):
            text = ("A relay is ready: if the two editors cannot reach each "
                    "other directly, the session goes through it (still "
                    "encrypted end to end), so anyone can join.")
        elif v.get("symmetric"):
            text = ("⚠ This connection gives a new port for every destination "
                    "(symmetric NAT). Joining may fail unless the other side "
                    "has an open router"
                    + (" — or fill in Relay (a TURN server) on the first page, "
                       "and anyone can join." if host else
                       ", or the host has a relay (a TURN server) set up."))
        elif v.get("answers", 0) == 0:
            text = ("The STUN servers did not answer, so only the same "
                    "network or a VPN will work this time.")
        elif v.get("symmetric") is None:
            text = "Connection checked once; it should be able to connect."
        else:
            text = "This connection can be punched through: it should connect."
        if v.get("relay_why"):
            text += f" (No relay this time: {v['relay_why']}.)"
        # What the code gives away. A direct connection needs it, and the
        # code is how the other side learns it.
        net = self.ctl.net
        if not host and net is not None and net.host_relay_only:
            text = ("The host's relay carries this session (encrypted end to "
                    "end). Your reply gives your IP address to the host alone "
                    "— two relays cannot pass it between them.\n\nNothing "
                    "connects until the host pastes your reply: send it back "
                    "to them.")
        elif self.ctl.route() == "relay" and not host:
            text += ("\n\nYou have no relay of your own, so the reply carries "
                     "this computer's IP addresses — to the host alone. The "
                     "invite showed nothing of theirs.")
        else:
            text += ("\n\nDirect: the " + ("invite" if host else "reply")
                     + " carries this computer's IP addresses — your public "
                     "one, your home network's and any IPv6. Send it only to "
                     "people you trust, and never post it publicly. Through a "
                     "relay (first page) keeps them private.")
        (self.nat_h if self.ctl.session and self.ctl.session.role == "host"
         else self.nat_j).setText(text)

    def show_song(self) -> None:
        info = getattr(self.ctl, "host_song", None)
        joined = self.ctl.joined()
        self.song_btn.setVisible(joined and bool(info))
        if not joined:
            self.song_lbl.setText("Joiners get this editor's song: the same "
                                  "upload when it was fetched, otherwise a "
                                  "search at its exact length.")
            return
        if not info:
            self.song_lbl.setText("The host has not opened a song yet.")
            return
        self.song_lbl.setText(f"Song: {info['title'] or '?'}"
                              f"{' — ' + info['artist'] if info['artist'] else ''}"
                              f" ({info['dur']:.0f}s) — "
                              f"{getattr(self.ctl, 'song_state', '') or 'here'}")

    def failed(self, why: str) -> None:
        self.say(f"Could not connect: {why}.")

    def joined(self) -> None:
        self._to(3)
        self.refresh_people()
        self.show_song()

    def refresh_people(self) -> None:
        s = self.ctl.session
        sig = (self.ctl.active(), s and s.role, s and s.me, self.ctl.following,
               s and tuple(self.ctl.path_of(k) for k in sorted(s.peers)),
               s and tuple(sorted((k, p["n"], p["c"], bool(p.get("ro")))
                                  for k, p in s.peers.items())),
               self.pages.currentIndex())
        if sig == getattr(self, "_sig", None):
            return
        self._sig = sig
        while self.people.count():
            it = self.people.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        s = self.ctl.session
        live = self.ctl.active()
        self.invite_more.setVisible(bool(s) and s.role == "host")
        self.freeze_btn.setVisible(bool(s) and s.role == "host")
        self.show_song()
        self.hold_box.setVisible(bool(s) and s.role == "host")
        if not live:
            if self.pages.currentIndex() == 3:
                self._to(0)
            return
        for pid, p in sorted(s.peers.items()):
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            dot = _plain(QLabel("●"))
            dot.setStyleSheet(f"color:{p['c']};")
            lay.addWidget(dot)
            who = "you" if pid == s.me else p["n"]
            how = self.ctl.path_of(pid)
            lay.addWidget(_plain(QLabel(
                who + (" (host)" if pid == 0 else "")
                + (f" — {how}" if how else "")
                + (" (watching)" if p.get("ro") and s.role != "host" else ""))), 1)
            if s.role == "host" and pid != 0:
                edit = QCheckBox("Can edit")
                edit.setChecked(not p.get("ro"))
                edit.toggled.connect(lambda on, q=pid: self.ctl.set_role(q, not on))
                lay.addWidget(edit)
                boss = QPushButton("Make host")
                boss.setToolTip("Hand the session to them, so it carries on "
                                "when you leave: everybody moves across to "
                                "their editor, and yours leaves the session")
                boss.setEnabled(not p.get("ro"))
                boss.clicked.connect(
                    lambda _c=False, q=pid: self.say(self.ctl.hand_over(q)))
                lay.addWidget(boss)
                give = QPushButton("Give selected lines")
                give.setToolTip("The lines you have selected become theirs, "
                                "as if they had claimed them")
                give.clicked.connect(
                    lambda _c=False, q=pid: self.say(self.ctl.give_selection(q)))
                lay.addWidget(give)
            if pid != s.me:
                fol = QPushButton("Following" if pid == self.ctl.following
                                  else "Follow")
                fol.setCheckable(True)
                fol.setChecked(pid == self.ctl.following)
                fol.setToolTip("Keep their line in view as they move, until "
                               "you move your own cursor")
                fol.clicked.connect(lambda _c=False, q=pid: self.ctl.follow(q))
                lay.addWidget(fol)
            if s.role == "host" and pid != 0:
                kick = QPushButton("Remove")
                kick.clicked.connect(lambda _c=False, q=pid: self.ctl.kick(q))
                lay.addWidget(kick)
            self.people.addWidget(row)
        if self.pages.currentIndex() == 0:
            self._to(3)
