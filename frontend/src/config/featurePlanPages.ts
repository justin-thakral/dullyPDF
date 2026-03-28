import { FEATURE_PLAN_PAGES as SHARED_FEATURE_PLAN_PAGES } from './publicRouteSeoData.mjs';

export type FeaturePlanPageKey = 'free-features' | 'premium-features';

export type FeaturePlanFaq = {
  question: string;
  answer: string;
};

export type FeaturePlanDetailSection = {
  title: string;
  items: string[];
};

export type FeaturePlanPage = {
  key: FeaturePlanPageKey;
  path: string;
  navLabel: string;
  heroTitle: string;
  heroSummary: string;
  seoTitle: string;
  seoDescription: string;
  seoKeywords: string[];
  valuePoints: string[];
  detailSections: FeaturePlanDetailSection[];
  faqs: FeaturePlanFaq[];
  relatedLinks: Array<{ label: string; href: string }>;
};

const FEATURE_PLAN_PAGES = SHARED_FEATURE_PLAN_PAGES as FeaturePlanPage[];

export function getFeaturePlanPages(): FeaturePlanPage[] {
  return FEATURE_PLAN_PAGES;
}

export function getFeaturePlanPage(pageKey: FeaturePlanPageKey): FeaturePlanPage {
  const page = FEATURE_PLAN_PAGES.find((entry) => entry.key === pageKey);
  if (!page) {
    throw new Error(`Unknown feature plan page key: ${pageKey}`);
  }
  return page;
}

export function resolveFeaturePlanPath(pathname: string): FeaturePlanPageKey | null {
  const normalizedPath = pathname.replace(/\/+$/, '') || '/';
  const match = FEATURE_PLAN_PAGES.find((page) => page.path === normalizedPath);
  return match?.key ?? null;
}
