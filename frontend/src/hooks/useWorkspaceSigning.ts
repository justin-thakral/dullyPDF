import { useCallback, useEffect, useMemo, useState } from 'react';
import type { User } from 'firebase/auth';
import type { PdfField } from '../types';
import {
  ApiService,
  type CreateSigningRequestPayload,
  type SigningOptions,
  type SigningRequestSummary,
} from '../services/api';
import {
  buildSigningAnchorsFromFields,
  hashSourcePdfSha256,
  hasMeaningfulFillValues,
  type ReviewedFillContext,
} from '../utils/signing';
import type { SigningRecipientInput } from '../utils/signingRecipients';

export interface UseWorkspaceSigningDeps {
  verifiedUser: User | null;
  hasDocument: boolean;
  sourceDocumentName: string | null;
  sourceTemplateId?: string | null;
  sourceTemplateName?: string | null;
  fields: PdfField[];
  resolveSourcePdfBytes: (mode: CreateSigningRequestPayload['mode']) => Promise<Uint8Array>;
  reviewedFillContext?: ReviewedFillContext | null;
}

export type WorkspaceSigningDraftPayload = Omit<CreateSigningRequestPayload, 'signerName' | 'signerEmail'> & {
  recipients: SigningRecipientInput[];
};

function buildRecipientSpecificTitle(baseTitle: string | undefined, recipient: SigningRecipientInput, totalRecipients: number): string | undefined {
  const normalizedTitle = String(baseTitle || '').trim();
  if (!normalizedTitle) {
    return normalizedTitle || undefined;
  }
  if (totalRecipients <= 1) {
    return normalizedTitle;
  }
  return `${normalizedTitle} · ${recipient.name}`;
}

