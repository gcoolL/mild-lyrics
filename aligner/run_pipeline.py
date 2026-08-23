#!/usr/bin/env python3
"""The rest of it, unattended: wait, train, measure, write a report.

    nohup ./run_pipeline.py &

Runs after build_dataset.py. Waits for it, holds whole songs back, fine-tunes
wav2vec2 from read speech to singing, then aligns the held-back songs twice --
once with the stock model, once with the trained one -- and writes the two sets
of numbers to REPORT.md.

Written as one script because it has to survive a night on its own. Every stage
is wrapped: a failure in one is recorded and the report is still written.

WHAT IT MEASURED, so far: not enough to be worth running. A 10,000-step run
took 75 minutes and its loss fell 2.22 -> 1.68, cleanly, 0 batches skipped.
Aligned against word-synced references and compared word by word with the
stock model on the same two songs, same quiet card:

    SHOWSTOPPER   63 words closer, 44 further   (of 107 that moved)  p = 0.08
    bipolar       11 words closer, 18 further   (of  29 that moved)  p = 0.27
    pooled        74 closer, 62 further                              p = 0.35

The two songs disagree about the DIRECTION, which is the tell. A model that
had learnt something about when singing starts would not help a rap track and
hurt an emo-rock one; this is redistribution, not improvement. On bipolar,
where the stock model had no word beyond a second, the trained one made one.

Falling training loss did not predict any of that, and could not: there is no
dev split here, and CTC loss scores WHAT was sung while alignment lives or
dies on WHEN. Before spending another night on this, give it a held-out split
so the curve means something -- and note that the same two songs gained
65->75% and 76->89% of words inside 0.1s from arithmetic in the onset stage,
with no training at all. See bench.py, which is the instrument for both.
"""
import hashlib
import json
import os
import pathlib
import shutil
import statistics
import sys
import time
import traceback

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import lyric_sources as LS      # noqa: E402

HOME = pathlib.Path.home()
DATA = LS.cache_root() / "dataset"
TUNED = LS.cache_root() / "w2v-singing"
REPORT = pathlib.Path(__file__).resolve().parent.parent / "REPORT.md"
NOTE = []

TRAIN_MAX = 8.0
STEPS = 3000
BATCH = 2
ACCUM = 8
HOLD_OUT = 12
DEV_OUT = 8
EVAL_EVERY = 250
EVAL_BATCHES = 40
PATIENCE = 6
PACKED_OK = 0.12
HEARD_MARGIN = 0.15
WRONG_AUDIO = {"Miracle Musical, Shane - Labyrinth"}


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)
    NOTE.append(msg)


def wait_for_dataset():
    """Sit until build_dataset.py stops adding songs."""
    last, still = -1, 0
    while still < 6:
        n = 0
        if (DATA / "manifest.jsonl").exists():
            n = len({r.get("name") for r in load_manifest()})
        if n == last:
            still += 1
        else:
            still, last = 0, n
            say(f"dataset: {n} songs so far")
        time.sleep(50)
    say(f"dataset finished at {last} songs")
    return last


