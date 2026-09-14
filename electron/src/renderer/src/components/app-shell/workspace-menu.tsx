import { Link, useRouterState } from '@tanstack/react-router';
import {
  AudioLinesIcon,
  FingerprintIcon,
  BookOpenIcon,
  FolderIcon,
  WrenchIcon,
  LayersIcon,
  LibraryIcon,
  FilmIcon,
  WandSparklesIcon,
  MicIcon,
  UsersRoundIcon,
  ChevronRightIcon,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { setWorkspace } from '@/lib/store/workspace';
import { cn } from '@/lib/utils';

type Destination = readonly [
  to:
    | '/clone'
    | '/stories'
    | '/audiobook'
    | '/projects'
    | '/tools'
    | '/batch'
    | '/gallery'
    | '/dub'
    | '/design'
    | '/transcriptions'
    | '/personas',
  label: string,
  icon: typeof AudioLinesIcon,
  activate?: () => void,
];

const openSaved = () => setWorkspace({ libraryOpen: true, libraryTab: 'voices' });

const compactDestinations: Destination[] = [
  ['/clone', 'nav.clone_short', FingerprintIcon, openSaved],
  ['/stories', 'nav.stories', AudioLinesIcon],
  ['/dub', 'dubWorkspace.title', FilmIcon],
  ['/batch', 'nav.batch_dub', LayersIcon],
  ['/personas', 'nav.saved', UsersRoundIcon, openSaved],
  ['/gallery', 'nav.gallery', LibraryIcon],
  ['/transcriptions', 'nav.transcribe', MicIcon],
  ['/design', 'designWorkspace.title', WandSparklesIcon],
  ['/audiobook', 'audiobook.title', BookOpenIcon],
  ['/projects', 'projects.title', FolderIcon],
  ['/tools', 'tools.title', WrenchIcon],
];

const laterDestinations: Destination[] = [
  ['/transcriptions', 'nav.transcribe', MicIcon],
  ['/design', 'designWorkspace.title', WandSparklesIcon],
  ['/audiobook', 'audiobook.title', BookOpenIcon],
  ['/projects', 'projects.title', FolderIcon],
  ['/tools', 'tools.title', WrenchIcon],
];

const itemClass =
  'group relative isolate flex h-8 min-w-0 items-center overflow-hidden rounded-md text-sm text-sidebar-foreground/80 outline-none transition-[color,background-color,box-shadow,backdrop-filter] duration-150 before:pointer-events-none before:absolute before:inset-0 before:-z-10 before:rounded-[inherit] before:bg-gradient-to-r before:from-white/[0.07] before:via-white/[0.025] before:to-transparent before:opacity-0 before:transition-opacity before:duration-150 hover:bg-sidebar-accent/65 hover:text-sidebar-foreground hover:backdrop-blur-xl hover:shadow-[inset_0_1px_0_rgb(255_255_255/9%),0_6px_18px_rgb(0_0_0/10%)] hover:ring-1 hover:ring-inset hover:ring-sidebar-border/60 hover:before:opacity-100 focus-visible:ring-2 focus-visible:ring-ring';
const iconClass =
  'size-4 shrink-0 text-muted-foreground transition-[color,filter] duration-150 group-hover:text-sidebar-foreground group-hover:drop-shadow-[0_1px_3px_rgb(0_0_0/22%)]';

function NavigationLink({
  destination: [to, label, Icon, activate],
  compact = false,
  nested = false,
}: {
  destination: Destination;
  compact?: boolean;
  nested?: boolean;
}) {
  const { t } = useTranslation();
  const link = (
    <Link
      to={to}
      aria-label={compact ? t(label) : undefined}
      onClick={activate}
      className={cn(
        itemClass,
        compact ? 'justify-center px-0' : nested ? 'h-7 gap-2 px-2 text-xs' : 'gap-2.5 px-2.5',
      )}
      activeProps={{
        className:
          'bg-sidebar-accent/80 text-sidebar-foreground shadow-sm ring-1 ring-inset ring-sidebar-border/60',
        'aria-current': 'page',
      }}
    >
      <Icon className={cn(iconClass, nested && 'size-3.5')} aria-hidden="true" />
      {!compact && <span className="truncate">{t(label)}</span>}
    </Link>
  );
  if (!compact) return link;
  return (
    <Tooltip>
      <TooltipTrigger render={link} />
      <TooltipContent side="right">{t(label)}</TooltipContent>
    </Tooltip>
  );
}

function NavigationGroup({
  label,
  icon: Icon,
  to,
  active,
  onActivate,
  children,
}: {
  label: string;
  icon: typeof AudioLinesIcon;
  to: '/dub' | '/personas';
  active: boolean;
  onActivate?: () => void;
  children: Destination[];
}) {
  const { t } = useTranslation();
  return (
    <div className="py-0.5">
      <Link
        to={to}
        onClick={onActivate}
        aria-expanded={active}
        className={cn(
          itemClass,
          'gap-2.5 px-2.5 font-medium',
          active &&
            'bg-sidebar-accent/65 text-sidebar-foreground shadow-sm ring-1 ring-inset ring-sidebar-border/50',
        )}
      >
        <Icon className={iconClass} aria-hidden="true" />
        <span className="truncate">{t(label)}</span>
        <ChevronRightIcon
          className={cn(
            'ml-auto size-3.5 shrink-0 text-muted-foreground/70 transition-[color,transform] duration-200 group-hover:text-sidebar-foreground motion-reduce:transform-none',
            active && 'rotate-90 text-sidebar-foreground',
          )}
          aria-hidden="true"
        />
      </Link>
      <div
        aria-hidden={!active}
        inert={!active}
        className={cn(
          'grid transition-[grid-template-rows,opacity] duration-200 motion-reduce:transition-none',
          active ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0',
        )}
      >
        <div className="overflow-hidden">
          <div className="ml-[1.08rem] mt-0.5 space-y-0.5 border-l border-sidebar-border/60 pl-2">
            {children.map((destination) => (
              <NavigationLink key={destination[0]} destination={destination} nested />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export function WorkspaceNavigation({ compact = false }: { compact?: boolean }) {
  const { t } = useTranslation();
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  });
  return (
    <nav
      data-slot="workspace-navigation"
      aria-label={t('nav.workspaces')}
      className={cn(
        'min-h-0 overflow-y-auto overscroll-contain py-2 [scrollbar-width:none]',
        compact ? 'space-y-0.5 px-1.5' : 'shrink-0 space-y-0.5 px-3',
      )}
    >
      {compact ? (
        compactDestinations.map((destination) => (
          <NavigationLink key={destination[0]} destination={destination} compact />
        ))
      ) : (
        <>
          <NavigationLink destination={['/clone', 'nav.clone_short', FingerprintIcon]} />
          <NavigationLink destination={['/stories', 'nav.stories', AudioLinesIcon]} />
          <NavigationGroup
            label="nav.dub"
            icon={FilmIcon}
            to="/dub"
            active={pathname === '/dub' || pathname === '/batch'}
            children={[
              ['/dub', 'dubWorkspace.title', FilmIcon],
              ['/batch', 'nav.batch_dub', LayersIcon],
            ]}
          />
          <NavigationGroup
            label="nav.persona"
            icon={UsersRoundIcon}
            to="/personas"
            onActivate={openSaved}
            active={pathname === '/personas' || pathname === '/gallery'}
            children={[
              ['/personas', 'nav.saved', UsersRoundIcon, openSaved],
              ['/gallery', 'nav.gallery', LibraryIcon],
            ]}
          />
          {laterDestinations.map((destination) => (
            <NavigationLink key={destination[0]} destination={destination} />
          ))}
        </>
      )}
    </nav>
  );
}
