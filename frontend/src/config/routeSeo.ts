import type { UsageDocsPageKey } from '../components/pages/usageDocsContent';
import { getIntentPages, type IntentFaq, type IntentPageKey } from './intentPages';

export type LegalRouteKey = 'privacy' | 'terms';

export type PublicRouteSeoTarget =
  | { kind: 'app' }
  | { kind: 'legal'; legalKind: LegalRouteKey }
  | { kind: 'usage-docs'; pageKey: UsageDocsPageKey }
  | { kind: 'intent'; intentKey: IntentPageKey };

export type RouteSeoMetadata = {
  title: string;
  description: string;
  canonicalPath: string;
  keywords: string[];
  ogTitle?: string;
  ogDescription?: string;
  twitterTitle?: string;
  twitterDescription?: string;
  structuredData?: Record<string, unknown>[];
};

export const SITE_ORIGIN = 'https://dullypdf.com';
export const DEFAULT_SOCIAL_IMAGE_PATH = '/DullyPDFLogoImproved.png';
export const DEFAULT_SOCIAL_IMAGE_ALT = 'DullyPDF logo';

const HOME_ROUTE_SEO: RouteSeoMetadata = {
  title: 'PDF to Fillable Form Converter and Database Mapping | DullyPDF',
  description:
    'Convert raw PDFs into fillable form templates, map fields to database columns, and auto-fill forms from CSV, Excel, or JSON in DullyPDF.',
  canonicalPath: '/',
  keywords: [
    'pdf to fillable form',
    'pdf to database template',
    'fillable pdf template generator',
    'map pdf fields to database columns',
    'auto fill pdf from csv',
  ],
  structuredData: [
    {
      '@context': 'https://schema.org',
      '@type': 'SoftwareApplication',
      name: 'DullyPDF',
      applicationCategory: 'BusinessApplication',
      operatingSystem: 'Web',
      url: 'https://dullypdf.com/',
      description:
        'DullyPDF converts PDFs into fillable templates, maps fields to schema headers, and fills mapped fields from structured data rows.',
      offers: {
        '@type': 'Offer',
        price: '0',
        priceCurrency: 'USD',
      },
      featureList: [
        'PDF field detection',
        'Fillable form template editing',
        'Schema mapping for CSV/XLSX/JSON',
        'Search and fill workflows',
      ],
    },
    {
      '@context': 'https://schema.org',
      '@type': 'Organization',
      name: 'DullyPDF',
      url: 'https://dullypdf.com/',
      logo: 'https://dullypdf.com/DullyPDFLogoImproved.png',
      contactPoint: {
        '@type': 'ContactPoint',
        contactType: 'customer support',
        email: 'justin@ttcommercial.com',
      },
    },
  ],
};

const LEGAL_ROUTE_SEO: Record<LegalRouteKey, RouteSeoMetadata> = {
  privacy: {
    title: 'Privacy Policy | DullyPDF',
    description:
      'Read how DullyPDF handles account data, uploaded PDFs, schema metadata, optional AI processing, and billing information.',
    canonicalPath: '/privacy',
    keywords: ['dullypdf privacy policy', 'pdf form automation privacy'],
  },
  terms: {
    title: 'Terms of Service | DullyPDF',
    description:
      'Review DullyPDF service terms covering accounts, AI-assisted workflows, billing, acceptable use, and platform limitations.',
    canonicalPath: '/terms',
    keywords: ['dullypdf terms', 'pdf automation terms of service'],
  },
};

