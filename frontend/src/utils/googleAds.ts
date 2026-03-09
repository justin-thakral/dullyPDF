import type { BillingCheckoutKind } from '../services/api';

declare global {
  interface Window {
    dataLayer?: unknown[];
    gtag?: (...args: unknown[]) => void;
  }
}

const TRACKED_CONVERSION_PREFIX = 'dullypdf.googleAdsConversion:';
const trackedConversionsFallback = new Set<string>();

function readEnvValue(key: string): string {
  const rawValue = import.meta.env[key];
  return typeof rawValue === 'string' ? rawValue.trim() : '';
}

const googleAdsTagId = readEnvValue('VITE_GOOGLE_ADS_TAG_ID');

function resolveSendTo(rawLabelOrSendTo: string): string | null {
  if (!rawLabelOrSendTo) return null;
  if (rawLabelOrSendTo.includes('/')) return rawLabelOrSendTo;
  if (!googleAdsTagId) return null;
  return `${googleAdsTagId}/${rawLabelOrSendTo}`;
}

const signupSendTo = resolveSendTo(readEnvValue('VITE_GOOGLE_ADS_SIGNUP_LABEL'));
const proSubscriptionSendTo = resolveSendTo(readEnvValue('VITE_GOOGLE_ADS_PRO_PURCHASE_LABEL'));
const refillPurchaseSendTo = resolveSendTo(readEnvValue('VITE_GOOGLE_ADS_REFILL_PURCHASE_LABEL'));

function getSessionStorage(): Storage | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

function reserveConversionKey(key: string): boolean {
  const storage = getSessionStorage();
  if (storage) {
    if (storage.getItem(key) === '1') return false;
    storage.setItem(key, '1');
    return true;
  }
  if (trackedConversionsFallback.has(key)) return false;
  trackedConversionsFallback.add(key);
  return true;
}

function releaseConversionKey(key: string): void {
  const storage = getSessionStorage();
  if (storage) {
    storage.removeItem(key);
    return;
  }
  trackedConversionsFallback.delete(key);
}

function emitGoogleAdsConversion(options: {
  sendTo: string | null;
  transactionId: string | null | undefined;
  value?: number | null;
  currency?: string | null;
}): boolean {
  const transactionId = (options.transactionId || '').trim();
  if (!options.sendTo || !transactionId || typeof window === 'undefined' || typeof window.gtag !== 'function') {
    return false;
  }

  const dedupeKey = `${TRACKED_CONVERSION_PREFIX}${options.sendTo}:${transactionId}`;
  if (!reserveConversionKey(dedupeKey)) {
    return false;
  }

  try {
    const payload: Record<string, unknown> = {
      send_to: options.sendTo,
      transaction_id: transactionId,
    };
    if (typeof options.value === 'number' && Number.isFinite(options.value)) {
      payload.value = options.value;
    }
    const normalizedCurrency = (options.currency || '').trim().toUpperCase();
    if (normalizedCurrency) {
      payload.currency = normalizedCurrency;
    }
    window.gtag('event', 'conversion', payload);
    return true;
  } catch {
    releaseConversionKey(dedupeKey);
    return false;
  }
}

export function trackGoogleAdsSignup(transactionId: string | null | undefined): boolean {
  return emitGoogleAdsConversion({
    sendTo: signupSendTo,
    transactionId,
  });
}

export function trackGoogleAdsBillingPurchase(options: {
  kind: BillingCheckoutKind;
  transactionId: string | null | undefined;
  value?: number | null;
  currency?: string | null;
}): boolean {
  const sendTo = options.kind === 'refill_500' ? refillPurchaseSendTo : proSubscriptionSendTo;
  return emitGoogleAdsConversion({
    sendTo,
    transactionId: options.transactionId,
    value: options.value,
    currency: options.currency,
  });
}
