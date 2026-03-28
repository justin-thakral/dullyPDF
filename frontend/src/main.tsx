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
import { resolveFeaturePlanPath, type FeaturePlanPageKey } from './config/featurePlanPages';
import { initializeGoogleAds } from './utils/googleAds';
import {
  parseWorkspaceBrowserRoute,
  type WorkspaceBrowserRoute,
} from './utils/workspaceRoutes';

const App = lazy(() => import('./App'));
const LegalPage = lazy(() => import('./components/pages/LegalPage'));
const PublicNotFoundPage = lazy(() => import('./components/pages/PublicNotFoundPage'));
const FillLinkPublicPage = lazy(() => import('./components/pages/FillLinkPublicPage'));
const PublicSigningPage = lazy(() => import('./components/pages/PublicSigningPage'));
const PublicSigningValidationPage = lazy(() => import('./components/pages/PublicSigningValidationPage'));
const AccountActionPage = lazy(() => import('./components/pages/AccountActionPage'));
const UsageDocsPage = lazy(() => import('./components/pages/UsageDocsPage'));
const UsageDocsNotFoundPage = lazy(() => import('./components/pages/UsageDocsNotFoundPage'));
const IntentLandingPage = lazy(() => import('./components/pages/IntentLandingPage'));
const IntentHubPage = lazy(() => import('./components/pages/IntentHubPage'));
const FeaturePlanPage = lazy(() => import('./components/pages/FeaturePlanPage'));
const BlogIndexPage = lazy(() => import('./components/pages/BlogIndexPage'));
const BlogPostPage = lazy(() => import('./components/pages/BlogPostPage'));

type AppRoute =
  | { kind: 'app'; browserRoute: WorkspaceBrowserRoute }
  | { kind: 'legal'; legalKind: LegalPageKind }
  | { kind: 'fill-link-public'; token: string }
  | { kind: 'signing-public'; token: string }
  | { kind: 'signing-validation'; token: string }
  | { kind: 'intent'; intentKey: IntentPageKey }
  | { kind: 'intent-hub'; hubKey: 'workflows' | 'industries' }
  | { kind: 'feature-plan'; planKey: FeaturePlanPageKey }
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
  if (typeof window === 'undefined') {
    return {
      kind: 'app',
      browserRoute: { kind: 'homepage' },
    };
  }
  const path = window.location.pathname || '/';
  const normalizedPath = path.replace(/\/+$/, '') || '/';
  const workspaceBrowserRoute = parseWorkspaceBrowserRoute(path, window.location.search);
  if (workspaceBrowserRoute) {
    return {
      kind: 'app',
      browserRoute: workspaceBrowserRoute,
    };
  }

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

  if (normalizedPath.startsWith('/respond/')) {
    const token = normalizedPath.slice('/respond/'.length);
    if (token && !token.includes('/')) {
      if (path !== normalizedPath) replaceBrowserPath(normalizedPath);
      return { kind: 'fill-link-public', token };
    }
  }
  if (normalizedPath.startsWith('/sign/')) {
    const token = normalizedPath.slice('/sign/'.length);
    if (token && !token.includes('/')) {
      if (path !== normalizedPath) replaceBrowserPath(normalizedPath);
      return { kind: 'signing-public', token };
    }
  }
  if (normalizedPath.startsWith('/verify-signing/')) {
    const token = normalizedPath.slice('/verify-signing/'.length);
    if (token && !token.includes('/')) {
      if (path !== normalizedPath) replaceBrowserPath(normalizedPath);
      return { kind: 'signing-validation', token };
    }
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

  const featurePlanKey = resolveFeaturePlanPath(normalizedPath);
  if (featurePlanKey) {
    if (path !== normalizedPath) replaceBrowserPath(normalizedPath);
    return { kind: 'feature-plan', planKey: featurePlanKey };
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
  return { kind: 'not-found', requestedPath: normalizedPath };
};

const renderRoute = (route: AppRoute) => {
  switch (route.kind) {
    case 'legal':
      return <LegalPage kind={route.legalKind} />;
    case 'fill-link-public':
      return <FillLinkPublicPage token={route.token} />;
    case 'signing-public':
      return <PublicSigningPage token={route.token} />;
    case 'signing-validation':
      return <PublicSigningValidationPage token={route.token} />;
    case 'account-action':
      return <AccountActionPage />;
    case 'intent-hub':
      return <IntentHubPage hubKey={route.hubKey} />;
    case 'feature-plan':
      return <FeaturePlanPage pageKey={route.planKey} />;
    case 'intent':
      return <IntentLandingPage pageKey={route.intentKey} />;
    case 'usage-docs':
      return <UsageDocsPage pageKey={route.pageKey} />;
    case 'usage-docs-not-found':
      return <UsageDocsNotFoundPage requestedPath={route.requestedPath} />;
    case 'blog-index':
      return <BlogIndexPage />;
    case 'blog-post':
      return <BlogPostPage slug={route.slug} />;
    case 'not-found':
      return <PublicNotFoundPage requestedPath={route.requestedPath} />;
    case 'app':
      return <App initialBrowserRoute={route.browserRoute} />;
  }

  const exhaustiveCheck: never = route;
  return exhaustiveCheck;
};

const route = resolveRoute();

if (typeof window !== 'undefined' && route.kind === 'app') {
  initializeGoogleAds();
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Suspense fallback={null}>
      {renderRoute(route)}
    </Suspense>
  </StrictMode>,
);
