import { beforeEach, describe, expect, it } from 'vitest';
import { clearBreadcrumbs, getBreadcrumbs } from '../../../../../frontend/src/utils/breadcrumbs';
import { recordActionBreadcrumb, routeBreadcrumb } from './report-breadcrumb';

beforeEach(clearBreadcrumbs);

describe('routeBreadcrumb', () => {
  it('keeps only fixed workspace and settings labels', () => {
    expect(routeBreadcrumb('#/clone')).toBe('view:clone');
    expect(routeBreadcrumb('#/settings/models/tts')).toBe('view:settings/models');
    expect(routeBreadcrumb('#/personas?query=private-name')).toBe('view:personas');
    expect(routeBreadcrumb('#/private/user/content')).toBe('view:other');
  });
});

describe('recordActionBreadcrumb', () => {
  it('records fixed workflow actions and rejects dynamic values', () => {
    recordActionBreadcrumb('generate:clone:start');
    recordActionBreadcrumb('private-file:C:/Users/name/voice.wav' as never);
    expect(getBreadcrumbs().map((entry) => entry.action)).toEqual(['generate:clone:start']);
  });
});
