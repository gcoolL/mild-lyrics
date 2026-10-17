"""What the active keyboard layout types on each key of the main block.

`read(platform)` returns a Layout or None where it cannot be read; keymap.py
names keys with it. Why and how: docs/notes/mild-lyrics/keymap.md.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import mmap
import os
import sys

# The typing keys, as each platform numbers them: xkb keycodes (evdev + 8)
# and Windows set-1 scan codes. Digits, three letter rows, `, \ and the ISO key.
XKB_CODES = [*range(10, 22), *range(24, 36), *range(38, 50), *range(51, 62), 94]
WIN_CODES = [*range(0x02, 0x0E), *range(0x10, 0x1C), *range(0x1E, 0x2A),
             *range(0x2B, 0x36), 0x56]

# xkb's dead keysyms, as the mark keymap.DEAD names them by
DEAD_SYMS = {"dead_circumflex": "^", "dead_grave": "`", "dead_acute": "´",
             "dead_tilde": "~", "dead_diaeresis": "¨", "dead_abovering": "°",
             "dead_cedilla": "¸", "dead_caron": "ˇ", "dead_macron": "¯",
             "dead_breve": "˘", "dead_abovedot": "˙", "dead_doubleacute": "˝",
             "dead_ogonek": "˛"}


class Layout:
    """{code: (plain, shifted)} per group; each side is (char, dead) or None."""

    def __init__(self, groups: list, group: int = 0, source: str = ""):
        self.groups = groups
        self.group = group if 0 <= group < len(groups) else 0
        self.source = source

    def typed(self, code: int, shifted: bool, group: int | None = None):
        keys = self.groups[self.group if group is None else group]
        got = keys.get(code)
        return got[1 if shifted else 0] if got else None


def read(platform: str) -> Layout | None:
    """The layout Qt's platform `platform` is typing with, or None."""
    try:
        if sys.platform == "win32":
            return _windows()
        if sys.platform.startswith("linux"):
            if platform == "wayland":
                return _wayland()
            if platform == "xcb":
                return _x11()
    except Exception:                                       # noqa: BLE001
        return None
    return None


# ------------------------------------------------------------------ xkb

def _lib(name: str):
    path = ctypes.util.find_library(name)
    return ctypes.CDLL(path) if path else None


_XKB = None


def _xkb():
    global _XKB
    if _XKB is None:
        x = _lib("xkbcommon")
        if x is None:
            raise OSError("no libxkbcommon")
        P, U, I = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int
        x.xkb_context_new.restype = P
        x.xkb_context_new.argtypes = [I]
        x.xkb_context_unref.argtypes = [P]
        x.xkb_keymap_new_from_string.restype = P
        x.xkb_keymap_new_from_string.argtypes = [P, ctypes.c_char_p, I, I]
        x.xkb_keymap_unref.argtypes = [P]
        x.xkb_keymap_num_layouts.restype = U
        x.xkb_keymap_num_layouts.argtypes = [P]
        x.xkb_keymap_mod_get_index.restype = U
        x.xkb_keymap_mod_get_index.argtypes = [P, ctypes.c_char_p]
        x.xkb_state_new.restype = P
        x.xkb_state_new.argtypes = [P]
        x.xkb_state_unref.argtypes = [P]
        x.xkb_state_update_mask.restype = I
        x.xkb_state_update_mask.argtypes = [P, U, U, U, U, U, U]
        x.xkb_state_key_get_one_sym.restype = U
        x.xkb_state_key_get_one_sym.argtypes = [P, U]
        x.xkb_state_key_get_utf32.restype = U
        x.xkb_state_key_get_utf32.argtypes = [P, U]
        x.xkb_state_serialize_layout.restype = U
        x.xkb_state_serialize_layout.argtypes = [P, I]
        x.xkb_keysym_get_name.restype = I
        x.xkb_keysym_get_name.argtypes = [U, ctypes.c_char_p, ctypes.c_size_t]
        _XKB = x
    return _XKB


def _sym(x, state, code: int):
    ch = x.xkb_state_key_get_utf32(state, code)
    if ch and chr(ch).isprintable():
        return (chr(ch), False)
    sym = x.xkb_state_key_get_one_sym(state, code)
    buf = ctypes.create_string_buffer(64)
    if sym and x.xkb_keysym_get_name(sym, buf, 64) > 0:
        mark = DEAD_SYMS.get(buf.value.decode("ascii", "replace"))
        if mark:
            return (mark, True)
    return None


def _from_keymap(km, group: int = 0, source: str = "") -> Layout | None:
    x = _xkb()
    shift = x.xkb_keymap_mod_get_index(km, b"Shift")
    if shift >= 32:
        return None
    state = x.xkb_state_new(km)
    if not state:
        return None
    try:
        groups = []
        for g in range(max(1, x.xkb_keymap_num_layouts(km))):
            keys = {}
            for code in XKB_CODES:
                x.xkb_state_update_mask(state, 0, 0, 0, 0, 0, g)
                plain = _sym(x, state, code)
                x.xkb_state_update_mask(state, 1 << shift, 0, 0, 0, 0, g)
                keys[code] = (plain, _sym(x, state, code))
            groups.append(keys)
    finally:
        x.xkb_state_unref(state)
    return Layout(groups, group, source)


