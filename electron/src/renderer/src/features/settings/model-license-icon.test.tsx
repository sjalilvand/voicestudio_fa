import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { describe, expect, it } from 'vitest';
import { modelLicenseStatus } from './model-license-contract';
import { ModelLicenseIcon } from './model-license-icon';

describe('model licence status icons', () => {
  it('maps unknown and future statuses to the unverified glyph, never a permissive one', () => {
    expect(modelLicenseStatus('restricted')).toBe('restricted');
    expect(modelLicenseStatus('separate_permission_required')).toBe('permission');
    for (const value of [undefined, '', 'unknown', 'permitted', 'allowed', 'future_status']) {
      expect(modelLicenseStatus(value)).toBe('unknown');
    }
  });

  it('renders a decorative, distinct glyph per status', () => {
    const shapes = new Set<string>();
    for (const status of ['restricted', 'permission', 'unknown'] as const) {
      const host = document.createElement('div');
      const root = createRoot(host);
      act(() => root.render(<ModelLicenseIcon status={status} />));
      const svg = host.querySelector('svg')!;
      expect(svg.getAttribute('aria-hidden')).toBe('true');
      expect(svg.getAttribute('data-license-status')).toBe(status);
      shapes.add(svg.innerHTML);
      act(() => root.unmount());
    }
    expect(shapes.size).toBe(3);
  });
});
