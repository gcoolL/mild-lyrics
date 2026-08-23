"""A synchroniser trained from noise on this player's own listening.

Nothing in here is borrowed. The acoustic model is defined in model.py and
starts from random weights; the alignment is the CTC lattice in ctcalign.py;
the lyrics are the spl uploads from Spicy Lyrics and never Apple Music's; and
the displacement between a fetched copy and the timings it is judged against is
measured, in offset.py, rather than assumed to be zero.

    python -m sync.sync status
"""
__all__ = ["audio", "bench", "ctcalign", "data", "dataset", "generate",
           "model", "offset", "text", "train"]