def load_manifest():
    rows = []
    for line in (DATA / "manifest.jsonl").read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def train(train_songs, dev_songs=()):
    """Fine-tune wav2vec2 on the clips. Returns True if a model was written.

    The model that gets written is the one with the best HELD-OUT loss, not
    the one the last step happened to leave behind. Those are different models
    as soon as the fitting outruns the learning, and without a dev split there
    is no moment at which that becomes visible.
    """
    import numpy as np
    import torch
    from torch.utils.data import Dataset, DataLoader
    from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

    name = "facebook/wav2vec2-base-960h"
    proc = Wav2Vec2Processor.from_pretrained(name)
    model = Wav2Vec2ForCTC.from_pretrained(name, ctc_loss_reduction="mean")
    model.config.ctc_zero_infinity = True
    model.config.apply_spec_augment = False
    model.freeze_feature_encoder()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(dev).train()

    def clips_of(songs):
        out = []
        for song in songs:
            for line in song["lines"]:
                if line["secs"] <= TRAIN_MAX:
                    out.append((line["clip"], line["text"]))
        return out

    items = clips_of(train_songs)
    dev_items = clips_of(dev_songs)
    say(f"training on {len(items)} clips from {len(train_songs)} songs")
    if len(items) < 200:
        say("not enough clips to train on")
        return False
    if dev_items:
        say(f"scoring on {len(dev_items)} held-out clips from "
            f"{len(dev_songs)} songs it never trains on")
    else:
        say("no held-out clips — the loss below says only that the training "
            "clips are being fitted")

    class Clips(Dataset):
        def __init__(self, rows):
            self.rows = rows

        def __len__(self):
            return len(self.rows)

        def __getitem__(self, i):
            clip, text = self.rows[i]
            wave = np.load(DATA / "clips" / clip)
            wave = (wave - wave.mean()) / (wave.std() + 1e-7)
            ids = proc.tokenizer(text.upper()).input_ids
            return torch.from_numpy(wave), torch.tensor(ids, dtype=torch.long)

    def collate(batch):
        waves, labels = zip(*batch)
        wl = max(w.shape[0] for w in waves)
        ll = max(x.shape[0] for x in labels)
        x = torch.zeros(len(waves), wl)
        y = torch.full((len(labels), ll), -100, dtype=torch.long)
        for i, (w, t) in enumerate(zip(waves, labels)):
            x[i, :w.shape[0]] = w
            y[i, :t.shape[0]] = t
        return x, y

    loader = DataLoader(Clips(items), batch_size=BATCH, shuffle=True,
                        collate_fn=collate, num_workers=0, drop_last=True)
    dev_loader = DataLoader(Clips(dev_items), batch_size=BATCH, shuffle=False,
                            collate_fn=collate, num_workers=0,
                            drop_last=True) if dev_items else None

    def dev_loss():
        model.eval()
        got = []
        try:
            with torch.no_grad():
                for n, (x, y) in enumerate(dev_loader):
                    if n >= EVAL_BATCHES:
                        break
                    x, y = x.to(dev), y.to(dev)
                    with torch.amp.autocast("cuda", dtype=torch.bfloat16,
                                            enabled=(dev == "cuda")):
                        out = model(x, labels=y)
                    if torch.isfinite(out.loss):
                        got.append(float(out.loss))
        finally:
            model.train()
        return statistics.mean(got) if got else float("nan")

    opt = torch.optim.AdamW(model.parameters(), lr=1e-5)
    step, seen, skipped, run_bad, losses = 0, 0, 0, 0, []
    best, best_at, best_state, stale, curve = float("inf"), 0, None, 0, []
    if dev_loader is not None:
        base = dev_loss()
        if base == base:
            best = base
            say(f"held-out loss before training: {base:.3f} — a checkpoint has "
                f"to beat this to be kept")
    t0 = time.monotonic()
    while step < STEPS:
        for x, y in loader:
            x, y = x.to(dev), y.to(dev)
            with torch.amp.autocast("cuda", dtype=torch.bfloat16,
                                    enabled=(dev == "cuda")):
                out = model(x, labels=y)
                loss = out.loss / ACCUM
            if not torch.isfinite(loss):
                skipped += 1
                run_bad += 1
                if run_bad > 200:
                    raise RuntimeError(
                        f"200 batches running at step {step} and every loss "
                        f"is non-finite")
                continue
            run_bad = 0
            loss.backward()
            seen += 1
            if seen % ACCUM == 0:
                norm = torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                if not torch.isfinite(norm):
                    opt.zero_grad(set_to_none=True)
                    skipped += 1
                    continue
                opt.step()
                opt.zero_grad(set_to_none=True)
                step += 1
                losses.append(out.loss.detach().item())
                if step % 25 == 0:
                    say(f"  step {step}/{STEPS} loss "
                        f"{statistics.mean(losses[-25:]):.3f} "
                        f"({time.monotonic() - t0:.0f}s, {skipped} skipped)")
                if dev_loader is not None and step % EVAL_EVERY == 0:
                    got = dev_loss()
                    curve.append((step, statistics.mean(losses[-EVAL_EVERY:]),
                                  got))
                    mark = ""
                    if got == got and got < best - 1e-4:
                        best, best_at, stale = got, step, 0
                        best_state = {k: v.detach().to("cpu").clone()
                                      for k, v in model.state_dict().items()}
                        mark = "  <- best"
                    else:
                        stale += 1
                    say(f"  step {step}/{STEPS} HELD-OUT loss {got:.3f}"
                        f"  (train {statistics.mean(losses[-EVAL_EVERY:]):.3f})"
                        f"{mark}")
                    if stale >= PATIENCE:
                        say(f"  held-out loss has not improved in "
                            f"{PATIENCE} evaluations — stopping at step {step}, "
                            f"best was {best:.3f} at step {best_at}")
                        step = STEPS
                if step >= STEPS:
                    break
    if best_state is None:
        say("NOTHING beat the untrained model on held-out loss — not saving. "
            f"The best any checkpoint managed was {min([c[2] for c in curve], default=float('nan')):.3f} "
            f"against {best:.3f} untrained.")
        return False
    model.load_state_dict(best_state)
    say(f"keeping the model from step {best_at}, where the held-out loss "
        f"was {best:.3f}")
    TUNED.mkdir(parents=True, exist_ok=True)
    model.half().save_pretrained(TUNED)
    proc.save_pretrained(TUNED)
    say(f"trained {step} steps, final training loss "
        f"{statistics.mean(losses[-250:]):.3f}, saved to {TUNED}")
    if curve:
        say("  held-out loss against training loss:")
        for at, tr, ho in curve:
            say(f"    step {at:6}  train {tr:.3f}  held-out {ho:.3f}")
        first, last = curve[0], curve[-1]
        say(f"  training  {first[1]:.3f} -> {last[1]:.3f}")
        say(f"  held-out  {first[2]:.3f} -> {last[2]:.3f}"
            f"   (best {best:.3f} at step {best_at})")
        fell = first[2] - last[2]
        say("  the held-out loss fell with the training loss — it learnt "
            "something" if fell > 0.05 else
            "  the held-out loss did NOT follow the training loss — it fitted "
            "the clips without generalising")
        NOTE.append(f"held-out loss {first[2]:.3f} -> {last[2]:.3f} "
                    f"(best {best:.3f} at step {best_at})")
    return True


