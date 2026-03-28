import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';

const baseUrl = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5173';
const artifactDir = path.resolve(process.cwd(), 'output/playwright');
const PDF_BYTES = Buffer.from('%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n', 'utf8');
const SIGNATURE_UPLOAD_PNG_BASE64 =
  'iVBORw0KGgoAAAANSUhEUgAAAPAAAABgCAYAAABbj1P3AAAAAXNSR0IArs4c6QAAAAlwSFlzAAALEwAACxMBAJqcGAAABoBJREFUeF7t3c9L1FEYx/Hf4xBiuWnQJkG0C0mXIkVvRZFs0wUhCdkQNgiiqCl0FYrIxS6CeBf6A6QbGomgtoQF2m4VxQ3p5v1d9+5x9mZn5s7M7uzO3u99zhw5c+fOTJJ4AABAgQIECBAgAABAgQIECBAgAABAgQIECCwP4VcK6eV+r4Bf8qj2z2gV6S8v1v2KX1F4m2l9zL0QvV8lf9eQ8pX7k7+LzP9yC7wP8tG6QK9dc8wWZ7A0R7m9cD6Q2gWgS8v0QK9rM5LqXq5C8B6QGwV4A5V0d6S8mXgS8B6QGwV4A5V0f6R8mXgS8B6QGwV4A5V0f6R8mXgS8B6QGwV4A5V0f6R8mXgS8B6QGwV4A5V0f6R8mXgS8B6QGwV4A5V0f6R8mXgS8B6QGwV4A5V0f6R8mXgS8B6QGwV4A5V0f6R8mXgS8B6QGwV4A5V0f6R8mXgS8B6QGwV4A5V0f6R8mXgS8B6QGwV4A5V0f6R8mXgS8B6QGwV4A5V0f6R8mXgS8B6QGwV4A5V0f6R8mXgS8B6QGwV4A5V0f6R8mXgS8B6QGwV4A5V0f6R8mXgS8B6QGwV4A5V0f6R8mXgS8B6QGwV4A5V0f6R8mXgS8B6QGwV4A5V0f6R8mXgS8B6QGwd4qPpQq1tE7Z0L5l3L7E4m4Xh4wT4D8qY6f7mQYg6QW5hP7U7L2qz8q8E9P0p5f8h7Q3fM4w4f3F9p0b/7H2mE4r5tq8lWq3q8j8h4Y3xJ4k3xgECAAAECBAgQIECAAAECBAgQIECAAAECBAj8P8C6yS3fN0fU1gAAAABJRU5ErkJggg==';

function ensureSignatureUploadFile() {
  const uploadPath = path.join(artifactDir, 'signing-public-upload-signature.png');
  if (!fs.existsSync(uploadPath)) {
    fs.writeFileSync(uploadPath, Buffer.from(SIGNATURE_UPLOAD_PNG_BASE64, 'base64'));
  }
  return uploadPath;
}

function buildDisclosure(token, state) {
  if (state.signatureMode !== 'consumer') {
    return {
      version: 'us-esign-business-v1',
      summaryLines: ['By continuing you agree to sign this record electronically.'],
    };
  }
  return {
    version: 'us-esign-consumer-v1',
    summaryLines: ['Consumer consent applies only to this request.'],
    paperOption: {
      instructions: 'Use the manual fallback option if you need paper follow-up.',
      fees: 'No platform fee.',
    },
    hardwareSoftware: ['A browser that can display PDF documents.'],
    accessCheck: {
      required: true,
      format: 'pdf',
      instructions: 'Open the access-check PDF and enter the code shown there.',
      accessPath: `/api/signing/public/${token}/consumer-access-pdf`,
      codeLength: 6,
    },
  };
}

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
    signerName: state.signerName,
    signerEmailHint: state.signatureMode === 'consumer' ? 'p***@example.com' : 'a***@example.com',
    anchors: [{ kind: 'signature', page: 1, rect: { x: 40, y: 40, width: 120, height: 36 } }],
    disclosureVersion: state.signatureMode === 'consumer' ? 'us-esign-consumer-v1' : 'us-esign-business-v1',
    disclosure: buildDisclosure(token, state),
    verificationRequired: true,
    verificationMethod: 'email_otp',
    verificationCompletedAt: state.verificationVerifiedAt,
    documentPath: `/api/signing/public/${token}/document`,
    artifacts: {
      signedPdf: {
        available: state.status === 'completed',
        downloadPath: null,
        digitalSignature: {
          available: state.status === 'completed',
          method: state.status === 'completed' ? 'dev_pem' : null,
          algorithm: state.status === 'completed' ? 'rsa_sha256' : null,
          fieldName: state.status === 'completed' ? 'DullyPDFDigitalSignature' : null,
          subfilter: state.status === 'completed' ? '/ETSI.CAdES.detached' : null,
          timestamped: false,
          certificateSubject: state.status === 'completed' ? 'CN=DullyPDF Development PDF Signer' : null,
        },
      },
      auditReceipt: {
        available: state.status === 'completed',
        downloadPath: null,
      },
    },
    createdAt: '2026-03-24T12:00:00Z',
    sentAt: '2026-03-24T12:01:00Z',
    openedAt: state.openedAt,
    reviewedAt: state.reviewedAt,
    consentedAt: state.consentedAt,
    signatureAdoptedAt: state.signatureAdoptedAt,
    signatureAdoptedName: state.signatureAdoptedName,
    signatureAdoptedMode: state.signatureAdoptedMode,
    signatureAdoptedImageDataUrl: state.signatureAdoptedImageDataUrl,
    manualFallbackRequestedAt: state.manualFallbackRequestedAt,
    completedAt: state.completedAt,
  };
}

