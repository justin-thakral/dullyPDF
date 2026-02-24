/**
 * User profile overview with tier limits and saved forms.
 */
import React, { useMemo, useState } from 'react';
import './ProfilePage.css';
import type {
  BillingCheckoutKind,
  BillingPlanCatalogItem,
  CreditPricingConfig,
  ProfileLimits,
  SavedFormSummary,
} from '../../services/api';

interface ProfilePageProps {
  email?: string | null;
  role?: string | null;
  creditsRemaining?: number | null;
  monthlyCreditsRemaining?: number | null;
  refillCreditsRemaining?: number | null;
  availableCredits?: number | null;
  refillCreditsLocked?: boolean;
  isLoading?: boolean;
  limits: ProfileLimits;
  savedForms: SavedFormSummary[];
  savedFormsLoading?: boolean;
  onSelectSavedForm: (formId: string) => void;
  onDeleteSavedForm?: (formId: string) => void;
  deletingFormId?: string | null;
  billingCheckoutInProgressKind?: BillingCheckoutKind | null;
  billingCancelInProgress?: boolean;
  billingEnabled?: boolean | null;
  billingHasSubscription?: boolean | null;
  billingSubscriptionStatus?: string | null;
  billingCancelAtPeriodEnd?: boolean | null;
  billingCancelAt?: number | null;
  billingCurrentPeriodEnd?: number | null;
  billingPlans?: Partial<Record<BillingCheckoutKind, BillingPlanCatalogItem>>;
  profileError?: string | null;
  creditPricing?: CreditPricingConfig | null;
  onStartBillingCheckout?: (kind: BillingCheckoutKind) => void;
  onCancelBillingSubscription?: () => void;
  onClose: () => void;
  onSignOut?: () => void;
}

function formatPlanPrice(plan?: BillingPlanCatalogItem): string | null {
  if (!plan) return null;
  const currency = (plan.currency || '').trim();
  const unitAmount = typeof plan.unitAmount === 'number' ? plan.unitAmount : null;
  if (!currency || unitAmount === null || Number.isNaN(unitAmount)) return null;
  try {
    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency: currency.toUpperCase(),
    }).format(unitAmount / 100);
  } catch {
    return null;
  }
}

function formatPlanLabel(plan: BillingPlanCatalogItem | undefined, fallback: string): string {
  const baseLabel = (plan?.label || '').trim() || fallback;
  const priceLabel = formatPlanPrice(plan);
  if (!priceLabel) return baseLabel;
  return `${baseLabel} (${priceLabel})`;
}

/**
 * Render a dedicated profile screen with tier details and saved forms.
 */
