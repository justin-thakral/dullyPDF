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
const screenshotPath = path.join(artifactDir, 'signing-owner-verification.png');
const summaryPath = path.join(artifactDir, 'signing-owner-verification.json');
const samplePdfPath = path.resolve(
  repoRoot,
  'samples/fieldDetecting/pdfs/native/intake/new_patient_intake_form_fillable_badc6aa21d.pdf',
);
const samplePdfBytes = fs.readFileSync(samplePdfPath);

function logStep(message) {
  console.log(`[signing-owner-verification-smoke] ${message}`);
}

function assertExists(filePath) {
  if (!fs.existsSync(filePath)) {
    throw new Error(`Missing required file: ${filePath}`);
  }
}

function makeProfile(email) {
  return {
    email,
    displayName: 'Signing Verification Smoke Owner',
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
    ],
  };
}

function buildSigningRequest(payload, overrides = {}) {
  const mode = payload.mode || 'sign';
  const hasPublicTokenOverride = Object.prototype.hasOwnProperty.call(overrides, 'publicToken');
  const publicToken = hasPublicTokenOverride ? overrides.publicToken : 'owner-signing-verify-public-token';
  const hasPublicPathOverride = Object.prototype.hasOwnProperty.call(overrides, 'publicPath');
  const publicPath = hasPublicPathOverride ? overrides.publicPath : '/sign/owner-signing-verify-public-token';
  return {
    id: overrides.id || 'signing-owner-verify-req',
    title: payload.title || 'Owner Signing Verification Smoke',
    mode,
    signatureMode: payload.signatureMode || 'business',
    sourceType: payload.sourceType || 'workspace',
    sourceId: payload.sourceId || null,
    sourceLinkId: payload.sourceLinkId || null,
    sourceRecordLabel: payload.sourceRecordLabel || null,
    sourceDocumentName: payload.sourceDocumentName || 'Signing Verification Smoke.pdf',
    sourceTemplateId: payload.sourceTemplateId || null,
    sourceTemplateName: payload.sourceTemplateName || payload.sourceDocumentName || 'Signing Verification Smoke.pdf',
    sourcePdfSha256: payload.sourcePdfSha256 || null,
    sourcePdfPath: overrides.sourcePdfPath || null,
    sourceVersion: overrides.sourceVersion || `workspace:${payload.sourcePdfSha256 || 'pending'}`,
    documentCategory: payload.documentCategory || 'ordinary_business_form',
    documentCategoryLabel: 'Ordinary business form',
    manualFallbackEnabled: payload.manualFallbackEnabled !== false,
    signerName: payload.signerName || 'Alex Signer',
    signerEmail: payload.signerEmail || 'alex@example.com',
    signerEmailHint: overrides.signerEmailHint || 'a***@example.com',
    status: overrides.status || 'draft',
    anchors: Array.isArray(payload.anchors) ? payload.anchors : [],
    disclosureVersion: payload.signatureMode === 'consumer' ? 'us-esign-consumer-v1' : 'us-esign-business-v1',
    verificationRequired: overrides.verificationRequired ?? true,
    verificationMethod: overrides.verificationMethod ?? 'email_otp',
    verificationCompletedAt: overrides.verificationCompletedAt || null,
    publicToken,
    publicPath,
    createdAt: overrides.createdAt || '2026-03-27T15:00:00Z',
    updatedAt: overrides.updatedAt || '2026-03-27T15:00:00Z',
    ownerReviewConfirmedAt: overrides.ownerReviewConfirmedAt || null,
    sentAt: overrides.sentAt || null,
    completedAt: null,
    expiresAt: overrides.expiresAt || '2026-04-10T15:02:00Z',
    retentionUntil: overrides.retentionUntil || null,
    openedAt: overrides.openedAt || null,
    reviewedAt: overrides.reviewedAt || null,
    consentedAt: null,
    consentWithdrawnAt: null,
    signatureAdoptedAt: null,
    signatureAdoptedName: null,
    manualFallbackRequestedAt: null,
    invalidatedAt: null,
    invalidationReason: null,
    documentPath: overrides.documentPath || `/api/signing/public/${publicToken || 'owner-signing-verify-public-token'}/document`,
    disclosure: {
      version: 'us-esign-business-v1',
      summaryLines: ['By proceeding you agree to sign electronically.'],
    },
    artifacts: overrides.artifacts || {
      signedPdf: {
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

async function installOwnerAndPublicSigningApiMocks(page, email) {
  const state = {
    templateSessionId: 'template-session-owner-verify',
    verificationCode: '123456',
    sessionToken: 'session-token-owner-verify',
    createdDraft: null,
    sendBodySeen: false,
    verificationSent: false,
    verificationVerified: false,
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
        id: 'signing-owner-verify-req',
        status: 'draft',
        publicToken: null,
        publicPath: null,
        createdAt: '2026-03-27T15:01:00Z',
        updatedAt: '2026-03-27T15:01:00Z',
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

    if (method === 'GET' && pathname === '/api/signing/requests/signing-owner-verify-req') {
      await json(200, { request: state.createdDraft });
      return;
    }

    if (method === 'POST' && pathname === '/api/signing/requests/signing-owner-verify-req/send') {
      state.sendBodySeen = true;
      const sourcePdfSha256 = state.createdDraft?.sourcePdfSha256 || null;
      state.createdDraft = buildSigningRequest(state.createdDraft || {}, {
        id: 'signing-owner-verify-req',
        status: 'sent',
        publicToken: 'owner-signing-verify-public-token',
        publicPath: '/sign/owner-signing-verify-public-token',
        sourcePdfPath: 'gs://dullypdf-signing/users/owner/signing/signing-owner-verify-req/source/sample.pdf',
        sourceVersion: `workspace:${sourcePdfSha256 || 'pending'}`,
        sentAt: '2026-03-27T15:02:00Z',
        retentionUntil: '2033-03-27T15:02:00Z',
        updatedAt: '2026-03-27T15:02:00Z',
      });
      await json(200, { request: state.createdDraft });
      return;
    }

    if (method === 'POST' && pathname === `/api/sessions/${encodeURIComponent(state.templateSessionId)}/touch`) {
      await json(200, { success: true, sessionId: state.templateSessionId });
      return;
    }

    if (method === 'GET' && pathname === '/api/signing/public/owner-signing-verify-public-token') {
      await json(200, { request: state.createdDraft });
      return;
    }

    if (method === 'POST' && pathname === '/api/signing/public/owner-signing-verify-public-token/bootstrap') {
      state.createdDraft = {
        ...state.createdDraft,
        openedAt: '2026-03-27T15:03:00Z',
      };
      await json(200, {
        request: state.createdDraft,
        session: {
          id: 'session-owner-verify',
          token: state.sessionToken,
          expiresAt: '2026-03-27T16:03:00Z',
          verifiedAt: state.verificationVerified ? '2026-03-27T15:04:00Z' : null,
          verificationSentAt: state.verificationSent ? '2026-03-27T15:03:30Z' : null,
          verificationExpiresAt: state.verificationSent ? '2026-03-27T15:13:30Z' : null,
          verificationAttemptCount: 0,
          verificationResendCount: state.verificationSent ? 1 : 0,
          verificationResendAvailableAt: state.verificationSent ? '2026-03-27T15:04:30Z' : null,
        },
      });
      return;
    }

    if (method === 'POST' && pathname === '/api/signing/public/owner-signing-verify-public-token/verification/send') {
      state.verificationSent = true;
      await json(200, {
        request: state.createdDraft,
        session: {
          id: 'session-owner-verify',
          token: state.sessionToken,
          expiresAt: '2026-03-27T16:03:00Z',
          verifiedAt: state.verificationVerified ? '2026-03-27T15:04:00Z' : null,
          verificationSentAt: '2026-03-27T15:03:30Z',
          verificationExpiresAt: '2026-03-27T15:13:30Z',
          verificationAttemptCount: 0,
          verificationResendCount: 1,
          verificationResendAvailableAt: '2026-03-27T15:04:30Z',
        },
      });
      return;
    }

    if (method === 'POST' && pathname === '/api/signing/public/owner-signing-verify-public-token/verification/verify') {
      const payload = JSON.parse(request.postData() || '{}');
      if (payload.code !== state.verificationCode) {
        await json(400, { detail: 'That verification code is invalid. Try again.' });
        return;
      }
      state.verificationVerified = true;
      state.createdDraft = {
        ...state.createdDraft,
        verificationCompletedAt: '2026-03-27T15:04:00Z',
      };
      await json(200, {
        request: state.createdDraft,
        session: {
          id: 'session-owner-verify',
          token: state.sessionToken,
          expiresAt: '2026-03-27T16:03:00Z',
          verifiedAt: '2026-03-27T15:04:00Z',
          verificationSentAt: '2026-03-27T15:03:30Z',
          verificationExpiresAt: '2026-03-27T15:13:30Z',
          verificationAttemptCount: 0,
          verificationResendCount: 1,
          verificationResendAvailableAt: '2026-03-27T15:04:30Z',
        },
      });
      return;
    }

    if (method === 'GET' && pathname === '/api/signing/public/owner-signing-verify-public-token/document') {
      if (!state.verificationVerified) {
        await json(401, { detail: 'Verify your email before opening this signing document.' });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/pdf',
        body: samplePdfBytes,
      });
      return;
    }

    if (method === 'POST' && pathname === '/api/signing/public/owner-signing-verify-public-token/review') {
      if (!state.verificationVerified) {
        await json(403, { detail: 'Verify the email code before continuing this signing request.' });
        return;
      }
      state.createdDraft = {
        ...state.createdDraft,
        reviewedAt: '2026-03-27T15:05:00Z',
      };
      await json(200, { request: state.createdDraft });
      return;
    }

    console.error(`[signing-owner-verification-smoke] unhandled mock API request: ${method} ${pathname}`);
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
    console.error(
      `[signing-owner-verification-smoke][pageerror] ${error instanceof Error ? error.stack || error.message : String(error)}`,
    );
  });
  page.on('console', (message) => {
    if (message.type() === 'error' || message.type() === 'warning') {
      console.log(`[signing-owner-verification-smoke][browser:${message.type()}] ${message.text()}`);
    }
  });

  let mockState = null;
  const fixtureUid = `pw-signing-owner-verify-${Date.now()}`;
  const fixtureEmail = 'codex-signing-owner-verify@example.com';

  try {
    logStep('opening frontend');
    await page.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
    logStep('installing owner and public signing API mocks');
    mockState = await installOwnerAndPublicSigningApiMocks(page, fixtureEmail);
    logStep('signing in with custom token');
    const customToken = createCustomToken(fixtureUid);
    await signInWithCustomTokenHarness(page, customToken);

    logStep('opening workspace');
    await page.goto(`${baseUrl}/ui`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.getByText('Upload PDF for Field Detection').waitFor({ timeout: 30000 });

    logStep('uploading fillable PDF with signature anchor');
    await page.getByLabel('Upload Fillable PDF Template').setInputFiles(samplePdfPath);
    await page.getByRole('button', { name: 'Send PDF for Signature by email' }).waitFor({ timeout: 30000 });
    await page.locator('.panel-mode-chip').filter({ hasText: 'Signature' }).first().click();
    await page.locator('[aria-label="Draw signature field"]').first().click({ position: { x: 160, y: 160 } });

    logStep('opening signing dialog');
    await page.getByRole('button', { name: 'Send PDF for Signature by email' }).click();
    await page.getByRole('heading', { name: 'Send PDF for Signature by email' }).waitFor({ timeout: 10000 });
    await page.waitForFunction(() => {
      return document.querySelectorAll('.signature-request-dialog select option').length >= 3;
    }, { timeout: 10000 });

    logStep('saving signing draft');
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
      return response.url().includes('/api/signing/requests/signing-owner-verify-req/send')
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

    if (!mockState?.createdDraft?.verificationRequired || mockState?.createdDraft?.verificationMethod !== 'email_otp') {
      throw new Error('Owner send flow did not mark the signing request for email OTP verification.');
    }

    logStep('opening public signing route');
    await page.goto(`${baseUrl}${mockState.createdDraft.publicPath}`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.getByRole('heading', { name: 'Verify your email' }).waitFor({ timeout: 10000 });
    const reviewButtonVisible = await page.getByRole('button', { name: 'I reviewed this document' }).isVisible().catch(() => false);
    if (reviewButtonVisible) {
      throw new Error('Public signing review action should stay hidden until OTP verification succeeds.');
    }

    logStep('requesting and verifying OTP code');
    await page.getByRole('button', { name: 'Send code' }).click();
    await page.getByText(/A 6-digit code was sent/i).waitFor({ timeout: 10000 });
    await page.getByLabel('Verification code').fill(mockState.verificationCode);
    await page.getByRole('button', { name: 'Verify code' }).click();
    await page.getByRole('button', { name: 'I reviewed this document' }).waitFor({ timeout: 10000 });

    logStep('capturing verification screenshot');
    await page.screenshot({
      path: screenshotPath,
      fullPage: true,
    });

    const summary = {
      ok: true,
      screenshotPath,
      summaryPath,
      requestId: mockState.createdDraft.id,
      publicPath: mockState.createdDraft.publicPath,
      verificationRequired: mockState.createdDraft.verificationRequired,
      verificationMethod: mockState.createdDraft.verificationMethod,
      verificationVerified: mockState.verificationVerified,
      sendBodySeen: Boolean(mockState.sendBodySeen),
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
