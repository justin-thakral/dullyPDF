import { act, render, waitFor } from '@testing-library/react';
import { useEffect, useState } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { UserProfile } from '../../../src/services/api';
import {
  useDowngradeRetentionRuntime,
  type UseDowngradeRetentionRuntimeDeps,
} from '../../../src/hooks/useDowngradeRetentionRuntime';

const createBillingCheckoutSessionMock = vi.hoisted(() => vi.fn());
const cancelBillingSubscriptionMock = vi.hoisted(() => vi.fn());
const updateDowngradeRetentionMock = vi.hoisted(() => vi.fn());
const deleteDowngradeRetentionNowMock = vi.hoisted(() => vi.fn());
const reconcileBillingCheckoutFulfillmentMock = vi.hoisted(() => vi.fn());
const trackGoogleAdsBillingPurchaseMock = vi.hoisted(() => vi.fn());

vi.mock('../../../src/services/api', () => ({
  ApiService: {
    createBillingCheckoutSession: createBillingCheckoutSessionMock,
    cancelBillingSubscription: cancelBillingSubscriptionMock,
    updateDowngradeRetention: updateDowngradeRetentionMock,
    deleteDowngradeRetentionNow: deleteDowngradeRetentionNowMock,
    reconcileBillingCheckoutFulfillment: reconcileBillingCheckoutFulfillmentMock,
  },
}));

vi.mock('../../../src/utils/googleAds', () => ({
  trackGoogleAdsBillingPurchase: trackGoogleAdsBillingPurchaseMock,
}));

type HarnessDeps = Omit<UseDowngradeRetentionRuntimeDeps, 'userProfile' | 'mutateUserProfile'> & {
  initialUserProfile: UserProfile | null;
};

function makeProfile(overrides: Partial<UserProfile> = {}): UserProfile {
  return {
    email: 'qa@example.com',
    role: 'base',
    creditsRemaining: 10,
    monthlyCreditsRemaining: 0,
    refillCreditsRemaining: 0,
    availableCredits: 10,
    refillCreditsLocked: false,
    billing: {
      enabled: true,
      hasSubscription: false,
      cancelAtPeriodEnd: false,
      plans: {
        pro_monthly: {
          kind: 'pro_monthly',
          mode: 'subscription',
          priceId: 'price_monthly',
          label: 'Pro Monthly',
          currency: 'usd',
          unitAmount: 1000,
          interval: 'month',
        },
      },
    },
    retention: {
      status: 'grace_period',
      policyVersion: 1,
      downgradedAt: '2026-03-01T00:00:00Z',
      graceEndsAt: '2026-03-15T00:00:00Z',
      daysRemaining: 5,
      savedFormsLimit: 2,
      fillLinksActiveLimit: 2,
      keptTemplateIds: ['tpl-1', 'tpl-2'],
      pendingDeleteTemplateIds: ['tpl-3'],
      pendingDeleteLinkIds: ['link-3'],
      counts: {
        keptTemplates: 2,
        pendingTemplates: 1,
        affectedGroups: 0,
        pendingLinks: 1,
      },
      templates: [
        { id: 'tpl-1', name: 'Packet Alpha', status: 'kept' },
        { id: 'tpl-2', name: 'Packet Beta', status: 'kept' },
        { id: 'tpl-3', name: 'Packet Gamma', status: 'pending_delete' },
      ],
      groups: [],
      links: [],
    },
    limits: {
      detectMaxPages: 10,
      fillableMaxPages: 20,
      savedFormsMax: 5,
      fillLinksActiveMax: 2,
      fillLinkResponsesMax: 100,
    },
    ...overrides,
  };
}

function createDeps(overrides: Partial<HarnessDeps> = {}): HarnessDeps {
  return {
    authReady: true,
    assumeAuthReady: false,
    verifiedUser: { uid: 'user-1' } as any,
    initialUserProfile: makeProfile(),
    loadUserProfile: vi.fn().mockResolvedValue(makeProfile()),
    setBannerNotice: vi.fn(),
    requestConfirm: vi.fn().mockResolvedValue(true),
    refreshSavedForms: vi.fn().mockResolvedValue([]),
    refreshGroups: vi.fn().mockResolvedValue([]),
    activeSavedFormId: 'tpl-2',
    activeGroupTemplates: [],
    clearWorkspace: vi.fn(),
    ...overrides,
  };
}

