import { useEffect, useRef, useState } from 'react';
import { Check, Monitor } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '../ui';
import { UI_SCALE_OPTIONS, suggestUiScale } from '../utils/uiScaleSuggestion';

function getViewport() {
  if (typeof window === 'undefined') return { width: 1440, height: 900 };
  return {
    width: Math.max(1, Math.round(window.innerWidth)),
    height: Math.max(1, Math.round(window.innerHeight)),
  };
}

export default function UiScaleSetup({
  uiScale,
  setUiScale,
  setUiScaleConfigured,
  setUiScalePreviewed,
}) {
  const { t } = useTranslation();
  const [viewport, setViewport] = useState(getViewport);
  const suggestedScale = suggestUiScale(viewport);
  const [selectedScale, setSelectedScale] = useState(() =>
    uiScale === 1 ? suggestUiScale(getViewport()) : uiScale,
  );
  const hasPickedRef = useRef(false);
  const optionRefs = useRef([]);

  useEffect(() => {
    const handleResize = () => setViewport(getViewport());
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  useEffect(() => {
    if (hasPickedRef.current) return;
    setSelectedScale(suggestedScale);
    setUiScale(suggestedScale);
  }, [setUiScale, suggestedScale]);

  const chooseScale = (scale) => {
    hasPickedRef.current = true;
    setSelectedScale(scale);
    setUiScale(scale);
    setUiScalePreviewed(true);
  };

  const moveSelection = (event, currentIndex) => {
    let nextIndex;
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
      nextIndex = (currentIndex + 1) % UI_SCALE_OPTIONS.length;
    } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
      nextIndex = (currentIndex - 1 + UI_SCALE_OPTIONS.length) % UI_SCALE_OPTIONS.length;
    } else if (event.key === 'Home') {
      nextIndex = 0;
    } else if (event.key === 'End') {
      nextIndex = UI_SCALE_OPTIONS.length - 1;
    } else {
      return;
    }
    event.preventDefault();
    chooseScale(UI_SCALE_OPTIONS[nextIndex]);
    optionRefs.current[nextIndex]?.focus();
  };

  const finish = () => {
    setUiScale(selectedScale);
    setUiScaleConfigured(true);
    setUiScalePreviewed(false);
  };

  const selectedPercent = Math.round(selectedScale * 100);
  const suggestedPercent = Math.round(suggestedScale * 100);

  return (
    <main
      className="ui-scale-setup"
      aria-labelledby="ui-scale-setup-title"
      data-testid="ui-scale-setup"
    >
      <section className="ui-scale-setup__card">
        <div className="ui-scale-setup__eyebrow">
          <Monitor size={14} aria-hidden="true" />
          {t('settings.ui_scale_setup_screen', viewport)}
        </div>
        <h1 id="ui-scale-setup-title" className="ui-scale-setup__title">
          {t('settings.ui_scale_setup_title')}
        </h1>
        <p className="ui-scale-setup__description">{t('settings.ui_scale_setup_desc')}</p>

        <div
          className="ui-scale-setup__options"
          role="radiogroup"
          aria-label={t('settings.ui_scale')}
        >
          {UI_SCALE_OPTIONS.map((scale, index) => {
            const percent = Math.round(scale * 100);
            const isSelected = selectedScale === scale;
            const isSuggested = suggestedScale === scale;
            return (
              <button
                key={scale}
                ref={(node) => {
                  optionRefs.current[index] = node;
                }}
                type="button"
                role="radio"
                aria-checked={isSelected}
                tabIndex={isSelected ? 0 : -1}
                className={`ui-scale-option${isSelected ? ' is-selected' : ''}`}
                onClick={() => chooseScale(scale)}
                onKeyDown={(event) => moveSelection(event, index)}
                data-testid={`ui-scale-option-${percent}`}
              >
                <span className="ui-scale-option__value">{percent}%</span>
                {isSuggested ? (
                  <span className="ui-scale-option__hint">
                    {t('settings.ui_scale_setup_suggested')}
                  </span>
                ) : null}
                {isSelected ? <Check size={14} aria-hidden="true" /> : null}
              </button>
            );
          })}
        </div>

        <div className="ui-scale-preview" aria-live="polite">
          <div className="ui-scale-preview__heading">
            <span>{t('settings.ui_scale_setup_preview_title')}</span>
            <span className="ui-scale-preview__percent">{selectedPercent}%</span>
          </div>
          <div className="ui-scale-preview__window" aria-hidden="true">
            <div className="ui-scale-preview__toolbar">
              <span className="ui-scale-preview__dot" />
              <span className="ui-scale-preview__dot" />
              <span className="ui-scale-preview__dot" />
            </div>
            <div className="ui-scale-preview__body">
              <div className="ui-scale-preview__sidebar" />
              <div className="ui-scale-preview__content">
                <div className="ui-scale-preview__line ui-scale-preview__line--wide" />
                <div className="ui-scale-preview__line" />
                <div className="ui-scale-preview__controls">
                  <span />
                  <span />
                  <span />
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="ui-scale-setup__footer">
          <span className="ui-scale-setup__note">
            {t('settings.ui_scale_setup_current_suggestion', { percent: suggestedPercent })}
          </span>
          <Button variant="primary" onClick={finish} data-testid="ui-scale-setup-continue">
            {t('settings.ui_scale_setup_continue', { percent: selectedPercent })}
          </Button>
        </div>
      </section>
    </main>
  );
}
