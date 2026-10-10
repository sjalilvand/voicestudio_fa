import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import en from '@/i18n/locales/en.json';
import {
  MODEL_LICENCE_REQUIRED_EVENT,
  modelLicenceRequirements,
  type ModelLicenceRequirement,
} from './model-license-contract';

const mock = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock('@/lib/api/client', () => {
  class ApiError extends Error {
    constructor(
      readonly status: number,
      readonly detail: string,
      readonly payload: unknown = null,
    ) {
      super(detail);
    }
  }
  return { apiJson: mock.api, ApiError };
});
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key.split('.').reduce((value: any, part) => value?.[part], en) ?? key,
  }),
}));
import { ApiError } from '@/lib/api/client';
import {
  ModelLicenceAccepted,
  ModelLicenceAcceptanceForm,
  ModelLicenceGate,
} from './model-licence-acceptance';

const gated: ModelLicenceRequirement = {
  repo_id: 'test/noncommercial',
  license: 'CC-BY-NC-4.0',
  category: 'noncommercial',
  fingerprint: `v1:${'a'.repeat(64)}`,
};

let host: HTMLDivElement;
let root: Root;
const text = () => document.body.textContent ?? '';
const button = (name: string) =>
  Array.from(document.querySelectorAll('button')).find((item) => item.textContent === name);
async function render(node: React.ReactNode) {
  const client = new QueryClient();
  await act(async () =>
    root.render(<QueryClientProvider client={client}>{node}</QueryClientProvider>),
  );
}
async function confirmAndAccept() {
  await act(async () =>
    (document.querySelector('input[type="checkbox"]') as HTMLInputElement).click(),
  );
  await act(async () => button(en.modelLicense.accept)!.click());
}

beforeEach(() => {
  (globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
  mock.api.mockReset();
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

describe('model licence acceptance', () => {
  it('parses only well-formed model_licence_required errors', () => {
    expect(
      modelLicenceRequirements({ detail: { code: 'model_licence_required', models: [gated] } }),
    ).toEqual([gated]);
    expect(modelLicenceRequirements({ detail: { code: 'other', models: [gated] } })).toBeNull();
    expect(
      modelLicenceRequirements({ detail: { code: 'model_licence_required', models: [{}] } }),
    ).toBeNull();
    expect(modelLicenceRequirements('nope')).toBeNull();
  });

  it('states VoiceStudio is not the licensor and needs explicit confirmation', async () => {
    await render(<ModelLicenceAcceptanceForm models={[gated]} />);
    expect(text()).toContain(en.modelLicense.acceptNotice);
    expect(text()).toContain('CC-BY-NC-4.0');
    expect(button(en.modelLicense.accept)!.disabled).toBe(true);
  });

  it('accepts the exact fingerprint shown', async () => {
    const onAccepted = vi.fn();
    mock.api.mockResolvedValue({ accepted: true });
    await render(<ModelLicenceAcceptanceForm models={[gated]} onAccepted={onAccepted} />);
    await confirmAndAccept();
    expect(mock.api).toHaveBeenCalledWith('/models/licenses/accept', {
      method: 'POST',
      body: JSON.stringify({
        repo_id: gated.repo_id,
        fingerprint: gated.fingerprint,
        accepted: true,
      }),
    });
    expect(onAccepted).toHaveBeenCalled();
  });

  it('asks to review again when the terms changed', async () => {
    const onAccepted = vi.fn();
    mock.api.mockRejectedValue(new ApiError(409, 'x', { detail: { code: 'terms_changed' } }));
    await render(<ModelLicenceAcceptanceForm models={[gated]} onAccepted={onAccepted} />);
    await confirmAndAccept();
    expect(text()).toContain(en.modelLicense.acceptChanged);
    expect(onAccepted).not.toHaveBeenCalled();
  });

  it('can withdraw an acceptance', async () => {
    mock.api.mockResolvedValue({ accepted: false });
    await render(<ModelLicenceAccepted repoId={gated.repo_id} />);
    await act(async () => button(en.modelLicense.revoke)!.click());
    expect(mock.api).toHaveBeenCalledWith('/models/licenses/revoke', {
      method: 'POST',
      body: JSON.stringify({ repo_id: gated.repo_id }),
    });
  });

  it('opens the app-level dialog when any request reports an unaccepted licence', async () => {
    await render(<ModelLicenceGate />);
    expect(text()).not.toContain(en.modelLicense.requiredTitle);
    await act(async () => {
      window.dispatchEvent(new CustomEvent(MODEL_LICENCE_REQUIRED_EVENT, { detail: [gated] }));
    });
    expect(text()).toContain(en.modelLicense.requiredTitle);
    expect(text()).toContain(gated.repo_id);
  });
});
