import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';

const baseUrl = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5173';
const artifactDir = path.resolve(process.cwd(), 'output/playwright');
const screenshotPath = path.join(artifactDir, 'template-api-manager-smoke.png');

async function mountHarness(page) {
  await page.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.evaluate(async () => {
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
    const React = ReactModule.default || ReactModule;
    const props = {
      open: true,
      onClose: () => {},
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
    };

    const createRoot = ReactDomClientModule.createRoot || ReactDomClientModule.default?.createRoot;
    if (typeof createRoot !== 'function') {
      throw new Error('ReactDOM createRoot is unavailable in the harness.');
    }
    createRoot(root).render(React.createElement(dialogModule.default, props));
  });
}

async function main() {
  fs.mkdirSync(artifactDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1400 } });

  try {
    await mountHarness(page);
    await page.getByRole('heading', { name: 'API Fill' }).waitFor({ timeout: 15000 });
    await page.getByText('Limits and activity').waitFor({ timeout: 15000 });
    await page.getByText('Recent activity').waitFor({ timeout: 15000 });

    await page.getByRole('button', { name: /Editable PDF/i }).click();
    await page.getByRole('button', { name: 'Republish snapshot' }).click();

    const actions = await page.evaluate(() => window.__templateApiActions);
    if (!Array.isArray(actions) || actions.length !== 1 || actions[0]?.type !== 'publish' || actions[0]?.mode !== 'editable') {
      throw new Error(`Unexpected action payload: ${JSON.stringify(actions)}`);
    }

    await page.screenshot({ path: screenshotPath, fullPage: true });

    console.log(JSON.stringify({ ok: true, screenshotPath, actions }));
  } finally {
    await page.close();
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack || error.message : String(error));
  process.exitCode = 1;
});
