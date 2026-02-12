import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ProfilePage from '../../../../src/components/pages/ProfilePage';
import type { ProfileLimits, SavedFormSummary } from '../../../../src/services/api';

const limits: ProfileLimits = {
  detectMaxPages: 10,
  fillableMaxPages: 20,
  savedFormsMax: 5,
};

const savedForms: SavedFormSummary[] = [
  { id: 'form-alpha', name: 'Intake Form Alpha', createdAt: '2026-01-01T00:00:00Z' },
  { id: 'form-beta', name: 'Consent Form Beta', createdAt: '2026-01-02T00:00:00Z' },
  { id: 'form-gamma', name: 'Referral Gamma', createdAt: '2026-01-03T00:00:00Z' },
];

describe('ProfilePage', () => {
  it('renders tier and limits cards for basic and god users', () => {
    const { rerender } = render(
      <ProfilePage
        email="basic@example.com"
        role="basic"
        creditsRemaining={8}
        limits={limits}
        savedForms={savedForms}
        onSelectSavedForm={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText('Basic tier')).toBeTruthy();
    expect(screen.getByText('8')).toBeTruthy();
    expect(screen.getByText(String(limits.detectMaxPages))).toBeTruthy();
    expect(screen.getByText(String(limits.fillableMaxPages))).toBeTruthy();
    expect(screen.getAllByText(String(limits.savedFormsMax)).length).toBeGreaterThan(0);

    rerender(
      <ProfilePage
        email="god@example.com"
        role="god"
        creditsRemaining={0}
        limits={limits}
        savedForms={savedForms}
        onSelectSavedForm={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText('God tier')).toBeTruthy();
    expect(screen.getByText('Unlimited')).toBeTruthy();
  });

  it('filters saved forms by search query and shows empty state', async () => {
    const user = userEvent.setup();

    render(
      <ProfilePage
        email="search@example.com"
        role="basic"
        creditsRemaining={5}
        limits={limits}
        savedForms={savedForms}
        onSelectSavedForm={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    const searchInput = screen.getByRole('searchbox', { name: 'Search saved forms' });
    await user.type(searchInput, 'consent');

    expect(screen.queryByRole('button', { name: 'Intake Form Alpha' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Consent Form Beta' })).toBeTruthy();

    await user.clear(searchInput);
    await user.type(searchInput, 'no-match');

    expect(screen.getByText('No saved forms match your search.')).toBeTruthy();
  });

  it('triggers select/delete callbacks and disables actions for deleting forms', async () => {
    const user = userEvent.setup();
    const onSelectSavedForm = vi.fn();
    const onDeleteSavedForm = vi.fn();

    render(
      <ProfilePage
        email="actions@example.com"
        role="basic"
        creditsRemaining={2}
        limits={limits}
        savedForms={savedForms}
        onSelectSavedForm={onSelectSavedForm}
        onDeleteSavedForm={onDeleteSavedForm}
        deletingFormId="form-beta"
        onClose={vi.fn()}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Intake Form Alpha' }));
    await user.click(screen.getByRole('button', { name: 'Delete saved form Intake Form Alpha' }));

    expect(onSelectSavedForm).toHaveBeenCalledWith('form-alpha');
    expect(onDeleteSavedForm).toHaveBeenCalledWith('form-alpha');

    const deletingNameButton = screen.getByRole('button', { name: 'Consent Form Beta' }) as HTMLButtonElement;
    const deletingDeleteButton = screen.getByRole('button', {
      name: 'Delete saved form Consent Form Beta',
    }) as HTMLButtonElement;

    expect(deletingNameButton.disabled).toBe(true);
    expect(deletingDeleteButton.disabled).toBe(true);

    await user.click(deletingNameButton);
    await user.click(deletingDeleteButton);

    expect(onSelectSavedForm).toHaveBeenCalledTimes(1);
    expect(onDeleteSavedForm).toHaveBeenCalledTimes(1);
  });

  it('wires header navigation callbacks for close and sign out', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const onSignOut = vi.fn();

    render(
      <ProfilePage
        email="header@example.com"
        role="basic"
        creditsRemaining={1}
        limits={limits}
        savedForms={savedForms}
        onSelectSavedForm={vi.fn()}
        onClose={onClose}
        onSignOut={onSignOut}
      />,
    );

    await user.click(screen.getByRole('button', { name: '← Back to workspace' }));
    await user.click(screen.getByRole('button', { name: 'Sign out' }));

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onSignOut).toHaveBeenCalledTimes(1);
  });
});