function buildSession(token, state) {
  return {
    id: `session-${token}`,
    token: state.sessionToken,
    expiresAt: '2026-03-24T13:02:00Z',
    verifiedAt: state.verificationVerifiedAt,
    verificationSentAt: state.verificationSentAt,
    verificationExpiresAt: state.verificationExpiresAt,
    verificationAttemptCount: state.verificationAttemptCount,
    verificationResendCount: state.verificationSendCount,
    verificationResendAvailableAt: state.verificationResendAvailableAt,
  };
}

async function installSigningRoutes(page, token, { signatureMode = 'business', expireFirstCode = false } = {}) {
  const state = {
    sessionToken: `session-${token}`,
    signatureMode,
    signerName: signatureMode === 'consumer' ? 'Pat Consumer' : 'Alex Signer',
    status: 'sent',
    openedAt: null,
    reviewedAt: null,
    consentedAt: null,
    signatureAdoptedAt: null,
    signatureAdoptedName: null,
    signatureAdoptedMode: null,
    signatureAdoptedImageDataUrl: null,
    manualFallbackRequestedAt: null,
    completedAt: null,
    verificationSendCount: 0,
    verificationSentAt: null,
    verificationExpiresAt: null,
    verificationResendAvailableAt: null,
    verificationVerifiedAt: null,
    verificationAttemptCount: 0,
    currentVerificationCode: '123456',
    currentCodeExpired: false,
    consumerAccessCode: 'ABC123',
    lastAdoptPayload: null,
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
        session: buildSession(token, state),
      }),
    });
  });

  await page.route(`**/api/signing/public/${token}/verification/send`, async (route) => {
    state.verificationSendCount += 1;
    state.verificationAttemptCount = 0;
    state.verificationSentAt = state.verificationSendCount > 1 ? '2026-03-24T12:05:00Z' : '2026-03-24T12:03:00Z';
    state.verificationExpiresAt = state.verificationSendCount > 1 ? '2026-03-24T12:15:00Z' : '2026-03-24T12:13:00Z';
    state.verificationResendAvailableAt = '2026-03-24T12:04:00Z';
    state.currentVerificationCode = state.verificationSendCount > 1 ? '654321' : '123456';
    state.currentCodeExpired = Boolean(expireFirstCode && state.verificationSendCount === 1);

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        request: buildRequest(token, state),
        session: buildSession(token, state),
      }),
    });
  });

  await page.route(`**/api/signing/public/${token}/verification/verify`, async (route, request) => {
    const payload = JSON.parse(request.postData() || '{}');
    if (state.currentCodeExpired) {
      await route.fulfill({
        status: 409,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Request a new verification code to continue.' }),
      });
      return;
    }
    if (payload.code !== state.currentVerificationCode) {
      state.verificationAttemptCount += 1;
      await route.fulfill({
        status: 400,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'That verification code is invalid. Try again.' }),
      });
      return;
    }
    state.verificationVerifiedAt = state.verificationSendCount > 1 ? '2026-03-24T12:05:30Z' : '2026-03-24T12:04:30Z';
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        request: buildRequest(token, state),
        session: buildSession(token, state),
      }),
    });
  });

  await page.route(`**/api/signing/public/${token}/consumer-access-pdf`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/pdf',
      body: PDF_BYTES,
    });
  });

  await page.route(`**/api/signing/public/${token}/document`, async (route) => {
    if (!state.verificationVerifiedAt) {
      await route.fulfill({
        status: 403,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Verify the email code before continuing this signing request.' }),
      });
      return;
    }
    if (state.signatureMode === 'consumer' && !state.consentedAt) {
      await route.fulfill({
        status: 409,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Consumer e-consent is required before the document can be reviewed.' }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/pdf',
      body: PDF_BYTES,
    });
  });

  await page.route(`**/api/signing/public/${token}/review`, async (route) => {
    if (!state.verificationVerifiedAt) {
      await route.fulfill({
        status: 403,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Verify the email code before continuing this signing request.' }),
      });
      return;
    }
    if (state.signatureMode === 'consumer' && !state.consentedAt) {
      await route.fulfill({
        status: 409,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Consumer e-consent is required before the document can be reviewed.' }),
      });
      return;
    }
    state.reviewedAt = '2026-03-24T12:06:00Z';
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ request: buildRequest(token, state) }),
    });
  });

  await page.route(`**/api/signing/public/${token}/consent`, async (route, request) => {
    if (!state.verificationVerifiedAt) {
      await route.fulfill({
        status: 403,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Verify the email code before continuing this signing request.' }),
      });
      return;
    }
    const payload = JSON.parse(request.postData() || '{}');
    if (payload.accessCode !== state.consumerAccessCode) {
      await route.fulfill({
        status: 400,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Open the consumer access PDF and enter the 6-character access code before consenting.' }),
      });
      return;
    }
    state.consentedAt = '2026-03-24T12:05:00Z';
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ request: buildRequest(token, state) }),
    });
  });

  await page.route(`**/api/signing/public/${token}/manual-fallback`, async (route) => {
    if (!state.verificationVerifiedAt) {
      await route.fulfill({
        status: 403,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Verify the email code before continuing this signing request.' }),
      });
      return;
    }
    state.manualFallbackRequestedAt = '2026-03-24T12:03:45Z';
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ request: buildRequest(token, state) }),
    });
  });

  await page.route(`**/api/signing/public/${token}/adopt-signature`, async (route, request) => {
    if (!state.verificationVerifiedAt) {
      await route.fulfill({
        status: 403,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Verify the email code before continuing this signing request.' }),
      });
      return;
    }
    const payload = JSON.parse(request.postData() || '{}');
    state.lastAdoptPayload = payload;
    state.signatureAdoptedAt = '2026-03-24T12:07:00Z';
    state.signatureAdoptedMode = payload.signatureType || 'typed';
    state.signatureAdoptedName = state.signatureAdoptedMode === 'default'
      ? state.signerName
      : (payload.adoptedName || state.signerName);
    state.signatureAdoptedImageDataUrl = payload.signatureImageDataUrl || null;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ request: buildRequest(token, state) }),
    });
  });

  await page.route(`**/api/signing/public/${token}/complete`, async (route) => {
    if (!state.verificationVerifiedAt) {
      await route.fulfill({
        status: 403,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Verify the email code before continuing this signing request.' }),
      });
      return;
    }
    state.status = 'completed';
    state.completedAt = '2026-03-24T12:08:00Z';
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ request: buildRequest(token, state) }),
    });
  });

  await page.route(`**/api/signing/public/${token}/artifacts/*/issue`, async (route) => {
    const routeUrl = route.request().url();
    const artifactKey = routeUrl.includes('audit_receipt') ? 'audit_receipt' : 'signed_pdf';
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        artifactKey,
        downloadPath: `/api/signing/public/artifacts/mock-${artifactKey}-token`,
        expiresAt: '2026-03-24T12:13:00Z',
      }),
    });
  });

  await page.route('**/api/signing/public/artifacts/*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/pdf',
      body: PDF_BYTES,
    });
  });

  return state;
}

