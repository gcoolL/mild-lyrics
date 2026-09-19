# mild-lyrics
my goofy lyrics bro

## Setting up

Check the machine, and install whatever is missing:

    ./setup.sh          # Linux, macOS
    setup.cmd           # Windows -- double-click works too

Nothing is installed without being asked, and `--check` never asks at all.
The only thing it needs first is Python 3.10 or newer; where there is none,
it says where to get one for this platform.

Only PyQt6 is actually required. Everything else buys one feature and says
which -- a waveform, syllables in the editor, the romanisation of a line
that is not in the Latin alphabet -- so it can be turned down without
guessing at what breaks.

Local alignment (torch, demucs) is the exception: gigabytes, and the one
group whose failures belong to the machine rather than to the package. It
prints what this machine has -- memory, cores, card, disk, how old the CPU
is -- says what that means for it here, and only then asks. It is offered
with `--heavy`, and everything else works without it.

Afterwards, `aligner/doctor.py` checks the rest: players, the Spotify debug
port, caches, credentials, and the desktop shortcuts.
