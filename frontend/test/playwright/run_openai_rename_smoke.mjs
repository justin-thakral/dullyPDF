import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { chromium } from 'playwright';
import {
  createCustomToken,
  createHybridEmailUser,
  deleteCurrentUserHarness,
  deleteUserByInitialToken,
  signInWithCustomTokenHarness,
  signOutHarness,
} from './helpers/downgradeFixture.mjs';
import {
  buildMockRenameResult,
  collectFieldNames,
  parseJsonPostData,
  pollOpenAiJob,
  repoRoot,
  retry,
  setGodRole,
  uploadFillablePdfAndWaitForEditor,
} from './helpers/workspaceFixture.mjs';

const baseUrl = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5173';
const apiBaseUrl = (process.env.PLAYWRIGHT_API_URL || 'http://127.0.0.1:8000').replace(/\/+$/, '');
const artifactDir = path.resolve(process.cwd(), 'output/playwright');
const screenshotPath = path.join(artifactDir, 'openai-rename-smoke.png');
const summaryPath = path.join(artifactDir, 'openai-rename-smoke.json');
const mockExpensiveAi = /^true$/i.test(process.env.PLAYWRIGHT_MOCK_EXPENSIVE_AI || '');

function logStep(message) {
  console.log(`[openai-rename-real-flow] ${message}`);
}

