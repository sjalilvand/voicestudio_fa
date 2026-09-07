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
 * The fix tracks which stages were actually observed (sticky, via the
 * `bootstrap_status` poll) and derives doneness + journey-chrome visibility
 * from that instead of list position.
 */
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
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
});
