---
phase: quick-260518-ivy
plan: 01
subsystem: backend.api.routers.system
tags:
  - security
  - fastapi
  - backend
  - loopback
dependency_graph:
  requires: []
  provides:
    - SEC-LOOPBACK-01
  affects:
    - backend/api/routers/system.py
    - tests/test_api.py
tech_stack:
  added: []
  patterns:
    - fastapi.Request injection for peer-address gating
    - TestClient(app, client=("127.0.0.1", 50000)) to simulate loopback in tests
key_files:
  created:
    - .planning/quick/260518-ivy-add-loopback-origin-check-to-system-set-/260518-ivy-deferred-items.md
  modified:
    - backend/api/routers/system.py
    - tests/test_api.py
decisions:
  - "Read request.client.host (TCP peer) — not any X-Forwarded-For header — so the guard is not spoofable by clients on a reverse-proxy boundary."
  - "Treat request.client is None as non-loopback (also 403) — defensive for pathological transports."
  - "Did NOT add loopback guards to the other five POST endpoints in system.py this commit. Cataloged in deferred-items.md for Task #18 follow-up; the credential-mutation vector was the urgent fix."
  - "Did NOT factor out a shared loopback dependency / decorator yet — rule-of-three. Will refactor when the second endpoint adopts the same gate."
  - "Restored an incidental uv.lock drift (setuptools specifier) before committing — out of scope for this security fix."
metrics:
  duration: "5m 12s"
  completed: "2026-05-18T08:15:03Z"
---

# Quick Task 260518-ivy: Loopback Origin Check on /system/set-env

Hardened `POST /system/set-env` against LAN credential-overwrite by gating the handler on `request.client.host ∈ {"127.0.0.1", "::1", "localhost"}` before any `os.environ` mutation; covered with three regression tests and shipped in a single atomic commit on the worktree branch.

## What shipped

**Production change** (`backend/api/routers/system.py`):
1. Extended the existing fastapi import on line 7 to include `Request` (no duplicate import line).
2. Changed the handler signature on line 525 from `async def set_env_var(body: dict):` to `async def set_env_var(request: Request, body: dict):`.
3. Inserted the loopback gate as the FIRST executable statement of the function body, before `ALLOWED_KEYS`:

   ```python
   host = request.client.host if request.client else None
   if host not in ("127.0.0.1", "::1", "localhost"):
       raise HTTPException(status_code=403, detail="set-env requires loopback origin")
   ```
4. Every other line of the handler is byte-for-byte unchanged (ALLOWED_KEYS check, value branch / pop branch, logger.info lines, return dict). Confirmed via `grep -c 'request.client.host' backend/api/routers/system.py` → exactly 1 match.

**Test change** (`tests/test_api.py`, appended below `test_kani_tts_synth_streaming_e2e_explicit_sampling`):
- `test_set_env_rejects_non_loopback` — uses the existing `client` fixture (default `request.client.host == "testclient"`), POSTs `{"key": "HF_TOKEN", "value": "__set_env_should_not_be_set__"}`, asserts 403, asserts `"loopback" in detail.lower()`, asserts os.environ is unchanged. Wrapped in try/finally to restore any prior `HF_TOKEN` on teardown.
- `test_set_env_allows_loopback` — builds a fresh `TestClient(app, client=("127.0.0.1", 50000))`, POSTs `{"key": "HF_TOKEN", "value": "hf_loopback_ok"}`, asserts 200, asserts `response.json() == {"key": "HF_TOKEN", "set": True}`, asserts `os.environ["HF_TOKEN"] == "hf_loopback_ok"`. Try/finally restores `HF_TOKEN` to its prior state.
- `test_set_env_loopback_still_validates_allowlist` — confirms the new guard does NOT bypass the existing allow-list: loopback POST with `{"key": "DISALLOWED", ...}` still returns 400 and `DISALLOWED` is not added to `os.environ`.

**Deferred-items file** (`.planning/quick/260518-ivy-add-loopback-origin-check-to-system-set-/260518-ivy-deferred-items.md`):
Enumerates the other five `@router.post(...)` endpoints in `backend/api/routers/system.py` with one-line descriptions and per-endpoint risk notes, plus a recommended triage step (loopback-only / rate-limit / token-auth) for the Task #18 follow-up:
- `/model/unload/{model_id}` (line 108) — model eviction DOS, severity low
- `/system/logs/clear` (line 318) — anti-forensics, severity low–medium
- `/system/logs/tauri/clear` (line 341) — anti-forensics, severity low–medium
- `/system/flush-memory` (line 384) — performance degradation DOS, severity low
- `/clean-audio` (line 555) — resource exhaustion + disk write, severity medium

