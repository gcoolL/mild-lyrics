"""The walls around a plugin's process, put up before its code is imported.

Linux: Landlock and seccomp, enforced by the kernel. Everywhere: Python
audit-hook guards, a second layer on Linux and the only one elsewhere --
code that breaks out of Python itself can get past them. See
docs/notes/mild-lyrics/plugins.md (2026-10-13, the sandbox).
"""

from __future__ import annotations

import os
import sys

# ------------------------------------------------------------------ Landlock
_FS = {  # right: first ABI with it
    "EXECUTE": (1 << 0, 1), "WRITE_FILE": (1 << 1, 1), "READ_FILE": (1 << 2, 1),
    "READ_DIR": (1 << 3, 1), "REMOVE_DIR": (1 << 4, 1), "REMOVE_FILE": (1 << 5, 1),
    "MAKE_CHAR": (1 << 6, 1), "MAKE_DIR": (1 << 7, 1), "MAKE_REG": (1 << 8, 1),
    "MAKE_SOCK": (1 << 9, 1), "MAKE_FIFO": (1 << 10, 1), "MAKE_BLOCK": (1 << 11, 1),
    "MAKE_SYM": (1 << 12, 1), "REFER": (1 << 13, 2), "TRUNCATE": (1 << 14, 3),
    "IOCTL_DEV": (1 << 15, 5),
}
_FILE_ONLY = ("EXECUTE", "WRITE_FILE", "READ_FILE", "TRUNCATE", "IOCTL_DEV")
_READ = ("READ_FILE", "READ_DIR")
_WRITE = _READ + ("WRITE_FILE", "REMOVE_DIR", "REMOVE_FILE", "MAKE_DIR",
                  "MAKE_REG", "REFER", "TRUNCATE")
_NET_BIND, _NET_CONNECT = 1 << 0, 1 << 1
_SCOPE_ABSTRACT_UNIX, _SCOPE_SIGNAL = 1 << 0, 1 << 1
_SYS_CREATE, _SYS_ADD, _SYS_RESTRICT = 444, 445, 446   # the same on every arch
_PR_SET_NO_NEW_PRIVS, _PR_SET_PDEATHSIG, _PR_SET_SECCOMP = 38, 1, 22


def _libc():
    import ctypes
    return ctypes, ctypes.CDLL(None, use_errno=True)


def landlock_abi() -> int:
    if not sys.platform.startswith("linux"):
        return 0
    try:
        ctypes, libc = _libc()
        abi = libc.syscall(_SYS_CREATE, None, ctypes.c_size_t(0), ctypes.c_uint32(1))
    except (OSError, AttributeError):
        return 0
    return max(0, abi)


def landlock(read: list[str], write: list[str], connect: list[int],
             bind: list[int]) -> int:
    """Restrict this process for good. Returns the ABI used; 0 if unsupported."""
    abi = landlock_abi()
    if abi < 1:
        return 0
    ctypes, libc = _libc()
    have = {k: bit for k, (bit, since) in _FS.items() if abi >= since}
    handled = sum(have.values())

    def rights(names, is_dir):
        return sum(have[n] for n in names if n in have and (is_dir or n in _FILE_ONLY))

    class Ruleset(ctypes.Structure):
        _fields_ = [("fs", ctypes.c_uint64), ("net", ctypes.c_uint64),
                    ("scoped", ctypes.c_uint64)]

    class PathBeneath(ctypes.Structure):
        _pack_ = 1
        _fields_ = [("allowed", ctypes.c_uint64), ("fd", ctypes.c_int32)]

    class NetPort(ctypes.Structure):
        _fields_ = [("allowed", ctypes.c_uint64), ("port", ctypes.c_uint64)]

    net = (_NET_BIND | _NET_CONNECT) if abi >= 4 else 0
    scoped = (_SCOPE_ABSTRACT_UNIX | _SCOPE_SIGNAL) if abi >= 6 else 0
    attr = Ruleset(handled, net, scoped)
    size = 8 if abi < 4 else 16 if abi < 6 else 24
    fd = libc.syscall(_SYS_CREATE, ctypes.byref(attr), ctypes.c_size_t(size),
                      ctypes.c_uint32(0))
    if fd < 0:
        raise OSError(ctypes.get_errno(), "landlock_create_ruleset")
    try:
        for paths, names in ((read, _READ), (write, _WRITE)):
            for path in paths:
                try:
                    pfd = os.open(path, os.O_PATH | os.O_CLOEXEC)
                except OSError:
                    continue                # not there: nothing to allow
                try:
                    is_dir = os.path.isdir(path)
                    rule = PathBeneath(rights(names, is_dir), pfd)
                    if libc.syscall(_SYS_ADD, fd, 1, ctypes.byref(rule), 0) != 0:
                        raise OSError(ctypes.get_errno(), f"landlock rule for {path}")
                finally:
                    os.close(pfd)
        if net:
            for allowed, ports in ((_NET_CONNECT, connect), (_NET_BIND, bind)):
                for port in ports:
                    rule = NetPort(allowed, port)
                    if libc.syscall(_SYS_ADD, fd, 2, ctypes.byref(rule), 0) != 0:
                        raise OSError(ctypes.get_errno(), f"landlock port {port}")
        if libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "no_new_privs")
        if libc.syscall(_SYS_RESTRICT, fd, 0) != 0:
            raise OSError(ctypes.get_errno(), "landlock_restrict_self")
    finally:
        os.close(fd)
    return abi


