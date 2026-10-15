import { useEffect, useState } from 'react';
import { getBridge } from '@/components/bridge';
import type { AccountPublicState } from '../../../../preload/index.d';

export function useAccount() {
  const account = getBridge()?.account;
  const [state, setState] = useState<AccountPublicState | undefined>();
  useEffect(() => {
    if (!account) return;
    let live = true;
    void account.get().then((s) => live && setState(s)).catch(() => {});
    const off = account.onState((s) => live && setState(s));
    return () => { live = false; off(); };
  }, [account]);
  return {
    supported: Boolean(account),
    state,
    setSwitches: async (p: { accountEnabled?: boolean; syncEnabled?: boolean }) =>
      account && setState(await account.setSwitches(p)),
    signIn: () => account?.signIn(),
    cancelSignIn: () => account?.cancelSignIn(),
    signOut: () => account?.signOut(),
  };
}
