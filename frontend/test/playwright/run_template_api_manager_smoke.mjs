import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';

const baseUrl = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5173';
const apiBaseUrl = (process.env.PLAYWRIGHT_API_URL || 'http://localhost:8000').replace(/\/+$/, '');
const artifactDir = path.resolve(process.cwd(), 'output/playwright');
const screenshotPath = path.join(artifactDir, 'template-api-manager-smoke.png');
const summaryPath = path.join(artifactDir, 'template-api-manager-smoke.json');

function createScenario(overrides = {}) {
  const baseScenario = {
    templateName: 'Patient Intake',
    hasActiveTemplate: true,
    endpoint: {
      id: 'tep_live_patient_intake',
      templateId: 'tpl_patient_intake',
      templateName: 'Patient Intake',
      status: 'active',
      snapshotVersion: 4,
      keyPrefix: 'dpa_live_abc123',
      createdAt: '2026-03-25T12:00:00.000Z',
      updatedAt: '2026-03-25T12:00:00.000Z',
      publishedAt: '2026-03-25T12:00:00.000Z',
      lastUsedAt: '2026-03-25T14:30:00.000Z',
      usageCount: 18,
      currentUsageMonth: '2026-03',
      currentMonthUsageCount: 18,
      authFailureCount: 1,
      validationFailureCount: 2,
      suspiciousFailureCount: 1,
      lastFailureAt: '2026-03-25T15:15:00.000Z',
      lastFailureReason: 'Unknown API Fill keys: ignored_key.',
      auditEventCount: 4,
      fillPath: '/api/v1/fill/tep_live_patient_intake.pdf',
      schemaPath: '/api/template-api-endpoints/tep_live_patient_intake/schema',
    },
    schema: {
      snapshotVersion: 4,
      defaultExportMode: 'flat',
      fields: [
        { key: 'first_name', fieldName: 'first_name', type: 'text', page: 1 },
        { key: 'last_name', fieldName: 'last_name', type: 'text', page: 1 },
        { key: 'date_of_birth', fieldName: 'date_of_birth', type: 'date', page: 1 },
      ],
      checkboxFields: [
        { key: 'agree_to_terms', fieldName: 'agree_to_terms', type: 'checkbox', page: 1 },
      ],
      checkboxGroups: [
        {
          key: 'consent_signed',
          groupKey: 'consent_group',
          type: 'checkbox_rule',
          operation: 'yes_no',
          options: [
            { optionKey: 'yes', optionLabel: 'Yes', fieldName: 'i_consent_yes' },
            { optionKey: 'no', optionLabel: 'No', fieldName: 'i_consent_no' },
          ],
          trueOption: 'yes',
          falseOption: 'no',
          valueMap: null,
        },
      ],
      radioGroups: [
        {
          groupKey: 'marital_status',
          type: 'radio',
          options: [
            { optionKey: 'single', optionLabel: 'Single' },
            { optionKey: 'married', optionLabel: 'Married' },
          ],
        },
      ],
      exampleData: {
        first_name: 'Ada',
        last_name: 'Lovelace',
        date_of_birth: '1815-12-10',
        agree_to_terms: true,
        consent_signed: true,
        marital_status: 'single',
        middle_name: null,
      },
    },
    limits: {
      activeEndpointsMax: 2,
      activeEndpointsUsed: 1,
      requestsPerMonthMax: 250,
      requestsThisMonth: 18,
      requestUsageMonth: '2026-03',
      maxPagesPerRequest: 25,
      templatePageCount: 2,
    },
    recentEvents: [
      {
        id: 'evt-1',
        eventType: 'published',
        outcome: 'success',
        createdAt: '2026-03-25T12:00:00.000Z',
        snapshotVersion: 4,
        summary: 'Endpoint published',
        metadata: { exportMode: 'flat' },
      },
      {
        id: 'evt-2',
        eventType: 'fill_validation_failed',
        outcome: 'error',
        createdAt: '2026-03-25T15:15:00.000Z',
        snapshotVersion: 4,
        summary: 'Invalid fill payload rejected',
        metadata: { reason: 'Unknown API Fill keys: ignored_key.' },
      },
    ],
    loading: false,
    publishing: false,
    rotating: false,
    revoking: false,
    error: null,
    latestSecret: 'dpa_live_secret_value',
  };

  return {
    ...baseScenario,
    ...overrides,
    endpoint: overrides.endpoint === null
      ? null
      : { ...baseScenario.endpoint, ...(overrides.endpoint || {}) },
    schema: overrides.schema === null
      ? null
      : { ...baseScenario.schema, ...(overrides.schema || {}) },
    limits: overrides.limits === null
      ? null
      : { ...baseScenario.limits, ...(overrides.limits || {}) },
    recentEvents: overrides.recentEvents || baseScenario.recentEvents,
  };
}

