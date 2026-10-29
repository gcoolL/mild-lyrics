"""The system tray icon: the window hides into it, keeps playing, and comes
back on the view and page it left. Notes: docs/notes/mild-lyrics/tray.md."""
from __future__ import annotations

import getpass
import hashlib

from PyQt6.QtCore import QObject, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QGuiApplication, QIcon, QPainter, QPixmap
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

# close: the close button hides to the tray as well; minimise: only a
# minimise does (where the system reports one -- Wayland does not); off: no icon.
MODES = ["close", "minimise", "off"]
DEFAULT = "off"
SIZES = (16, 20, 22, 24, 32, 48, 64)
LIGHT_INK, DARK_INK = QColor(234, 234, 234), QColor(28, 28, 32)


def wayland() -> bool:
    return QGuiApplication.platformName().startswith("wayland")


def _door_name() -> str:
    try:
        who = getpass.getuser()
    except Exception:                                # noqa: BLE001
        who = "me"
    return "mild-lyrics-tray-" + hashlib.sha1(who.encode()).hexdigest()[:10]


def knock() -> bool:
    """Wake a Mild Lyrics hidden in the tray; False if none is hidden."""
    sock = QLocalSocket()
    sock.connectToServer(_door_name())
    if not sock.waitForConnected(1000):
        return False
    sock.write(b"show\n")
    sock.flush()
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    return True


def icon(font: QFont, ink: QColor) -> QIcon:
    """'ML' as the home page's narrow rail writes it, at the tray's sizes."""
    out = QIcon()
    for n in SIZES:
        pm = QPixmap(n, n)
        pm.fill(Qt.GlobalColor.transparent)
        f = QFont(font)
        f.setWeight(QFont.Weight.Black)
        f.setPixelSize(n)
        w = QFontMetricsF(f).horizontalAdvance("ML")
        f.setPixelSize(max(6, int(n * min(1.0, n * 0.96 / max(1.0, w)))))
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setFont(f)
        p.setPen(ink)
        p.drawText(QRectF(0, 0, n, n), int(Qt.AlignmentFlag.AlignCenter), "ML")
        p.end()
        out.addPixmap(pm)
    return out


