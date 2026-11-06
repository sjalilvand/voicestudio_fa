import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render } from '@testing-library/react';
import { I18nextProvider } from 'react-i18next';
import i18n from '../i18n';
import { useAppStore } from '../store';
import LanguageSwitchPrompt from '../components/LanguageSwitchPrompt';
import { configureLongformDurableStoreForTests } from '../utils/longformPersistence';

const withI18n = (node) => <I18nextProvider i18n={i18n}>{node}</I18nextProvider>;

function seed(partial) {
  useAppStore.setState({
    locale: 'de',
    localeChosen: false,
    langPromptSeen: false,
    ...partial,
  });
}

beforeEach(async () => {
  let durableRecord = null;
  configureLongformDurableStoreForTests({
    read: async () => durableRecord,
    write: async (record) => {
      durableRecord = structuredClone(record);
    },
    clear: async () => {
      durableRecord = null;
    },
  });
  // Production bootstrap now awaits async IndexedDB hydration before render.
  await useAppStore.persist.rehydrate();
  seed({});
});
afterEach(() => {
  vi.restoreAllMocks();
});

/**
 * Persian fork (voicestudio_fa): the "Switch to English?" first-run offer is
 * disabled outright — the fork opens in Persian on purpose, and offering a
 * switch to English would only nag the target audience. Upstream keeps the
 * interactive banner; here the component must render nothing in EVERY state,
 * including the states where upstream would show it.
 */
describe('LanguageSwitchPrompt — disabled in the Persian fork', () => {
  it('never renders for a non-English first run with no prior choice', () => {
    const { container } = render(withI18n(<LanguageSwitchPrompt />));
    expect(container.firstChild).toBeNull();
  });

  it('never renders for an English UI', () => {
    seed({ locale: 'en' });
    const { container } = render(withI18n(<LanguageSwitchPrompt />));
    expect(container.firstChild).toBeNull();
  });

  it('never renders once the seen flag is set (one-time)', () => {
    seed({ langPromptSeen: true });
    const { container } = render(withI18n(<LanguageSwitchPrompt />));
    expect(container.firstChild).toBeNull();
  });

  it('never renders once the user has explicitly chosen a language', () => {
    seed({ localeChosen: true });
    const { container } = render(withI18n(<LanguageSwitchPrompt />));
    expect(container.firstChild).toBeNull();
  });
});
