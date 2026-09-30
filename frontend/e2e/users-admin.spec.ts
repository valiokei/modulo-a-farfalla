import { test, expect, type Page } from '@playwright/test';

// End-to-end coverage for the reported bug: editing a user (add team + set
// display name + change password) returned a 422 that the SPA showed as
// "[object Object]". Root cause: a sub-8-char password failed Pydantic's
// min_length and FastAPI's default 422 body carries detail as an object list.
// These run against the deployed stack (see playwright.config.ts).
// Env: E2E_BASE_URL, E2E_ADMIN_EMAIL, E2E_ADMIN_PASSWORD.
const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL || 'admin@example.com';
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || 'change-me-now';

async function login(page: Page, email: string, password: string) {
  await page.goto('/');
  await page.locator('.login input[type=email]').fill(email);
  await page.locator('.login input[type=password]').fill(password);
  await page.locator('.login form button.primary').click();
  await expect(page.locator('.userTable')).toBeVisible({ timeout: 8000 });
}

function rowFor(page: Page, text: string) {
  return page.locator('.userTable .playerRow', { hasText: text });
}

async function createUser(page: Page, data: { name: string; email: string; password: string; role?: string; teamIndex?: number }) {
  await page.locator('.libraryTop button.primary').click();
  await page.waitForSelector('.modal form');
  const modal = page.locator('.modal form');
  await modal.locator('input').nth(0).fill(data.name);
  await modal.locator('input[type=email]').fill(data.email);
  await modal.locator('input[type=password]').fill(data.password);
  if (data.role) await modal.locator('select').nth(0).selectOption(data.role);
  if (data.teamIndex !== undefined) await modal.locator('select').nth(1).selectOption({ index: data.teamIndex });
  await modal.locator('button.primary').click();
  await expect(rowFor(page, data.email)).toBeVisible({ timeout: 8000 });
}

test.describe('admin user console', () => {
  const stamp = Date.now();
  const emailA = `e2e.a.${stamp}@touchline.local`;
  const emailB = `e2e.b.${stamp}@touchline.local`;

  // Self-healing: drop leftover users from previous failed runs (unique e2e domain).
  test.beforeAll(async ({ request }) => {
    if (!(await request.post('/api/auth/login', { data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD } })).ok()) return;
    for (const u of await (await request.get('/api/users')).json())
      if (/^e2e\..*@touchline\.local$/.test(u.email)) await request.delete(`/api/users/${u.id}`);
  });

  async function removeUser(page: Page, email: string) {
    await rowFor(page, email).locator('button.danger').click();
    await page.waitForSelector('.modal');
    await page.locator('.modal button.danger').click();
    await expect(rowFor(page, email)).toHaveCount(0);
  }

  test('edit display name + team + valid password persists and login works', async ({ page, request }) => {
    await login(page, ADMIN_EMAIL, ADMIN_PASSWORD);
    await createUser(page, { name: 'E2E Before', email: emailA, password: 'seedpass123', role: 'coach' });

    const failures: string[] = [];
    page.on('response', (r) => { if (r.url().includes('/api/users') && r.status() >= 400) failures.push(`${r.request().method()} -> ${r.status()}`); });

    // The reported scenario, valid version: display name + team + new password in one save.
    await rowFor(page, emailA).locator('.rowActions button').first().click();
    await page.waitForSelector('.modal form');
    const modal = page.locator('.modal form');
    await modal.locator('input').nth(0).fill('E2E After');
    await modal.locator('select').nth(1).selectOption({ index: 1 });
    await modal.locator('input[type=password]').fill('newsecret123');
    await modal.locator('button.primary').click();
    await expect(rowFor(page, 'E2E After')).toBeVisible({ timeout: 8000 });
    expect(failures, `unexpected user API failures: ${failures.join(', ')}`).toEqual([]);
    await page.screenshot({ path: 'e2e/.output/01-edited-user-row.png' });

    // The new password is live (checked through the API, separate context).
    expect((await request.post('/api/auth/login', { data: { email: emailA, password: 'newsecret123' } })).status()).toBe(200);
    expect((await request.post('/api/auth/login', { data: { email: emailA, password: 'seedpass123' } })).status()).toBe(401);

    await removeUser(page, emailA);
  });

  test('sub-8-char password shows a readable inline error and never reaches the API', async ({ page }) => {
    await login(page, ADMIN_EMAIL, ADMIN_PASSWORD);
    await createUser(page, { name: 'E2E Pw', email: emailB, password: 'seedpass123', role: 'coach' });

    let patched = false;
    page.on('request', (r) => { if (r.method() === 'PATCH' && r.url().includes('/api/users')) patched = true; });

    await rowFor(page, emailB).locator('.rowActions button').first().click();
    await page.waitForSelector('.modal form');
    const modal = page.locator('.modal form');
    await modal.locator('input[type=password]').fill('short');

    // Inline localized error appears while typing (both locales mention "8").
    await expect(modal.locator('.error')).toContainText('8');
    await page.screenshot({ path: 'e2e/.output/02-short-password-inline-error.png' });

    await modal.locator('button.primary').click();
    await page.waitForTimeout(400);
    expect(patched, 'no PATCH should be issued for a sub-8-char password').toBe(false);
    await expect(page.locator('.modal')).toBeVisible();

    await page.locator('.modal button.ghost').click();
    await removeUser(page, emailB);
  });

  test('API 422 detail is a readable string, not an object list', async ({ request }) => {
    // Regression for "[object Object]": Pydantic-level validation errors must
    // arrive as {detail:"<text>"} so the SPA can render them.
    expect((await request.post('/api/auth/login', { data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD } })).ok()).toBeTruthy();
    const users = await (await request.get('/api/users')).json();
    const me = users.find((u: any) => u.email === ADMIN_EMAIL.toLowerCase());
    const bad = await request.patch(`/api/users/${me.id}`, { data: { password: 'short' } });
    expect(bad.status()).toBe(422);
    const detail = (await bad.json()).detail;
    expect(typeof detail).toBe('string');
    expect(detail).toContain('password');
    expect(detail).toContain('at least 8');
  });
});