const ProfilePage: React.FC<ProfilePageProps> = ({
  email,
  role,
  creditsRemaining,
  monthlyCreditsRemaining,
  refillCreditsRemaining,
  availableCredits,
  refillCreditsLocked = false,
  isLoading = false,
  limits,
  savedForms,
  savedFormsLoading = false,
  onSelectSavedForm,
  onDeleteSavedForm,
  deletingFormId,
  billingCheckoutInProgressKind = null,
  billingCancelInProgress = false,
  billingEnabled = null,
  billingHasSubscription = null,
  billingSubscriptionStatus = null,
  billingCancelAtPeriodEnd = null,
  billingCancelAt = null,
  billingCurrentPeriodEnd = null,
  billingPlans,
  profileError = null,
  creditPricing,
  onStartBillingCheckout,
  onCancelBillingSubscription,
  onClose,
  onSignOut,
}) => {
  const [query, setQuery] = useState('');
  const normalizedRole = role === 'god' ? 'God' : role === 'pro' ? 'Pro' : 'Basic';
  const initial = (email || 'U').charAt(0).toUpperCase();
  const isGod = role === 'god';
  const isPro = role === 'pro';
  const hasBillingSubscription = billingHasSubscription === true;
  const cancelScheduled = billingCancelAtPeriodEnd === true;
  const billingStatus = (billingSubscriptionStatus || '').trim().toLowerCase() || null;
  const cancelEffectiveAt =
    typeof billingCancelAt === 'number'
      ? billingCancelAt
      : (typeof billingCurrentPeriodEnd === 'number' ? billingCurrentPeriodEnd : null);
  const billingBusy = billingCheckoutInProgressKind !== null || billingCancelInProgress;
  const cancelButtonLabel = billingCancelInProgress
    ? 'Canceling…'
    : (cancelScheduled ? 'Cancelled' : (isPro ? 'Cancel Pro Subscription' : 'Cancel Subscription'));
  const resolvedAvailableCredits =
    typeof availableCredits === 'number' ? availableCredits : (creditsRemaining ?? 0);
  const creditsLabel = isGod ? 'Unlimited' : String(resolvedAvailableCredits);
  const monthlyLabel = isGod ? 'Unlimited' : String(monthlyCreditsRemaining ?? 0);
  const refillLabel = isGod ? 'Unlimited' : String(refillCreditsRemaining ?? 0);
  const pricing = creditPricing ?? {
    pageBucketSize: 5,
    renameBaseCost: 1,
    remapBaseCost: 1,
    renameRemapBaseCost: 2,
  };
  const monthlyPlan = billingPlans?.pro_monthly;
  const yearlyPlan = billingPlans?.pro_yearly;
  const refillPlan = billingPlans?.refill_500;
  const monthlyPlanAvailable = Boolean(monthlyPlan);
  const yearlyPlanAvailable = Boolean(yearlyPlan);
  const refillPlanAvailable = Boolean(refillPlan);
  const monthlyPlanLabel = formatPlanLabel(monthlyPlan, 'Pro Monthly');
  const yearlyPlanLabel = formatPlanLabel(yearlyPlan, 'Pro Yearly');
  const refillPlanLabel = formatPlanLabel(refillPlan, 'Refill 500 Credits');
  const cancelEffectiveDateLabel = useMemo(() => {
    if (!cancelEffectiveAt) return null;
    try {
      return new Date(cancelEffectiveAt * 1000).toLocaleDateString(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
      });
    } catch {
      return null;
    }
  }, [cancelEffectiveAt]);

  const filteredForms = useMemo(() => {
    const trimmed = query.trim().toLowerCase();
    if (!trimmed) return savedForms;
    return savedForms.filter((form) => form.name.toLowerCase().includes(trimmed));
  }, [query, savedForms]);

  return (
    <div className="profile-page">
      <div className="profile-shell">
        <header className="profile-header">
          <button type="button" className="profile-back" onClick={onClose}>
            ← Back to workspace
          </button>
          <div className="profile-identity">
            <div className="profile-avatar" aria-hidden="true">
              {initial}
            </div>
            <div>
              <p className="profile-email">{email || 'User profile'}</p>
              <div className="profile-tier">
                <span>{normalizedRole} tier</span>
              </div>
            </div>
          </div>
          {onSignOut ? (
            <button type="button" className="profile-signout" onClick={onSignOut}>
              Sign out
            </button>
          ) : null}
        </header>

        {isLoading ? (
          <div className="profile-loading" role="status" aria-live="polite">
            Loading profile details…
          </div>
        ) : null}
        {profileError ? (
          <div className="profile-loading" role="status" aria-live="polite">
            Profile refresh failed: {profileError}
          </div>
        ) : null}

        <section className="profile-metrics">
          <div className="metric-card">
            <span className="metric-label">OpenAI credits left</span>
            <span className="metric-value">{creditsLabel}</span>
            <p className="metric-note">
              Credits are consumed per OpenAI action bucket: Rename ({pricing.renameBaseCost}),
              Remap ({pricing.remapBaseCost}), Rename + Remap ({pricing.renameRemapBaseCost})
              per {pricing.pageBucketSize} pages.
            </p>
          </div>
          <div className="metric-card">
            <span className="metric-label">Monthly credits</span>
            <span className="metric-value">{monthlyLabel}</span>
            <p className="metric-note">
              Pro plan monthly pool resets to 500 each month.
            </p>
          </div>
          <div className="metric-card">
            <span className="metric-label">Refill credits</span>
            <span className="metric-value">{refillLabel}</span>
            <p className="metric-note">
              Refill credits do not expire.
            </p>
          </div>
          <div className="metric-card">
            <span className="metric-label">Max pages per scan</span>
            <span className="metric-value">{limits.detectMaxPages}</span>
            <p className="metric-note">Detection uploads over this size are blocked.</p>
          </div>
          <div className="metric-card">
            <span className="metric-label">Max fillable pages</span>
            <span className="metric-value">{limits.fillableMaxPages}</span>
            <p className="metric-note">Applies to local fillable template uploads.</p>
          </div>
          <div className="metric-card">
            <span className="metric-label">Saved forms limit</span>
            <span className="metric-value">{limits.savedFormsMax}</span>
            <p className="metric-note">Delete older forms to make room.</p>
          </div>
        </section>

        {!isGod && billingEnabled === true ? (
          <section className="profile-billing">
            <div className="profile-billing__header">
              <h2>Billing</h2>
              <p>Manage Pro access and OpenAI credit refills.</p>
            </div>
            <div className="profile-billing__actions">
              <button
                type="button"
                className="profile-billing__button"
                onClick={() => onStartBillingCheckout?.('pro_monthly')}
                disabled={!onStartBillingCheckout || billingBusy || isPro || !monthlyPlanAvailable}
              >
                {!monthlyPlanAvailable
                  ? 'Pro Monthly unavailable'
                  : (billingCheckoutInProgressKind === 'pro_monthly'
                    ? 'Starting checkout…'
                    : (isPro
                      ? `${monthlyPlanLabel} (cancel current first)`
                      : `Upgrade to ${monthlyPlanLabel}`))}
              </button>
              <button
                type="button"
                className="profile-billing__button profile-billing__button--secondary"
                onClick={() => onStartBillingCheckout?.('pro_yearly')}
                disabled={!onStartBillingCheckout || billingBusy || isPro || !yearlyPlanAvailable}
              >
                {!yearlyPlanAvailable
                  ? 'Pro Yearly unavailable'
                  : (billingCheckoutInProgressKind === 'pro_yearly'
                    ? 'Starting checkout…'
                    : (isPro
                      ? `${yearlyPlanLabel} (cancel current first)`
                      : `Upgrade to ${yearlyPlanLabel}`))}
              </button>
              <button
                type="button"
                className="profile-billing__button"
                onClick={() => onStartBillingCheckout?.('refill_500')}
                disabled={!onStartBillingCheckout || !isPro || billingBusy || !refillPlanAvailable}
              >
                {!refillPlanAvailable
                  ? 'Refill unavailable'
                  : (billingCheckoutInProgressKind === 'refill_500' ? 'Starting checkout…' : refillPlanLabel)}
              </button>
              <button
                type="button"
                className="profile-billing__button profile-billing__button--danger"
                onClick={() => onCancelBillingSubscription?.()}
                disabled={!onCancelBillingSubscription || billingBusy || !hasBillingSubscription}
              >
                {cancelButtonLabel}
              </button>
            </div>
            {!isPro ? (
              <p className="profile-billing__note">
                Credit refills are available only with an active Pro subscription.
              </p>
            ) : null}
            {hasBillingSubscription && cancelScheduled ? (
              <p className="profile-billing__note">
                Cancellation is scheduled for period end{cancelEffectiveDateLabel ? ` (${cancelEffectiveDateLabel})` : ''}.
              </p>
            ) : null}
            {isPro && hasBillingSubscription && !cancelScheduled ? (
              <p className="profile-billing__note">
                Active Pro subscription detected. Cancel your current subscription before starting a new Pro checkout.
              </p>
            ) : null}
            {!hasBillingSubscription ? (
              <p className="profile-billing__note">
                Cancellation becomes available after subscription linkage is synchronized.
              </p>
            ) : null}
            {hasBillingSubscription && !isPro ? (
              <p className="profile-billing__note">
                A subscription is linked to this profile. You can still cancel it while role sync catches up.
              </p>
            ) : null}
            {hasBillingSubscription && billingStatus ? (
              <p className="profile-billing__note">
                Subscription status: {billingStatus}.
              </p>
            ) : null}
            {!monthlyPlanAvailable || !yearlyPlanAvailable || !refillPlanAvailable ? (
              <p className="profile-billing__note">
                Some billing plans are currently unavailable due to configuration.
              </p>
            ) : null}
            {refillCreditsLocked ? (
              <p className="profile-billing__note">
                You have refill credits stored. Upgrade back to Pro to use them.
              </p>
            ) : null}
          </section>
        ) : null}

        {!isGod && billingEnabled === false && !isLoading ? (
          <section className="profile-billing">
            <div className="profile-billing__header">
              <h2>Billing</h2>
              <p>Stripe billing is currently unavailable.</p>
            </div>
          </section>
        ) : null}

        {!isGod && billingEnabled === null && !isLoading ? (
          <section className="profile-billing">
            <div className="profile-billing__header">
              <h2>Billing</h2>
              <p>
                {profileError
                  ? 'Billing status is temporarily unavailable because profile data could not be refreshed.'
                  : 'Billing status is currently loading.'}
              </p>
            </div>
          </section>
        ) : null}

        <section className="profile-saved">
          <div className="profile-saved-header">
            <div>
              <h2>Saved Forms (max {limits.savedFormsMax})</h2>
              <p>{savedFormsLoading && savedForms.length === 0 ? 'Loading saved forms…' : `${savedForms.length} total saved`}</p>
            </div>
            <div className="profile-search">
              <input
                type="search"
                id="saved-form-search"
                name="saved-form-search"
                placeholder="Search saved forms"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                aria-label="Search saved forms"
              />
            </div>
          </div>
          {savedFormsLoading && savedForms.length === 0 ? (
            <div className="profile-empty" role="status" aria-live="polite">
              <p>Loading saved forms while the backend starts…</p>
            </div>
          ) : filteredForms.length === 0 ? (
            <div className="profile-empty">
              <p>No saved forms match your search.</p>
            </div>
          ) : (
            <div className="profile-saved-list" role="list">
              {filteredForms.map((form) => {
                const isDeleting = deletingFormId === form.id;
                return (
                  <div key={form.id} className="saved-form-pill" role="listitem">
                    <button
                      type="button"
                      className="saved-form-pill__name"
                      onClick={() => onSelectSavedForm(form.id)}
                      title={form.name}
                      disabled={isDeleting}
                    >
                      {form.name}
                    </button>
                    {onDeleteSavedForm ? (
                      <button
                        type="button"
                        className="saved-form-pill__delete"
                        onClick={() => onDeleteSavedForm(form.id)}
                        aria-label={`Delete saved form ${form.name}`}
                        disabled={isDeleting}
                      >
                        X
                      </button>
                    ) : null}
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </div>
    </div>
  );
};

export default ProfilePage;
