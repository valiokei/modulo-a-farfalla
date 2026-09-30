import { test, expect, type Page } from '@playwright/test';

// Team logos: upload -> visible crest -> remove -> initials fallback.
// Runs against the deployed stack; TeamManager is coach-only, so a throwaway
// coach account drives the UI. All created rows are removed again.
// Env: E2E_BASE_URL, E2E_ADMIN_EMAIL, E2E_ADMIN_PASSWORD.
const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL || 'admin@example.com';
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || 'change-me-now';
const stamp = Date.now();
const coachEmail = `e2e.coach.${stamp}@touchline.local`;
const coachPassword = 'e2ecoach123';
const teamName = `E2E Logo FC ${stamp}`;
const PNG_1PX = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg==', 'base64');

test.describe('team logos', () => {
  let coachId = '';
  let teamId = '';

  test.beforeAll(async ({ request }) => {
    expect((await request.post('/api/auth/login', { data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD } })).ok()).toBeTruthy();
    const coach = await (await request.post('/api/users', { data: { email: coachEmail, password: coachPassword, role: 'coach', name: 'E2E Logo Coach' } })).json();
    coachId = coach.id;
  });

  test.afterAll(async ({ request }) => {
    if (!(await request.post('/api/auth/login', { data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD } })).ok()) return;
    if (teamId) await request.delete(`/api/teams/${teamId}`);           // also purges the logo file
    if (coachId) await request.delete(`/api/users/${coachId}`);
  });

  test('upload, render and remove a team logo', async ({ page, request }) => {
    // coach session for team creation (API) and UI below
    expect((await request.post('/api/auth/login', { data: { email: coachEmail, password: coachPassword } })).ok()).toBeTruthy();
    teamId = (await (await request.post('/api/teams', { data: { name: teamName } })).json()).id;

    await page.goto('/');
    await page.locator('.login input[type=email]').fill(coachEmail);
    await page.locator('.login input[type=password]').fill(coachPassword);
    await page.locator('.login form button.primary').click();
    await expect(page.locator('.matchGrid, .empty')).toBeVisible({ timeout: 8000 });

    // Teams section -> select the throwaway team.
    await page.locator('.mainNav button', { hasText: /squadre|teams/i }).click();
    await page.locator('.teamList button', { hasText: teamName }).click();

    // Initial state: initials avatar, no crest.
    await expect(page.locator('.teamDetailHead span.teamAvatar')).toBeVisible();

    const failures: string[] = [];
    page.on('response', (r) => { if (r.url().includes('/api/teams') && r.status() >= 400) failures.push(`${r.request().method()} ${r.url()} -> ${r.status()}`); });

    // Upload through the hidden file input behind "Carica logo".
    await page.locator('.teamDetail input[type=file]').setInputFiles({ name: 'logo.png', mimeType: 'image/png', buffer: PNG_1PX });
    const crest = page.locator('.teamDetailHead img.teamLogo');
    await expect(crest).toBeVisible({ timeout: 8000 });
    await expect.poll(() => crest.evaluate((el) => (el as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
    await page.screenshot({ path: 'e2e/.output/03-team-logo-uploaded.png' });
    expect(failures, `team API failures: ${failures.join(', ')}`).toEqual([]);

    // The crest is also served authenticated (the <img> used cookies).
    expect((await request.get(`/api/teams/${teamId}/logo`)).status()).toBe(200);

    // Remove -> initials avatar returns.
    await page.locator('.teamDetail button', { hasText: /rimuovi logo|remove logo/i }).click();
    await expect(page.locator('.teamDetailHead img.teamLogo')).toHaveCount(0);
    await expect(page.locator('.teamDetailHead span.teamAvatar')).toBeVisible();

    // Delete the team through the UI (confirm dialog) and check the row is gone.
    page.once('dialog', (d) => d.accept());
    await page.locator('.teamDetail button', { hasText: /delete|elimina/i }).click();
    await expect(page.locator('.teamList button', { hasText: teamName })).toHaveCount(0);
    teamId = '';
  });
});