const USAGE_DOCS_ROUTE_SEO: Record<UsageDocsPageKey, RouteSeoMetadata> = {
  index: {
    title: 'PDF Form Automation Docs and Workflow Guide | DullyPDF',
    description:
      'Learn the full DullyPDF workflow: PDF field detection, OpenAI rename and mapping, editor cleanup, and Search & Fill output steps.',
    canonicalPath: '/usage-docs',
    keywords: [
      'pdf form automation docs',
      'fillable form workflow',
      'pdf template workflow',
    ],
  },
  'getting-started': {
    title: 'How to Convert PDF to Fillable Form Template | DullyPDF Docs',
    description:
      'Follow a practical quick-start for turning a PDF into a reusable fillable template with mapping and Search & Fill validation.',
    canonicalPath: '/usage-docs/getting-started',
    keywords: ['convert pdf to fillable form', 'fillable pdf setup guide'],
    structuredData: [
      {
        '@context': 'https://schema.org',
        '@type': 'FAQPage',
        mainEntity: [
          {
            '@type': 'Question',
            name: 'How do I convert a PDF into a fillable template in DullyPDF?',
            acceptedAnswer: {
              '@type': 'Answer',
              text:
                'Upload a PDF, run field detection, review/edit field geometry and names, then save the template for reuse.',
            },
          },
          {
            '@type': 'Question',
            name: 'Do I need mapping before Search and Fill?',
            acceptedAnswer: {
              '@type': 'Answer',
              text:
                'Mapping is strongly recommended for reliable output, especially for checkbox groups and non-trivial schemas.',
            },
          },
        ],
      },
    ],
  },
  detection: {
    title: 'AI PDF Form Field Detection Guide | DullyPDF Docs',
    description:
      'Understand PDF field detection confidence, geometry constraints, and cleanup strategies for accurate fillable templates.',
    canonicalPath: '/usage-docs/detection',
    keywords: ['pdf form field detection', 'ai pdf detection', 'detect fillable fields in pdf'],
  },
  'rename-mapping': {
    title: 'Map PDF Fields to Database Template Columns | DullyPDF Docs',
    description:
      'Use OpenAI rename and schema mapping to align detected PDF fields with database headers for repeatable auto-fill workflows.',
    canonicalPath: '/usage-docs/rename-mapping',
    keywords: [
      'map pdf fields to database',
      'pdf to database template',
      'pdf schema mapping',
    ],
    structuredData: [
      {
        '@context': 'https://schema.org',
        '@type': 'FAQPage',
        mainEntity: [
          {
            '@type': 'Question',
            name: 'What is PDF field to database mapping?',
            acceptedAnswer: {
              '@type': 'Answer',
              text:
                'It links PDF field identifiers to schema headers so row data can populate the correct fields during fill operations.',
            },
          },
          {
            '@type': 'Question',
            name: 'Should I run rename before map?',
            acceptedAnswer: {
              '@type': 'Answer',
              text:
                'When labels are inconsistent, rename first improves field naming consistency and typically improves mapping quality.',
            },
          },
        ],
      },
    ],
  },
  'editor-workflow': {
    title: 'Edit Fillable PDF Fields and Template Geometry | DullyPDF Docs',
    description:
      'Use overlay, field list, and inspector tools to refine field names, types, and coordinates before production use.',
    canonicalPath: '/usage-docs/editor-workflow',
    keywords: ['editable fillable pdf template', 'pdf field editor workflow'],
  },
  'search-fill': {
    title: 'Auto Fill PDF from CSV, Excel, and JSON | DullyPDF Docs',
    description:
      'Connect local data rows, search records, and auto-fill mapped PDF templates from CSV, Excel, or JSON sources.',
    canonicalPath: '/usage-docs/search-fill',
    keywords: ['auto fill pdf from csv', 'fill pdf from excel', 'fill pdf from json'],
    structuredData: [
      {
        '@context': 'https://schema.org',
        '@type': 'FAQPage',
        mainEntity: [
          {
            '@type': 'Question',
            name: 'Can DullyPDF fill PDF fields from CSV rows?',
            acceptedAnswer: {
              '@type': 'Answer',
              text:
                'Yes. After mapping, Search and Fill lets you select a row and populate mapped PDF fields from CSV, XLSX, or JSON data.',
            },
          },
          {
            '@type': 'Question',
            name: 'What data sources are supported for row-based fill?',
            acceptedAnswer: {
              '@type': 'Answer',
              text:
                'CSV, XLSX, and JSON support row-based fill. TXT is schema-only and does not provide row data for filling.',
            },
          },
        ],
      },
    ],
  },
  'save-download-profile': {
    title: 'Save Reusable PDF Templates and Download Outputs | DullyPDF Docs',
    description:
      'Learn when to download generated files or save templates to your DullyPDF profile for reuse, billing, and collaboration.',
    canonicalPath: '/usage-docs/save-download-profile',
    keywords: ['save pdf template', 'download filled pdf', 'reusable pdf templates'],
  },
  troubleshooting: {
    title: 'PDF Form Automation Troubleshooting Guide | DullyPDF Docs',
    description:
      'Diagnose detection, mapping, and fill issues with targeted checks and known validation errors in DullyPDF workflows.',
    canonicalPath: '/usage-docs/troubleshooting',
    keywords: ['pdf automation troubleshooting', 'fillable pdf mapping issues'],
  },
};

const toFaqSchema = (faqs: IntentFaq[]): Record<string, unknown>[] => [
  {
    '@context': 'https://schema.org',
    '@type': 'FAQPage',
    mainEntity: faqs.map((faq) => ({
      '@type': 'Question',
      name: faq.question,
      acceptedAnswer: { '@type': 'Answer', text: faq.answer },
    })),
  },
];

const INTENT_ROUTE_SEO: Record<IntentPageKey, RouteSeoMetadata> = getIntentPages().reduce(
  (acc, page) => {
    acc[page.key] = {
      title: page.seoTitle,
      description: page.seoDescription,
      canonicalPath: page.path,
      keywords: page.seoKeywords,
      structuredData: toFaqSchema(page.faqs),
    };
    return acc;
  },
  {} as Record<IntentPageKey, RouteSeoMetadata>,
);

const USAGE_DOCS_ROUTE_ORDER: UsageDocsPageKey[] = [
  'index',
  'getting-started',
  'detection',
  'rename-mapping',
  'editor-workflow',
  'search-fill',
  'save-download-profile',
  'troubleshooting',
];

export const INDEXABLE_PUBLIC_ROUTE_PATHS: string[] = [
  HOME_ROUTE_SEO.canonicalPath,
  LEGAL_ROUTE_SEO.privacy.canonicalPath,
  LEGAL_ROUTE_SEO.terms.canonicalPath,
  ...USAGE_DOCS_ROUTE_ORDER.map((pageKey) => USAGE_DOCS_ROUTE_SEO[pageKey].canonicalPath),
  ...getIntentPages().map((page) => page.path),
];

export const resolveRouteSeo = (target: PublicRouteSeoTarget): RouteSeoMetadata => {
  if (target.kind === 'app') return HOME_ROUTE_SEO;
  if (target.kind === 'legal') return LEGAL_ROUTE_SEO[target.legalKind];
  if (target.kind === 'intent') return INTENT_ROUTE_SEO[target.intentKey];
  return USAGE_DOCS_ROUTE_SEO[target.pageKey];
};
