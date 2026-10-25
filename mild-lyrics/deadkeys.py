"""Windows: one press of a dead key reaches the window, as it does on Linux,
via a WH_KEYBOARD hook while the layout has dead keys. Notes:
docs/notes/mild-lyrics/keymap.md."""
from __future__ import annotations

import sys

import keymap as KM

WH_KEYBOARD = 2
HC_ACTION = 0
VK_SHIFT, VK_CONTROL, VK_MENU = 0x10, 0x11, 0x12
MODIFIER_VKS = {0x10, 0x11, 0x12, 0x14, 0x5B, 0x5C, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5}

_HOOK = {"handle": None, "proc": None}

# The window's say: whether a press of the key named `name` is a key there now, not the
# start of an accent being typed. Set by the window; until then, nothing is taken.
taker = None


def has_dead(lay) -> bool:
    return bool(lay) and any(side and side[1] for keys in lay.groups
                             for got in keys.values() for side in got)


def sync() -> None:
    """Install the hook while the layout in use has dead keys; remove it otherwise."""
    if sys.platform != "win32":
        return
    try:
        want = has_dead(KM.layout())
        if want and _HOOK["handle"] is None:
            _install()
        elif not want and _HOOK["handle"] is not None:
            _remove()
    except Exception:                                       # noqa: BLE001
        pass


def _user32():
    import ctypes
    from ctypes import wintypes
    u = ctypes.WinDLL("user32")
    proc = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
    u.SetWindowsHookExW.restype = ctypes.c_void_p
    u.SetWindowsHookExW.argtypes = [ctypes.c_int, proc, ctypes.c_void_p, wintypes.DWORD]
    u.CallNextHookEx.restype = ctypes.c_ssize_t
    u.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
    u.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
    u.GetKeyState.restype = ctypes.c_short
    return u, proc


def _install() -> None:
    import ctypes
    u, proto = _user32()

    def hook(code, wparam, lparam):
        try:
            if code == HC_ACTION and _key(u, int(wparam), int(lparam)):
                return 1                # swallowed: Windows starts no accent
        except Exception:                                   # noqa: BLE001
            pass
        return u.CallNextHookEx(None, code, wparam, lparam)
    proc = proto(hook)
    tid = ctypes.WinDLL("kernel32").GetCurrentThreadId()
    handle = u.SetWindowsHookExW(WH_KEYBOARD, proc, None, tid)
    if handle:
        _HOOK.update(handle=handle, proc=proc)      # proc held: Windows calls it


def _remove() -> None:
    u, _ = _user32()
    u.UnhookWindowsHookEx(_HOOK["handle"])
    _HOOK.update(handle=None, proc=None)


def _key(u, vk: int, lp: int) -> bool:
    """A key-down off the queue: True when it is a dead key the window takes, posted as one."""
    if lp & (1 << 31) or vk in MODIFIER_VKS or taker is None:
        return False
    lay = KM._LAY["layout"] if KM._LAY["read"] else None
    shift = bool(u.GetKeyState(VK_SHIFT) & 0x8000)
    held = bool(u.GetKeyState(VK_CONTROL) & 0x8000) or bool(u.GetKeyState(VK_MENU) & 0x8000)
    scan = (lp >> 16) & 0xFF
    got = lay.typed(scan, shift) if lay is not None and not held else None
    if not (got and got[1]):
        return False
    name = KM.code_name(lay, scan, shift)
    if not (name and taker(name)):
        return False
    return post(got[0], shift, scan, vk)


QT_DEAD = {mark: name for name, mark in KM.DEAD.items()}


def post(mark: str, shift: bool, scan: int, vk: int) -> bool:
    """A Key_Dead_* press for `mark` to whatever has focus; False if Qt has no such key."""
    from PyQt6.QtCore import QCoreApplication, QEvent, Qt
    from PyQt6.QtGui import QGuiApplication, QKeyEvent
    key = getattr(Qt.Key, QT_DEAD.get(mark, ""), None)
    target = QGuiApplication.focusObject() or QGuiApplication.focusWindow()
    if key is None or target is None:
        return False
    mods = Qt.KeyboardModifier.ShiftModifier if shift else Qt.KeyboardModifier.NoModifier
    QCoreApplication.postEvent(target, QKeyEvent(QEvent.Type.KeyPress, key, mods, scan, vk, 0, ""))
    return True
