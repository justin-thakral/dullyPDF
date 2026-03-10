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
const backendUrl = process.env.PLAYWRIGHT_BACKEND_URL || 'http://127.0.0.1:8080';
const artifactDir = path.resolve(repoRoot, 'output/playwright');
const screenshotPath = path.join(artifactDir, 'fill-link-download-smoke.png');
const summaryPath = path.join(artifactDir, 'fill-link-download-smoke.json');
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

function logStep(message) {
  console.log(`[fill-link-download-smoke] ${message}`);
}

function setGodRole(email) {
  execFileSync('bash', ['-lc', './scripts/set-role-dev.sh --email "$PW_EMAIL" --role god'], {
    cwd: repoRoot,
    env: { ...process.env, PW_EMAIL: email },
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
  });
}

/**
 * Seeds a template, a fill link with respondent PDF download enabled,
 * and returns the public token and fixture metadata.
 */
function seedFillLinkDownloadFixture({ uid, email }) {
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
from backend.firebaseDB.fill_link_database import create_fill_link
from backend.services.fill_link_download_service import build_template_fill_link_download_snapshot

uid = os.environ["PW_UID"]
email = os.environ["PW_EMAIL"]
sample_pdf_path = os.environ["PW_SAMPLE_PDF_PATH"]

init_firebase()
client = get_firestore_client()
client.collection("app_users").document(uid).set(
    {
        "firebase_uid": uid,
        "email": email,
        "displayName": "Fill Link Download Smoke User",
        "role": "god",
    },
    merge=True,
)

reader = PdfReader(sample_pdf_path)
page_count = len(reader.pages)
page_sizes = {}
for page_number, page in enumerate(reader.pages, start=1):
    width = float(page.mediabox.width)
    height = float(page.mediabox.height)
    page_sizes[str(page_number)] = {"width": width, "height": height}

copied_pdf_path = None
with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_pdf:
    shutil.copyfile(sample_pdf_path, temp_pdf.name)
    copied_pdf_path = temp_pdf.name

try:
    pdf_path = upload_form_pdf(copied_pdf_path, f"users/{uid}/saved-forms/download-smoke.pdf")
    template_path = upload_template_pdf(copied_pdf_path, f"users/{uid}/templates/download-smoke.pdf")

    metadata = {"name": "Download Smoke Template"}
    template = create_template(uid, pdf_path, template_path, metadata=metadata)

    fields = [
        {
            "id": "field-patient-name",
            "name": "patient_name",
            "type": "text",
            "page": 1,
            "rect": {"x": 72.0, "y": 120.0, "width": 180.0, "height": 18.0},
            "value": None,
        },
        {
            "id": "field-date-of-birth",
            "name": "date_of_birth",
            "type": "text",
            "page": 1,
            "rect": {"x": 72.0, "y": 160.0, "width": 180.0, "height": 18.0},
            "value": None,
        },
    ]

    snapshot = build_template_fill_link_download_snapshot(
        template=template,
        fields=fields,
    )

    questions = [
        {
            "key": "respondent_identifier",
            "label": "Respondent Name or ID",
            "type": "text",
            "requiredForRespondentIdentity": True,
        },
        {
            "key": "patient_name",
            "label": "Patient Name",
            "type": "text",
        },
        {
            "key": "date_of_birth",
            "label": "Date of Birth",
            "type": "text",
        },
    ]

    link = create_fill_link(
        uid,
        scope_type="template",
        template_id=template.id,
        template_name="Download Smoke Template",
        template_ids=[template.id],
        title="Download Smoke Link",
        questions=questions,
        require_all_fields=False,
        max_responses=100,
        respondent_pdf_download_enabled=True,
        respondent_pdf_snapshot=snapshot,
    )

    print(json.dumps({
        "templateId": template.id,
        "linkId": link.id,
        "publicToken": link.public_token,
        "questions": questions,
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

function cleanupFillLinkDownloadFixture(uid) {
  runBackendPython(
    `
import os

from backend.firebaseDB.fill_link_database import delete_fill_link, list_fill_links
from backend.firebaseDB.firebase_service import get_firestore_client, init_firebase
from backend.firebaseDB.template_database import delete_template, list_templates

uid = os.environ["PW_UID"]
init_firebase()
for record in list_fill_links(uid):
    delete_fill_link(record.id, uid)
for record in list_templates(uid):
    delete_template(record.id, uid)
client = get_firestore_client()
client.collection("app_users").document(uid).delete()
print("ok")
`,
    { PW_UID: uid },
  );
}

async function main() {
  fs.mkdirSync(artifactDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1400, height: 1000 },
    acceptDownloads: true,
  });
  const page = await context.newPage();

  let userFixture = null;
  let fixtureUid = null;
  let seeded = null;

  try {
    // ── Step 1: Create test user and seed data ──
    logStep('creating temporary Firebase user');
    await page.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
    userFixture = await createHybridEmailUser(page);
    fixtureUid = userFixture.uid;
    logStep(`promoting ${userFixture.email} to god role`);
    setGodRole(userFixture.email);
    logStep('seeding template, fill link, and snapshot');
    seeded = seedFillLinkDownloadFixture({ uid: fixtureUid, email: userFixture.email });
    logStep(`seeded link ${seeded.linkId} with token ${seeded.publicToken}`);

    // ── Step 2: Navigate to the public fill link page ──
    const publicUrl = `${baseUrl}/fill/${seeded.publicToken}`;
    logStep(`navigating to public fill link page: ${publicUrl}`);
    await page.goto(publicUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });

    // ── Step 3: Verify the download hint text is visible (pre-submit) ──
    logStep('verifying pre-submit download hint is visible');
    await retry('check download hint', 10, async () => {
      const hintText = page.getByText('PDF copy available after submit');
      const visible = await hintText.isVisible().catch(() => false);
      if (!visible) {
        throw new Error('Expected "PDF copy available after submit" hint to be visible');
      }
    });

    // ── Step 4: Verify the download button is NOT visible before submit ──
    logStep('verifying download button is NOT visible before submit');
    const downloadSection = page.locator('[aria-label="Submitted PDF download"]');
    const downloadSectionVisible = await downloadSection.isVisible().catch(() => false);
    if (downloadSectionVisible) {
      throw new Error('Download section should NOT be visible before submit');
    }

    // ── Step 5: Fill out the form ──
    logStep('filling out the form');
    await retry('fill form', 5, async () => {
      const nameInput = page.getByLabel('Respondent Name or ID');
      await nameInput.waitFor({ timeout: 15000 });
      await nameInput.fill('John Doe Smoke Test');

      const patientInput = page.getByLabel('Patient Name');
      await patientInput.fill('Jane Patient');

      const dobInput = page.getByLabel('Date of Birth');
      await dobInput.fill('1990-01-15');
    });

    // ── Step 6: Submit the form ──
    logStep('submitting the form');
    const submitButton = page.getByRole('button', { name: 'Submit' });
    await submitButton.click();

    // ── Step 7: Wait for success message ──
    logStep('waiting for success message');
    await retry('wait for success', 15, async () => {
      const successText = page.getByText('Your response was submitted');
      const visible = await successText.isVisible().catch(() => false);
      if (!visible) {
        throw new Error('Success message not yet visible');
      }
    });

    // ── Step 8: Verify the download section IS visible after submit ──
    logStep('verifying download section is visible after submit');
    await retry('check download section', 10, async () => {
      const visible = await downloadSection.isVisible().catch(() => false);
      if (!visible) {
        throw new Error('Download section should be visible after submit');
      }
    });

    const downloadHeading = page.getByText('Download your submitted PDF');
    const headingVisible = await downloadHeading.isVisible().catch(() => false);
    if (!headingVisible) {
      throw new Error('Download heading "Download your submitted PDF" not visible');
    }

    // ── Step 9: Click the download button and verify PDF blob is received ──
    logStep('clicking download button');
    const downloadButton = page.getByRole('button', { name: 'Download submitted PDF' });
    await downloadButton.waitFor({ timeout: 10000 });

    const downloadPromise = page.waitForEvent('download', { timeout: 60000 });
    await downloadButton.click();

    logStep('waiting for download to start');
    const download = await downloadPromise;
    const suggestedFilename = download.suggestedFilename();
    logStep(`download started: ${suggestedFilename}`);

    if (!suggestedFilename.endsWith('.pdf')) {
      throw new Error(`Expected PDF filename, got: ${suggestedFilename}`);
    }

    const downloadPath = path.join(artifactDir, suggestedFilename);
    await download.saveAs(downloadPath);
    const stat = fs.statSync(downloadPath);
    logStep(`downloaded file size: ${stat.size} bytes`);

    if (stat.size < 500) {
      throw new Error(`Downloaded PDF is suspiciously small: ${stat.size} bytes`);
    }

    // ── Step 10: Verify button doesn't show loading state after completion ──
    logStep('verifying button returns to normal state after download');
    await retry('button normal state', 10, async () => {
      const buttonText = await downloadButton.textContent();
      if (buttonText.includes('Preparing')) {
        throw new Error('Button still showing loading state');
      }
    });

    await page.screenshot({ path: screenshotPath, fullPage: true });

    const summary = {
      ok: true,
      uid: fixtureUid,
      email: userFixture.email,
      linkId: seeded.linkId,
      publicToken: seeded.publicToken,
      downloadedFilename: suggestedFilename,
      downloadedFileSize: stat.size,
      screenshotPath,
      summaryPath,
    };
    fs.writeFileSync(summaryPath, JSON.stringify(summary, null, 2));
    console.log(JSON.stringify(summary));
    logStep('PASSED');
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
        cleanupFillLinkDownloadFixture(fixtureUid);
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
