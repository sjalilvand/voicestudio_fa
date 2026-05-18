# Deferred Items — 260518-ivy follow-up

**Trigger:** PR #66 security review surfaced that `backend/api/routers/system.py` binds `0.0.0.0:3900` and several `@router.post(...)` endpoints in this router lack any authentication or origin check. Quick task `260518-ivy` hardened only `/system/set-env` (the credential-mutation vector). The remaining unauthenticated POST endpoints in the same file are catalogued here for a follow-up triage pass.

**Out of scope for the 260518-ivy commit — to be triaged in a follow-up quick task (Task #18 in backlog) or as part of Phase 5 (Opt-in Bug Reporting) security review.**

These endpoints all share the same trust-boundary defect: any LAN host (or arbitrary same-machine process) can reach them because the backend listens on `0.0.0.0:3900`. None of them rotate credentials, but several enable denial-of-service or anti-forensics attacks from a LAN attacker. None are gated by the loopback origin check shipped in this commit; each will need its own analysis (some may legitimately want LAN access — e.g., a future "control OmniVoice from your phone" feature — and others should be loopback-only).

## Other POST endpoints in `backend/api/routers/system.py`

- `/model/unload/{model_id}` (line 108) — unloads a named model from memory. Risk: a LAN host can force-evict the user's loaded TTS/ASR model, causing a re-load stall on next inference. Severity: low (no data exfil, no credential mutation).
- `/system/logs/clear` (line 318) — truncates the backend log file. Risk: a LAN host can destroy diagnostic evidence (anti-forensics). Severity: low–medium.
- `/system/logs/tauri/clear` (line 341) — truncates the frontend (Tauri) log file. Risk: same as above. Severity: low–medium.
- `/system/flush-memory` (line 384) — forces a GC / VRAM-flush cycle. Risk: a LAN host can trigger repeated flushes to degrade performance. Severity: low.
- `/clean-audio` (line 555) — accepts an uploaded WAV and runs demucs. Risk: a LAN host can upload arbitrary audio and consume CPU/GPU/disk on the user's machine. Severity: medium (resource exhaustion + writes to OUTPUTS_DIR).

## Recommended next step

Open Task #18 to triage the above with one of three dispositions per endpoint:

1. **Loopback-only** — reuse the guard pattern from `set_env_var` (factor into a small dependency / decorator after the third copy).
2. **Keep open with rate-limiting** — for endpoints that may legitimately be reached from a future LAN-control surface.
3. **Authenticated** — wait for the local-token scheme planned for the Tauri ↔ backend handshake (separate roadmap item, not in v0.3.x scope).

The router-wide audit should also cover the GET endpoints (e.g. `/system/info`, `/system/logs`) for information-disclosure analogues; those were not enumerated in this commit because they do not mutate state.
