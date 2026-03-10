import type { UsageDocsPageKey } from '../components/pages/usageDocsContent';
import { getIntentPages, type IntentFaq, type IntentPageKey } from './intentPages';
import { getFeaturePlanPages, type FeaturePlanPageKey } from './featurePlanPages';
import { BLOG_INDEX_SEO, resolveBlogSeo } from './blogSeo';
import { getBlogSlugs } from './blogPosts';

export type LegalRouteKey = 'privacy' | 'terms';
export type IntentHubRouteKey = 'workflows' | 'industries';

export type PublicRouteSeoTarget =
  | { kind: 'app' }
  | { kind: 'legal'; legalKind: LegalRouteKey }
  | { kind: 'intent-hub'; hubKey: IntentHubRouteKey }
  | { kind: 'feature-plan'; planKey: FeaturePlanPageKey }
  | { kind: 'usage-docs'; pageKey: UsageDocsPageKey }
  | { kind: 'intent'; intentKey: IntentPageKey }
  | { kind: 'blog-index' }
  | { kind: 'blog-post'; slug: string };

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
  title: 'DullyPDF | Convert PDFs to Fillable Forms, Share Fill Links, and Map Data',
  description:
    'DullyPDF is a PDF form builder for existing documents. Convert PDFs into fillable templates with AI field detection, publish native Fill By Link forms, map fields to database columns, and auto-fill from CSV, Excel, JSON, or respondent records. Free to start.',
  canonicalPath: '/',
  keywords: [
    'pdf to fillable form',
    'pdf form builder',
    'fillable pdf builder',
    'fill by link pdf',
    'shareable pdf form link',
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
        'DullyPDF is a PDF form builder for existing documents. It converts PDFs into fillable templates, publishes native Fill By Link forms, maps fields to schema headers, and fills mapped fields from structured data rows or respondent records.',
      offers: {
        '@type': 'Offer',
        price: '0',
        priceCurrency: 'USD',
      },
      featureList: [
        'PDF form builder for existing PDFs',
        'PDF field detection',
        'Fillable form template editing',
        'Native Fill By Link forms for saved templates',
        'Free includes 1 shareable link and 5 responses',
        'Premium supports every template and up to 10,000 responses per link',
        'Schema mapping for CSV/XLSX/JSON',
        'Search and fill workflows with local rows or stored respondents',
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
        email: 'justin@dullypdf.com',
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

const INTENT_HUB_ROUTE_SEO: Record<IntentHubRouteKey, RouteSeoMetadata> = {
  workflows: {
    title: 'Workflow Library for PDF Automation | DullyPDF',
    description:
      'Explore DullyPDF workflow pages for converting PDFs to fillable templates, mapping fields to schemas, and auto-filling from structured data.',
    canonicalPath: '/workflows',
    keywords: [
      'pdf workflow library',
      'pdf to fillable form workflow',
      'pdf mapping and autofill workflows',
    ],
  },
  industries: {
    title: 'Industry PDF Automation Solutions | DullyPDF',
    description:
      'Explore DullyPDF industry pages for healthcare, insurance, legal, HR, finance, and other repeat PDF automation workflows.',
    canonicalPath: '/industries',
    keywords: [
      'industry pdf automation',
      'healthcare insurance legal pdf workflows',
      'pdf form automation by industry',
    ],
  },
};

const USAGE_DOCS_ROUTE_SEO: Record<UsageDocsPageKey, RouteSeoMetadata> = {
  index: {
    title: 'PDF Form Automation Docs and Workflow Guide | DullyPDF',
    description:
      'Learn the full DullyPDF workflow: PDF field detection, OpenAI rename and mapping, editor cleanup, native Fill By Link publishing, and Search & Fill output steps.',
    canonicalPath: '/usage-docs',
    keywords: [
      'pdf form automation docs',
      'fillable form workflow',
      'pdf template workflow',
      'fill by link pdf docs',
    ],
  },
  'getting-started': {
    title: 'How to Convert PDF to Fillable Form Template | DullyPDF Docs',
    description:
      'Follow a practical quick-start for turning a PDF into a reusable fillable template with mapping, Fill By Link publishing, and Search & Fill validation.',
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
    title: 'Auto Fill PDF from CSV, Excel, JSON, or Fill By Link Respondents | DullyPDF Docs',
    description:
      'Connect local data rows or stored Fill By Link respondents, search records, and auto-fill mapped PDF templates from CSV, Excel, JSON, or native DullyPDF respondent sources.',
    canonicalPath: '/usage-docs/search-fill',
    keywords: ['auto fill pdf from csv', 'fill pdf from excel', 'fill pdf from json', 'fill by link pdf'],
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
                'CSV, XLSX, JSON, and stored DullyPDF Fill By Link respondent records support row-based fill. TXT is schema-only and does not provide row data for filling.',
            },
          },
          {
            '@type': 'Question',
            name: 'Can Fill By Link responses be used in Search and Fill?',
            acceptedAnswer: {
              '@type': 'Answer',
              text:
                'Yes. Owners can publish a native Fill By Link from a saved template, collect respondent answers, and then select a respondent record from the workspace when generating the final PDF.',
            },
          },
        ],
      },
    ],
  },
  'fill-by-link': {
    title: 'Fill By Link Workflow and Respondent Forms | DullyPDF Docs',
    description:
      'Publish native DullyPDF Fill By Link forms from saved templates or groups, share respondent links, and generate PDFs later from stored submissions.',
    canonicalPath: '/usage-docs/fill-by-link',
    keywords: ['fill by link pdf', 'shareable pdf form link', 'respondent form workflow', 'html form to fill pdf'],
    structuredData: [
      {
        '@context': 'https://schema.org',
        '@type': 'FAQPage',
        mainEntity: [
          {
            '@type': 'Question',
            name: 'Does Fill By Link publish the PDF itself?',
            acceptedAnswer: {
              '@type': 'Answer',
              text:
                'No. DullyPDF publishes a hosted HTML form and generates the final PDF later from the saved respondent submission.',
            },
          },
          {
            '@type': 'Question',
            name: 'Can one group publish a single shared respondent form?',
            acceptedAnswer: {
              '@type': 'Answer',
              text:
                'Yes. An open group can publish one merged Fill By Link that includes every distinct respondent-facing field across the group.',
            },
          },
        ],
      },
    ],
  },
  'create-group': {
    title: 'Create Group Workflows for Full PDF Packets | DullyPDF Docs',
    description:
      'Create groups of saved templates, switch packet members quickly, Search and Fill full document sets, and batch Rename + Map every template in the group.',
    canonicalPath: '/usage-docs/create-group',
    keywords: ['create group pdf templates', 'group pdf workflow', 'batch rename map pdf packet', 'pdf packet automation'],
    structuredData: [
      {
        '@context': 'https://schema.org',
        '@type': 'FAQPage',
        mainEntity: [
          {
            '@type': 'Question',
            name: 'What does a DullyPDF group do?',
            acceptedAnswer: {
              '@type': 'Answer',
              text:
                'A group bundles saved templates into one packet so teams can switch documents quickly, fill the packet from one record, and run batch rename and mapping actions.',
            },
          },
          {
            '@type': 'Question',
            name: 'Can Rename + Map run across the whole group?',
            acceptedAnswer: {
              '@type': 'Answer',
              text:
                'Yes. Rename + Map Group runs across every saved template in the open group and overwrites each template on success.',
            },
          },
        ],
      },
    ],
  },
  'save-download-profile': {
    title: 'Save Reusable PDF Templates and Download Outputs | DullyPDF Docs',
    description:
      'Learn when to download generated files or save templates to your DullyPDF profile for reuse, Fill By Link publishing, billing, and collaboration.',
    canonicalPath: '/usage-docs/save-download-profile',
    keywords: ['save pdf template', 'download filled pdf', 'reusable pdf templates', 'share pdf form link'],
  },
  troubleshooting: {
    title: 'PDF Form Automation Troubleshooting Guide | DullyPDF Docs',
    description:
      'Diagnose detection, mapping, and fill issues with targeted checks and known validation errors in DullyPDF workflows.',
    canonicalPath: '/usage-docs/troubleshooting',
    keywords: ['pdf automation troubleshooting', 'fillable pdf mapping issues'],
  },
};

