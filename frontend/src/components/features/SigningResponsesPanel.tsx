import { useMemo, useState } from 'react';
import { ApiService, type SigningRequestSummary } from '../../services/api';
import '../../styles/ui-buttons.css';

type SigningResponsesPanelProps = {
  requests: SigningRequestSummary[];
  loading?: boolean;
  sourceDocumentName?: string | null;
  sourceTemplateId?: string | null;
  revokingRequestId?: string | null;
  reissuingRequestId?: string | null;
  onRevoke?: (requestId: string) => Promise<void> | void;
  onReissue?: (requestId: string) => Promise<void> | void;
  onRefresh?: () => Promise<void> | void;
};

function resolveLifecycleLabel(request: SigningRequestSummary): string {
  if (request.status === 'completed') return 'Signed';
  if (request.status === 'invalidated' && request.publicLinkRevokedAt) return 'Revoked';
  if (request.status === 'sent' && request.isExpired) return 'Expired';
  if (request.status === 'sent' && (request.publicLinkVersion || 1) > 1) return 'Reissued';
  if (request.status === 'sent') return 'Active';
  if (request.status === 'invalidated') return 'Invalidated';
  return 'Draft';
}

function resolveInviteLabel(request: SigningRequestSummary): string {
  const isReplacementLink = (request.publicLinkVersion || 1) > 1;
  if (request.status === 'invalidated' && request.publicLinkRevokedAt) return 'Link revoked';
  if (request.status === 'sent' && request.isExpired) return 'Link expired';
  if (request.inviteMethod === 'manual_link' || request.manualLinkSharedAt) return 'Manual link shared';
  if (request.inviteDeliveryStatus === 'sent') return isReplacementLink ? 'Replacement emailed' : 'Invite emailed';
  if (request.inviteDeliveryStatus === 'failed') return isReplacementLink ? 'Replacement failed' : 'Invite failed';
  if (request.inviteDeliveryStatus === 'skipped') return 'Email unavailable';
  if (request.status === 'sent') return isReplacementLink ? 'Replacement pending' : 'Invite pending';
  return 'Not sent';
}

function resolveInviteMethodSummary(request: SigningRequestSummary): string {
  if (request.inviteMethod === 'manual_link' || request.manualLinkSharedAt) {
    return request.manualLinkSharedAt ? `Manual link shared ${formatTimestamp(request.manualLinkSharedAt)}` : 'Manual link shared';
  }
  if (request.inviteDeliveryStatus === 'sent') {
    return request.inviteProvider === 'gmail_api' ? 'Email invite via Gmail API' : 'Email invite';
  }
  if (request.inviteDeliveryStatus === 'failed') return 'Email invite failed';
  if (request.inviteDeliveryStatus === 'skipped') return 'Email delivery unavailable';
  if (request.status === 'sent') return 'Email invite pending';
  return 'Not sent';
}

function resolveSenderSummary(request: SigningRequestSummary): string {
  return request.senderEmail || 'Owner account';
}

function canCopySignerLink(request: SigningRequestSummary): boolean {
  return Boolean(request.publicPath) && (request.status === 'completed' || (request.status === 'sent' && !request.isExpired));
}

function canRevokeRequest(request: SigningRequestSummary): boolean {
  return request.status === 'draft' || request.status === 'sent';
}

function canReissueRequest(request: SigningRequestSummary): boolean {
  const hasImmutableSource = Boolean(request.artifacts?.sourcePdf?.available);
  if (!hasImmutableSource) return false;
  if (request.status === 'sent') return true;
  return request.status === 'invalidated' && Boolean(request.publicLinkRevokedAt);
}

function formatTimestamp(value?: string | null): string {
  const raw = String(value || '').trim();
  if (!raw) return '—';
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) return raw;
  return parsed.toLocaleString();
}

