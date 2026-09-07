/**
 * Regression tests for #1894 — the first-run INSTALLING journey was shown on
 * every launch, with green ticks for work that never ran.
 *
 * `BootstrapSplash` used to derive "done" purely from `STEPS.indexOf(stage)`
 * (BootstrapSplash.jsx:453/774 pre-fix): on a warm start Rust jumps straight
 * from `checking` to `starting_backend` (bootstrap.rs finds the venv healthy
 * and returns early), so `downloading_uv`, `creating_venv` and
 * `installing_deps` — including the "first run, 5–10 min." label — all
 * rendered with a green DONE tick for work that never happened. The same
 * fabrication hit a repair sync (venv exists, only `installing_deps` runs,
 * but `downloading_uv`/`creating_venv` still rendered done), and `JourneyRail`
 * hardcoded Setup=done/Installing=active regardless of `stage`.
 *
 * The fix tracks which stages were actually observed and derives doneness +
 * journey-chrome visibility from that instead of list position.
 *
 * Two follow-up findings from bot review on PR #1896 are covered at the end:
 *   - the ~1s `bootstrap_status` poll can miss a stage that starts and
 *     finishes between samples, so stage-tagged `bootstrap-log` lines are
 *     unioned in as independent proof a stage ran;
 *   - a Retry restarts the bootstrap, so stages observed during the previous
 *     attempt must not carry over and render as done in the new one.
 */
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react';
import { BootstrapSplash } from '../components/BootstrapSplash';

vi.mock('@tauri-apps/api/core', () => ({
  invoke: vi.fn(async () => null),
}));
vi.mock('@tauri-apps/api/event', () => ({
  listen: vi.fn(async () => () => {}),
}));
vi.mock('@tauri-apps/plugin-opener', () => ({
  revealItemInDir: vi.fn(),
}));

beforeEach(() => {
  // Not in a Tauri context: the log/progress subscription effects no-op.
  delete window.__TAURI_INTERNALS__;
});

