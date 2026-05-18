---
phase: quick-260518-ivy
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/api/routers/system.py
  - tests/test_api.py
  - .planning/quick/260518-ivy-add-loopback-origin-check-to-system-set-/260518-ivy-deferred-items.md
autonomous: true
requirements:
  - SEC-LOOPBACK-01
tags:
  - security
  - fastapi
  - backend

must_haves:
  truths:
    - "POST /system/set-env from any non-loopback client returns HTTP 403"
    - "POST /system/set-env from 127.0.0.1 (or ::1, localhost) with an allowed key still mutates os.environ and returns 200"
    - "All existing allow-list, env-mutation, logging, and return-shape behavior of the endpoint is preserved unchanged"
    - "Other POST endpoints in backend/api/routers/system.py are NOT modified by this commit"
    - "A deferred-items file enumerates the remaining unauthenticated POST endpoints in system.py for follow-up triage"
    - "A single atomic commit lands on main with message: security: add loopback origin check to /system/set-env"
  artifacts:
    - path: "backend/api/routers/system.py"
      provides: "Loopback-only guard on /system/set-env"
      contains: "request.client.host"
    - path: "tests/test_api.py"
      provides: "Regression test(s) for loopback enforcement"
      contains: "set-env"
    - path: ".planning/quick/260518-ivy-add-loopback-origin-check-to-system-set-/260518-ivy-deferred-items.md"
      provides: "Audit list of other unauthenticated POST endpoints in system.py for follow-up"
      contains: "/system/"
  key_links:
    - from: "backend/api/routers/system.py:set_env_var"
      to: "fastapi.Request.client.host"
      via: "request parameter injected by FastAPI"
      pattern: "request\\.client\\.host"
    - from: "tests/test_api.py"
      to: "fastapi.testclient.TestClient"
      via: "client_kwarg={'client': ('127.0.0.1', 50000)} override for happy-path test"
      pattern: "TestClient\\(.*client=\\("
---

<objective>
Close a local-LAN credential-overwrite vulnerability on `POST /system/set-env` (backend/api/routers/system.py:524-552). The backend binds 0.0.0.0:3900 and this endpoint mutates `os.environ` for `HF_TOKEN` and `TRANSLATE_API_KEY` with no auth or origin check, so any LAN host or arbitrary local process can overwrite stored tokens. PR #66 widened the blast radius by persisting tokens to `prefs.json`. This plan adds a loopback-origin allow-list as the first statement of the handler and surfaces (without fixing) the other POST endpoints in the same router for a follow-up triage.

Purpose: Reinforce OmniVoice's local-first guarantee (per CLAUDE.md: "no required cloud calls, accounts, or API keys" — and by extension, no remote mutation of locally-stored credentials). Today the endpoint is reachable from any host on the user's network; after this fix it is only reachable from the same machine.

Output:
- Hardened `/system/set-env` handler with `Request`-based loopback gate
- Regression test(s) covering both 403 (non-loopback) and 200 (loopback) paths
- `260518-ivy-deferred-items.md` enumerating the other unauthenticated POST routes in `system.py` for the next security pass
- One atomic commit on `main`
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@CLAUDE.md
@backend/api/routers/system.py
@tests/test_api.py

<interfaces>
<!-- Key signatures the executor needs. Extracted from current file at lines 524-552. -->
<!-- Do not re-explore the codebase for these. -->

Current handler (backend/api/routers/system.py, lines 524-552):
- Decorator: @router.post("/system/set-env")
- Signature: async def set_env_var(body: dict):
- Allow-list (preserve verbatim): ALLOWED_KEYS = {"HF_TOKEN", "TRANSLATE_API_KEY"}
- Existing import line at top of file (line 7):
    from fastapi import APIRouter, File, UploadFile, HTTPException, Query
  -> Add `Request` to this import (do NOT add a second `from fastapi import ...` line).

Other @router.post routes in the same file (for deferred-items audit, lines confirmed via grep):
- line 108: /model/unload/{model_id}
- line 318: /system/logs/clear
- line 341: /system/logs/tauri/clear
- line 384: /system/flush-memory
- line 524: /system/set-env   ← THIS task
- line 555: /clean-audio

