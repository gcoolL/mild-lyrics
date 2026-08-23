# `aligner/run_pipeline.py`

Comments lifted out of `aligner/run_pipeline.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

**line 55** — before `TRAIN_MAX = 8.0`

> Clips longer than this are dropped from TRAINING only: attention cost grows
> with the square of the input and this card has 8 GB.

**line 62** — before `DEV_OUT = 8`

> Songs kept out of training to score the loss on. Whole SONGS, never a slice
> of clips: clips off one recording share a singer, a mix and a mastering
> chain, so a clip-level split scores the model on music it has already heard
> and answers a question nobody asked.
>
> This is the thing a 10,000-step run was missing. Its training loss fell
> 2.22 -> 1.68 without a stumble and predicted nothing -- word for word against
> the references the trained model came out 74 closer and 62 further, p = 0.35.
> A falling training loss says the clips are being fitted. Only a held-out one
> can say whether anything was learnt.

**line 73** — on `EVAL_EVERY = 250`

> steps between dev evaluations

**line 74** — on `EVAL_BATCHES = 40`

> dev batches each time, the SAME ones every time

**line 75** — on `PATIENCE = 6`

> evaluations without a new best before stopping

**line 76** — before `PACKED_OK = 0.12`

> Provisional, from seven songs. Every played song now carries these numbers,
> so the distribution -- not this sample -- should set them. If _packed turns
> out unimodal, a cutoff is the wrong instrument and this should rank instead.

**line 81** — before `WRONG_AUDIO = {"Miracle Musical, Shane - Labyrinth"}`

> Songs whose audio is not the song. Labyrinth's copy is somebody else's
> recording of the right length: it aligned at 18.5s in both arms of every
> comparison, and the speech model heard 34% of its words against a healthy
> 82-84%. Kept out of the eval set because it measures the fetcher, not the
> aligner, and its 18s sat in every summary as though it were ours.


## `wait_for_dataset`

**line 97** — on `    while still < 6:`

> ~5 minutes with no new song

**line 100** — before `n = len({r.get("name") for r in load_manifest()})`

> Songs, not rows. The same recording is cached under several track
> ids, so the file held 424 rows for 270 songs and every count that
> read it overstated the dataset by half.


## `train`

**line 140** — before `model.config.ctc_zero_infinity = True`

> A CTC loss sums log probabilities over hundreds of frames, and in fp16
> every one of them came back NaN -- which the skip below then swallowed,
> silently, for an hour. bf16 has fp32's exponent range and is finite here.

**line 144** — before `model.config.apply_spec_augment = False`

> SpecAugment substitutes a learned vector into masked timesteps, and this
> checkpoint has no such vector -- transformers draws a random one on every
> load, sometimes with values around 1e34, which overflows the encoder and
> turns every loss to NaN. It regularises nothing here; turn it off.

**line 149** — on `    model.freeze_feature_encoder()`

> the convolutions already hear fine


## `train.Clips.__getitem__`

**line 184** — before `wave = (wave - wave.mean()) / (wave.std() + 1e-7)`

> The checkpoint ships do_normalize: true and _logits() normalises
> every window at inference. This checkpoint's group norm happens
> to cancel a pure gain difference, so it trains either way -- but
> the two paths should not disagree about a documented step.

**line 189** — before `ids = proc.tokenizer(text.upper()).input_ids`

> The model's vocabulary is upper case; our text is not.


## `train`

**line 206** — before `dev_loader = DataLoader(Clips(dev_items), batch_size=BATCH, shuffle=False,`

> Not shuffled, and only the first EVAL_BATCHES of it: every evaluation has
> to score the SAME clips, or the number moves for reasons that have
> nothing to do with the model.

**line 234** — before `if dev_loader is not None:`

> What the model scores BEFORE any of this touches it.
>
> Without it `best` starts at infinity, the first evaluation wins by
> default, and a run that makes the model worse from its very first step
> still writes a checkpoint -- one that is worse than the model it started
> from, with nothing anywhere to notice. Seeding `best` with the untrained
> score means a checkpoint has to BEAT not training at all before it is
> kept, and if none does, nothing is written and the old model survives.

**line 257** — before `skipped += 1`

> One unfittable clip is ordinary. A run of them means the loss
> is broken, and spinning here forever looks exactly like
> training from the outside -- so refuse to, at ANY step. The
> first version of this guard only checked step == 0, which
> left the same silent night available from step 700 onwards.

**line 275** — before `opt.zero_grad(set_to_none=True)`

> NaN clamps to NaN and multiplies through: stepping here
> poisons every parameter and drops us into the loop above.

**line 294** — before `best, best_at, stale = got, step, 0`

> Kept on the CPU so it survives the next step, and
> written at the end. The final model is only the best
> one if nothing overfitted, which is the question.

**line 314** — before `say("NOTHING beat the untrained model on held-out loss — not saving. "`

> Nothing beat the untrained model. Saying so and leaving whatever is
> already on disk alone is the honest outcome -- writing a regression
> here would be indistinguishable, from the outside, from a run that
> worked.

**line 331** — before `say("  held-out loss against training loss:")`

> Printed together at the end, because the shape is the point and it
> is unreadable spread through three thousand lines of step logging.
> Training down while held-out is flat or rising is overfitting, and
> it is the one thing the previous run had no way to show.

**line 339** — before `say(f"  training  {first[1]:.3f} -> {last[1]:.3f}")`

> Written as "from -> to" rather than as a signed delta on purpose. A
> delta needs the reader to remember which direction is good, and the
> first version of this line printed "held-out +0.345" for a loss that
> had FALLEN by 0.345, which is the opposite of what it read as.


## `measure`

**line 404** — before `if listen.exists():`

> Emptied, not merely created. A .ttml left from an earlier run sits beside
> this run's with nothing marking it, and gets read as evidence about a run
> it had no part in -- which has already happened once.

**line 415** — before `def skip(why, _n=song["name"]):`

> A song that drops out of a measurement changes the numbers of the
> ones that stay, so every way out of this loop says why. Four of the
> twelve vanished from the last run and nothing recorded a reason.

**line 441** — before `got = LA.align(audio, doc, want="gpu", spare=0.4,`

> log= at last: the aligner narrates whether it anchored,
> and that line -- the one that says whether this walk was
> pinned or free -- was generated and thrown away 21 times
> before anyone could read it.
> acoustic= is left at align()'s own default. Forcing "w2v"
> measured a configuration the app never runs, and spent two
> held-out slots on Japanese songs whose English ASR head, by
> its own docstring, "has nothing to say about" them.

**line 454** — on `                if not keep.exists():`

> the copy, to listen along with

**line 488** — before `LA.release()`

> Not on the happy path only: an early continue used to leave the
> card holding demucs and Whisper until the next song evicted them.


## `summarise`

**line 526** — before `lean = statistics.median([r[2] for r in rows])`

> The signed median is worth carrying again now the songs are all in one
> clump: several sit at a consistent +0.08 to +0.12s, and a shared lateness
> is one constant to find rather than a property of each song.


## `main`

**line 548** — before `import argparse`

> learn.py passes --steps through; nothing else takes arguments.

**line 561** — before `import spicy_lyrics as SL`

> Metadata and references, gathered while Spotify is still up.

**line 578** — before `by_name = {}`

> One entry per track before splitting. The same song is cached under
> several ids, and counting those as separate songs both wastes
> held-out slots on repeats and -- if a pair straddles the boundary --
> trains on a song we are about to measure.
> One entry per SONG, not per track id. The same recording is cached
> under several ids, and de-duplicating by id misses exactly the case
> it was written for: NYOTAIMORI! was held out as 0HBBdg... and trained
> on as 3HutyG..., 42 identical lines each. The name is what identifies
> a song across ids.

**line 591** — before `songs.sort(key=lambda s: hashlib.sha1(`

> Membership from a hash of the name, not from where the song lands in
> a sort. sorted(...)[:12] re-draws the whole eval set whenever a song
> with an earlier name is cached, and two runs then measure different
> music -- which is the one thing an A/B cannot survive.

**line 597** — before `held = songs[:HOLD_OUT]`

> Three groups, not two, and all three cut from the same hash order so
> none of them drifts when the cache grows: songs to MEASURE the
> aligner on, songs to SCORE the loss on, and the rest to train on.
> The eval set is still songs[:HOLD_OUT], so its membership is exactly
> what it was before the dev split existed and old runs stay comparable.

**line 640** — before `steps = [n for n in NOTE if n.lstrip().startswith("step ")]`

> The log is trimmed at both ends rather than the tail: the last 80
> lines are all step lines, which buries the split, the dataset counts
> and the whole before pass -- the parts worth comparing between runs.

**line 678** — before `keep = REPORT.parent / "reports"`

> Kept as well as overwritten: the point of a report is comparing runs.
