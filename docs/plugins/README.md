# Writing a Mild Lyrics plugin

A plugin is a folder of Python that Mild Lyrics runs alongside the lyrics
window. It can follow what is playing, read the lyrics, drive the player, and
show its own settings in the drawer. Anyone can write one, try it locally, and
submit it to the marketplace, where everyone can install it from the **Plugins** tab of
the settings drawer.

Each plugin runs in a process of its own, walled in: it reads its own
folder, writes its own data folder, and reaches only what its plugin.json
asks for and the person installing it allows. On Linux the system itself
enforces that; elsewhere Python-level checks do, and people are told so
before the plugin runs. The marketplace also lists only plugins that have
been read and approved.

- [The folder](#the-folder)
- [plugin.json](#pluginjson)
- [Permissions](#permissions)
- [The walls](#the-walls)
- [The code](#the-code)
- [The api](#the-api)
- [Good habits](#good-habits)
- [Trying it](#trying-it)
- [Submitting it](#submitting-it)
- [Updating it](#updating-it)

A complete, small example is in [`example/now-playing-file`](example/now-playing-file):
it writes the song and the line being sung to text files for a stream overlay.

## The folder

    my-plugin/
      plugin.json      what it is, and its settings
      __init__.py      start(api) and stop()
      helper.py        anything else it imports, as `from . import helper`
      lib/             optional: third-party packages it bundles

Installed plugins live in Mild Lyrics' config folder, under `plugins/<id>/`;
**Settings → Plugins → Plugins folder** opens it. A plugin's own settings are
kept apart from its code, in `plugin-data/<id>/settings.json`, so updating a
plugin keeps them.

## plugin.json

```json
{
  "id": "now-playing-file",
  "name": "Now playing file",
  "version": "1.0.0",
  "api": 1,
  "author": "Your name",
  "homepage": "https://github.com/you/now-playing-file",
  "description": "One line, shown in the marketplace and beside the switch.",
  "settings": [
    {"heading": "Files"},
    {"key": "folder", "label": "Folder", "kind": "text", "default": "",
     "hint": "shown in the text box while it is edited"},
    {"key": "format", "label": "Song as", "kind": "choice",
     "choices": ["artist - title", "title"], "default": "artist - title"},
    {"key": "delay", "label": "Delay", "kind": "num",
     "min": -5000, "max": 5000, "step": 10, "format": "{:+.0f} ms", "default": 0},
    {"key": "token", "label": "Token", "kind": "secret", "default": ""},
    {"key": "enabled_extra", "label": "Extra", "kind": "bool", "default": false},
    {"key": "open", "label": "Folder", "kind": "action", "verb": "Open"}
  ]
}
```

| Field | |
|---|---|
| `id` | Lower-case letters, digits, `-` and `_`; at most 48. It is the folder's name once installed, and it cannot change later. |
| `name` | What the drawer and the marketplace call it. |
| `version` | Digits, letters, `.`, `+`, `-`. Compared as dotted numbers, so `1.10.0` is newer than `1.9.2`. |
| `api` | The plugin API it is written against: `1`, or `2` for `control`, `spotify` and `lyrics`. A Mild Lyrics too old for it says so instead of loading it. |
| `author`, `homepage` | Optional; shown in the marketplace. `homepage` must be `https://`. |
| `description` | One line. |
| `note` | Optional. A few lines shown under the plugin's tab title, above its rows: what its fields take, say. |
| `settings` | Rows in the plugin's own drawer tab, in this order. Optional. |
| `permissions` | What it needs beyond its own folder; see [Permissions](#permissions). Optional. |

Settings are declared here, not created from code, so the drawer can show a
plugin and its switch without running any of it. Each row is a heading
(`{"heading": "…"}`) or a setting with a `key`, a `label` and a `kind`:

| Kind | Holds | Needs |
|---|---|---|
| `bool` | `true` / `false` | |
| `choice` | one of `choices` | `choices` |
| `num` | a number, clamped to its range | `min`, `max`, `step`; optional `format` |
| `text` | a string | optional `hint` |
| `secret` | a string, kept in the settings file only | optional `hint` |
| `action` | nothing: a button | optional `verb` (the button's word) |

`default` is optional for every kind. A plugin is installed switched off.

## Permissions

Anything beyond its own folder and settings is asked for in `plugin.json`,
shown before it is installed or switched on, and asked again if an update
asks for more.

```json
"permissions": {
  "network": ["api.example.com", "*.cdn.example.com"],
  "player": true,
  "spotify": true,
  "listen": true,
  "folders": [
    {"path": "config:other-app", "access": "read", "setting": "folder"},
    {"path": "config:other-app/extensions/mine", "access": "write",
     "setting": "folder", "within": "extensions/mine"}
  ]
}
```

| Permission | Lets it |
|---|---|
| `network` | Make HTTPS requests to these sites, and no others. `*.example.com` is its subdomains. There is no "anywhere". |
| `player` | `api.control`: play, pause, skip, seek, volume, open. |
| `spotify` | `api.spotify`: run JavaScript in Spotify's app, which can do anything the person's account can. Ask only if you truly need it. |
| `listen` | Accept connections from other apps on this computer (a server on 127.0.0.1). |
| `folders` | Read, or read and write, a folder outside its own: `config:<name>` (the system's config folder, `~/.config` on Linux, `%APPDATA%` on Windows) or `home:<name>`. With `setting`, a text setting the person may fill instead (then `within` is the part below it). Never the home or config folder itself, and never Mild Lyrics' own. |

## The walls

A plugin's process can:

- read its own folder and Python's libraries, and read and write its data
  folder (`api.data_folder`, which is also its working directory and temp
  folder);
- make HTTPS requests to its listed sites. `requests`, `urllib` and most
  libraries go through Mild Lyrics' proxy on their own (it is in
  `HTTPS_PROXY`); there is no direct network and no DNS;
- start threads.

It cannot read or change any other file, run programs, signal or attach to
other processes, open UDP, raw or Unix sockets, or load native code it
brings with it. Something it is refused raises `PermissionError`.

## The code

`__init__.py` needs a `start(api)`. A `stop()` is optional.

```python
_api = None
_last = ""

def start(api):
    global _api, _last
    _api, _last = api, ""
    api.every(0.25, tick)
    api.status(lambda: _last)

def tick(now):
    global _last
    if now["playing"] and now["title"] != _last:
        _last = now["title"]
        _api.log("now playing", now["title"], "at", round(now["pos"]), "s")

def stop():
    ...   # end your threads, close your sockets
```

`start` is called when the plugin is switched on (or the app starts with it
on). `stop` is called when it is switched off or the app quits. Switched on
again, `start` is called again on the same module, so reset module state
inside `start`.

If `start` raises, or one hook raises three times in a row, the plugin is
stopped and its switch says `failed · <the error>`. Everything is logged
to the terminal with the plugin's id; run Mild Lyrics from a terminal while
you work on one.

## The api

`start` is handed an `api` object. These are everything it has.

### Settings

| | |
|---|---|
| `api.get(key)` / `api[key]` | A setting's value. |
| `api.set(key, value)` | Change one: saved, and the drawer shows it. |
| `api.reset()` | Every setting back to its default. |
| `api.on_change(fn)` | `fn(key, value)` after any of its settings changes. |
| `api.on_action(key, fn)` | `fn()` when the action row `key` is pressed. |

### What is playing

`api.every(seconds, fn)` calls `fn(now)` every `seconds` (0.1 at the
finest); `api.playback()` returns the same dict whenever asked.

| Key | |
|---|---|
| `tid` | The player's id for the track; `''` when nothing is playing. |
| `title`, `artist`, `album` | As the player gave them. |
| `shown_title`, `shown_artist` | As the window shows them: a guest credit moved from the title to the artists. |
| `art` | The cover's URL. |
| `spotify` | The Spotify track id, or `''`. |
| `spotify_match` | The Spotify track another player's song was matched to, if it has been. |
| `player` | Which player is followed: `'spotify'`, `'mpris:…'`, … |
| `status`, `playing` | `'Playing'`, `'Paused'`, `'Stopped'` or `'Error'`; and a bool. |
| `pos`, `length` | Seconds into the song as the lyrics are drawn, and its length (0.0 when unknown). |
| `volume` | 0.0–1.0, or `None`. |
| `line`, `next` | The line being sung (`''` between lines), and the one after. |

### Lyrics (API 2)

`api.lyrics()` returns the playing song's lyrics, or `None` when nothing is
playing:

| Key | |
|---|---|
| `tid` | The track they are for. |
| `state` | `'ready'`, `'pending'` (still being looked for) or `'none'`. |
| `doc` | The lyrics in Spicy Lyrics' shape (`{"Type": …, "Content": …}`), times in seconds; `None` unless ready. Don't change it. |
| `source` | Where they came from, as the window credits it. |
| `makers`, `uploaders` | Who made the sync: `[{"name", "url"}]`. |
| `offset` | Seconds the window draws them later by. |

Call it from a hook (`every`, `on_change`, …), not from your own thread.

### Driving the player (API 2)

Both need their [permission](#permissions); without it they raise
`PermissionError`.

`api.control(name, value=None)`: `PlayPause`, `Next`, `Previous`,
`seek` (seconds), `volume` (0.0–1.0), `open` (a `spotify:` URI, or a
`(context URI, track URI)` pair; Spotify's own app only). It takes effect at
the next plugin tick, the same way the window's own keys do.

`api.spotify(js)` evaluates JavaScript in Spotify's desktop app over the
connection Mild Lyrics reads it through, and returns the result. It blocks,
so call it from a thread of your own. It raises `ConnectionError` when there
is no Spotify page to ask.

### Everything else

| | |
|---|---|
| `api.status(fn)` | `fn()` returns a few words shown beside the switch: `on · <words>`. |
| `api.toast(text)` | A short message in the window, as `<name>: text`. |
| `api.log(*bits)` | A line in the terminal's log, under the plugin's id. |
| `api.id`, `api.version` | The plugin's id, and the plugin API version of this Mild Lyrics. |
| `api.folder` | The plugin's own installed folder (read-only in spirit: an update replaces it). |
| `api.data_folder` | A folder for its own files, kept across updates. |

## Good habits

Hooks run one at a time on the plugin's own main thread, so a slow one holds
up the plugin's next hooks (never the window).

- **Network and slow disk work go on a thread of your own**, never in a hook.
  The example's `_writer` thread is the pattern: hooks put jobs on a queue.
- `api.control`, `api.toast`, `api.set` and `api.spotify` are safe from any
  thread.
- End your threads in `stop()`. A daemon thread is fine for the app quitting,
  but switching the plugin off and on should not leave two running.
- Don't retry a failing service in a tight loop; back off, and say what is
  wrong through `api.status`.

### Bundling packages

Put pure-Python packages in `lib/` (`pip install --target lib <package>`);
native code a plugin brings is refused by the walls. Mild Lyrics adds `lib/`
to the end of Python's import path, so a package the app already has is used
instead of the bundled one, and the log says so. A module in `lib/` with the
same name as one of Mild Lyrics' own stops the plugin from starting.

## Trying it

**Settings → Plugins → Install a plugin** and pick your folder's
`plugin.json` (or a `.zip` of the folder); its permissions are shown first.
Restart Mild Lyrics, find the plugin's tab, and switch it on. To try a
change, install again: if its settings did not change, it restarts at once
on the new files; otherwise restart Mild Lyrics.

## Submitting it

**Settings → Plugins → Submit a plugin**, and pick its `plugin.json`. Mild
Lyrics checks it the same way it checks an install, zips the folder (without
`__pycache__`, `.git` or `tests`), shows what will be sent, and sends it for
review. Before you send it:

- **Nothing of yours may be in the folder**: keys, tokens, your settings,
  your paths. Settings belong in `settings` with an empty default; files the
  plugin makes belong in `api.data_folder`. Files whose names look private
  are pointed out before anything is sent.
- `description` says plainly what it does, and what it sends where.
- Bump `version` for every submission of an already-listed plugin.

Without the app, the same submission is one request:

    cd my-plugin/.. && zip -r my-plugin.zip my-plugin -x '*/__pycache__/*'
    curl --data-binary @my-plugin.zip -H 'Content-Type: application/zip' \
         -H 'X-Plugin: my-plugin 1.0.0' \
         https://raspy-snowflake-c23c.gcoolltm.workers.dev/plugins/submit

At most 5 MB, three submissions an hour. The answer names the submission.

### What review looks at

Every submission is read before it is listed: the code, every address it
talks to, what it reads and writes, and what changed since the version
already listed. It is turned down if it:

- sends anything anywhere its description does not say;
- reads files, keys or sessions it does not need for what it says it does;
- ships native code (`.so`, `.pyd`, `.dll`, `.exe`) that cannot be read, or
  code it downloads and runs later;
- is an update to somebody else's plugin;
- is unreadable on purpose (obfuscated, minified, packed).

A submission nobody has acted on is forgotten after 30 days. Nothing about
the submitter is kept: the Worker counts uploads by a hash of the address,
for an hour.

## In the marketplace

Browse shows each plugin's downloads, size, author and the date its version
was published, and can be searched, sorted by downloads, recency or name,
and narrowed to what is installed or has an update. A download counts once a
day per address, so updating or reinstalling does not inflate it.

## Updating it

Change `version` in `plugin.json` and submit again. Once approved, anyone who
has it installed sees `<version> in Browse plugins` beside its switch the
next time they open Browse, and updates from there. A published version is
never replaced, so every change needs a new version.
