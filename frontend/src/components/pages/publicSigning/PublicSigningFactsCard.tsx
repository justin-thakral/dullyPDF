import { Alert } from '../../ui/Alert';
import type { PublicSigningRequest } from '../../../services/api';
import type { PublicSigningFact } from './publicSigningHelpers';

type PublicSigningFactsCardProps = {
  request: PublicSigningRequest;
  facts: PublicSigningFact[];
};

export function PublicSigningFactsCard({ request, facts }: PublicSigningFactsCardProps) {
  return (
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
  );
}
