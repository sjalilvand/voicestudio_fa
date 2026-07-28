---
id: TASK-1
title: Investigate OmniVoice VRAM/lifecycle bug (stuck model loads, unkillable abandoned jobs)
status: To Do
assignee: []
created_date: '2026-07-28 17:00'
updated_date: '2026-07-28 17:00'
labels:
  - omnivoice
  - bug
  - vram
  - lifecycle
  - mps
dependencies: []
priority: high
ordinal: 1000
---

## Description

OmniVoice (MPS backend) is chronically VRAM-starved, causing a recurring lifecycle failure:

1. A heavy model load exceeds the 1200s execution-time budget.
2. OmniVoice "abandons" the GPU-pool worker, but **cannot kill it**. The abandoned worker keeps running and **holds the MPS device**.
3. Every subsequent synth (REST `/v1/audio/speech`, `/generate`, and even the MCP `generate_speech`) queues behind the device-holding abandoned worker and hangs (60s-180s+ timeouts).

Evidence from `~/Library/Application Support/OmniVoice/omnivoice.log` (read 2026-07-28):
- `Model load exceeded 1200.0s; resetting GPU pool` appears **3 times**: 2026-07-20 11:34, 2026-07-28 16:22, 2026-07-28 16:58 (recurred ~36 min apart the same day, i.e. a retry cascade: stuck, retry, still stuck because the device is held).
- `abandoned ... cannot be killed: it keeps running and keeps holding the device` appears **34 times**.
- VRAM / memory-pressure events: **40 times**.

OmniVoice's own message references internal issues #730 / #1190.

The MCP path (`mcp__omnivoice__generate_speech`) works when the device is free (succeeded 2026-07-28 12:17 @35s and 12:30 @13s), but hangs once the abandoned worker holds the device (16:22 onward). v0.4.2 (released 2026-07-28) did NOT introduce this per its changelog (update-UX + model-repair + localization), so it predates the release.

## Acceptance Criteria

- [ ] Root cause of the VRAM starvation: which resident model + which load contends, and why the load exceeds 1200s of compute.
- [ ] Root cause of the unkillable abandoned worker (the lifecycle bug behind #730/#1190): why OmniVoice cannot kill/clean up an abandoned GPU-pool worker.
- [ ] A reproducer (input/state that reliably triggers the stuck load).
- [ ] Fix so abandoned workers are actually killed (release the device) OR so loads cannot starve past the budget.
- [ ] Verify the fix prevents recurrence under sustained use (no stuck loads in a long-run test).
