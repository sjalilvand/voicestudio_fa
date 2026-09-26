import { describe, expect, it } from 'vitest';
import { matchesProLicense } from './pro-license-validation';

const expected = { store: 1, product: 2, variants: [3, 5] };
const active = { meta: { store_id: 1, product_id: 2, variant_id: 3 }, license_key: { status: 'active', expires_at: null } };

describe('Pro licence response validation', () => {
  it('accepts only the configured product and an active, unexpired key', () => {
    expect(matchesProLicense(active, expected)).toBe(true);
    expect(matchesProLicense({ ...active, meta: { ...active.meta, variant_id: 5 } }, expected)).toBe(true);
    expect(matchesProLicense({ ...active, meta: { ...active.meta, variant_id: 4 } }, expected)).toBe(false);
    expect(matchesProLicense({ ...active, license_key: { status: 'disabled', expires_at: null } }, expected)).toBe(false);
    expect(matchesProLicense({ ...active, license_key: { status: 'active', expires_at: '2020-01-01T00:00:00Z' } }, expected)).toBe(false);
    expect(matchesProLicense({ ...active, license_key: { status: 'active', expires_at: 'broken' } }, expected)).toBe(false);
  });
});