def patched_w2v():
    """Make local_align read with the fine-tuned model instead of the bundle."""
    import torch
    import torchaudio
    from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
    import local_align as LA

    proc = Wav2Vec2Processor.from_pretrained(TUNED)
    mod = Wav2Vec2ForCTC.from_pretrained(TUNED).float()
    mod.eval()
    vocab = {k.lower(): v for k, v in proc.tokenizer.get_vocab().items()}
    blank = proc.tokenizer.pad_token_id or 0

    def tokenizer(words):
        return [[vocab[c] for c in w if c in vocab] for w in words]

    def aligner(emission, tokens):
        flat = [t for w in tokens for t in w]
        if not flat:
            return [[] for _ in tokens]
        got, scores = torchaudio.functional.forced_align(
            emission[None], torch.tensor([flat], dtype=torch.int32), blank=blank)
        spans = torchaudio.functional.merge_tokens(got[0], scores[0].exp(),
                                                   blank=blank)
        if len(spans) != len(flat):
            raise RuntimeError("span count")
        out, at = [], 0
        for w in tokens:
            out.append(list(spans[at:at + len(w)]) if w else [])
            at += len(w)
        return out

    class Bundle:
        sample_rate = 16000
    LA._w2v_built = (Bundle(), mod, tokenizer, aligner)