async function mountHarness(page, scenario) {
  await page.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.evaluate(async (initialScenario) => {
    document.body.innerHTML = '<div id="root"></div>';
    document.title = 'Template API Manager Smoke';

    const ReactModule = await import('/node_modules/.vite/deps/react.js');
    const ReactDomClientModule = await import('/node_modules/.vite/deps/react-dom_client.js');
    const dialogModule = await import('/src/components/features/ApiFillManagerDialog.tsx');

    const root = document.getElementById('root');
    if (!root) {
      throw new Error('Missing harness root.');
    }

    window.__templateApiActions = [];
    window.__templateApiClipboard = [];
    Object.defineProperty(window.navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: async (value) => {
          window.__templateApiClipboard.push(String(value));
        },
      },
    });

    const React = ReactModule.default || ReactModule;
    const buildProps = (scenario) => ({
      key: JSON.stringify({
        endpointId: scenario.endpoint?.id || 'none',
        endpointStatus: scenario.endpoint?.status || 'none',
        hasSecret: Boolean(scenario.latestSecret),
      }),
      open: true,
      onClose: () => {},
      onPublish: async (mode) => {
        window.__templateApiActions.push({ type: 'publish', mode });
      },
      onRotate: async () => {
        window.__templateApiActions.push({ type: 'rotate' });
      },
      onRevoke: async () => {
        window.__templateApiActions.push({ type: 'revoke' });
      },
      onRefresh: async () => {
        window.__templateApiActions.push({ type: 'refresh' });
      },
      ...scenario,
    });
    const createRoot = ReactDomClientModule.createRoot || ReactDomClientModule.default?.createRoot;
    if (typeof createRoot !== 'function') {
      throw new Error('ReactDOM createRoot is unavailable in the harness.');
    }
    const reactRoot = createRoot(root);
    window.__mountTemplateApiHarness = (scenario) => {
      reactRoot.render(React.createElement(dialogModule.default, buildProps(scenario)));
    };
    window.__getTemplateApiHarnessState = () => ({
      actions: Array.from(window.__templateApiActions || []),
      clipboard: Array.from(window.__templateApiClipboard || []),
    });
    window.__mountTemplateApiHarness(initialScenario);
  }, scenario);
}

async function assertClipboardCopy(page, buttonName, expectedValue, expectedNotice) {
  await page.getByRole('button', { name: buttonName }).click();
  await page.getByText(expectedNotice).waitFor({ timeout: 15000 });
  const state = await page.evaluate(() => window.__getTemplateApiHarnessState());
  const clipboard = Array.isArray(state?.clipboard) ? state.clipboard : [];
  if (clipboard.at(-1) !== expectedValue) {
    throw new Error(`Unexpected clipboard value for ${buttonName}: ${JSON.stringify(clipboard)}`);
  }
}

async function remountHarness(page, scenario) {
  await page.evaluate((nextScenario) => {
    window.__mountTemplateApiHarness(nextScenario);
  }, scenario);
}

async function getHarnessState(page) {
  return page.evaluate(() => window.__getTemplateApiHarnessState());
}

