import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';

const repoRoot = process.cwd();
const baseUrl = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5173';
const apiBaseUrl = process.env.PLAYWRIGHT_API_URL || 'http://127.0.0.1:8000';
const artifactDir = path.resolve(repoRoot, 'output/playwright');
const screenshotPath = path.join(artifactDir, 'workspace-dialog-regression.png');
const summaryPath = path.join(artifactDir, 'workspace-dialog-regression.json');

const email = requireEnv('DULLYPDF_E2E_EMAIL');
const password = requireEnv('DULLYPDF_E2E_PASSWORD');

const detectPdfPath = resolveRequiredPath(
  process.env.PW_DETECT_PDF || 'quickTestFiles/dentalintakeform_d1c394f594.pdf',
);
const fillablePdfPath = resolveRequiredPath(
  process.env.PW_FILLABLE_PDF || 'quickTestFiles/cms1500_06_03d2696ed5.pdf',
);
const groupName = `Dialog Regression ${Date.now()}`;
const savedFormNameA = `Dialog Saved A ${Date.now()}`;
const savedFormNameB = `Dialog Saved B ${Date.now()}`;
const processingChecks = [];
const dialogChecks = [];
const fillLinkRecaptchaAction = process.env.PW_FILL_LINK_RECAPTCHA_ACTION?.trim() || 'fill_link_submit';
const recaptchaSiteKey = (() => {
  const explicit = process.env.PW_RECAPTCHA_SITE_KEY?.trim();
  if (explicit) {
    return explicit;
  }
  return readEnvValueFromFile(path.resolve(repoRoot, 'env/backend.dev.env'), 'RECAPTCHA_SITE_KEY');
})();

function logStep(message) {
  console.log(`[workspace-dialog-regression] ${message}`);
}

function requireEnv(name) {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return value;
}

function resolveRequiredPath(relativeOrAbsolutePath) {
  const resolved = path.resolve(repoRoot, relativeOrAbsolutePath);
  if (!fs.existsSync(resolved)) {
    throw new Error(`Missing required file: ${resolved}`);
  }
  return resolved;
}

function readEnvValueFromFile(filePath, key) {
  if (!fs.existsSync(filePath)) {
    return '';
  }
  const contents = fs.readFileSync(filePath, 'utf8');
  const match = contents.match(new RegExp(`^${key}=(.*)$`, 'm'));
  if (!match) {
    return '';
  }
  const rawValue = match[1].trim();
  if (
    (rawValue.startsWith('"') && rawValue.endsWith('"'))
    || (rawValue.startsWith("'") && rawValue.endsWith("'"))
  ) {
    return rawValue.slice(1, -1);
  }
  return rawValue;
}

function sleep(durationMs) {
  return new Promise((resolve) => {
    setTimeout(resolve, durationMs);
  });
}

async function delayBackendRequests(page, delayMs = 350) {
  await page.route('http://localhost:8000/**', async (route) => {
    await sleep(delayMs);
    await route.continue();
  });
}

async function signIn(page) {
  await page.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForFunction(() => {
    const isVisible = (element) => {
      if (!(element instanceof HTMLElement)) {
        return false;
      }
      const style = window.getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
    };

    const emailInput = document.querySelector('#auth-email');
    const uploadHeading = Array.from(document.querySelectorAll('*')).find((element) => element.textContent?.trim() === 'Upload PDF for Field Detection');
    const tryNowButton = Array.from(document.querySelectorAll('button'))
      .find((button) => button.textContent?.trim() === 'Try Now');
    const signInButton = Array.from(document.querySelectorAll('button'))
      .find((button) => button.textContent?.trim() === 'Sign in');

    return isVisible(emailInput) || isVisible(uploadHeading) || isVisible(tryNowButton) || isVisible(signInButton);
  }, { timeout: 30000 });
  const emailField = page.getByLabel('Email');
  const uploadHeading = page.getByText('Upload PDF for Field Detection');
  const isAlreadyAtLogin = await emailField.isVisible().catch(() => false);
  if (!isAlreadyAtLogin) {
    const tryNowButton = page.getByRole('button', { name: 'Try Now' }).first();
    const headerSignIn = page.locator('.signin-button').first();
    if (await tryNowButton.isVisible().catch(() => false)) {
      await tryNowButton.click();
    } else if (await headerSignIn.isVisible().catch(() => false)) {
      await headerSignIn.click();
    } else if (await uploadHeading.isVisible().catch(() => false)) {
      return;
    } else {
      throw new Error('Unable to find a visible workspace entry button.');
    }

    await Promise.race([
      emailField.waitFor({ state: 'visible', timeout: 30000 }),
      uploadHeading.waitFor({ state: 'visible', timeout: 30000 }),
    ]);
  }

  if (await uploadHeading.isVisible().catch(() => false)) {
    return;
  }

  await emailField.fill(email);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.getByRole('button', { name: 'Try Now' }).waitFor({ timeout: 30000 });
}