def measure(songs, refs, tag):
    """Align each held-out song and compare with its reference.

    Every alignment is also written out as a .ttml, because the numbers below
    are a proxy and the only real test is playing it against the song.
    """
    import local_align as LA
    import lyrics_gui as L
    import eval_aligner as EV
    import spicy_lyrics as SL
    listen = REPORT.parent / "held-out" / tag
    if listen.exists():
        shutil.rmtree(listen)
    listen.mkdir(parents=True, exist_ok=True)
    out = []
    for song in songs:
        tid = song["tid"]
        ref = refs.get(tid) or []
        meta = song.get("meta") or {}
        def skip(why, _n=song["name"]):
            say(f"  {tag} SKIPPED {_n[:38]:40} {why}")
        if len(ref) < 40:
            skip(f"reference has only {len(ref)} words")
            continue
        if not meta.get("length"):
            skip("no length from Spotify")
            continue
        try:
            doc = LA.genius_doc(L.load_token(), meta)
            if not doc:
                skip("no lyrics from Genius")
                continue
            with LA.fetched(f"{meta['artist']} {meta['title']}",
                            float(meta["length"]),
                            artist=meta.get("artist", ""), tid=tid) as audio:
                if not audio:
                    skip(f"no copy — {LA.fetched.last_error[:44]}")
                    continue
                if LA.fetched.swapped:
                    say(f"  ! {song['name'][:36]} is a DIFFERENT copy than "
                        f"last time ({LA.fetched.swapped[1][:40]}) -- its "
                        f"number is not comparable with the run before")
                got = LA.align(audio, doc, want="gpu", spare=0.4,
                               target=float(meta["length"]),
                               log=lambda m: say(f"      {str(m).strip()}"))
                keep = listen.parent / (song["name"].replace("/", "-")
                                        + pathlib.Path(audio).suffix)
                if not keep.exists():
                    shutil.copyfile(audio, keep)
            if got is None:
                skip(f"align failed — {LA.align.last_error[:44]}")
                continue
            safe = song["name"].replace("/", "-")
            (listen / f"{safe}.ttml").write_text(
                SL.render(got, "ttml") + "\n", encoding="utf-8")
            errs = EV.compare(EV.ours(got), [(w, t) for w, t in ref])
            if len(errs) < 20:
                skip(f"only {len(errs)} words matched the reference "
                     f"of {len(ref)}")
                continue
            anc = got.get("_anchors", 0)
            why = got.get("_unanchored_why") or ""
            heard_at = got.get("_heard_share")
            null_at = got.get("_heard_null")
            out.append((song["name"], len(errs),
                        statistics.median(errs),
                        statistics.median([abs(e) for e in errs]),
                        sum(1 for e in errs if abs(e) < 0.3) / len(errs),
                        anc, EV.shape(errs), got.get("_packed", 0.0),
                        heard_at, null_at))
            thirds = EV.shape(errs).get("thirds")
            say(f"  {tag} {song['name'][:40]:42} "
                f"med {statistics.median(errs):+.3f}s  "
                f"|med| {out[-1][3]:.3f}s  in 0.3s {out[-1][4]*100:.0f}%  "
                f"packed {got.get('_packed', 0)*100:.0f}%"
                + (f"  thirds {thirds[0]:+.2f}/{thirds[1]:+.2f}/{thirds[2]:+.2f}"
                   if thirds else "")
                + f"  {verdict(out[-1])}")
        except Exception:
            skip("raised:\n" + traceback.format_exc()[-300:])
        finally:
            LA.release()
    return out


def verdict(row):
    """What the two reference-free detectors say, read together.

    They fail on different things, so neither alone is a diagnosis:

      words absent, packing normal   the audio is a different recording
      words absent, packing high     the right song, and nothing can hear it
      words heard,  packing high     the alignment was damaged
    """
    _name, _n, _med, _abs, _hit, _anc, _shape, packed, heard, null = row
    tight = packed <= PACKED_OK
    if heard is None:
        return "packing ok" if tight else f"PACKED {packed*100:.0f}%"
    margin = heard - (null or 0.0)
    if margin < HEARD_MARGIN:
        return ("WRONG RECORDING?" if tight else
                "nothing can hear this song")
    return "ok" if tight else "alignment damaged?"


def summarise(rows):
    """One line for a set of songs.

    No median: the distribution is two clumps, a few songs at 0.1s and a few
    at 15-30s, and its median lands in the empty middle describing no song in
    the set. How many are usable and how many are broken is the whole story.
    """
    if not rows:
        return "no songs measured"
    hit = statistics.mean([r[4] for r in rows])
    bad = sum(1 for r in rows if r[3] > 1.0)
    good = sum(1 for r in rows if r[3] < 0.3)
    lean = statistics.median([r[2] for r in rows])
    return (f"{len(rows)} songs | {good} good (<0.3s) | {bad} broken (>1s) | "
            f"within 0.3s {hit*100:.0f}% of words | they run {lean:+.3f}s "
            f"{'late' if lean > 0 else 'early'}")


