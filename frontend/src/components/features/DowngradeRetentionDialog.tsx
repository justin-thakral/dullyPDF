import { useEffect, useMemo, useState } from 'react';
import { Dialog } from '../ui/Dialog';
import type { DowngradeRetentionSummary } from '../../services/api';
import './DowngradeRetentionDialog.css';

type DowngradeRetentionDialogProps = {
  open: boolean;
  retention: DowngradeRetentionSummary | null;
  billingEnabled: boolean;
  savingSelection?: boolean;
  deletingNow?: boolean;
  checkoutInProgress?: boolean;
  reactivateLabel?: string;
  onClose: () => void;
  onSaveSelection: (keptTemplateIds: string[]) => void;
  onDeleteNow: () => void;
  onReactivatePremium: () => void;
};

function formatRetentionDate(value?: string | null): string {
  if (!value) return 'Unknown date';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return 'Unknown date';
  return parsed.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  });
}

function buildTemplateSelectionKey(templateIds: string[]): string {
  return [...new Set(templateIds)].sort().join('|');
}

export function DowngradeRetentionDialog({
  open,
  retention,
  billingEnabled,
  savingSelection = false,
  deletingNow = false,
  checkoutInProgress = false,
  reactivateLabel = 'Reactivate Pro Monthly',
  onClose,
  onSaveSelection,
  onDeleteNow,
  onReactivatePremium,
}: DowngradeRetentionDialogProps) {
  const [selectedTemplateIds, setSelectedTemplateIds] = useState<string[]>([]);

  useEffect(() => {
    if (!open || !retention) return;
    setSelectedTemplateIds(retention.keptTemplateIds);
  }, [open, retention]);

  const keepLimit = Math.max(0, retention?.savedFormsLimit ?? 0);
  const pendingTemplateCount = retention?.counts.pendingTemplates ?? 0;
  const selectedCount = selectedTemplateIds.length;
  const actionsBusy = savingSelection || deletingNow || checkoutInProgress;
  const initialSelectionKey = buildTemplateSelectionKey(retention?.keptTemplateIds ?? []);
  const selectedSelectionKey = buildTemplateSelectionKey(selectedTemplateIds);
  const canSaveSelection = Boolean(
    retention &&
    !actionsBusy &&
    selectedCount === keepLimit &&
    initialSelectionKey !== selectedSelectionKey,
  );
  const deadlineLabel = formatRetentionDate(retention?.graceEndsAt);

  const templateRows = useMemo(() => retention?.templates ?? [], [retention]);

  const handleToggleTemplate = (templateId: string) => {
    setSelectedTemplateIds((previous) => {
      if (previous.includes(templateId)) {
        return previous.filter((entry) => entry !== templateId);
      }
      if (previous.length >= keepLimit) {
        return previous;
      }
      return [...previous, templateId];
    });
  };

  if (!retention) return null;

  return (
    <Dialog
      open={open}
      title="Downgraded account retention"
      description={(
        <div className="retention-dialog__description">
          <p>
            Your account is back on the free tier. Saved forms outside your free limit stay available until{' '}
            <strong>{deadlineLabel}</strong>, then they are deleted unless you reactivate Pro.
          </p>
          <p>
            Choose which {keepLimit} saved form{keepLimit === 1 ? '' : 's'} to keep. The remaining{' '}
            {pendingTemplateCount} saved form{pendingTemplateCount === 1 ? '' : 's'} and dependent Fill By Link
            records stay in the delete queue during the grace period.
          </p>
        </div>
      )}
      onClose={onClose}
      className="retention-dialog"
      footer={(
        <div className="retention-dialog__footer">
          <button type="button" className="ui-button ui-button--ghost" onClick={onClose} disabled={actionsBusy}>
            Keep free plan
          </button>
          <button type="button" className="ui-button ui-button--danger" onClick={onDeleteNow} disabled={actionsBusy}>
            {deletingNow ? 'Deleting queued data...' : 'Delete now'}
          </button>
          <button
            type="button"
            className="ui-button ui-button--primary"
            onClick={onReactivatePremium}
            disabled={!billingEnabled || actionsBusy}
          >
            {checkoutInProgress ? 'Starting checkout...' : reactivateLabel}
          </button>
        </div>
      )}
    >
      <div className="retention-dialog__meta">
        <div className="retention-dialog__stat">
          <span>Days left</span>
          <strong>{retention.daysRemaining}</strong>
        </div>
        <div className="retention-dialog__stat">
          <span>Groups affected</span>
          <strong>{retention.counts.affectedGroups}</strong>
        </div>
        <div className="retention-dialog__stat">
          <span>Links pending delete</span>
          <strong>{retention.counts.pendingLinks}</strong>
        </div>
      </div>

      <div className="retention-dialog__selection">
        <div className="retention-dialog__selection-header">
          <div>
            <h3>Keep these saved forms</h3>
            <p>
              Select exactly {keepLimit}. Oldest-first is the default, but you can swap them before the grace period ends.
            </p>
          </div>
          <button
            type="button"
            className="ui-button ui-button--primary"
            onClick={() => onSaveSelection(selectedTemplateIds)}
            disabled={!canSaveSelection}
          >
            {savingSelection ? 'Saving selection...' : 'Save kept forms'}
          </button>
        </div>
        <p className="retention-dialog__selection-count">
          {selectedCount} of {keepLimit} selected
        </p>
        <div className="retention-dialog__template-list" role="list">
          {templateRows.map((template) => {
            const checked = selectedTemplateIds.includes(template.id);
            const createdAtLabel = formatRetentionDate(template.createdAt);
            return (
              <label
                key={template.id}
                className={`retention-dialog__template ${checked ? 'retention-dialog__template--checked' : ''}`}
              >
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => handleToggleTemplate(template.id)}
                  disabled={actionsBusy}
                />
                <div className="retention-dialog__template-body">
                  <span className="retention-dialog__template-name">{template.name}</span>
                  <span className="retention-dialog__template-date">Created {createdAtLabel}</span>
                </div>
                <span className={`retention-dialog__template-status retention-dialog__template-status--${checked ? 'kept' : 'queued'}`}>
                  {checked ? 'Keep' : 'Delete later'}
                </span>
              </label>
            );
          })}
        </div>
        {retention.counts.closedLinks ? (
          <p className="retention-dialog__note">
            Extra active Fill By Link records above the free limit were closed automatically. They are not in the delete queue unless their saved form is queued.
          </p>
        ) : null}
        {!billingEnabled ? (
          <p className="retention-dialog__note">
            Stripe billing is currently unavailable, so reactivation is temporarily disabled.
          </p>
        ) : null}
      </div>
    </Dialog>
  );
}

export default DowngradeRetentionDialog;
