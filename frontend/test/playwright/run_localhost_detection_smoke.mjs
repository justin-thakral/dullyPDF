import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';
import {
  collectFieldNames,
  getCurrentAuthToken,
  retry,
  signInFromHomepageAndOpenProfile,
  uploadFillablePdfAndWaitForEditor,
} from './helpers/workspaceFixture.mjs';

const repoRoot = process.cwd();
const baseUrl = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5173';
const apiBaseUrl = (process.env.PLAYWRIGHT_API_URL || 'http://127.0.0.1:8010').replace(/\/+$/, '');
const artifactDir = path.resolve(repoRoot, 'output/playwright');
const screenshotPath = path.join(artifactDir, 'localhost-detection-smoke.png');
const summaryPath = path.join(artifactDir, 'localhost-detection-smoke.json');
const loginEmail = (process.env.SMOKE_LOGIN_EMAIL || process.env.PLAYWRIGHT_LOGIN_EMAIL || '').trim();
const loginPassword = process.env.SMOKE_LOGIN_PASSWORD || process.env.PLAYWRIGHT_LOGIN_PASSWORD || '';
const samplePdfPath = path.resolve(repoRoot, 'quickTestFiles/new_patient_forms_1915ccb015.pdf');
const mockExpensiveGpu = /^true$/i.test(process.env.PLAYWRIGHT_MOCK_EXPENSIVE_GPU || '');

function logStep(message) {
  console.log(`[localhost-detection-smoke] ${message}`);
}

async function startDetection(authToken) {
  const pdfBytes = fs.readFileSync(samplePdfPath);
  const formData = new FormData();
  formData.append('file', new Blob([pdfBytes], { type: 'application/pdf' }), path.basename(samplePdfPath));
  formData.append('pipeline', 'commonforms');

  const response = await fetch(`${apiBaseUrl}/detect-fields`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${authToken}`,
    },
    body: formData,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(`Detection kickoff failed (${response.status}): ${JSON.stringify(payload)}`);
  }
  if (!payload?.sessionId) {
    throw new Error(`Detection kickoff did not return a sessionId: ${JSON.stringify(payload)}`);
  }
  return payload;
}

async function pollDetection(authToken, sessionId) {
  return retry(`poll detection ${sessionId}`, 120, async () => {
    const response = await fetch(`${apiBaseUrl}/detect-fields/${encodeURIComponent(sessionId)}`, {
      headers: {
        Authorization: `Bearer ${authToken}`,
      },
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(`Detection poll failed (${response.status}): ${JSON.stringify(payload)}`);
    }
    const status = String(payload?.status || '').toLowerCase();
    if (status === 'failed') {
      throw new Error(`Detection failed: ${JSON.stringify(payload)}`);
    }
    if (status !== 'complete' || !Array.isArray(payload?.fields) || payload.fields.length === 0) {
      throw new Error(`Waiting for detection completion. Latest payload: ${JSON.stringify(payload)}`);
    }
    return payload;
  });
}

async function main() {
  if (!fs.existsSync(samplePdfPath)) {
    throw new Error(`Missing detection sample PDF: ${samplePdfPath}`);
  }

  fs.mkdirSync(artifactDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1480, height: 1100 } });
  const results = {
    ok: false,
    baseUrl,
    apiBaseUrl,
    screenshotPath,
    summaryPath,
    pageErrors: [],
    consoleErrors: [],
  };

  try {
    page.on('pageerror', (error) => {
      results.pageErrors.push(error instanceof Error ? error.message : String(error));
    });
    page.on('console', (message) => {
      if (message.type() === 'error') {
        results.consoleErrors.push(message.text());
      }
    });

    await signInFromHomepageAndOpenProfile(page, {
      baseUrl,
      loginEmail,
      loginPassword,
      logStep,
    });

    if (mockExpensiveGpu) {
      logStep('using fillable editor bootstrap instead of paid GPU detection');
      await page.getByRole('button', { name: 'Return to workspace' }).click();
      await uploadFillablePdfAndWaitForEditor(page, baseUrl);
      const fieldNames = await collectFieldNames(page);
      if (fieldNames.length === 0) {
        throw new Error('Expected visible editor fields after fillable PDF bootstrap.');
      }
      results.ok = true;
      results.currentUrl = page.url();
      results.finalStatus = 'mock_complete';
      results.fieldCount = fieldNames.length;
      results.pageCount = null;
      results.detectionRuntime = 'mock_fillable_bootstrap';
      results.sampleFieldNames = fieldNames.slice(0, 8);
    } else {
      logStep('capturing authenticated token');
      const authToken = await getCurrentAuthToken(page);

      logStep('starting real detection through backend API');
      const kickoffPayload = await startDetection(authToken);
      results.sessionId = kickoffPayload.sessionId;
      results.kickoffStatus = kickoffPayload.status || null;
      results.kickoffPayload = kickoffPayload;

      logStep('polling for completed detection result');
      const finalPayload = await pollDetection(authToken, kickoffPayload.sessionId);
      results.ok = true;
      results.currentUrl = page.url();
      results.finalStatus = finalPayload.status || null;
      results.fieldCount = Array.isArray(finalPayload.fields) ? finalPayload.fields.length : 0;
      results.pageCount = finalPayload.pageCount ?? null;
      results.detectionRuntime = finalPayload.detectionRuntime ?? null;
      results.sampleFieldNames = Array.isArray(finalPayload.fields)
        ? finalPayload.fields.slice(0, 8).map((field) => String(field?.name || '').trim()).filter(Boolean)
        : [];
    }

    await page.screenshot({ path: screenshotPath, fullPage: true });
  } catch (error) {
    results.error = error instanceof Error ? error.message : String(error);
    results.currentUrl = page.url();
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