async function resetHarnessActions(page) {
  await page.evaluate(() => {
    window.__templateApiActions = [];
  });
}

async function main() {
  fs.mkdirSync(artifactDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1400 } });

  try {
    const activeScenario = createScenario();
    const revokedScenario = createScenario({
      endpoint: {
        status: 'revoked',
        keyPrefix: null,
      },
      latestSecret: null,
    });
    const expectedFillUrl = `${apiBaseUrl}/api/v1/fill/tep_live_patient_intake.pdf`;
    const expectedSchemaUrl = `${apiBaseUrl}/api/v1/fill/tep_live_patient_intake/schema`;

    await mountHarness(page, activeScenario);
    await page.getByRole('heading', { name: 'API Fill' }).waitFor({ timeout: 15000 });
    await page.getByText('Limits and activity').waitFor({ timeout: 15000 });
    await page.getByText('Recent activity').waitFor({ timeout: 15000 });
    await page.locator('code').filter({ hasText: expectedFillUrl }).first().waitFor({ timeout: 15000 });
    await page.locator('code').filter({ hasText: expectedSchemaUrl }).first().waitFor({ timeout: 15000 });
    await page.getByText(/"agree_to_terms": True/).waitFor({ timeout: 15000 });
    await page.getByText(/"middle_name": None/).waitFor({ timeout: 15000 });
    await page.getByText(/"strict": true/).waitFor({ timeout: 15000 });

    await assertClipboardCopy(page, 'Copy key', 'dpa_live_secret_value', 'API key copied.');
    await assertClipboardCopy(page, 'Copy URL', expectedFillUrl, 'Endpoint URL copied.');
    await assertClipboardCopy(page, 'Copy schema URL', expectedSchemaUrl, 'Schema URL copied.');
    const clipboardState = (await getHarnessState(page)).clipboard;

    await resetHarnessActions(page);
    await page.getByRole('button', { name: 'Refresh' }).click();
    await page.getByRole('button', { name: 'Rotate key' }).click();
    await page.getByRole('button', { name: 'Revoke' }).click();

    await page.getByRole('button', { name: /Editable PDF/i }).click();
    await page.getByRole('button', { name: 'Republish snapshot' }).click();

    const activeState = await getHarnessState(page);
    const actions = Array.isArray(activeState?.actions) ? activeState.actions : [];
    const expectedActions = [
      { type: 'refresh' },
      { type: 'rotate' },
      { type: 'revoke' },
      { type: 'publish', mode: 'editable' },
    ];
    if (JSON.stringify(actions) !== JSON.stringify(expectedActions)) {
      throw new Error(`Unexpected action payload: ${JSON.stringify(actions)}`);
    }

    await page.screenshot({ path: screenshotPath, fullPage: true });
    await remountHarness(page, revokedScenario);
    await page.getByRole('button', { name: 'Generate key' }).waitFor({ timeout: 15000 });
    await page.getByText('This endpoint is revoked.').waitFor({ timeout: 15000 });

    const revokedCopyUrlCount = await page.getByRole('button', { name: 'Copy URL' }).count();
    const revokedCopySchemaCount = await page.getByRole('button', { name: 'Copy schema URL' }).count();
    const revokedCurlHeadingCount = await page.getByText('cURL').count();
    if (revokedCopyUrlCount !== 0 || revokedCopySchemaCount !== 0 || revokedCurlHeadingCount !== 0) {
      throw new Error('Revoked scenario still exposed active endpoint controls.');
    }

    fs.writeFileSync(
      summaryPath,
      JSON.stringify(
        {
          ok: true,
          screenshotPath,
          actions,
          clipboard: clipboardState,
          expectedFillUrl,
          expectedSchemaUrl,
        },
        null,
        2,
      ),
      'utf8',
    );

    console.log(JSON.stringify({ ok: true, screenshotPath, summaryPath, actions, clipboard: clipboardState }));
  } finally {
    await page.close();
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack || error.message : String(error));
  process.exitCode = 1;
});
