import { useEffect, useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { ApiError, apiJson } from '@/lib/api/client';
import { ModelLicenseIcon } from './model-license-icon';
import {
  MODEL_LICENCE_REQUIRED_EVENT,
  modelLicenseCategory,
  modelLicenseCategoryKey,
  type ModelLicenceAcceptance,
  type ModelLicenceRequirement,
} from './model-license-contract';

/**
 * Use-time licence acceptance. VoiceStudio is not the licensor and cannot grant
 * model access, so the user confirms they hold the rights each licence needs.
 * Acceptance is bound to the exact terms fingerprint the backend reported.
 */
export function ModelLicenceAcceptanceForm({
  models,
  onAccepted,
}: {
  models: ModelLicenceRequirement[];
  onAccepted?: () => void;
}) {
  const { t } = useTranslation();
  const client = useQueryClient();
  const confirmId = useId();
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<'failed' | 'changed' | null>(null);
  const key = models.map((m) => `${m.repo_id}@${m.fingerprint}`).join('|');

  useEffect(() => {
    setConfirmed(false);
    setError(null);
  }, [key]);

  const accept = async () => {
    if (!confirmed || busy) return;
    setBusy(true);
    setError(null);
    try {
      for (const model of models) {
        await apiJson<ModelLicenceAcceptance>('/models/licenses/accept', {
          method: 'POST',
          body: JSON.stringify({
            repo_id: model.repo_id,
            fingerprint: model.fingerprint,
            accepted: true,
          }),
        });
      }
      onAccepted?.();
    } catch (err) {
      const changed =
        err instanceof ApiError &&
        err.status === 409 &&
        JSON.stringify(err.payload ?? '').includes('terms_changed');
      setError(changed ? 'changed' : 'failed');
    } finally {
      setBusy(false);
      await client.invalidateQueries({ queryKey: ['model-catalogue'] });
    }
  };

  return (
    <section className="space-y-3 rounded-lg border border-warning/30 bg-warning/5 p-3 text-sm">
      <h3 className="font-medium">{t('modelLicense.acceptTitle')}</h3>
      <p>{t('modelLicense.acceptNotice')}</p>
      <ul className="space-y-1">
        {models.map((model) => (
          <li key={model.repo_id} className="flex items-center gap-1.5 [overflow-wrap:anywhere]">
            <ModelLicenseIcon category={modelLicenseCategory(model.category)} />
            <span>
              {model.repo_id} · {model.license || t('common.unknown')} ·{' '}
              {t(modelLicenseCategoryKey(model.category))}
            </span>
          </li>
        ))}
      </ul>
      <label
        htmlFor={confirmId}
        className="flex items-start gap-2 rounded-lg border border-border p-3"
      >
        <input
          id={confirmId}
          type="checkbox"
          checked={confirmed}
          disabled={busy}
          onChange={(event) => setConfirmed(event.currentTarget.checked)}
          className="mt-0.5 size-4 shrink-0 accent-primary focus-visible:ring-2 focus-visible:ring-ring"
        />
        <span>{t('modelLicense.acceptConfirm')}</span>
      </label>
      {error && (
        <p role="alert" className="text-destructive">
          {t(error === 'changed' ? 'modelLicense.acceptChanged' : 'modelLicense.acceptFailed')}
        </p>
      )}
      <Button size="sm" disabled={!confirmed || busy} onClick={() => void accept()}>
        {t('modelLicense.accept')}
      </Button>
    </section>
  );
}

/** Accepted state with a way to withdraw it; the model is blocked again after. */
export function ModelLicenceAccepted({ repoId }: { repoId: string }) {
  const { t } = useTranslation();
  const client = useQueryClient();
  const [busy, setBusy] = useState(false);
  const revoke = async () => {
    setBusy(true);
    try {
      await apiJson('/models/licenses/revoke', {
        method: 'POST',
        body: JSON.stringify({ repo_id: repoId }),
      });
    } finally {
      setBusy(false);
      await client.invalidateQueries({ queryKey: ['model-catalogue'] });
    }
  };
  return (
    <section className="flex flex-wrap items-center gap-2 rounded-lg border border-border/60 p-3 text-sm">
      <p className="min-w-0 flex-1">{t('modelLicense.acceptedState')}</p>
      <Button size="sm" variant="outline" disabled={busy} onClick={() => void revoke()}>
        {t('modelLicense.revoke')}
      </Button>
    </section>
  );
}

/** App-level dialog for a `model_licence_required` error from any feature. */
export function ModelLicenceGate() {
  const { t } = useTranslation();
  const [models, setModels] = useState<ModelLicenceRequirement[] | null>(null);

  useEffect(() => {
    const onRequired = (event: Event) => {
      const detail = (event as CustomEvent<ModelLicenceRequirement[]>).detail;
      if (Array.isArray(detail) && detail.length) setModels(detail);
    };
    window.addEventListener(MODEL_LICENCE_REQUIRED_EVENT, onRequired);
    return () => window.removeEventListener(MODEL_LICENCE_REQUIRED_EVENT, onRequired);
  }, []);

  return (
    <Dialog open={!!models} onOpenChange={(open) => !open && setModels(null)}>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t('modelLicense.requiredTitle')}</DialogTitle>
          <DialogDescription>{t('modelLicense.requiredError')}</DialogDescription>
        </DialogHeader>
        {models && (
          <ModelLicenceAcceptanceForm models={models} onAccepted={() => setModels(null)} />
        )}
        <DialogFooter>
          <Button variant="ghost" onClick={() => setModels(null)}>
            {t('common.close')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
