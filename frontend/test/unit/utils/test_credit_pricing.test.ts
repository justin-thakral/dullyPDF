import { describe, expect, it } from 'vitest';

import {
  estimateCreditsForPageCount,
  estimateCreditsForPageCounts,
  resolveClientCreditPricing,
  resolveOpenAiCreditOperation,
  summarizeDetectPageCounts,
} from '../../../src/utils/creditPricing';

describe('creditPricing utilities', () => {
  it('falls back to default pricing when config values are missing or invalid', () => {
    expect(resolveClientCreditPricing(null)).toEqual({
      pageBucketSize: 5,
      renameBaseCost: 1,
      remapBaseCost: 1,
      renameRemapBaseCost: 2,
    });

    expect(
      resolveClientCreditPricing({
        pageBucketSize: 0 as any,
        renameBaseCost: -1 as any,
        remapBaseCost: 'bad' as any,
        renameRemapBaseCost: 3,
      }),
    ).toEqual({
      pageBucketSize: 5,
      renameBaseCost: 1,
      remapBaseCost: 1,
      renameRemapBaseCost: 3,
    });
  });

  it('computes bucketed pricing for a single document', () => {
    expect(estimateCreditsForPageCount('rename', 12)).toMatchObject({
      pageCount: 12,
      bucketSize: 5,
      bucketCount: 3,
      baseCost: 1,
      totalCredits: 3,
    });

    expect(estimateCreditsForPageCount('rename_remap', 12)).toMatchObject({
      bucketCount: 3,
      baseCost: 2,
      totalCredits: 6,
    });
  });

  it('sums multi-document estimates per PDF instead of collapsing them into one page total', () => {
    const estimate = estimateCreditsForPageCounts('rename', [1, 1, 1]);

    expect(estimate.totalPages).toBe(3);
    expect(estimate.documentCount).toBe(3);
    expect(estimate.totalCredits).toBe(3);
    expect(estimate.documents.map((entry) => entry.totalCredits)).toEqual([1, 1, 1]);
  });

  it('summarizes detect page counts and flags documents over the plan limit', () => {
    expect(summarizeDetectPageCounts([3, 8, 5], 5)).toEqual({
      maxPages: 5,
      totalPages: 16,
      largestPageCount: 8,
      withinLimit: false,
      offendingPageCounts: [8],
    });
  });

  it('resolves the active credit operation from rename/map toggles', () => {
    expect(resolveOpenAiCreditOperation(false, false)).toBeNull();
    expect(resolveOpenAiCreditOperation(true, false)).toBe('rename');
    expect(resolveOpenAiCreditOperation(false, true)).toBe('remap');
    expect(resolveOpenAiCreditOperation(true, true)).toBe('rename_remap');
  });
});
