import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import DowngradeRetentionDialog from '../../../../src/components/features/DowngradeRetentionDialog';
import type { DowngradeRetentionSummary } from '../../../../src/services/api';

const retentionSummary: DowngradeRetentionSummary = {
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

describe('DowngradeRetentionDialog', () => {
  it('renders downgrade metadata and action buttons', () => {
    render(
      <DowngradeRetentionDialog
        open
        retention={retentionSummary}
        billingEnabled
        onClose={vi.fn()}
        onSaveSelection={vi.fn()}
        onDeleteNow={vi.fn()}
        onReactivatePremium={vi.fn()}
      />,
    );

    expect(screen.getByText('Downgraded account retention')).toBeTruthy();
    expect(screen.getByText('Days left')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Delete now' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Reactivate Pro Monthly' })).toBeTruthy();
  });

  it('allows swapping kept forms and saving the new selection', async () => {
    const user = userEvent.setup();
    const onSaveSelection = vi.fn();

    render(
      <DowngradeRetentionDialog
        open
        retention={retentionSummary}
        billingEnabled
        onClose={vi.fn()}
        onSaveSelection={onSaveSelection}
        onDeleteNow={vi.fn()}
        onReactivatePremium={vi.fn()}
      />,
    );

    const saveButton = screen.getByRole('button', { name: 'Save kept forms' }) as HTMLButtonElement;
    expect(saveButton.disabled).toBe(true);

    await user.click(screen.getByText('Template Three'));
    await user.click(screen.getByText('Template Four'));

    expect(saveButton.disabled).toBe(false);
    await user.click(saveButton);
    expect(onSaveSelection).toHaveBeenCalledWith(['tpl-1', 'tpl-2', 'tpl-4']);
  });

  it('wires delete-now and reactivate actions', async () => {
    const user = userEvent.setup();
    const onDeleteNow = vi.fn();
    const onReactivatePremium = vi.fn();

    render(
      <DowngradeRetentionDialog
        open
        retention={retentionSummary}
        billingEnabled
        onClose={vi.fn()}
        onSaveSelection={vi.fn()}
        onDeleteNow={onDeleteNow}
        onReactivatePremium={onReactivatePremium}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Delete now' }));
    await user.click(screen.getByRole('button', { name: 'Reactivate Pro Monthly' }));

    expect(onDeleteNow).toHaveBeenCalledTimes(1);
    expect(onReactivatePremium).toHaveBeenCalledTimes(1);
  });

  it('disables overlapping actions while a retention request is in progress', () => {
    render(
      <DowngradeRetentionDialog
        open
        retention={retentionSummary}
        billingEnabled
        savingSelection
        onClose={vi.fn()}
        onSaveSelection={vi.fn()}
        onDeleteNow={vi.fn()}
        onReactivatePremium={vi.fn()}
      />,
    );

    expect((screen.getByRole('button', { name: 'Keep free plan' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Delete now' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Saving selection...' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Reactivate Pro Monthly' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('disables reactivation when billing is unavailable', () => {
    render(
      <DowngradeRetentionDialog
        open
        retention={retentionSummary}
        billingEnabled={false}
        onClose={vi.fn()}
        onSaveSelection={vi.fn()}
        onDeleteNow={vi.fn()}
        onReactivatePremium={vi.fn()}
      />,
    );

    expect((screen.getByRole('button', { name: 'Reactivate Pro Monthly' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText('Stripe billing is currently unavailable, so reactivation is temporarily disabled.')).toBeTruthy();
  });

  it('caps selection at the keep limit and resets when reopened', async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <DowngradeRetentionDialog
        open
        retention={retentionSummary}
        billingEnabled
        onClose={vi.fn()}
        onSaveSelection={vi.fn()}
        onDeleteNow={vi.fn()}
        onReactivatePremium={vi.fn()}
      />,
    );

    await user.click(screen.getByText('Template Three'));
    await user.click(screen.getByText('Template Four'));
    expect(screen.getByText('3 of 3 selected')).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Save kept forms' }) as HTMLButtonElement).disabled).toBe(false);

    rerender(
      <DowngradeRetentionDialog
        open={false}
        retention={retentionSummary}
        billingEnabled
        onClose={vi.fn()}
        onSaveSelection={vi.fn()}
        onDeleteNow={vi.fn()}
        onReactivatePremium={vi.fn()}
      />,
    );
    rerender(
      <DowngradeRetentionDialog
        open
        retention={retentionSummary}
        billingEnabled
        onClose={vi.fn()}
        onSaveSelection={vi.fn()}
        onDeleteNow={vi.fn()}
        onReactivatePremium={vi.fn()}
      />,
    );

    expect(screen.getByText('3 of 3 selected')).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Save kept forms' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText('Template Three').closest('label')?.textContent).toContain('Keep');
    expect(screen.getByText('Template Four').closest('label')?.textContent).toContain('Delete later');
  });

  it('keeps save disabled when the final kept set is unchanged but reordered', async () => {
    const user = userEvent.setup();
    render(
      <DowngradeRetentionDialog
        open
        retention={retentionSummary}
        billingEnabled
        onClose={vi.fn()}
        onSaveSelection={vi.fn()}
        onDeleteNow={vi.fn()}
        onReactivatePremium={vi.fn()}
      />,
    );

    const saveButton = screen.getByRole('button', { name: 'Save kept forms' }) as HTMLButtonElement;
    expect(saveButton.disabled).toBe(true);

    await user.click(screen.getByText('Template One'));
    await user.click(screen.getByText('Template One'));

    expect(screen.getByText('3 of 3 selected')).toBeTruthy();
    expect(saveButton.disabled).toBe(true);
  });
});