TestClient pattern (FastAPI / Starlette):
- Default TestClient sets request.client.host = "testclient" — this is what makes the 403 test trivially pass.
- To simulate a loopback origin, construct: TestClient(app, client=("127.0.0.1", 50000))
- Existing client fixture at tests/test_api.py:71-76 returns `TestClient(app)` — reuse it for the 403 case; build a second loopback client inline for the 200 case.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Add loopback-origin guard to /system/set-env and regression tests</name>
  <files>backend/api/routers/system.py, tests/test_api.py</files>
  <behavior>
    Test 1 (403 path, non-loopback origin):
      - Using the default TestClient fixture (host = "testclient"), POST /system/set-env with body {"key": "HF_TOKEN", "value": "hf_dummy"}.
      - Expect status_code == 403.
      - Expect response JSON detail to contain "loopback".
      - Expect os.environ.get("HF_TOKEN") to be UNCHANGED (the env mutation must not run when the guard rejects).

    Test 2 (200 path, loopback origin):
      - Construct TestClient(app, client=("127.0.0.1", 50000)).
      - POST /system/set-env with body {"key": "HF_TOKEN", "value": "hf_loopback_ok"}.
      - Expect status_code == 200.
      - Expect response JSON == {"key": "HF_TOKEN", "set": True}.
      - Expect os.environ["HF_TOKEN"] == "hf_loopback_ok".
      - Teardown: pop HF_TOKEN from os.environ to keep test isolation (use a try/finally or a monkeypatch fixture if available in the test module).

    Test 3 (optional, only if trivial — skip if it complicates the test):
      - POST with body {"key": "DISALLOWED", "value": "x"} from loopback origin still returns 400 (existing allow-list still enforced after the guard).
  </behavior>
  <action>
    Implement the security fix and its tests in one task.

    Production change in backend/api/routers/system.py:
    1. Extend the existing fastapi import at line 7 to include Request — i.e., the line becomes:
         from fastapi import APIRouter, File, UploadFile, HTTPException, Query, Request
       Do NOT add a duplicate import line.
    2. Change the handler signature at line 525 from:
         async def set_env_var(body: dict):
       to:
         async def set_env_var(request: Request, body: dict):
    3. Insert the loopback check as the FIRST statement of the function body (above the ALLOWED_KEYS line). Use the exact triple from task_specifics — ("127.0.0.1", "::1", "localhost") — and raise HTTPException(status_code=403, detail="set-env requires loopback origin"). Defensive note: request.client may be None in pathological transports; treat that case as non-loopback (also 403). A safe expression is:
         host = request.client.host if request.client else None
         if host not in ("127.0.0.1", "::1", "localhost"):
             raise HTTPException(status_code=403, detail="set-env requires loopback origin")
    4. Leave the rest of the function body byte-for-byte identical: ALLOWED_KEYS check, value branch / pop branch, logger.info lines, and the return dict.

    Test change in tests/test_api.py:
    - Append a new test block at the end of the file (do not interleave with existing fixtures). Reuse the existing `client` fixture for Test 1. For Test 2, instantiate a second TestClient inline via the pattern documented in <interfaces>. Wrap the os.environ mutation in try/finally so the test cleans up after itself even on failure.
    - Use the `_mock_model` session fixture (autouse) implicitly — no additional model mocking is needed for this endpoint.
    - Name the tests `test_set_env_rejects_non_loopback`, `test_set_env_allows_loopback`, and (if included) `test_set_env_loopback_still_validates_allowlist`.

    Do not modify any other @router.post handler in system.py in this task — those are deferred to Task 2's audit file.
  </action>
  <verify>
    <automated>cd /Users/user4/Desktop/voice-design/OmniVoice &amp;&amp; python -m pytest tests/test_api.py -k "set_env" -x -q</automated>
  </verify>
  <done>
    - backend/api/routers/system.py imports Request from fastapi (single import line, not duplicated).
    - Handler signature is `async def set_env_var(request: Request, body: dict):`.
    - First executable statement in the handler body is the loopback guard raising 403 for non-allow-listed hosts.
    - Existing ALLOWED_KEYS / os.environ / logger / return behavior is unchanged.
    - `pytest tests/test_api.py -k set_env` passes with at least the two new tests green.
    - No other endpoint in system.py is touched.
  </done>
</task>

