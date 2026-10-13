// Mild Lyrics' Worker: animated covers for Discord, the TTML Editor's
// multiplayer relay and the plugin marketplace. One free Cloudflare account.
//
// ---------------------------------------------------------------- covers
// Discord shows a cover by fetching a public URL from its own servers, so a
// GIF made on somebody's machine has to live somewhere it can be fetched.
// This is that somewhere, in one KV namespace bound as ART. The app makes the
// GIF (a Worker has 10ms of CPU, far too little for ffmpeg) and puts it here
// once; everyone after that is handed the same one.
//
//   GET/HEAD /a/<key>.gif   the GIF, or 404
//   PUT      /a/<key>.gif   store it, once. Headers:
//                             X-Source: the Apple stream it was made from
//                           body: the GIF
//
// The upload address ships inside the app, so anyone can find it. What is
// stored is therefore held to what it claims to be:
//   - <key> is the first 32 hex of sha256(X-Source), so a key belongs to one
//     stream and cannot be picked freely;
//   - X-Source must be an Apple animated-cover stream, and Apple must answer
//     for it -- an album with no animation has no key at all;
//   - written once: a key that has a GIF keeps it;
//   - a real GIF, at most MAX_BYTES.
// What none of that can prove is that the GIF is a picture OF that stream.
//
// ----------------------------------------------------------------- rooms
// A multiplayer session's relay, so that nobody in it learns anybody else's
// IP address: every editor talks to the room (a Durable Object, bound as
// ROOMS), and the room passes datagrams between the host and each joiner.
//
//   GET /room/<32 hex>?as=host&k=<32 hex>   the host's WebSocket
//   GET /room/<32 hex>?as=join              a joiner's
//
// What goes through is the editors' QUIC: encrypted end to end, under a
// certificate the invite pins, so the room relays bytes it cannot read. A
// joiner's binary message goes to the host with the joiner's member number
// in front (4 bytes, big-endian); the host's carries the number of the joiner
// it is for, and goes to that joiner without it. Joiners never reach each
// other. On connecting, each side is told its number: {"t":"you","m":n}.
//
// The room id is in the invite, so anyone holding an invite can knock; what
// lets them in is the editors' own token and certificate, not this. The host
// key `k` is the host's alone: the first host to arrive keeps the room under
// it, so a joiner cannot take the host's place. Nothing is recorded about
// anyone, addresses included, and a room forgets everything when it empties.
// Sockets use the hibernation API, so an idle room costs nothing.
//
// --------------------------------------------------------------- plugins
//   GET/HEAD /plugins/index.json          what the app's Browse lists
//   GET/HEAD /plugins/<id>/<version>.zip  one release, never replaced
//   POST     /plugins/submit               a zip for review (X-Plugin: id version)
//
// publish.py beside this file writes the listing; a submission waits under
// submissions/, unlisted and unreadable here, until it is reviewed there.
// Downloads are counted in one Durable Object (COUNTS): an address once a
// day per plugin, known by a hash kept for that day only. The listing is
// served with each plugin's count added as "downloads".
const MAX_BYTES = 2 * 1024 * 1024;
const SOURCE = /^https:\/\/mvod\.itunes\.apple\.com\/itunes-assets\/[A-Za-z0-9._\/-]+\.m3u8$/;
const PATH = /^\/a\/([0-9a-f]{32})\.gif$/;
const ROOM = /^\/room\/([0-9a-f]{32})$/;
const SUBMIT_MAX = 5 * 1024 * 1024;
const SUBMIT_QUEUE = 50;           // waiting at once
const SUBMIT_PER_HOUR = 3;         // from one address
const SUBMIT_DAYS = 30;            // an unreviewed one is forgotten after
const SUBMIT_WHAT = /^([a-z0-9][a-z0-9_-]{0,47}) ([0-9A-Za-z.+-]{1,32})$/;
const PLUGIN = /^\/plugins\/(index\.json|[a-z0-9][a-z0-9_-]{0,47}\/[0-9A-Za-z.+-]{1,32}\.zip)$/;
const ROOM_MAX = 12;            // sockets in one room: a host and its joiners
const DATAGRAMS_MAX = 65536;    // bytes in one message, a batch of datagrams
// Every message into a room is counted against the day's allowance, so a
// socket sending far more than any session needs -- an editor stuck in a
// loop, say -- is closed. Per minute, a joiner's; a host speaks to each of
// its joiners, so it gets that many times over. A busy session (four people
// each acting four times a second, nonstop) is about 500 a joiner.
const FLOOD_WINDOW = 60_000;
const FLOOD_MAX = 1200;
const FLOOD_CODE = 4029;        // the editor does not come back after this one