async function verifyAndReview(page, token) {
  await page.goto(`${baseUrl}/sign/${token}`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.getByRole('heading', { name: 'Verify your email' }).waitFor({ timeout: 10000 });
  await page.getByRole('button', { name: 'Send code' }).click();
  await page.getByText(/A 6-digit code was sent/i).waitFor({ timeout: 10000 });
  await page.getByLabel('Verification code').fill('123456');
  await page.getByRole('button', { name: 'Verify code' }).click();
  await page.getByRole('button', { name: 'I reviewed this document' }).waitFor({ timeout: 10000 });
  await page.getByRole('button', { name: 'I reviewed this document' }).click();
}

async function finishSigning(page) {
  await page.getByLabel('I adopt this signature and sign this exact record electronically.').check();
  await page.getByRole('button', { name: 'Finish Signing' }).click();
  await page.getByText(/This signing request was completed/i).waitFor({ timeout: 10000 });
  await page.getByText(/Embedded PDF signature:/).waitFor({ timeout: 10000 });
}

async function drawSignature(page) {
  const canvas = page.getByLabel('Draw signature');
  const box = await canvas.boundingBox();
  if (!box) {
    throw new Error('Expected the drawn signature canvas to be visible.');
  }
  await page.mouse.move(box.x + 32, box.y + 120);
  await page.mouse.down();
  await page.mouse.move(box.x + 96, box.y + 78, { steps: 8 });
  await page.mouse.move(box.x + 170, box.y + 126, { steps: 8 });
  await page.mouse.move(box.x + 252, box.y + 68, { steps: 8 });
  await page.mouse.up();
}

async function runBusinessTypedHappyPath(browser, results) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 960 } });
  try {
    const state = await installSigningRoutes(page, 'token-business-typed', { signatureMode: 'business' });
    await verifyAndReview(page, 'token-business-typed');
    await page.getByLabel('Adopted signature name').fill('Alex Signer');
    await page.getByRole('button', { name: 'Adopt this signature' }).click();
    if (state.lastAdoptPayload?.signatureType !== 'typed' || state.lastAdoptPayload?.adoptedName !== 'Alex Signer') {
      throw new Error(`Typed signature adoption payload was incorrect: ${JSON.stringify(state.lastAdoptPayload)}`);
    }
    await finishSigning(page);

    await page.screenshot({
      path: path.join(artifactDir, 'signing-public-business-typed-complete.png'),
      fullPage: true,
    });
    results.business_typed_signature = true;
  } finally {
    await page.close();
  }
}

