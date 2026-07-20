# API access control & the two-tier trust model

OmniVoice's backend is local-first: by default it is reachable only from the
machine it runs on. Everything below is about the opt-in paths that let a
*non*-loopback client reach it (LAN share, remote GPU box, Docker), and the
boundary that keeps those clients out of the admin surface.

## Two tiers of trust

The backend distinguishes **consumption** from **administration**, and they do
not share a gate:

| Tier | Routes (examples) | Gate helper | Trusted-network client? |
|------|-------------------|-------------|-------------------------|
| **Consumption** | TTS generate, dubbing, dictation model/prefs + WS | `require_local` / middleware (`is_local_host`) | ✅ exempt |
| **Administration** | `/system/*` (incl. `set-env` — RCE-class), `/api/settings/*`, engine install/uninstall, pronunciation, media tools, MCP bindings | `require_loopback` (`is_loopback`) | ❌ never, by membership alone |

`is_loopback` matches only `127.0.0.1` / `::1` / `localhost`. `is_local_host`
matches those **plus** any CIDR in `OMNIVOICE_TRUSTED_NETWORKS`. The admin gate
uses `is_loopback`; the consumption gates use `is_local_host`. That split is the
whole model: **consumption trust ≠ admin trust.**

## The credential gates (middleware)

Two ASGI middlewares sit in front of every route. Both are **inert unless
configured**, and both **bypass loopback and trusted-network clients**
(`is_local_host`):

- **Share PIN** (`NetworkAccessMiddleware`) — when a PIN is set, a non-local
  client must send `x-omnivoice-pin` / `?pin=` / the `ov_pin` cookie. Guards
  casual LAN-share guests for one session.
- **API key** (`BearerKeyMiddleware`, `OMNIVOICE_API_KEY`) — when set, a
  non-local client must send `Authorization: Bearer <key>` / `?api_key=` / the
  `ov_key` cookie, on HTTP **and** WebSocket. The durable credential for
  running the backend remotely (Tailscale, Docker GPU box).

Because both bypass `is_local_host`, a client in a trusted CIDR presents **no
credential at all** and is still let through — that is the point:
`OMNIVOICE_TRUSTED_NETWORKS` exists for a reverse proxy / LAN that *cannot*
present the credential (e.g. a proxy that strips `Authorization`).

## `OMNIVOICE_TRUSTED_NETWORKS`

Comma-separated CIDRs (`192.168.1.0/24,10.0.0.0/8`) that are treated as
loopback-trusted **for consumption only**. Set it so LAN clients or a reverse
proxy can hit TTS/dictation without the PIN/API key. It **never** exempts the
admin surface — a trusted-network client still gets `403` on `/system/*` and
`/api/settings/*` unless it is genuine loopback or (in server mode) presents the
**API key** — and only when a credential is configured at all (a bare
no-credential deployment leaves admin open; see Server mode below).

## Server mode (`OMNIVOICE_SERVER_MODE=1`, the Docker image)

In Docker the loopback origin is **unenforceable**: NAT rewrites every
`request.client.host` to the bridge gateway (e.g. `172.17.0.1`), so even a
`-p 127.0.0.1:3900:3900` mapping makes every request look non-loopback. Server
mode therefore drops the *true-loopback* requirement on admin routes (issue
#261 — otherwise the operator is 403'd out of `/system/info`, `set-env`, etc.).

It does **not** drop the credential requirement. Under server mode the admin
gate applies this rule (see `require_loopback` in
`backend/api/dependencies.py`):

- **No credential configured** (no API key, no PIN) → admin is open (`403` never fires). This is the
  #261 flow: a bare Docker deployment where the operator reaches `/system/*` off
  the bridge gateway with nothing set. Exposure rests on the port mapping.
- **A credential IS configured** (API key and/or PIN) → the request must present
  the **API key** (`Authorization: Bearer` / `?api_key` / `ov_key` cookie).
  Loopback still passes with no credential. The 6-digit share PIN is a
  *consumption* credential and is **not** accepted for admin — it is short enough
  to brute-force, so it must never gate `/system/set-env` (RCE-class). A PIN-only
  deployment therefore keeps admin **loopback-only**; remote admin requires the
  (long) API key.

### Why the credential re-check exists (#1213)

Before #1213, server mode made `require_loopback` an unconditional no-op. That
collapsed the two-tier model in one specific configuration:

> `OMNIVOICE_SERVER_MODE=1` **+** `OMNIVOICE_API_KEY=secret` (lock the backend)
> **+** `OMNIVOICE_TRUSTED_NETWORKS=10.0.0.0/8` (let a LAN proxy do TTS without
> the key).

A client at `10.1.2.3` (in the trusted CIDR) could then `POST /system/set-env`
— RCE-class — with **no API key**: the API-key middleware bypassed it as
`is_local_host`, and the admin gate was a no-op. Trusted-network membership, a
*consumption* exemption, silently unlocked full admin (read the masked HF-token
preview, install engines, set arbitrary env, clear logs, …).

The fix keeps the admin gate independent: in server mode admin requires the API
key (or loopback), and neither trusted-network membership nor the share PIN
satisfies it. The trusted client keeps its consumption exemption (TTS/dictation
still work without the key) but is `403`'d on the admin surface until it presents
the API key. A deployment that sets **no** credential is unchanged (admin open,
#261), and the loopback operator path is unchanged.

## Quick reference — who reaches admin (`/system/*`, `/api/settings/*`)?

| Client | Desktop (no server mode) | Server mode, no credential | Server mode, API key/PIN set |
|--------|--------------------------|----------------------------|------------------------------|
| Loopback (`127.0.0.1`) | ✅ | ✅ | ✅ (no credential needed) |
| Trusted CIDR, no credential | ❌ 403 | ✅ | ❌ 403 |
| Trusted CIDR, valid credential | ❌ 403 | ✅ | ✅ |
| Other non-loopback, valid credential | ❌ 403 | ✅ | ✅ |
| Other non-loopback, no credential | ❌ 403 | ✅ | ❌ (blocked at middleware) |

Consumption routes (TTS, dubbing, dictation) follow `is_local_host`, so every
loopback **and** trusted-CIDR client reaches them; other non-loopback clients
need the credential when one is set.
