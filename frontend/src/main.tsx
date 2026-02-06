/** React entrypoint that mounts the application shell. */
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './index.css';
import App from './App';
import LegalPage, { type LegalPageKind } from './components/pages/LegalPage';

// Best-effort warmup to reduce Cloud Run cold-start latency during signup reCAPTCHA assessment.
// This is intentionally fire-and-forget; failures are ignored and the real API call will surface errors.
if (typeof window !== 'undefined') {
  fetch('/api/health', { method: 'GET', mode: 'cors' }).catch(() => {});
}

const resolveLegalKind = (): LegalPageKind | null => {
  if (typeof window === 'undefined') return null;
  const path = window.location.pathname || '/';
  const normalizedPath = path.replace(/\/+$/, '') || '/';
  if (normalizedPath === '/privacy' || normalizedPath === '/privacy-policy') return 'privacy';
  if (normalizedPath === '/terms' || normalizedPath === '/terms-of-service') return 'terms';
  return null;
};

const legalKind = resolveLegalKind();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {legalKind ? <LegalPage kind={legalKind} /> : <App />}
  </StrictMode>,
);