function renderHookHarness(initialDeps: HarnessDeps) {
  let latest: ReturnType<typeof useDowngradeRetentionRuntime> | null = null;

  function Harness({ deps }: { deps: HarnessDeps }) {
    const [userProfile, setUserProfile] = useState<UserProfile | null>(deps.initialUserProfile);

    useEffect(() => {
      setUserProfile(deps.initialUserProfile);
    }, [deps.initialUserProfile]);

    latest = useDowngradeRetentionRuntime({
      authReady: deps.authReady,
      assumeAuthReady: deps.assumeAuthReady,
      verifiedUser: deps.verifiedUser,
      userProfile,
      loadUserProfile: deps.loadUserProfile,
      mutateUserProfile: (updater) => {
        setUserProfile((previous) => updater(previous));
      },
      setBannerNotice: deps.setBannerNotice,
      requestConfirm: deps.requestConfirm,
      refreshSavedForms: deps.refreshSavedForms,
      refreshGroups: deps.refreshGroups,
      activeSavedFormId: deps.activeSavedFormId,
      activeGroupTemplates: deps.activeGroupTemplates,
      clearWorkspace: deps.clearWorkspace,
    });

    return null;
  }

  const view = render(<Harness deps={initialDeps} />);

  return {
    rerender(nextDeps: HarnessDeps) {
      view.rerender(<Harness deps={nextDeps} />);
    },
    get current() {
      if (!latest) {
        throw new Error('hook not initialized');
      }
      return latest;
    },
  };
}

