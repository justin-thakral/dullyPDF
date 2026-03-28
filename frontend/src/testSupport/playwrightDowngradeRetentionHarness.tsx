import { useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import DowngradeRetentionDialog from '../components/features/DowngradeRetentionDialog';
import ProfilePage from '../components/pages/ProfilePage';
import type { DowngradeRetentionSummary, ProfileLimits, SavedFormSummary } from '../services/api';

type HarnessEvent =
  | { type: 'close' }
  | { type: 'save'; keptTemplateIds: string[] }
  | { type: 'delete' }
  | { type: 'reactivate' }
  | { type: 'profile-open' };

type HarnessWindow = Window & {
  __PW_RETENTION_SUMMARY__?: DowngradeRetentionSummary;
  __PW_RETENTION_EVENTS__?: HarnessEvent[];
  __PW_RETENTION_OPTIONS__?: {
    billingEnabled?: boolean;
    savingSelection?: boolean;
    deletingNow?: boolean;
    checkoutInProgress?: boolean;
    reactivateLabel?: string;
  };
};

const harnessWindow = window as HarnessWindow;

const defaultRetention: DowngradeRetentionSummary = {
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

const limits: ProfileLimits = {
  detectMaxPages: 10,
  fillableMaxPages: 20,
  savedFormsMax: 3,
  fillLinksActiveMax: 1,
  fillLinkResponsesMax: 5,
  signingRequestsPerDocumentMax: 10,
};

const savedForms: SavedFormSummary[] = [
  { id: 'tpl-1', name: 'Template One', createdAt: '2026-01-01T00:00:00Z' },
  { id: 'tpl-2', name: 'Template Two', createdAt: '2026-01-02T00:00:00Z' },
  { id: 'tpl-3', name: 'Template Three', createdAt: '2026-01-03T00:00:00Z' },
  { id: 'tpl-4', name: 'Template Four', createdAt: '2026-01-04T00:00:00Z' },
];

function recordEvent(event: HarnessEvent): void {
  harnessWindow.__PW_RETENTION_EVENTS__ = [...(harnessWindow.__PW_RETENTION_EVENTS__ || []), event];
}

function HarnessApp() {
  const retention = harnessWindow.__PW_RETENTION_SUMMARY__ || defaultRetention;
  const options = harnessWindow.__PW_RETENTION_OPTIONS__ || {};
  const [open, setOpen] = useState(true);
  const limitsLabel = useMemo(() => limits, []);
  const billingEnabled = options.billingEnabled !== false;

  return (
    <div style={{ padding: '24px', background: '#f4f7fb' }}>
      <ProfilePage
        email="playwright@example.com"
        role="base"
        creditsRemaining={3}
        monthlyCreditsRemaining={0}
        refillCreditsRemaining={0}
        availableCredits={3}
        billingEnabled={billingEnabled}
        retention={retention}
        limits={limitsLabel}
        savedForms={savedForms}
        onSelectSavedForm={() => {}}
        onOpenDowngradeRetention={() => {
          recordEvent({ type: 'profile-open' });
          setOpen(true);
        }}
        onClose={() => {}}
      />
      <DowngradeRetentionDialog
        open={open}
        retention={retention}
        billingEnabled={billingEnabled}
        savingSelection={options.savingSelection === true}
        deletingNow={options.deletingNow === true}
        checkoutInProgress={options.checkoutInProgress === true}
        reactivateLabel={options.reactivateLabel}
        onClose={() => {
          recordEvent({ type: 'close' });
          setOpen(false);
        }}
        onSaveSelection={(keptTemplateIds) => recordEvent({ type: 'save', keptTemplateIds })}
        onDeleteNow={() => recordEvent({ type: 'delete' })}
        onReactivatePremium={() => recordEvent({ type: 'reactivate' })}
      />
    </div>
  );
}

harnessWindow.__PW_RETENTION_EVENTS__ = [];
document.body.innerHTML = '<div id="pw-downgrade-retention-root"></div>';
createRoot(document.getElementById('pw-downgrade-retention-root') as HTMLElement).render(<HarnessApp />);
