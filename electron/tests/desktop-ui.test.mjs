import { test } from 'node:test';
import assert from 'node:assert/strict';
import { withApp } from './desktop-harness.mjs';

const bridgeFacts = (page) =>
  page.evaluate(() => ({
    title: document.title,
    platform: window.voicestudio?.app?.platform,
    saveData: typeof window.voicestudio?.files?.saveData,
  }));

test('launch: window, title and bridge match the real OS', async (t) => {
  await withApp(t, {}, async ({ page }) => {
    await page.waitForFunction(() => Boolean(window.voicestudio?.files?.saveData));
    const facts = await bridgeFacts(page);
    assert.match(facts.title, /VoiceStudio/);
    assert.equal(facts.platform, process.platform);
    assert.equal(facts.saveData, 'function');
  });
});

test('guard: a main-process request leaving the machine fails the run', async (t) => {
  await assert.rejects(
    withApp(t, {}, async ({ app }) => {
      await app.evaluate(({ net }) => net.fetch('https://example.com/leak').catch(() => {}));
    }),
    /Requests left the machine/,
  );
});

test('guard: a renderer request leaving the machine fails the run', async (t) => {
  // The app's CSP blocks it; the console error is what the harness reports.
  await assert.rejects(
    withApp(t, {}, async ({ page }) => {
      await page.waitForFunction(() => Boolean(window.voicestudio?.files?.saveData));
      await page.evaluate(() => fetch('https://example.com/leak').catch(() => {}));
    }),
    /Renderer reported errors/,
  );
});

test('reload keeps the bridge working', async (t) => {
  await withApp(t, {}, async ({ page }) => {
    await page.reload();
    await page.waitForFunction(() => Boolean(window.voicestudio?.files?.saveData));
    const facts = await bridgeFacts(page);
    assert.equal(facts.platform, process.platform);
    assert.equal(facts.saveData, 'function');
  });
});
