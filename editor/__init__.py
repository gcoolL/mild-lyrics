"""The TTML synchroniser: write the words, then place them in time.

Everything here is a *tool*, not a player. It reads and writes the same
document shape the rest of Mild Lyrics passes around -- the Spicy Lyrics
document, with `Content` a list of lines, each with a `Lead` group of
syllables and any number of `Background` ones -- so a file edited here is a
file the player can already draw, and no format has to be invented for it.
"""