async function runBusinessDefaultSignatureMode(browser, results) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 960 } });
  try {
    const state = await installSigningRoutes(page, 'token-business-default', { signatureMode: 'business' });
    await verifyAndReview(page, 'token-business-default');
    await page.getByRole('radio', { name: /Use legal name/i }).click();
    await page.getByText(/DullyPDF will use the signer name on this request/i).waitFor({ timeout: 10000 });
    await page.getByRole('button', { name: 'Adopt this signature' }).click();
    if (state.lastAdoptPayload?.signatureType !== 'default' || Object.hasOwn(state.lastAdoptPayload, 'adoptedName')) {
      throw new Error(`Default signature adoption payload was incorrect: ${JSON.stringify(state.lastAdoptPayload)}`);
    }
    await finishSigning(page);

    await page.screenshot({
      path: path.join(artifactDir, 'signing-public-business-default-complete.png'),
      fullPage: true,
    });
    results.business_default_signature = true;
  } finally {
    await page.close();
  }
}

async function runBusinessDrawnSignatureMode(browser, results) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 960 } });
  try {
    const state = await installSigningRoutes(page, 'token-business-drawn', { signatureMode: 'business' });
    await verifyAndReview(page, 'token-business-drawn');
    await page.getByRole('radio', { name: /Draw signature/i }).click();
    await drawSignature(page);
    await page.getByRole('img', { name: 'Signature preview' }).waitFor({ timeout: 10000 });
    await page.getByRole('button', { name: 'Adopt this signature' }).click();
    if (
      state.lastAdoptPayload?.signatureType !== 'drawn'
      || !String(state.lastAdoptPayload?.signatureImageDataUrl || '').startsWith('data:image/png;base64,')
    ) {
      throw new Error(`Drawn signature adoption payload was incorrect: ${JSON.stringify(state.lastAdoptPayload)}`);
    }
    await finishSigning(page);

    await page.screenshot({
      path: path.join(artifactDir, 'signing-public-business-drawn-complete.png'),
      fullPage: true,
    });
    results.business_drawn_signature = true;
  } finally {
    await page.close();
  }
}

