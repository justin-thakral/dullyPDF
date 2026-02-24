/** React entrypoint that mounts the application shell. */
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './index.css';
import App from './App';
import LegalPage, { type LegalPageKind } from './components/pages/LegalPage';
import UsageDocsPage from './components/pages/UsageDocsPage';
import {
  resolveUsageDocsPath,
  type UsageDocsPageKey,
} from './components/pages/usageDocsContent';

// Best-effort warmup to reduce Cloud Run cold-start latency during signup reCAPTCHA assessment.
// This is intentionally fire-and-forget; failures are ignored and the real API call will surface errors.
if (typeof window !== 'undefined') {
  fetch('/api/health', { method: 'GET', mode: 'cors' }).catch(() => {});
}

type AppRoute =
  | { kind: 'app' }
  | { kind: 'legal'; legalKind: LegalPageKind }
  | { kind: 'usage-docs'; pageKey: UsageDocsPageKey; unknownSlug: string | null };

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

  const usageDocsRoute = resolveUsageDocsPath(normalizedPath);
  if (usageDocsRoute) {
    return {
      kind: 'usage-docs',
      pageKey: usageDocsRoute.pageKey,
      unknownSlug: usageDocsRoute.unknownSlug,
    };
  }

  return { kind: 'app' };
};

const route = resolveRoute();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {route.kind === 'legal' ? (
      <LegalPage kind={route.legalKind} />
    ) : route.kind === 'usage-docs' ? (
      <UsageDocsPage pageKey={route.pageKey} unknownSlug={route.unknownSlug} />
    ) : (
      <App />
    )}
  </StrictMode>,
);
