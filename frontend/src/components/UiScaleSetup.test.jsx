import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { I18nextProvider } from 'react-i18next';
import i18n from '../i18n';
import UiScaleSetup from './UiScaleSetup';

const renderSetup = () => {
  const setUiScale = vi.fn();
  const setUiScaleConfigured = vi.fn();
  render(
    <I18nextProvider i18n={i18n}>
      <UiScaleSetup
        uiScale={1}
        setUiScale={setUiScale}
        setUiScaleConfigured={setUiScaleConfigured}
      />
    </I18nextProvider>,
  );
  return { setUiScale, setUiScaleConfigured };
};

describe('<UiScaleSetup />', () => {
  it('preselects the resolution suggestion and persists the checked choice', () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1280 });
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 720 });
    const { setUiScale, setUiScaleConfigured } = renderSetup();

    expect(screen.getByTestId('ui-scale-option-80')).toHaveAttribute('aria-checked', 'true');
    fireEvent.click(screen.getByTestId('ui-scale-option-110'));
    expect(setUiScale).toHaveBeenLastCalledWith(1.1);

    fireEvent.click(screen.getByTestId('ui-scale-setup-continue'));
    expect(setUiScaleConfigured).toHaveBeenCalledWith(true);
    expect(setUiScale).toHaveBeenLastCalledWith(1.1);
  });

  it('supports roving keyboard selection across the scale choices', () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1440 });
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 900 });
    const { setUiScale } = renderSetup();
    const selected = screen.getByTestId('ui-scale-option-100');
    selected.focus();

    fireEvent.keyDown(selected, { key: 'ArrowRight' });
    expect(screen.getByTestId('ui-scale-option-110')).toHaveFocus();
    expect(screen.getByTestId('ui-scale-option-110')).toHaveAttribute('aria-checked', 'true');
    expect(setUiScale).toHaveBeenLastCalledWith(1.1);
  });
});
