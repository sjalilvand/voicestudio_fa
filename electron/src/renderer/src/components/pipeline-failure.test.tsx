import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { publicFailureFromEvent } from '@/lib/api/failure';
import { PipelineFailure } from './pipeline-failure';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

afterEach(cleanup);

it("preserves and opens the backend's exact contextual documentation URL", () => {
  const docsUrl =
    'https://github.com/debpalash/VoiceStudio/blob/main/docs/features/diarization.md#troubleshooting';
  const failure = publicFailureFromEvent(
    {
      reason: 'The installed diarisation runtime failed to load',
      docs_topic: 'DIARIZATION_LOAD_FAILED',
      docs_url: docsUrl,
    },
    'Fallback',
  );

  render(<PipelineFailure failure={failure} fallback="Fallback" />);

  expect(screen.getByRole('link', { name: /dub.open_docs/ })).toHaveAttribute('href', docsUrl);
});

it('rejects a non-web documentation URL and uses the shared safe fallback', () => {
  render(
    <PipelineFailure
      failure={{ reason: 'Failure', docsUrl: 'javascript:alert(1)' }}
      fallback="Fallback"
    />,
  );

  expect(screen.getByRole('link', { name: /dub.open_docs/ })).toHaveAttribute(
    'href',
    'https://github.com/debpalash/VoiceStudio/blob/main/docs/install/troubleshooting.md',
  );
});
