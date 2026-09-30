import { defineConfig } from '@playwright/test';
import fs from 'fs';
import os from 'os';
import path from 'path';

// Browser e2e for the admin/user/team flows runs against a running deployment.
// Default target is the local Docker stack (`http://127.0.0.1:8080`).
// Env: E2E_BASE_URL, E2E_ADMIN_EMAIL, E2E_ADMIN_PASSWORD (required), CHROMIUM_PATH.
function findChromium(): string {
  if (process.env.CHROMIUM_PATH) return process.env.CHROMIUM_PATH;
  const cache = path.join(os.homedir(), '.cache', 'ms-playwright');
  try {
    // Newest revision wins; binary lives in chrome-linux/ or chrome-linux64/.
    const dirs = fs.readdirSync(cache).filter((d) => /^chromium-\d+$/.test(d)).sort((a, b) => Number(b.split('-')[1]) - Number(a.split('-')[1]));
    for (const d of dirs)
      for (const sub of ['chrome-linux64', 'chrome-linux']) {
        const bin = path.join(cache, d, sub, 'chrome');
        if (fs.existsSync(bin)) return bin;
      }
  } catch { /* cache missing */ }
  return 'chromium';
}

export default defineConfig({
  testDir: './e2e',
  outputDir: './e2e/.output',
  timeout: 30_000,
  workers: 1,
  reporter: [['list'], ['html', { outputFolder: 'e2e/report', open: 'never' }]],
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://127.0.0.1:8080',
    headless: true,
    viewport: { width: 1440, height: 900 },
    screenshot: 'only-on-failure',
    launchOptions: { executablePath: findChromium() },
  },
});
