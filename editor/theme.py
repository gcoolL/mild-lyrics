"""One palette, one type scale, one set of metrics -- for every window here.

The colours were written twice before this file existed, once in the strip
and once in the list, and they had already drifted: the same syllable was a
different blue depending on which half of the window it was drawn in. A
lyric is one material and has to look like one, so there is one place to
change it.

The scheme is Mild Lyrics' own, brought inland: near-black, one bright ink
for the lead voice and everything that means "here", a warm one for backing
vocals, a green for the answering voice. Surfaces step UP toward the viewer
-- the window is the darkest thing on screen and a control at rest is two
steps lighter -- so depth reads without a single shadow.
"""
from __future__ import annotations

from PyQt6.QtGui import QColor, QFont, QFontDatabase

# ---------------------------------------------------------------- surfaces
INK_0 = "#0d0e12"
INK_1 = "#14161c"
INK_2 = "#1b1e26"
INK_3 = "#232733"
INK_4 = "#2c313f"
LINE = "#2a2e3a"
TEXT = "#e9eaee"
MUTE = "#8d92a2"
FAINT = "#7b8194"

# ------------------------------------------------------------------- inks
ACCENTS = {"blue": "#5b8cff", "violet": "#9a7bff", "teal": "#2fb8b0",
           "green": "#46c07a", "amber": "#e3a24b", "rose": "#ff6f91"}
NEW_ACCENTS = {"white": "#eaeaea", **ACCENTS}
LEAD = ACCENTS["blue"]
LEAD_DIM = "#3a5fa8"
BACK = "#e8a05c"
DUET = "#61c98a"
WARN = "#e2585f"

CHIP = "#262a35"
CHIP_HOVER = "#313747"
SUNG = "#39415a"

# ----------------------------------------------------------------- metrics
R_BUTTON, R_CHIP, R_BADGE = 6, 5, 3
PAD, GAP, GROUP, EDGE = 4, 8, 16, 24
ROW_H = 40


# -------------------------------------------------------------------- looks
# Two looks, one switch: the classic one above, and the new one, which takes
# on the player's -- glass over the album colours, white ink, no accent. The
# painted widgets read these names once per repaint of their palette (their
# `_inks`), so changing look is re-reading the names and re-dressing.
LOOK = "classic"
_CLASSIC = {k: v for k, v in dict(globals()).items()
            if k in ("INK_0", "INK_1", "INK_2", "INK_3", "INK_4", "LINE",
                     "TEXT", "MUTE", "FAINT", "LEAD", "LEAD_DIM", "BACK",
                     "DUET", "CHIP", "CHIP_HOVER", "SUNG")}
NEW = {
    "INK_0": "#07070a", "INK_1": "#00000000", "INK_2": "#1aeaeaea",
    "INK_3": "#14eaeaea", "INK_4": "#29eaeaea", "LINE": "#24eaeaea",
    "TEXT": "#eaeaea", "MUTE": "#a6eaeaea", "FAINT": "#80eaeaea",
    "LEAD": "#eaeaea", "LEAD_DIM": "#38eaeaea", "BACK": "#b3eaeaea",
    "DUET": "#d9eaeaea", "CHIP": "#1feaeaea", "CHIP_HOVER": "#2eeaeaea",
    "SUNG": "#29eaeaea",
}
ON_INK = "#141419"


def set_look(look: str) -> str:
    """"new" or "classic": which palette every widget here is drawn in."""
    global LOOK
    look = "new" if look == "new" else "classic"
    if look == LOOK:
        return LOOK
    was = LOOK
    LOOK = look
    if look == "new":
        if was == "classic":
            _CLASSIC.update({k: globals()[k] for k in _CLASSIC})
        globals().update(NEW)
    else:
        globals().update(_CLASSIC)
    accent()
    return LOOK


def rgba(hexcode: str) -> str:
    """A token as a stylesheet colour. Qt reads #AARRGGBB, a browser does
    not; written out this way the sheet means the same thing in both."""
    c = QColor(hexcode)
    return f"rgba({c.red()},{c.green()},{c.blue()},{c.alpha()})"


def px(n: float) -> int:
    """A metric in the same scale as the type."""
    return max(1, int(round(n * SCALE)))

SCALE = 1.0


def scale() -> float:
    global SCALE
    try:
        from . import keys as K
        SCALE = max(0.7, min(2.2, float(K.config().get("scale", 1.0))))
    except Exception:
        SCALE = 1.0
    return SCALE