async function runBusinessUploadedSignatureMode(browser, results) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 960 } });
  try {
    const state = await installSigningRoutes(page, 'token-business-uploaded', { signatureMode: 'business' });
    const uploadPath = ensureSignatureUploadFile();
    await verifyAndReview(page, 'token-business-uploaded');
    await page.getByRole('radio', { name: /Upload image/i }).click();
    await page.locator('#public-signing-uploaded-signature').setInputFiles(uploadPath);
    await page.getByRole('img', { name: 'Signature preview' }).waitFor({ timeout: 10000 });
    await page.getByRole('button', { name: 'Adopt this signature' }).click();
    if (
      state.lastAdoptPayload?.signatureType !== 'uploaded'
      || !String(state.lastAdoptPayload?.signatureImageDataUrl || '').startsWith('data:image/')
    ) {
      throw new Error(`Uploaded signature adoption payload was incorrect: ${JSON.stringify(state.lastAdoptPayload)}`);
    }
    await finishSigning(page);

    await page.screenshot({
      path: path.join(artifactDir, 'signing-public-business-uploaded-complete.png'),
      fullPage: true,
    });
    results.business_uploaded_signature = true;
  } finally {
    await page.close();
  }
}

async function runConsumerConsentGate(browser, results) {
  const page = await browser.newPage({ viewport: { width: 430, height: 932 } });
  try {
    await installSigningRoutes(page, 'token-consumer', { signatureMode: 'consumer' });
    await page.goto(`${baseUrl}/sign/token-consumer`, { waitUntil: 'domcontentloaded', timeout: 30000 });

    await page.getByRole('heading', { name: 'Verify your email' }).waitFor({ timeout: 10000 });
    await page.getByRole('button', { name: 'Send code' }).click();
    await page.getByLabel('Verification code').fill('123456');
    await page.getByRole('button', { name: 'Verify code' }).click();

    await page.getByRole('heading', { name: 'Consent to electronic records' }).waitFor({ timeout: 10000 });
    const reviewButtonVisible = await page.getByRole('button', { name: 'I reviewed this document' }).isVisible().catch(() => false);
    if (reviewButtonVisible) {
      throw new Error('Consumer flow should stay on e-consent until access code consent is completed.');
    }

    await page.getByLabel('Access code').fill('ABC123');
    await page.getByRole('button', { name: 'I consent to electronic records' }).click();
    await page.getByRole('button', { name: 'I reviewed this document' }).waitFor({ timeout: 10000 });

    await page.screenshot({
      path: path.join(artifactDir, 'signing-public-consumer-consent.png'),
      fullPage: true,
    });
    results.consumer_consent_gate = true;
  } finally {
    await page.close();
  }
}

async function runExpiredCodeRecovery(browser, results) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 960 } });
  try {
    await installSigningRoutes(page, 'token-expired', { signatureMode: 'business', expireFirstCode: true });
    await page.goto(`${baseUrl}/sign/token-expired`, { waitUntil: 'domcontentloaded', timeout: 30000 });

    await page.getByRole('heading', { name: 'Verify your email' }).waitFor({ timeout: 10000 });
    await page.getByRole('button', { name: 'Send code' }).click();
    await page.getByLabel('Verification code').fill('123456');
    await page.getByRole('button', { name: 'Verify code' }).click();
    await page.getByText(/Request a new verification code to continue/i).waitFor({ timeout: 10000 });

    await page.getByRole('button', { name: 'Resend code' }).click();
    await page.getByLabel('Verification code').fill('');
    await page.getByLabel('Verification code').fill('654321');
    await page.getByRole('button', { name: 'Verify code' }).click();
    await page.getByRole('button', { name: 'I reviewed this document' }).waitFor({ timeout: 10000 });

    await page.screenshot({
      path: path.join(artifactDir, 'signing-public-expired-code-recovery.png'),
      fullPage: true,
    });
    results.expired_code_recovery = true;
  } finally {
    await page.close();
  }
}

async function main() {
  fs.mkdirSync(artifactDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const results = {};

  try {
    await runBusinessTypedHappyPath(browser, results);
    await runBusinessDefaultSignatureMode(browser, results);
    await runBusinessDrawnSignatureMode(browser, results);
    await runBusinessUploadedSignatureMode(browser, results);
    await runConsumerConsentGate(browser, results);
    await runExpiredCodeRecovery(browser, results);
    console.log(JSON.stringify({ ok: true, ...results }));
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack || error.message : String(error));
  process.exitCode = 1;
});
