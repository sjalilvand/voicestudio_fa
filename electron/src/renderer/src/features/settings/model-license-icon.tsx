import type { ModelLicenseStatus } from './model-license-contract';

/**
 * Status glyphs for model terms. Every glyph is a document outline so none can
 * read as an approval; there is deliberately no check-mark or "open" state.
 * Meaning is always carried by adjacent text, so the SVG is decorative.
 */
const marks: Record<ModelLicenseStatus, React.ReactNode> = {
  // Coin struck through: commercial use is restricted.
  restricted: (
    <>
      <circle cx="12" cy="12" r="5" />
      <path d="M12 9.5v5M10.5 11h2.25a1 1 0 0 1 0 2H10.5" />
      <path d="M8.5 15.5l7-7" />
    </>
  ),
  // Padlock: a separate grant from the rights holder is required.
  permission: (
    <>
      <rect x="9" y="12" width="6" height="4.5" rx="1" />
      <path d="M10.5 12v-1.25a1.5 1.5 0 0 1 3 0V12" />
    </>
  ),
  // Question mark: terms are not verified (not the same as permitted).
  unknown: <path d="M10.25 10.25a1.9 1.9 0 1 1 2.6 1.75c-.5.25-.85.6-.85 1.25M12 15.5v.01" />,
};

export function ModelLicenseIcon({
  status,
  className = 'size-4',
}: {
  status: ModelLicenseStatus;
  className?: string;
}) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      data-license-status={status}
      aria-hidden="true"
      focusable="false"
    >
      <path
        d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"
        strokeDasharray={status === 'unknown' ? '2.5 2' : undefined}
      />
      <path d="M14 3v5h5" />
      {marks[status]}
    </svg>
  );
}
