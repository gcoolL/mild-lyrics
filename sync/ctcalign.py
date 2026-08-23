"""Where each letter was sung: Viterbi through the CTC lattice.

The model says, for every 20 ms frame, how likely each symbol is. The lyric
says which symbols, in which order. Forced alignment is the single best path
that spells the lyric and nothing else -- so a word cannot be placed before the
word in front of it, and a chorus repeated four times cannot have its second
line stolen by its fourth.

The lattice is the usual CTC one: the token sequence with a blank threaded
between every pair and at both ends, a path that may stay where it is, step
forward one, or skip a blank to reach the next token when the two tokens
differ. Maximum instead of sum, because the question is where the words are,
not how likely they were.

Backpointers are the whole cost: two floats wide at any moment, but one byte
per (frame, lattice position) for the trace, which for a long song and a wordy
lyric is hundreds of megabytes. So they are written a thousand frames at a
time and pushed to main memory as they go, which is why a ten-minute song
aligns on a card with a gigabyte free.
"""
from __future__ import annotations

import torch

from . import audio, text

NEG = -1e9

# How loud a flux peak has to be to count as a new syllable rather than the
# ripple of a note being held. Vibrato inside the sustain of "all" measured
# 0.22-0.39; the attack that began it measured 0.67.
STRONG = 0.50

# How much of the model's own label prior to divide out before searching. See
# levelled() -- 0 is the raw posterior, 1 is a full division.
PRIOR = 0.8


def levelled(logp, alpha: float = PRIOR):
    """The emissions with the model's own label prior divided out.

    CTC trains a model to be PEAKY: nearly every frame comes back blank, with
    a narrow spike where a letter is certain. That is fine for reading a
    transcript off the argmax and quietly ruinous for alignment. Measured on
    this model, blank sits at 0.91 through frames where the reference says a
    word is being sung -- so the path can idle in blank almost for free and
    the few frames that actually decide where a word lands are chosen by
    noise. Songs whose vocals the model hears less well are exactly the ones
    where that noise wins, which is why the failures were not near misses but
    whole songs sliding tens of seconds.

    The correction is the old hybrid-ASR one: score a frame by how much more
    likely a label is here than it is ON AVERAGE, log p(k|x) - a*log p(k),
    with the prior taken from THIS SONG's own emissions rather than a constant
    baked in at training time. Per song matters -- a quiet acoustic track and a
    wall-of-guitars track have very different blank rates, and a fixed number
    tuned on one is wrong for the other. It also means a retrained model, which
    will be peaky to its own degree, needs no new constant here.

    Measured on the held-out songs: the songs that were already right moved by
    a few milliseconds, and songs that were seconds out came back. See the
    bench report from the day this landed.
    """
    if alpha <= 0:
        return logp
    return logp - alpha * _prior(logp)


def _prior(logp):
    """log p(k), each label's average posterior over whatever it is given."""
    return logp.exp().mean(dim=0).clamp_min(1e-8).log()


