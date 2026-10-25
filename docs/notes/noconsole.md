# `noconsole.py`

## Lift — 2026-10-25

Docstrings shortened in `noconsole.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> Start a child program without a console window flashing up in front of it.
>
> Only Windows has anything to do here. Both launchers are .pyw files, which
> Windows binds to pythonw.exe -- no console -- and that is exactly what makes
> the problem: a process with no console of its own gets a BRAND NEW one when
> it starts a console program, and Windows draws that console on top of
> whatever the user was looking at. So fetching a song's audio in the editor
> put a black window over the lyrics for every yt-dlp and every ffmpeg it ran,
> which on a fetch-and-separate is several.
>
> CREATE_NO_WINDOW says not to make that console. STARTUPINFO with SW_HIDE goes
> with it because the two flags answer different halves of the question -- the
> flag decides whether a console is created, the startupinfo decides how a
> window the child asks for itself is shown -- and a child that opens one of
> its own is not hypothetical here: ffmpeg does not, yt-dlp's ffmpeg
> post-processor is another process again.
>
> Everywhere else this is the identity function, so callers do not have to ask
> what platform they are on. That is the whole point of it being here rather
> than spelled out at each of the dozen call sites, which is how it was: one of
> them had the flag, eleven did not.
