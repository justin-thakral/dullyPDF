import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import FeaturePlanPage from '../../../../src/components/pages/FeaturePlanPage';

const authState = vi.hoisted(() => ({
  user: null as any,
  callbacks: new Set<(user: any) => void>(),
}));

const authMocks = vi.hoisted(() => ({
  onAuthStateChanged: vi.fn((callback: (user: any) => void) => {
    authState.callbacks.add(callback);
    callback(authState.user);
    return () => authState.callbacks.delete(callback);
  }),
}));

const apiMocks = vi.hoisted(() => ({
  getProfile: vi.fn(),
}));

const billingCheckoutMocks = vi.hoisted(() => ({
  createTrustedBillingCheckoutForUser: vi.fn(),
}));

vi.mock('../../../../src/services/auth', () => ({
  Auth: authMocks,
}));

vi.mock('../../../../src/services/api', () => ({
  ApiService: apiMocks,
}));

vi.mock('../../../../src/utils/billingCheckout', () => ({
  createTrustedBillingCheckoutForUser: billingCheckoutMocks.createTrustedBillingCheckoutForUser,
}));

vi.mock('../../../../src/utils/seo', () => ({
  applyRouteSeo: vi.fn(),
}));

const setAuthUser = (user: any) => {
  authState.user = user;
  authState.callbacks.forEach((callback) => callback(user));
};

const baseBillingPlans = {
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
};

describe('FeaturePlanPage', () => {
  beforeEach(() => {
    authState.user = null;
    authState.callbacks.clear();
    authMocks.onAuthStateChanged.mockClear();
    apiMocks.getProfile.mockReset();
    billingCheckoutMocks.createTrustedBillingCheckoutForUser.mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('renders free plan content and related links', () => {
    render(<FeaturePlanPage pageKey="free-features" />);

    expect(screen.getByRole('heading', { level: 1, name: 'Free DullyPDF Features for PDF-to-Form Setup' })).toBeTruthy();
    expect(screen.getAllByRole('link', { name: 'Premium Features' }).some((link) => link.getAttribute('href') === '/premium-features')).toBe(true);
    expect(screen.getByText('Unlimited PDF-to-form setup and access to the form builder.')).toBeTruthy();
  });

  it('shows a sign-in CTA on the premium page when signed out', async () => {
    render(<FeaturePlanPage pageKey="premium-features" />);

    expect(await screen.findByRole('link', { name: 'Sign In to Buy' })).toBeTruthy();
    expect(screen.getByText('Signed out')).toBeTruthy();
    expect(apiMocks.getProfile).not.toHaveBeenCalled();
  });

  it('renders live purchase buttons for signed-in free users and surfaces checkout errors', async () => {
    const user = userEvent.setup();
    setAuthUser({ uid: 'user-1', email: 'owner@example.com' });
    apiMocks.getProfile.mockResolvedValue({
      role: 'basic',
      billing: {
        enabled: true,
        plans: baseBillingPlans,
        hasSubscription: false,
      },
      limits: {
        detectMaxPages: 10,
        fillableMaxPages: 20,
        savedFormsMax: 5,
        fillLinksActiveMax: 1,
        fillLinkResponsesMax: 5,
      },
    });
    billingCheckoutMocks.createTrustedBillingCheckoutForUser.mockRejectedValue(new Error('Checkout unavailable.'));

    render(<FeaturePlanPage pageKey="premium-features" />);

    const buyButton = await screen.findByRole('button', { name: /Buy Pro Monthly/ });
    expect(screen.getByText('Signed in as owner@example.com')).toBeTruthy();

    await user.click(buyButton);

    await waitFor(() => {
      expect(billingCheckoutMocks.createTrustedBillingCheckoutForUser).toHaveBeenCalledWith('user-1', 'pro_monthly');
    });
    expect(screen.getByText('Checkout unavailable.')).toBeTruthy();
  });

  it('shows an already-premium message instead of upgrade buttons for premium accounts', async () => {
    setAuthUser({ uid: 'user-2', email: 'pro@example.com' });
    apiMocks.getProfile.mockResolvedValue({
      role: 'pro',
      billing: {
        enabled: true,
        plans: baseBillingPlans,
        hasSubscription: true,
      },
      limits: {
        detectMaxPages: 10,
        fillableMaxPages: 20,
        savedFormsMax: 5,
        fillLinksActiveMax: 10,
        fillLinkResponsesMax: 10000,
      },
    });

    render(<FeaturePlanPage pageKey="premium-features" />);

    expect(await screen.findByText('This account already has premium access. Use Profile in the workspace to manage cancellation or refills.')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Buy Pro Monthly/ })).toBeNull();
  });
});
