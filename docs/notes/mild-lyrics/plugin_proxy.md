# `mild-lyrics/plugin_proxy.py`

## Lift — 2026-10-25

Docstrings shortened in `mild-lyrics/plugin_proxy.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> The only way out to the network a plugin has: an HTTPS CONNECT proxy on
> 127.0.0.1, which lets each plugin through to the sites its plugin.json lists.
>
> A plugin is told who it is by the login in its proxy URL (HTTPS_PROXY), a
> token made fresh each time it starts. Only port 443, and never to this
> machine or the local network, whatever a name resolves to.
