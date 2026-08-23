# sync — a synchroniser trained from noise

A lyric synchroniser that is this project's own, end to end. It does not borrow
an acoustic model from anywhere: `model.py` defines a small convolutional
network, it starts from random weights, and it is trained on singing this
player has already played. No wav2vec2, no Whisper, no MMS, no SOFA, no
pretrained anything -- and, since it reads the song as it was mixed, no
separator either. Separation is available behind `--stem` and is off
everywhere by default: demucs is cleaner but it invents, smearing and inventing
onsets exactly where a quiet consonant sits under a cymbal, and a timing model
taught on those artefacts learns to time the artefact.

    python -m sync.sync status

## The loop

    python -m sync.sync snapshot            keep every spl lyric on disk
    python -m sync.sync dataset --songs 250 cut clips from the songs as mixed
    python -m sync.sync train               a model from noise (~1 h)
    python -m sync.sync bench --calibrate    measure it, and fix its bias
    python -m sync.sync offsets             measure where each copy sits
    python -m sync.sync dataset --songs 80  cut clips at those offsets
    python -m sync.sync train --more 8000   carry on training on them
    python -m sync.sync ttml "artist title" write a synced lyric file

It is a loop on purpose. The first pass is trained on clips cut where a
stranger's timings said they were; every pass after that on clips cut where
this model heard the singing.

## The parts

| file | what it is |
|---|---|
| `text.py` | the 29-symbol alphabet, how a lyric is spelled into it, and a syllable rule |
| `audio.py` | 80 log-mel bands every 10 ms; the model folds two into one, so every answer is a multiple of 20 ms |
| `model.py` | SyncNet: a stem and twelve dilated depthwise-separable blocks, 5.6M parameters, CTC head |
| `ctcalign.py` | Viterbi through the CTC lattice — where each letter was sung |
| `data.py` | line clips, split by a hash of the SONG's name so a chorus cannot be in both halves |
| `train.py` | the trainer: warm-up, cosine, SpecAugment, resumable |
| `offset.py` | the two offset defences, and the one sign convention |
| `dataset.py` | the snapshot of spl lyrics, and cutting clips at measured offsets |
| `bench.py` | seconds against human references, on held-out songs only |
| `generate.py` | a song in, a TTML out, in this project's existing shape |

## Three things worth knowing

**Why there is no attention in it.** The clips it learns from are four seconds
long and the songs it is asked about are four minutes. Every layer is a
convolution, so a frame is judged by the second and a half of sound around it
and by nothing else — the model cannot tell where in a song a frame sits, and
so cannot be wrong about it. Train on lines, run on songs, no seam.

**Why the loss never reads the timings.** CTC asks only that the words appear
in order somewhere inside the clip. A line whose words sit 200 ms from where
its label claimed is still a correct example, which is what makes training on
other people's timings sound rather than circular. What CTC cannot absorb is a
line cut so far from its words that they fall outside the clip — hence:

**The automatic offset.** About a quarter of fetched copies are displaced
against the master their lyric was timed on. Two defences, in `offset.py`:
a length-and-silence check that needs nothing trained and runs on every song,
every time; and a measurement, once a model exists, that aligns the whole song
and takes the median difference against the reference. Both use one sign
convention — a positive lag means the copy is late — and the measurement is
gated on its own spread, so a song whose errors are scattered is recorded as
*not trusted* and is cut exactly where it always was. A wrong shift is worse
than no shift. (Guessing the shift from loudness peaks was tried in this
project and was sign-flipped on a good few songs; it is not done here.)

There is a third, smaller one: `bench --calibrate` measures the model's own
standing bias — CTC puts a symbol where it is surest of it, which is a little
after the sound starts — and stores it in the checkpoint, so every file
generated afterwards has it taken off.

## The peaky-CTC correction

CTC trains a model to be peaky: nearly every frame comes back blank, with a
narrow spike where a letter is certain. Measured on this model, blank sits at
**0.91 through the frames where the reference says a word is being sung**. A
path that can idle in blank almost for free is decided by noise in the few
frames that are left — and the failure that produces is not a near miss, it is
a whole song sliding tens of seconds.

So `ctcalign.levelled` scores a frame by how much more likely a label is here
than it is on average — `log p(k|x) - a·log p(k)` — with the prior taken from
**that song's own emissions**, not a constant baked in at training time. A
quiet acoustic track and a wall-of-guitars track have very different blank
rates, and a retrained model will be peaky to its own degree; nothing here has
to be retuned when either changes. `a` is `ctcalign.PRIOR`, measured at 0.8.

The search runs on the levelled emissions; word confidence is still read off
the raw ones, because `offset.summarise` and the benchmark's trust gate both
mean "how sure was the model" by it.

## The lyrics are spl only

Every lyric comes from Spicy Lyrics' community uploads, `source: spl`. The same
cache also holds Apple Music's word-synced lyrics under `aml`, and this project
has already been bitten once by mixing them — 149 of 376 documents were
Apple's, and nothing told them apart. Here it is checked in two places, refuses
loudly rather than falling back, and `--any-source` is the only way past it.

## Checking it

    python3 tests/test_sync.py     # 42 checks, no GPU, no training
    python -m sync.sync bench      # seconds, against held-out human timings

The numbers below were measured on the earlier separated-vocal build, before
separation was turned off; they are the bar the mixture build has to clear, not
a claim about it. Where it stood after one pass over 186 songs (5.6M parameters, 20,500 steps),
on 12 held-out songs, 3,900 words: **typical error 0.176 s**, 58% of words
within 0.3 s, running +0.030 s late (now calibrated out), 8 songs good, 3 that
turned out to be the wrong recording and were flagged as such rather than
averaged in. Benchmarked at three points, 6k / 12.5k / 20.5k steps, it measured
0.233 / 0.171 / 0.194 s while the held-out CTC loss rose the whole way -- which
is why `bench` decides and the loss does not.

`bench` writes a report to `sync/reports/`. Read it knowing the references were
typed by people against a master and carry their own error at 0.05–0.10 s: a
song inside that is as good as this measurement can say.
