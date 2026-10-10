import { useEffect, useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { ExternalLink } from '@/components/external-link';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { apiJson } from '@/lib/api/client';
import { ModelLicenseIcon } from './model-license-icon';
import {
  canAcknowledgeModelPlan,
  modelLicenseCategory,
  modelLicenseCategoryKey,
  modelLicenseStatusKey,
  modelLicenseUrl,
  type ModelLicenseInfo,
  type ModelReviewPlan,
} from './model-license-contract';

const blockerKeys: Record<string, string> = {
  component_closure_incomplete: 'modelLicense.blockerComponents',
  artifact_manifest_unverified: 'modelLicense.blockerArtifacts',
  terms_unverified: 'modelLicense.blockerTerms',
  runtime_revision_unverified: 'modelLicense.blockerRuntime',
  evidence_revision_mismatch: 'modelLicense.blockerMismatch',
  upstream_access_unverified: 'modelLicense.blockerAccess',
  variant_provenance_unverified: 'modelLicense.blockerVariant',
  remote_review_unsupported: 'modelLicense.blockerRemote',
};

export function ModelLicense({
  repoId,
  label,
  info,
  target,
}: {
  repoId: string;
  label: string;
  info?: ModelLicenseInfo;
  target: string;
}) {
  const { t } = useTranslation();
  const acknowledgementId = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const generation = useRef(0);
  const busyRef = useRef<'prepare' | 'commit' | null>(null);
  const request = useRef<AbortController | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<'prepare' | 'commit' | null>(null);
  const [plan, setPlan] = useState<ModelReviewPlan | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [failed, setFailed] = useState(false);
  const [completed, setCompleted] = useState(false);
  const ready = canAcknowledgeModelPlan(plan, repoId, target, info?.registry_digest);

  // A refreshed registry/selection invalidates the preview and acknowledgement.
  // Closing during preparation also makes its eventual response unusable.
  useEffect(() => {
    generation.current += 1;
    request.current?.abort();
    busyRef.current = null;
    setBusy(null);
    setPlan(null);
    setAcknowledged(false);
    setFailed(false);
    setCompleted(false);
    return () => {
      generation.current += 1;
      request.current?.abort();
    };
  }, [repoId, target, info?.registry_digest]);

  const close = () => {
    if (busyRef.current === 'commit') return;
    generation.current += 1;
    request.current?.abort();
    busyRef.current = null;
    setBusy(null);
    setPlan(null);
    setAcknowledged(false);
    setFailed(false);
    setOpen(false);
    setCompleted(false);
  };

  const prepare = async () => {
    if (busyRef.current) return;
    const current = ++generation.current;
    busyRef.current = 'prepare';
    setBusy('prepare');
    setFailed(false);
    setAcknowledged(false);
    setPlan(null);
    request.current = new AbortController();
    try {
      const result = await apiJson<ModelReviewPlan>('/models/install/prepare', {
        method: 'POST',
        signal: request.current.signal,
        body: JSON.stringify({ repo_id: repoId, target }),
      });
      if (generation.current === current) setPlan(result);
    } catch {
      if (generation.current === current) setFailed(true);
    } finally {
      if (generation.current === current) {
        busyRef.current = null;
        setBusy(null);
      }
    }
  };

  const commit = async () => {
    if (busyRef.current || !ready || !acknowledged || !plan) return;
    const current = generation.current;
    busyRef.current = 'commit';
    setBusy('commit');
    setFailed(false);
    try {
      const result = await apiJson<{ status: string }>('/models/install/commit', {
        method: 'POST',
        body: JSON.stringify({
          plan_id: plan.plan_id,
          plan_digest: plan.plan_digest,
          acknowledged_document_ids: plan.documents.map((document) => document.id),
          acknowledged: true,
          target,
        }),
      });
      if (result.status !== 'verified') throw new Error('Unexpected reviewed-cache result');
      if (generation.current === current) {
        setPlan(null);
        setAcknowledged(false);
        setCompleted(true);
      }
    } catch {
      if (generation.current === current) {
        // A changed/expired plan must be prepared and acknowledged again.
        setFailed(true);
        setPlan(null);
        setAcknowledged(false);
      }
    } finally {
      if (generation.current === current) {
        busyRef.current = null;
        setBusy(null);
      }
    }
  };

  const sourceLink = (url: string | null | undefined, text: string) => {
    const href = modelLicenseUrl(url);
    return href ? <ExternalLink href={href}>{text}</ExternalLink> : null;
  };
  const category = t(modelLicenseCategoryKey(info?.license_category));
  const review = t(
    info?.review_status === 'cleared' ? 'modelLicense.reviewed' : 'modelLicense.notReviewed',
  );
  const summary = `${info?.license || t('common.unknown')} · ${category} · ${review}`;
  const blockers = [...new Set([...(info?.blockers ?? []), ...(plan?.blockers ?? [])])];

  return (
    <>
      <Button
        ref={trigger}
        size="sm"
        variant="outline"
        className="gap-1.5"
        onClick={() => setOpen(true)}
        title={summary}
        aria-label={`${t('modelLicense.label')}: ${summary}; ${label}`}
      >
        <span aria-hidden="true">{t('modelLicense.label')}:</span>
        <ModelLicenseIcon category={modelLicenseCategory(info?.license_category)} />
      </Button>
      <Dialog open={open} onOpenChange={(next) => (next ? setOpen(true) : close())}>
        <DialogContent
          showCloseButton={false}
          finalFocus={trigger}
          className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-2xl"
        >
          <DialogHeader>
            <DialogTitle>
              {t('modelLicense.title')} · {label}
            </DialogTitle>
            <DialogDescription>{t('modelLicense.disclaimer')}</DialogDescription>
          </DialogHeader>
          <p className="text-xs text-muted-foreground">{t('modelLicense.preview')}</p>
          <p className="text-xs [overflow-wrap:anywhere]">
            {repoId} · {t('common.backend')}: {target}
          </p>
          <dl className="grid min-w-0 gap-2 text-sm [overflow-wrap:anywhere]">
            <div>
              <dt className="font-medium">{t('modelLicense.category')}</dt>
              <dd className="flex items-center gap-1.5">
                <ModelLicenseIcon category={modelLicenseCategory(info?.license_category)} />
                {category} · {review}
              </dd>
              <dd className="text-xs text-muted-foreground">{t('modelLicense.categoryHint')}</dd>
            </div>
            <div>
              <dt className="font-medium">{t('modelLicense.commercial')}</dt>
              <dd>{t(modelLicenseStatusKey(info?.commercial_inference))}</dd>
            </div>
            <div>
              <dt className="font-medium">{t('modelLicense.outputs')}</dt>
              <dd>{t(modelLicenseStatusKey(info?.commercial_outputs))}</dd>
            </div>
            <div>
              <dt className="font-medium">{t('modelLicense.redistribution')}</dt>
              <dd>{t('modelLicense.unknown')}</dd>
            </div>
            <div>
              <dt className="font-medium">{t('modelLicense.voice')}</dt>
              <dd>{t('modelLicense.unknown')}</dd>
            </div>
            <div>
              <dt className="font-medium">{t('modelLicense.vendor')}</dt>
              <dd>{info?.credit || t('common.unknown')}</dd>
            </div>
            <div>
              <dt className="font-medium">{t('modelLicense.terms')}</dt>
              <dd>{info?.license || t('common.unknown')}</dd>
            </div>
            <div>
              <dt className="font-medium">{t('modelLicense.runtime')}</dt>
              <dd>{info?.runtime_revision || t('common.unknown')}</dd>
            </div>
            <div>
              <dt className="font-medium">{t('modelLicense.evidenceRevision')}</dt>
              <dd>{info?.evidence_revision || t('common.unknown')}</dd>
            </div>
            <div>
              <dt className="font-medium">{t('modelLicense.checked')}</dt>
              <dd>{info?.evidence_checked_at || t('common.unknown')}</dd>
            </div>
          </dl>
          <div className="flex flex-wrap gap-2">
            {sourceLink(info?.evidence_url, t('modelLicense.evidence'))}
            {sourceLink(info?.source_url, t('modelLicense.source'))}
          </div>
          <p className="text-xs text-muted-foreground">{t('modelLicense.external')}</p>
          {info?.notes && (
            <section className="rounded-lg border border-border/60 p-3 text-sm [overflow-wrap:anywhere]">
              <h3 className="font-medium">{t('modelLicense.notes')}</h3>
              <p>{info.notes}</p>
            </section>
          )}
          {info?.variants?.map((variant) => (
            <section
              key={variant.id}
              className="rounded-lg border border-border/60 p-3 text-sm [overflow-wrap:anywhere]"
            >
              <h3 className="font-medium">{variant.label}</h3>
              <p className="flex items-center gap-1.5">
                <ModelLicenseIcon category={modelLicenseCategory(variant.license_category)} />
                {t(modelLicenseCategoryKey(variant.license_category))}
              </p>
              <p>
                {t('modelLicense.commercial')}:{' '}
                {t(modelLicenseStatusKey(variant.commercial_inference))}
              </p>
              <p>
                {t('modelLicense.outputs')}: {t(modelLicenseStatusKey(variant.commercial_outputs))}
              </p>
              <p className="text-xs text-muted-foreground">{t('modelLicense.notes')}</p>
              {variant.observations?.output_terms && <p>{variant.observations.output_terms}</p>}
              {variant.observations?.license_status && <p>{variant.observations.license_status}</p>}
              {variant.blockers.map((blocker) => (
                <p key={blocker}>{t(blockerKeys[blocker] ?? 'modelLicense.unknown')}</p>
              ))}
              {sourceLink(variant.evidence_url, t('modelLicense.evidence'))}
            </section>
          ))}
          {blockers.length > 0 && (
            <section className="rounded-lg border border-warning/30 bg-warning/5 p-3 text-sm">
              <h3 className="font-medium">{t('modelLicense.unresolved')}</h3>
              <ul className="list-disc space-y-1 ps-5">
                {blockers.map((blocker) => (
                  <li key={blocker}>{t(blockerKeys[blocker] ?? 'modelLicense.unknown')}</li>
                ))}
              </ul>
            </section>
          )}
          {plan && (
            <section className="space-y-3 text-sm [overflow-wrap:anywhere]">
              <p>
                {t('modelLicense.downloadSource')}: {plan.source}
              </p>
              <h3 className="font-medium">{t('modelLicense.components')}</h3>
              {plan.components.map((component) => (
                <details key={component.id} className="rounded-lg border border-border/60 p-3">
                  <summary className="cursor-pointer rounded focus-visible:ring-2 focus-visible:ring-ring">
                    {component.id}
                  </summary>
                  <p>
                    {component.credit} · {component.license}
                  </p>
                  <p>{component.revision || t('common.unknown')}</p>
                  <ul className="space-y-1">
                    {component.artifacts.map((artifact) => (
                      <li key={artifact.path}>
                        {artifact.path} · SHA-256: {artifact.sha256}
                      </li>
                    ))}
                  </ul>
                </details>
              ))}
              <h3 className="font-medium">{t('modelLicense.documents')}</h3>
              {plan.documents.map((document) => (
                <details key={document.id} className="rounded-lg border border-border/60 p-3">
                  <summary className="cursor-pointer rounded focus-visible:ring-2 focus-visible:ring-ring">
                    {document.title}
                  </summary>
                  <p className="text-xs">SHA-256: {document.sha256}</p>
                  <pre className="my-2 whitespace-pre-wrap break-words font-sans text-xs">
                    {document.text}
                  </pre>
                  {sourceLink(document.source_url, t('modelLicense.evidence'))}
                </details>
              ))}
              <p role="status">{t(ready ? 'modelLicense.ready' : 'modelLicense.blocked')}</p>
              {ready && (
                <>
                  <p>{plan.acknowledgement.text}</p>
                  <p className="text-xs text-muted-foreground">
                    {plan.acknowledgement.prompt_id} · {plan.acknowledgement.prompt_version} ·{' '}
                    {plan.plan_digest}
                  </p>
                  <label
                    htmlFor={acknowledgementId}
                    className="flex items-start gap-2 rounded-lg border border-border p-3"
                  >
                    <input
                      id={acknowledgementId}
                      type="checkbox"
                      checked={acknowledged}
                      disabled={busy === 'commit'}
                      onChange={(event) => setAcknowledged(event.currentTarget.checked)}
                      className="mt-0.5 size-4 shrink-0 accent-primary focus-visible:ring-2 focus-visible:ring-ring"
                    />
                    <span>{t('modelLicense.acknowledge')}</span>
                  </label>
                </>
              )}
            </section>
          )}
          {info && (
            <p className="text-xs text-muted-foreground [overflow-wrap:anywhere]">
              {t('modelLicense.registry')}: {info.registry_version} · {info.registry_digest}
            </p>
          )}
          {failed && (
            <p role="alert" className="text-sm text-destructive">
              {t('modelLicense.failed')}
            </p>
          )}
          {completed && (
            <p role="status" className="text-sm">
              {t('modelLicense.downloaded')}
            </p>
          )}
          {busy && (
            <p role="status" className="text-sm">
              {t('common.loading')}
            </p>
          )}
          <DialogFooter>
            <Button variant="ghost" disabled={busy === 'commit'} onClick={close}>
              {t('common.close')}
            </Button>
            {completed ? null : ready ? (
              <Button
                className="h-auto min-h-8"
                disabled={Boolean(busy) || !acknowledged}
                onClick={() => void commit()}
              >
                <span className="whitespace-normal">{t('modelLicense.commit')}</span>
              </Button>
            ) : (
              <Button
                variant="outline"
                className="h-auto min-h-8"
                disabled={Boolean(busy) || target !== 'local' || !info}
                onClick={() => void prepare()}
              >
                <span className="whitespace-normal">{t('modelLicense.prepare')}</span>
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
