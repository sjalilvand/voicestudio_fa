import assert from 'node:assert/strict';
import { chromium } from 'playwright';

const browser = await chromium.launch({ channel: 'msedge', headless: true });
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
const ui = process.env.VOICESTUDIO_UI_URL || 'http://localhost:3912';
let changed = false;
let currentTier = 'fast';
let fail = false;
let releaseSave;
let releaseEngines;
const saveGate = new Promise((resolve) => {
  releaseSave = resolve;
});
const engineGate = new Promise((resolve) => {
  releaseEngines = resolve;
});
const writes = [];
const model = () => (changed ? 'test/medium' : 'test/small');
const profile = () => ({
  global: currentTier,
  overrides: {},
  effective: { asr: changed ? 'balanced' : 'fast' },
  families: ['tts', 'asr'],
  implemented_families: ['asr'],
  applicable_families: ['asr'],
  targets: { tts: {}, asr: { beam_size: changed ? 3 : 1 } },
  selections: {
    tts: { engine: 'kitten', model: null },
    asr: {
      engine: 'faster-whisper',
      model: model(),
      label: changed ? 'Whisper medium' : 'Whisper small',
    },
  },
  plan: {
    resolved: currentTier === 'auto' ? 'quality' : currentTier,
    status: 'adjusted',
    max_status: 'adjusted',
    hardware: { device: 'cuda', ram_gb: 32, vram_gb: 8, cpu_threads: 16 },
    families: Object.fromEntries(
      ['tts', 'asr', 'translation', 'dictation', 'diarisation', 'llm'].map((name) => [
        name,
        { tier: 'quality', reason: name === 'asr' ? 'memory' : 'installed', selection: null },
      ]),
    ),
  },
});
try {
  await page.addInitScript(() => localStorage.setItem('voicestudio.setup.complete.v1', '1'));
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.endsWith('/settings/performance-profile')) {
      if (request.method() === 'PUT') {
        writes.push(request.postDataJSON());
        if (fail) return route.fulfill({ status: 409, json: { detail: 'Test: engine busy' } });
        await saveGate;
        changed = true;
        currentTier = request.postDataJSON().tier;
      }
      return route.fulfill({ json: profile() });
    }
    assert.equal(request.method(), 'GET', 'The smoke test must never mutate the live backend');
    if (path.endsWith('/engines')) {
      if (changed) await engineGate;
      return route.fulfill({
        json: {
          tts: {
            active: 'kitten',
            active_model: null,
            backends: [{ id: 'kitten', display_name: 'KittenTTS', available: true }],
          },
          asr: {
            active: 'faster-whisper',
            active_model: model(),
            backends: [{ id: 'faster-whisper', display_name: 'Faster-Whisper', available: true }],
          },
          llm: { active: 'off', backends: [{ id: 'off', display_name: 'Off', available: true }] },
        },
      });
    }
    if (path.endsWith('/model/loaded')) return route.fulfill({ json: { models: [], count: 0 } });
    if (path.endsWith('/batch/jobs')) return route.fulfill({ json: [] });
    return route.continue();
  });
  await page.goto(ui + '/#/clone');
  const footer = page.locator('aside').first().locator('footer');
  const slider = footer.getByRole('slider');
  await slider.waitFor();
  await page.waitForFunction(() => !document.querySelector('footer input[type=range]')?.disabled);
  await slider.focus();
  await slider.press('ArrowRight');
  await page.waitForFunction(() => document.querySelector('footer input[type=range]')?.disabled);
  releaseSave();
  await footer.locator('[data-detail-level=models]').waitFor();
  const asr = footer.locator('[data-slot=engine-row]').filter({ hasText: 'Speech to text' });
  await asr.getByRole('status').filter({ hasText: 'Switching' }).waitFor();
  assert.ok(
    (await asr.innerText()).includes('medium'),
    'Show the confirmed replacement while catalogue refresh is pending',
  );
  assert.equal(await asr.getAttribute('aria-busy'), 'true');
  releaseEngines();
  await asr.getByRole('status').filter({ hasText: 'Available' }).waitFor();
  assert.equal(await asr.getAttribute('aria-busy'), 'false');
  assert.equal(await slider.getAttribute('aria-valuetext'), 'Balanced');
  assert.deepEqual(writes, [{ tier: 'balanced', family: null }]);
  fail = true;
  await slider.focus();
  await slider.press('ArrowLeft');
  await footer.getByRole('alert').waitFor();
  assert.equal(
    await slider.getAttribute('aria-valuetext'),
    'Balanced',
    'A rejected save restores the confirmed preset',
  );
  assert.ok(
    (await asr.innerText()).includes('medium'),
    'A rejected save preserves the confirmed model',
  );
  fail = false;
  await slider.focus();
  await slider.press('End');
  await page.waitForFunction(
    () =>
      document.querySelector('footer input[type=range]')?.getAttribute('aria-valuetext') === 'Auto',
  );
  await page.waitForFunction(() => !document.querySelector('footer input[type=range]')?.disabled);
  await footer.getByRole('button', { name: 'Quality · Adapted to your hardware' }).click();
  await page.getByText('32 GB RAM · 16 CPU threads · 8 GB VRAM').waitFor();
  await page.getByText('Memory limit', { exact: true }).waitFor();
  assert.deepEqual(writes.at(-1), { tier: 'auto', family: null });
  await page
    .locator('[data-slot=popover-content]')
    .evaluate((el) => Promise.all(el.getAnimations().map((animation) => animation.finished)));
  await page.screenshot({ path: '.tmp-sidebar-auto.png' });
  console.log(
    'Slider: confirmed model feedback, loading, rollback, Auto selection and hardware explanation passed; all writes mocked.',
  );
} finally {
  releaseSave();
  releaseEngines();
  await browser.close();
}
