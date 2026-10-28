import { act, cleanup, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
// CLEAN-ROOM (spec W11-residue §T2): hoisted shortcut-listener mock state and module mocks (i18n, dictation demo, native dictation hooks)
import { ShortcutSettings } from './shortcut-settings';
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});
it('verifies only the current registered shortcut and removes its listener on departure', async () => {
  Object.defineProperty(window, 'voicestudio', {
    configurable: true,
    value: {
      capture: {
        getShortcut: () => Promise.resolve({ accelerator: 'Ctrl+Shift+Space', active: true }),
        onShortcutPressed: (listener: (key: string) => void) => {
          mock.listener = listener;
          return mock.unsubscribe;
        },
      },
    },
  });
  const client = new QueryClient();
  const view = render(
    <QueryClientProvider client={client}>
      <ShortcutSettings />
    </QueryClientProvider>,
  );
  await screen.findByText('demo.dictation_status_pending');
  act(() => mock.listener?.('Ctrl+Alt+Space'));
  expect(screen.queryByText('demo.dictation_status_ok')).not.toBeInTheDocument();
  act(() => mock.listener?.('Ctrl+Shift+Space'));
  await screen.findByText('demo.dictation_status_ok');
  act(() =>
    client.setQueryData(['native-shortcut'], { accelerator: 'Ctrl+Alt+Space', active: true }),
  );
  await screen.findByText('demo.dictation_status_pending');
  act(() =>
    client.setQueryData(['native-shortcut'], { accelerator: 'Ctrl+Shift+Space', active: false }),
  );
  await screen.findByText('demo.dictation_status_warn');
  view.unmount();
  expect(mock.unsubscribe).toHaveBeenCalledTimes(1);
  Reflect.deleteProperty(window, 'voicestudio');
});