def paired(before, after):
    """The two passes cut down to the songs BOTH of them measured.

    Comparing 9 songs against a different 8 lets a song vanishing from one
    pass move the summary on its own, which is what happened when ISSBROKIE
    dropped out of `after` and took its 22.832s with it.
    """
    both = {r[0] for r in before} & {r[0] for r in after}
    return ([r for r in before if r[0] in both],
            [r for r in after if r[0] in both], both)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=STEPS)
    args, _rest = ap.parse_known_args()
    globals()["STEPS"] = args.steps
    say("pipeline started")
    try:
        wait_for_dataset()
        songs = load_manifest()
        if len(songs) < 20:
            say(f"only {len(songs)} songs; stopping")
            return
        import spicy_lyrics as SL
        import eval_aligner as EV
        from spotify_dom import connect
        cdp = connect(9222, "spotify")
        refs = {}
        for song in songs:
            try:
                refs[song["tid"]] = EV.reference(cdp, song["tid"])
                song["meta"] = cdp.evaluate(
                    EV.JS_TRACK % json.dumps("spotify:track:" + song["tid"]))
            except Exception:
                refs[song["tid"]] = []
        (DATA / "refs.json").write_text(json.dumps(
            {k: v for k, v in refs.items()}))
        say(f"references captured for {sum(1 for v in refs.values() if v)} songs")

        by_name = {}
        for song in songs:
            by_name.setdefault(song["name"], song)
        songs = [s for s in by_name.values() if s["name"] not in WRONG_AUDIO]
        songs.sort(key=lambda s: hashlib.sha1(
            s["name"].encode("utf-8")).hexdigest())
        held = songs[:HOLD_OUT]
        dev_songs = songs[HOLD_OUT:HOLD_OUT + DEV_OUT]
        rest = songs[HOLD_OUT + DEV_OUT:]
        seen_in = {}
        for group, where in ((held, "measured"), (dev_songs, "scored"),
                             (rest, "trained on")):
            for s in group:
                if s["name"] in seen_in:
                    raise RuntimeError(
                        f"{s['name']!r} is both {seen_in[s['name']]} and "
                        f"{where}")
                seen_in[s["name"]] = where
        say(f"holding back {len(held)} songs to measure, {len(dev_songs)} to "
            f"score the loss on, training on {len(rest)}")

        say("=== before: stock wav2vec2")
        before = measure(held, refs, "before")

        ok = False
        try:
            ok = train(rest, dev_songs)
        except Exception:
            say("training failed:\n" + traceback.format_exc()[-800:])

        after = []
        if ok:
            try:
                patched_w2v()
                say("=== after: fine-tuned on singing")
                after = measure(held, refs, "after")
            except Exception:
                say("measuring the trained model failed:\n"
                    + traceback.format_exc()[-800:])

        pb, pa, both = paired(before, after)
        missed = ({r[0] for r in before} ^ {r[0] for r in after})
        quiet = [s["name"] for s in held
                 if s["name"] not in {r[0] for r in before}]
        steps = [n for n in NOTE if n.lstrip().startswith("step ")]
        story = [n for n in NOTE if not n.lstrip().startswith("step ")]
        when = time.strftime("%Y-%m-%d %H:%M")
        body = (
            "# Fine-tuning wav2vec2 on singing\n\n"
            f"Run of {when}.  Held out {len(held)} songs to measure and "
            f"{len(dev_songs)} to score the loss on, trained on "
            f"{len(rest)}.\n\n"
            f"Compared on the {len(both)} songs BOTH passes measured:\n\n"
            f"- before (stock): {summarise(pb)}\n"
            f"- after  (tuned): {summarise(pa)}\n\n"
            + (f"Not comparable — measured by only one pass: "
               f"{', '.join(sorted(missed))}\n\n" if missed else "")
            + (f"Never measured by either pass: {', '.join(sorted(quiet))}\n\n"
               if quiet else "")
            + "## per song\n\n"
            "| song | words | before | after | thirds (before) | packed | "
            "heard vs null | reading |\n"
            "|---|---|---|---|---|---|---|---|\n"
            + "".join(
                f"| {b[0]} | {b[1]} | {b[3]:.3f}s | "
                + (f"{a[3]:.3f}s | " if (a := next(
                    (x for x in after if x[0] == b[0]), None)) else "- | ")
                + (f"{b[6]['thirds'][0]:+.2f} / {b[6]['thirds'][1]:+.2f} / "
                   f"{b[6]['thirds'][2]:+.2f} | " if b[6].get("thirds")
                   else "- | ")
                + f"{b[7]*100:.0f}% | "
                + (f"{b[8]*100:.0f}% vs {(b[9] or 0)*100:.0f}% | "
                   if b[8] is not None else "not heard | ")
                + f"{verdict(b)} |\n"
                for b in before)
            + f"\n## log\n\n```\n" + "\n".join(story)
            + f"\n\n({len(steps)} training step lines omitted; "
            + (steps[-1].strip() if steps else "none") + ")\n```\n")
        REPORT.write_text(body, encoding="utf-8")
        keep = REPORT.parent / "reports"
        keep.mkdir(exist_ok=True)
        (keep / f"REPORT-{time.strftime('%Y%m%d-%H%M')}.md").write_text(
            body, encoding="utf-8")
        say(f"report written to {REPORT}")
    except Exception:
        say("pipeline failed:\n" + traceback.format_exc()[-1000:])
        try:
            REPORT.write_text("# Pipeline failed\n\n```\n"
                              + "\n".join(NOTE[-60:]) + "\n```\n")
        except Exception:
            pass


if __name__ == "__main__":
    main()
