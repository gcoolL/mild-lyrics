// Mild Lyrics' Worker: animated covers for Discord, and the TTML Editor's
// multiplayer relay. One Worker, one free Cloudflare account, two jobs.
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
const MAX_BYTES = 2 * 1024 * 1024;
const SOURCE = /^https:\/\/mvod\.itunes\.apple\.com\/itunes-assets\/[A-Za-z0-9._\/-]+\.m3u8$/;
const PATH = /^\/a\/([0-9a-f]{32})\.gif$/;
const ROOM = /^\/room\/([0-9a-f]{32})$/;
const ROOM_MAX = 12;            // sockets in one room: a host and its joiners
const DATAGRAMS_MAX = 65536;    // bytes in one message, a batch of datagrams
// Every message into a room is counted against the day's allowance, so a
// socket sending far more than any session needs -- an editor stuck in a
// loop, say -- is closed. Per minute, a joiner's; a host speaks to each of
// its joiners, so it gets that many times over. A busy session (four people
// each acting four times a second, nonstop) is about 720 a joiner.
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

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const r = url.pathname.match(ROOM);
    if (r) {
      if (req.headers.get("upgrade") !== "websocket") return say(426, "WebSocket only");
      return env.ROOMS.get(env.ROOMS.idFromName(r[1])).fetch(req);
    }
    const m = url.pathname.match(PATH);
    if (!m) return say(404, "not here");
    const key = m[1];

    if (req.method === "GET" || req.method === "HEAD") {
      const gif = await env.ART.get(key, "arrayBuffer");
      if (!gif) return say(404, "no cover");
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
    await this._empty(ws);
  }

  async webSocketError(ws) {
    await this._empty(ws);
  }

  async _empty(gone) {
    // Everyone gone: the room keeps nothing, not even who hosted it.
    if (this.ctx.getWebSockets().every((w) => w === gone)) {
      await this.ctx.storage.deleteAll();
    }
  }
}
