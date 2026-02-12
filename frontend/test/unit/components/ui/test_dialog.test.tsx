import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  ConfirmDialog,
  Dialog,
  PromptDialog,
  SavedFormsLimitDialog,
} from '../../../../src/components/ui/Dialog';

describe('Dialog', () => {
  it('renders only when open and closes from backdrop clicks', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const { rerender } = render(
      <Dialog open={false} title="Dialog title" onClose={onClose}>
        <p>Body content</p>
      </Dialog>,
    );

    expect(screen.queryByRole('dialog')).toBeNull();

    rerender(
      <Dialog open title="Dialog title" onClose={onClose}>
        <p>Body content</p>
      </Dialog>,
    );

    expect(screen.getByRole('dialog')).toBeTruthy();
    await user.click(screen.getByText('Body content'));
    expect(onClose).not.toHaveBeenCalled();

    await user.click(screen.getByRole('presentation'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('closes on Escape key when open', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();

    render(
      <Dialog open title="Keyboard close" onClose={onClose}>
        <p>Press escape</p>
      </Dialog>,
    );

    await user.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('focuses the confirm button and applies tone classes', async () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    const { rerender } = render(
      <ConfirmDialog
        open
        title="Delete item"
        confirmLabel="Delete"
        tone="danger"
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );

    const dangerConfirm = screen.getByRole('button', { name: 'Delete' });
    await waitFor(() => {
      expect(document.activeElement).toBe(dangerConfirm);
    });
    expect(dangerConfirm.classList.contains('ui-button--danger')).toBe(true);

    rerender(
      <ConfirmDialog
        open
        title="Continue"
        confirmLabel="Continue"
        tone="default"
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );

    const defaultConfirm = screen.getByRole('button', { name: 'Continue' });
    expect(defaultConfirm.classList.contains('ui-button--primary')).toBe(true);
  });

  it('supports default, custom, and hidden cancel label variants in confirm dialog', async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    const { rerender } = render(
      <ConfirmDialog open title="Confirm" onConfirm={onConfirm} onCancel={onCancel} />,
    );

    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onCancel).toHaveBeenCalledTimes(1);

    rerender(
      <ConfirmDialog
        open
        title="Confirm"
        cancelLabel="Never mind"
        confirmLabel="OK"
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Never mind' }));
    await user.click(screen.getByRole('button', { name: 'OK' }));
    expect(onCancel).toHaveBeenCalledTimes(2);
    expect(onConfirm).toHaveBeenCalledTimes(1);

    rerender(
      <ConfirmDialog
        open
        title="Confirm"
        cancelLabel={null}
        confirmLabel="Only action"
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );

    expect(screen.queryByRole('button', { name: /cancel/i })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Never mind' })).toBeNull();
  });

  it('enforces requireValue in prompt dialog and supports Enter-key submit', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    const onCancel = vi.fn();

    render(
      <PromptDialog
        open
        title="Rename"
        requireValue
        defaultValue=""
        onSubmit={onSubmit}
        onCancel={onCancel}
      />,
    );

    const input = screen.getByRole('textbox') as HTMLInputElement;
    const saveButton = screen.getByRole('button', { name: 'Save' }) as HTMLButtonElement;

    expect(saveButton.disabled).toBe(true);

    await user.type(input, '   ');
    expect(saveButton.disabled).toBe(true);
    await user.keyboard('{Enter}');
    expect(onSubmit).not.toHaveBeenCalled();

    await user.clear(input);
    await user.type(input, 'Invoice Name');
    expect(saveButton.disabled).toBe(false);

    await user.keyboard('{Enter}');
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenLastCalledWith('Invoice Name');
  });

  it('renders saved forms list, wires delete actions, and handles deleting state', async () => {
    const user = userEvent.setup();
    const onDelete = vi.fn();
    const onClose = vi.fn();

    render(
      <SavedFormsLimitDialog
        open
        maxSavedForms={2}
        savedForms={[
          { id: 'a', name: 'Form A', createdAt: '2025-01-10T00:00:00.000Z' },
          { id: 'b', name: 'Form B', createdAt: '' },
        ]}
        deletingFormId="a"
        onDelete={onDelete}
        onClose={onClose}
      />,
    );

    expect(screen.getByText('Form A')).toBeTruthy();
    expect(screen.getByText('Form B')).toBeTruthy();
    expect(screen.getByText('Unknown date')).toBeTruthy();

    const deletingButton = screen.getByRole('button', { name: 'Delete saved form Form A' }) as HTMLButtonElement;
    const activeDeleteButton = screen.getByRole('button', { name: 'Delete saved form Form B' });

    expect(deletingButton.disabled).toBe(true);
    expect(deletingButton.textContent).toBe('Deleting...');

    await user.click(deletingButton);
    await user.click(activeDeleteButton);

    expect(onDelete).toHaveBeenCalledTimes(1);
    expect(onDelete).toHaveBeenCalledWith('b');

    await user.click(screen.getByRole('button', { name: 'Exit without saving' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('shows empty saved-forms message when list is empty', () => {
    render(
      <SavedFormsLimitDialog
        open
        maxSavedForms={3}
        savedForms={[]}
        onDelete={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText('No saved forms are available.')).toBeTruthy();
  });
});
