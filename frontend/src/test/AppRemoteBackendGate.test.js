import { describe, expect, it } from 'vitest';
import appSource from '../App.jsx?raw';

describe('App remote-backend startup gate', () => {
  it('probes a configured remote before the local setup-status path', () => {
    const remoteProbe = appSource.indexOf('const remote = configuredRemoteBackend()');
    const localSetup = appSource.indexOf("import('./api/setup')", remoteProbe);
    expect(remoteProbe).toBeGreaterThan(-1);
    expect(localSetup).toBeGreaterThan(remoteProbe);
    expect(appSource.slice(remoteProbe, localSetup)).toContain('probeRemoteBackend');
    expect(appSource.slice(remoteProbe, localSetup)).toContain('return;');
  });

  it('renders recovery before it can route to the local SetupWizard', () => {
    const recovery = appSource.indexOf('if (remoteFailure)');
    const wizard = appSource.indexOf("if (setupNeeded && bootstrapStage === 'ready')", recovery);
    expect(recovery).toBeGreaterThan(-1);
    expect(wizard).toBeGreaterThan(recovery);
    expect(appSource.slice(recovery, wizard)).toContain('RemoteBackendRecovery');
  });
});