async function keyOf(source) {
  const digest = await crypto.subtle.digest(
    "SHA-256", new TextEncoder().encode(source));
  return [...new Uint8Array(digest)]
    .map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 32);
}

function say(status, text) {
  return new Response(text + "\n", {
    status, headers: { "content-type": "text/plain; charset=utf-8" } });
}

// Only a hash of the address is kept, for an hour, to count its uploads.
async function submit(req, env) {
  const size = Number(req.headers.get("content-length") || 0);
  if (!size) return say(411, "send a Content-Length");
  if (size > SUBMIT_MAX) return say(413, "too big: 5 MB at most");
  const what = (req.headers.get("x-plugin") || "").match(SUBMIT_WHAT);
  if (!what) return say(400, "send X-Plugin: <id> <version>");
  const rate = "submit-rate/" + (await keyOf(req.headers.get("cf-connecting-ip") || ""));
  const sent = Number((await env.ART.get(rate)) || 0);
  if (sent >= SUBMIT_PER_HOUR) return say(429, "three an hour at most; try again later");
  const queue = await env.ART.list({ prefix: "submissions/", limit: SUBMIT_QUEUE });
  if (queue.keys.length >= SUBMIT_QUEUE) return say(503, "the review queue is full; try again in a few days");
  const body = await req.arrayBuffer();
  if (body.byteLength > SUBMIT_MAX) return say(413, "too big: 5 MB at most");
  const head = new Uint8Array(body, 0, Math.min(4, body.byteLength));
  if (head.length < 4 || head[0] !== 0x50 || head[1] !== 0x4b || head[2] !== 3 || head[3] !== 4) {
    return say(415, "not a zip");
  }
  const id = Date.now().toString(36) + "-" + crypto.randomUUID().slice(0, 8);
  await env.ART.put("submissions/" + id + ".zip", body, {
    expirationTtl: SUBMIT_DAYS * 86400,
    metadata: { id: what[1], version: what[2], size: body.byteLength,
                at: new Date().toISOString() },
  });
  await env.ART.put(rate, String(sent + 1), { expirationTtl: 3600 });
  return say(202, `received as ${id}; it is listed once it has been reviewed`);
}

function counts(env) {
  return env.COUNTS.get(env.COUNTS.idFromName("plugins"));
}

// The listing with the counts in; as stored, if the counts cannot be had.
async function counted(env, body) {
  try {
    const n = await (await counts(env).fetch("https://counts/")).json();
    const index = JSON.parse(new TextDecoder().decode(body));
    for (const e of index.plugins || []) e.downloads = n[e.id] || 0;
    return new TextEncoder().encode(JSON.stringify(index));
  } catch (e) {
    return body;
  }
}

async function plugin(req, env, ctx, name) {
  if (req.method !== "GET" && req.method !== "HEAD") return say(405, "GET or HEAD");
  let body = await env.ART.get("plugins/" + name, "arrayBuffer");
  if (!body) {
    const r = say(404, "no such plugin");
    r.headers.set("cache-control", "no-store");
    return r;
  }
  const index = name === "index.json";
  if (index) {
    body = await counted(env, body);
  } else if (req.method === "GET") {
    const who = await keyOf(req.headers.get("cf-connecting-ip") || "");
    ctx.waitUntil(counts(env).fetch("https://counts/", {
      method: "POST", body: JSON.stringify({ id: name.split("/")[0], who }),
    }).catch(() => {}));
  }
  return new Response(req.method === "HEAD" ? null : body, {
    headers: {
      "content-type": index ? "application/json; charset=utf-8" : "application/zip",
      "content-length": String(body.byteLength),
      "cache-control": index ? "public, max-age=300"
                             : "public, max-age=31536000, immutable",
    },
  });
}