def path(logp, tokens: list[int], device: str | None = None,
         chunk: int = 1024, raw=None,
         hold: list[int] | None = None) -> list[tuple[int, int, float]]:
    """One (first frame, last frame, score) per token, in order.

    `logp` is (frames, classes) log-probabilities and `tokens` the token ids to
    spell. Score is the mean probability the model gave that token over the
    frames the path spent on it -- low means the path had to put it somewhere
    it could not hear it, which is exactly the word a caller should doubt.
    """
    if not tokens:
        return []
    device = device or ("cuda" if logp.is_cuda else "cpu")
    logp = logp.to(device)
    T = logp.shape[0]
    # HOW LONG A TOKEN MUST LAST. `hold[i]` copies of token i are threaded into
    # the lattice instead of one, so the path has to spend a frame on each copy
    # and the token cannot be crossed in less than hold[i] frames. Nothing in
    # the recurrence changes; the constraint is entirely in the shape of `ext`.
    #
    # This is what stops a line being crushed to reach the next one it is sure
    # of. Measured on Krantenwijk: eleven words squeezed into 1.76s, one of
    # them 0.04s long, to arrive at a line the model could hear -- and a 40 ms
    # word does not exist. Across 27,736 words the user timed by hand, 0.03%
    # are under 40 ms and 0.12% under 60 ms, so a floor there forbids almost
    # nothing a human would write.
    held = [max(1, m) for m in (hold or [1] * len(tokens))]
    places: list[list[int]] = []
    layout = [text.BLANK]
    for tok, many in zip(tokens, held):
        places.append(list(range(len(layout), len(layout) + many)))
        layout += [tok] * many + [text.BLANK]
    ext = torch.tensor(layout, dtype=torch.long, device=device)
    S = ext.shape[0]
    # A duplicate copy is not a place the path may enter from outside: only the
    # FIRST copy of a token can be reached by skipping the blank before it.
    opens = torch.zeros(S, dtype=torch.bool, device=device)
    opens[torch.tensor([run[0] for run in places], device=device)] = True
    need = sum(held)
    if T < need:
        raise ValueError(f"{T} frames cannot hold {len(tokens)} symbols "
                         f"-- the audio is shorter than the words")

    # A skip is allowed only into a token that differs from the one two back;
    # otherwise the blank between two identical letters is what keeps them apart.
    #
    # `opens` matters and is not redundant: for the SECOND copy of a token the
    # position two back is the blank before the run, so the plain rule would
    # call that a legal skip and let the token be crossed in one frame after
    # all -- which is the whole thing this is here to prevent. From the third
    # copy on the plain rule refuses by itself.
    can_skip = torch.zeros(S, dtype=torch.bool, device=device)
    can_skip[2:] = ((ext[2:] != text.BLANK) & (ext[2:] != ext[:-2])
                    & opens[2:])

    # The (frames, lattice) score matrix is deliberately NOT built: for a wordy
    # four-minute song it is a third of a gigabyte of VRAM that is read once,
    # in order. One row is gathered per step instead.
    alpha = torch.full((S,), NEG, device=device)
    alpha[0] = logp[0, ext[0]]
    if S > 1:
        alpha[1] = logp[0, ext[1]]

    traces, buf, at = [], torch.empty((chunk, S), dtype=torch.uint8,
                                      device=device), 0
    for t in range(1, T):
        one = torch.cat([alpha.new_full((1,), NEG), alpha[:-1]])
        two = torch.cat([alpha.new_full((2,), NEG), alpha[:-2]])
        two = torch.where(can_skip, two, torch.full_like(two, NEG))
        stacked = torch.stack([alpha, one, two])
        best, back = stacked.max(dim=0)
        alpha = best + logp[t, ext]
        buf[at] = back.to(torch.uint8)
        at += 1
        if at == chunk:
            traces.append(buf.cpu())
            buf, at = torch.empty_like(buf), 0
    if at:
        traces.append(buf[:at].cpu())
    back = (torch.cat(traces, dim=0).numpy() if traces
            else torch.empty((0, S), dtype=torch.uint8).numpy())

    # Ending on the last token or on the blank after it, whichever the model
    # preferred -- both spell the lyric exactly.
    s = int(S - 1 if S == 1 or alpha[S - 1] >= alpha[S - 2] else S - 2)
    where = [0] * T
    for t in range(T - 1, 0, -1):
        where[t] = s
        s -= int(back[t - 1][s])
    where[0] = s

    # One pass over the path, not one pass per token: a wordy song has
    # thousands of tokens and twelve thousand frames, and asking each token to
    # scan the whole path turns a two-second job into a minute of Python.
    first = [-1] * S
    last = [-1] * S
    reached = [T - 1] * S
    seen = 0
    for t, s in enumerate(where):
        if first[s] < 0:
            first[s] = t
        last[s] = t
        while seen <= s:
            reached[seen] = t
            seen += 1

    prob = (logp if raw is None else raw.to(logp.device)).exp().cpu()
    ids = ext.cpu().tolist()
    spans: list[tuple[int, int, float]] = []
    for k in range(len(tokens)):
        # Over the whole RUN of copies, not one position: with a minimum
        # duration a token owns several lattice positions, and its span runs
        # from the first frame any copy was reached to the last frame any copy
        # still held.
        run = places[k]
        got = [q for q in run if first[q] >= 0]
        pos = run[0]
        if got:
            a = min(first[q] for q in got)
            b = max(last[q] for q in got)
            spans.append((a, b, float(prob[a:b + 1, ids[pos]].mean())))
        else:
            # The path stepped over it inside one frame. It still happened, at
            # the frame the path was on when it passed -- never dropped, or the
            # caller's words and these spans stop lining up.
            near = reached[pos]
            spans.append((near, near, 0.0))
    return spans


