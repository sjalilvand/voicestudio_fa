// CLEAN-ROOM (spec W11-residue §T26): test imports, hoisted apiJson mock, i18n and api-client mocks
import { DictationCleanupSettings } from './dictation-cleanup-settings';
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
it('turns spoken punctuation on without needing an LLM', async () => {
  mock.apiJson.mockImplementation(async (_path: string, init?: { method?: string }) =>
    init?.method === 'PUT'
      ? { auto: true, llm_ready: false, spoken_punctuation: true }
      : { auto: true, llm_ready: false, spoken_punctuation: false },
  );
  render(
    <QueryClientProvider client={new QueryClient()}>
      <DictationCleanupSettings />
    </QueryClientProvider>,
  );
  const toggle = await screen.findByRole('switch', {
    name: 'dictation.spoken_punctuation',
  });
  expect(toggle).not.toBeChecked();
  expect(toggle).toBeEnabled();
  expect(screen.getByText('dictation.spoken_punctuation_desc')).toBeInTheDocument();
  fireEvent.click(toggle);
  await waitFor(() => expect(toggle).toBeChecked());
  const put = mock.apiJson.mock.calls.find(([, init]) => init?.method === 'PUT');
  expect(put?.[0]).toBe('/api/settings/dictation-refinement');
  expect(JSON.parse(put?.[1].body)).toEqual({ spoken_punctuation: true });
});
it('offers Retry when the settings cannot be loaded', async () => {
  mock.apiJson.mockRejectedValueOnce(new Error('offline'));
  mock.apiJson.mockResolvedValue({ spoken_punctuation: false });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <DictationCleanupSettings />
    </QueryClientProvider>,
  );
  fireEvent.click(await screen.findByRole('button', { name: 'backend.retry' }));
  expect(await screen.findByRole('switch', { name: 'dictation.spoken_punctuation' })).toBeEnabled();
});
