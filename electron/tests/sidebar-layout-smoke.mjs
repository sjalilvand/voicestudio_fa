import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
const browser = await chromium.launch({ channel: 'msedge', headless: true });
const page = await browser.newPage();
const out = mkdtempSync(join(tmpdir(), 'voicestudio-sidebar-'));
const ui = process.env.VOICESTUDIO_UI_URL || 'http://localhost:3912';
try {
  await page.addInitScript(() => localStorage.setItem('voicestudio.setup.complete.v1', '1'));
  await page.goto(ui + '/#/clone');
  const sidebar = page.locator('aside').first();
  const navigation = sidebar.getByRole('navigation', { name: 'Workspaces', exact: true });
  await navigation.waitFor();
  assert.equal(await sidebar.locator('footer a:visible').count(), 6);
  await sidebar.getByRole('link', { name: 'Change engine TTS', exact: true }).hover();
  const engineTooltip = page.locator('[data-slot=tooltip-content]');
  await engineTooltip.waitFor();
  assert.ok((await engineTooltip.innerText()).includes('TTS'));
  await page.mouse.move(800, 100);
  await engineTooltip.waitFor({ state: 'detached' });
  for (const [width, height] of [
    [1280, 720],
    [960, 600],
  ]) {
    await page.setViewportSize({ width, height });
    assert.equal(await navigation.getByRole('link').count(), 9);
    assert.equal(await page.getByRole('menu').count(), 0);
    const bounds = await navigation.boundingBox();
    assert.ok(bounds && bounds.width <= (await sidebar.boundingBox()).width);
    if (height >= 700) {
      assert.ok(
        await navigation.evaluate((el) => el.scrollHeight <= el.clientHeight),
        'Collapsed workspace navigation should fit without scrolling at standard window height',
      );
    }
    await page.screenshot({ path: join(out, 'navigation-' + height + '.png') });
    const summary = sidebar.locator('[aria-controls=sidebar-engine-details]');
    await summary.click();
    await sidebar.locator('#sidebar-engine-details a').nth(5).waitFor();
    assert.equal(await sidebar.locator('#sidebar-engine-details a').count(), 6);
    const modelDetails = sidebar.locator('#sidebar-engine-details a p:nth-of-type(2)');
    assert.equal(await modelDetails.count(), 6);
    assert.ok(await modelDetails.first().isVisible());
    assert.ok(
      await sidebar
        .locator('#sidebar-engine-details')
        .evaluate((el) => el.scrollHeight <= el.clientHeight),
    );
    const footer = await sidebar.getByRole('link', { name: 'Settings', exact: true }).boundingBox();
    assert.ok(
      footer && footer.y + footer.height <= height,
      `Settings footer escaped ${width}x${height}: ${JSON.stringify(footer)}`,
    );
    assert.ok(!(await sidebar.innerText()).includes('\u00c2'));
    await page.screenshot({ path: join(out, 'engines-' + height + '.png') });
    await summary.click();
    await page.screenshot({ path: join(out, 'compact-' + height + '.png') });
  }
  await navigation.getByRole('link', { name: 'Stories', exact: true }).click();
  await page.waitForURL('**/#/stories');
  for (const width of [1920, 960]) {
    await page.setViewportSize({ width, height: 720 });
    await page.goto(ui + '/#/personas');
    const compactMain = page.locator('[data-slot=compact-main-sidebar]');
    await compactMain.waitFor();
    assert.equal(Math.round((await compactMain.boundingBox()).width), 48);
    const openMain = compactMain.getByRole('button', { name: 'Toggle Sidebar' });
    assert.equal(await openMain.locator('.lucide-panel-left-open').count(), 1);
    assert.equal(await openMain.locator('img').count(), 0);
    assert.equal(await page.getByRole('heading', { name: 'Saved voices', exact: true }).count(), 1);
    if (width === 1920) {
      await openMain.click();
      await compactMain.waitFor({ state: 'detached' });
      const expandedMain = page.locator('.brand-sidebar').filter({ hasText: 'Saved voices' });
      await expandedMain.waitFor();
      await expandedMain.getByRole('button', { name: 'Close' }).click();
      await compactMain.waitFor();
    }
  }
  console.log(
    'Sidebar compact/expanded, 9 destinations, 6 engine links, visible models, non-duplicated Profiles, settings visibility and navigation passed. ' +
      out,
  );
} finally {
  await browser.close();
  if (process.env.VOICESTUDIO_KEEP_SMOKE_ARTIFACTS !== '1') {
    rmSync(out, { recursive: true, force: true });
  }
}
