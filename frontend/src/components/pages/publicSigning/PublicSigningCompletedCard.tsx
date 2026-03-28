import { Alert } from '../../ui/Alert';
import type { PublicSigningFlowState } from './usePublicSigningFlow';

type PublicSigningCompletedCardProps = {
  flow: PublicSigningFlowState;
};

export function PublicSigningCompletedCard({ flow }: PublicSigningCompletedCardProps) {
  if (!flow.request || flow.request.status !== 'completed') {
    return null;
  }

  const digitalSignature = flow.request.artifacts?.signedPdf?.digitalSignature;

  return (
    <div className="public-signing-page__card">
      <Alert
        tone="success"
        variant="inline"
        message={`This signing request was completed${flow.request.completedAt ? ` on ${new Date(flow.request.completedAt).toLocaleString()}` : ''}.`}
      />
      {flow.verificationRequired && !flow.verificationComplete ? (
        <Alert
          tone="info"
          variant="inline"
          message="Verify your email to open the immutable source PDF or download the completed signing artifacts."
        />
      ) : null}
      {digitalSignature?.available ? (
        <div className="public-signing-page__signature-helper">
          <strong>Embedded PDF signature:</strong>{' '}
          The signed PDF includes a cryptographic PDF signature
          {digitalSignature.method ? ` via ${digitalSignature.method}` : ''}.
          {digitalSignature.certificateSubject ? ` Certificate subject: ${digitalSignature.certificateSubject}.` : ''}
        </div>
      ) : null}
      {flow.verificationComplete ? (
        <div className="public-signing-page__button-group">
          {flow.request.artifacts?.signedPdf?.available ? (
            <button
              className="ui-button ui-button--primary"
              type="button"
              disabled={flow.artifactBusyKey !== null || !flow.sessionToken}
              onClick={flow.handleDownloadSignedPdf}
            >
              {flow.artifactBusyKey === 'signedPdf' ? 'Downloading signed PDF…' : 'Download signed PDF'}
            </button>
          ) : null}
          {flow.request.artifacts?.auditReceipt?.available ? (
            <button
              className="ui-button ui-button--ghost"
              type="button"
              disabled={flow.artifactBusyKey !== null || !flow.sessionToken}
              onClick={flow.handleDownloadAuditReceipt}
            >
              {flow.artifactBusyKey === 'auditReceipt' ? 'Downloading audit receipt…' : 'Download audit receipt'}
            </button>
          ) : null}
          {flow.request.validationPath ? (
            <a className="ui-button ui-button--ghost" href={flow.request.validationPath}>
              Validate retained record
            </a>
          ) : null}
          <button
            className="ui-button ui-button--ghost"
            type="button"
            disabled={flow.artifactBusyKey !== null || !flow.documentObjectUrl || flow.documentLoading}
            onClick={() => flow.handleOpenDocument('The immutable source PDF is not available yet.')}
          >
            {flow.documentLoading ? 'Loading source PDF…' : 'Open original immutable source'}
          </button>
        </div>
      ) : null}
      {flow.documentError ? <Alert tone="error" variant="inline" message={flow.documentError} /> : null}
    </div>
  );
}
