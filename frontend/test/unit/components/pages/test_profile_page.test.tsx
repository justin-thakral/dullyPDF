import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ProfilePage from '../../../../src/components/pages/ProfilePage';
import type {
  BillingProfileConfig,
  DowngradeRetentionSummary,
  ProfileLimits,
  SavedFormSummary,
} from '../../../../src/services/api';

const limits: ProfileLimits = {
  detectMaxPages: 10,
  fillableMaxPages: 20,
  savedFormsMax: 5,
  fillLinksActiveMax: 1,
  fillLinkResponsesMax: 5,
};

const savedForms: SavedFormSummary[] = [
  { id: 'form-alpha', name: 'Intake Form Alpha', createdAt: '2026-01-01T00:00:00Z' },
  { id: 'form-beta', name: 'Consent Form Beta', createdAt: '2026-01-02T00:00:00Z' },
  { id: 'form-gamma', name: 'Referral Gamma', createdAt: '2026-01-03T00:00:00Z' },
  { id: 'form-delta', name: 'Follow Up Delta', createdAt: '2026-01-04T00:00:00Z' },
];

const billingConfig: BillingProfileConfig = {
  enabled: true,
  plans: {
    pro_monthly: {
      kind: 'pro_monthly',
      mode: 'subscription',
      priceId: 'price_monthly',
      label: 'Pro Monthly',
      currency: 'usd',
      unitAmount: 1000,
      interval: 'month',
      refillCredits: null,
    },
    pro_yearly: {
      kind: 'pro_yearly',
      mode: 'subscription',
      priceId: 'price_yearly',
      label: 'Pro Yearly',
      currency: 'usd',
      unitAmount: 7500,
      interval: 'year',
      refillCredits: null,
    },
    refill_500: {
      kind: 'refill_500',
      mode: 'payment',
      priceId: 'price_refill',
      label: 'Refill 500 Credits',
      currency: 'usd',
      unitAmount: 900,
      interval: null,
      refillCredits: 500,
    },
  },
};

const retentionSummary: DowngradeRetentionSummary = {
  status: 'grace_period',
  policyVersion: 1,
  downgradedAt: '2026-03-01T00:00:00Z',
  graceEndsAt: '2026-03-31T00:00:00Z',
  daysRemaining: 21,
  savedFormsLimit: 3,
  fillLinksActiveLimit: 1,
  keptTemplateIds: ['form-alpha', 'form-beta', 'form-gamma'],
  pendingDeleteTemplateIds: ['form-delta'],
  pendingDeleteLinkIds: ['link-delta'],
  counts: {
    keptTemplates: 3,
    pendingTemplates: 1,
    affectedGroups: 1,
    pendingLinks: 1,
    closedLinks: 1,
  },
  templates: [
    { id: 'form-alpha', name: 'Intake Form Alpha', createdAt: '2026-01-01T00:00:00Z', status: 'kept' },
    { id: 'form-beta', name: 'Consent Form Beta', createdAt: '2026-01-02T00:00:00Z', status: 'kept' },
    { id: 'form-gamma', name: 'Referral Gamma', createdAt: '2026-01-03T00:00:00Z', status: 'kept' },
    { id: 'form-delta', name: 'Follow Up Delta', createdAt: '2026-01-04T00:00:00Z', status: 'pending_delete' },
  ],
  groups: [{ id: 'group-1', name: 'Admissions', templateCount: 4, pendingTemplateCount: 1, willDelete: false }],
  links: [{ id: 'link-delta', title: 'Delta Link', scopeType: 'template', status: 'closed', templateId: 'form-delta', pendingDeleteReason: 'template_pending_delete' }],
};

