"""Bounded, disposable image decoder for plugin_overlay; no plugin code runs
here. Input is a bounded snapshot, not a path. Output is a small JSON header
followed by tightly packed RGBA frames. The parent enforces a wall deadline."""

import json
import os
import struct
import sys

MAX_INPUT = 16 * 1024 * 1024
MAX_BYTES = 8 * 1024 * 1024
MAX_SIDE = 1024
MAX_FRAMES = 256
MEMORY = 512 * 1024 * 1024


def limit_memory():
    if os.name == "posix":
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (MEMORY, MEMORY))
        resource.setrlimit(resource.RLIMIT_CPU, (4, 4))
    elif os.name == "nt":
        import ctypes as C
        from ctypes import wintypes as W

        class Basic(C.Structure):
            _fields_ = [("process_time", C.c_int64), ("job_time", C.c_int64),
                        ("flags", W.DWORD), ("min_ws", C.c_size_t),
                        ("max_ws", C.c_size_t), ("active", W.DWORD),
                        ("affinity", C.c_size_t), ("priority", W.DWORD),
                        ("scheduling", W.DWORD)]

        class IO(C.Structure):
            _fields_ = [(n, C.c_uint64) for n in
                        ("read_ops", "write_ops", "other_ops", "read", "write", "other")]

        class Extended(C.Structure):
            _fields_ = [("basic", Basic), ("io", IO),
                        ("process_memory", C.c_size_t), ("job_memory", C.c_size_t),
                        ("peak_process", C.c_size_t), ("peak_job", C.c_size_t)]

        k = C.WinDLL("kernel32", use_last_error=True)
        k.CreateJobObjectW.argtypes = [C.c_void_p, W.LPCWSTR]
        k.CreateJobObjectW.restype = W.HANDLE
        k.SetInformationJobObject.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.DWORD]
        k.AssignProcessToJobObject.argtypes = [W.HANDLE, W.HANDLE]
        k.GetCurrentProcess.restype = W.HANDLE
        job = k.CreateJobObjectW(None, None)
        info = Extended()
        info.basic.flags = 0x100                 # JOB_OBJECT_LIMIT_PROCESS_MEMORY
        info.process_memory = MEMORY
        if not job or not k.SetInformationJobObject(job, 9, C.byref(info), C.sizeof(info)):
            raise OSError("could not bound decoder memory")
        if not k.AssignProcessToJobObject(job, k.GetCurrentProcess()):
            raise OSError("could not attach decoder memory limit")
        # Keep the job handle until process exit.


def decode(data):
    from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
    from PyQt6.QtGui import QImage, QImageReader

    QImageReader.setAllocationLimit(16)           # MiB per Qt image allocation
    buf = QBuffer()
    buf.setData(QByteArray(data))
    buf.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buf)
    reader.setDecideFormatFromContent(True)
    if bytes(reader.format()) not in (b"png", b"jpeg", b"gif", b"webp"):
        raise ValueError("only PNG, JPEG, GIF and WebP overlays are supported")
    size = reader.size()
    w, h = size.width(), size.height()
    if not (0 < w <= MAX_SIDE and 0 < h <= MAX_SIDE):
        raise ValueError("overlay dimensions exceed 1024 pixels")
    count = reader.imageCount()
    if count > MAX_FRAMES or (count > 0 and count * w * h * 4 > MAX_BYTES):
        raise ValueError("overlay exceeds frame or decoded-byte limit")
    frames, delays = [], []
    while reader.canRead():
        if len(frames) >= MAX_FRAMES or (len(frames) + 1) * w * h * 4 > MAX_BYTES:
            raise ValueError("overlay exceeds frame or decoded-byte limit")
        image = reader.read()
        if image.isNull() or image.width() != w or image.height() != h:
            raise ValueError("invalid overlay frame")
        image = image.convertToFormat(QImage.Format.Format_RGBA8888)
        ptr = image.constBits()
        ptr.setsize(image.sizeInBytes())
        frames.append(bytes(ptr))
        ms = reader.nextImageDelay()
        delays.append((ms if ms > 10 else 100) / 1000.0)
        if not reader.supportsAnimation():
            break
    if not frames:
        raise ValueError("overlay has no readable frames")
    header = json.dumps({"width": w, "height": h, "delays": delays}).encode("ascii")
    out = sys.stdout.buffer
    out.write(struct.pack("!I", len(header)))
    out.write(header)
    for frame in frames:
        out.write(frame)


if __name__ == "__main__":
    try:
        limit_memory()
        source = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(source) > MAX_INPUT:
            raise ValueError("overlay input too large")
        decode(source)
    except Exception as exc:
        print(str(exc)[:300], file=sys.stderr)
        sys.exit(1)
