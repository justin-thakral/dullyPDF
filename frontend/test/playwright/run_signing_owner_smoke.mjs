import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import {
  createCustomToken,
  signInWithCustomTokenHarness,
  signOutHarness,
} from './helpers/downgradeFixture.mjs';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(scriptDir, '..', '..');
const repoRoot = path.resolve(frontendRoot, '..');
const baseUrl = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5173';
const artifactDir = path.resolve(frontendRoot, 'output/playwright');
const screenshotPath = path.join(artifactDir, 'signing-owner-sent.png');
const summaryPath = path.join(artifactDir, 'signing-owner-smoke.json');
const samplePdfPath = path.resolve(
  repoRoot,
  'samples/fieldDetecting/pdfs/native/intake/new_patient_intake_form_fillable_badc6aa21d.pdf',
);
const samplePdfBytes = fs.readFileSync(samplePdfPath);

function logStep(message) {
  console.log(`[signing-owner-smoke] ${message}`);
}

function assertExists(filePath) {
  if (!fs.existsSync(filePath)) {
    throw new Error(`Missing required file: ${filePath}`);
  }
}

function makeProfile(email) {
  return {
    email,
    displayName: 'Signing Smoke Owner',
    role: 'pro',
    billing: {
      enabled: true,
      plans: {},
      hasSubscription: true,
      subscriptionStatus: 'active',
      cancelAtPeriodEnd: false,
    },
    limits: {
      detectMaxPages: 100,
      fillableMaxPages: 1000,
      savedFormsMax: 20,
      fillLinksActiveMax: 10,
      fillLinkResponsesMax: 1000,
    },
  };
}

function buildSigningOptions() {
  return {
    modes: [
      { key: 'sign', label: 'Sign' },
      { key: 'fill_and_sign', label: 'Fill and Sign' },
    ],
    signatureModes: [
      { key: 'business', label: 'Business' },
      { key: 'consumer', label: 'Consumer' },
    ],
    categories: [
      {
        key: 'ordinary_business_form',
        label: 'Ordinary business form',
        blocked: false,
      },
      {
        key: 'court_document',
        label: 'Court document',
        blocked: true,
        reason: 'Court notices and court documents stay outside the DullyPDF e-sign workflow.',
      },
    ],
  };
}

function buildSigningRequest(payload, overrides = {}) {
  const mode = payload.mode || 'sign';
  return {
    id: overrides.id || 'signing-owner-req',
    title: payload.title || 'Owner Signing Smoke',
    mode,
    signatureMode: payload.signatureMode || 'business',
    sourceType: payload.sourceType || 'workspace',
    sourceId: payload.sourceId || null,
    sourceLinkId: payload.sourceLinkId || null,
    sourceRecordLabel: payload.sourceRecordLabel || null,
    sourceDocumentName: payload.sourceDocumentName || 'Signing Smoke.pdf',
    sourceTemplateId: payload.sourceTemplateId || null,
    sourceTemplateName: payload.sourceTemplateName || payload.sourceDocumentName || 'Signing Smoke.pdf',
    sourcePdfSha256: payload.sourcePdfSha256 || null,
    sourcePdfPath: overrides.sourcePdfPath || null,
    sourceVersion: overrides.sourceVersion || `workspace:${payload.sourcePdfSha256 || 'pending'}`,
    documentCategory: payload.documentCategory || 'ordinary_business_form',
    documentCategoryLabel: 'Ordinary business form',
    manualFallbackEnabled: payload.manualFallbackEnabled !== false,
    signerName: payload.signerName || 'Alex Signer',
    signerEmail: payload.signerEmail || 'alex@example.com',
    status: overrides.status || 'draft',
    anchors: Array.isArray(payload.anchors) ? payload.anchors : [],
    disclosureVersion: payload.signatureMode === 'consumer' ? 'us-esign-consumer-v1' : 'us-esign-business-v1',
    publicToken: overrides.publicToken || 'owner-signing-public-token',
    publicPath: overrides.publicPath || '/sign/owner-signing-public-token',
    createdAt: overrides.createdAt || '2026-03-24T15:00:00Z',
    updatedAt: overrides.updatedAt || '2026-03-24T15:00:00Z',
    ownerReviewConfirmedAt: overrides.ownerReviewConfirmedAt || null,
    sentAt: overrides.sentAt || null,
    completedAt: null,
    retentionUntil: overrides.retentionUntil || null,
    openedAt: null,
    reviewedAt: null,
    consentedAt: null,
    signatureAdoptedAt: null,
    signatureAdoptedName: null,
    manualFallbackRequestedAt: null,
    invalidatedAt: null,
    invalidationReason: null,
    artifacts: overrides.artifacts || {
      signedPdf: {
        available: false,
        downloadPath: null,
      },
      auditManifest: {
        available: false,
        downloadPath: null,
      },
      auditReceipt: {
        available: false,
        downloadPath: null,
      },
    },
  };
}

