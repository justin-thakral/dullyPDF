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

const repoRoot = process.cwd();
const baseUrl = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5173';
const apiBaseUrl = (process.env.PLAYWRIGHT_API_URL || 'http://localhost:8000').replace(/\/+$/, '');
const artifactDir = path.resolve(repoRoot, 'output/playwright');
const screenshotPath = path.join(artifactDir, 'template-api-manager-real-user-flow.png');
const summaryPath = path.join(artifactDir, 'template-api-manager-real-user-flow.json');
const samplePdfPath = path.resolve(repoRoot, 'quickTestFiles/cms1500_06_03d2696ed5.pdf');

function sleep(durationMs) {
  return new Promise((resolve) => {
    setTimeout(resolve, durationMs);
  });
}

async function retry(label, attempts, fn) {
  let lastError = null;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await fn(attempt);
    } catch (error) {
      lastError = error;
      if (attempt >= attempts) {
        break;
      }
      console.warn(`[playwright] ${label} attempt ${attempt} failed: ${error instanceof Error ? error.message : String(error)}`);
      await sleep(1500);
    }
  }
  throw lastError instanceof Error ? lastError : new Error(String(lastError));
}

function logStep(message) {
  console.log(`[template-api-manager-real-user-flow] ${message}`);
}

function runBackendPython(script, extraEnv = {}) {
  const bashScript = `
set -euo pipefail
set -a
source env/backend.dev.env
set +a
source scripts/_load_firebase_secret.sh
load_firebase_secret
backend/.venv/bin/python - <<'PY'
${script}
PY
`;
  return execFileSync('bash', ['-lc', bashScript], {
    cwd: repoRoot,
    env: { ...process.env, ...extraEnv },
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
  }).trim();
}

function seedTemplateApiFixture({ uid, email }) {
  const output = runBackendPython(
    `
import json
import os
import shutil
import tempfile

from pypdf import PdfReader

from backend.firebaseDB.firebase_service import get_firestore_client, init_firebase
from backend.firebaseDB.storage_service import upload_form_pdf, upload_template_pdf
from backend.firebaseDB.template_database import create_template
from backend.services.saved_form_snapshot_service import upload_saved_form_editor_snapshot

uid = os.environ["PW_UID"]
email = os.environ["PW_EMAIL"]
sample_pdf_path = os.environ["PW_SAMPLE_PDF_PATH"]

init_firebase()
client = get_firestore_client()
client.collection("app_users").document(uid).set(
    {
        "firebase_uid": uid,
        "email": email,
        "displayName": "Template API Playwright User",
        "role": "god",
    },
    merge=True,
)

reader = PdfReader(sample_pdf_path)
page_count = len(reader.pages)
page_sizes = {}
for page_number, page in enumerate(reader.pages, start=1):
    page_sizes[str(page_number)] = {
        "width": float(page.mediabox.width),
        "height": float(page.mediabox.height),
    }

copied_pdf_path = None
with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_pdf:
    shutil.copyfile(sample_pdf_path, temp_pdf.name)
    copied_pdf_path = temp_pdf.name

try:
    pdf_path = upload_form_pdf(copied_pdf_path, f"users/{uid}/template-api/patient-intake.pdf")
    template_path = upload_template_pdf(copied_pdf_path, f"users/{uid}/template-api/patient-intake-template.pdf")
    snapshot_payload = {
        "version": 1,
        "pageCount": page_count,
        "pageSizes": page_sizes,
        "fields": [
            {
                "id": "api-fill-name",
                "name": "api_fill_name",
                "type": "text",
                "page": 1,
                "rect": {
                    "x": 72.0,
                    "y": 120.0,
                    "width": 180.0,
                    "height": 18.0,
                },
                "value": None,
            }
        ],
        "hasRenamedFields": True,
        "hasMappedSchema": False,
    }
    snapshot_path, snapshot_manifest = upload_saved_form_editor_snapshot(
        user_id=uid,
        form_id=f"{uid}-template-api",
        timestamp_ms=1742500000000,
        snapshot=snapshot_payload,
    )
    record = create_template(
        uid,
        pdf_path,
        template_path,
        metadata={
            "name": "Template API Packet",
            "editorSnapshot": snapshot_manifest,
        },
    )
    print(json.dumps({
        "templateId": record.id,
        "templateName": "Template API Packet",
        "fieldName": "api_fill_name",
        "snapshotPath": snapshot_path,
    }, sort_keys=True))
finally:
    if copied_pdf_path and os.path.exists(copied_pdf_path):
        os.unlink(copied_pdf_path)
`,
    {
      PW_UID: uid,
      PW_EMAIL: email,
      PW_SAMPLE_PDF_PATH: samplePdfPath,
    },
  );
  return JSON.parse(output.split('\n').pop());
}

