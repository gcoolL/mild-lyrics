# out_delay.py

## Why — 2026-11-05

Qt 6.12's FFmpeg renderer (`qffmpegaudiorenderer.cpp`) takes only its own
QAudioSink buffer (`bufferSize - bytesFree`) off the position it reports. The
PipeWire backend calls `pw_stream_get_time_n` for xrun detection only (and has
that switched off), so the graph quantum and the device's ALSA buffer are
never counted: `QMediaPlayer.position()` is ahead of the sound by them.

Words timed in the editor against a local file were stamped late by that much,
and played back on the same clock they looked right, so the error only showed
elsewhere: the AMLL beta editor (HTMLMediaElement time, which subtracts the
output latency) showed them behind. The AMLL TTML Tool has the same fault as
we had (it counts samples its AudioWorklet has pulled).

## How

- `pw-dump`: this process's `Stream/Output/Audio` nodes (by
  `application.process.id`), their `Latency` param, direction Input: the
  downstream latency as quantum multiples + samples + ns. It includes any
  filter between the stream and the device.
- The quantum is the driver's live one from `pw-top -b -n 2` (the first sample
  is empty); the `settings` metadata (`clock.force-quantum`, `clock.quantum`,
  `clock.rate`) when the driver is idle.
- Read on a thread at most every 10 s, only while asked; `delay()` never waits.
  Not Linux, no PipeWire, no stream yet, or past 0.5 s: 0.
- Applied while playing only, scaled by the playback rate in the editor; never
  back before the point the clock last held at (a seek, a resume, a stall), so
  a seek holds for the delay instead of stepping back. Paused positions are
  Qt's.
- Editor `LocalPlayer.position()` (its own state keeps file time:
  `_file_pos()`), Mild Lyrics `LocalPlayer.reading()`. The editor linked to
  Mild Lyrics gets it through the reading.
- Setting `out_delay` auto/off in both; auto's note shows the reading.

## Checked

Their G435 output at quantum 1024 / 48 kHz: Latency = 1 quantum + 512 samples
(the ALSA headroom) = 32 ms, read from the running player's stream. Offscreen
on a fake 32 ms: holds at a seek for 32 ms then runs 32 ms behind the file,
16 ms at 0.5x, unshifted when paused or off. Not yet checked: by ear against
the beta editor; a Bluetooth or filter-chain output; Windows (WASAPI has the
same question, left at 0 until measured). The headset's own radio latency is
invisible to every program and not counted.

## The stretcher — 2026-11-05

At any rate but 1, Qt (pitch compensation, on by default) runs the audio
through Signalsmith Stretch `presetDefault` (0.12 s window) in
`qffmpegaudioframeconverter.cpp` and labels its output with the input frames'
times: the position is ahead by half a window of input plus half a window of
output, 0.06 * (1 + rate) song seconds. At 1 the stretcher is bypassed. Taps at
0.5x landed late against the spectrogram (which is not stretched) while 1x
was right.

Measured offline (scratch `lat.cpp`, the vendored header called as Qt calls
it, 1152-frame chunks, 44.1 kHz): the half-level point of a sine or noise
onset comes out at +88.9/+90.9 ms at 0.5x, +104/+105.5 at 0.75x, +113 at 0.9x,
+132 at 1.25x, against 90/105/114/135 from the formula. `stretch()` adds it in
the editor's `position()` while Qt reports pitch compensation; the setting's
off turns it off too. Mild Lyrics' own player always plays at 1.

Confirmed by ear the same day: taps at 1x and below land on the spectrogram.