async function openUploadView(page) {
  const uploadHeading = page.getByText('Upload PDF for Field Detection');
  if (await uploadHeading.isVisible().catch(() => false)) {
    return;
  }

  const homeButton = page.getByRole('button', { name: 'Home' });
  const tryNowButton = page.getByRole('button', { name: 'Try Now' });
  if (await homeButton.isVisible().catch(() => false)) {
    await homeButton.click();
    await page.waitForTimeout(300);
    const uploadVisibleAfterHomeClick = await uploadHeading.isVisible().catch(() => false);
    const homepageReadyAfterHomeClick = await tryNowButton.isVisible().catch(() => false);
    if (!uploadVisibleAfterHomeClick && !homepageReadyAfterHomeClick && await homeButton.isVisible().catch(() => false)) {
      await page.locator('.back-button').evaluate((button) => {
        if (button instanceof HTMLButtonElement) {
          button.click();
        }
      });
      await page.waitForTimeout(300);
    }
    if (await uploadHeading.isVisible().catch(() => false)) {
      return;
    }
  }

  if (!(await tryNowButton.isVisible().catch(() => false))) {
    await page.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
  }
  await tryNowButton.waitFor({ timeout: 30000 });
  await tryNowButton.click();
  const uploadVisibleAfterFirstClick = await uploadHeading.isVisible().catch(() => false);
  if (!uploadVisibleAfterFirstClick) {
    await page.waitForTimeout(500);
    if (!(await uploadHeading.isVisible().catch(() => false))) {
      await page.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await tryNowButton.waitFor({ timeout: 30000 });
      await tryNowButton.click();
    }
  }
  await uploadHeading.waitFor({ timeout: 30000 });
}

async function waitForEditor(page, options = {}) {
  const saveButton = page.getByRole('button', { name: 'Save' });
  await saveButton.waitFor({ timeout: options.timeoutMs || 60000 });
  return saveButton;
}

async function assertProcessingCopy(page, heading, detail) {
  await page.waitForFunction(
    ([expectedHeading, expectedDetail]) => {
      const events = Array.isArray(window.__PW_PROCESSING_EVENTS__)
        ? window.__PW_PROCESSING_EVENTS__
        : [];
      return events.some((entry) => entry?.heading === expectedHeading && entry?.detail === expectedDetail);
    },
    [heading, detail],
    { timeout: 30000 },
  );
  processingChecks.push({ heading, detail });
}