<task type="auto">
  <name>Task 2: Enumerate other unauthenticated POST endpoints in system.py (deferred-items audit)</name>
  <files>.planning/quick/260518-ivy-add-loopback-origin-check-to-system-set-/260518-ivy-deferred-items.md</files>
  <action>
    Create `260518-ivy-deferred-items.md` in this quick task's directory listing every `@router.post(...)` in backend/api/routers/system.py OTHER than `/system/set-env`, with one line each describing what the endpoint does and a one-line risk note. Use the enumeration already verified via grep (do not re-grep; the lines below are authoritative for this commit):

    - `/model/unload/{model_id}` (line 108) — unloads a named model from memory. Risk: a LAN host can force-evict the user's loaded TTS/ASR model, causing a re-load stall on next inference. Severity: low (no data exfil, no credential mutation).
    - `/system/logs/clear` (line 318) — truncates the backend log file. Risk: a LAN host can destroy diagnostic evidence (anti-forensics). Severity: low–medium.
    - `/system/logs/tauri/clear` (line 341) — truncates the frontend (Tauri) log file. Risk: same as above. Severity: low–medium.
    - `/system/flush-memory` (line 384) — forces a GC / VRAM-flush cycle. Risk: a LAN host can trigger repeated flushes to degrade performance. Severity: low.
    - `/clean-audio` (line 555) — accepts an uploaded WAV and runs demucs. Risk: a LAN host can upload arbitrary audio and consume CPU/GPU/disk on the user's machine. Severity: medium (resource exhaustion + writes to OUTPUTS_DIR).

    Format the file with a short header citing the trigger (PR #66 security review, Task #17 follow-up) and explicit "Out of scope for the 260518-ivy commit — to be triaged in a follow-up quick task or as part of Phase 5 (Opt-in Bug Reporting) security review." Reference Task #18 in our backlog.

    Do NOT modify backend/api/routers/system.py or any test in this task. This is documentation-only.
  </action>
  <verify>
    <automated>test -f /Users/user4/Desktop/voice-design/OmniVoice/.planning/quick/260518-ivy-add-loopback-origin-check-to-system-set-/260518-ivy-deferred-items.md &amp;&amp; grep -v '^#' /Users/user4/Desktop/voice-design/OmniVoice/.planning/quick/260518-ivy-add-loopback-origin-check-to-system-set-/260518-ivy-deferred-items.md | grep -c '/system/\|/model/\|/clean-audio' | awk '$1 &gt;= 5 {exit 0} {exit 1}'</automated>
  </verify>
  <done>
    - File exists at the expected path.
    - Contains exactly the five other POST routes from system.py with one-line descriptions and risk notes.
    - Explicitly marked as out-of-scope for this commit and referenced to Task #18 / follow-up.
    - No production code or tests were modified in this task.
  </done>
</task>

<task type="auto">
  <name>Task 3: Atomic commit on main</name>
  <files>.git (commit metadata)</files>
  <action>
    Stage exactly the three modified paths:
      - backend/api/routers/system.py
      - tests/test_api.py
      - .planning/quick/260518-ivy-add-loopback-origin-check-to-system-set-/260518-ivy-deferred-items.md
      - .planning/quick/260518-ivy-add-loopback-origin-check-to-system-set-/260518-ivy-PLAN.md (this plan — include so the artifact is traceable in git history)

    Verify with `git status` that no other files are staged inadvertently (no edits to other endpoints, no formatter sweeps, no .pyc files).

    Land directly on `main` (per user direction — no feature branch for this security fix). Use a HEREDOC commit message:

    Title: `security: add loopback origin check to /system/set-env`
    Body:
      - Reference: surfaced during PR #66 security review.
      - Closes a local-LAN credential-overwrite vector — the endpoint mutates os.environ for HF_TOKEN / TRANSLATE_API_KEY and the backend binds 0.0.0.0:3900, so any LAN host or local process could overwrite stored tokens. The vector existed pre-PR for in-memory state and was widened by PR #66's prefs.json persistence.
      - Notes: other POST endpoints in backend/api/routers/system.py share the same gap and are catalogued in `.planning/quick/260518-ivy.../260518-ivy-deferred-items.md` for follow-up (Task #18).
      - Co-Authored-By trailer for Claude per repo convention.

    Do NOT push to remote unless explicitly requested by the user later. Do NOT amend any prior commit. Do NOT skip hooks (no --no-verify). If a pre-commit hook fails, fix the underlying issue and create a NEW commit (do not amend).
  </action>
  <verify>
    <automated>cd /Users/user4/Desktop/voice-design/OmniVoice &amp;&amp; git log -1 --pretty=%s | grep -q '^security: add loopback origin check to /system/set-env$' &amp;&amp; git log -1 --name-only --pretty=format: | grep -q 'backend/api/routers/system.py' &amp;&amp; git status --porcelain | wc -l | awk '$1 == 0 {exit 0} {exit 1}'</automated>
  </verify>
  <done>
    - HEAD on `main` is a new commit titled exactly `security: add loopback origin check to /system/set-env`.
    - Commit touches at minimum: backend/api/routers/system.py, tests/test_api.py, the deferred-items file, and this PLAN.md.
    - `git status` is clean post-commit.
    - No push to remote.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| LAN host → backend (0.0.0.0:3900) | Untrusted: any device on the user's network can reach the backend |
| Local process (non-OmniVoice) → backend (loopback) | Semi-trusted: same-machine processes are still distinct security principals from the Tauri frontend, but cannot be distinguished at HTTP layer without OS-level auth (out of scope) |
| Tauri frontend → backend (loopback) | Trusted within OmniVoice's local-first model |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-ivy-01 | Tampering | POST /system/set-env from LAN host | mitigate | Loopback-only allow-list ("127.0.0.1", "::1", "localhost") on `request.client.host`; non-matching origin → HTTP 403 before any os.environ mutation. |
| T-ivy-02 | Elevation of Privilege | LAN host overwriting HF_TOKEN with attacker-controlled token, redirecting subsequent HF downloads | mitigate | Same loopback gate. Attacker on LAN can no longer reach the mutation path at all. |
| T-ivy-03 | Information Disclosure | Logger emits `Set environment variable: HF_TOKEN (length=N)` | accept | Length-only log; no value, no PII. Pre-existing behavior, no regression. |
| T-ivy-04 | Tampering | Local non-OmniVoice process on loopback still able to call /system/set-env | accept | Out of scope for this quick fix. OS-level UID/process auth would be required; defer to a future hardening pass. Same-machine processes already share write access to $HF_HOME/token under the local-first model. |
| T-ivy-05 | Spoofing | `X-Forwarded-For` header tricking the guard | mitigate-by-design | Guard reads `request.client.host` (the actual TCP peer), NOT any header. Documented in test rationale. |
| T-ivy-SC | Tampering | npm/pip installs in this commit | mitigate | No new package installs — `fastapi.Request` is already present in the pinned dependency set. Slopcheck not required for this commit. |
</threat_model>

<verification>
Run the new regression tests and confirm no other system.py endpoint behavior shifted:

```bash
cd /Users/user4/Desktop/voice-design/OmniVoice
python -m pytest tests/test_api.py -k "set_env" -x -q
python -m pytest tests/test_router_smoke.py -x -q   # smoke check — should remain green
git log -1 --stat   # confirm only the four intended paths were touched
grep -n 'request.client.host' backend/api/routers/system.py   # exactly one match expected, in set_env_var
```

Manual sanity (optional, can be skipped per yolo mode):
- Start the backend, then from a second machine on the LAN: `curl -X POST http://<host-ip>:3900/system/set-env -d '{"key":"HF_TOKEN","value":"x"}'` → expect 403.
- From the same machine: `curl -X POST http://127.0.0.1:3900/system/set-env -d '{"key":"HF_TOKEN","value":"x"}'` → expect 200.
</verification>

<success_criteria>
- `/system/set-env` returns 403 for any non-loopback caller and 200 (with env mutation) for loopback callers.
- All existing allow-list, env-mutation, logging, and return-shape behavior is preserved verbatim for the loopback path.
- New regression tests in `tests/test_api.py` cover both the 403 and 200 paths and pass.
- `260518-ivy-deferred-items.md` exists in the quick directory enumerating the other five POST routes in `system.py` with risk notes.
- Single atomic commit on `main` with title `security: add loopback origin check to /system/set-env`, body referencing PR #66, no other endpoints modified, `git status` clean.
- Local-first guarantee from CLAUDE.md is reinforced (not weakened): credentials cannot be mutated by anyone other than a same-machine principal.
</success_criteria>

<output>
Create `.planning/quick/260518-ivy-add-loopback-origin-check-to-system-set-/260518-ivy-SUMMARY.md` when done summarizing what shipped, the test results, the deferred items, and the commit SHA.
</output>
