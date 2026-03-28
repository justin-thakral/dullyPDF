import type { UsageDocsPageKey } from '../components/pages/usageDocsContent';
import { INTENT_PAGES as SHARED_INTENT_PAGES } from './publicRouteSeoData.mjs';

export type IntentPageKey =
  | 'pdf-to-fillable-form'
  | 'pdf-to-database-template'
  | 'fill-pdf-from-csv'
  | 'fill-pdf-by-link'
  | 'pdf-signature-workflow'
  | 'esign-ueta-pdf-workflow'
  | 'pdf-fill-api'
  | 'fill-information-in-pdf'
  | 'fillable-form-field-name'
  | 'healthcare-pdf-automation'
  | 'acord-form-automation'
  | 'insurance-pdf-automation'
  | 'real-estate-pdf-automation'
  | 'government-form-automation'
  | 'finance-loan-pdf-automation'
  | 'hr-pdf-automation'
  | 'legal-pdf-workflow-automation'
  | 'education-form-automation'
  | 'nonprofit-pdf-form-automation'
  | 'logistics-pdf-automation'
  | 'batch-fill-pdf-forms'
  | 'pdf-checkbox-automation'
  | 'pdf-radio-button-editor'
  | 'pdf-field-detection-tool'
  | 'construction-pdf-automation'
  | 'accounting-tax-pdf-automation';

export type IntentPageCategory = 'workflow' | 'industry';

export type IntentFaq = {
  question: string;
  answer: string;
};

export type IntentArticleSection = {
  title: string;
  paragraphs: string[];
  bullets?: string[];
};

export type IntentSupportLink = {
  label: string;
  href: string;
  description?: string;
};

export type IntentSupportSection = {
  title: string;
  paragraphs?: string[];
  links?: IntentSupportLink[];
};

export type IntentFootnote = {
  id: string;
  label: string;
  href: string;
};

export type IntentPage = {
  key: IntentPageKey;
  category: IntentPageCategory;
  path: string;
  navLabel: string;
  heroTitle: string;
  heroSummary: string;
  seoTitle: string;
  seoDescription: string;
  seoKeywords: string[];
  valuePoints: string[];
  proofPoints: string[];
  faqs: IntentFaq[];
  articleSections?: IntentArticleSection[];
  footnotes?: IntentFootnote[];
  supportSections?: IntentSupportSection[];
  relatedIntentPages?: IntentPageKey[];
  relatedDocs?: UsageDocsPageKey[];
};

const INTENT_PAGES = SHARED_INTENT_PAGES as IntentPage[];

const PAGE_BY_KEY = new Map<IntentPageKey, IntentPage>(INTENT_PAGES.map((page) => [page.key, page]));
const PAGE_BY_PATH = new Map<string, IntentPage>(INTENT_PAGES.map((page) => [page.path, page]));

export const getIntentPages = (): IntentPage[] => INTENT_PAGES;

export const getIntentPage = (key: IntentPageKey): IntentPage => {
  const page = PAGE_BY_KEY.get(key);
  if (!page) throw new Error(`Unknown intent page key: ${key}`);
  return page;
};

export const resolveIntentPath = (pathname: string): IntentPageKey | null => {
  const normalizedPath = pathname.replace(/\/+$/, '') || '/';
  const page = PAGE_BY_PATH.get(normalizedPath);
  return page?.key ?? null;
};
