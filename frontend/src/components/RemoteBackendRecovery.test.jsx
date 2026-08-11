import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import RemoteBackendRecovery from './RemoteBackendRecovery';

describe('RemoteBackendRecovery', () => {
  it('explains the classified failure and supports retry', () => {
    const onRetry = vi.fn();
    const onOpenSettings = vi.fn();
    render(
      <RemoteBackendRecovery
        failure={{
          ok: false,
          kind: 'wrong_port',
          target: 'https://gpu-box:7443',
        }}
        onRetry={onRetry}
        onOpenSettings={onOpenSettings}
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('7443');
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(onRetry).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
    expect(onOpenSettings).toHaveBeenCalledOnce();
  });

  it('clears the remote URL and API key before reloading locally', () => {
    localStorage.setItem('ov_backend_url', 'https://gpu-box:3900');
    localStorage.setItem('ov_api_key', 'secret');
    const reload = vi.fn();
    render(
      <RemoteBackendRecovery
        failure={{ ok: false, kind: 'tls', target: 'https://gpu-box:3900' }}
        onRetry={vi.fn()}
        onOpenSettings={vi.fn()}
        reload={reload}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Use local backend' }));
    expect(localStorage.getItem('ov_backend_url')).toBeNull();
    expect(localStorage.getItem('ov_api_key')).toBeNull();
    expect(reload).toHaveBeenCalledOnce();
  });
});
