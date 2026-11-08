# `editor/shared_splits.py` and `editor/splits_ui.py`

## 2026-10-16 — the shared splitting dictionary

One dictionary of how words are cut into syllables, that anyone can add to,
kept on the Worker (`docs/discord-cover-worker/worker.js`, the `Splits`
Durable Object, one per language). Decided 2026-10-15:

- **Anyone writes, no account; the last entry for a word wins.** `[]` removes
  an entry.
- **One list per language**, filed by the song's language (the editor's split
  language, `en_US` → `en`), because the same spelling splits differently:
  "rose" is one syllable in English and ro|se in Dutch and German.
- **Locking.** The owner locks an entry ("pro|cess" once it is right) and
  nobody can change or remove it. Enforced at the Worker, not in the editor:
  `POST /splits/<lang>/lock` with `X-Owner-Hash`, the sha256 hex of the
  secret's UTF-8, compared in constant time against the hash of the
  `SPLITS_OWNER` Worker secret (`npx wrangler secret put SPLITS_OWNER`). A
  hash rather than the secret, because a header carries bytes and a secret
  with accents came out differently on the two sides (2026-10-16: it was
  refused). The editor keeps the secret in `editor.json` as `splits_owner`.
- **Precedence:** a choice made for this song, then your own correction
  (kept or held), then the shared entry, then the rule. The shared entry
  replaces the rule outright. `override_for(word, lang)` in syllables.py.
- **A word with more than one right way is asked about** (`splits_ui.ask_ways`)
  before Syllabify cuts it, once per word per song (`SY.choose`, forgotten
  in `let_go_all`). Cutting while typing does not ask, and uses the chosen
  way or the first. Both ways count as right in the review (`is_accepted`
  with `lang`).
- **Contributing is its own tab** (the drawer's Splits tab; Shared splits…
  in the classic menu), not offered on each correction. "Show my own
  corrections" lists the local store, so a correction can be shared from it.

Writes that change nothing send nothing (2026-10-16, asked): the editor
answers "already so" from the list it holds -- the same split shared again, a
locked word locked, a missing word removed -- and the Worker does the same as
a second line, without counting the write or moving the version. Several
words go as one request (`entries` / `words`, up to 500), so locking fifty
is one round trip.

Cost: a language's list is fetched at most every 30 min (`STALE`), with an
ETag, so an unchanged list is a 304; it is kept on disk under
`cache/shared-splits/<lang>.json` and read from there first. Writes are
counted per address (a hash kept for the day), 300 a day. Settings ▸
Splitting ▸ Shared dictionary turns it off, and nothing is fetched then.

`ops._split_memo` is keyed by `SH.version()`, the chosen ways and the setting,
so a list arriving in the background re-cuts what the counts show.

Tests: `test_shared_splits.py` (offline), `test_splits_worker.py` and
`test_shared_splits_live.py` (against `npx wrangler dev --port 8797 --var
SPLITS_OWNER:test-owner`).

## Sharing from the automatic split (2026-10-17)

Auto split… has "Share to the shared splits…": the picked preview rows, or
all of them, filtered to words with a correction of yours (kept or held for
this song) -- rule output is never sent, since a shared entry replaces the
rule and sharing the rule's own answer adds nothing. A dialogue lists each
word against the shared list (new / replaces … / already shared / locked);
only the first two are ticked and sendable. `splits_ui.share_corrections`.

## The player's review and the preview (2026-11-03)

The review in Mild Lyrics (`review.py`) already cut through `SY.split` with
the document's language, so a shared entry was its "Correct split" -- but a
word's other shared ways were still raised (`bub|b|ly` against `bub|bly /
bub|b|ly`), because `_kept_right` read only your own store. It now reads
`accepted(core, lang)` = `SY.ways_known`: your ways if you kept any, else the
shared list's. The report's key carries `SH.version()`, so a list arriving in
the background redoes the open review. Correct the split (C) starts from the
shared ways too; Shift+K still restores only what was kept here, so undoing
never writes a shared way into your store.

Syllabify and Auto split already cut by the shared list (`SY.split` with
`lang`). Auto split's preview now lists every shared way (`ways_for(word,
lang)`), marks such words "shared", and lists a shared one-piece entry as it
does a kept one. The word menus' "Cut … into syllables" test the song's
language rather than English.

`test_review.py` stubs `SH.words` (the live list changed `rewrite` under it).
