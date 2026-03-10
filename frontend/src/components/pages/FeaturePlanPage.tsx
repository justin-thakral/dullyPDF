import { useCallback, useEffect, useMemo, useState } from 'react';
import type { User } from 'firebase/auth';
import { getFeaturePlanPage, type FeaturePlanPageKey } from '../../config/featurePlanPages';
import { applyRouteSeo } from '../../utils/seo';
import { IntentPageShell } from './IntentPageShell';
import './FeaturePlanPage.css';
import { Auth } from '../../services/auth';
import {
  ApiService,
  type BillingCheckoutKind,
  type BillingPlanCatalogItem,
  type UserProfile,
} from '../../services/api';
import { clearPendingBillingCheckout } from '../../utils/billingCheckoutState';
import { createTrustedBillingCheckoutForUser } from '../../utils/billingCheckout';

type FeaturePlanPageProps = {
  pageKey: FeaturePlanPageKey;
};

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

function formatPlanButtonLabel(plan: BillingPlanCatalogItem | undefined, fallback: string): string {
  const baseLabel = (plan?.label || '').trim() || fallback;
  const priceLabel = formatPlanPrice(plan);
  if (!priceLabel) return baseLabel;
  return `${baseLabel} (${priceLabel})`;
}

const FeaturePlanPage = ({ pageKey }: FeaturePlanPageProps) => {
  const page = getFeaturePlanPage(pageKey);
  const [authReady, setAuthReady] = useState(false);
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [billingMessage, setBillingMessage] = useState<string | null>(null);
  const [checkoutInProgressKind, setCheckoutInProgressKind] = useState<BillingCheckoutKind | null>(null);

  useEffect(() => {
    applyRouteSeo({ kind: 'feature-plan', planKey: pageKey });
  }, [pageKey]);

  useEffect(() => {
    let isActive = true;
    let syncVersion = 0;
    const unsubscribe = Auth.onAuthStateChanged((user) => {
      syncVersion += 1;
      const currentSyncVersion = syncVersion;
      if (!isActive) return;
      setCurrentUser(user);
      setProfile(null);
      setProfileError(null);
      setBillingMessage(null);
      if (!user) {
        setProfileLoading(false);
        setAuthReady(true);
        return;
      }
      setProfileLoading(true);
      setAuthReady(true);
      void (async () => {
        try {
          const nextProfile = await ApiService.getProfile();
          if (!isActive || currentSyncVersion !== syncVersion) return;
          setProfile(nextProfile);
          if (!nextProfile) {
            setProfileError('Signed-in billing details are not available yet. Open the workspace profile to confirm account access.');
          }
        } catch (error) {
          if (!isActive || currentSyncVersion !== syncVersion) return;
          setProfileError(error instanceof Error ? error.message : 'Failed to load billing details.');
        } finally {
          if (isActive && currentSyncVersion === syncVersion) {
            setProfileLoading(false);
          }
        }
      })();
    });

    return () => {
      isActive = false;
      unsubscribe();
    };
  }, []);

  const normalizedRole = profile?.role === 'god'
    ? 'God'
    : profile?.role === 'pro'
      ? 'Premium'
      : 'Free';
  const billingEnabled = profile?.billing?.enabled === true;
  const hasPremiumAccess = profile?.role === 'pro' || profile?.role === 'god';
  const hasSubscription = profile?.billing?.hasSubscription === true;
  const monthlyPlan = profile?.billing?.plans?.pro_monthly;
  const yearlyPlan = profile?.billing?.plans?.pro_yearly;
  const monthlyLabel = formatPlanButtonLabel(monthlyPlan, 'Pro Monthly');
  const yearlyLabel = formatPlanButtonLabel(yearlyPlan, 'Pro Yearly');

  const handleStartCheckout = useCallback(async (kind: BillingCheckoutKind) => {
    if (!currentUser?.uid) {
      setBillingMessage('Sign in from the homepage before starting Stripe checkout.');
      return;
    }
    if (!billingEnabled) {
      setBillingMessage('Stripe billing is currently unavailable.');
      return;
    }
    setBillingMessage(null);
    setCheckoutInProgressKind(kind);
    try {
      const payload = await createTrustedBillingCheckoutForUser(currentUser.uid, kind);
      window.location.assign(payload.checkoutUrl);
    } catch (error) {
      clearPendingBillingCheckout();
      setBillingMessage(error instanceof Error ? error.message : 'Failed to start checkout.');
    } finally {
      setCheckoutInProgressKind(null);
    }
  }, [billingEnabled, currentUser?.uid]);

  const purchasePanel = useMemo(() => {
    if (pageKey !== 'premium-features') return null;

    return (
      <section className="intent-page__panel feature-plan__billing-panel">
        <h2>Buy premium</h2>
        <p>
          Secure purchases run through Stripe Checkout. The live buy buttons are available only after this page
          confirms your signed-in account and billing availability.
        </p>

        <div className="feature-plan__status-row">
          <span className="feature-plan__status-pill">
            {authReady ? (currentUser ? `Signed in as ${currentUser.email || 'current account'}` : 'Signed out') : 'Checking sign-in status…'}
          </span>
          <span className="feature-plan__status-pill">
            Current tier: {profile ? normalizedRole : 'Unknown'}
          </span>
        </div>

        {!authReady || profileLoading ? (
          <p className="feature-plan__billing-note">Loading billing details…</p>
        ) : null}

        {!currentUser ? (
          <>
            <p className="feature-plan__billing-note">
              Sign in from the homepage to start a premium checkout session.
            </p>
            <div className="intent-page__cta-row">
              <a href="/" className="intent-page__cta intent-page__cta--primary">
                Sign In to Buy
              </a>
            </div>
          </>
        ) : null}

        {currentUser && profileError ? (
          <p className="feature-plan__billing-note feature-plan__billing-note--error">{profileError}</p>
        ) : null}

        {currentUser && profile && hasPremiumAccess ? (
          <p className="feature-plan__billing-note">
            This account already has premium access. Use Profile in the workspace to manage cancellation or refills.
          </p>
        ) : null}

        {currentUser && profile && !hasPremiumAccess && !billingEnabled ? (
          <p className="feature-plan__billing-note">
            Stripe billing is currently unavailable for this account, so premium checkout is temporarily disabled.
          </p>
        ) : null}

        {currentUser && profile && !hasPremiumAccess && billingEnabled ? (
          <>
            <div className="feature-plan__billing-actions">
              <button
                type="button"
                className="feature-plan__billing-button"
                onClick={() => void handleStartCheckout('pro_monthly')}
                disabled={checkoutInProgressKind !== null || !monthlyPlan}
              >
                {checkoutInProgressKind === 'pro_monthly' ? 'Starting checkout…' : `Buy ${monthlyLabel}`}
              </button>
              <button
                type="button"
                className="feature-plan__billing-button feature-plan__billing-button--secondary"
                onClick={() => void handleStartCheckout('pro_yearly')}
                disabled={checkoutInProgressKind !== null || !yearlyPlan}
              >
                {checkoutInProgressKind === 'pro_yearly' ? 'Starting checkout…' : `Buy ${yearlyLabel}`}
              </button>
            </div>
            {hasSubscription ? (
              <p className="feature-plan__billing-note">
                A subscription is already linked to this account. Reopen the workspace profile if billing status looks out of date.
              </p>
            ) : null}
            {!monthlyPlan || !yearlyPlan ? (
              <p className="feature-plan__billing-note">
                Some premium plans are currently unavailable due to configuration.
              </p>
            ) : null}
          </>
        ) : null}

        {billingMessage ? (
          <p className="feature-plan__billing-note feature-plan__billing-note--error">{billingMessage}</p>
        ) : null}
      </section>
    );
  }, [
    authReady,
    billingEnabled,
    billingMessage,
    checkoutInProgressKind,
    currentUser,
    handleStartCheckout,
    hasPremiumAccess,
    hasSubscription,
    monthlyLabel,
    monthlyPlan,
    normalizedRole,
    pageKey,
    profile,
    profileError,
    profileLoading,
    yearlyLabel,
    yearlyPlan,
  ]);

  return (
    <IntentPageShell
      breadcrumbItems={[
        { label: 'Home', href: '/' },
        { label: 'Plans' },
        { label: page.navLabel },
      ]}
      heroKicker="Plan details"
      heroTitle={page.heroTitle}
      heroSummary={page.heroSummary}
    >
      <section className="intent-page__grid">
        <article className="intent-page__panel">
          <h2>What this plan covers</h2>
          <ul>
            {page.valuePoints.map((point) => (
              <li key={point}>{point}</li>
            ))}
          </ul>
        </article>
        <article className="intent-page__panel">
          <h2>Where this fits in the product</h2>
          <p>
            These public plan pages explain the free and premium workflow surfaces without forcing long billing copy
            into the homepage CTA card. Use them when you need a direct explanation of what changes across tiers.
          </p>
          <div className="intent-page__related-links">
            {page.relatedLinks.map((link) => (
              <a key={link.href} href={link.href} className="intent-page__related-link">
                {link.label}
              </a>
            ))}
          </div>
        </article>
      </section>

      {purchasePanel}

      <section className="feature-plan__details">
        {page.detailSections.map((section) => (
          <article key={section.title} className="intent-page__panel">
            <h2>{section.title}</h2>
            <ul>
              {section.items.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </article>
        ))}
      </section>

      <section className="intent-page__panel">
        <h2>Frequently asked questions</h2>
        <div className="intent-page__faq-list">
          {page.faqs.map((faq) => (
            <article key={faq.question} className="intent-page__faq-item">
              <h3>{faq.question}</h3>
              <p>{faq.answer}</p>
            </article>
          ))}
        </div>
      </section>
    </IntentPageShell>
  );
};

export default FeaturePlanPage;
