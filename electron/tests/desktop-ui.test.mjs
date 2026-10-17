import { test } from 'node:test';
import assert from 'node:assert/strict';
import { realpathSync } from 'node:fs';
import { withApp } from './desktop-harness.mjs';
import { ROUTES } from './fixtures/routes.mjs';

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

test('first run: setup gate completes to home', async (t) => {
  await withApp(t, { seed: false }, async ({ page }) => {
    await page.getByRole('heading', { name: 'System check', exact: true }).first().waitFor();
    const next = page.getByRole('button', { name: /All good/ });
    // System check -> Model packs -> Privacy -> Enter studio
    for (const heading of ['Model packs', 'Privacy', 'Enter studio']) {
      await next.click();
      await page.getByRole('heading', { name: heading, exact: true }).first().waitFor();
    }
    await page.getByRole('button', { name: 'Enter studio', exact: true }).last().click();
    await page.getByRole('heading', { name: 'Home', exact: true }).waitFor();
    assert.equal(
      await page.evaluate(() => localStorage.getItem('voicestudio.setup.complete.v1')),
      '1',
    );
    assert.match(await page.evaluate(() => location.hash), /^(#\/?)?$/);
  });
});

test('consent: declining analytics keeps the app usable and sends nothing', async (t) => {
  const prompted = { available: true, prompted: false, opted_in: false };
  await withApp(
    t,
    { fixtures: { '/api/settings/analytics': prompted } },
    async ({ page, backend }) => {
      const yes = page.getByRole('button', { name: 'Yes, share anonymous stats', exact: true });
      const no = page.getByRole('button', { name: 'No thanks', exact: true });
      await yes.waitFor();
      assert.equal(await no.isVisible(), true, 'Both choices must carry equal weight');
      await no.click();
      await yes.waitFor({ state: 'detached' });
      const writes = backend.requests.filter(
        (r) => r.method === 'PUT' && r.path === '/api/settings/analytics',
      );
      assert.deepEqual(
        writes.map((r) => JSON.parse(r.body)),
        [{ enabled: false }],
      );
      await page.getByRole('heading', { name: 'Home', exact: true }).waitFor();
      // withApp's request guard fails the run if any analytics host was contacted.
    },
  );
});

test('backend down: app shows the connecting state without crashing', async (t) => {
  await withApp(t, { backend: 'down' }, async ({ page }) => {
    await page.getByText('Connecting to the running engine…').waitFor();
    assert.equal(await page.evaluate(() => typeof window.voicestudio?.files?.saveData), 'function');
  });
});

test('routes: every route renders', async (t) => {
  await withApp(t, {}, async ({ page, backend }) => {
    const crashed = [];
    for (const route of ROUTES) {
      await page.evaluate((path) => {
        location.hash = '#' + path;
      }, route);
      // A route may redirect (e.g. /settings -> /settings/general), so accept any hash that
      // still sits under the requested path.
      await page
        .waitForFunction((path) => location.hash.startsWith('#' + path), route, { timeout: 5000 })
        .catch(async () => {
          assert.fail(`Route ${route} settled on hash "${await page.evaluate(() => location.hash)}"`);
        });
      // A crashed route replaces the shell with the error boundary's alert.
      await page.locator('main, [role=alert]').first().waitFor();
      if (await page.getByText('This tab hit a snag.', { exact: true }).count()) {
        crashed.push(route);
        // The boundary outlives route changes; reload so later routes are judged on their own.
        await page.reload();
      }
    }
    assert.deepEqual(crashed, [], 'Routes rendered the error boundary');
    const missing = [
      ...new Set(backend.requests.filter((r) => r.status === 404).map((r) => `${r.method} ${r.path}`)),
    ];
    assert.deepEqual(missing, [], 'Routes requested backend paths the fake backend lacks');
  });
});

const insideProfile = (path, profile) => {
  const norm = (value) => {
    const real = realpathSync.native(value).normalize('NFC');
    return process.platform === 'win32' ? real.toLowerCase() : real;
  };
  return norm(path).startsWith(norm(profile));
};

test('settings: theme and language survive restart, user data stays in the profile', async (t) => {
  await withApp(t, {}, async (session) => {
    const { page, profile } = session;
    await page.evaluate(() => {
      location.hash = '#/settings/appearance';
    });
    const dark = page.getByRole('group', { name: 'Dark', exact: true });
    // Studio is the default palette, so pick the other one to make the change observable.
    const original = dark.getByRole('button', { name: 'VoiceStudio Original', exact: true });
    await original.click();
    await original.and(page.locator('[aria-pressed="true"]')).waitFor();

    await page.evaluate(() => {
      location.hash = '#/settings/general';
    });
    await page.getByRole('combobox', { name: 'Language', exact: true }).click();
    await page.getByRole('option', { name: 'Deutsch', exact: true }).click();
    await page.waitForFunction(() => localStorage.getItem('voicestudio.locale') === 'de');

    const paths = await session.app.evaluate(({ app }) => [
      app.getPath('userData'),
      app.getPath('sessionData'),
    ]);
    for (const path of paths) {
      assert.equal(insideProfile(path, profile), true, `${path} is outside ${profile}`);
    }

    const restarted = await session.relaunch();
    const saved = await restarted.page.evaluate(() => ({
      locale: localStorage.getItem('voicestudio.locale'),
      theme: JSON.parse(localStorage.getItem('voicestudio.theme.v2') || '{}'),
    }));
    assert.equal(saved.locale, 'de');
    assert.equal(saved.theme.dark, 'signal');
    await restarted.page.waitForFunction(() => document.documentElement.dataset.themeId === 'signal');
  });
});

test('unclean exit: relaunch on the same profile starts normally', async (t) => {
  await withApp(t, {}, async (session) => {
    session.app.process().kill('SIGKILL');
    const restarted = await session.relaunch();
    await restarted.page.waitForFunction(() => Boolean(window.voicestudio?.files?.saveData));
    const facts = await bridgeFacts(restarted.page);
    assert.equal(facts.platform, process.platform);
  });
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
