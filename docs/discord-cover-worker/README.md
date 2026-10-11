# Mild Lyrics' Worker

One Cloudflare Worker, on the free plan with a free `*.workers.dev` address
(no domain, no card), with two jobs:

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

`wrangler.toml` names the Worker, binds the KV namespace as `ART` and the
`Room` class as `ROOMS`, and carries the migration that creates the rooms'
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

## Free plan limits

100,000 requests a day for the Worker and its rooms together, and 1,000 KV
writes, 1 GB stored.

- Covers: a GIF is about 100–300 KB, so a few thousand albums, one write per
  new album. Discord caches what it fetches, so most card views never reach
  the Worker.
- Rooms: every message an editor sends into a room is counted, at 20
  messages to a request (the free plan included); the rooms' own running
  time costs nothing while they wait, since their sockets hibernate, and
  WebSocket pings are free. Measured: a two-person session sitting idle is
  about 360 messages an hour (18 requests); working in it -- moving around,
  playing the song -- some 2,000-9,000 (100-450 requests). A four-person
  session with everyone acting four times a second, nonstop, is about
  175,000 (8,700 requests), some eleven hours of that a day. When a day's
  allowance is gone, rooms refuse new connections until 00:00 UTC; hosting
  through your own TURN server still works then.
- A socket that sends more than 1,200 messages in a minute (a host: that
  many per joiner) is closed with code 4029, and the editor does not come
  back after it -- the busy case above is about 720 a joiner. It is there
  for an editor stuck in a loop, which would otherwise spend the day's
  allowance for everyone.

The dashboard's Worker page counts the Worker's requests alone; the rooms'
are under the Durable Object (ROOMS). Their metrics show every message, not
the 20:1 count that is billed.
