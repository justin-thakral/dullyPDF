import { ApiService, type BillingCheckoutKind } from '../services/api';
import { persistPendingBillingCheckout } from './billingCheckoutState';

const TRUSTED_BILLING_CHECKOUT_HOSTS = new Set([
  'checkout.stripe.com',
  'billing.stripe.com',
  'buy.stripe.com',
]);

export function resolveTrustedBillingCheckoutUrl(rawUrl: unknown): string {
  const normalizedUrl = typeof rawUrl === 'string' ? rawUrl.trim() : '';
  if (!normalizedUrl) {
    throw new Error('Stripe checkout URL is missing.');
  }
  let parsedUrl: URL;
  try {
    parsedUrl = new URL(normalizedUrl);
  } catch {
    throw new Error('Stripe checkout URL is invalid.');
  }
  if (parsedUrl.protocol !== 'https:') {
    throw new Error('Stripe checkout URL must use HTTPS.');
  }
  if (!TRUSTED_BILLING_CHECKOUT_HOSTS.has(parsedUrl.hostname.toLowerCase())) {
    throw new Error('Stripe checkout URL is not trusted.');
  }
  return parsedUrl.toString();
}

export async function createTrustedBillingCheckoutForUser(
  userId: string,
  kind: BillingCheckoutKind,
): Promise<{
    success: boolean;
    kind: BillingCheckoutKind;
    sessionId: string;
    checkoutUrl: string;
    attemptId?: string | null;
    checkoutPriceId?: string | null;
  }> {
  const normalizedUserId = userId.trim();
  if (!normalizedUserId) {
    throw new Error('Sign in again before starting Stripe checkout.');
  }
  const payload = await ApiService.createBillingCheckoutSession(kind);
  const checkoutUrl = resolveTrustedBillingCheckoutUrl(payload?.checkoutUrl);
  persistPendingBillingCheckout({
    userId: normalizedUserId,
    requestedKind: kind,
    sessionId: payload.sessionId,
    attemptId: payload.attemptId ?? null,
    checkoutPriceId: payload.checkoutPriceId ?? null,
    startedAt: Date.now(),
  });
  return {
    ...payload,
    checkoutUrl,
  };
}
