import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, fireEvent, screen } from '@testing-library/react';
import '../i18n';
import MultiLangPicker from './MultiLangPicker';

const rect = (overrides = {}) => ({
  x: 40,
  y: 720,
  top: 720,
  right: 64,
  bottom: 744,
  left: 40,
  width: 24,
  height: 24,
  toJSON: () => {},
  ...overrides,
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('MultiLangPicker viewport-safe menu', () => {
  it('portals outside clipping ancestors and flips above a bottom-edge trigger', () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1000 });
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 800 });
    const onChange = vi.fn();
    const { container } = render(
      <div data-testid="clipper" style={{ overflow: 'hidden', height: 40 }}>
        <MultiLangPicker selected={[]} onChange={onChange} />
      </div>,
    );
    const trigger = screen.getByRole('button', { name: 'Add language' });
    vi.spyOn(trigger, 'getBoundingClientRect').mockReturnValue(rect());

    fireEvent.click(trigger);

    const menu = screen.getByRole('dialog', { name: 'Add language' });
    expect(container).not.toContainElement(menu);
    expect(menu).toHaveStyle({ bottom: '84px', left: '40px', width: '220px' });
    expect(menu.style.top).toBe('');
    expect(menu.style.maxHeight).toBe('260px');

    fireEvent.click(screen.getAllByRole('button', { name: /Spanish/ })[0]);
    expect(onChange).toHaveBeenCalledWith([{ lang: 'Spanish', code: 'es' }]);
  });

  it('opens below when space permits and Escape closes then restores trigger focus', () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1000 });
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 800 });
    render(<MultiLangPicker selected={[]} onChange={vi.fn()} />);
    const trigger = screen.getByRole('button', { name: 'Add language' });
    vi.spyOn(trigger, 'getBoundingClientRect').mockReturnValue(
      rect({ y: 20, top: 20, bottom: 44 }),
    );

    fireEvent.click(trigger);
    const menu = screen.getByRole('dialog', { name: 'Add language' });
    expect(menu).toHaveStyle({ top: '48px' });
    expect(menu.style.bottom).toBe('');

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: 'Add language' })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });
});
