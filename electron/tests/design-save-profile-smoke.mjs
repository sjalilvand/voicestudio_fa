import { chromium } from 'playwright';
import assert from 'node:assert/strict';

// Saving a designed voice confirms it: the form only clears its name field, so
// without the toast the save looked like nothing happened.
const BASE = process.env.VOICESTUDIO_UI_URL || 'http://localhost:3912';
const browser = await chromium.launch({
  ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}),
  headless: true,
});
try {
  // CLEAN-ROOM (spec W7-tests §11): mocked page with profile-create handler, then open the design route
  await page.getByRole('textbox', { name: 'Profile name' }).fill('Release voice');
  await page.getByRole('button', { name: 'Save as voice profile' }).click();
  await page.locator('[data-sonner-toast]', { hasText: 'Voice profile saved.' }).waitFor();
  assert.equal(created.length, 1);
  assert.equal(await page.getByRole('textbox', { name: 'Profile name' }).inputValue(), '');
  console.log('design save profile smoke passed');
} finally {
  await browser.close();
}