async function installOwnerWorkspaceApiMocks(page, email) {
  const state = {
    templateSessionId: 'template-session-owner',
    createdDraft: null,
    sendBodySeen: false,
  };

  await page.route('**/api/**', async (route, request) => {
    const url = new URL(request.url());
    const { pathname } = url;
    const method = request.method().toUpperCase();

    const json = async (status, body) => {
      await route.fulfill({
        status,
        contentType: 'application/json',
        body: JSON.stringify(body),
      });
    };

    if (method === 'GET' && pathname === '/api/profile') {
      await json(200, makeProfile(email));
      return;
    }

    if (method === 'GET' && pathname === '/api/health') {
      await json(200, { ok: true, status: 'ok' });
      return;
    }

    if (method === 'GET' && pathname === '/api/saved-forms') {
      await json(200, { forms: [] });
      return;
    }

    if (method === 'GET' && pathname === '/api/groups') {
      await json(200, { groups: [] });
      return;
    }

    if (method === 'GET' && pathname === '/api/signing/options') {
      await json(200, buildSigningOptions());
      return;
    }

    if (method === 'POST' && pathname === '/api/templates/session') {
      await json(200, {
        success: true,
        sessionId: state.templateSessionId,
        fieldCount: 4,
        pageCount: 2,
      });
      return;
    }

    if (method === 'POST' && pathname === '/api/forms/materialize') {
      await route.fulfill({
        status: 200,
        contentType: 'application/pdf',
        body: samplePdfBytes,
      });
      return;
    }

    if (method === 'POST' && pathname === '/api/signing/requests') {
      const payload = JSON.parse(request.postData() || '{}');
      state.createdDraft = buildSigningRequest(payload, {
        id: 'signing-owner-req',
        status: 'draft',
        createdAt: '2026-03-24T15:01:00Z',
        updatedAt: '2026-03-24T15:01:00Z',
      });
      await json(201, { request: state.createdDraft });
      return;
    }

    if (method === 'GET' && pathname === '/api/signing/requests') {
      await json(200, {
        requests: state.createdDraft ? [state.createdDraft] : [],
      });
      return;
    }

    if (method === 'GET' && pathname === '/api/signing/requests/signing-owner-req') {
      await json(200, { request: state.createdDraft });
      return;
    }

    if (method === 'POST' && pathname === '/api/signing/requests/signing-owner-req/send') {
      state.sendBodySeen = true;
      const sourcePdfSha256 = state.createdDraft?.sourcePdfSha256 || null;
      state.createdDraft = buildSigningRequest(state.createdDraft || {}, {
        id: 'signing-owner-req',
        status: 'sent',
        sourcePdfPath: 'gs://dullypdf-signing/users/owner/signing/signing-owner-req/source/sample.pdf',
        sourceVersion: `workspace:${sourcePdfSha256 || 'pending'}`,
        sentAt: '2026-03-24T15:02:00Z',
        retentionUntil: '2033-03-24T15:02:00Z',
        updatedAt: '2026-03-24T15:02:00Z',
      });
      await json(200, { request: state.createdDraft });
      return;
    }

    if (method === 'POST' && pathname === `/api/sessions/${encodeURIComponent(state.templateSessionId)}/touch`) {
      await json(200, { success: true, sessionId: state.templateSessionId });
      return;
    }

    console.error(`[signing-owner-smoke] unhandled mock API request: ${method} ${pathname}`);
    await route.fulfill({
      status: 501,
      contentType: 'application/json',
      body: JSON.stringify({
        detail: `Unhandled mock API request: ${method} ${pathname}`,
      }),
    });
  });

  return state;
}