def set_accent(name: str) -> str:
    """Make `name` the bright ink of the look that is on.

    Each look keeps its own: the classic one is blue unless told otherwise,
    and the new one is white -- the player's ink -- unless a colour is picked
    for it. Only the ink changes; the new look's buttons stay white.
    """
    if LOOK == "new":
        global LEAD, LEAD_DIM
        want = QColor(NEW_ACCENTS.get(str(name).lower(), str(name or "")))
        if not want.isValid():
            return LEAD
        LEAD = want.name()
        LEAD_DIM = "#38" + LEAD[1:]
        return LEAD
    return _set_accent(name)


def _set_accent(name: str) -> str:
    """Make `name` the bright ink, and derive the dim one from it.

    LEAD_DIM is not a second setting: it is what the accent looks like with
    the window behind it, and a person picking a colour is not also picking
    how far to sink it. Mixed rather than darkened, because darkening a blue
    gives a navy and mixing it with the near-black surface gives the same
    colour at a distance -- which is what "dim" has to mean for a chip that
    has already been sung.
    """
    global LEAD, LEAD_DIM
    want = ACCENTS.get(str(name).lower(), str(name or ""))
    c = QColor(want)
    if not c.isValid():
        return LEAD
    LEAD = c.name()
    back = QColor(INK_0)
    LEAD_DIM = QColor(
        round(c.red() * 0.55 + back.red() * 0.45),
        round(c.green() * 0.55 + back.green() * 0.45),
        round(c.blue() * 0.55 + back.blue() * 0.45)).name()
    return LEAD


def accent() -> str:
    """The accent this machine is set to for the look that is on, applied."""
    try:
        from . import keys as K
        if LOOK == "new":
            return set_accent(str(K.config().get("accent_new", "white")))
        return set_accent(str(K.config().get("accent", "blue")))
    except Exception:
        return LEAD


def set_scale(value: float) -> float:
    from . import keys as K
    global SCALE
    SCALE = max(0.7, min(2.2, float(value)))
    K.remember(scale=round(SCALE, 3))
    return SCALE


FAMILIES = ["Outfit", "Inter", "Poppins", "Noto Sans", "Cantarell",
            "Segoe UI Variable Display", "Segoe UI", "SF Pro Display",
            "Helvetica Neue", "DejaVu Sans", "Arial"]


def q(name: str, alpha: int | None = None) -> QColor:
    """A token as a QColor, optionally at some opacity."""
    c = QColor(name)
    if alpha is not None:
        c.setAlpha(alpha)
    return c


def family() -> str:
    """The first face on this machine from the project's own stack."""
    have = set(QFontDatabase.families())
    for name in FAMILIES:
        if name in have:
            return name
    return FAMILIES[-1]


def font(px: float = 12, weight: int = 500, mono: bool = False,
         caps: bool = False) -> QFont:
    """The house face at `px`, scaled with the window.

    `mono` is what the clock and the times ask for, so their digits line up
    down a column. The classic look answers with the system's monospace; the
    new one keeps the house face and turns its tabular figures on instead,
    so every number in the window is in the same type as everything else.
    """
    tabular = mono and LOOK == "new"
    f = QFont("monospace" if mono and not tabular else family())
    f.setPixelSize(max(7, int(round(px * SCALE))))
    f.setWeight(QFont.Weight(min(900, max(100, int(weight)))))
    if tabular:
        try:
            f.setFeature(QFont.Tag("tnum"), 1)
        except Exception:                                # noqa: BLE001
            pass
    elif mono:
        f.setStyleHint(QFont.StyleHint.Monospace)
    if caps:
        f.setCapitalization(QFont.Capitalization.AllUppercase)
        f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 108)
    return f


