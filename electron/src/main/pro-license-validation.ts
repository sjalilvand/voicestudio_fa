export type LicenseResponse = {
  activated?: boolean;
  valid?: boolean;
  deactivated?: boolean;
  instance?: { id?: string };
  license_key?: { status?: string; expires_at?: string | null };
  meta?: { store_id?: number; product_id?: number; variant_id?: number };
};

export function matchesProLicense(
  response: LicenseResponse,
  expected: { store: number; product: number; variants: number[] },
  now = Date.now(),
): boolean {
  const expiry = response.license_key?.expires_at;
  return response.meta?.store_id === expected.store &&
    response.meta?.product_id === expected.product &&
    expected.variants.includes(response.meta?.variant_id ?? -1) &&
    response.license_key?.status === 'active' &&
    (!expiry || (Number.isFinite(Date.parse(expiry)) && Date.parse(expiry) > now));
}
