import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, Zap } from 'lucide-react';
import { cn } from '@/lib/utils';
import { openExternal } from '../api/external';
import { apiPost } from '../api/client';
import { Button, Input } from '../ui';

/* CLEAN-ROOM (spec P-pr1874 §10): component documentation block. */
export default function HfTokenCard({ className = '' }) {
  const { t } = useTranslation();
  const [hfToken, setHfToken] = useState('');
  const [hfState, setHfState] = useState('idle'); // idle | saving | saved | error

  // CLEAN-ROOM (spec P-pr1874 §10): token-state loading (request, validation, retry) and the explicit replace gate live here.
  const saveHfToken = async () => {
    const value = hfToken.trim();
    if (!value || hfState === 'saving') return;
    setHfState('saving');
    try {
      await apiPost('/api/settings/hf-token', { token: value });
      setHfState('saved');
      setHfToken('');
    } catch {
      setHfState('error');
    }
  };

  if (hfState === 'saved') {
    return (
      <div
        className={cn(
          'flex flex-wrap items-center gap-2 rounded-md border border-transparent bg-success/[0.09] px-3 py-2 text-sm',
          className,
        )}
      >
        <span className="inline-flex items-center gap-1.5 font-semibold text-success">
          <Check size={14} aria-hidden="true" />
          {t('firstrun.hf_token_saved', 'Hugging Face token saved')}
        </span>
      </div>
    );
  }

  // CLEAN-ROOM (spec P-pr1874 §10): error state with Retry when the token-state check fails.

  // CLEAN-ROOM (spec P-pr1874 §10): neutral "checking" placeholder while the token-state request is in flight.

  // CLEAN-ROOM (spec P-pr1874 §10): when a token is already active, show a satisfied state (source label, masked value) with a Replace control instead of the pitch.

  // A successful state read found no token, or replacement was explicit.
  return (
    <div
      className={cn(
        'flex flex-wrap items-center gap-2 rounded-md border border-transparent bg-primary/[0.07] px-3 py-2 text-sm',
        className,
      )}
    >
      <Zap size={16} className="shrink-0 text-primary" aria-hidden="true" />
      {/* CLEAN-ROOM (spec P-pr1874 §10): headline text switches to an overwrite warning while replacing an active token. */}
      <span className="font-semibold max-[560px]:hidden">
        {t('firstrun.hf_token_inline_prompt', 'Speed up downloads with a free Hugging Face token')}
      </span>
      <Input
        size="sm"
        className="min-w-[130px] flex-1 basis-[180px]"
        type="password"
        placeholder={t('firstrun.hf_token_inline_ph', 'Paste hf_… token (optional)')}
        value={hfToken}
        autoComplete="off"
        disabled={hfState === 'saving'}
        onChange={(e) => {
          if (hfState === 'saving') return;
          setHfToken(e.target.value);
          if (hfState !== 'idle') setHfState('idle');
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter') saveHfToken();
        }}
        aria-label={t(
          'firstrun.hf_token_card_title',
          'Add a free Hugging Face token for faster downloads',
        )}
      />
      <Button
        variant="primary"
        size="sm"
        disabled={!hfToken.trim() || hfState === 'saving'}
        onClick={saveHfToken}
      >
        {hfState === 'saving'
          ? t('firstrun.hf_token_saving', 'saving…')
          : t('firstrun.hf_token_save', 'Save')}
      </Button>
      {/* CLEAN-ROOM (spec P-pr1874 §10): when replacing an active token, a Cancel control that leaves replace mode, clears the input and resets save state. */}
      <button
        type="button"
        className="cursor-pointer appearance-none whitespace-nowrap border-0 bg-transparent p-0 text-[0.76rem] text-primary underline hover:no-underline"
        onClick={() => openExternal('https://huggingface.co/settings/tokens')}
      >
        {t('firstrun.hf_token_get_short', 'Get one free →')}
      </button>
      {hfState === 'error' && (
        <span className="basis-full text-[0.76rem] text-danger">
          {t(
            'firstrun.hf_token_error',
            'Could not save the token — try again or set it later in Settings → Credentials.',
          )}
        </span>
      )}
    </div>
  );
}
