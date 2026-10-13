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
  at launch and never retried (their choice, 2026-10-13); the switch rows'
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

- Asked to keep it inside Mild Lyrics (a system-styled window was a worry on
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

Asked to make plugins unable to "delete a random file, or do other sketchy
stuff", limited more than Mild Lyrics itself. Python can't fence code inside
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
  walks, ctypes, code objects and native code from the plugin's folders).
- **Network** goes through `plugin_proxy.py`: HTTPS CONNECT only, port 443
  only, only to the sites plugin.json lists, never to private, loopback or
  link-local addresses whatever a name resolves to; each plugin is known by
  a per-start token in its HTTPS_PROXY URL. Known gap: Landlock limits TCP by
  port, not address, so a plugin that gets past the Python guard could reach
  an outside server listening on the proxy's port number. A network
  namespace would close it.
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