export function useWorkspaceSigning(deps: UseWorkspaceSigningDeps) {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [signingOptions, setSigningOptions] = useState<SigningOptions | null>(null);
  const [signingOptionsRequested, setSigningOptionsRequested] = useState(false);
  const [signingOptionsLoading, setSigningOptionsLoading] = useState(false);
  const [signingRequests, setSigningRequests] = useState<SigningRequestSummary[]>([]);
  const [signingRequestsLoading, setSigningRequestsLoading] = useState(false);
  const [signingSaveInProgress, setSigningSaveInProgress] = useState(false);
  const [signingSendInProgress, setSigningSendInProgress] = useState(false);
  const [signingRevokeRequestId, setSigningRevokeRequestId] = useState<string | null>(null);
  const [signingReissueRequestId, setSigningReissueRequestId] = useState<string | null>(null);
  const [signingError, setSigningError] = useState<string | null>(null);
  const [signingNotice, setSigningNotice] = useState<string | null>(null);
  const [createdSigningRequests, setCreatedSigningRequests] = useState<SigningRequestSummary[]>([]);

  const defaultAnchors = useMemo(
    () => buildSigningAnchorsFromFields(deps.fields),
    [deps.fields],
  );
  const canShowAction = Boolean(deps.verifiedUser);
  const canSendForSignature = Boolean(deps.verifiedUser && deps.hasDocument);
  const hasFilledValues = useMemo(() => hasMeaningfulFillValues(deps.fields), [deps.fields]);

  const openDialog = useCallback(() => {
    if (!deps.verifiedUser) return;
    setSigningError(null);
    setSigningNotice(null);
    setCreatedSigningRequests([]);
    if (!signingOptions) {
      setSigningOptionsRequested(true);
    }
    void (async () => {
      setSigningRequestsLoading(true);
      try {
        const requests = await ApiService.getSigningRequests();
        setSigningRequests(requests);
      } catch (error) {
        setSigningError(error instanceof Error ? error.message : 'Unable to load signing responses.');
      } finally {
        setSigningRequestsLoading(false);
      }
    })();
    setDialogOpen(true);
  }, [deps.verifiedUser, signingOptions]);

  const closeDialog = useCallback(() => {
    setDialogOpen(false);
  }, []);

  useEffect(() => {
    if (!dialogOpen || signingOptions || signingOptionsLoading || !signingOptionsRequested || !deps.verifiedUser) return;
    setSigningOptionsLoading(true);
    setSigningOptionsRequested(false);
    setSigningError(null);
    ApiService.getSigningOptions()
      .then((payload) => {
        setSigningOptions(payload);
      })
      .catch((error) => {
        setSigningError(error instanceof Error ? error.message : 'Unable to load signing options.');
      })
      .finally(() => {
        setSigningOptionsLoading(false);
      });
  }, [dialogOpen, signingOptions, signingOptionsLoading, signingOptionsRequested, deps.verifiedUser]);

  const refreshResponses = useCallback(async () => {
    if (!deps.verifiedUser) {
      setSigningRequests([]);
      return;
    }
    setSigningRequestsLoading(true);
    try {
      const requests = await ApiService.getSigningRequests();
      setSigningRequests(requests);
    } catch (error) {
      setSigningError(error instanceof Error ? error.message : 'Unable to load signing responses.');
    } finally {
      setSigningRequestsLoading(false);
    }
  }, [deps.verifiedUser]);

  const createDrafts = useCallback(async (payload: WorkspaceSigningDraftPayload) => {
    setSigningSaveInProgress(true);
    setSigningError(null);
    setSigningNotice(null);
    try {
      const recipients = payload.recipients || [];
      if (!recipients.length) {
        throw new Error('Add at least one recipient before saving a signing draft.');
      }
      const sourcePdfBytes = await deps.resolveSourcePdfBytes(payload.mode);
      const sourcePdfSha256 = await hashSourcePdfSha256(sourcePdfBytes);
      const fillContext = payload.mode === 'fill_and_sign' ? deps.reviewedFillContext ?? null : null;
      const created: SigningRequestSummary[] = [];
      const failed: string[] = [];
      for (const recipient of recipients) {
        try {
          const request = await ApiService.createSigningRequest({
            ...payload,
            title: buildRecipientSpecificTitle(payload.title, recipient, recipients.length),
            sourceType: fillContext?.sourceType || payload.sourceType,
            sourceId: fillContext?.sourceId || payload.sourceId,
            sourceLinkId: fillContext?.sourceLinkId || undefined,
            sourceRecordLabel: fillContext?.sourceRecordLabel || undefined,
            sourcePdfSha256,
            signerName: recipient.name,
            signerEmail: recipient.email,
          });
          created.push(request);
        } catch (error) {
          const detail = error instanceof Error ? error.message : 'Unable to save draft';
          failed.push(`${recipient.email}: ${detail}`);
        }
      }
      setCreatedSigningRequests(created);
      await refreshResponses();
      if (created.length) {
        setSigningNotice(
          created.length === 1
            ? `Saved 1 signing draft for ${created[0].signerEmail}.`
            : `Saved ${created.length} signing drafts.`,
        );
      }
      if (failed.length) {
        setSigningError(
          failed.length === 1 && created.length <= 1
            ? failed[0].replace(/^[^:]+:\s*/, '')
            : created.length
              ? `Some drafts failed: ${failed.join(' | ')}`
              : failed.join(' | '),
        );
      }
    } catch (error) {
      setSigningError(error instanceof Error ? error.message : 'Unable to save signing draft.');
    } finally {
      setSigningSaveInProgress(false);
    }
  }, [deps]);

  const createSingleDraft = useCallback(async (payload: CreateSigningRequestPayload) => {
    await createDrafts({
      ...payload,
      recipients: [
        {
          name: payload.signerName,
          email: payload.signerEmail,
          source: 'manual',
        },
      ],
    });
  }, [createDrafts]);

  const sendDrafts = useCallback(async (options?: { ownerReviewConfirmed?: boolean }) => {
    if (!createdSigningRequests.length) return;
    setSigningSendInProgress(true);
    setSigningError(null);
    setSigningNotice(null);
    try {
      const [firstRequest] = createdSigningRequests;
      const sourcePdfBytes = await deps.resolveSourcePdfBytes(firstRequest.mode);
      const sourcePdfSha256 = await hashSourcePdfSha256(sourcePdfBytes);
      const pdfBlobBytes = new Uint8Array(sourcePdfBytes);
      const nextRequests: SigningRequestSummary[] = [];
      const failed: string[] = [];
      for (const request of createdSigningRequests) {
        if (request.status !== 'draft') {
          nextRequests.push(request);
          continue;
        }
        try {
          const sentRequest = await ApiService.sendSigningRequest(request.id, {
            pdf: new Blob([pdfBlobBytes], { type: 'application/pdf' }),
            filename: `${deps.sourceDocumentName || 'signing-source'}.pdf`,
            sourcePdfSha256,
            ownerReviewConfirmed: options?.ownerReviewConfirmed,
          });
          nextRequests.push(sentRequest);
        } catch (error) {
          try {
            const refreshed = await ApiService.getSigningRequest(request.id);
            nextRequests.push(refreshed);
          } catch {
            nextRequests.push(request);
          }
          const detail = error instanceof Error ? error.message : 'Unable to send signing request.';
          failed.push(`${request.signerEmail}: ${detail}`);
        }
      }
      setCreatedSigningRequests(nextRequests);
      await refreshResponses();
      const sentCount = nextRequests.filter((entry) => entry.status === 'sent').length;
      if (sentCount) {
        setSigningNotice(
          sentCount === 1
            ? `Sent 1 signing request.`
            : `Sent ${sentCount} signing requests.`,
        );
      }
      if (failed.length) {
        setSigningError(
          failed.length === 1 && nextRequests.length <= 1
            ? failed[0].replace(/^[^:]+:\s*/, '')
            : sentCount
              ? `Some requests failed to send: ${failed.join(' | ')}`
              : failed.join(' | '),
        );
      }
    } catch (error) {
      setSigningError(error instanceof Error ? error.message : 'Unable to send signing request.');
    } finally {
      setSigningSendInProgress(false);
    }
  }, [createdSigningRequests, deps, refreshResponses]);

  const sendDisabledReason = useMemo(() => {
    if (!createdSigningRequests.length) return null;
    const invalidatedRequest = createdSigningRequests.find((entry) => entry.status === 'invalidated');
    if (invalidatedRequest) {
      return invalidatedRequest.invalidationReason || 'One of these drafts was invalidated because the source PDF changed.';
    }
    const pendingDrafts = createdSigningRequests.filter((entry) => entry.status === 'draft');
    if (!pendingDrafts.length) {
      return 'All current signing requests have already been sent or are no longer sendable.';
    }
    const missingHash = pendingDrafts.find((entry) => !entry.sourcePdfSha256);
    if (missingHash) {
      return 'At least one draft is missing a source PDF hash. Recreate the draft batch before sending.';
    }
    const hasSignatureAnchor = pendingDrafts.some((request) => request.anchors.some((entry) => entry.kind === 'signature'));
    if (!hasSignatureAnchor) {
      return 'Add at least one signature anchor before sending these requests.';
    }
    return null;
  }, [createdSigningRequests]);

  const revokeRequest = useCallback(async (requestId: string) => {
    const normalizedRequestId = String(requestId || '').trim();
    if (!normalizedRequestId) return;
    setSigningRevokeRequestId(normalizedRequestId);
    setSigningError(null);
    setSigningNotice(null);
    try {
      const revokedRequest = await ApiService.revokeSigningRequest(normalizedRequestId);
      setCreatedSigningRequests((current) => current.map((entry) => (
        entry.id === revokedRequest.id ? revokedRequest : entry
      )));
      await refreshResponses();
      setSigningNotice(
        revokedRequest.sentAt
          ? 'Signing request revoked. The signer link is now inactive.'
          : 'Signing draft canceled.',
      );
    } catch (error) {
      setSigningError(error instanceof Error ? error.message : 'Unable to revoke the signing request.');
    } finally {
      setSigningRevokeRequestId((current) => (current === normalizedRequestId ? null : current));
    }
  }, [refreshResponses]);

  const reissueRequest = useCallback(async (requestId: string) => {
    const normalizedRequestId = String(requestId || '').trim();
    if (!normalizedRequestId) return;
    setSigningReissueRequestId(normalizedRequestId);
    setSigningError(null);
    setSigningNotice(null);
    try {
      const reissuedRequest = await ApiService.reissueSigningRequest(normalizedRequestId);
      setCreatedSigningRequests((current) => current.map((entry) => (
        entry.id === reissuedRequest.id ? reissuedRequest : entry
      )));
      await refreshResponses();
      setSigningNotice('Replacement signer link issued. Previous links are now inactive.');
    } catch (error) {
      setSigningError(error instanceof Error ? error.message : 'Unable to reissue the signing link.');
    } finally {
      setSigningReissueRequestId((current) => (current === normalizedRequestId ? null : current));
    }
  }, [refreshResponses]);

  const dialogProps = useMemo(() => ({
    open: dialogOpen,
    onClose: closeDialog,
    hasDocument: deps.hasDocument,
    sourceDocumentName: deps.sourceDocumentName,
    sourceTemplateId: deps.sourceTemplateId ?? null,
    sourceTemplateName: deps.sourceTemplateName ?? null,
    options: signingOptions,
    optionsLoading: signingOptionsLoading,
    responses: signingRequests,
    responsesLoading: signingRequestsLoading,
    saving: signingSaveInProgress,
    sending: signingSendInProgress,
    revokingRequestId: signingRevokeRequestId,
    reissuingRequestId: signingReissueRequestId,
    error: signingError,
    notice: signingNotice,
    createdRequests: createdSigningRequests,
    createdRequest: createdSigningRequests[0] ?? null,
    sendDisabledReason,
    defaultAnchors,
    hasMeaningfulFillValues: hasFilledValues,
    fillAndSignContext: deps.reviewedFillContext ?? null,
    onCreateDraft: createSingleDraft,
    onCreateDrafts: createDrafts,
    onSendRequest: sendDrafts,
    onSendRequests: sendDrafts,
    onRevokeRequest: revokeRequest,
    onReissueRequest: reissueRequest,
    onRefreshResponses: refreshResponses,
  }), [
    closeDialog,
    createSingleDraft,
    createDrafts,
    createdSigningRequests,
    defaultAnchors,
    deps.reviewedFillContext,
    deps.hasDocument,
    deps.sourceDocumentName,
    deps.sourceTemplateId,
    deps.sourceTemplateName,
    dialogOpen,
    hasFilledValues,
    signingError,
    signingNotice,
    signingOptions,
    signingOptionsLoading,
    signingRevokeRequestId,
    signingReissueRequestId,
    signingRequests,
    signingRequestsLoading,
    signingSendInProgress,
    signingSaveInProgress,
    sendDisabledReason,
    sendDrafts,
    revokeRequest,
    reissueRequest,
    refreshResponses,
  ]);

  return {
    canShowAction,
    canSendForSignature,
    openDialog,
    closeDialog,
    dialogProps,
  };
}
