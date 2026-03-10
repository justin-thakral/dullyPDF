import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { GroupCreateDialog } from '../../../../src/components/features/GroupCreateDialog';

describe('GroupCreateDialog', () => {
  it('preserves the typed group name across rerenders with equivalent initial selections', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const onSubmit = vi.fn();
    const savedForms = [
      { id: 'form-1', name: 'Alpha Intake', createdAt: '2026-03-10T12:00:00.000Z' },
      { id: 'form-2', name: 'Beta Intake', createdAt: '2026-03-10T12:00:00.000Z' },
    ];

    const { rerender } = render(
      <GroupCreateDialog
        open
        savedForms={savedForms}
        initialSelectedIds={[]}
        onClose={onClose}
        onSubmit={onSubmit}
      />,
    );

    const nameInput = screen.getByPlaceholderText('New hire packet');
    await user.type(nameInput, 'Hiring Packet');

    rerender(
      <GroupCreateDialog
        open
        savedForms={[...savedForms]}
        initialSelectedIds={[]}
        onClose={onClose}
        onSubmit={onSubmit}
      />,
    );

    expect(
      (screen.getByPlaceholderText('New hire packet') as HTMLInputElement).value,
    ).toBe('Hiring Packet');
  });
});
