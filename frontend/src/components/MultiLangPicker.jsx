import React, { useState, useMemo, useRef, useEffect, useLayoutEffect, useId } from 'react';
import { createPortal } from 'react-dom';
import { X, Search, Plus } from 'lucide-react';
import { POPULAR_LANGS } from '../utils/constants';
import { LANG_CODES } from '../utils/languages';
import { useTranslation } from 'react-i18next';
import LanguageFlag from './LanguageFlag';

/**
 * MultiLangPicker — chip-based multi-language selector for batch dubbing.
 *
 * Shows selected languages as removable badges. Click "+" to open a
 * searchable dropdown with Popular + All Languages sections.
 */
export default function MultiLangPicker({
  selected = [], // array of { lang: string, code: string }
  onChange, // (newSelected) => void
  disabled = false,
}) {
  const { t } = useTranslation();
  const [dropOpen, setDropOpen] = useState(false);
  const [query, setQuery] = useState('');
  const dropRef = useRef(null);
  const menuRef = useRef(null);
  const triggerRef = useRef(null);
  const inputRef = useRef(null);
  const menuId = useId();
  const [menuPos, setMenuPos] = useState(null);

  // Close dropdown on outside click
  useEffect(() => {
    if (!dropOpen) return;
    const handler = (e) => {
      const insideTrigger = dropRef.current?.contains(e.target);
      const insideMenu = menuRef.current?.contains(e.target);
      if (!insideTrigger && !insideMenu) setDropOpen(false);
    };
    const onKeyDown = (e) => {
      if (e.key !== 'Escape') return;
      setDropOpen(false);
      triggerRef.current?.focus();
    };
    document.addEventListener('mousedown', handler);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', handler);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [dropOpen]);

  // The picker appears inside scrollable/clipping dubbing panels. A body
  // portal escapes every overflow ancestor; fixed positioning plus an
  // above/below flip keeps the menu inside the viewport at either edge.
  useLayoutEffect(() => {
    if (!dropOpen) return;
    const place = () => {
      const trigger = triggerRef.current;
      if (!trigger) return;
      const rect = trigger.getBoundingClientRect();
      const margin = 8;
      const gap = 4;
      const viewportWidth = window.innerWidth;
      const viewportHeight = window.innerHeight;
      const width = Math.min(Math.max(rect.width, 220), viewportWidth - margin * 2);
      const left = Math.min(
        Math.max(margin, rect.left),
        Math.max(margin, viewportWidth - width - margin),
      );
      const below = viewportHeight - rect.bottom - gap - margin;
      const above = rect.top - gap - margin;
      const openUp = below < 260 && above > below;
      const maxHeight = Math.max(0, Math.min(260, openUp ? above : below));
      setMenuPos(
        openUp
          ? { bottom: viewportHeight - rect.top + gap, left, width, maxHeight }
          : { top: rect.bottom + gap, left, width, maxHeight },
      );
    };
    place();
    window.addEventListener('scroll', place, true);
    window.addEventListener('resize', place);
    return () => {
      window.removeEventListener('scroll', place, true);
      window.removeEventListener('resize', place);
    };
  }, [dropOpen]);

  // Focus search when dropdown opens
  useEffect(() => {
    if (dropOpen && inputRef.current) inputRef.current.focus();
  }, [dropOpen]);

  const selectedCodes = useMemo(() => new Set(selected.map((s) => s.code)), [selected]);

  const addLang = (lang, code) => {
    if (selectedCodes.has(code)) return;
    onChange?.([...selected, { lang, code }]);
    setQuery('');
  };

  const removeLang = (code) => {
    onChange?.(selected.filter((s) => s.code !== code));
  };

  const filteredLangs = useMemo(() => {
    const q = query.toLowerCase().trim();
    return LANG_CODES.filter(
      (lc) =>
        !selectedCodes.has(lc.code) &&
        (!q || lc.label.toLowerCase().includes(q) || lc.code.toLowerCase().includes(q)),
    );
  }, [query, selectedCodes]);

  const popularFiltered = useMemo(() => {
    const q = query.toLowerCase().trim();
    return POPULAR_LANGS.map((lang) => {
      const match = LANG_CODES.find((lc) => lc.label.toLowerCase() === lang.toLowerCase());
      return match ? { lang, code: match.code } : null;
    }).filter(
      (item) =>
        item &&
        !selectedCodes.has(item.code) &&
        (!q || item.lang.toLowerCase().includes(q) || item.code.includes(q)),
    );
  }, [query, selectedCodes]);

  return (
    <div className="relative" ref={dropRef}>
      <div className="flex items-start gap-[5px] min-h-[28px]">
        {selected.length > 0 && (
          <div
            className="grid min-w-0 flex-1 grid-cols-[repeat(auto-fit,minmax(112px,1fr))] gap-[4px]"
            data-testid="multi-lang-selected-grid"
          >
            {selected.map((s) => (
              <span
                key={s.code}
                className="flex min-w-0 items-center gap-[5px] px-[6px] py-[3px] bg-[var(--chrome-hover-bg)] border border-solid border-transparent rounded-[var(--chrome-radius-pill)] [font-family:var(--font-sans)] text-[0.68rem] font-medium text-[color:var(--chrome-fg)]"
                title={s.lang}
              >
                <LanguageFlag code={s.code} />
                <span className="min-w-0 flex-1 truncate">{s.lang}</span>
                <span className="[font-family:var(--font-mono)] text-[0.58rem] uppercase text-[color:var(--chrome-fg-dim)]">
                  {s.code}
                </span>
                {!disabled && (
                  <button
                    type="button"
                    className="bg-transparent border-0 text-[color:var(--chrome-fg-muted)] cursor-pointer p-0 flex shrink-0 items-center rounded-full [transition:color_0.15s] hover:text-danger focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--chrome-accent)]"
                    onClick={() => removeLang(s.code)}
                    aria-label={t('common.remove', { term: s.lang })}
                  >
                    <X size={8} aria-hidden="true" />
                  </button>
                )}
              </span>
            ))}
          </div>
        )}
        {!disabled && (
          <button
            ref={triggerRef}
            type="button"
            className="flex shrink-0 items-center justify-center w-[24px] h-[24px] mt-[2px] rounded-full border border-dashed border-transparent bg-transparent text-[color:var(--chrome-fg-muted)] cursor-pointer [transition:background-color_0.15s,color_0.15s,border-color_0.15s] hover:bg-[var(--chrome-hover-bg)] hover:text-[color:var(--chrome-fg)] hover:border-solid focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--chrome-accent)]"
            onClick={() => setDropOpen((open) => !open)}
            title={t('dub.add_language')}
            aria-label={t('dub.add_language')}
            aria-haspopup="dialog"
            aria-expanded={dropOpen}
            aria-controls={dropOpen ? menuId : undefined}
          >
            <Plus size={10} aria-hidden="true" />
          </button>
        )}
      </div>

      {selected.length > 0 && (
        <div className="[font-family:var(--font-mono)] text-[0.62rem] text-[color:var(--chrome-fg-dim)] mt-[4px]">
          {t('dub.languages_selected', { count: selected.length })}
        </div>
      )}

      {dropOpen &&
        createPortal(
          <div
            ref={menuRef}
            id={menuId}
            className="multi-lang__drop"
            role="dialog"
            aria-label={t('dub.add_language')}
            style={
              menuPos
                ? {
                    left: menuPos.left,
                    width: menuPos.width,
                    maxHeight: menuPos.maxHeight,
                    ...(menuPos.bottom != null ? { bottom: menuPos.bottom } : { top: menuPos.top }),
                  }
                : { visibility: 'hidden' }
            }
          >
            <div className="flex items-center gap-[6px] px-[10px] py-[8px] border-b border-solid border-b-transparent text-[color:var(--chrome-fg-muted)]">
              <Search size={10} aria-hidden="true" />
              <input
                ref={inputRef}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t('dub.search_languages')}
                aria-label={t('dub.search_languages')}
                name="language-search"
                autoComplete="off"
                spellCheck={false}
                className="flex-1 bg-transparent border-0 text-[color:var(--chrome-fg)] [font-family:var(--font-sans)] text-[0.78rem] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--chrome-accent)]"
              />
            </div>
            <div className="overflow-y-auto overscroll-contain flex-1 py-[4px]">
              {popularFiltered.length > 0 && (
                <>
                  <div className="[font-family:var(--font-mono)] text-[0.62rem] font-semibold uppercase [letter-spacing:0.04em] text-[color:var(--chrome-fg-dim)] pt-[6px] px-[10px] pb-[2px]">
                    {t('dub.popular')}
                  </div>
                  <div className="grid grid-cols-[repeat(auto-fit,minmax(140px,1fr))] gap-[2px] px-[4px]">
                    {popularFiltered.map((item) => (
                      <button
                        key={item.code}
                        type="button"
                        className="flex min-w-0 items-center gap-[7px] rounded-[4px] px-[7px] py-[5px] bg-transparent border-0 text-[color:var(--chrome-fg)] [font-family:var(--font-sans)] text-[0.76rem] cursor-pointer text-left [transition:background_0.1s] hover:bg-[var(--chrome-hover-bg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--chrome-accent)]"
                        onClick={() => addLang(item.lang, item.code)}
                      >
                        <LanguageFlag code={item.code} />
                        <span className="[font-family:var(--font-mono)] text-[0.64rem] text-[color:var(--chrome-accent)] min-w-[24px] font-semibold uppercase">
                          {item.code}
                        </span>
                        <span className="min-w-0 truncate">{item.lang}</span>
                      </button>
                    ))}
                  </div>
                </>
              )}
              <div className="[font-family:var(--font-mono)] text-[0.62rem] font-semibold uppercase [letter-spacing:0.04em] text-[color:var(--chrome-fg-dim)] pt-[6px] px-[10px] pb-[2px]">
                {t('dub.all_languages')}
              </div>
              <div
                className="grid grid-cols-[repeat(auto-fit,minmax(140px,1fr))] gap-[2px] px-[4px]"
                data-testid="multi-lang-all-grid"
              >
                {filteredLangs.slice(0, 50).map((lc) => (
                  <button
                    key={lc.code}
                    type="button"
                    className="flex min-w-0 items-center gap-[7px] rounded-[4px] px-[7px] py-[5px] bg-transparent border-0 text-[color:var(--chrome-fg)] [font-family:var(--font-sans)] text-[0.76rem] cursor-pointer text-left [transition:background_0.1s] hover:bg-[var(--chrome-hover-bg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--chrome-accent)]"
                    onClick={() => addLang(lc.label, lc.code)}
                  >
                    <LanguageFlag code={lc.code} />
                    <span className="[font-family:var(--font-mono)] text-[0.64rem] text-[color:var(--chrome-accent)] min-w-[24px] font-semibold uppercase">
                      {lc.code}
                    </span>
                    <span className="min-w-0 truncate">{lc.label}</span>
                  </button>
                ))}
              </div>
              {filteredLangs.length > 50 && (
                <div className="px-[10px] py-[8px] text-[0.7rem] text-[color:var(--chrome-fg-dim)] text-center">
                  {t('dub.more_to_narrow', { count: filteredLangs.length - 50 })}
                </div>
              )}
              {filteredLangs.length === 0 && popularFiltered.length === 0 && (
                <div className="px-[10px] py-[8px] text-[0.7rem] text-[color:var(--chrome-fg-dim)] text-center">
                  {t('dub.no_matches')}
                </div>
              )}
            </div>
          </div>,
          document.body,
        )}
    </div>
  );
}
