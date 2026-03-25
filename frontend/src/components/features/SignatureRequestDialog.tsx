import { useEffect, useMemo, useState } from 'react';
import type {
  CreateSigningRequestPayload,
  SigningCategoryOption,
  SigningOptions,
  SigningRequestSummary,
} from '../../services/api';
import type { ReviewedFillContext } from '../../utils/signing';
import {
  mergeSigningRecipients,
  normalizeSigningRecipient,
  parseSigningRecipientsFromFile,
  parseSigningRecipientsFromText,
  type SigningRecipientInput,
} from '../../utils/signingRecipients';
import type { WorkspaceSigningDraftPayload } from '../../hooks/useWorkspaceSigning';
import { Dialog } from '../ui/Dialog';
import { Alert } from '../ui/Alert';
import { SigningResponsesPanel } from './SigningResponsesPanel';
import '../../styles/ui-buttons.css';
import './SignatureRequestDialog.css';

type SignatureRequestDialogProps = {
  open: boolean;
  onClose: () => void;
  hasDocument: boolean;
  sourceDocumentName: string | null;
  sourceTemplateId?: string | null;
  sourceTemplateName?: string | null;
  options: SigningOptions | null;
  optionsLoading?: boolean;
  responses?: SigningRequestSummary[];
  responsesLoading?: boolean;
  saving?: boolean;
  sending?: boolean;
  error?: string | null;
  notice?: string | null;
  createdRequest?: SigningRequestSummary | null;
  createdRequests?: SigningRequestSummary[];
  sendDisabledReason?: string | null;
  hasMeaningfulFillValues?: boolean;
  fillAndSignContext?: ReviewedFillContext | null;
  defaultAnchors?: WorkspaceSigningDraftPayload['anchors'];
  onCreateDraft?: (payload: CreateSigningRequestPayload) => Promise<void> | void;
  onCreateDrafts: (payload: WorkspaceSigningDraftPayload) => Promise<void> | void;
  onSendRequest?: (options?: { ownerReviewConfirmed?: boolean }) => Promise<void> | void;
  onSendRequests?: (options?: { ownerReviewConfirmed?: boolean }) => Promise<void> | void;
  onRefreshResponses?: () => Promise<void> | void;
};

type DialogTab = 'prepare' | 'responses';

const DEFAULT_MODE: WorkspaceSigningDraftPayload['mode'] = 'sign';
const DEFAULT_SIGNATURE_MODE: WorkspaceSigningDraftPayload['signatureMode'] = 'business';

function firstAllowedCategory(options: SigningOptions | null): string {
  const allowed = options?.categories?.find((entry) => !entry.blocked);
  return allowed?.key || 'ordinary_business_form';
}

function buildDefaultTitle(sourceDocumentName: string | null, mode: WorkspaceSigningDraftPayload['mode']): string {
  const base = sourceDocumentName?.trim() || 'Untitled PDF';
  if (mode === 'fill_and_sign') {
    return `${base} Fill And Sign`;
  }
  return `${base} Signature Request`;
}

function describeMode(mode: WorkspaceSigningDraftPayload['mode'], fillAndSignContext: ReviewedFillContext | null): string {
  return mode === 'fill_and_sign'
    ? fillAndSignContext?.sourceType === 'fill_link_response'
      ? 'DullyPDF will freeze the reviewed Fill By Link response exactly as it appears in the workspace, then hand that immutable PDF to each signer.'
      : 'DullyPDF will freeze the current reviewed workspace values into an immutable PDF, then hand that exact record to each signer.'
    : 'DullyPDF will freeze the current PDF state into an immutable source snapshot before signature collection begins.';
}

function describeFillAndSignSource(fillAndSignContext: ReviewedFillContext | null): string {
  if (!fillAndSignContext) {
    return 'Current workspace values';
  }
  if (fillAndSignContext.sourceType === 'fill_link_response') {
    return fillAndSignContext.sourceRecordLabel
      ? `Fill By Link response: ${fillAndSignContext.sourceRecordLabel}`
      : 'Stored Fill By Link response';
  }
  return fillAndSignContext.sourceLabel || 'Current workspace values';
}