# ------------------------------------------------------------------- seccomp
# Syscalls refused outright, by architecture. socket() is filtered by its
# arguments instead: only AF_INET/AF_INET6 SOCK_STREAM gets through.
_DENY = {
    "x86_64": {"socket": 41, "execve": 59, "execveat": 322, "ptrace": 101,
               "process_vm_readv": 310, "process_vm_writev": 311, "bpf": 321,
               "perf_event_open": 298, "userfaultfd": 323, "keyctl": 250,
               "add_key": 248, "request_key": 249, "mount": 165, "umount2": 166,
               "pivot_root": 155, "chroot": 161, "unshare": 272, "setns": 308,
               "kexec_load": 246, "init_module": 175, "finit_module": 313,
               "delete_module": 176, "io_uring_setup": 425, "io_uring_enter": 426,
               "io_uring_register": 427, "tkill": 200, "rt_sigqueueinfo": 129,
               "rt_tgsigqueueinfo": 297, "pidfd_send_signal": 424, "pidfd_open": 434,
               "pidfd_getfd": 438, "kcmp": 312, "process_madvise": 440,
               "kill": 62, "tgkill": 234},
    "aarch64": {"socket": 198, "execve": 221, "execveat": 281, "ptrace": 117,
                "process_vm_readv": 270, "process_vm_writev": 271, "bpf": 280,
                "perf_event_open": 241, "userfaultfd": 282, "keyctl": 219,
                "add_key": 217, "request_key": 218, "mount": 40, "umount2": 39,
                "pivot_root": 41, "chroot": 51, "unshare": 97, "setns": 268,
                "kexec_load": 104, "init_module": 105, "finit_module": 273,
                "delete_module": 106, "io_uring_setup": 425, "io_uring_enter": 426,
                "io_uring_register": 427, "tkill": 130, "rt_sigqueueinfo": 138,
                "rt_tgsigqueueinfo": 240, "pidfd_send_signal": 424, "pidfd_open": 434,
                "pidfd_getfd": 438, "kcmp": 272, "process_madvise": 440,
                "kill": 129, "tgkill": 131},
}
_AUDIT_ARCH = {"x86_64": 0xC000003E, "aarch64": 0xC00000B7}


