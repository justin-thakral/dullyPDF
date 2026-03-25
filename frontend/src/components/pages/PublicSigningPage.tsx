import { useEffect, useMemo, useRef, useState } from 'react';
import { ApiService, type PublicSigningRequest } from '../../services/api';
import { Alert } from '../ui/Alert';
import '../../styles/ui-buttons.css';
import './PublicSigningPage.css';

type PublicSigningPageProps = {
  token: string;
};

type SigningStepKey = 'consent' | 'review' | 'adopt' | 'complete';

const BUSINESS_STEPS: SigningStepKey[] = ['review', 'adopt', 'complete'];
const CONSUMER_STEPS: SigningStepKey[] = ['consent', 'review', 'adopt', 'complete'];

const CONSUMER_DISCLOSURES = [
  'You can request paper or manual handling instead of signing electronically.',
  'You can withdraw electronic consent before completing this signing request by stopping here and contacting the sender.',
  'This consent applies only to this signing request.',
  'You need a device that can open PDFs and an internet browser that can display this page.',
];

function resolveCurrentStep(request: PublicSigningRequest | null): SigningStepKey {
  if (!request) {
    return 'review';
  }
  if (request.signatureMode === 'consumer' && !request.consentedAt) {
    return 'consent';
  }
  if (!request.reviewedAt) {
    return 'review';
  }
  if (!request.signatureAdoptedAt) {
    return 'adopt';
  }
  return 'complete';
}

function isActionableStatus(status: string): boolean {
  return status === 'sent';
}

function hasManualFallbackLock(request: PublicSigningRequest | null): boolean {
  return Boolean(request?.manualFallbackRequestedAt);
}

function canBootstrapSession(request: PublicSigningRequest | null): boolean {
  return Boolean(request && isActionableStatus(request.status) && !hasManualFallbackLock(request));
}

function resolveInactiveRequestMessage(request: PublicSigningRequest): string {
  if (request.status === 'draft') {
    return 'This signing request has been prepared but not sent yet. Ask the sender to finish Review and Send before using this link.';
  }
  if (request.status === 'invalidated') {
    return 'This signing request is no longer valid. Contact the sender for a fresh signing link or a paper/manual alternative.';
  }
  return 'This request cannot be signed right now. Contact the sender for a fresh signing link or a paper/manual alternative.';
}