export default {
  async fetch(req, env, ctx) {
    const url = new URL(req.url);
    const r = url.pathname.match(ROOM);
    if (r) {
      if (req.headers.get("upgrade") !== "websocket") return say(426, "WebSocket only");
      return env.ROOMS.get(env.ROOMS.idFromName(r[1])).fetch(req);
    }
    if (url.pathname === "/plugins/submit") {
      return req.method === "POST" ? submit(req, env) : say(405, "POST");
    }
    const pl = url.pathname.match(PLUGIN);
    if (pl) return plugin(req, env, ctx, pl[1]);
    const m = url.pathname.match(PATH);
    if (!m) return say(404, "not here");
    const key = m[1];

    if (req.method === "GET" || req.method === "HEAD") {
      const gif = await env.ART.get(key, "arrayBuffer");
      if (!gif) {
        // Not kept: a cover can be stored a moment after this is asked --
        // and KV reaches other locations up to a minute later -- so nothing
        // on the way, Discord's image proxy included, should hold on to
        // the miss.
        const r = say(404, "no cover");
        r.headers.set("cache-control", "no-store");
        return r;
      }
      return new Response(req.method === "HEAD" ? null : gif, {
        headers: {
          "content-type": "image/gif",
          "content-length": String(gif.byteLength),
          // A key is one stream, written once: it never changes.
          "cache-control": "public, max-age=31536000, immutable",
        },
      });
    }

    if (req.method !== "PUT") return say(405, "GET, HEAD or PUT");

    const source = req.headers.get("x-source") || "";
    if (!SOURCE.test(source)) return say(400, "not an Apple cover stream");
    if ((await keyOf(source)) !== key) return say(400, "key is not the stream's");
    if (await env.ART.get(key, "arrayBuffer")) return say(409, "already have it");

    const size = Number(req.headers.get("content-length") || 0);
    if (size > MAX_BYTES) return say(413, "too big");
    const body = await req.arrayBuffer();
    if (body.byteLength > MAX_BYTES) return say(413, "too big");
    const head = new TextDecoder().decode(new Uint8Array(body, 0, 6));
    if (head !== "GIF89a" && head !== "GIF87a") return say(415, "not a GIF");

    const apple = await fetch(source, { headers: { "user-agent": "Mozilla/5.0" } });
    if (!apple.ok || !(await apple.text()).startsWith("#EXTM3U")) {
      return say(400, "Apple does not know that stream");
    }

    await env.ART.put(key, body);
    return say(201, "stored");
  },
};

// ------------------------------------------------------------------ rooms
const KEY = /^[0-9a-f]{32}$/;

export class Room {
  constructor(ctx, env) {
    this.ctx = ctx;
    // In memory only: storage writes are counted too. Hibernating forgets
    // it -- and a room quiet enough to hibernate is not flooding.
    this.rate = new Map();
  }

  async fetch(req) {
    const url = new URL(req.url);
    const as = url.searchParams.get("as");
    if (as !== "host" && as !== "join") return say(400, "as=host or as=join");
    const live = this.ctx.getWebSockets();
    if (live.length >= ROOM_MAX) return say(429, "this session is full");

    let mid = 0;
    if (as === "host") {
      const k = url.searchParams.get("k") || "";
      if (!KEY.test(k)) return say(400, "no host key");
      const hash = await keyOf(k);
      const kept = await this.ctx.storage.get("host");
      if (kept && kept !== hash) return say(403, "this room has another host");
      if (!kept) await this.ctx.storage.put("host", hash);
      // A host coming back takes over from its own dropped socket.
      for (const old of this.ctx.getWebSockets("host")) {
        try { old.close(4000, "the host connected again"); } catch (e) {}
      }
    } else {
      mid = ((await this.ctx.storage.get("next")) || 0) + 1;
      await this.ctx.storage.put("next", mid);
    }

    const [client, server] = Object.values(new WebSocketPair());
    this.ctx.acceptWebSocket(server, [as === "host" ? "host" : "m" + mid]);
    server.serializeAttachment({ as, mid });
    server.send(JSON.stringify({ t: "you", m: mid }));
    return new Response(null, { status: 101, webSocket: client });
  }

