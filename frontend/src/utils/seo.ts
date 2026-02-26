import {
  DEFAULT_SOCIAL_IMAGE_ALT,
  DEFAULT_SOCIAL_IMAGE_PATH,
  SITE_ORIGIN,
  resolveRouteSeo,
  type PublicRouteSeoTarget,
  type RouteSeoMetadata,
} from '../config/routeSeo';

const ensureMetaByName = (name: string): HTMLMetaElement => {
  const existing = document.head.querySelector(`meta[name="${name}"]`);
  if (existing instanceof HTMLMetaElement) return existing;
  const meta = document.createElement('meta');
  meta.setAttribute('name', name);
  document.head.appendChild(meta);
  return meta;
};

const ensureMetaByProperty = (property: string): HTMLMetaElement => {
  const existing = document.head.querySelector(`meta[property="${property}"]`);
  if (existing instanceof HTMLMetaElement) return existing;
  const meta = document.createElement('meta');
  meta.setAttribute('property', property);
  document.head.appendChild(meta);
  return meta;
};

const ensureCanonicalLink = (): HTMLLinkElement => {
  const existing = document.head.querySelector('link[rel="canonical"]');
  if (existing instanceof HTMLLinkElement) return existing;
  const link = document.createElement('link');
  link.setAttribute('rel', 'canonical');
  document.head.appendChild(link);
  return link;
};

const toAbsoluteUrl = (path: string): string => {
  if (/^https?:\/\//i.test(path)) return path;
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  return `${SITE_ORIGIN}${normalizedPath}`;
};

const clearSeoJsonLdScripts = (): void => {
  document.head.querySelectorAll('script[data-seo-jsonld="true"]').forEach((node) => {
    node.remove();
  });
};

const applySeoJsonLd = (entries: Record<string, unknown>[]): void => {
  clearSeoJsonLdScripts();
  entries.forEach((entry, index) => {
    const script = document.createElement('script');
    script.setAttribute('type', 'application/ld+json');
    script.setAttribute('data-seo-jsonld', 'true');
    script.setAttribute('data-seo-jsonld-index', String(index));
    script.textContent = JSON.stringify(entry);
    document.head.appendChild(script);
  });
};

export const applySeoMetadata = (metadata: RouteSeoMetadata): void => {
  if (typeof document === 'undefined') return;

  const canonicalUrl = toAbsoluteUrl(metadata.canonicalPath);
  const ogTitle = metadata.ogTitle ?? metadata.title;
  const ogDescription = metadata.ogDescription ?? metadata.description;
  const twitterTitle = metadata.twitterTitle ?? ogTitle;
  const twitterDescription = metadata.twitterDescription ?? ogDescription;
  const imageUrl = toAbsoluteUrl(DEFAULT_SOCIAL_IMAGE_PATH);

  document.title = metadata.title;

  ensureMetaByName('description').setAttribute('content', metadata.description);
  ensureMetaByName('keywords').setAttribute('content', metadata.keywords.join(', '));
  ensureMetaByName('robots').setAttribute('content', 'index,follow');

  ensureCanonicalLink().setAttribute('href', canonicalUrl);

  ensureMetaByProperty('og:type').setAttribute('content', 'website');
  ensureMetaByProperty('og:site_name').setAttribute('content', 'DullyPDF');
  ensureMetaByProperty('og:title').setAttribute('content', ogTitle);
  ensureMetaByProperty('og:description').setAttribute('content', ogDescription);
  ensureMetaByProperty('og:url').setAttribute('content', canonicalUrl);
  ensureMetaByProperty('og:image').setAttribute('content', imageUrl);
  ensureMetaByProperty('og:image:alt').setAttribute('content', DEFAULT_SOCIAL_IMAGE_ALT);

  ensureMetaByName('twitter:card').setAttribute('content', 'summary_large_image');
  ensureMetaByName('twitter:title').setAttribute('content', twitterTitle);
  ensureMetaByName('twitter:description').setAttribute('content', twitterDescription);
  ensureMetaByName('twitter:image').setAttribute('content', imageUrl);

  if (metadata.structuredData?.length) {
    applySeoJsonLd(metadata.structuredData);
  } else {
    clearSeoJsonLdScripts();
  }
};

export const applyRouteSeo = (target: PublicRouteSeoTarget): RouteSeoMetadata => {
  const metadata = resolveRouteSeo(target);
  applySeoMetadata(metadata);
  return metadata;
};

type NoIndexSeoOptions = {
  title: string;
  description: string;
  canonicalPath: string;
};

export const applyNoIndexSeo = (options: NoIndexSeoOptions): void => {
  if (typeof document === 'undefined') return;

  document.title = options.title;
  ensureMetaByName('description').setAttribute('content', options.description);
  ensureMetaByName('robots').setAttribute('content', 'noindex,follow');
  ensureCanonicalLink().setAttribute('href', toAbsoluteUrl(options.canonicalPath));
  clearSeoJsonLdScripts();
};