describe('useDowngradeRetentionRuntime', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/');
    window.sessionStorage.clear();
    createBillingCheckoutSessionMock.mockReset();
    cancelBillingSubscriptionMock.mockReset();
    updateDowngradeRetentionMock.mockReset();
    deleteDowngradeRetentionNowMock.mockReset();
    reconcileBillingCheckoutFulfillmentMock.mockReset();
    trackGoogleAdsBillingPurchaseMock.mockReset();
  });

  it('auto-opens once for a downgrade event and only reopens when the visit key changes', async () => {
    const deps = createDeps();
    const hook = renderHookHarness(deps);

    await waitFor(() => {
      expect(hook.current.showDowngradeRetentionDialog).toBe(true);
    });

    act(() => {
      hook.current.closeDowngradeRetentionDialog();
    });
    expect(hook.current.showDowngradeRetentionDialog).toBe(false);

    hook.rerender(deps);
    await waitFor(() => {
      expect(hook.current.showDowngradeRetentionDialog).toBe(false);
    });

    const nextDeps = createDeps({
      initialUserProfile: makeProfile({
        retention: {
          ...makeProfile().retention!,
          graceEndsAt: '2026-03-20T00:00:00Z',
        },
      }),
    });
    hook.rerender(nextDeps);

    await waitFor(() => {
      expect(hook.current.showDowngradeRetentionDialog).toBe(true);
    });
  });

  it('updates local retention immediately and shows an info banner when refreshes partially fail', async () => {
    const nextRetention = {
      ...makeProfile().retention!,
      keptTemplateIds: ['tpl-1', 'tpl-4'],
      pendingDeleteTemplateIds: ['tpl-2', 'tpl-3'],
    };
    updateDowngradeRetentionMock.mockResolvedValue(nextRetention);

    const deps = createDeps({
      loadUserProfile: vi.fn().mockResolvedValue(null),
      refreshSavedForms: vi.fn().mockRejectedValue(new Error('saved forms refresh failed')),
      refreshGroups: vi.fn().mockResolvedValue([]),
    });
    const hook = renderHookHarness(deps);

    await act(async () => {
      await hook.current.handleSaveDowngradeRetentionSelection(['tpl-1', 'tpl-4']);
    });

    expect(updateDowngradeRetentionMock).toHaveBeenCalledWith(['tpl-1', 'tpl-4']);
    expect(hook.current.currentDowngradeRetention?.keptTemplateIds).toEqual(['tpl-1', 'tpl-4']);
    expect(deps.setBannerNotice).toHaveBeenLastCalledWith(expect.objectContaining({
      tone: 'info',
      message: expect.stringContaining('some views may need a refresh'),
    }));
  });

  it('clears retention locally, closes the dialog, and resets the workspace when delete-now removes the active template', async () => {
    deleteDowngradeRetentionNowMock.mockResolvedValue({
      success: true,
      deletedTemplateIds: ['tpl-2'],
      deletedLinkIds: ['link-2'],
    });

    const deps = createDeps();
    const hook = renderHookHarness(deps);

    await waitFor(() => {
      expect(hook.current.showDowngradeRetentionDialog).toBe(true);
    });

    await act(async () => {
      await hook.current.handleDeleteDowngradeRetentionNow();
    });

    expect(deps.requestConfirm).toHaveBeenCalledTimes(1);
    expect(deleteDowngradeRetentionNowMock).toHaveBeenCalledTimes(1);
    expect(deps.clearWorkspace).toHaveBeenCalledTimes(1);
    expect(hook.current.currentDowngradeRetention).toBeNull();
    expect(hook.current.showDowngradeRetentionDialog).toBe(false);
    expect(deps.setBannerNotice).toHaveBeenLastCalledWith(expect.objectContaining({
      tone: 'success',
      message: expect.stringContaining('dependent Fill By Link records were deleted'),
    }));
  });

  it('does not reconcile billing success without a matching pending checkout marker', async () => {
    window.history.replaceState({}, '', '/?billing=success');
    const profile = makeProfile({ retention: null, role: 'pro' });
    const deps = createDeps({
      initialUserProfile: profile,
      loadUserProfile: vi.fn().mockResolvedValue(profile),
    });

    renderHookHarness(deps);

    await waitFor(() => {
      expect(deps.loadUserProfile).toHaveBeenCalled();
    });
    expect(reconcileBillingCheckoutFulfillmentMock).not.toHaveBeenCalled();
    expect(deps.setBannerNotice).toHaveBeenLastCalledWith(expect.objectContaining({
      tone: 'info',
      message: expect.stringContaining('did not have a matching pending checkout'),
    }));
    expect(window.location.search.includes('billing=')).toBe(false);
  });

  it('preserves the pending checkout marker until a verified user can process the billing return', async () => {
    const startedAt = Date.now();
    window.history.replaceState({}, '', '/?billing=success');
    window.sessionStorage.setItem('dullypdf.pendingBillingCheckout', JSON.stringify({
      userId: 'user-1',
      requestedKind: 'pro_monthly',
      sessionId: 'cs_pending_123',
      attemptId: 'attempt_pending_123',
      checkoutPriceId: 'price_monthly',
      startedAt,
    }));
    reconcileBillingCheckoutFulfillmentMock.mockResolvedValue({
      success: true,
      dryRun: false,
      scope: 'self',
      auditedEventCount: 1,
      candidateEventCount: 1,
      pendingReconciliationCount: 1,
      reconciledCount: 1,
      alreadyProcessedCount: 0,
      processingCount: 0,
      retryableCount: 0,
      failedCount: 0,
      invalidCount: 0,
      skippedForUserCount: 0,
      events: [
        {
          eventId: 'checkout_session:cs_pending_123',
          checkoutSessionId: 'cs_pending_123',
          checkoutAttemptId: 'attempt_pending_123',
          checkoutKind: 'pro_monthly',
          checkoutPriceId: 'price_monthly',
          billingEventStatus: null,
        },
      ],
    });

    const profile = makeProfile({ retention: null, role: 'pro' });
    const initialDeps = createDeps({
      verifiedUser: null,
      initialUserProfile: profile,
      loadUserProfile: vi.fn().mockResolvedValue(profile),
    });
    const hook = renderHookHarness(initialDeps);

    await waitFor(() => {
      expect(hook.current.billingCheckoutInProgressKind).toBeNull();
    });
    expect(reconcileBillingCheckoutFulfillmentMock).not.toHaveBeenCalled();
    expect(window.sessionStorage.getItem('dullypdf.pendingBillingCheckout')).not.toBeNull();
    expect(window.location.search).toContain('billing=success');

    hook.rerender(createDeps({
      verifiedUser: { uid: 'user-1' } as any,
      initialUserProfile: profile,
      loadUserProfile: initialDeps.loadUserProfile,
      setBannerNotice: initialDeps.setBannerNotice,
      requestConfirm: initialDeps.requestConfirm,
      refreshSavedForms: initialDeps.refreshSavedForms,
      refreshGroups: initialDeps.refreshGroups,
      activeSavedFormId: initialDeps.activeSavedFormId,
      activeGroupTemplates: initialDeps.activeGroupTemplates,
      clearWorkspace: initialDeps.clearWorkspace,
    }));

    await waitFor(() => {
      expect(reconcileBillingCheckoutFulfillmentMock).toHaveBeenCalledWith({
        lookbackHours: 72,
        dryRun: false,
        sessionId: 'cs_pending_123',
        attemptId: 'attempt_pending_123',
      });
    });
    await waitFor(() => {
      expect(window.sessionStorage.getItem('dullypdf.pendingBillingCheckout')).toBeNull();
    });
    expect(window.location.search.includes('billing=')).toBe(false);
  });

  it('ignores and preserves a pending checkout marker that belongs to a different user', async () => {
    const startedAt = Date.now();
    window.history.replaceState({}, '', '/?billing=success');
    window.sessionStorage.setItem('dullypdf.pendingBillingCheckout', JSON.stringify({
      userId: 'user-1',
      requestedKind: 'pro_monthly',
      sessionId: 'cs_other_user_123',
      attemptId: 'attempt_other_user_123',
      checkoutPriceId: 'price_monthly',
      startedAt,
    }));
    const profile = makeProfile({ retention: null, role: 'pro' });
    const deps = createDeps({
      verifiedUser: { uid: 'user-2' } as any,
      initialUserProfile: profile,
      loadUserProfile: vi.fn().mockResolvedValue(profile),
    });

    renderHookHarness(deps);

    await waitFor(() => {
      expect(deps.loadUserProfile).toHaveBeenCalled();
    });
    expect(reconcileBillingCheckoutFulfillmentMock).not.toHaveBeenCalled();
    expect(window.sessionStorage.getItem('dullypdf.pendingBillingCheckout')).toContain('"userId":"user-1"');
    expect(deps.setBannerNotice).toHaveBeenLastCalledWith(expect.objectContaining({
      tone: 'info',
      message: expect.stringContaining('did not have a matching pending checkout'),
    }));
    expect(window.location.search.includes('billing=')).toBe(false);
  });

  it('keeps the pending checkout marker when billing success cannot be confirmed yet', async () => {
    const startedAt = Date.now();
    window.history.replaceState({}, '', '/?billing=success');
    window.sessionStorage.setItem('dullypdf.pendingBillingCheckout', JSON.stringify({
      userId: 'user-1',
      requestedKind: 'pro_monthly',
      sessionId: 'cs_unconfirmed_123',
      attemptId: 'attempt_unconfirmed_123',
      checkoutPriceId: 'price_monthly',
      startedAt,
    }));
    reconcileBillingCheckoutFulfillmentMock.mockResolvedValue({
      success: true,
      dryRun: false,
      scope: 'self',
      auditedEventCount: 1,
      candidateEventCount: 0,
      pendingReconciliationCount: 0,
      reconciledCount: 0,
      alreadyProcessedCount: 0,
      processingCount: 0,
      retryableCount: 0,
      failedCount: 0,
      invalidCount: 0,
      skippedForUserCount: 0,
      events: [],
    });
    const profile = makeProfile({ retention: null, role: 'pro' });
    const deps = createDeps({
      verifiedUser: { uid: 'user-1' } as any,
      initialUserProfile: profile,
      loadUserProfile: vi.fn().mockResolvedValue(profile),
    });

    renderHookHarness(deps);

    await waitFor(() => {
      expect(reconcileBillingCheckoutFulfillmentMock).toHaveBeenCalledWith({
        lookbackHours: 72,
        dryRun: false,
        sessionId: 'cs_unconfirmed_123',
        attemptId: 'attempt_unconfirmed_123',
      });
    });
    expect(window.sessionStorage.getItem('dullypdf.pendingBillingCheckout')).toContain('"sessionId":"cs_unconfirmed_123"');
    expect(deps.setBannerNotice).toHaveBeenLastCalledWith(expect.objectContaining({
      tone: 'info',
      message: expect.stringContaining('could not be confirmed yet'),
    }));
    expect(window.location.search.includes('billing=')).toBe(false);
  });

  it('drops expired pending checkout markers before processing billing success', async () => {
    window.history.replaceState({}, '', '/?billing=success');
    window.sessionStorage.setItem('dullypdf.pendingBillingCheckout', JSON.stringify({
      userId: 'user-1',
      requestedKind: 'pro_monthly',
      sessionId: 'cs_expired_123',
      attemptId: 'attempt_expired_123',
      checkoutPriceId: 'price_monthly',
      startedAt: Date.now() - (7 * 60 * 60 * 1000),
    }));
    const profile = makeProfile({ retention: null, role: 'pro' });
    const deps = createDeps({
      verifiedUser: { uid: 'user-1' } as any,
      initialUserProfile: profile,
      loadUserProfile: vi.fn().mockResolvedValue(profile),
    });

    renderHookHarness(deps);

    await waitFor(() => {
      expect(deps.loadUserProfile).toHaveBeenCalled();
    });
    expect(reconcileBillingCheckoutFulfillmentMock).not.toHaveBeenCalled();
    expect(window.sessionStorage.getItem('dullypdf.pendingBillingCheckout')).toBeNull();
    expect(deps.setBannerNotice).toHaveBeenLastCalledWith(expect.objectContaining({
      tone: 'info',
      message: expect.stringContaining('marker expired'),
    }));
  });

  it('rejects untrusted checkout URLs before redirecting or persisting a pending checkout marker', async () => {
    createBillingCheckoutSessionMock.mockResolvedValue({
      checkoutUrl: 'https://evil.example.com/session',
      sessionId: 'cs_untrusted_123',
      attemptId: 'attempt_untrusted_123',
      checkoutPriceId: 'price_monthly',
    });

    const profile = makeProfile({ retention: null, role: 'base' });
    const deps = createDeps({
      verifiedUser: { uid: 'user-1' } as any,
      initialUserProfile: profile,
      loadUserProfile: vi.fn().mockResolvedValue(profile),
    });
    const hook = renderHookHarness(deps);

    await act(async () => {
      await hook.current.handleStartBillingCheckout('pro_monthly');
    });

    expect(window.sessionStorage.getItem('dullypdf.pendingBillingCheckout')).toBeNull();
    expect(deps.setBannerNotice).toHaveBeenLastCalledWith(expect.objectContaining({
      tone: 'error',
      message: 'Stripe checkout URL is not trusted.',
    }));
  });

  it('does not clear the pending checkout marker for a billing cancel return without Stripe correlation', async () => {
    const startedAt = Date.now();
    window.history.replaceState({}, '', '/?billing=cancel');
    window.sessionStorage.setItem('dullypdf.pendingBillingCheckout', JSON.stringify({
      userId: 'user-1',
      requestedKind: 'pro_monthly',
      sessionId: 'cs_cancel_pending_123',
      attemptId: 'attempt_cancel_pending_123',
      checkoutPriceId: 'price_monthly',
      startedAt,
    }));
    const profile = makeProfile({ retention: null, role: 'pro' });
    const deps = createDeps({
      verifiedUser: { uid: 'user-1' } as any,
      initialUserProfile: profile,
      loadUserProfile: vi.fn().mockResolvedValue(profile),
    });

    renderHookHarness(deps);

    await waitFor(() => {
      expect(deps.setBannerNotice).toHaveBeenLastCalledWith(expect.objectContaining({
        tone: 'info',
        message: expect.stringContaining('Checkout was canceled'),
      }));
    });
    expect(reconcileBillingCheckoutFulfillmentMock).not.toHaveBeenCalled();
    expect(window.sessionStorage.getItem('dullypdf.pendingBillingCheckout')).toContain('"sessionId":"cs_cancel_pending_123"');
    expect(window.location.search.includes('billing=')).toBe(false);
  });
});