function waitForLocalBackend() {
  execFileSync('bash', ['-lc', 'curl --silent --fail "$PW_API_BASE_URL/api/health" >/dev/null'], {
    cwd: repoRoot,
    env: { ...process.env, PW_API_BASE_URL: apiBaseUrl },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
}

async function main() {
  fs.mkdirSync(artifactDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1480, height: 1100 } });
  const capture = {
    renameKickoff: null,
    renameRequest: null,
    renameResult: null,
  };

  let userFixture = null;

  try {
    waitForLocalBackend();
    logStep('creating temporary Firebase user');
    await page.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
    userFixture = await createHybridEmailUser(page);
    logStep(`promoting ${userFixture.email} to god role`);
    setGodRole(userFixture.email);
    logStep('signing in with custom token');
    await signInWithCustomTokenHarness(page, createCustomToken(userFixture.uid));
    logStep('uploading real fillable PDF template');
    await uploadFillablePdfAndWaitForEditor(page, baseUrl);

    const initialFieldNames = await collectFieldNames(page);
    if (initialFieldNames.length === 0) {
      throw new Error('Expected at least one field to be visible before rename.');
    }

    logStep('opening rename confirmation and cancelling once');
    await page.getByRole('button', { name: /Rename or Remap/i }).click();
    await page.getByRole('menuitem', { name: 'Rename', exact: true }).click();
    await page.getByRole('dialog', { name: 'Send to OpenAI?' }).waitFor({ timeout: 10000 });
    await page.getByText('Row data and field input values are not sent.').waitFor({ timeout: 10000 });
    if (capture.renameResult !== null) {
      throw new Error('Rename should not call the backend before confirmation.');
    }

    await page.getByRole('button', { name: 'Cancel' }).click();
    await page.getByRole('dialog', { name: 'Send to OpenAI?' }).waitFor({ state: 'hidden', timeout: 10000 });
    if (capture.renameResult !== null) {
      throw new Error('Rename cancel should not call the backend.');
    }

    logStep('running real OpenAI rename');
    await page.getByRole('button', { name: /Rename or Remap/i }).click();
    await page.getByRole('menuitem', { name: 'Rename', exact: true }).click();
    await page.getByRole('dialog', { name: 'Send to OpenAI?' }).waitFor({ timeout: 10000 });
    if (mockExpensiveAi) {
      logStep('mocking expensive OpenAI rename request');
      await page.route('**/api/renames/ai', async (route) => {
        const renameRequest = parseJsonPostData(route.request());
        const templateFields = Array.isArray(renameRequest?.templateFields) ? renameRequest.templateFields : [];
        const renameResult = buildMockRenameResult(templateFields);
        capture.renameRequest = renameRequest;
        capture.renameKickoff = renameResult;
        capture.renameResult = renameResult;
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(renameResult),
        });
      }, { times: 1 });
    }
    const renameResponsePromise = page.waitForResponse((response) => {
      return response.request().method() === 'POST'
        && response.url().includes('/api/renames/ai')
        && response.ok();
    }, { timeout: 120000 });
    await page.getByRole('button', { name: 'Continue' }).click();
    const renameResponse = await renameResponsePromise;
    capture.renameKickoff = await renameResponse.json();
    capture.renameRequest = parseJsonPostData(renameResponse);
    if (
      capture.renameKickoff?.success
      && Array.isArray(capture.renameKickoff?.fields)
      && capture.renameKickoff.fields.length > 0
    ) {
      capture.renameResult = capture.renameKickoff;
    }

    if (!capture.renameKickoff?.success || !capture.renameRequest?.sessionId) {
      throw new Error(`Rename kickoff payload was incomplete: ${JSON.stringify(capture.renameKickoff)}`);
    }
    if (!capture.renameResult && capture.renameKickoff?.jobId) {
      capture.renameResult = await pollOpenAiJob(page, {
        apiBaseUrl,
        resource: 'renames',
        jobId: String(capture.renameKickoff.jobId),
      });
    }
    if (!capture.renameResult) {
      throw new Error(`Rename did not produce a final payload. Kickoff: ${JSON.stringify(capture.renameKickoff)}`);
    }

    if (!capture.renameRequest?.sessionId) {
      throw new Error(`Rename request should include a sessionId. Payload: ${JSON.stringify(capture.renameRequest)}`);
    }
    if (!Array.isArray(capture.renameRequest?.templateFields) || capture.renameRequest.templateFields.length === 0) {
      throw new Error(`Rename request should include templateFields. Payload: ${JSON.stringify(capture.renameRequest)}`);
    }
    if (!Array.isArray(capture.renameResult?.fields) || capture.renameResult.fields.length === 0) {
      throw new Error(`Rename response should include renamed fields. Payload: ${JSON.stringify(capture.renameResult)}`);
    }
    const renamedFieldNames = capture.renameResult.fields
      .map((field) => String(field?.name || '').trim())
      .filter(Boolean);
    if (renamedFieldNames.length === 0) {
      throw new Error(`Rename response contained no usable field names. Payload: ${JSON.stringify(capture.renameResult)}`);
    }

    const finalFieldNames = await retry('wait for renamed field names in the editor', 40, async () => {
      const names = await collectFieldNames(page);
      if (names.length === 0) {
        throw new Error('Waiting for visible field names after rename.');
      }
      const visibleRenameMatch = names.some((name) => renamedFieldNames.includes(name));
      if (!visibleRenameMatch) {
        throw new Error(`Waiting for renamed field names to appear in the editor. Visible names: ${JSON.stringify(names.slice(0, 8))}`);
      }
      return names;
    });

    await page.screenshot({ path: screenshotPath, fullPage: true });

    const summary = {
      ok: true,
      screenshotPath,
      summaryPath,
      mockExpensiveAi,
      userEmail: userFixture.email,
      initialFieldCount: initialFieldNames.length,
      finalFieldCount: finalFieldNames.length,
      renamedFieldCount: renamedFieldNames.length,
      renameRequestSessionId: capture.renameRequest.sessionId,
      renameRequestFieldCount: capture.renameRequest.templateFields.length,
      checkboxRuleCount: Array.isArray(capture.renameResult.checkboxRules) ? capture.renameResult.checkboxRules.length : 0,
      renamedFieldsSample: renamedFieldNames.slice(0, 8),
    };
    fs.writeFileSync(summaryPath, JSON.stringify(summary, null, 2));
    console.log(JSON.stringify(summary));
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
    await page.close();
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack || error.message : String(error));
  process.exitCode = 1;
});