function resolveBatchStatus(createdRequests: SigningRequestSummary[]): string {
  if (!createdRequests.length) return 'No batch yet';
  const completed = createdRequests.filter((entry) => entry.status === 'completed').length;
  const sent = createdRequests.filter((entry) => entry.status === 'sent').length;
  const drafts = createdRequests.filter((entry) => entry.status === 'draft').length;
  if (completed && !sent && !drafts) return `All ${completed} signed`;
  if (sent && !drafts) return `${sent} waiting for signer`;
  if (drafts && !sent) return `${drafts} draft${drafts === 1 ? '' : 's'} saved`;
  return `${sent} waiting, ${completed} signed, ${drafts} drafts`;
}

function joinRejectedRecipients(rejected: string[]): string | null {
  if (!rejected.length) return null;
  return `These rows could not be read: ${rejected.join(' | ')}`;
}

export function SignatureRequestDialog({
  open,
  onClose,
  hasDocument,
  sourceDocumentName,
  sourceTemplateId = null,
  sourceTemplateName = null,
  options,
  optionsLoading = false,
  responses = [],
  responsesLoading = false,
  saving = false,
  sending = false,
  error = null,
  notice = null,
  createdRequest = null,
  createdRequests = [],
  sendDisabledReason = null,
  hasMeaningfulFillValues = false,
  fillAndSignContext = null,
  defaultAnchors = [],
  onCreateDraft,
  onCreateDrafts,
  onSendRequest,
  onSendRequests,
  onRefreshResponses,
}: SignatureRequestDialogProps) {
  const stableCreatedRequests = createdRequests;
  const [activeTab, setActiveTab] = useState<DialogTab>('prepare');
  const [mode, setMode] = useState<WorkspaceSigningDraftPayload['mode']>(DEFAULT_MODE);
  const [signatureMode, setSignatureMode] = useState<WorkspaceSigningDraftPayload['signatureMode']>(DEFAULT_SIGNATURE_MODE);
  const [documentCategory, setDocumentCategory] = useState<string>(firstAllowedCategory(options));
  const [manualFallbackEnabled, setManualFallbackEnabled] = useState(true);
  const [draftSignerName, setDraftSignerName] = useState('');
  const [draftSignerEmail, setDraftSignerEmail] = useState('');
  const [recipientImportText, setRecipientImportText] = useState('');
  const [recipientImportError, setRecipientImportError] = useState<string | null>(null);
  const [recipients, setRecipients] = useState<SigningRecipientInput[]>([]);
  const [ownerReviewConfirmed, setOwnerReviewConfirmed] = useState(false);

  useEffect(() => {
    if (!open) return;
    setDocumentCategory(firstAllowedCategory(options));
  }, [open, options]);

  useEffect(() => {
    if (!open) return;
    setActiveTab('prepare');
    setMode(DEFAULT_MODE);
    setSignatureMode(DEFAULT_SIGNATURE_MODE);
    setManualFallbackEnabled(true);
    setDraftSignerName('');
    setDraftSignerEmail('');
    setRecipientImportText('');
    setRecipientImportError(null);
    setRecipients([]);
    setOwnerReviewConfirmed(false);
  }, [open, sourceDocumentName]);

  const effectiveCreatedRequests = useMemo(
    () => (stableCreatedRequests.length
      ? stableCreatedRequests
      : createdRequest
        ? [createdRequest]
        : []),
    [createdRequest, stableCreatedRequests],
  );

  const createdRequestResetKey = useMemo(
    () => effectiveCreatedRequests.map((entry) => `${entry.id}:${entry.status}:${entry.sourceVersion || ''}`).join('|'),
    [effectiveCreatedRequests],
  );

  useEffect(() => {
    if (!open) return;
    setOwnerReviewConfirmed(false);
  }, [createdRequestResetKey, open]);

  const pendingManualRecipient = useMemo(
    () => normalizeSigningRecipient(draftSignerName, draftSignerEmail, 'manual'),
    [draftSignerEmail, draftSignerName],
  );
  const selectedCategory = useMemo(
    () => options?.categories?.find((entry) => entry.key === documentCategory) || null,
    [documentCategory, options],
  );
  const blockedCategory = Boolean(selectedCategory?.blocked);
  const fillAndSignNeedsValues = mode === 'fill_and_sign' && !hasMeaningfulFillValues;
  const anchorCount = defaultAnchors.length;
  const workflowLabel = mode === 'fill_and_sign' ? 'Fill and Sign' : 'Sign';
  const defaultTitle = buildDefaultTitle(sourceDocumentName, mode);
  const plannedRecipients = resolveRecipientsForSubmit();
  const plannedRecipientCount = plannedRecipients.length;
  const pendingDraftCount = effectiveCreatedRequests.filter((entry) => entry.status === 'draft').length;
  const batchNeedsOwnerReview = effectiveCreatedRequests.some((entry) => entry.mode === 'fill_and_sign');
  const sendReady = Boolean(
    effectiveCreatedRequests.length
    && pendingDraftCount > 0
    && !sendDisabledReason
    && !saving
    && !sending
    && (onSendRequests || onSendRequest)
    && (!batchNeedsOwnerReview || ownerReviewConfirmed),
  );

  const readinessItems = [
    { label: 'PDF loaded', ready: hasDocument },
    { label: 'Recipients queued', ready: recipients.length > 0 || Boolean(pendingManualRecipient) },
    { label: 'Allowed category', ready: Boolean(documentCategory && !blockedCategory) },
    {
      label: mode === 'fill_and_sign' ? 'Reviewed fill values' : 'Signature anchors',
      ready: mode === 'fill_and_sign' ? !fillAndSignNeedsValues : anchorCount > 0,
    },
  ];

  const canSubmit = Boolean(
    hasDocument
    && sourceDocumentName
    && plannedRecipientCount > 0
    && documentCategory
    && !blockedCategory
    && !fillAndSignNeedsValues
    && !optionsLoading
    && options,
  );

  function pushRecipient(recipient: SigningRecipientInput | null) {
    if (!recipient) {
      setRecipientImportError('Enter a valid signer email before adding the recipient.');
      return;
    }
    setRecipients((current) => mergeSigningRecipients(current, [recipient]));
    setDraftSignerName('');
    setDraftSignerEmail('');
    setRecipientImportError(null);
  }

  function resolveRecipientsForSubmit(): SigningRecipientInput[] {
    return pendingManualRecipient
      ? mergeSigningRecipients(recipients, [pendingManualRecipient])
      : recipients;
  }

  async function handleImportFromText() {
    const result = parseSigningRecipientsFromText(recipientImportText, {
      source: 'paste',
      csvMode: recipientImportText.includes(','),
    });
    if (!result.recipients.length && !result.rejected.length) {
      setRecipientImportError('Paste at least one email address, `Name <email>`, or CSV row before importing.');
      return;
    }
    setRecipients((current) => mergeSigningRecipients(current, result.recipients));
    setRecipientImportError(joinRejectedRecipients(result.rejected));
    setRecipientImportText('');
  }

  async function handleImportFile(event: React.ChangeEvent<HTMLInputElement>) {
    const [file] = Array.from(event.target.files || []);
    event.target.value = '';
    if (!file) return;
    const result = await parseSigningRecipientsFromFile(file);
    setRecipients((current) => mergeSigningRecipients(current, result.recipients));
    setRecipientImportError(joinRejectedRecipients(result.rejected));
  }

  async function handleCreate() {
    const nextRecipients = resolveRecipientsForSubmit();
    setRecipients(nextRecipients);
    if (!canSubmit || !sourceDocumentName || !nextRecipients.length) return;
    if (onCreateDraft && nextRecipients.length === 1) {
      const [recipient] = nextRecipients;
      await onCreateDraft({
        title: defaultTitle,
        mode,
        signatureMode,
        sourceType: mode === 'fill_and_sign' ? (fillAndSignContext?.sourceType || 'workspace') : 'workspace',
        sourceId: mode === 'fill_and_sign'
          ? fillAndSignContext?.sourceId || sourceTemplateId || undefined
          : sourceTemplateId || undefined,
        sourceLinkId: mode === 'fill_and_sign' ? fillAndSignContext?.sourceLinkId || undefined : undefined,
        sourceRecordLabel: mode === 'fill_and_sign' ? fillAndSignContext?.sourceRecordLabel || undefined : undefined,
        sourceDocumentName,
        sourceTemplateId: sourceTemplateId || undefined,
        sourceTemplateName: sourceTemplateName || undefined,
        documentCategory,
        manualFallbackEnabled,
        signerName: recipient.name,
        signerEmail: recipient.email,
        anchors: defaultAnchors,
      });
      return;
    }
    await onCreateDrafts({
      title: defaultTitle,
      mode,
      signatureMode,
      sourceType: mode === 'fill_and_sign' ? (fillAndSignContext?.sourceType || 'workspace') : 'workspace',
      sourceId: mode === 'fill_and_sign'
        ? fillAndSignContext?.sourceId || sourceTemplateId || undefined
        : sourceTemplateId || undefined,
      sourceLinkId: mode === 'fill_and_sign' ? fillAndSignContext?.sourceLinkId || undefined : undefined,
      sourceRecordLabel: mode === 'fill_and_sign' ? fillAndSignContext?.sourceRecordLabel || undefined : undefined,
      sourceDocumentName,
      sourceTemplateId: sourceTemplateId || undefined,
      sourceTemplateName: sourceTemplateName || undefined,
      documentCategory,
      manualFallbackEnabled,
      anchors: defaultAnchors,
      recipients: nextRecipients,
    });
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Send PDF for Signature by email"
      description={(
        <span className="signature-request-dialog__intro">
          Create U.S. e-sign signing requests, freeze the exact PDF version, and email that immutable record into the signer ceremony.
        </span>
      )}
      className="signature-request-dialog"
    >
      <div className="signature-request-dialog__body">
        <div className="signature-request-dialog__topbar">
          <div className="signature-request-dialog__tabs" role="tablist" aria-label="Signing tabs">
            <button
              type="button"
              className={activeTab === 'prepare' ? 'signature-request-dialog__tab signature-request-dialog__tab--active' : 'signature-request-dialog__tab'}
              onClick={() => setActiveTab('prepare')}
            >
              Prepare
            </button>
            <button
              type="button"
              className={activeTab === 'responses' ? 'signature-request-dialog__tab signature-request-dialog__tab--active' : 'signature-request-dialog__tab'}
              onClick={() => setActiveTab('responses')}
            >
              Responses
            </button>
          </div>
        </div>

        {!hasDocument ? (
          <Alert tone="error" variant="inline" message="Load a PDF in the workspace before starting a signing request." />
        ) : null}
        {error ? <Alert tone="error" variant="inline" message={error} /> : null}
        {notice ? <Alert tone="success" variant="inline" message={notice} /> : null}
        {!notice && effectiveCreatedRequests.length ? (
          <Alert
            tone={effectiveCreatedRequests.every((entry) => entry.status === 'sent') ? 'success' : 'info'}
            variant="inline"
            message={
              effectiveCreatedRequests.every((entry) => entry.status === 'sent')
                ? effectiveCreatedRequests.length === 1
                  ? 'Signing request sent. Invite delivery status and signer progress now appear in Responses.'
                  : 'Signing requests sent. Invite delivery status and signer progress now appear in Responses.'
                : effectiveCreatedRequests.length === 1
                  ? 'Draft saved. The signer link stays inactive until you click Review and Send.'
                  : 'Drafts saved. Review the batch summary, then click Review and Send to activate signer links.'
            }
          />
        ) : null}

        {activeTab === 'responses' ? (
          <SigningResponsesPanel
            requests={responses}
            loading={responsesLoading}
            sourceDocumentName={sourceDocumentName}
            sourceTemplateId={sourceTemplateId}
            onRefresh={onRefreshResponses}
          />
        ) : (
          <>
            <section className="signature-request-dialog__hero" aria-label="Signing request overview">
              <div className="signature-request-dialog__hero-copy">
                <span className="signature-request-dialog__eyebrow">Signing setup</span>
                <h3>{workflowLabel === 'Fill and Sign' ? 'Freeze the reviewed record, then route it to signature.' : 'Freeze the active PDF, then send it to signature.'}</h3>
                <p className="signature-request-dialog__supporting-copy">{describeMode(mode, fillAndSignContext)}</p>
              </div>
              <div className="signature-request-dialog__hero-facts">
                <div className="signature-request-dialog__metric">
                  <span className="signature-request-dialog__label">Workflow</span>
                  <strong>{workflowLabel}</strong>
                </div>
                <div className="signature-request-dialog__metric">
                  <span className="signature-request-dialog__label">Signature mode</span>
                  <strong>{signatureMode === 'consumer' ? 'Consumer' : 'Business'}</strong>
                </div>
                <div className="signature-request-dialog__metric">
                  <span className="signature-request-dialog__label">Recipients</span>
                  <strong>{plannedRecipientCount}</strong>
                </div>
                <div className="signature-request-dialog__metric">
                  <span className="signature-request-dialog__label">Anchors</span>
                  <strong>{anchorCount}</strong>
                </div>
              </div>
            </section>

            <div className="signature-request-dialog__layout">
              <div className="signature-request-dialog__column signature-request-dialog__column--main">
                <section className="signature-request-dialog__section">
                  <h3>Workflow</h3>
                  <div className="signature-request-dialog__mode-row" role="tablist" aria-label="Signing mode">
                    <button
                      type="button"
                      className={mode === 'sign' ? 'ui-button ui-button--primary' : 'ui-button ui-button--ghost'}
                      onClick={() => setMode('sign')}
                    >
                      Sign
                    </button>
                    <button
                      type="button"
                      className={mode === 'fill_and_sign' ? 'ui-button ui-button--primary' : 'ui-button ui-button--ghost'}
                      onClick={() => setMode('fill_and_sign')}
                    >
                      Fill and Sign
                    </button>
                  </div>
                  <p className="signature-request-dialog__supporting-copy">{describeMode(mode, fillAndSignContext)}</p>
                </section>

                <section className="signature-request-dialog__section">
                  <h3>Document</h3>
                  <div className="signature-request-dialog__fact-grid">
                    <div>
                      <span className="signature-request-dialog__label">Source document</span>
                      <strong>{sourceDocumentName || 'No active document'}</strong>
                    </div>
                    <div>
                      <span className="signature-request-dialog__label">Template context</span>
                      <strong>{sourceTemplateName || 'Unsaved workspace document'}</strong>
                    </div>
                    <div>
                      <span className="signature-request-dialog__label">Detected anchors</span>
                      <strong>{anchorCount}</strong>
                    </div>
                    {mode === 'fill_and_sign' ? (
                      <div>
                        <span className="signature-request-dialog__label">Reviewed fill source</span>
                        <strong>{describeFillAndSignSource(fillAndSignContext)}</strong>
                      </div>
                    ) : null}
                  </div>
                  {mode === 'fill_and_sign' && fillAndSignNeedsValues ? (
                    <Alert
                      tone="warning"
                      variant="inline"
                      message="Fill and Sign needs reviewed field values in the workspace. Fill the PDF first, then create the signing draft."
                    />
                  ) : null}
                </section>

                <section className="signature-request-dialog__section">
                  <h3>Policy</h3>
                  <div className="signature-request-dialog__field-grid">
                    <label className="signature-request-dialog__field">
                      <span>Signature mode</span>
                      <select
                        value={signatureMode}
                        onChange={(event) => setSignatureMode(event.target.value as WorkspaceSigningDraftPayload['signatureMode'])}
                      >
                        {(options?.signatureModes || []).map((entry) => (
                          <option key={entry.key} value={entry.key}>{entry.label}</option>
                        ))}
                      </select>
                    </label>
                    <label className="signature-request-dialog__field">
                      <span>Document category</span>
                      <select value={documentCategory} onChange={(event) => setDocumentCategory(event.target.value)}>
                        {(options?.categories || []).map((entry: SigningCategoryOption) => (
                          <option key={entry.key} value={entry.key} disabled={entry.blocked}>
                            {entry.blocked ? `${entry.label} (Blocked)` : entry.label}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                  {blockedCategory && selectedCategory?.reason ? (
                    <Alert tone="error" variant="inline" message={selectedCategory.reason} />
                  ) : null}
                  <label className="signature-request-dialog__checkbox">
                    <input
                      type="checkbox"
                      checked={manualFallbackEnabled}
                      onChange={(event) => setManualFallbackEnabled(event.target.checked)}
                    />
                    <span>Allow a paper/manual fallback path for this request</span>
                  </label>
                </section>

                <section className="signature-request-dialog__section">
                  <div className="signature-request-dialog__section-header">
                    <div>
                      <h3>Recipients</h3>
                      <p className="signature-request-dialog__supporting-copy">
                        Add one signer manually, paste TXT/CSV rows, or upload a `.txt` / `.csv` file to queue a batch.
                      </p>
                    </div>
                    <span className="signature-request-dialog__recipient-count">{plannedRecipientCount} queued</span>
                  </div>

                  <div className="signature-request-dialog__recipient-builder">
                    <div className="signature-request-dialog__field-grid">
                      <label className="signature-request-dialog__field">
                        <span>Signer name</span>
                        <input value={draftSignerName} onChange={(event) => setDraftSignerName(event.target.value)} />
                      </label>
                      <label className="signature-request-dialog__field">
                        <span>Signer email</span>
                        <input type="email" value={draftSignerEmail} onChange={(event) => setDraftSignerEmail(event.target.value)} />
                      </label>
                    </div>
                    <div className="signature-request-dialog__recipient-builder-actions">
                      <button
                        type="button"
                        className="ui-button ui-button--ghost"
                        onClick={() => pushRecipient(normalizeSigningRecipient(draftSignerName, draftSignerEmail, 'manual'))}
                      >
                        Add recipient
                      </button>
                    </div>
                  </div>
                  {pendingManualRecipient ? (
                    <p className="signature-request-dialog__supporting-copy">
                      Pending manual recipient will be included automatically when you save drafts.
                    </p>
                  ) : null}

                  <div className="signature-request-dialog__import-grid">
                    <label className="signature-request-dialog__field signature-request-dialog__field--textarea">
                      <span>Paste TXT or CSV rows</span>
                      <textarea
                        value={recipientImportText}
                        onChange={(event) => setRecipientImportText(event.target.value)}
                        placeholder={'alex@example.com\nTaylor Example,taylor@example.com\nJordan Example <jordan@example.com>'}
                      />
                    </label>
                    <div className="signature-request-dialog__import-actions">
                      <button
                        type="button"
                        className="ui-button ui-button--ghost"
                        onClick={() => { void handleImportFromText(); }}
                      >
                        Import pasted recipients
                      </button>
                      <label className="ui-button ui-button--ghost signature-request-dialog__file-button">
                        Upload .txt or .csv
                        <input type="file" accept=".txt,.csv,text/plain,text/csv" onChange={(event) => { void handleImportFile(event); }} />
                      </label>
                      <p className="signature-request-dialog__supporting-copy">
                        If a row only includes an email address, DullyPDF will derive the display name from the email local part.
                      </p>
                    </div>
                  </div>

                  {recipientImportError ? <Alert tone="warning" variant="inline" message={recipientImportError} /> : null}

                  <div className="signature-request-dialog__recipient-list">
                    {recipients.length ? recipients.map((recipient) => (
                      <article key={recipient.email} className="signature-request-dialog__recipient-card">
                        <div>
                          <strong>{recipient.name}</strong>
                          <span>{recipient.email}</span>
                        </div>
                        <div className="signature-request-dialog__recipient-card-actions">
                          <span className="signature-request-dialog__response-badge signature-request-dialog__response-badge--muted">
                            {recipient.source}
                          </span>
                          <button
                            type="button"
                            className="ui-button ui-button--ghost"
                            onClick={() => setRecipients((current) => current.filter((entry) => entry.email !== recipient.email))}
                          >
                            Remove
                          </button>
                        </div>
                      </article>
                    )) : (
                      <div className="signature-request-dialog__empty-state">
                        No recipients queued yet.
                      </div>
                    )}
                  </div>
                </section>
              </div>

              <aside className="signature-request-dialog__column signature-request-dialog__column--side">
                <section className="signature-request-dialog__section signature-request-dialog__section--summary">
                  <h3>Draft readiness</h3>
                  <p className="signature-request-dialog__supporting-copy">
                    Saving stores the request policy, signer batch, source provenance, and the exact reviewed source hash that will be checked again before send.
                  </p>
                  <div className="signature-request-dialog__draft-preview">
                    <span className="signature-request-dialog__label">Draft title</span>
                    <strong>{defaultTitle}</strong>
                  </div>
                  <ul className="signature-request-dialog__checklist">
                    {readinessItems.map((item) => (
                      <li key={item.label} className={item.ready ? 'signature-request-dialog__checklist-item signature-request-dialog__checklist-item--ready' : 'signature-request-dialog__checklist-item'}>
                        <span className="signature-request-dialog__check-indicator" aria-hidden="true">{item.ready ? 'Ready' : 'Needs work'}</span>
                        <span>{item.label}</span>
                      </li>
                    ))}
                  </ul>
                </section>

                {effectiveCreatedRequests.length ? (
                  <section className="signature-request-dialog__section signature-request-dialog__section--summary">
                    <h3>Batch review and send</h3>
                    <div className="signature-request-dialog__response-grid">
                      <div>
                        <span className="signature-request-dialog__label">Batch status</span>
                        <strong>{resolveBatchStatus(effectiveCreatedRequests)}</strong>
                      </div>
                      <div>
                        <span className="signature-request-dialog__label">Requests</span>
                        <strong>{effectiveCreatedRequests.length}</strong>
                      </div>
                      <div>
                        <span className="signature-request-dialog__label">Source version</span>
                        <strong>{effectiveCreatedRequests[0]?.sourceVersion || 'Pending'}</strong>
                      </div>
                      <div>
                        <span className="signature-request-dialog__label">Category</span>
                        <strong>{effectiveCreatedRequests[0]?.documentCategoryLabel || 'Pending'}</strong>
                      </div>
                      <div>
                        <span className="signature-request-dialog__label">Pending sends</span>
                        <strong>{pendingDraftCount}</strong>
                      </div>
                      <div>
                        <span className="signature-request-dialog__label">Source SHA-256</span>
                        <strong className="signature-request-dialog__hash">{effectiveCreatedRequests[0]?.sourcePdfSha256 || 'Pending'}</strong>
                      </div>
                    </div>
                    {sendDisabledReason ? (
                      <Alert tone="info" variant="inline" message={sendDisabledReason} />
                    ) : null}
                    {effectiveCreatedRequests.some((entry) => entry.inviteDeliveryStatus === 'failed' || entry.inviteDeliveryStatus === 'skipped') ? (
                      <Alert
                        tone="warning"
                        variant="inline"
                        message="One or more invite emails were not delivered automatically. Use the Responses tab to copy signer links and follow up manually."
                      />
                    ) : null}
                    {(mode === 'fill_and_sign' || batchNeedsOwnerReview) ? (
                      <label className="signature-request-dialog__checkbox">
                        <input
                          type="checkbox"
                          checked={ownerReviewConfirmed}
                          onChange={(event) => setOwnerReviewConfirmed(event.target.checked)}
                        />
                        <span>I reviewed the filled PDF and want to freeze this exact version for signature.</span>
                      </label>
                    ) : null}
                    <p className="signature-request-dialog__supporting-copy">
                      Sending stores an immutable source PDF snapshot and moves each request from draft to sent. If the source PDF changes before send,
                      the affected drafts will be invalidated and must be recreated.
                    </p>
                  </section>
                ) : null}
              </aside>
            </div>
          </>
        )}
      </div>

      <div className="ui-dialog__actions signature-request-dialog__actions">
        <button className="ui-button ui-button--ghost" type="button" onClick={onClose}>
          Close
        </button>
        {activeTab === 'prepare' && effectiveCreatedRequests.length ? (
          <button
            className="ui-button ui-button--ghost"
            type="button"
            onClick={() => {
              void (onSendRequests || onSendRequest)?.({ ownerReviewConfirmed });
            }}
            disabled={!sendReady}
          >
            {sending ? 'Sending requests…' : 'Review and Send'}
          </button>
        ) : null}
        {activeTab === 'prepare' ? (
          <button
            className="ui-button ui-button--primary"
            type="button"
            onClick={() => { void handleCreate(); }}
            disabled={!canSubmit || saving}
          >
            {saving ? 'Saving drafts…' : plannedRecipientCount <= 1 ? 'Save Signing Draft' : 'Save Signing Drafts'}
          </button>
        ) : null}
      </div>
    </Dialog>
  );
}

export default SignatureRequestDialog;
