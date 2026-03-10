import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';

const baseUrl = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5173';
const artifactDir = path.resolve(process.cwd(), 'output/playwright');
const screenshotPath = path.join(artifactDir, 'workspace-zoom-smoke.png');

const authEmail = process.env.PLAYWRIGHT_USER_EMAIL || '';
const authPassword = process.env.PLAYWRIGHT_USER_PASSWORD || '';

async function retry(label, attempts, fn) {
  let lastError = null;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await fn(attempt);
    } catch (error) {
      lastError = error;
      if (attempt >= attempts) {
        break;
      }
      console.warn(`[playwright] ${label} attempt ${attempt} failed: ${error instanceof Error ? error.message : String(error)}`);
      await new Promise((resolve) => setTimeout(resolve, 1500));
    }
  }
  throw lastError instanceof Error ? lastError : new Error(String(lastError));
}

async function signInIfConfigured(page) {
  if (!authEmail || !authPassword) {
    return { signedIn: false };
  }

  await retry('sign in', 3, async () => {
    await page.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.getByRole('button', { name: 'Sign in' }).first().click();
    await page.getByLabel('Email').fill(authEmail);
    await page.getByLabel('Password').fill(authPassword);
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    await page.getByRole('button', { name: 'Sign out' }).waitFor({ timeout: 20000 });
  });

  return { signedIn: true };
}

async function openDemo(page) {
  await retry('open demo', 3, async () => {
    await page.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.getByRole('button', { name: 'Demo', exact: true }).click();
    await page.getByText('Form Field Editor').waitFor({ timeout: 30000 });
    await page.locator('[data-page-number="1"]').waitFor({ timeout: 30000 });
  });
}

async function setZoom(page, nextScale) {
  await page.locator('input[aria-label="Zoom"]').evaluate((element, value) => {
    const input = element;
    const valueSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
    valueSetter?.call(input, String(value));
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }, nextScale);
  await page.locator('input[aria-label="Zoom"]').evaluate((element, expectedValue) => {
    if (element.value !== String(expectedValue)) {
      throw new Error(`Zoom slider did not update to ${expectedValue}. Current value: ${element.value}`);
    }
  }, nextScale);
  await page.locator('.ui-chip--slider .ui-chip__value').filter({ hasText: `${Math.round(nextScale * 100)}%` }).first().waitFor({ timeout: 10000 });
}

async function main() {
  fs.mkdirSync(artifactDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1200 } });

  try {
    const auth = await signInIfConfigured(page);
    await openDemo(page);

    const firstPage = page.locator('[data-page-number="1"]').first();
    const widthBefore = await firstPage.evaluate((element) => element.getBoundingClientRect().width);

    await setZoom(page, 2);
    const widthZoomedIn = await firstPage.evaluate((element) => element.getBoundingClientRect().width);

    await setZoom(page, 0.5);
    const widthZoomedOut = await firstPage.evaluate((element) => element.getBoundingClientRect().width);

    if (!(widthZoomedIn > widthBefore * 1.5)) {
      throw new Error(`Expected zoom-in width to grow materially. before=${widthBefore}, after=${widthZoomedIn}`);
    }
    if (!(widthZoomedOut < widthBefore * 0.75)) {
      throw new Error(`Expected zoom-out width to shrink materially. before=${widthBefore}, after=${widthZoomedOut}`);
    }

    await page.screenshot({ path: screenshotPath, fullPage: true });

    console.log(JSON.stringify({
      ok: true,
      signedIn: auth.signedIn,
      screenshotPath,
      widthBefore,
      widthZoomedIn,
      widthZoomedOut,
    }));
  } finally {
    await page.close();
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack || error.message : String(error));
  process.exitCode = 1;
});
