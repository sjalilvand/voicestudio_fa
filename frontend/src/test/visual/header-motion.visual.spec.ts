import { expect, test } from '@playwright/test';

test('header dot responds to reduced motion and narrow viewports', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await page.goto('/src/test/visual/harness.html?component=HeaderStatus');
  const dot = page.locator('span[class*="hqPulse"]');
  await expect(dot).toBeVisible();
  await expect(dot).toHaveCSS('animation-name', 'hqPulse');
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await expect(dot).toHaveCSS('animation-name', 'none');
  await page.setViewportSize({ width: 800, height: 800 });
  await expect(dot).toBeHidden();
  await page.setViewportSize({ width: 1280, height: 800 });
  await expect(dot).toBeVisible();
  await expect(dot).toHaveCSS('animation-name', 'none');
});
