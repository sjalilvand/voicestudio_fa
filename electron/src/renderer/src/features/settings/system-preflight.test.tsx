import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
const mock = vi.hoisted(() => ({ api: vi.fn() }));
// Keys the fake catalog "knows" — mirrors what en.json carries for the
// structured preflight variants; everything else counts as missing so the
// component must fall back to the backend text.
const catalog = vi.hoisted(() =>
  new Set([
    'setup.check_arch_label',
    'setup.check_arch_detail',
    'setup.check_arch_fix',
    'setup.check_ram_low_detail',
    'setup.check_ram_low_fix',
    'setup.check_gpu_none_detail',
    'setup.check_gpu_none_fix',
    'setup.check_gpu_none_label',
    'setup.check_os_detail',
    'setup.check_network_auto_canonical_detail',
  ]),
);
vi.mock('@/lib/api/client', () => ({ apiJson: mock.api }));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, values?: Record<string, unknown>) =>
      values && Object.keys(values).length > 0
        ? `${key}(${JSON.stringify(values)})`
        : key,
    i18n: { exists: (key: string) => catalog.has(key) },
  }),
}));
import { SystemPreflight } from './system-preflight';
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
function mount() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <SystemPreflight />
    </QueryClientProvider>,
  );
}
it('runs only on explicit request and renders backend diagnostics and fixes', async () => {
  mock.api.mockResolvedValue({
    checks: [
      { id: 'ram', label: 'Memory', status: 'warn', detail: '8 GB', fix: 'Use a smaller model' },
    ],
  });
  mount();
  expect(mock.api).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'setup.system_check' }));
  await screen.findByText('Use a smaller model');
  expect(mock.api).toHaveBeenCalledWith(
    '/setup/preflight',
    expect.objectContaining({ signal: expect.any(AbortSignal) }),
  );
  fireEvent.click(screen.getByRole('button', { name: 'setup.recheck' }));
  await waitFor(() => expect(mock.api).toHaveBeenCalledTimes(2));
});
it('shows failure and permits an explicit retry without automatic probes', async () => {
  mock.api.mockRejectedValue(new Error('unreachable'));
  mount();
  fireEvent.click(screen.getByRole('button', { name: 'setup.system_check' }));
  await screen.findByRole('alert');
  expect(mock.api).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('button', { name: 'setup.system_check' })).toBeEnabled();
});
it('renders the Windows-on-ARM notice from the translation catalog, not backend text', async () => {
  mock.api.mockResolvedValue({
    checks: [
      {
        id: 'arch',
        label: 'Windows on ARM',
        status: 'warn',
        detail: 'English detail',
        fix: 'English fix',
      },
    ],
  });
  mount();
  fireEvent.click(screen.getByRole('button', { name: 'setup.system_check' }));
  await screen.findByText('setup.check_arch_label');
  expect(screen.getByText('setup.check_arch_detail')).toBeTruthy();
  expect(screen.getByText('setup.check_arch_fix')).toBeTruthy();
  expect(screen.queryByText('English detail')).toBeNull();
});
it('renders structured check variants (key + values) from the catalog', async () => {
  mock.api.mockResolvedValue({
    checks: [
      {
        id: 'ram',
        label: 'System RAM',
        status: 'warn',
        detail: '7.6 GB total (12+ GB recommended)',
        fix: 'Long videos may hit swap. Keep other apps closed during dubbing.',
        key: 'low',
        values: { gb: '7.6', recommended: 12 },
      },
      {
        id: 'gpu',
        label: 'GPU acceleration',
        status: 'warn',
        detail: 'No compatible GPU detected — running CPU-only.',
        fix: 'Everything works on CPU, just ~10× slower than a GPU.',
        key: 'none',
        values: {},
      },
    ],
  });
  mount();
  fireEvent.click(screen.getByRole('button', { name: 'setup.system_check' }));
  await screen.findByText(/setup\.check_ram_low_detail\(/);
  expect(screen.getByText(/setup\.check_ram_low_fix\(/)).toBeTruthy();
  // Empty values render the bare key (mock passes no interpolation suffix).
  expect(screen.getByText('setup.check_gpu_none_detail')).toBeTruthy();
  expect(screen.queryByText('7.6 GB total (12+ GB recommended)')).toBeNull();
  expect(screen.queryByText('No compatible GPU detected — running CPU-only.')).toBeNull();
});
it('falls back to backend text when the catalog lacks the variant', async () => {
  mock.api.mockResolvedValue({
    checks: [
      {
        id: 'ram',
        label: 'System RAM',
        status: 'warn',
        detail: '9.9 GB total (new advice)',
        fix: null,
        key: 'future_variant',
        values: { gb: '9.9' },
      },
    ],
  });
  mount();
  fireEvent.click(screen.getByRole('button', { name: 'setup.system_check' }));
  await screen.findByText('9.9 GB total (new advice)');
  expect(screen.queryByText(/future_variant/)).toBeNull();
});
it('uses the variant label when present, the plain id label otherwise', async () => {
  mock.api.mockResolvedValue({
    checks: [
      {
        id: 'network',
        label: 'Network (hf-mirror.com)',
        status: 'pass',
        detail: 'Reachable (100 ms)',
        fix: null,
        key: 'auto_canonical',
        values: { host: 'hf-mirror.com', latency: ' (100 ms)' },
      },
      {
        id: 'os',
        label: 'Operating system',
        status: 'pass',
        detail: 'Windows-10 (AMD64)',
        fix: null,
        key: 'default',
        values: { version: 'Windows-10', arch: 'AMD64' },
      },
    ],
  });
  mount();
  fireEvent.click(screen.getByRole('button', { name: 'setup.system_check' }));
  // network: no variant label in the catalog → falls back to the plain
  // label key, which also is not in the fake catalog → backend label kept.
  await screen.findByText('Network (hf-mirror.com)');
  expect(screen.getByText(/setup\.check_network_auto_canonical_detail\(/)).toBeTruthy();
  // os: key "default" maps to the plain variant-less detail key.
  expect(screen.getByText(/setup\.check_os_detail\(/)).toBeTruthy();
});
