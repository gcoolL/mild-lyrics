"""Training the synchroniser from noise, and training it further later.

    python -m sync.sync train                  # 20k steps, from scratch
    python -m sync.sync train --more 5000      # 5k more on what is on disk
    python -m sync.sync train --dim 256        # a smaller one

The loss is CTC, which asks only that the symbols appear in order somewhere in
the clip. That choice is what lets this be trained on somebody else's timings:
a line whose words sit 200 ms from where the label claims is still a correct
example, because the loss never reads the label's times -- only its words. What
CTC cannot absorb is a line cut so far from its words that they are outside the
clip, and that is offset.py's job, upstream of here.

Two numbers are printed while it runs and they mean different things:

  loss   how surprised the model is by the clips it is training on. It falls
         fast for an hour and then crawls, and the crawl is where the timing
         actually improves.
  held   the same on songs it has never seen. It stops falling long before the
         timings stop improving -- see the note by the -lowloss checkpoint --
         so a rising held loss is a reason to run `sync bench`, not a reason to
         stop.
  heard  the share of characters it gets right on held-out songs with NO lyric
         to guide it. It is not the thing being optimised and it will never be
         high -- singing over a band is hard, and this model is small on
         purpose -- but a model that hears nothing cannot time anything, so it
         is the honest early warning that a run has gone nowhere.

Neither of them is the answer. The answer is `sync bench`, which measures
seconds against references, and it is a separate command because it is slow and
because a training loss that improves while the timings get worse is a thing
that happens.
"""
from __future__ import annotations

import json
import math
import pathlib
import time

import torch

from . import ctcalign, data, model as M, text

HOME = pathlib.Path.home() / ".cache/mild-lyrics/sync"
CKPT = HOME / "syncnet.pt"


def _lr(step: int, total: int, peak: float, warm: int) -> float:
    """Warm up, then cosine down. The warm-up is not optional: a fresh CTC head
    at full learning rate collapses to all-blank in a hundred steps and never
    comes back out of it."""
    if step < warm:
        return peak * (step + 1) / warm
    done = (step - warm) / max(1, total - warm)
    return peak * (0.05 + 0.95 * 0.5 * (1 + math.cos(math.pi * min(1.0, done))))


def _validate(net, loader, device, limit: int = 40) -> tuple[float, float, str]:
    """(loss, character accuracy, one example) on held-out songs."""
    net.eval()
    total, frames, right, chars = 0.0, 0, 0, 0
    sample = ""
    with torch.no_grad():
        for n, (mel, lengths, targets, widths, labels, _boundary) in enumerate(loader):
            if n >= limit:
                break
            mel = mel.to(device)
            logp, _boundary_logits = net(mel)
            ins = torch.tensor([net.out_len(int(x)) for x in lengths])
            loss = torch.nn.functional.ctc_loss(
                logp.transpose(0, 1), targets, ins, widths,
                blank=text.BLANK, zero_infinity=True, reduction="sum")
            total += float(loss)
            frames += int(widths.sum())
            for i, label in enumerate(labels):
                said = ctcalign.greedy(logp[i, :ins[i]].cpu())
                right += sum(1 for a, b in zip(said, label) if a == b)
                chars += len(label)
                if not sample:
                    sample = f"{label[:48]!r} -> {said[:48]!r}"
    net.train()
    return (total / max(1, frames), right / max(1, chars), sample)


