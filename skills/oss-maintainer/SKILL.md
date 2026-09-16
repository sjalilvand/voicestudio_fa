---
name: oss-maintainer
description: Triage GitHub issues, review contributor pull requests, diagnose CI, and prepare explicitly requested releases using the target repository's rules. Use for repository maintenance work, not ordinary VoiceStudio audio generation.
---

# OSS maintenance

Read the target repository's AGENTS.md, CLAUDE.md, contribution guide, and release documentation first. Their policies override this general workflow. Installing this skill does not authorize merges, releases, issue closures, or messages to contributors.

## Triage and implementation

- Inspect current code and existing PRs before duplicating a reported fix. Reuse contributor work where it solves the problem; retain attribution.
- Reproduce the reported behavior where possible. Separate confirmed failures from diagnosis, and record meaningful limitations in the PR.
- Fix the cause with the smallest complete change. Test observable behavior where it can regress; do not mistake a source-text assertion for an end-to-end test.
- Preserve local changes. Use an isolated worktree when branch switching would disturb them.
- Read existing CI failures and reviewer comments before rerunning work. Diagnose failures before retries; never hide a failing gate behind a successful piped command.
- Keep user-facing docs and required translations aligned with the implementation.

## Review and authorized landing

Review the current diff, bot findings, and required checks against current main. Resolve material findings on the PR branch before landing; do not merge first and promise a follow-up. Refresh stale branches using the repository's policy and preserve contributor commits.

Before an authorized merge, verify required checks are green, the head has not changed, and the PR is mergeable. After landing, inspect main's own runs; investigate regressions immediately. Report remaining blockers without inventing a successful verification.

## Release preparation

Preparing CI or packaging is distinct from publishing. Do not tag, bump versions, enable publishing, or cut a release unless that action is authorized.

Use the repository's version source of truth, changelog format, supported platforms, and distribution channels. Validate packaging and workflows without publishing when that is the requested scope. After an authorized release, verify actual artifacts, release notes, updater metadata, and requested registry channels; a green build alone does not prove distribution.

## Communication

Lead with the outcome and evidence. Credit concrete contributor work. Do not close stale issues merely because of age, or claim reporter confirmation that has not occurred. For authorized closures, give the resolution and what evidence would justify reopening.

## VoiceStudio-specific routing

When maintaining debpalash/VoiceStudio, consult its current rules rather than old architecture assumptions:
- Electron development and packaging: `electron/README.md`, `electron/package.json`, and `.github/workflows/`.
- Backend contracts: running `/openapi.json`, `backend/api/`, and targeted tests.
- Release channels and version ownership: `docs/RELEASING.md` and CLAUDE.md. Never infer a version bump from a fix request.
- Read CodeRabbit/Greptile findings and required CI before merging. Follow main's post-merge CI.
- Preserve local-first behavior, cross-platform behavior, model-install consent, synthetic-audio marking, and localization requirements.
