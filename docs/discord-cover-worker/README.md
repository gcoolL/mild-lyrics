# Mild Lyrics' Worker

One Cloudflare Worker, on the free plan with a free `*.workers.dev` address
(no domain, no card), with these jobs:

- **Animated covers for Discord.** Discord shows a Rich Presence cover by
  fetching a public URL from its own servers, so an animated cover has to
  live somewhere public. Mild Lyrics turns Apple's animated cover into a
  small GIF and puts it here once per album; every Mild Lyrics card for that
  album then points at the same file. Kept in Workers KV.
- **The TTML Editor's multiplayer relay.** Every editor in a session talks to
  a room here instead of to each other, so nobody learns anybody's IP
  address, and joining takes only the invite. The editors' traffic is QUIC,
  encrypted end to end, so the room carries bytes it cannot read. Rooms are
  Durable Objects.

- **The player's listen along.** One person shares what they play; anyone
  with the invite follows it in their own Spotify. A `Listen` Durable Object
  passes the sharer's state (encrypted, a few messages a song) to the
  listeners, who send nothing. See `docs/notes/mild-lyrics/listen_along.md`.

- **The plugin marketplace.** What the player's *Browse plugins* lists, and
  the plugins' zips, kept in the same KV namespace. Anyone can submit a
  plugin; only `publish.py`, with your wrangler login, lists one.

- **The shared splitting dictionary.** How words are cut into syllables, one
  list per language, that anyone can add to from the TTML Editor's Splits
  tab. A `Splits` Durable Object per language. Entries can be locked by the
  owner: set the secret once with `npx wrangler secret put SPLITS_OWNER` and
  type the same text into the Splits tab. See
  `docs/notes/editor/shared_splits.md`.

## Setting it up