describe('ProfilePage', () => {
  it('renders tier and limits cards for basic and god users', () => {
    const { rerender } = render(
      <ProfilePage
        email="basic@example.com"
        role="basic"
        creditsRemaining={8}
        monthlyCreditsRemaining={0}
        refillCreditsRemaining={0}
        availableCredits={8}
        billingEnabled={billingConfig.enabled}
        billingPlans={billingConfig.plans}
        limits={limits}
        savedForms={savedForms}
        onSelectSavedForm={vi.fn()}
        onStartBillingCheckout={vi.fn()}
        onCancelBillingSubscription={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText('Basic tier')).toBeTruthy();
    expect(screen.getByText('8')).toBeTruthy();
    expect(screen.getByText(String(limits.detectMaxPages))).toBeTruthy();
    expect(screen.getByText(String(limits.fillableMaxPages))).toBeTruthy();
    expect(screen.getAllByText(String(limits.savedFormsMax)).length).toBeGreaterThan(0);
    expect(screen.getAllByText(String(limits.fillLinksActiveMax)).length).toBeGreaterThan(0);
    expect(screen.getAllByText(String(limits.fillLinkResponsesMax)).length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: /Upgrade to Pro Monthly/ })).toBeTruthy();
    expect(screen.getByRole('button', { name: /Upgrade to Pro Yearly/ })).toBeTruthy();
    expect(screen.getByRole('button', { name: /Refill 500 Credits/ })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Cancel Subscription' })).toBeTruthy();

    rerender(
      <ProfilePage
        email="god@example.com"
        role="god"
        creditsRemaining={0}
        monthlyCreditsRemaining={500}
        refillCreditsRemaining={100}
        availableCredits={600}
        billingEnabled={billingConfig.enabled}
        billingHasSubscription
        billingPlans={billingConfig.plans}
        limits={limits}
        savedForms={savedForms}
        onSelectSavedForm={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText('God tier')).toBeTruthy();
    expect(screen.getAllByText('Unlimited').length).toBeGreaterThan(0);
    expect(screen.queryByText('Billing')).toBeNull();
  });

  it('filters saved forms by search query and shows empty state', async () => {
    const user = userEvent.setup();

    render(
      <ProfilePage
        email="search@example.com"
        role="basic"
        creditsRemaining={5}
        monthlyCreditsRemaining={0}
        refillCreditsRemaining={0}
        availableCredits={5}
        billingEnabled={billingConfig.enabled}
        billingHasSubscription
        billingPlans={billingConfig.plans}
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

  it('shows a saved-forms loading message while backend startup is pending', () => {
    render(
      <ProfilePage
        email="loading@example.com"
        role="basic"
        creditsRemaining={3}
        monthlyCreditsRemaining={0}
        refillCreditsRemaining={0}
        availableCredits={3}
        billingEnabled={billingConfig.enabled}
        billingPlans={billingConfig.plans}
        limits={limits}
        savedForms={[]}
        savedFormsLoading
        onSelectSavedForm={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText('Loading saved forms while the backend starts…')).toBeTruthy();
    expect(screen.queryByText('No saved forms match your search.')).toBeNull();
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
        monthlyCreditsRemaining={0}
        refillCreditsRemaining={0}
        availableCredits={2}
        billingEnabled={billingConfig.enabled}
        billingHasSubscription
        billingPlans={billingConfig.plans}
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
        monthlyCreditsRemaining={0}
        refillCreditsRemaining={0}
        availableCredits={1}
        billingEnabled={billingConfig.enabled}
        billingHasSubscription
        billingPlans={billingConfig.plans}
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

  it('shows refill and cancel controls for pro users and locked refill note when downgraded', () => {
    const onCheckout = vi.fn();
    const onCancelSubscription = vi.fn();
    const { rerender } = render(
      <ProfilePage
        email="pro@example.com"
        role="pro"
        creditsRemaining={12}
        monthlyCreditsRemaining={10}
        refillCreditsRemaining={2}
        availableCredits={12}
        billingEnabled={billingConfig.enabled}
        billingHasSubscription
        billingPlans={billingConfig.plans}
        limits={limits}
        savedForms={savedForms}
        onSelectSavedForm={vi.fn()}
        onStartBillingCheckout={onCheckout}
        onCancelBillingSubscription={onCancelSubscription}
        onClose={vi.fn()}
      />,
    );

    const monthlyButton = screen.getByRole('button', { name: /Pro Monthly .*cancel current first/ }) as HTMLButtonElement;
    const yearlyButton = screen.getByRole('button', { name: /Pro Yearly .*cancel current first/ }) as HTMLButtonElement;
    expect(monthlyButton.disabled).toBe(true);
    expect(yearlyButton.disabled).toBe(true);
    expect(screen.getByRole('button', { name: /Refill 500 Credits/ })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Cancel Pro Subscription' })).toBeTruthy();
    expect(
      screen.getByText('Active Pro subscription detected. Cancel your current subscription before starting a new Pro checkout.'),
    ).toBeTruthy();

    rerender(
      <ProfilePage
        email="pro@example.com"
        role="pro"
        creditsRemaining={12}
        monthlyCreditsRemaining={10}
        refillCreditsRemaining={2}
        availableCredits={12}
        billingEnabled={billingConfig.enabled}
        billingHasSubscription
        billingCancelAtPeriodEnd
        billingCancelAt={1775000000}
        billingPlans={billingConfig.plans}
        limits={limits}
        savedForms={savedForms}
        onSelectSavedForm={vi.fn()}
        onStartBillingCheckout={onCheckout}
        onCancelBillingSubscription={onCancelSubscription}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByRole('button', { name: 'Cancelled' })).toBeTruthy();
    expect(screen.getByText(/Cancellation is scheduled for period end/)).toBeTruthy();

    rerender(
      <ProfilePage
        email="base-locked@example.com"
        role="base"
        creditsRemaining={0}
        monthlyCreditsRemaining={0}
        refillCreditsRemaining={50}
        availableCredits={0}
        refillCreditsLocked
        billingEnabled={billingConfig.enabled}
        billingPlans={billingConfig.plans}
        limits={limits}
        savedForms={savedForms}
        onSelectSavedForm={vi.fn()}
        onStartBillingCheckout={vi.fn()}
        onCancelBillingSubscription={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText('You have refill credits stored. Upgrade back to Pro to use them.')).toBeTruthy();
  });

  it('hides billing actions when billing is disabled', () => {
    render(
      <ProfilePage
        email="billing-disabled@example.com"
        role="base"
        creditsRemaining={3}
        monthlyCreditsRemaining={0}
        refillCreditsRemaining={0}
        availableCredits={3}
        billingEnabled={false}
        limits={limits}
        savedForms={savedForms}
        onSelectSavedForm={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText('Stripe billing is currently unavailable.')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Upgrade to Pro Monthly/ })).toBeNull();
  });

  it('shows billing fallback status when profile refresh fails', () => {
    render(
      <ProfilePage
        email="profile-error@example.com"
        role="base"
        creditsRemaining={3}
        monthlyCreditsRemaining={0}
        refillCreditsRemaining={0}
        availableCredits={3}
        billingEnabled={null}
        profileError="Request timed out."
        limits={limits}
        savedForms={savedForms}
        onSelectSavedForm={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText('Profile refresh failed: Request timed out.')).toBeTruthy();
    expect(
      screen.getByText('Billing status is temporarily unavailable because profile data could not be refreshed.'),
    ).toBeTruthy();
  });

  it('shows downgrade retention summary and re-open action', async () => {
    const user = userEvent.setup();
    const onOpenDowngradeRetention = vi.fn();

    render(
      <ProfilePage
        email="retention@example.com"
        role="base"
        creditsRemaining={3}
        monthlyCreditsRemaining={0}
        refillCreditsRemaining={0}
        availableCredits={3}
        billingEnabled={billingConfig.enabled}
        billingPlans={billingConfig.plans}
        retention={retentionSummary}
        limits={limits}
        savedForms={savedForms}
        onSelectSavedForm={vi.fn()}
        onOpenDowngradeRetention={onOpenDowngradeRetention}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText('Downgrade retention')).toBeTruthy();
    expect(screen.getByText(/queued for deletion on/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Review retention queue' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Follow Up Delta' })).toBeTruthy();
    expect(screen.getByText('Queued for deletion')).toBeTruthy();
    expect(screen.getAllByText('Kept').length).toBeGreaterThan(0);

    await user.click(screen.getByRole('button', { name: 'Review retention queue' }));
    expect(onOpenDowngradeRetention).toHaveBeenCalledTimes(1);
  });

  it('wires billing callbacks and busy labels', async () => {
    const user = userEvent.setup();
    const onStartBillingCheckout = vi.fn();
    const onCancelBillingSubscription = vi.fn();
    const { rerender } = render(
      <ProfilePage
        email="billing-actions@example.com"
        role="pro"
        creditsRemaining={10}
        monthlyCreditsRemaining={8}
        refillCreditsRemaining={2}
        availableCredits={10}
        billingEnabled={billingConfig.enabled}
        billingHasSubscription
        billingPlans={billingConfig.plans}
        limits={limits}
        savedForms={savedForms}
        onSelectSavedForm={vi.fn()}
        onStartBillingCheckout={onStartBillingCheckout}
        onCancelBillingSubscription={onCancelBillingSubscription}
        onClose={vi.fn()}
      />,
    );

    await user.click(screen.getByRole('button', { name: /Refill 500 Credits/ }));
    await user.click(screen.getByRole('button', { name: 'Cancel Pro Subscription' }));
    expect(onStartBillingCheckout).toHaveBeenCalledWith('refill_500');
    expect(onCancelBillingSubscription).toHaveBeenCalledTimes(1);

    rerender(
      <ProfilePage
        email="billing-actions@example.com"
        role="pro"
        creditsRemaining={10}
        monthlyCreditsRemaining={8}
        refillCreditsRemaining={2}
        availableCredits={10}
        billingEnabled={billingConfig.enabled}
        billingHasSubscription
        billingPlans={billingConfig.plans}
        limits={limits}
        savedForms={savedForms}
        onSelectSavedForm={vi.fn()}
        billingCheckoutInProgressKind="refill_500"
        billingCancelInProgress
        onStartBillingCheckout={onStartBillingCheckout}
        onCancelBillingSubscription={onCancelBillingSubscription}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByRole('button', { name: 'Starting checkout…' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Canceling…' })).toBeTruthy();
  });
});
