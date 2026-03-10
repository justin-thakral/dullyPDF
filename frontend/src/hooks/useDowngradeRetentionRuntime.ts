import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { User } from 'firebase/auth';
import {
  ApiService,
  type BillingCheckoutKind,
  type BillingPlanCatalogItem,
  type SavedFormSummary,
  type UserProfile,
} from '../services/api';
import type { BannerNotice, ConfirmDialogOptions } from '../types';
import {
  clearExpiredPendingBillingCheckout,
  clearPendingBillingCheckout,
  readPendingBillingCheckoutForUser,
  type PendingBillingCheckout,
} from '../utils/billingCheckoutState';
import { createTrustedBillingCheckoutForUser } from '../utils/billingCheckout';
import { debugLog } from '../utils/debug';
import { trackGoogleAdsBillingPurchase } from '../utils/googleAds';
const ZERO_DECIMAL_CURRENCIES = new Set([
  'BIF',
  'CLP',
  'DJF',
  'GNF',
  'JPY',
  'KMF',
  'KRW',
  'MGA',
  'PYG',
  'RWF',
  'UGX',
  'VND',
  'VUV',
  'XAF',
  'XOF',
  'XPF',
]);
type BillingReconcileEvent = Awaited<ReturnType<typeof ApiService.reconcileBillingCheckoutFulfillment>>['events'][number];

function findMatchingBillingCheckoutEvent(
  events: BillingReconcileEvent[],
  pendingCheckout: PendingBillingCheckout | null,
): BillingReconcileEvent | null {
  if (!pendingCheckout) return null;
  const normalizedSessionId = pendingCheckout.sessionId.trim();
  const normalizedAttemptId = (pendingCheckout.attemptId || '').trim();
  return events.find((event) => {
    const eventSessionId = (event.checkoutSessionId || '').trim();
    if (normalizedSessionId && eventSessionId && eventSessionId === normalizedSessionId) {
      return true;
    }
    const eventAttemptId = (event.checkoutAttemptId || '').trim();
    return Boolean(normalizedAttemptId && eventAttemptId && eventAttemptId === normalizedAttemptId);
  }) ?? null;
}

function resolveTrackedBillingKind(
  event: BillingReconcileEvent | null,
  pendingCheckout: PendingBillingCheckout | null,
): BillingCheckoutKind | null {
  const eventKind = (event?.checkoutKind || '').trim();
  if (eventKind === 'pro_monthly' || eventKind === 'pro_yearly' || eventKind === 'refill_500') {
    return eventKind;
  }
  return pendingCheckout?.requestedKind ?? null;
}

function resolveBillingPlanForTracking(
  profile: UserProfile | null,
  event: BillingReconcileEvent | null,
  pendingCheckout: PendingBillingCheckout | null,
): BillingPlanCatalogItem | null {
  const plans = profile?.billing?.plans;
  if (!plans) return null;
  const trackedKind = resolveTrackedBillingKind(event, pendingCheckout);
  if (trackedKind && plans[trackedKind]) {
    return plans[trackedKind] ?? null;
  }
  const targetPriceId = (event?.checkoutPriceId || pendingCheckout?.checkoutPriceId || '').trim();
  if (!targetPriceId) return null;
  return Object.values(plans).find((plan) => plan?.priceId === targetPriceId) ?? null;
}

function resolveGoogleAdsPurchaseValue(plan: BillingPlanCatalogItem | null): number | null {
  if (typeof plan?.unitAmount !== 'number' || !Number.isFinite(plan.unitAmount) || plan.unitAmount <= 0) {
    return null;
  }
  const normalizedCurrency = (plan.currency || '').trim().toUpperCase();
  const divisor = ZERO_DECIMAL_CURRENCIES.has(normalizedCurrency) ? 1 : 100;
  return Number((plan.unitAmount / divisor).toFixed(divisor === 1 ? 0 : 2));
}

export type UseDowngradeRetentionRuntimeDeps = {
  authReady: boolean;
  assumeAuthReady?: boolean;
  verifiedUser: User | null;
  userProfile: UserProfile | null;
  loadUserProfile: () => Promise<UserProfile | null>;
  mutateUserProfile: (updater: (previous: UserProfile | null) => UserProfile | null) => void;
  setBannerNotice: (notice: BannerNotice | null) => void;
  requestConfirm: (options: ConfirmDialogOptions) => Promise<boolean>;
  refreshSavedForms: (options?: { allowRetry?: boolean; throwOnError?: boolean }) => Promise<unknown>;
  refreshGroups: (options?: { throwOnError?: boolean }) => Promise<unknown>;
  activeSavedFormId: string | null;
  activeGroupTemplates: SavedFormSummary[];
  clearWorkspace: () => void;
};

