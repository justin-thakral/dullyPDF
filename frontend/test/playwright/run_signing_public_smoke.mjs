import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';

const baseUrl = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5173';
const artifactDir = path.resolve(process.cwd(), 'output/playwright');
const PDF_BYTES = Buffer.from('%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n', 'utf8');

function buildRequest(token, state) {
  return {
    id: `req-${token}`,
    title: 'Bravo Packet Signature Request',
    mode: 'sign',
    signatureMode: state.signatureMode,
    status: state.status,
    statusMessage: state.status === 'completed'
      ? 'This signing request has already been completed.'
      : 'This signing request is ready for review and signature.',
    sourceDocumentName: state.signatureMode === 'consumer' ? 'Consumer Packet' : 'Bravo Packet',
    sourcePdfSha256: 'abc123',
    sourceVersion: 'workspace:abc123',
    documentCategory: state.signatureMode === 'consumer' ? 'authorization_consent_form' : 'ordinary_business_form',
    documentCategoryLabel: state.signatureMode === 'consumer' ? 'Authorization or consent form' : 'Ordinary business form',
    manualFallbackEnabled: true,
    signerName: state.signatureMode === 'consumer' ? 'Pat Consumer' : 'Alex Signer',
    anchors: [{ kind: 'signature', page: 1, rect: { x: 40, y: 40, width: 120, height: 36 } }],
    disclosureVersion: state.signatureMode === 'consumer' ? 'us-esign-consumer-v1' : 'us-esign-business-v1',
    documentPath: `/api/signing/public/${token}/document`,
    createdAt: '2026-03-24T12:00:00Z',
    sentAt: '2026-03-24T12:01:00Z',
    openedAt: state.openedAt,
    reviewedAt: state.reviewedAt,
    consentedAt: state.consentedAt,
    signatureAdoptedAt: state.signatureAdoptedAt,
    signatureAdoptedName: state.signatureAdoptedName,
    manualFallbackRequestedAt: state.manualFallbackRequestedAt,
    completedAt: state.completedAt,
  };
}

async function installSigningRoutes(page, token, { signatureMode = 'business' } = {}) {
  const sessionToken = `session-${token}`;
  const state = {
    signatureMode,
    status: 'sent',
    openedAt: null,
    reviewedAt: null,
    consentedAt: null,
    signatureAdoptedAt: null,
    signatureAdoptedName: null,
    manualFallbackRequestedAt: null,
    completedAt: null,
  };

  await page.route(`**/api/signing/public/${token}`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ request: buildRequest(token, state) }),
    });
  });

  await page.route(`**/api/signing/public/${token}/bootstrap`, async (route) => {
    state.openedAt = '2026-03-24T12:02:00Z';
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        request: buildRequest(token, state),
        session: {
          id: `session-${token}`,
          token: sessionToken,
          expiresAt: '2026-03-24T13:02:00Z',
        },
      }),
    });
  });

  await page.route(`**/api/signing/public/${token}/document`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/pdf',
      body: PDF_BYTES,
    });
  });

  await page.route(`**/api/signing/public/${token}/review`, async (route) => {
    if (state.signatureMode === 'consumer' && !state.consentedAt) {
      await route.fulfill({
        status: 409,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Consumer e-consent is required before the document can be reviewed.' }),
      });
      return;
    }
    state.reviewedAt = '2026-03-24T12:03:00Z';
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ request: buildRequest(token, state) }),
    });
  });

  await page.route(`**/api/signing/public/${token}/consent`, async (route) => {
    state.consentedAt = '2026-03-24T12:03:30Z';
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ request: buildRequest(token, state) }),
    });
  });

  await page.route(`**/api/signing/public/${token}/manual-fallback`, async (route) => {
    state.manualFallbackRequestedAt = '2026-03-24T12:03:45Z';
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ request: buildRequest(token, state) }),
    });
  });

  await page.route(`**/api/signing/public/${token}/adopt-signature`, async (route, request) => {
    const payload = JSON.parse(request.postData() || '{}');
    state.signatureAdoptedAt = '2026-03-24T12:04:00Z';
    state.signatureAdoptedName = payload.adoptedName || 'Alex Signer';
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ request: buildRequest(token, state) }),
    });
  });

  await page.route(`**/api/signing/public/${token}/complete`, async (route) => {
    state.status = 'completed';
    state.completedAt = '2026-03-24T12:05:00Z';
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ request: buildRequest(token, state) }),
    });
  });

  return { sessionToken, state };
}

async function main() {
  fs.mkdirSync(artifactDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const results = {};

  try {
    {
      const page = await browser.newPage({ viewport: { width: 1280, height: 960 } });
      await installSigningRoutes(page, 'token-business', { signatureMode: 'business' });
      await page.goto(`${baseUrl}/sign/token-business`, { waitUntil: 'domcontentloaded', timeout: 30000 });

      await page.getByRole('button', { name: 'I reviewed this document' }).waitFor({ timeout: 10000 });
      await page.getByRole('button', { name: 'I reviewed this document' }).click();

      await page.getByLabel('Adopted signature name').fill('Alex Signer');
      await page.getByRole('button', { name: 'Adopt this signature' }).click();

      await page.getByLabel('I adopt this signature and sign this exact record electronically.').check();
      await page.getByRole('button', { name: 'Finish Signing' }).click();

      await page.getByText(/This signing request was completed/i).waitFor({ timeout: 10000 });
      await page.screenshot({
        path: path.join(artifactDir, 'signing-public-business-complete.png'),
        fullPage: true,
      });
      results.business_happy_path = true;
      await page.close();
    }

    {
      const page = await browser.newPage({ viewport: { width: 430, height: 932 } });
      await installSigningRoutes(page, 'token-consumer', { signatureMode: 'consumer' });
      await page.goto(`${baseUrl}/sign/token-consumer`, { waitUntil: 'domcontentloaded', timeout: 30000 });

      await page.getByRole('heading', { name: 'Consent to electronic records' }).waitFor({ timeout: 10000 });
      const reviewButtonVisible = await page.getByRole('button', { name: 'I reviewed this document' }).isVisible().catch(() => false);
      if (reviewButtonVisible) {
        throw new Error('Consumer flow should not show the review action before consent.');
      }

      await page.getByRole('button', { name: 'Request paper/manual fallback' }).click();
      await page.getByText(/paper\/manual fallback request was recorded/i).waitFor({ timeout: 10000 });
      await page.getByRole('button', { name: 'I consent to electronic records' }).click();
      await page.getByRole('button', { name: 'I reviewed this document' }).waitFor({ timeout: 10000 });

      await page.screenshot({
        path: path.join(artifactDir, 'signing-public-consumer-consent.png'),
        fullPage: true,
      });
      results.consumer_consent_gate = true;
      await page.close();
    }

    console.log(JSON.stringify({ ok: true, ...results }));
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack || error.message : String(error));
  process.exitCode = 1;
});