export default function PublicSigningPage({ token }: PublicSigningPageProps) {
  const [request, setRequest] = useState<PublicSigningRequest | null>(null);
  const [sessionToken, setSessionToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionBusy, setActionBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [adoptedName, setAdoptedName] = useState('');
  const [intentConfirmed, setIntentConfirmed] = useState(false);
  const loadRequestRef = useRef<{
    token: string | null;
    promise: Promise<{
      request: PublicSigningRequest | null;
      sessionToken: string | null;
      error: string | null;
    }> | null;
  }>({
    token: null,
    promise: null,
  });

  useEffect(() => {
    let mounted = true;

    setLoading(true);
    setError(null);
    setActionError(null);
    setSessionToken(null);
    setIntentConfirmed(false);
    setAdoptedName('');

    if (loadRequestRef.current.token !== token || !loadRequestRef.current.promise) {
      loadRequestRef.current = {
        token,
        promise: (async () => {
          try {
            const nextRequest = await ApiService.getPublicSigningRequest(token);
            if (canBootstrapSession(nextRequest)) {
              const bootstrap = await ApiService.startPublicSigningSession(token);
              return {
                request: bootstrap.request,
                sessionToken: bootstrap.session?.token || null,
                error: null,
              };
            }
            return {
              request: nextRequest,
              sessionToken: null,
              error: null,
            };
          } catch (nextError) {
            return {
              request: null,
              sessionToken: null,
              error: nextError instanceof Error ? nextError.message : 'Unable to load this signing request.',
            };
          }
        })(),
      };
    }

    const activeLoadPromise = loadRequestRef.current.promise;
    if (!activeLoadPromise) {
      setLoading(false);
      return () => {
        mounted = false;
      };
    }

    void activeLoadPromise.then((result) => {
      if (!mounted) return;
      setRequest(result.request);
      setSessionToken(result.sessionToken);
      setError(result.error);
      setAdoptedName(result.request?.signatureAdoptedName || result.request?.signerName || '');
      setLoading(false);
    });
    return () => {
      mounted = false;
    };
  }, [token]);

  const currentStep = resolveCurrentStep(request);
  const steps = useMemo(
    () => (request?.signatureMode === 'consumer' ? CONSUMER_STEPS : BUSINESS_STEPS),
    [request?.signatureMode],
  );
  const manualFallbackLocked = hasManualFallbackLock(request);

  async function runSignerAction(action: () => Promise<PublicSigningRequest>) {
    setActionBusy(true);
    setActionError(null);
    try {
      const nextRequest = await action();
      setRequest(nextRequest);
    } catch (nextError) {
      setActionError(nextError instanceof Error ? nextError.message : 'Unable to continue this signing request.');
    } finally {
      setActionBusy(false);
    }
  }

  const requiresSession = Boolean(request && isActionableStatus(request.status) && !manualFallbackLocked);
  const missingSession = requiresSession && !sessionToken;
  const sessionErrorMessage = 'Your signing session expired. Reload the page and try again.';
  const facts = request
    ? [
        {
          label: 'Document',
          value: request.sourceDocumentName,
          className: 'public-signing-page__fact public-signing-page__fact--wide',
        },
        {
          label: 'Status',
          value: request.status,
          className: 'public-signing-page__fact',
        },
        {
          label: 'Source version',
          value: request.sourceVersion || 'Pending',
          className: 'public-signing-page__fact public-signing-page__fact--wide public-signing-page__fact--code',
        },
        {
          label: 'Category',
          value: request.documentCategoryLabel,
          className: 'public-signing-page__fact',
        },
        {
          label: 'Signature mode',
          value: request.signatureMode,
          className: 'public-signing-page__fact',
        },
        {
          label: 'Signer',
          value: request.signerName,
          className: 'public-signing-page__fact',
        },
        {
          label: 'Manual fallback',
          value: request.manualFallbackEnabled ? 'Available' : 'Disabled',
          className: 'public-signing-page__fact',
        },
        {
          label: 'Anchors',
          value: String(request.anchors.length),
          className: 'public-signing-page__fact',
        },
        {
          label: 'SHA-256',
          value: request.sourcePdfSha256 || 'Pending',
          className: 'public-signing-page__fact public-signing-page__fact--full public-signing-page__fact--code',
        },
      ]
    : [];

  return (
    <main className="public-signing-page">
      <section className="public-signing-page__shell">
        <header className="public-signing-page__hero">
          <p className="public-signing-page__eyebrow">DullyPDF Signature Request</p>
          <h1>Review and sign</h1>
          <p className="public-signing-page__lead">
            DullyPDF freezes the document before signature collection. Review the exact record, adopt your signature, then finish with an explicit sign action.
          </p>
        </header>

        {loading ? <p>Loading signing request…</p> : null}
        {error ? <Alert tone="error" variant="inline" message={error} /> : null}

        {request ? (
          <>
            <div className="public-signing-page__card">
              <dl className="public-signing-page__facts">
                {facts.map((fact) => (
                  <div key={fact.label} className={fact.className}>
                    <dt>{fact.label}</dt>
                    <dd className={fact.label === 'SHA-256' ? 'public-signing-page__hash' : undefined}>{fact.value}</dd>
                  </div>
                ))}
              </dl>
              <Alert tone="info" variant="inline" message={request.statusMessage} />
            </div>

            {request.status === 'completed' ? (
              <div className="public-signing-page__card">
                <Alert
                  tone="success"
                  variant="inline"
                  message={`This signing request was completed${request.completedAt ? ` on ${new Date(request.completedAt).toLocaleString()}` : ''}.`}
                />
                <div className="public-signing-page__button-group">
                  {request.artifacts?.signedPdf?.downloadPath ? (
                    <a
                      className="ui-button ui-button--primary"
                      href={request.artifacts.signedPdf.downloadPath}
                    >
                      Download signed PDF
                    </a>
                  ) : null}
                  {request.artifacts?.auditReceipt?.downloadPath ? (
                    <a
                      className="ui-button ui-button--ghost"
                      href={request.artifacts.auditReceipt.downloadPath}
                    >
                      Download audit receipt
                    </a>
                  ) : null}
                  <a
                    className="ui-button ui-button--ghost"
                    href={request.documentPath}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Open original immutable source
                  </a>
                </div>
              </div>
            ) : null}

            {request.status !== 'completed' && request.status !== 'sent' ? (
              <div className="public-signing-page__card">
                <Alert
                  tone={request.status === 'draft' ? 'info' : 'warning'}
                  variant="inline"
                  message={resolveInactiveRequestMessage(request)}
                />
              </div>
            ) : null}

            {request.status === 'sent' ? (
              <>
                <div className="public-signing-page__card public-signing-page__progress-card">
                  {!manualFallbackLocked ? (
                    <ol className="public-signing-page__steps" aria-label="Signing progress">
                      {steps.map((step, index) => {
                        const active = step === currentStep;
                        const completed = steps.indexOf(currentStep) > index || request.status === 'completed';
                        return (
                          <li
                            key={step}
                            className={[
                              'public-signing-page__step',
                              active ? 'public-signing-page__step--active' : '',
                              completed ? 'public-signing-page__step--complete' : '',
                            ].filter(Boolean).join(' ')}
                          >
                            <span>{index + 1}</span>
                            <strong>{step === 'consent' ? 'E-Consent' : step === 'review' ? 'Review' : step === 'adopt' ? 'Adopt Signature' : 'Finish Signing'}</strong>
                          </li>
                        );
                      })}
                    </ol>
                  ) : (
                    <Alert
                      tone="success"
                      variant="inline"
                      message="A paper/manual fallback request was recorded for this signer. Electronic signing is now paused until the sender follows up."
                    />
                  )}

                  <div className="public-signing-page__button-group public-signing-page__button-group--secondary">
                    {request.manualFallbackEnabled ? (
                      request.manualFallbackRequestedAt ? null : (
                        <button
                          className="ui-button ui-button--ghost"
                          type="button"
                          disabled={actionBusy || missingSession}
                          onClick={() => {
                            if (!sessionToken) {
                              setActionError(sessionErrorMessage);
                              return;
                            }
                            void runSignerAction(() => ApiService.requestPublicSigningManualFallback(token, sessionToken));
                          }}
                        >
                          Request paper/manual fallback
                        </button>
                      )
                    ) : null}

                    <a
                      className="ui-button ui-button--ghost"
                      href={request.documentPath}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Open document in new tab
                    </a>
                  </div>
                </div>

                {actionError ? <Alert tone="error" variant="inline" message={actionError} /> : null}
                {missingSession ? <Alert tone="warning" variant="inline" message={sessionErrorMessage} /> : null}

                {!manualFallbackLocked && currentStep === 'consent' ? (
                  <div className="public-signing-page__card">
                    <h2>Consent to electronic records</h2>
                    <p className="public-signing-page__support">
                      Consumer signing requests require a separate electronic-records consent before DullyPDF continues to the document review.
                    </p>
                    <ul className="public-signing-page__list">
                      {CONSUMER_DISCLOSURES.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                    <button
                      className="ui-button ui-button--primary"
                      type="button"
                      disabled={actionBusy || missingSession}
                      onClick={() => {
                        if (!sessionToken) {
                          setActionError(sessionErrorMessage);
                          return;
                        }
                        void runSignerAction(() => ApiService.consentPublicSigningRequest(token, sessionToken));
                      }}
                    >
                      {actionBusy ? 'Saving consent…' : 'I consent to electronic records'}
                    </button>
                  </div>
                ) : null}

                {!manualFallbackLocked && currentStep === 'review' ? (
                  <div className="public-signing-page__card">
                    <h2>Review the exact record</h2>
                    <p className="public-signing-page__support">
                      Review the immutable PDF below. Your signature will be tied to this exact source hash and version.
                    </p>
                    <div className="public-signing-page__document-frame">
                      <iframe title="Signing document preview" src={request.documentPath} />
                    </div>
                    <button
                      className="ui-button ui-button--primary"
                      type="button"
                      disabled={actionBusy || missingSession}
                      onClick={() => {
                        if (!sessionToken) {
                          setActionError(sessionErrorMessage);
                          return;
                        }
                        void runSignerAction(() => ApiService.reviewPublicSigningRequest(token, sessionToken));
                      }}
                    >
                      {actionBusy ? 'Recording review…' : 'I reviewed this document'}
                    </button>
                  </div>
                ) : null}

                {!manualFallbackLocked && currentStep === 'adopt' ? (
                  <div className="public-signing-page__card">
                    <h2>Adopt your signature</h2>
                    <p className="public-signing-page__support">
                      Type the name you want to adopt as your electronic signature for this request.
                    </p>
                    <label className="public-signing-page__field">
                      <span>Adopted signature name</span>
                      <input
                        value={adoptedName}
                        onChange={(event) => setAdoptedName(event.target.value)}
                        placeholder={request.signerName}
                        autoComplete="name"
                      />
                    </label>
                    <div className="public-signing-page__signature-preview" aria-live="polite">
                      <span>Signature preview</span>
                      <strong>{adoptedName || request.signerName}</strong>
                    </div>
                    <button
                      className="ui-button ui-button--primary"
                      type="button"
                      disabled={actionBusy || missingSession || !adoptedName.trim()}
                      onClick={() => {
                        if (!sessionToken) {
                          setActionError(sessionErrorMessage);
                          return;
                        }
                        void runSignerAction(() => ApiService.adoptPublicSigningSignature(token, sessionToken, adoptedName));
                      }}
                    >
                      {actionBusy ? 'Saving signature…' : 'Adopt this signature'}
                    </button>
                  </div>
                ) : null}

                {!manualFallbackLocked && currentStep === 'complete' ? (
                  <div className="public-signing-page__card">
                    <h2>Finish signing</h2>
                    <p className="public-signing-page__support">
                      This is the final signing action. DullyPDF records the timestamp, secure signing session, device information, and document hash for this request.
                    </p>
                    <label className="public-signing-page__checkbox">
                      <input
                        type="checkbox"
                        checked={intentConfirmed}
                        onChange={(event) => setIntentConfirmed(event.target.checked)}
                      />
                      <span>I adopt this signature and sign this exact record electronically.</span>
                    </label>
                    <button
                      className="ui-button ui-button--primary"
                      type="button"
                      disabled={actionBusy || missingSession || !intentConfirmed}
                      onClick={() => {
                        if (!sessionToken) {
                          setActionError(sessionErrorMessage);
                          return;
                        }
                        void runSignerAction(() => ApiService.completePublicSigningRequest(token, sessionToken));
                      }}
                    >
                      {actionBusy ? 'Finishing signing…' : 'Finish Signing'}
                    </button>
                  </div>
                ) : null}
              </>
            ) : null}
          </>
        ) : null}
      </section>
    </main>
  );
}
