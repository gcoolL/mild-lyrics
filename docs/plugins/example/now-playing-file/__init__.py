"""Now playing file: the song and the sung line, kept in two text files."""

import pathlib
import queue
import threading

_api = None
_jobs: queue.Queue = queue.Queue()
_last = {}
_wrote = ""


def _folder() -> pathlib.Path:
    return _api.data_folder                 # the one folder a plugin may write


def _song(now: dict) -> str:
    if not now.get("tid"):
        return ""
    title, artist = now["shown_title"], now["shown_artist"]
    return {"title - artist": f"{title} - {artist}",
            "title": title}.get(_api["format"], f"{artist} - {title}")


def _writer():
    """The disk work, off the GUI thread. None stops it."""
    global _wrote
    while (job := _jobs.get()) is not None:
        name, text = job
        try:
            folder = _folder()
            folder.mkdir(parents=True, exist_ok=True)
            tmp = folder / f".{name}.tmp"
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(folder / name)
            _wrote = name
        except OSError as e:
            _api.log(f"could not write {name}: {e}")


def _tick(now: dict):
    for name, text in (("song.txt", _song(now)), ("line.txt", now.get("line", ""))):
        if _last.get(name) != text:
            _last[name] = text
            _jobs.put((name, text))


def start(api):
    global _api
    _api = api
    _last.clear()
    threading.Thread(target=_writer, daemon=True, name="now-playing-file").start()
    api.every(0.2, _tick)
    api.status(lambda: f"writing to {_folder()}" if _wrote else "")
    api.on_change(lambda key, value: _last.clear())   # rewrite both


def stop():
    _jobs.put(None)
