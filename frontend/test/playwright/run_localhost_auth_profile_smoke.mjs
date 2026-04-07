import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';
import { signInFromHomepageAndOpenProfile } from './helpers/workspaceFixture.mjs';

const baseUrl = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5173';
const artifactDir = path.resolve(process.cwd(), 'output/playwright');
const screenshotPath = path.join(artifactDir, 'localhost-auth-profile-smoke.png');
const summaryPath = path.join(artifactDir, 'localhost-auth-profile-smoke.json');
const loginEmail = (process.env.SMOKE_LOGIN_EMAIL || process.env.PLAYWRIGHT_LOGIN_EMAIL || '').trim();
const loginPassword = process.env.SMOKE_LOGIN_PASSWORD || process.env.PLAYWRIGHT_LOGIN_PASSWORD || '';

function logStep(message) {
  console.log(`[localhost-auth-profile-smoke] ${message}`);
}

async function main() {
  fs.mkdirSync(artifactDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
  const results = {
    ok: false,
    baseUrl,
    screenshotPath,
    summaryPath,
    apiEvents: [],
  };

  try {
    page.on('response', async (response) => {
      const url = response.url();
      if (!url.includes('/api/') && !url.includes('identitytoolkit.googleapis.com')) {
        return;
      }
      results.apiEvents.push({
        url,
        status: response.status(),
        method: response.request().method(),
      });
    });

    await signInFromHomepageAndOpenProfile(page, {
      baseUrl,
      loginEmail,
      loginPassword,
      logStep,
    });

    const heroTitle = await page.getByRole('heading', { level: 1 }).textContent();
    results.ok = true;
    results.profileTitle = heroTitle?.trim() || null;
    results.currentUrl = page.url();

    await page.screenshot({ path: screenshotPath, fullPage: true });
  } catch (error) {
    results.error = error instanceof Error ? error.message : String(error);
    results.currentUrl = page.url();
    results.pageTitle = await page.title().catch(() => null);
    results.bodySnippet = await page.locator('body').textContent().catch(() => null);
    await page.screenshot({ path: screenshotPath, fullPage: true }).catch(() => {});
    console.error(error instanceof Error ? error.stack || error.message : String(error));
  } finally {
    fs.writeFileSync(summaryPath, JSON.stringify(results, null, 2));
    await page.close();
    await browser.close();
  }

  console.log(JSON.stringify(results, null, 2));
  if (!results.ok) {
    process.exitCode = 1;
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack || error.message : String(error));
  process.exitCode = 1;
});