class Tray(QObject):
    """The icon, its menu, and the window's trip into the tray and back."""

    def __init__(self, view, mode: str = DEFAULT) -> None:
        super().__init__(view)
        self.v = view
        self.mode = mode if mode in MODES else DEFAULT
        self.icon: QSystemTrayIcon | None = None
        self.menu: QMenu | None = None
        self.hidden = False
        self.quitting = False
        self._was = Qt.WindowState.WindowNoState
        self._mini = False
        self._door: QLocalServer | None = None
        self._told = False
        self._tip = None
        self._tip_timer = QTimer(self, interval=2000, timeout=self.refresh)
        app = QApplication.instance()
        if app is not None:
            app.commitDataRequest.connect(self._session_ends)
            app.styleHints().colorSchemeChanged.connect(lambda *_: self.redraw())

    # ------------------------------------------------------------ icon
    def available(self) -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    def on(self) -> bool:
        return self.icon is not None and self.icon.isVisible()

    def apply(self, mode: str | None = None) -> None:
        """Show or take away the icon to match the setting."""
        if mode is not None:
            self.mode = mode if mode in MODES else DEFAULT
        if self.mode == "off" or not self.available():
            if self.hidden:
                self.show_window()
            if self.icon is not None:
                self._tip_timer.stop()
                self.icon.hide()
                self.icon.deleteLater()
                self.icon = None
                self._tip = None
            return
        if self.icon is None:
            self.icon = QSystemTrayIcon(self)
            self.menu = QMenu()
            self._build()
            self.menu.aboutToShow.connect(self._sync)
            self.icon.setContextMenu(self.menu)
            self.icon.activated.connect(self._clicked)
            self.redraw()
            self.refresh()
            self._tip_timer.start()
        self.icon.show()

    def redraw(self) -> None:
        if self.icon is None:
            return
        light = QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Light
        self.icon.setIcon(icon(self.v.ui_font(16, QFont.Weight.Black),
                               DARK_INK if light else LIGHT_INK))

    def refresh(self) -> None:
        """The hover text and the menu: what is playing. Plasma shows the menu
        it last read, so it is kept current rather than set on open."""
        if self.icon is None:
            return
        self._sync()
        meta = getattr(self.v.clock, "meta", None) or {}
        title, artist = str(meta.get("title") or ""), str(meta.get("artist") or "")
        song = " — ".join(x for x in (title, artist) if x)
        tip = f"Mild Lyrics\n{song}" if song else "Mild Lyrics"
        if tip != self._tip:
            self._tip = tip
            self.icon.setToolTip(tip)

    def said(self) -> str:
        """The setting's value as the menu shows it."""
        if self.mode != "off" and not self.available():
            return f"{self.mode} · no tray here"
        if self.mode == "minimise" and wayland():
            return "minimise · can't on Wayland"
        return self.mode

    # ------------------------------------------------------------ menu
    def _build(self) -> None:
        """The menu, made once. Plasma clicks the item ids it read earlier, so
        rebuilding on open left every click on a deleted item; only texts change."""
        m, v = self.menu, self.v
        self._head = m.addAction("")
        self._head.setEnabled(False)
        self._head_sep = m.addSeparator()
        self._play = m.addAction("Play")
        self._play.triggered.connect(lambda: v.player_do("PlayPause"))
        m.addAction("Next track").triggered.connect(lambda: v.do_action("next_track"))
        m.addAction("Previous track").triggered.connect(lambda: v.do_action("prev_track"))
        m.addSeparator()
        self._shown = m.addAction("Hide to tray")
        self._shown.triggered.connect(lambda: self.show_window() if self.hidden else self.hide_window())
        m.addAction("Lyrics").triggered.connect(lambda: self.show_view("lyrics"))
        m.addAction("Home").triggered.connect(lambda: self.show_view("browse"))
        m.addSeparator()
        m.addAction("Quit Mild Lyrics").triggered.connect(self.quit)

    def _sync(self) -> None:
        """The menu's changing texts: the song, Play/Pause, Show/Hide."""
        if self.menu is None:
            return
        v = self.v
        meta = getattr(v.clock, "meta", None) or {}
        song = " — ".join(x for x in (str(meta.get("title") or ""),
                                       str(meta.get("artist") or "")) if x)
        song = song if len(song) <= 60 else song[:59] + "…"
        for act, text in ((self._head, song),
                          (self._play, "Pause" if v.clock.status == "Playing" else "Play"),
                          (self._shown, "Show Mild Lyrics" if self.hidden else "Hide to tray")):
            if act.text() != text:
                act.setText(text)
        if self._head.isVisible() != bool(song):
            self._head.setVisible(bool(song))
            self._head_sep.setVisible(bool(song))

    def _clicked(self, why) -> None:
        R = QSystemTrayIcon.ActivationReason
        if why == R.Trigger:
            self.show_window()
        elif why == R.MiddleClick:
            self.v.player_do("PlayPause")

    def show_view(self, view: str) -> None:
        v = self.v
        if view == "browse" and v.view != "browse":
            v.open_browse("home")
        elif view == "lyrics" and v.view == "browse":
            v.close_browse()
        home = v._home
        if view == "lyrics" and home is not None and home.mini:
            self._mini = False                    # the big window, not the mini one
            if self.hidden:
                self._back()
            home.exit_mini()
            return
        self.show_window()

    # ------------------------------------------------------------ the trip
    def hide_window(self, was=None) -> None:
        """Into the tray. `was` is the state before a minimise, when one sent it here."""
        v = self.v
        if self.hidden or not self.on():
            return
        home = v._home
        self._mini = bool(home is not None and home.mini and home.mini_win is not None)
        if self._mini:
            home.mini_win.hide()
        else:
            st = v.windowState() if was is None else was
            self._was = st & ~Qt.WindowState.WindowMinimized
            v.hide()
        self.hidden = True
        QApplication.setQuitOnLastWindowClosed(False)
        self._open_door()
        self._sync()
        v.tray_rest(True)

    def _back(self) -> None:
        self.hidden = False
        self._close_door()
        QApplication.setQuitOnLastWindowClosed(True)
        self._sync()
        self.v.tray_rest(False)

    def show_window(self) -> None:
        """Back where it was: fullscreen, maximised, or the mini player."""
        v = self.v
        home = v._home
        if not self.hidden:
            if home is not None and home.mini and home.mini_win is not None:
                home.mini_win.raise_()
                home.mini_win.activateWindow()
            else:
                v.raise_window()
            return
        self._back()
        if self._mini and home is not None and home.mini and home.mini_win is not None:
            win = home.mini_win
            win.show()
            if v.home_mini_top:
                QTimer.singleShot(400, lambda: home.mini_win is not None
                                  and v.keep_window_above(home.mini_win, True))
            win.raise_()
            win.activateWindow()
            return
        if self._was & Qt.WindowState.WindowFullScreen:
            v.showFullScreen()
        elif self._was & Qt.WindowState.WindowMaximized:
            v.showMaximized()
        else:
            v.showNormal()
        # KWin's keepAbove went with the surface the hide threw away (as exit_mini).
        if getattr(v, "on_top", False) and wayland():
            v.keep_window_above(v, True)
        v.raise_()
        v.activateWindow()

    def minimised(self, old) -> None:
        """The window was minimised (heard on Windows and X11 only)."""
        if self.mode in ("close", "minimise") and self.on() and not self.hidden:
            QTimer.singleShot(0, lambda: self.hide_window(was=old))

    def takes_close(self, ev) -> bool:
        """Whether a close goes to the tray: the window's own close button
        (spontaneous), in close mode. Quit, Esc and restarts call close() and quit."""
        if self.quitting or self.mode != "close" or not self.on() or not ev.spontaneous():
            return False
        self.hide_window()
        if not self._told and not self.v.tray_told and self.icon is not None:
            self._told = self.v.tray_told = True
            self.icon.showMessage("Mild Lyrics is still playing",
                                  "It is in the tray. Right-click the ML icon to quit.",
                                  QSystemTrayIcon.MessageIcon.Information, 6000)
        return True

    def quit(self) -> None:
        self.quitting = True
        self._close_door()
        self.v.close()
        QApplication.quit()

    def _session_ends(self, _mgr) -> None:
        self.quitting = True                # logging out must not stop at a hidden window

    def close(self) -> None:
        self._close_door()
        self._tip_timer.stop()
        if self.icon is not None:
            self.icon.hide()

    # ------------------------------------------------------------ the door
    def _open_door(self) -> None:
        """Listen for a second launch while hidden, so it opens this window instead."""
        if self._door is not None or getattr(self.v.args, "no_persist", False):
            return
        srv = QLocalServer(self)
        srv.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        name = _door_name()
        if not srv.listen(name):
            QLocalServer.removeServer(name)            # left behind by a crash
            if not srv.listen(name):
                srv.deleteLater()
                return
        srv.newConnection.connect(self._knocked)
        self._door = srv

    def _close_door(self) -> None:
        if self._door is not None:
            self._door.close()
            self._door.deleteLater()
            self._door = None

    def _knocked(self) -> None:
        srv = self._door
        while srv is not None and srv.hasPendingConnections():
            s = srv.nextPendingConnection()
            s.disconnected.connect(s.deleteLater)
            s.readyRead.connect(lambda s=s: (s.abort(), self.quitting or self.show_window()))
