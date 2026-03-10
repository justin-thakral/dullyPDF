import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';

const baseUrl = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5173';
const artifactDir = path.resolve(process.cwd(), 'output/playwright');
const screenshotPath = path.join(artifactDir, 'downgrade-retention-smoke.png');
const eventsPath = path.join(artifactDir, 'downgrade-retention-smoke-events.json');

const retentionSummary = {
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

async function main() {
  fs.mkdirSync(artifactDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1400 } });

  try {
    await page.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.evaluate(async (summary) => {
      window.__PW_RETENTION_SUMMARY__ = summary;
      await import('/src/testSupport/playwrightDowngradeRetentionHarness.tsx');
    }, retentionSummary);

    await page.getByText('Downgraded account retention').waitFor({ timeout: 10000 });
    await page.screenshot({ path: screenshotPath, fullPage: true });

    await page.locator('.retention-dialog__template-name', { hasText: 'Template Three' }).click();
    await page.locator('.retention-dialog__template-name', { hasText: 'Template Four' }).click();
    await page.getByRole('button', { name: 'Save kept forms' }).click();
    await page.getByRole('button', { name: 'Keep free plan' }).click();
    await page.getByRole('button', { name: 'Review retention queue' }).click();
    await page.getByRole('button', { name: 'Delete now' }).click();
    await page.getByRole('button', { name: 'Reactivate Pro Monthly' }).click();

    const events = await page.evaluate(() => window.__PW_RETENTION_EVENTS__ || []);
    fs.writeFileSync(eventsPath, JSON.stringify(events, null, 2));

    const saveEvent = events.find((event) => event.type === 'save');
    if (!saveEvent) {
      throw new Error('Missing save event from downgrade retention dialog.');
    }
    const keptTemplateIds = Array.isArray(saveEvent.keptTemplateIds) ? saveEvent.keptTemplateIds : [];
    if (keptTemplateIds.join('|') !== 'tpl-1|tpl-2|tpl-4') {
      throw new Error(`Unexpected keptTemplateIds payload: ${JSON.stringify(keptTemplateIds)}`);
    }
    for (const eventType of ['close', 'profile-open', 'delete', 'reactivate']) {
      if (!events.some((event) => event.type === eventType)) {
        throw new Error(`Missing ${eventType} event from downgrade retention harness.`);
      }
    }

    console.log(JSON.stringify({ ok: true, screenshotPath, eventsPath, eventCount: events.length }));
  } finally {
    await page.close();
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack || error.message : String(error));
  process.exitCode = 1;
});
