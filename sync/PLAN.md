# The from-scratch aligner, as it actually works

This is the brief for "build a lyrics-to-audio forced aligner from scratch, on
polyphonic audio, no Whisper and no wav2vec2" — rewritten against what is in
this repository, what has been measured here, and what the original plan gets
wrong. Every section says three things: **what the brief asked for**, **what is
actually true**, and **where the code is**.

The short version: eight of the brief's steps already exist and are better than
the brief's version of them; two of them are wrong in ways that break a whole
song rather than a word; and one thing the brief never mentions — the peaky-CTC
correction — is the difference between 0.06 s of error and 20 s of it.

---

## 0. What is already here

| the brief's step | this repo | status |
|---|---|---|
| log-mel feature pipeline | `sync/audio.py` | done, and fixed by arithmetic |
| character tokenizer with a blank | `sync/text.py` | done, 29 symbols |
| `Dataset` + `collate_fn` | `sync/data.py` | done, plus a song-level split |
| the acoustic model | `sync/model.py` | done — **not** a CRNN, see §2 |
| CTC training loop | `sync/train.py` | done, resumable |
| forced alignment | `sync/ctcalign.py` | done — Viterbi, **not** DTW, see §4 |
| TTML output | `sync/generate.py` | done, this project's own shape |
| measurement | `sync/bench.py` | done, seconds against human timings |

So the work is not "write the pipeline". The work is: **the model that ships is
a wav2vec2 fine-tune, and the brief forbids that.** `sync/encoder.py` holds it,
and every checkpoint in `~/.cache/mild-lyrics/sync/syncnet-w2v-*.pt` is one. The
from-scratch model in `model.py` exists and works, but the only checkpoints it
ever produced are from the stem era (16 Aug), trained on separated vocals, which
is the input this project no longer uses. **There is no from-scratch model
trained on the mixture corpus.** That is what §6 is doing about it.

---

## 1. Data pipeline — the brief's sources are the wrong ones

**Asked for:** DALI (word-level) and JamendoLyrics.

**Actually:**

*DALI* does not ship audio. It ships YouTube ids, a good share of which are dead
or now point at a different upload, and a copy fetched today is not necessarily
the master its timings were written against — which is the single worst failure
mode in this task and the one §1.3 exists for. Its word timings are also not
hand-made; they come from a teacher-student loop over karaoke files, so they
carry error of their own. They are fine to *train* on (CTC never reads a
timestamp — §3) and unfit to *measure* against.

*JamendoLyrics* is 20 songs, about 80 in the multilingual 2023 set. That is a
benchmark, not a training set, and it is a benchmark on Creative Commons audio
that sounds nothing like the loudness-war masters this player is pointed at.

**What this project trains on instead**, and it is more than either:

- **326 community TTMLs from Spicy Lyrics** (`source: spl`) — syllable-timed by
  people, snapshotted out of the player's own cache into
  `~/.cache/mild-lyrics/sync/spl`. `sync/dataset.py:snapshot`.