def seccomp() -> bool:
    """Install the syscall filter. False where the architecture is unknown."""
    import platform
    arch = platform.machine()
    table = _DENY.get(arch)
    if table is None or not sys.platform.startswith("linux"):
        return False
    ctypes, libc = _libc()
    LD, JEQ, JSET, RET, AND, K = 0x20, 0x15, 0x45, 0x06, 0x54, 0x00
    ALU = 0x04
    ALLOW, KILL = 0x7FFF0000, 0x80000000
    EPERM = 0x00050000 | 1
    prog = []

    def op(code, k, jt=0, jf=0):
        prog.append((code, jt, jf, k))
    op(LD, 4)                                       # arch
    op(JEQ | K, _AUDIT_ARCH[arch], 1, 0)
    op(RET, KILL)
    op(LD, 0)                                       # nr
    if arch == "x86_64":
        op(JSET | K, 0x40000000, 0, 1)              # x32 calls: refuse
        op(RET, EPERM)
    sock = table["socket"]
    me = os.getpid()
    for name in ("kill", "tgkill"):                 # signals: only to itself
        op(JEQ | K, table[name], 0, 4)
        op(LD, 16)                                  # args[0]: pid / tgid
        op(JEQ | K, me, 0, 1)
        op(RET, ALLOW)
        op(RET, EPERM)
        op(LD, 0)                                   # not this call: nr back in A
    denied = [nr for name, nr in table.items()
              if name not in ("socket", "kill", "tgkill")]
    op(JEQ | K, sock, 0, 8)                         # socket(): check its args
    op(LD, 16)                                      # args[0] low: domain
    op(JEQ | K, 2, 1, 0)                            # AF_INET
    op(JEQ | K, 10, 0, 4)                           # AF_INET6, else refuse
    op(LD, 24)                                      # args[1] low: type
    op(ALU | AND | K, 0xF)                          # without CLOEXEC/NONBLOCK
    op(JEQ | K, 1, 0, 1)                            # SOCK_STREAM
    op(RET, ALLOW)
    op(RET, EPERM)
    for k, nr in enumerate(denied):
        op(JEQ | K, nr, 0, 1)
        op(RET, EPERM)
    op(RET, ALLOW)

    class Filter(ctypes.Structure):
        _fields_ = [("code", ctypes.c_uint16), ("jt", ctypes.c_uint8),
                    ("jf", ctypes.c_uint8), ("k", ctypes.c_uint32)]

    class Prog(ctypes.Structure):
        _fields_ = [("len", ctypes.c_uint16), ("filter", ctypes.POINTER(Filter))]
    arr = (Filter * len(prog))(*[Filter(*p) for p in prog])
    fp = Prog(len(prog), arr)
    libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)
    if libc.prctl(_PR_SET_SECCOMP, 2, ctypes.byref(fp), 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "seccomp")
    return True


def die_with_parent() -> None:
    if sys.platform.startswith("linux"):
        import signal
        ctypes, libc = _libc()
        libc.prctl(_PR_SET_PDEATHSIG, int(signal.SIGKILL), 0, 0, 0)


def limits() -> None:
    try:
        import resource
    except ImportError:             # Windows
        resource = None
    if resource is None:
        return
    for what, cap in ((resource.RLIMIT_AS, 4 * 1024 ** 3),
                      (resource.RLIMIT_FSIZE, 256 * 1024 * 1024),
                      (resource.RLIMIT_NOFILE, 256), (resource.RLIMIT_CORE, 0)):
        try:
            soft, hard = resource.getrlimit(what)
            cap = cap if hard == resource.RLIM_INFINITY else min(cap, hard)
            resource.setrlimit(what, (cap, cap))
        except (ValueError, OSError):
            pass
    try:
        os.nice(10)                 # not on Windows: AttributeError
    except (OSError, AttributeError):
        pass