def from_text(text: str, source: str = "keymap") -> Layout | None:
    """A Layout from an xkb keymap in text form (what Wayland hands out)."""
    x = _xkb()
    ctx = x.xkb_context_new(0)
    if not ctx:
        return None
    try:
        km = x.xkb_keymap_new_from_string(ctx, text.encode("utf-8"), 1, 0)
        if not km:
            return None
        try:
            return _from_keymap(km, 0, source)
        finally:
            x.xkb_keymap_unref(km)
    finally:
        x.xkb_context_unref(ctx)


# -------------------------------------------------------------- Wayland

class _Arg(ctypes.Union):
    _fields_ = [("u", ctypes.c_uint32), ("s", ctypes.c_char_p),
                ("o", ctypes.c_void_p)]


def _wayland_keymap() -> str | None:
    """The compositor's keymap, from a wl_keyboard on a connection of our
    own: it is sent to every keyboard object as soon as one is made."""
    wl = _lib("wayland-client")
    if wl is None:
        return None
    P, U, I = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int32
    wl.wl_display_connect.restype = P
    wl.wl_display_connect.argtypes = [ctypes.c_char_p]
    wl.wl_display_disconnect.argtypes = [P]
    wl.wl_display_roundtrip.restype = ctypes.c_int
    wl.wl_display_roundtrip.argtypes = [P]
    wl.wl_proxy_get_version.restype = U
    wl.wl_proxy_get_version.argtypes = [P]
    wl.wl_proxy_marshal_array_flags.restype = P
    wl.wl_proxy_marshal_array_flags.argtypes = [P, U, P, U, U, ctypes.POINTER(_Arg)]
    wl.wl_proxy_add_listener.restype = ctypes.c_int
    wl.wl_proxy_add_listener.argtypes = [P, P, P]
    wl.wl_proxy_destroy.argtypes = [P]

    def iface(name):
        return ctypes.addressof(ctypes.c_char.in_dll(wl, name))

    reg_if, seat_if, kb_if = (iface("wl_registry_interface"),
                              iface("wl_seat_interface"),
                              iface("wl_keyboard_interface"))
    display = wl.wl_display_connect(None)
    if not display:
        return None
    got = {"seat": None, "keymap": None}
    made = []
    try:
        args = (_Arg * 1)()
        registry = wl.wl_proxy_marshal_array_flags(
            display, 1, reg_if, wl.wl_proxy_get_version(display), 0, args)
        if not registry:
            return None
        made.append(registry)

        GLOBAL = ctypes.CFUNCTYPE(None, P, P, U, ctypes.c_char_p, U)
        REMOVE = ctypes.CFUNCTYPE(None, P, P, U)

        def on_global(_d, _r, name, interface, version):
            if interface == b"wl_seat" and got["seat"] is None:
                got["seat"] = (name, min(int(version), 5))

        reg_cbs = (GLOBAL(on_global), REMOVE(lambda *_a: None))
        reg_listener = (P * 2)(*[ctypes.cast(c, P) for c in reg_cbs])
        wl.wl_proxy_add_listener(registry, reg_listener, None)
        wl.wl_display_roundtrip(display)
        if got["seat"] is None:
            return None

        name, version = got["seat"]
        seat_name = ctypes.cast(ctypes.c_void_p.from_address(seat_if),
                                ctypes.c_char_p).value
        args = (_Arg * 4)()
        args[0].u, args[1].s, args[2].u, args[3].o = name, seat_name, version, None
        seat = wl.wl_proxy_marshal_array_flags(registry, 0, seat_if, version, 0, args)
        if not seat:
            return None
        made.append(seat)
        args = (_Arg * 1)()
        keyboard = wl.wl_proxy_marshal_array_flags(
            seat, 1, kb_if, wl.wl_proxy_get_version(seat), 0, args)
        if not keyboard:
            return None
        made.append(keyboard)

        KEYMAP = ctypes.CFUNCTYPE(None, P, P, U, I, U)

        def on_keymap(_d, _k, fmt, fd, size):
            try:
                if fmt == 1 and size:
                    with mmap.mmap(fd, size, prot=mmap.PROT_READ) as m:
                        got["keymap"] = m[:size].split(b"\0", 1)[0].decode(
                            "utf-8", "replace")
            finally:
                os.close(fd)

        kb_cbs = (KEYMAP(on_keymap),
                  ctypes.CFUNCTYPE(None, P, P, U, P, P)(lambda *_a: None),
                  ctypes.CFUNCTYPE(None, P, P, U, P)(lambda *_a: None),
                  ctypes.CFUNCTYPE(None, P, P, U, U, U, U)(lambda *_a: None),
                  ctypes.CFUNCTYPE(None, P, P, U, U, U, U, U)(lambda *_a: None),
                  ctypes.CFUNCTYPE(None, P, P, I, I)(lambda *_a: None))
        kb_listener = (P * 6)(*[ctypes.cast(c, P) for c in kb_cbs])
        wl.wl_proxy_add_listener(keyboard, kb_listener, None)
        wl.wl_display_roundtrip(display)
        return got["keymap"]
    finally:
        for proxy in reversed(made):
            wl.wl_proxy_destroy(proxy)
        wl.wl_display_disconnect(display)