- **247 Apple Music word-synced lyrics** (`aml`), kept in a *separate directory*
  — training reads both, the benchmark reads only `spl`. The split is
  structural rather than a flag because these two were mixed once already (149
  of 376 documents were Apple's and nothing told them apart).
- **36 hand-timed TTMLs** at the repo root, timed against the master by one
  hand. These are worth more as a benchmark than as training material:
  a reference set with one convention throughout can see below the 0.05–0.10 s
  disagreement *between* annotators, which is where this model now lives.
  `data.gold_split` counts out a quarter of them and never trains on those.

Currently cut: **567 songs, 28,873 line clips, 26.3 hours**, at
`~/.cache/mild-lyrics/sync/dataset` (`meta.json` records `stem: false`).

### 1.1 Audio features — `sync/audio.py`

The brief is right about log-mel and torchaudio, and misses two things.

- **80 bands, 25 ms window, 10 ms hop, 16 kHz mono.** The model folds two
  frames into one, so every answer this project ever gives is a multiple of
  **20 ms**. These are constants, not checkpoint fields, deliberately: change
  one and every checkpoint ever trained becomes unreadable.
- **Normalise per clip, not per corpus.** A song's loudness, its mastering and
  the codec it arrived through move the whole spectrogram up or down together,
  and none of that is information about where the words are. Per-clip mean and
  standard deviation is what lets a bedroom recording and a loudness-war master
  look the same to the model.

The brief's "polyphonic, unseparated" instinct is right and this project agrees
for a reason it measured: demucs is cleaner but it *invents* — smearing and
phantom onsets exactly where a quiet consonant sits under a cymbal — and a
timing model taught on those artefacts learns to time the artefact. `--stem` is
available and off everywhere.

### 1.2 Tokenizer — `sync/text.py`

The brief says a–z, space, `<blank>`. That alphabet cannot spell `don't`,
`café`, or anything in kana. Actual alphabet, 29 symbols: **blank at index 0**,
`|` for space, a–z, and the apostrophe. `flatten()` does NFKD and strips
combining marks so `café` → `cafe` rather than `caf`, normalises the three
typographic apostrophes to one, and hands anything in another script to the
player's romaniser — a Japanese song is otherwise not a hard example but an
empty one.

The part the brief has no equivalent of, and needs one: **`spell()` returns the
token sequence *and* a map from each word to its token span.** Without that
there is no way back from a frame to a word, and word-level TTML is the entire
deliverable. Words the alphabet cannot hold are simply absent from the spans
rather than shifting every word after them by one.

### 1.3 The thing the brief has no idea about: offset

**About a quarter of fetched copies are displaced against the master the lyric
was timed on.** A clip cut 200 ms early is survivable (§3); a clip cut two
seconds early has its words outside the clip, and CTC cannot forgive that — it
teaches the model that those words sound like whatever *is* in the clip.

Two defences, in `sync/offset.py`, one sign convention (positive lag = the copy
is late):

1. a length-and-silence check that needs nothing trained, run on every song;
2. once a model exists, align the whole song and take the median difference
   against the reference — gated on its own spread, so a song whose errors are
   scattered is recorded *not trusted* and cut exactly where it always was.

A wrong shift is worse than no shift. (Guessing the shift from loudness peaks
was tried here and came out sign-flipped on a good few songs. It is not done.)

### 1.4 Dataset and collate — `sync/data.py`

`Clips` and `batches` do what the brief asks — pad the mels, concatenate the
CTC targets, return both length tensors — plus four things the brief omits and
would be wrong without:

- **The split is by song, and by a hash of the song's *name*.** Lines from one
  song share a voice, a mix and half their words; a clip-level shuffle measures
  memorisation. A name hash also does not move when the corpus grows, so a model
  trained last week and one trained tonight stay comparable.
- **A clip must be long enough to hold its own label.** CTC cannot spell twelve
  symbols in six frames and a batch containing one such clip is a batch with no
  gradient. Checked with room to spare, because the tempo augmentation may
  shorten it by a further 11%.
- **Augmentation aimed at a measured failure**, not at a list: SpecAugment,
  tempo stretch, and `distract()` — another song mixed underneath at 4–18 dB
  SNR, half the time. That last one is there because over 31 blocks of five or
  more consecutively lost words, the model scored the words *higher where the
  aligner wrongly put them* than where the reference says they are, in 25 of the
  31. The words were audible. The rest of the band simply scored better
  somewhere else.
- **A boundary target beside the CTC target**: word starts and word ends as two
  soft Gaussian channels, 80 ms sigma, on the same 20 ms grid. See §2.

---

## 2. Architecture — the brief's CRNN is the wrong shape

**Asked for:** 2D convs with max-pooling to downsample time, then a Bi-LSTM,
then a linear layer to `vocab+1` and log-softmax.

Two of those are actively harmful here.

### 2.1 Max-pooling the time axis throws away the deliverable

The output *is* time. A CRNN that pools 4× over time has a best-possible answer
of 80 ms on a task whose references are written to about 50 ms, and no amount of
alignment cleverness downstream recovers it. This project reduces time exactly
once — a stride-2 in the stem — and never again. Everything after runs at 20 ms
per frame, which is fine enough that a listener cannot hear the quantisation and
coarse enough that a four-minute song is 12,000 frames rather than 4 million
samples.

### 2.2 The Bi-LSTM has a train/test seam that a convolution does not

The clips it learns from are four seconds long. The songs it is asked about are
four minutes. A recurrent layer trained on 200 timesteps and run on 12,000 is
being asked about a regime it has never seen, and its state has no bounded
horizon — there is no window size that is provably enough, so a long song
cannot be chunked without the joins showing.

Every layer here is a convolution, so a frame is judged by the second and a half
of sound around it and by nothing else. The model **cannot tell where in a song
a frame sits, and therefore cannot be wrong about it.** Train on lines, run on
songs, no seam. `SyncNet.context()` returns the exact receptive field in output
frames — real arithmetic, not a guess — and `emit()` uses it to trim window
edges, so windowed inference over a ten-minute song is bit-identical in the
interior to running it whole.

### 2.3 What the model actually is — `sync/model.py`

**SyncNet, 5.6M parameters:**

```
stem      Conv1d(80 → dim, k=5, stride=2) → GELU → Conv1d(dim, dim, k=5)
body      12 × residual block:
            LayerNorm
            depthwise Conv1d(k=9, dilation ∈ 1,2,4,8 repeating)  — mixes time
            Linear(dim → 2·dim) → GELU → Linear(2·dim → dim)     — mixes bands
            residual scaled by a learned per-channel gate init'd at 1e-3
norm      LayerNorm
head      Linear(dim → 29) → log_softmax        CTC posteriorgram
boundary  Linear(dim → 2)                       word-start / word-end logits
```

Depthwise-separable is cheap where the cost would otherwise be and expensive
where the capacity is wanted. The dilation cycle reaches ±1.5 s in twelve blocks
without ever pooling. The residual gate starting at 1e-3 means a fresh block
passes its input through untouched and has to earn every change it makes, which
is why a 12-deep stack trains from noise with no tricks.

**The boundary head is not in the brief and the deliverable needs it.** CTC tells
you where a symbol is most *certain*, which is a little after the sound starts
and says nothing at all about where a word *stops*. Word ends in a TTML come
from this head, trained on soft Gaussian targets against the human timings, with
positive-class weighting because a 5-frame bump in a 200-frame clip is a target
a head can win by ignoring.

---

## 3. Training and CTC loss — right in outline, thin on the traps

The brief's account of CTC is correct: the loss sums over every alignment that
spells the target after collapsing repeats and dropping blanks, so the model is
never told *where* a symbol goes, only that the sequence appears in order.

**Why that choice is what makes this project possible:** the loss never reads
the label's times. A line whose words sit 200 ms from where a stranger's TTML
claimed is still a correct training example. Training on other people's timings
is therefore sound rather than circular — and the only thing it cannot absorb is
a line cut so far off that its words fall outside the clip, which is §1.3.

Shapes, since the brief asks for them explicitly:

```python
logp, edge = net(mel)                      # (B, T_out, 29), (B, T_out, 2)
ins = torch.tensor([net.out_len(int(x)) for x in lengths])   # NOT mel lengths
loss = F.ctc_loss(logp.float().transpose(0, 1),   # (T, B, C) — time first
                  targets,                         # 1-D, all clips concatenated
                  ins, widths,                     # input / target lengths
                  blank=text.BLANK, zero_infinity=True)
```

`out_len()` is the model's own answer for how many output frames `n` mel frames
become. Passing the mel length instead is the single most common way to get a
loss that trains to a plausible number and aligns to nothing.

Four things learned the hard way, all in `sync/train.py`:

- **Warm-up is not optional.** A fresh CTC head at full learning rate collapses
  to all-blank within a hundred steps and never comes back out. Linear warm-up,
  then cosine.
- **`zero_infinity=True`**, or one impossible clip poisons the batch.
- **Never overwrite a good checkpoint with a diverged one.** `model.save`
  refuses to write when any tensor is non-finite. A continuation went NaN and
  wrote itself over a model that had taken an hour; the moment of writing is the
  only place where the old file still exists.
- **The held-out loss is not the objective.** Benchmarked at 6k / 12.5k / 20.5k
  steps, this model measured 0.233 / 0.171 / 0.194 s of alignment error *while
  the held-out CTC loss rose the whole way*. Recognition and alignment are not
  the same objective: given the words, a model only has to know where they are.
  `sync bench` decides, in seconds. The loss does not.

The combined objective is `ctc + 0.20·boundary` (plus optional pitch and
line-start terms that only the waveform encoder has heads for).

---

## 4. Inference and forced alignment — DTW is the wrong algorithm

**Asked for:** "DTW or CTC-segmentation".

**DTW does not apply.** Dynamic time warping aligns two sequences *of the same
kind* — it needs a reference feature sequence to warp against, and there isn't
one: one side here is a `(frames × 29)` probability matrix and the other is a
list of token ids. The right algorithm is **Viterbi through the CTC lattice**,
which is what CTC-segmentation is a variant of, and it is already written:
`sync/ctcalign.py`.

The lattice is the usual one — the token sequence with a blank threaded between
every pair and at both ends; a path may stay, step forward one, or skip a blank
to reach the next token when the two tokens differ — with **max instead of sum,
because the question is where the words are, not how likely they were.** A word
therefore cannot be placed before the word in front of it, and the second line
of a four-times chorus cannot be stolen by the fourth.

Cost is all in the backpointers: two floats wide at any moment, but one byte per
(frame, lattice position) for the trace, which for a long song and a wordy lyric
is hundreds of megabytes. They are written a thousand frames at a time and
pushed to host memory as they go — which is why a ten-minute song aligns on a
card with a gigabyte free.

### 4.1 The correction the brief has never heard of, and it is the big one

**CTC trains a model to be peaky.** Nearly every frame comes back blank with a
narrow spike where a letter is certain. Measured on this model, blank sits at
**0.91 through the frames where the reference says a word is being sung.** A
path that can idle in blank almost for free is then decided by noise in the few
frames that are left — and the failure that produces is not a near miss, it is a
whole song sliding tens of seconds. The two worst rows of the last benchmark are
15.7 s and 24.4 s of mean error; that is this, not a bad model.

So `ctcalign.levelled` scores a frame by how much more likely a label is *here*
than it is on average:

```
score(k, t) = log p(k | x_t) − α · log p(k),    α = 0.8
```

with the prior `p(k)` taken from **that song's own emissions**, not a constant
baked in at training time. Per-song matters: a quiet acoustic track and a
wall-of-guitars track have very different blank rates, and a retrained model is
peaky to its own degree, so nothing here needs retuning when either changes.

The search runs on levelled emissions; **word confidence is still read off the
raw ones**, because "how sure was the model" has to keep meaning that.

### 4.2 Minimum duration

`path(..., hold=[...])` threads `hold[i]` copies of token `i` into the lattice,
so a token cannot be crossed in fewer than that many frames. This is what stops
a line being crushed to reach the next line the model is sure of — measured on
one song, eleven words squeezed into 1.76 s, one of them 0.04 s long. Across
27,736 hand-timed words, 0.03% are under 40 ms, so a floor there forbids almost
nothing a person would actually write.

### 4.3 TTML

`sync/generate.py` already writes this project's TTML shape — per-word `<span>`
with `begin`/`end`, agents, ad-libs peeled out of brackets, syllable splits from
`text.syllables` for the karaoke sweep. Times are `MM:SS.mmm`, or `H:MM:SS.mmm`
past the hour (`spicy_lyrics.ttml_ts`). Two notes the brief would need if it
were writing this from nothing:

- **word starts and word ends come from different places, and from different
  heads.** A start is the Viterbi frame, then pulled *earlier only* — never
  later, never past the previous word's end — by a softmax vote between
  boundary channel 0 and the audio's own onset flux, reaching back 0.12 s
  (further, up to 0.8 s, when the note is held). An end is boundary channel 1.
  Using the next word's start as this word's end is the naive thing and it
  produces a karaoke sweep that never rests.
- **the model runs late.** CTC puts a symbol where it is surest of it, which is
  after the sound begins. `bench --calibrate` measures that standing bias — last
  measured +0.030 s — and stores it in the checkpoint so every file written
  afterwards has it taken off.

---

## 5. Measuring it — the part the brief leaves out entirely

A forced aligner cannot be evaluated by its loss (§3) and cannot be evaluated by
its median error either: `sync bench` reports mean, p90, worst-30, and the share
of words more than a second from where their own song sits, because a song can
have a 0.05 s median and a 40-word run of the chorus attached to the wrong
verse. In the last full run, **28 of 30 songs looked good by median and 14 of 30
were actually clean.** That gap is the reason the table has the columns it has.

References were typed by people against a master and carry their own error at
0.05–0.10 s. A song inside that is as good as this measurement can say.

---

## 6. What was done, and what it measured

**The gap this plan set out to close: there was no from-scratch model trained on
the mixture corpus.** The from-scratch path was last trained on separated vocals
on 16 August, before separation was turned off everywhere; the models that ship
today are wav2vec2 fine-tunes, which the brief forbids.

So one was trained, 2026-09-06 — 5.6M parameters, ~26,000 clips, from noise —
and then improved. Every row below is the same 41 held-out songs, 14,198 words,
and the only arbiter is the mean; `heard` is character accuracy with no lyric to
guide it, on held-out songs.

| model | recipe | mean | p90 | usable | clean | adrift | ends | heard |
|---|---|---|---|---|---|---|---|---|
| `scratch-base.pt` | 20k mixture | 2.484 s | 6.378 | 8/41 | 3/41 | 23.0% | 0.160 s | 6.3% |
| `scratch-rebal.pt` | 20k, `--rebalance` | 3.134 s | 8.534 | 6/41 | 1/41 | 26.9% | 0.229 s | 6.2% |
| `scratch-long.pt` | 40k mixture | 2.230 s | 5.640 | 13/41 | 5/41 | 17.3% | — | 8.3% |
| **`scratch-stemfirst.pt`** | **20k stem → 20k mixture** | **1.760 s** | **4.387** | **15/41** | 3/41 | **16.2%** | **0.127 s** | 7.1% |
| `scratch-sf60.pt` | 20k stem → 40k mixture | 1.976 s | 5.565 | 12/41 | 5/41 | 18.5% | — | 6.3% |
| `scratch-sf40.pt` | 40k stem → 20k mixture | 1.833 s | 4.802 | 14/41 | 4/41 | 16.2% | 0.124 s | — |
| `scratch-mix.pt` | 20k, contaminated split | 2.390 s | 6.951 | 11/41 | 1/41 | 23.1% | 0.146 s | 6.0% |

**What moved it, in order of how much.**

*The order of the corpus, not its size.* Training 20,000 steps on the separated
cut and then carrying the same weights on to the mixture beats 40,000 steps of
mixture alone — 1.760 s against 2.230 s — on a run with HALF the mixture steps.
It also beats it on p90 (4.387 against 5.640), on usable songs, on drift, and on
word ends; the one column it loses is clean songs, 3 against 5. Its standing
bias is +0.008 s, which is very nearly unbiased before calibration is applied at
all.

Nothing is borrowed here: both stages are this project's own model from noise,
on this project's own clips, and the stem cut is the same 28,915 lines as the
mixture cut, sample-aligned. What the first stage buys is a model that can
already spell what a voice is doing before it is asked to find that voice under
a band. `heard` ends LOWER than the 40k mixture run (7.1% against 8.3%) while
aligning much better, which is this project's oldest lesson restated: given the
words, a model only has to know where they are.

*Length, second, and only on the mixture-only path.* 20k → 40k of mixture alone
moved every column the right way (2.484 → 2.230). But the same trick applied
AFTER the curriculum makes it worse: 20k stem → 40k mixture measures 1.976 s
against the 1.760 s of 20k → 20k, losing three usable songs and 2.3 points of
drift while gaining two clean ones. So the second stage saturates early, and
the room that is left — if there is any — is in the first. That is what
`scratch-sf40.pt` (40k voice → 20k band) is testing.

*`--rebalance`, not at all.* Rebuilding each clip at 0.7–2× its own
accompaniment measured worse on every column. It samples balances uniformly
from step zero, so there is no stage at which the voice is clear — which is
precisely what the curriculum provides, and is the most likely reason one works
and the other does not. The annealed version of it (start vocal-heavy, end at
the released balance) is the obvious next test and has not been run.

*A trap worth writing down.* `--workers 4` costs about 2.7 GB of RSS per worker
on this machine, and `train.run` builds two loaders — the training one at
`--workers` and the hold-out one at `min(2, workers)` — so the flag's real cost
is six worker processes and roughly 11 GB. Three runs were killed for system
memory before this was noticed. `--workers 2` costs little throughput at batch
8, because computing a mel is cheap next to reading the clip.

*The length of the first stage does not matter; its existence does.* Doubling
it — 40k voice → 20k band — measures 1.833 s against 1.760 s, which is inside
the run-to-run wobble on the mean. Underneath it trades: displaced songs halve
(5 → 2) and clean songs go 3 → 4, while usable goes 15 → 14. So 20k of voice is
enough, and the curriculum's value is in happening at all.

*The search is not the lever, and this is now measured rather than assumed.*
`alpha` was tuned on the wav2vec2 model, and `ctcalign.levelled`'s docstring is
explicit that a retrained model is peaky to its own degree — so it was swept for
this one, on the emissions in `sync/jar/`, no GPU and no song heard again:

| alpha | 0.5 | 0.65 | 0.8 (shipped) | 0.95 | 1.1 |
|---|---|---|---|---|---|
| mean | 1.765 | 1.740 | 1.762 | 1.688 | 2.162 |
| usable | 15/41 | 15/41 | 15/41 | 15/41 | 11/41 |

Flat across 0.5–0.95 with identical usable counts, then a cliff. The 1.688 at
0.95 comes with a worse p90 (4.819 against 4.398) and is not worth banking. The
shipped default is already right for this model.

`gate` is the exception, and the only search constant that moves anything:

| gate | 0 | 1 | 2 (shipped) | 3 |
|---|---|---|---|---|
| mean | 1.651 | 1.751 | 1.762 | 1.761 |
| p90 | 4.314 | 4.350 | 4.398 | 4.394 |
| median | 0.079 | 0.082 | 0.083 | 0.083 |
| usable | 14/41 | 15/41 | 15/41 | 15/41 |

Turning it OFF is worth 0.111 s of mean, a better p90 and a better median, for
one usable song — small, but consistent in direction. The reason is in the
flag's own help text: the gate gives a silent frame a blank bonus from the
audio's own energy, and it is "worth most on a separated vocal, where quiet
means nobody is singing". On a mixture quiet does not mean that, and 2.0 was
measured on a different model. So `--gate 0` for the from-scratch models;
`generate.GATE` is left alone, because it ships for the wav2vec2 one.

Everything else in the search is flat, which means the 1.760 s is not being held
back by tuning: what is left is perception, in the 33 songs that come out
locally broken.

*And the second-pass space is mostly answered already.* Anchoring — re-solving
between high-confidence words — is the obvious next idea and `local_align`'s
notes record it measured at **won 0, tied 17, lost 0**, with one song's error
IMPROVING by 0.028 s when its 32 anchors were cut to 1. The reason is the one
that matters for any coarse-to-fine scheme here: those anchors were re-read from
the same path they were meant to correct, and the evidence that once justified
the stage came from a donor document, which this project deliberately no longer
uses. A coarse stage is only worth building on evidence the character path does
not already contain — the line-start head, or the waveform's own `present` and
`onset`, both of which are already cached beside every emission in the jar.

*The coarse stage was built, and it does not pay.* The full chain was made and
measured on 2026-09-06: a third boundary channel labelled from each clip's own
separated vocal (`--voice`), the winning curriculum trained with it, and a
segmenter that cuts the song at the holes that channel finds and re-solves each
piece.

| what | measured |
|---|---|
| the head, held-out CLIPS, against stem truth | AUC 0.840, against 0.595 for the loudness curve the gate uses today |
| the head, held-out SONGS, per song, median | AUC 0.891 against 0.814 — but it wins on only 24 of 40, and its worst three are 0.344, 0.390, 0.484, i.e. below chance |
| alignment cost of carrying it | 1.651 s → 1.906 s, usable 14/41 → 10/41 |
| segmentation, 19 of 41 songs with candidates | 1.556 s → 1.557 s |
| segmentation with an ORACLE picking the best split by error | 1.556 s → **1.553 s** |

That last row is the one that settles it. The oracle is not a heuristic that can
be improved: it is the best any acceptance test could ever do with these
candidates, and it is worth three milliseconds. Cutting a song at the places
nobody is singing only helps if the path escapes THROUGH those places, and this
model's failure is mis-locating words inside sung regions instead.

*Why the head cannot see silence, and what would fix it.* The clips are cut
around lines, so they contain almost none: the median training clip is **0.000**
non-sung frames and only 13 of 300 are as much as 20% silent. A head trained on
that learns to answer yes, and at song scale it calls just 3.9% of frames "no
voice". The corpus structurally lacks the one class a coarse stage needs. Fixing
that is not a flag — it is a different cut, over whole songs including the
instrumental stretches between lines, rather than one clip per line. That is the
"most of a day" job, and given the oracle above it should be done for the sake
of a better voice head, not in the expectation that segmentation will pay.

*What has not been tested:* width. `dim 512, blocks 16` OOM'd twice — ollama and
voicetype hold ~4 GB of this 8 GB card — so capacity remains an open question.

**Why the checkpoints are named outside the `syncnet*.pt` glob.**
`sync.sync._default_ckpt` globs that pattern and ranks by step count, so a fresh
20,000-step model would silently become the default the editor and player use
before anything had measured it. Promoting one is then a `mv` away.

---

## 7. Issues found in the existing code while doing this

1. **`_default_ckpt` ranks by step count, and picks a checkpoint the trainer's
   own comments call broken.** It resolves to `syncnet-w2v-nl.pt` (17,000
   steps) over `syncnet-w2v-linemix.pt` (15,500). The Dutch checkpoint was
   continued for 1,500 steps on a five-song set with an empty hold-out set, and
   on the seventeen gold songs it aligns the mixture at 1.222 s against 0.571 s
   for the model it was continued from. `scores.json` already knows this.

   **And so does the other picker.** `aligner/lyrics_gui._sync_ckpt` solved
   this already — a measured checkpoint beats an unmeasured one, better mean
   error wins, step count decides only among unmeasured candidates, and a
   pinned `align_ckpt` overrules everything; its docstring names the `-nl`
   incident outright. It lands on `syncnet-w2v-linemix.pt` for the mixture and
   `syncnet-w2v-pitch.pt` for stems. So the GUI and the editor are already
   right and only the CLI is wrong, which means which model you get depends on
   which door you came through. The fix is for `_default_ckpt` to call that
   function rather than to grow its own second opinion.
2. **`~/.cache/mild-lyrics/tracks.json` was missing**, and with it every song
   lookup: `sync bench` failed with `no held-out song has both a lyric and a
   track entry` for *every* model, not just a new one. Rebuilt from Spotify for
   the 572 snapshotted track ids (572 restored, 0 unanswered) rather than by
   running `sync snapshot`, which would also have rewritten all 325 stored
   lyric documents with today's copy of each upload — and this file's own
   docstring is why that matters: an upload can be edited by its author, and a
   benchmark that silently moves is not a benchmark.

   **The failure underneath it is worse than the missing file.** `_tracks()`
   returns `{}` on any error, `name_of` then answers `"? - <tid>"` for every
   song, and `train.run` builds `gold_held` out of those strings. They match
   no name in the manifest, so **nothing is held back for the gold set and
   nothing says so** — the run prints a plausible song count, writes
   `gold_by: gc` and a 19-name `gold_held` list into the checkpoint, and has
   trained on the songs the benchmark is about to measure it on. `train.run`
   already refuses to start with an empty *hold-out set*; it should equally
   refuse when `gold_by` is set and `gold_held` matches nothing in the corpus.
3. **`--rebalance` was a no-op for the from-scratch model.** `data.Clips`
   applied it only in the `wants == "wave"` branch, while `train.run` accepted
   the flag with `--kind syncnet`, *required* the stem cut to exist, and wrote
   `augment: {rebalance: 0.5}` into the checkpoint — a file claiming an
   augmentation that never ran, in a project where every A/B is a comparison
   between two such files. Fixed, with three checks in `tests/test_sync.py`
   that spy on the call rather than compare two clips (drawing the factor moves
   the random stream, so a mel comparison would pass for the wrong reason).
4. **`bench --calibrate` orphans every jar entry it just wrote.** `jar.stamp`
   keys on the checkpoint's name, size and mtime, and `--calibrate` writes the
   measured bias back into the checkpoint after the run — so the emissions are
   filed under a stamp that no longer exists the moment the run finishes, and
   the next benchmark of that model hears all 41 songs again. The jar exists to
   make exactly that unnecessary. Stamping on `step` plus config, or writing the
   calibration before the entries, would fix it.
5. **`model.emit` allocated the stitched boundary buffer two channels wide**,
   whatever the head actually was — so a three-channel model aligned any song
   short enough to fit one window and raised `RuntimeError` on everything
   longer, which is every real song. Fixed, with a check that windows a
   ten-second clip through a three-channel head.
6. **`bench --all-held` still obeys `--songs`, which defaults to 12.** So
   `sync bench --all-held` reports twelve of the forty-one songs it offered and
   says `offered=41` in a line most readers will skim. `--songs 0` is the way
   to actually get the set. Given the flag's whole argument is that 17 or 30
   songs is not enough to tell a real change from a fresh run, `--all-held`
   should probably imply no limit.