const toFaqSchema = (faqs: Array<Pick<IntentFaq, 'question' | 'answer'>>): Record<string, unknown>[] => [
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

const FEATURE_PLAN_ROUTE_SEO: Record<FeaturePlanPageKey, RouteSeoMetadata> = getFeaturePlanPages().reduce(
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
  {} as Record<FeaturePlanPageKey, RouteSeoMetadata>,
);

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
  'fill-by-link',
  'create-group',
  'save-download-profile',
  'troubleshooting',
];

export const INDEXABLE_PUBLIC_ROUTE_PATHS: string[] = [
  HOME_ROUTE_SEO.canonicalPath,
  LEGAL_ROUTE_SEO.privacy.canonicalPath,
  LEGAL_ROUTE_SEO.terms.canonicalPath,
  INTENT_HUB_ROUTE_SEO.workflows.canonicalPath,
  INTENT_HUB_ROUTE_SEO.industries.canonicalPath,
  ...getFeaturePlanPages().map((page) => page.path),
  ...USAGE_DOCS_ROUTE_ORDER.map((pageKey) => USAGE_DOCS_ROUTE_SEO[pageKey].canonicalPath),
  ...getIntentPages().map((page) => page.path),
  BLOG_INDEX_SEO.canonicalPath,
  ...getBlogSlugs().map((slug) => `/blog/${slug}`),
];

export const resolveRouteSeo = (target: PublicRouteSeoTarget): RouteSeoMetadata => {
  if (target.kind === 'app') return HOME_ROUTE_SEO;
  if (target.kind === 'legal') return LEGAL_ROUTE_SEO[target.legalKind];
  if (target.kind === 'intent-hub') return INTENT_HUB_ROUTE_SEO[target.hubKey];
  if (target.kind === 'feature-plan') return FEATURE_PLAN_ROUTE_SEO[target.planKey];
  if (target.kind === 'intent') return INTENT_ROUTE_SEO[target.intentKey];
  if (target.kind === 'blog-index') return BLOG_INDEX_SEO;
  if (target.kind === 'blog-post') {
    const blogSeo = resolveBlogSeo(target.slug);
    if (blogSeo) return blogSeo;
    return BLOG_INDEX_SEO;
  }
  return USAGE_DOCS_ROUTE_SEO[target.pageKey];
};