def _wayland() -> Layout | None:
    text = _wayland_keymap()
    return from_text(text, "wayland") if text else None


# ------------------------------------------------------------------ X11

def _x11() -> Layout | None:
    xcb, xx = _lib("xcb"), _lib("xkbcommon-x11")
    if xcb is None or xx is None:
        return None
    x = _xkb()
    P, I = ctypes.c_void_p, ctypes.c_int
    xcb.xcb_connect.restype = P
    xcb.xcb_connect.argtypes = [ctypes.c_char_p, P]
    xcb.xcb_connection_has_error.restype = I
    xcb.xcb_connection_has_error.argtypes = [P]
    xcb.xcb_disconnect.argtypes = [P]
    xx.xkb_x11_setup_xkb_extension.restype = I
    xx.xkb_x11_setup_xkb_extension.argtypes = [P, ctypes.c_uint16, ctypes.c_uint16,
                                               I, P, P, P, P]
    xx.xkb_x11_get_core_keyboard_device_id.restype = ctypes.c_int32
    xx.xkb_x11_get_core_keyboard_device_id.argtypes = [P]
    xx.xkb_x11_keymap_new_from_device.restype = P
    xx.xkb_x11_keymap_new_from_device.argtypes = [P, P, ctypes.c_int32, I]
    xx.xkb_x11_state_new_from_device.restype = P
    xx.xkb_x11_state_new_from_device.argtypes = [P, P, ctypes.c_int32]
    conn = xcb.xcb_connect(None, None)
    if not conn:
        return None
    try:
        if xcb.xcb_connection_has_error(conn):
            return None
        if not xx.xkb_x11_setup_xkb_extension(conn, 1, 0, 0, None, None, None, None):
            return None
        dev = xx.xkb_x11_get_core_keyboard_device_id(conn)
        if dev < 0:
            return None
        ctx = x.xkb_context_new(0)
        try:
            km = xx.xkb_x11_keymap_new_from_device(ctx, conn, dev, 0)
            if not km:
                return None
            try:
                state = xx.xkb_x11_state_new_from_device(km, conn, dev)
                group = 0
                if state:
                    group = x.xkb_state_serialize_layout(state, 0x80)  # effective
                    x.xkb_state_unref(state)
                return _from_keymap(km, int(group), "x11")
            finally:
                x.xkb_keymap_unref(km)
        finally:
            x.xkb_context_unref(ctx)
    finally:
        xcb.xcb_disconnect(conn)


# -------------------------------------------------------------- Windows

def _windows() -> Layout | None:
    """Unverified here: no Windows to run it on. keymap checks every press
    against it and stops using it if Qt says otherwise."""
    from ctypes import wintypes
    u = ctypes.WinDLL("user32")
    u.GetKeyboardLayout.restype = ctypes.c_void_p
    u.GetKeyboardLayout.argtypes = [wintypes.DWORD]
    u.MapVirtualKeyExW.restype = wintypes.UINT
    u.MapVirtualKeyExW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p]
    u.ToUnicodeEx.restype = ctypes.c_int
    u.ToUnicodeEx.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                              wintypes.LPWSTR, ctypes.c_int, wintypes.UINT,
                              ctypes.c_void_p]
    hkl = u.GetKeyboardLayout(0)
    if not hkl:
        return None
    keys = {}
    for code in WIN_CODES:
        vk = u.MapVirtualKeyExW(code, 3, hkl)                 # VSC_TO_VK_EX
        if not vk:
            continue
        sides = []
        for shifted in (False, True):
            state = (ctypes.c_ubyte * 256)()
            if shifted:
                state[0x10] = 0x80                            # VK_SHIFT
            buf = ctypes.create_unicode_buffer(8)
            # flag 4: leave the kernel's dead-key state alone (1607+); the
            # second call clears it where the flag is not honoured.
            n = u.ToUnicodeEx(vk, code, state, buf, 8, 4, hkl)
            if n < 0:
                mark = buf.value[:1]
                u.ToUnicodeEx(vk, code, state, ctypes.create_unicode_buffer(8),
                              8, 4, hkl)
                sides.append((mark, True) if mark else None)
            elif n == 1 and buf.value[:1].isprintable():
                sides.append((buf.value[:1], False))
            else:
                sides.append(None)
        keys[code] = tuple(sides)
    return Layout([keys], 0, "windows")
