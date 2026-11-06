import { beforeEach, describe, expect, it } from 'vitest';

import { discardPendingWrites } from '../utils/coalescedJsonStorage';
import { discardLongformPendingWrites } from '../utils/longformPersistence';
import { APP_STORE_KEY, useAppStore } from './index';

describe('locale persistence', () => {
  beforeEach(() => {
    localStorage.clear();
    useAppStore.setState(useAppStore.getInitialState(), true);
    discardLongformPendingWrites();
    discardPendingWrites((key) => key === APP_STORE_KEY);
  });

  it('restores the selected locale after rehydration', async () => {
    localStorage.setItem(
      APP_STORE_KEY,
      JSON.stringify({ state: { locale: 'zh-CN', localeChosen: true }, version: 8 }),
    );
    await useAppStore.persist.rehydrate();

    expect(useAppStore.getState().locale).toBe('zh-CN');
  });

  it('v10: migrates an auto-detected (never chosen) locale to Persian', async () => {
    // Persian fork (voicestudio_fa): stores written before the fork seeded
    // locale from navigator.language — 'en' with localeChosen:false is an
    // auto-detection, not a user decision, so it becomes Persian. An explicit
    // choice (localeChosen:true) is never touched.
    localStorage.setItem(
      APP_STORE_KEY,
      JSON.stringify({ state: { locale: 'en', localeChosen: false }, version: 9 }),
    );
    await useAppStore.persist.rehydrate();

    expect(useAppStore.getState().locale).toBe('fa');
    expect(useAppStore.getState().localeChosen).toBe(false);
  });

  it('v10: keeps an explicitly chosen locale untouched', async () => {
    localStorage.setItem(
      APP_STORE_KEY,
      JSON.stringify({ state: { locale: 'en', localeChosen: true }, version: 9 }),
    );
    await useAppStore.persist.rehydrate();

    expect(useAppStore.getState().locale).toBe('en');
  });
});
