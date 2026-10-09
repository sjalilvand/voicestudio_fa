import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import en from '@/i18n/locales/en.json';
import type { ModelLicenseInfo, ModelReviewPlan } from './model-license-contract';
import {
  canAcknowledgeModelPlan,
  modelLicenseStatusKey,
  modelLicenseUrl,
} from './model-license-contract';

const mock = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock('@/lib/api/client', () => ({ apiJson: mock.api }));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key.split('.').reduce((value: any, part) => value?.[part], en) ?? key,
  }),
}));
vi.mock('@/components/external-link', () => ({
  ExternalLink: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));
import { ModelLicense } from './model-license';

// Deliberately invented identities and document bytes for UI tests only.
const info: ModelLicenseInfo = {
  registry_version: 'synthetic-test',
  registry_digest: 'b'.repeat(64),
  license: 'LicenseRef-SyntheticTest',
  credit: 'Synthetic test source',
  source_url: 'https://example.invalid/model',
  evidence_url: 'https://example.invalid/pinned',
  evidence_revision: 'a'.repeat(40),
  runtime_revision: 'a'.repeat(40),
  review_status: 'unreviewed',
  commercial_inference: 'unknown',
  commercial_outputs: 'unknown',
  component_closure: 'incomplete',
  readiness: 'not_verified',
  blockers: [],
  enforcement: 'disclosure_only',
};
function syntheticPlan(): ModelReviewPlan {
  return {
    plan_id: 'synthetic-test',
    plan_digest: 'c'.repeat(64),
    registry_digest: info.registry_digest,
    repo_id: 'test/model',
    target: 'local',
    source: 'https://example.invalid',
    readiness: 'ready',
    blockers: [],
    enforcement: 'reviewed_install_only',
    components: [
      {
        id: 'test/model',
        revision: 'a'.repeat(40),
        license: info.license,
        credit: info.credit,
        component_closure: 'complete',
        artifacts: [
          { path: 'test.bin', sha256: 'd'.repeat(64), size_bytes: 1, document_ids: ['test-terms'] },
        ],
      },
    ],
    documents: [
      {
        id: 'test-terms',
        title: 'Synthetic terms',
        text: 'Synthetic test document. Not a real grant.',
        source_url: 'https://example.invalid/terms',
        sha256: 'e'.repeat(64),
        redistribution: 'permitted',
        agreement_required: false,
      },
    ],
    acknowledgement: {
      prompt_id: 'synthetic-notice',
      prompt_version: 1,
      text: 'Synthetic notice only.',
    },
  };
}
let host: HTMLDivElement;
let root: Root;
const text = () => document.body.textContent ?? '';
const button = (name: string) =>
  Array.from(document.querySelectorAll('button')).find((item) => item.textContent === name)!;
async function click(element: HTMLElement) {
  await act(async () => element.click());
}
async function render(licenseInfo = info, target = 'local') {
  await act(async () =>
    root.render(
      <ModelLicense repoId="test/model" label="Test model" info={licenseInfo} target={target} />,
    ),
  );
}
async function open() {
  await click(document.querySelector('button')!);
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

describe('versioned model notices', () => {
  it.each([
    ['restricted', en.modelLicense.restricted],
    ['separate_permission_required', en.modelLicense.permission],
    ['unknown', en.modelLicense.unknown],
    ['permitted', en.modelLicense.unknown],
  ])(
    'includes the visible localized status and model in the %s trigger name',
    async (status, statusLabel) => {
      await render({ ...info, commercial_inference: status });
      const visibleLabel = `${en.modelLicense.title}: ${statusLabel}`;
      const trigger = within(host).getByRole('button', { name: `${visibleLabel}; Test model` });
      expect(trigger.textContent).toBe(visibleLabel);
      expect(trigger.querySelector('svg')?.getAttribute('aria-hidden')).toBe('true');
      expect(trigger.querySelector('svg')?.getAttribute('focusable')).toBe('false');
    },
  );

  it('shows separate unknown scopes and pinned evidence without downloading on open', async () => {
    await render();
    await open();
    expect(text()).toContain(en.modelLicense.commercial);
    expect(text()).toContain(en.modelLicense.outputs);
    expect(text()).toContain(en.modelLicense.voice);
    expect(text()).toContain(en.modelLicense.redistribution);
    expect(document.querySelector('a[href="https://example.invalid/pinned"]')).not.toBeNull();
    expect(mock.api).not.toHaveBeenCalled();
    await click(button(en.common.close));
    await vi.waitFor(() => expect(document.querySelector('[role="dialog"]')).toBeNull());
    expect(document.activeElement).toBe(document.querySelector('button'));
  });

  it('never offers acknowledgement for a real-style incomplete plan', async () => {
    mock.api.mockResolvedValue({
      ...syntheticPlan(),
      readiness: 'blocked',
      blockers: ['terms_unverified'],
      documents: [],
    });
    await render();
    await open();
    await click(button(en.modelLicense.prepare));
    expect(text()).toContain(en.modelLicense.blocked);
    expect(text()).toContain(en.modelLicense.blockerTerms);
    expect(document.querySelector('input[type="checkbox"]')).toBeNull();
    expect(button(en.modelLicense.commit)).toBeUndefined();
    expect(mock.api.mock.calls.map(([path]) => path)).toEqual(['/models/install/prepare']);
  });

  it('ignores preparation completing after Close and reopen', async () => {
    let resolve!: (plan: ModelReviewPlan) => void;
    mock.api.mockReturnValue(
      new Promise((done) => {
        resolve = done;
      }),
    );
    await render();
    await open();
    await click(button(en.modelLicense.prepare));
    await click(button(en.common.close));
    await open();
    await act(async () => resolve(syntheticPlan()));
    expect(document.querySelector('input[type="checkbox"]')).toBeNull();
    expect(text()).not.toContain('Synthetic notice only.');
  });

  it('clears a prepared plan when registry or selected target changes', async () => {
    mock.api.mockResolvedValue(syntheticPlan());
    await render();
    await open();
    await click(button(en.modelLicense.prepare));
    await click(document.querySelector('input')!);
    await render({ ...info, registry_digest: 'f'.repeat(64) });
    expect(document.querySelector('input[type="checkbox"]')).toBeNull();
    await render(info, 'worker:test');
    expect(button(en.modelLicense.prepare).disabled).toBe(true);
    expect(text()).toContain('worker:test');
  });

  it('requires an explicit checkbox and commits the exact document set once', async () => {
    mock.api.mockResolvedValueOnce(syntheticPlan());
    let resolve!: (value: { status: string }) => void;
    mock.api.mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    );
    await render();
    await open();
    await click(button(en.modelLicense.prepare));
    const commit = button(en.modelLicense.commit);
    expect(commit.disabled).toBe(true);
    await click(document.querySelector('input')!);
    await act(async () => {
      commit.click();
      commit.click();
    });
    expect(mock.api).toHaveBeenCalledTimes(2);
    expect(mock.api.mock.calls[1][0]).toBe('/models/install/commit');
    expect(JSON.parse(mock.api.mock.calls[1][1].body)).toEqual({
      plan_id: 'synthetic-test',
      plan_digest: 'c'.repeat(64),
      acknowledged_document_ids: ['test-terms'],
      acknowledged: true,
      target: 'local',
    });
    expect(button(en.common.close).disabled).toBe(true);
    await act(async () => resolve({ status: 'verified' }));
    expect(text()).toContain(en.modelLicense.downloaded);
    expect(document.querySelector('input[type="checkbox"]')).toBeNull();
    expect(
      mock.api.mock.calls.some(
        ([path]) => path === '/api/settings/license' || path === '/models/install',
      ),
    ).toBe(false);
  });

  it('requires a new plan and acknowledgement after a failed commit', async () => {
    mock.api
      .mockResolvedValueOnce(syntheticPlan())
      .mockRejectedValueOnce(new Error('plan_changed'));
    await render();
    await open();
    await click(button(en.modelLicense.prepare));
    await click(document.querySelector('input')!);
    await click(button(en.modelLicense.commit));
    expect(text()).toContain(en.modelLicense.failed);
    expect(document.querySelector('input[type="checkbox"]')).toBeNull();
    expect(button(en.modelLicense.prepare).disabled).toBe(false);
  });

  it('renders original documents as inert text and rejects unsafe source links', async () => {
    const plan = syntheticPlan();
    plan.documents[0].text = '<img src=x onerror=alert(1)>';
    plan.documents[0].source_url = 'javascript:alert(1)';
    mock.api.mockResolvedValue(plan);
    await render({ ...info, source_url: 'file:///private', evidence_url: 'data:text/html,unsafe' });
    await open();
    await click(button(en.modelLicense.prepare));
    expect(text()).toContain('<img src=x onerror=alert(1)>');
    expect(document.querySelector('img')).toBeNull();
    expect(document.querySelector('a')).toBeNull();
  });
});

describe('conservative model notice contract', () => {
  it('never derives commercial permission from an unknown status or engine licence', () => {
    for (const status of [
      undefined,
      'unknown',
      'yes',
      'MIT',
      'publisher_permissive',
      'conflicting',
    ]) {
      expect(modelLicenseStatusKey(status)).toBe('modelLicense.unknown');
    }
    expect(modelLicenseStatusKey('restricted')).toBe('modelLicense.restricted');
  });
  it('rejects changed identities, upstream-assent documents and absent evidence', () => {
    const plan = syntheticPlan();
    expect(canAcknowledgeModelPlan(plan, 'test/model', 'local', info.registry_digest)).toBe(true);
    for (const changed of [
      { ...plan, repo_id: 'different/model' },
      { ...plan, registry_digest: 'changed' },
      { ...plan, documents: [] },
      { ...plan, blockers: ['terms_unverified'] },
      { ...plan, documents: [{ ...plan.documents[0], agreement_required: true }] },
    ])
      expect(canAcknowledgeModelPlan(changed, 'test/model', 'local', info.registry_digest)).toBe(
        false,
      );
    expect(canAcknowledgeModelPlan(plan, 'test/model', 'worker:test', info.registry_digest)).toBe(
      false,
    );
  });
  it('allows only HTTPS source URLs without embedded credentials', () => {
    for (const value of [
      'javascript:alert(1)',
      'data:text/html,hi',
      'file:///tmp/a',
      'https://user:secret@example.org',
      'invalid',
    ]) {
      expect(modelLicenseUrl(value)).toBeNull();
    }
    expect(modelLicenseUrl('https://example.org/terms')).toBe('https://example.org/terms');
  });
});