## Test results

```
$ uv run python -m pytest tests/test_api.py -k "set_env" -x -q
...                                                                      [100%]
3 passed, 28 deselected in 1.36s
```

Plus the wider router smoke suite as a non-regression check:

```
$ uv run python -m pytest tests/test_router_smoke.py -x -q
23 passed, 7 warnings in 106.67s
```

The seven warnings are pre-existing pydub `DeprecationWarning`s from upstream (`pydub/utils.py` invalid escape sequences and `audioop` removal in Python 3.13) — not introduced by this commit and out of scope per the analysis-paralysis-guard / scope-boundary rules.

## Commit

| Field | Value |
| ----- | ----- |
| SHA   | `e1f08a6845e3d1766ce69dce776fa9ef3875f2ae` (`e1f08a6`) |
| Branch | `worktree-agent-aece56abfce0a911a` (per-agent worktree; not pushed) |
| Subject | `security: add loopback origin check to /system/set-env` |
| Files | `backend/api/routers/system.py`, `tests/test_api.py`, `.planning/quick/260518-ivy-.../260518-ivy-deferred-items.md` |
| Net diff | 93 insertions, 2 deletions across 3 files |

The PLAN.md was already committed in the base commit (`58a1ec0 docs(260518-ivy): pre-dispatch plan for loopback origin check on /system/set-env`), so it's traceable in git history without re-committing — `git status` confirmed clean post-commit. No push to remote.

## Threat model coverage

The plan's `<threat_model>` register lists six threats; this commit closes/handles each as documented:

- **T-ivy-01 (Tampering, LAN host hits /system/set-env)** — MITIGATED by the loopback gate, verified by `test_set_env_rejects_non_loopback`.
- **T-ivy-02 (Elevation of Privilege, LAN host overwriting HF_TOKEN)** — MITIGATED by the same gate; attacker has no reachable mutation path.
- **T-ivy-03 (Information Disclosure via length-only log line)** — ACCEPTED; pre-existing behavior, no regression introduced.
- **T-ivy-04 (Tampering by same-machine non-OmniVoice process)** — ACCEPTED; OS-level UID/process auth is out of scope, documented in deferred-items for a future hardening pass.
- **T-ivy-05 (Spoofing via X-Forwarded-For)** — MITIGATED-BY-DESIGN; guard reads `request.client.host` (actual TCP peer), never any header.
- **T-ivy-SC (Supply-chain risk via package install)** — MITIGATED; no new package installs in this commit. `fastapi.Request` was already importable from the existing pinned `fastapi` dep.

## Deviations from Plan

None — plan executed exactly as written. The three tasks ran in order, the production edit matched the `<action>` block byte-for-byte (single-line import extension, signature change, four-line guard insertion above ALLOWED_KEYS), the test names match the plan's prescribed names, the deferred-items file enumerates the five routes the plan listed with the same risk notes, and the commit subject is exactly `security: add loopback origin check to /system/set-env`.

One minor non-deviation observation: running `uv run` during verification incidentally rewrote a `setuptools` specifier line in `uv.lock`. Per the plan's Task 3 instruction ("Verify with `git status` that no other files are staged inadvertently") I reverted `uv.lock` before staging so the commit touches only the four intended paths. This is in-scope cleanup, not a deviation.

## Threat Flags

None introduced beyond those in the plan's threat register. The change strictly reduces attack surface.

## Known Stubs

None.

## Self-Check: PASSED

- `backend/api/routers/system.py`: FOUND, contains `request.client.host` (1 match, in `set_env_var`).
- `tests/test_api.py`: FOUND, contains `test_set_env_rejects_non_loopback`, `test_set_env_allows_loopback`, `test_set_env_loopback_still_validates_allowlist`.
- `.planning/quick/260518-ivy-add-loopback-origin-check-to-system-set-/260518-ivy-deferred-items.md`: FOUND, enumerates the five other POST routes.
- Commit `e1f08a6`: FOUND in `git log --oneline`.
- `pytest tests/test_api.py -k set_env`: 3 passed / 28 deselected.
- `pytest tests/test_router_smoke.py`: 23 passed (non-regression).
- `git status` post-commit: clean.
