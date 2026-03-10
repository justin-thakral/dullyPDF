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
const artifactDir = path.resolve(repoRoot, 'output/playwright');
const screenshotPath = path.join(artifactDir, 'saved-form-snapshot-smoke.png');
const summaryPath = path.join(artifactDir, 'saved-form-snapshot-smoke.json');
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
  console.log(`[saved-form-snapshot-smoke] ${message}`);
}

function setGodRole(email) {
  execFileSync('bash', ['-lc', './scripts/set-role-dev.sh --email "$PW_EMAIL" --role god'], {
    cwd: repoRoot,
    env: { ...process.env, PW_EMAIL: email },
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
  });
}

function seedSavedFormSnapshotFixture({ uid, email }) {
  const output = runBackendPython(
    `
import json
import os
import re
import shutil
import tempfile

from pypdf import PdfReader

from backend.firebaseDB.firebase_service import get_firestore_client, init_firebase
from backend.firebaseDB.group_database import create_group
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
        "displayName": "Snapshot Smoke User",
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

templates = [
    {"slug": "alpha", "name": "Alpha Packet", "field_name": "alpha_patient_name", "x": 72.0, "y": 120.0},
    {"slug": "bravo", "name": "Bravo Packet", "field_name": "bravo_policy_number", "x": 72.0, "y": 180.0},
    {"slug": "charlie", "name": "Charlie Packet", "field_name": "charlie_follow_up_code", "x": 72.0, "y": 240.0},
]

created_templates = []
copied_pdf_path = None
with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_pdf:
    shutil.copyfile(sample_pdf_path, temp_pdf.name)
    copied_pdf_path = temp_pdf.name

try:
    for index, template in enumerate(templates, start=1):
        pdf_path = upload_form_pdf(copied_pdf_path, f"users/{uid}/saved-forms/{template['slug']}.pdf")
        template_path = upload_template_pdf(copied_pdf_path, f"users/{uid}/templates/{template['slug']}.pdf")
        snapshot_payload = {
            "version": 1,
            "pageCount": page_count,
            "pageSizes": page_sizes,
            "fields": [
                {
                    "id": f"{template['slug']}-field-1",
                    "name": template["field_name"],
                    "type": "text",
                    "page": 1,
                    "rect": {
                        "x": template["x"],
                        "y": template["y"],
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
            form_id=f"{uid}-{template['slug']}",
            timestamp_ms=1741600000000 + index,
            snapshot=snapshot_payload,
        )
        metadata = {
            "name": template["name"],
            "editorSnapshot": snapshot_manifest,
        }
        record = create_template(
            uid,
            pdf_path,
            template_path,
            metadata=metadata,
        )
        created_templates.append({
            "id": record.id,
            "name": template["name"],
            "fieldName": template["field_name"],
            "snapshotPath": snapshot_path,
        })

    group = create_group(
        uid,
        name="Admissions Snapshot Group",
        template_ids=[created_templates[0]["id"], created_templates[1]["id"]],
    )

    print(json.dumps({
        "groupId": group.id,
        "groupName": group.name,
        "templates": created_templates,
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

function cleanupSavedFormSnapshotFixture(uid) {
  runBackendPython(
    `
import os

from backend.firebaseDB.firebase_service import get_firestore_client, init_firebase
from backend.firebaseDB.group_database import list_groups, delete_group
from backend.firebaseDB.template_database import list_templates
from backend.services.template_cleanup_service import delete_saved_form_assets

uid = os.environ["PW_UID"]
init_firebase()
for group in list_groups(uid):
    delete_group(group.id, uid)
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

async function waitForSavedBrowser(page, expectedNames) {
  logStep('waiting for saved-form browser');
  await page.locator('[aria-label="Filter saved forms by group"] select').waitFor({ timeout: 30000 });
  const loadingMessage = page.getByText('Loading saved forms while the backend starts…');
  if (await loadingMessage.isVisible().catch(() => false)) {
    await loadingMessage.waitFor({ state: 'hidden', timeout: 90000 });
  }
  for (const name of expectedNames) {
    await page.locator('[aria-label="Saved templates"] .saved-chip__label').filter({ hasText: name }).first().waitFor({
      timeout: 90000,
    });
  }
}

async function readSelectedOptionText(locator) {
  return locator.evaluate((element) => {
    if (!(element instanceof HTMLSelectElement)) {
      throw new Error('Expected select element.');
    }
    return element.selectedOptions.item(0)?.textContent?.trim() || '';
  });
}

async function readVisibleTemplateNames(page) {
  return page.locator('[aria-label="Saved templates"] .saved-chip__label').allTextContents();
}

async function waitForFieldListName(page, fieldName) {
  await page.locator('.field-list .field-row__name').filter({ hasText: fieldName }).first().waitFor({
    timeout: 30000,
  });
}

async function waitForGroupTemplateOptionReady(page, templateId) {
  const selector = page.locator('select.ui-group-select');
  await retry(`wait for group template option ${templateId}`, 20, async () => {
    const optionState = await selector.evaluate((element, expectedTemplateId) => {
      if (!(element instanceof HTMLSelectElement)) {
        throw new Error('Expected group select element.');
      }
      const option = Array.from(element.options).find((entry) => entry.value === expectedTemplateId) ?? null;
      if (!option) {
        return { exists: false, disabled: true, label: '' };
      }
      return {
        exists: true,
        disabled: option.disabled,
        label: option.textContent?.trim() || '',
      };
    }, templateId);

    if (!optionState.exists || optionState.disabled || optionState.label.includes('Preparing')) {
      throw new Error(`Template option not ready yet: ${JSON.stringify(optionState)}`);
    }
  });
}

async function assertFilteredTemplateNames(page, expectedNames) {
  await retry('assert filtered template names', 10, async () => {
    const visibleNames = (await readVisibleTemplateNames(page))
      .map((value) => value.trim())
      .filter(Boolean)
      .sort();
    const sortedExpected = [...expectedNames].sort();
    if (visibleNames.join('|') !== sortedExpected.join('|')) {
      throw new Error(`Expected templates ${sortedExpected.join(', ')}, received ${visibleNames.join(', ')}`);
    }
  });
}

async function main() {
  fs.mkdirSync(artifactDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1200 } });

  let userFixture = null;
  let fixtureUid = null;
  let seeded = null;

  try {
    logStep('creating temporary Firebase user');
    await page.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
    userFixture = await createHybridEmailUser(page);
    fixtureUid = userFixture.uid;
    logStep(`promoting ${userFixture.email} to god role`);
    setGodRole(userFixture.email);
    logStep('seeding saved forms, snapshots, and group fixture');
    seeded = seedSavedFormSnapshotFixture({ uid: fixtureUid, email: userFixture.email });
    const customToken = createCustomToken(fixtureUid);

    logStep('signing in with custom token');
    await signInWithCustomTokenHarness(page, customToken);
    logStep('opening upload view');
    await openUploadView(page);
    await waitForSavedBrowser(page, seeded.templates.map((template) => template.name));

    const filterSelect = page.locator('[aria-label="Filter saved forms by group"] select');
    logStep(`selecting saved-form filter ${seeded.groupName}`);
    await filterSelect.selectOption(seeded.groupId);
    await retry('wait for selected group filter label', 10, async () => {
      const selectedText = await readSelectedOptionText(filterSelect);
      if (selectedText !== seeded.groupName) {
        throw new Error(`Unexpected selected group label: ${selectedText}`);
      }
    });

    await assertFilteredTemplateNames(page, [
      seeded.templates[0].name,
      seeded.templates[1].name,
    ]);

    const groupToggle = page.getByRole('checkbox', { name: /Switch to groups/i });
    logStep('toggling into group list');
    await groupToggle.click();
    await page.locator('[aria-label="Saved form groups"]').waitFor({ timeout: 30000 });

    const templateToggle = page.getByRole('checkbox', { name: /Switch to templates/i });
    logStep('toggling back to template list');
    await templateToggle.click();
    await page.locator('[aria-label="Saved templates"]').waitFor({ timeout: 30000 });

    const selectedAfterToggle = await readSelectedOptionText(filterSelect);
    if (selectedAfterToggle !== seeded.groupName) {
      throw new Error(`Selected group label did not persist after toggle. Found: ${selectedAfterToggle}`);
    }

    await assertFilteredTemplateNames(page, [
      seeded.templates[0].name,
      seeded.templates[1].name,
    ]);

    logStep('opening seeded group');
    await groupToggle.click();
    const groupOpenStart = Date.now();
    await page.getByRole('button', { name: new RegExp(`^${seeded.groupName}`) }).click();
    await page.getByRole('button', { name: 'Save' }).waitFor({ timeout: 60000 });
    const groupOpenMs = Date.now() - groupOpenStart;

    await waitForFieldListName(page, seeded.templates[0].fieldName);
    const groupSelector = page.locator('select.ui-group-select');
    await groupSelector.waitFor({ timeout: 30000 });

    const initialGroupTemplateLabel = await readSelectedOptionText(groupSelector);
    if (!initialGroupTemplateLabel.startsWith(seeded.templates[0].name)) {
      throw new Error(`Expected the group to open on ${seeded.templates[0].name}, found ${initialGroupTemplateLabel}`);
    }

    logStep(`waiting for ${seeded.templates[1].name} to finish preparing`);
    await waitForGroupTemplateOptionReady(page, seeded.templates[1].id);
    logStep(`switching group template to ${seeded.templates[1].name}`);
    const switchTemplateStart = Date.now();
    await groupSelector.selectOption(seeded.templates[1].id);
    await waitForFieldListName(page, seeded.templates[1].fieldName);
    const switchTemplateMs = Date.now() - switchTemplateStart;

    const switchedTemplateLabel = await readSelectedOptionText(groupSelector);
    if (!switchedTemplateLabel.startsWith(seeded.templates[1].name)) {
      throw new Error(`Expected the group selector to switch to ${seeded.templates[1].name}, found ${switchedTemplateLabel}`);
    }

    await page.screenshot({ path: screenshotPath, fullPage: true });

    const summary = {
      ok: true,
      uid: fixtureUid,
      email: userFixture.email,
      groupId: seeded.groupId,
      groupName: seeded.groupName,
      groupOpenMs,
      switchTemplateMs,
      screenshotPath,
      summaryPath,
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
    if (fixtureUid) {
      try {
        cleanupSavedFormSnapshotFixture(fixtureUid);
      } catch (error) {
        console.warn(`[playwright] cleanup failed for ${fixtureUid}: ${error instanceof Error ? error.message : String(error)}`);
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
