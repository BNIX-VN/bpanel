"""The page the panel port serves when its certificate cannot be used (1.20.3).

The panel used to fall back to serving its whole self over plain HTTP whenever
the certificate it was configured with was missing: app/serve.py simply left
TLS off. Cookie flags follow the request scheme, so the session and CSRF
cookies then went out without ``Secure`` and an admin login crossed the
network in clear text, with nothing but a missing padlock to say so.

So the port still answers - the operator can see what is wrong from a browser -
but with this page and nothing else. No application, no database, no
authentication: this module imports none of them, so there is no route to sign
in through, even by mistake.

An administrator who chose an http:// panel URL is not in this case: that is a
setting (PANEL_SSL_CERT left empty), and serve.py still honours it.
"""

from __future__ import annotations

HELPER = "sudo -u bpanel env HOME=/opt/bpanel sudo -n /usr/local/sbin/bpanel-helper"
SELF_SIGNED_COMMAND = f"{HELPER} panel-ssl-selfsigned &lt;hostname-or-ip&gt; &lt;port&gt;"

_PAGE = f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BPanel unavailable</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{
    margin: 0; min-height: 100vh; display: grid; place-items: center;
    background: #11151c; color: #e6e9ef; padding: 24px;
    font: 15px/1.6 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  }}
  main {{ max-width: 46rem; }}
  h1 {{ font-size: 1.35rem; margin: 0 0 .75rem; color: #ffb4a2; }}
  p {{ margin: 0 0 .9rem; color: #c3c9d4; }}
  code, pre {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 13px; }}
  pre {{
    background: #0b0e13; border: 1px solid #262d3a; border-radius: 6px;
    padding: 12px 14px; overflow-x: auto; color: #dfe4ec; white-space: pre-wrap;
  }}
  ol {{ color: #c3c9d4; padding-left: 1.25rem; }}
  li {{ margin-bottom: .5rem; }}
</style>
<main>
  <h1>BPanel is not serving right now</h1>
  <p>
    The panel could not load its TLS certificate, and there is no self-signed
    one to fall back on. It will not serve itself over an unencrypted
    connection: signing in here would send your password and session cookie
    across the network in clear text.
  </p>
  <p>Websites on this server are unaffected &mdash; only the panel is down.</p>
  <p>To fix it, over SSH as root:</p>
  <ol>
    <li>
      Read why the certificate was rejected:
      <pre>journalctl -u bpanel-api -n 50 --no-pager</pre>
    </li>
    <li>
      Issue the panel a Let's Encrypt certificate again:
      <pre>bpanel install-panel-ssl</pre>
      or give it a self-signed one (browsers will warn once):
      <pre>{SELF_SIGNED_COMMAND}</pre>
    </li>
    <li>
      Start the panel again, if the step above did not:
      <pre>systemctl restart bpanel-api</pre>
    </li>
  </ol>
</main>
"""

_BODY = _PAGE.encode("utf-8")

HEADERS = [
    (b"content-type", b"text/html; charset=utf-8"),
    (b"content-length", str(len(_BODY)).encode("ascii")),
    (b"cache-control", b"no-store"),
    # Nothing here is meant to be framed, indexed or sniffed.
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"x-robots-tag", b"noindex, nofollow"),
]


async def app(scope, receive, send) -> None:
    """A complete ASGI app of its own: every request gets the same 503."""
    if scope["type"] == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return
    if scope["type"] != "http":
        return
    await send({"type": "http.response.start", "status": 503, "headers": HEADERS})
    await send({"type": "http.response.body", "body": _BODY})