describe('BootstrapSplash — observed-stage tracking (#1894)', () => {
  it('warm start (checking -> starting_backend): no fabricated done ticks, no "first run" chrome', () => {
    const { rerender } = render(<BootstrapSplash stage="checking" message={null} />);

    // The journey rail and "Installing" heading must not appear before any
    // real install stage has ever been observed.
    expect(screen.queryByText('Installing')).toBeNull();
    expect(screen.queryByText('Setup')).toBeNull();
    expect(screen.queryByText('Models & engines')).toBeNull();

    rerender(<BootstrapSplash stage="starting_backend" message={null} />);

    // Live stage label still shows — this is not a blank screen.
    expect(screen.getByText('Starting backend…')).toBeInTheDocument();
    // The install journey never appeared: bootstrap.rs never entered any of
    // downloading_uv/creating_venv/installing_deps on this run.
    expect(screen.queryByText('Installing')).toBeNull();
    expect(screen.queryByText('Downloading uv (Python package manager)…')).toBeNull();
    expect(screen.queryByText('Creating Python virtual environment…')).toBeNull();
    expect(screen.queryByText(/first run, 5.10 min/)).toBeNull();
  });

  it('repair sync (checking -> installing_deps): installing_deps active, earlier steps not fabricated done', () => {
    const { rerender } = render(<BootstrapSplash stage="checking" message={null} />);
    rerender(<BootstrapSplash stage="installing_deps" message={null} />);

    // Real install work observed: the journey chrome comes back (both the
    // JourneyRail item and the section heading render the same "Installing"
    // string, so there are two matches).
    expect(screen.getAllByText('Installing').length).toBeGreaterThan(0);
    // The live stage label (masthead) and the step-list item both render the
    // "first run, 5-10 min" text; scope to the step-list one inside the <ol>.
    const activeLabel = screen.getAllByText(/first run, 5.10 min/).find((el) => el.closest('ol'));
    expect(activeLabel).toBeInTheDocument();
    // The active step renders semibold, not the muted "done" styling.
    expect(activeLabel.className).toMatch(/font-semibold/);
    expect(activeLabel.className).not.toMatch(/text-fg-muted/);

    // downloading_uv/creating_venv were never entered by Rust on a repair
    // sync — they must render as pending, not done.
    const uvStep = screen.getByText('Downloading uv (Python package manager)…');
    const venvStep = screen.getByText('Creating Python virtual environment…');
    expect(uvStep.className).not.toMatch(/text-fg-muted/);
    expect(venvStep.className).not.toMatch(/text-fg-muted/);
  });

  it('genuine first run walks all five stages: every step is marked done as it passes (no regression)', () => {
    const stages = [
      'checking',
      'downloading_uv',
      'creating_venv',
      'installing_deps',
      'starting_backend',
    ];
    const { rerender } = render(<BootstrapSplash stage={stages[0]} message={null} />);

    for (let i = 1; i < stages.length; i += 1) {
      rerender(<BootstrapSplash stage={stages[i]} message={null} />);
      // Every stage strictly before the current one must show as done
      // (muted styling), since this run genuinely walked through each one.
      for (let j = 0; j < i; j += 1) {
        const stepLabel = screen.getByText(
          {
            checking: 'Checking environment…',
            downloading_uv: 'Downloading uv (Python package manager)…',
            creating_venv: 'Creating Python virtual environment…',
            installing_deps: /first run, 5.10 min/,
            starting_backend: 'Starting backend…',
          }[stages[j]],
        );
        expect(stepLabel.className).toMatch(/text-fg-muted/);
      }
    }
  });

  it('a stage the 1s poll never sampled still counts as done when its logs prove it ran', async () => {
    // Greptile finding on #1896: `bootstrap_status` is sampled ~1/s, so on a
    // fast disk `creating_venv` can start and finish between two samples and
    // never be polled. Stage-tagged bootstrap logs are emitted as the work
    // happens, so they are independent proof the stage ran.
    window.__TAURI_INTERNALS__ = {};
    const { invoke } = await import('@tauri-apps/api/core');
    invoke.mockImplementation(async (cmd) =>
      cmd === 'get_bootstrap_logs'
        ? [{ stage: 'creating_venv', line: 'Creating virtualenv at .venv' }]
        : null,
    );

    // Poll sequence skips creating_venv entirely.
    const { rerender } = render(<BootstrapSplash stage="downloading_uv" message={null} />);
    rerender(<BootstrapSplash stage="installing_deps" message={null} />);

    await waitFor(() => {
      const venvStep = screen.getByText('Creating Python virtual environment…');
      expect(venvStep.className).toMatch(/text-fg-muted/);
    });
  });

  it('a retry drops stages observed during the previous attempt', () => {
    // Greptile finding on #1896: the observed set was add-only and the splash
    // stays mounted across a Retry, so a stage the FAILED attempt reached
    // would still render done in the new attempt even if that attempt skips
    // it. Arriving back at `checking` from elsewhere means a new attempt.
    const { rerender } = render(<BootstrapSplash stage="checking" message={null} />);
    rerender(<BootstrapSplash stage="downloading_uv" message={null} />);
    rerender(<BootstrapSplash stage="installing_deps" message={null} />);
    rerender(<BootstrapSplash stage="failed" message="uv sync failed" />);

    // Retry: Rust goes back to `checking`, then this attempt finds the venv
    // healthy and jumps straight to starting_backend.
    rerender(<BootstrapSplash stage="checking" message={null} />);
    rerender(<BootstrapSplash stage="starting_backend" message={null} />);

    // Nothing from the previous attempt may be presented as this attempt's
    // completed work — so the install chrome is gone entirely again.
    expect(screen.queryByText('Downloading uv (Python package manager)…')).toBeNull();
    expect(screen.queryByText(/first run, 5.10 min/)).toBeNull();
    expect(screen.getByText('Starting backend…')).toBeInTheDocument();
  });

  it('logs arriving after Retry but before the next poll are not discarded', async () => {
    // Greptile finding on ece08bd7: the attempt boundary was stamped when the
    // ~1s poll first reported `checking`, which lands AFTER the Rust side has
    // already emitted the new attempt's first log lines — so that evidence was
    // filtered out as "previous attempt" and a fast stage missed by polling
    // stayed pending. The boundary must open when the retry is initiated.
    window.__TAURI_INTERNALS__ = {};
    const { invoke } = await import('@tauri-apps/api/core');
    const { listen } = await import('@tauri-apps/api/event');
    const handlers = {};
    listen.mockImplementation(async (name, cb) => {
      handlers[name] = cb;
      return () => {};
    });
    invoke.mockImplementation(async () => null);

    const { rerender } = render(<BootstrapSplash stage="failed" message="uv sync failed" />);
    await waitFor(() => expect(handlers['bootstrap-log']).toBeTypeOf('function'));

    // User clicks Retry — this opens the new attempt.
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /^Retry$/ }));
    });

    // Rust immediately emits the new attempt's logs, still before the poll
    // has reported `checking`.
    await act(async () => {
      handlers['bootstrap-log']({
        payload: { stage: 'creating_venv', line: 'Creating virtualenv at .venv' },
      });
    });

    // Only now does the poll catch up, and it never samples creating_venv.
    rerender(<BootstrapSplash stage="checking" message={null} />);
    rerender(<BootstrapSplash stage="installing_deps" message={null} />);

    // The log line proved creating_venv ran in THIS attempt; it must not have
    // been discarded by a boundary stamped after it arrived.
    await waitFor(() => {
      const venvStep = screen.getByText('Creating Python virtual environment…');
      expect(venvStep.className).toMatch(/text-fg-muted/);
    });
  });

  it('a retry whose restart stage the poll never sampled still drops the old evidence', () => {
    // CodeRabbit finding on 5e9538a0: a retry can go failed -> checking ->
    // starting_backend inside one ~1s sample window, so the poll observes
    // only failed -> starting_backend. Keying the reset solely off arriving
    // at a restart stage would leave the FAILED attempt's stages in place and
    // present them as this attempt's completed work.
    const { rerender } = render(<BootstrapSplash stage="checking" message={null} />);
    rerender(<BootstrapSplash stage="downloading_uv" message={null} />);
    rerender(<BootstrapSplash stage="installing_deps" message={null} />);
    rerender(<BootstrapSplash stage="failed" message="uv sync failed" />);

    // Retry — and the poll misses `checking` entirely.
    rerender(<BootstrapSplash stage="starting_backend" message={null} />);

    expect(screen.getByText('Starting backend…')).toBeInTheDocument();
    // Nothing from the failed attempt may be shown as this attempt's work.
    expect(screen.queryByText('Downloading uv (Python package manager)…')).toBeNull();
    expect(screen.queryByText(/first run, 5.10 min/)).toBeNull();
    expect(screen.queryByText('Installing')).toBeNull();
  });
});