function cleanupTemplateApiFixture(uid) {
  runBackendPython(
    `
import os

from backend.firebaseDB.firebase_service import get_firestore_client, init_firebase
from backend.firebaseDB.template_database import list_templates
from backend.services.template_cleanup_service import delete_saved_form_assets

uid = os.environ["PW_UID"]
init_firebase()
for template in list_templates(uid):
    delete_saved_form_assets(template.id, uid, hard_delete_link_records=True)
client = get_firestore_client()
client.collection("app_users").document(uid).delete()
print("ok")
`,
    { PW_UID: uid },
  );
}

async function openUploadView(page) {
  await retry('open upload view', 3, async () => {
    await page.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
    const uploadHeading = page.getByText('Upload PDF for Field Detection');
    if (await uploadHeading.isVisible().catch(() => false)) {
      return;
    }
    const tryNowButton = page.getByRole('button', { name: 'Try Now' });
    await tryNowButton.waitFor({ timeout: 30000 });
    await tryNowButton.click();
    await uploadHeading.waitFor({ timeout: 30000 });
  });
}

async function waitForSavedTemplate(page, templateName) {
  await page.locator('[aria-label="Filter saved forms by group"] select').waitFor({ timeout: 30000 });
  const loadingMessage = page.getByText('Loading saved forms while the backend starts…');
  if (await loadingMessage.isVisible().catch(() => false)) {
    await loadingMessage.waitFor({ state: 'hidden', timeout: 90000 });
  }
  await page.locator('[aria-label="Saved templates"] .saved-chip__content').filter({ hasText: templateName }).first().waitFor({
    timeout: 90000,
  });
}

async function waitForEditor(page) {
  await page.getByRole('button', { name: 'Save' }).waitFor({ timeout: 60000 });
}

function buildBasicAuthHeader(secret) {
  return `Basic ${Buffer.from(`${secret}:`).toString('base64')}`;
}

async function callPublicSchema(requestContext, schemaUrl, secret) {
  return requestContext.get(schemaUrl, {
    headers: {
      Authorization: buildBasicAuthHeader(secret),
    },
  });
}

async function callPublicFill(requestContext, fillUrl, secret, data) {
  return requestContext.post(fillUrl, {
    headers: {
      Authorization: buildBasicAuthHeader(secret),
      'Content-Type': 'application/json',
    },
    data: {
      data,
      strict: true,
    },
  });
}

async function getFreshOwnerIdToken(page) {
  const idToken = await page.evaluate(async () => {
    const authModule = await import('/src/services/auth.ts');
    return authModule.getFreshIdToken(true);
  });
  if (!idToken) {
    throw new Error('Unable to resolve an authenticated Firebase ID token for the signed-in owner.');
  }
  return idToken;
}

async function callOwnerEndpointSchema(requestContext, endpointId, idToken) {
  return requestContext.get(`${apiBaseUrl}/api/template-api-endpoints/${encodeURIComponent(endpointId)}/schema`, {
    headers: {
      Authorization: `Bearer ${idToken}`,
    },
  });
}

async function waitForTemplateApiDialog(page) {
  await page.getByRole('heading', { name: 'API Fill' }).waitFor({ timeout: 30000 });
  await page.getByText('Publish settings').waitFor({ timeout: 30000 });
}

async function readVisibleSecret(page) {
  await page.locator('.template-api-dialog__secret-row code').waitFor({ timeout: 30000 });
  const value = await page.locator('.template-api-dialog__secret-row code').textContent();
  return String(value || '').trim();
}

