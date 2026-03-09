/** React entrypoint that mounts the application shell. */
import { StrictMode, Suspense, lazy } from 'react';
import { createRoot } from 'react-dom/client';
import './index.css';
import {
  ACCOUNT_ACTION_ROUTE_PATH,
  LEGACY_ACCOUNT_ACTION_ROUTE_PATH,
} from './utils/emailActions';
import type { LegalPageKind } from './components/pages/LegalPage';
import {
  resolveUsageDocsPath,
  type UsageDocsPageKey,
} from './components/pages/usageDocsContent';
import { resolveIntentPath, type IntentPageKey } from './config/intentPages';

const App = lazy(() => import('./App'));
const LegalPage = lazy(() => import('./components/pages/LegalPage'));
const PublicNotFoundPage = lazy(() => import('./components/pages/PublicNotFoundPage'));
const AccountActionPage = lazy(() => import('./components/pages/AccountActionPage'));
const UsageDocsPage = lazy(() => import('./components/pages/UsageDocsPage'));
const UsageDocsNotFoundPage = lazy(() => import('./components/pages/UsageDocsNotFoundPage'));
const IntentLandingPage = lazy(() => import('./components/pages/IntentLandingPage'));
const IntentHubPage = lazy(() => import('./components/pages/IntentHubPage'));
const BlogIndexPage = lazy(() => import('./components/pages/BlogIndexPage'));
const BlogPostPage = lazy(() => import('./components/pages/BlogPostPage'));

type AppRoute =
  | { kind: 'app' }
  | { kind: 'legal'; legalKind: LegalPageKind }
  | { kind: 'intent'; intentKey: IntentPageKey }
  | { kind: 'intent-hub'; hubKey: 'workflows' | 'industries' }
  | { kind: 'account-action' }
  | { kind: 'usage-docs'; pageKey: UsageDocsPageKey }
  | { kind: 'usage-docs-not-found'; requestedPath: string }
  | { kind: 'blog-index' }
  | { kind: 'blog-post'; slug: string }
  | { kind: 'not-found'; requestedPath: string };

const replaceBrowserPath = (targetPath: string): void => {
  if (typeof window === 'undefined') return;
  if (window.location.pathname === targetPath) return;
  window.history.replaceState({}, '', `${targetPath}${window.location.search}${window.location.hash}`);
};

const resolveRoute = (): AppRoute => {
  if (typeof window === 'undefined') return { kind: 'app' };
  const path = window.location.pathname || '/';
  const normalizedPath = path.replace(/\/+$/, '') || '/';

  if (normalizedPath === '/privacy' || normalizedPath === '/privacy-policy') {
    return { kind: 'legal', legalKind: 'privacy' };
  }
  if (normalizedPath === '/terms' || normalizedPath === '/terms-of-service') {
    return { kind: 'legal', legalKind: 'terms' };
  }
  if (normalizedPath === ACCOUNT_ACTION_ROUTE_PATH || normalizedPath === LEGACY_ACCOUNT_ACTION_ROUTE_PATH) {
    if (normalizedPath === LEGACY_ACCOUNT_ACTION_ROUTE_PATH || path !== ACCOUNT_ACTION_ROUTE_PATH) {
      replaceBrowserPath(ACCOUNT_ACTION_ROUTE_PATH);
    }
    return { kind: 'account-action' };
  }

  if (normalizedPath === '/blog') {
    if (path !== normalizedPath) replaceBrowserPath(normalizedPath);
    return { kind: 'blog-index' };
  }
  if (normalizedPath.startsWith('/blog/')) {
    const slug = normalizedPath.slice('/blog/'.length);
    if (slug && !slug.includes('/')) {
      if (path !== normalizedPath) replaceBrowserPath(normalizedPath);
      return { kind: 'blog-post', slug };
    }
  }

  if (normalizedPath === '/workflows' || normalizedPath === '/industries') {
    if (path !== normalizedPath) replaceBrowserPath(normalizedPath);
    return {
      kind: 'intent-hub',
      hubKey: normalizedPath === '/workflows' ? 'workflows' : 'industries',
    };
  }

  const intentKey = resolveIntentPath(normalizedPath);
  if (intentKey) {
    if (path !== normalizedPath) replaceBrowserPath(normalizedPath);
    return { kind: 'intent', intentKey };
  }

  const usageDocsRoute = resolveUsageDocsPath(normalizedPath);
  if (usageDocsRoute) {
    if (usageDocsRoute.kind === 'redirect') {
      replaceBrowserPath(usageDocsRoute.targetPath);
      const canonicalRoute = resolveUsageDocsPath(usageDocsRoute.targetPath);
      if (canonicalRoute?.kind === 'canonical') {
        return {
          kind: 'usage-docs',
          pageKey: canonicalRoute.pageKey,
        };
      }
      return {
        kind: 'usage-docs-not-found',
        requestedPath: usageDocsRoute.targetPath,
      };
    }

    if (usageDocsRoute.kind === 'canonical') {
      if (path !== normalizedPath) replaceBrowserPath(normalizedPath);
      return {
        kind: 'usage-docs',
        pageKey: usageDocsRoute.pageKey,
      };
    }

    if (path !== normalizedPath) replaceBrowserPath(normalizedPath);
    return {
      kind: 'usage-docs-not-found',
      requestedPath: usageDocsRoute.requestedPath,
    };
  }

  if (normalizedPath === '/') return { kind: 'app' };

  return { kind: 'not-found', requestedPath: normalizedPath };
};

const route = resolveRoute();

// Best-effort warmup to reduce Cloud Run cold-start latency during signup reCAPTCHA assessment.
// Run only on app/editor routes so docs/legal visits avoid unnecessary startup network work.
if (typeof window !== 'undefined' && route.kind === 'app') {
  fetch('/api/health', { method: 'GET', mode: 'cors' }).catch(() => {});
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Suspense fallback={null}>
      {route.kind === 'legal' ? (
        <LegalPage kind={route.legalKind} />
      ) : route.kind === 'account-action' ? (
        <AccountActionPage />
      ) : route.kind === 'intent-hub' ? (
        <IntentHubPage hubKey={route.hubKey} />
      ) : route.kind === 'intent' ? (
        <IntentLandingPage pageKey={route.intentKey} />
      ) : route.kind === 'usage-docs' ? (
        <UsageDocsPage pageKey={route.pageKey} />
      ) : route.kind === 'usage-docs-not-found' ? (
        <UsageDocsNotFoundPage requestedPath={route.requestedPath} />
      ) : route.kind === 'blog-index' ? (
        <BlogIndexPage />
      ) : route.kind === 'blog-post' ? (
        <BlogPostPage slug={route.slug} />
      ) : route.kind === 'not-found' ? (
        <PublicNotFoundPage requestedPath={route.requestedPath} />
      ) : (
        <App />
      )}
    </Suspense>
  </StrictMode>,
);