async function auditDialog(page, selector, label) {
  await page.locator(selector).waitFor({ state: 'visible', timeout: 20000 });
  const metrics = await page.evaluate((dialogSelector) => {
    const dialog = document.querySelector(dialogSelector);
    if (!(dialog instanceof HTMLElement)) {
      throw new Error(`Dialog not found for selector: ${dialogSelector}`);
    }
    const backdrop = dialog.closest('.ui-dialog-backdrop');
    if (!(backdrop instanceof HTMLElement)) {
      throw new Error(`Backdrop missing for selector: ${dialogSelector}`);
    }
    const dialogRect = dialog.getBoundingClientRect();
    const header = document.querySelector('.ui-header, .app-header');
    const headerRect = header instanceof HTMLElement ? header.getBoundingClientRect() : null;
    const probeX = dialogRect.left + Math.min(48, Math.max(1, dialogRect.width / 2));
    const probeY = dialogRect.top + Math.min(24, Math.max(1, dialogRect.height / 2));
    const topElement = document.elementsFromPoint(probeX, probeY)[0];
    const backdropStyle = window.getComputedStyle(backdrop);
    const dialogStyle = window.getComputedStyle(dialog);
    return {
      backdropColor: backdropStyle.backgroundColor,
      backdropFilter: backdropStyle.backdropFilter,
      backdropOpacity: backdropStyle.opacity,
      bodyLocked: document.body.classList.contains('ui-dialog-open'),
      dialogTop: dialogRect.top,
      dialogLeft: dialogRect.left,
      dialogZIndex: dialogStyle.zIndex,
      headerBottom: headerRect ? headerRect.bottom : null,
      topElementInsideDialog: topElement instanceof Element ? dialog.contains(topElement) : false,
    };
  }, selector);

  if (!metrics.bodyLocked) {
    throw new Error(`${label}: body scroll lock is missing.`);
  }
  if (metrics.backdropColor === 'rgba(0, 0, 0, 0)' || metrics.backdropOpacity === '0') {
    throw new Error(`${label}: backdrop is transparent.`);
  }
  if (!metrics.topElementInsideDialog) {
    throw new Error(`${label}: dialog is not topmost at the probe point.`);
  }

  dialogChecks.push({ label, selector, ...metrics });
}

async function refreshSavedAssets(page, expectedTemplateNames = []) {
  await page.locator('[aria-label="Filter saved forms by group"]').waitFor({ timeout: 30000 });
  const loadingMessage = page.getByText('Loading saved forms while the backend starts…');
  if (await loadingMessage.isVisible().catch(() => false)) {
    await loadingMessage.waitFor({ state: 'hidden', timeout: 90000 });
  }
  const savedTemplates = page.locator('[aria-label="Saved templates"] .saved-chip__content');
  if (expectedTemplateNames.length === 0) {
    await savedTemplates.first().waitFor({ timeout: 90000 });
    return savedTemplates;
  }
  for (const expectedName of expectedTemplateNames) {
    await savedTemplates.filter({ hasText: expectedName }).first().waitFor({ timeout: 90000 });
  }
  return savedTemplates;
}

async function waitForSavedFormVisible(page, formName) {
  await openUploadView(page);
  await refreshSavedAssets(page, [formName]);
}

async function submitSavePrompt(page, saveName) {
  const saveRequest = page.waitForResponse((response) => {
    return response.url().includes('/api/saved-forms')
      && response.request().method() === 'POST'
      && response.ok();
  }, { timeout: 120000 });
  await page.locator('.ui-dialog__input').fill(saveName);
  await page.locator('.ui-dialog').getByRole('button', { name: 'Save', exact: true }).click();
  await saveRequest;
  await page.locator('.ui-dialog-backdrop .ui-dialog').waitFor({ state: 'hidden', timeout: 30000 });
}

async function overwriteOpenGroupTemplate(page) {
  const overwriteRequest = page.waitForResponse((response) => {
    return response.url().includes('/api/saved-forms')
      && response.request().method() === 'POST'
      && response.ok();
  }, { timeout: 120000 });
  await page.getByRole('button', { name: 'Save' }).click();
  await page.getByRole('heading', { name: 'Overwrite group template?' }).waitFor({ timeout: 10000 });
  await page.getByRole('button', { name: 'Overwrite', exact: true }).click();
  await overwriteRequest;
  await page.locator('.ui-dialog-backdrop .ui-dialog').waitFor({ state: 'hidden', timeout: 30000 });
}

