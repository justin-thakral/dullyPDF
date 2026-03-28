import type { PublicSigningRequest, PublicSigningSession } from '../../../services/api';

export type SigningStepKey = 'verify' | 'consent' | 'review' | 'adopt' | 'complete';
export type BusyActionKey =
  | 'sendCode'
  | 'verifyCode'
  | 'review'
  | 'consent'
  | 'withdrawConsent'
  | 'manualFallback'
  | 'adopt'
  | 'complete'
  | null;
export type ArtifactActionKey = 'signedPdf' | 'auditReceipt' | null;

export type PublicSigningFact = {
  label: string;
  value: string;
  className: string;
};

const BUSINESS_STEPS: SigningStepKey[] = ['review', 'adopt', 'complete'];
const CONSUMER_STEPS: SigningStepKey[] = ['consent', 'review', 'adopt', 'complete'];

export const PUBLIC_SIGNING_SESSION_ERROR_MESSAGE = 'Your signing session expired. Reload the page and try again.';

export function normalizePath(path: string | null | undefined): string | null {
  const normalizedPath = String(path || '').trim();
  if (!normalizedPath) return null;
  return normalizedPath;
}

export function parseDate(value: string | null | undefined): Date | null {
  const normalized = String(value || '').trim();
  if (!normalized) return null;
  const parsed = new Date(normalized);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function formatDateTime(value: string | null | undefined): string | null {
  const parsed = parseDate(value);
  return parsed ? parsed.toLocaleString() : null;
}

export function resolveCurrentStep(
  request: PublicSigningRequest | null,
  session: PublicSigningSession | null,
): SigningStepKey {
  if (!request) {
    return 'review';
  }
  if (request.verificationRequired && !session?.verifiedAt) {
    return 'verify';
  }
  if (request.status === 'completed') {
    return 'complete';
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

export function resolveSigningSteps(request: PublicSigningRequest | null): SigningStepKey[] {
  const baseSteps = request?.signatureMode === 'consumer' ? CONSUMER_STEPS : BUSINESS_STEPS;
  return request?.verificationRequired ? ['verify', ...baseSteps] : baseSteps;
}

export function getSigningStepLabel(step: SigningStepKey): string {
  if (step === 'verify') {
    return 'Verify Email';
  }
  if (step === 'consent') {
    return 'E-Consent';
  }
  if (step === 'review') {
    return 'Review';
  }
  if (step === 'adopt') {
    return 'Adopt Signature';
  }
  return 'Finish Signing';
}

export function isActionableStatus(status: string): boolean {
  return status === 'sent';
}

export function isActionableRequest(request: PublicSigningRequest | null): boolean {
  return Boolean(request && isActionableStatus(request.status) && !request.isExpired);
}

export function hasManualFallbackLock(request: PublicSigningRequest | null): boolean {
  return Boolean(request?.manualFallbackRequestedAt);
}

export function hasConsentWithdrawnLock(request: PublicSigningRequest | null): boolean {
  return Boolean(request?.consentWithdrawnAt);
}

export function canBootstrapSession(request: PublicSigningRequest | null): boolean {
  if (!request) return false;
  if (request.status === 'completed') return true;
  return isActionableRequest(request) && !hasManualFallbackLock(request) && !hasConsentWithdrawnLock(request);
}

export function resolveInactiveRequestMessage(request: PublicSigningRequest): string {
  if (request.isExpired) {
    return 'This signing request expired before it was completed. Contact the sender for a fresh signing link or a paper/manual alternative.';
  }
  if (request.status === 'draft') {
    return 'This signing request has been prepared but not sent yet. Ask the sender to finish Review and Send before using this link.';
  }
  if (request.status === 'invalidated') {
    return 'This signing request is no longer valid. Contact the sender for a fresh signing link or a paper/manual alternative.';
  }
  return 'This request cannot be signed right now. Contact the sender for a fresh signing link or a paper/manual alternative.';
}

export function buildPublicSigningFacts(
  request: PublicSigningRequest | null,
  {
    verificationRequired,
    verificationComplete,
  }: {
    verificationRequired: boolean;
    verificationComplete: boolean;
  },
): PublicSigningFact[] {
  if (!request) {
    return [];
  }
  return [
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
      label: 'Signer email',
      value: request.signerEmailHint || 'Hidden',
      className: 'public-signing-page__fact',
    },
    {
      label: 'Sender',
      value: request.senderDisplayName || 'Unavailable',
      className: 'public-signing-page__fact',
    },
    {
      label: 'Sender contact',
      value: request.senderContactEmail || 'Unavailable',
      className: 'public-signing-page__fact',
    },
    {
      label: 'Email verification',
      value: verificationRequired ? (verificationComplete ? 'Verified' : 'Required') : 'Not required',
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
  ];
}