async function main() {
  assertExists(samplePdfPath);
  fs.mkdirSync(artifactDir, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1200 } });
  page.on('pageerror', (error) => {
    console.error(`[signing-owner-smoke][pageerror] ${error instanceof Error ? error.stack || error.message : String(error)}`);
  });
  page.on('console', (message) => {
    if (message.type() === 'error' || message.type() === 'warning') {
      console.log(`[signing-owner-smoke][browser:${message.type()}] ${message.text()}`);
    }
  });

  let mockState = null;
  const fixtureUid = `pw-signing-owner-${Date.now()}`;
  const fixtureEmail = 'codex-signing-owner@example.com';

  try {
    logStep('opening frontend');
    await page.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
    logStep('installing workspace API mocks');
    mockState = await installOwnerWorkspaceApiMocks(page, fixtureEmail);
    logStep('signing in with custom token');
    const customToken = createCustomToken(fixtureUid);
    await signInWithCustomTokenHarness(page, customToken);

    logStep('opening workspace');
    await page.goto(`${baseUrl}/ui`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.getByText('Upload PDF for Field Detection').waitFor({ timeout: 30000 });

    logStep('uploading fillable PDF with signature anchors');
    await page.getByLabel('Upload Fillable PDF Template').setInputFiles(samplePdfPath);
    await page.getByRole('button', { name: 'Send PDF for Signature by email' }).waitFor({ timeout: 30000 });
    logStep('adding a signature anchor in the editor');
    await page.locator('.panel-mode-chip').filter({ hasText: 'Signature' }).first().click();
    await page.locator('[aria-label="Draw signature field"]').first().click({ position: { x: 160, y: 160 } });
    const signingOptionsResponse = page.waitForResponse((response) => {
      return response.url().includes('/api/signing/options')
        && response.request().method() === 'GET'
        && response.ok();
    }, { timeout: 15000 });
    await page.getByRole('button', { name: 'Send PDF for Signature by email' }).click();
    await signingOptionsResponse;

    logStep('saving signing draft');
    await page.getByRole('heading', { name: 'Send PDF for Signature by email' }).waitFor({ timeout: 10000 });
    await page.waitForFunction(() => {
      return document.querySelectorAll('.signature-request-dialog select option').length >= 3;
    }, { timeout: 10000 });
    await page.locator('label:has-text("Signer name") input').fill('Alex Signer');
    await page.locator('label:has-text("Signer email") input').fill('alex.signer@example.com');
    await page.waitForFunction(() => {
      const buttons = Array.from(document.querySelectorAll('button'));
      const saveButton = buttons.find((button) => button.textContent?.trim() === 'Save Signing Draft');
      return saveButton instanceof HTMLButtonElement && !saveButton.disabled;
    }, { timeout: 15000 });
    const createDraftResponse = page.waitForResponse((response) => {
      return response.url().includes('/api/signing/requests')
        && response.request().method() === 'POST'
        && response.status() === 201;
    }, { timeout: 15000 });
    await page.getByRole('button', { name: 'Save Signing Draft' }).click();
    await createDraftResponse;

    await page.getByText(/Draft saved\./i).waitFor({ timeout: 10000 });
    await page.getByRole('heading', { name: 'Batch review and send' }).waitFor({ timeout: 10000 });
    logStep('sending immutable signing request');
    await page.waitForFunction(() => {
      const buttons = Array.from(document.querySelectorAll('button'));
      const sendButton = buttons.find((button) => button.textContent?.trim() === 'Review and Send');
      return sendButton instanceof HTMLButtonElement && !sendButton.disabled;
    }, { timeout: 15000 });
    const materializeResponse = page.waitForResponse((response) => {
      return response.url().includes('/api/forms/materialize')
        && response.request().method() === 'POST'
        && response.ok();
    }, { timeout: 15000 });
    const sendDraftResponse = page.waitForResponse((response) => {
      return response.url().includes('/api/signing/requests/signing-owner-req/send')
        && response.request().method() === 'POST'
        && response.ok();
    }, { timeout: 15000 });
    await page.getByRole('button', { name: 'Review and Send' }).evaluate((button) => {
      if (!(button instanceof HTMLButtonElement)) {
        throw new Error('Review and Send control is not a button element.');
      }
      button.click();
    });
    await materializeResponse;
    await sendDraftResponse;

    await page.getByText(/Sent 1 signing request\./i).waitFor({ timeout: 10000 });
    await page.getByText(/All current signing requests have already been sent or are no longer sendable\./i).waitFor({ timeout: 10000 });
    await page.getByText(/workspace:/i).waitFor({ timeout: 10000 });

    logStep('capturing screenshot');
    await page.screenshot({
      path: screenshotPath,
      fullPage: true,
    });

    const summary = {
      ok: true,
      screenshotPath,
      summaryPath,
      requestId: mockState?.createdDraft?.id || null,
      sourcePdfSha256: mockState?.createdDraft?.sourcePdfSha256 || null,
      anchorCount: Array.isArray(mockState?.createdDraft?.anchors) ? mockState.createdDraft.anchors.length : 0,
      sendBodySeen: Boolean(mockState?.sendBodySeen),
    };
    fs.writeFileSync(summaryPath, JSON.stringify(summary, null, 2));
    console.log(JSON.stringify(summary));
  } finally {
    try {
      await signOutHarness(page);
    } catch {}
    await page.close();
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack || error.message : String(error));
  process.exitCode = 1;
});
