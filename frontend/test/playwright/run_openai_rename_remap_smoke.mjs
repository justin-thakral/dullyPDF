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
  buildMockMappingResult,
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
const screenshotPath = path.join(artifactDir, 'openai-rename-remap-smoke.png');
const summaryPath = path.join(artifactDir, 'openai-rename-remap-smoke.json');
const remapSamplePdfPath = path.join(
  repoRoot,
  'quickTestFiles/dentalintakeform_d1c394f594.pdf',
);
const mockExpensiveAi = /^true$/i.test(process.env.PLAYWRIGHT_MOCK_EXPENSIVE_AI || '');

function logStep(message) {
  console.log(`[openai-rename-remap-real-flow] ${message}`);
}

function waitForLocalBackend() {
  execFileSync('bash', ['-lc', 'curl --silent --fail "$PW_API_BASE_URL/api/health" >/dev/null'], {
    cwd: repoRoot,
    env: { ...process.env, PW_API_BASE_URL: apiBaseUrl },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
}

function buildSchemaFilePath() {
  const schemaPath = path.join(artifactDir, 'openai-rename-remap-schema.txt');
  fs.writeFileSync(
    schemaPath,
    [
      'full_name:string',
      'date:date',
      'signature_name:string',
      'phone:string',
      'email:string',
    ].join('\n'),
    'utf8',
  );
  return schemaPath;
}

async function main() {
  fs.mkdirSync(artifactDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1480, height: 1100 } });
  const schemaPath = buildSchemaFilePath();
  const capture = {
    schemaCreate: null,
    renameKickoff: null,
    renameRequest: null,
    renameResult: null,
    mappingKickoff: null,
    mappingRequest: null,
    mappingResult: null,
  };

  let userFixture = null;
  let results = {};
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
    await uploadFillablePdfAndWaitForEditor(page, baseUrl, remapSamplePdfPath);

    const initialFieldNames = await collectFieldNames(page);
    if (initialFieldNames.length === 0) {
      throw new Error('Expected visible fields before schema mapping.');
    }

    logStep('uploading real TXT schema');
    const schemaCreatePromise = page.waitForResponse((response) => {
      return response.request().method() === 'POST'
        && response.url().includes('/api/schemas')
        && response.ok();
    }, { timeout: 30000 });
    await page.getByLabel('Upload TXT schema file').setInputFiles(schemaPath);
    const schemaCreateResponse = await schemaCreatePromise;
    capture.schemaCreate = await schemaCreateResponse.json();
    if (!capture.schemaCreate?.schemaId) {
      throw new Error(`Schema upload did not return a schemaId: ${JSON.stringify(capture.schemaCreate)}`);
    }

    logStep('running real Rename + Map flow');
    await page.getByRole('button', { name: /Rename or Remap/i }).click();
    await page.getByRole('menuitem', { name: 'Rename + Map', exact: true }).click();
    await page.getByRole('dialog', { name: 'Send to OpenAI?' }).waitFor({ timeout: 10000 });
    if (mockExpensiveAi) {
      logStep('mocking expensive OpenAI rename + map requests');
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
      await page.route('**/api/schema-mappings/ai', async (route) => {
        const mappingRequest = parseJsonPostData(route.request());
        const templateFields = Array.isArray(mappingRequest?.templateFields) ? mappingRequest.templateFields : [];
        const mappingResult = buildMockMappingResult(templateFields);
        capture.mappingRequest = mappingRequest;
        capture.mappingKickoff = mappingResult;
        capture.mappingResult = mappingResult;
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(mappingResult),
        });
      }, { times: 1 });
    }
    const renameRequestPromise = page.waitForRequest((request) => {
      return request.method() === 'POST'
        && request.url().includes('/api/renames/ai');
    }, { timeout: 120000 });
    const mappingRequestPromise = page.waitForRequest((request) => {
      return request.method() === 'POST'
        && request.url().includes('/api/schema-mappings/ai');
    }, { timeout: 180000 });
    await page.getByRole('button', { name: 'Continue' }).click();

    const renameRequest = await renameRequestPromise;
    const renameResponse = await renameRequest.response();
    if (!renameResponse || !renameResponse.ok()) {
      const responseText = renameResponse ? await renameResponse.text() : 'missing response';
      throw new Error(`Rename kickoff request did not return a successful response: ${responseText}`);
    }
    capture.renameKickoff = await renameResponse.json();
    capture.renameRequest = parseJsonPostData(renameRequest);
    if (
      capture.renameKickoff?.success
      && Array.isArray(capture.renameKickoff?.fields)
      && capture.renameKickoff.fields.length > 0
    ) {
      capture.renameResult = capture.renameKickoff;
    }
    if (!capture.renameKickoff?.success) {
      throw new Error(`Rename kickoff response was incomplete: ${JSON.stringify(capture.renameKickoff)}`);
    }
    if (!capture.renameResult && capture.renameKickoff?.jobId) {
      capture.renameResult = await pollOpenAiJob(page, {
        apiBaseUrl,
        resource: 'renames',
        jobId: String(capture.renameKickoff.jobId),
      });
    }
    const mappingRequest = await mappingRequestPromise;
    const mappingResponse = await mappingRequest.response();
    if (!mappingResponse || !mappingResponse.ok()) {
      const responseText = mappingResponse ? await mappingResponse.text() : 'missing response';
      throw new Error(`Mapping kickoff request did not return a successful response: ${responseText}`);
    }
    capture.mappingKickoff = await mappingResponse.json();
    capture.mappingRequest = parseJsonPostData(mappingRequest);
    if (capture.mappingKickoff?.success && capture.mappingKickoff?.mappingResults) {
      capture.mappingResult = capture.mappingKickoff;
    }
    if (!capture.mappingKickoff?.success) {
      throw new Error(`Mapping kickoff response was incomplete: ${JSON.stringify(capture.mappingKickoff)}`);
    }
    if (!capture.mappingResult && capture.mappingKickoff?.jobId) {
      capture.mappingResult = await pollOpenAiJob(page, {
        apiBaseUrl,
        resource: 'schema-mappings',
        jobId: String(capture.mappingKickoff.jobId),
      });
    }
    if (!capture.renameResult || !capture.mappingResult) {
      throw new Error(
        `Rename + Map did not produce final payloads. Rename kickoff: ${JSON.stringify(capture.renameKickoff)} Mapping kickoff: ${JSON.stringify(capture.mappingKickoff)}`,
      );
    }

    if (!capture.renameRequest?.sessionId) {
      throw new Error(`Rename request should include a sessionId. Payload: ${JSON.stringify(capture.renameRequest)}`);
    }
    if (capture.mappingRequest?.schemaId !== capture.schemaCreate.schemaId) {
      throw new Error(
        `Mapping request should use created schemaId ${capture.schemaCreate.schemaId}. Payload: ${JSON.stringify(capture.mappingRequest)}`,
      );
    }
    const mappingCount = Array.isArray(capture.mappingResult?.mappingResults?.mappings)
      ? capture.mappingResult.mappingResults.mappings.length
      : 0;
    if (mappingCount <= 0) {
      throw new Error(`Expected at least one mapping result. Payload: ${JSON.stringify(capture.mappingResult)}`);
    }
    const mappedFieldNames = (capture.mappingResult?.mappingResults?.mappings || [])
      .map((mapping) => String(mapping?.pdfField || '').trim())
      .filter(Boolean);
    if (mappedFieldNames.length === 0) {
      throw new Error(`Expected usable mapped field names. Payload: ${JSON.stringify(capture.mappingResult)}`);
    }

    const finalFieldNames = await retry('wait for mapped field names in the editor', 40, async () => {
      const names = await collectFieldNames(page);
      if (names.length === 0) {
        throw new Error('Waiting for visible fields after Rename + Map.');
      }
      const anyMappedNameVisible = names.some((name) => mappedFieldNames.includes(name));
      if (!anyMappedNameVisible) {
        throw new Error(`Waiting for mapped field labels to appear in the editor. Visible names: ${JSON.stringify(names.slice(0, 8))}`);
      }
      return names;
    });

    await page.screenshot({ path: screenshotPath, fullPage: true });
    results = {
      ok: true,
      userEmail: userFixture.email,
      screenshotPath,
      summaryPath,
      mockExpensiveAi,
      schemaId: capture.schemaCreate.schemaId,
      initialFieldCount: initialFieldNames.length,
      finalFieldCount: finalFieldNames.length,
      renameFieldCount: Array.isArray(capture.renameResult?.fields) ? capture.renameResult.fields.length : 0,
      mappingCount,
      renamedFieldsSample: (capture.renameResult?.fields || []).map((field) => String(field?.name || '')).filter(Boolean).slice(0, 8),
      mappedFieldsSample: finalFieldNames.slice(0, 8),
    };
  } catch (error) {
    results = {
      ...results,
      ok: false,
    };
    results.error = error instanceof Error ? error.message : String(error);
    console.error(error instanceof Error ? error.stack || error.message : String(error));
  } finally {
    fs.writeFileSync(summaryPath, JSON.stringify(results, null, 2));
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

  console.log(JSON.stringify(results, null, 2));

  if (!results.ok) {
    process.exitCode = 1;
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack || error.message : String(error));
  process.exitCode = 1;
});
