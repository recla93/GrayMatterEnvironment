# Bridge guide — use Neuron from ChatGPT (HTTP)

Most MCP clients (Claude Desktop/Code, Cursor, OpenCode, …) launch Neuron directly as a local
stdio subprocess. **ChatGPT** can't do that — it only talks to a **remote HTTPS** MCP endpoint.
So you put a tiny **stdio → HTTP bridge** in front of Neuron and give ChatGPT the bridge's URL.

> Transport and storage are independent: the bridge only changes *how the client reaches
> Neuron*. The wrapped Neuron still uses your normal storage — local file, or the shared Turso
> Cloud DB if your `.env` provides the credentials (see the [Team guide](TEAM.md)).

## The easy way — one command

Run the helper **with the Python where Neuron is installed** (its venv). It finds/launches
the transport in-process (MCP SDK Streamable HTTP), checks Neuron actually starts, and prints
the next step:

```bash
python scripts/bridge.py            # → serves http://127.0.0.1:8000/mcp (+ legacy /sse)
# options:  --port 9000   --print-cmd (dry run)   -- <your own neuron launch command>
```

If you don't have `uv` yet (the script will tell you), install it — **no pip required**:

```
Windows      : irm https://astral.sh/uv/install.ps1 | iex
macOS / Linux: curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then expose the local port over **public HTTPS** (remote connectors can't reach `localhost`):

```bash
cloudflared tunnel --url http://127.0.0.1:8000     # → https://<random>.trycloudflare.com
```

Finally, in your client (**Perplexity**, or **ChatGPT → Settings → Connectors (Developer
Mode)**) add the public URL with the **`/mcp`** path, e.g.
`https://<random>.trycloudflare.com/mcp`.

> **Use `/mcp`, not `/sse`.** The bridge serves `/mcp`, which is the modern
> **Streamable HTTP** transport, while `/sse` is the legacy HTTP+SSE one. Behind a
> Cloudflare tunnel the legacy transport hangs: Cloudflare buffers the initial SSE
> `endpoint` handshake event, so the client never learns where to POST and times out
> (this is the classic "connector can't get a valid response in 15s" error). `/mcp`
> uses plain request/response and works through the tunnel.

That's it: `python scripts/bridge.py` + a tunnel + paste the URL.

## What it runs under the hood

`scripts/bridge.py` is just a wrapper around
the MCP SDK's own Streamable HTTP transport, served in-process. The equivalent manual
command (see it with `--print-cmd`) is:

```bash
<python-that-has-neuron> -m neuron.bridge --port 8000 --host 127.0.0.1
```

> **Don't use `mcp-remote`** — it goes the opposite direction (adapts a stdio *client* to a
> remote server), which is not what we need.

## Troubleshooting

- **`McpError: Connection closed` / "unhandled errors in a TaskGroup"** — the Neuron child
  process died on startup. Almost always it was launched with the **wrong Python** (a bare
  `python3 -m neuron` hitting a Python where Neuron isn't installed). Fixes:
  - run `python scripts/bridge.py` **with Neuron's venv Python** (it then launches that same
    interpreter — the reliable default), or
  - pass your real launch command explicitly, e.g. on a Windows install:
    `python scripts/bridge.py -- cmd /c %LOCALAPPDATA%\Programs\neuron\scripts\run_mcp.bat`
  - sanity-check first: `python -m neuron` should start and **wait** (not exit). If it exits,
    that error is your real problem — fix the install before bridging.
- **Connector can't connect / "no valid response in 15s"** — make sure you used the
  **public HTTPS** tunnel URL (not `localhost`), that you appended the **`/mcp`** path
  (not `/sse` — see the note above), and that the tunnel is still running. Quick check:
  `curl -sS -m5 -H "Accept: application/json, text/event-stream" -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"c","version":"0"}}}' https://<random>.trycloudflare.com/mcp`
  should return a JSON `initialize` result with `serverInfo`.

## Security

The tunnel exposes a network endpoint and **Neuron has no auth layer** — anyone with the URL
can read/write your memory (on a shared Turso DB, the whole team's). Keep the tunnel
private and short-lived, tear it down when unused, and put access control (e.g. Cloudflare
Access) in front of anything long-lived.

## Requirements & future

ChatGPT MCP connectors need **Developer Mode** (beta) and a paid web plan — check ChatGPT's
current docs. A first-class **native HTTP transport** (Neuron serving Streamable HTTP directly,
no bridge) is a planned option (**T15** in `TASKLIST.md`); it would remove the proxy hop but
still needs a public HTTPS endpoint for ChatGPT, so the bridge above is the simplest path today.


## Why there is no external proxy any more

The bridge used to wrap the stdio server with `mcp-proxy`, fetched on demand via
`uvx`. That is a separate project on a separate release cycle, and when the MCP
SDK dropped `request_ctx` in 1.28 it kept importing it: both bridges died at
startup with an ImportError nobody saw — `start` checked liveness after a fixed
second, the crash landed later, so it reported success and `stop` then found
nothing.

The SDK ships `streamable_http_manager` now, so protocol and transport come
from the same package. Nothing extra to install, and the next breaking bump
fails in the test suite instead of at a user's `start`.