# -------------------------------------------------------------------- guards
def guards(read: list[str], write: list[str], plugin_dir: str, proxy_port: int,
           may_listen: bool) -> None:
    """The audit hook. Everything it decides with is captured here, as
    immutable values, so nothing a plugin can reach changes its answers."""
    realpath, isabs, join, sep = os.path.realpath, os.path.isabs, os.path.join, os.sep
    getcwd, fspath = os.getcwd, os.fspath
    reads = tuple(realpath(p) for p in read)
    writes = tuple(realpath(p) for p in write)
    native_from = (realpath(plugin_dir),) + writes
    perm = PermissionError
    ok_hosts = frozenset({"127.0.0.1", "::1", "localhost"})
    port = int(proxy_port)
    listen = bool(may_listen)
    wflags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
    native_ends = (".so", ".pyd", ".dll", ".dylib")
    refuse = frozenset((
        "subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn",
        "os.fork", "os.forkpty", "os.startfile", "pty.spawn", "os.kill", "os.killpg",
        "signal.pthread_kill", "_winapi.CreateProcess", "_winapi.CreateNamedPipe",
        "_winapi.OpenProcess", "_winapi.TerminateProcess", "code.__new__",
        "gc.get_objects", "gc.get_referrers", "gc.get_referents", "webbrowser.open",
        "ctypes.dlopen", "ctypes.dlsym", "ctypes.cdata", "ctypes.call_function",
        "ctypes.addressof", "ctypes.string_at", "ctypes.wstring_at", "ctypes.set_errno",
        "os.chroot", "os.mknod", "os.mkfifo", "sys.remote_exec",
        "socket.gethostbyname", "socket.gethostbyname_ex", "socket.gethostbyaddr",
        "socket.sethostname", "mmap.__new__"))
    one_path = frozenset(("os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.chown",
                          "os.truncate", "os.utime", "os.chflags", "os.lchflags",
                          "os.listxattr", "os.removexattr", "os.setxattr",
                          "shutil.rmtree", "shutil.chown", "os.scandir", "os.listdir"))
    two_paths = frozenset(("os.rename", "os.link", "os.symlink", "shutil.move"))
    copies = frozenset(("shutil.copyfile", "shutil.copymode", "shutil.copystat",
                        "shutil.copytree"))
    listing = frozenset(("os.scandir", "os.listdir"))

    def where(p):
        if isinstance(p, int) or p is None:
            return None
        p = fspath(p)
        if isinstance(p, bytes):
            p = p.decode("utf-8", "surrogateescape")
        return realpath(p if isabs(p) else join(getcwd(), p))

    def under(p, roots):
        return any(p == r or p.startswith(r + sep) for r in roots)

    def hook(event, args):
        if event in refuse or event.startswith(("winreg.", "ctypes.")):
            raise perm(f"plugins may not use {event}")
        if event == "open":
            path = where(args[0])
            if path is None:
                return
            mode, flags = args[1], args[2] or 0
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) \
                or bool(flags & wflags)
            if not under(path, writes) and (writing or not under(path, reads + writes)):
                raise perm(f"plugins may not {'write' if writing else 'read'} {path}")
        elif event in one_path:
            path = where(args[0]) if args else None
            if path is not None and not under(
                    path, writes + (reads if event in listing else ())):
                raise perm(f"plugins may not touch {path}")
        elif event in two_paths:
            for a in args[:2]:
                path = where(a)
                if path is not None and not under(path, writes):
                    raise perm(f"plugins may not touch {path}")
        elif event in copies:
            src, dst = (where(a) for a in args[:2])
            if src is not None and not under(src, reads + writes):
                raise perm(f"plugins may not read {src}")
            if dst is not None and not under(dst, writes):
                raise perm(f"plugins may not write {dst}")
        elif event == "import":
            origin = args[1] if len(args) > 1 else None
            if args[0] in ("ctypes", "_ctypes", "cffi", "_cffi_backend"):
                raise perm(f"plugins may not import {args[0]}")
            if isinstance(origin, str) and origin.endswith(native_ends) \
                    and under(realpath(origin), native_from):
                raise perm("plugins may not load native code they bring")
        elif event == "socket.__new__":
            family, kind = args[1], args[2]
            if family not in (2, 10, 23) or (kind & 0xF) != 1:
                raise perm("plugins may only open TCP connections")
        elif event in ("socket.connect", "socket.connect_ex"):
            addr = args[1]
            if not (isinstance(addr, tuple) and addr[0] in ok_hosts and addr[1] == port):
                raise perm("plugins reach the network only through Mild Lyrics")
        elif event == "socket.bind":
            addr = args[1]
            if not (listen and isinstance(addr, tuple) and addr[0] in ok_hosts):
                raise perm("plugins may not listen for connections here")
        elif event == "socket.getaddrinfo":
            if args[0] not in ok_hosts and args[0] is not None:
                raise perm("plugins reach the network only through Mild Lyrics")
        elif event == "object.__setattr__" and args[1] in (
                "__code__", "__globals__", "__closure__"):
            raise perm("plugins may not rewrite functions")

    sys.addaudithook(hook)


def python_paths() -> list[str]:
    """What this Python needs to read to run: its library and packages."""
    import sysconfig
    out = {sys.prefix, sys.base_prefix, sys.exec_prefix, sys.base_exec_prefix}
    out.update(v for k, v in sysconfig.get_paths().items()
               if k in ("stdlib", "platstdlib", "purelib", "platlib"))
    out.update(p for p in sys.path if p and os.path.isdir(p))
    # TLS needs the certificates; the time zone, its rules.
    out.update(("/etc/ssl", "/etc/ca-certificates", "/usr/share/ca-certificates",
                "/etc/pki", "/etc/localtime", "/usr/share/zoneinfo",
                "/usr/lib/locale", "/etc/os-release"))
    # Never a folder that holds the home or config folder ("/", "/home", a
    # PYTHONPATH pointing at ~): reading Python would then read everything.
    homes = {os.path.realpath(os.path.expanduser("~"))}
    for k in ("XDG_CONFIG_HOME", "APPDATA"):
        if os.environ.get(k):
            homes.add(os.path.realpath(os.environ[k]))
    keep = []
    for p in sorted(x for x in out if x and os.path.exists(x)):
        r = os.path.realpath(p)
        if any(h == r or h.startswith(r.rstrip(os.sep) + os.sep) for h in homes):
            continue
        keep.append(p)
    return keep