async function main() {
  fs.mkdirSync(artifactDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1600, height: 1400 },
  });
  const page = await context.newPage();

  let userFixture = null;
  let fixtureUid = null;
  let seeded = null;

  try {
    logStep('creating temporary Firebase user');
    await page.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
    userFixture = await createHybridEmailUser(page);
    fixtureUid = userFixture.uid;

    logStep('seeding saved template fixture');
    seeded = seedTemplateApiFixture({ uid: fixtureUid, email: userFixture.email });
    const customToken = createCustomToken(fixtureUid);

    logStep('signing in with custom token');
    await signInWithCustomTokenHarness(page, customToken);

    logStep('opening workspace and selecting saved template');
    await openUploadView(page);
    await waitForSavedTemplate(page, seeded.templateName);
    await page.locator('[aria-label="Saved templates"] .saved-chip__content').filter({ hasText: seeded.templateName }).first().click();
    await waitForEditor(page);

    logStep('opening API Fill manager');
    await page.getByRole('button', { name: 'API Fill' }).waitFor({ timeout: 30000 });
    await page.getByRole('button', { name: 'API Fill' }).click();
    await waitForTemplateApiDialog(page);

    logStep('publishing endpoint from the authenticated UI flow');
    await page.getByRole('button', { name: 'Generate key' }).click();
    await page.getByText('Shown once').waitFor({ timeout: 30000 });

    const firstSecret = await readVisibleSecret(page);
    if (!firstSecret.startsWith('dpa_live_')) {
      throw new Error(`Unexpected published secret prefix: ${firstSecret}`);
    }

    const fillUrl = String(await page.locator('.template-api-dialog__endpoint-row').nth(0).locator('code').textContent() || '').trim();
    const schemaUrl = String(await page.locator('.template-api-dialog__endpoint-row').nth(1).locator('code').textContent() || '').trim();
    if (!fillUrl || !schemaUrl) {
      throw new Error('Missing public endpoint URLs after publish.');
    }
    const endpointIdMatch = fillUrl.match(/\/fill\/([^/.]+)\.pdf$/);
    const endpointId = endpointIdMatch?.[1] || '';
    if (!endpointId) {
      throw new Error(`Unable to parse endpoint id from fill URL: ${fillUrl}`);
    }
    const ownerIdToken = await getFreshOwnerIdToken(page);

    logStep('verifying published public schema and fill routes');
    const schemaResponse = await callPublicSchema(context.request, schemaUrl, firstSecret);
    if (schemaResponse.status() !== 200) {
      throw new Error(`Expected schema route to succeed after publish, got ${schemaResponse.status()}`);
    }
    const schemaPayload = await schemaResponse.json();
    const scalarKeys = Array.isArray(schemaPayload?.schema?.fields)
      ? schemaPayload.schema.fields.map((field) => field?.key)
      : [];
    if (!scalarKeys.includes('api_fill_name')) {
      throw new Error(`Published schema did not include api_fill_name: ${JSON.stringify(schemaPayload)}`);
    }
    const schemaSnippetText = String(
      await page.locator('.template-api-dialog__card')
        .filter({ has: page.getByRole('heading', { name: 'Schema' }) })
        .locator('pre')
        .textContent() || '',
    ).trim();
    const displayedExamplePayload = JSON.parse(schemaSnippetText);
    const publishedExamplePayload = schemaPayload?.schema?.exampleData || {};
    if (JSON.stringify(displayedExamplePayload) !== JSON.stringify(publishedExamplePayload)) {
      throw new Error(
        `Displayed schema example payload drifted from the published schema. UI=${JSON.stringify(displayedExamplePayload)} schema=${JSON.stringify(publishedExamplePayload)}`,
      );
    }

    const fillResponse = await callPublicFill(context.request, fillUrl, firstSecret, displayedExamplePayload);
    if (fillResponse.status() !== 200) {
      throw new Error(`Expected fill route to succeed after publish, got ${fillResponse.status()}`);
    }
    const fillContentType = fillResponse.headers()['content-type'] || '';
    if (!fillContentType.toLowerCase().includes('application/pdf')) {
      throw new Error(`Unexpected fill content-type: ${fillContentType}`);
    }
    const fillBody = await fillResponse.body();
    if (!fillBody || fillBody.length === 0) {
      throw new Error('Fill route returned an empty PDF body.');
    }

    logStep('verifying strict-mode failure does not look like success to the owner');
    const strictFailureResponse = await callPublicFill(context.request, fillUrl, firstSecret, {
      ...displayedExamplePayload,
      ignored_key: 'should-fail',
    });
    if (strictFailureResponse.status() !== 400) {
      throw new Error(`Expected strict-mode unknown key failure, got ${strictFailureResponse.status()}`);
    }
    const strictFailurePayload = await strictFailureResponse.json();
    if (!String(strictFailurePayload?.detail || '').includes('Unknown API Fill keys')) {
      throw new Error(`Unexpected strict-mode failure payload: ${JSON.stringify(strictFailurePayload)}`);
    }

    const ownerSchemaResponse = await callOwnerEndpointSchema(context.request, endpointId, ownerIdToken);
    if (ownerSchemaResponse.status() !== 200) {
      throw new Error(`Expected owner endpoint schema route to succeed, got ${ownerSchemaResponse.status()}`);
    }
    const ownerSchemaPayload = await ownerSchemaResponse.json();
    if ((ownerSchemaPayload?.endpoint?.usageCount || 0) !== 1) {
      throw new Error(`Expected exactly one successful fill in owner metrics, got ${JSON.stringify(ownerSchemaPayload?.endpoint)}`);
    }
    if ((ownerSchemaPayload?.endpoint?.currentMonthUsageCount || 0) !== 1) {
      throw new Error(`Expected month usage count to stay at one after strict failure, got ${JSON.stringify(ownerSchemaPayload?.endpoint)}`);
    }
    if ((ownerSchemaPayload?.endpoint?.validationFailureCount || 0) < 1) {
      throw new Error(`Expected owner metrics to record at least one validation failure, got ${JSON.stringify(ownerSchemaPayload?.endpoint)}`);
    }
    const ownerEventTypes = Array.isArray(ownerSchemaPayload?.recentEvents)
      ? ownerSchemaPayload.recentEvents.map((event) => event?.eventType)
      : [];
    if (!ownerEventTypes.includes('fill_succeeded') || !ownerEventTypes.includes('fill_validation_failed')) {
      throw new Error(`Expected owner activity to include both success and validation failure events, got ${JSON.stringify(ownerEventTypes)}`);
    }

    logStep('rotating key from the authenticated UI flow');
    await page.getByRole('button', { name: 'Rotate key' }).click();
    await page.waitForFunction(
      (previousSecret) => {
        const nextValue = document.querySelector('.template-api-dialog__secret-row code')?.textContent?.trim() || '';
        return Boolean(nextValue) && nextValue !== previousSecret;
      },
      firstSecret,
      { timeout: 30000 },
    );
    const rotatedSecret = await readVisibleSecret(page);
    if (rotatedSecret === firstSecret) {
      throw new Error('Rotate key did not produce a new secret.');
    }

    const oldSchemaResponse = await callPublicSchema(context.request, schemaUrl, firstSecret);
    if (oldSchemaResponse.status() !== 401) {
      throw new Error(`Expected old secret to fail after rotate, got ${oldSchemaResponse.status()}`);
    }
    const rotatedSchemaResponse = await callPublicSchema(context.request, schemaUrl, rotatedSecret);
    if (rotatedSchemaResponse.status() !== 200) {
      throw new Error(`Expected rotated secret to work, got ${rotatedSchemaResponse.status()}`);
    }

    logStep('revoking endpoint from the authenticated UI flow');
    await page.getByRole('button', { name: 'Revoke' }).click();
    await page.getByRole('button', { name: 'Generate key' }).waitFor({ timeout: 30000 });
    if (await page.getByRole('button', { name: 'Copy URL' }).count() !== 0) {
      throw new Error('Revoked endpoint still exposed the public fill URL.');
    }

    const revokedSchemaResponse = await callPublicSchema(context.request, schemaUrl, rotatedSecret);
    if (revokedSchemaResponse.status() !== 401) {
      throw new Error(`Expected revoked secret to fail, got ${revokedSchemaResponse.status()}`);
    }

    await page.screenshot({ path: screenshotPath, fullPage: true });

    const summary = {
      ok: true,
      templateId: seeded.templateId,
      templateName: seeded.templateName,
      endpointId,
      fillUrl,
      schemaUrl,
      publishStatus: schemaResponse.status(),
      fillStatus: fillResponse.status(),
      strictFailureStatus: strictFailureResponse.status(),
      ownerUsageCount: ownerSchemaPayload.endpoint.usageCount,
      ownerValidationFailureCount: ownerSchemaPayload.endpoint.validationFailureCount || 0,
      rotateOldKeyStatus: oldSchemaResponse.status(),
      rotateNewKeyStatus: rotatedSchemaResponse.status(),
      revokeStatus: revokedSchemaResponse.status(),
      screenshotPath,
      summaryPath,
    };
    fs.writeFileSync(summaryPath, JSON.stringify(summary, null, 2), 'utf8');
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
    if (fixtureUid) {
      try {
        cleanupTemplateApiFixture(fixtureUid);
      } catch (error) {
        console.warn(`[playwright] cleanup failed for ${fixtureUid}: ${error instanceof Error ? error.message : String(error)}`);
      }
    }
    await page.close();
    await context.close();
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack || error.message : String(error));
  process.exitCode = 1;
});