The first time, in the dashboard (steps 1–5). Since the multiplayer rooms,
the Worker is deployed from this folder with wrangler instead -- see
[Deploying with wrangler](#deploying-with-wrangler) -- because the rooms
need a Durable Object migration the dashboard's editor cannot make.

1. **Make the Worker.** In the Cloudflare dashboard, open **Workers & Pages**
   → **Create** → **Create Worker**. Keep the "Hello World" starter, name it
   (for example `mild-lyrics-covers`) and **Deploy**.
2. **Put the code in.** Open the Worker → **Edit code**, replace everything
   with the contents of [`worker.js`](worker.js), and **Deploy**.
3. **Make the storage.** In the sidebar, **Storage & Databases** → **Workers
   KV** → **Create** a namespace (for example `mild-lyrics-covers`).
4. **Bind it.** Back in the Worker → **Settings** → **Bindings** → **Add** →
   **KV namespace**. The variable name must be exactly **`ART`**; pick the
   namespace from step 3. Save or deploy.
5. **Copy its address.** Open the Worker from **Workers & Pages**; its
   address is under **Domains & Routes** (or behind **Visit**), like
   `https://mild-lyrics-covers.<your-subdomain>.workers.dev`. That address
   is what Mild Lyrics ships with: it is the one line `ART_HOST = "…"` near
   the top of `mild-lyrics/discord_presence.py`. While that line is empty,
   cards keep the still cover.

To check it is up, open `<address>/a/00000000000000000000000000000000.gif`:
it should say `no cover`.

## Deploying with wrangler

From this folder:

    npx wrangler login               # once: approves access in the browser
    npx wrangler kv namespace list   # the id of mild-lyrics-covers
    # put that id in wrangler.toml, as the ART namespace's id
    npx wrangler deploy

`wrangler.toml` names the Worker, binds the KV namespace as `ART`, the
`Room` class as `ROOMS` and `Listen` as `LISTENS`, and carries the migration that creates the rooms'
(SQLite-backed, the free plan's kind) storage. To try it locally first,
`npx wrangler dev` runs the same code on your machine.

## What it does

    GET/HEAD /a/<key>.gif   the GIF, or 404
    PUT      /a/<key>.gif   store it, once (header X-Source: the Apple stream)

The upload address ships inside the app, so anyone can find it. An upload is
only kept if:

- `<key>` is the first 32 hex characters of `sha256(X-Source)`;
- `X-Source` is an Apple animated-cover stream (`mvod.itunes.apple.com`) and
  Apple answers for it;
- nothing is stored under that key yet (write once, never replaced);
- it is a real GIF of at most 2 MB.

What none of that proves is that the GIF is a picture *of* that stream: the
first upload for an album wins. To take a bad one down, delete its key in the
KV namespace's page in the dashboard; the next player of that album uploads
it again.

### Rooms

    GET /room/<32 hex>?as=host&k=<32 hex>   the host's WebSocket
    GET /room/<32 hex>?as=join              a joiner's

The invite carries the room id; the host key never leaves the host, and the
first host to arrive keeps the room under it, so a joiner cannot take its
place. A joiner's messages go to the host alone, the host's to the joiner it
names; joiners never reach each other. At most 12 sockets a room. Nothing is
recorded about anyone, and a room forgets everything when it empties.
Sockets hibernate, so an idle room costs nothing.

When a socket closes, the room says so -- `{"t":"gone","m":<n>}` to the host
for a joiner, `{"t":"gone","m":0}` to every joiner for the host (unless the
host is already back on a new socket). The editors keep no keepalives of
their own through the relay: they wait a short while for that socket to come
back, and let the connection go if it does not.

### Plugins

    GET/HEAD /plugins/index.json          the listing
    GET/HEAD /plugins/<id>/<version>.zip  one release

To publish (or update, after bumping `version` in its `plugin.json`):

    python publish.py <plugin folder>
    python publish.py --remove <id>      # delist; its zips stay

`publish.py` checks the folder the way the player does, zips it without
`__pycache__`, `.git` or `tests` (the same files always make the same zip),
and refuses to put different files under a version already published. The
listing carries each zip's size and sha256, and the player installs nothing
that does not match. `--local` writes into `npx wrangler dev`'s store instead,
to try it first; `--dry-run` only writes the zip here and prints the entry.
Optional `author` and `homepage` (https) fields in `plugin.json` are shown.

#### Download counts

Each plugin's downloads are counted in a Durable Object (`COUNTS`, SQLite,
the free plan's kind) and added to the listing as `"downloads"` when it is
served. An address counts once a day per plugin, so reinstalling, updating
or a script fetching the same zip again does not add up; it is known by a
hash, kept until the next 00:00 UTC. HEAD requests and `publish.py` (which
reads KV directly) are not counted. Every listing view and download is one
Durable Object request against the free plan's 100,000 a day.

#### Submissions

    POST /plugins/submit    body: the zip; header X-Plugin: <id> <version>

The guide for authors is [docs/plugins](../plugins/README.md). A submission
is kept under `submissions/` in ART (unlisted; the Worker never serves it) for
30 days. At most 5 MB, 50 waiting at once, three an hour from one address --
counted by a hash of the address, kept an hour. To review:

    python publish.py --pending              what is waiting
    python publish.py --fetch <submission>   unpack it into ~/.cache/mild-lyrics-review
    python publish.py --approve <submission> publish that, and drop it from the queue
    python publish.py --reject <submission>

`--fetch` only reads: it unpacks, checks `plugin.json`, flags native code,
lists every address the code names, and when the plugin is already listed,
diffs it against the listed version (`report.txt` beside it). Don't run a
submission outside a sandbox before it is approved.

## Free plan limits

100,000 requests a day for the Worker and its rooms together, and 1,000 KV
writes, 1 GB stored.

- Covers: a GIF is about 100–300 KB, so a few thousand albums, one write per
  new album. Discord caches what it fetches, so most card views never reach
  the Worker.
- Rooms: every message an editor sends into a room is counted, at 20
  messages to a request (the free plan included); the rooms' own running
  time costs nothing while they wait, since their sockets hibernate, and
  WebSocket pings are free. Measured, two people: sitting idle, or a song
  playing with nobody touching anything, sends nothing -- the others carry
  the song forward themselves. Every pause, play, seek, edit and cursor
  move is a message as it happens: a pause or a seek about 2 (it and its
  acknowledgement), moving between lines once a second about 5,500 an hour
  (275 requests), timing nonstop at three taps a second about 14,000 while
  the others watch and 22,000 (1,100 requests) for a joiner's own taps --
  each an edit and the host's answer. A four-person
  session with everyone acting four times a second, nonstop, is about
  115,000 (5,700 requests), some seventeen hours of that a day. When a day's
  allowance is gone, rooms refuse new connections until 00:00 UTC; hosting
  through your own TURN server still works then.
- A socket that sends more than 1,200 messages in a minute (a host: that
  many per joiner) is closed with code 4029, and the editor does not come
  back after it -- the busy case above is about 500 a joiner. It is there
  for an editor stuck in a loop, which would otherwise spend the day's
  allowance for everyone.

The dashboard's Worker page counts the Worker's requests alone; the rooms'
are under the Durable Object (ROOMS). Their metrics show every message, not
the 20:1 count that is billed.
