# plugins.py

## 2026-10-12 — host fixes

- **Reinstall swaps by rename.** The old folder is renamed to `.<id>.old`, the
  new one renamed in, then the old one deleted. Deleting first could leave half
  a plugin when Windows held a file open (a loaded `.pyd` in `lib/`); a rename
  of a folder with an open file fails whole instead. The running copy is
  stopped first and marked `stale` ("updated · restart Mild Lyrics"): its
  module stays cached, and restarting it would run the old code against the
  new files. If the swap fails, the old copy is started again.
- **Failures are counted per hook.** One shared counter was reset by any
  success, so `status()` (polled by the drawer four times a second) kept a
  tick hook that raised every time from ever failing out.
- **Thread hops.** `api.set` stores and saves at once (under a lock) but runs
  `on_change` listeners at the GUI thread's next tick; `api.toast` from a
  thread waits for the tick too. Asks from a stopped plugin are dropped.
- **`lib/` clashes.** `lib/` is appended to `sys.path`, so any name already
  importable wins. A lib module hidden by one of Mild Lyrics' own modules fails
  `start()` with that reason (the plugin would get the app's module); one
  hidden by the stdlib, site-packages or another plugin's lib is logged.

## 2026-10-12 — marketplace (plugin_store.py)

- The listing and zips live in the Worker's ART namespace under `plugins/`,
  written only by `docs/discord-cover-worker/publish.py` (wrangler); the
  Worker serves them read-only. An entry is accepted only if its `zip` is
  exactly `plugins/<id>/<version>.zip`, and a download only if its size and
  sha256 are the entry's -- this guards the transfer, not a compromised
  Cloudflare account (that would need a signed index).
- The listing is looked at only when Browse opens (or "Look again"), never
  at launch and never retried (decided 2026-10-13); the switch rows'
  "x.y in Browse plugins" appears once it has been.
- An update reloads in place when the settings and name are unchanged and
  there is no `lib/`; otherwise the plugin waits for a restart (`stale`),
  since the menu is built once at start. A new plugin always needs a restart.

## 2026-10-13 — submissions from other people

- `POST /plugins/submit` stores a zip under `submissions/<id>.zip` in ART
  (not under `plugins/`, so the read route can never serve one), with
  `{id, version, size, at}` as KV metadata for `publish.py --pending`. Limits:
  5 MB, 50 waiting, 3 an hour per address (a sha256 of it, kept an hour, two
  KV writes a submission); unreviewed ones expire after 30 days. KV's counts
  are eventually consistent, so the queue cap is the hard limit.
- `publish.py --fetch` unpacks into `~/.cache/mild-lyrics-review/<id>/`
  through `plugins._unpacked` (traversal check) after a 50 MB unpacked-size
  check, and never imports it; `--approve` refuses until that folder exists.
- `plugins.pack()` is the one zip maker (app submit and publish.py), so a
  folder always packs to the same bytes.
- The guide for authors is `docs/plugins/README.md`; the Browse window links
  to it on GitHub's main branch.

## 2026-10-13 — download counts, the Browse list, uninstall

- Counts live in a Durable Object, not KV: KV's free plan allows 1,000 writes
  a day and has no atomic increment, so two downloads at once would lose one.
  One SQLite row per plugin, plus `seen` rows (hashed address|plugin, day)
  deleted when the day turns, for once-a-day-per-address counting.
- The Browse window is plain Qt in the system palette, like the app's other
  dialogs: search (every word, any field), sort (downloads, recent, name),
  All / Installed / Updates, cards with an initials tile coloured from the
  id. Installed plugins the listing doesn't have show as "Not in the
  marketplace", so they can be uninstalled from there too.
- `plugins.uninstall()` renames the code aside and deletes it (the same
  in-use rule as install) and keeps `plugin-data/`; the plugin is marked
  `removed` so its rows say so and it won't start until a restart.
- Offscreen grabs of the window need `processEvents()` first: cards added
  after a `clear()` are not laid out until the loop runs.

## 2026-10-13 — the marketplace moved into the drawer

- Kept inside Mild Lyrics (a system-styled window was a worry on
  Windows). In the new interface it is the drawer's fourth tab, "Plugins"
  (`market_tab.MarketTab`, held as `view.market`), drawn with the drawer's
  own helpers; its hits are `("mk", ...)` and lyrics_gui only dispatches
  paint, `_dr_said`, presses, wheel and keys to it. Questions go through
  `view.ask` and errors become toasts (`plugin_store.ask` / `tell`). The
  classic interface keeps the Qt window, as it keeps system dialogues
  everywhere else.
- `MarketTab.said()` is what the drawer's picture cache watches on this tab:
  the listing's identity, downloads in flight, notes, every plugin's
  version/removed/stale, and the caret's blink while searching.

## 2026-10-13 — the sandbox

Goal: plugins that cannot delete arbitrary files or do anything else
unexpected, limited more than Mild Lyrics itself. Python can't fence code inside
its own process, so each switched-on plugin now runs in its own process
(`plugin_runner.py`), walled in before its code is imported
(`plugin_sandbox.py`):

- **Linux, kernel-enforced.** Landlock (ABI 10 on the dev machine): read
  Python's libraries, the app's module folder and the plugin's folder; read
  and write only its data folder and granted folders; no execute right; TCP
  connect only to the proxy's port, bind only to port 0 with `listen`;
  signals and abstract Unix sockets scoped (ABI 6+). seccomp: socket() only
  for AF_INET/AF_INET6 SOCK_STREAM (no UDP, raw, netlink or Unix sockets),
  no execve, io_uring, ptrace, bpf, mounts, namespaces, keyrings, pidfd
  tricks, and kill/tgkill only to itself. Also PDEATHSIG, rlimits (4 GiB
  address space, 256 MB files, 256 fds), nice 10.
- **Everywhere, Python audit-hook guards** with the same rules; on Windows
  and macOS the only layer, so a plugin runs there only after the person
  allows it with that said (`_unguarded`). Bypassable by code that gets out
  of Python (the hook keeps its rules in closure values, refuses gc object
  walks, ctypes and code objects).
  Native code: loading an extension raises no audit event (the `import`
  event's filename is always None, so an origin check there never fires).
  `_imp.create_dynamic`/`create_builtin` are swapped for wrappers that raise
  `mild.native`; the hook alone holds the originals and loads only from the
  stdlib's own extension folder (DESTSHARED, `DLLs`, the embeddable root).
  Without this, any package with compiled parts (PyQt6's
  `QProcess.startDetached`) ran programs past the guards on Windows. Also
  refused by name: a fresh `_imp` (it would carry the unwrapped loaders) and
  the sub-interpreter modules (a sub-interpreter starts with no audit hook
  at all; `cpython.PyInterpreterState_New` does not fire for them).
  Windows: `_winapi.CreateFile` is path-checked like `open` (read-only
  rights + OPEN_EXISTING may read; anything else needs a write grant); every
  other `_winapi` call and `msvcrt.open_osfhandle` is refused. Known gap:
  `_overlapped` (asyncio's Windows loop needs it) can connect named pipes.
  A manifest's `"on"` is ignored: a dropped-in plugin starts switched off.
  It also refuses opening a directory the plugin may not write: the `open`
  event carries no `dir_fd`, so otherwise `os.open(name, O_WRONLY, dir_fd=…)`
  against a read-only grant would be checked against the cwd, not the real
  target, and write into a read-only folder (Landlock blocks this on Linux;
  the guard is the only wall on Windows/macOS). Plugins use scandir/listdir.
- **Network** goes through `plugin_proxy.py`: HTTPS CONNECT only, port 443
  only, only to the sites plugin.json lists, never to private, loopback or
  link-local addresses whatever a name resolves to; each plugin is known by
  a per-start token in its HTTPS_PROXY URL. (The gap this left -- Landlock
  limits TCP by port, not address -- is closed by the network namespace,
  below.)
- **Permissions** (`network`, `player`, `spotify`, `listen`, `folders`) are
  declared in plugin.json, shown before install and switch-on, and kept as
  `_granted`; an update asking for more doesn't start until allowed. The
  host enforces player/spotify on its side too (forged pipe messages are
  refused). Folder grants never cover home, the config folder or anything
  above them, or Mild Lyrics' own; a write grant's folder is created only
  once the owning app's folder exists.
- Messages are JSON lines; the host never blocks on a plugin (reader and
  writer threads, bounded queue, playback dropped first). Status is pushed
  by the plugin, so the drawer never calls into one.

## 2026-10-13 — a network namespace per plugin

The network gap, closed. A Linux plugin with `network` now runs in a
user+network namespace of its own (`plugin_sandbox.netns`: unshare, then
`lo` up by ioctl, single-threaded, before Landlock and seccomp), where
nothing is routed. The runner's `Bridge` listens on that loopback (its port
goes into HTTPS_PROXY) and, for each connection, sends "c" over an AF_UNIX
socketpair the host handed it; the host (`Plugin._bridge`) connects to the
proxy from outside and passes the socket back by SCM_RIGHTS. The proxy
still decides the site. Verified with the Python guard off: an outside
address on the allowed port gives "Network is unreachable". Where
namespaces are refused (unprivileged user namespaces off, or AppArmor's
restriction on recent Ubuntu) it falls back to the port limit and logs it.

`listen` is now a socket the host opens on 127.0.0.1 and hands in
(`api.listener()`, API 3), so Landlock grants no bind at all; a plugin
listening inside its namespace would be unreachable anyway. Mildify link
1.2.0 uses it, falling back to its own socket on an older Mild Lyrics.

## 2026-11-01 — renderers of their own (API 4)

A renderer cannot run in a plugin's process: it paints every frame, and
nothing here waits on a plugin. So a plugin hands over the whole song once,
as a scene of timed pages (`api.renderer(name, scene)`), and the window
draws it with the clock: `plugin_scene.check` validates and caps it on the
GUI thread (pages, lines, fragments, finite times, `#rrggbb[aa]` colours,
weights in hundreds), and `renderers.PluginScene` wraps each line with the
window's own `wrap_pieces`, shrinks a page that would not fit, and wipes
each fragment hard-edged from ink to sung. A line given as `text` with
`start`/`end` wipes across all its rows by advance (no syllable times are
made up), and untimed text is split into words so it never wraps inside one.

Names come from plugin.json `renderers` and join `RENDER_MODES` in place
right after `PL.load`, before the menu is built, so they appear from the next
start like declared settings do; a name a built-in has is dropped. A scene
is drawn only while its `tid` is the clock's track; otherwise (plugin off,
or not caught up) the karaoke renderer stands in. Click-to-seek maps a
scene line to the window's line starting nearest it (within 0.3s).

Exact rows per page need the wrapping, which only the window has (it
depends on the window's width and the lyric size). So a scene can also
carry a `flow`: lines the window wraps, then pages by rows, `rows` a page,
a new one after a `break`-second gap, `lead` early after a break, the next
taking over at overlapping vocals, a line longer than a page carried on
(its whole-line wipe continuing by advance). Pages are rebuilt per size,
cached on (scene, width, height, lyric size, face), and pages without a
`to` last until the next comes up, so a title card can end where the
first flowed page begins without the plugin knowing when that is.

The first users are the old-karaoke plugin (the karaoke-video look, kept
out of the built-ins) and a scene-test plugin that shows every feature.
Lyrics documents seldom carry `"Type": "Vocal"` on their lines, and a
syllable document can hold a line with no `Lead`; plugins reading
`api.lyrics()` must allow both.

## 2026-11-02 — players from plugins (API 6)

A player Mild Lyrics cannot see well (MusicBee: its own plugin API gives
exact positions, the file and the cover) reaches the window through a plugin:
`api.player(reading)` with the `media` permission. The reader thread stamps
each `player` message on arrival (`_at`), since the GUI tick that handles it
can be 100ms later; `player_spec` checks it; `players()` lists the ones
heard from in the last `PLAYER_STALE` (5s) as `plugin:<id>`.

They join the platform transports rather than being a transport of their
own: `SessionTransport.__init_subclass__` wraps each subclass's
`_sessions`, `_read_one`, `_app_of`, `_rank`, `seek`, `command` and
`set_volume`, so SMTC, MPRIS and macOS all list them first, read them, pin
them and pass them buttons with no change to the following logic. Rank 1:
above every player but Spotify, so a plugin player outranks the same app's
own SMTC session. Listed only with Any media player on, or when pinned,
like any other non-Spotify player. Pos runs from the arrival stamp, so
plugins send on change plus a 2s beat.

The first user is the MusicBee plugin (~/musicbee-plugin): a C# MusicBee
plugin `mb_MildLyrics.dll` connects to `api.listener()`'s port, which the
Python side writes with a token to `<MusicBee data>/MildLyrics/link.json`.
The DLL makes that folder itself, so the Store Python on Windows writes into
an existing folder in place, not into its redirected copy.

Later the same day, from the first live run on Windows:

- **No vetting for plugin players.** With Any media player on, a non-Spotify
  player's new track waits in `pending` until a provider has words for it
  (kept for browser tabs). A plugin player's skip was held there: the old
  song read as paused, and after HOME_AFTER BackupTransport handed back to
  Spotify (`transport-switch … stopped: true`), never to return for a song
  no source knew. `_worth` now passes `plugin:` readings straight through.
- **`any_player` in the playback dict.** The plugin guessed the setting
  from six seconds of not being followed, and so blamed it while a song
  was only being vetted. It now reads it.
- **Identify songs for plugin players.** A reading with `identify` and a
  `file:` url is run through its own `local_identify.Identifier`
  (`PLAYER_IDENT`, `player-ids.json`, so the library's answers file has one
  writer), keyed by path and mtime. As with local files, the track has no
  id for up to `LocalPlayer.IDENT_WAIT` while the answer is pending, so the
  lyrics are not fetched for the tags and then again for the song; a
  picture the player gave stays over Deezer's cover.

## Lift — 2026-10-25

Docstrings shortened in `mild-lyrics/plugins.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> Plugins: code somebody installs after the app, into its config folder.
>
> A plugin is a folder under <config>/plugins/ with a plugin.json (what it is,
> its settings, its permissions) and an __init__.py with start(api) and
> optionally stop(). docs/plugins/README.md is the guide for writing one.
>
> Each switched-on plugin runs in a process of its own (plugin_runner), walled
> in by plugin_sandbox before its code loads: it reads its own folder, writes
> its own data folder, reaches only the sites it lists through plugin_proxy,
> and gets what else it asks for in "permissions" once it has been allowed.
> Messages both ways are JSON lines; nothing here waits on a plugin.
