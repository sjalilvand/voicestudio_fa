# Authenticating the local API

OmniVoice's backend is **loopback-only and unauthenticated by default** — a
script running on the same machine as `http://localhost:3900` needs no key, no
PIN, no header. Everything on this page only matters once you reach the backend
from **another device** (a phone on your LAN, a laptop over Tailscale, a client
behind a reverse proxy).

There are two independent gates, both **inert until you turn them on**, plus one
env var that exempts trusted callers:

| Gate | Turn on with | Guards | Applies to |
|---|---|---|---|
| **Share PIN** | the in-app Network share toggle | casual LAN-share guests, one session | non-loopback **HTTP** |
| **API key** | `OMNIVOICE_API_KEY` env var on the backend | a durable remote credential | non-loopback **HTTP + WebSocket** |
| **Trusted networks** | `OMNIVOICE_TRUSTED_NETWORKS` env var | *exempts* the two gates above | non-loopback consumption routes |

Loopback traffic (`127.0.0.1`, `::1`, `localhost`) is **never** gated — local
tools keep working unchanged whichever gate is set.

> Both gates can be active at once. The PIN and the API key are independent; when
> both are set, each is checked on the paths it covers.

---

## Share PIN

The PIN is the lightweight, in-app path: flip on **Network** sharing (footer
**Local** pill → **Network**, or **Settings → Sharing & Remote Access**) and the
app generates a fresh **6-digit PIN** for that session. It is regenerated every
time you enable sharing and is **never written to disk**. See
[docs/sharing.md](sharing.md) for the UI walkthrough.

While a PIN is set, every **non-loopback HTTP request** to an API route must
present it. Supply it any one of three ways:

| Where | How |
|---|---|
| Header | `X-OmniVoice-Pin: <pin>` |
| Query param | `?pin=<pin>` |
| Cookie | `ov_pin=<pin>` — the backend sets this automatically after the first valid PIN, so browser sessions only prove it once |

```bash
# From another device on the LAN — with the PIN
curl http://<host>:3900/v1/audio/voices \
  -H "X-OmniVoice-Pin: 123456"
```

A missing or wrong PIN returns:

```
HTTP/1.1 401 Unauthorized
{"detail": "PIN required"}
```

Notes on the PIN gate (`NetworkAccessMiddleware`, `backend/main.py`):

- It covers **HTTP only** — it does **not** gate WebSockets. The dictation
  WebSocket has its own guard (see below), and the PIN does **not** authorize
  it; use the API key or a trusted network for remote dictation.
- The SPA shell (`/`, `/index.html`, `/favicon*`, `/assets/*`, `/health`) is
  always served un-PIN'd so the PIN-prompt UI can load.
- It is completely inert when no PIN is set (the default, and every Docker
  deploy).

---

## API key

The API key is the durable credential for running the backend somewhere and
driving it remotely — a GPU box on your tailnet, a Docker container, a
reverse-proxied host. Set it on the **backend** process:

```bash
# Generate a strong key and start the backend with it
export OMNIVOICE_API_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(24))')"
uv run uvicorn backend.main:app --host 0.0.0.0 --port 3900
# Docker: pass -e OMNIVOICE_API_KEY=…
```

While `OMNIVOICE_API_KEY` is set, every **non-loopback HTTP and WebSocket**
request must present it. Supply it any one of three ways:

