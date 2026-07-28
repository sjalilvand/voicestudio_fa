---
id: TASK-2
title: Exploration - durable fixes for OmniVoice VRAM pressure / synth reliability
status: To Do
assignee: []
created_date: '2026-07-28 17:00'
updated_date: '2026-07-28 17:00'
labels:
  - omnivoice
  - exploration
  - vram
  - reliability
dependencies:
  - TASK-1
priority: medium
ordinal: 2000
---

## Description

While TASK-1 investigates the root lifecycle bug, evaluate these durable mitigations (from OmniVoice's own error message + the voice-on-reaction integration findings) so the TTS is reliable for unattended / reaction-triggered use. Document the tradeoff of each, then pick the one(s) to adopt.

Candidates to explore:

1. **Flush caches / Unload the resident model** (OmniVoice UI: Settings -> Models, or an API call) before a heavy/long synth, to free VRAM so the load does not starve. Question: can this be automated (API or script) so it runs before each long synth or on a schedule?
2. **Set the engine to CPU** (Settings -> Models) to remove MPS VRAM contention; stable but slower. Quantify the speed/quality tradeoff and whether it is acceptable for the voice-on-reaction use case.
3. **Raise `OMNIVOICE_GENERATE_TIMEOUT_S`** to tolerate long generations. Caveat: this does NOT fix the unkillable-worker hang (the device stays held regardless); evaluate whether it helps or only delays the failure.
4. **Shorter text per synth**: chunk long messages into multiple shorter synths to reduce per-call load. Evaluate the chunking strategy and how to concatenate the audio.
5. **Plugin-side PocketTTS fallback** (deployed 2026-07-28 in the hermes-agent `table_image_fallback` voice module, `_voice.py`): on the OmniVoice-trigger emoji, try OmniVoice; on timeout/failure, fall back to PocketTTS. Makes the voice-on-reaction feature robust regardless of OmniVoice's state (OmniVoice quality when healthy, PocketTTS speed as fallback). This complements, not replaces, TASK-1.

## Acceptance Criteria

- [ ] For each candidate: documented tradeoff (reliability gain vs cost/complexity/quality).
- [ ] Pick the durable fix(es) to adopt for unattended use; record the decision (and link TASK-1's root cause).
- [ ] If a candidate is automated (e.g. auto-flush before a long synth), implement and verify it prevents the stuck-load recurrence.
