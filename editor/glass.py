"""The controls the new interface is built from, carried over from the player's
look, and the settings drawer. The classic look uses only Switch."""
from __future__ import annotations

from PyQt6.QtCore import (QEvent, QPointF, QRect, QRectF, QSize, Qt,
                          pyqtSignal)
from PyQt6.QtGui import (QColor, QKeySequence, QPainter,
                         QRadialGradient)
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QFrame, QHBoxLayout, QLabel, QLayout, QLineEdit,
    QMenu,
    QPushButton, QScrollArea, QSizePolicy, QSlider, QStackedWidget,
    QVBoxLayout, QWidget, QWidgetAction,
)

from . import keys as K, theme as T


def W(a: float) -> QColor:
    return QColor(234, 234, 234, max(0, min(255, int(round(a * 255)))))


# ------------------------------------------------------------- a bar that wraps
class Wrap(QLayout):
    """A row of controls that wraps onto a second row instead of holding the
    window wide; `glue` keeps an item with the one before, `right` pushes a
    run right."""

    def __init__(self, parent=None, spacing: int = 0) -> None:
        super().__init__(parent)
        self._items: list = []       # [QLayoutItem, glue, right, sep]
        self._gap = spacing
        self.setContentsMargins(0, 0, 0, 0)

    # the QLayout contract
    def addItem(self, item) -> None:                      # noqa: N802 (Qt name)
        self._items.append([item, False, False, False])

    def add(self, w: QWidget, glue: bool = False, right: bool = False,
            sep: bool = False) -> None:
        """`sep`: a rule that starts a run, dropped where it would start a
        row instead of standing between two things."""
        self.addWidget(w)
        self._items[-1][1:] = [glue, right, sep]

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, i: int):                             # noqa: N802 (Qt name)
        return self._items[i][0] if 0 <= i < len(self._items) else None

    def takeAt(self, i: int):                             # noqa: N802 (Qt name)
        return self._items.pop(i)[0] if 0 <= i < len(self._items) else None

    def spacing(self) -> int:
        return self._gap

    def setSpacing(self, gap: int) -> None:               # noqa: N802 (Qt name)
        self._gap = gap
        self.invalidate()

    def expandingDirections(self):                        # noqa: N802 (Qt name)
        return Qt.Orientation.Horizontal

    def hasHeightForWidth(self) -> bool:                  # noqa: N802 (Qt name)
        return True

    def heightForWidth(self, w: int) -> int:              # noqa: N802 (Qt name)
        return self._place(QRect(0, 0, w, 0), move=False)

    def sizeHint(self) -> QSize:                          # noqa: N802 (Qt name)
        runs = self._runs()
        w = sum(self._run_w(r, hint=True) for r in runs)
        w += self._gap * max(0, len(runs) - 1)
        h = max((self._row_h(r) for r in runs), default=0)
        return self._edged(w, h)

    def minimumSize(self) -> QSize:                       # noqa: N802 (Qt name)
        runs = self._runs()
        w = max((self._run_w(r, hint=False) for r in runs), default=0)
        h = max((self._row_h(r) for r in runs), default=0)
        return self._edged(w, h)

    def setGeometry(self, rect: QRect) -> None:           # noqa: N802 (Qt name)
        super().setGeometry(rect)
        self._place(rect, move=True)

    # the packing
    def _edged(self, w: int, h: int) -> QSize:
        m = self.contentsMargins()
        return QSize(w + m.left() + m.right(), h + m.top() + m.bottom())

    def _runs(self) -> list:
        """The visible items, in runs that do not break."""
        runs: list = []
        for item, glue, right, sep in self._items:
            w = item.widget()
            if w is not None and w.isHidden():
                continue
            if item.isEmpty() and w is None:
                continue
            if glue and runs:
                runs[-1]["items"].append(item)
            else:
                runs.append({"items": [item], "right": right, "sep": sep})
        return runs

    def _run_w(self, run, hint: bool) -> int:
        items = run["items"]
        ws = [(i.sizeHint() if hint else i.minimumSize()).width() for i in items]
        return sum(ws) + self._gap * (len(items) - 1)

    @staticmethod
    def _row_h(run) -> int:
        return max(i.sizeHint().height() for i in run["items"])

    def _place(self, rect: QRect, move: bool) -> int:
        """Lay the runs out in `rect`, or only measure; the height taken."""
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        width = max(1, area.width())
        rows: list = []
        used = 0
        for run in self._runs():
            # Packed by what each run can take, as a box layout is: a row
            # breaks only where its runs could not all be had at their least.
            rw = self._run_w(run, hint=False)
            if rows and used + self._gap + rw <= width:
                rows[-1].append(run)
                used += self._gap + rw
            else:
                rows.append([run])
                used = rw
        y = area.y()
        for k, row in enumerate(rows):
            items = [i for run in row for i in run["items"]]
            h = max(self._row_h(run) for run in row)
            if move:
                self._lay_row(row, items, area.x(), y, width, h)
            y += h + (self._gap if k < len(rows) - 1 else 0)
        return y - area.y() + m.top() + m.bottom()

    def _lay_row(self, row, items, x0: int, y: int, width: int, h: int) -> None:
        low = [i.minimumSize().width() for i in items]
        want = [max(0, i.sizeHint().width() - a) for i, a in zip(items, low)]
        free = max(0, width - sum(low) - self._gap * (len(items) - 1))
        # From the least each takes toward what each would like, in step.
        room = sum(want)
        give = min(free, room)
        hint = [a + (g * give // room if room else 0)
                for a, g in zip(low, want)]
        free -= sum(hint) - sum(low)
        # Right-hand runs keep to the right, on a row of their own as well.
        push = next((run["items"][0] for run in row if run["right"]), None)
        x = x0
        for k, (item, w) in enumerate(zip(items, hint)):
            if k == 0 and row[0]["sep"]:
                item.setGeometry(QRect(x, y, 0, 0))
                continue
            if item is push:
                x += free
            iw = item.widget()
            pol = iw.sizePolicy().verticalPolicy() if iw is not None else None
            grow = pol is not None and bool(
                pol.value & QSizePolicy.PolicyFlag.GrowFlag.value)
            ih = min(h, item.maximumSize().height()) if grow \
                else min(h, item.sizeHint().height())
            item.setGeometry(QRect(x, y + (h - ih) // 2, w, ih))
            x += w + self._gap


# --------------------------------------------------------------- background
class Backdrop(QWidget):
    """The window's floor: the album colours, blurred and dimmed, painted as
    four radial washes. `colours` takes the cover's palette."""

    DEFAULT = ["#7a3b5c", "#28506f", "#8c5a2a", "#3c2a6b"]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.colours = list(self.DEFAULT)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

    def paintEvent(self, _ev) -> None:                    # noqa: N802 (Qt name)
        p = QPainter(self)
        W_, H = self.width(), self.height()
        if T.LOOK != "new":
            p.fillRect(self.rect(), T.q(T.INK_0))
            return
        p.fillRect(self.rect(), QColor("#1b1420"))
        spots = ((0.18, 0.28, 0.62), (0.78, 0.72, 0.62), (0.62, 0.18, 0.5),
                 (0.30, 0.85, 0.55))
        for (cx, cy, rad), col in zip(spots, self.colours):
            g = QRadialGradient(QPointF(W_ * cx, H * cy), max(W_, H) * rad)
            c = QColor(col)
            g.setColorAt(0.0, c)
            c2 = QColor(col)
            c2.setAlpha(0)
            g.setColorAt(1.0, c2)
            p.fillRect(self.rect(), g)
        p.fillRect(self.rect(), QColor(8, 8, 11, 168))


def glass(widget: QWidget | None = None) -> QFrame:
    """A pane of the new look's glass, with `widget` in it if given."""
    f = QFrame()
    f.setProperty("glass", "1")
    if widget is not None:
        lay = QVBoxLayout(f)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(widget)
    return f


def rule(vertical: bool = True) -> QFrame:
    f = QFrame()
    f.setProperty("rule", "1")
    if vertical:
        f.setFixedSize(1, T.px(28))
    else:
        f.setFixedHeight(1)
    return f


def restyle(widget: QWidget) -> None:
    """Make a property change show: Qt reads dynamic properties once."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


# -------------------------------------------------------------- the switch
class Switch(QCheckBox):
    """On/off. A switch in the new look, an ordinary check box in classic."""

    def sizeHint(self) -> QSize:                          # noqa: N802 (Qt name)
        if T.LOOK != "new":
            return super().sizeHint()
        fm = self.fontMetrics()
        text = fm.horizontalAdvance(self.text()) + T.px(10) if self.text() else 0
        return QSize(T.px(40) + text, max(T.px(24), fm.height() + 4))

    def minimumSizeHint(self) -> QSize:                   # noqa: N802 (Qt name)
        return self.sizeHint()

    def hitButton(self, pos) -> bool:                     # noqa: N802 (Qt name)
        return self.rect().contains(pos) if T.LOOK == "new" \
            else super().hitButton(pos)

    def paintEvent(self, ev) -> None:                     # noqa: N802 (Qt name)
        if T.LOOK != "new":
            super().paintEvent(ev)
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isChecked()
        h = T.px(22)
        box = QRectF(0, (self.height() - h) / 2, T.px(40), h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#eaeaea") if on else W(0.18))
        if not self.isEnabled():
            p.setOpacity(0.45)
        p.drawRoundedRect(box, h / 2, h / 2)
        k = h - T.px(4)
        x = box.right() - T.px(2) - k if on else box.x() + T.px(2)
        p.setBrush(QColor(22, 22, 27) if on else W(0.75))
        p.drawEllipse(QRectF(x, box.y() + T.px(2), k, k))
        if self.text():
            p.setPen(QColor("#eaeaea"))
            p.setFont(self.font())
            p.drawText(QRectF(box.right() + T.px(10), 0,
                              self.width() - box.right() - T.px(10),
                              self.height()),
                       int(Qt.AlignmentFlag.AlignVCenter
                           | Qt.AlignmentFlag.AlignLeft), self.text())


# ----------------------------------------------------- side-by-side buttons
class Segmented(QFrame):
    """A short list of choices, side by side, the picked one filled."""

    picked = pyqtSignal(str)

    def __init__(self, options, value: str = "", big: bool = False,
                 labels: dict | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("wellbig" if big else "well", "1")
        lay = QHBoxLayout(self)
        m = T.px(4 if big else 3)
        lay.setContentsMargins(m, m, m, m)
        lay.setSpacing(T.px(3 if big else 2))
        self.buttons: dict = {}
        for o in options:
            b = QPushButton((labels or {}).get(o, str(o)))
            b.setCheckable(True)
            b.setProperty("segbig" if big else "seg", "1")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _c=False, o=o: self._click(o))
            lay.addWidget(b)
            self.buttons[o] = b
        self.set_value(value)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def _click(self, o) -> None:
        self.set_value(o)
        self.picked.emit(str(o))

    def set_value(self, value) -> None:
        for o, b in self.buttons.items():
            b.setChecked(str(o) == str(value))

    def value(self) -> str:
        return next((str(o) for o, b in self.buttons.items() if b.isChecked()), "")


# ------------------------------------------------------------ the ▾ menus
class _Row(QWidget):
    """One entry in a ▾ menu: what it does, what that means, and its key or
    its switch -- the explanation the ribbon kept in a tooltip, in view."""

    def __init__(self, item: dict, menu: QMenu) -> None:
        super().__init__()
        self.item, self.menu = item, menu
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMouseTracking(True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(T.px(12), T.px(9), T.px(12), T.px(9))
        lay.setSpacing(T.px(12))
        col = QVBoxLayout()
        col.setSpacing(T.px(2))
        name = QLabel(item["label"])
        name.setStyleSheet(
            f"font-size:{T.px(15)}px; font-weight:600; color:"
            + ("rgb(240,160,150)" if item.get("danger") else "#eaeaea") + ";")
        col.addWidget(name)
        self._name, self._tip, self._side, self._col = name, None, None, col
        if item.get("tip"):
            tip = self._tip = QLabel(item["tip"])
            tip.setWordWrap(True)
            tip.setStyleSheet(f"font-size:{T.px(13)}px; font-weight:500;"
                              f" color:rgba(234,234,234,140);")
            col.addWidget(tip)
        lay.addLayout(col, 1)
        self.switch = None
        if item.get("toggle") is not None:
            self.switch = Switch()
            self.switch.setChecked(bool(item["toggle"]()))
            self.switch.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            lay.addWidget(self.switch, 0, Qt.AlignmentFlag.AlignTop)
            self._side = self.switch
        elif item.get("key"):
            key = QLabel(item["key"])
            key.setStyleSheet(f"font-size:{T.px(12.5)}px; font-weight:600;"
                              f" color:rgba(234,234,234,128);")
            lay.addWidget(key, 0, Qt.AlignmentFlag.AlignTop)
            self._side = key
        if not item.get("enabled", True):
            self.setEnabled(False)
        self._width = T.px(item.get("width", 400))
        self.setFixedWidth(self._width)

    def sizeHint(self) -> QSize:                          # noqa: N802 (Qt name)
        """Wrapped text's height at the row's real width, added up from the
        labels. Qt's own guess is made at another width: it stretched the
        title, or cut the tip and drew it over the title."""
        self.ensurePolished()
        lay = self.layout()
        m = lay.contentsMargins()
        text = self._width - m.left() - m.right()
        if self._side is not None:
            text -= self._side.sizeHint().width() + lay.spacing()
        h = self._name.heightForWidth(text)
        h = h if h > 0 else self._name.sizeHint().height()
        if self._tip is not None:
            h += self._col.spacing() + self._tip.heightForWidth(text)
        if self._side is not None:
            h = max(h, self._side.sizeHint().height())
        return QSize(self._width, h + m.top() + m.bottom())

    def minimumSizeHint(self) -> QSize:                   # noqa: N802 (Qt name)
        return self.sizeHint()

    def paintEvent(self, ev) -> None:                     # noqa: N802 (Qt name)
        if self.underMouse() and self.isEnabled():
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(W(0.09))
            p.drawRoundedRect(QRectF(self.rect()), T.px(8), T.px(8))
        super().paintEvent(ev)

    def enterEvent(self, ev) -> None:                     # noqa: N802 (Qt name)
        self.update()
        super().enterEvent(ev)

    def leaveEvent(self, ev) -> None:                     # noqa: N802 (Qt name)
        self.update()
        super().leaveEvent(ev)

    def mouseReleaseEvent(self, ev) -> None:              # noqa: N802 (Qt name)
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        fn = self.item.get("fn")
        if self.switch is not None:
            # A switch flips where it is, and the menu stays up: several can
            # be set in one visit, and the switch shows what it is now.
            if fn is not None:
                fn()
            self.switch.setChecked(bool(self.item["toggle"]()))
            return
        sub = self.item.get("sub")
        if sub is not None:
            # A menu of its own beside this row, the way a submenu opens,
            # with this one still up behind it.
            # Esc in it comes back here; a choice in it closes both.
            child = rich_menu(self.menu, sub(), self.item.get("width", 400))
            child.above = self.menu
            child.exec(self.mapToGlobal(QPointF(self.width() + T.px(10),
                                                -T.px(6)).toPoint()))
            return
        # Every menu this one opened from goes too, before the command runs:
        # a file dialogue does not come up over a menu still open.
        _close_up(self.menu)
        if fn is not None:
            fn()


def _close_up(menu) -> None:
    """Close a menu and every menu it was opened from."""
    while menu is not None:
        menu.close()
        menu = getattr(menu, "above", None)


def rich_menu(parent, items: list, width: int = 400) -> QMenu:
    """A ▾ menu of rows that say what they do. `items` are dicts:
    label, tip, fn, key, toggle (a getter), danger, enabled, sub (a callable
    giving the items of a menu opened beside the row); None is a rule.
    A row with a toggle flips it and leaves the menu open."""
    menu = QMenu(parent)
    menu.setWindowFlags(menu.windowFlags()
                        | Qt.WindowType.NoDropShadowWindowHint)
    for item in items:
        if item is None:
            menu.addSeparator()
            continue
        act = QWidgetAction(menu)
        act.setDefaultWidget(_Row(dict(item, width=width), menu))
        menu.addAction(act)
    return menu


class MenuButton(QPushButton):
    """"Name ▾", opening a rich menu under itself. `items` is a callable, so
    the menu is built afresh each time and its switches say what is true."""

    def __init__(self, name: str, items, width: int = 400, parent=None) -> None:
        super().__init__(f"{name}  ▾", parent)
        self.items, self.width_ = items, width
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self.pop)

    def pop(self) -> None:
        menu = rich_menu(self, self.items(), self.width_)
        self.setDown(True)
        menu.exec(self.mapToGlobal(self.rect().bottomLeft()
                                   + QPointF(0, T.px(8)).toPoint()))
        self.setDown(False)


# ---------------------------------------------------------------- the drawer
class Drawer(QFrame):
    """Settings and keys in a panel that slides in from the right; every change
    is kept the moment it is made."""

    changed = pyqtSignal(dict)
    interface = pyqtSignal(str)

    def __init__(self, keys: K.Keys, sections, parent=None, extra=None) -> None:
        super().__init__(parent)
        self.keys = keys
        self.sections = sections
        # (tab name, a function making its page): a third tab, built on first open.
        self.extra = extra
        self._extra_page = None
        self.setObjectName("drawer")
        self.setStyleSheet(
            "QFrame#drawer { background: rgba(16,16,21,250);"
            " border: none; border-left: 1px solid rgba(234,234,234,26); }")
        self.capture: str | None = None
        self.notes: dict = {}
        self.tab = 0
        self._nav: list = []
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)

        head = QHBoxLayout()
        head.setContentsMargins(T.px(28), T.px(24), T.px(24), T.px(18))
        self.which = Segmented(["Settings", "Keys"] + ([extra[0]] if extra else []),
                               "Settings", big=True)
        self.which.picked.connect(self.show_tab)
        head.addWidget(self.which)
        head.addStretch(1)
        close = QPushButton("✕")
        close.setProperty("quiet", "1")
        close.setFixedSize(T.px(40), T.px(40))
        close.setStyleSheet(f"border-radius:{T.px(20)}px; font-size:{T.px(18)}px;")
        close.setToolTip("Close (Esc)")
        close.clicked.connect(self.hide)
        head.addWidget(close)
        box.addLayout(head)
        box.addWidget(self._hair())

        self.pages = QStackedWidget()
        self.pages.addWidget(self._settings_page())
        self.pages.addWidget(self._keys_page())
        box.addWidget(self.pages, 1)

        box.addWidget(self._hair(0.1))
        foot = QHBoxLayout()
        foot.setContentsMargins(T.px(28), T.px(16), T.px(28), T.px(20))
        col = QVBoxLayout()
        col.setSpacing(0)
        a = QLabel("Interface")
        a.setStyleSheet(f"font-size:{T.px(16.5)}px; font-weight:700;")
        b = QLabel("Shared with Mild Lyrics")
        b.setStyleSheet(f"font-size:{T.px(13.5)}px; font-weight:500;"
                        " color:rgba(234,234,234,140);")
        col.addWidget(a)
        col.addWidget(b)
        foot.addLayout(col, 1)
        self.iface = Segmented(["new", "classic"], "new",
                               labels={"new": "New", "classic": "Classic"})
        self.iface.picked.connect(self.interface.emit)
        foot.addWidget(self.iface)
        box.addLayout(foot)
        self.hide()

    @staticmethod
    def _hair(a: float = 0.08) -> QFrame:
        f = QFrame()
        f.setFixedHeight(1)
        f.setStyleSheet(f"background: rgba(234,234,234,{int(a * 255)});"
                        " border: none;")
        return f

    # ------------------------------------------------------- the settings
    def _settings_page(self) -> QWidget:
        page = QWidget()
        lay = QHBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        nav = QWidget()
        nav.setFixedWidth(T.px(180))
        nl = QVBoxLayout(nav)
        nl.setContentsMargins(T.px(10), T.px(14), T.px(10), T.px(14))
        nl.setSpacing(T.px(2))
        self.find = QLineEdit()
        self.find.setPlaceholderText("Search")
        self.find.setClearButtonEnabled(True)
        self.find.setStyleSheet(
            f"QLineEdit {{ min-height:{T.px(36)}px; padding:0 {T.px(10)}px;"
            f" border:none; border-radius:{T.px(9)}px;"
            f" background:rgba(234,234,234,20); font-size:{T.px(15)}px; }}")
        self.find.textChanged.connect(lambda _t: self.refresh())
        nl.addWidget(self.find)
        nl.addSpacing(T.px(8))
        for i, (name, _rows) in enumerate(self.sections()):
            b = QPushButton(name)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton {{ text-align:left; padding:0 {T.px(14)}px;"
                f" min-height:{T.px(40)}px; border:none; border-radius:{T.px(9)}px;"
                f" background:transparent; color:rgba(234,234,234,158);"
                f" font-size:{T.px(16)}px; font-weight:600; }}"
                f" QPushButton:hover {{ background:rgba(234,234,234,13); }}"
                f" QPushButton:checked {{ background:rgba(234,234,234,33);"
                f" color:#ffffff; }}")
            b.clicked.connect(lambda _c=False, i=i: self._pick(i))
            nl.addWidget(b)
            self._nav.append(b)
        nl.addStretch(1)
        lay.addWidget(nav)
        side = QFrame()
        side.setFixedWidth(1)
        side.setStyleSheet("background: rgba(234,234,234,20); border:none;")
        lay.addWidget(side)
        self.rows_area = QScrollArea()
        self.rows_area.setWidgetResizable(True)
        self.rows_area.setFrameShape(QFrame.Shape.NoFrame)
        lay.addWidget(self.rows_area, 1)
        self.show_section(0)
        return page

    def _pick(self, i: int) -> None:
        """A section picked from the list: the search gives way to it."""
        self.find.blockSignals(True)
        self.find.clear()
        self.find.blockSignals(False)
        self.show_section(i)

    def refresh(self) -> None:
        """Redraw the settings page from the config as it is now."""
        self.show_section(self.tab)

    @staticmethod
    def _page(name: str) -> tuple[QWidget, QVBoxLayout]:
        body = QWidget()
        col = QVBoxLayout(body)
        col.setContentsMargins(T.px(16), T.px(18), T.px(16), T.px(24))
        col.setSpacing(T.px(2))
        title = QLabel(name)
        title.setWordWrap(True)
        title.setStyleSheet(f"font-size:{T.px(24)}px; font-weight:800;"
                            f" padding: 0 {T.px(12)}px {T.px(10)}px;")
        col.addWidget(title)
        return body, col

    def show_section(self, i: int) -> None:
        secs = self.sections()
        self.tab = max(0, min(len(secs) - 1, i))
        query = self.find.text().strip()
        for n, b in enumerate(self._nav):
            b.setChecked(n == self.tab and not query)
        if query:
            self._show_found(secs, query)
            return
        name, rows = secs[self.tab]
        body, col = self._page(name)
        cfg = K.config()
        for label, key, kind, spec, default, note in rows:
            col.addWidget(self._row(label, key, kind, spec, default, note,
                                    cfg.get(key, default)))
        col.addStretch(1)
        self.rows_area.setWidget(body)

    def _show_found(self, secs, query: str) -> None:
        """Every row, in every section, whose words hold all of `query`'s."""
        words = query.casefold().split()
        body, col = self._page("Search")
        cfg = K.config()
        hits = 0
        for name, rows in secs:
            found = [r for r in rows if all(
                w in " ".join([name, r[0], r[5] or "",
                               *(map(str, r[3]) if r[2] == "choice" else ())]
                              ).casefold() for w in words)]
            if not found:
                continue
            head = QLabel(name.upper())
            head.setStyleSheet(
                f"padding:{T.px(14)}px {T.px(12)}px {T.px(4)}px;"
                f" font-size:{T.px(13)}px; font-weight:700; letter-spacing:1px;"
                " color:rgba(234,234,234,140);")
            col.addWidget(head)
            for label, key, kind, spec, default, note in found:
                col.addWidget(self._row(label, key, kind, spec, default, note,
                                        cfg.get(key, default)))
            hits += len(found)
        if not hits:
            none = QLabel(f"No setting mentions “{query}”.")
            none.setWordWrap(True)
            none.setStyleSheet(f"padding:{T.px(6)}px {T.px(12)}px;"
                               f" font-size:{T.px(15)}px;"
                               " color:rgba(234,234,234,140);")
            col.addWidget(none)
        col.addStretch(1)
        self.rows_area.setWidget(body)

    def _row(self, label, key, kind, spec, default, note, value) -> QWidget:
        row = QWidget()
        row.setObjectName("setrow")
        row.setStyleSheet("QWidget#setrow { border-radius: 10px; }"
                          " QWidget#setrow:hover { background: rgba(234,234,234,16); }")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(T.px(12), T.px(10), T.px(12), T.px(10))
        lay.setSpacing(T.px(16))
        col = QVBoxLayout()
        col.setSpacing(T.px(3))
        name = QLabel(label)
        name.setWordWrap(True)
        name.setStyleSheet(f"font-size:{T.px(16.5)}px; font-weight:600;"
                           " color:rgba(234,234,234,235);")
        col.addWidget(name)
        if note:
            n = QLabel(note)
            n.setWordWrap(True)
            n.setStyleSheet(f"font-size:{T.px(13.5)}px; font-weight:500;"
                            " color:rgba(234,234,234,140);")
            col.addWidget(n)
        lay.addLayout(col, 1)
        ctl = self._control(key, kind, spec, default, value)
        lay.addWidget(ctl, 0, Qt.AlignmentFlag.AlignVCenter)
        return row

    def _control(self, key, kind, spec, default, value) -> QWidget:
        def keep(v):
            K.remember(**{key: v})
            self.changed.emit({key: v})

        def keep_soon(v):
            K.remember_soon(**{key: v})
            self.changed.emit({key: v})

        if kind == "bool":
            w = Switch()
            w.setChecked(bool(value))
            w.setCursor(Qt.CursorShape.PointingHandCursor)
            w.toggled.connect(lambda on: keep(bool(on)))
            return w
        if kind == "lang":
            from .langpick import LangBox
            w = LangBox(str(value or default))
            w.setFixedWidth(T.px(240))
            w.picked.connect(keep)
            return w
        if kind == "choice":
            opts = [str(x) for x in spec]
            if str(value) not in opts:
                value = default
            fm = self.fontMetrics()
            wide = sum(fm.horizontalAdvance(o) for o in opts) + len(opts) * T.px(26)
            if len(opts) <= 4 and wide < T.px(300):
                w = Segmented(opts, str(value))
                w.picked.connect(keep)
                return w
            btn = QPushButton(f"{value}   ▾")
            btn.setMinimumWidth(T.px(150))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)

            def pop(_c=False, btn=btn):
                cur = str(K.config().get(key, default))
                items = [{"label": ("✓  " if o == cur else "     ") + o,
                          "fn": (lambda o=o: (btn.setText(f"{o}   ▾"), keep(o)))}
                         for o in opts]
                rich_menu(btn, items, 200).exec(
                    btn.mapToGlobal(btn.rect().bottomLeft()))
            btn.clicked.connect(pop)
            return btn
        if kind == "num":
            low, high, step, places, suffix = spec
            box = QWidget()
            hl = QHBoxLayout(box)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(T.px(14))
            s = QSlider(Qt.Orientation.Horizontal)
            n = max(1, int(round((high - low) / step)))
            s.setRange(0, n)
            s.setValue(int(round((float(value) - low) / step)))
            s.setFixedWidth(T.px(150))
            lab = QLabel()
            lab.setFixedWidth(T.px(96))
            lab.setAlignment(Qt.AlignmentFlag.AlignRight
                             | Qt.AlignmentFlag.AlignVCenter)
            lab.setFont(T.font(15, 600, mono=True))

            def shown(i):
                v = round(low + i * step, 4)
                lab.setText(f"{v:.{places}f}{suffix}")
                return v
            shown(s.value())
            s.valueChanged.connect(lambda i: keep_soon(shown(i)))
            hl.addWidget(s)
            hl.addWidget(lab)
            return box
        w = QLineEdit(str(value or ""))
        w.setFixedWidth(T.px(220))
        w.editingFinished.connect(lambda: keep(w.text().strip()))
        return w

    # ----------------------------------------------------------- the keys
    def _keys_page(self) -> QWidget:
        self.keys_area = QScrollArea()
        self.keys_area.setWidgetResizable(True)
        self.keys_area.setFrameShape(QFrame.Shape.NoFrame)
        self._fill_keys()
        return self.keys_area

    def _fill_keys(self) -> None:
        body = QWidget()
        col = QVBoxLayout(body)
        col.setContentsMargins(T.px(28), T.px(14), T.px(28), T.px(24))
        col.setSpacing(0)
        top = QHBoxLayout()
        intro = QLabel("Click a key to change it, then press the new one. "
                       "Backspace leaves it with no key, Esc keeps it as it was.")
        intro.setWordWrap(True)
        intro.setStyleSheet(f"font-size:{T.px(14)}px; font-weight:500;"
                            " color:rgba(234,234,234,153);")
        top.addWidget(intro, 1)
        back = QPushButton("Back to the defaults")
        back.clicked.connect(self._defaults)
        top.addWidget(back)
        col.addLayout(top)
        self.news = QLabel("")
        self.news.setWordWrap(True)
        self.news.setStyleSheet(
            f"margin-top:{T.px(12)}px; padding:{T.px(9)}px {T.px(12)}px;"
            " border-radius:9px; background:rgba(234,234,234,20);"
            f" font-size:{T.px(14)}px; font-weight:600;")
        self.news.setVisible(bool(getattr(self, "_news", "")))
        self.news.setText(getattr(self, "_news", ""))
        col.addWidget(self.news)
        groups: list = []
        where: dict = {}
        for name, label, _d, group in K.ACTIONS:
            if group not in where:
                where[group] = len(groups)
                groups.append((group, []))
            groups[where[group]][1].append((name, label))
        self.chips: dict = {}
        for group, rows in groups:
            head = QLabel(group.upper())
            head.setStyleSheet(
                f"padding:{T.px(18)}px 0 {T.px(6)}px; font-size:{T.px(14)}px;"
                " font-weight:700; letter-spacing:1px; color:rgba(234,234,234,140);")
            col.addWidget(head)
            for name, label in rows:
                col.addWidget(self._key_row(name, label))
        col.addStretch(1)
        self.keys_area.setWidget(body)

    def _key_row(self, name: str, label: str) -> QWidget:
        row = QWidget()
        row.setObjectName("keyrow")
        row.setStyleSheet("QWidget#keyrow { border-bottom: 1px solid"
                          " rgba(234,234,234,15); }")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, T.px(4), 0, T.px(4))
        col = QVBoxLayout()
        col.setSpacing(T.px(2))
        d = QLabel(label)
        d.setStyleSheet(f"font-size:{T.px(16)}px; font-weight:500;"
                        " color:rgba(234,234,234,217);")
        col.addWidget(d)
        ok, why = self.keys.possible(name)
        note = self.notes.get(name) or ("" if ok else why)
        if note:
            n = QLabel(note)
            n.setWordWrap(True)
            n.setStyleSheet(f"font-size:{T.px(13)}px; font-weight:500;"
                            " color:rgba(234,234,234,128);")
            col.addWidget(n)
        lay.addLayout(col, 1)
        key = K.canon(self.keys.map.get(name))
        cap = self.capture == name
        chip = QPushButton("Press a key…" if cap else (key or "no key"))
        chip.setCursor(Qt.CursorShape.PointingHandCursor)
        chip.setToolTip("Click to change")
        style = ("background:#eaeaea; color:#141419; border:1px solid #eaeaea;"
                 if cap else
                 "background:rgba(234,234,234,26); border:1px solid rgba(234,234,234,41);"
                 if key else
                 "background:transparent; color:rgba(234,234,234,128);"
                 " border:1px dashed rgba(234,234,234,77);")
        chip.setStyleSheet(f"QPushButton {{ {style} min-height:{T.px(28)}px;"
                           f" min-width:{T.px(34)}px; padding:0 {T.px(10)}px;"
                           f" border-radius:{T.px(6)}px; font-size:{T.px(14.5)}px;"
                           " font-weight:700; }")
        chip.clicked.connect(lambda _c=False, n=name: self._grab(n))
        lay.addWidget(chip, 0, Qt.AlignmentFlag.AlignVCenter)
        return row

    def _grab(self, name: str) -> None:
        self.capture = None if self.capture == name else name
        self._news = ""
        if self.capture:
            QApplication.instance().installEventFilter(self)
        else:
            QApplication.instance().removeEventFilter(self)
        self._fill_keys()

    def eventFilter(self, obj, ev) -> bool:               # noqa: N802 (Qt name)
        if self.capture is None:
            return False
        if ev.type() == QEvent.Type.ShortcutOverride:
            ev.accept()
            return True
        if ev.type() != QEvent.Type.KeyPress:
            return False
        k = ev.key()
        if k in (Qt.Key.Key_Shift, Qt.Key.Key_Control, Qt.Key.Key_Alt,
                 Qt.Key.Key_Meta, Qt.Key.Key_AltGr):
            return True
        name, self.capture = self.capture, None
        QApplication.instance().removeEventFilter(self)
        if k == Qt.Key.Key_Escape:
            self._fill_keys()
            return True
        if k in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            self._bind(name, "")
            return True
        mods = ev.modifiers() & (Qt.KeyboardModifier.ControlModifier
                                 | Qt.KeyboardModifier.ShiftModifier
                                 | Qt.KeyboardModifier.AltModifier
                                 | Qt.KeyboardModifier.MetaModifier)
        seq = K.canon(QKeySequence(int(mods.value) | int(k)).toString())
        held = K.fixed().get(seq, "")
        if held:
            self._news = f"{seq} is “{held}” — the window keeps that one"
            self._fill_keys()
            return True
        self._bind(name, seq)
        return True

    def _bind(self, name: str, key: str) -> None:
        want = dict(self.keys.map)
        took = [o for o, k in want.items() if o != name and key
                and K.canon(k) == key]
        want[name] = key
        for o in took:
            want[o] = ""
        self.keys.set(want)
        self.notes.pop(name, None)
        for o in took:
            self.notes[o] = f"{key} has gone to “{K.LABELS[name]}”"
        if took:
            self._news = (f"{key} taken off “{K.LABELS[took[0]]}”, which has "
                          f"no key now")
        elif not key:
            self._news = f"“{K.LABELS[name]}” has no key now"
        else:
            self._news = ""
        self._fill_keys()

    def _defaults(self) -> None:
        self.keys.set(dict(K.DEFAULTS))
        self.notes = {}
        self._news = "every key back where it started"
        self._fill_keys()

    # ------------------------------------------------------------ showing
    def show_tab(self, which: str) -> None:
        self.which.set_value(which)
        if self.extra and which == self.extra[0]:
            if self._extra_page is None:
                self._extra_page = self.extra[1]()
                self.pages.addWidget(self._extra_page)
            self.pages.setCurrentWidget(self._extra_page)
            return
        self.pages.setCurrentIndex(1 if which == "Keys" else 0)
        if which == "Keys":
            self._fill_keys()
        else:
            self.show_section(self.tab)

    def open(self, which: str = "Settings") -> None:
        self.show_tab(which)
        self.place()
        self.show()
        self.raise_()

    def place(self) -> None:
        host = self.parentWidget()
        if host is None:
            return
        w = min(host.width() - T.px(40), T.px(660))
        self.setGeometry(host.width() - w, 0, w, host.height())

    def hideEvent(self, ev) -> None:                      # noqa: N802 (Qt name)
        if self.capture:
            self.capture = None
            QApplication.instance().removeEventFilter(self)
        super().hideEvent(ev)

    def keyPressEvent(self, ev) -> None:                  # noqa: N802 (Qt name)
        if ev.key() == Qt.Key.Key_Escape:
            if self.find.text() and self.pages.currentIndex() == 0:
                self.find.clear()
                return
            self.hide()
            return
        super().keyPressEvent(ev)


class Tile(QFrame):
    """A large choice that says what it does: a name, and a line under it."""

    clicked = pyqtSignal()

    def __init__(self, name: str, what: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("tile")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setStyleSheet(
            "QFrame#tile { background: rgba(234,234,234,20);"
            " border: 1px solid rgba(234,234,234,36);"
            f" border-radius: {T.px(12)}px; }}"
            " QFrame#tile:hover { background: rgba(234,234,234,36); }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(T.px(16), T.px(14), T.px(16), T.px(14))
        lay.setSpacing(T.px(4))
        self.head = QHBoxLayout()
        self.head.setSpacing(T.px(8))
        top = QLabel(name)
        top.setStyleSheet(f"font-size:{T.px(16)}px; font-weight:700;")
        self.head.addWidget(top)
        self.head.addStretch(1)
        lay.addLayout(self.head)
        sub = QLabel(what)
        sub.setWordWrap(True)
        sub.setStyleSheet(f"font-size:{T.px(13.5)}px; font-weight:500;"
                          " color: rgba(234,234,234,150);")
        lay.addWidget(sub)
        lay.addStretch(1)

    def mouseReleaseEvent(self, ev) -> None:              # noqa: N802 (Qt name)
        if ev.button() == Qt.MouseButton.LeftButton and self.rect().contains(
                ev.position().toPoint()):
            self.clicked.emit()


class Toast(QLabel):
    """A line that says what just happened, and goes."""

    def __init__(self, parent) -> None:
        super().__init__(parent)
        from PyQt6.QtCore import QTimer
        self.setStyleSheet(
            "background: rgba(24,24,29,235); border: 1px solid rgba(234,234,234,46);"
            f" border-radius: {T.px(20)}px; padding: {T.px(9)}px {T.px(18)}px;"
            f" font-size: {T.px(17)}px; font-weight: 600; color: #eaeaea;")
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._over)
        self.held = None
        self.held_used = False
        self.hide()

    HELD_AFTER = 5000

    def say(self, text: str, ms: int = 1800, hold: bool = False) -> None:
        """`hold`: stay up until a key, click or scroll in the app, then
        HELD_AFTER more -- someone away from the keyboard still sees it.
        A plain toast meanwhile shows over it and gives it back."""
        from PyQt6.QtWidgets import QApplication
        if hold:
            if self.held is None:
                QApplication.instance().installEventFilter(self)
            self.held, self.held_used = text, False
        self._show(text)
        if hold:
            self.timer.stop()
        else:
            self.timer.start(ms)

    def _show(self, text: str) -> None:
        self.setText(text)
        self.adjustSize()
        host = self.parentWidget()
        if host is not None:
            self.move((host.width() - self.width()) // 2,
                      host.height() - self.height() - T.px(70))
        self.show()
        self.raise_()

    def _over(self) -> None:
        if self.held is None:
            self.hide()
            return
        text = self.held
        if self.held_used:
            self._release()
            self.timer.start(self.HELD_AFTER)
        self._show(text)

    def _release(self) -> None:
        from PyQt6.QtWidgets import QApplication
        self.held = None
        QApplication.instance().removeEventFilter(self)

    def eventFilter(self, obj, ev) -> bool:               # noqa: N802 (Qt name)
        if (self.held is not None and not self.held_used and ev.type() in (
                ev.Type.KeyPress, ev.Type.MouseButtonPress, ev.Type.Wheel)):
            self.held_used = True
            if not self.timer.isActive():
                self._release()
                self.timer.start(self.HELD_AFTER)
        return False
