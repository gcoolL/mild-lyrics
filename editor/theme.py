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
INK_0 = "#0d0e12"        # the window behind everything
INK_1 = "#14161c"        # the lyric list, the waveform bed
INK_2 = "#1b1e26"        # chrome: ribbon, transport, dialogs
INK_3 = "#232733"        # a control at rest
INK_4 = "#2c313f"        # ...under the pointer
LINE = "#2a2e3a"         # hairlines, 1px, never heavier
TEXT = "#e9eaee"
MUTE = "#8d92a2"
# Lifted to 4.6:1 on INK_1 -- line numbers are set in it, and a
# number nobody can read is not a quieter number, it is a missing one.
FAINT = "#7b8194"

# ------------------------------------------------------------------- inks
# Two carry meaning. Nothing else is allowed to be colourful, so that these
# always mean what they say.
LEAD = "#5b8cff"         # the lead voice, the playhead, the primary action
LEAD_DIM = "#3a5fa8"
BACK = "#e8a05c"         # backing vocals, wherever they are drawn
DUET = "#61c98a"         # the answering voice
WARN = "#e2585f"         # only for losing work

CHIP = "#262a35"         # a syllable at rest
CHIP_HOVER = "#313747"
SUNG = "#39415a"         # sung through, in preview

# ----------------------------------------------------------------- metrics
R_BUTTON, R_CHIP, R_BADGE = 6, 5, 3
PAD, GAP, GROUP, EDGE = 4, 8, 16, 24
ROW_H = 40


def px(n: float) -> int:
    """A metric in the same scale as the type."""
    return max(1, int(round(n * SCALE)))

# Everything is sized through font(), so one number moves the whole window.
# Lyrics are the thing being read here, not chrome, and they are set larger
# than a settings panel would be -- this is a tool for looking at words.
SCALE = 1.0


def scale() -> float:
    global SCALE
    try:
        from . import keys as K
        SCALE = max(0.7, min(2.2, float(K.config().get("scale", 1.0))))
    except Exception:
        SCALE = 1.0
    return SCALE


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
    f = QFont("monospace" if mono else family())
    f.setPixelSize(max(7, int(round(px * SCALE))))
    f.setWeight(QFont.Weight(min(900, max(100, int(weight)))))
    if mono:
        # Times and line numbers have to line up vertically down a column or
        # they cannot be compared at a glance, which is the only reason
        # anybody reads a column of times.
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
