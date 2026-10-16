import { Link } from '@tanstack/react-router';
import { UserRoundIcon } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useAccount } from '@/features/account/use-account';
import { cn } from '@/lib/utils';

function initials(name: string): string {
  const words = name.includes('@') ? [name] : name.trim().split(/\s+/);
  return words
    .slice(0, 2)
    .map((word) => word[0] ?? '')
    .join('')
    .toUpperCase();
}

function Avatar({ name, url, size }: { name: string; url: string | null; size: string }) {
  return url ? (
    <img src={url} alt="" className={cn(size, 'shrink-0 rounded-full object-cover')} />
  ) : (
    <span
      aria-hidden="true"
      className={cn(
        size,
        'grid shrink-0 place-items-center rounded-full bg-primary/15 text-[11px] font-semibold text-primary',
      )}
    >
      {initials(name)}
    </span>
  );
}

/**
 * Always-visible "signed in" badge in the main sidebar: the profile photo (or
 * initials) and name, linking to Settings → Account. Nothing shows unless the
 * user turned account features on and is signed in.
 */
export function AccountBadge({ compact = false }: { compact?: boolean }) {
  const { t } = useTranslation();
  const { state } = useAccount();
  if (!state?.available || !state.accountEnabled) return null;

  if (!state.signedIn) {
    if (state.notice !== 'signed_out_expired') return null;
    return (
      <Link
        to="/settings/account"
        aria-label={t('account.badge_sign_in_again')}
        title={t('account.signed_out_expired')}
        className={cn(
          'workspace-nav-item flex min-w-0 items-center gap-2 rounded-md text-sm text-muted-foreground outline-none hover:bg-[var(--sidebar-row-hover)] focus-visible:ring-2 focus-visible:ring-ring',
          compact ? 'size-8 justify-center' : 'px-2 py-1.5',
        )}
      >
        <UserRoundIcon className="size-4 shrink-0" aria-hidden="true" />
        {!compact && <span className="truncate">{t('account.badge_sign_in_again')}</span>}
      </Link>
    );
  }

  const name = state.profile?.displayName || state.profile?.email || t('account.title');
  const label = t('account.signed_in_as', { name });
  const photo = state.profile?.avatarUrl ?? null;
  return (
    <Link
      to="/settings/account"
      aria-label={label}
      title={label}
      data-slot="account-badge"
      className={cn(
        'workspace-nav-item flex min-w-0 items-center gap-2 rounded-md outline-none hover:bg-[var(--sidebar-row-hover)] focus-visible:ring-2 focus-visible:ring-ring',
        compact ? 'size-8 justify-center' : 'px-2 py-1.5',
      )}
    >
      <span className="relative shrink-0">
        <Avatar name={name} url={photo} size={compact ? 'size-6' : 'size-7'} />
        {/* Signed-in dot */}
        <span
          aria-hidden="true"
          className="absolute -right-0.5 -bottom-0.5 size-2.5 rounded-full border-2 border-sidebar bg-success"
        />
      </span>
      {!compact && <span className="min-w-0 truncate text-sm font-medium">{name}</span>}
    </Link>
  );
}