def words(logp, items: list[str], device: str | None = None,
          boundary=None, alpha: float = PRIOR, prior_from=None,
          present=None, gate: float = 0.0,
          onset=None, attack: float = 0.0,
          floor: float = 0.0, sustain: float = 0.0) -> list[dict]:
    """Time every word of a lyric against `logp`.

    Returns one row per word the alphabet could spell: its index in `items`,
    its start and end in seconds, and the path's confidence in it. Words it
    could not spell -- a bare bracket, a script with no romanisation -- are
    absent, and the caller fills them in from their neighbours.
    """
    tokens, spans = text.spell(items)
    if not tokens:
        return []
    # Searched on the levelled emissions, scored on the raw ones: `score` has
    # to keep meaning "how sure was the model", because offset.summarise and
    # the benchmark's trust gate both read it.
    # `prior_from` is for callers timing a few words inside a WINDOW of a song
    # -- an ad-lib under its line. A four-second window has no meaningful label
    # prior of its own; taken there, the correction would be measuring whatever
    # happens to be sung in those four seconds. The song's own emissions are
    # passed instead.
    emissions = (levelled(logp, alpha) if prior_from is None
                 else logp - alpha * _prior(prior_from))
    # What the AUDIO says about where the singing is, if the caller measured
    # it. On a separated vocal a quiet frame really is a frame with no singing
    # in it, and the lattice has no other way to know: crossing an instrumental
    # it can only idle in blank, and idling is cheap. See sync/vocal.py.
    if present is not None and gate > 0:
        from . import vocal
        emissions = vocal.gate(emissions, present, gate)
    # The duration floor is a per-WORD minimum, not a per-character one: it is
    # put on each word's FIRST character and nowhere else. A uniform floor
    # would make a nine-letter word last nine times as long as the shortest
    # allowed word, which is not a claim anybody wants to make, and would push
    # the same minimum into the SPACE between words -- forcing a gap of silence
    # into every join.
    hold = None
    if floor > 0:
        k = max(1, int(round(floor / audio.FRAME)))
        hold = [1] * len(tokens)
        for _i, begins, _ends in spans:
            hold[begins] = k
    marks = path(emissions, tokens, device, raw=logp, hold=hold)
    bprob = None
    if boundary is not None:
        bprob = torch.sigmoid(torch.as_tensor(boundary).float()).cpu()
        if bprob.ndim != 2 or bprob.shape[0] != logp.shape[0] or bprob.shape[1] < 2:
            bprob = None
    out = []
    for at, (i, first, last) in enumerate(spans):
        a, b = marks[first], marks[last]
        score = sum(m[2] for m in marks[first:last + 1]) / (last - first + 1)

        # ---- where the word STARTS ---------------------------------------
        # The model has emitted word-start evidence at every frame since the
        # boundary head was added (model.py:84, channel 0) and NOTHING has
        # ever read it -- only channel 1, for ends. The Viterbi start is where
        # the first character became most likely, which is a little after the
        # sound begins, because that is what CTC is trained to do.
        #
        # The audio's own attack is the other half. Both are only ever allowed
        # to pull the start EARLIER, never later, and never past the previous
        # word's end: the search already found a start that spells the lyric,
        # and this refines it rather than second-guessing it.
        start_frame = a[0]
        if (bprob is not None or onset is not None) and attack > 0:
            floor = (marks[spans[at - 1][2]][1] + 1) if at else 0
            lo = max(floor, a[0] - int(round(attack / audio.FRAME)))
            if a[0] > lo:
                votes = torch.zeros(a[0] - lo + 1)
                if bprob is not None and bprob.shape[1] > 0:
                    q = torch.as_tensor(bprob[lo:a[0] + 1, 0]).float()
                    votes = votes + torch.log(q.clamp(1e-5, 1 - 1e-5)
                                              / (1.0 - q.clamp(1e-5, 1 - 1e-5)))
                if onset is not None:
                    f = torch.as_tensor(onset).float().cpu()
                    if f.shape[0] > lo:
                        f = f[lo:a[0] + 1]
                        if f.shape[0] < votes.shape[0]:
                            f = torch.cat(
                                [f, f[-1:].expand(votes.shape[0] - f.shape[0])])
                        votes = votes + 2.0 * f
                weights = torch.softmax(votes / 0.75, dim=0)
                frames = torch.arange(lo, a[0] + 1, dtype=torch.float32)
                centre = float((frames * weights).sum().item())
                start_frame = int(round(max(float(lo), min(centre, float(a[0])))))

        # ---- a word that is HELD ---------------------------------------
        # CTC puts a letter where it is most certain of it, and for a vowel
        # held for a second that is somewhere inside the note, not at its
        # start. Measured on "Guilty All the Same": the word "all" begins on a
        # clear attack at 95.78s and was placed at 96.30s, half a second late,
        # with unbroken singing across the gap. The 0.12s the ordinary start
        # refinement reaches cannot cross that.
        #
        # Reaching further is only safe for a SUSTAIN, and a sustain is
        # recognisable: one strong attack, then the weak periodic flux of
        # vibrato. A run of syllables -- a rapped bar, where the vocal is just
        # as continuously loud -- has strong attacks all the way through, and
        # those block the reach. Without that test this would drag every word
        # in a dense verse back onto its neighbour.
        if (sustain > 0 and onset is not None and present is not None
                and start_frame > 0):
            flux = torch.as_tensor(onset).float().cpu()
            live = torch.as_tensor(present).float().cpu()
            back = max(floor if at else 0,
                       start_frame - int(round(sustain / audio.FRAME)))
            found = None
            for f in range(back, start_frame):
                if flux[f] < STRONG or flux[f] < flux[max(0, f - 2):f + 3].max():
                    continue
                held = live[f:start_frame + 1]
                between = flux[f + 1:start_frame]
                if held.numel() and float(held.min()) < 0.5:
                    continue            # the singing stops -- not one note
                if between.numel() and float(between.max()) >= STRONG:
                    continue            # another syllable started -- not held
                found = f
                break
            if found is not None and (start_frame - found) * audio.FRAME >= 0.15:
                start_frame = found

        end_frame = b[1]
        if bprob is not None and b[1] + 1 < logp.shape[0]:
            # The boundary head is a distribution over possible end frames, not
            # a one-frame answer. Treating its argmax as the endpoint makes a
            # narrow early spike win even when a word remains active afterwards.
            #
            # Combine:
            #   1. boundary-head end evidence,
            #   2. final-character posterior tail,
            # then take the weighted center of that local distribution.
            #
            # The next word is only a ceiling against overlap. A long gap after
            # this word therefore remains a long gap; it cannot pull the current
            # word's endpoint towards the next lyric.
            # `at`, not `i`: `i` is the word's index into the CALLER's list
            # and `spans` holds only the words the alphabet could spell. The
            # two agree until a lyric contains something unspellable -- a
            # punctuation-only word, a line of kana -- and from that word on,
            # `spans[i + 1]` was some later word's span or, past the end,
            # nothing at all, which quietly removed the overlap ceiling and
            # let an endpoint run 0.5s into the next word.
            ceiling = (marks[spans[at + 1][1]][0] - 1
                       if at + 1 < len(spans) else logp.shape[0] - 1)
            lo = b[1]
            hi = min(ceiling, b[1] + int(round(0.5 / audio.FRAME)))

            if hi > lo:
                token_id = tokens[last]
                token = logp[lo:hi + 1, token_id].exp().cpu()
                token = token / token.max().clamp_min(1e-6)

                p = torch.as_tensor(bprob[lo:hi + 1, 1]).float()
                p = p.clamp(1e-5, 1 - 1e-5)
                elogit = torch.log(p / (1.0 - p))

                tscore = torch.log(token.clamp_min(1e-5))

                # Soft temperature: don't let one 20 ms boundary spike decide
                # the endpoint by itself.
                candidate = elogit + 0.35 * tscore
                weights = torch.softmax(candidate / 0.75, dim=0)

                frames = torch.arange(lo, hi + 1, dtype=torch.float32)
                center = float((frames * weights).sum().item())
                end_frame = int(round(max(float(lo), min(center, float(hi)))))

        # Character spans remain exact Viterbi spans. Only the word endpoint
        # is boundary-refined; generate.py propagates that to the final syllable.
        out.append({"i": i, "word": items[i],
                    "start": audio.seconds(start_frame),
                    "end": audio.seconds(end_frame + 1),
                    "score": round(float(score), 4),
                    "chars": [(audio.seconds(s), audio.seconds(e + 1))
                              for s, e, _p in marks[first:last + 1]]})
    return out


def greedy(logp) -> str:
    """What the model heard with nothing to guide it -- for reading the loss."""
    return text.decode(logp.argmax(dim=-1).tolist())
