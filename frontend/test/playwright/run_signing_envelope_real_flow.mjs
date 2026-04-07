/**
 * Real integration Playwright test for the multi-signer envelope flow.
 *
 * This test hits the REAL backend (no API mocks). It:
 * 1. Creates a real Firebase user
 * 2. Signs in and navigates to the workspace
 * 3. Uploads a real PDF with signature fields
 * 4. Opens the signing dialog
 * 5. Verifies the current workflow/policy defaults
 * 6. Adds 2 recipients
 * 7. Saves 2 real signing drafts (POST /api/signing/requests — real)
 * 8. Sends the 2 real requests (POST /api/signing/requests/{id}/send — real)
 * 9. Verifies the backend returned the expected request data
 *
 * Requires: dev backend + frontend running on localhost:5173
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import {
  createCustomToken,
  createHybridEmailUser,
  deleteCurrentUserHarness,
  deleteUserByInitialToken,
  signInWithCustomTokenHarness,
  signOutHarness,
} from './helpers/downgradeFixture.mjs';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(scriptDir, '..', '..');
const repoRoot = path.resolve(frontendRoot, '..');
const baseUrl = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5173';
const artifactDir = path.resolve(frontendRoot, 'output/playwright');
const samplePdfPath = path.resolve(
  repoRoot,
  'quickTestFiles/cms1500_06_03d2696ed5.pdf',
);
const requestedSigningMode = (process.env.SIGNING_MODE || 'separate').trim().toLowerCase();

if (!['separate', 'parallel', 'sequential'].includes(requestedSigningMode)) {
  throw new Error(`Unsupported SIGNING_MODE=${requestedSigningMode}. Expected separate, parallel, or sequential.`);
}

function logStep(message) {
  console.log(`[envelope-real-flow] ${message}`);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForCaptureCount(label, getCount, expectedCount, attempts = 20) {
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    const count = getCount();
    if (count >= expectedCount) {
      return;
    }
    if (attempt < attempts) {
      console.warn(`[envelope-real-flow] ${label} attempt ${attempt} saw ${count}/${expectedCount} captured responses`);
      await sleep(1000);
      continue;
    }
    throw new Error(`${label} timed out after ${attempts} attempts: expected ${expectedCount}, got ${count}`);
  }
}

async function waitForJsonResponse(page, matcher, label, timeout = 30000) {
  const response = await page.waitForResponse(matcher, { timeout });
  const rawBody = await response.text();
  let body = rawBody;
  try {
    body = rawBody ? JSON.parse(rawBody) : null;
  } catch {
    // Keep the raw body when the endpoint returns plain text or HTML.
  }
  if (!response.ok()) {
    const detail = typeof body === 'string' ? body : JSON.stringify(body);
    throw new Error(`${label} failed with status ${response.status()}: ${detail}`);
  }
  return { response, body };
}

async function main() {
  if (!fs.existsSync(samplePdfPath)) {
    throw new Error(`Missing sample PDF: ${samplePdfPath}`);
  }
  fs.mkdirSync(artifactDir, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1200 } });

  // Capture both the legacy per-request flow and the envelope flow so this
  // real test can verify Separate, Parallel, and Sequential modes.
  const captured = {
    requestCreatePayloads: [],
    requestCreateResponses: [],
    requestSendResponses: [],
    envelopeCreatePayload: null,
    envelopeCreateResponse: null,
    envelopeSendResponse: null,
  };

  page.on('pageerror', (error) => {
    console.error(`[envelope-real-flow][pageerror] ${error instanceof Error ? error.stack || error.message : String(error)}`);
  });

  page.on('response', async (response) => {
    const url = response.url();
    const method = response.request().method();
    if (method === 'POST' && url.includes('/api/signing/requests') && !url.includes('/send')) {
      try {
        const payload = JSON.parse(response.request().postData() || '{}');
        const body = await response.json();
        captured.requestCreatePayloads.push(payload);
        captured.requestCreateResponses.push(body?.request || body);
      } catch {
        // Ignore malformed request/response bodies from unrelated calls.
      }
    }
    if (method === 'POST' && url.includes('/api/signing/requests/') && url.includes('/send')) {
      try {
        const body = await response.json();
        captured.requestSendResponses.push(body?.request || body);
      } catch {
        // Ignore malformed send responses.
      }
    }
    if (method === 'POST' && url.includes('/api/signing/envelopes') && !url.includes('/send')) {
      try {
        captured.envelopeCreatePayload = JSON.parse(response.request().postData() || '{}');
        captured.envelopeCreateResponse = await response.json();
      } catch {
        // Ignore malformed envelope payloads from unrelated calls.
      }
    }
    if (method === 'POST' && url.includes('/api/signing/envelopes/') && url.includes('/send')) {
      try {
        captured.envelopeSendResponse = await response.json();
      } catch {
        // Ignore malformed send responses.
      }
    }
  });

  let userFixture = null;

  try {
    // ---------------------------------------------------------------
    // Step 1: Create real Firebase user and sign in
    // ---------------------------------------------------------------
    logStep('opening frontend');
    await page.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });

    logStep('creating Firebase test user');
    userFixture = await createHybridEmailUser(page);
    logStep(`created user: ${userFixture.email} (${userFixture.uid})`);

    const customToken = createCustomToken(userFixture.uid);
    await signInWithCustomTokenHarness(page, customToken);

    // ---------------------------------------------------------------
    // Step 2: Navigate to workspace and upload PDF
    // ---------------------------------------------------------------
    logStep('navigating to workspace');
    await page.goto(`${baseUrl}/ui`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.getByText('Upload PDF for Field Detection').waitFor({ timeout: 30000 });

    logStep('uploading PDF with signature fields');
    await page.getByLabel('Upload Fillable PDF Template').setInputFiles(samplePdfPath);
    await page.getByRole('button', { name: 'Send PDF for Signature by email' }).waitFor({ timeout: 30000 });

    const recipients = requestedSigningMode === 'separate'
      ? [
          { name: 'Alice First', email: 'alice-test@example.com' },
          { name: 'Bob Second', email: 'bob-test@example.com' },
        ]
      : [
          { name: 'Alice First', email: 'alice-test@example.com', order: 1 },
          { name: 'Bob Second', email: 'bob-test@example.com', order: 2 },
          { name: 'Carol Third', email: 'carol-test@example.com', order: 3 },
        ];

    // ---------------------------------------------------------------
    // Step 3: Add signature anchors via the editor
    // ---------------------------------------------------------------
    logStep(`adding ${recipients.length} signature anchors in the editor`);
    await page.locator('.panel-mode-chip').filter({ hasText: 'Signature' }).first().click();
    for (let index = 0; index < recipients.length; index += 1) {
      const y = 160 + (index * 100);
      await page.locator('[aria-label="Draw signature field"]').first().click({ position: { x: 160, y } });
      await sleep(500);
    }

    // ---------------------------------------------------------------
    // Step 4: Open the signing dialog
    // ---------------------------------------------------------------
    logStep('opening signing dialog');
    const signingOptionsResponse = page.waitForResponse((response) => {
      return response.url().includes('/api/signing/options')
        && response.request().method() === 'GET'
        && response.ok();
    }, { timeout: 15000 });
    await page.getByRole('button', { name: 'Send PDF for Signature by email' }).click();
    await signingOptionsResponse;
    await page.getByRole('heading', { name: 'Send PDF for Signature by email' }).waitFor({ timeout: 10000 });

    // ---------------------------------------------------------------
    // Step 5: Verify workflow/policy defaults
    // ---------------------------------------------------------------
    logStep('verifying workflow defaults');
    const workflowTabs = page.locator('.signature-request-dialog__mode-row').filter({ hasText: 'Fill and Sign' }).first();
    await workflowTabs.waitFor({ timeout: 15000 });
    const signButton = workflowTabs.getByRole('button', { name: 'Sign', exact: true });
    const fillAndSignButton = workflowTabs.getByRole('button', { name: 'Fill and Sign', exact: true });
    const signClass = await signButton.getAttribute('class');
    const fillAndSignClass = await fillAndSignButton.getAttribute('class');
    if (!signClass?.includes('ui-button--primary')) {
      throw new Error(`Expected Sign to be the default workflow mode, got class=${signClass}`);
    }
    if (fillAndSignClass?.includes('ui-button--primary')) {
      throw new Error(`Expected Fill and Sign to be inactive by default, got class=${fillAndSignClass}`);
    }

    const signatureModeSelect = page.locator('select[name="signature_mode"]');
    await signatureModeSelect.waitFor({ timeout: 10000 });
    const signatureModeValue = await signatureModeSelect.inputValue();
    if (signatureModeValue !== 'business') {
      throw new Error(`Expected signature_mode=business by default, got ${signatureModeValue}`);
    }

    if (requestedSigningMode !== 'separate') {
      logStep(`switching signing mode to ${requestedSigningMode}`);
      const signingModeSection = page.locator('.signature-request-dialog__section').filter({
        has: page.getByRole('heading', { name: 'Signing Mode' }),
      }).first();
      const targetModeLabel = requestedSigningMode === 'parallel' ? 'Parallel' : 'Sequential';
      const targetModeButton = signingModeSection.getByRole('button', { name: targetModeLabel, exact: true });
      await targetModeButton.waitFor({ timeout: 10000 });
      await targetModeButton.click();
      const targetClasses = await targetModeButton.getAttribute('class');
      if (!targetClasses?.includes('ui-button--primary')) {
        throw new Error(`Expected ${targetModeLabel} to be active, got class=${targetClasses}`);
      }
    }

    logStep(`adding ${recipients.length} recipients`);
    for (const recipient of recipients) {
      await page.locator('label:has-text("Signer name") input').fill(recipient.name);
      await page.locator('label:has-text("Signer email") input').fill(recipient.email);
      await page.getByRole('button', { name: 'Add recipient' }).click();
      await page.locator('.signature-request-dialog__recipient-card').filter({ hasText: recipient.email }).first().waitFor({ timeout: 5000 });
    }

    const recipientCards = page.locator('.signature-request-dialog__recipient-card');
    const recipientCount = await recipientCards.count();
    if (recipientCount !== recipients.length) {
      throw new Error(`Expected ${recipients.length} queued recipient cards, found ${recipientCount}`);
    }
    logStep(`verified ${recipientCount} queued recipients`);

    if (requestedSigningMode === 'sequential') {
      const orderBadges = page.locator('.signature-request-dialog__recipient-order');
      const orderBadgeCount = await orderBadges.count();
      if (orderBadgeCount !== recipients.length) {
        throw new Error(`Expected ${recipients.length} sequential order badges, found ${orderBadgeCount}`);
      }
    }

    if (requestedSigningMode !== 'separate') {
      logStep('assigning signature anchors to recipient order');
      const assignmentSection = page.locator('.signature-request-dialog__section').filter({
        has: page.getByRole('heading', { name: 'Assign Signature Fields' }),
      }).first();
      await assignmentSection.waitFor({ timeout: 10000 });
      const assignmentSelects = assignmentSection.locator('select');
      const assignmentCount = await assignmentSelects.count();
      if (assignmentCount < 1) {
        throw new Error('Expected at least one signature assignment select in envelope mode.');
      }
      for (let index = 0; index < assignmentCount; index += 1) {
        const signerOrder = String((index % recipients.length) + 1);
        await assignmentSelects.nth(index).selectOption(signerOrder);
      }
    }

    // ---------------------------------------------------------------
    // Step 7: Confirm e-sign eligibility and save the real draft batch
    // ---------------------------------------------------------------
    logStep('confirming e-sign eligibility');
    await page.getByRole('checkbox', {
      name: /I reviewed the blocked-category list.*confirm this document is eligible/i,
    }).check();

    await page.waitForFunction(() => {
      const buttons = Array.from(document.querySelectorAll('button'));
      const btn = buttons.find((b) => /Save Signing Draft/i.test(b.textContent || ''));
      return btn instanceof HTMLButtonElement && !btn.disabled;
    }, { timeout: 15000 });

    const saveButton = page.locator('button').filter({ hasText: /Save Signing Draft/i }).first();
    const errors = [];
    const expectedEmails = recipients.map((recipient) => recipient.email).sort();
    const expectedNames = recipients.map((recipient) => recipient.name);

    if (requestedSigningMode === 'separate') {
      logStep('saving signing request drafts');
      const createRequestResponse = page.waitForResponse((response) => {
        return response.url().includes('/api/signing/requests')
          && !response.url().includes('/send')
          && response.request().method() === 'POST'
          && response.status() === 201;
      }, { timeout: 30000 });
      await saveButton.click();
      await createRequestResponse;
      await waitForCaptureCount('create responses', () => captured.requestCreateResponses.length, recipients.length);
      await page.getByRole('heading', { name: 'Batch review and send' }).waitFor({ timeout: 10000 });
      await page.getByText(
        /(?:Saved 2 signing drafts\.|Drafts saved\. Review the batch summary, then click Review and Send to activate signer links\.)/i,
      ).first().waitFor({ timeout: 15000 });

      await page.screenshot({
        path: path.join(artifactDir, `envelope-real-flow-${requestedSigningMode}-draft.png`),
        fullPage: true,
      });

      logStep('sending the signing requests');
      await page.waitForFunction(() => {
        const buttons = Array.from(document.querySelectorAll('button'));
        const btn = buttons.find((b) => b.textContent?.trim() === 'Review and Send');
        return btn instanceof HTMLButtonElement && !btn.disabled;
      }, { timeout: 15000 });

      const sendRequestResponse = page.waitForResponse((response) => {
        return response.url().includes('/api/signing/requests/')
          && response.url().includes('/send')
          && response.request().method() === 'POST'
          && response.ok();
      }, { timeout: 30000 });

      await page.getByRole('button', { name: 'Review and Send' }).evaluate((btn) => {
        if (btn instanceof HTMLButtonElement) btn.click();
      });
      await sendRequestResponse;
      await page.getByText(/Sent 2 signing requests\./i).waitFor({ timeout: 20000 });
      await waitForCaptureCount('send responses', () => captured.requestSendResponses.length, recipients.length);

      await page.screenshot({
        path: path.join(artifactDir, `envelope-real-flow-${requestedSigningMode}-sent.png`),
        fullPage: true,
      });

      const createPayloads = captured.requestCreatePayloads;
      const createResults = captured.requestCreateResponses;
      const sendResults = captured.requestSendResponses;

      if (createPayloads.length !== recipients.length) {
        errors.push(`Expected ${recipients.length} create payloads, got ${createPayloads.length}`);
      }
      if (createResults.length !== recipients.length) {
        errors.push(`Expected ${recipients.length} create responses, got ${createResults.length}`);
      }
      if (sendResults.length !== recipients.length) {
        errors.push(`Expected ${recipients.length} send responses, got ${sendResults.length}`);
      }

      if (createPayloads.length === recipients.length) {
        const createdEmails = createPayloads.map((payload) => payload.signerEmail).sort();
        if (JSON.stringify(createdEmails) !== JSON.stringify(expectedEmails)) {
          errors.push(`Create payload emails mismatch: ${JSON.stringify(createdEmails)}`);
        }
        createPayloads.forEach((payload, index) => {
          if (payload.mode !== 'sign') {
            errors.push(`Create payload ${index + 1} expected mode=sign, got ${payload.mode}`);
          }
          if (payload.signatureMode !== 'business') {
            errors.push(`Create payload ${index + 1} expected signatureMode=business, got ${payload.signatureMode}`);
          }
          if (payload.esignEligibilityConfirmed !== true) {
            errors.push(`Create payload ${index + 1} missing e-sign eligibility confirmation`);
          }
          if (!payload.sourcePdfSha256) {
            errors.push(`Create payload ${index + 1} missing sourcePdfSha256`);
          }
          if (!Array.isArray(payload.anchors) || payload.anchors.length < 2) {
            errors.push(`Create payload ${index + 1} expected at least 2 anchors, got ${payload.anchors?.length}`);
          }
        });
      }

      if (createResults.length === recipients.length) {
        const responseEmails = createResults.map((entry) => entry.signerEmail).sort();
        if (JSON.stringify(responseEmails) !== JSON.stringify(expectedEmails)) {
          errors.push(`Create response emails mismatch: ${JSON.stringify(responseEmails)}`);
        }
        createResults.forEach((entry, index) => {
          if (!entry.id) {
            errors.push(`Create response ${index + 1} missing request id`);
          }
          if (entry.status !== 'draft') {
            errors.push(`Create response ${index + 1} expected status=draft, got ${entry.status}`);
          }
        });
      }

      if (sendResults.length === recipients.length) {
        const sentEmails = sendResults.map((entry) => entry.signerEmail).sort();
        if (JSON.stringify(sentEmails) !== JSON.stringify(expectedEmails)) {
          errors.push(`Send response emails mismatch: ${JSON.stringify(sentEmails)}`);
        }
        sendResults.forEach((entry, index) => {
          if (entry.status !== 'sent') {
            errors.push(`Send response ${index + 1} expected status=sent, got ${entry.status}`);
          }
          if (!entry.sentAt) {
            errors.push(`Send response ${index + 1} missing sentAt`);
          }
          if (!entry.publicToken) {
            errors.push(`Send response ${index + 1} missing publicToken`);
          }
        });
      }

      if (errors.length > 0) {
        console.error('[envelope-real-flow] VERIFICATION ERRORS:');
        errors.forEach((entry) => console.error(`  - ${entry}`));
        throw new Error(`Verification failed with ${errors.length} error(s):\n${errors.join('\n')}`);
      }

      logStep('ALL VERIFICATIONS PASSED');

      const summary = {
        ok: true,
        uid: userFixture.uid,
        email: userFixture.email,
        signingMode: requestedSigningMode,
        requestIds: createResults.map((entry) => entry.id),
        requestCount: createResults.length,
        signatureMode: createPayloads[0]?.signatureMode || null,
        workflowMode: createPayloads[0]?.mode || null,
        recipientNames: expectedNames,
        recipientEmails: expectedEmails,
        anchorCount: createPayloads[0]?.anchors?.length || 0,
        sentStatuses: sendResults.map((entry) => entry.status),
      };
      fs.writeFileSync(
        path.join(artifactDir, `envelope-real-flow-${requestedSigningMode}.json`),
        JSON.stringify(summary, null, 2),
      );
      console.log(JSON.stringify(summary));
    } else {
      logStep(`saving ${requestedSigningMode} signing envelope`);
      const createEnvelopeResponse = waitForJsonResponse(page, (response) => {
        return response.url().includes('/api/signing/envelopes')
          && !response.url().includes('/send')
          && response.request().method() === 'POST';
      }, `${requestedSigningMode} envelope create`, 30000);
      await saveButton.click();
      await createEnvelopeResponse;
      await waitForCaptureCount('envelope create response', () => (captured.envelopeCreateResponse ? 1 : 0), 1);
      await page.getByRole('heading', { name: 'Batch review and send' }).waitFor({ timeout: 10000 });
      await page.getByText(new RegExp(`Saved signing envelope with ${recipients.length} signers\\.`, 'i')).waitFor({ timeout: 15000 });

      await page.screenshot({
        path: path.join(artifactDir, `envelope-real-flow-${requestedSigningMode}-draft.png`),
        fullPage: true,
      });

      logStep(`sending ${requestedSigningMode} signing envelope`);
      await page.waitForFunction(() => {
        const buttons = Array.from(document.querySelectorAll('button'));
        const btn = buttons.find((b) => b.textContent?.trim() === 'Review and Send');
        return btn instanceof HTMLButtonElement && !btn.disabled;
      }, { timeout: 15000 });

      const sendEnvelopeResponse = waitForJsonResponse(page, (response) => {
        return response.url().includes('/api/signing/envelopes/')
          && response.url().includes('/send')
          && response.request().method() === 'POST';
      }, `${requestedSigningMode} envelope send`, 30000);
      await page.getByRole('button', { name: 'Review and Send' }).evaluate((btn) => {
        if (btn instanceof HTMLButtonElement) btn.click();
      });
      await sendEnvelopeResponse;
      await waitForCaptureCount('envelope send response', () => (captured.envelopeSendResponse ? 1 : 0), 1);
      await page.getByText(new RegExp(`Sent ${recipients.length} signing requests\\.`, 'i')).waitFor({ timeout: 20000 });

      await page.screenshot({
        path: path.join(artifactDir, `envelope-real-flow-${requestedSigningMode}-sent.png`),
        fullPage: true,
      });

      const envelopePayload = captured.envelopeCreatePayload;
      const createResult = captured.envelopeCreateResponse;
      const sendResult = captured.envelopeSendResponse;
      const createdEnvelope = createResult?.envelope || null;
      const createdRequests = Array.isArray(createResult?.requests) ? createResult.requests : [];
      const sentRequests = Array.isArray(sendResult?.requests) ? sendResult.requests : [];

      if (!envelopePayload) {
        errors.push('Missing envelope create payload capture.');
      }
      if (!createdEnvelope?.id) {
        errors.push('Envelope create response missing envelope id.');
      }
      if (createdRequests.length !== recipients.length) {
        errors.push(`Expected ${recipients.length} created envelope requests, got ${createdRequests.length}`);
      }
      if (sentRequests.length !== recipients.length) {
        errors.push(`Expected ${recipients.length} sent envelope requests, got ${sentRequests.length}`);
      }
      if (envelopePayload?.signingMode !== requestedSigningMode) {
        errors.push(`Expected envelope payload signingMode=${requestedSigningMode}, got ${envelopePayload?.signingMode}`);
      }
      if (createdEnvelope?.signingMode !== requestedSigningMode) {
        errors.push(`Expected envelope response signingMode=${requestedSigningMode}, got ${createdEnvelope?.signingMode}`);
      }
      if (envelopePayload?.mode !== 'sign') {
        errors.push(`Expected envelope payload mode=sign, got ${envelopePayload?.mode}`);
      }
      if (envelopePayload?.signatureMode !== 'business') {
        errors.push(`Expected envelope payload signatureMode=business, got ${envelopePayload?.signatureMode}`);
      }
      if (!Array.isArray(envelopePayload?.anchors) || envelopePayload.anchors.length < recipients.length) {
        errors.push(`Expected at least ${recipients.length} anchors in envelope payload, got ${envelopePayload?.anchors?.length}`);
      }
      const payloadEmails = Array.isArray(envelopePayload?.recipients)
        ? envelopePayload.recipients.map((recipient) => recipient.email).sort()
        : [];
      if (JSON.stringify(payloadEmails) !== JSON.stringify(expectedEmails)) {
        errors.push(`Envelope payload emails mismatch: ${JSON.stringify(payloadEmails)}`);
      }
      if (requestedSigningMode === 'sequential' && Array.isArray(envelopePayload?.recipients)) {
        const payloadOrders = envelopePayload.recipients.map((recipient) => recipient.order);
        const expectedOrders = recipients.map((recipient) => recipient.order);
        if (JSON.stringify(payloadOrders) !== JSON.stringify(expectedOrders)) {
          errors.push(`Sequential payload orders mismatch: ${JSON.stringify(payloadOrders)}`);
        }
      }
      createdRequests.forEach((entry, index) => {
        if (!entry.id) {
          errors.push(`Created envelope request ${index + 1} missing request id`);
        }
        if (entry.status !== 'draft') {
          errors.push(`Created envelope request ${index + 1} expected status=draft, got ${entry.status}`);
        }
      });
      sentRequests.forEach((entry, index) => {
        if (entry.status !== 'sent') {
          errors.push(`Sent envelope request ${index + 1} expected status=sent, got ${entry.status}`);
        }
      });

      if (errors.length > 0) {
        console.error('[envelope-real-flow] VERIFICATION ERRORS:');
        errors.forEach((entry) => console.error(`  - ${entry}`));
        throw new Error(`Verification failed with ${errors.length} error(s):\n${errors.join('\n')}`);
      }

      logStep('ALL VERIFICATIONS PASSED');

      const summary = {
        ok: true,
        uid: userFixture.uid,
        email: userFixture.email,
        signingMode: requestedSigningMode,
        envelopeId: createdEnvelope?.id || null,
        requestIds: createdRequests.map((entry) => entry.id),
        requestCount: createdRequests.length,
        signatureMode: envelopePayload?.signatureMode || null,
        workflowMode: envelopePayload?.mode || null,
        recipientNames: expectedNames,
        recipientEmails: expectedEmails,
        anchorCount: envelopePayload?.anchors?.length || 0,
        sentStatuses: sentRequests.map((entry) => entry.status),
      };
      fs.writeFileSync(
        path.join(artifactDir, `envelope-real-flow-${requestedSigningMode}.json`),
        JSON.stringify(summary, null, 2),
      );
      console.log(JSON.stringify(summary));
    }

  } finally {
    try {
      await signOutHarness(page);
    } catch {}
    if (userFixture) {
      try {
        await deleteCurrentUserHarness(page);
      } catch {
        try {
          await deleteUserByInitialToken(page, userFixture.apiKey, userFixture.initialIdToken);
        } catch {}
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
