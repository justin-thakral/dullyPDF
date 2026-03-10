import type { BillingCheckoutKind } from '../services/api';

export const PENDING_BILLING_CHECKOUT_STORAGE_KEY = 'dullypdf.pendingBillingCheckout';
export const PENDING_BILLING_CHECKOUT_MAX_AGE_MS = 6 * 60 * 60 * 1000;

export type PendingBillingCheckout = {
  userId: string;
  requestedKind: BillingCheckoutKind;
  sessionId: string;
  attemptId?: string | null;
  checkoutPriceId?: string | null;
  startedAt: number;
};

function getSessionStorage(): Storage | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function persistPendingBillingCheckout(payload: PendingBillingCheckout): void {
  const storage = getSessionStorage();
  if (!storage) return;
  storage.setItem(PENDING_BILLING_CHECKOUT_STORAGE_KEY, JSON.stringify(payload));
}

export function clearPendingBillingCheckout(): void {
  const storage = getSessionStorage();
  if (!storage) return;
  storage.removeItem(PENDING_BILLING_CHECKOUT_STORAGE_KEY);
}

export function peekPendingBillingCheckout(): PendingBillingCheckout | null {
  const storage = getSessionStorage();
  if (!storage) return null;
  const raw = storage.getItem(PENDING_BILLING_CHECKOUT_STORAGE_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<PendingBillingCheckout> | null;
    const userId = typeof parsed?.userId === 'string' ? parsed.userId.trim() : '';
    const sessionId = typeof parsed?.sessionId === 'string' ? parsed.sessionId.trim() : '';
    const requestedKind = typeof parsed?.requestedKind === 'string' ? parsed.requestedKind.trim() : '';
    const startedAt = typeof parsed?.startedAt === 'number' && Number.isFinite(parsed.startedAt)
      ? parsed.startedAt
      : NaN;
    if (!userId || !sessionId || !requestedKind || !Number.isFinite(startedAt) || startedAt <= 0) return null;
    if (!['pro_monthly', 'pro_yearly', 'refill_500'].includes(requestedKind)) return null;
    return {
      userId,
      requestedKind: requestedKind as BillingCheckoutKind,
      sessionId,
      attemptId: typeof parsed?.attemptId === 'string' ? parsed.attemptId.trim() || null : null,
      checkoutPriceId: typeof parsed?.checkoutPriceId === 'string' ? parsed.checkoutPriceId.trim() || null : null,
      startedAt,
    };
  } catch {
    return null;
  }
}

export function isPendingBillingCheckoutExpired(
  pendingCheckout: PendingBillingCheckout,
  maxAgeMs = PENDING_BILLING_CHECKOUT_MAX_AGE_MS,
): boolean {
  if (!Number.isFinite(pendingCheckout.startedAt)) return true;
  return (Date.now() - pendingCheckout.startedAt) > Math.max(1, maxAgeMs);
}

export function clearExpiredPendingBillingCheckout(
  maxAgeMs = PENDING_BILLING_CHECKOUT_MAX_AGE_MS,
): boolean {
  const pendingCheckout = peekPendingBillingCheckout();
  if (!pendingCheckout || !isPendingBillingCheckoutExpired(pendingCheckout, maxAgeMs)) {
    return false;
  }
  clearPendingBillingCheckout();
  return true;
}

export function hasFreshPendingBillingCheckout(): boolean {
  const pendingCheckout = peekPendingBillingCheckout();
  return Boolean(pendingCheckout && !isPendingBillingCheckoutExpired(pendingCheckout));
}

export function readPendingBillingCheckoutForUser(
  currentUserId?: string | null,
  maxAgeMs = PENDING_BILLING_CHECKOUT_MAX_AGE_MS,
): PendingBillingCheckout | null {
  const pendingCheckout = peekPendingBillingCheckout();
  if (!pendingCheckout || isPendingBillingCheckoutExpired(pendingCheckout, maxAgeMs)) {
    return null;
  }
  const normalizedCurrentUserId = (currentUserId || '').trim();
  if (!normalizedCurrentUserId || pendingCheckout.userId !== normalizedCurrentUserId) {
    return null;
  }
  return pendingCheckout;
}
