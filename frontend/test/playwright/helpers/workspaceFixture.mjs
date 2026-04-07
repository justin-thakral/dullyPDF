import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

export const repoRoot = process.cwd();
export const defaultFillableSamplePdfPath = path.resolve(
  repoRoot,
  'quickTestFiles/dentalintakeform_d1c394f594.pdf',
);

export function sleep(durationMs) {
  return new Promise((resolve) => {
    setTimeout(resolve, durationMs);
  });
}

export async function retry(label, attempts, fn) {
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

function normalizeNameToken(value) {
  return String(value || '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');
}

export function parseJsonPostData(requestOrResponse) {
  const request = typeof requestOrResponse?.postData === 'function'
    ? requestOrResponse
    : requestOrResponse?.request?.();
  const postData = request?.postData?.();
  if (!postData) {
    return null;
  }
  try {
    return JSON.parse(postData);
  } catch {
    return null;
  }
}

export function buildMockRenameResult(templateFields = []) {
  const renameTargets = [
    'patient_full_name',
    'patient_first_name',
    'patient_last_name',
    'patient_date_of_birth',
    'patient_phone',
    'patient_email',
    'patient_signature_name',
    'patient_address',
  ];
  const fields = Array.isArray(templateFields) && templateFields.length > 0
    ? templateFields
    : [{ name: 'field_1', type: 'text', page: 1 }];
  const renamedFields = fields.map((field, index) => {
    const originalName = String(field?.name || `field_${index + 1}`);
    const fallbackName = normalizeNameToken(originalName) || `field_${index + 1}`;
    const renamedName = renameTargets[index] || `${fallbackName}_renamed`;
    const fieldType = String(field?.type || '').toLowerCase();
    const baseRename = {
      ...field,
      originalName,
      name: renamedName,
      renameConfidence: 0.98,
    };
    if (fieldType !== 'checkbox') {
      return baseRename;
    }
    return {
      ...baseRename,
      groupKey: 'patient_consent',
      optionKey: index % 2 === 0 ? 'yes' : 'no',
      optionLabel: index % 2 === 0 ? 'Yes' : 'No',
      groupLabel: 'Patient Consent',
    };
  });

  const checkboxRules = renamedFields.some((field) => String(field?.type || '').toLowerCase() === 'checkbox')
    ? [
      {
        databaseField: 'patient_consent',
        groupKey: 'patient_consent',
        operation: 'yes_no',
        trueOption: 'yes',
        falseOption: 'no',
        confidence: 0.95,
      },
    ]
    : [];

  return {
    success: true,
    status: 'complete',
    fields: renamedFields,
    checkboxRules,
  };
}

export function buildMockMappingResult(templateFields = []) {
  const mappingTargets = [
    'full_name',
    'date',
    'signature_name',
    'phone',
    'email',
  ];
  const fields = Array.isArray(templateFields) ? templateFields : [];
  const mappings = fields.slice(0, mappingTargets.length).map((field, index) => ({
    originalPdfField: String(field?.name || `field_${index + 1}`),
    pdfField: mappingTargets[index],
    confidence: 0.97,
  }));

  return {
    success: true,
    status: 'complete',
    mappingResults: {
      mappings,
      checkboxRules: [],
      radioGroupSuggestions: [],
      textTransformRules: [],
      fillRules: {
        checkboxRules: [],
        textTransformRules: [],
      },
      identifierKey: mappings[0]?.pdfField || null,
    },
  };
}

export function setGodRole(email) {
  execFileSync('bash', ['-lc', './scripts/set-role-dev.sh --email "$PW_EMAIL" --role god'], {
    cwd: repoRoot,
    env: { ...process.env, PW_EMAIL: email },
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
  });
}

export async function openUploadView(page, baseUrl) {
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

export async function waitForEditorReady(page) {
  await page.getByRole('button', { name: 'Save' }).waitFor({ timeout: 60000 });
  await page.locator('.field-list .field-row__name').first().waitFor({ timeout: 60000 });
}

export async function uploadFillablePdfAndWaitForEditor(page, baseUrl, pdfPath = defaultFillableSamplePdfPath) {
  if (!fs.existsSync(pdfPath)) {
    throw new Error(`Missing sample fillable PDF: ${pdfPath}`);
  }
  await openUploadView(page, baseUrl);
  await page.getByLabel('Upload Fillable PDF Template').setInputFiles(pdfPath);
  await waitForEditorReady(page);
}

export async function collectFieldNames(page) {
  return page.locator('.field-list .field-row__name').evaluateAll((nodes) => {
    return nodes
      .map((node) => node.textContent?.trim() || '')
      .filter(Boolean);
  });
}

export async function getCurrentAuthToken(page) {
  return page.evaluate(async () => {
    const { firebaseAuth } = await import('/src/services/firebaseClient.ts');
    const user = firebaseAuth.currentUser;
    if (!user) {
      throw new Error('Expected an authenticated Firebase user for Playwright.');
    }
    return user.getIdToken(true);
  });
}

export async function signInFromHomepageAndOpenProfile(page, {
  baseUrl,
  loginEmail,
  loginPassword,
  logStep = () => {},
}) {
  if (!loginEmail || !loginPassword) {
    throw new Error('SMOKE_LOGIN_EMAIL and SMOKE_LOGIN_PASSWORD are required for the localhost auth smoke.');
  }

  const signInButton = page.getByRole('button', { name: 'Sign in', exact: true });
  const openProfileButton = page.getByTitle('Open profile');
  const signInHeading = page.getByRole('heading', { name: 'Sign in to DullyPDF' });

  logStep('opening homepage');
  await page.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });

  await Promise.race([
    signInButton.waitFor({ timeout: 60000 }),
    openProfileButton.waitFor({ timeout: 60000 }),
  ]);

  if (await signInButton.isVisible().catch(() => false)) {
    logStep(`signing in as ${loginEmail}`);
    await signInButton.click();
    await signInHeading.waitFor({ timeout: 30000 });

    const signInResponsePromise = page.waitForResponse((response) => {
      return response.request().method() === 'POST'
        && response.url().includes('identitytoolkit.googleapis.com')
        && response.url().includes('accounts:signInWithPassword');
    }, { timeout: 60000 });

    await page.getByLabel('Email').fill(loginEmail);
    await page.getByLabel('Password').fill(loginPassword);
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();

    const signInResponse = await signInResponsePromise;
    if (!signInResponse.ok()) {
      throw new Error(`Password sign-in failed with status ${signInResponse.status()}.`);
    }
    await page.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => {});
    await openProfileButton.waitFor({ timeout: 60000 });
  }

  logStep('opening profile');
  await openProfileButton.click();
  await page.getByText('Account overview').waitFor({ timeout: 60000 });
  await page.getByRole('heading', { level: 1 }).waitFor({ timeout: 60000 });
  await page.getByRole('button', { name: 'Return to workspace' }).waitFor({ timeout: 60000 });
}

export async function pollOpenAiJob(page, { apiBaseUrl, resource, jobId, attempts = 120 }) {
  return retry(`poll ${resource} job ${jobId}`, attempts, async () => {
    const token = await getCurrentAuthToken(page);
    const response = await fetch(`${apiBaseUrl}/api/${resource}/ai/${jobId}`, {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(`OpenAI job poll failed (${response.status}): ${JSON.stringify(payload)}`);
    }
    const status = String(payload?.status || '').toLowerCase();
    if (status === 'failed') {
      throw new Error(`OpenAI job ${jobId} failed: ${JSON.stringify(payload)}`);
    }
    if (status !== 'complete' || !payload?.success) {
      throw new Error(`Waiting for OpenAI job ${jobId} to complete.`);
    }
    return payload;
  });
}
