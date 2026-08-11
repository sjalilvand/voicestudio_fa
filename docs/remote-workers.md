# Remote GPU workers

Run OmniVoice on this machine, but hand individual jobs to GPUs on your other
machines. Results come back here.

This is **opt-in and off by default**. Until you turn it on and approve a
worker, nothing leaves your computer, no port is opened, and the app behaves
exactly as it did before.

> **Not the same as [Remote backend](remote-gpu.md).** That points this app at
> a backend running somewhere else, so the whole app — your projects, your
> voices, your history — lives on that machine. This keeps everything here and
> only sends out individual tasks. Both still work; pick whichever matches what
> you want.

---

## What you need

* OmniVoice on both machines, on versions no more than two releases apart.
* The worker machine must be able to **reach** this one over the network. Same
  LAN is enough at home; across networks, a VPN such as
  [Tailscale](https://tailscale.com/) is the reliable answer. The worker dials
  out to the control plane, so the *worker* never needs a public address or a
  forwarded port — but this machine does need to be reachable.
* The engine you want to use must be installed on the worker. A worker reports
  what it actually has, and the scheduler only sends it work it can run.

## Setting it up

**1. On this machine (the one you work on):**

Settings → System → Remote workers → turn on **Use remote workers**.

The panel shows the address workers should connect to, and a **Generate token**
button.

**2. Generate an enrollment token.**

Copy it immediately. It is shown once, works once, and expires after 15
minutes — only its hash is stored here, so it cannot be shown again. If you
lose it, generate another.

**3. On the worker machine:**

Start OmniVoice in worker mode and give it the token:

```bash
OMNIVOICE_WORKER_TOKEN='ovw_…' OMNIVOICE_WORKER_MODE=1 omnivoice
```

The worker generates its own key pair on first run, presents the token once to
enroll, and proves possession of that key on every later connection. The token
is spent at that point and never used again.

**4. Approve the worker.**

It appears in the list on this machine. Approving it is what allows your audio,
reference voices, and text to be sent there — consent is recorded per worker,
because agreeing to use your own desktop is not agreeing to use whatever gets
added later.

## What you can change

| Control | What it does |
|---|---|
| Enable / disable | Stop sending new work without removing the worker |
| Preferred | Prefer this worker when several can run a task |
| Resume | Clear a paused worker after you've fixed it |
| Remove | Revoke its key — it cannot reconnect without a new token |

That is the whole surface, deliberately. **Preferred** pins new work to that
worker; if it is asleep, VoiceStudio names that worker instead of silently
sending the job elsewhere. There are no routing weights or per-model
concurrency settings: concurrency is measured from free VRAM at runtime because
a configured value silently corrupts output on compiled models and crashes
small cards.

## What runs remotely

**Speech synthesis and audiobook chapters.** Audiobooks are dispatched one
chapter at a time; if a worker repeatedly fails, the failed chapter and the
rest of that book run locally and the job reports one combined notice. ASR,
diarization, translation and RVC still run on this machine. Dictation always
runs here, deliberately and permanently, because there latency *is* the
feature. The remaining operations are being ported one at a time.

The picker knows this. It resolves against the surface you are on, so a chosen
worker reads **Local** on a tab whose work has no remote path yet and names the
reason, instead of showing a green dot next to a GPU that receives nothing.
The Dictation surface states that it always uses this machine without showing
the generic "not ported yet" notice.

While the port is in progress, the only way to place a task by hand is
`POST /workers/tasks` — a **development-only** endpoint. It is loopback-only,
sits behind the same opt-in as everything else here, takes a mandatory
deadline, submits one task and waits for it. It is not a stable API and goes
away once generation routes itself.

## How work is placed

A task goes to a worker that is connected, approved, enabled, has the engine,
has a free slot, and is not paused. An explicitly preferred worker is a hard
choice. Without one, VoiceStudio chooses the least-busy eligible worker and
breaks ties in favour of a worker that already has the model loaded — a warm
model is seconds away where a cold one can be minutes.
Model identities are stable scheduling keys; the worker reports a separate
human-readable model name, so label changes do not split capacity or history.

If every capable worker is busy, the task waits. If **no** worker can run it at
all, it fails immediately and says so, rather than waiting for something that
will never happen.

## When things go wrong

**A worker disconnects mid-task.** Nothing is failed straight away. It has a
grace window to come back, and if it returns carrying a finished result, that
result is used — the task is never run twice just because a network blip
happened. Only when the window expires is the task retried elsewhere.

**A worker fails repeatedly.** After three consecutive failures that are
actually its fault, it is paused for a minute, then automatically given one
task to prove itself. Repeated trips back off further, up to thirty minutes.
Being busy, being asked for an engine it doesn't have, or losing its network
connection are *not* counted against it.

Long-running work sends explicit keepalive frames. They let a slow render live
past the two-minute progress lease, but cannot extend it beyond the current
phase budget when the worker is genuinely stuck.

The row tells you what happened in words — "Paused after 3 failures … retrying
in 45s" — and **Resume** clears it immediately when you've fixed the machine.

**You quit the app mid-task.** Remote work keeps running on the worker. On next
launch OmniVoice recovers those tasks and reconciles with each worker about
what is genuinely still in flight.

**Version mismatch.** A worker more than two releases away from this machine is
refused with a message saying which side to update, rather than failing tasks
mysteriously.

## Security

* **All traffic is TLS.** There is no way to disable verification.
* This machine generates its own certificate. The enrollment token carries that
  certificate's fingerprint, and the worker pins it — so a machine on the same
  café Wi-Fi cannot impersonate your control plane.
* **A worker's identity is a key it generates and never sends.** The worker ID
  is a display name, not a credential; knowing it gets an attacker nothing.
* **Removing a worker revokes its key**, and that survives restarting the app.
* Idle worker sessions use TLS keepalives, so NAT mappings stay open without
  the control plane mistaking its own keepalive interval for abusive traffic.
* Tasks name engines from a fixed registry, never file paths — a path here
  would be remote code execution on every worker.

**What a worker can see:** to synthesise your text it has to receive that text,
and to clone a voice it has to receive the reference audio. There is no way
around that. Only add machines you control, which is why approval is per
worker and never implicit.

## Turning it off

Settings → System → Remote workers → toggle off. The listening socket closes
and the background loops stop. Your enrolled workers and their settings are
kept, so turning it back on does not mean setting everything up again.

## Environment variables

| Variable | Purpose |
|---|---|
| `OMNIVOICE_REMOTE_WORKERS` | `1`/`0` — enable without the UI (headless, Docker) |
| `OMNIVOICE_WORKER_PORT` | Control-plane port (default `7443`) |
| `OMNIVOICE_WORKER_ENDPOINT_HOST` | Override the address shown to workers |
| `OMNIVOICE_WORKER_MODE` | `1` on the worker machine |
| `OMNIVOICE_WORKER_TOKEN` | Enrollment token, first run only |

Only one VoiceStudio instance can accept remote workers on a given port. If
another instance already owns the configured port, the app continues running
with remote workers unavailable and shows the conflict in Settings. Close the
other instance, or give this one a different `OMNIVOICE_WORKER_PORT` and
restart it.

State lives under your data directory in `workers/`: the certificate and key,
the worker's own key, and received artifacts.