async function parseJsonResponse(response, contextLabel) {
  const bodyText = await response.text();
  let payload = null;
  try {
    payload = bodyText ? JSON.parse(bodyText) : null;
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const detail = payload?.detail || payload?.message || bodyText || response.statusText;
    throw new Error(`${contextLabel} failed (${response.status}): ${detail}`);
  }
  return payload;
}

function buildFillLinkAnswers(questions, respondentLabel) {
  const availableQuestions = Array.isArray(questions) ? questions : [];
  if (!availableQuestions.length) {
    throw new Error('Fill By Link has no questions.');
  }
  const question = availableQuestions.find((entry) => entry?.requiredForRespondentIdentity) || availableQuestions[0];
  const key = String(question?.key || '').trim() || 'respondent_identifier';
  const questionType = String(question?.type || 'text').trim().toLowerCase();
  const options = Array.isArray(question?.options) ? question.options : [];
  const firstOptionKey = String(options[0]?.key || '').trim()
    || String(options[0]?.value || '').trim()
    || String(options[0]?.label || '').trim();
  const answers = {};

  if (questionType === 'boolean') {
    answers[key] = true;
  } else if (questionType === 'multi_select') {
    answers[key] = firstOptionKey ? [firstOptionKey] : ['choice_1'];
  } else if (questionType === 'radio') {
    if (!firstOptionKey) {
      throw new Error(`Radio question "${key}" has no options to select.`);
    }
    answers[key] = firstOptionKey;
  } else if (questionType === 'date') {
    answers[key] = '2026-03-10';
  } else {
    answers[key] = respondentLabel;
  }

  return { answers, answerKey: key };
}

async function getRecaptchaToken(page, siteKey, action) {
  if (!siteKey) {
    throw new Error('Missing reCAPTCHA site key for public Fill By Link submission.');
  }
  return page.evaluate(async ({ nextSiteKey, nextAction }) => {
    const existingApi = globalThis.grecaptcha?.enterprise;
    const loadRecaptchaEnterprise = () => new Promise((resolve, reject) => {
      if (existingApi) {
        resolve(existingApi);
        return;
      }

      const scriptId = 'pw-recaptcha-enterprise';
      const existingScript = document.getElementById(scriptId);
      if (existingScript) {
        existingScript.addEventListener('load', () => resolve(globalThis.grecaptcha?.enterprise), { once: true });
        existingScript.addEventListener('error', () => reject(new Error('reCAPTCHA Enterprise failed to load.')), { once: true });
        return;
      }

      const script = document.createElement('script');
      script.id = scriptId;
      script.src = `https://www.google.com/recaptcha/enterprise.js?render=${encodeURIComponent(nextSiteKey)}`;
      script.async = true;
      script.defer = true;
      script.addEventListener('load', () => resolve(globalThis.grecaptcha?.enterprise), { once: true });
      script.addEventListener('error', () => reject(new Error('reCAPTCHA Enterprise failed to load.')), { once: true });
      document.head.appendChild(script);
    });

    const enterpriseApi = await loadRecaptchaEnterprise();
    if (!enterpriseApi) {
      throw new Error('reCAPTCHA Enterprise API is unavailable.');
    }

    return new Promise((resolve, reject) => {
      enterpriseApi.ready(() => {
        enterpriseApi.execute(nextSiteKey, { action: nextAction }).then(resolve).catch((error) => {
          reject(new Error(error instanceof Error ? error.message : String(error)));
        });
      });
    });
  }, { nextSiteKey: siteKey, nextAction: action });
}

async function submitFillLinkResponse(page, publicToken, respondentLabel) {
  const loadResponse = await fetch(`${apiBaseUrl}/api/fill-links/public/${encodeURIComponent(publicToken)}`);
  const loadPayload = await parseJsonResponse(loadResponse, 'Load public Fill By Link');
  const questions = Array.isArray(loadPayload?.link?.questions) ? loadPayload.link.questions : [];
  const { answers, answerKey } = buildFillLinkAnswers(questions, respondentLabel);
  const recaptchaToken = await getRecaptchaToken(page, recaptchaSiteKey, fillLinkRecaptchaAction);
  const submitResponse = await fetch(`${apiBaseUrl}/api/fill-links/public/${encodeURIComponent(publicToken)}/submit`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      answers,
      recaptchaToken,
      recaptchaAction: fillLinkRecaptchaAction,
      attemptId: `pw_fill_link_${Date.now()}`,
    }),
  });
  const submitPayload = await parseJsonResponse(submitResponse, 'Submit public Fill By Link');
  return {
    responseId: submitPayload?.responseId || null,
    respondentLabel: submitPayload?.respondentLabel || respondentLabel,
    answerKey,
  };
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

