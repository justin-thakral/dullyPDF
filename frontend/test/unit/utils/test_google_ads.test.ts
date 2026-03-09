import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

describe('googleAds', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllEnvs();
    window.sessionStorage.clear();
    delete window.gtag;
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    window.sessionStorage.clear();
    delete window.gtag;
  });

  it('builds signup send_to from the shared Google Ads tag id and dedupes repeats', async () => {
    vi.stubEnv('VITE_GOOGLE_ADS_TAG_ID', 'AW-17999798747');
    vi.stubEnv('VITE_GOOGLE_ADS_SIGNUP_LABEL', 'NNOICN-IlYUcENvD_IZD');
    const gtag = vi.fn();
    window.gtag = gtag;

    const { trackGoogleAdsSignup } = await import('../../../src/utils/googleAds');

    expect(trackGoogleAdsSignup('user-signup-123')).toBe(true);
    expect(trackGoogleAdsSignup('user-signup-123')).toBe(false);
    expect(gtag).toHaveBeenCalledTimes(1);
    expect(gtag).toHaveBeenCalledWith('event', 'conversion', {
      send_to: 'AW-17999798747/NNOICN-IlYUcENvD_IZD',
      transaction_id: 'user-signup-123',
    });
  });

  it('tracks refill purchases with value and normalized currency', async () => {
    vi.stubEnv('VITE_GOOGLE_ADS_TAG_ID', 'AW-17999798747');
    vi.stubEnv('VITE_GOOGLE_ADS_REFILL_PURCHASE_LABEL', 'XoL_COWIlYUcENvD_IZD');
    const gtag = vi.fn();
    window.gtag = gtag;

    const { trackGoogleAdsBillingPurchase } = await import('../../../src/utils/googleAds');

    expect(trackGoogleAdsBillingPurchase({
      kind: 'refill_500',
      transactionId: 'cs_refill_123',
      value: 25,
      currency: 'usd',
    })).toBe(true);
    expect(gtag).toHaveBeenCalledWith('event', 'conversion', {
      send_to: 'AW-17999798747/XoL_COWIlYUcENvD_IZD',
      transaction_id: 'cs_refill_123',
      value: 25,
      currency: 'USD',
    });
  });
});
