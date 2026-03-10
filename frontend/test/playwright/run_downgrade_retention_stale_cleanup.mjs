import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';
import {
  cleanupFixture,
  createCustomToken,
  createHybridEmailUser,
  deleteCurrentUserHarness,
  deleteUserByInitialToken,
  readFixtureState,
  seedStaleProRetentionFixture,
  signInWithCustomTokenHarness,
  signOutHarness,
} from './helpers/downgradeFixture.mjs';

const baseUrl = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5173';
const artifactDir = path.resolve(process.cwd(), 'output/playwright');
const screenshotPath = path.join(artifactDir, 'downgrade-retention-stale-cleanup.png');
const summaryPath = path.join(artifactDir, 'downgrade-retention-stale-cleanup.json');

function sleep(durationMs) {
  return new Promise((resolve) => setTimeout(resolve, durationMs));
}

async function retry(label, attempts, fn) {
  let lastError = null;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await fn(attempt);
    } catch (error) {
      lastError = error;
      if (attempt >= attempts) break;
      console.warn(`[playwright] ${label} attempt ${attempt} failed: ${error instanceof Error ? error.message : String(error)}`);
      await sleep(1500);
    }
  }
  throw lastError instanceof Error ? lastError : new Error(String(lastError));
}

async function main() {
  fs.mkdirSync(artifactDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1200 } });

  let userFixture = null;
  let fixtureUid = null;

  try {
    await page.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
    userFixture = await createHybridEmailUser(page);
    fixtureUid = userFixture.uid;
    seedStaleProRetentionFixture({ uid: fixtureUid, email: userFixture.email });

    const customToken = createCustomToken(fixtureUid);
    await signInWithCustomTokenHarness(page, customToken);
    await page.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });

    const state = await retry('verify stale retention cleanup', 10, async () => {
      if (await page.getByText('Downgraded account retention').isVisible().catch(() => false)) {
        throw new Error('Stale retention dialog should not render for an active Pro account.');
      }
      const current = readFixtureState(fixtureUid);
      if (current.role !== 'pro') {
        throw new Error(`Expected role to remain pro while clearing stale retention, found ${current.role}`);
      }
      if (current.subscriptionStatus !== 'active') {
        throw new Error(`Expected active subscription status, found ${current.subscriptionStatus}`);
      }
      if (current.retention !== null && current.retention !== undefined) {
        throw new Error(`Stale retention should be cleared after profile load: ${JSON.stringify(current.retention)}`);
      }
      return current;
    });

    await page.screenshot({ path: screenshotPath, fullPage: true });
    const summary = {
      ok: true,
      uid: fixtureUid,
      email: userFixture.email,
      state,
      screenshotPath,
    };
    fs.writeFileSync(summaryPath, JSON.stringify(summary, null, 2));
    console.log(JSON.stringify({ ok: true, screenshotPath, summaryPath, uid: fixtureUid }));
  } finally {
    if (userFixture) {
      try {
        await deleteCurrentUserHarness(page);
      } catch {
        try {
          await deleteUserByInitialToken(page, userFixture.apiKey, userFixture.initialIdToken);
        } catch {}
      }
      try {
        await signOutHarness(page);
      } catch {}
    }
    if (fixtureUid) {
      try {
        cleanupFixture(fixtureUid);
      } catch (error) {
        console.warn(`[playwright] cleanup failed for ${fixtureUid}: ${error instanceof Error ? error.message : String(error)}`);
      }
    }
    await page.close();
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack || error.message : String(error));
  process.exitCode = 1;
});