def sheet() -> str:
    """The stylesheet for every ordinary widget in the tool."""
    return f"""
/* No font-size here on purpose: a stylesheet rule outranks setFont(), so a
   size set on QWidget silently defeats every explicit font in the program --
   the start screen's 26px title came out at 12. The base size is set once on
   the application instead, and setFont works everywhere below it. */
QWidget {{ background: {INK_0}; color: {TEXT}; }}
QMainWindow, QDialog {{ background: {INK_0}; }}
QLabel {{ background: transparent; }}
QLabel[hint="1"] {{ color: {MUTE}; }}
QLabel[caption="1"] {{ color: {MUTE}; font-size: {px(10)}px;
                       font-weight: 600; }}

QPushButton {{
    background: {INK_3}; color: {TEXT};
    border: 1px solid {LINE}; border-radius: {R_BUTTON}px;
    padding: {px(5)}px {px(11)}px; font-size: {px(12)}px;
    font-weight: 500; }}
QPushButton:hover {{ background: {INK_4}; border-color: #39405020; }}
QPushButton:pressed {{ background: {LEAD_DIM}; border-color: {LEAD}; }}
QPushButton:disabled {{ color: {FAINT}; background: {INK_2};
                        border-color: {INK_2}; }}
QPushButton[primary="1"] {{
    background: {LEAD}; border-color: {LEAD}; color: #0b1020;
    font-weight: 600; }}
QPushButton[primary="1"]:hover {{ background: #6f9bff; }}
QPushButton[ghost="1"] {{ background: transparent; border-color: transparent;
                          color: {MUTE}; padding: 4px 8px; }}
QPushButton[ghost="1"]:hover {{ background: {INK_3}; color: {TEXT}; }}
QPushButton[mode="1"] {{
    background: transparent; border: none; border-radius: {R_BUTTON}px;
    padding: {px(10)}px {px(18)}px; font-size: {px(13)}px;
    font-weight: 600; color: {MUTE}; }}
QPushButton[mode="1"]:hover {{ background: {INK_3}; color: {TEXT}; }}
QPushButton[mode="1"]:checked {{ background: {LEAD}; color: #0b1020; }}

QLineEdit, QPlainTextEdit, QTextEdit, QListWidget, QTableWidget, QComboBox,
QSpinBox, QDoubleSpinBox, QKeySequenceEdit {{
    background: {INK_1}; color: {TEXT};
    border: 1px solid {LINE}; border-radius: {R_BUTTON}px;
    padding: {px(5)}px {px(7)}px; font-size: {px(13)}px;
    selection-background-color: {LEAD_DIM};
    selection-color: {TEXT}; }}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QListWidget:focus,
QKeySequenceEdit:focus {{ border: 1px solid {LEAD}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {INK_2}; border: 1px solid {LINE};
    selection-background-color: {LEAD_DIM}; outline: none; }}
QListWidget {{ padding: 2px; }}
QListWidget::item {{ padding: 3px 6px; border-radius: {R_BADGE}px; }}
QListWidget::item:selected {{ background: {LEAD_DIM}; color: {TEXT}; }}

QCheckBox, QRadioButton {{ spacing: 7px; color: {TEXT};
                           font-size: {px(13)}px; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: {px(15)}px; height: {px(15)}px; border: 1px solid {FAINT};
    background: {INK_1}; }}
QCheckBox::indicator {{ border-radius: {R_BADGE}px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {LEAD}; border-color: {LEAD}; }}

QMenu {{ background: {INK_2}; border: 1px solid {LINE};
         border-radius: {R_BUTTON}px; padding: 5px; }}
QMenu::item {{ padding: {px(6)}px {px(16)}px; font-size: {px(13)}px;
               border-radius: {R_BADGE}px; }}
QMenu::item:selected {{ background: {LEAD_DIM}; }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: 5px 8px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {INK_4}; border-radius: 5px;
                               min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {FAINT}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {INK_4}; border-radius: 5px;
                                 min-width: 30px; }}

/* Both halves of the groove are named. Styling the groove and the filled
   half and leaving `add-page` to Qt is what put a pale slab down the rest of
   the track: an unstyled sub-control falls back to the platform style, which
   draws its own light trough over the dark groove and reads as the window
   showing through the control. The two pages are the same height, radius and
   border as each other, so the track is one shape in two colours. */
QSlider {{ background: transparent; }}
QSlider::groove:horizontal {{ background: {INK_1}; border: 1px solid {LINE};
                              height: {px(4)}px; border-radius: {px(3)}px; }}
QSlider::sub-page:horizontal {{ background: {LEAD}; border: 1px solid {LEAD};
                                height: {px(4)}px; border-radius: {px(3)}px; }}
QSlider::add-page:horizontal {{ background: {INK_1}; border: 1px solid {LINE};
                                height: {px(4)}px; border-radius: {px(3)}px; }}
QSlider::handle:horizontal {{ background: {TEXT}; border: 1px solid {LINE};
                              width: {px(11)}px; margin: -{px(5)}px 0;
                              border-radius: {px(6)}px; }}
QSlider::handle:horizontal:hover {{ background: {LEAD}; border-color: {LEAD}; }}
/* Sub-control FIRST, then the state -- `QSlider:disabled::handle` is not the
   same selector with the words in a different order. Qt reads the leading
   pseudo-state as the widget's own, so that spelling set `background: FAINT`
   on the QSlider itself: a pale slab the height of the whole control behind
   the track, which reads as the window showing through it. It also landed in
   the widget's palette, so the wrongness outlived the rule. */
QSlider::sub-page:horizontal:disabled {{ background: {INK_4};
                                         border-color: {INK_4}; }}
QSlider::add-page:horizontal:disabled {{ background: {INK_1};
                                         border-color: {INK_2}; }}
QSlider::handle:horizontal:disabled {{ background: {FAINT};
                                       border-color: {LINE}; }}

QToolTip {{ background: {INK_2}; color: {TEXT}; border: 1px solid {LINE};
            border-radius: {R_BADGE}px; padding: 6px 8px; }}
QSplitter::handle {{ background: {LINE}; }}
"""


