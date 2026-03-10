import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';

const baseUrl = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5173';
const artifactDir = path.resolve(process.cwd(), 'output/playwright');
const resultsPath = path.join(artifactDir, 'downgrade-retention-matrix.json');

const defaultRetention = {
  status: 'grace_period',
  policyVersion: 1,
  downgradedAt: '2026-03-01T00:00:00Z',
  graceEndsAt: '2026-03-31T00:00:00Z',
  daysRemaining: 21,
  savedFormsLimit: 3,
  fillLinksActiveLimit: 1,
  keptTemplateIds: ['tpl-1', 'tpl-2', 'tpl-3'],
  pendingDeleteTemplateIds: ['tpl-4'],
  pendingDeleteLinkIds: ['link-4'],
  counts: {
    keptTemplates: 3,
    pendingTemplates: 1,
    affectedGroups: 1,
    pendingLinks: 1,
    closedLinks: 1,
  },
  templates: [
    { id: 'tpl-1', name: 'Template One', createdAt: '2026-01-01T00:00:00Z', status: 'kept' },
    { id: 'tpl-2', name: 'Template Two', createdAt: '2026-01-02T00:00:00Z', status: 'kept' },
    { id: 'tpl-3', name: 'Template Three', createdAt: '2026-01-03T00:00:00Z', status: 'kept' },
    { id: 'tpl-4', name: 'Template Four', createdAt: '2026-01-04T00:00:00Z', status: 'pending_delete' },
  ],
  groups: [{ id: 'group-1', name: 'Admissions Packet', templateCount: 4, pendingTemplateCount: 1, willDelete: false }],
  links: [{ id: 'link-4', title: 'Template Four Link', scopeType: 'template', status: 'closed', templateId: 'tpl-4', pendingDeleteReason: 'template_pending_delete' }],
};

async function mountHarness(page, retentionSummary, options = {}) {
  await page.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.evaluate(async ({ summary, harnessOptions }) => {
    window.__PW_RETENTION_SUMMARY__ = summary;
    window.__PW_RETENTION_OPTIONS__ = harnessOptions;
    await import('/src/testSupport/playwrightDowngradeRetentionHarness.tsx');
  }, { summary: retentionSummary, harnessOptions: options });
  await page.getByText('Downgraded account retention').waitFor({ timeout: 10000 });
}

async function runScenario(browser, name, run) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1400 } });
  try {
    const result = await run(page);
    return { name, ok: true, ...result };
  } finally {
    await page.close();
  }
}

async function main() {
  fs.mkdirSync(artifactDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });

  try {
    const scenarios = [];

    scenarios.push(await runScenario(browser, 'default-flow', async (page) => {
      await mountHarness(page, defaultRetention);
      const screenshotPath = path.join(artifactDir, 'downgrade-retention-default-flow.png');

      await page.locator('.retention-dialog__template-name', { hasText: 'Template Three' }).click();
      await page.locator('.retention-dialog__template-name', { hasText: 'Template Four' }).click();
      await page.getByRole('button', { name: 'Save kept forms' }).click();
      await page.getByRole('button', { name: 'Keep free plan' }).click();
      await page.getByRole('button', { name: 'Review retention queue' }).click();
      await page.getByRole('button', { name: 'Delete now' }).click();
      await page.getByRole('button', { name: 'Reactivate Pro Monthly' }).click();
      await page.screenshot({ path: screenshotPath, fullPage: true });

      const events = await page.evaluate(() => window.__PW_RETENTION_EVENTS__ || []);
      const saveEvent = events.find((event) => event.type === 'save');
      if (!saveEvent) {
        throw new Error('Missing save event in default-flow scenario.');
      }
      const keptTemplateIds = Array.isArray(saveEvent.keptTemplateIds) ? saveEvent.keptTemplateIds : [];
      if (keptTemplateIds.join('|') !== 'tpl-1|tpl-2|tpl-4') {
        throw new Error(`Unexpected keptTemplateIds payload: ${JSON.stringify(keptTemplateIds)}`);
      }
      for (const eventType of ['close', 'profile-open', 'delete', 'reactivate']) {
        if (!events.some((event) => event.type === eventType)) {
          throw new Error(`Missing ${eventType} event in default-flow scenario.`);
        }
      }
      return { screenshotPath, eventCount: events.length };
    }));

    scenarios.push(await runScenario(browser, 'billing-disabled', async (page) => {
      await mountHarness(page, defaultRetention, { billingEnabled: false });
      const reactivateButton = page.getByRole('button', { name: 'Reactivate Pro Monthly' });
      if (!(await reactivateButton.isDisabled())) {
        throw new Error('Reactivate button should be disabled when billing is unavailable.');
      }
      await page.getByText('Stripe billing is currently unavailable, so reactivation is temporarily disabled.').waitFor({ timeout: 10000 });
      return {};
    }));

    scenarios.push(await runScenario(browser, 'saving-busy', async (page) => {
      await mountHarness(page, defaultRetention, { savingSelection: true });
      for (const name of ['Keep free plan', 'Delete now', 'Saving selection...', 'Reactivate Pro Monthly']) {
        const button = page.getByRole('button', { name });
        if (!(await button.isDisabled())) {
          throw new Error(`${name} should be disabled during saving.`);
        }
      }
      return {};
    }));

    scenarios.push(await runScenario(browser, 'deleting-busy', async (page) => {
      await mountHarness(page, defaultRetention, { deletingNow: true });
      const deleteButton = page.getByRole('button', { name: 'Deleting queued data...' });
      if (!(await deleteButton.isDisabled())) {
        throw new Error('Delete button should be disabled while deletion is in progress.');
      }
      return {};
    }));

    scenarios.push(await runScenario(browser, 'no-auto-closed-links-note', async (page) => {
      await mountHarness(page, {
        ...defaultRetention,
        counts: {
          ...defaultRetention.counts,
          closedLinks: 0,
        },
      });
      if (await page.getByText('Extra active Fill By Link records above the free limit were closed automatically. They are not in the delete queue unless their saved form is queued.').isVisible().catch(() => false)) {
        throw new Error('Closed-links note should be hidden when there are no auto-closed links.');
      }
      return {};
    }));

    fs.writeFileSync(resultsPath, JSON.stringify(scenarios, null, 2));
    console.log(JSON.stringify({ ok: true, scenarioCount: scenarios.length, resultsPath }));
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack || error.message : String(error));
  process.exitCode = 1;
});
