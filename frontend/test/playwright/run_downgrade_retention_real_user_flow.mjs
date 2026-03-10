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
  seedDowngradedAccountFixture,
  signInWithCustomTokenHarness,
  signOutHarness,
} from './helpers/downgradeFixture.mjs';

const baseUrl = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5173';
const artifactDir = path.resolve(process.cwd(), 'output/playwright');
const screenshotPath = path.join(artifactDir, 'downgrade-retention-real-user.png');
const summaryPath = path.join(artifactDir, 'downgrade-retention-real-user.json');

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

async function waitForRetentionDialog(page) {
  await retry('wait for retention dialog', 3, async () => {
    await page.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.getByText('Downgraded account retention').waitFor({ timeout: 30000 });
    await page.getByText('3 of 3 selected').waitFor({ timeout: 10000 });
  });
}

function retentionDialog(page) {
  return page.getByLabel('Downgraded account retention');
}

async function setTemplateChecked(page, templateName, checked) {
  await page.evaluate(({ name, nextChecked }) => {
    const rows = Array.from(document.querySelectorAll('.retention-dialog__template'));
    const row = rows.find((entry) => entry.textContent?.includes(name));
    if (!(row instanceof HTMLLabelElement)) {
      throw new Error(`Missing retention template row for ${name}`);
    }
    const checkbox = row.querySelector('input[type="checkbox"]');
    if (!(checkbox instanceof HTMLInputElement)) {
      throw new Error(`Missing checkbox for ${name}`);
    }
    if (checkbox.checked !== nextChecked) {
      row.click();
    }
  }, { name: templateName, nextChecked: checked });
}

async function waitForEnabled(locator, label) {
  await retry(`wait for enabled ${label}`, 10, async () => {
    if (!(await locator.isEnabled())) {
      throw new Error(`${label} is still disabled.`);
    }
  });
}

async function assertNoRetentionDialog(page) {
  await sleep(2500);
  if (await page.getByText('Downgraded account retention').isVisible().catch(() => false)) {
    throw new Error('Retention dialog should not be visible.');
  }
}

async function main() {
  fs.mkdirSync(artifactDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1400 } });

  let userFixture = null;
  let fixtureUid = null;

  try {
    await page.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
    userFixture = await createHybridEmailUser(page);
    fixtureUid = userFixture.uid;
    const seeded = seedDowngradedAccountFixture({ uid: fixtureUid, email: userFixture.email });
    const customToken = createCustomToken(fixtureUid);

    await signInWithCustomTokenHarness(page, customToken);
    await waitForRetentionDialog(page);

    await page.getByText('Days left').waitFor({ timeout: 10000 });
    await page.getByText('Groups affected').waitFor({ timeout: 10000 });
    await page.getByText('Links pending delete').waitFor({ timeout: 10000 });

    const dialog = retentionDialog(page);
    await setTemplateChecked(page, 'Referral Gamma', false);
    await setTemplateChecked(page, 'Follow Up Delta', true);
    const saveButton = dialog.getByRole('button', { name: 'Save kept forms' });
    await waitForEnabled(saveButton, 'Save kept forms');
    await saveButton.click();

    const afterSave = await retry('verify saved retention selection', 10, async () => {
      const state = readFixtureState(fixtureUid);
      const keptAfterSave = state.retention?.kept_template_ids || [];
      const pendingAfterSave = state.retention?.pending_delete_template_ids || [];
      if (!keptAfterSave.includes(`${fixtureUid}-tpl-delta`) || keptAfterSave.includes(`${fixtureUid}-tpl-gamma`)) {
        throw new Error(`Unexpected kept template ids after save: ${JSON.stringify(keptAfterSave)}`);
      }
      if (pendingAfterSave.join('|') !== `${fixtureUid}-tpl-gamma`) {
        throw new Error(`Unexpected pending template ids after save: ${JSON.stringify(pendingAfterSave)}`);
      }
      if ((state.retention?.pending_delete_link_ids || []).includes(`${fixtureUid}-link-delta`)) {
        throw new Error(`Delta link should not stay in the pending delete queue: ${JSON.stringify(state.retention?.pending_delete_link_ids || [])}`);
      }
      const deltaLink = state.links.find((link) => link.id === `${fixtureUid}-link-delta`);
      if (!deltaLink || deltaLink.status !== 'closed' || deltaLink.closedReason !== 'downgrade_link_limit') {
        throw new Error(`Expected delta link to stay closed under the free active-link limit after being kept: ${JSON.stringify(deltaLink)}`);
      }
      return state;
    });

    await dialog.getByRole('button', { name: 'Delete now' }).click();
    await page.getByRole('button', { name: 'Delete queued data' }).click();

    const afterDelete = await retry('verify delete-now retention purge', 10, async () => {
      const state = readFixtureState(fixtureUid);
      if (state.retention !== null && state.retention !== undefined) {
        throw new Error(`Retention should be cleared after delete-now: ${JSON.stringify(state.retention)}`);
      }
      if (state.templates.length !== 3) {
        throw new Error(`Expected 3 templates after delete-now, found ${state.templates.length}`);
      }
      if (state.templates.some((template) => template.id === `${fixtureUid}-tpl-gamma`)) {
        throw new Error('Queued template still exists after delete-now.');
      }
      const linkLimitClosure = state.links.find((link) => link.id === `${fixtureUid}-link-beta`);
      if (!linkLimitClosure || linkLimitClosure.status !== 'closed' || linkLimitClosure.closedReason !== 'downgrade_link_limit') {
        throw new Error(`Expected beta link to stay closed for the free active-link limit: ${JSON.stringify(linkLimitClosure)}`);
      }
      const keptDeltaLink = state.links.find((link) => link.id === `${fixtureUid}-link-delta`);
      if (!keptDeltaLink || keptDeltaLink.status !== 'closed' || keptDeltaLink.closedReason !== 'downgrade_link_limit') {
        throw new Error(`Expected kept delta link to remain closed for the free active-link limit: ${JSON.stringify(keptDeltaLink)}`);
      }
      return state;
    });
    await assertNoRetentionDialog(page);

    await page.screenshot({ path: screenshotPath, fullPage: true });

    const summary = {
      ok: true,
      uid: fixtureUid,
      email: userFixture.email,
      initialRetention: seeded.summary,
      afterSave,
      afterDelete,
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
