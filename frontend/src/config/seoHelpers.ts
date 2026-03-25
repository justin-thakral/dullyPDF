export type SeoStructuredDataEntry = Record<string, unknown>;

export type SeoBreadcrumbItem = {
  label: string;
  href?: string;
};

const SITE_ORIGIN = 'https://dullypdf.com';

export const buildBreadcrumbSchema = (items: SeoBreadcrumbItem[]): SeoStructuredDataEntry => ({
  '@context': 'https://schema.org',
  '@type': 'BreadcrumbList',
  itemListElement: items.map((item, index) => ({
    '@type': 'ListItem',
    position: index + 1,
    name: item.label,
    ...(item.href ? { item: `${SITE_ORIGIN}${item.href}` } : {}),
  })),
});

export const appendStructuredData = (
  existingEntries: SeoStructuredDataEntry[] | undefined,
  nextEntry: SeoStructuredDataEntry,
): SeoStructuredDataEntry[] => [...(existingEntries ?? []), nextEntry];

export const buildIntentSeoTitle = (heroTitle: string): string => `${heroTitle} | DullyPDF`;

export const buildIntentSeoDescription = (heroSummary: string): string => heroSummary;