  async webSocketMessage(ws, msg) {
    if (typeof msg === "string") return;        // nothing to say in text
    if (msg.byteLength > DATAGRAMS_MAX + 4) return;
    const me = ws.deserializeAttachment() || {};
    if (this._flooding(ws, me)) return;
    if (me.as === "join") {
      const host = this.ctx.getWebSockets("host")[0];
      if (!host) return;
      const out = new Uint8Array(4 + msg.byteLength);
      new DataView(out.buffer).setUint32(0, me.mid);
      out.set(new Uint8Array(msg), 4);
      try { host.send(out); } catch (e) {}
    } else if (me.as === "host" && msg.byteLength > 4) {
      const to = new DataView(msg).getUint32(0);
      const peer = this.ctx.getWebSockets("m" + to)[0];
      if (peer) {
        try { peer.send(msg.slice(4)); } catch (e) {}
      }
    }
  }

  _flooding(ws, me) {
    const now = Date.now();
    let r = this.rate.get(ws);
    if (!r || now - r.t > FLOOD_WINDOW) this.rate.set(ws, (r = { t: now, n: 0 }));
    const cap = FLOOD_MAX * (me.as === "host"
      ? Math.max(1, this.ctx.getWebSockets().length - 1) : 1);
    if (++r.n <= cap) return false;
    this.rate.delete(ws);
    try { ws.close(FLOOD_CODE, "far more traffic than a session needs"); } catch (e) {}
    return true;
  }

  async webSocketClose(ws, code, reason) {
    this.rate.delete(ws);
    try { ws.close(1000, "bye"); } catch (e) {}
    this._gone(ws);
    await this._empty(ws);
  }

  async webSocketError(ws) {
    this._gone(ws);
    await this._empty(ws);
  }

  // Somebody's connection closed: the other side is told, so the editors
  // need no keepalives of their own to find out (and messages out of a room
  // are free; the keepalives coming in were not). A joiner gone is said to
  // the host; the host gone, to every joiner -- unless it has already come
  // back on a new socket, which is what closed this one.
  _gone(ws) {
    const me = ws.deserializeAttachment() || {};
    const say = (to, m) => {
      try { to.send(JSON.stringify({ t: "gone", m })); } catch (e) {}
    };
    if (me.as === "join") {
      for (const h of this.ctx.getWebSockets("host")) say(h, me.mid);
    } else if (me.as === "host") {
      if (this.ctx.getWebSockets("host").some((h) => h !== ws)) return;
      for (const w of this.ctx.getWebSockets()) {
        if (w !== ws && (w.deserializeAttachment() || {}).as === "join") say(w, 0);
      }
    }
  }

  async _empty(gone) {
    // Everyone gone: the room keeps nothing, not even who hosted it.
    if (this.ctx.getWebSockets().every((w) => w === gone)) {
      await this.ctx.storage.deleteAll();
    }
  }
}

// Plugin download counts. POST {id, who} counts one; GET answers {id: n}.
export class Counts {
  constructor(ctx, env) {
    this.sql = ctx.storage.sql;
    this.sql.exec("CREATE TABLE IF NOT EXISTS n (id TEXT PRIMARY KEY, c INTEGER NOT NULL)");
    this.sql.exec("CREATE TABLE IF NOT EXISTS seen (k TEXT PRIMARY KEY, day INTEGER NOT NULL)");
  }

  async fetch(req) {
    if (req.method !== "POST") {
      const out = {};
      for (const r of this.sql.exec("SELECT id, c FROM n")) out[r.id] = r.c;
      return Response.json(out);
    }
    const { id, who } = await req.json();
    if (!/^[a-z0-9][a-z0-9_-]{0,47}$/.test(id || "")) return new Response("bad id", { status: 400 });
    const day = Math.floor(Date.now() / 86400000);
    this.sql.exec("DELETE FROM seen WHERE day < ?", day);
    const k = `${who}|${id}`;
    if (this.sql.exec("SELECT 1 FROM seen WHERE k = ?", k).toArray().length === 0) {
      this.sql.exec("INSERT INTO seen (k, day) VALUES (?, ?)", k, day);
      this.sql.exec("INSERT INTO n (id, c) VALUES (?, 1) "
                    + "ON CONFLICT(id) DO UPDATE SET c = c + 1", id);
    }
    return new Response("counted");
  }
}
