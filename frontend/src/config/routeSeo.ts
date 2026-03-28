import type { UsageDocsPageKey } from '../components/pages/usageDocsContent';
import type { FeaturePlanPageKey } from './featurePlanPages';
import type { IntentPageKey } from './intentPages';
import {
  ALL_ROUTES as SHARED_PUBLIC_ROUTES,
  DEFAULT_SOCIAL_IMAGE_PATH as SHARED_DEFAULT_SOCIAL_IMAGE_PATH,
  SITE_ORIGIN as SHARED_SITE_ORIGIN,
} from './publicRouteSeoData.mjs';

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

export type RouteBodyLink = {
  label: string;
  href: string;
  description?: string;
};

export type RouteBodySection = {
  title: string;
  description: string;
  href?: string;
};

export type RouteBodySupportSection = {
  title: string;
  paragraphs?: string[];
  links?: RouteBodyLink[];
};

export type RouteSeoBodyContent = {
  heroKicker?: string;
  heading: string;
  paragraphs: string[];
  sections?: RouteBodySection[];
  sectionTitles?: string[];
  articleSections?: Record<string, unknown>[];
  valuePoints?: string[];
  proofPoints?: string[];
  faqs?: Record<string, unknown>[];
  panelTitle?: string;
  panelDescription?: string;
  supportSections?: RouteBodySupportSection[];
};

type SharedPublicRouteKind =
  | 'home'
  | 'legal'
  | 'intent-hub'
  | 'feature-plan'
  | 'usage-docs'
  | 'intent'
  | 'blog-index'
  | 'blog-post';

type SharedPublicRoutePageKey =
  | LegalRouteKey
  | IntentHubRouteKey
  | FeaturePlanPageKey
  | UsageDocsPageKey
  | IntentPageKey;

type SharedPublicRouteEntry = {
  path: string;
  kind: SharedPublicRouteKind;
  pageKey?: SharedPublicRoutePageKey;
  slug?: string;
  seo: RouteSeoMetadata & { bodyContent?: RouteSeoBodyContent };
};

const PUBLIC_ROUTE_ENTRIES = SHARED_PUBLIC_ROUTES as SharedPublicRouteEntry[];

const resolveSharedRoute = (
  predicate: (route: SharedPublicRouteEntry) => boolean,
  description: string,
): SharedPublicRouteEntry => {
  const route = PUBLIC_ROUTE_ENTRIES.find(predicate);
  if (!route) {
    throw new Error(`Missing public SEO route for ${description}`);
  }
  return route;
};

const resolveSeoByKindAndPageKey = (
  kind: SharedPublicRouteKind,
  pageKey: SharedPublicRoutePageKey,
): RouteSeoMetadata => resolveSharedRoute(
  (route) => route.kind === kind && route.pageKey === pageKey,
  `${kind}:${pageKey}`,
).seo;

const BLOG_INDEX_ROUTE = resolveSharedRoute((route) => route.kind === 'blog-index', 'blog-index');

export const SITE_ORIGIN: string = SHARED_SITE_ORIGIN;
export const DEFAULT_SOCIAL_IMAGE_PATH: string = SHARED_DEFAULT_SOCIAL_IMAGE_PATH;
export const DEFAULT_SOCIAL_IMAGE_ALT = 'DullyPDF logo';
export const BLOG_INDEX_SEO: RouteSeoMetadata = BLOG_INDEX_ROUTE.seo;

export const INDEXABLE_PUBLIC_ROUTE_PATHS: string[] = PUBLIC_ROUTE_ENTRIES.map((route) => route.path);

export const resolveBlogRouteSeo = (slug: string | undefined): RouteSeoMetadata | null => {
  if (!slug) return BLOG_INDEX_SEO;

  const blogRoute = PUBLIC_ROUTE_ENTRIES.find(
    (route) => route.kind === 'blog-post' && route.slug === slug,
  );

  return blogRoute?.seo ?? null;
};

export const resolveRouteSeoBodyContent = (
  target: PublicRouteSeoTarget,
): RouteSeoBodyContent | null => {
  if (target.kind === 'blog-post') {
    const blogRoute = PUBLIC_ROUTE_ENTRIES.find(
      (route) => route.kind === 'blog-post' && route.slug === target.slug,
    );
    return blogRoute?.seo.bodyContent ?? null;
  }

  if (target.kind === 'blog-index') {
    return BLOG_INDEX_ROUTE.seo.bodyContent ?? null;
  }

  if (target.kind === 'app') {
    return resolveSharedRoute((route) => route.kind === 'home', 'home').seo.bodyContent ?? null;
  }

  if (target.kind === 'legal') {
    return resolveSharedRoute(
      (route) => route.kind === 'legal' && route.pageKey === target.legalKind,
      `legal:${target.legalKind}`,
    ).seo.bodyContent ?? null;
  }

  if (target.kind === 'intent-hub') {
    return resolveSharedRoute(
      (route) => route.kind === 'intent-hub' && route.pageKey === target.hubKey,
      `intent-hub:${target.hubKey}`,
    ).seo.bodyContent ?? null;
  }

  if (target.kind === 'feature-plan') {
    return resolveSharedRoute(
      (route) => route.kind === 'feature-plan' && route.pageKey === target.planKey,
      `feature-plan:${target.planKey}`,
    ).seo.bodyContent ?? null;
  }

  if (target.kind === 'usage-docs') {
    return resolveSharedRoute(
      (route) => route.kind === 'usage-docs' && route.pageKey === target.pageKey,
      `usage-docs:${target.pageKey}`,
    ).seo.bodyContent ?? null;
  }

  return resolveSharedRoute(
    (route) => route.kind === 'intent' && route.pageKey === target.intentKey,
    `intent:${target.intentKey}`,
  ).seo.bodyContent ?? null;
};

export const resolveRouteSeo = (target: PublicRouteSeoTarget): RouteSeoMetadata => {
  if (target.kind === 'app') {
    return resolveSharedRoute((route) => route.kind === 'home', 'home').seo;
  }

  if (target.kind === 'legal') {
    return resolveSeoByKindAndPageKey('legal', target.legalKind);
  }

  if (target.kind === 'intent-hub') {
    return resolveSeoByKindAndPageKey('intent-hub', target.hubKey);
  }

  if (target.kind === 'feature-plan') {
    return resolveSeoByKindAndPageKey('feature-plan', target.planKey);
  }

  if (target.kind === 'usage-docs') {
    return resolveSeoByKindAndPageKey('usage-docs', target.pageKey);
  }

  if (target.kind === 'intent') {
    return resolveSeoByKindAndPageKey('intent', target.intentKey);
  }

  if (target.kind === 'blog-index') {
    return BLOG_INDEX_SEO;
  }

  return resolveBlogRouteSeo(target.slug) ?? BLOG_INDEX_SEO;
};