function buildRequestScopeMatches(
  request: SigningRequestSummary,
  options: {
    sourceDocumentName: string | null | undefined;
    sourceTemplateId: string | null | undefined;
  },
): boolean {
  const { sourceDocumentName, sourceTemplateId } = options;
  if (sourceTemplateId && request.sourceTemplateId) {
    return request.sourceTemplateId === sourceTemplateId;
  }
  if (sourceDocumentName) {
    return request.sourceDocumentName === sourceDocumentName;
  }
  return true;
}

export function SigningResponsesPanel({
  requests,
  loading = false,
  sourceDocumentName = null,
  sourceTemplateId = null,
  revokingRequestId = null,
  reissuingRequestId = null,
  onRevoke,
  onReissue,
  onRefresh,
}: SigningResponsesPanelProps) {
  const [copiedRequestId, setCopiedRequestId] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [downloadingPath, setDownloadingPath] = useState<string | null>(null);
  const scopedRequests = useMemo(
    () => requests.filter((entry) => buildRequestScopeMatches(entry, { sourceDocumentName, sourceTemplateId })),
    [requests, sourceDocumentName, sourceTemplateId],
  );
  const totals = useMemo(() => ({
    waiting: scopedRequests.filter((entry) => entry.status === 'sent' && !entry.isExpired).length,
    signed: scopedRequests.filter((entry) => entry.status === 'completed').length,
    drafts: scopedRequests.filter((entry) => entry.status === 'draft').length,
    expired: scopedRequests.filter((entry) => entry.status === 'sent' && entry.isExpired).length,
    needsManual: scopedRequests.filter((entry) => (
      entry.inviteDeliveryStatus === 'failed'
      || entry.inviteDeliveryStatus === 'skipped'
      || entry.inviteMethod === 'manual_link'
      || Boolean(entry.manualLinkSharedAt)
    )).length,
  }), [scopedRequests]);

  async function handleCopyLink(request: SigningRequestSummary) {
    if (!request.publicPath) return;
    const signingUrl = `${window.location.origin}${request.publicPath}`;
    await navigator.clipboard.writeText(signingUrl);
    try {
      await ApiService.recordSigningManualShare(request.id);
      await onRefresh?.();
    } catch {
      // Copying the signer link should still succeed even if audit recording is temporarily unavailable.
    }
    setCopiedRequestId(request.id);
    window.setTimeout(() => {
      setCopiedRequestId((current) => (current === request.id ? null : current));
    }, 2000);
  }

  async function handleArtifactDownload(downloadPath: string, fallbackFilename: string) {
    setDownloadError(null);
    setDownloadingPath(downloadPath);
    try {
      await ApiService.downloadAuthenticatedFile(downloadPath, { filename: fallbackFilename });
    } catch (error) {
      setDownloadError(error instanceof Error ? error.message : 'Failed to download file.');
    } finally {
      setDownloadingPath((current) => (current === downloadPath ? null : current));
    }
  }

  async function handleRevoke(request: SigningRequestSummary) {
    if (!onRevoke || !canRevokeRequest(request)) return;
    const confirmed = window.confirm(
      request.status === 'draft'
        ? 'Cancel this signing draft? The signer link will remain inactive.'
        : 'Revoke this signer link? The public signing URL will stop working immediately.',
    );
    if (!confirmed) return;
    await onRevoke(request.id);
  }

  async function handleReissue(request: SigningRequestSummary) {
    if (!onReissue || !canReissueRequest(request)) return;
    const confirmed = window.confirm(
      request.status === 'sent' && !request.isExpired
        ? 'Issue a replacement signer link? The current public signing URL will stop working immediately.'
        : 'Issue a fresh signer link and email it to the signer? Older public signing URLs will remain inactive.',
    );
    if (!confirmed) return;
    await onReissue(request.id);
  }

  return (
    <section className="signature-request-dialog__responses">
      <div className="signature-request-dialog__section signature-request-dialog__section--summary">
        <div className="signature-request-dialog__responses-header">
          <div>
            <h3>Responses</h3>
            <p className="signature-request-dialog__supporting-copy">
              Track every send for the active document, including waiting signers, completed signatures, and downloadable signed copies.
            </p>
          </div>
          <button
            type="button"
            className="ui-button ui-button--ghost"
            onClick={() => { void onRefresh?.(); }}
            disabled={loading}
          >
            {loading ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>
        <div className="signature-request-dialog__responses-stats">
          <div>
            <span className="signature-request-dialog__label">Waiting</span>
            <strong>{totals.waiting}</strong>
          </div>
          <div>
            <span className="signature-request-dialog__label">Signed</span>
            <strong>{totals.signed}</strong>
          </div>
          <div>
            <span className="signature-request-dialog__label">Drafts</span>
            <strong>{totals.drafts}</strong>
          </div>
          <div>
            <span className="signature-request-dialog__label">Expired</span>
            <strong>{totals.expired}</strong>
          </div>
          <div>
            <span className="signature-request-dialog__label">Manual follow-up</span>
            <strong>{totals.needsManual}</strong>
          </div>
        </div>
      </div>

      {loading && !scopedRequests.length ? (
        <div className="signature-request-dialog__section">
          <p className="signature-request-dialog__supporting-copy">Loading signing responses…</p>
        </div>
      ) : null}

      {downloadError ? (
        <div className="signature-request-dialog__section">
          <p className="signature-request-dialog__response-note">{downloadError}</p>
        </div>
      ) : null}

      {!loading && !scopedRequests.length ? (
        <div className="signature-request-dialog__section">
          <h3>No sends yet</h3>
          <p className="signature-request-dialog__supporting-copy">
            Once you create and send signing requests for this document, they will appear here with invite status and signed-form downloads.
          </p>
        </div>
      ) : null}

      {scopedRequests.map((request) => (
        <article key={request.id} className="signature-request-dialog__section signature-request-dialog__response-card">
          <div className="signature-request-dialog__response-header">
            <div className="signature-request-dialog__response-identity">
              <strong>{request.signerName}</strong>
              <span>{request.signerEmail}</span>
            </div>
            <div className="signature-request-dialog__response-badges">
              <span className="signature-request-dialog__response-badge">{resolveLifecycleLabel(request)}</span>
              <span className="signature-request-dialog__response-badge signature-request-dialog__response-badge--muted">
                {resolveInviteLabel(request)}
              </span>
            </div>
          </div>

          <div className="signature-request-dialog__response-grid">
            <div>
              <span className="signature-request-dialog__label">Document</span>
              <strong>{request.sourceDocumentName}</strong>
            </div>
            <div>
              <span className="signature-request-dialog__label">Category</span>
              <strong>{request.documentCategoryLabel}</strong>
            </div>
            <div>
              <span className="signature-request-dialog__label">Sent</span>
              <strong>{formatTimestamp(request.sentAt)}</strong>
            </div>
            <div>
              <span className="signature-request-dialog__label">Completed</span>
              <strong>{formatTimestamp(request.completedAt)}</strong>
            </div>
            <div>
              <span className="signature-request-dialog__label">Expires</span>
              <strong>{formatTimestamp(request.expiresAt)}</strong>
            </div>
            <div>
              <span className="signature-request-dialog__label">Invite attempt</span>
              <strong>{formatTimestamp(request.inviteLastAttemptAt)}</strong>
            </div>
            <div>
              <span className="signature-request-dialog__label">Delivery method</span>
              <strong>{resolveInviteMethodSummary(request)}</strong>
            </div>
            <div>
              <span className="signature-request-dialog__label">Sender</span>
              <strong>{resolveSenderSummary(request)}</strong>
            </div>
            <div>
              <span className="signature-request-dialog__label">Source version</span>
              <strong>{request.sourceVersion || 'Pending'}</strong>
            </div>
          </div>

          {request.inviteDeliveryError ? (
            <p className="signature-request-dialog__response-note">
              {request.inviteDeliveryError}
            </p>
          ) : null}
          {request.status === 'draft' ? (
            <p className="signature-request-dialog__response-note">
              Review and send this draft from the Prepare tab to activate the signer link.
            </p>
          ) : null}
          {request.status === 'invalidated' ? (
            <p className="signature-request-dialog__response-note">
              {request.publicLinkRevokedAt
                ? 'This signer link was revoked by the sender. Reissue the link to activate a fresh replacement URL.'
                : request.invalidationReason || 'This signing request is no longer valid.'}
            </p>
          ) : null}
          {request.status === 'sent' && request.isExpired ? (
            <p className="signature-request-dialog__response-note">
              This signer link expired. Reissue it to rotate a fresh URL and restart the signer ceremony.
            </p>
          ) : null}
          {request.status === 'sent' && !request.isExpired && (request.publicLinkVersion || 1) > 1 ? (
            <p className="signature-request-dialog__response-note">
              Older signer links were rotated out. Only the newest signer URL remains valid.
            </p>
          ) : null}

          <div className="signature-request-dialog__response-actions">
            {canCopySignerLink(request) ? (
              <button
                type="button"
                className="ui-button ui-button--ghost"
                onClick={() => { void handleCopyLink(request); }}
              >
                {copiedRequestId === request.id ? 'Copied signer link' : 'Copy signer link'}
              </button>
            ) : null}
            {canRevokeRequest(request) ? (
              <button
                type="button"
                className="ui-button ui-button--ghost"
                onClick={() => { void handleRevoke(request); }}
                disabled={revokingRequestId === request.id}
              >
                {revokingRequestId === request.id
                  ? 'Updating…'
                  : request.status === 'draft'
                    ? 'Cancel draft'
                    : 'Revoke signer link'}
              </button>
            ) : null}
            {canReissueRequest(request) ? (
              <button
                type="button"
                className="ui-button ui-button--ghost"
                onClick={() => { void handleReissue(request); }}
                disabled={reissuingRequestId === request.id}
              >
                {reissuingRequestId === request.id ? 'Updating…' : 'Reissue signer link'}
              </button>
            ) : null}
            {request.artifacts?.sourcePdf?.downloadPath ? (
              <button
                type="button"
                className="ui-button ui-button--ghost"
                onClick={() => {
                  void handleArtifactDownload(
                    request.artifacts!.sourcePdf!.downloadPath!,
                    request.mode === 'fill_and_sign' ? 'respondent-form.pdf' : 'source.pdf',
                  );
                }}
                disabled={downloadingPath === request.artifacts.sourcePdf.downloadPath}
              >
                {downloadingPath === request.artifacts.sourcePdf.downloadPath
                  ? 'Downloading…'
                  : request.mode === 'fill_and_sign' ? 'Download respondent form' : 'Download source PDF'}
              </button>
            ) : null}
            {request.artifacts?.signedPdf?.downloadPath ? (
              <button
                type="button"
                className="ui-button ui-button--primary"
                onClick={() => {
                  void handleArtifactDownload(request.artifacts!.signedPdf!.downloadPath!, 'signed-form.pdf');
                }}
                disabled={downloadingPath === request.artifacts.signedPdf.downloadPath}
              >
                {downloadingPath === request.artifacts.signedPdf.downloadPath ? 'Downloading…' : 'Download signed form'}
              </button>
            ) : null}
            {request.artifacts?.auditReceipt?.downloadPath ? (
              <button
                type="button"
                className="ui-button ui-button--ghost"
                onClick={() => {
                  void handleArtifactDownload(request.artifacts!.auditReceipt!.downloadPath!, 'audit-receipt.pdf');
                }}
                disabled={downloadingPath === request.artifacts.auditReceipt.downloadPath}
              >
                {downloadingPath === request.artifacts.auditReceipt.downloadPath ? 'Downloading…' : 'Download audit receipt'}
              </button>
            ) : null}
          </div>
        </article>
      ))}
    </section>
  );
}

export default SigningResponsesPanel;