| Where | How |
|---|---|
| Header | `Authorization: Bearer <key>` (preferred for HTTP) |
| Query param | `?api_key=<key>` (browser WebSockets can't set headers) |
| Cookie | `ov_key=<key>` — set automatically after the first authenticated HTTP request |

```bash
curl http://gpu-box:3900/v1/audio/speech \
  -H "Authorization: Bearer $OMNIVOICE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"tts-1","voice":"alloy","input":"Hello from a keyed backend.","response_format":"wav"}' \
  --output speech.wav
```

```python
# The OpenAI SDK sends the key as a Bearer token automatically
from openai import OpenAI

client = OpenAI(
    base_url="http://gpu-box:3900/v1",
    api_key="<your OMNIVOICE_API_KEY>",   # locally, any string works — nothing checks it
)
audio = client.audio.speech.create(
    model="tts-1", voice="alloy", input="Hello from a keyed backend.",
)
audio.stream_to_file("speech.wav")
```

A missing or wrong key returns:

```
HTTP/1.1 401 Unauthorized
{"detail": "API key required"}
```

On a **WebSocket**, a missing or wrong key rejects the handshake with close
code **1008** (policy violation) instead of a JSON body.

Notes on the API-key gate (`BearerKeyMiddleware`, `backend/main.py`):

- The key is compared in **constant time** and is **never logged**.
- The SPA shell paths bypass the gate on **HTTP** so a remote UI can load and
  show what's wrong; WebSockets have no such exemption.
- **Plain HTTP is sniffable** — a Bearer key over `http://` on a hostile
  network can be read off the wire. Use Tailscale (WireGuard) or TLS for
  anything beyond a fully trusted LAN. See
  [docs/remote-gpu.md](remote-gpu.md) for the full remote-backend setup.

---

## Dictation WebSocket

The live-dictation stream at **`ws://<host>:3900/ws/transcribe`** carries its
own inline guard (`backend/api/routers/capture_ws.py`) *in addition to* the
API-key middleware. A non-loopback client reaches it only if it is **either**:

- on a [trusted network](#trusted-networks) (`is_local_host` passes), **or**
- presenting the **API key** — as `Authorization: Bearer <key>`,
  `?api_key=<key>`, or the `ov_key` cookie.

```
ws://gpu-box:3900/ws/transcribe?api_key=<key>
```

The **share PIN does not authorize dictation** — the PIN gate is HTTP-only, and
the dictation guard checks only the API key (or trusted-network membership). A
LAN guest who has only entered a PIN can use the HTTP API but **not** live
dictation. When neither the API key nor a trusted network applies, the handshake
is closed with code **1008** and reason `loopback origin required`.

---

## Trusted networks

`OMNIVOICE_TRUSTED_NETWORKS` is a comma-separated list of **CIDR ranges** whose
clients are treated as loopback-trusted by the **consumption** gates — so a
reverse proxy or a trusted LAN/Tailnet can reach the API **without a PIN or key**
(useful when a proxy strips the `Authorization` header).

```bash
export OMNIVOICE_TRUSTED_NETWORKS="192.168.1.0/24,10.0.0.0/8"
```

What it exempts vs. what it does not:

- **Exempts** (via `is_local_host`, `backend/api/dependencies.py`): the share
  PIN gate, the API-key gate, and the dictation WebSocket guard. Clients in a
  listed range need no PIN or key for these.
- **Does NOT exempt** admin routes. `/system/*` and `/api/settings/*` use a
  strict **true-loopback** check (`is_loopback`), so a trusted-network client is
  still `403`'d on the admin surface. For headless admin access, use
  `OMNIVOICE_SERVER_MODE=1` instead — **but** note that in server mode the admin
  loopback gate is disabled, so a trusted-network client can then reach admin
  routes too. Don't set `OMNIVOICE_TRUSTED_NETWORKS` if you need admin
  protection under `OMNIVOICE_SERVER_MODE=1`.

Details: malformed CIDR entries are silently ignored (a bad entry never wedges
the gate); IPv4-mapped IPv6 addresses (`::ffff:192.168.1.5`) from dual-stack
proxies are unwrapped so they match IPv4 CIDRs; the value is read at request
time, so in production **restart the backend** to apply a change. Default empty
— no change to the strict loopback default.

---

## Status codes

| Code | Meaning | What to do |
|---|---|---|
| **401** | Consumption auth failed — `{"detail": "PIN required"}` or `{"detail": "API key required"}`. | Supply the PIN / key (header, query param, or cookie above). A WebSocket surfaces this as close code **1008**. |
| **403** | `{"detail": "loopback origin required"}` — you reached a **loopback-gated** route (admin: `/system/*`, `/api/settings/*`; or a `require_local` route from outside a trusted network) from a non-loopback origin. | A PIN or key won't help. Run the request from the box itself, add the caller's network to `OMNIVOICE_TRUSTED_NETWORKS` (for `require_local` routes only), or set `OMNIVOICE_SERVER_MODE=1` for headless admin. |
| **429** | **Not an auth failure.** The GPU pool is saturated (admission control) or a model download is rate-limited. Ships with `Retry-After` and `X-OmniVoice-Retryable: true`. | Back off for `Retry-After` seconds and retry the identical request. |

---

## See also

- [docs/remote-gpu.md](remote-gpu.md) — end-to-end remote-backend setup over
  Tailscale, with the API key.
- [docs/sharing.md](sharing.md) — the in-app LAN share + PIN flow.
- [docs/agentic-voice.md](agentic-voice.md) — pointing OpenAI-compatible agent
  frameworks at OmniVoice.
- [docs/mcp.md](mcp.md) — the MCP server for AI agents.
</content>
</invoke>
