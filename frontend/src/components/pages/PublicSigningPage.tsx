import { Alert } from '../ui/Alert';
import { PublicSigningCeremony } from './publicSigning/PublicSigningCeremony';
import { PublicSigningCompletedCard } from './publicSigning/PublicSigningCompletedCard';
import { PublicSigningFactsCard } from './publicSigning/PublicSigningFactsCard';
import {
  isActionableRequest,
  resolveInactiveRequestMessage,
} from './publicSigning/publicSigningHelpers';
import { usePublicSigningFlow } from './publicSigning/usePublicSigningFlow';
import '../../styles/ui-buttons.css';
import './PublicSigningPage.css';

type PublicSigningPageProps = {
  token: string;
};

export default function PublicSigningPage({ token }: PublicSigningPageProps) {
  const flow = usePublicSigningFlow(token);

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

        {flow.loading ? <p>Loading signing request…</p> : null}
        {flow.error ? <Alert tone="error" variant="inline" message={flow.error} /> : null}

        {flow.request ? (
          <>
            <PublicSigningFactsCard request={flow.request} facts={flow.facts} />

            <PublicSigningCompletedCard flow={flow} />

            {flow.request.status === 'completed' && flow.actionError ? (
              <Alert tone="error" variant="inline" message={flow.actionError} />
            ) : null}
            {flow.request.status === 'completed' && flow.missingSession ? (
              <Alert tone="warning" variant="inline" message={flow.sessionErrorMessage} />
            ) : null}

            {flow.request.status !== 'completed' && !isActionableRequest(flow.request) ? (
              <div className="public-signing-page__card">
                <Alert
                  tone={flow.request.status === 'draft' ? 'info' : 'warning'}
                  variant="inline"
                  message={resolveInactiveRequestMessage(flow.request)}
                />
              </div>
            ) : null}

            <PublicSigningCeremony flow={flow} />
          </>
        ) : null}
      </section>
    </main>
  );
}