_CARDS = 0


def card(widget, level: str = INK_2) -> None:
    """Put a widget on a raised surface with a hairline round it.

    Scoped to this widget by object name. An unscoped stylesheet on a parent
    is inherited by every descendant, which put a border and a 6px radius
    around every label and text box inside the card and flattened the buttons
    with it -- Qt's selectors match children unless told otherwise.
    """
    global _CARDS
    _CARDS += 1
    name = f"card{_CARDS}"
    widget.setObjectName(name)
    widget.setStyleSheet(
        f"QWidget#{name} {{ background: {level}; border: 1px solid {LINE}; "
        f"border-radius: {R_BUTTON}px; }}")


def sheet_new() -> str:
    """The new look: the player's glass and white ink, for ordinary widgets.

    Surfaces are panes of dark glass over the painted background rather than
    steps of grey, the one filled thing on screen is white, and nothing is
    blue. Radii and sizes follow the player's own settings drawer.
    """
    w = lambda a: f"rgba(234,234,234,{a})"            # noqa: E731
    return f"""
QWidget {{ background: transparent; color: #eaeaea; }}
QMainWindow, QDialog {{ background: #0c0c10; }}
QDialog QWidget {{ background: transparent; }}
QLabel {{ background: transparent; }}
QLabel[hint="1"] {{ color: {w(.65)}; }}
QLabel[caption="1"] {{ color: {w(.55)}; }}
QLabel[faint="1"] {{ color: {w(.5)}; }}

QPushButton, QToolButton {{
    background: {w(.08)}; color: #eaeaea;
    border: 1px solid {w(.14)}; border-radius: {px(10)}px;
    padding: 0 {px(14)}px; min-height: {px(38)}px;
    font-size: {px(15)}px; font-weight: 600; }}
QPushButton:hover, QToolButton:hover {{ background: {w(.14)}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {w(.2)}; }}
QPushButton:disabled {{ color: {w(.35)}; background: {w(.04)};
                        border-color: {w(.06)}; }}
QPushButton[primary="1"] {{ background: #eaeaea; color: #141419;
                            border-color: #eaeaea; font-weight: 700; }}
QPushButton[primary="1"]:hover {{ background: #ffffff; }}
QPushButton[ghost="1"] {{ background: transparent; border-color: transparent;
                          color: {w(.75)}; min-height: {px(28)}px;
                          padding: 0 {px(10)}px; font-size: {px(13.5)}px; }}
QPushButton[ghost="1"]:hover {{ background: {w(.1)}; color: #ffffff; }}
QPushButton[quiet="1"] {{ background: transparent; border-color: transparent;
                          color: {w(.8)}; }}
QPushButton[quiet="1"]:hover {{ background: {w(.1)}; color: #ffffff; }}
QPushButton[seg="1"] {{ background: transparent; border: none;
                        border-radius: {px(7)}px; min-height: {px(28)}px;
                        padding: 0 {px(11)}px; font-size: {px(14)}px;
                        color: {w(.8)}; }}
QPushButton[seg="1"]:hover {{ background: {w(.12)}; color: #ffffff; }}
QPushButton[seg="1"]:checked {{ background: {w(.92)}; color: #141419; }}
QPushButton[segbig="1"] {{ background: transparent; border: none;
                           border-radius: {px(9)}px; min-height: {px(34)}px;
                           padding: 0 {px(18)}px; font-size: {px(15)}px;
                           font-weight: 700; color: {w(.75)}; }}
QPushButton[segbig="1"]:hover {{ background: {w(.1)}; }}
QPushButton[segbig="1"]:checked {{ background: {w(.92)}; color: #141419; }}
QPushButton[play="1"] {{ background: #eaeaea; color: #141419;
                         border: 1px solid #eaeaea;
                         border-radius: {px(21)}px; min-height: {px(42)}px;
                         padding: 0 {px(20)}px; font-size: {px(16)}px;
                         font-weight: 700; }}
QPushButton[play="1"]:hover {{ background: #ffffff; }}
QPushButton[pad="1"] {{ border-radius: {px(12)}px; font-size: {px(16)}px;
                        font-weight: 700; min-height: {px(64)}px; }}
QPushButton[pad="row"] {{ font-size: {px(14.5)}px; min-height: {px(44)}px; }}
QPushButton[pad="1"][primary="1"] {{ background: #eaeaea; color: #141419; }}

QFrame[glass="1"] {{ background: rgba(20,20,26,140);
                     border: 1px solid {w(.1)}; border-radius: {px(14)}px; }}
QFrame[well="1"] {{ background: {w(.07)}; border: none;
                    border-radius: {px(10)}px; }}
QFrame[wellbig="1"] {{ background: {w(.07)}; border: none;
                       border-radius: {px(12)}px; }}
QFrame[rule="1"] {{ background: {w(.14)}; border: none; }}
QFrame[splitl="1"] {{ border: none; border-left: 1px solid {w(.12)};
                      border-radius: 0; }}

QLineEdit, QPlainTextEdit, QTextEdit, QListWidget, QTableWidget, QComboBox,
QSpinBox, QDoubleSpinBox, QKeySequenceEdit, QTreeWidget {{
    background: rgba(0,0,0,70); color: #eaeaea;
    border: 1px solid {w(.18)}; border-radius: {px(9)}px;
    padding: {px(6)}px {px(10)}px; font-size: {px(15)}px;
    selection-background-color: {w(.3)}; selection-color: #ffffff; }}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QListWidget:focus,
QKeySequenceEdit:focus {{ border: 1px solid {w(.55)}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{ background: rgb(30,30,37); border: 1px solid {w(.14)};
    selection-background-color: {w(.12)}; outline: none; }}
QListWidget::item:selected, QTreeWidget::item:selected {{
    background: {w(.14)}; color: #ffffff; }}
QHeaderView::section {{ background: transparent; color: {w(.6)};
                        border: none; padding: 4px; }}

QCheckBox, QRadioButton {{ spacing: 8px; color: #eaeaea;
                           font-size: {px(14)}px; font-weight: 600; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: {px(16)}px; height: {px(16)}px; border: 1.5px solid {w(.4)};
    background: transparent; border-radius: {px(5)}px; }}
QRadioButton::indicator {{ border-radius: {px(8)}px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: #eaeaea; border-color: #eaeaea; }}

QMenu {{ background: rgb(28,28,35); border: 1px solid {w(.14)};
         border-radius: {px(12)}px; padding: 6px; }}
QMenu::item {{ padding: {px(8)}px {px(16)}px; font-size: {px(14)}px;
               border-radius: {px(8)}px; }}
QMenu::item:selected {{ background: {w(.09)}; }}
QMenu::separator {{ height: 1px; background: {w(.1)}; margin: 5px 8px; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 9px; margin: 3px; }}
QScrollBar::handle:vertical {{ background: {w(.18)}; border-radius: 4px;
                               min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {w(.3)}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 9px; margin: 3px; }}
QScrollBar::handle:horizontal {{ background: {w(.18)}; border-radius: 4px;
                                 min-width: 30px; }}

QSlider {{ background: transparent; min-height: {px(18)}px; }}
QSlider::groove:horizontal {{ background: {w(.16)}; border: none;
                              height: {px(4)}px; border-radius: {px(2)}px; }}
QSlider::sub-page:horizontal {{ background: {w(.86)}; border: none;
                                height: {px(4)}px; border-radius: {px(2)}px; }}
QSlider::add-page:horizontal {{ background: {w(.16)}; border: none;
                                height: {px(4)}px; border-radius: {px(2)}px; }}
QSlider::handle:horizontal {{ background: #eaeaea; border: none;
                              width: {px(14)}px; margin: -{px(5)}px 0;
                              border-radius: {px(7)}px; }}
QSlider::sub-page:horizontal:disabled {{ background: {w(.3)}; }}
QSlider::handle:horizontal:disabled {{ background: {w(.45)}; }}

QTabWidget::pane {{ border: 1px solid {w(.1)}; border-radius: {px(10)}px; }}
QTabBar::tab {{ background: transparent; color: {w(.62)}; padding: 8px 14px;
                border-radius: {px(8)}px; font-weight: 600; }}
QTabBar::tab:selected {{ background: {w(.13)}; color: #ffffff; }}

QToolTip {{ background: rgb(28,28,35); color: #eaeaea;
            border: 1px solid {w(.14)}; border-radius: {px(8)}px;
            padding: 6px 9px; }}
"""