def run(steps: int = 20000, more: int = 0, root=data.DATA, ckpt=CKPT,
        dim: int = 320, blocks: int = 12, batch: int = 16, hold: float = 0.08,
        device: str = "cuda", workers: int = 4, every: int = 250,
        lr: float | None = None, drop: float = 0.2, seed: int = 0,
        gold_by: str = "gc", kind: str = "syncnet", accum: int = 1,
        freeze: int = 800, large: bool = False, top: int = 0,
        pitch: bool = False) -> int:
    torch.manual_seed(seed)
    device = device if torch.cuda.is_available() else "cpu"
    ckpt = pathlib.Path(ckpt).expanduser()

    # The songs one known hand timed are held out at a higher rate -- see
    # data.holdout. Named here rather than inside Clips so the checkpoint can
    # record whose hand it was.
    from . import dataset as DS
    gold = {DS.name_of(t) for t in DS.by_hand(gold_by, DS.snapshots(DS.SNAP))} \
        if gold_by else set()
    gold_held = data.gold_split(gold) if gold else frozenset()
    # A pretrained encoder reads the waveform; the small model reads mels.
    from . import encoder as ENC
    kit = ENC if kind == "wav2vec" else M
    wants = "wave" if kind == "wav2vec" else "mel"
    # Shorter clips for the encoder: attention costs the square of the input,
    # and the longest clips are what push a batch over the card.
    longest = 10.0 if kind == "wav2vec" else 12.0
    train = data.Clips(root, hold, "train", gold_held=gold_held, wants=wants,
                       max_secs=longest, pitch=pitch)
    heldout = data.Clips(root, hold, "held", augment=False, gold_held=gold_held,
                         wants=wants, max_secs=longest, pitch=pitch)
    if not len(train):
        raise SystemExit(f"no training clips under {root}")
    print(f"{len(train.songs)} songs, {len(train)} clips to train on; "
          f"{len(heldout.songs)} songs, {len(heldout)} clips held back")

    started, history = 0, []
    # A continuation is NOT a fresh run, and the difference is not cosmetic.
    # `--more 8000` on the encoder restarted the schedule at its peak rate and
    # kept the 30x head multiplier that exists only to bootstrap a head made of
    # noise. The head was already trained; multiplying its rate by thirty and
    # then ramping back to peak drove it to NaN and the run wrote itself over
    # an hour-old checkpoint. Everything below that reads `resume` is that
    # incident, in code.
    resume = bool(more and ckpt.exists())
    if more and ckpt.exists():
        net, rest = kit.load(ckpt, device)
        started = int(rest.get("step") or 0)
        history = list(rest.get("history") or [])
        # The split is the checkpoint's, not this run's: a model that has seen
        # a song must not be measured on it because a flag was typed
        # differently three weeks later.
        if abs(float(rest.get("hold", hold)) - hold) > 1e-9:
            hold = float(rest["hold"])
            # wants/max_secs too: rebuilding these without them handed a
            # waveform encoder mel clips.
            train = data.Clips(root, hold, "train", gold_held=gold_held,
                               wants=wants, max_secs=longest)
            heldout = data.Clips(root, hold, "held", augment=False,
                                 gold_held=gold_held, wants=wants,
                                 max_secs=longest)
        total = started + more
        print(f"carrying on from step {started} for {more} more "
              f"({net.size()}, holding back {hold:.0%})")
    elif more:
        raise SystemExit(f"nothing to carry on from at {ckpt}")
    else:
        if kind == "wav2vec":
            net = ENC.build({"drop": min(drop, 0.1),
                             "name": ENC.LARGE if large else ENC.NAME,
                             "train_top": top, "pitch": pitch}).to(device)
            # SpecAugment OFF, and this is not a preference.
            #
            # This checkpoint ships without `masked_spec_embed` -- every load
            # report says MISSING -- so turning masking on substitutes a
            # randomly initialised vector for real frames. Measured over 200
            # steps against an otherwise identical run: 2.21 without it, NaN
            # with it. Layerdrop costs something too (2.21 -> 2.93), so it
            # goes as well. The clips already carry their own noise
            # augmentation, which is masking enough for 26 hours of singing.
            net.body.config.apply_spec_augment = False
            net.body.config.layerdrop = 0.0
            # Activations, not weights, are what does not fit on this card.
            # This is NOT conditional on the batch size, though it was for one
            # run: 8 GB shared with a desktop leaves about 5, a twelve-second
            # clip through a 12-layer transformer spikes past that, and the run
            # died of OOM at step 250 having looked fine in a 20-step test.
            # A third of the speed is the price of finishing.
            net.body.gradient_checkpointing_enable()
            # net.name, not ENC.NAME: with --large the constant is the wrong
            # one, and a run that says it is fine-tuning a model it is not is
            # a log nobody can trust afterwards.
            print(f"fine-tuning {net.name}: {net.size()}")
        else:
            net = M.build({"dim": dim, "blocks": blocks, "drop": drop}).to(device)
            print(f"a new model from noise: {net.size()}")
        total = steps

    net.to(device).train()
    # A pretrained encoder is nudged, not driven: the rate that trains a small
    # model from noise would undo what 960 hours of speech put into this one.
    peak = lr or ((1e-5 if resume else 3e-5) if kind == "wav2vec"
                  else M.scale_lr(net))
    if kind == "wav2vec":
        # TWO rates and a frozen start, both learned the hard way.
        #
        # The first fine-tune trained everything at one rate from step one and
        # collapsed: after 8000 steps it emitted the same distribution at every
        # frame (blank 0.841, min 0.841). The cause is that a randomly
        # initialised head produces meaningless gradients, and those gradients
        # go straight into an encoder that had 960 hours of speech in it. By
        # the time the head is worth listening to, the features it was supposed
        # to read are gone.
        #
        # Proof rather than theory: with the body frozen, the head alone went
        # from 18.9 to 2.07 in 400 steps and decoded 30 characters of a
        # 36-character line. Nothing was wrong with the loss, the targets or
        # the data -- only with letting the body move too early.
        #
        # So the head trains alone for `freeze` steps, and thereafter the body
        # joins at a thirtieth of the head's rate.
        head = [p for n, p in net.named_parameters()
                if n.startswith(("head.", "boundary."))]
        # Only what is still trainable: with --top the lower layers are frozen
        # for good, and handing frozen tensors to AdamW just wastes the state.
        body = [p for n, p in net.named_parameters()
                if not n.startswith(("head.", "boundary.")) and p.requires_grad]
        # 30x only while the head is noise. On a continuation both sides are
        # trained and read the same rate.
        boost = 1.0 if resume else 30.0
        opt = torch.optim.AdamW(
            [{"params": body, "scale": 1.0}, {"params": head, "scale": boost}],
            lr=peak, betas=(0.9, 0.98), weight_decay=0.05)
        if resume:
            freeze = 0
            print(f"carrying on at {peak:.1e}, head and encoder together "
                  f"-- no warm-up, no head multiplier")
        else:
            for p in body:
                p.requires_grad = False
            print(f"the head learns alone for {freeze} steps, then the encoder "
                  f"joins at {peak:.1e} while the head stays at {peak * boost:.1e}")
    else:
        opt = torch.optim.AdamW(net.parameters(), lr=peak, betas=(0.9, 0.98),
                                weight_decay=0.05)
    if more and ckpt.exists():
        try:
            state = torch.load(ckpt, map_location=device, weights_only=False)
            if state.get("optimiser"):
                opt.load_state_dict(state["optimiser"])
        except Exception as exc:
            print(f"  (starting the optimiser fresh: {type(exc).__name__})")

    bag = data.loader(train, batch, True, workers)
    check = data.loader(heldout, batch, False, min(2, workers), augment=False)
    amp = device == "cuda"
    step, t0, running, seen = started, time.monotonic(), [], 0
    opt.zero_grad(set_to_none=True)
    best = min((h["held"] for h in history), default=float("inf"))

    while step < total:
        for mel, lengths, targets, widths, _labels, boundary in bag:
            if step >= total:
                break
            if kind == "wav2vec" and freeze and step == started + freeze:
                for p in body:
                    p.requires_grad = True
                print(f"  step {step}: the encoder is now learning too")
            now = _lr(step - started, total - started, peak,
                      min(1000, (total - started) // 10 or 1))
            for group in opt.param_groups:
                group["lr"] = now * group.get("scale", 1.0)
            mel = mel.to(device, non_blocking=True)
            with torch.autocast("cuda", dtype=torch.bfloat16, enabled=amp):
                logp, boundary_logits = net(mel)
            ins = torch.tensor([net.out_len(int(x)) for x in lengths])
            ctc_loss = torch.nn.functional.ctc_loss(
                logp.float().transpose(0, 1), targets, ins, widths,
                blank=text.BLANK, zero_infinity=True)

            # Both sides trimmed to the shorter. The target's frame count is
            # arithmetic on samples and the model's is its own; for a waveform
            # encoder they can differ by one, and truncating only the target
            # leaves the loss comparing tensors of different length.
            width = min(boundary_logits.shape[1], boundary.shape[1])
            boundary_logits = boundary_logits[:, :width]
            bt = boundary[:, :width].to(device, non_blocking=True)
            valid = (torch.arange(width, device=device)[None, :]
                     < ins.to(device)[:, None])
            mask = valid.unsqueeze(-1)

            # Soft Gaussian targets are sparse. Weight positive regions so the
            # boundary head cannot win by predicting near-zero everywhere.
            # From the BOUNDARY channels alone. The pitch channels are dense
            # -- a note height near 0.5 at almost every frame -- so counting
            # them here would report the sparse targets as common and switch
            # the weighting off.
            edges = min(2, bt.shape[-1])
            pos = bt[..., :edges].sum().clamp_min(1.0)
            neg = (mask.sum() * edges - pos).clamp_min(1.0)
            pos_weight = (neg / pos).clamp(1.0, 20.0)
            # Channels 0 and 1 are the word boundaries and are a yes/no
            # question. Channels 2 and 3, when present, are how high the note
            # is and how much it just moved -- quantities, so absolute error,
            # not cross entropy. Predicting them teaches the body nothing about
            # the lyric and everything about where notes begin, which is the
            # same place syllables begin more often than not.
            per = torch.nn.functional.binary_cross_entropy_with_logits(
                boundary_logits[..., :edges], bt[..., :edges],
                pos_weight=pos_weight, reduction="none")
            boundary_loss = (per * mask).sum() / mask.sum().clamp_min(1.0)
            pitch_loss = torch.zeros((), device=device)
            if bt.shape[-1] > 2 and boundary_logits.shape[-1] > 2:
                said = torch.sigmoid(boundary_logits[..., 2:4])
                gap = (said - bt[..., 2:4]).abs()
                pitch_loss = (gap * mask).sum() / mask.sum().clamp_min(1.0)

            loss = ctc_loss + 0.20 * boundary_loss + 0.10 * pitch_loss
            # Accumulated when the batch that fits on the card is smaller than
            # the batch the model wants. A step is `accum` of these.
            (loss / accum).backward()
            seen += 1
            if seen % accum:
                continue
            torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
            opt.step()
            opt.zero_grad(set_to_none=True)
            running.append(float(loss.detach()))
            step += 1

            if step % every == 0 or step == total:
                mean = sum(running) / len(running)
                running = []
                vloss, acc, sample = _validate(net, check, device)
                rate = (step - started) / max(1e-9, time.monotonic() - t0)
                left = (total - step) / max(rate, 1e-9)
                print(f"  step {step:6}/{total}  loss {mean:6.3f}  "
                      f"held {vloss:6.3f}  heard {acc*100:4.1f}%  "
                      f"{rate:4.1f} steps/s  {left/60:5.1f} min left")
                if sample:
                    print(f"          {sample}")
                history.append({"step": step, "loss": round(mean, 4),
                                "held": round(vloss, 4), "heard": round(acc, 4)})
                kit.save(ckpt, net, step=step, hold=hold, history=history,
                         optimiser=opt.state_dict(), root=str(root),
                         boundary_head=1, gold_by=gold_by,
                         gold_held=sorted(gold_held))
                if vloss < best:
                    best = vloss
                    # Kept, but NOT called "best": measured on eight held-out
                    # songs, the checkpoint with the lowest held-out CTC loss
                    # aligned WORSE than one twice as far into training that had
                    # been overfitting for six thousand steps -- 0.233s typical
                    # error against 0.171s, and a spread three times as wide.
                    # Recognition and alignment are not the same objective:
                    # given the words, a model only has to know where they are.
                    # `sync bench` is the arbiter, not this file.
                    kit.save(ckpt.with_name(ckpt.stem + "-lowloss.pt"), net,
                           step=step, hold=hold, history=history, root=str(root),
                           boundary_head=1)

    M.save(ckpt, net, step=step, hold=hold, history=history,
           optimiser=opt.state_dict(), root=str(root))
    (HOME / "history.json").write_text(json.dumps(history, indent=1),
                                       encoding="utf-8")
    took = (time.monotonic() - t0) / 60
    print(f"done: {step} steps in {took:.0f} min, model at {ckpt}")
    print("Now measure it against real songs:  python -m sync.sync bench")
    return 0