export function useDowngradeRetentionRuntime(deps: UseDowngradeRetentionRuntimeDeps) {
  const {
    authReady,
    assumeAuthReady = false,
    verifiedUser,
    userProfile,
    loadUserProfile,
    mutateUserProfile,
    setBannerNotice,
    requestConfirm,
    refreshSavedForms,
    refreshGroups,
    activeSavedFormId,
    activeGroupTemplates,
    clearWorkspace,
  } = deps;
  const [billingCheckoutInProgressKind, setBillingCheckoutInProgressKind] = useState<BillingCheckoutKind | null>(null);
  const [billingCancelInProgress, setBillingCancelInProgress] = useState(false);
  const [showDowngradeRetentionDialog, setShowDowngradeRetentionDialog] = useState(false);
  const [downgradeRetentionSaveInProgress, setDowngradeRetentionSaveInProgress] = useState(false);
  const [downgradeRetentionDeleteInProgress, setDowngradeRetentionDeleteInProgress] = useState(false);
  const openedDowngradeRetentionKeyRef = useRef<string | null>(null);

  const currentDowngradeRetention = userProfile?.retention ?? null;
  const downgradeRetentionReactivateLabel = userProfile?.billing?.plans?.pro_monthly?.label
    ? `Reactivate ${userProfile.billing.plans.pro_monthly.label}`
    : 'Reactivate Pro Monthly';

  // This visit key auto-opens the retention dialog once per unique downgrade event.
  const downgradeRetentionVisitKey = useMemo(() => {
    if (!verifiedUser || !currentDowngradeRetention || currentDowngradeRetention.status !== 'grace_period') {
      return null;
    }
    return [
      verifiedUser.uid,
      currentDowngradeRetention.policyVersion,
      currentDowngradeRetention.downgradedAt ?? '',
      currentDowngradeRetention.graceEndsAt ?? '',
    ].join(':');
  }, [currentDowngradeRetention, verifiedUser]);

  const closeDowngradeRetentionDialog = useCallback(() => {
    setShowDowngradeRetentionDialog(false);
  }, []);

  const refreshProfileAfterBillingAction = useCallback(
    async (options?: { attempts?: number; retryDelayMs?: number }) => {
      const attempts = Math.max(1, options?.attempts ?? 3);
      const retryDelayMs = Math.max(0, options?.retryDelayMs ?? 1200);
      for (let attempt = 0; attempt < attempts; attempt += 1) {
        const profile = await loadUserProfile();
        if (profile) return profile;
        if (attempt < attempts - 1 && retryDelayMs > 0) {
          await new Promise((resolve) => setTimeout(resolve, retryDelayMs));
        }
      }
      return null;
    },
    [loadUserProfile],
  );

  const refreshRetentionViews = useCallback(async () => {
    const [profileResult, savedFormsResult, groupsResult] = await Promise.allSettled([
      Promise.resolve().then(() => loadUserProfile()),
      Promise.resolve().then(() => refreshSavedForms({ allowRetry: true, throwOnError: true })),
      Promise.resolve().then(() => refreshGroups({ throwOnError: true })),
    ]);
    return {
      profile: profileResult.status === 'fulfilled' && Boolean(profileResult.value),
      savedForms: savedFormsResult.status === 'fulfilled',
      groups: groupsResult.status === 'fulfilled',
    };
  }, [loadUserProfile, refreshGroups, refreshSavedForms]);

  const handleStartBillingCheckout = useCallback(
    async (kind: BillingCheckoutKind) => {
      if (billingCancelInProgress) return;
      if (!verifiedUser?.uid) {
        setBannerNotice({
          tone: 'error',
          message: 'Sign in again before starting Stripe checkout.',
          autoDismissMs: 8000,
        });
        return;
      }
      if (!userProfile?.billing?.enabled) {
        setBannerNotice({
          tone: 'error',
          message: 'Stripe billing is currently unavailable.',
          autoDismissMs: 8000,
        });
        return;
      }
      setBillingCheckoutInProgressKind(kind);
      try {
        const payload = await createTrustedBillingCheckoutForUser(verifiedUser.uid, kind);
        window.location.assign(payload.checkoutUrl);
      } catch (error) {
        clearPendingBillingCheckout();
        const message = error instanceof Error ? error.message : 'Failed to start checkout.';
        setBannerNotice({ tone: 'error', message, autoDismissMs: 8000 });
      } finally {
        setBillingCheckoutInProgressKind(null);
      }
    },
    [billingCancelInProgress, setBannerNotice, userProfile?.billing?.enabled, verifiedUser?.uid],
  );

  const handleCancelBillingSubscription = useCallback(async () => {
    if (billingCheckoutInProgressKind !== null) return;
    if (!userProfile?.billing?.enabled) {
      setBannerNotice({
        tone: 'error',
        message: 'Stripe billing is currently unavailable.',
        autoDismissMs: 8000,
      });
      return;
    }
    if (!userProfile?.billing?.hasSubscription) {
      setBannerNotice({
        tone: 'info',
        message: 'No active subscription is linked to this profile yet.',
        autoDismissMs: 7000,
      });
      return;
    }
    if (userProfile?.billing?.cancelAtPeriodEnd === true) {
      setBannerNotice({
        tone: 'info',
        message: 'Subscription is already cancelled for period end.',
        autoDismissMs: 7000,
      });
      return;
    }
    setBillingCancelInProgress(true);
    try {
      const payload = await ApiService.cancelBillingSubscription();
      const alreadyCanceled = Boolean(payload?.alreadyCanceled);
      const cancelAtPeriodEnd = Boolean(payload?.cancelAtPeriodEnd);
      const stateSyncDeferred = Boolean(payload?.stateSyncDeferred);
      const refreshedProfile = await refreshProfileAfterBillingAction({
        attempts: 2,
        retryDelayMs: 1200,
      });
      if (alreadyCanceled) {
        setBannerNotice({
          tone: 'info',
          message: 'Subscription is already cancelled for period end.',
          autoDismissMs: 7000,
        });
      } else if (stateSyncDeferred) {
        setBannerNotice({
          tone: 'info',
          message: cancelAtPeriodEnd
            ? 'Stripe cancellation is scheduled, but profile sync is delayed. Refresh in a moment to confirm local role and billing status.'
            : 'Stripe cancellation succeeded, but profile sync is delayed. Refresh in a moment to confirm local role and billing status.',
          autoDismissMs: 9000,
        });
      } else if (!refreshedProfile) {
        setBannerNotice({
          tone: 'error',
          message: 'Stripe accepted the cancellation, but profile refresh failed. Reopen Profile in a moment to confirm subscription status.',
          autoDismissMs: 9000,
        });
      } else {
        setBannerNotice({
          tone: 'success',
          message: cancelAtPeriodEnd
            ? 'Subscription cancellation is scheduled for period end. Pro access remains active until then.'
            : 'Subscription canceled.',
          autoDismissMs: 8000,
        });
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to cancel subscription.';
      setBannerNotice({ tone: 'error', message, autoDismissMs: 8000 });
    } finally {
      setBillingCancelInProgress(false);
    }
  }, [
    billingCheckoutInProgressKind,
    refreshProfileAfterBillingAction,
    setBannerNotice,
    userProfile?.billing?.cancelAtPeriodEnd,
    userProfile?.billing?.enabled,
    userProfile?.billing?.hasSubscription,
  ]);

  const handleSaveDowngradeRetentionSelection = useCallback(async (keptTemplateIds: string[]) => {
    if (downgradeRetentionSaveInProgress || downgradeRetentionDeleteInProgress || billingCheckoutInProgressKind !== null) {
      return;
    }
    setDowngradeRetentionSaveInProgress(true);
    try {
      const retention = await ApiService.updateDowngradeRetention(keptTemplateIds);
      mutateUserProfile((previous) => (previous ? { ...previous, retention } : previous));
      const refreshStatus = await refreshRetentionViews();
      setBannerNotice({
        tone: refreshStatus.profile && refreshStatus.savedForms && refreshStatus.groups ? 'success' : 'info',
        message:
          refreshStatus.profile && refreshStatus.savedForms && refreshStatus.groups
            ? 'Saved forms kept during the downgrade grace period were updated.'
            : 'Saved forms kept during the downgrade grace period were updated, but some views may need a refresh.',
        autoDismissMs: refreshStatus.profile && refreshStatus.savedForms && refreshStatus.groups ? 7000 : 9000,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to update downgrade retention.';
      setBannerNotice({ tone: 'error', message, autoDismissMs: 8000 });
    } finally {
      setDowngradeRetentionSaveInProgress(false);
    }
  }, [
    billingCheckoutInProgressKind,
    downgradeRetentionDeleteInProgress,
    downgradeRetentionSaveInProgress,
    mutateUserProfile,
    refreshRetentionViews,
    setBannerNotice,
  ]);

  const handleDeleteDowngradeRetentionNow = useCallback(async () => {
    if (downgradeRetentionSaveInProgress || downgradeRetentionDeleteInProgress || billingCheckoutInProgressKind !== null) {
      return;
    }
    const confirmed = await requestConfirm({
      title: 'Delete queued saved forms now?',
      message: 'This permanently deletes every queued saved form and its dependent Fill By Link records.',
      confirmLabel: 'Delete queued data',
      cancelLabel: 'Keep grace period',
      tone: 'danger',
    });
    if (!confirmed) {
      return;
    }
    setDowngradeRetentionDeleteInProgress(true);
    try {
      const result = await ApiService.deleteDowngradeRetentionNow();
      const deletedTemplateIds = new Set(result.deletedTemplateIds || []);
      const deletedCurrentSavedForm = Boolean(
        activeSavedFormId && deletedTemplateIds.has(activeSavedFormId),
      );
      const deletedOpenGroupTemplate = activeGroupTemplates.some((template) => deletedTemplateIds.has(template.id));
      mutateUserProfile((previous) => (previous ? { ...previous, retention: null } : previous));
      const refreshStatus = await refreshRetentionViews();
      if (deletedCurrentSavedForm || deletedOpenGroupTemplate) {
        clearWorkspace();
      }
      setShowDowngradeRetentionDialog(false);
      setBannerNotice({
        tone: refreshStatus.profile && refreshStatus.savedForms && refreshStatus.groups ? 'success' : 'info',
        message:
          refreshStatus.profile && refreshStatus.savedForms && refreshStatus.groups
            ? 'Queued saved forms and dependent Fill By Link records were deleted.'
            : 'Queued saved forms and dependent Fill By Link records were deleted, but some views may need a refresh.',
        autoDismissMs: refreshStatus.profile && refreshStatus.savedForms && refreshStatus.groups ? 8000 : 9000,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to delete downgraded saved forms.';
      setBannerNotice({ tone: 'error', message, autoDismissMs: 8000 });
    } finally {
      setDowngradeRetentionDeleteInProgress(false);
    }
  }, [
    activeGroupTemplates,
    activeSavedFormId,
    billingCheckoutInProgressKind,
    clearWorkspace,
    downgradeRetentionDeleteInProgress,
    downgradeRetentionSaveInProgress,
    mutateUserProfile,
    requestConfirm,
    refreshRetentionViews,
    setBannerNotice,
  ]);

  const handleOpenDowngradeRetentionDialog = useCallback(() => {
    if (!userProfile?.retention) return;
    setShowDowngradeRetentionDialog(true);
  }, [userProfile?.retention]);

  const handleReactivateDowngradedAccount = useCallback(() => {
    if (downgradeRetentionSaveInProgress || downgradeRetentionDeleteInProgress || billingCheckoutInProgressKind !== null) {
      return;
    }
    void handleStartBillingCheckout('pro_monthly');
  }, [
    billingCheckoutInProgressKind,
    downgradeRetentionDeleteInProgress,
    downgradeRetentionSaveInProgress,
    handleStartBillingCheckout,
  ]);

  useEffect(() => {
    if (!downgradeRetentionVisitKey) {
      openedDowngradeRetentionKeyRef.current = null;
      setShowDowngradeRetentionDialog(false);
      return;
    }
    if (openedDowngradeRetentionKeyRef.current === downgradeRetentionVisitKey) {
      return;
    }
    openedDowngradeRetentionKeyRef.current = downgradeRetentionVisitKey;
    setShowDowngradeRetentionDialog(true);
  }, [downgradeRetentionVisitKey]);

  useEffect(() => {
    if (!authReady && !assumeAuthReady) return;
    if (typeof window === 'undefined') return;
    const url = new URL(window.location.href);
    const billingState = (url.searchParams.get('billing') || '').toLowerCase();
    if (!billingState) return;
    if (billingState === 'cancel') {
      setBannerNotice({
        tone: 'info',
        message: 'Checkout was canceled.',
        autoDismissMs: 6000,
      });
      url.searchParams.delete('billing');
      window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`);
      return;
    }
    if (billingState !== 'success') {
      url.searchParams.delete('billing');
      window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`);
      return;
    }
    if (!verifiedUser) return;
    const clearedExpiredCheckout = clearExpiredPendingBillingCheckout();
    const pendingCheckout = readPendingBillingCheckoutForUser(verifiedUser.uid);
    if (!pendingCheckout) {
      void (async () => {
        const refreshedProfile = await refreshProfileAfterBillingAction({
          attempts: 2,
          retryDelayMs: 1200,
        });
        setBannerNotice({
          tone: 'info',
          message: clearedExpiredCheckout
            ? 'Billing return detected, but the local checkout marker expired before confirmation. Reopen Profile to verify billing status.'
            : (refreshedProfile
              ? 'Billing return detected. This tab did not have a matching pending checkout, but your profile was refreshed.'
              : 'Billing return detected. This tab did not have a matching pending checkout. Reopen Profile in a moment to verify billing status.'),
          autoDismissMs: 8000,
        });
        url.searchParams.delete('billing');
        window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`);
      })();
      return;
    }
    setBannerNotice({
      tone: 'info',
      message: 'Checkout completed. Syncing your profile credits…',
      autoDismissMs: 8000,
    });
    void (async () => {
      let reconciledCount = 0;
      let reconcileFailed = false;
      let matchedBillingEvent: BillingReconcileEvent | null = null;
      try {
        const reconciliation = await ApiService.reconcileBillingCheckoutFulfillment({
          lookbackHours: 72,
          dryRun: false,
          sessionId: pendingCheckout.sessionId,
          attemptId: pendingCheckout.attemptId ?? null,
        });
        reconciledCount = typeof reconciliation?.reconciledCount === 'number' ? reconciliation.reconciledCount : 0;
        matchedBillingEvent = findMatchingBillingCheckoutEvent(reconciliation?.events ?? [], pendingCheckout);
      } catch (error) {
        reconcileFailed = true;
        debugLog('Billing checkout reconciliation failed', error);
      }
      const refreshedProfile = await refreshProfileAfterBillingAction({
        attempts: 3,
        retryDelayMs: 1200,
      });
      if (matchedBillingEvent) {
        const trackedKind = resolveTrackedBillingKind(matchedBillingEvent, pendingCheckout);
        const trackedPlan = resolveBillingPlanForTracking(
          refreshedProfile ?? userProfile,
          matchedBillingEvent,
          pendingCheckout,
        );
        if (trackedKind) {
          trackGoogleAdsBillingPurchase({
            kind: trackedKind,
            transactionId: matchedBillingEvent.checkoutSessionId ?? pendingCheckout.sessionId,
            value: resolveGoogleAdsPurchaseValue(trackedPlan),
            currency: trackedPlan?.currency ?? null,
          });
        }
      }
      if (matchedBillingEvent) {
        clearPendingBillingCheckout();
      }
      if (matchedBillingEvent && refreshedProfile) {
        const message = reconciledCount > 0
          ? `Checkout completed. Recovered ${reconciledCount} missed billing event${reconciledCount === 1 ? '' : 's'} and refreshed your profile.`
          : 'Checkout completed and your profile has been refreshed.';
        setBannerNotice({
          tone: 'success',
          message,
          autoDismissMs: 8000,
        });
      } else if (matchedBillingEvent) {
        setBannerNotice({
          tone: 'error',
          message: 'Checkout completed, but profile refresh failed. Reopen Profile in a moment to verify credits and subscription status.',
          autoDismissMs: 9000,
        });
      } else if (refreshedProfile) {
        setBannerNotice({
          tone: 'info',
          message: reconcileFailed
            ? 'Billing return detected, but checkout confirmation is still pending because reconciliation is temporarily unavailable. Reopen Profile in a moment to verify status.'
            : 'Billing return detected, but this checkout could not be confirmed yet. Reopen Profile in a moment to verify billing status.',
          autoDismissMs: 9000,
        });
      } else {
        setBannerNotice({
          tone: 'error',
          message: 'Billing return detected, but checkout confirmation is still pending and profile refresh failed. Reopen Profile in a moment to verify billing status.',
          autoDismissMs: 9000,
        });
      }
      url.searchParams.delete('billing');
      window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`);
    })();
  }, [
    assumeAuthReady,
    authReady,
    refreshProfileAfterBillingAction,
    setBannerNotice,
    userProfile,
    verifiedUser,
  ]);

  return {
    billingCheckoutInProgressKind,
    billingCancelInProgress,
    showDowngradeRetentionDialog,
    downgradeRetentionSaveInProgress,
    downgradeRetentionDeleteInProgress,
    currentDowngradeRetention,
    downgradeRetentionReactivateLabel,
    closeDowngradeRetentionDialog,
    handleOpenDowngradeRetentionDialog,
    handleStartBillingCheckout,
    handleCancelBillingSubscription,
    handleSaveDowngradeRetentionSelection,
    handleDeleteDowngradeRetentionNow,
    handleReactivateDowngradedAccount,
  };
}
