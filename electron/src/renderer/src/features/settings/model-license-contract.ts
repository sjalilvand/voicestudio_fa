/** Additive legal projection of the existing /models catalogue. */
export interface ModelLicenseVariant {
  id: string;
  label: string;
  commercial_inference: string;
  commercial_outputs: string;
  review_status: string;
  license_category?: string;
  blockers: string[];
  evidence_url?: string | null;
  observations?: { output_terms?: string; license_status?: string };
}

export interface ModelLicenseInfo {
  registry_version: string;
  registry_digest: string;
  license: string;
  credit: string;
  notes?: string;
  source_url?: string | null;
  evidence_url?: string | null;
  evidence_revision?: string | null;
  evidence_checked_at?: string | null;
  runtime_revision?: string | null;
  review_status: string;
  commercial_inference: string;
  commercial_outputs: string;
  component_closure: string;
  readiness: string;
  license_category?: string;
  blockers: string[];
  enforcement: 'disclosure_only';
  variants?: ModelLicenseVariant[];
}

export interface ModelReviewDocument {
  id: string;
  title: string;
  source_url: string;
  sha256: string;
  text: string;
  redistribution: 'permitted';
  agreement_required: boolean;
}

export interface ModelReviewPlan {
  plan_id: string;
  plan_digest: string;
  registry_digest: string;
  repo_id: string;
  target: string;
  source: string;
  components: {
    id: string;
    revision: string | null;
    license: string;
    credit: string;
    evidence_url?: string | null;
    component_closure: string;
    artifacts: { path: string; sha256: string; size_bytes: number; document_ids: string[] }[];
  }[];
  documents: ModelReviewDocument[];
  blockers: string[];
  readiness: 'blocked' | 'ready';
  acknowledgement: { prompt_id: string; prompt_version: number; text: string };
  enforcement: 'reviewed_install_only';
}

export type ModelLicenseStatus = 'restricted' | 'permission' | 'unknown';

/** Unknown/future statuses collapse to `unknown`, never to a permissive state. */
export function modelLicenseStatus(value?: string): ModelLicenseStatus {
  if (value === 'restricted' || value?.startsWith('noncommercial')) return 'restricted';
  if (value === 'separate_permission_required') return 'permission';
  return 'unknown';
}

export function modelLicenseStatusKey(value?: string): string {
  return `modelLicense.${modelLicenseStatus(value)}`;
}

/** What the declared licence says; never what VoiceStudio has verified. */
export type ModelLicenseCategory = 'commercial' | 'conditions' | 'noncommercial' | 'unknown';

const categories: readonly string[] = ['commercial', 'conditions', 'noncommercial'];

/** Missing, older-backend or future categories collapse to `unknown`. */
export function modelLicenseCategory(value?: string): ModelLicenseCategory {
  return value && categories.includes(value) ? (value as ModelLicenseCategory) : 'unknown';
}

export function modelLicenseCategoryKey(value?: string): string {
  const category = modelLicenseCategory(value);
  return `modelLicense.category${category[0].toUpperCase()}${category.slice(1)}`;
}

/** Upstream data is inert text; external navigation accepts HTTPS only. */
export function modelLicenseUrl(value?: string | null): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && !url.username && !url.password ? url.href : null;
  } catch {
    return null;
  }
}

export function canAcknowledgeModelPlan(
  plan: ModelReviewPlan | null,
  repoId: string,
  target: string,
  registryDigest?: string,
): boolean {
  return Boolean(
    plan &&
    plan.enforcement === 'reviewed_install_only' &&
    plan.readiness === 'ready' &&
    plan.blockers.length === 0 &&
    plan.repo_id === repoId &&
    plan.target === target &&
    target === 'local' &&
    registryDigest &&
    plan.registry_digest === registryDigest &&
    plan.plan_id &&
    plan.plan_digest &&
    plan.components.length > 0 &&
    plan.documents.length > 0 &&
    plan.documents.every(
      (document) => !document.agreement_required && document.text && document.sha256,
    ),
  );
}
