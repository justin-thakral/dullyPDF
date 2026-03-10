import type { CreditPricingConfig } from '../services/api';

export type OpenAiCreditOperation = 'rename' | 'remap' | 'rename_remap';

export type CreditEstimate = {
  operation: OpenAiCreditOperation;
  pageCount: number;
  bucketSize: number;
  bucketCount: number;
  baseCost: number;
  totalCredits: number;
};

export type BatchCreditEstimate = {
  operation: OpenAiCreditOperation;
  totalPages: number;
  documentCount: number;
  totalCredits: number;
  documents: CreditEstimate[];
};

export type DetectPageSummary = {
  maxPages: number;
  totalPages: number;
  largestPageCount: number;
  withinLimit: boolean;
  offendingPageCounts: number[];
};

const DEFAULT_PRICING: CreditPricingConfig = {
  pageBucketSize: 5,
  renameBaseCost: 1,
  remapBaseCost: 1,
  renameRemapBaseCost: 2,
};

function coercePositiveInt(value: unknown, fallback = 1): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  const normalized = Math.floor(parsed);
  return normalized > 0 ? normalized : fallback;
}

export function resolveClientCreditPricing(
  pricing?: CreditPricingConfig | null,
): CreditPricingConfig {
  return {
    pageBucketSize: coercePositiveInt(pricing?.pageBucketSize, DEFAULT_PRICING.pageBucketSize),
    renameBaseCost: coercePositiveInt(pricing?.renameBaseCost, DEFAULT_PRICING.renameBaseCost),
    remapBaseCost: coercePositiveInt(pricing?.remapBaseCost, DEFAULT_PRICING.remapBaseCost),
    renameRemapBaseCost: coercePositiveInt(
      pricing?.renameRemapBaseCost,
      DEFAULT_PRICING.renameRemapBaseCost,
    ),
  };
}

export function resolveOpenAiCreditOperation(
  wantsRename: boolean,
  wantsMap: boolean,
): OpenAiCreditOperation | null {
  if (wantsRename && wantsMap) return 'rename_remap';
  if (wantsRename) return 'rename';
  if (wantsMap) return 'remap';
  return null;
}

function resolveBaseCost(
  operation: OpenAiCreditOperation,
  pricing: CreditPricingConfig,
): number {
  if (operation === 'rename') return pricing.renameBaseCost;
  if (operation === 'remap') return pricing.remapBaseCost;
  return pricing.renameRemapBaseCost;
}

export function estimateCreditsForPageCount(
  operation: OpenAiCreditOperation,
  pageCount: number,
  pricingInput?: CreditPricingConfig | null,
): CreditEstimate {
  const pricing = resolveClientCreditPricing(pricingInput);
  const normalizedPageCount = coercePositiveInt(pageCount);
  const bucketSize = pricing.pageBucketSize;
  const bucketCount = Math.max(1, Math.ceil(normalizedPageCount / bucketSize));
  const baseCost = resolveBaseCost(operation, pricing);
  return {
    operation,
    pageCount: normalizedPageCount,
    bucketSize,
    bucketCount,
    baseCost,
    totalCredits: Math.max(1, bucketCount * baseCost),
  };
}

export function estimateCreditsForPageCounts(
  operation: OpenAiCreditOperation,
  pageCounts: number[],
  pricingInput?: CreditPricingConfig | null,
): BatchCreditEstimate {
  const documents = pageCounts
    .map((pageCount) => estimateCreditsForPageCount(operation, pageCount, pricingInput));
  return {
    operation,
    totalPages: documents.reduce((sum, entry) => sum + entry.pageCount, 0),
    documentCount: documents.length,
    totalCredits: documents.reduce((sum, entry) => sum + entry.totalCredits, 0),
    documents,
  };
}

export function summarizeDetectPageCounts(
  pageCounts: number[],
  maxPages: number,
): DetectPageSummary {
  const normalizedMax = coercePositiveInt(maxPages);
  const normalizedPages = pageCounts.map((pageCount) => coercePositiveInt(pageCount));
  const offendingPageCounts = normalizedPages.filter((pageCount) => pageCount > normalizedMax);
  return {
    maxPages: normalizedMax,
    totalPages: normalizedPages.reduce((sum, pageCount) => sum + pageCount, 0),
    largestPageCount: normalizedPages.length ? Math.max(...normalizedPages) : 0,
    withinLimit: offendingPageCounts.length === 0,
    offendingPageCounts,
  };
}

