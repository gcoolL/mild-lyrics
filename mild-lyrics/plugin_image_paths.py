"""Read a local overlay without following links/reparse points or contacting
a network share. This is called off the GUI thread. Ancestor directory
handles stay open during the read, so renaming a directory cannot redirect
the final open outside its approved root."""

import os
import pathlib
import stat

MAX_INPUT = 16 * 1024 * 1024


def snapshot(path, root):
    path, root = pathlib.Path(path), pathlib.Path(root)
    if not path.is_absolute() or not root.is_absolute() or not path.is_relative_to(root):
        raise ValueError("overlay is outside its plugin's folders")
    if ".." in path.parts or "\0" in str(path):
        raise ValueError("invalid overlay path")
    if os.name == "nt":
        return _windows(path)
    return _posix(path)


def _read(fd):
    try:
        stream = os.fdopen(fd, "rb")
    except Exception:
        os.close(fd)
        raise
    with stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_INPUT:
            raise ValueError("overlay must be a regular file of 16 MB or less")
        data = stream.read(MAX_INPUT + 1)
        if len(data) > MAX_INPUT:
            raise ValueError("overlay input too large")
        return data


def _posix(path):
    dirs = []
    try:
        fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        dirs.append(fd)
        for part in path.parts[1:-1]:
            fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            dirs.append(fd)
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        return _read(fd)
    finally:
        for fd in reversed(dirs):
            os.close(fd)


def _windows(path):
    import ctypes as C
    from ctypes import wintypes as W
    import msvcrt

    # Must also check here: the GUI's lexical check is not a security boundary
    # for callers of this helper. No UNC, device names, ADS or DOS aliases.
    if str(path).startswith(("\\", "/")) or len(path.drive) != 2:
        raise ValueError("not a local drive path")
    for part in path.parts[1:]:
        if (":" in part or part.endswith((".", " "))
                or pathlib.PureWindowsPath(part).is_reserved()):
            raise ValueError("invalid Windows image path")

    class Info(C.Structure):
        _fields_ = [("attributes", W.DWORD), ("creation", W.FILETIME),
                    ("access", W.FILETIME), ("write", W.FILETIME),
                    ("volume", W.DWORD), ("size_high", W.DWORD),
                    ("size_low", W.DWORD), ("links", W.DWORD),
                    ("index_high", W.DWORD), ("index_low", W.DWORD)]

    k = C.WinDLL("kernel32", use_last_error=True)
    k.GetDriveTypeW.argtypes = [W.LPCWSTR]
    if k.GetDriveTypeW(path.anchor) not in (2, 3, 6):
        raise ValueError("overlay must be on a local drive")
    k.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, C.c_void_p,
                             W.DWORD, W.DWORD, W.HANDLE]
    k.CreateFileW.restype = W.HANDLE
    k.GetFileInformationByHandle.argtypes = [W.HANDLE, C.POINTER(Info)]
    k.CloseHandle.argtypes = [W.HANDLE]
    handles = []
    try:
        parts = path.parts
        for i in range(1, len(parts) + 1):
            final = i == len(parts)
            prefix = str(pathlib.Path(*parts[:i]))
            # No DELETE sharing: keep this ancestor from being renamed/replaced.
            # OPEN_REPARSE_POINT refuses traversing junctions even for the file.
            h = k.CreateFileW(prefix, 0x80000000 if final else 0,
                              3, None, 3, 0x02200000, None)
            if h == C.c_void_p(-1).value:
                raise C.WinError(C.get_last_error())
            handles.append(h)
            info = Info()
            if not k.GetFileInformationByHandle(h, C.byref(info)):
                raise C.WinError(C.get_last_error())
            if info.attributes & 0x400:
                raise ValueError("overlay path contains a reparse point")
            if not final and not info.attributes & 0x10:
                raise ValueError("overlay ancestor is not a directory")
            if final and info.attributes & 0x10:
                raise ValueError("overlay must be a regular file")
        fd = msvcrt.open_osfhandle(handles[-1], os.O_RDONLY | os.O_BINARY)
        handles.pop()                         # fd owns it now
        return _read(fd)
    finally:
        for h in reversed(handles):
            k.CloseHandle(h)
