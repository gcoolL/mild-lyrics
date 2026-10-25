"""Stream links handed to Qt over loopback plain HTTP, fetched here and resumed
with a Range when cut short. Notes: docs/notes/mild-lyrics/home_page.md."""
from __future__ import annotations

import http.client
import http.server
import secrets
import threading
import urllib.error
import urllib.request

ON = True
RESUMES = 5                  # upstream reopenings per request before Qt is let see the drop
KEEP = 64                    # links remembered (a queue's worth; the oldest go first)
CHUNK = 1 << 16
LOG: list = [None]           # log(event, **fields): the local player's follow.log rows

_lock = threading.Lock()
_server: list = [None]
_links: dict[str, str] = {}  # token -> upstream link
_tokens: dict[str, str] = {}


def _note(event: str, **kw) -> None:
    try:
        if LOG[0] is not None:
            LOG[0](event, **kw)
    except Exception:                                    # noqa: BLE001
        pass


def _open(url: str, rng: str | None):
    headers = {"User-Agent": "Mozilla/5.0"}
    if rng:
        headers["Range"] = rng
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20)


def _span(r) -> tuple[int, int | None]:
    """(first byte, last byte or None) of an upstream answer's body."""
    cr = r.headers.get("Content-Range") or ""
    if r.status == 206 and cr.startswith("bytes ") and "-" in cr:
        a, _, rest = cr[6:].partition("-")
        try:
            return int(a), int(rest.partition("/")[0])
        except ValueError:
            return 0, None
    n = r.headers.get("Content-Length")
    return 0, (int(n) - 1 if n and n.isdigit() else None)


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_a) -> None:
        pass

    def do_HEAD(self) -> None:
        self._serve(False)

    def do_GET(self) -> None:
        self._serve(True)

    def _serve(self, body: bool) -> None:
        url = _links.get(self.path.rsplit("/", 1)[-1])
        if url is None:
            self.send_error(404)
            return
        try:
            r = _open(url, self.headers.get("Range"))
        except urllib.error.HTTPError as e:
            self.send_response(e.code)                  # a stale link: Qt errors and the player fetches anew
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        except Exception:                                # noqa: BLE001
            self.send_error(502)
            return
        try:
            self.send_response(r.status)
            for h in ("Content-Type", "Content-Length", "Content-Range", "Last-Modified"):
                if r.headers.get(h):
                    self.send_header(h, r.headers[h])
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            if body:
                self._pipe(r, url)
        finally:
            r.close()
        self.close_connection = True

    def _pipe(self, r, url: str) -> None:
        pos, end = _span(r)
        resumes = 0
        while True:
            try:
                chunk = r.read(CHUNK)
            except (OSError, http.client.HTTPException):
                chunk = b""
            if chunk:
                try:
                    self.wfile.write(chunk)
                except OSError:
                    return                              # Qt let go: a seek, a stop, another song
                pos += len(chunk)
                continue
            if end is None or pos > end:
                return
            resumes += 1
            _note("relay-resume", at=pos, of=end + 1, n=resumes)
            if resumes > RESUMES:
                return
            r.close()
            try:
                r = _open(url, f"bytes={pos}-{end}")
            except Exception as e:                       # noqa: BLE001
                _note("relay-resume-failed", at=pos, err=repr(e)[:160])
                return
            if r.status != 206 or _span(r)[0] != pos:
                _note("relay-resume-failed", at=pos, err=f"status {r.status}")
                r.close()
                return


def _port() -> int:
    with _lock:
        if _server[0] is None:
            try:
                s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
            except OSError as e:
                _note("relay-off", err=repr(e)[:160])
                return 0
            s.daemon_threads = True
            threading.Thread(target=s.serve_forever, name="stream-relay", daemon=True).start()
            _server[0] = s
        return _server[0].server_address[1]


def wrap(url: str) -> str:
    """The link Qt is given for `url`: through the relay when it is on, `url` itself otherwise."""
    if not ON or not url.startswith("https://"):
        return url
    port = _port()
    if not port:
        return url
    with _lock:
        tok = _tokens.get(url)
        if tok is None:
            tok = secrets.token_hex(8)
            _tokens[url], _links[tok] = tok, url
            while len(_links) > KEEP:
                old = next(iter(_links))
                _tokens.pop(_links.pop(old), None)
    return f"http://127.0.0.1:{port}/s/{tok}"


def unwrap(url: str) -> str:
    """The upstream link behind a relayed one (anything else unchanged)."""
    if url.startswith("http://127.0.0.1:") and "/s/" in url:
        return _links.get(url.rsplit("/", 1)[-1], url)
    return url
