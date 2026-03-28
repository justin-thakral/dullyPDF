import { useEffect, useState } from 'react';
import { Alert } from '../ui/Alert';
import { ApiService, type PublicSigningValidation } from '../../services/api';
import '../../styles/ui-buttons.css';
import './PublicSigningValidationPage.css';

type PublicSigningValidationPageProps = {
  token: string;
};

function formatDateTime(value?: string | null): string {
  if (!value) return 'Not recorded';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function resolveStatusTone(validation: PublicSigningValidation): 'success' | 'warning' | 'error' {
  if (validation.valid) return 'success';
  if (validation.available) return 'error';
  return 'warning';
}

export default function PublicSigningValidationPage({ token }: PublicSigningValidationPageProps) {
  const [validation, setValidation] = useState<PublicSigningValidation | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    setValidation(null);
    void ApiService.getPublicSigningValidation(token)
      .then((payload) => {
        if (!active) return;
        setValidation(payload);
        setLoading(false);
      })
      .catch((nextError) => {
        if (!active) return;
        setError(nextError instanceof Error ? nextError.message : 'Unable to validate this signing record.');
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [token]);

  return (
    <main className="public-signing-validation-page">
      <section className="public-signing-validation-page__shell">
        <header className="public-signing-validation-page__hero">
          <p className="public-signing-validation-page__eyebrow">DullyPDF Signing Validation</p>
          <h1>Validate a completed signing record</h1>
          <p className="public-signing-validation-page__lead">
            This page checks DullyPDF’s retained audit evidence for one completed signing request and reports whether the stored hashes and signed audit envelope still line up.
          </p>
        </header>

        {loading ? <p>Loading validation record…</p> : null}
        {error ? <Alert tone="error" variant="inline" message={error} /> : null}

        {validation ? (
          <>
            <div className="public-signing-validation-page__card">
              <Alert tone={resolveStatusTone(validation)} variant="inline" message={validation.statusMessage} />
              <dl className="public-signing-validation-page__facts">
                <div>
                  <dt>Document</dt>
                  <dd>{validation.sourceDocumentName}</dd>
                </div>
                <div>
                  <dt>Category</dt>
                  <dd>{validation.documentCategoryLabel}</dd>
                </div>
                <div>
                  <dt>Completed</dt>
                  <dd>{formatDateTime(validation.completedAt)}</dd>
                </div>
                <div>
                  <dt>Validated</dt>
                  <dd>{formatDateTime(validation.validatedAt)}</dd>
                </div>
                <div>
                  <dt>Sender</dt>
                  <dd>{validation.sender?.displayName || validation.sender?.contactEmail || 'Not recorded'}</dd>
                </div>
                <div>
                  <dt>Signer</dt>
                  <dd>{validation.signer?.adoptedName || validation.signer?.name || 'Not recorded'}</dd>
                </div>
                <div className="public-signing-validation-page__fact--wide">
                  <dt>Validation URL</dt>
                  <dd className="public-signing-validation-page__code">{validation.validationUrl}</dd>
                </div>
                <div className="public-signing-validation-page__fact--wide">
                  <dt>Source PDF SHA-256</dt>
                  <dd className="public-signing-validation-page__code">{validation.sourcePdfSha256 || 'Not recorded'}</dd>
                </div>
                <div className="public-signing-validation-page__fact--wide">
                  <dt>Signed PDF SHA-256</dt>
                  <dd className="public-signing-validation-page__code">{validation.signedPdfSha256 || 'Not recorded'}</dd>
                </div>
                <div className="public-signing-validation-page__fact--wide">
                  <dt>Audit Manifest SHA-256</dt>
                  <dd className="public-signing-validation-page__code">{validation.auditManifestSha256 || 'Not recorded'}</dd>
                </div>
                <div className="public-signing-validation-page__fact--wide">
                  <dt>Audit Receipt SHA-256</dt>
                  <dd className="public-signing-validation-page__code">{validation.auditReceiptSha256 || 'Not recorded'}</dd>
                </div>
              </dl>
            </div>

            <div className="public-signing-validation-page__card">
              <h2>Validation checks</h2>
              <ul className="public-signing-validation-page__checks">
                {validation.checks.map((check) => (
                  <li key={check.key} className={check.passed ? 'is-passed' : 'is-failed'}>
                    <strong>{check.passed ? 'Pass' : 'Fail'}</strong> {check.label}
                  </li>
                ))}
              </ul>
              <p className="public-signing-validation-page__support">
                Event count in retained audit trail: {validation.eventCount ?? 'Not recorded'}
              </p>
              {validation.signature ? (
                <p className="public-signing-validation-page__support">
                  Audit signature: {validation.signature.method || 'Unknown method'} / {validation.signature.algorithm || 'Unknown algorithm'}
                </p>
              ) : null}
            </div>
          </>
        ) : null}
      </section>
    </main>
  );
}
