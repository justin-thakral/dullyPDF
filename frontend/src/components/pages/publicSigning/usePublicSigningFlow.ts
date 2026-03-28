import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ApiService,
  type PublicSigningBootstrap,
  type PublicSigningAdoptPayload,
  type PublicSigningFileResult,
  type PublicSigningRequest,
  type PublicSigningSession,
  type SigningAdoptedMode,
} from '../../../services/api';
import {
  PUBLIC_SIGNING_SESSION_ERROR_MESSAGE,
  buildPublicSigningFacts,
  canBootstrapSession,
  formatDateTime,
  hasConsentWithdrawnLock,
  hasManualFallbackLock,
  isActionableRequest,
  normalizePath,
  parseDate,
  resolveCurrentStep,
  resolveSigningSteps,
  type ArtifactActionKey,
  type BusyActionKey,
} from './publicSigningHelpers';

type LoadRequestResult = {
  request: PublicSigningRequest | null;
  session: PublicSigningSession | null;
  error: string | null;
};

function buildMissingSessionRunner(setActionError: (value: string | null) => void) {
  return (): false => {
    setActionError(PUBLIC_SIGNING_SESSION_ERROR_MESSAGE);
    return false;
  };
}

export function usePublicSigningFlow(token: string) {
  const [request, setRequest] = useState<PublicSigningRequest | null>(null);
  const [session, setSession] = useState<PublicSigningSession | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState<BusyActionKey>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [adoptedName, setAdoptedName] = useState('');
  const [signatureType, setSignatureType] = useState<SigningAdoptedMode>('typed');
  const [signatureImageDataUrl, setSignatureImageDataUrl] = useState<string | null>(null);
  const [accessCode, setAccessCode] = useState('');
  const [verificationCode, setVerificationCode] = useState('');
  const [intentConfirmed, setIntentConfirmed] = useState(false);
  const [artifactBusyKey, setArtifactBusyKey] = useState<ArtifactActionKey>(null);
  const [documentObjectUrl, setDocumentObjectUrl] = useState<string | null>(null);
  const [documentError, setDocumentError] = useState<string | null>(null);
  const [documentLoading, setDocumentLoading] = useState(false);
  const loadRequestRef = useRef<{
    token: string | null;
    promise: Promise<LoadRequestResult> | null;
  }>({
    token: null,
    promise: null,
  });

  function applyRequestState(nextRequest: PublicSigningRequest) {
    setRequest(nextRequest);
    setAdoptedName((current) => nextRequest.signatureAdoptedName || current || nextRequest.signerName || '');
    setSignatureType((current) => nextRequest.signatureAdoptedMode || current || 'typed');
    setSignatureImageDataUrl((current) => nextRequest.signatureAdoptedImageDataUrl || current || null);
  }

  function applyBootstrapState(nextPayload: PublicSigningBootstrap) {
    applyRequestState(nextPayload.request);
    setSession(nextPayload.session || null);
  }

  useEffect(() => {
    let mounted = true;

    setLoading(true);
    setError(null);
    setActionError(null);
    setBusyAction(null);
    setArtifactBusyKey(null);
    setSession(null);
    setIntentConfirmed(false);
    setAdoptedName('');
    setSignatureType('typed');
    setSignatureImageDataUrl(null);
    setAccessCode('');
    setVerificationCode('');
    setDocumentError(null);
    setDocumentLoading(false);
    setDocumentObjectUrl((current) => {
      if (current) URL.revokeObjectURL(current);
      return null;
    });

    if (loadRequestRef.current.token !== token || !loadRequestRef.current.promise) {
      loadRequestRef.current = {
        token,
        promise: (async (): Promise<LoadRequestResult> => {
          try {
            const nextRequest = await ApiService.getPublicSigningRequest(token);
            if (canBootstrapSession(nextRequest)) {
              const bootstrap = await ApiService.startPublicSigningSession(token);
              return {
                request: bootstrap.request,
                session: bootstrap.session || null,
                error: null,
              };
            }
            return {
              request: nextRequest,
              session: null,
              error: null,
            };
          } catch (nextError) {
            return {
              request: null,
              session: null,
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
      setSession(result.session);
      setError(result.error);
      setAdoptedName(result.request?.signatureAdoptedName || result.request?.signerName || '');
      setSignatureType(result.request?.signatureAdoptedMode || 'typed');
      setSignatureImageDataUrl(result.request?.signatureAdoptedImageDataUrl || null);
      setLoading(false);
    });

    return () => {
      mounted = false;
    };
  }, [token]);

  async function runRequestAction(
    nextBusyAction: Exclude<BusyActionKey, 'sendCode' | 'verifyCode' | null>,
    action: () => Promise<PublicSigningRequest>,
  ) {
    setBusyAction(nextBusyAction);
    setActionError(null);
    try {
      const nextRequest = await action();
      applyRequestState(nextRequest);
    } catch (nextError) {
      setActionError(nextError instanceof Error ? nextError.message : 'Unable to continue this signing request.');
    } finally {
      setBusyAction(null);
    }
  }

  async function runVerificationAction(
    nextBusyAction: Extract<BusyActionKey, 'sendCode' | 'verifyCode'>,
    action: () => Promise<PublicSigningBootstrap>,
  ) {
    setBusyAction(nextBusyAction);
    setActionError(null);
    try {
      const nextPayload = await action();
      applyBootstrapState(nextPayload);
      if (nextBusyAction === 'verifyCode') {
        setVerificationCode('');
      }
    } catch (nextError) {
      setActionError(nextError instanceof Error ? nextError.message : 'Unable to verify this signing request.');
    } finally {
      setBusyAction(null);
    }
  }

  async function runArtifactAction(nextArtifactAction: Exclude<ArtifactActionKey, null>, action: () => Promise<void>) {
    setArtifactBusyKey(nextArtifactAction);
    setActionError(null);
    try {
      await action();
    } catch (nextError) {
      setActionError(nextError instanceof Error ? nextError.message : 'Unable to load the requested signing file.');
    } finally {
      setArtifactBusyKey(null);
    }
  }

  const currentStep = resolveCurrentStep(request, session);
  const steps = useMemo(() => resolveSigningSteps(request), [request]);
  const sessionToken = session?.token || null;
  const manualFallbackLocked = hasManualFallbackLock(request);
  const consentWithdrawnLocked = hasConsentWithdrawnLock(request);
  const signingLocked = manualFallbackLocked || consentWithdrawnLocked;
  const consumerDisclosure = request?.disclosure || null;
  const consumerDisclosureLines = consumerDisclosure?.summaryLines || [];
  const consumerHardwareRequirements = consumerDisclosure?.hardwareSoftware || [];
  const consumerAccessPath = normalizePath(consumerDisclosure?.accessCheck?.accessPath || null);
  const requiresSession = Boolean(request && (request.status === 'completed' || (isActionableRequest(request) && !signingLocked)));
  const missingSession = requiresSession && !sessionToken;
  const verificationRequired = Boolean(request?.verificationRequired);
  const verificationComplete = !verificationRequired || Boolean(session?.verifiedAt);
  const showCompletedVerificationGate = Boolean(request?.status === 'completed' && verificationRequired && !verificationComplete);
  const showInteractiveCeremony = Boolean(request && (isActionableRequest(request) || showCompletedVerificationGate));
  const canOpenSourceDocument = Boolean(
    request
      && sessionToken
      && verificationComplete
      && (
        request.status === 'completed'
        || (request.signatureMode !== 'consumer' || request.consentedAt)
      ),
  );
  const resendAvailableAt = parseDate(session?.verificationResendAvailableAt);
  const resendBlocked = Boolean(
    resendAvailableAt
      && resendAvailableAt.getTime() > Date.now()
      && !session?.verifiedAt,
  );
  const resendAvailableLabel = formatDateTime(session?.verificationResendAvailableAt);
  const verificationExpiresLabel = formatDateTime(session?.verificationExpiresAt);
  const verificationCodeTrimmed = verificationCode.trim();
  const normalizedAdoptedName = adoptedName.trim();
  const previewSignatureName = normalizedAdoptedName || request?.signerName || '';
  const canSubmitAdoptedSignature = signatureType === 'drawn' || signatureType === 'uploaded'
    ? Boolean(signatureImageDataUrl)
    : (signatureType === 'default' || Boolean(normalizedAdoptedName));
  const facts = useMemo(
    () => buildPublicSigningFacts(request, { verificationRequired, verificationComplete }),
    [request, verificationRequired, verificationComplete],
  );

  useEffect(() => {
    const documentPath = normalizePath(request?.documentPath || null);
    if (!request || !sessionToken || !documentPath) {
      setDocumentLoading(false);
      setDocumentError(null);
      setDocumentObjectUrl((current) => {
        if (current) URL.revokeObjectURL(current);
        return null;
      });
      return undefined;
    }

    const allowedToLoadDocument = request.status === 'completed'
      ? (!request.verificationRequired || Boolean(session?.verifiedAt))
      : (!signingLocked && (!request.verificationRequired || Boolean(session?.verifiedAt)) && (
        request.signatureMode !== 'consumer' || Boolean(request.consentedAt)
      ));

    if (!allowedToLoadDocument) {
      setDocumentLoading(false);
      setDocumentError(null);
      setDocumentObjectUrl((current) => {
        if (current) URL.revokeObjectURL(current);
        return null;
      });
      return undefined;
    }

    let active = true;
    let pendingObjectUrl: string | null = null;
    setDocumentLoading(true);
    setDocumentError(null);

    void ApiService.getPublicSigningDocumentBlob(token, sessionToken)
      .then((file: PublicSigningFileResult) => {
        const resolvedObjectUrl = URL.createObjectURL(file.blob);
        pendingObjectUrl = resolvedObjectUrl;
        if (!active) {
          URL.revokeObjectURL(resolvedObjectUrl);
          pendingObjectUrl = null;
          return;
        }
        setDocumentObjectUrl((current) => {
          if (current) URL.revokeObjectURL(current);
          return resolvedObjectUrl;
        });
        pendingObjectUrl = null;
        setDocumentLoading(false);
      })
      .catch((nextError) => {
        if (!active) return;
        setDocumentObjectUrl((current) => {
          if (current) URL.revokeObjectURL(current);
          return null;
        });
        setDocumentError(nextError instanceof Error ? nextError.message : 'Unable to load the immutable signing document.');
        setDocumentLoading(false);
      });

    return () => {
      active = false;
      if (pendingObjectUrl) {
        URL.revokeObjectURL(pendingObjectUrl);
      }
    };
  }, [
    request,
    sessionToken,
    session?.verifiedAt,
    signingLocked,
    token,
  ]);

  const requireSession = buildMissingSessionRunner(setActionError);

  function handleOpenDocument(fallbackMessage: string) {
    if (!documentObjectUrl) {
      setActionError(documentError || fallbackMessage);
      return;
    }
    window.open(documentObjectUrl, '_blank', 'noopener,noreferrer');
  }

  function handleSendCode() {
    if (!sessionToken && !requireSession()) {
      return;
    }
    void runVerificationAction('sendCode', () => ApiService.sendPublicSigningVerificationCode(token, sessionToken!));
  }

  function handleVerifyCode() {
    if (!sessionToken && !requireSession()) {
      return;
    }
    void runVerificationAction(
      'verifyCode',
      () => ApiService.verifyPublicSigningVerificationCode(token, sessionToken!, verificationCodeTrimmed),
    );
  }

  function handleWithdrawConsent() {
    if (!sessionToken && !requireSession()) {
      return;
    }
    void runRequestAction('withdrawConsent', () => ApiService.withdrawPublicSigningConsent(token, sessionToken!));
  }

  function handleManualFallback() {
    if (!sessionToken && !requireSession()) {
      return;
    }
    void runRequestAction('manualFallback', () => ApiService.requestPublicSigningManualFallback(token, sessionToken!));
  }

  function handleDownloadSignedPdf() {
    if (!sessionToken && !requireSession()) {
      return;
    }
    if (!request?.artifacts?.signedPdf?.available) {
      setActionError('The signed PDF is not available yet.');
      return;
    }
    void runArtifactAction('signedPdf', async () => {
      const issued = await ApiService.issuePublicSigningArtifactDownload(token, sessionToken!, 'signed_pdf');
      await ApiService.downloadPublicSigningFile(
        issued.downloadPath,
        sessionToken!,
        'signed-document.pdf',
      );
    });
  }

  function handleDownloadAuditReceipt() {
    if (!sessionToken && !requireSession()) {
      return;
    }
    if (!request?.artifacts?.auditReceipt?.available) {
      setActionError('The audit receipt is not available yet.');
      return;
    }
    void runArtifactAction('auditReceipt', async () => {
      const issued = await ApiService.issuePublicSigningArtifactDownload(token, sessionToken!, 'audit_receipt');
      await ApiService.downloadPublicSigningFile(
        issued.downloadPath,
        sessionToken!,
        'audit-receipt.pdf',
      );
    });
  }

  function handleConsent() {
    if (!sessionToken && !requireSession()) {
      return;
    }
    void runRequestAction('consent', () => ApiService.consentPublicSigningRequest(
      token,
      sessionToken!,
      { accessCode: accessCode.trim().toUpperCase() },
    ));
  }

  function handleReview() {
    if (!sessionToken && !requireSession()) {
      return;
    }
    void runRequestAction('review', () => ApiService.reviewPublicSigningRequest(token, sessionToken!));
  }

  function handleAdopt() {
    if (!sessionToken && !requireSession()) {
      return;
    }
    const payload: PublicSigningAdoptPayload = {
      signatureType,
    };
    if (signatureType !== 'default') {
      payload.adoptedName = normalizedAdoptedName || request?.signerName || '';
    }
    if (signatureType === 'drawn' || signatureType === 'uploaded') {
      payload.signatureImageDataUrl = signatureImageDataUrl;
    }
    void runRequestAction('adopt', () => ApiService.adoptPublicSigningSignature(token, sessionToken!, payload));
  }

  function handleComplete() {
    if (!sessionToken && !requireSession()) {
      return;
    }
    void runRequestAction('complete', () => ApiService.completePublicSigningRequest(token, sessionToken!));
  }

  return {
    request,
    session,
    loading,
    busyAction,
    error,
    actionError,
    adoptedName,
    signatureType,
    signatureImageDataUrl,
    accessCode,
    verificationCode,
    intentConfirmed,
    artifactBusyKey,
    documentObjectUrl,
    documentError,
    documentLoading,
    currentStep,
    steps,
    sessionToken,
    manualFallbackLocked,
    consentWithdrawnLocked,
    signingLocked,
    consumerDisclosure,
    consumerDisclosureLines,
    consumerHardwareRequirements,
    consumerAccessPath,
    missingSession,
    sessionErrorMessage: PUBLIC_SIGNING_SESSION_ERROR_MESSAGE,
    verificationRequired,
    verificationComplete,
    showInteractiveCeremony,
    canOpenSourceDocument,
    resendBlocked,
    resendAvailableLabel,
    verificationExpiresLabel,
    verificationCodeTrimmed,
    previewSignatureName,
    canSubmitAdoptedSignature,
    facts,
    setActionError,
    setAdoptedName,
    setSignatureType,
    setSignatureImageDataUrl,
    setAccessCode,
    setVerificationCode,
    setIntentConfirmed,
    handleSendCode,
    handleVerifyCode,
    handleWithdrawConsent,
    handleManualFallback,
    handleOpenDocument,
    handleDownloadSignedPdf,
    handleDownloadAuditReceipt,
    handleConsent,
    handleReview,
    handleAdopt,
    handleComplete,
  };
}

export type PublicSigningFlowState = ReturnType<typeof usePublicSigningFlow>;
