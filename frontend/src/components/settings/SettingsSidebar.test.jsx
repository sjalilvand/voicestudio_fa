import { describe, it, expect, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import React from 'react';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import SettingsSidebar from './SettingsSidebar';

describe('SettingsSidebar — zero-match search empty state', () => {
  it('renders a "no results" message with the query and a Clear action instead of a blank nav', () => {
    const onClearSearch = vi.fn();
    render(
      <SettingsSidebar
        visibleIds={new Set()}
        active="appearance"
        onSelect={() => {}}
        query="zzz-no-such-setting"
        onClearSearch={onClearSearch}
      />,
    );
    const empty = screen.getByTestId('settings-search-empty');
    expect(empty.textContent).toContain('zzz-no-such-setting');
    // Neither the (empty) narrow <select> nor any rail item renders.
    expect(screen.queryByTestId('settings-nav-select')).toBeNull();
    expect(screen.queryByTestId('settings-nav-general')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Clear' }));
    expect(onClearSearch).toHaveBeenCalledTimes(1);
  });

  it('renders the full grouped nav (and the narrow select) when nothing is filtered', () => {
    render(<SettingsSidebar active="appearance" onSelect={() => {}} />);
    expect(screen.queryByTestId('settings-search-empty')).toBeNull();
    expect(screen.getByTestId('settings-nav-select')).toBeInTheDocument();
    expect(screen.getByTestId('settings-nav-appearance')).toBeInTheDocument();
    expect(screen.queryByTestId('settings-nav-general')).toBeNull();
    expect(screen.getByTestId('settings-nav-about')).toBeInTheDocument();
  });

  it('keeps the wide category rail independently scrollable', () => {
    render(<SettingsSidebar active="appearance" onSelect={() => {}} />);
    expect(screen.getByTestId('settings-nav-scroll')).toHaveClass('overflow-y-auto');
    expect(screen.getByTestId('settings-nav-scroll')).toHaveClass('overscroll-contain');
  });

  it('switches navigation from scaled shell width, never raw viewport width', () => {
    render(<SettingsSidebar active="appearance" onSelect={() => {}} />);
    const nav = screen.getByRole('navigation', { name: 'Settings' });
    expect(nav.className).toContain('@min-[760px]/settings-shell:flex');
    expect(nav.className).not.toMatch(/(?:^|\s)min-\[760px\]:/);

    const settingsPage = readFileSync(resolve(process.cwd(), 'src/pages/Settings.jsx'), 'utf8');
    expect(settingsPage).toContain('[container-name:settings-shell]');
    expect(settingsPage).toContain('@min-[760px]/settings-shell:grid');
    expect(settingsPage).not.toMatch(/(?:^|\s)min-\[760px\]:/);
  });

  it('renders only the matching categories when a filter set is provided', () => {
    render(
      <SettingsSidebar
        visibleIds={new Set(['network'])}
        active="network"
        onSelect={() => {}}
        query="proxy"
        onClearSearch={() => {}}
      />,
    );
    expect(screen.getByTestId('settings-nav-network')).toBeInTheDocument();
    expect(screen.queryByTestId('settings-nav-general')).toBeNull();
    expect(screen.queryByTestId('settings-search-empty')).toBeNull();
  });
});
