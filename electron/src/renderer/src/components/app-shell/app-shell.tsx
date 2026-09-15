import { WorkspaceSidebar } from './workspace-sidebar';
import { CommandPalette } from '@/components/command-palette';
import { Outlet, useRouterState } from '@tanstack/react-router';
import { BackendGate } from '../backend-gate';
import { RepairAgentDock } from './repair-agent-dock';
import { isMac } from '../bridge';
import { cn } from '@/lib/utils';

export function AppShell() {
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  });
  const settings = pathname.startsWith('/settings');
  const macWorkspace = isMac() && !settings;
  const SettingsWorkspace = pathname === '/settings/openapi' ? 'div' : 'main';
  return (
    <div
      className={cn(
        'app-surface relative flex h-full flex-col bg-background text-foreground',
        macWorkspace && 'macos-notification-safe-area',
      )}
    >
      <div className="flex min-h-0 flex-1">
        {settings ? (
          <>
            <CommandPalette />
            <SettingsWorkspace
              role={pathname === '/settings/openapi' ? 'main' : undefined}
              className="@container relative flex min-w-0 flex-1 flex-col overflow-hidden"
            >
              <div className="min-h-0 flex-1 overflow-hidden">
                <Outlet />
              </div>
              <RepairAgentDock />
            </SettingsWorkspace>
          </>
        ) : (
          <BackendGate repairDock={<RepairAgentDock />}>
            <CommandPalette />
            <WorkspaceSidebar />
            <main className="@container relative flex min-w-0 flex-1 flex-col overflow-hidden">
              <div className="min-h-0 flex-1 overflow-hidden">
                <Outlet />
              </div>
              <RepairAgentDock />
            </main>
          </BackendGate>
        )}
      </div>
    </div>
  );
}
