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

const FEATURE_PLAN_PAGES: FeaturePlanPage[] = [
  {
    key: 'free-features',
    path: '/free-features',
    navLabel: 'Free Features',
    heroTitle: 'Free DullyPDF Features for PDF-to-Form Setup',
    heroSummary:
      'Start with unlimited PDF-to-form conversion and the form builder, then use the free tier to validate your template workflow before upgrading for higher usage.',
    seoTitle: 'Free PDF Form Builder Features | DullyPDF',
    seoDescription:
      'Review the free DullyPDF feature set, including unlimited PDF-to-form setup, form builder access, and the free Fill By Link limits before upgrading.',
    seoKeywords: [
      'free pdf form builder',
      'free pdf to form tool',
      'free fillable pdf builder',
      'free pdf workflow software',
    ],
    valuePoints: [
      'Unlimited PDF-to-form setup and access to the form builder.',
      'A practical free tier for validating field detection, cleanup, and saved-template workflows.',
      'Native Fill By Link support with 1 active published link and up to 5 accepted responses.',
    ],
    detailSections: [
      {
        title: 'Best fit for',
        items: [
          'Teams validating one workflow before rolling out larger intake or packet automation.',
          'Owners who want to test field detection, editor cleanup, and mapping quality on real documents.',
          'Users who need one live respondent link instead of a larger link portfolio.',
        ],
      },
      {
        title: 'Included workflow access',
        items: [
          'Upload PDFs up to 50MB and convert them into editable templates.',
          'Use the form builder, field inspector, list panel, and saved-template workflow.',
          'Run Search & Fill with local CSV, Excel, JSON, or stored respondent records once your template is mapped.',
        ],
      },
      {
        title: 'Free-tier limits that stay visible',
        items: [
          'Fill By Link: 1 active published link and 5 accepted responses per link.',
          'OpenAI credits and some effective profile limits are enforced server-side and shown in Profile.',
          'When you need higher usage, premium expands link capacity and monthly OpenAI credit access.',
        ],
      },
    ],
    faqs: [
      {
        question: 'Does free still let me convert PDFs into fillable templates?',
        answer:
          'Yes. Free includes unlimited PDF-to-form setup plus the form builder so you can detect, clean up, and save reusable templates.',
      },
      {
        question: 'What is the main free-tier Fill By Link limit?',
        answer:
          'Free supports 1 active published link at a time, and each link accepts up to 5 responses before it closes.',
      },
      {
        question: 'Where do I confirm my current limits?',
        answer:
          'The signed-in Profile view shows your effective account limits, billing status, and remaining credits.',
      },
    ],
    relatedLinks: [
      { label: 'Premium Features', href: '/premium-features' },
      { label: 'Usage Docs', href: '/usage-docs' },
      { label: 'Fill By Link Docs', href: '/usage-docs/fill-by-link' },
    ],
  },
  {
    key: 'premium-features',
    path: '/premium-features',
    navLabel: 'Premium Features',
    heroTitle: 'Premium DullyPDF Features for Higher-Usage Workflows',
    heroSummary:
      'Premium is the higher-usage tier for teams running repeat PDF automation, larger Fill By Link traffic, and Stripe-backed account billing.',
    seoTitle: 'Premium PDF Automation Features and Billing | DullyPDF',
    seoDescription:
      'Review premium DullyPDF features, including higher usage across the platform, expanded Fill By Link capacity, monthly OpenAI credits, and sign-in purchase options.',
    seoKeywords: [
      'premium pdf automation software',
      'pdf form builder subscription',
      'fill by link premium plan',
      'stripe pdf software billing',
    ],
    valuePoints: [
      'Higher usage across DullyPDF workflows instead of the lighter free-tier guardrails.',
      'A shareable Fill By Link on every saved template with up to 10,000 accepted responses per link.',
      'Stripe-backed monthly or yearly purchase options when you are signed in.',
    ],
    detailSections: [
      {
        title: 'Premium unlocks',
        items: [
          'Higher-usage access across PDF detection, template reuse, mapping, and Fill By Link workflows.',
          'One shareable Fill By Link per saved template instead of the free single-link cap.',
          'Up to 10,000 accepted responses per link for respondent-driven workflows.',
        ],
      },
      {
        title: 'OpenAI and billing',
        items: [
          'Pro billing actions run through Stripe Checkout with monthly and yearly subscriptions.',
          'Premium profiles receive a monthly OpenAI credit pool, and refill packs remain available from Profile.',
          'Cancellation is managed from the signed-in profile billing section and is scheduled for period end.',
        ],
      },
      {
        title: 'Best fit for',
        items: [
          'Teams operating repeat intake or packet workflows across many saved templates.',
          'Owners publishing multiple public respondent links at once.',
          'Accounts that need higher sustained usage instead of one-off free-tier validation.',
        ],
      },
    ],
    faqs: [
      {
        question: 'What is the biggest premium Fill By Link difference?',
        answer:
          'Premium removes the single-link cap by allowing a shareable link on every saved template and raises response capacity to 10,000 per link.',
      },
      {
        question: 'Can I buy premium from this page?',
        answer:
          'Yes. When you are signed in and billing is available, this page can launch the Stripe Checkout flow for monthly or yearly premium.',
      },
      {
        question: 'What if I already have premium?',
        answer:
          'The page will show that the current account already has premium access instead of offering another upgrade button.',
      },
    ],
    relatedLinks: [
      { label: 'Free Features', href: '/free-features' },
      { label: 'Save, Download, and Profile Docs', href: '/usage-docs/save-download-profile' },
      { label: 'Fill By Link Docs', href: '/usage-docs/fill-by-link' },
    ],
  },
];

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