async function findOwnerGroupFillLink(page, ownerGroupName) {
  const idToken = await getFreshOwnerIdToken(page);
  const response = await fetch(`${apiBaseUrl}/api/fill-links?scopeType=group`, {
    headers: {
      Authorization: `Bearer ${idToken}`,
    },
  });
  const payload = await parseJsonResponse(response, 'Load owner Fill By Link records');
  const links = Array.isArray(payload?.links) ? payload.links : [];
  return links.find((link) => link?.groupName === ownerGroupName || link?.title === ownerGroupName) || null;
}

async function main() {
  fs.mkdirSync(artifactDir, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1400 },
  });
  await context.addInitScript(() => {
    const state = window;
    state.__PW_PROCESSING_EVENTS__ = [];
    const recordProcessingCopy = () => {
      const root = document.querySelector('.processing-indicator');
      if (!(root instanceof HTMLElement)) {
        return;
      }
      const heading = root.querySelector('h3')?.textContent?.trim() || '';
      const detail = root.querySelector('p')?.textContent?.trim() || '';
      if (!heading || !detail) {
        return;
      }
      const nextEntry = { heading, detail };
      const existing = Array.isArray(state.__PW_PROCESSING_EVENTS__) ? state.__PW_PROCESSING_EVENTS__ : [];
      if (existing.some((entry) => entry?.heading === heading && entry?.detail === detail)) {
        return;
      }
      existing.push(nextEntry);
      state.__PW_PROCESSING_EVENTS__ = existing;
    };

    const observer = new MutationObserver(() => {
      recordProcessingCopy();
    });

    const attachObserver = () => {
      if (!(document.documentElement instanceof HTMLElement)) {
        return;
      }
      observer.observe(document.documentElement, {
        childList: true,
        subtree: true,
        characterData: true,
      });
      recordProcessingCopy();
    };

    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', attachObserver, { once: true });
    } else {
      attachObserver();
    }
  });
  const page = await context.newPage();
  let fatalError = null;

  try {
    logStep('Signing in');
    await delayBackendRequests(page);
    await signIn(page);

    logStep('Saving first fillable template');
    await openUploadView(page);
    await page.getByLabel('Upload Fillable PDF Template').setInputFiles(fillablePdfPath);
    await assertProcessingCopy(page, 'Opening your fillable PDF…', 'Opening your fillable PDF in the editor.');
    await waitForEditor(page);
    await page.getByRole('button', { name: 'Save' }).click();
    await page.getByRole('heading', { name: 'Name this saved form' }).waitFor({ timeout: 10000 });
    await auditDialog(page, '.ui-dialog-backdrop .ui-dialog', 'Prompt dialog');
    await submitSavePrompt(page, savedFormNameA);
    await waitForSavedFormVisible(page, savedFormNameA);

    logStep('Saving second template');
    await page.getByLabel('Upload Fillable PDF Template').setInputFiles(detectPdfPath);
    await assertProcessingCopy(page, 'Opening your fillable PDF…', 'Opening your fillable PDF in the editor.');
    await waitForEditor(page);
    await page.getByRole('button', { name: 'Save' }).click();
    await page.getByRole('heading', { name: 'Name this saved form' }).waitFor({ timeout: 10000 });
    await submitSavePrompt(page, savedFormNameB);
    await waitForSavedFormVisible(page, savedFormNameB);

    logStep('Creating a group');
    await refreshSavedAssets(page, [savedFormNameA, savedFormNameB]);
    await page.getByRole('button', { name: 'Create Group' }).click();
    await page.getByRole('heading', { name: 'Create Group' }).waitFor({ timeout: 10000 });
    await auditDialog(page, '.ui-dialog.group-create-modal', 'Group create dialog');
    const groupNameInput = page.locator('.ui-dialog.group-create-modal input[placeholder=\"New hire packet\"]');
    await groupNameInput.fill(groupName);
    const actualGroupName = await groupNameInput.inputValue();
    if (actualGroupName !== groupName) {
      throw new Error(`Unable to set group name. Expected "${groupName}" but found "${actualGroupName}".`);
    }
    await page.getByRole('checkbox', { name: savedFormNameA, exact: true }).check();
    await page.getByRole('checkbox', { name: savedFormNameB, exact: true }).check();
    await page.locator('.ui-dialog.group-create-modal').getByRole('button', { name: 'Create group', exact: true }).click();
    await page.locator('.ui-dialog.group-create-modal').waitFor({ state: 'hidden', timeout: 30000 });

    logStep('Opening a saved form');
    const firstSavedFormName = savedFormNameA;
    await page.locator('[aria-label="Saved templates"] .saved-chip__content').filter({ hasText: savedFormNameA }).first().click();
    await assertProcessingCopy(page, 'Opening your saved form…', 'Grabbing your saved form from the cloud.');
    await page.waitForTimeout(750);

    logStep('Opening a saved group');
    await openUploadView(page);
    await refreshSavedAssets(page, [savedFormNameA, savedFormNameB]);
    await page.getByText('Switch to groups').click();
    const savedGroups = page.locator('[aria-label="Saved form groups"] .saved-chip');
    const firstGroupChip = savedGroups.filter({ hasText: groupName }).first();
    await firstGroupChip.waitFor({ timeout: 30000 });
    const firstGroupName = groupName;
    await firstGroupChip.getByRole('button', { name: `Delete group ${groupName}` }).click();
    await page.getByRole('heading', { name: 'Delete group?' }).waitFor({ timeout: 10000 });
    await auditDialog(page, '.ui-dialog-backdrop .ui-dialog', 'Confirm dialog');
    await page.getByRole('button', { name: 'Cancel' }).click();

    await firstGroupChip.locator('.saved-chip__content').click();
    await assertProcessingCopy(page, 'Opening your group…', 'Opening the first template in this group.');
    await waitForEditor(page, { timeoutMs: 180000 });
    await page.locator('.ui-group-select').waitFor({ timeout: 30000 });
    await overwriteOpenGroupTemplate(page);

    logStep('Opening Fill By Link');
    const templateFillLinkLoad = page.waitForResponse((response) => {
      return response.url().includes('/api/fill-links?templateId=')
        && response.request().method() === 'GET'
        && response.ok();
    }, { timeout: 60000 });
    const groupFillLinkLoad = page.waitForResponse((response) => {
      return response.url().includes('/api/fill-links?groupId=')
        && response.request().method() === 'GET'
        && response.ok();
    }, { timeout: 60000 });
    await page.getByRole('button', { name: 'Fill By Link' }).click();
    await page.locator('.ui-dialog.fill-link-dialog .ui-dialog__title').waitFor({ timeout: 10000 });
    await Promise.all([templateFillLinkLoad, groupFillLinkLoad]);
    await auditDialog(page, '.ui-dialog.fill-link-dialog', 'Fill By Link dialog');

    const groupSection = page.locator('.fill-link-dialog__section').filter({
      has: page.getByRole('heading', { name: 'Group Fill By Link' }),
    }).first();
    const groupUrlInput = groupSection.getByLabel('Group Fill By Link URL');
    const publishGroupButton = groupSection.getByRole('button', { name: 'Publish Group Fill By Link', exact: true });
    await Promise.race([
      groupUrlInput.waitFor({ state: 'visible', timeout: 60000 }),
      publishGroupButton.waitFor({ state: 'visible', timeout: 60000 }),
    ]);
    const hasExistingGroupLink = await groupUrlInput.isVisible().catch(() => false);
    if (!hasExistingGroupLink) {
      await groupSection.scrollIntoViewIfNeeded();
      await publishGroupButton.waitFor({ state: 'visible', timeout: 30000 });
      await publishGroupButton.click({ timeout: 30000 });
      const groupLinkReady = await groupUrlInput.waitFor({ timeout: 10000 }).then(() => true).catch(() => false);
      if (!groupLinkReady) {
        const ownerGroupLink = await findOwnerGroupFillLink(page, groupName);
        if (!ownerGroupLink?.publicPath) {
          throw new Error(`Group Fill By Link did not publish for ${groupName}.`);
        }
        await page.keyboard.press('Escape');
        await page.locator('.ui-dialog.fill-link-dialog').waitFor({ state: 'hidden', timeout: 30000 });
        const templateFillLinkReload = page.waitForResponse((response) => {
          return response.url().includes('/api/fill-links?templateId=')
            && response.request().method() === 'GET'
            && response.ok();
        }, { timeout: 60000 });
        const groupFillLinkReload = page.waitForResponse((response) => {
          return response.url().includes('/api/fill-links?groupId=')
            && response.request().method() === 'GET'
            && response.ok();
        }, { timeout: 60000 });
        await page.getByRole('button', { name: 'Fill By Link' }).click();
        await page.locator('.ui-dialog.fill-link-dialog .ui-dialog__title').waitFor({ timeout: 10000 });
        await Promise.all([templateFillLinkReload, groupFillLinkReload]);
        await groupUrlInput.waitFor({ timeout: 30000 });
      }
    }
    const groupUrl = await groupUrlInput.inputValue();
    const publicToken = new URL(groupUrl).pathname.split('/').pop();
    if (!publicToken) {
      throw new Error(`Unable to extract public token from ${groupUrl}`);
    }

    const respondent = await submitFillLinkResponse(page, publicToken, `Dialog Response ${Date.now()}`);
    await groupSection.getByRole('button', { name: 'Refresh responses' }).click();
    await groupSection.getByText(respondent.respondentLabel).waitFor({ timeout: 30000 });
    logStep('Opening Search & Fill');
    await groupSection.getByRole('button', { name: 'Open Search & Fill' }).click();

    await page.getByRole('heading', { name: 'Search, Fill & Clear' }).waitFor({ timeout: 10000 });
    await auditDialog(page, '.ui-dialog.searchfill-modal__card', 'Search & Fill dialog');
    await page.getByText('Select which PDFs receive the row').waitFor({ timeout: 10000 });
    await page.getByText('Group Fill By Link respondents', { exact: false }).waitFor({ timeout: 10000 });
    await page.screenshot({ path: screenshotPath, fullPage: true });

    const summary = {
      ok: true,
      baseUrl,
      groupName,
      firstSavedFormName,
      firstGroupName,
      publicLinkVerified: true,
      respondentSubmissionVerified: Boolean(respondent.responseId),
      processingChecks,
      dialogChecks,
      screenshotPath,
    };
    fs.writeFileSync(summaryPath, `${JSON.stringify(summary, null, 2)}\n`);
    console.log(JSON.stringify({ ok: true, summaryPath, screenshotPath }));
  } catch (error) {
    fatalError = error;
    try {
      await page.screenshot({
        path: path.join(artifactDir, 'workspace-dialog-regression-failure.png'),
        fullPage: true,
      });
    } catch {
      // Ignore secondary screenshot failures so the original error is preserved.
    }
    throw error;
  } finally {
    const cleanupActions = [
      () => page.close(),
      () => context.close(),
      () => browser.close(),
    ];
    for (const cleanup of cleanupActions) {
      try {
        await cleanup();
      } catch (cleanupError) {
        if (!fatalError) {
          throw cleanupError;
        }
      }
    }
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack || error.message : String(error));
  process.exitCode = 1;
});
