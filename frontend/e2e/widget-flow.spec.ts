import { expect, test, type APIRequestContext } from '@playwright/test';
import { mkdirSync } from 'node:fs';

// End-to-end *example* that drives the real UI against the live stack and the
// real Copilot agent. It demonstrates the tools → permissions → widgets flow:
// a prompt makes Papa call the gated `delete` tool, which emits a permission
// widget that blocks the composer until the user answers (here: Deny).
//
// Requires the stack to be up (Vite :5173, backend :8000, Docker infra) and the
// local Copilot login active. Run with:  npm run e2e

const ADMIN = { 'X-User-Name': 'admin', 'X-User-Key': 'admin' };
const SEED_PATH = ['mongodb', 'default', 'app', 'users', 'u1'];
const SHOTS = 'playwright-artifacts';

mkdirSync(SHOTS, { recursive: true });

// Seed a datum (idempotent) so there is a concrete resource for Papa to delete.
async function seed(request: APIRequestContext) {
  const api = 'http://localhost:8000';
  const post = (path: string, data: unknown) =>
    request.post(`${api}${path}`, { headers: ADMIN, data });
  await post('/resources/db', { engine: 'mongodb', name: 'default' });
  await post('/resources', { parent_path: ['mongodb', 'default'], name: 'app' });
  await post('/resources', {
    parent_path: ['mongodb', 'default', 'app'],
    name: 'users',
  });
  await post('/resources', {
    parent_path: ['mongodb', 'default', 'app', 'users'],
    name: 'u1',
    data: { name: 'Ada', role: 'admin' },
  });
}

test('permission widget gates the delete tool', async ({ page, request }) => {
  await seed(request);

  // 1. Sign in (the form defaults to admin / admin).
  await page.goto('/');
  await page.getByRole('button', { name: 'Sign in' }).click();

  // 2. Create a project. The directory picker auto-selects home, so Create is
  //    enabled immediately.
  await page.getByRole('button', { name: '+ New Project' }).click();
  await page.getByPlaceholder('My project').fill('Widget Demo');
  await expect(page.getByRole('button', { name: 'Create' })).toBeEnabled();
  await page.getByRole('button', { name: 'Create' }).click();

  // 3. Prompt Papa to call the gated delete tool on the seeded resource.
  const composer = page.getByPlaceholder(/Send a message/);
  await expect(composer).toBeVisible();
  await composer.fill(
    `Call the delete tool now on the resource at the exact path ${SEED_PATH.join(
      '/',
    )}. Do not call any other tool first.`,
  );
  await composer.press('Enter');

  // 4. The permission widget appears and blocks the composer.
  const widget = page.locator('.widget--permission');
  await expect(widget).toBeVisible({ timeout: 90_000 });
  await expect(widget).toContainText('Permission required');
  await expect(composer).toBeDisabled();
  await page.screenshot({
    path: `${SHOTS}/01-permission-widget.png`,
    fullPage: true,
  });

  // 5. Deny — the tool aborts, the widget clears, and the turn finishes.
  await widget.getByRole('button', { name: 'Deny' }).click();
  await expect(widget).toBeHidden();
  await page.screenshot({ path: `${SHOTS}/02-after-deny.png`, fullPage: true });

  // The seeded resource still exists because we denied the delete.
  const check = await request.get(
    `http://localhost:8000/resources/data/${SEED_PATH.join('/')}`,
    { headers: ADMIN },
  );
  expect(check.ok()).toBeTruthy();
});
